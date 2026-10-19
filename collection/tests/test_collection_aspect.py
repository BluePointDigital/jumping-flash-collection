import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

TOOLS=Path(__file__).resolve().parents[1]/'tools'
sys.path.insert(0,str(TOOLS))
from patch_graphics import collection_aspect_source


SOURCE='''#include <cstdint>
#include <cassert>
static bool collection_mode=true;
static int g_video_aspect_num=4;
static int           g_video_aspect_den = 3;
static int applied_num=0,applied_den=0,api_calls=0;
static int gte_mode=0;
static void gpu_ws_set_gte_game_mode(int value){gte_mode=value;}
static int psx_mod_set_fixed_display_aspect(uint32_t n,uint32_t d){
    ++api_calls;g_video_aspect_num=n;g_video_aspect_den=d;return 1;
}
static void gl_renderer_set_display_aspect(int n,int d){applied_num=n;applied_den=d;}
static struct {bool has_aspect_ratio;int aspect_num,aspect_den;}us;
static void resolve(){
        if (us.has_aspect_ratio) {
            g_video_aspect_num = us.aspect_num;
            g_video_aspect_den = us.aspect_den;
        }
    // The actual frontend clears legacy aspect before trusted activation.
    g_video_aspect_num=4;g_video_aspect_den=3;
    /* Display aspect. Identity at the default 4:3. The present letterbox uses
     * this aspect; native-wide fills it with a genuinely wider frame (no
     * stretch), squash mode stretches the 4:3 frame into it. */
    gl_renderer_set_display_aspect(g_video_aspect_num, g_video_aspect_den);
}
'''


class CollectionAspectTests(unittest.TestCase):
    def test_idempotent_and_rejects_changed_or_ambiguous_sources(self):
        patched=collection_aspect_source(SOURCE)
        self.assertEqual(collection_aspect_source(patched),patched)
        with self.assertRaises(ValueError):
            collection_aspect_source(SOURCE.replace('g_video_aspect_den = 3;','g_video_aspect_den = 4;'))
        with self.assertRaises(ValueError):
            collection_aspect_source(SOURCE+SOURCE)

    def test_compiled_setting_resolution_uses_native_api_after_legacy_clamp(self):
        bundled=TOOLS.parents[1]/'.jf2-workbench/recomp/toolchain/bin/clang++.exe'
        compiler=str(bundled) if bundled.is_file() else shutil.which('clang++')
        if not compiler:self.skipTest('C++ compiler unavailable')
        source=collection_aspect_source(SOURCE)+'''
int main(){
    struct Case{bool collection,has;int n,d,expected_n,expected_d;};
    for(const auto& c:{Case{true,true,16,10,16,10},Case{true,true,16,9,16,9},
        Case{true,true,4,3,4,3},Case{true,true,21,9,4,3},Case{true,true,0,0,4,3},
        Case{true,false,16,10,4,3},Case{false,true,16,10,4,3}}){
        collection_display_num=4;collection_display_den=3;api_calls=0;gte_mode=0;
        g_video_aspect_num=4;g_video_aspect_den=3;
        collection_mode=c.collection;us={c.has,c.n,c.d};resolve();
        assert(applied_num==c.expected_n&&applied_den==c.expected_d);
        assert(api_calls==(c.collection?1:0));
        assert(gte_mode==0);
    }
}
'''
        source=source.replace('#include <cassert>','#include <cassert>\n#include <initializer_list>')
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);path=root/'test.cpp';path.write_text(source)
            exe=root/('test.exe' if os.name=='nt' else 'test')
            for title in ('JF1_DESKTOP','JF2_DESKTOP','ROBBIT_DESKTOP'):
                command=[compiler,'-O2','-std=c++17','-D'+title,str(path),'-o',str(exe)]
                if os.name=='nt':command.insert(1,'-static')
                result=subprocess.run(command,capture_output=True,text=True)
                self.assertEqual(result.returncode,0,result.stderr)
                result=subprocess.run([str(exe)],capture_output=True,text=True)
                self.assertEqual(result.returncode,0,result.stderr)


if __name__=='__main__':unittest.main()
