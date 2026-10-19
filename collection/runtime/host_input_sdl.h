#pragma once
#include "host_input.h"
static SDL_GameController* collection_controller=nullptr;
static SDL_JoystickID collection_probe_id=0;
static collection_input::Config collection_controls;
static collection_input::ReleaseGate collection_release_gate;
static uint64_t collection_input_tick=UINT64_MAX,collection_input_time=0;
static bool collection_gameplay_previous=false,collection_aim_live=false;
static bool collection_menu_open=false;
static bool collection_aim_owned=false;
static bool collection_controller_changed=false;
static float collection_aim_x=0,collection_aim_y=0;
static uint16_t collection_controller_word=0xffff;
static std::array<uint8_t,SDL_NUM_SCANCODES> collection_keys;
static bool collection_gameplay_live();
static void collection_look_apply(double x,double y);
static void collection_look_reset();
static void collection_move_apply(float,float);
#ifdef JF1_DESKTOP
static uint16_t jf1_input_pad(const Uint8*,int);
#endif
static int savestate_input_guard_active(void);
static collection_input::Sample collection_physical_sample(){
    collection_input::Sample sample;
    if(collection_probe_id&&collection_controller&&SDL_JoystickInstanceID(SDL_GameControllerGetJoystick(collection_controller))!=collection_probe_id){SDL_GameControllerClose(collection_controller);collection_controller=nullptr;collection_controller_changed=true;}
    if(collection_controller&&!SDL_GameControllerGetAttached(collection_controller)){SDL_GameControllerClose(collection_controller);collection_controller=nullptr;collection_controller_changed=true;}
    if(!collection_controller){const int n=SDL_NumJoysticks();for(int i=0;i<n;++i)if(SDL_IsGameController(i)&&(!collection_probe_id||SDL_JoystickGetDeviceInstanceID(i)==collection_probe_id)){collection_controller=SDL_GameControllerOpen(i);if(collection_controller)collection_controller_changed=true;break;}}
    if(collection_controller){
        for(int b=0;b<SDL_CONTROLLER_BUTTON_MAX&&b<21;++b)sample.buttons[b]=SDL_GameControllerGetButton(collection_controller,(SDL_GameControllerButton)b)!=0;
        for(int a=0;a<6;++a)sample.axes[a]=collection_input::axis(SDL_GameControllerGetAxis(collection_controller,(SDL_GameControllerAxis)a),collection_controls.deadzone);}
    // Polling must also enforce the release gate if a hotplug event was missed.
    if(collection_controller_changed)collection_release_gate.arm(sample);
    return sample;
}
static void collection_input_reset(){collection_release_gate.arm(collection_physical_sample());collection_aim_owned=collection_aim_live=false;collection_look_reset();collection_aim_x=collection_aim_y=0;collection_controller_word=0xffff;collection_input_tick=UINT64_MAX;}
static const Uint8* collection_host_keys(const Uint8* keys,int player){
    if(!collection_mode||player!=1)return keys;
    static bool loaded=false;if(!loaded){collection_controls=collection_input::load(collection_user_data/"host-input.toml");loaded=true;}
    if(collection_input_tick!=s_frame_count){
        collection_input_tick=s_frame_count;auto raw=collection_physical_sample();
        if(collection_controller_changed){collection_controller_changed=false;collection_aim_owned=collection_aim_live=false;collection_look_reset();collection_aim_x=collection_aim_y=0;collection_controller_word=0xffff;}
        const bool gameplay=collection_gameplay_live();
        if(gameplay!=collection_gameplay_previous){collection_release_gate.arm(raw);collection_aim_owned=false;collection_look_reset();collection_gameplay_previous=gameplay;}
        const bool focused=sdl_window&&(SDL_GetWindowFlags(sdl_window)&SDL_WINDOW_INPUT_FOCUS);
        if(!focused||savestate_input_guard_active()||collection_menu_open)collection_release_gate.arm(raw);
        auto sample=collection_release_gate.clean(raw);collection_controller_word=0xffff;
        auto down=[&](int b,uint16_t bit){if(sample.buttons[b])collection_controller_word&=~bit;};
        down(SDL_CONTROLLER_BUTTON_DPAD_UP,0x10);down(SDL_CONTROLLER_BUTTON_DPAD_DOWN,0x40);
        down(SDL_CONTROLLER_BUTTON_DPAD_LEFT,0x80);down(SDL_CONTROLLER_BUTTON_DPAD_RIGHT,0x20);
        // Native title, pause, save and dialogue actions keep their original meaning.
        if(!collection_controls.modern||!gameplay){
            down(SDL_CONTROLLER_BUTTON_A,0x4000);down(SDL_CONTROLLER_BUTTON_B,0x2000);down(SDL_CONTROLLER_BUTTON_X,0x8000);down(SDL_CONTROLLER_BUTTON_Y,0x1000);
            down(SDL_CONTROLLER_BUTTON_START,8);down(SDL_CONTROLLER_BUTTON_BACK,1);
            down(SDL_CONTROLLER_BUTTON_LEFTSHOULDER,0x400);down(SDL_CONTROLLER_BUTTON_RIGHTSHOULDER,0x800);
            if(sample.axes[4]>.55f)collection_controller_word&=~0x100;if(sample.axes[5]>.55f)collection_controller_word&=~0x200;
            if(sample.axes[0]<-.35f)collection_controller_word&=~0x80;if(sample.axes[0]>.35f)collection_controller_word&=~0x20;
            if(sample.axes[1]<-.35f)collection_controller_word&=~0x10;if(sample.axes[1]>.35f)collection_controller_word&=~0x40;
        }else{
            if(collection_input::held(sample,collection_controls.jump))collection_controller_word&=~0x4000;
            if(collection_input::held(sample,collection_controls.fire))collection_controller_word&=~0x8000;
            if(collection_input::held(sample,collection_controls.secondary))collection_controller_word&=~0x2000;
            if(collection_input::held(sample,collection_controls.special))collection_controller_word&=~0x1000;
            down(SDL_CONTROLLER_BUTTON_START,8);
        }
        std::copy(keys,keys+SDL_NUM_SCANCODES,collection_keys.begin());
        if(collection_controls.modern&&gameplay&&focused&&!savestate_input_guard_active()&&!collection_menu_open){
#if defined(JF1_DESKTOP)
            collection_move_apply(sample.axes[0]+float(sample.buttons[SDL_CONTROLLER_BUTTON_DPAD_RIGHT])-float(sample.buttons[SDL_CONTROLLER_BUTTON_DPAD_LEFT]),
                -sample.axes[1]+float(sample.buttons[SDL_CONTROLLER_BUTTON_DPAD_UP])-float(sample.buttons[SDL_CONTROLLER_BUTTON_DPAD_DOWN]));
#else
#if defined(ROBBIT_DESKTOP)
            if(sample.axes[0]<-.25f)collection_keys[SDL_SCANCODE_A]=1;if(sample.axes[0]>.25f)collection_keys[SDL_SCANCODE_D]=1;
            if(sample.axes[1]<-.25f)collection_keys[SDL_SCANCODE_W]=1;if(sample.axes[1]>.25f)collection_keys[SDL_SCANCODE_S]=1;
#else
            if(sample.axes[0]<-.25f)collection_controller_word&=~0x400;if(sample.axes[0]>.25f)collection_controller_word&=~0x800;
            if(sample.axes[1]<-.25f)collection_controller_word&=~0x10;if(sample.axes[1]>.25f)collection_controller_word&=~0x40;
#endif
#endif
            collection_aim_x=sample.axes[2];collection_aim_y=sample.axes[3];
            if(std::abs(collection_aim_x)+std::abs(collection_aim_y)>.01f)collection_aim_owned=true;
            collection_aim_live=collection_aim_owned&&collection_controller&&focused;
            const auto now=SDL_GetTicks();double dt=collection_input_time?std::min<uint64_t>(now-collection_input_time,50)/1000.:0;collection_input_time=now;
            if(collection_aim_live)collection_look_apply(collection_aim_x*1024*dt,collection_aim_y*1024*dt);
        }else{collection_move_apply(0,0);collection_aim_live=false;collection_input_time=SDL_GetTicks();}
    }
    return collection_keys.data();
}
