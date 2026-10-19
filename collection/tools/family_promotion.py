"""Private, source-pinned JF1 family promotion transforms.

This module is a proposal for prepare_runtimes.py to call after the existing
JF1 adapters have been applied to a PRIVATE framework copy.  It never edits
the maintained source tree.  The family capability remains opt-in; the
dispatcher integration is a separate explicit transform of the maintained
palette-native generator output.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
COLLECTION_ROOT = HERE.parent
BUNDLE = COLLECTION_ROOT / "runtime/jf1_family_sources"
MANIFEST = BUNDLE / "bundle-manifest.json"

def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def read_utf8(path: Path) -> tuple[str, str]:
    raw = path.read_bytes()
    text = raw.decode("utf-8")
    newline = "\r\n" if b"\r\n" in raw else "\n"
    return text.replace("\r\n", "\n"), newline

def exact_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise ValueError(f"{label}: expected one exact anchor, found {count}: {old[:90]!r}")
    return text.replace(old, new, 1)

def verify_bundle() -> dict:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    for row in manifest["sources"]:
        bundled = row.get("bundle")
        if bundled:
            path = BUNDLE / Path(bundled.replace("\\", "/"))
            if not path.is_file() or sha(path.read_bytes()) != row["bundle_sha256"]:
                raise ValueError(f"family bundle drift: {bundled}")
    for row in manifest.get("supplemental_artifacts", []):
        path = BUNDLE / Path(row["path"].replace("\\", "/"))
        if not path.is_file() or sha(path.read_bytes()) != row["sha256"]:
            raise ValueError(f"family supplemental artifact drift: {row['path']}")
    return manifest

def patch_desktop_header(source: str) -> str:
    """Apply only family lifecycle and exact-world eligibility to maintained header."""
    if "JF1_F4354_FAMILY_ACCESSOR_V1" in source:
        return source
    if "jf1_f4354_family_gameplay_state" in source:
        raise ValueError("partial or unknown family accessor already present")
    source = exact_once(source, '#include "jf1_profiles.h"\n',
        '#include "jf1_profiles.h"\n#include "jf1_f4354_family_contract.h"\n#include <cstdlib>\n#include <cstring>\n',
        "desktop header family includes")
    source = exact_once(source, 'static const Jf1Profile* jf1_profile=nullptr;\n',
        'extern "C" void psx_jf1_f4354_ratio_request_reset(void);\n'
        'static const Jf1Profile* jf1_profile=nullptr;\n'
        'static uint64_t jf1_profile_epoch=1;\n', "profile epoch")
    source = exact_once(source, 'static void collection_input_reset();\n',
        'static void collection_input_reset();\n'
        'static void jf1_f4354_lifecycle_reset(){\n'
        '    if(++jf1_profile_epoch==0)jf1_profile_epoch=1;\n'
        '    psx_jf1_f4354_ratio_request_reset();\n'
        '}\n', "family lifecycle reset helper")
    source = exact_once(source,
        '    if(jf1_profile!=previous){\n'
        '        jf1_player_frame=0;jf1_motion_frame=UINT64_MAX;\n'
        '        jf1_release_inputs();collection_input_reset();\n'
        '    }',
        '    if(jf1_profile!=previous){\n'
        '        jf1_f4354_lifecycle_reset();\n'
        '        jf1_player_frame=0;jf1_motion_frame=UINT64_MAX;\n'
        '        jf1_release_inputs();collection_input_reset();\n'
        '    }', "profile-change lifecycle")
    old_gameplay = (
        'static bool jf1_gameplay(){\n'
        '    if(!collection_mode)return false;\n'
        '    const auto* p=jf1_find_profile(0);\n'
        '    if(!p||!jf1_player_frame||s_frame_count-jf1_player_frame>=8)return false;\n'
        '    return jf1::manual(psx_read_word(p->demo_mode),psx_read_word(p->control_live),psx_read_word(p->original_pause),\n'
        '        psx_read_word(p->control_block),psx_read_word(p->finish),psx_read_word(p->finish2),\n'
        '        psx_read_word(p->movie),psx_read_word(p->movie_ready))&&psx_read_half(p->player+0x5c)>0;\n'
        '}')
    new_gameplay = (
        'static bool jf1_profile_gameplay(const Jf1Profile* p){\n'
        '    if(!collection_mode)return false;\n'
        '    if(!p||!jf1_player_frame||s_frame_count-jf1_player_frame>=8)return false;\n'
        '    return jf1::manual(psx_read_word(p->demo_mode),psx_read_word(p->control_live),psx_read_word(p->original_pause),\n'
        '        psx_read_word(p->control_block),psx_read_word(p->finish),psx_read_word(p->finish2),\n'
        '        psx_read_word(p->movie),psx_read_word(p->movie_ready))&&psx_read_half(p->player+0x5c)>0;\n'
        '}\n'
        'static bool jf1_gameplay(){\n'
        '    if(!collection_mode)return false;\n'
        '    return jf1_profile_gameplay(jf1_find_profile(0));\n'
        '}')
    source = exact_once(source, old_gameplay, new_gameplay, "profile gameplay factoring")
    family_access = '''
/* JF1_F4354_FAMILY_ACCESSOR_V1: exact image identity plus existing live guards. */
static bool jf1_f4354_family_image_matches(const char* image,const char* world){
    if(!image||!world)return false;
    static constexpr char suffix[]="/MAIN.PEX";
    const std::size_t world_length=std::strlen(world);
    const std::size_t suffix_length=sizeof(suffix)-1;
    const std::size_t image_length=std::strlen(image);
    return image_length==world_length+suffix_length&&
        std::memcmp(image,world,world_length)==0&&
        std::memcmp(image+world_length,suffix,suffix_length)==0;
}
extern "C" int psx_jf1_f4354_family_gameplay_state(uint32_t *profile_index,
                                                    uint64_t *profile_epoch){
    if(profile_index)*profile_index=0;
    if(profile_epoch)*profile_epoch=0;
    const char* enabled=std::getenv("PSX_JF1_F4354_XCULL");
    if(!enabled||std::strcmp(enabled,"1")!=0)return 0;
    if(!collection_mode)return 0;
    const auto* p=jf1_find_profile(0);
    if(!p||!jf1_profile_gameplay(p))return 0;
    static_assert(sizeof(jf1_profiles)/sizeof(jf1_profiles[0])==JF1_F4354_FAMILY_PROFILE_COUNT,
                  "JF1 control profile table must stay aligned with family metadata");
    static_assert(sizeof(jf1_f4354_profiles)/sizeof(jf1_f4354_profiles[0])==JF1_F4354_FAMILY_PROFILE_COUNT,
                  "JF1 family metadata count changed");
    for(uint32_t i=0;i<JF1_F4354_FAMILY_PROFILE_COUNT;++i){
        if(jf1_f4354_family_image_matches(p->image,jf1_f4354_profiles[i].world)){
            if(profile_index)*profile_index=i;
            if(profile_epoch)*profile_epoch=jf1_profile_epoch;
            return 1;
        }
    }
    return 0;
}
'''
    source = exact_once(source, 'static void jf1_release_inputs(){',
                        family_access + 'static void jf1_release_inputs(){', "family accessor insertion")
    source = exact_once(source,
        '    if(gameplay!=jf1_input_previous){jf1_input_previous=gameplay;jf1_release_inputs();}',
        '    if(gameplay!=jf1_input_previous){jf1_input_previous=gameplay;jf1_f4354_lifecycle_reset();jf1_release_inputs();}',
        "gameplay transition lifecycle")
    return source

def patch_main(text: str) -> str:
    """Add accepted focus/savestate resets without copying the large main TU."""
    if "JF1_F4354_FAMILY_MAIN_V2" in text:
        signature = "static bool host_hotkey_input_focused(void) {"
        if text.count(signature) != 1:
            raise ValueError("marked family main has a changed focus-function count")
        start = text.index(signature)
        opening = text.index("{", start, start + len(signature))
        end = _cpp_function_end(text, opening)
        focus = text[start:end + 1]
        if ("psx_jf1_owner_correlation_reset();" not in focus
                or "psx_jf1_f4354_ratio_request_reset();" not in focus):
            raise ValueError("marked family main has an incomplete focus reset body")
        for lifecycle in ("psx_frontend_on_savestate_loaded", "psx_frontend_on_rb_snap_loaded"):
            hook = f'extern "C" void {lifecycle}(void) {{'
            if text.count(hook) != 1:
                raise ValueError(f"marked family main has a changed {lifecycle} definition")
            hook_start = text.index(hook)
            hook_brace = text.index("{", hook_start)
            hook_end = _cpp_function_end(text, hook_brace)
            if "psx_jf1_f4354_ratio_request_reset();" not in text[hook_brace:hook_end]:
                raise ValueError(f"marked family main has an incomplete {lifecycle} reset")
        return text
    if "psx_jf1_f4354_ratio_request_reset" in text:
        raise ValueError("partial or unknown family main hooks already present")
    signature = "static bool host_hotkey_input_focused(void) {"
    if text.count(signature) != 1:
        raise ValueError("hotkey focus function signature count changed")
    start = text.index(signature)
    opening = text.index("{", start, start + len(signature))
    end = _cpp_function_end(text, opening)
    replacement = '''#ifdef JF1_DESKTOP
extern "C" void psx_jf1_owner_correlation_reset(void);
extern "C" void psx_jf1_f4354_ratio_request_reset(void);
#endif
static bool host_hotkey_input_focused(void) {
#ifdef JF1_DESKTOP
    const bool focused = !sdl_window ||
        (SDL_GetWindowFlags(sdl_window) & SDL_WINDOW_INPUT_FOCUS) != 0;
    static int previous_focus = -1;
    if (previous_focus >= 0 && previous_focus != (focused ? 1 : 0)) {
        psx_jf1_owner_correlation_reset();
        psx_jf1_f4354_ratio_request_reset();
    }
    previous_focus = focused ? 1 : 0;
    return focused;
#else
    if (!sdl_window) return true;
    return (SDL_GetWindowFlags(sdl_window) & SDL_WINDOW_INPUT_FOCUS) != 0;
#endif
}'''
    text = text[:start] + replacement + text[end + 1:]
    text = exact_once(text, 'extern "C" void psx_frontend_on_savestate_loaded(void) {',
        'extern "C" void psx_frontend_on_savestate_loaded(void) {\n#ifdef JF1_DESKTOP\n    psx_jf1_f4354_ratio_request_reset();\n#endif',
        "savestate lifecycle")
    text = exact_once(text, 'extern "C" void psx_frontend_on_rb_snap_loaded(void) {',
        'extern "C" void psx_frontend_on_rb_snap_loaded(void) {\n#ifdef JF1_DESKTOP\n    psx_jf1_f4354_ratio_request_reset();\n#endif',
        "rollback lifecycle")
    return '/* JF1_F4354_FAMILY_MAIN_V2 */\n' + text

def _cpp_function_end(text: str, opening: int) -> int:
    """Find a C++ function's closing brace while ignoring comments and literals."""
    depth = 0
    state = "code"
    escaped = False
    i = opening
    while i < len(text):
        ch = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if state == "line_comment":
            if ch == "\n": state = "code"
        elif state == "block_comment":
            if ch == "*" and nxt == "/": state = "code"; i += 1
        elif state in ("string", "char"):
            if escaped: escaped = False
            elif ch == "\\": escaped = True
            elif (state == "string" and ch == '"') or (state == "char" and ch == "'"):
                state = "code"
        else:
            if ch == "/" and nxt == "/": state = "line_comment"; i += 1
            elif ch == "/" and nxt == "*": state = "block_comment"; i += 1
            elif ch == '"': state = "string"
            elif ch == "'": state = "char"
            elif ch == "{": depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0: return i
        i += 1
    raise ValueError("unterminated hotkey focus function")

