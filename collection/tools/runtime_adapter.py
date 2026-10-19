"""Apply collection-only integration to isolated runtime source copies."""
from pathlib import Path
import argparse
import re
from patch_graphics import patch_camera_fit,patch_history,patch_framegen_redraw,collection_aspect_source

def replace_once(text, old, new):
    if text.count(old) != 1:
        raise ValueError(f'Expected one integration anchor: {old[:100]}')
    return text.replace(old, new, 1)

def adapt(framework):
    path = Path(framework) / 'runtime/src/main.cpp'
    text = path.read_text(encoding='utf-8')
    if '// COLLECTION_RUNTIME_ADAPTER_V1' in text:
        text=adapt_state_boot(text)
        text=adapt_deck_profile(text)
        text=text.replace('static bool collection_gameplay_live(){\n','static bool collection_gameplay_live(){\n    if(!collection_mode)return false;\n') if 'static bool collection_gameplay_live(){\n    if(!collection_mode)' not in text else text
        if 'static void collection_look_reset(){' not in text:
            text=text.replace('#include "collection_runtime.h"',look_reset_bridge()+'#include "collection_runtime.h"')
        if '#include "host_input_probe.h"' not in text:text=text.replace('#include "collection_runtime.h"','#include "host_input_probe.h"\n#include "collection_runtime.h"')
        text = text.replace('jf2_desktop_init(exe_dir_from_argv(argv[0]));','jf2_desktop_init(collection_storage(argv[0]));')
        text=adapt_resume_guard(adapt_jf1_input(adapt_input(adapt_pause(text))))
        path.write_text(collection_aspect_source(text),encoding='utf-8')
        adapt_desktop(Path(framework).parent)
        adapt_renderer(Path(framework))
        patch_history(Path(framework))
        patch_camera_fit(Path(framework))
        patch_framegen_redraw(Path(framework))
        adapt_diagnostics(Path(framework))
        adapt_jf1_timing(Path(framework))
        return
    text = replace_once(text, 'static std::filesystem::path exe_dir_from_argv(const char* argv0) {',
        '// COLLECTION_RUNTIME_ADAPTER_V1\nstatic std::filesystem::path collection_user_data;\n'
        'static bool collection_mode=false, collection_deck=false;\n'
        'static std::filesystem::path exe_dir_from_argv(const char* argv0) {')
    # The helper is inserted after exe_dir_from_argv, before other consumers.
    end = text.index('\n}', text.index('static std::filesystem::path exe_dir_from_argv')) + 2
    text = text[:end] + '\nstatic std::filesystem::path collection_storage(const char* argv0) {\n' + \
        '    return collection_user_data.empty()?exe_dir_from_argv(argv0):collection_user_data;\n}\n' + text[end:]
    text = replace_once(text, 'if (std::strcmp(argv[i], "--bios") == 0 && i + 1 < argc) {',
        'if (std::strcmp(argv[i], "--user-data-dir") == 0 && i + 1 < argc) {\n'
        '            collection_user_data=std::filesystem::absolute(consume_path_arg(i)).lexically_normal();\n'
        '            std::filesystem::create_directories(collection_user_data);\n'
        '        } else if (std::strcmp(argv[i], "--collection-mode") == 0) {\n'
        '            collection_mode=true;\n'
        '        } else if (std::strcmp(argv[i], "--deck-profile") == 0) {\n'
        '            collection_deck=true;\n'
        '        } else if (std::strcmp(argv[i], "--bios") == 0 && i + 1 < argc) {')
    text = re.sub(r'exe_dir_from_argv\((argv\[0\]|argv0)\) / "(settings.toml|input.ini|config.ini)"',
                  r'collection_storage(\1) / "\2"',text)
    text = text.replace('psx_keybinds_init(argv0);',
        'psx_keybinds_init(collection_user_data.empty()?argv0:(collection_user_data / "runtime.exe").string().c_str());')
    text = text.replace('psx_keybinds_init(argv[0]);',
        'psx_keybinds_init(collection_user_data.empty()?argv[0]:(collection_user_data / "runtime.exe").string().c_str());')
    text = replace_once(text, 'std::filesystem::path exe_dir = exe_dir_from_argv(argv[0]);\n        std::string cache_dir',
        'std::filesystem::path exe_dir = collection_storage(argv[0]);\n        std::string cache_dir')
    text = replace_once(text, 'const std::filesystem::path tk_dir = tk_xd / "overlay_toolchain";',
        'const std::filesystem::path tk_dir = collection_mode?\n'
        '            tk_xd.parent_path().parent_path() / "toolchain":tk_xd / "overlay_toolchain";')
    text = replace_once(text, 'if (!line.empty() && std::filesystem::exists(line, cec)) tk_compiler = line;',
        'if (!line.empty()) {\n'
        '                    std::filesystem::path compiler_path(line);\n'
        '                    if (compiler_path.is_relative()) compiler_path=tk_dir/compiler_path;\n'
        '                    if (std::filesystem::exists(compiler_path,cec)) tk_compiler=compiler_path.string();\n'
        '                }')
    text = text.replace('cmd_quote((tk_xd / "cache").string())','cmd_quote((collection_storage(argv[0]) / "cache").string())')
    text = text.replace('c += " --jobs 2";', 'c += collection_deck?" --jobs 1":" --jobs 2";')
    # This block occurs both before and after the launcher in the current framework.
    text = text.replace('    if (cli_memcard_dir) {\n        memcard_dir = std::filesystem::path(cli_memcard_dir);',
        '    if (!collection_user_data.empty()) {\n        memcard_dir=collection_user_data / "saves";memcard1_path.clear();memcard2_path.clear();\n'
        '        std::filesystem::create_directories(memcard_dir);\n    }\n'
        '    if (cli_memcard_dir) {\n        memcard_dir = std::filesystem::path(cli_memcard_dir);')
    text = replace_once(text, 'static bool drain_host_events() {\n    SDL_Event ev;\n    while (SDL_PollEvent(&ev)) {',
        '#include "collection_runtime.h"\nstatic bool drain_host_events() {\n    SDL_Event ev;\n'
        '    while (SDL_PollEvent(&ev)) {\n        if (collection_runtime_event(ev)) continue;')
    text = replace_once(text, '\n    psx_local_mouse_begin(sdl_window, local_mouse_live(override));',
        '\n    if (collection_mode) {\n'
        '        if (collection_pad_frames>0) {override=collection_pad_word;--collection_pad_frames;}\n'
        '        else if (collection_menu_open) override=0xffff;\n'
        '    }\n    psx_local_mouse_begin(sdl_window, local_mouse_live(override));')
    # Send diagnostics/captures into the game-owned storage, even if the old config points up-tree.
    text = replace_once(text, 'resolve_overlay_capture_path(deferred_overlay_project_root, exe_dir, game_id);',
        'collection_user_data.empty()?resolve_overlay_capture_path(deferred_overlay_project_root,exe_dir,game_id):\n'
        '                collection_user_data / "overlay_captures.json";')
    text=adapt_resume_guard(adapt_jf1_input(adapt_deck_profile(adapt_state_boot(adapt_input(adapt_pause(text))))))
    path.write_text(collection_aspect_source(text),encoding='utf-8')
    adapt_desktop(Path(framework).parent)
    adapt_renderer(Path(framework))
    patch_history(Path(framework))
    patch_camera_fit(Path(framework))
    patch_framegen_redraw(Path(framework))
    adapt_diagnostics(Path(framework))
    adapt_jf1_timing(Path(framework))
    print(f'Applied collection data/launch integration: {path}')

