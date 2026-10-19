#include <array>
#include <cstring>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <vector>
#include "host_input.h"
#include "../../tools/recomp/jf2_desktop_core.h"
#include "jf2_profile_core.h"

static void check(bool ok,const char* message){if(!ok)throw std::runtime_error(message);}
static std::array<uint8_t,0x200000> ram{};
static unsigned writes=0,input_resets=0,releases=0;
static uint32_t psx_read_word(uint32_t address){
    const auto p=address&0x1fffffffu;if(p+4>ram.size())return 0;
    return uint32_t(ram[p])|uint32_t(ram[p+1])<<8|uint32_t(ram[p+2])<<16|uint32_t(ram[p+3])<<24;
}
static uint8_t psx_read_byte(uint32_t a){return uint8_t(psx_read_word(a));}
static uint16_t psx_read_half(uint32_t a){return uint16_t(psx_read_word(a));}
static void psx_write_word(uint32_t a,uint32_t v){
    const auto p=a&0x1fffffffu;check(p+4<=ram.size(),"write outside RAM");
    for(unsigned i=0;i<4;++i)ram[p+i]=uint8_t(v>>(i*8));++writes;
}
struct CPUState {uint32_t gpr[32]{};};
static CPUState cpu;
static CPUState* jf2_cpu=&cpu;
static struct {int kind=2;} g_players[1];
static bool collection_mode=true,collection_aim_live=false,load_guard=false,menu_open=false;
static bool savestate_input_guard_active(){return load_guard;}
static bool jf2_desktop_open(){return menu_open;}
static struct {bool jf2_control_style=true,jf2_invert_y=false,jf2_jump_camera=false;
    int jf2_mouse_sensitivity=100,jf2_boost_percent=150;} jf2_settings;
static jf2::MouseLook jf2_look;
static uint64_t s_frame_count=100,jf2_camera_frame=0,jf2_update_frame=UINT64_MAX,jf2_updates=0;
static bool jf2_move_command=false,jf2_keyboard_motion_pending=false,jf2_captured=false,jf2_boost_held=false;
static uint16_t jf2_last_pad=0xffff,jf2_asserted_pad=0xffff;
static int jf2_injected_pad=-1,jf2_move_angle=0,jf2_move_speed=0;
static uint32_t jf2_saved_move_pad=0,jf2_saved_move_yaw=0,jf2_saved_move_base=0;
static uint32_t jf2_saved_move_mode=0,jf2_saved_look_mode=0;
static uint64_t jf2_strafe_updates=0,jf2_boost_updates=0;
static collection_input::Sample physical_pad;
static collection_input::ReleaseGate release_gate;
static void jf2_release_inputs(){
    ++releases;jf2_captured=false;jf2_look.clear();jf2_boost_held=false;jf2_keyboard_motion_pending=false;
}
#include "jf2_profile_controls.h"
static void collection_input_reset(){
    ++input_resets;release_gate.arm(physical_pad);collection_aim_live=false;jf2_look.clear();
}

static void guard_tests(){
    Jf2Profile p{};
    const uint32_t a=0x80010000;
    psx_write_word(a,0x03e00008);psx_write_word(a+4,0);psx_write_word(a+8,0);psx_write_word(a+12,0);
    for(auto& g:p.guards)g={a,4,0x03e00008,0,0x372d4072812dbfc4ull};
    check(jf2_profile_matches(p,psx_read_word),"known little endian hash rejected");
    psx_write_word(a+8,1);check(!jf2_profile_matches(p,psx_read_word),"interior guard mutation accepted");
    psx_write_word(a+8,0);p.guards[0].words=0;check(!jf2_profile_matches(p,psx_read_word),"empty guard accepted");
    p.guards[0].words=4;p.guards[0].address=0x801ffffc;
    check(!jf2_profile_matches(p,psx_read_word),"out of RAM guard accepted");
    for(const auto& profile:jf2_profiles){
        check(jf2_control_site(profile.update)&&jf2_control_site(profile.restore),"generated sites incomplete");
        check(jf2_profile_role(profile,profile.camera)==0xe7f1c,"camera role changed");
        check(!jf2_profile_role(profile,profile.update+4),"interior instruction became hook");
    }
}

