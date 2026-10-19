#include <cstdint>
#include <cstdlib>
#include <cstdio>
#include <vector>
#define PSX_SDL3 1
#define PSX_NO_DEBUG_TOOLS 1
#define PSX_MAX_PLAYERS 2
using SDL_Keycode=int;
enum {SDL_KEYDOWN=1,SDL_EVENT_WINDOW_FOCUS_LOST,SDL_EVENT_GAMEPAD_BUTTON_DOWN,
      SDL_EVENT_GAMEPAD_ADDED,SDL_EVENT_GAMEPAD_REMOVED,SDL_QUIT};
enum {SDL_SCANCODE_F8=20,SDL_SCANCODE_UP,SDL_SCANCODE_DOWN,SDL_SCANCODE_W,
      SDL_SCANCODE_S,SDL_SCANCODE_ESCAPE,SDL_SCANCODE_RETURN};
enum {SDLK_UP=40,SDLK_DOWN,SDLK_RETURN};
enum {SDL_CONTROLLER_BUTTON_BACK=60,SDL_CONTROLLER_BUTTON_START,
      SDL_CONTROLLER_BUTTON_DPAD_UP,SDL_CONTROLLER_BUTTON_DPAD_DOWN,
      SDL_CONTROLLER_BUTTON_B,SDL_CONTROLLER_BUTTON_A};
#define SDL_CONTROLLERDEVICEADDED SDL_EVENT_GAMEPAD_ADDED
#define SDL_CONTROLLERDEVICEREMOVED SDL_EVENT_GAMEPAD_REMOVED
struct SDL_Event {int type=0;struct {int scancode=0,key=0,repeat=0;} key;
    struct {int button=0;} gbutton;struct {int which=0;} gdevice;};
struct Player {int instance=-1;};
static Player g_players[PSX_MAX_PLAYERS];
static bool collection_mode=true,collection_menu_open=true;
static void* sdl_window=nullptr;
static int available=-1,resets=0,closes=0,refreshes=0,guard=0,polls=0,held=1;
static std::vector<int> calls;
static std::vector<SDL_Event> queue;
static std::size_t cursor=0;
static void host_osd_push(const char*,int){}
static void collection_input_reset(){resets++;held=0;calls.push_back(1);}
static bool collection_gameplay_live(){return false;}
static void psx_crash_trace_set_exit_origin(const char*){}
static void shutdown_runtime(){}
static void psx_local_mouse_begin(void*,bool){}
static void psx_local_mouse_reset(){}
static void freeze_heartbeat_set_paused(int){}
static void starvation_watchdog_heartbeat(){}
static void rewind_pause_present(){}
static void savestate_input_guard_arm(){guard++;}
static void close_controller(){closes++;calls.push_back(2);for(auto& p:g_players)p.instance=-1;}
static void refresh_player_devices(){refreshes++;calls.push_back(3);g_players[0].instance=available;}
static int SDL_PollEvent(SDL_Event* e){
    polls++;
    if(cursor==queue.size())return 0;
    *e=queue[cursor++];
    if(e->type==SDL_EVENT_GAMEPAD_ADDED)available=e->gdevice.which;
    if(e->type==SDL_EVENT_GAMEPAD_REMOVED && available==e->gdevice.which)available=-1;
    return 1;
}
static void SDL_Delay(int){if(collection_menu_open && cursor==queue.size())std::exit(9);}
// The tested implementation is the actual full header, without copied logic.
#include "../runtime/collection_runtime.h"
static SDL_Event event(int type,int instance=0){SDL_Event e;e.type=type;e.gdevice.which=instance;return e;}
static SDL_Event back(){SDL_Event e;e.type=SDL_EVENT_GAMEPAD_BUTTON_DOWN;e.gbutton.button=SDL_CONTROLLER_BUTTON_B;return e;}
static void reset(){
    collection_mode=true;collection_menu_open=true;collection_menu_choice=0;
    collection_pad_frames=0;g_players[0].instance=11;g_players[1].instance=-1;
    available=11;resets=closes=refreshes=guard=polls=0;held=1;calls.clear();queue.clear();cursor=0;
}
#define CHECK(c) do{if(!(c)){std::printf("FAIL line %d: %s\n",__LINE__,#c);return 1;}}while(0)
int main(){
    reset();queue={event(SDL_EVENT_GAMEPAD_REMOVED,11),event(SDL_EVENT_GAMEPAD_ADDED,22),back()};
    collection_host_pause_loop();
    CHECK(g_players[0].instance==22);CHECK(resets==2 && closes==1 && refreshes==2);
    CHECK(held==0 && guard==1 && collection_pad_frames==0);
    CHECK(calls==std::vector<int>({1,2,3,1,3}));
    reset();queue={event(SDL_EVENT_GAMEPAD_REMOVED,99),back()};collection_host_pause_loop();
    CHECK(g_players[0].instance==11 && closes==0 && refreshes==0 && resets==1 && guard==1);
    reset();g_players[0].instance=-1;available=-1;
    queue={event(SDL_EVENT_GAMEPAD_ADDED,33),back()};collection_host_pause_loop();
    CHECK(g_players[0].instance==33 && closes==0 && refreshes==1 && resets==1 && guard==1);
    reset();queue={event(SDL_EVENT_WINDOW_FOCUS_LOST),back()};collection_host_pause_loop();
    CHECK(resets==1 && held==0 && closes==0 && refreshes==0 && guard==1);
    reset();collection_mode=false;queue={back()};collection_host_pause_loop();CHECK(polls==0 && guard==0);
    reset();collection_menu_open=false;queue={back()};collection_host_pause_loop();CHECK(polls==0 && guard==0);
    std::puts("PASS six actual-header pause event scenarios");return 0;
}