def adapt_state_boot(text):
    # A inherited developer diagnostic variable must never replace native Continue.
    anchor='if (const char *ls = std::getenv("PSX_LOAD_SLOT")) {'
    return text.replace(anchor,'if (const char *ls = collection_mode?nullptr:std::getenv("PSX_LOAD_SLOT")) {')

def adapt_deck_profile(text):
    if '// COLLECTION_DECK_PROFILE_V1' in text:
        return text.replace('g_video_internal_res_env=720;\n','g_video_internal_res_env=720;g_video_dynres_env=0;\n')
    anchor='    apply_internal_resolution(psx_sdl_display_pixel_height(nullptr));'
    return replace_once(text,anchor,'''    // COLLECTION_DECK_PROFILE_V1
    if(collection_mode&&collection_deck){
        g_video_internal_res_env=720;g_video_dynres_env=0;
        g_video_win_w=1280;
        if(!g_headless&&!g_hidden_window)g_fullscreen=1;
    }
'''+anchor)

def adapt_pause(text):
    anchor='if (!drain_host_events()) return ep;'
    return text.replace(anchor,anchor+'\n        collection_host_pause_loop();') if 'collection_host_pause_loop();' not in text else text

def adapt_jf1_timing(framework):
    path=framework/'runtime/src/overlay_loader.c';text=path.read_text(encoding='utf-8')
    anchor="#if defined(JF2_DESKTOP) || defined(ROBBIT_DESKTOP)\n    // JF2's nested World 1 frame wait"
    replacement="#if defined(JF2_DESKTOP) || defined(ROBBIT_DESKTOP) || defined(JF1_DESKTOP)\n    // These titles' nested frame waits"
    text=text.replace(anchor,replacement)
    path.write_text(text,encoding='utf-8')

