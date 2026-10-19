// Included by this title's main.cpp; guest code and hardware timing stay in PSXRecomp.
#include "recomp_runtime_ui.h"
#include "common/recomp_runtime_ui_internal.h"
#include "imgui.h"
#include "imgui_impl_sdl3.h"
#include "imgui_impl_opengl3.h"
#include <array>
#include <cmath>
#include <windows.h>
#include <shellapi.h>
#include "jf2_desktop_core.h"

static std::filesystem::path jf2_dir;
static PSXRecompV4::UserSettings jf2_settings;
static RecompRuntimeUi* jf2_ui = nullptr;
static CPUState* jf2_cpu = nullptr;
static ImGuiContext* jf2_imgui = nullptr;
static int jf2_rebind = -1;
static bool jf2_captured = false, jf2_initialized = false;
static bool jf2_restoring=false;
static std::array<uint8_t, SDL_NUM_SCANCODES> jf2_held{};
static std::array<uint64_t, SDL_NUM_SCANCODES> jf2_pressed_until{};
static std::array<uint64_t,6> jf2_mouse_until{};
static uint16_t jf2_asserted_pad=0xFFFF;
static uint64_t jf2_asserted_frame=0;
static uint32_t jf2_mouse_held = 0;
static jf2::MouseLook jf2_look;
static uint64_t jf2_updates = 0, jf2_key_events = 0;
static uint64_t jf2_update_frame=UINT64_MAX, jf2_mouse_events=0;
static uint32_t jf2_title_actor=0;
static uint64_t jf2_title_frame=0;
static int jf2_title_row=0;
static bool jf2_title_accept=false;
static uint64_t jf2_title_click_until=0;
static jf2::TitleInputGate jf2_title_gate;
static bool jf2_boost_held=false, jf2_launcher_boost_capture=false, jf2_visuals_applied=false;
// Temporary input command around the native movement routine, restored before camera helpers.
static bool jf2_move_command=false, jf2_keyboard_motion_pending=false;
static int jf2_injected_pad=-1;
extern "C" int debug_server_get_input_boost(void);
extern "C" void jf2_desktop_input_source(int pad) {
    jf2_injected_pad=pad;
    // Diagnostic routes exercise the existing booster; normal SDL sampling is unchanged.
    if(pad>=0) jf2_boost_held=jf2_settings.jf2_boost && debug_server_get_input_boost();
}
static uint32_t jf2_saved_move_pad=0, jf2_saved_move_yaw=0, jf2_saved_move_base=0;
static uint32_t jf2_saved_move_mode=0, jf2_saved_look_mode=0;
static uint64_t jf2_boost_updates=0, jf2_strafe_updates=0;
static int jf2_move_angle=0, jf2_move_speed=0;
static double jf2_last_dx=0,jf2_last_dy=0;
static int jf2_last_key = 0;
static uint16_t jf2_last_pad = 0xFFFF;
static bool jf2_pad_release = false, jf2_renderer_pending = false;
static uint64_t jf2_camera_frame = 0;
static uint64_t jf2_blank_since = 0;
static uint64_t jf2_compile_probe=0;
static bool jf2_compiling=false;
static int jf2_slot = 0, jf2_volume = 100;
static uint64_t jf2_load_confirm_until=0;
static uint64_t jf2_guide_until=0;
static int jf2_shot_sequence=-1;
static const char* jf2_visuals[]={"Custom", "Compatibility (recommended)", "Crisp HD (experimental)", "Retro scanlines"};
static std::vector<RecompRuntimeUiItem> jf2_items;
static char jf2_bind_labels[16][80];
static const char* jf2_styles[] = {"Classic", "Modern"};
static const char* jf2_renderers[] = {"Software", "OpenGL"};
static const char* jf2_resolutions[] = {"Native", "720p", "960p", "1080p", "1440p", "4K", "Match display"};
// Framework encoding: 1 means native; 0 means unset and is not persisted.
static const int jf2_res_lines[] = {1,720,960,1080,1440,2160,-1};
static const char* jf2_sizes[] = {"640 x 480", "960 x 720", "1280 x 960", "1600 x 1200"};
static const int jf2_widths[] = {640,960,1280,1600};
static std::vector<std::string> jf2_device_names, jf2_device_ids;
static std::vector<const char*> jf2_devices;
static const char* jf2_filters[] = {"Nearest", "Bilinear", "Stable world"};
static const char* jf2_aa[] = {"Off", "FXAA", "FXAA high quality"};
static const char* jf2_menu_styles[] = {"Desktop", "PS1 in-game"};
static char jf2_boost_label[80];
static const char* jf2_bind_keys[] = {"bind0","bind1","bind2","bind3","bind4","bind5","bind6","bind7","bind8","bind9","bind10","bind11","bind12","bind13","bind14","bind15"};
static bool jf2_desktop_open() {
#ifdef COLLECTION_RUNTIME
    return collection_menu_open;
#else
    return false;
#endif
}
static bool jf2_camera_supported();
static void jf2_release_inputs();
static bool jf2_title_active() { return false; }
static void jf2_open_mods() {
    // JF2-specific graphical mods are disabled in compatibility mode.
}
static bool jf2_pixel_menu() { return !g_gl_active || jf2_settings.jf2_native_menu; }
static int& jf2_boost_key() { return jf2_settings.jf2_control_style?jf2_settings.jf2_boost_modern_key:jf2_settings.jf2_boost_classic_key; }
static bool jf2_reserved_key(int sc) { return sc==SDL_SCANCODE_ESCAPE || sc==SDL_SCANCODE_F1 || sc==SDL_SCANCODE_F2 || sc==SDL_SCANCODE_F5 || sc==SDL_SCANCODE_F9 || sc==SDL_SCANCODE_F12; }
static bool jf2_bind_boost(int sc) {
    if(sc<=0 || sc>=SDL_NUM_SCANCODES || jf2_reserved_key(sc)) return false;
    for(int i=0;i<PSX_KB_COUNT;++i) if(psx_keybinds_get_button(1,i)==sc || psx_keybinds_get_button_alt(1,i)==sc) return false;
    jf2_boost_key()=sc;return true;
}
extern "C" void gte_geometry_correction_set(int);
extern "C" int gte_geometry_correction_enabled(void);
extern "C" void gpu_texture_correction_set(int);
extern "C" int gpu_texture_correction_enabled(void);

