"""Hash-guarded lazy trace-storage transform for prepared collection targets only."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

AUDIO_BASE = "26e5d2684ed21b4996aca00760a435f9db1c4fd795c8033b1105ecdf29f4c8b3"
AUDIO_OUT = "540ea3a907ef8688510bd1cb99a2972b29d87825e97a2b585e9ccea2c7872166"
FNTRACE_BASE = {
    "jf1": "cf5640a5a943eef3f70d22b813eb4d4c2cfdb2baeba0c3639d9d14edb7bf39f2",
    "jf2": "92a86008cfe9ebe6537c0fd8a5db0ddd9adbe262dacfc8fe1395a95e1bbe592b",
    "robbit": "cf5640a5a943eef3f70d22b813eb4d4c2cfdb2baeba0c3639d9d14edb7bf39f2",
}
FNTRACE_OUTPUT = {
    "jf1": "a6771d6c629124ca7d03048a2109b48a1dbae778f48d95c8197404f82bd02749",
    "jf2": "16e76ee882a98f6d676dfe39267ff939fb322dd3cd3e13e7d917f9e99086373c",
    "robbit": "a6771d6c629124ca7d03048a2109b48a1dbae778f48d95c8197404f82bd02749",
}
FNTRACE_HEADER_BASE = "bc12ba76ebe025548148b1dd9ff40fc0e1f0167c4149cb92bce0fd1f9a7fe512"
FNTRACE_HEADER_OUT = "77a7a870c133b0aa8c48c914efe073d7df7b19a292825ec09e61c16bd93875d8"
TEMPLATE_DIR = Path(__file__).resolve().parent / "trace_storage"
AUDIO_TEMPLATE = TEMPLATE_DIR / "audio_trace.c.template"
FNTRACE_HEADER_TEMPLATE = TEMPLATE_DIR / "fntrace.h.template"
RECEIPT_NAME = "trace-storage-source-receipt.json"

ALLOC_HELPER = """/* The pointer stays in .bss; the 144 MiB ring is allocated only when tracing
 * first records an armed dispatch. */
PSX_BSS FntraceEntry *g_fntrace_ring;
uint64_t             g_fntrace_seq = 0;
static int            s_fntrace_ring_alloc_attempted;

/* Single writer: fntrace_record runs on the emulation thread. Remember failed
 * allocation so an OOM does not retry malloc on every subsequent dispatch. */
