#pragma once
#ifndef PSX_NO_DEBUG_TOOLS
// Process-local SDL virtual device for reproducible integration tests. It never
// installs a driver or sends input to another application.
static SDL_Joystick* collection_probe_joystick=nullptr;
extern "C" int collection_input_probe(int enable,uint32_t buttons,const int axes[6]){
    if(!collection_mode)return 0;
    if(enable==0){
        if(collection_probe_joystick)SDL_CloseJoystick(collection_probe_joystick);
        collection_probe_joystick=nullptr;
        if(collection_probe_id)SDL_DetachVirtualJoystick(collection_probe_id);
        collection_probe_id=0;collection_input_reset();return 1;
    }
    if(!collection_probe_id){SDL_VirtualJoystickDesc desc{};SDL_INIT_INTERFACE(&desc);
        desc.type=SDL_JOYSTICK_TYPE_GAMEPAD;desc.naxes=6;desc.nbuttons=21;
        desc.button_mask=(1u<<21)-1;desc.axis_mask=(1u<<6)-1;desc.name="Collection integration test";
        collection_probe_id=SDL_AttachVirtualJoystick(&desc);
        if(!collection_probe_id)return 0;
        collection_probe_joystick=SDL_OpenJoystick(collection_probe_id);
        if(!collection_probe_joystick){SDL_DetachVirtualJoystick(collection_probe_id);collection_probe_id=0;return 0;}
    }
    for(int b=0;b<21;++b)SDL_SetJoystickVirtualButton(collection_probe_joystick,b,(buttons&(1u<<b))!=0);
    for(int a=0;a<6;++a){int value=a>=4?std::clamp(axes[a],0,32767)*2-32768:std::clamp(axes[a],-32768,32767);
        SDL_SetJoystickVirtualAxis(collection_probe_joystick,a,(Sint16)value);}
    return 1;
}
extern "C" int collection_input_status_json(char* out,int capacity){
    int count=0;auto* pads=SDL_GetGamepads(&count);SDL_free(pads);
    auto sample=collection_physical_sample();
    int length=std::snprintf(out,capacity,"\"collection_mode\":%d,\"controllers\":%d,\"virtual_probe\":%d,\"modern\":%d,\"gameplay\":%d,\"aim_owned\":%d,\"pad_word\":%u,\"axes\":[%.3f,%.3f,%.3f,%.3f,%.3f,%.3f]",
        collection_mode,count,collection_probe_id!=0,collection_controls.modern,collection_gameplay_live(),collection_aim_owned,
        collection_controller_word,sample.axes[0],sample.axes[1],sample.axes[2],sample.axes[3],sample.axes[4],sample.axes[5]);
#ifdef JF1_DESKTOP
    if(length>0&&length<capacity)length+=std::snprintf(out+length,capacity-length,
        ",\"jf1\":{\"profile\":\"%s\",\"mouse_captured\":%d,\"compatibility_mouse\":%d,\"look_updates\":%llu,\"move_updates\":%llu,\"movement\":[%.3f,%.3f],\"hook_calls\":%llu,\"last_hook\":%u,\"guard_failures\":%llu,\"bad_guard\":%u}",
        jf1_profile?jf1_profile->image:"",jf1_captured,jf1_compat_mouse,(unsigned long long)jf1_look_updates,
        (unsigned long long)jf1_move_updates,jf1_move_x,jf1_move_forward,(unsigned long long)jf1_hook_calls,
        jf1_last_hook,(unsigned long long)jf1_guard_failures,jf1_bad_guard);
#endif
    return length;
}
#endif
