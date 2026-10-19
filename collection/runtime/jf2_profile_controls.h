#pragma once
#include "jf2_profile_core.h"
static const Jf2Profile* jf2_profile=nullptr;
static uint64_t jf2_profile_changes=0;
static void collection_input_reset();
static bool jf2_host_input_ready(){return collection_mode||g_players[0].kind==1;}
static bool jf2_camera_supported(){
    const auto* next=jf2_cpu?jf2_find_profile(jf2_profile,[](uint32_t pc){return psx_read_word(pc);}):nullptr;
    if(next!=jf2_profile){
        jf2_profile=next;++jf2_profile_changes;
        jf2_camera_frame=0;jf2_update_frame=UINT64_MAX;jf2_move_command=false;
        jf2_last_pad=0xffff;jf2_asserted_pad=0xffff;jf2_injected_pad=-1;
        jf2_release_inputs();collection_input_reset();
    }
    return next!=nullptr;
}
static void jf2_gameplay_camera(CPUState* cpu,uint32_t address){
    if(!cpu||!jf2_control_site(address))return;
    if(jf2_profile&&!jf2_profile_role(*jf2_profile,address)&&!jf2_update_site(address))return;
    if(!jf2_camera_supported()||!jf2_profile_role(*jf2_profile,address))return;
    const auto& profile=*jf2_profile;
    const uint32_t pc=jf2_profile_role(profile,address),actor=profile.actor;
    if(savestate_input_guard_active()){jf2_move_command=false;return;}
    if((pc==0xe2550||pc==0xe2b90||pc==0xe2b4c)&&cpu->gpr[4]!=actor)return;
    if(pc==0xe2b90 && jf2_move_command && cpu->gpr[4]==actor) {
        psx_write_word(profile.pad,jf2_saved_move_pad);
        psx_write_word(actor+0x88,jf2_saved_move_yaw);
        psx_write_word(profile.base_speed,jf2_saved_move_base);
        psx_write_word(profile.movement_mode,jf2_saved_move_mode);
        psx_write_word(profile.look_mode,jf2_saved_look_mode);
        jf2_move_command=false;
        jf2_move_speed=(int32_t)psx_read_word(actor+0xac);
        return;
    }
    if(pc==0xe2550) {
        // PAL W1: alter the command BEFORE the native ground/air integrator.
        // Never overwrite +94/+AC velocity, vertical state, or collision results.
        if(cpu->gpr[4]!=actor || psx_read_word(profile.movement)!=0x27bdffd8 ||
            psx_read_word(profile.movement+0x3a4)!=0xae0200ac || psx_read_word(profile.restore)!=0x27bdffd8 ||
            jf2_move_command || jf2_desktop_open() || savestate_input_guard_active() || !jf2_host_input_ready()) return;
        const uint32_t native_pad=psx_read_word(profile.pad);
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
        const int base=(int32_t)psx_read_word(profile.base_speed);
        if(base<=0 || base>4096) return;
        jf2_saved_move_pad=psx_read_word(profile.pad);jf2_saved_move_yaw=psx_read_word(actor+0x88);
        jf2_saved_move_base=base;jf2_saved_move_mode=psx_read_word(profile.movement_mode);jf2_saved_look_mode=psx_read_word(profile.look_mode);
        const uint16_t sampled=jf2::host_pad(jf2_saved_move_pad);
        auto move=jf2::movement(sampled,(int32_t)jf2_saved_move_yaw);
        if(lateral) {
            // A/D are direction commands, not the native L1 run modifier.
            psx_write_word(profile.pad,jf2::movement_pad(jf2_saved_move_pad,move.active));
            psx_write_word(profile.movement_mode,0);psx_write_word(profile.look_mode,0);
            if(move.active) psx_write_word(actor+0x88,move.angle);
            jf2_move_angle=move.angle;
            if((sampled&0x0c00)!=0x0c00 && move.active) ++jf2_strafe_updates;
        }
        // +FF is floor contact, not an airborne flag. State/vertical speed
        // also exclude the first jump update while contact is still stale.
        const bool airborne=!jf2::grounded(psx_read_byte(actor+0xff),
            (int16_t)psx_read_half(actor+0x18),(int32_t)psx_read_word(actor+0x74));
        const int boosted=jf2::ground_boost(base,jf2_boost_held,airborne,jf2_settings.jf2_boost_percent);
        if(boosted!=base) {psx_write_word(profile.base_speed,boosted);++jf2_boost_updates;}
        jf2_move_command=true;
        return;
    }
    if(pc==0xe7f1c && (cpu->gpr[31]!=profile.camera_return || cpu->gpr[17]!=actor)) return;
    if(pc==0xe2b4c && cpu->gpr[4]!=actor) return;
    jf2_camera_frame=s_frame_count;
    if(pc==0xe1528 && jf2_update_frame!=s_frame_count) {jf2_update_frame=s_frame_count;++jf2_updates;}
    if(!jf2_settings.jf2_control_style || !(jf2_captured || collection_aim_live) || jf2_desktop_open()) return;
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
}
