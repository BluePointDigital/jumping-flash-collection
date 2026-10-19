"""Reproducible collection-only performance defaults; no overlay ABI changes."""
from pathlib import Path
from patch_diagnostics import (patch_range_serializer, patch_ambient_memory_trace,
    patch_automatic_freeze_dumps, patch_batch_diagnostic, patch_gte_diagnostics,
    patch_sreg_trace_fastpath, patch_host_image_base)


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise ValueError(f'Performance patch anchor changed: {old[:100]}')
    return text.replace(old, new, 1)


def patch(framework):
    framework=Path(framework)
    patch_range_serializer(framework)
    patch_ambient_memory_trace(framework)
    patch_automatic_freeze_dumps(framework)
    patch_batch_diagnostic(framework)
    patch_gte_diagnostics(framework)
    patch_sreg_trace_fastpath(framework)
    patch_host_image_base(framework)
    def edit(name,marker,transform):
        path=framework/'runtime/src'/name
        text=path.read_text(encoding='utf-8')
        if marker in text:return
        text=transform(text)
        path.write_text('// '+marker+'\n#include "collection_diagnostics.h"\n#include "collection_metrics.h"\n'+text,encoding='utf-8')

    def debug(text):
        text=text.replace('#ifdef JF2_DESKTOP\n        /* Per-frame GL readbacks',
                          '#if defined(JF2_DESKTOP) || defined(ROBBIT_DESKTOP)\n        /* Per-frame GL readbacks')
        text=replace_once(text,'#if defined(JF2_DESKTOP) || defined(ROBBIT_DESKTOP)\n        /* Per-frame GL readbacks',
            '#if defined(COLLECTION_RUNTIME)\n        enabled=collection_diagnostic_enabled("PSX_DISPLAY_RING");\n'
            '#elif defined(JF2_DESKTOP) || defined(ROBBIT_DESKTOP)\n        /* Per-frame GL readbacks')
        text=replace_once(text,'static void phase_sampler_start(void)\n{',
            'static void phase_sampler_start(void)\n{\n    if(!collection_diagnostic_enabled("PSX_PHASE_SAMPLER"))return;')
        handler='''static void handle_collection_perf(int id,const char *json){
    char state[32768];
    int after=json_get_int(json,"after",0);
    if(!collection_metrics_json(state,sizeof(state),after<0?0:(uint64_t)after)){
        send_err(id,"collection metric snapshot exceeded buffer");return;
    }
    send_fmt("{\\"id\\":%d,\\"ok\\":true,%s}\\n",id,state);
}
'''
        text=replace_once(text,'static const CmdEntry s_commands[] = {',
            handler+'static const CmdEntry s_commands[] = {\n    {"collection_perf",handle_collection_perf},')
        return text
    edit('debug_server.c','COLLECTION_PERF_DEBUG_V1',debug)

    path=framework/'runtime/src/gpu.c'
    text=path.read_text(encoding='utf-8')
    if 'COLLECTION_PERF_CENSUS_DEFAULT_OFF_V1' not in text:
        text=replace_once(text,
            'static int            ws_census_on  = 1;     /* always-on; toggle via ws_census */',
            'static int            ws_census_on  = 0;     /* opt-in; toggle via ws_census */')
        path.write_text('// COLLECTION_PERF_CENSUS_DEFAULT_OFF_V1\n'+text,encoding='utf-8')

    edit('present_image_ring.c','COLLECTION_PERF_IMAGE_RING_V1',lambda t:replace_once(t,
        "s_enabled = (!e || !*e || *e != '0') ? 1 : 0;",
        's_enabled = collection_diagnostic_enabled("PSX_PRESENT_IMAGE_RING");'))

    def renderer(text):
        text=replace_once(text,"if (enabled && enabled[0] == '0') return;",
            'if (!collection_diagnostic_enabled("PSX_GL_PERF")) return;')
        text=replace_once(text,'    gl_present_swap();\n    if (rthf_t0)',
            '    gl_present_swap();\n    collection_metrics_swap(generated);\n    if (rthf_t0)')
        return text
    edit('gpu_gl_renderer.c','COLLECTION_PERF_RENDER_V1',renderer)

    def main(text):
        text=replace_once(text,'    debug_server_record_frame();',
            '    collection_metrics_guest_tick(s_frame_count);\n    debug_server_record_frame();')
        text=text.replace('fps=%.1f avg_fps=%.1f ', 'guest_hz=%.1f avg_guest_hz=%.1f ')
        text=text.replace('emu_busy=%.1f%% render_busy=%.1f%% dynres=',
                          'emu_nonwait_wall=%.1f%% render_replay_wall=%.1f%% dynres=')
        text=text.replace('gen_fps=%.1f real_fps=%.1f', 'generated_hz=%.1f fg_real_path_hz=%.1f')
        return text
    edit('main.cpp','COLLECTION_PERF_MAIN_V1',main)
    path=framework/'runtime/src/main.cpp'
    text=path.read_text(encoding='utf-8')
    if 'COLLECTION_PERF_LIVE_TOGGLES_V1' not in text:
        begin=text.index('static int debug_toggles_on(void) {')
        end=text.index('\n}',begin)+2
        text=text[:begin]+'''// COLLECTION_PERF_LIVE_TOGGLES_V1
static int debug_toggles_on(void) {
    static int enabled=-1;
    if(enabled<0)enabled=collection_diagnostic_enabled("PSX_DEBUG_TOGGLES");
    return enabled;
}'''+text[end:]
        path.write_text(text,encoding='utf-8')
    if 'COLLECTION_PERF_SETTINGS_V1' not in text:
        getter='''// COLLECTION_PERF_SETTINGS_V1
extern "C" int collection_settings_json(char *out,int capacity){
    int w=0,h=0;if(sdl_window)SDL_GetWindowSizeInPixels(sdl_window,&w,&h);
    GlDynresStats ds{};gl_renderer_dynres_stats(&ds);
    return std::snprintf(out,capacity,
        "\\"effective_settings\\":{\\"deck_profile\\":%s,\\"internal_resolution\\":%d,\\"render_scale\\":%d,"
        "\\"reference_lines\\":%d,\\"output_width\\":%d,\\"output_height\\":%d,"
        "\\"active_scale\\":%d,\\"scale_ceiling\\":%d,"
        "\\"compiler_workers\\":%d,\\"render_thread_requested\\":%d,\\"render_thread_running\\":%d,"
        "\\"frame_generation\\":%d,\\"temporal_interpolation\\":%d,\\"swap_interval\\":%d,"
        "\\"guest_period_ms\\":%.6f,\\"renderer\\":\\"%s\\"}",
        collection_deck?"true":"false",effective_internal_resolution(),g_video_scale,g_video_ref_lines,w,h,ds.level,ds.ceiling,
        collection_deck?1:2,g_render_thread,rt_running(),g_frame_generation,g_frame_interpolation,
        present_effective_swap_interval(),g_guest_frame_period_ms,g_gl_active?"opengl":g_vk_active?"vulkan":"software");
}
'''
        text=replace_once(text,'static void frame_report_tick(uint64_t frames) {',getter+'static void frame_report_tick(uint64_t frames) {')
        path.write_text(text,encoding='utf-8')
    # Upgrade already-prepared candidates without touching the original settings receipt.
    text=path.read_text(encoding='utf-8')
    if 'COLLECTION_PERF_SETTINGS_SCALE_V2' not in text:
        if 'GlDynresStats ds{};gl_renderer_dynres_stats(&ds);' not in text:
            begin=text.index('extern "C" int collection_settings_json(')
            end=text.index('\n}',begin)+2
            block=text[begin:end]
            block=block.replace('    return std::snprintf', '    GlDynresStats ds{};gl_renderer_dynres_stats(&ds);\n    return std::snprintf')
            block=block.replace('"\\"compiler_workers\\":%d,', '"\\"active_scale\\":%d,\\"scale_ceiling\\":%d,\\"compiler_workers\\":%d,')
            block=block.replace('g_video_ref_lines,w,h,','g_video_ref_lines,w,h,ds.level,ds.ceiling,')
            text=text[:begin]+block+text[end:]
        path.write_text('// COLLECTION_PERF_SETTINGS_SCALE_V2\n'+text,encoding='utf-8')
    path=framework/'runtime/src/debug_server.c'
    text=path.read_text(encoding='utf-8')
    if 'collection_settings_json' not in text:
        begin=text.index('static void handle_collection_perf(')
        end=text.index('static const CmdEntry s_commands[]',begin)
        block=text[begin:end]
        block=replace_once(block,'    char state[32768];',
            '    extern int collection_settings_json(char*,int);\n    char state[32768],settings[1024];\n    collection_settings_json(settings,sizeof(settings));')
        block=replace_once(block,'true,%s}\\n",id,state);','true,%s,%s}\\n",id,state,settings);')
        path.write_text(text[:begin]+block+text[end:],encoding='utf-8')
    text=path.read_text(encoding='utf-8')
    if 'COLLECTION_PERF_DISABLED_ERRORS_V1' not in text:
        features={'phase_profile':'PSX_PHASE_SAMPLER','frame_perf':'PSX_GL_PERF','frame_perf_samples':'PSX_GL_PERF',
            'cyc_watch':'PSX_INTERPRETER_TRACE','cyc_watch_dump':'PSX_INTERPRETER_TRACE',
            'dirty_block_log':'PSX_INTERPRETER_TRACE','dirty_flow_log':'PSX_INTERPRETER_TRACE','dirty_insn_log':'PSX_INTERPRETER_TRACE'}
        for handler,feature in features.items():
            anchor=f'static void handle_{handler}(int id, const char *json)\n{{'
            text=replace_once(text,anchor,anchor+f'\n    if(!collection_diagnostic_enabled("{feature}")){{send_err(id,"Diagnostic disabled; restart with {feature}=1");return;}}')
        path.write_text('// COLLECTION_PERF_DISABLED_ERRORS_V1\n'+text,encoding='utf-8')

    def loader(text):
        begin=text.index('static int cache_idx_has_path(const char *path) {')
        end=text.index('\n}',begin)+2
        block=text[begin:end]
        block=block.replace('#if defined(JF2_DESKTOP) || defined(ROBBIT_DESKTOP)\n','').replace('#ifdef JF2_DESKTOP\n','').replace('#endif\n','')
        return text[:begin]+block+text[end:]
    edit('overlay_loader.c','COLLECTION_PERF_CACHE_HASH_V1',loader)
    path=framework/'runtime/src/overlay_loader.c'
    text=path.read_text(encoding='utf-8')
    if 'COLLECTION_CAPACITY_PROFILE_V1' not in text:
        text=replace_once(text,'#define CAND_CAP   PSX_OVERLAY_TEST_CANDIDATE_CAP\n#else',
            '#define CAND_CAP   PSX_OVERLAY_TEST_CANDIDATE_CAP\n'
            '#elif defined(COLLECTION_RUNTIME)\n#include "collection_overlay_limits.h"\n'
            '#define CAND_CAP   COLLECTION_OVERLAY_CANDIDATE_CAP\n#else')
        text+='''
// COLLECTION_CAPACITY_PROFILE_V1: host tables only; native shard ABI is unchanged.
#ifdef COLLECTION_RUNTIME
int collection_overlay_limits_json(char *out,int capacity){
    return snprintf(out,capacity,"\\"overlay_limits_schema\\":1,\\"overlay_limits_profile\\":\\"collection-v1\\","
        "\\"overlay_candidate_capacity\\":%d,\\"overlay_capacity_tables_bytes\\":%llu",CAND_CAP,
        (unsigned long long)(sizeof(s_cand)+sizeof(s_range_links)+sizeof(s_lazy_man)+sizeof(s_lazy_range_links)));
}
#endif
'''
        path.write_text(text,encoding='utf-8')
    path=framework/'runtime/src/debug_server.c'
    text=path.read_text(encoding='utf-8')
    if 'COLLECTION_PERF_LIMITS_JSON_V1' not in text:
        begin=text.index('static void handle_collection_perf(');end=text.index('static const CmdEntry s_commands[]',begin)
        block=text[begin:end]
        block=replace_once(block,'    char state[32768],settings[1024];',
            '    extern int collection_overlay_limits_json(char*,int);\n'
            '    char state[32768],settings[1024],limits[256];\n'
            '    collection_overlay_limits_json(limits,sizeof(limits));')
        block=replace_once(block,'true,%s,%s}\\n",id,state,settings);','true,%s,%s,%s}\\n",id,state,settings,limits);')
        path.write_text('// COLLECTION_PERF_LIMITS_JSON_V1\n'+text[:begin]+block+text[end:],encoding='utf-8')
    path=framework/'runtime/src/main.cpp';text=path.read_text(encoding='utf-8')
    if 'COLLECTION_RUNTIME_INFO_V1' not in text:
        anchor='int main(int argc, char** argv) {'
        info='''// COLLECTION_RUNTIME_INFO_V1: before crash handlers, SDL, assets or writable state.
#ifdef COLLECTION_RUNTIME
extern "C" int collection_overlay_limits_json(char*,int);
#endif
int main(int argc, char** argv) {
#ifdef COLLECTION_RUNTIME
    for(int i=1;i<argc;++i)if(std::strcmp(argv[i],"--collection-runtime-info")==0){
        char limits[256];collection_overlay_limits_json(limits,sizeof(limits));
        std::printf("{%s}\\n",limits);return 0;
    }
#endif'''
        path.write_text(replace_once(text,anchor,info),encoding='utf-8')
    # Reject unrelated PCs in C before crossing into the guarded C++ controller callback.
    path=framework/'runtime/src/dirty_ram_interp.c'
    text=path.read_text(encoding='utf-8')
    if 'COLLECTION_JF2_INTERP_SITES_V1' not in text:
        anchor='    /* A load\'s writeback becomes visible to the instruction AFTER its delay'
        addition='''    // COLLECTION_JF2_INTERP_SITES_V1
#if defined(JF2_DESKTOP) && defined(COLLECTION_RUNTIME)
    if(jf2_control_site(pc)&&(pc&0x1fffffffu)!=0xf3a44u){
        extern void jf2_desktop_camera(CPUState*,uint32_t);
        jf2_desktop_camera(cpu,pc);
    }
#endif
'''
        text=replace_once(text,anchor,addition+anchor)
        # Gameplay now uses the exact fetched-instruction path. The separately
        # guarded title remains on the original interpreter dispatch callback.
        text=replace_once(text,'    jf2_desktop_camera(cpu,addr);',
            '    if((addr&0x1fffffffu)==0xf3a44u)jf2_desktop_camera(cpu,addr);')
        text='#include "jf2_control_sites.h"\n'+text
        path.write_text(text,encoding='utf-8')
    if 'COLLECTION_ROBBIT_INTERP_SITES_V1' not in text and '    if ((pc & 0x1fffffffu)==0x99c0cu) {' in text:
        # Partial native coverage can fall through player/camera sites without
        # another dispatcher entry. Observe exact sites before interpretation;
        # the existing title fingerprint still authorizes every actual change.
        text=replace_once(text,'    if ((pc & 0x1fffffffu)==0x99c0cu) {',
            '    // COLLECTION_ROBBIT_INTERP_SITES_V1\n'
            '    const uint32_t collection_robbit_pc=pc & 0x1fffffffu;\n'
            '    if (collection_robbit_pc==0xa2778u || collection_robbit_pc==0xa441cu ||\n'
            '        collection_robbit_pc==0xa24b4u || collection_robbit_pc==0x99c0cu) {')
        path.write_text(text,encoding='utf-8')
    if 'COLLECTION_ROBBIT_INTERP_SITES_V1' in text and 'COLLECTION_ROBBIT_INTERP_SITES_V2' not in text:
        old=('    const uint32_t collection_robbit_pc=pc & 0x1fffffffu;\n'
             '    if (collection_robbit_pc==0xa2778u || collection_robbit_pc==0xa441cu ||\n'
             '        collection_robbit_pc==0xa24b4u || collection_robbit_pc==0x99c0cu) {')
        text=replace_once(text,old,'    // COLLECTION_ROBBIT_INTERP_SITES_V2\n    if (robbit_control_site(pc)) {')
        text='#include "robbit_control_sites.h"\n'+text
        path.write_text(text,encoding='utf-8')
    if 'COLLECTION_PERF_JF1_PREFILTER_V1' not in text:
        if '// COLLECTION_JF1_INTERP_HOOK' in text:
            text=replace_once(text,'    jf1_desktop_camera(cpu,pc);',
                '    if(jf1_control_site(pc))jf1_desktop_camera(cpu,pc);')
            path.write_text('// COLLECTION_PERF_JF1_PREFILTER_V1\n#include "jf1_control_sites.h"\n'+text,encoding='utf-8')
    text=path.read_text(encoding='utf-8')
    if 'COLLECTION_PERF_TRACE_V1' not in text:
        text=replace_once(text,'    if (g_insn_log_frozen) return;\n    /* Freeze-on-target',
            '    if (!collection_trace_enabled() || g_insn_log_frozen) return;\n    /* Freeze-on-target')
        text=replace_once(text,'void dirty_ram_log_marker(uint32_t addr, uint32_t tag, int kind) {\n    if (g_insn_log_frozen) return;',
            'void dirty_ram_log_marker(uint32_t addr, uint32_t tag, int kind) {\n    if (!collection_trace_enabled() || g_insn_log_frozen) return;')
        text=text.replace('if (!g_insn_log_frozen) {','if (collection_trace_enabled() && !g_insn_log_frozen) {')
        helper='''// COLLECTION_PERF_TRACE_V1
#include "collection_diagnostics.h"
static inline int collection_trace_enabled(void){
    static int enabled=-1;
    if(enabled<0)enabled=collection_diagnostic_enabled("PSX_INTERPRETER_TRACE");
    return enabled;
}
'''
        path.write_text(helper+text,encoding='utf-8')
    text=path.read_text(encoding='utf-8')
    if 'COLLECTION_PERF_TRACE_CALLS_V2' not in text:
        text=replace_once(text,'        dirty_ram_log_instruction(cpu, pc, insn, before_s0, next_pc,',
            '        if(collection_trace_enabled())dirty_ram_log_instruction(cpu, pc, insn, before_s0, next_pc,')
        text=replace_once(text,'        g_ls_dirty_observe = 1;\n        debug_server_cyc_observe(pc & 0x1FFFFFFFu);\n        g_ls_dirty_observe = 0;',
            '        if(collection_trace_enabled()){\n            g_ls_dirty_observe = 1;\n            debug_server_cyc_observe(pc & 0x1FFFFFFFu);\n            g_ls_dirty_observe = 0;\n        }')
        path.write_text('// COLLECTION_PERF_TRACE_CALLS_V2\n'+text,encoding='utf-8')