def adapt_input(text):
    if '#include "host_input_sdl.h"' in text:return text
    text=replace_once(text,'static uint16_t pad_from_keyboard(int player) {',
        '#include "host_input_sdl.h"\nstatic uint16_t pad_from_keyboard(int player) {')
    start=text.index('static uint16_t pad_from_keyboard(int player) {')
    end=text.index('\n}',start)
    block=text[start:end]
    block=block.replace('const Uint8* keys = SDL_GetKeyboardState(NULL);','const Uint8* keys = collection_host_keys(SDL_GetKeyboardState(NULL),player);')
    block=block.replace('return robbit_input_pad(keys,player);','return robbit_input_pad(keys,player) & (player==1&&collection_mode?collection_controller_word:0xffff);')
    block=block.replace('return jf2_desktop_pad(keys, player);','return jf2_desktop_pad(keys, player) & (player==1&&collection_mode?collection_controller_word:0xffff);')
    block=block.replace('return psx_keybinds_pad_word(keys, player);','return psx_keybinds_pad_word(keys, player) & (player==1&&collection_mode?collection_controller_word:0xffff);')
    text=text[:start]+block+text[end:]
    bridge='''static bool collection_gameplay_live(){
    if(!collection_mode)return false;
#if defined(JF2_DESKTOP)
    jf2_settings.jf2_control_style=collection_controls.modern;jf2_settings.jf2_mouse_sensitivity=collection_controls.sensitivity;jf2_settings.jf2_invert_y=collection_controls.invert_y;
    return jf2_camera_supported()&&!jf2_desktop_open()&&jf2_camera_frame&&s_frame_count-jf2_camera_frame<8;
#elif defined(ROBBIT_DESKTOP)
    robbit_modern=collection_controls.modern;robbit_sensitivity=collection_controls.sensitivity;robbit_invert=collection_controls.invert_y;
    return robbit_gameplay();
#else
    return false; // JF1 camera/scene hooks still require independent recovery.
#endif
}
static void collection_look_apply(double x,double y){
#if defined(JF2_DESKTOP)
    jf2_look.move(x,y);
#elif defined(ROBBIT_DESKTOP)
    robbit_look.move(x,y);
#endif
}
'''
    text=replace_once(text,'#include "collection_runtime.h"',bridge+look_reset_bridge()+'#include "host_input_probe.h"\n#include "collection_runtime.h"')
    return text

