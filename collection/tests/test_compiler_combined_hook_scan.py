"""One hook-address scan preserves generated C while removing a full-source pass."""
from pathlib import Path
import hashlib
import importlib.util
import re
import sys
import tempfile
import unittest
from unittest.mock import patch as mock_patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import patch_compiler
from prepare_runtimes import PROJECTS

RETAINED_C=ROOT/'.workbench/static-recomp/staged/luna-static-coverage/jf1-232-helper-emission-v2/retained-jm6-full.c'
RETAINED_SHA256='4ab260a1b2ec7e549392c055af635a4ed83629d0f731cd9e3d50b2d139106fa7'


class CombinedHookScanTests(unittest.TestCase):
    def test_retained_and_synthetic_c_are_byte_identical_with_one_hook_scan(self):
        self.assertTrue(RETAINED_C.is_file(),'retained actual emitter C unavailable')
        retained=RETAINED_C.read_bytes()
        self.assertEqual(hashlib.sha256(retained).hexdigest(),RETAINED_SHA256)
        source_path=PROJECTS['jf2'][0]/'psxrecomp/tools/compile_overlays.py'
        source_bytes=source_path.read_bytes()

        class CountingRegex:
            def __init__(self,module):
                self.module=module;self.hook_passes=0
            def sub(self,pattern,*args,**kwargs):
                if 'block_([0-9A-Fa-f]{8}):$' in pattern or r'\s*\n\{' in pattern:
                    self.hook_passes+=1
                return re.sub(pattern,*args,**kwargs)
            def __getattr__(self,name):return getattr(re,name)

        def make_module(temp,combined):
            path=Path(temp)/'compile_overlays.py';path.write_bytes(source_bytes)
            if combined:
                patch_compiler.patch(path)
            else:
                with mock_patch.object(patch_compiler,'patch_combined_hook_scan',lambda _path:None):
                    patch_compiler.patch(path)
            spec=importlib.util.spec_from_file_location('combined_'+str(combined),path)
            module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
            module.DISPATCH_PREAMBLE=''
            return module

        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            baseline=make_module(a,False);optimized=make_module(b,True)
            baseline_re=CountingRegex(baseline);optimized_re=CountingRegex(optimized)
            baseline.re=baseline_re;optimized.re=optimized_re

            def compare(candidate, load, size):
                before_old=baseline_re.hook_passes;before_new=optimized_re.hook_passes
                old=baseline.patch_generated_c(candidate,load,size)
                new=optimized.patch_generated_c(candidate,load,size)
                self.assertEqual(new,old)
                self.assertEqual(baseline_re.hook_passes-before_old,2)
                self.assertEqual(optimized_re.hook_passes-before_new,1)
                before_old=baseline_re.hook_passes;before_new=optimized_re.hook_passes
                old=baseline.patch_generated_c_static(candidate,load,size)
                new=optimized.patch_generated_c_static(candidate,load,size)
                self.assertEqual(new,old)
                self.assertEqual(baseline_re.hook_passes-before_old,2)
                self.assertEqual(optimized_re.hook_passes-before_new,1)

            source=retained.decode('utf-8')
            compare(source,0x800EF2CC,232)
            self.assertNotIn('if(psx_mod_function_entry(cpu,',
                             baseline.patch_generated_c(source,0x800EF2CC,232))

            # Block-label, callable-entry, and legacy instruction spellings keep
            # the same callback behavior through both patch paths.
            block_candidate=('void func_800CA514(CPUState* cpu)\n{\n'
                'block_800CA514:\n    return;\n}\n')
            compare(block_candidate,0x800CA514,64)

            entry_candidate=('void func_800CA978(CPUState* cpu)\n{\n'
                '    return;\n}\n')
            compare(entry_candidate,0x800CA978,64)
            self.assertIn('psx_mod_function_entry(cpu,0x800CA978u)',
                          optimized.patch_generated_c(entry_candidate,0x800CA978,64))

            legacy_spelling=('void func_800CA9A0(CPUState* cpu)\n{\n'
                '    psx_mod_instruction ( cpu, 0X800CA9A0U , 0u);\n'
                '    return;\n}\n')
            compare(legacy_spelling,0x800CA9A0,64)
            self.assertNotIn('psx_mod_function_entry(cpu,0x800CA9A0u)',
                             optimized.patch_generated_c(legacy_spelling,0x800CA9A0,64))

            lower_label=('void func_800CAA10(CPUState* cpu)\n{\n'
                'block_800caa10:\n    return;\n}\n')
            compare(lower_label,0x800CAA10,64)

            duplicate_block=('void func_800CAA40(CPUState* cpu)\n{\n'
                'block_800CAA40:\n    goto block_800CAA40;\n'
                '}\nvoid func_800CAA40(CPUState* cpu)\n{\n'
                'block_800CAA40:\n    return;\n}\n')
            compare(duplicate_block,0x800CAA40,64)

            # Existing block detection historically uses a broad literal search,
            # including comments; keep that behavior byte-for-byte.
            comment_substring=('void func_800CAAC0(CPUState* cpu)\n{\n'
                '    /* retained block_800CAAC0: marker */\n'
                '    return;\n}\n')
            compare(comment_substring,0x800CAAC0,64)
            self.assertNotIn('psx_mod_function_entry(cpu,0x800CAAC0u)',
                             optimized.patch_generated_c(comment_substring,0x800CAAC0,64))

            # Anchor drift fails before the source file is changed.
            with tempfile.TemporaryDirectory() as temp:
                malformed=Path(temp)/'malformed.py'
                malformed.write_text('no hook anchors\n',encoding='utf-8')
                original=malformed.read_bytes()
                with self.assertRaisesRegex(ValueError,'Combined hook scan anchors changed'):
                    patch_compiler.patch_combined_hook_scan(malformed)
                self.assertEqual(malformed.read_bytes(),original)


if __name__=='__main__':
    unittest.main()