def patch_gte(text: str) -> str:
    """Apply the pinned minimal GTE additions only to the exact current base."""
    spec = json.loads((HERE / "data/jf1-family-gte-hunks.json").read_text(encoding="utf-8"))
    raw = text.encode("utf-8")
    if sha(raw) == spec["candidate_sha256"]:
        return text
    if sha(raw) != spec["base_sha256"]:
        raise ValueError(f"GTE base drift: {sha(raw)} != {spec['base_sha256']}")
    lines = text.splitlines(keepends=True)
    for op in reversed(spec["ops"]):
        start, end = op["start"], op["end"]
        if lines[start:end] != op["old"]:
            raise ValueError(f"GTE hunk drift at base lines {start+1}-{end}")
        lines[start:end] = op["new"]
    result = "".join(lines)
    if sha(result.encode("utf-8")) != spec["candidate_sha256"]:
        raise ValueError("GTE patch output does not match accepted candidate")
    return result

def patch_debug(text: str) -> str:
    """Insert only the family-return endpoint into the already instrumented server."""
    if '"jf1_f4354_family_returns"' in text:
        return text
    inc = (BUNDLE / "src/family_debug/jf1_f4354_family_debug.inc").read_text(encoding="utf-8")
    text = exact_once(text, '#include "collection_metrics.h"\n',
        '#include "collection_metrics.h"\n#ifdef JF1_DESKTOP\n'
        '#include "jf1_f4354_family_snapshot_v3.h"\n'
        '#include "jf1_cull_trace_wire.h"\n#endif\n', "family debug headers")
    text = exact_once(text, 'static const CmdEntry s_commands[] = {',
        inc + '\nstatic const CmdEntry s_commands[] = {', "family debug handler")
    text = exact_once(text, 'static const CmdEntry s_commands[] = {',
        'static const CmdEntry s_commands[] = {\n#ifdef JF1_DESKTOP\n'
        '    { "jf1_f4354_family_returns", handle_jf1_f4354_family_returns },\n#endif',
        "family debug command")
    return text