def adapt_jf1_input(text):
    # Upgrade existing private adapters as well as fresh snapshots.
    if '// COLLECTION_JF1_INPUT_V1' in text:return text
    text=text.replace('static bool collection_gameplay_live(){',
        '#ifdef JF1_DESKTOP\n#include "jf1_desktop.h"\n#endif\n// COLLECTION_JF1_INPUT_V1\nstatic bool collection_gameplay_live(){',1)
    text=text.replace('return false; // JF1 camera/scene hooks still require independent recovery.',
        '#if defined(JF1_DESKTOP)\n    return jf1_gameplay();\n#else\n    return false;\n#endif')
    text=text.replace('static void collection_look_apply(double x,double y){',
        'static void collection_move_apply(float x,float forward){\n#ifdef JF1_DESKTOP\n    jf1_pad_x=x;jf1_pad_forward=forward;\n#endif\n}\nstatic void collection_look_apply(double x,double y){\n#ifdef JF1_DESKTOP\n    jf1_look.move(x,y);\n#endif')
    text=text.replace('static void collection_look_reset(){',
        'static void collection_look_reset(){\n#ifdef JF1_DESKTOP\n    jf1_release_inputs();\n#endif')
    anchor='static uint16_t pad_from_keyboard(int player) {'
    text=text.replace(anchor,anchor+'\n#ifdef JF1_DESKTOP\n    if(collection_mode)return jf1_input_pad(collection_host_keys(SDL_GetKeyboardState(nullptr),player),player);\n#endif',1)
    # Collection owns its shared keyboard/gamepad bridge regardless of which
    # framework device happened to be selected in an inherited preference file.
    anchor='static uint16_t pad_buttons_for(const PlayerInput& p, int player, bool suppress_stick_axes) {'
    text=text.replace(anchor,anchor+'\n    if(collection_mode&&player==1)return pad_from_keyboard(player);',1)
    text=text.replace('if (collection_runtime_event(ev)) continue;',
        'if (collection_runtime_event(ev)) continue;\n#ifdef JF1_DESKTOP\n        if(jf1_input_event(ev))continue;\n#endif',1)
    text=text.replace('static void sdl_vblank_present(void) {',
        'static void sdl_vblank_present(void) {\n#ifdef JF1_DESKTOP\n    jf1_desktop_tick();\n#endif',1)
    return text

def adapt_resume_guard(text):
    if '// COLLECTION_RAW_RESUME_GUARD' in text:return text
    anchor='static int savestate_resume_inputs_held(void) {\n'
    # The transformed pad reader itself consults this guard. Reading it from
    # the release test recursively re-enters the guard after its minimum hold.
    addition='''    // COLLECTION_RAW_RESUME_GUARD: inspect physical sources, never transformed pad readers.
    if(collection_mode){
        const auto* raw_keys=SDL_GetKeyboardState(nullptr);
        if(raw_keys)for(int sc=0;sc<SDL_NUM_SCANCODES;++sc)if(raw_keys[sc])return 1;
        if(SDL_GetMouseState(nullptr,nullptr))return 1;
        const auto raw=collection_physical_sample();
        for(bool button:raw.buttons)if(button)return 1;
        for(float axis:raw.axes)if(std::abs(axis)>.05f)return 1;
        return 0;
    }
'''
    return replace_once(text,anchor,anchor+addition)

def adapt_diagnostics(framework):
    path=framework/'runtime/src/debug_server.c';text=path.read_text(encoding='utf-8')
    if 'handle_collection_input' in text:return
    anchor='static const CmdEntry s_commands[] = {'
    handlers='''#ifdef COLLECTION_RUNTIME
extern int collection_input_probe(int,uint32_t,const int[6]);
extern int collection_input_status_json(char*,int);
static void handle_collection_input(int id,const char* json){
    int enable=json_get_int(json,"enable",-1);
    int axes[6]={json_get_int(json,"lx",0),json_get_int(json,"ly",0),json_get_int(json,"rx",0),json_get_int(json,"ry",0),json_get_int(json,"lt",0),json_get_int(json,"rt",0)};
    if(enable>=0&&!collection_input_probe(enable,(uint32_t)json_get_int(json,"buttons",0),axes)){send_err(id,"SDL virtual controller probe unavailable");return;}
    char state[1024];collection_input_status_json(state,sizeof(state));send_fmt("{\\"id\\":%d,\\"ok\\":true,%s}\\n",id,state);
}
#endif
'''
    text=replace_once(text,anchor,handlers+anchor+'\n#ifdef COLLECTION_RUNTIME\n    {"collection_input",handle_collection_input},\n#endif')
    path.write_text(text,encoding='utf-8')

