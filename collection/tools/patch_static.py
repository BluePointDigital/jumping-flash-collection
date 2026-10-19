"""Instrument real interpreter execution and compiler requests in private builds."""
from pathlib import Path
import re


def patch(framework):
    directory=Path(framework)/'runtime/src'
    def edit(name,anchor,replacement):
        path=directory/name;text=path.read_text(encoding='utf-8')
        if '// COLLECTION_STATIC_AUDIT_V1' in text:return
        if text.count(anchor)!=1:raise ValueError(f'Static-audit anchor changed: {name}')
        path.write_text('// COLLECTION_STATIC_AUDIT_V1\n#include "collection_static.h"\n'+
            text.replace(anchor,replacement,1),encoding='utf-8')
    anchor='    /* Force line-buffered output so messages appear even if killed. */'
    edit('main.cpp',anchor,'    collection_static_init();\n'+anchor)
    anchor='static int exec_one_fetched(CPUState *cpu, uint32_t pc, uint32_t insn,\n                            uint32_t *next_pc_out) {'
    edit('dirty_ram_interp.c',anchor,anchor+'\n    if(collection_static_mode)collection_static_interpreter(1,pc,insn,cpu->gpr[31],s_frame_count);')
    anchor='    uint32_t insn = cpu->read_word(pc);'
    edit('psx_interpreter.c',anchor,anchor+'\n    if(collection_static_mode)collection_static_interpreter(2,pc,insn,cpu->gpr[31],0);')
    anchor='    if (s_retry_not_before_ms &&\n        autocompile_now_ms() < s_retry_not_before_ms) return 0;'
    edit('autocompile.c',anchor,anchor+'\n    if(collection_static_mode)collection_static_compiler_request();')
    anchor='static int build_module(const BmToolchain *tk, const char *dump_path,\n                        const char *stem, const char *out_path,\n                        char *err, size_t err_cap) {'
    edit('psx_bios_module.c',anchor,anchor+'\n    if(collection_static_mode)collection_static_compiler_request();')
    anchor='static const CmdEntry s_commands[] = {'
    handler='''static void handle_collection_static(int id,const char *json){
    (void)json;char state[1024];
    if(!collection_static_json(state,sizeof(state))){send_err(id,"Static-audit snapshot overflow");return;}
    send_fmt("{\\"id\\":%d,\\"ok\\":true,%s}\\n",id,state);
}
'''
    edit('debug_server.c',anchor,handler+anchor+'\n    {"collection_static",handle_collection_static},')
    path=directory/'overlay_loader.c';text=path.read_text(encoding='utf-8')
    if '// COLLECTION_STATIC_LOADER_LOG_V1' not in text:
        anchor='    vsnprintf(s_last_msg, sizeof(s_last_msg), fmt, ap);\n    va_end(ap);'
        addition='''
    // COLLECTION_STATIC_LOADER_LOG_V1: explicit diagnostic, default silent.
    static int collection_loader_log=-1;
    if(collection_loader_log<0){const char *value=getenv("PSX_STATIC_LOADER_LOG");collection_loader_log=value&&value[0]=='1';}
    if(collection_loader_log)fprintf(stderr,"[Static loader] %s\\n",s_last_msg);'''
        if text.count(anchor)!=1:raise ValueError('Static loader log anchor changed')
        text=text.replace(anchor,anchor+addition,1)
        # Surface why a matching, indexed artifact was not admitted.
        anchor=r'\"loaded\":%d,\"crc\":'
        if text.count(anchor)!=1:raise ValueError('Lazy candidate diagnostic anchor changed')
        text=text.replace(anchor,r'\"loaded\":%d,\"load_failed\":%d,\"capacity_suppressed\":%d,\"crc\":',1)
        anchor='dll_already_loaded(s_cache_idx[ci].path), lm->fn.crc, live,'
        if text.count(anchor)!=1:raise ValueError('Lazy candidate diagnostic arguments changed')
        text=text.replace(anchor,'dll_already_loaded(s_cache_idx[ci].path), s_cache_idx[ci].load_failed, s_cache_idx[ci].capacity_suppressed, lm->fn.crc, live,',1)
        path.write_text(text,encoding='utf-8')
    patch_lazy_validation_diagnostics(directory/'overlay_loader.c')
    patch_cached_fallthrough(directory/'dirty_ram_interp.c')
    path=directory/'dirty_ram_interp.c';text=path.read_text(encoding='utf-8')
    if '// COLLECTION_STATIC_CONTEXT_V1' not in text:
        anchor='    if(collection_static_mode)collection_static_interpreter(1,pc,insn,cpu->gpr[31],s_frame_count);'
        replacement='''    if(collection_static_mode){
        // COLLECTION_STATIC_CONTEXT_V1: one bounded line before strict exit.
        if(collection_static_mode==2)fprintf(stderr,"PSX_STATIC_CONTEXT forced_span=%d precise=%d replay=%d\\n",
            span_forced(pc & 0x1fffffffu),g_precise_mode,g_ls_replay_active);
        collection_static_interpreter(1,pc,insn,cpu->gpr[31],s_frame_count);
    }'''
        if text.count(anchor)!=1:raise ValueError('Static interpreter context anchor changed')
        path.write_text(text.replace(anchor,replacement,1),encoding='utf-8')
    patch_strict_context(directory)
    patch_rejected_continuation(directory/'overlay_loader.c')
    patch_stale_exact_continuation(directory/'overlay_loader.c')
    patch_first_miss_capture(directory/'dirty_ram_interp.c')
    patch_boot_watch_reset(directory)
    patch_strict_static_requirement(Path(framework)/'runtime/runtime.cmake')