static void jf2_release_mouse() {
    if (sdl_window) SDL_SetWindowRelativeMouseMode(sdl_window, false);
    jf2_captured=false; jf2_look.clear();
}
static void jf2_release_inputs() {
    jf2_release_mouse(); jf2_pad_release=true;
    jf2_load_confirm_until=0;
    jf2_title_click_until=0;
    jf2_boost_held=false;jf2_keyboard_motion_pending=false;
    jf2_pressed_until.fill(0);jf2_mouse_until.fill(0);
    const Uint8* keys=SDL_GetKeyboardState(nullptr);
    for(int i=0;i<SDL_NUM_SCANCODES;++i) jf2_held[i]=keys && keys[i];
    jf2_mouse_held=SDL_GetMouseState(nullptr,nullptr);
}
static void jf2_store_desktop(PSXRecompV4::UserSettings& s) {
    s.jf2_has_settings=true;
    s.jf2_control_style=jf2_settings.jf2_control_style;
    s.jf2_mouse_sensitivity=jf2_settings.jf2_mouse_sensitivity;
    s.jf2_invert_y=jf2_settings.jf2_invert_y;
    s.jf2_jump_camera=jf2_settings.jf2_jump_camera;
    s.jf2_fps=jf2_settings.jf2_fps;
    s.jf2_integer_scaling=jf2_settings.jf2_integer_scaling;
    s.jf2_audio_volume=jf2_settings.jf2_audio_volume;
    s.jf2_muted=jf2_settings.jf2_muted;
    s.jf2_boost=jf2_settings.jf2_boost;s.jf2_boost_percent=jf2_settings.jf2_boost_percent;
    s.jf2_boost_classic_key=jf2_settings.jf2_boost_classic_key;s.jf2_boost_modern_key=jf2_settings.jf2_boost_modern_key;
    s.jf2_arrow_strafe=jf2_settings.jf2_arrow_strafe;s.jf2_messages=jf2_settings.jf2_messages;
    s.jf2_native_menu=jf2_settings.jf2_native_menu;s.jf2_post_aa=jf2_settings.jf2_post_aa;
}
static void jf2_save() {
    if(jf2_dir.empty()) return;
    auto s=PSXRecompV4::load_user_settings(jf2_dir/"settings.toml");
    if(s.parse_error) { host_osd_push("Settings file could not be read; changes were not saved",4000); return; }
    jf2_store_desktop(s);
    if(!PSXRecompV4::save_user_settings(jf2_dir/"settings.toml",s)) host_osd_push("Unable to save desktop settings",4000);
    psx_keybinds_save();
    std::error_code ec;
    std::filesystem::copy_file(jf2_dir/"keybinds.ini",jf2_dir/(jf2_settings.jf2_control_style?"keybinds-modern.ini":"keybinds-classic.ini"),std::filesystem::copy_options::overwrite_existing,ec);
    if(ec) host_osd_push("Unable to save control preset",4000);
}
static void jf2_default_bindings() {
    psx_keybinds_reset_player(1);
    if(!jf2_settings.jf2_control_style) return;
    for(int i=0;i<PSX_KB_COUNT;++i) psx_keybinds_set_button(1,i,SDL_SCANCODE_UNKNOWN);
    psx_keybinds_set_button(1,PSX_KB_UP,SDL_SCANCODE_W);
    psx_keybinds_set_button(1,PSX_KB_DOWN,SDL_SCANCODE_S);
    psx_keybinds_set_button(1,PSX_KB_L1,SDL_SCANCODE_A);
    psx_keybinds_set_button(1,PSX_KB_R1,SDL_SCANCODE_D);
    psx_keybinds_set_button(1,PSX_KB_LEFT,SDL_SCANCODE_LEFT);
    psx_keybinds_set_button(1,PSX_KB_RIGHT,SDL_SCANCODE_RIGHT);
    psx_keybinds_set_button(1,PSX_KB_CROSS,SDL_SCANCODE_SPACE);
    psx_keybinds_set_button(1,PSX_KB_SQUARE,PSXKB_MOUSE_SC(1));
    psx_keybinds_set_button(1,PSX_KB_CIRCLE,PSXKB_MOUSE_SC(3));
    psx_keybinds_set_button(1,PSX_KB_TRIANGLE,SDL_SCANCODE_F);
    psx_keybinds_set_button(1,PSX_KB_START,SDL_SCANCODE_RETURN);
    psx_keybinds_set_button(1,PSX_KB_SELECT,SDL_SCANCODE_RSHIFT);
    psx_keybinds_set_button(1,PSX_KB_L2,SDL_SCANCODE_Q);
    psx_keybinds_set_button(1,PSX_KB_R2,SDL_SCANCODE_E);
    // Arrow keys remain usable in the original menus.
    psx_keybinds_set_button_alt(1,PSX_KB_UP,SDL_SCANCODE_UP);
    psx_keybinds_set_button_alt(1,PSX_KB_DOWN,SDL_SCANCODE_DOWN);
}
static void jf2_desktop_reload_bindings() {
    std::error_code ec;
    auto preset=jf2_dir/(jf2_settings.jf2_control_style?"keybinds-modern.ini":"keybinds-classic.ini");
    if(std::filesystem::exists(preset)) {
        std::filesystem::copy_file(preset,jf2_dir/"keybinds.ini",std::filesystem::copy_options::overwrite_existing,ec);
        if(ec) { host_osd_push("Cannot load control preset",4000); return; }
        psx_keybinds_init((jf2_dir/"JumpingFlash2_Recompiled.exe").string().c_str());
    } else { jf2_default_bindings(); jf2_save(); }
}
static void jf2_select_style(int style) {
    if(style==jf2_settings.jf2_control_style) return;
    jf2_save(); jf2_release_inputs();
    jf2_settings.jf2_control_style=style; jf2_rebind=-1;
    jf2_desktop_reload_bindings(); jf2_save();
}
extern "C" uint32_t jf2_desktop_mouse_buttons() {
    uint32_t bits=SDL_GetMouseState(nullptr,nullptr);
    for(int b=1;b<=5;++b) if(jf2_mouse_until[b]>s_frame_count) bits|=SDL_BUTTON_MASK(b);
    return bits;
}
uint16_t jf2_desktop_pad(const Uint8* keys,int player) {
    if(player!=1) return psx_keybinds_pad_word(keys,player);
    if(jf2_desktop_open() || jf2_rebind>=0) {jf2_boost_held=false;return 0xFFFF;}
    std::array<uint8_t,SDL_NUM_SCANCODES> clean{};
    for(int i=0;i<SDL_NUM_SCANCODES;++i) {
        if(!keys[i]) jf2_held[i]=0;
        clean[i]=(keys[i] || jf2_pressed_until[i]>s_frame_count) && !jf2_held[i];
    }
    uint32_t mouse=jf2_desktop_mouse_buttons();
    for(int i=1;i<=5;++i) {
        uint32_t bit=SDL_BUTTON_MASK(i);
        if(!(mouse&bit)) { jf2_mouse_held&=~bit; psx_keybinds_release_control(1,PSXKB_MOUSE_SC(i)); }
        else if(jf2_mouse_held&bit) psx_keybinds_suppress_control(1,PSXKB_MOUSE_SC(i));
    }
    jf2_last_pad=psx_keybinds_pad_word(clean.data(),1);
    jf2_boost_held=jf2_settings.jf2_boost && jf2_boost_key()>0 && jf2_boost_key()<SDL_NUM_SCANCODES && clean[jf2_boost_key()];
    if(jf2_settings.jf2_control_style && jf2_camera_supported())
        jf2_last_pad=jf2::strafe_arrows(jf2_last_pad,jf2_settings.jf2_arrow_strafe);
    if(jf2_last_pad!=0xFFFF) {jf2_asserted_pad=jf2_last_pad;jf2_asserted_frame=s_frame_count;}
    return jf2_last_pad;
}

