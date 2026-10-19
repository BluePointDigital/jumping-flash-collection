"""Exercise the maintained transformation against clean title source inputs."""
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
CLANG=ROOT.parent/'.jf2-workbench/recomp/toolchain/bin/clang.exe'
sys.path.insert(0,str(ROOT/'tools'))
from patch_performance import patch
from prepare_runtimes import PROJECTS


class PerformancePatchTests(unittest.TestCase):
    def test_all_clean_titles_idempotent_and_fail_closed(self):
        names=('debug_server.c','freeze_heartbeat.c','present_image_ring.c','gpu_gl_renderer.c','main.cpp','overlay_loader.c','dirty_ram_interp.c','gpu.c','gte.cpp','host_sampler.c')
        for game,(source,_) in PROJECTS.items():
            with self.subTest(game=game),tempfile.TemporaryDirectory() as temporary:
                framework=Path(temporary)
                target=framework/'runtime/src';target.mkdir(parents=True)
                for name in names:
                    (target/name).write_bytes((source/'psxrecomp/runtime/src'/name).read_bytes())
                patch(framework)
                before={name:(target/name).read_bytes() for name in names}
                patch(framework)
                self.assertEqual(before,{name:(target/name).read_bytes() for name in names})
                self.assertIn(b'collection_metrics_swap(generated)',before['gpu_gl_renderer.c'])
                self.assertIn(b'collection_metrics_guest_tick(s_frame_count)',before['main.cpp'])
                self.assertNotIn(b'fps=%.1f',before['main.cpp'])
                loader=before['overlay_loader.c'].split(b'static int cache_idx_has_path',1)[1].split(b'\n}',1)[0]
                self.assertNotIn(b'#if',loader)
                self.assertIn(b'cache_path_equal',loader)
                self.assertIn(b'COLLECTION_OVERLAY_CANDIDATE_CAP',before['overlay_loader.c'])
                self.assertIn(b'collection_overlay_limits_json',before['debug_server.c'])
                self.assertIn(b'PSX_PHASE_SAMPLER',before['debug_server.c'])
                self.assertIn(b'PSX_DIAG_GTE_RTP',before['gte.cpp'])
                self.assertIn(b'if (trace_intpl) gte_intpl_record',before['gte.cpp'])
                self.assertIn(b'if(jf2_control_site(pc)&&(pc&0x1fffffffu)!=0xf3a44u)',before['dirty_ram_interp.c'])
                self.assertIn(b'if((addr&0x1fffffffu)==0xf3a44u)jf2_desktop_camera(cpu,addr);',before['dirty_ram_interp.c'])
                census=before['gpu.c'].decode('utf-8')
                self.assertIn('COLLECTION_PERF_CENSUS_DEFAULT_OFF_V1',census)
                self.assertIn('static int            ws_census_on  = 0;     /* opt-in; toggle via ws_census */',census)
                record_start=census.index('static void ws_census_record(uint8_t opcode, int32_t x, int32_t y) {')
                record_end=census.index('\n}',record_start)+2
                record=census[record_start:record_end]
                self.assertLess(record.index('if (!ws_census_on) return;'),record.index('calloc(WS_CENSUS_CAP'))
                setter='void gpu_ws_census_set(int on) { ws_census_on = on ? 1 : 0; }'
                self.assertIn(setter,census)
                if game=='robbit':
                    self.assertIn(b'if (robbit_control_site(pc))',before['dirty_ram_interp.c'])
                    self.assertIn(b'#include "robbit_control_sites.h"',before['dirty_ram_interp.c'])
                    self.assertNotIn(b'collection_robbit_pc==',before['dirty_ram_interp.c'])
                broken=(target/'present_image_ring.c')
                broken.write_text('/* unexpected upstream source */')
                with self.assertRaises(ValueError):patch(framework)

    def test_census_default_off_skips_allocation_but_explicit_toggle_records(self):
        if not CLANG.is_file():self.skipTest(f'host clang unavailable: {CLANG}')
        source=PROJECTS['jf1'][0]/'psxrecomp/runtime/src/gpu.c'
        with tempfile.TemporaryDirectory() as temporary:
            framework=Path(temporary)
            target=framework/'runtime/src';target.mkdir(parents=True)
            for name in ('debug_server.c','freeze_heartbeat.c','present_image_ring.c','gpu_gl_renderer.c','main.cpp','overlay_loader.c','dirty_ram_interp.c','gte.cpp','host_sampler.c'):
                (target/name).write_bytes((source.parent/name).read_bytes())
            gpu=target/'gpu.c';gpu.write_bytes(source.read_bytes())
            patch(framework)
            census=gpu.read_text(encoding='utf-8')
            start=census.index('static void ws_census_record(uint8_t opcode, int32_t x, int32_t y) {')
            end=census.index('\n}',start)+2
            record=census[start:end]
            declaration=next(line for line in census.splitlines() if 'ws_census_on  = 0;' in line)
            setter_start=census.index('void gpu_ws_census_set(int on) {')
            setter_end=census.index('\n',setter_start)
            setter=census[setter_start:setter_end]
            prefix='''#include <stdint.h>
#include <stdlib.h>
typedef struct { uint32_t frame,src_addr; int16_t cam_x,cam_y,x,y,xmin,xmax,base_x; uint8_t opcode,tagged; } WsCensusEntry;
#define WS_CENSUS_CAP 8u
static WsCensusEntry *ws_census=NULL;
static uint64_t ws_census_seq=0,s_frame_count=3;
static uint32_t gp0_cmd_source_addr=0x1234;
static int draw_area_left=512;
static int alloc_calls=0;
static void *tracked_calloc(size_t n,size_t size){alloc_calls++;return calloc(n,size);}
#define calloc tracked_calloc
static void prim_sx_extent(uint8_t op,int32_t *xmin,int32_t *xmax){(void)op;*xmin=-2;*xmax=2;}
static uint16_t psx_read_half(uint32_t addr){(void)addr;return 17;}
static int psx_ws_prim_is_tagged(void){return 1;}
'''
            suffix='''
int main(void){
    ws_census_record(0x20,10,20);
    if(alloc_calls!=0||ws_census!=NULL||ws_census_seq!=0)return 1;
    gpu_ws_census_set(1);
    ws_census_record(0x20,30,40);
    if(alloc_calls!=1||ws_census==NULL||ws_census_seq!=1||ws_census[0].x!=30)return 2;
    gpu_ws_census_set(0);
    ws_census_record(0x20,50,60);
    if(alloc_calls!=1||ws_census_seq!=1)return 3;
    free(ws_census);
    return 0;
}
'''
            harness=target/'census_default_off_test.c'
            harness.write_text(prefix+declaration+'\n'+record+'\n'+setter+'\n'+suffix,encoding='utf-8')
            executable=target/'census_default_off_test.exe'
            compiled=subprocess.run([str(CLANG),'-std=c11',str(harness),'-o',str(executable)],
                                    capture_output=True,text=True,timeout=30)
            self.assertEqual(compiled.returncode,0,compiled.stderr)
            ran=subprocess.run([str(executable)],capture_output=True,text=True,timeout=10)
            self.assertEqual(ran.returncode,0,ran.stderr)


if __name__=='__main__':unittest.main()