def patch_palette_native_dispatcher(text: str) -> str:
    """JF1-only narrow generator-output transform; caller must update interpreter args."""
    if "psx_jf1_f4354_try_dispatch" in text:
        return text
    anchor = 'int psx_palette_native_try_dispatch(CPUState *cpu,uint32_t address,int forced,int native_enabled,int cps_mode){\n    if(!cpu||forced||!native_enabled||!cps_mode)return 0;\n'
    replacement = '''int psx_palette_native_try_dispatch(CPUState *cpu,uint32_t address,int forced,int native_enabled,int cps_mode,int precise_mode,int lockstep_mode){
    if(!cpu||forced||!native_enabled||!cps_mode)return 0;
#if defined(JF1_DESKTOP)
    if(psx_jf1_f4354_try_dispatch(cpu,address,forced,native_enabled,cps_mode,precise_mode,lockstep_mode))return 1;
#else
    (void)precise_mode;(void)lockstep_mode;
#endif
'''
    if anchor not in text:
        raise ValueError("palette dispatcher callsite anchor changed")
    text = text.replace(anchor, replacement, 1)
    text = '#if defined(JF1_DESKTOP)\n#include "f4354_dispatch_gate.h"\n#endif\n' + text
    return text

def patch_palette_native_dirty_callsite(text: str) -> str:
    """Carry existing interpreter-mode gates into the family dispatcher."""
    marker = "JF1_F4354_FAMILY_DISPATCH_ARGS_V1"
    if marker in text:
        return text
    old = "psx_palette_native_try_dispatch(cpu,addr,forced,overlay_loader_get_native_exec(),g_psx_cps_mode)"
    old_local = "psx_palette_native_try_dispatch(cpu,target,(int)span_forced(target_phys),overlay_loader_get_native_exec(),g_psx_cps_mode)"
    decl = "extern int psx_palette_native_try_dispatch(CPUState*,uint32_t,int,int,int);"
    accepted_decl = "extern int psx_palette_native_try_dispatch(CPUState*,uint32_t,int,int,int,int,int);"
    accepted_calls = (
        "psx_palette_native_try_dispatch(cpu,addr,forced,overlay_loader_get_native_exec(),g_psx_cps_mode,g_precise_mode,g_ls_replay_active)",
        "psx_palette_native_try_dispatch(cpu,target,(int)span_forced(target_phys),overlay_loader_get_native_exec(),g_psx_cps_mode,g_precise_mode,g_ls_replay_active)")
    if (text.count(accepted_decl) == 2 and
            all(text.count(call) == 1 for call in accepted_calls)):
        return text
    if text.count(old) != 1 or text.count(old_local) != 1 or text.count(decl) != 2:
        raise ValueError("palette interpreter dispatcher callsite count changed")
    text = text.replace(decl,
        "extern int psx_palette_native_try_dispatch(CPUState*,uint32_t,int,int,int,int,int);")
    text = text.replace(old, old[:-1] + ",g_precise_mode,g_ls_replay_active)", 1)
    text = text.replace(old_local, old_local[:-1] + ",g_precise_mode,g_ls_replay_active)", 1)
    return "/* " + marker + " */\n" + text

