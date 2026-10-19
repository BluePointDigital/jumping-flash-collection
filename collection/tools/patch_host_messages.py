"""Apply the private host-message default and toggle patch to a title source copy."""
from __future__ import annotations

import os
from pathlib import Path
import tempfile


class PatchError(ValueError):
    pass


MAIN_GUARD = "#if defined(RECOMP_LAUNCHER) && (defined(JF1_DESKTOP) || defined(ROBBIT_DESKTOP))\n"
UI_GUARD = MAIN_GUARD[:-1] + " && !defined(JF2_DESKTOP)\n"


def _replace_exact(text: str, old: str, new: str, label: str) -> str:
    old_count = text.count(old)
    new_count = text.count(new)
    overlap_count = new.count(old)
    if old_count == 1 and new_count == 0:
        result = text.replace(old, new, 1)
        if result.count(new) != 1 or result.count(old) != overlap_count:
            raise PatchError(f"{label}: post-transform anchor check failed")
        return result
    if new_count == 1 and old_count == overlap_count:
        return text
    raise PatchError(f"{label}: expected one original or one patched anchor (old={old_count}, new={new_count})")


def _main_transform(text: str) -> str:
    text = _replace_exact(
        text,
        "    std::filesystem::path g_lnch_settings_path;\n",
        "    std::filesystem::path g_lnch_settings_path;\n"
        + MAIN_GUARD
        + "    static bool g_collection_host_osd_visible = false;\n#endif\n",
        "main state",
    )

    tail = (
        "    }\n}  // namespace\n#endif\n\n"
        "/* [timing] guest_cycle_scale_gate reader: main RAM only, side-effect free\n"
    )
    callbacks = (
        "    }\n}  // namespace\n"
        + MAIN_GUARD
        + 'extern "C" int collection_host_osd_visible_get(void) {\n'
        + "    return g_collection_host_osd_visible ? 1 : 0;\n}\n"
        + 'extern "C" void collection_host_osd_visible_set(int visible) {\n'
        + "    g_collection_host_osd_visible = visible != 0;\n"
        + "    host_osd_set_text_visible(g_collection_host_osd_visible ? 1 : 0);\n"
        + "    if (g_lnch_settings_path.empty()) return;\n"
        + "    PSXRecompV4::UserSettings s =\n"
        + "        PSXRecompV4::load_user_settings(g_lnch_settings_path);\n"
        + "    if (s.parse_error) {\n"
        + '        std::fprintf(stderr, "psxrecomp: host-message preference not saved: settings.toml is invalid\\n");\n'
        + "        return;\n    }\n"
        + "    s.jf2_messages = g_collection_host_osd_visible;\n"
        + "    if (!PSXRecompV4::save_user_settings(g_lnch_settings_path, s))\n"
        + '        std::fprintf(stderr, "psxrecomp: unable to save host-message preference\\n");\n'
        + "}\n#endif\n#endif\n\n"
        "/* [timing] guest_cycle_scale_gate reader: main RAM only, side-effect free\n"
    )
    text = _replace_exact(text, tail, callbacks, "main callbacks")

    load = (
        "        const PSXRecompV4::UserSettings us =\n"
        "            PSXRecompV4::load_user_settings(settings_path);\n"
    )
    text = _replace_exact(
        text,
        load,
        load + MAIN_GUARD
        + "        g_collection_host_osd_visible = us.jf2_messages;\n"
        + "        host_osd_set_text_visible(g_collection_host_osd_visible ? 1 : 0);\n#endif\n",
        "main startup application",
    )
    seed = "            PSXRecompV4::UserSettings seed;\n"
    text = _replace_exact(
        text,
        seed,
        seed + MAIN_GUARD
        + "            seed.jf2_messages = g_collection_host_osd_visible;\n#endif\n",
        "main launch seed",
    )
    save = "            if (lr == 0 || lr == 1) {\n"
    text = _replace_exact(
        text,
        save,
        save + MAIN_GUARD
        + "                seed.jf2_messages = g_collection_host_osd_visible;\n#endif\n",
        "main save seed",
    )
    return text


