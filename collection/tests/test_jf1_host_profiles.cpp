#include <array>
#include <cstdint>
#include <cstdio>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include "host_input.h"

static void check(bool ok,const char* message){if(!ok)throw std::runtime_error(message);}
using Uint8=uint8_t;
constexpr int SDL_NUM_SCANCODES=512,SDL_WINDOW_INPUT_FOCUS=1;
enum {SDL_EVENT_WINDOW_FOCUS_LOST=1,SDL_KEYDOWN,SDL_KEYUP,SDL_MOUSEBUTTONUP,SDL_MOUSEBUTTONDOWN,SDL_MOUSEMOTION};
enum {SDL_SCANCODE_A=4,SDL_SCANCODE_D=7,SDL_SCANCODE_E=8,SDL_SCANCODE_F=9,SDL_SCANCODE_S=22,
      SDL_SCANCODE_W=26,SDL_SCANCODE_RETURN=40,SDL_SCANCODE_ESCAPE=41,SDL_SCANCODE_SPACE=44,SDL_SCANCODE_F6=63};
constexpr int SDL_BUTTON_LEFT=1;
#define SDL_BUTTON_MASK(b) (1u<<((b)-1))
constexpr uint32_t SDL_BUTTON_LMASK=1,SDL_BUTTON_RMASK=4;
struct SDL_Event {int type;struct {int scancode;bool repeat;} key;
    struct {int button;} button;struct {double x,y,xrel,yrel;} motion;};
struct SDL_Window{};
static SDL_Window window;
static SDL_Window* sdl_window=&window;
static std::array<uint8_t,SDL_NUM_SCANCODES> physical_keys{};
static uint32_t physical_mouse=0;
static const Uint8* SDL_GetKeyboardState(void*){return physical_keys.data();}
static uint32_t SDL_GetMouseState(void*,void*){return physical_mouse;}
static uint32_t SDL_GetWindowFlags(SDL_Window*){return SDL_WINDOW_INPUT_FOCUS;}
static bool SDL_SetWindowMouseGrab(SDL_Window*,bool){return true;}
static bool SDL_SetWindowRelativeMouseMode(SDL_Window*,bool){return true;}
static void SDL_ShowCursor(){}
static void SDL_HideCursor(){}
static void SDL_GetWindowSize(SDL_Window*,int* w,int* h){*w=1280;*h=800;}
static void SDL_WarpMouseInWindow(SDL_Window*,int,int){}
static uint64_t SDL_GetTicks(){return 1000;}
static void host_osd_push(const char*,int){}
static uint16_t psx_keybinds_pad_word(const Uint8*,int){return 0xffff;}
static bool collection_mode=true,collection_deck=false,collection_aim_live=false,load_guard=false;
static uint16_t collection_controller_word=0xffff;
static collection_input::Config collection_controls;
static bool savestate_input_guard_active(){return load_guard;}
static uint64_t s_frame_count=100;
struct CPUState {uint32_t gpr[32]{};};
static std::array<uint8_t,0x200000> ram{};
static unsigned writes=0,input_resets=0;
static uint32_t psx_read_word(uint32_t a){
    a&=0x1fffffffu;if(uint64_t(a)+4>ram.size())return 0;
    return uint32_t(ram[a])|uint32_t(ram[a+1])<<8|uint32_t(ram[a+2])<<16|uint32_t(ram[a+3])<<24;
}
static uint16_t psx_read_half(uint32_t a){return uint16_t(psx_read_word(a));}
static void psx_write_word(uint32_t a,uint32_t v){
    a&=0x1fffffffu;check(uint64_t(a)+4<=ram.size(),"write outside RAM");
    for(unsigned i=0;i<4;++i)ram[a+i]=uint8_t(v>>(i*8));++writes;
}
static collection_input::Sample physical_pad;
static collection_input::ReleaseGate release_gate;
#include "jf1_desktop.h"
static void collection_input_reset(){
    ++input_resets;release_gate.arm(physical_pad);collection_aim_live=false;collection_controller_word=0xffff;
}

static void guard_tests(){
    ram.fill(0);jf1_profile=&jf1_profiles[0];jf1_player_frame=s_frame_count;
    physical_keys[SDL_SCANCODE_W]=1;physical_mouse=SDL_BUTTON_LMASK;
    physical_pad.buttons[0]=true;physical_pad.axes[2]=1;
    jf1_captured=true;collection_aim_live=true;jf1_look.move(10,5);
    jf1_move_x=jf1_move_forward=jf1_pad_x=jf1_pad_forward=1;
    const auto resets=input_resets;
    check(!jf1_find_profile(0)&&!jf1_player_frame&&!jf1_captured,"invalid profile retained scene/capture");
    check(input_resets==resets+1&&!collection_aim_live&&jf1_look.dx==0,"invalid profile retained aim");
    check(jf1_move_x==0&&jf1_move_forward==0&&jf1_pad_x==0&&jf1_pad_forward==0,"invalid profile retained movement");
    check(jf1_blocked_keys[SDL_SCANCODE_W]&&jf1_blocked_mouse==SDL_BUTTON_LMASK,"held sources not blocked");
    const auto sample=release_gate.clean(physical_pad);
    check(!sample.buttons[0]&&sample.axes[2]==0,"held controller not blocked");
    check(!jf1_find_profile(0)&&input_resets==resets+1,"unsupported profile repeatedly reset input");
    physical_keys.fill(0);physical_mouse=0;physical_pad={};release_gate.clean(physical_pad);
}

