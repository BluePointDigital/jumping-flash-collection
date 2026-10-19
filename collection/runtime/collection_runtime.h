#pragma once
// Collection-only menu. Ordinary standalone launch behavior stays unchanged.
static int collection_menu_choice=0;
static int collection_pad_frames=0;
static uint16_t collection_pad_word=0xffff;
static void collection_pause_pulse(bool opening) {
    collection_pad_frames=6;collection_pad_word=opening?0xfff7:0xdfff;
}
static void collection_menu_show() {
    const char* line=collection_menu_choice==0?
        "BACK TO GAME | W/S, Enter/A":
        "RETURN TO COLLECTION | Enter/A";
    host_osd_push(line,300000);
}
static bool collection_runtime_event(const SDL_Event& e) {
    if(!collection_mode)return false;
#if defined(PSX_SDL3)
    if(e.type==SDL_EVENT_WINDOW_FOCUS_LOST||e.type==SDL_EVENT_GAMEPAD_REMOVED||e.type==SDL_EVENT_GAMEPAD_ADDED)collection_input_reset();
#endif
    const bool key=e.type==SDL_KEYDOWN;
#if defined(PSX_SDL3)
    const int sc=key?e.key.scancode:0;
    const SDL_Keycode code=key?e.key.key:0;
    const bool pad=e.type==SDL_EVENT_GAMEPAD_BUTTON_DOWN;
    const int button=pad?e.gbutton.button:-1;
#else
    const int sc=key?e.key.keysym.scancode:0;
    const SDL_Keycode code=key?e.key.keysym.sym:0;
    const bool pad=e.type==SDL_CONTROLLERBUTTONDOWN;
    const int button=pad?e.cbutton.button:-1;
#endif
    // Menu pauses live gameplay; View/F8 is also available outside gameplay.
    if((key&&sc==SDL_SCANCODE_F8&&!e.key.repeat)||(pad&&(button==SDL_CONTROLLER_BUTTON_BACK||
        (button==SDL_CONTROLLER_BUTTON_START&&(collection_menu_open||collection_gameplay_live()))))){
        collection_menu_open=!collection_menu_open;collection_menu_choice=0;
        collection_input_reset();
        collection_pause_pulse(collection_menu_open);
        if(collection_menu_open)collection_menu_show();else host_osd_push("Back to game",700);
        return true;
    }
    if(!collection_menu_open)return false;
    if((key&&(sc==SDL_SCANCODE_UP||sc==SDL_SCANCODE_DOWN||sc==SDL_SCANCODE_W||sc==SDL_SCANCODE_S||code==SDLK_UP||code==SDLK_DOWN))||(pad&&(button==SDL_CONTROLLER_BUTTON_DPAD_UP||button==SDL_CONTROLLER_BUTTON_DPAD_DOWN))){collection_menu_choice=1-collection_menu_choice;collection_menu_show();return true;}
    if((key&&sc==SDL_SCANCODE_ESCAPE)||(pad&&button==SDL_CONTROLLER_BUTTON_B)){collection_menu_open=false;collection_pause_pulse(false);host_osd_push("Back to game",700);return true;}
    if((key&&(sc==SDL_SCANCODE_RETURN||code==SDLK_RETURN))||(pad&&button==SDL_CONTROLLER_BUTTON_A)){
        if(collection_menu_choice==1){psx_crash_trace_set_exit_origin("return_to_collection");shutdown_runtime();std::exit(0);}
        collection_menu_open=false;collection_pause_pulse(false);host_osd_push("Back to game",700);return true;
    }
    return key||pad;
}

static void collection_host_pause_loop() {
    if(!collection_mode||!collection_menu_open)return;
    psx_local_mouse_begin(sdl_window,false);psx_local_mouse_reset();
    collection_pad_frames=0;
    freeze_heartbeat_set_paused(1);
    while(collection_menu_open){
#ifndef PSX_NO_DEBUG_TOOLS
        debug_server_poll();
#endif
        SDL_Event event;
        while(SDL_PollEvent(&event)){
            if(event.type==SDL_QUIT){shutdown_runtime();std::exit(0);}
            collection_runtime_event(event);
            if(event.type==SDL_CONTROLLERDEVICEADDED){refresh_player_devices();}
            else if(event.type==SDL_CONTROLLERDEVICEREMOVED){
                bool ours=false;
                for(int s=0;s<PSX_MAX_PLAYERS;s++){
#if defined(PSX_SDL3)
                    if(event.gdevice.which==g_players[s].instance){ours=true;break;}
#else
                    if(event.cdevice.which==g_players[s].instance){ours=true;break;}
#endif
                }
                if(ours){close_controller();refresh_player_devices();}
            }
        }
        rewind_pause_present();starvation_watchdog_heartbeat();SDL_Delay(8);
    }
    collection_pad_frames=0;
    freeze_heartbeat_set_paused(0);savestate_input_guard_arm();
}