#ifdef COLLECTION_RUNTIME
#include "jf2_profile_controls.h"
#else
static bool jf2_host_input_ready(){return g_players[0].kind==1;}
// These signatures and fixed player identity belong to the supplied PAL W1 overlay.
static bool jf2_camera_supported() {
    return jf2_cpu && psx_read_word(0x800e1528)==0x27bdffc0 &&
        psx_read_word(0x800e1530)==0x3c118013 && psx_read_word(0x800e1534)==0x26316d88 &&
        psx_read_word(0x800e7f1c)==0x3c02800b && psx_read_word(0x800e7f20)==0x8c42c8e4 &&
        psx_read_word(0x800e2b4c)==0x8c82008c && psx_read_word(0x800e1be8)==0x00001021 &&
        psx_read_word(0x800fe684)==0;
}
#endif
extern "C" void jf2_desktop_camera(CPUState* cpu,uint32_t address) {
    const uint32_t pc=address&0x1fffffff, actor=0x80136d88;
    /* Title-screen input and rendering remain entirely native. */
#ifdef COLLECTION_RUNTIME
    jf2_gameplay_camera(cpu,address);
#else
    if(pc!=0xe1528 && pc!=0xe7f1c && pc!=0xe2b4c && pc!=0xe2550 && pc!=0xe2b90) return;
    if(!jf2_camera_supported()) {jf2_move_command=false;return;}
    if(pc==0xe2b90 && jf2_move_command && cpu->gpr[4]==actor) {
        psx_write_word(0x801051d0,jf2_saved_move_pad);
        psx_write_word(actor+0x88,jf2_saved_move_yaw);
        psx_write_word(0x80104418,jf2_saved_move_base);
        psx_write_word(0x801051c8,jf2_saved_move_mode);
        psx_write_word(0x801051cc,jf2_saved_look_mode);
        jf2_move_command=false;
        jf2_move_speed=(int32_t)psx_read_word(actor+0xac);
        return;
    }
    if(pc==0xe2550) {
        // PAL W1: alter the command BEFORE the native ground/air integrator.
        // Never overwrite +94/+AC velocity, vertical state, or collision results.
        if(cpu->gpr[4]!=actor || psx_read_word(0x800e2550)!=0x27bdffd8 ||
            psx_read_word(0x800e28f4)!=0xae0200ac || psx_read_word(0x800e2b90)!=0x27bdffd8 ||
            jf2_move_command || jf2_desktop_open() || savestate_input_guard_active() || g_players[0].kind!=1) return;
        const uint32_t native_pad=psx_read_word(0x801051d0);
        if((jf2_last_pad&0x0c50)!=0x0c50) jf2_keyboard_motion_pending=true;
        if(!(native_pad&0x500c)) jf2_keyboard_motion_pending=false;
        // Attract demos use the same overlay/actor. Do not reinterpret their
        // recorded controller stream as keyboard movement.
        if(!jf2_boost_held && (!jf2_settings.jf2_control_style ||
            (!jf2_keyboard_motion_pending && jf2_injected_pad<0))) return;
        const bool lateral=jf2_settings.jf2_control_style && jf2::lateral_command(jf2::host_pad(native_pad));
        // Forward/backward already have a native command path, including the
        // original jump-state movement modes. Leave those entirely intact.
        if(!lateral && !jf2_boost_held) return;
        const int base=(int32_t)psx_read_word(0x80104418);
        if(base<=0 || base>4096) return;
        jf2_saved_move_pad=psx_read_word(0x801051d0);jf2_saved_move_yaw=psx_read_word(actor+0x88);
        jf2_saved_move_base=base;jf2_saved_move_mode=psx_read_word(0x801051c8);jf2_saved_look_mode=psx_read_word(0x801051cc);
        const uint16_t sampled=jf2::host_pad(jf2_saved_move_pad);
        auto move=jf2::movement(sampled,(int32_t)jf2_saved_move_yaw);
        if(lateral) {
            // A/D are direction commands, not the native L1 run modifier.
            psx_write_word(0x801051d0,jf2::movement_pad(jf2_saved_move_pad,move.active));
            psx_write_word(0x801051c8,0);psx_write_word(0x801051cc,0);
            if(move.active) psx_write_word(actor+0x88,move.angle);
            jf2_move_angle=move.angle;
            if((sampled&0x0c00)!=0x0c00 && move.active) ++jf2_strafe_updates;
        }
        // +FF is floor contact, not an airborne flag. State/vertical speed
        // also exclude the first jump update while contact is still stale.
        const bool airborne=!jf2::grounded(psx_read_byte(actor+0xff),
            (int16_t)psx_read_half(actor+0x18),(int32_t)psx_read_word(actor+0x74));
        const int boosted=jf2::ground_boost(base,jf2_boost_held,airborne,jf2_settings.jf2_boost_percent);
        if(boosted!=base) {psx_write_word(0x80104418,boosted);++jf2_boost_updates;}
        jf2_move_command=true;
        return;
    }
    if(pc==0xe7f1c && (cpu->gpr[31]!=0x800e1b78 || cpu->gpr[17]!=actor)) return;
    if(pc==0xe2b4c && cpu->gpr[4]!=actor) return;
    jf2_camera_frame=s_frame_count;
    if(pc==0xe1528 && jf2_update_frame!=s_frame_count) {jf2_update_frame=s_frame_count;++jf2_updates;}
    if(!jf2_settings.jf2_control_style || !jf2_captured || jf2_desktop_open()) return;
    if(pc==0xe1528) {
        // Apply once before movement/weapon helpers read the player's orientation.
        int yaw=jf2_look.update((int32_t)psx_read_word(actor+0x88),
            (int32_t)psx_read_word(actor+0x8c),s_frame_count,
            jf2_settings.jf2_mouse_sensitivity,jf2_settings.jf2_invert_y);
        psx_write_word(actor+0x88,(uint32_t)yaw);
    }
    if(!jf2_settings.jf2_jump_camera && jf2_look.initialized) {
        psx_write_word(actor+0x8c,(uint32_t)(int32_t)std::lround(jf2_look.pitch));
        // The original pitch integrator uses +98; neutralize its jump assistance.
        if(pc==0xe2b4c) psx_write_word(actor+0x98,0);
    }
#endif
}
static uint16_t jf2_desktop_device_pad(uint16_t raw,int player) {
    if(player!=1) return raw;
    if(jf2_desktop_open()) return 0xFFFF;
    if(jf2_pad_release) { if(raw!=0xFFFF) return 0xFFFF; jf2_pad_release=false; }
    return raw;
}
static void jf2_screenshot() {
    std::error_code ec;auto folder=jf2_dir/"screenshots";std::filesystem::create_directories(folder,ec);
    auto path=folder/("JumpingFlash2-"+std::to_string(GetTickCount64())+".png");
    if(ec || !present_shot_request(path.string().c_str())) {host_osd_push("Screenshot unavailable",2500);return;}
    jf2_shot_sequence=present_shot_seq();
}
static void jf2_quick_load() {
    const uint64_t now=SDL_GetTicks();
    if(now>jf2_load_confirm_until) {
        jf2_load_confirm_until=now+3000;
        host_osd_push("Press F9 again to restore quick slot 7",3000);
        return;
    }
    jf2_load_confirm_until=0;
    jf2_release_inputs();
    savestate_request_load(7);
}
extern "C" void jf2_desktop_integer_rect(int ww,int wh,int*x,int*y,int*w,int*h) {
    if(!jf2_settings.jf2_integer_scaling) return;
    GpuDisplayInfo d;gpu_get_display_info(&d);
    int bh=std::max(1,(int)d.height),bw=bh*4/3;
    jf2::integer_rect(ww,wh,bw,bh,*x,*y,*w,*h);
}
static void jf2_desktop_software_rect(SDL_Rect& dst,int source_h) {
    if(!jf2_settings.jf2_integer_scaling || !sdl_window || source_h<=0) return;
    int ww,wh;SDL_GetWindowSizeInPixels(sdl_window,&ww,&wh);
    double fit=std::min(ww/(double)g_logical_w,wh/(480.0*g_video_scale));
    if(fit<=0) return;
    int x=0,y=0,w=ww,h=wh;
    jf2::integer_rect(ww,wh,source_h*4/3,source_h,x,y,w,h);
    if(std::min(ww/(source_h*4/3),wh/source_h)<1) return;
    dst.x=(int)std::lround((x-(ww-g_logical_w*fit)/2)/fit);
    dst.y=(int)std::lround((y-(wh-480*g_video_scale*fit)/2)/fit);
    dst.w=(int)std::lround(w/fit);dst.h=(int)std::lround(h/fit);
}
extern "C" int jf2_desktop_debug(char* out,int capacity) {
    return std::snprintf(out,capacity,"{\"style\":\"%s\",\"menu\":%s,\"captured\":%s,\"supported\":%s,\"updates\":%llu,\"key_events\":%llu,\"last_scancode\":%d,\"last_keyboard_pad\":%u,\"last_asserted_pad\":%u,\"asserted_frame\":%llu,\"dx\":%.3f,\"dy\":%.3f,\"mouse_events\":%llu,\"last_dx\":%.3f,\"last_dy\":%.3f,\"boost_updates\":%llu,\"strafe_updates\":%llu,\"move_angle\":%d,\"move_speed\":%d,\"messages\":%s,\"native_menu\":%s,\"post_aa\":%d"
#ifdef COLLECTION_RUNTIME
        ",\"control_profile\":\"%s\",\"profile_changes\":%llu"
#endif
        "}",
        jf2_settings.jf2_control_style?"modern":"classic",jf2_desktop_open()?"true":"false",
        jf2_captured?"true":"false",jf2_camera_supported()?"true":"false",
        (unsigned long long)jf2_updates,(unsigned long long)jf2_key_events,jf2_last_key,jf2_last_pad,jf2_asserted_pad,(unsigned long long)jf2_asserted_frame,jf2_look.dx,jf2_look.dy,(unsigned long long)jf2_mouse_events,jf2_last_dx,jf2_last_dy,(unsigned long long)jf2_boost_updates,(unsigned long long)jf2_strafe_updates,jf2_move_angle,jf2_move_speed,jf2_settings.jf2_messages?"true":"false",jf2_settings.jf2_native_menu?"true":"false",gl_renderer_post_aa()
#ifdef COLLECTION_RUNTIME
        ,jf2_profile?jf2_profile->image:"",(unsigned long long)jf2_profile_changes
#endif
        );
}

