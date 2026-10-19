#pragma once
#include "robbit_profile_core.h"
static const RobbitProfile* robbit_profile=nullptr;
static uint64_t robbit_profile_changes=0;
static void robbit_release_mouse();
static void collection_input_reset();

static bool robbit_supported(){
    const auto* next=robbit_find_profile(robbit_profile,[](uint32_t address){return psx_read_word(address);});
    if(next!=robbit_profile){
        robbit_profile=next;++robbit_profile_changes;
        robbit_player_frame=0;robbit_motion_frame=UINT64_MAX;robbit_move_until=0;
        robbit_release_mouse();
        robbit_pulses.block_held(SDL_GetKeyboardState(nullptr));
        collection_input_reset();
    }
    return next!=nullptr;
}
static bool robbit_gameplay(){
    return robbit_supported()&&robbit_live_flags(psx_read_word(robbit_profile->live_flags),
        (int16_t)psx_read_half(robbit_profile->mode),
        (int16_t)psx_read_half(robbit_profile->lock1)|(int16_t)psx_read_half(robbit_profile->lock2))&&
        robbit_player_frame&&s_frame_count-robbit_player_frame<8;
}
extern "C" void robbit_desktop_camera(CPUState* cpu,uint32_t address){
    if(!cpu||!robbit_control_site(address))return;
    if(robbit_profile&&!robbit_profile_site(*robbit_profile,address)&&!robbit_update_site(address))return;
    // The vector helper also serves NPCs. Reject unrelated callers before
    // hashing player routines; this branch can only prevent an input write.
    if(robbit_profile&&(address&0x1fffffffu)==(robbit_profile->vector&0x1fffffffu)&&
       !robbit_update_site(address)&&
       (cpu->gpr[31]!=robbit_profile->move1_return&&cpu->gpr[31]!=robbit_profile->move2_return))return;
    if(!robbit_supported()||!robbit_profile_site(*robbit_profile,address))return;
    const auto& profile=*robbit_profile;
    const uint32_t pc=address&0x1fffffffu,actor=profile.player;
    if(pc==(profile.update&0x1fffffffu))robbit_player_frame=s_frame_count;
    if(pc==(profile.vector&0x1fffffffu)){
        ++robbit_vector_calls;robbit_vector_ra=cpu->gpr[31];robbit_vector_a2=cpu->gpr[6];robbit_vector_a3=cpu->gpr[7];
        if(robbit_modern&&robbit_host_input_ready()&&robbit_gameplay()&&!savestate_input_guard_active()&&
           SDL_GetTicks()<robbit_move_until&&(robbit_move_x||robbit_move_forward)&&
           (cpu->gpr[31]==profile.move1_return||cpu->gpr[31]==profile.move2_return)&&
           cpu->gpr[6]==actor+0x28&&cpu->gpr[7]==actor+0x20){
            cpu->gpr[4]=psx_read_word(actor+0x14)+(uint32_t)(robbit_move_angle(robbit_move_x,robbit_move_forward)*4096);
            ++robbit_move_updates;
        }
        return;
    }
    if(!robbit_modern||!(robbit_captured||collection_aim_live)||!robbit_gameplay()||savestate_input_guard_active())return;
    if(pc==(profile.update&0x1fffffffu)&&robbit_motion_frame!=s_frame_count){
        robbit_motion_frame=s_frame_count;
        int yaw=robbit_look.update((int32_t)psx_read_word(actor+0x14)/4096,
            (int32_t)psx_read_word(actor+0x10)/4096,robbit_sensitivity,robbit_invert);
        psx_write_word(actor+0x14,(uint32_t)(yaw*4096));
        psx_write_word(actor+0x10,(uint32_t)((int)std::lround(robbit_look.pitch)*4096));
        ++robbit_camera_updates;
    }
    if(!robbit_look.initialized)return;
    const int pitch=(int)std::lround(robbit_look.pitch);
    if(pc==(profile.rotation_return&0x1fffffffu)&&cpu->gpr[17]==actor&&cpu->gpr[31]==profile.rotation_return){
        const uint32_t physical=psx_read_word(actor+0x48);
        if(physical>=0x80050000&&physical<0x801fff00&&!(physical&3))psx_write_half(physical+0x28,(uint16_t)pitch);
    }
    if(pc==(profile.pitch&0x1fffffffu))psx_write_word(actor+0x10,(uint32_t)(pitch*4096));
}
