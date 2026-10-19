#include <array>
#include <cstring>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <vector>
#include "host_input.h"
#include "../../robbit-mon-dieu/tools/robbit_input_core.h"
#include "robbit_profile_core.h"

static void check(bool ok,const char* message){if(!ok)throw std::runtime_error(message);}
static std::array<uint8_t,0x200000> ram{};
static unsigned writes=0,input_resets=0;
static uint32_t psx_read_word(uint32_t address){
    const auto p=address&0x1fffffffu;if(p+4>ram.size())return 0;
    return uint32_t(ram[p])|uint32_t(ram[p+1])<<8|uint32_t(ram[p+2])<<16|uint32_t(ram[p+3])<<24;
}
static uint16_t psx_read_half(uint32_t address){return uint16_t(psx_read_word(address));}
static void psx_write_word(uint32_t address,uint32_t value){
    const auto p=address&0x1fffffffu;check(p+4<=ram.size(),"write outside RAM");
    for(unsigned i=0;i<4;++i)ram[p+i]=uint8_t(value>>(i*8));++writes;
}
static void psx_write_half(uint32_t address,uint16_t value){
    const auto p=address&0x1fffffffu;check(p+2<=ram.size(),"half write outside RAM");
    ram[p]=uint8_t(value);ram[p+1]=uint8_t(value>>8);++writes;
}
struct CPUState {uint32_t gpr[32]{};};
static struct {int kind=1;} g_players[1];
static bool collection_mode=true;
static bool robbit_host_input_ready(){return collection_mode||g_players[0].kind==1;}
static uint64_t s_frame_count=100;
static uint64_t SDL_GetTicks(){return 1000;}
static std::array<uint8_t,512> physical_keys{};
static const uint8_t* SDL_GetKeyboardState(void*){return physical_keys.data();}
static bool load_guard=false,collection_aim_live=false;
static int savestate_input_guard_active(){return load_guard;}
static RobbitMouseLook robbit_look;
static RobbitKeyPulses<512> robbit_pulses;
static bool robbit_captured=false,robbit_modern=true,robbit_invert=false;
static int robbit_sensitivity=100,robbit_move_x=0,robbit_move_forward=0;
static uint64_t robbit_move_until=0,robbit_player_frame=0,robbit_motion_frame=UINT64_MAX;
static uint64_t robbit_vector_calls=0,robbit_move_updates=0,robbit_camera_updates=0;
static uint32_t robbit_vector_ra=0,robbit_vector_a2=0,robbit_vector_a3=0;
static collection_input::Sample physical_pad;
static collection_input::ReleaseGate release_gate;
#include "robbit_profile_controls.h"
static void robbit_release_mouse(){
    robbit_captured=false;robbit_look.clear();robbit_pulses.block_held(SDL_GetKeyboardState(nullptr));
    robbit_move_x=robbit_move_forward=0;robbit_move_until=0;
}
static void collection_input_reset(){
    ++input_resets;release_gate.arm(physical_pad);collection_aim_live=false;robbit_look.clear();
}

static void guard_tests(){
    RobbitProfile profile{};profile.update=0x80010000;profile.pitch=0x80010020;
    profile.vector=0x80010040;profile.rotation_return=0x80010060;
    for(unsigned i=0;i<9;++i){
        const uint32_t address=0x80010000+i*32;
        psx_write_word(address,0x03e00008);psx_write_word(address+4,0);
        psx_write_word(address+8,0x24020001);psx_write_word(address+12,0x34030004);
        profile.guards[i]={address,4,0x03e00008,0x34030004,0xc69d280921a390d8ull};
    }
    check(robbit_profile_matches(profile,psx_read_word),"exact synthetic guards rejected");
    for(const auto& guard:profile.guards){
        psx_write_word(guard.address+8,0x24020002);
        check(!robbit_profile_matches(profile,psx_read_word),"interior mutation accepted");
        psx_write_word(guard.address+8,0x24020001);
    }
    for(uint32_t pc:{profile.update,profile.pitch,profile.vector,profile.rotation_return}){
        check(robbit_profile_site(profile,pc),"site rejected");
        check(robbit_profile_site(profile,pc&0x1fffffff),"physical site rejected");
    }
    check(!robbit_profile_site(profile,profile.update+4),"unconfigured site accepted");
    auto invalid=profile;invalid.guards[0].words=0;
    check(!robbit_profile_matches(invalid,psx_read_word),"empty guard accepted");
    invalid=profile;invalid.guards[0].address=0x801ffffc;
    check(!robbit_profile_matches(invalid,psx_read_word),"out-of-RAM guard accepted");
    invalid=profile;invalid.guards[0].address|=1;
    check(!robbit_profile_matches(invalid,psx_read_word),"unaligned guard accepted");
}

