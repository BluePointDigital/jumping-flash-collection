from __future__ import annotations

import hashlib
import importlib.util
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("fastprefix_v4", HERE.parent / "tools/enable_jf2_fastprefix.py")
fastprefix = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(fastprefix)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class FastprefixPrivateIntegrationTest(unittest.TestCase):
    def fixture(self):
        temp = tempfile.TemporaryDirectory()
        root = Path(temp.name)
        project = root / "private jf2 project"
        framework = project / "psxrecomp"
        (framework / "runtime/include").mkdir(parents=True)
        (project / "game.toml").write_text('[game]\nid = "SCES-00111"\n', encoding="utf-8")
        static = project / "static"
        static.mkdir()
        tu = static / fastprefix.TU_NAME
        tu_bytes = b"audited TU0036 test bytes"
        tu.write_bytes(tu_bytes)
        cmake = project / "CMakeLists.txt"
        cmake.write_text(
            'cmake_minimum_required(VERSION 3.20)\n'
            'set(PSXRECOMP_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/psxrecomp" CACHE PATH "")\n'
            'project(JF2 LANGUAGES C CXX)\n'
            'psxrecomp_add_game_runtime(psx-runtime\n'
            '    GAME_OVERLAY_STATIC_C "${CMAKE_CURRENT_SOURCE_DIR}/static/overlays_static.c"\n)\n'
            'set(_JF2_AUDITED_STATIC_SOURCES\n'
            '    "${CMAKE_CURRENT_SOURCE_DIR}/static/overlays_static_0036.c"\n)\n'
            'set_source_files_properties(${_JF2_AUDITED_STATIC_SOURCES} PROPERTIES\n'
            '    COMPILE_OPTIONS "-ffunction-sections")\n'
            'target_link_options(psx-runtime PRIVATE "-Wl,--gc-sections")\n', encoding="utf-8")
        base_header = framework / "runtime/include/psx_cyc.h"
        base_bytes = b"original cycles header"
        base_header.write_bytes(base_bytes)
        candidate = root / "candidate/psx_cyc.h"
        candidate.parent.mkdir()
        fast_bytes = b"reviewed fastprefix header"
        candidate.write_bytes(fast_bytes)
        fastprefix.TU_SHA256 = digest(tu_bytes)
        fastprefix.FAST_SHA256 = digest(fast_bytes)
        fastprefix.BASE_SHA256 = digest(base_bytes)
        return temp, project, candidate, cmake, tu, framework

    def test_late_append_is_opt_in_and_integrity_checked(self):
        temp, project, candidate, cmake, tu, framework = self.fixture()
        with temp:
            before = cmake.read_bytes()
            result = fastprefix.apply(project, candidate, write=True)
            self.assertEqual(result["state"], "private-prepared-opt-in-off")
            transformed = cmake.read_bytes()
            text = transformed.decode("utf-8")
            self.assertGreater(text.index("set_source_files_properties(${_JF2_AUDITED_STATIC_SOURCES}"),
                                text.index("psxrecomp_add_game_runtime"))
            self.assertGreater(text.index(fastprefix.MARKER), text.index('COMPILE_OPTIONS "-ffunction-sections"'))
            self.assertIn('APPEND PROPERTY COMPILE_OPTIONS "-include"', text)
            self.assertIn("OFF)", text)
            self.assertEqual(transformed[:len(before)], before)
            self.assertEqual((framework / "runtime/include" / fastprefix.HEADER_NAME).read_bytes(),
                             candidate.read_bytes())
            self.assertEqual(fastprefix.apply(project, candidate, write=True)["state"],
                             "already-prepared-integrity-verified")
            cmake.write_bytes(transformed.replace(b"project(JF2", b"project(JF2 "))
            with self.assertRaisesRegex(ValueError, "drifted"):
                fastprefix.apply(project, candidate, write=True)

    def test_duplicate_tu_rejects_before_writing(self):
        temp, project, candidate, cmake, tu, framework = self.fixture()
        with temp:
            text = cmake.read_text(encoding="utf-8")
            source = '    "${CMAKE_CURRENT_SOURCE_DIR}/static/overlays_static_0036.c"\n'
            cmake.write_text(text.replace(source, source + source), encoding="utf-8")
            before = cmake.read_bytes()
            with self.assertRaisesRegex(ValueError, "found 2"):
                fastprefix.apply(project, candidate, write=True)
            self.assertEqual(cmake.read_bytes(), before)
            self.assertFalse((framework / "runtime/include" / fastprefix.HEADER_NAME).exists())

    def test_title_and_exact_tu_must_match_before_writes(self):
        temp, project, candidate, cmake, tu, framework = self.fixture()
        with temp:
            (project / "game.toml").write_text('[game]\nid = "OTHER"\n', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "game.id"):
                fastprefix.apply(project, candidate, write=True)
            self.assertNotIn(fastprefix.MARKER, cmake.read_text(encoding="utf-8"))
            (project / "game.toml").write_text('[game]\nid = "SCES-00111"\n', encoding="utf-8")
            tu.write_bytes(b"different source bytes")
            with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                fastprefix.apply(project, candidate, write=True)
            self.assertFalse((framework / "runtime/include" / fastprefix.HEADER_NAME).exists())

    def test_standalone_framework_override_is_rejected(self):
        temp, project, candidate, cmake, tu, framework = self.fixture()
        with temp:
            real_repo = next(p for p in HERE.parents if (p / ".jf2-workbench").is_dir())
            standalone = real_repo / ".jf2-workbench/recomp/JumpingFlash2Recomp/psxrecomp"
            cmake.write_text(cmake.read_text(encoding="utf-8").replace(
                '${CMAKE_CURRENT_SOURCE_DIR}/psxrecomp', str(standalone).replace("\\", "/")),
                encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "inside the private"):
                fastprefix.apply(project, candidate, write=True)
            self.assertNotIn(fastprefix.MARKER, cmake.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

