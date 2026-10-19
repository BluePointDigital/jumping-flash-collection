"""Collection-only pipeline preferences preserve the existing JF2 adapters."""
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'collection/tools'))
from runtime_adapter import adapt_desktop,adapt_jf2_collection_pipeline_ui


class Jf2PipelineUiTests(unittest.TestCase):
    def test_private_header_upgrade_preserves_hooks_and_standalone_source(self):
        baseline=ROOT/'tools/recomp/jf2_desktop.h'
        before=baseline.read_bytes()
        with tempfile.TemporaryDirectory() as folder:
            project=Path(folder)
            header=project/'desktop/jf2_desktop.h'
            main=project/'psxrecomp/runtime/src/main.cpp'
            header.parent.mkdir(parents=True);main.parent.mkdir(parents=True)
            header.write_bytes(before)
            main.write_text('jf2_desktop_init(exe_dir_from_argv(argv[0]));\n')
            adapt_desktop(project)
            first=header.read_bytes();text=header.read_text(encoding='utf-8')
            for hook in ('if(collection_mode)jf2_last_pad &= collection_controller_word;',
                         '!(jf2_captured || collection_aim_live) || jf2_desktop_open()',
                         'if(collection_mode){jf2_save();jf2_release_inputs();'):
                self.assertEqual(text.count(hook),1)
            self.assertIn('if(collection_mode) {\n        add("render_thread"',text)
            self.assertIn('s.render_thread=g_render_thread_pref!=0;s.has_render_thread=true;',text)
            self.assertIn('s.frame_generation=g_frame_generation_pref!=0;s.has_frame_generation=true;',text)
            self.assertNotIn('add("present_thread"',text)
            adapt_desktop(project)
            self.assertEqual(header.read_bytes(),first)
            self.assertEqual(baseline.read_bytes(),before)
        with self.assertRaises(ValueError):adapt_jf2_collection_pipeline_ui('unknown source')

    def test_production_availability_helpers(self):
        compiler=ROOT/'.jf2-workbench/recomp/toolchain/bin/clang++.exe'
        if not compiler.is_file():self.skipTest('bundled compiler unavailable')
        source=adapt_jf2_collection_pipeline_ui((ROOT/'tools/recomp/jf2_desktop.h').read_text(encoding='utf-8'))
        helpers=re.search(r'static bool jf2_pipeline_options_available\(bool.*?(?=\nstatic bool jf2_pipeline_options_available\(\))',source,re.S)
        self.assertIsNotNone(helpers)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'helpers.cpp';exe=Path(folder)/'helpers.exe'
            path.write_text('#include <cassert>\n'+helpers.group(0)+'''\nint main(){
    assert(!jf2_pipeline_options_available(false,1));
    assert(!jf2_pipeline_options_available(true,0));
    assert(jf2_pipeline_options_available(true,1));
    assert(!jf2_pipeline_option_enabled(false,false,1));
    assert(jf2_pipeline_option_enabled(true,false,0));
    assert(!jf2_pipeline_option_enabled(true,true,0));
    assert(jf2_pipeline_option_enabled(true,true,1));
}''',encoding='utf-8')
            result=subprocess.run([str(compiler),'-std=c++17','-static',str(path),'-o',str(exe)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(subprocess.run([str(exe)]).returncode,0)


if __name__=='__main__':unittest.main()