def patch_cmake(text: str) -> str:
    marker = "JF1_F4354_FAMILY_SOURCES_V1"
    if marker in text:
        return text
    anchor = "target_compile_definitions(psx-runtime PRIVATE JF1_DESKTOP=1)"
    if text.count(anchor) < 1:
        raise ValueError("JF1 family CMake anchor changed")
    files = [
        "jf1_f4354_ratio_bridge.cpp",
        "f4354_family_gate.c",
        "f4354_family_candidates.c",
        "candidate_800EF2CC.c", "candidate_800F0F78.c",
        "candidate_800F3A60.c", "candidate_800F3A78.c",
        "candidate_800F4354.c", "candidate_800F4D14.c",
        "candidate_800F4D24.c", "candidate_800F8F28.c",
        "candidate_800F9024.c",
    ]
    lines = [
        "\n# " + marker,
        'target_include_directories(psx-runtime BEFORE PRIVATE "${PSXRECOMP_ROOT}/runtime/jf1_family/include")',
        "target_sources(psx-runtime PRIVATE",
    ] + [f'    "${{PSXRECOMP_ROOT}}/runtime/jf1_family/src/{name}"' for name in files] + [")"]
    pos = text.rfind(anchor) + len(anchor)
    return text[:pos] + "\n" + "\n".join(lines) + text[pos:]