def patch_strict_static_requirement(path):
    """Make static overlay presence mandatory only for opted-in builds."""
    path=Path(path);text=path.read_text(encoding='utf-8')
    marker='# COLLECTION_REQUIRE_STATIC_OVERLAYS_V1'
    anchor='''    psxrecomp_overlay_static_sources(_ov_static_sources _ov_static_present
        TARGET      "${target}"
        STATIC_C    "${PSXRT_GAME_OVERLAY_STATIC_C}"
        PROFILE     "${CMAKE_CURRENT_SOURCE_DIR}/aot/overlays.json"
        GAME_LINKED ${_ov_static_game_linked})'''
    replacement='''    # COLLECTION_REQUIRE_STATIC_OVERLAYS_V1
    option(COLLECTION_REQUIRE_STATIC_OVERLAYS
        "Fail configure if a declared static overlay dispatcher is missing" OFF)
'''+anchor+'''
    if(COLLECTION_REQUIRE_STATIC_OVERLAYS AND NOT _ov_static_present)
        message(FATAL_ERROR
            "${target}: COLLECTION_REQUIRE_STATIC_OVERLAYS=ON but no static "
            "overlay dispatcher is present. Generate and audit the files named "
            "by GAME_OVERLAY_STATIC_C before configuring this release target.")
    endif()'''
    if marker in text:
        if text.count(marker)!=1 or text.count(replacement)!=1:
            raise ValueError('Strict static-overlay marker is inconsistent')
        return False
    if text.count(anchor)!=1:
        raise ValueError('Strict static-overlay call anchor changed')
    path.write_text(text.replace(anchor,replacement,1),encoding='utf-8',newline='')
    return True


