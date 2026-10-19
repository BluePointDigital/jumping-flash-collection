#pragma once
#include "jf1_controls_core.h"
#include "jf1_profiles.h"
static const Jf1Profile* jf1_profile=nullptr;
static uint64_t jf1_player_frame=0,jf1_motion_frame=UINT64_MAX;
static uint64_t jf1_look_updates=0,jf1_move_updates=0;
static uint64_t jf1_hook_calls=0,jf1_guard_failures=0;
static uint32_t jf1_last_hook=0,jf1_bad_guard=0;
static jf1::Look jf1_look;
static bool jf1_captured=false,jf1_input_previous=false;
static bool jf1_compat_mouse=false,jf1_recenter=false,jf1_mouse_mode_initialized=false;
static std::array<uint8_t,SDL_NUM_SCANCODES> jf1_blocked_keys{};
static std::array<uint64_t,SDL_NUM_SCANCODES> jf1_key_until{};
static std::array<uint64_t,6> jf1_mouse_until{};
static uint32_t jf1_blocked_mouse=0;
static float jf1_move_x=0,jf1_move_forward=0,jf1_pad_x=0,jf1_pad_forward=0;
static void jf1_release_inputs();
static void collection_input_reset();
static bool jf1_guards(const Jf1Profile& p,bool record_failure=true){
    for(const auto& g:p.guards){uint64_t hash=14695981039346656037ull;
        for(uint32_t n=0;n<g.words;++n){uint32_t word=psx_read_word(g.address+n*4);
            for(int b=0;b<4;++b){hash=(hash^(word&255))*1099511628211ull;word>>=8;}}
        if(hash!=g.hash){if(record_failure){jf1_bad_guard=g.address;++jf1_guard_failures;}return false;}}
    return true;
}
static const Jf1Profile* jf1_find_profile(uint32_t address){
    const auto* previous=jf1_profile;
    if(previous&&jf1_guards(*previous))return previous;
    jf1_profile=nullptr;
    // Addresses overlap unrelated functions in other world images. Select by
    // the complete code fingerprint, never by whichever callback ran first.
    for(const auto& p:jf1_profiles){
        if(&p!=previous&&jf1_guards(p,false)){jf1_profile=&p;break;}}
    if(jf1_profile!=previous){
        jf1_player_frame=0;jf1_motion_frame=UINT64_MAX;
        jf1_release_inputs();collection_input_reset();
    }
    return jf1_profile;
}
static bool jf1_gameplay(){
    if(!collection_mode)return false;
    const auto* p=jf1_find_profile(0);
    if(!p||!jf1_player_frame||s_frame_count-jf1_player_frame>=8)return false;
    return jf1::manual(psx_read_word(p->demo_mode),psx_read_word(p->control_live),psx_read_word(p->original_pause),
        psx_read_word(p->control_block),psx_read_word(p->finish),psx_read_word(p->finish2),
        psx_read_word(p->movie),psx_read_word(p->movie_ready))&&psx_read_half(p->player+0x5c)>0;
}
static void jf1_release_inputs(){
    if(jf1_captured&&sdl_window){if(jf1_compat_mouse){SDL_SetWindowMouseGrab(sdl_window,false);SDL_ShowCursor();}
        else SDL_SetWindowRelativeMouseMode(sdl_window,false);}
    jf1_captured=false;jf1_look.clear();jf1_move_x=jf1_move_forward=jf1_pad_x=jf1_pad_forward=0;
    jf1_key_until.fill(0);jf1_mouse_until.fill(0);jf1_recenter=false;
    const auto* keys=SDL_GetKeyboardState(nullptr);
    for(int i=0;i<SDL_NUM_SCANCODES;++i)jf1_blocked_keys[i]=keys&&keys[i];
    jf1_blocked_mouse=SDL_GetMouseState(nullptr,nullptr);
}
static bool jf1_focused(){return sdl_window&&(SDL_GetWindowFlags(sdl_window)&SDL_WINDOW_INPUT_FOCUS);}
static uint16_t jf1_input_pad(const Uint8* keys,int player){
    if(player!=1||!collection_mode)return psx_keybinds_pad_word(keys,player);
    const bool gameplay=jf1_gameplay();
    if(gameplay!=jf1_input_previous){jf1_input_previous=gameplay;jf1_release_inputs();}
    if(!jf1_focused()||savestate_input_guard_active()){jf1_release_inputs();return 0xffff;}
    std::array<uint8_t,SDL_NUM_SCANCODES> clean{};
    const auto now=SDL_GetTicks();
    for(int i=0;i<SDL_NUM_SCANCODES;++i){if(!keys[i])jf1_blocked_keys[i]=0;
        clean[i]=(keys[i]||now<jf1_key_until[i])&&!jf1_blocked_keys[i];}
    if(!collection_controls.modern||!gameplay)return psx_keybinds_pad_word(clean.data(),player)&collection_controller_word;
    jf1_move_x=std::clamp(jf1_pad_x+float(clean[SDL_SCANCODE_D])-float(clean[SDL_SCANCODE_A]),-1.f,1.f);
    jf1_move_forward=std::clamp(jf1_pad_forward+float(clean[SDL_SCANCODE_W])-float(clean[SDL_SCANCODE_S]),-1.f,1.f);
    uint16_t pad=collection_controller_word|0x00f0u;
    if(jf1::magnitude(jf1_move_x,jf1_move_forward)>.01f)pad&=~0x10u;
    if(clean[SDL_SCANCODE_SPACE])pad&=~0x4000u;
    if(clean[SDL_SCANCODE_F])pad&=~0x1000u;
    if(clean[SDL_SCANCODE_E])pad&=~0x2000u;
    if(clean[SDL_SCANCODE_RETURN])pad&=~8u;
    auto mouse=SDL_GetMouseState(nullptr,nullptr);jf1_blocked_mouse&=mouse;
    for(int b=1;b<=5;++b)if(now<jf1_mouse_until[b])mouse|=SDL_BUTTON_MASK(b);
    mouse&=~jf1_blocked_mouse;
    if(jf1_captured){if(mouse&SDL_BUTTON_LMASK)pad&=~0x8000u;if(mouse&SDL_BUTTON_RMASK)pad&=~0x2000u;}
    return pad;
}
static bool jf1_input_event(const SDL_Event& e){
    if(!collection_mode)return false;
    if(!jf1_mouse_mode_initialized){jf1_compat_mouse=collection_deck;jf1_mouse_mode_initialized=true;}
    if(e.type==SDL_EVENT_WINDOW_FOCUS_LOST){jf1_release_inputs();return false;}
    if(e.type==SDL_KEYDOWN&&e.key.scancode==SDL_SCANCODE_ESCAPE&&jf1_captured){jf1_release_inputs();return true;}
    if(e.type==SDL_KEYUP)jf1_blocked_keys[e.key.scancode]=0;
    if(e.type==SDL_KEYDOWN&&!e.key.repeat){
        const int sc=e.key.scancode;
        if(sc==SDL_SCANCODE_F6&&collection_controls.modern){jf1_release_inputs();jf1_compat_mouse=!jf1_compat_mouse;
            host_osd_push(jf1_compat_mouse?"Compatibility mouse | Click gameplay to capture":"Raw mouse | Click gameplay to capture",2200);return true;}
        if(collection_controls.modern&&jf1_gameplay()&&jf1_focused()&&!savestate_input_guard_active()&&!jf1_blocked_keys[sc]&&
           (sc==SDL_SCANCODE_W||sc==SDL_SCANCODE_A||sc==SDL_SCANCODE_S||sc==SDL_SCANCODE_D||
            sc==SDL_SCANCODE_SPACE||sc==SDL_SCANCODE_F||sc==SDL_SCANCODE_E))jf1_key_until[sc]=SDL_GetTicks()+80;
    }
    if(e.type==SDL_MOUSEBUTTONUP&&e.button.button<=5)jf1_blocked_mouse&=~SDL_BUTTON_MASK(e.button.button);
    if(e.type==SDL_MOUSEBUTTONDOWN&&e.button.button==SDL_BUTTON_LEFT&&collection_controls.modern&&
       jf1_gameplay()&&jf1_focused()&&!savestate_input_guard_active()&&!jf1_captured){
        if(jf1_compat_mouse){jf1_captured=SDL_SetWindowMouseGrab(sdl_window,true);if(jf1_captured){SDL_HideCursor();jf1_recenter=true;}}
        else jf1_captured=SDL_SetWindowRelativeMouseMode(sdl_window,true);
        jf1_blocked_mouse|=SDL_BUTTON_LMASK;
        jf1_look.clear();host_osd_push(jf1_captured?"Mouse aim captured | WASD move | Space jump | Esc releases":"Mouse capture failed | Try F6 compatibility mouse",2200);return true;}
    if(e.type==SDL_MOUSEBUTTONDOWN&&e.button.button<=5&&jf1_captured&&!(jf1_blocked_mouse&SDL_BUTTON_MASK(e.button.button)))
        jf1_mouse_until[e.button.button]=SDL_GetTicks()+80;
    if(e.type==SDL_MOUSEMOTION&&jf1_captured){
        if(jf1_compat_mouse){int w=0,h=0;SDL_GetWindowSize(sdl_window,&w,&h);double dx=e.motion.x-w/2,dy=e.motion.y-h/2;
            if(std::abs(dx)<1&&std::abs(dy)<1)return true;jf1_look.move(dx*2,dy*2);jf1_recenter=true;}
        else jf1_look.move(e.motion.xrel*2,e.motion.yrel*2);return true;}
    return false;
}
static void jf1_desktop_tick(){
    if(jf1_captured&&(!jf1_gameplay()||!jf1_focused()||savestate_input_guard_active()))jf1_release_inputs();
    if(jf1_captured&&jf1_compat_mouse&&jf1_recenter){int w=0,h=0;SDL_GetWindowSize(sdl_window,&w,&h);
        SDL_WarpMouseInWindow(sdl_window,w/2,h/2);jf1_recenter=false;}
}
extern "C" void jf1_desktop_camera(CPUState* cpu,uint32_t address){
    if(!collection_mode||!cpu)return;
    address=0x80000000u|(address&0x1fffffffu);
    if(!jf1_control_site(address))return;
    ++jf1_hook_calls;jf1_last_hook=address;
    const auto* p=jf1_find_profile(address);if(!p)return;
    if(address==p->update){jf1_player_frame=s_frame_count;return;}
    if(!jf1_gameplay()||!collection_controls.modern||!jf1_focused()||savestate_input_guard_active())return;
    if(address==p->movement){
        if(cpu->gpr[4]!=p->player)return;
        if((jf1_captured||collection_aim_live)&&jf1_motion_frame!=s_frame_count){
            jf1_motion_frame=s_frame_count;
            int yaw=jf1_look.update((int32_t)psx_read_word(p->player+0x8c),(int32_t)psx_read_word(p->player+0x90),
                collection_controls.sensitivity,collection_controls.invert_y);
            psx_write_word(p->player+0x8c,(uint32_t)yaw);++jf1_look_updates;}
    }else if(address==p->command&&cpu->gpr[16]==p->player){
        // Before native acceleration/friction: change the requested heading and
        // speed only. Jump, gravity, collision and actual velocity remain guest code.
        const float magnitude=jf1::magnitude(jf1_move_x,jf1_move_forward);
        if(magnitude>.01f&&psx_read_word(p->player+0xac)>0){
            int heading=jf1::wrap((int32_t)psx_read_word(p->player+0x8c)+jf1::heading(jf1_move_x,jf1_move_forward));
            psx_write_word(p->player+0xa4,(uint32_t)heading);
            psx_write_word(p->player+0xac,(uint32_t)std::lround(psx_read_word(p->player+0xac)*magnitude));++jf1_move_updates;}
    }else if(address==p->camera&&cpu->gpr[16]==p->player&&jf1_look.initialized&&(jf1_captured||collection_aim_live)){
        psx_write_word(p->player+0x90,(uint32_t)(int)std::lround(jf1_look.pitch));psx_write_word(p->player+0x9c,0);
    }
}
