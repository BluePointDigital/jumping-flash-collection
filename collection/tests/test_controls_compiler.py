"""Both real compiler patching paths must retain interior and callable hooks."""
from pathlib import Path
import importlib.util
import unittest

ROOT=Path(__file__).resolve().parents[1]
script=ROOT/'.workbench/native/jf1/psxrecomp/tools/compile_overlays.py'
spec=importlib.util.spec_from_file_location('collection_compiler',script)
compiler=importlib.util.module_from_spec(spec);spec.loader.exec_module(compiler)
compiler.load_dispatch_preamble(str(script.parents[1]/'runtime/include'))

class ControlsCompilerTests(unittest.TestCase):
    def patch(self,source,static):
        result=compiler.patch_generated_c_static(source,0x800b0000,0x50000) if static else compiler.patch_generated_c(source,0x800b0000,0x50000)
        return result[0] if static else result

    def test_callable_without_label_and_interior_with_label(self):
        source='''#include "psx_runtime.h"
void func_800DC4C4(CPUState* cpu);
void func_800DC4C4(CPUState* cpu)
{
block_800DC928:
    return;
}
'''
        for static in [False,True]:
            with self.subTest(static=static):
                result=self.patch(source,static)
                self.assertEqual(result.count('if(psx_mod_function_entry(cpu,0x800DC4C4u))return;'),1)
                self.assertEqual(result.count('if(psx_mod_function_entry(cpu,0x800DC928u))return;'),1)

    def test_labeled_entry_not_duplicated_and_other_function_untouched(self):
        source='''#include "psx_runtime.h"
void func_800DD158(CPUState* cpu)
{
block_800DD158:
block_800DD260:
    return;
}
void func_800DC000(CPUState* cpu)
{
    return;
}
'''
        for static in [False,True]:
            with self.subTest(static=static):
                result=self.patch(source,static)
                self.assertEqual(result.count('if(psx_mod_function_entry(cpu,0x800DD158u))return;'),1)
                self.assertEqual(result.count('if(psx_mod_function_entry(cpu,0x800DD260u))return;'),1)
                self.assertNotIn('if(psx_mod_function_entry(cpu,0x800DC000u))return;',result)

if __name__=='__main__':unittest.main()
