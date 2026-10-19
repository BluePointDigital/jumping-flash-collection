from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from patch_compiler import patch_runtime
from prepare_runtimes import PROJECTS


class RobbitRuntimePatchTests(unittest.TestCase):
    def test_instruction_bridge_is_before_optional_plugin_gate_and_idempotent(self):
        source=PROJECTS['robbit'][0]/'psxrecomp'
        with tempfile.TemporaryDirectory() as directory:
            framework=Path(directory)
            names=('runtime/include/overlay_api.h','runtime/src/mod_runtime.cpp','runtime/src/dirty_ram_interp.c')
            for name in names:
                target=framework/name;target.parent.mkdir(parents=True,exist_ok=True)
                target.write_bytes((source/name).read_bytes())
            patch_runtime(framework)
            before={name:(framework/name).read_bytes() for name in names}
            patch_runtime(framework)
            self.assertEqual(before,{name:(framework/name).read_bytes() for name in names})
            text=(framework/'runtime/src/mod_runtime.cpp').read_text()
            body=text.split('extern "C" void psx_mod_instruction(CPUState* cpu, uint32_t address, uint32_t instruction) {',1)[1].split('\n}',1)[0]
            self.assertLess(body.index('robbit_desktop_camera(cpu,address)'),body.index('!g_psx_mod_instruction_hooks'))
            self.assertIn('#ifdef ROBBIT_DESKTOP',body)
            self.assertIn('robbit_control_site(address)',body)
            self.assertIn('cpu->gpr[0]=0',body)
            self.assertLess(body.index('jf2_desktop_camera(cpu,address)'),body.index('!g_psx_mod_instruction_hooks'))
            self.assertIn('defined(JF2_DESKTOP) && defined(COLLECTION_RUNTIME)',body)
            self.assertIn('jf2_control_site(address)',body)
            instruction=text.index('extern "C" void psx_mod_instruction(')
            for name in ('robbit_desktop_camera','jf2_desktop_camera'):
                self.assertLess(text.index(f'extern "C" void {name}(CPUState*,uint32_t);'),instruction)


if __name__=='__main__':unittest.main()
