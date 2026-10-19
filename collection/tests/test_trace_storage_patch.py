from __future__ import annotations

import hashlib
import importlib.util
import shutil
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1] / "tools"
REPO = next(p for p in HERE.parents if (p / "collection/catalog.toml").is_file())
SPEC = importlib.util.spec_from_file_location("trace_storage_patch", HERE / "patch_trace_storage.py")
PATCH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PATCH)

SOURCE_ROOTS = {
    "jf1": REPO / "jumping-flash-1/.workbench/psxrecomp",
    "jf2": REPO / ".jf2-workbench/recomp/JumpingFlash2Recomp/psxrecomp",
    "robbit": REPO / "robbit-mon-dieu/.workbench/psxrecomp",
}
RELATIVE_FILES = (
    Path("runtime/src/audio_trace.c"),
    Path("runtime/src/fntrace.c"),
    Path("runtime/include/fntrace.h"),
    Path("overlay_toolchain/include/fntrace.h"),
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_copy(tmp: Path, title: str) -> Path:
    src = SOURCE_ROOTS[title]
    dst = tmp / "psxrecomp"
    for rel in RELATIVE_FILES:
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src / rel, target)
    return dst


class TraceStoragePatchTests(unittest.TestCase):
    def test_all_three_titles_and_idempotence(self):
        for title in SOURCE_ROOTS:
            with self.subTest(title=title), tempfile.TemporaryDirectory() as td:
                project = make_copy(Path(td), title)
                before = {str(rel): digest(project / rel) for rel in RELATIVE_FILES}
                record = PATCH.patch_trace_storage(project, title)
                self.assertEqual(record["state"], "transformed")
                self.assertTrue(record["standalone_sources_modified"] is False)
                self.assertEqual(digest(project / RELATIVE_FILES[0]), PATCH.AUDIO_OUT)
                self.assertEqual(digest(project / RELATIVE_FILES[2]), PATCH.FNTRACE_HEADER_OUT)
                self.assertEqual((project / RELATIVE_FILES[2]).read_bytes(), (project / RELATIVE_FILES[3]).read_bytes())
                fn = (project / RELATIVE_FILES[1]).read_bytes()
                self.assertIn(b"PSX_BSS FntraceEntry *g_fntrace_ring;", fn)
                self.assertIn(b"if (!fntrace_ring_ensure()) return;", fn)
                callback = b"jf2_desktop_camera(cpu,target);" if title == "jf2" else b"robbit_desktop_camera(cpu,target);"
                self.assertIn(callback, fn)
                self.assertEqual(digest(SOURCE_ROOTS[title] / RELATIVE_FILES[1]), before[str(RELATIVE_FILES[1])])
                times = {str(rel): (project / rel).stat().st_mtime_ns for rel in RELATIVE_FILES}
                repeated = PATCH.patch_trace_storage(project, title)
                self.assertEqual(repeated, record)
                self.assertEqual(times, {str(rel): (project / rel).stat().st_mtime_ns for rel in RELATIVE_FILES})

    def test_unknown_input_rejected_before_any_write(self):
        with tempfile.TemporaryDirectory() as td:
            project = make_copy(Path(td), "jf1")
            changed = project / RELATIVE_FILES[0]
            changed.write_bytes(changed.read_bytes() + b"\nunknown drift\n")
            before = {str(rel): digest(project / rel) for rel in RELATIVE_FILES}
            with self.assertRaises(PATCH.TraceStoragePatchError):
                PATCH.patch_trace_storage(project, "jf1")
            self.assertEqual(before, {str(rel): digest(project / rel) for rel in RELATIVE_FILES})
            self.assertFalse((project / PATCH.RECEIPT_NAME).exists())

    def test_mixed_header_state_rejected_before_any_write(self):
        with tempfile.TemporaryDirectory() as td:
            project = make_copy(Path(td), "jf2")
            (project / RELATIVE_FILES[2]).write_bytes(PATCH.FNTRACE_HEADER_TEMPLATE.read_bytes())
            before = {str(rel): digest(project / rel) for rel in RELATIVE_FILES}
            with self.assertRaises(PATCH.TraceStoragePatchError):
                PATCH.patch_trace_storage(project, "jf2")
            self.assertEqual(before, {str(rel): digest(project / rel) for rel in RELATIVE_FILES})
            self.assertFalse((project / PATCH.RECEIPT_NAME).exists())


if __name__ == "__main__":
    unittest.main()