static uint32_t read_u32(std::ifstream& stream){
    uint8_t b[4];check(bool(stream.read(reinterpret_cast<char*>(b),4)),"short fixture header");
    return uint32_t(b[0])|uint32_t(b[1])<<8|uint32_t(b[2])<<16|uint32_t(b[3])<<24;
}
static void fixture_tests(const char* path){
    std::ifstream stream(path,std::ios::binary);check(bool(stream),"fixture missing");
    check(read_u32(stream)==0x3146314a,"wrong JF1 fixture format");
    const auto count=read_u32(stream);check(count==std::size(jf1_profiles),"wrong fixture count");
    for(unsigned i=0;i<count;++i){
        const auto load=read_u32(stream),size=read_u32(stream),offset=load&0x1fffffffu;
        check(uint64_t(offset)+size<=ram.size(),"fixture outside RAM");ram.fill(0);
        check(bool(stream.read(reinterpret_cast<char*>(ram.data()+offset),size)),"short fixture body");
        const auto& p=jf1_profiles[i];check(jf1_guards(p),"source profile guard mismatch");
        // Loading occurs inside the same guest frame: the old per-frame cache
        // must not return a now-invalid profile or retain the previous inputs.
        const auto* previous=jf1_profile;const auto resets=input_resets;
        physical_keys[SDL_SCANCODE_W]=1;physical_mouse=SDL_BUTTON_LMASK;
        physical_pad.buttons[0]=true;physical_pad.axes[2]=1;
        jf1_captured=true;collection_aim_live=true;jf1_look.move(10,5);
        jf1_move_x=jf1_move_forward=jf1_pad_x=jf1_pad_forward=1;
        const auto* selected=jf1_find_profile(p.update);
        check(selected&&jf1_guards(*selected)&&selected->player==p.player,"stale same-frame profile returned");
        if(selected!=previous){
            check(input_resets==resets+1&&!jf1_captured&&!jf1_look.initialized&&jf1_look.dx==0,
                  "profile change did not reset aim/controller");
            check(jf1_move_x==0&&jf1_move_forward==0&&jf1_pad_x==0&&jf1_pad_forward==0,
                  "profile change retained movement");
            check(jf1_blocked_keys[SDL_SCANCODE_W]&&jf1_blocked_mouse==SDL_BUTTON_LMASK,
                  "held keyboard/mouse was not blocked");
            check(!release_gate.clean(physical_pad).buttons[0]&&release_gate.clean(physical_pad).axes[2]==0,
                  "held controller was not blocked");
        }
        psx_write_word(p.demo_mode,0);psx_write_word(p.control_live,1);psx_write_word(p.original_pause,0);
        psx_write_word(p.control_block,0);psx_write_word(p.finish,0);psx_write_word(p.finish2,0);
        psx_write_word(p.movie,1);psx_write_word(p.movie_ready,0);psx_write_word(p.player+0x5c,100);
        check(!jf1_gameplay(),"new profile inherited previous scene freshness");
        CPUState cpu;jf1_desktop_camera(&cpu,p.update);check(jf1_gameplay(),"valid update did not establish gameplay");
        jf1_input_pad(physical_keys.data(),1);
        check(jf1_move_forward==0,"held keyboard moved new scene");
        physical_keys[SDL_SCANCODE_W]=0;jf1_input_pad(physical_keys.data(),1);
        physical_keys[SDL_SCANCODE_W]=1;
        check(!(jf1_input_pad(physical_keys.data(),1)&0x10)&&jf1_move_forward>0,"fresh movement rejected");
        collection_aim_live=true;cpu.gpr[4]=p.player;jf1_look.move(10,5);
        psx_write_word(p.player+0x8c,0);psx_write_word(p.player+0x90,0);
        jf1_desktop_camera(&cpu,p.movement);
        check(psx_read_word(p.player+0x8c)==10,"fresh same-frame scene aim rejected");
        // A change in the middle of a routine must invalidate a profile even
        // if it was already recognized in this frame.
        const auto address=p.guards[0].address+8;psx_write_word(address,psx_read_word(address)^0xffffffffu);
        const auto before=writes;jf1_desktop_camera(&cpu,p.movement);
        check(!jf1_profile&&writes==before&&!jf1_gameplay(),"changed same-frame guard allowed input writes");
        physical_pad={};release_gate.clean(physical_pad);physical_keys.fill(0);physical_mouse=0;
        jf1_input_previous=false;
    }
    check(stream.peek()==std::char_traits<char>::eof(),"extra fixture bytes");
    std::cout<<"PASS: "<<count<<" real JF1 layouts, same-frame guard changes, input release and fresh aim/movement\n";
}
int main(int argc,char** argv){
    try{
        guard_tests();std::cout<<"PASS: invalid JF1 profile releases held inputs\n";
        if(argc==2)fixture_tests(argv[1]);else check(argc==1,"expected optional private fixture");
        return 0;
    }catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}
}
