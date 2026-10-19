"""Regression fixture for one-pass generated-C hook dedup scans."""
from pathlib import Path
import hashlib
import re
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from patch_compiler import patch_instruction_hook_dedup

RETAINED_C = ROOT / ".workbench/static-recomp/staged/luna-static-coverage/jf1-232-helper-emission-v2/retained-jm6-full.c"
RETAINED_C_SHA256 = "4ab260a1b2ec7e549392c055af635a4ed83629d0f731cd9e3d50b2d139106fa7"

BASE_SOURCE = r'''import re

def patch_generated_c(src, camera_sites):
    def add_camera_hook(match):
        address=int(match.group(1),16)
        if (address & 0x1fffffff) not in camera_sites:return match.group(0)
        return match.group(0) + f'\n    if(psx_mod_function_entry(cpu,0x{address:08X}u))return;'
    src = re.sub(r'^block_([0-9A-Fa-f]{8}):$',add_camera_hook,src,flags=re.MULTILINE)
    def add_entry_hook(match):
        address=int(match.group(2),16)
        if (address & 0x1fffffff) not in camera_sites or f'block_{address:08X}:' in src:return match.group(0)
        return match.group(0)+f'\n    if(psx_mod_function_entry(cpu,0x{address:08X}u))return;'
    src=re.sub(r'^(void func_([0-9A-Fa-f]{8})\(CPUState\* cpu\)\s*\n\{)',add_entry_hook,src,flags=re.MULTILINE)
    return src

def patch_generated_c_static(src, camera_sites):
    def add_camera_hook(match):
        address=int(match.group(1),16)
        if (address & 0x1fffffff) not in camera_sites:return match.group(0)
        return match.group(0) + f'\n    if(psx_mod_function_entry(cpu,0x{address:08X}u))return;'
    src = re.sub(r'^block_([0-9A-Fa-f]{8}):$',add_camera_hook,src,flags=re.MULTILINE)
    def add_entry_hook(match):
        address=int(match.group(2),16)
        if (address & 0x1fffffff) not in camera_sites or f'block_{address:08X}:' in src:return match.group(0)
        return match.group(0)+f'\n    if(psx_mod_function_entry(cpu,0x{address:08X}u))return;'
    src=re.sub(r'^(void func_([0-9A-Fa-f]{8})\(CPUState\* cpu\)\s*\n\{)',add_entry_hook,src,flags=re.MULTILINE)
    return src
'''


def legacy_source() -> str:
    camera_anchor = "        if (address & 0x1fffffff) not in camera_sites:return match.group(0)"
    entry_anchor = "        if (address & 0x1fffffff) not in camera_sites or f'block_{address:08X}:' in src:return match.group(0)"
    scan = r"        if re.search(r'\bpsx_mod_instruction\s*\(\s*cpu,\s*0x%08x[uU]?\s*,' % address,src,re.I):return match.group(0)"
    return BASE_SOURCE.replace(camera_anchor, camera_anchor + "\n" + scan).replace(
        entry_anchor, entry_anchor + "\n" + scan)