def patch_stale_exact_continuation(path):
    """An invalid historical exact entry must not hide a loaded CPS caller."""
    path=Path(path);text=path.read_text(encoding='utf-8')
    if '// COLLECTION_STALE_EXACT_CONTINUATION_V1' in text:return
    start=text.index('static int overlay_loader_dispatch_seg(CPUState *cpu, uint32_t addr) {')
    end=text.index('\n/* ---- Self-modification',start)
    body=text[start:end]
    replacements={
        '    int lazy_loaded = 0;':'    int lazy_loaded = 0;\n    int collection_range_after_exact_miss = 0; // COLLECTION_STALE_EXACT_CONTINUATION_V1',
        'if (head < 0 && s_active && overlay_cache_window_contains(phys)) {':'if ((head < 0 || collection_range_after_exact_miss) && s_active && overlay_cache_window_contains(phys)) {',
        'lazy_exact = head < 0 && lazy_has_exact_entry(seg, phys);':'lazy_exact = lazy_has_exact_entry(seg, phys);',
        'if (head < 0 && g_psx_cps_mode)':'if ((head < 0 || collection_range_after_exact_miss) && g_psx_cps_mode)',
        'if (head < 0 && (loaded_range_ci < 0 || exact_needs_load) &&':'if ((head < 0 || collection_range_after_exact_miss) && (loaded_range_ci < 0 || exact_needs_load) &&',
    }
    for old,new in replacements.items():
        expected=2 if old=='if (head < 0 && g_psx_cps_mode)' else 1
        if body.count(old)!=expected:raise ValueError(f'Stale exact continuation anchor changed: {old}')
        body=body.replace(old,new)
    body=re.sub(r'\blazy_loaded\s*=\s*1;',
        'lazy_loaded = 1; collection_range_after_exact_miss = 0;',body)
    anchor='    /* Publish at most one cached DLL and retry this same dispatch once. This'
    retry='''    // COLLECTION_STALE_EXACT_RETRY_V1
    /* Exact candidates have all failed their existing gates. Reuse the normal
     * loaded-caller path once, preserving its CRC/slot/entry-switch checks. */
    if (!collection_range_after_exact_miss && head >= 0 && g_psx_cps_mode &&
        !s_in_shadow && overlay_cache_window_contains(phys) &&
        overlay_find_by_range(seg, phys) >= 0) {
        collection_range_after_exact_miss = 1;
        goto retry_candidates;
    }
    // COLLECTION_STALE_EXACT_RETRY_END

'''
    if body.count(anchor)!=1:raise ValueError('Exact continuation retry anchor changed')
    body=body.replace(anchor,retry+anchor,1)
    path.write_text(text[:start]+body+text[end:],encoding='utf-8')


def patch_boot_watch_reset(directory):
    directory=Path(directory)
    path=directory/'overlay_loader.c';text=path.read_text(encoding='utf-8')
    if '// COLLECTION_BOOT_WATCH_RESET_V1' not in text:
        text+='''
// COLLECTION_BOOT_WATCH_RESET_V1
/* The loader can preload before memory_init clears page watches/generations.
 * Re-arm every registered/lazy guard after reset, including initially invalid
 * BIOS stubs. Preserve safety blacklists; no candidate is blessed here. */
void collection_overlay_rearm_after_memory_reset(void) {
    if(!s_active)return;
    for(int i=0;i<s_cand_n;i++){
        Candidate *c=&s_cand[i];
        ov_ranges_watch(c->range_lo,c->range_len,c->nranges);
        c->val_gen=0xffffffffu;
    }
    for(int i=0;i<s_lazy_man_n;i++){
        LazyMan *lm=&s_lazy_man[i];
        ov_ranges_watch(lm->fn.lo,lm->fn.len,lm->fn.n);
        lm->state=0xff;lm->val_gen=0;
    }
    overlay_loader_clear_lazy_miss();
}
'''
        path.write_text(text,encoding='utf-8')
    path=directory/'memory.c';text=path.read_text(encoding='utf-8')
    if '// COLLECTION_BOOT_WATCH_RESET_V1' in text:return
    start=text.index('void dirty_ram_reset_for_boot(void) {')
    end=text.index('\n}',start)
    addition='''
    // COLLECTION_BOOT_WATCH_RESET_V1
    extern void collection_overlay_rearm_after_memory_reset(void);
    collection_overlay_rearm_after_memory_reset();'''
    path.write_text(text[:end]+addition+text[end:],encoding='utf-8')