def _ui_transform(text: str) -> str:
    header = "#endif\n// launcher_imgui.cpp"
    text = _replace_exact(
        text,
        header,
        "#endif\n" + UI_GUARD
        + 'extern "C" int collection_host_osd_visible_get(void);\n'
        + 'extern "C" void collection_host_osd_visible_set(int visible);\n'
        + "#endif\n// launcher_imgui.cpp",
        "UI declarations",
    )
    display = (
        '        if (ImGui::IsItemHovered() && dir[0]) ImGui::SetTooltip("%s", dir);\n'
        "    }\n}\n\n"
    )
    text = _replace_exact(
        text,
        display,
        '        if (ImGui::IsItemHovered() && dir[0]) ImGui::SetTooltip("%s", dir);\n'
        "    }\n" + UI_GUARD
        + '    row_label_right("Show host messages", th, px(SETTINGS_CTRL_W));\n'
        + "    bool host_messages = collection_host_osd_visible_get() != 0;\n"
        + '    if (ImGui::Checkbox("##host_messages", &host_messages))\n'
        + "        collection_host_osd_visible_set(host_messages ? 1 : 0);\n#endif\n}\n\n",
        "UI display checkbox",
    )
    return text


def _transform_bytes(raw: bytes, transform, label: str) -> bytes:
    newline = "\r\n" if b"\r\n" in raw else "\n"
    try:
        text = raw.decode("utf-8").replace("\r\n", "\n")
        output = transform(text).replace("\n", newline).encode("utf-8")
    except (UnicodeDecodeError, PatchError) as exc:
        raise PatchError(f"{label}: {exc}") from exc
    return output


def patch(private_title_root: Path | str, game: str) -> dict:
    """Apply OSD default-off to any title; add persisted toggle for JF1/Robbit.

    `private_title_root` must be a writable copied source tree containing
    `psxrecomp/` and `recomp-ui/`. The function validates all target files and
    anchors before writing any changed file. It does not touch files outside
    that root.
    """
    if game not in {"jf1", "jf2", "robbit"}:
        raise PatchError(f"unsupported game: {game}")
    root = Path(private_title_root).resolve()
    if not (root / "psxrecomp").is_dir() or not (root / "recomp-ui").is_dir():
        raise PatchError("title root must contain psxrecomp/ and recomp-ui/")

    operations = [
        (Path("psxrecomp/runtime/src/host_osd.c"), b"static int s_text_visible = 1;", b"static int s_text_visible = 0;", None),
        (Path("psxrecomp/recompiler/src/config_loader.h"), b"bool jf2_messages = true;", b"bool jf2_messages = false;", None),
    ]
    if game in {"jf1", "robbit"}:
        operations.extend([
            (Path("psxrecomp/runtime/src/main.cpp"), None, None, _main_transform),
            (Path("recomp-ui/src/common/backends/imgui/launcher_imgui.cpp"), None, None, _ui_transform),
        ])

    pending: dict[Path, bytes] = {}
    for relative, old, new, transform in operations:
        path = root / relative
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise PatchError(f"source escapes private title root: {relative.as_posix()}")
        if not path.is_file():
            raise PatchError(f"missing expected source file: {relative.as_posix()}")
        raw = path.read_bytes()
        if transform is not None:
            output = _transform_bytes(raw, transform, relative.as_posix())
        else:
            assert old is not None and new is not None
            old_count, new_count = raw.count(old), raw.count(new)
            if old_count == 1 and new_count == 0:
                output = raw.replace(old, new, 1)
            elif old_count == 0 and new_count == 1:
                output = raw
            else:
                raise PatchError(f"{relative.as_posix()}: expected one original or patched default anchor")
        if output != raw:
            pending[path] = output

    # All files/anchors are validated before temp files or writes are created.
    temporaries: list[tuple[Path, Path]] = []
    try:
        for target, data in pending.items():
            with tempfile.NamedTemporaryFile(prefix=target.name + ".", suffix=".tmp", dir=target.parent, delete=False) as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
                temp = Path(f.name)
            temporaries.append((temp, target))
        for temp, target in temporaries:
            os.replace(temp, target)
    finally:
        for temp, _ in temporaries:
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass

    return {"game": game, "changed_files": [p.relative_to(root).as_posix() for p in pending], "changed_count": len(pending)}