static void jf2_restart(bool launcher) {
    jf2_save(); jf2_release_inputs();
    auto exe=(jf2_dir/"JumpingFlash2_Recompiled.exe").wstring();
    std::wstring command=L"\""+exe+L"\"";
    command+=L" --game \""+(jf2_dir.parent_path()/"game.toml").wstring()+L"\" --debug-port 4392";
    if(!launcher) command+=L" --no-launcher";
    STARTUPINFOW si{}; si.cb=sizeof(si); PROCESS_INFORMATION pi{};
    SECURITY_ATTRIBUTES sa{sizeof(sa),nullptr,TRUE};
    const auto stamp=std::to_wstring(GetTickCount64());
    HANDLE log=CreateFileW((jf2_dir/"logs"/(L"restart-"+stamp+L".log")).c_str(),GENERIC_WRITE,FILE_SHARE_READ,&sa,CREATE_NEW,FILE_ATTRIBUTE_NORMAL,nullptr);
    if(log==INVALID_HANDLE_VALUE) {host_osd_push("Cannot create restart log; game remains running",4000);return;}
    si.dwFlags=STARTF_USESTDHANDLES;si.hStdOutput=log;si.hStdError=log;si.hStdInput=GetStdHandle(STD_INPUT_HANDLE);
    BOOL started=CreateProcessW(exe.c_str(),command.data(),nullptr,nullptr,TRUE,CREATE_NO_WINDOW,nullptr,jf2_dir.wstring().c_str(),&si,&pi);
    CloseHandle(log);
    if(!started) {
        host_osd_push("Restart failed; current game remains running",4000); return;
    }
    CloseHandle(pi.hThread);CloseHandle(pi.hProcess);shutdown_runtime();std::exit(0);
}
static int jf2_get(void*,const RecompRuntimeUiItem* item,int* out) {
    std::string k=item->key;
    if(k=="style") *out=jf2_settings.jf2_control_style;
    else if(k=="sensitivity") *out=jf2_settings.jf2_mouse_sensitivity;
    else if(k=="invert") *out=jf2_settings.jf2_invert_y;
    else if(k=="jump") *out=jf2_settings.jf2_jump_camera;
    else if(k=="boost") *out=jf2_settings.jf2_boost;
    else if(k=="boostpct") *out=jf2_settings.jf2_boost_percent;
    else if(k=="strafe") *out=jf2_settings.jf2_arrow_strafe;
    else if(k=="messages") *out=jf2_settings.jf2_messages;
    else if(k=="menustyle") *out=jf2_settings.jf2_native_menu;
    else if(k=="aa") *out=jf2_settings.jf2_post_aa;
    else if(k=="geometry") *out=gte_geometry_correction_enabled();
    else if(k=="perspective") *out=gpu_texture_correction_enabled();
    else if(k=="scanlines") *out=g_video_scanlines;
    else if(k=="scanpct") *out=(int)std::lround(g_video_scanline_strength*100);
    else if(k=="fps") *out=fps_telemetry_enabled();
    else if(k=="device") {*out=g_players[0].kind==2?1:0;for(size_t i=2;i<jf2_device_ids.size();++i) if(jf2_device_ids[i]==g_players[0].guid) *out=(int)i;}
    else if(k=="renderer") *out=jf2_renderer_pending?jf2_settings.renderer:g_video_renderer;
    else if(k=="filter") *out=g_video_texfilter;
    else if(k=="volume") *out=jf2_settings.jf2_audio_volume;
    else if(k=="mute") *out=jf2_settings.jf2_muted;
    else if(k=="integer") *out=jf2_settings.jf2_integer_scaling;
    else if(k=="fullscreen") *out=sdl_window && (SDL_GetWindowFlags(sdl_window)&SDL_WINDOW_FULLSCREEN);
    else if(k=="slot") *out=jf2_slot;
    else if(k=="visual") {
        *out=0;auto s=PSXRecompV4::load_user_settings(jf2_dir/"settings.toml");
        if(s.internal_resolution==1 && !s.scanlines && !s.geometry_correction && s.texture_filter==0) *out=1;
        if(s.internal_resolution==1080 && s.geometry_correction && s.perspective_texturing) *out=2;
        if(s.internal_resolution==1 && s.scanlines && s.texture_filter==1) *out=3;
    }
    else if(k=="resolution") { *out=0; for(int i=0;i<7;++i) if(jf2_settings.internal_resolution==jf2_res_lines[i]) *out=i; }
    else if(k=="size") { *out=2;int w=0,h=0;if(sdl_window) SDL_GetWindowSize(sdl_window,&w,&h);for(int i=0;i<4;++i) if(w==jf2_widths[i]) *out=i; }
    else return 0;
    return 1;
}
static int jf2_enabled(void*,const RecompRuntimeUiItem* item) {
    std::string k=item->key;
    if(k=="sensitivity" || k=="invert" || k=="jump") return jf2_settings.jf2_control_style!=0;
    if(k=="strafe") return jf2_settings.jf2_control_style!=0;
    if(k=="boostpct" || k=="boostkey") return jf2_settings.jf2_boost;
    if(k=="aa" || k=="scanlines" || k=="scanpct" || k=="geometry" || k=="perspective") return g_gl_active;
    return 1;
}
static int jf2_set(void*,const RecompRuntimeUiItem* item,int value) {
    auto s=PSXRecompV4::load_user_settings(jf2_dir/"settings.toml");
    if(s.parse_error) return 0;
    std::string k=item->key;
    if(k=="style") jf2_select_style(value);
    else if(k=="visual") {
        if(value==0) return 1;
        s.renderer=1;s.has_renderer=true;s.internal_resolution=value==2?1080:1;s.has_internal_resolution=true;
        s.has_supersampling=true;s.supersampling=1;s.has_antialiasing=true;s.antialiasing=false;
        s.texture_filter=value==3?1:0;s.has_texture_filter=true;
        s.geometry_correction=value==2;s.has_geometry_correction=true;
        s.perspective_texturing=value==2;s.has_perspective_texturing=true;
        s.scanlines=value==3;s.has_scanlines=true;s.scanline_strength=0.35f;s.has_scanline_strength=true;
        jf2_settings.internal_resolution=s.internal_resolution;jf2_settings.renderer=1;jf2_renderer_pending=true;
        recomp_runtime_ui_set_status(jf2_ui,"Visual preset saved. Restart to apply.");
    }
    else if(k=="sensitivity") jf2_settings.jf2_mouse_sensitivity=value;
    else if(k=="invert") jf2_settings.jf2_invert_y=value;
    else if(k=="jump") jf2_settings.jf2_jump_camera=value;
    else if(k=="boost") {jf2_settings.jf2_boost=value;jf2_release_inputs();}
    else if(k=="boostpct") jf2_settings.jf2_boost_percent=value;
    else if(k=="strafe") {jf2_settings.jf2_arrow_strafe=value;jf2_release_inputs();}
    else if(k=="messages") {jf2_settings.jf2_messages=value;host_osd_set_text_visible(value);}
    else if(k=="menustyle") jf2_settings.jf2_native_menu=value;
    else if(k=="aa") {jf2_settings.jf2_post_aa=value;g_video_post_aa=value;gl_renderer_set_post_aa(value);}
    else if(k=="geometry") {gte_geometry_correction_set(value);s.geometry_correction=value;s.has_geometry_correction=true;}
    else if(k=="perspective") {gpu_texture_correction_set(value);s.perspective_texturing=value;s.has_perspective_texturing=true;}
    else if(k=="scanlines" || k=="scanpct") {
        psx_video_set_scanlines(k=="scanlines"?value:g_video_scanlines,k=="scanpct"?value/100.f:g_video_scanline_strength);
        s.scanlines=g_video_scanlines;s.has_scanlines=true;s.scanline_strength=g_video_scanline_strength;s.has_scanline_strength=true;
    }
    else if(k=="device") { if(value<0 || value>=(int)jf2_device_ids.size()) return 0;jf2_release_inputs();set_player_device(g_players[0],jf2_device_ids[value],0);refresh_player_devices();s.p_device[0]=jf2_device_ids[value];s.has_p_device[0]=true; }
    else if(k=="renderer") { s.renderer=value;s.has_renderer=true;jf2_settings.renderer=value;jf2_renderer_pending=true;recomp_runtime_ui_set_status(jf2_ui,"Renderer saved. Restart to apply."); }
    else if(k=="filter") { g_video_texfilter=value;gr_set_texture_filter(value);s.texture_filter=value;s.has_texture_filter=true; }
    else if(k=="fullscreen") { SDL_SetWindowFullscreen(sdl_window,value!=0);s.fullscreen=value;s.has_fullscreen=true; }
    else if(k=="size") { SDL_SetWindowSize(sdl_window,jf2_widths[value],jf2_widths[value]*3/4);if(sdl_renderer) SDL_RenderSetLogicalSize(sdl_renderer,g_logical_w,480*g_video_scale);s.window_width=jf2_widths[value];s.has_window_width=true; }
    else if(k=="resolution") {
        s.internal_resolution=jf2_res_lines[value];s.has_internal_resolution=true;
        jf2_settings.internal_resolution=s.internal_resolution;
        recomp_runtime_ui_set_status(jf2_ui,"Resolution saved. Restart to apply.");
    }
    else if(k=="fps") { (value!=fps_telemetry_enabled()?fps_telemetry_toggle():void());jf2_settings.jf2_fps=value; }
    else if(k=="volume") { jf2_settings.jf2_audio_volume=value;host_volume_set(jf2_settings.jf2_muted?0:value); }
    else if(k=="mute") { jf2_settings.jf2_muted=value;host_volume_set(value?0:jf2_settings.jf2_audio_volume); }
    else if(k=="integer") jf2_settings.jf2_integer_scaling=value;
    else if(k=="slot") jf2_slot=value;
    else return 0;
    jf2_store_desktop(s);PSXRecompV4::save_user_settings(jf2_dir/"settings.toml",s);jf2_save();return 1;
}
static int jf2_action(void*,const RecompRuntimeUiItem* item) {
    std::string k=item->key;
    if(k=="resume") { recomp_runtime_ui_close(jf2_ui);jf2_release_inputs(); }
    else if(k=="mods") {recomp_runtime_ui_enter_section(jf2_ui,2);}
    else if(k=="settings") {recomp_runtime_ui_leave_section(jf2_ui);}
    else if(k=="save") {recomp_runtime_ui_close(jf2_ui);jf2_release_inputs();return savestate_request_save(jf2_slot);}
    else if(k=="load") {recomp_runtime_ui_close(jf2_ui);jf2_release_inputs();return savestate_request_load(jf2_slot);}
    else if(k=="restart") jf2_restart(false);
    else if(k=="launcher") jf2_restart(true);
    else if(k=="exit") {jf2_save();shutdown_runtime();std::exit(0);}
    else if(k=="logs") ShellExecuteW(nullptr,L"open",(jf2_dir/"logs").wstring().c_str(),nullptr,nullptr,SW_SHOWNORMAL);
    else if(k=="defaults") {
        jf2_release_inputs();jf2_default_bindings();
        jf2_boost_key()=SDL_SCANCODE_LSHIFT;jf2_settings.jf2_boost=false;jf2_settings.jf2_boost_percent=125;
        if(jf2_settings.jf2_control_style) {jf2_settings.jf2_mouse_sensitivity=100;jf2_settings.jf2_invert_y=false;jf2_settings.jf2_jump_camera=false;}
        if(jf2_settings.jf2_control_style) jf2_settings.jf2_arrow_strafe=true;
        jf2_save();
    }
    else if(k=="shot") {recomp_runtime_ui_close(jf2_ui);jf2_release_inputs();jf2_screenshot();}
    else if(k=="shots") ShellExecuteW(nullptr,L"open",(jf2_dir/"screenshots").wstring().c_str(),nullptr,nullptr,SW_SHOWNORMAL);
    else if(k=="help") {jf2_guide_until=SDL_GetTicks()+10000;recomp_runtime_ui_set_toast(jf2_ui,"Control guide",jf2_settings.jf2_control_style?"W/S forward/back; A/D strafe.\nLeft/right arrows: strafe or turn.\nHold assigned boost key (Shift).\nSpace: jump again in air.\nMouse: look / fire / fireworks.\nEscape: settings; F5/F9: states.":"Arrows move/turn; Q/W sidestep.\nHold assigned boost key (Shift).\nX jump, Z fire, S fireworks.\nEnter Start; Escape settings.\nF5 saves slot 7; F9 twice restores.\nF12 screenshot.");}
    else if(k=="boostkey") {jf2_rebind=16;recomp_runtime_ui_set_status(jf2_ui,"Unused keyboard key; Esc cancels.");}
    else if(k.rfind("bind",0)==0) {jf2_rebind=std::stoi(k.substr(4));recomp_runtime_ui_set_status(jf2_ui,"Press key / mouse. Esc cancels.");}
    else return 0;
    return 1;
}
static void jf2_menu_create() {
    jf2_device_names={"Keyboard / mouse","First available gamepad"};jf2_device_ids={"keyboard","auto"};
    int count=0;SDL_JoystickID* ids=SDL_GetGamepads(&count);
    for(int i=0;i<count;++i) {char guid[40]{};SDL_GUIDToString(SDL_GetGamepadGUIDForID(ids[i]),guid,sizeof(guid));const char* name=SDL_GetGamepadNameForID(ids[i]);jf2_device_names.emplace_back(name?name:"Gamepad");jf2_device_ids.emplace_back(guid);}
    SDL_free(ids);
    for(auto& name:jf2_device_names) jf2_devices.push_back(name.c_str());
    auto add=[](const char*k,const char*s,const char*l,RecompRuntimeUiItemType t,int lo,int hi,const char*const*c=nullptr,int n=0,const char*d="") {
        RecompRuntimeUiItem i{};i.key=k;i.section=s;i.label=l;i.type=t;i.minimum=lo;i.maximum=hi;i.step=1;i.choices=c;i.choice_count=n;i.description=d;jf2_items.push_back(i);
    };
    add("resume","Game","Resume game",RECOMP_RUNTIME_UI_ACTION,0,0);
    add("mods","Game","Mods",RECOMP_RUNTIME_UI_ACTION,0,0,nullptr,0,"Boost, messages and menu appearance.");
    add("settings","Game","All settings",RECOMP_RUNTIME_UI_ACTION,0,0);
    add("style","Game","Control style",RECOMP_RUNTIME_UI_CHOICE,0,1,jf2_styles,2);
    add("help","Controls","Show control guide",RECOMP_RUNTIME_UI_ACTION,0,0,nullptr,0,"Modern: click gameplay for mouse look.");
    add("device","Controls","Input device",RECOMP_RUNTIME_UI_CHOICE,0,(int)jf2_devices.size()-1,jf2_devices.data(),(int)jf2_devices.size(),"Devices at startup. Restart to refresh.");
    add("sensitivity","Controls","Mouse sensitivity %",RECOMP_RUNTIME_UI_INT,10,300);
    add("invert","Controls","Invert mouse Y",RECOMP_RUNTIME_UI_BOOL,0,1);
    add("jump","Controls","Modern jump camera assistance",RECOMP_RUNTIME_UI_BOOL,0,1);
    add("strafe","Controls","Left/right arrows strafe",RECOMP_RUNTIME_UI_BOOL,0,1,nullptr,0,"Modern: arrows strafe; A/D always do.");
    add("boost","Mods","Ground movement booster",RECOMP_RUNTIME_UI_BOOL,0,1,nullptr,0,"Optional ground boost; native air.");
    add("boostkey","Mods",jf2_boost_label,RECOMP_RUNTIME_UI_ACTION,0,0);
    add("boostpct","Mods","Boost speed %",RECOMP_RUNTIME_UI_INT,125,200);
    add("messages","Mods","Top-left messages",RECOMP_RUNTIME_UI_BOOL,0,1,nullptr,0,"Hide host text; game HUD stays.");
    add("menustyle","Mods","Menu presentation",RECOMP_RUNTIME_UI_CHOICE,0,1,jf2_menu_styles,2);
    add("defaults","Controls","Restore preset defaults",RECOMP_RUNTIME_UI_ACTION,0,0);
    for(int i=0;i<16;++i) add(jf2_bind_keys[i],"Bindings",jf2_bind_labels[i],RECOMP_RUNTIME_UI_ACTION,0,0);
    add("renderer","Display","Renderer",RECOMP_RUNTIME_UI_CHOICE,0,1,jf2_renderers,2,"Restart required. GL / Software only.");
    add("visual","Display","Visual preset",RECOMP_RUNTIME_UI_CHOICE,0,3,jf2_visuals,4,"Restart required; HD is experimental.");
    add("resolution","Display","Internal resolution",RECOMP_RUNTIME_UI_CHOICE,0,6,jf2_resolutions,7,"Restart required; Software up to 4x.");
    add("size","Display","Window size",RECOMP_RUNTIME_UI_CHOICE,0,3,jf2_sizes,4);
    add("fullscreen","Display","Borderless fullscreen",RECOMP_RUNTIME_UI_BOOL,0,1);
    add("integer","Display","Integer scaling",RECOMP_RUNTIME_UI_BOOL,0,1,nullptr,0,"4:3 whole pixels; small windows fit.");
    add("filter","Display","Texture filtering",RECOMP_RUNTIME_UI_CHOICE,0,2,jf2_filters,3);
    add("aa","Display","Edge smoothing",RECOMP_RUNTIME_UI_CHOICE,0,2,jf2_aa,3,"OpenGL: live FXAA; sharp menu text.");
    add("geometry","Display","Stable geometry",RECOMP_RUNTIME_UI_BOOL,0,1,nullptr,0,"GL, experimental. Use HD resolution.");
    add("perspective","Display","Perspective textures",RECOMP_RUNTIME_UI_BOOL,0,1,nullptr,0,"GL, experimental. Off fixes distortion.");
    add("scanlines","Display","CRT scanlines",RECOMP_RUNTIME_UI_BOOL,0,1);
    add("scanpct","Display","Scanline strength %",RECOMP_RUNTIME_UI_INT,0,100);
    add("fps","Display","FPS display",RECOMP_RUNTIME_UI_BOOL,0,1);
    add("shot","Game","Take screenshot (F12)",RECOMP_RUNTIME_UI_ACTION,0,0);
    add("shots","Game","Open screenshots",RECOMP_RUNTIME_UI_ACTION,0,0);
    add("volume","Audio","Volume",RECOMP_RUNTIME_UI_INT,0,100);
    add("mute","Audio","Mute",RECOMP_RUNTIME_UI_BOOL,0,1);
    add("slot","Game","Save state slot",RECOMP_RUNTIME_UI_INT,0,9);
    add("save","Game","Save state",RECOMP_RUNTIME_UI_ACTION,0,0);
    add("load","Game","Load state",RECOMP_RUNTIME_UI_ACTION,0,0);
    add("restart","Game","Restart game",RECOMP_RUNTIME_UI_ACTION,0,0);
    add("launcher","Game","Return to launcher",RECOMP_RUNTIME_UI_ACTION,0,0);
    add("logs","Game","Open diagnostic logs",RECOMP_RUNTIME_UI_ACTION,0,0);
    add("exit","Game","Exit",RECOMP_RUNTIME_UI_ACTION,0,0);
    RecompRuntimeUiConfig c{};c.title="Jumping Flash! 2";c.subtitle="PAUSE / MODS";c.theme="psx";c.items=jf2_items.data();c.item_count=jf2_items.size();c.callbacks.get_value=jf2_get;c.callbacks.set_value=jf2_set;c.callbacks.run_action=jf2_action;
    c.callbacks.is_enabled=jf2_enabled;jf2_ui=recomp_runtime_ui_create(&c);
}
static void jf2_desktop_init(const std::filesystem::path& dir) {
    jf2_dir=dir; jf2_settings=PSXRecompV4::load_user_settings(dir/"settings.toml");
    jf2_settings.jf2_boost=false;
    jf2_settings.jf2_post_aa=0;
    jf2_settings.jf2_messages=false;
    std::error_code logs_error;std::filesystem::create_directories(dir/"logs",logs_error);std::filesystem::create_directories(dir/"screenshots",logs_error);
    if(!jf2_settings.has_window_width) { jf2_settings.has_window_width=true;jf2_settings.window_width=1280; }
    if(!jf2_settings.has_internal_resolution) {jf2_settings.has_internal_resolution=true;jf2_settings.internal_resolution=1;}
    if(!jf2_settings.has_fullscreen) {jf2_settings.has_fullscreen=true;jf2_settings.fullscreen=0;}
    host_volume_set(jf2_settings.jf2_muted?0:jf2_settings.jf2_audio_volume);
    host_osd_set_text_visible(jf2_settings.jf2_messages);
    if(!jf2_settings.parse_error) PSXRecompV4::save_user_settings(dir/"settings.toml",jf2_settings);
    psx_keybinds_init((dir/"JumpingFlash2_Recompiled.exe").string().c_str());
    // Preserve the original keyboard profile on the first desktop launch.
    if(!std::filesystem::exists(dir/"keybinds-classic.ini")) {
        std::error_code ec;std::filesystem::copy_file(dir/"keybinds.ini",dir/"keybinds-classic.ini",std::filesystem::copy_options::none,ec);
    }
    jf2_desktop_reload_bindings();jf2_initialized=true;
    (jf2_settings.jf2_fps!=fps_telemetry_enabled()?fps_telemetry_toggle():void());
}
void jf2_launcher_controls() {
    if(!jf2_initialized) return;
    ImGui::SeparatorText("CONTROL STYLE");
    int style=jf2_settings.jf2_control_style;
    if(ImGui::Combo("Classic / Modern",&style,jf2_styles,2)) jf2_select_style(style);
    ImGui::TextWrapped(style?"Modern: WASD, Space to jump, mouse to look and fire. Use the shared pause menu for settings.":"Classic: arrow keys and original PlayStation buttons. Original jump camera; mouse capture disabled.");
    if(style) {
        if(ImGui::SliderInt("Mouse sensitivity %",&jf2_settings.jf2_mouse_sensitivity,10,300)) jf2_save();
        if(ImGui::Checkbox("Invert mouse Y",&jf2_settings.jf2_invert_y)) jf2_save();
        if(ImGui::Checkbox("Original jump camera assistance",&jf2_settings.jf2_jump_camera)) jf2_save();
        if(ImGui::Checkbox("Left/right arrows strafe",&jf2_settings.jf2_arrow_strafe)) jf2_save();
    }
}
bool jf2_launcher_event(const SDL_Event& e) {
    (void)e;
    return false;
}
void jf2_launcher_display() {
    // JF2-specific graphical mods are disabled in compatibility mode.
}
int jf2_launcher_navigation() {
    static int page=0;const char* pages[]={"Play","Display","Controls","Audio","Exit"};
    for(int i=0;i<5;++i) {if(i) ImGui::SameLine();if(ImGui::Selectable(pages[i],page==i,0,ImVec2(110,32))) page=i;}
    ImGui::Separator();return page;
}
void jf2_launcher_audio(int* volume) {
    if(jf2_settings.jf2_audio_volume!=*volume) {jf2_settings.jf2_audio_volume=*volume;jf2_save();}
    if(ImGui::Checkbox("Mute",&jf2_settings.jf2_muted)) jf2_save();
}
static void jf2_pointer(int x,int y,int width,int height,int direction) {
    auto* ui=jf2_ui;if(!ui || !ui->open) return;
    int scale=std::max(1,height/224),margin=6*scale,pw=std::min(244*scale,width-2*margin),px=(width-pw)/2;
    int extra=0;
    if(ui->config.subtitle && (int)(strlen(ui->config.title)+strlen(ui->config.subtitle))*6*scale+4*scale>pw-16*scale) extra=10*scale;
    int ly=margin+32*scale+extra,fy=height-margin-28*scale,rh=15*scale,visible=std::max(1,(fy-ly)/rh);
    if(x<px || x>px+pw) return;
    if(y>=margin && y<ly-3*scale) {recomp_runtime_ui_leave_section(ui);return;}
    size_t selected=ui->in_section?ui->row_index:ui->section_index;
    size_t first=selected>=(size_t)visible?selected-visible+1:0;
    int line=(y-ly+3*scale)/rh;
    if(y<ly-3*scale || line<0 || line>=visible) return;
    size_t row=first+line,count=ui->in_section?recomp_runtime_ui_section_item_count(ui,ui->section_index):ui->section_count;
    if(row>=count) return;
    if(!ui->in_section) recomp_runtime_ui_enter_section(ui,row);
    else { ui->row_index=row;recomp_runtime_ui_adjust_current(ui,direction,1,0); }
}
static bool jf2_desktop_event(const SDL_Event& e) {
    if(!jf2_initialized) return false;
    if(e.type==SDL_EVENT_KEY_DOWN) { ++jf2_key_events;jf2_last_key=e.key.scancode; }
    if(e.type==SDL_EVENT_KEY_UP && e.key.scancode<SDL_NUM_SCANCODES) jf2_held[e.key.scancode]=0;
    if(e.type==SDL_EVENT_WINDOW_FOCUS_LOST || e.type==SDL_EVENT_WINDOW_MINIMIZED || e.type==SDL_EVENT_WINDOW_HIDDEN) {
        jf2_release_inputs();
        return false;
    }
    if(jf2_desktop_open()) return false; // Shared collection pause menu owns pause input.
    if(e.type==SDL_EVENT_KEY_DOWN && !e.key.repeat) {
        if(e.key.scancode==SDL_SCANCODE_F5) { savestate_request_save(7); return true; }
        if(e.key.scancode==SDL_SCANCODE_F9) { jf2_quick_load(); return true; }
        if(e.key.scancode==SDL_SCANCODE_F12) { jf2_screenshot(); return true; }
        if(e.key.scancode==SDL_SCANCODE_ESCAPE && jf2_captured) { jf2_release_mouse(); return true; }
    }
    // Keep short SDL taps visible to the slower guest pad poller.
    if(e.type==SDL_EVENT_KEY_DOWN && !e.key.repeat && e.key.scancode<SDL_NUM_SCANCODES)
        jf2_pressed_until[e.key.scancode]=s_frame_count+4;
    if(e.type==SDL_EVENT_MOUSE_BUTTON_DOWN && e.button.button<=5)
        jf2_mouse_until[e.button.button]=s_frame_count+4;
    const bool gameplay=jf2_camera_supported() && s_frame_count-jf2_camera_frame<8;
    if(jf2_captured && (!gameplay || savestate_input_guard_active())) jf2_release_mouse();
    if(jf2_settings.jf2_control_style && !jf2_captured && e.type==SDL_EVENT_MOUSE_BUTTON_DOWN && e.button.button==SDL_BUTTON_LEFT) {
        if(gameplay && jf2_host_input_ready() && !g_headless && sdl_window &&
            (SDL_GetWindowFlags(sdl_window)&SDL_WINDOW_INPUT_FOCUS)) {
            jf2_captured=SDL_SetWindowRelativeMouseMode(sdl_window,true);jf2_look.clear();
            jf2_mouse_until[1]=0;jf2_mouse_held|=SDL_BUTTON_LMASK;psx_keybinds_suppress_control(1,PSXKB_MOUSE_SC(1));
        } else host_osd_push("Mouse look is available in supported World 1 gameplay",2500);
        return true;
    }
    if(jf2_captured && e.type==SDL_EVENT_MOUSE_MOTION) {
        ++jf2_mouse_events;jf2_last_dx=e.motion.xrel;jf2_last_dy=e.motion.yrel;
        jf2_look.move(e.motion.xrel,e.motion.yrel);return true;
    }
    return false;
}
extern "C" int jf2_desktop_image(const uint32_t** pixels,int* width,int* height) {
    (void)pixels;(void)width;(void)height;
    return 0;
}
extern "C" void jf2_desktop_gl_draw(SDL_Window* window) { (void)window; }
static void jf2_update_labels() {
    std::snprintf(jf2_boost_label,sizeof(jf2_boost_label),"Boost key [%s]",SDL_GetScancodeName((SDL_Scancode)jf2_boost_key()));
    for(int i=0;i<16;++i) {
        auto sc=psx_keybinds_get_button(1,i);
        const char* name=PSXKB_IS_MOUSE_SC(sc)?(sc==PSXKB_MOUSE_SC(1)?"Mouse left":sc==PSXKB_MOUSE_SC(3)?"Mouse right":"Mouse"):SDL_GetScancodeName(sc);
        const char* label=psx_keybinds_button_label(i);
        if(jf2_settings.jf2_control_style && i==PSX_KB_L1) label="Strafe left / L1";
        if(jf2_settings.jf2_control_style && i==PSX_KB_R1) label="Strafe right / R1";
        std::snprintf(jf2_bind_labels[i],80,"%s [%s]",label,name&&*name?name:"Unbound");
    }
}
static void jf2_desktop_tick() {
    if(!jf2_initialized || g_headless) return;
    const bool restoring=savestate_input_guard_active();
    if(restoring && !jf2_restoring) {
        jf2_release_inputs();jf2_update_frame=UINT64_MAX;jf2_move_command=false;
        jf2_title_actor=0;jf2_title_accept=false;
    }
    jf2_restoring=restoring;
    if(jf2_shot_sequence>=0 && present_shot_seq()!=jf2_shot_sequence) {
        host_osd_push(present_shot_ok()?"Screenshot saved in screenshots":"Screenshot could not be saved",2500);
        jf2_shot_sequence=-1;
    }
    if(jf2_captured && (!jf2_camera_supported() || s_frame_count-jf2_camera_frame>8 || restoring)) {
        jf2_release_inputs();
        host_osd_push("Mouse released during transition. Click gameplay to recapture.",2500);
    }
    GpuDisplayInfo di;gpu_get_display_info(&di);
    if(SDL_GetTicks()>jf2_compile_probe) {
        jf2_compile_probe=SDL_GetTicks()+500;char status[2048]{};autocompile_status_json(status,sizeof(status));
        jf2_compiling=std::strstr(status,"\"state\":\"running\"") || std::strstr(status,"\"state\": \"running\"");
    }
    const bool stalled=jf2_cpu && jf2_cpu->cop0[14]==0 && (jf2_cpu->cop0[13]&0x7c)==0x20;
    if(di.disabled || stalled || jf2_compiling) {
        const uint64_t now=SDL_GetTicks();if(!jf2_blank_since) jf2_blank_since=now;
        host_osd_set_status(jf2_compiling?"Compiling game code... Use the shared pause menu":now-jf2_blank_since>15000?"Still waiting for the game. Use the shared pause menu":"Loading game / compiling code...");
    } else if(jf2_blank_since) {jf2_blank_since=0;host_osd_set_status(nullptr);}
}