def patch_first_miss_capture(path):
    path=Path(path);text=path.read_text(encoding='utf-8')
    if '// COLLECTION_FIRST_MISS_CAPTURE_V1' in text:return
    anchor='        collection_static_interpreter(1,pc,insn,cpu->gpr[31],s_frame_count);'
    replacement='''        // COLLECTION_FIRST_MISS_CAPTURE_V1
        if(collection_static_interpreter(1,pc,insn,cpu->gpr[31],s_frame_count)){
            /* Capture this short-lived identity before a CPU decompressor can
             * overwrite it between periodic samples. Diagnostic mode only;
             * the ordinary decoder records this same execution bitmap bit. */
            extern void overlay_capture_write_json(void);
            exec_pc_table_record(pc);
            overlay_capture_write_json();
        }'''
    if text.count(anchor)!=1:raise ValueError('First-miss capture anchor changed')
    path.write_text(text.replace(anchor,replacement,1),encoding='utf-8')


def patch_rejected_continuation(path):
    path=Path(path);text=path.read_text(encoding='utf-8')
    old_retry='if (!lazy_loaded && lazy_exact && try_load_region(seg, phys)) {'
    safe_retry='if (!s_in_shadow && cpu->pc == addr && !lazy_loaded && lazy_exact && try_load_region(seg, phys)) {'
    if '// COLLECTION_REJECTED_CONTINUATION_V1' in text:
        if text.count(old_retry)==1:text=text.replace(old_retry,safe_retry,1)
        if text.count(safe_retry)!=1:raise ValueError('Rejected continuation safety gates changed')
        path.write_text(text,encoding='utf-8');return
    anchor='''                    s_disp_native--; s_disp_interp++;
                    return 0;            /* cpu->pc was restored to the requested PC */'''
    replacement='''                    s_disp_native--;
                    // COLLECTION_REJECTED_CONTINUATION_V1
                    /* Byte-range ownership does not prove a legal CPS resume
                     * label. The rejected call ran no guest instructions; try
                     * the exact guarded fragment before interpreting it. */
                    if (!s_in_shadow && cpu->pc == addr && !lazy_loaded && lazy_exact && try_load_region(seg, phys)) {
                        lazy_loaded = 1;
                        goto retry_candidates;
                    }
                    s_disp_interp++;
                    return 0;            /* cpu->pc was restored to the requested PC */'''
    if text.count(anchor)!=1:raise ValueError('Rejected CPS continuation anchor changed')
    path.write_text(text.replace(anchor,replacement,1),encoding='utf-8')


def patch_strict_context(directory):
    directory=Path(directory)
    path=directory/'overlay_loader.c';text=path.read_text(encoding='utf-8')
    if '// COLLECTION_STRICT_ADMISSION_CONTEXT_V1' not in text:
        text+='''
// COLLECTION_STRICT_ADMISSION_CONTEXT_V1
/* Snapshot the first strict miss before scene changes erase its live identity.
 * Only read validators are used: diagnostic queries must not admit a shard. */
void collection_static_admission_context(uint32_t addr) {
    uint32_t phys=addr & 0x1fffffffu,seg=addr & 0xe0000000u;
    fprintf(stderr,"PSX_STATIC_ADMISSION pc=%08X active=%d window=%d head=%d cps=%d native=%d loads_allowed=%d miss_cached=%d exact=%d\\n",
        addr,s_active,overlay_cache_window_contains(phys),s_active?idx_head_seg(phys,seg):-1,
        g_psx_cps_mode,s_native_exec,overlay_loads_allowed(),s_active?lazy_miss_cached(addr):0,
        s_active?lazy_has_exact_entry(seg,phys):0);
    if(s_active){
        char out[16384];
        overlay_loader_dump_candidates_at(addr,out,sizeof(out));
        fprintf(stderr,"PSX_STATIC_LOADED %s\\n",out);
        overlay_loader_dump_lazy_at(addr,out,sizeof(out));
        fprintf(stderr,"PSX_STATIC_INDEXED %s\\n",out);
    }
}
'''
        path.write_text(text,encoding='utf-8')
    path=directory/'dirty_ram_interp.c';text=path.read_text(encoding='utf-8')
    if '// COLLECTION_STRICT_ADMISSION_CONTEXT_V1' not in text:
        anchor='''        if(collection_static_mode==2)fprintf(stderr,"PSX_STATIC_CONTEXT forced_span=%d precise=%d replay=%d\\n",
            span_forced(pc & 0x1fffffffu),g_precise_mode,g_ls_replay_active);'''
        replacement='''        // COLLECTION_STRICT_ADMISSION_CONTEXT_V1
        if(collection_static_mode==2){
            extern void collection_static_admission_context(uint32_t);
            fprintf(stderr,"PSX_STATIC_CONTEXT forced_span=%d precise=%d replay=%d pending_load=%d cpu_pc=%08X\\n",
                span_forced(pc & 0x1fffffffu),g_precise_mode,g_ls_replay_active,s_ld_pend_armed,cpu->pc);
            collection_static_admission_context(pc);
        }'''
        if text.count(anchor)!=1:raise ValueError('Strict admission context anchor changed')
        path.write_text(text.replace(anchor,replacement,1),encoding='utf-8')


