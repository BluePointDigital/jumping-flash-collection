#include <array>
#include <cstdint>
#include <filesystem>
#include <iostream>
#include <stdexcept>
#include "host_input.h"

using Uint8=uint8_t;
using SDL_JoystickID=int;
using SDL_GameControllerButton=int;
using SDL_GameControllerAxis=int;
constexpr int SDL_NUM_SCANCODES=512,SDL_CONTROLLER_BUTTON_MAX=21,SDL_WINDOW_INPUT_FOCUS=1;
enum {SDL_CONTROLLER_BUTTON_A,SDL_CONTROLLER_BUTTON_B,SDL_CONTROLLER_BUTTON_X,SDL_CONTROLLER_BUTTON_Y,
 SDL_CONTROLLER_BUTTON_BACK,SDL_CONTROLLER_BUTTON_GUIDE,SDL_CONTROLLER_BUTTON_START,
 SDL_CONTROLLER_BUTTON_LEFTSTICK,SDL_CONTROLLER_BUTTON_RIGHTSTICK,
 SDL_CONTROLLER_BUTTON_LEFTSHOULDER,SDL_CONTROLLER_BUTTON_RIGHTSHOULDER,
 SDL_CONTROLLER_BUTTON_DPAD_UP,SDL_CONTROLLER_BUTTON_DPAD_DOWN,SDL_CONTROLLER_BUTTON_DPAD_LEFT,SDL_CONTROLLER_BUTTON_DPAD_RIGHT};
enum {SDL_SCANCODE_A=4,SDL_SCANCODE_D=7,SDL_SCANCODE_S=22,SDL_SCANCODE_W=26};
struct SDL_GameController {int id;};
struct SDL_Window {};
static SDL_GameController devices[2]{{11},{22}};
static SDL_Window window;
static SDL_Window* sdl_window=&window;
static int available=-1;
static std::array<bool,2> attached{};
static std::array<collection_input::Sample,2> samples{};
static uint64_t s_frame_count=1,ticks=1000;
static bool collection_mode=true,gameplay=false,loading=false,focused=true;
static std::filesystem::path collection_user_data="unused-input-unit-fixture";
static int resets=0;
static float applied_x=0,applied_forward=0;
static void SDL_GameControllerClose(SDL_GameController*){}
static SDL_GameController* SDL_GameControllerOpen(int i){return available==i?&devices[i]:nullptr;}
static bool SDL_GameControllerGetAttached(SDL_GameController* p){return attached[p-devices];}
static SDL_GameController* SDL_GameControllerGetJoystick(SDL_GameController* p){return p;}
static int SDL_JoystickInstanceID(SDL_GameController* p){return p->id;}
static int SDL_NumJoysticks(){return available>=0?2:0;}
static bool SDL_IsGameController(int i){return available==i;}
static int SDL_JoystickGetDeviceInstanceID(int i){return devices[i].id;}
static bool SDL_GameControllerGetButton(SDL_GameController* p,int button){return samples[p-devices].buttons[button];}
static int SDL_GameControllerGetAxis(SDL_GameController* p,int axis){return int(samples[p-devices].axes[axis]*32767);}
static uint32_t SDL_GetWindowFlags(SDL_Window*){return focused?SDL_WINDOW_INPUT_FOCUS:0;}
static uint64_t SDL_GetTicks(){return ticks;}
#include "host_input_sdl.h"
static bool collection_gameplay_live(){return gameplay;}
static void collection_look_apply(double,double){}
static void collection_look_reset(){++resets;}
static void collection_move_apply(float x,float y){applied_x=x;applied_forward=y;}
static int savestate_input_guard_active(){return loading;}
static std::array<Uint8,SDL_NUM_SCANCODES> keys{};
static void check(bool ok,const char* message){if(!ok)throw std::runtime_error(message);}
static void poll(){++s_frame_count;ticks+=16;collection_host_keys(keys.data(),1);}

int main(){
 try{
    // Hold confirm while connecting on a title screen; do not launch a game.
    available=0;attached[0]=true;samples[0].buttons[SDL_CONTROLLER_BUTTON_A]=true;
    poll();check(collection_controller_word==0xffff,"new controller accepted held confirm");
    samples[0]={};poll();samples[0].buttons[SDL_CONTROLLER_BUTTON_A]=true;poll();
    check(!(collection_controller_word&0x4000),"fresh confirm was blocked");

    gameplay=true;samples[0]={};poll();poll();samples[0].axes[2]=.8f;poll();
    check(collection_aim_owned&&collection_aim_live,"fresh aim did not acquire ownership");
    const auto before=resets;
    attached[0]=false;available=1;attached[1]=true;
    samples[1].buttons[SDL_CONTROLLER_BUTTON_A]=true;samples[1].axes[2]=.8f;
    poll();
    check(resets>before&&!collection_aim_owned&&!collection_aim_live,"replacement retained old aim ownership");
    check(collection_controller_word==0xffff&&collection_aim_x==0,"replacement accepted held input");
    samples[1]={};poll();samples[1].buttons[SDL_CONTROLLER_BUTTON_A]=true;samples[1].axes[2]=.8f;poll();
    check(!(collection_controller_word&0x4000)&&collection_aim_live,"fresh replacement input rejected");

    attached[1]=false;available=-1;poll();
    check(!collection_controller&&!collection_aim_owned&&!collection_aim_live&&collection_controller_word==0xffff,
        "disconnect retained controller state");
    attached[1]=true;available=1;samples[1].axes[4]=1;poll();
    check(collection_controller_word==0xffff,"reconnect accepted held trigger");
    samples[1]={};poll();samples[1].axes[4]=1;poll();
    check(!(collection_controller_word&0x2000),"fresh trigger rejected");

    // Losing focus or loading must require neutral input before resuming too.
    focused=false;poll();focused=true;poll();check(collection_controller_word==0xffff,"focus regain replayed held trigger");
    samples[1]={};poll();samples[1].buttons[SDL_CONTROLLER_BUTTON_A]=true;poll();
    loading=true;poll();loading=false;poll();check(collection_controller_word==0xffff,"load replayed held jump");
    samples[1]={};poll();samples[1].buttons[SDL_CONTROLLER_BUTTON_A]=true;poll();
    check(!(collection_controller_word&0x4000),"fresh input after load rejected");
    std::cout<<"PASS: connect/reconnect, aim ownership, held buttons/triggers, focus and loading release gates\n";
    return 0;
 }catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}
}
