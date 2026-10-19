from pathlib import Path
import subprocess,sys,tempfile,unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from patch_static import patch
from patch_static import patch_cached_fallthrough,patch_rejected_continuation,patch_first_miss_capture,patch_boot_watch_reset,patch_stale_exact_continuation
from prepare_runtimes import PROJECTS

class StaticPatchTests(unittest.TestCase):
    def test_stale_exact_chain_retries_valid_loaded_caller_once(self):
        compiler=ROOT.parent/'.jf2-workbench/recomp/toolchain/bin/clang.exe'
        if not compiler.is_file():self.skipTest('Local native compiler unavailable')
        with tempfile.TemporaryDirectory() as temp:
            directory=Path(temp);source=directory/'test.c'
            source.write_bytes((PROJECTS['jf1'][0]/'psxrecomp/runtime/src/overlay_loader.c').read_bytes())
            patch_rejected_continuation(source)
            patch_stale_exact_continuation(source);text=source.read_text(encoding='utf-8')
            patch_stale_exact_continuation(source);self.assertEqual(text,source.read_text(encoding='utf-8'))
            state=next(line for line in text.splitlines() if '// COLLECTION_STALE_EXACT_CONTINUATION_V1' in line)
            line=next(line.strip() for line in text.splitlines() if line.strip().startswith('if ((head < 0 || collection_range_after_exact_miss)') and line.strip().endswith('g_psx_cps_mode) {'))
            condition=line[4:-3]
            retry=text.split('// COLLECTION_STALE_EXACT_RETRY_V1',1)[1].split('// COLLECTION_STALE_EXACT_RETRY_END',1)[0]
            self.assertGreaterEqual(text.count('lazy_loaded = 1; collection_range_after_exact_miss = 0;'),3)
            fixture='''#include <assert.h>
#include <stdint.h>
static int g_psx_cps_mode=1,s_in_shadow,window=1,range_valid=1,entry_allowed=1;
static int lookups,native_calls,exact_calls,steps;
static int overlay_cache_window_contains(uint32_t phys){assert(phys==0xcfac0);return window;}
static int overlay_find_by_range(uint32_t seg,uint32_t phys){assert(seg==0x80000000&&phys==0xcfac0);lookups++;return range_valid?5:-1;}
static int run(int head,int exact_valid){
 uint32_t seg=0x80000000u,phys=0xcfac0u;
'''+state+'''
retry_candidates:
 assert(++steps<=2);
 if ('''+condition+''') {
  if(overlay_find_by_range(seg,phys)>=0){native_calls++;return entry_allowed?1:0;}
 }
 if(exact_valid){exact_calls++;return 2;}
'''+retry+'''
 return 0;
}
static void reset(void){lookups=native_calls=exact_calls=steps=0;}
int main(void){
 assert(run(0,1)==2&&exact_calls==1&&!lookups);reset();
 assert(run(0,0)==1&&native_calls==1&&steps==2&&lookups==2);reset();
 entry_allowed=0;assert(run(0,0)==0&&native_calls==1&&steps==2);entry_allowed=1;reset();
 range_valid=0;assert(!run(0,0)&&!native_calls&&steps==1);range_valid=1;reset();
 g_psx_cps_mode=0;assert(!run(0,0)&&!lookups);g_psx_cps_mode=1;reset();
 s_in_shadow=1;assert(!run(0,0)&&!lookups);s_in_shadow=0;reset();
 window=0;assert(!run(0,0)&&!lookups);window=1;reset();
 assert(run(-1,0)==1&&native_calls==1&&steps==1);return 0;
}'''
            source.write_text(fixture,encoding='utf-8');executable=directory/'test.exe'
            subprocess.run([str(compiler),str(source),'-O2','-static','-o',str(executable)],check=True,capture_output=True)
            subprocess.run([str(executable)],check=True,timeout=10)

    def test_boot_reset_rearms_preloaded_and_lazy_guards_without_blessing(self):
        compiler=ROOT.parent/'.jf2-workbench/recomp/toolchain/bin/clang.exe'
        if not compiler.is_file():self.skipTest('Local native compiler unavailable')
        with tempfile.TemporaryDirectory() as temp:
            directory=Path(temp)
            original=PROJECTS['jf1'][0]/'psxrecomp/runtime/src'
            for name in ['overlay_loader.c','memory.c']:(directory/name).write_bytes((original/name).read_bytes())
            patch_boot_watch_reset(directory)
            loader=(directory/'overlay_loader.c').read_text(encoding='utf-8')
            helper=loader.split('void collection_overlay_rearm_after_memory_reset(void)',1)[1]
            memory=(directory/'memory.c').read_text(encoding='utf-8')
            reset=memory.split('void dirty_ram_reset_for_boot(void)',1)[1].split('\n}',1)[0]+'\n}'
            fixture='''#include <assert.h>
#include <stdint.h>
#include <string.h>
#define DIRTY_RAM_EXEC_BITMAP_WORDS 1
static uint32_t dirty_ram_bitmap[1],text_modified_bitmap[1],text_diverged_bitmap[1];
static uint32_t overlay_watch_bitmap[1],overlay_page_gen[1];
static uint32_t g_dirty_ram_exec_page_bitmap[1],g_dirty_ram_exec_pc_bitmap[1];
static uint32_t g_text_diverged_pages,g_dirty_ram_code_gen;
static int s_active=1,s_cand_n=2,s_lazy_man_n=1,cleared;
typedef struct {uint32_t range_lo[1],range_len[1],val_gen;int nranges,state;} Candidate;
typedef struct {struct {uint32_t lo[1],len[1];int n;} fn;uint32_t val_gen;int state;} LazyMan;
static Candidate s_cand[2]={{{0xcf0},{16},0,1,1},{{0x1000},{16},0,1,2}};
static LazyMan s_lazy_man[1]={{.fn={.lo={0x2000},.len={16},.n=1},.val_gen=99,.state=1}};
static void ov_ranges_watch(const uint32_t *lo,const uint32_t *len,int n){
 assert(n==1&&len[0]==16);overlay_watch_bitmap[0]|=1u<<(lo[0]>>12);
}
static void overlay_loader_clear_lazy_miss(void){cleared++;}
static void dirty_ram_dispatch_evidence_clear(unsigned first,unsigned count){assert(first==0&&count==1);}
void collection_overlay_rearm_after_memory_reset(void)'''+helper+'''
void dirty_ram_reset_for_boot(void)'''+reset+'''
int main(void){
 overlay_watch_bitmap[0]=255;overlay_page_gen[0]=9;
 dirty_ram_reset_for_boot();
 assert(overlay_page_gen[0]==0&&overlay_watch_bitmap[0]==7&&cleared==1);
 assert(s_cand[0].val_gen!=0&&s_cand[0].state==1);
 assert(s_cand[1].val_gen!=0&&s_cand[1].state==2);
 assert(s_lazy_man[0].state==255&&s_lazy_man[0].val_gen==0);
 if(overlay_watch_bitmap[0]&1)overlay_page_gen[0]++;
 assert(overlay_page_gen[0]==1);
 s_active=0;dirty_ram_reset_for_boot();assert(!overlay_watch_bitmap[0]&&cleared==1);
 return 0;
}'''
            source=directory/'test.c';source.write_text(fixture,encoding='utf-8');executable=directory/'test.exe'
            subprocess.run([str(compiler),str(source),'-O2','-static','-o',str(executable)],check=True,capture_output=True)
            subprocess.run([str(executable)],check=True,timeout=10)
    def test_first_miss_capture_records_execution_before_snapshot_once(self):
        compiler=ROOT.parent/'.jf2-workbench/recomp/toolchain/bin/clang.exe'
        if not compiler.is_file():self.skipTest('Local native compiler unavailable')
        with tempfile.TemporaryDirectory() as temp:
            directory=Path(temp);source=directory/'test.c'
            source.write_text('        collection_static_interpreter(1,pc,insn,cpu->gpr[31],s_frame_count);',encoding='utf-8')
            patch_first_miss_capture(source);body=source.read_text(encoding='utf-8')
            patch_first_miss_capture(source);self.assertEqual(body,source.read_text(encoding='utf-8'))
            fixture='''#include <assert.h>
#include <stdint.h>
static int attempts,noted,captures;
static uint64_t s_frame_count=22;
static int collection_static_interpreter(int backend,uint32_t pc,uint32_t insn,uint32_t ra,uint64_t frame){
 assert(backend==1&&pc==0x800e447c&&insn==0x0c039b40&&ra==pc&&frame==22);
 return ++attempts==1;
}
static void exec_pc_table_record(uint32_t pc){assert(pc==0x800e447c);noted++;}
void overlay_capture_write_json(void){assert(noted==1);captures++;}
static void run(void){
 struct {uint32_t gpr[32];} state={{0}},*cpu=&state;
 uint32_t pc=0x800e447c,insn=0x0c039b40;cpu->gpr[31]=pc;
'''+body+'''
}
int main(void){run();run();assert(attempts==2&&noted==1&&captures==1);return 0;}
'''
            source.write_text(fixture,encoding='utf-8');executable=directory/'test.exe'
            subprocess.run([str(compiler),str(source),'-O2','-static','-o',str(executable)],check=True,capture_output=True)
            subprocess.run([str(executable)],check=True,timeout=10)

    def test_rejected_owner_tries_exact_fragment_once_and_keeps_failure_closed(self):
        compiler=ROOT.parent/'.jf2-workbench/recomp/toolchain/bin/clang.exe'
        if not compiler.is_file():self.skipTest('Local native compiler unavailable')
        with tempfile.TemporaryDirectory() as temp:
            directory=Path(temp);source=directory/'test.c'
            source.write_bytes((PROJECTS['jf1'][0]/'psxrecomp/runtime/src/overlay_loader.c').read_bytes())
            patch_rejected_continuation(source)
            body=source.read_text(encoding='utf-8').split('// COLLECTION_REJECTED_CONTINUATION_V1',1)[1].split('                    return 0;',1)[0]
            fixture='''#include <assert.h>
#include <stdint.h>
static int attempts,admitted,s_disp_interp,s_in_shadow,pc_changed;
static int try_load_region(uint32_t seg,uint32_t phys){
 assert(seg==0x80000000u&&phys==0xe7f7cu);attempts++;return admitted;
}
static int run(int lazy_loaded,int lazy_exact){
 int collection_range_after_exact_miss=0;
 uint32_t seg=0x80000000u,phys=0xe7f7cu;
 uint32_t addr=seg|phys;
 struct {uint32_t pc;} state={addr+pc_changed*4},*cpu=&state;
retry_candidates:
'''+body+'''
 return lazy_loaded;
}
int main(void){
 admitted=1;assert(run(0,1)==1);assert(attempts==1&&s_disp_interp==1);
 attempts=0;s_disp_interp=0;admitted=0;
 assert(run(0,1)==0);assert(attempts==1&&s_disp_interp==1);
 attempts=0;s_disp_interp=0;assert(run(0,0)==0);assert(!attempts&&s_disp_interp==1);
 s_disp_interp=0;assert(run(1,1)==1);assert(!attempts&&s_disp_interp==1);
 s_in_shadow=1;s_disp_interp=0;assert(run(0,1)==0);assert(!attempts&&s_disp_interp==1);
 s_in_shadow=0;pc_changed=1;s_disp_interp=0;assert(run(0,1)==0);assert(!attempts&&s_disp_interp==1);
 return 0;
}'''
            source.write_text(fixture,encoding='utf-8');executable=directory/'test.exe'
            subprocess.run([str(compiler),str(source),'-O2','-static','-o',str(executable)],check=True,capture_output=True)
            subprocess.run([str(executable)],check=True,timeout=10)
    def test_fallthrough_handoff_preserves_forced_modes_and_load_delay(self):
        compiler=ROOT.parent/'.jf2-workbench/recomp/toolchain/bin/clang.exe'
        if not compiler.is_file():self.skipTest('Local native compiler unavailable')
        with tempfile.TemporaryDirectory() as temp:
            directory=Path(temp);source=directory/'test.c'
            source.write_bytes((PROJECTS['jf1'][0]/'psxrecomp/runtime/src/dirty_ram_interp.c').read_bytes())
            patch_cached_fallthrough(source)
            body=source.read_text(encoding='utf-8').split('// COLLECTION_CACHED_FALLTHROUGH_V1',1)[1].split('        uint32_t next_pc = 0;',1)[0]
            fixture='''#include <assert.h>
#include <stdint.h>
static int g_precise_mode,g_ls_replay_active,s_ld_pend_armed,span,candidate;
static uint64_t g_dirty_ram_blocks_run;
static uint32_t g_dirty_interp_chain_target;
static int span_forced(uint32_t pc){(void)pc;return span;}
static int overlay_loader_is_candidate(uint32_t pc){(void)pc;return candidate;}
#define OV_FPLOG_RET1() return 1
static int run(int i,int forced){
 struct {uint32_t pc;} state={0},*cpu=&state;
 struct {uint64_t insns;} entry={0},*pc_entry=&entry;
 uint32_t pc=0x800e7f7c;int insns_executed=3;
'''+body+'''
 return 0;
}
int main(void){
 candidate=1;assert(!run(0,0));assert(run(1,0));
 assert(g_dirty_interp_chain_target==0x800e7f7c&&g_dirty_ram_blocks_run==1);
 assert(!run(1,1));g_precise_mode=1;assert(!run(1,0));g_precise_mode=0;
 g_ls_replay_active=1;assert(!run(1,0));g_ls_replay_active=0;
 s_ld_pend_armed=1;assert(!run(1,0));assert(s_ld_pend_armed==1);s_ld_pend_armed=0;
 span=1;assert(!run(1,0));span=0;candidate=0;assert(!run(1,0));
 assert(g_dirty_ram_blocks_run==1);return 0;
}'''
            source.write_text(fixture,encoding='utf-8');executable=directory/'test.exe'
            subprocess.run([str(compiler),str(source),'-O2','-static','-o',str(executable)],check=True,capture_output=True)
            subprocess.run([str(executable)],check=True,timeout=10)
    def test_real_title_sources_idempotent_and_changed_anchor_rejected(self):
        names=('main.cpp','memory.c','dirty_ram_interp.c','psx_interpreter.c','autocompile.c','psx_bios_module.c','debug_server.c','overlay_loader.c')
        for game,(source,_) in PROJECTS.items():
            with self.subTest(game=game),tempfile.TemporaryDirectory() as temp:
                root=Path(temp);out=root/'runtime/src';out.mkdir(parents=True)
                for name in names:(out/name).write_bytes((source/'psxrecomp/runtime/src'/name).read_bytes())
                cmake=root/'runtime/runtime.cmake'
                cmake.write_bytes((source/'psxrecomp/runtime/runtime.cmake').read_bytes())
                patch(root);before={name:(out/name).read_bytes() for name in names}
                cmake_before=cmake.read_bytes()
                patch(root);self.assertEqual(before,{name:(out/name).read_bytes() for name in names})
                self.assertEqual(cmake_before,cmake.read_bytes())
                self.assertIn(b'COLLECTION_REQUIRE_STATIC_OVERLAYS_V1',cmake_before)
                self.assertIn(b'collection_static_interpreter(1,pc,insn',before['dirty_ram_interp.c'])
                self.assertIn(b'COLLECTION_CACHED_FALLTHROUGH_V1',before['dirty_ram_interp.c'])
                self.assertIn(b'!s_ld_pend_armed && !span_forced',before['dirty_ram_interp.c'])
                self.assertIn(b'collection_static_interpreter(2,pc,insn',before['psx_interpreter.c'])
                self.assertIn(b'collection_static_compiler_request()',before['autocompile.c'])
                self.assertIn(b'collection_static_compiler_request()',before['psx_bios_module.c'])
                self.assertIn(b'"collection_static"',before['debug_server.c'])
                self.assertIn(b'PSX_STATIC_LOADER_LOG',before['overlay_loader.c'])
                self.assertIn(b'COLLECTION_REJECTED_CONTINUATION_V1',before['overlay_loader.c'])
                self.assertIn(b'collection_static_admission_context(pc)',before['dirty_ram_interp.c'])
                self.assertIn(b'COLLECTION_FIRST_MISS_CAPTURE_V1',before['dirty_ram_interp.c'])
                self.assertIn(b'load_failed\\\":%d',before['overlay_loader.c'])
                self.assertIn(b'lazy_miss_cached(addr)',before['overlay_loader.c'])
                (out/'autocompile.c').write_text('/* unexpected upstream layout */',encoding='utf-8')
                with self.assertRaises(ValueError):patch(root)

if __name__=='__main__':unittest.main()