def patch_lazy_validation_diagnostics(path):
    path=Path(path);text=path.read_text(encoding='utf-8')
    if '// COLLECTION_LAZY_VALIDATION_DIAGNOSTICS_V1' in text:return
    old=r'\"loaded\":%d,\"load_failed\":%d,\"capacity_suppressed\":%d,\"crc\":'
    new=r'\"loaded\":%d,\"load_failed\":%d,\"capacity_suppressed\":%d,\"state\":%d,\"val_gen\":%u,\"gen\":%u,\"slots_ok\":%d,\"miss_cached\":%d,\"crc\":'
    old_args='s_cache_idx[ci].capacity_suppressed, lm->fn.crc, live,'
    new_args='s_cache_idx[ci].capacity_suppressed, lm->state, lm->val_gen, lazy_man_gensum(&lm->fn), man_delay_slots_hashed(&lm->fn), lazy_miss_cached(addr), lm->fn.crc, live,'
    guard='li >= 0 && n < cap - 320;'
    if text.count(old)!=1 or text.count(old_args)!=1 or text.count(guard)!=1:raise ValueError('Lazy validation diagnostics anchors changed')
    text=text.replace(old,new,1).replace(old_args,new_args,1).replace(guard,'li >= 0 && n < cap - 512;',1)
    path.write_text('// COLLECTION_LAZY_VALIDATION_DIAGNOSTICS_V1\n'+text,encoding='utf-8')


def patch_cached_fallthrough(path):
    path=Path(path);text=path.read_text(encoding='utf-8')
    if '// COLLECTION_CACHED_FALLTHROUGH_V1' in text:return
    anchor='    for (int i = 0; i < MAX_INSNS_PER_DISPATCH; i++) {\n        uint32_t next_pc = 0;'
    replacement='''    for (int i = 0; i < MAX_INSNS_PER_DISPATCH; i++) {
        // COLLECTION_CACHED_FALLTHROUGH_V1
        /* A syscall can resume at a cached continuation by straight-line flow.
         * Surface it to the normal guarded dispatcher, without nesting native
         * execution or draining an owed load-delay writeback. On a guard miss
         * the next invocation still executes its first instruction (i == 0). */
        if (i > 0 && !forced && !g_precise_mode && !g_ls_replay_active &&
            !s_ld_pend_armed && !span_forced(pc & 0x1fffffffu) &&
            overlay_loader_is_candidate(pc & 0x1fffffffu)) {
            cpu->pc = pc;
            g_dirty_ram_blocks_run++;
            if (pc_entry) pc_entry->insns += (uint64_t)insns_executed;
            g_dirty_interp_chain_target = pc;
            OV_FPLOG_RET1();
        }
        uint32_t next_pc = 0;'''
    if text.count(anchor)!=1:raise ValueError('Cached fallthrough handoff anchor changed')
    path.write_text(text.replace(anchor,replacement,1),encoding='utf-8')


