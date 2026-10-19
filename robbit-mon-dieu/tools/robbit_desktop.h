#pragma once
static RobbitMouseLook robbit_look;
static bool robbit_captured=false, robbit_modern=true, robbit_invert=false;
static bool robbit_compat_mouse=false, robbit_recenter=false;
static int robbit_sensitivity=100;
static int robbit_move_x=0, robbit_move_forward=0;
static uint64_t robbit_move_until=0;
static uint64_t robbit_move_updates=0;
static uint64_t robbit_vector_calls=0;
static uint32_t robbit_vector_ra=0,robbit_vector_a2=0,robbit_vector_a3=0;
static uint64_t robbit_player_frame=0, robbit_mouse_events=0, robbit_camera_updates=0;
static uint64_t robbit_motion_frame=UINT64_MAX;
static uint32_t robbit_blocked_mouse=0;
static std::array<uint64_t,6> robbit_mouse_until{};

static bool robbit_host_input_ready(){
#ifdef COLLECTION_RUNTIME
    return collection_mode||g_players[0].kind==1;
#else
    return g_players[0].kind==1;
#endif
}

#ifdef COLLECTION_RUNTIME
#include "robbit_profile_controls.h"
#else
static bool robbit_supported() {
    // Supplied English common gameplay executable: player update, physical
    // rotation transfer, camera setter and mode getter. No JF2 offsets.
    return psx_read_word(0x800a2778)==0x27bdffb8 &&
        psx_read_word(0x800a2784)==0x2471bc00 &&
        psx_read_word(0x800a4414)==0x0c01e5ae &&
        psx_read_word(0x800a4554)==0xae220010 &&
        psx_read_word(0x800a24c0)==0x2451bc00 &&
        psx_read_word(0x8008a464)==0xa4430d90 &&
        psx_read_word(0x800adac4)==0x8c43101c &&
        psx_read_word(0x800a3f5c)==0x0c026703 &&
        psx_read_word(0x800a6844)==0x0c026703 &&
        psx_read_word(0x80099c0c)==0x10a00016;
}
static bool robbit_gameplay() {
    return robbit_supported() && robbit_live_flags(psx_read_word(0x800d101c),
        (int16_t)psx_read_half(0x800d0f5a),
        (int16_t)psx_read_half(0x800d0f5c)|(int16_t)psx_read_half(0x800d0f5e)) &&
        robbit_player_frame && s_frame_count-robbit_player_frame<8;
}
#endif
static void robbit_release_mouse() {
    if (robbit_captured) {
#if defined(PSX_SDL3)
        if (robbit_compat_mouse) { SDL_SetWindowMouseGrab(sdl_window,false); SDL_ShowCursor(); }
        else SDL_SetWindowRelativeMouseMode(sdl_window,false);
#else
        SDL_SetRelativeMouseMode(SDL_FALSE);
#endif
    }
    robbit_captured=false; robbit_look.clear(); robbit_pulses.block_held(SDL_GetKeyboardState(nullptr));
    robbit_move_x=robbit_move_forward=0;
    robbit_recenter=false;
    robbit_mouse_until.fill(0); robbit_motion_frame=UINT64_MAX;
    robbit_blocked_mouse=SDL_GetMouseState(nullptr,nullptr);
}
static void robbit_desktop_tick() {
    if (robbit_captured && (!robbit_gameplay() || savestate_input_guard_active() || !robbit_host_input_ready() ||
        !(SDL_GetWindowFlags(sdl_window)&SDL_WINDOW_INPUT_FOCUS))) robbit_release_mouse();
    if (robbit_captured && robbit_compat_mouse && robbit_recenter) {
        int width=0,height=0; SDL_GetWindowSize(sdl_window,&width,&height);
        SDL_WarpMouseInWindow(sdl_window,width/2,height/2); robbit_recenter=false;
    }
}
#ifndef COLLECTION_RUNTIME
extern "C" void robbit_desktop_camera(CPUState* cpu,uint32_t address) {
    const uint32_t pc=address&0x1fffffff;
    if (pc!=0xa2778 && pc!=0xa441c && pc!=0xa24b4 && pc!=0x99c0c) return;
    if (!robbit_supported()) return;
    if (pc==0xa2778) robbit_player_frame=s_frame_count;
    // Change only the native walking vector's heading, before its trigonometry.
    // Preserve guest acceleration, speed, jump physics and collision integration.
    if (pc==0x99c0c) {
        ++robbit_vector_calls; robbit_vector_ra=cpu->gpr[31]; robbit_vector_a2=cpu->gpr[6]; robbit_vector_a3=cpu->gpr[7];
        if (robbit_modern && g_players[0].kind==1 && robbit_gameplay() &&
            !savestate_input_guard_active() && SDL_GetTicks()<robbit_move_until && (robbit_move_x || robbit_move_forward) &&
            (cpu->gpr[31]==0x800a3f64 || cpu->gpr[31]==0x800a684c) &&
            cpu->gpr[6]==0x800dbc28 && cpu->gpr[7]==0x800dbc20) {
            cpu->gpr[4]=psx_read_word(0x800dbc14)+(uint32_t)(robbit_move_angle(robbit_move_x,robbit_move_forward)*4096);
            ++robbit_move_updates;
        }
        return;
    }
    if (!robbit_modern || !robbit_captured || !robbit_gameplay() || savestate_input_guard_active()) return;
    if (pc==0xa2778 && robbit_motion_frame!=s_frame_count) {
        robbit_motion_frame=s_frame_count;
        int yaw=robbit_look.update((int32_t)psx_read_word(0x800dbc14)/4096,
            (int32_t)psx_read_word(0x800dbc10)/4096,robbit_sensitivity,robbit_invert);
        psx_write_word(0x800dbc14,(uint32_t)(yaw*4096));
        psx_write_word(0x800dbc10,(uint32_t)((int)std::lround(robbit_look.pitch)*4096));
        ++robbit_camera_updates;
    }
    if (!robbit_look.initialized) return;
    const int pitch=(int)std::lround(robbit_look.pitch);
    if (pc==0xa441c && cpu->gpr[17]==0x800dbc00 && cpu->gpr[31]==0x800a441c) {
        const uint32_t physical=psx_read_word(0x800dbc48);
        if (physical>=0x80050000 && physical<0x801fff00 && !(physical&3))
            psx_write_half(physical+0x28,(uint16_t)pitch);
    }
    // Keep aim stable through jump camera assistance. Native position, velocity,
    // jump timing, collisions and objectives stay intact.
    if (pc==0xa24b4) psx_write_word(0x800dbc10,(uint32_t)(pitch*4096));
}
#endif
static uint16_t robbit_input_pad(const uint8_t* keys,int player) {
    if (player!=1) return psx_keybinds_pad_word(keys,player);
    // A menu confirmation held through Resume must not become movement/bomb.
    static bool was_gameplay=false;
    const bool gameplay=robbit_gameplay();
    if (gameplay!=was_gameplay) {
        was_gameplay=gameplay;
        robbit_pulses.block_held(SDL_GetKeyboardState(nullptr));
        robbit_move_x=robbit_move_forward=0;
        return 0xffff;
    }
    if (!robbit_modern || !gameplay) {
        robbit_move_x=robbit_move_forward=0;
        return psx_keybinds_pad_word(keys,player);
    }
    std::array<uint8_t,SDL_NUM_SCANCODES> clean{};
    std::copy(keys,keys+SDL_NUM_SCANCODES,clean.begin());
    for (int sc : {SDL_SCANCODE_W,SDL_SCANCODE_A,SDL_SCANCODE_S,SDL_SCANCODE_D,
                   SDL_SCANCODE_SPACE,SDL_SCANCODE_E,SDL_SCANCODE_F}) clean[sc]=0;
    uint16_t pad=psx_keybinds_pad_word(clean.data(),player);
    const int move_x=int(keys[SDL_SCANCODE_D]!=0)-int(keys[SDL_SCANCODE_A]!=0);
    const int move_forward=int(keys[SDL_SCANCODE_W]!=0)-int(keys[SDL_SCANCODE_S]!=0);
    if (move_x || move_forward) {
        robbit_move_x=move_x; robbit_move_forward=move_forward;
        robbit_move_until=SDL_GetTicks()+120;
        pad&=~0x0010u;
    }
    if (keys[SDL_SCANCODE_SPACE]) pad&=~0x4000u;
    if (keys[SDL_SCANCODE_E]) pad&=~0x1000u;
    if (keys[SDL_SCANCODE_F]) pad&=~0x2000u;
    uint32_t mouse=SDL_GetMouseState(nullptr,nullptr);
    for (int b=1;b<=5;++b) {
        const uint32_t bit=SDL_BUTTON_MASK(b);
        if (!(mouse&bit)) robbit_blocked_mouse&=~bit;
        if (robbit_mouse_until[b]>SDL_GetTicks()) mouse|=bit;
    }
    mouse&=~robbit_blocked_mouse;
    if (robbit_captured) {
        if (mouse&SDL_BUTTON_LMASK) pad&=~0x8000u;
        if (mouse&SDL_BUTTON_RMASK) pad&=~0x2000u;
    }
    return pad;
}
static bool robbit_input_event(const SDL_Event& e) {
#if defined(PSX_SDL3)
    const bool lost=e.type==SDL_EVENT_WINDOW_FOCUS_LOST;
#else
    const bool lost=e.type==SDL_WINDOWEVENT && e.window.event==SDL_WINDOWEVENT_FOCUS_LOST;
#endif
    if (lost) { robbit_release_mouse(); return false; }
    if (robbit_captured && (!robbit_gameplay() || savestate_input_guard_active())) robbit_release_mouse();
    if (e.type==SDL_KEYDOWN) {
#if defined(PSX_SDL3)
        const int sc=e.key.scancode;
#else
        const int sc=e.key.keysym.scancode;
#endif
        if (sc==SDL_SCANCODE_ESCAPE && robbit_captured) { robbit_release_mouse(); return true; }
        if (e.key.repeat) return false;
        if (sc==SDL_SCANCODE_F6 && robbit_modern) {
            robbit_release_mouse(); robbit_compat_mouse=!robbit_compat_mouse;
            host_osd_push(robbit_compat_mouse?"Compatibility mouse. Click gameplay to capture.":"Raw mouse. Click gameplay to capture.",2500);
            return true;
        }
        if (robbit_modern && robbit_gameplay() && (sc==SDL_SCANCODE_SPACE || sc==SDL_SCANCODE_E || sc==SDL_SCANCODE_F))
            robbit_pulses.press(sc,SDL_GetTicks());
        if (robbit_modern && robbit_gameplay() &&
            (sc==SDL_SCANCODE_W || sc==SDL_SCANCODE_A || sc==SDL_SCANCODE_S || sc==SDL_SCANCODE_D)) {
            robbit_pulses.press(sc,SDL_GetTicks()); return false;
        }
        for (int b=PSX_KB_UP;b<=PSX_KB_SELECT;++b)
            if (sc==psx_keybinds_get_button(1,b) || sc==psx_keybinds_get_button_alt(1,b))
                robbit_pulses.press(sc,SDL_GetTicks());
    }
    if (e.type==SDL_MOUSEBUTTONUP && e.button.button<=5) {
        robbit_blocked_mouse&=~SDL_BUTTON_MASK(e.button.button);
        psx_keybinds_release_control(1,PSXKB_MOUSE_SC(e.button.button));
    }
    if (e.type==SDL_MOUSEBUTTONDOWN && e.button.button<=5) {
        if (robbit_modern && !robbit_captured && e.button.button==SDL_BUTTON_LEFT && robbit_gameplay() && !savestate_input_guard_active() &&
            robbit_host_input_ready() && (SDL_GetWindowFlags(sdl_window)&SDL_WINDOW_INPUT_FOCUS)) {
#if defined(PSX_SDL3)
            if (robbit_compat_mouse) {
                robbit_captured=SDL_SetWindowMouseGrab(sdl_window,true);
                if (robbit_captured) { SDL_HideCursor(); robbit_recenter=true; }
            } else robbit_captured=SDL_SetWindowRelativeMouseMode(sdl_window,true);
#else
            robbit_captured=SDL_SetRelativeMouseMode(SDL_TRUE)==0;
#endif
            robbit_look.clear(); robbit_mouse_until.fill(0);
            robbit_blocked_mouse|=SDL_BUTTON_LMASK;
            psx_keybinds_suppress_control(1,PSXKB_MOUSE_SC(1));
            host_osd_push(robbit_captured?"Mouse look on. Escape releases the mouse.":"Mouse capture failed.",2000);
            return true;
        }
        if (robbit_captured && !(robbit_blocked_mouse&SDL_BUTTON_MASK(e.button.button)))
            robbit_mouse_until[e.button.button]=SDL_GetTicks()+80;
    }
    if (robbit_captured && e.type==SDL_MOUSEMOTION) {
        if (robbit_compat_mouse) {
            int width=0,height=0; SDL_GetWindowSize(sdl_window,&width,&height);
            const double dx=e.motion.x-width/2, dy=e.motion.y-height/2;
            if (std::abs(dx)<1 && std::abs(dy)<1) return true;
            robbit_recenter=true;
            // Absolute-pointer mode must measure from its warp target. SDL's
            // relative delta can include a queued recenter and feed back aim.
            robbit_look.move(dx,dy);
        } else {
            robbit_look.move(e.motion.xrel,e.motion.yrel);
        }
        ++robbit_mouse_events; return true;
    }
    return false;
}
extern "C" int robbit_desktop_status_json(char* out,int cap) {
#ifdef COLLECTION_RUNTIME
    const bool supported=robbit_supported();
    const uint32_t actor=supported?robbit_profile->player:0;
#else
    const bool supported=robbit_supported();
    const uint32_t actor=supported?0x800dbc00:0;
#endif
    int used=std::snprintf(out,(size_t)cap,
        "\"supported\":%d,\"gameplay\":%d,\"captured\":%d,\"compatibility_mouse\":%d,\"modern\":%d,\"sensitivity\":%d,\"invert_y\":%d,\"mouse_events\":%llu,\"camera_updates\":%llu,\"move_updates\":%llu,\"vector_calls\":%llu,\"vector_ra\":%u,\"vector_a2\":%u,\"vector_a3\":%u,\"yaw\":%d,\"pitch\":%d",
        supported,robbit_gameplay(),robbit_captured,robbit_compat_mouse,robbit_modern,robbit_sensitivity,robbit_invert,
        (unsigned long long)robbit_mouse_events,(unsigned long long)robbit_camera_updates,
        (unsigned long long)robbit_move_updates,
        (unsigned long long)robbit_vector_calls,robbit_vector_ra,robbit_vector_a2,robbit_vector_a3,
        actor?(int32_t)psx_read_word(actor+0x14)/4096:0,actor?(int32_t)psx_read_word(actor+0x10)/4096:0);
#ifdef COLLECTION_RUNTIME
    if(used>=0&&used<cap)used+=std::snprintf(out+used,(size_t)(cap-used),
        ",\"control_profile\":\"%s\",\"profile_changes\":%llu",robbit_profile?robbit_profile->image:"",
        (unsigned long long)robbit_profile_changes);
#endif
    return used;
}