static uint32_t read_u32(std::ifstream& s){
    uint8_t bytes[4];check(bool(s.read(reinterpret_cast<char*>(bytes),4)),"short fixture header");
    return uint32_t(bytes[0])|uint32_t(bytes[1])<<8|uint32_t(bytes[2])<<16|uint32_t(bytes[3])<<24;
}
static void fixture_tests(const char* path){
    std::ifstream stream(path,std::ios::binary);check(bool(stream),"fixture missing");
    check(read_u32(stream)==0x3146324a,"wrong JF2 fixture format");
    const auto count=read_u32(stream);check(count==std::size(jf2_profiles),"wrong profile count");
    for(unsigned i=0;i<count;++i){
        const auto load=read_u32(stream),size=read_u32(stream),offset=load&0x1fffffffu;
        check(offset+uint64_t(size)<=ram.size(),"fixture outside RAM");ram.fill(0);
        check(bool(stream.read(reinterpret_cast<char*>(ram.data()+offset),size)),"short fixture body");
        const auto& p=jf2_profiles[i];check(jf2_profile_matches(p,psx_read_word),"actual source guard mismatch");
        jf2_profile=nullptr;jf2_move_command=true;jf2_captured=true;collection_aim_live=true;
        physical_pad.buttons[0]=true;physical_pad.axes[2]=1;
        const auto before_resets=input_resets,before_releases=releases;
        cpu={};++s_frame_count;jf2_gameplay_camera(&cpu,p.update);
        check(jf2_profile&&jf2_profile_matches(*jf2_profile,psx_read_word),"profile not selected");
        check(input_resets==before_resets+1&&releases==before_releases+1&&!jf2_captured&&!jf2_move_command,
              "profile change retained old input/command");
        const auto blocked=release_gate.clean(physical_pad);
        check(!blocked.buttons[0]&&blocked.axes[2]==0,"held controller not gated");
        physical_pad={};release_gate.clean(physical_pad);physical_pad.buttons[0]=true;
        check(release_gate.clean(physical_pad).buttons[0],"fresh controller input rejected");
        check(jf2_camera_frame==s_frame_count,"update did not establish scene freshness");
        cpu.gpr[4]=p.actor+4;const auto foreign=writes;
        for(uint32_t site:{p.pitch,p.movement,p.restore})jf2_gameplay_camera(&cpu,site);
        check(writes==foreign,"foreign actor accepted input writes");

        psx_write_word(p.actor+0x88,1000);psx_write_word(p.actor+0x8c,100);
        collection_aim_live=true;jf2_look.move(10,5);++s_frame_count;
        jf2_gameplay_camera(&cpu,p.update);
        check(psx_read_word(p.actor+0x88)==1020&&psx_read_word(p.actor+0x8c)==110,"wrong aim fields/rate");
        const auto yaw=psx_read_word(p.actor+0x88);jf2_gameplay_camera(&cpu,p.update);
        check(psx_read_word(p.actor+0x88)==yaw,"aim consumed twice in one simulation tick");
        cpu.gpr[4]=p.actor;psx_write_word(p.actor+0x98,999);jf2_gameplay_camera(&cpu,p.pitch);
        check(psx_read_word(p.actor+0x98)==0,"jump pitch assistance was not neutralized");

        collection_aim_live=false;psx_write_word(p.actor+0x88,1000);
        psx_write_word(p.pad,4);psx_write_word(p.base_speed,100);
        psx_write_word(p.movement_mode,7);psx_write_word(p.look_mode,9);
        psx_write_word(p.actor+0x94,111);psx_write_word(p.actor+0xac,222);
        jf2_last_pad=uint16_t(0xffffu&~0x0400u);collection_mode=true;
        jf2_gameplay_camera(&cpu,p.movement);
        check(jf2_move_command&&psx_read_word(p.actor+0x88)==4072,"controller strafe did not map command");
        check(psx_read_word(p.pad)==0x1000&&psx_read_word(p.movement_mode)==0&&psx_read_word(p.look_mode)==0,
              "command fields incorrect");
        check(psx_read_word(p.actor+0x94)==111&&psx_read_word(p.actor+0xac)==222,"adapter overwrote native velocity");
        jf2_gameplay_camera(&cpu,p.restore);
        check(!jf2_move_command&&psx_read_word(p.pad)==4&&psx_read_word(p.actor+0x88)==1000&&
              psx_read_word(p.base_speed)==100&&psx_read_word(p.movement_mode)==7&&psx_read_word(p.look_mode)==9,
              "native command restoration failed");

        collection_mode=false;const auto before=writes;jf2_gameplay_camera(&cpu,p.movement);
        check(!jf2_move_command&&writes==before,"legacy device selection bypassed outside collection");collection_mode=true;
        load_guard=true;jf2_move_command=true;collection_aim_live=true;jf2_look.move(5,5);
        jf2_gameplay_camera(&cpu,p.update);check(!jf2_move_command&&writes==before,"loading accepted stale input");load_guard=false;
        const auto guard=p.guards[0].address+8;psx_write_word(guard,psx_read_word(guard)^0xffffffffu);
        const auto after=writes;jf2_gameplay_camera(&cpu,p.update);
        check(!jf2_profile&&writes==after,"modified code allowed input writes");
    }
    check(stream.peek()==std::char_traits<char>::eof(),"extra fixture bytes");
    std::cout<<"PASS: "<<count<<" actual PAL layouts, aim/strafe/restoration, load/input reset and rejected guards\n";
}
int main(int argc,char** argv){
    try{
        guard_tests();std::cout<<"PASS: JF2 complete guards and generated site roles\n";
        if(argc==2)fixture_tests(argv[1]);else check(argc==1,"expected optional private fixture");return 0;
    }catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}
}