def patch_main_lifecycle_from_disk(path: Path) -> None:
    text, nl = read_utf8(path)
    out = patch_main(text).replace("\n", nl)
    path.write_bytes(out.encode("utf-8"))

def prepare_family_sources(framework: Path, collection_runtime: Path, project_cmake: Path) -> dict:
    """Prepare family runtime sources after runtime_adapter, before palette install."""
    framework = framework.resolve()
    collection_runtime = collection_runtime.resolve()
    if not framework.is_dir() or not collection_runtime.is_dir():
        raise ValueError("private framework and runtime directories are required")
    verify_bundle()
    family_root = framework / "runtime/jf1_family"
    if family_root.exists():
        raise ValueError(f"refusing existing family destination: {family_root}")
    header_in = collection_runtime / "jf1_desktop.h"
    header_text, nl = read_utf8(header_in)
    header_out = patch_desktop_header(header_text).replace("\n", nl)

    transformed = {}
    for path, patcher in (
        (framework / "runtime/src/main.cpp", patch_main),
        (framework / "runtime/src/gte.cpp", patch_gte),
        (framework / "runtime/src/debug_server.c", patch_debug),
        (project_cmake, patch_cmake),
    ):
        text, nl = read_utf8(path)
        transformed[path] = patcher(text).replace("\n", nl).encode("utf-8")

    # All source anchors and the fresh destination state validate before writes.
    shutil.copytree(BUNDLE / "include", family_root / "include")
    shutil.copytree(BUNDLE / "src/family_candidates", family_root / "src")
    shutil.copytree(BUNDLE / "src/family_debug", family_root / "debug")
    (family_root / "include/jf1_desktop.h").write_bytes(header_out.encode("utf-8"))
    for path, data in transformed.items():
        if path.read_bytes() != data:
            path.write_bytes(data)
    return {"family_root": str(family_root), "project_cmake": str(project_cmake),
            "phase": "family source and lifecycle prepared; palette dispatcher not yet connected",
            "note": "private source preparation only; no compile or runtime"}

def finish_palette_family(framework: Path) -> dict:
    """Connect family gate to the already-installed JF1 palette dispatcher."""
    framework = framework.resolve()
    family_root = framework / "runtime/jf1_family"
    dispatcher = framework / "runtime/src/palette_native_dispatch.c"
    dirty = framework / "runtime/src/dirty_ram_interp.c"
    cmake = framework.parent / "CMakeLists.txt"
    if not family_root.is_dir() or not (family_root / "include/jf1_desktop.h").is_file():
        raise ValueError("JF1 family source opt-in is absent; refusing palette dispatcher changes")
    if not dispatcher.is_file() or not dirty.is_file():
        raise ValueError("JF1 palette-native installer must run before family dispatcher integration")
    if not cmake.is_file() or "COLLECTION_PALETTE_NATIVE_CPS_V1" not in cmake.read_text(encoding="utf-8"):
        raise ValueError("JF1 palette-native CMake install marker missing")
    transformed = {}
    for path, patcher in ((dispatcher, patch_palette_native_dispatcher),
                          (dirty, patch_palette_native_dirty_callsite)):
        text, nl = read_utf8(path)
        transformed[path] = patcher(text).replace("\n", nl).encode("utf-8")
    for path, data in transformed.items():
        if path.read_bytes() != data:
            path.write_bytes(data)
    return {"dispatcher_sha256": sha(transformed[dispatcher]),
            "dirty_interpreter_sha256": sha(transformed[dirty]),
            "runtime_feature_default": "off; PSX_JF1_F4354_XCULL must equal 1"}

def private_prepare(framework: Path, collection_runtime: Path, project_cmake: Path) -> dict:
    """Prepare and connect an already palette-installed PRIVATE framework copy."""
    base = prepare_family_sources(framework, collection_runtime, project_cmake)
    palette = finish_palette_family(framework)
    return {**base, "palette_integration": palette}