static int fntrace_ring_ensure(void) {
    if (g_fntrace_ring) return 1;
    if (s_fntrace_ring_alloc_attempted) return 0;
    s_fntrace_ring_alloc_attempted = 1;
    g_fntrace_ring = (FntraceEntry*)malloc(
        (size_t)FNTRACE_RING_CAP * sizeof(FntraceEntry));
    return g_fntrace_ring != NULL;
}
"""


class TraceStoragePatchError(RuntimeError):
    pass


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read(path: Path) -> bytes:
    if not path.is_file():
        raise TraceStoragePatchError(f"missing input: {path}")
    return path.read_bytes()


def _transform_fntrace(raw: bytes) -> bytes:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise TraceStoragePatchError("fntrace.c is not UTF-8") from exc
    newline = "\r\n" if b"\r\n" in raw else "\n"
    text = text.replace("\r\n", "\n")
    include = "#include <string.h>\n"
    old_decl = "PSX_BSS FntraceEntry g_fntrace_ring[FNTRACE_RING_CAP];\nuint64_t             g_fntrace_seq = 0;"
    old_check = "    if (was_frozen) return;"
    if text.count(include) != 1 or text.count(old_decl) != 1 or text.count(old_check) != 1:
        raise TraceStoragePatchError("fntrace.c transform anchors are missing or ambiguous")
    if "fntrace_ring_ensure" in text or "PSX_BSS FntraceEntry *g_fntrace_ring;" in text:
        raise TraceStoragePatchError("partial/already-transformed fntrace.c in baseline state")
    if "#include <stdlib.h>\n" not in text:
        text = text.replace(include, include + "#include <stdlib.h>\n", 1)
    text = text.replace("/* Explicit .bss: without this, MinGW+LTO can emit ~144MiB of zeros into .rdata. */\n", "", 1)
    text = text.replace(old_decl, ALLOC_HELPER.rstrip("\n"), 1)
    text = text.replace(old_check, old_check + "\n    if (!fntrace_ring_ensure()) return;", 1)
    out = text.replace("\n", newline).encode("utf-8")
    if b"PSX_BSS FntraceEntry *g_fntrace_ring;" not in out or b"if (!fntrace_ring_ensure()) return;" not in out:
        raise TraceStoragePatchError("fntrace output failed its structural postcondition")
    return out


def _atomic_write(path: Path, data: bytes) -> None:
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def patch_trace_storage(project, game):
    """Patch one already-copied psxrecomp project. Reject unknown/partial states."""
    if game not in FNTRACE_BASE:
        raise TraceStoragePatchError(f"unsupported title: {game}")
    project = Path(project).resolve()
    paths = {
        "audio_source": project / "runtime/src/audio_trace.c",
        "fntrace_source": project / "runtime/src/fntrace.c",
        "fntrace_runtime_header": project / "runtime/include/fntrace.h",
        "fntrace_overlay_header": project / "overlay_toolchain/include/fntrace.h",
    }
    # Read and pin every input before any write.
    original = {name: _read(path) for name, path in paths.items()}
    audio_template = _read(AUDIO_TEMPLATE)
    header_template = _read(FNTRACE_HEADER_TEMPLATE)
    if sha(audio_template) != AUDIO_OUT or sha(header_template) != FNTRACE_HEADER_OUT:
        raise TraceStoragePatchError("private template drift")
    current = {name: sha(data) for name, data in original.items()}
    baseline = {
        "audio_source": AUDIO_BASE,
        "fntrace_source": FNTRACE_BASE[game],
        "fntrace_runtime_header": FNTRACE_HEADER_BASE,
        "fntrace_overlay_header": FNTRACE_HEADER_BASE,
    }
    output_fntrace = _transform_fntrace(original["fntrace_source"]) if current["fntrace_source"] == FNTRACE_BASE[game] else None
    if output_fntrace is not None and sha(output_fntrace) != FNTRACE_OUTPUT[game]:
        raise TraceStoragePatchError("fntrace transformed output hash mismatch")
    expected_output = {
        "audio_source": AUDIO_OUT,
        "fntrace_source": sha(output_fntrace) if output_fntrace is not None else FNTRACE_OUTPUT[game],
        "fntrace_runtime_header": FNTRACE_HEADER_OUT,
        "fntrace_overlay_header": FNTRACE_HEADER_OUT,
    }
    all_base = all(current[key] == baseline[key] for key in paths)
    all_output = all(expected_output[key] is not None and current[key] == expected_output[key] for key in paths)
    receipt_path = project / RECEIPT_NAME
    if receipt_path.exists():
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if receipt.get("kind") != "collection-trace-storage-source-patch-v1" or receipt.get("game") != game:
            raise TraceStoragePatchError("existing source receipt is not this title/patch")
        if receipt.get("output_hashes") != current:
            raise TraceStoragePatchError("source receipt does not match current files")
        if all_output:
            return receipt
        raise TraceStoragePatchError("receipt exists but source files are not wholly transformed")
    if not all_base and not all_output:
        raise TraceStoragePatchError(f"unknown or mixed source state; no writes made: {current}")
    if all_output:
        state = "already-transformed-exact-output"
        output = original
        input_hashes = None
    else:
        state = "transformed"
        output = {
            "audio_source": audio_template,
            "fntrace_source": output_fntrace,
            "fntrace_runtime_header": header_template,
            "fntrace_overlay_header": header_template,
        }
        input_hashes = current.copy()
        if sha(output["audio_source"]) != AUDIO_OUT or sha(output["fntrace_runtime_header"]) != FNTRACE_HEADER_OUT:
            raise TraceStoragePatchError("candidate template hash mismatch")
        if game == "jf2" and b"jf2_desktop_camera(cpu,target);" not in output["fntrace_source"]:
            raise TraceStoragePatchError("JF2 camera callback was not preserved")
        if game in ("jf1", "robbit") and b"robbit_desktop_camera(cpu,target);" not in output["fntrace_source"]:
            raise TraceStoragePatchError("JF1/Robbit title callback was not preserved")
    output_hashes = {key: sha(value) for key, value in output.items()}
    if state == "transformed" and (output_hashes["audio_source"] != AUDIO_OUT or output_hashes["fntrace_runtime_header"] != FNTRACE_HEADER_OUT):
        raise TraceStoragePatchError("unexpected transformed output hash")
    receipt = {
        "schema": 1,
        "kind": "collection-trace-storage-source-patch-v1",
        "game": game,
        "state": state,
        "base_hashes": baseline,
        "input_hashes": input_hashes,
        "output_hashes": output_hashes,
        "changed_paths": [str(paths[key]) for key in paths] if state == "transformed" else [],
        "standalone_sources_modified": False,
        "reader_rebuild_required": ["runtime/src/fntrace.c", "runtime/src/main.cpp", "runtime/src/debug_server.c"],
    }
    if state == "transformed":
        for name, path in paths.items():
            _atomic_write(path, output[name])
        if {key: sha(_read(path)) for key, path in paths.items()} != output_hashes:
            raise TraceStoragePatchError("post-write output hash mismatch; preserve target for inspection")
    _atomic_write(receipt_path, (json.dumps(receipt, indent=2) + "\n").encode("utf-8"))
    return receipt