def look_reset_bridge():
    return '''static void collection_look_reset(){
#if defined(JF2_DESKTOP)
    jf2_look.clear();
#elif defined(ROBBIT_DESKTOP)
    robbit_look.clear();robbit_move_x=robbit_move_forward=0;robbit_move_until=0;
#endif
}
'''

def adapt_desktop(project):
    robbit=project/'desktop/robbit_desktop.h'
    if robbit.exists():
        text=robbit.read_text(encoding='utf-8')
        text=text.replace('!robbit_captured || !robbit_gameplay()', '!(robbit_captured || collection_aim_live) || !robbit_gameplay()')
        robbit.write_text(text,encoding='utf-8')
    header=project/'desktop/jf2_desktop.h'
    main=project/'psxrecomp/runtime/src/main.cpp'
    if not header.exists():return
    text=main.read_text(encoding='utf-8')
    main.write_text(text.replace('jf2_desktop_init(exe_dir_from_argv(argv[0]));','jf2_desktop_init(collection_storage(argv[0]));'),encoding='utf-8')
    text=header.read_text(encoding='utf-8')
    text=text.replace('!jf2_captured || jf2_desktop_open()', '!(jf2_captured || collection_aim_live) || jf2_desktop_open()')
    pad_hook='    if(collection_mode)jf2_last_pad &= collection_controller_word;'
    if pad_hook not in text:
        text=text.replace('jf2_last_pad=psx_keybinds_pad_word(clean.data(),1);','jf2_last_pad=psx_keybinds_pad_word(clean.data(),1);\n'+pad_hook)
    anchor='static void jf2_restart(bool launcher) {\n'
    addition='    if(collection_mode){jf2_save();jf2_release_inputs();psx_crash_trace_set_exit_origin("return_to_collection");shutdown_runtime();std::exit(0);}\n'
    if addition not in text:text=replace_once(text,anchor,anchor+addition)
    text=adapt_jf2_collection_pipeline_ui(text)
    header.write_text(text,encoding='utf-8')

def adapt_jf2_collection_pipeline_ui(text):
    marker='// COLLECTION_JF2_PIPELINE_UI_V1'
    if marker in text:return text
    helpers='''// COLLECTION_JF2_PIPELINE_UI_V1
static bool jf2_pipeline_options_available(bool in_collection,int renderer) {
    return in_collection && renderer==1;
}
static bool jf2_pipeline_option_enabled(bool available,bool frame_generation,int render_thread_pref) {
    return available && (!frame_generation || render_thread_pref!=0);
}
static bool jf2_pipeline_options_available() {
    return jf2_pipeline_options_available(collection_mode,
        jf2_renderer_pending?jf2_settings.renderer:g_video_renderer);
}
'''
    text=replace_once(text,'static int jf2_get(void*,const RecompRuntimeUiItem* item,int* out) {',helpers+'static int jf2_get(void*,const RecompRuntimeUiItem* item,int* out) {')
    text=replace_once(text,'    else if(k=="fps") *out=fps_telemetry_enabled();',
        '    else if(k=="render_thread") *out=g_render_thread_pref;\n'
        '    else if(k=="frame_generation") *out=g_frame_generation_pref;\n'
        '    else if(k=="fps") *out=fps_telemetry_enabled();')
    text=replace_once(text,'    if(k=="boostpct" || k=="boostkey") return jf2_settings.jf2_boost;',
        '    if(k=="render_thread" || k=="frame_generation")\n'
        '        return jf2_pipeline_option_enabled(jf2_pipeline_options_available(),k=="frame_generation",g_render_thread_pref);\n'
        '    if(k=="boostpct" || k=="boostkey") return jf2_settings.jf2_boost;')
    settings='''    else if(jf2_pipeline_options_available() && k=="render_thread") {
        g_render_thread_pref=value!=0;
        s.render_thread=g_render_thread_pref!=0;s.has_render_thread=true;
        recomp_runtime_ui_set_status(jf2_ui,"Render thread setting saved for the next collection launch.");
    }
    else if(jf2_pipeline_options_available() && k=="frame_generation") {
        g_frame_generation_pref=value!=0;
        s.frame_generation=g_frame_generation_pref!=0;s.has_frame_generation=true;
        recomp_runtime_ui_set_status(jf2_ui,"Smooth motion setting saved for the next collection launch.");
    }
'''
    text=replace_once(text,'    else if(k=="device") { if(value<0 || value>=(int)jf2_device_ids.size()) return 0;',settings+'    else if(k=="device") { if(value<0 || value>=(int)jf2_device_ids.size()) return 0;')
    rows='''    if(collection_mode) {
        add("render_thread","Display","Render thread",RECOMP_RUNTIME_UI_BOOL,0,1,nullptr,0,"Collection mode only; applies at next launch.");
        add("frame_generation","Display","Smooth motion",RECOMP_RUNTIME_UI_BOOL,0,1,nullptr,0,"Collection mode only; needs Render thread and applies at next launch.");
    }
'''
    text=replace_once(text,'    add("fps","Display","FPS display",RECOMP_RUNTIME_UI_BOOL,0,1);',rows+'    add("fps","Display","FPS display",RECOMP_RUNTIME_UI_BOOL,0,1);')
    return text