static uint32_t read_u32(std::ifstream& stream){
    uint8_t bytes[4];stream.read(reinterpret_cast<char*>(bytes),4);check(bool(stream),"truncated fixture");
    return uint32_t(bytes[0])|uint32_t(bytes[1])<<8|uint32_t(bytes[2])<<16|uint32_t(bytes[3])<<24;
}
static void fixture_tests(const char* path){
    std::ifstream stream(path,std::ios::binary);check(bool(stream),"fixture missing");
    check(read_u32(stream)==0x31444d52,"fixture magic changed");
    const auto count=read_u32(stream);check(count==std::size(robbit_profiles),"fixture/profile count changed");
    for(unsigned index=0;index<count;++index){
        const auto& expected=robbit_profiles[index];const auto load=read_u32(stream),size=read_u32(stream);
        check(load>=0x80000000&&uint64_t(load)+size<=0x80200000,"fixture bounds changed");
        ram.fill(0);stream.read(reinterpret_cast<char*>(ram.data()+(load&0x1fffffff)),size);
        check(bool(stream),"fixture body truncated");
        check(robbit_profile_matches(expected,psx_read_word),"actual request guards rejected");
        physical_keys[26]=1;physical_pad.buttons[0]=true;physical_pad.axes[0]=.8f;
        const auto resets_before=input_resets;
        robbit_captured=true;robbit_look.move(500,300);
        robbit_profile=nullptr;++s_frame_count;
        check(robbit_supported(),"request layout not found");
        const auto& p=*robbit_profile;
        check(p.player==expected.player&&p.mode==expected.mode&&p.live_flags==expected.live_flags&&
            p.update==expected.update&&p.rotation_return==expected.rotation_return,"wrong request layout selected");
        check(input_resets>resets_before&&!robbit_captured&&!robbit_look.initialized&&robbit_look.dx==0,
              "profile change retained old aim/capture");
        check(!release_gate.clean(physical_pad).buttons[0]&&release_gate.clean(physical_pad).axes[0]==0,
              "profile change retained held controller input");
        check(!robbit_pulses.sample(physical_keys.data(),SDL_GetTicks())[26],"profile change retained held key");
        physical_pad={};release_gate.clean(physical_pad);physical_keys[26]=0;
        robbit_pulses.sample(physical_keys.data(),SDL_GetTicks());
        physical_pad.buttons[0]=true;check(release_gate.clean(physical_pad).buttons[0],"fresh controller input blocked");
        psx_write_word(p.live_flags,0x00100000);psx_write_half(p.mode,1);
        psx_write_half(p.lock1,0);psx_write_half(p.lock2,0);
        psx_write_word(p.player+0x10,0);psx_write_word(p.player+0x14,0);
        CPUState cpu;robbit_captured=true;robbit_look.move(8,-2);++s_frame_count;
        robbit_desktop_camera(&cpu,p.update);
        check(psx_read_word(p.player+0x14)==12*4096&&psx_read_word(p.player+0x10)==3*4096,
              "modern aim used wrong request state");
        robbit_move_x=1;robbit_move_forward=1;robbit_move_until=1100;
        cpu.gpr[31]=p.move1_return;cpu.gpr[6]=p.player+0x28;cpu.gpr[7]=p.player+0x20;
        robbit_desktop_camera(&cpu,p.vector);
        check(cpu.gpr[4]==uint32_t((12+512)*4096),"modern movement heading wrong");
        cpu.gpr[4]=123;cpu.gpr[31]^=4;robbit_desktop_camera(&cpu,p.vector);
        check(cpu.gpr[4]==123,"unknown vector caller changed");
        cpu.gpr[31]=p.move2_return;cpu.gpr[6]+=4;robbit_desktop_camera(&cpu,p.vector);
        check(cpu.gpr[4]==123,"wrong vector output pointer accepted");
        cpu.gpr[6]=p.player+0x28;g_players[0].kind=2;robbit_desktop_camera(&cpu,p.vector);
        check(cpu.gpr[4]==uint32_t((12+512)*4096),"collection controls depended on legacy keyboard device kind");
        collection_mode=false;cpu.gpr[4]=123;robbit_desktop_camera(&cpu,p.vector);
        check(cpu.gpr[4]==123,"standalone device guard changed");collection_mode=true;g_players[0].kind=1;
        psx_write_word(p.player+0x48,0x801f0000);cpu.gpr[17]=p.player;cpu.gpr[31]=p.rotation_return;
        robbit_desktop_camera(&cpu,p.rotation_return);
        check(psx_read_half(0x801f0028)==3,"physical pitch transfer used wrong actor");
        psx_write_word(p.player+0x10,0);robbit_desktop_camera(&cpu,p.pitch);
        check(psx_read_word(p.player+0x10)==3*4096,"pitch setter used wrong request state");
        psx_write_half(p.lock1,1);const auto count_before=writes;robbit_look.move(5,5);++s_frame_count;
        robbit_desktop_camera(&cpu,p.update);check(writes==count_before,"locked request accepted aim writes");
        psx_write_half(p.lock1,0);const auto address=p.guards[0].address+8;
        psx_write_word(address,psx_read_word(address)^1);const auto before=writes;
        robbit_desktop_camera(&cpu,p.update);
        check(!robbit_profile&&writes==before,"changed guard allowed control writes");
    }
    check(stream.peek()==std::char_traits<char>::eof(),"extra fixture bytes");
    std::cout<<"PASS: "<<count<<" actual request layouts, aim/movement/pitch, held-input reset and rejected guards\n";
}
int main(int argc,char** argv){
    try{
        guard_tests();std::cout<<"PASS: complete guard ranges and configured sites\n";
        if(argc==2)fixture_tests(argv[1]);
        else check(argc==1,"expected an optional private fixture file");
        return 0;
    }catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}
}