class CompilerHookScanDedupTests(unittest.TestCase):
    def compare_legacy_and_optimized(self, prefix=""):
        source = prefix + r'''
/* Existing-call spellings intentionally preserve the old regex's substring behavior. */
psx_mod_instruction ( cpu, 0X800E1528U , 0x00000000u);
psx_mod_instruction(cpu, 0x800e7f1c, 0x00000000u);
/* Existing block lookup is also a case-sensitive substring test. block_800E2550: */
block_800E1528:
block_800e1528:
block_800E7F1C:
block_800E2B4C:
block_800E2B4C:
block_800e2b90:
void func_800E2550(CPUState* cpu)
{
    return;
}
void func_800E2B90(CPUState* cpu)
{
    return;
}
void func_800E1D2C(CPUState* cpu)
{
    return;
}
'''
        camera_sites = {0xE1528, 0xE7F1C, 0xE2B4C, 0xE2B90, 0xE2550, 0xE1D2C}
        legacy_ns = {"__name__": "legacy_fixture"}
        exec(compile(legacy_source(), "legacy-hook-fixture.py", "exec"), legacy_ns)
        legacy = legacy_ns["patch_generated_c"](source, camera_sites)

        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "compile_overlays.py"
            path.write_text(BASE_SOURCE, encoding="utf-8")
            patch_instruction_hook_dedup(path)
            optimized_source = path.read_text(encoding="utf-8")
            patch_instruction_hook_dedup(path)
            self.assertEqual(path.read_text(encoding="utf-8"), optimized_source)
            legacy_path = Path(temp) / "legacy_compile_overlays.py"
            legacy_path.write_text("# COLLECTION_CONFIGURED_SITE_DEDUP_V1\n" + legacy_source(), encoding="utf-8")
            patch_instruction_hook_dedup(legacy_path)
            self.assertEqual(legacy_path.read_text(encoding="utf-8"), optimized_source)
        self.assertEqual(optimized_source.count("existing_instruction_addresses = None"), 2)
        self.assertEqual(optimized_source.count("existing_block_literals = None"), 2)
        self.assertNotIn("re.search(r'\\bpsx_mod_instruction", optimized_source)

        class CountingRegex:
            def __init__(self):
                self.instruction_scans = 0
                self.block_scans = 0

            def finditer(self, pattern, *args, **kwargs):
                if "psx_mod_instruction" in pattern:
                    self.instruction_scans += 1
                return re.finditer(pattern, *args, **kwargs)

            def findall(self, pattern, *args, **kwargs):
                if pattern == r"block_[0-9A-F]{8}:":
                    self.block_scans += 1
                return re.findall(pattern, *args, **kwargs)

            def __getattr__(self, name):
                return getattr(re, name)

        optimized_ns = {"__name__": "optimized_fixture"}
        exec(compile(optimized_source, "optimized-hook-fixture.py", "exec"), optimized_ns)
        regex_counter = CountingRegex()
        optimized_ns["re"] = regex_counter
        optimized = optimized_ns["patch_generated_c"](source, camera_sites)
        optimized_static = optimized_ns["patch_generated_c_static"](source, camera_sites)
        self.assertEqual((regex_counter.instruction_scans, regex_counter.block_scans), (2, 2))
        regex_counter.instruction_scans = regex_counter.block_scans = 0
        no_camera_source = "block_80012345:\nvoid func_80012345(CPUState* cpu)\n{\n    return;\n}\n"
        self.assertEqual(optimized_ns["patch_generated_c"](no_camera_source, camera_sites), no_camera_source)
        self.assertEqual(optimized_ns["patch_generated_c_static"](no_camera_source, camera_sites), no_camera_source)
        self.assertEqual((regex_counter.instruction_scans, regex_counter.block_scans), (0, 0))
        legacy_static_ns = {"__name__": "legacy_static_fixture"}
        exec(compile(legacy_source(), "legacy-static-fixture.py", "exec"), legacy_static_ns)
        legacy_static = legacy_static_ns["patch_generated_c_static"](source, camera_sites)
        self.assertEqual(optimized, legacy)
        self.assertEqual(optimized_static, legacy_static)
        self.assertEqual(optimized.count("if(psx_mod_function_entry(cpu,0x800E2B4Cu))return;"), 2)
        self.assertEqual(optimized.count("if(psx_mod_function_entry(cpu,0x800E2B90u))return;"), 2)
        self.assertEqual(optimized.count("if(psx_mod_function_entry(cpu,0x800E1D2Cu))return;"), 1)
        self.assertNotIn("if(psx_mod_function_entry(cpu,0x800E1528u))return;", optimized)
        self.assertNotIn("if(psx_mod_function_entry(cpu,0x800E7F1Cu))return;", optimized)

    def test_synthetic_spellings_idempotence_and_upgrade_without_workbench(self):
        self.compare_legacy_and_optimized()

    @unittest.skipUnless(RETAINED_C.is_file(), "optional retained emitted C is unavailable in a clean checkout")
    def test_retained_generated_c_matches_legacy(self):
        raw = RETAINED_C.read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), RETAINED_C_SHA256)
        self.compare_legacy_and_optimized(raw.decode("utf-8"))

    def test_legacy_marker_drift_fails_before_write(self):
        changed = legacy_source().replace(
            "if re.search(r'\\bpsx_mod_instruction\\s*\\(\\s*cpu,\\s*0x%08x[uU]?\\s*,"
            "' % address,src,re.I):return match.group(0)",
            "if False:return match.group(0)",
            1,
        )
        self.assertNotEqual(changed, legacy_source(), "drift fixture did not change its anchor")
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "drifted_compile_overlays.py"
            original = "# COLLECTION_CONFIGURED_SITE_DEDUP_V1\n" + changed
            path.write_text(original, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Legacy configured-site scan patch drifted"):
                patch_instruction_hook_dedup(path)
            self.assertEqual(path.read_text(encoding="utf-8"), original)


if __name__ == "__main__":
    unittest.main()