def adapt_renderer(framework):
    renderer=framework/'runtime/src/gpu_gl_renderer.c'
    renderer_text=renderer.read_text(encoding='utf-8')
    old='case 4: { extern int jf2_desktop_image(const uint32_t**,int*,int*);return jf2_desktop_image(px,w,h); }'
    guarded='#if defined(JF2_DESKTOP)\n    '+old+'\n#endif'
    if old in renderer_text and guarded not in renderer_text:
        renderer_text=renderer_text.replace(old,guarded)
        renderer.write_text(renderer_text,encoding='utf-8')
    main=framework/'runtime/src/main.cpp'
    text=main.read_text(encoding='utf-8')
    if 'g_render_thread = g_present_thread = g_frame_generation = 0;' not in text:return
    text=text.replace('g_render_thread = g_present_thread = g_frame_generation = 0;',
        'if(!collection_mode)g_render_thread=g_frame_generation=0;\n    g_present_thread=0; // JF2 ImGui remains on the emulation thread during a context hold.')
    main.write_text(text,encoding='utf-8')
    renderer=framework/'runtime/src/gpu_gl_renderer.c'
    text=renderer.read_text(encoding='utf-8')
    text=text.replace('const uint32_t *px[4];\n    int w[4], h[4];','const uint32_t *px[5];\n    int w[5], h[5];')
    text=text.replace('int32_t needs_present, has, w[4], h[4];','int32_t needs_present, has, w[5], h[5];')
    text=text.replace('const uint32_t *px[4] = { NULL, NULL, NULL, NULL };','const uint32_t *px[5] = { NULL };')
    text=text.replace('int w[4] = { 0 }, h[4] = { 0 };','int w[5] = { 0 }, h[5] = { 0 };')
    # Change only the five overlay serialization/replay loops, not geometry's four-frame history.
    begin=text.index('static int rth_record_present(uint16_t op, int n, const int32_t *v) {')
    end=text.index('/* ---- render-thread frame cost',begin)
    text=text[:begin]+text[begin:end].replace('i < 4','i < 5')+text[end:]
    begin=text.index('/* The overlay of the real frame these lead up to. */')
    end=text.index('/* Timed without the swap',begin)
    text=text[:begin]+text[begin:end].replace('i < 4','i < 5')+text[end:]
    text=replace_once(text,'default: return psx_savestate_menu_overlay_image(px, w, h);',
        'case 3: return psx_savestate_menu_overlay_image(px,w,h);\n'
        '    #if defined(JF2_DESKTOP)\n'
        '    case 4: { extern int jf2_desktop_image(const uint32_t**,int*,int*);return jf2_desktop_image(px,w,h); }\n'
        '    #endif\n'
        '    default: return 0;')
    text=text.replace('if (jf2_desktop_image(&menu,&mw,&mh)) {','if (ov_image(4,&menu,&mw,&mh)) {')
    text=text.replace('    jf2_desktop_gl_draw(s_win);','    if(!rth_replaying())jf2_desktop_gl_draw(s_win);')
    renderer.write_text(text,encoding='utf-8')

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('framework');adapt(parser.parse_args().framework)
