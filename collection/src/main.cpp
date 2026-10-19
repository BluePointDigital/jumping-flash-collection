#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <SDL3/SDL.h>
#include <SDL3/SDL_opengl.h>
#include <imgui.h>
#include <imgui_impl_sdl3.h>
#include <imgui_impl_opengl3.h>
#define STB_IMAGE_IMPLEMENTATION
#include <stb_image.h>
#include <toml.hpp>
#include "model.h"
#include "menu_style.h"
#include "host_input.h"
#include <algorithm>
#include <atomic>
#include <cmath>
#include <fstream>
#include <iostream>
#include <memory>

using namespace collection;
static constexpr float PI=3.14159265359f;
enum class Page { Home, Game, Settings, Controls, Gallery, Credits, Setup, Files };
struct Texture {GLuint id=0;int w=0,h=0;};
struct FileEntry {fs::path path;std::string label;bool folder=false;};
struct App {
    fs::path root;
    std::vector<Game> games;
    Settings settings;
    Page page=Page::Home;
    SDL_Window* window=nullptr;
    SDL_GLContext context=nullptr;
    SDL_Gamepad* pad=nullptr;
    SDL_AudioStream* audio=nullptr;
    ImFont *small=nullptr,*body=nullptr,*heading=nullptr,*logo=nullptr;
    HANDLE child=nullptr;
    bool importing=false,done=false,controller=false;
    bool pending_play=false;
    std::string notice;
    int picker_kind=0;
    std::vector<Texture> gallery;
    Texture sky,mascot;
    std::array<Texture,3> islands{};
    std::array<float,3> emphasis{};
    int gallery_index=0,focus=0;
    uint64_t nav_repeat=0;
    std::atomic<float> music_volume{.08f};
    uint64_t audio_sample=0;
    collection_input::Config controls;
    int rebinding=-1;
    bool rebind_ready=false;
    bool input_ready=false;
    fs::path picker_directory;
    std::vector<FileEntry> files;
    std::vector<Page> history;
    bool scroll_selection=false;
    float credits_scroll=0;
};
static App app;
static void initialize_window();
static ImU32 rgba(int r,int g,int b,int a=255){return IM_COL32(r,g,b,a);}
static ImVec2 point(float x,float y){return {x,y};}
static void text(ImDrawList* d,ImFont* f,float size,float x,float y,ImU32 color,const std::string& value){
    x=std::round(x);y=std::round(y);
    d->AddText(f,size,point(x+2,y+2),rgba(6,13,40,230),value.c_str());
    d->AddText(f,size,point(x,y),color,value.c_str());
}

static void music_callback(void* context,SDL_AudioStream* stream,int bytes,int) {
    auto* a=static_cast<App*>(context);
    const int samples=bytes/int(sizeof(float));std::vector<float> pcm(samples);
    const double notes[]={130.8128,164.8138,195.9977,246.9417,164.8138,146.8324,174.6141,195.9977};
    const float volume=a->music_volume.load();
    for(int i=0;i<samples;i+=2){double t=double(a->audio_sample++)/48000.;int step=int(t/3.)%8;double phase=std::fmod(t,3.)/3.;
        double envelope=std::sin(PI*phase);double tone=std::sin(2*PI*notes[step]*t)*.3+std::sin(2*PI*notes[step]*2*t)*.09;
        float sample=float(tone*envelope*envelope)*volume;pcm[i]=sample;if(i+1<samples)pcm[i+1]=sample;}
    SDL_PutAudioStreamData(stream,pcm.data(),samples*sizeof(float));
}
static void write_preferences(){save_settings(app.root/"data/collection.toml",app.settings);app.music_volume=app.settings.muted?0.f:app.settings.volume/100.f*.12f;}
static Texture load_texture(const fs::path& file){
    Texture t;int channels=0;
    if(!stbi_info(file.string().c_str(),&t.w,&t.h,&channels)||t.w<=0||t.h<=0||t.w>8192||t.h>8192)return {};
    auto* pixels=stbi_load(file.string().c_str(),&t.w,&t.h,&channels,4);if(!pixels)return {};
    glGenTextures(1,&t.id);glBindTexture(GL_TEXTURE_2D,t.id);
    glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_LINEAR);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_S,GL_CLAMP_TO_EDGE);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_T,GL_CLAMP_TO_EDGE);
    glTexImage2D(GL_TEXTURE_2D,0,GL_RGBA,t.w,t.h,0,GL_RGBA,GL_UNSIGNED_BYTE,pixels);stbi_image_free(pixels);return t;
}
static void release_texture(Texture& texture){if(texture.id)glDeleteTextures(1,&texture.id);texture={};}
static void art_image(ImDrawList* draw,const Texture& image,float cx,float cy,float width,ImU32 tint=IM_COL32_WHITE){
    if(!image.id)return;float height=width*image.h/image.w;
    draw->AddImage((ImTextureID)(intptr_t)image.id,point(cx-width/2,cy-height/2),point(cx+width/2,cy+height/2),point(0,0),point(1,1),tint);
}
static void unload_gallery(){for(auto& t:app.gallery)if(t.id)glDeleteTextures(1,&t.id);app.gallery.clear();app.gallery_index=0;}
static void release_window(){
    release_texture(app.sky);release_texture(app.mascot);for(auto& image:app.islands)release_texture(image);
    unload_gallery();if(app.pad){SDL_CloseGamepad(app.pad);app.pad=nullptr;}
    if(app.audio){SDL_DestroyAudioStream(app.audio);app.audio=nullptr;}
    ImGui_ImplOpenGL3_Shutdown();ImGui_ImplSDL3_Shutdown();ImGui::DestroyContext();
    SDL_GL_DestroyContext(app.context);SDL_DestroyWindow(app.window);app.context=nullptr;app.window=nullptr;
    app.input_ready=false;
}
static void load_gallery(){
    unload_gallery();const auto folder=app.root/"data/games"/app.games[app.settings.selected].id/"gallery";
    if(!fs::is_directory(folder))return;
    std::vector<fs::path> files;for(auto& entry:fs::directory_iterator(folder))if(entry.is_regular_file()&&entry.path().extension()==".png")files.push_back(entry.path());
    std::sort(files.begin(),files.end());
    for(const auto& file:files){auto t=load_texture(file);if(t.id)app.gallery.push_back(t);}
}
static fs::path controls_path(){return app.root/"data/games"/app.games[app.settings.selected].id/"host-input.toml";}
static void select_game(int direction){if(app.child||app.page==Page::Files)return;app.settings.selected=(app.settings.selected+direction+3)%3;app.focus=0;app.rebinding=-1;app.input_ready=false;write_preferences();if(app.page==Page::Gallery||app.page==Page::Game)load_gallery();if(app.page==Page::Controls)app.controls=collection_input::load(controls_path());}
static void show(Page page){app.page=page;app.focus=0;app.rebinding=-1;app.input_ready=false;if(page==Page::Gallery||page==Page::Game)load_gallery();if(page==Page::Controls)app.controls=collection_input::load(controls_path());}
static void go(Page page){if(app.child||page==app.page)return;if(app.history.size()==16)app.history.erase(app.history.begin());app.history.push_back(app.page);show(page);}
static int& action_binding(int action){if(action==0)return app.controls.jump;if(action==1)return app.controls.fire;if(action==2)return app.controls.secondary;return app.controls.special;}
static void rebind(int action){app.rebinding=action;app.rebind_ready=false;app.notice="Release the controls, then press a button or trigger. View / Escape cancels; Menu stays assigned to pause.";}
static void browse(const fs::path& folder){
    app.files.clear();app.picker_directory=folder;app.focus=0;app.input_ready=false;app.scroll_selection=true;
    if(folder.empty()){wchar_t drives[1024];DWORD count=GetLogicalDriveStringsW(1024,drives);
        if(count&&count<1024)for(auto* drive=drives;*drive;drive+=wcslen(drive)+1){fs::path path(drive);app.files.push_back({path,path.u8string(),true});}return;}
    app.files.push_back({{},"Drives",true});if(folder.parent_path()!=folder)app.files.push_back({folder.parent_path(),".. Parent folder",true});
    std::vector<FileEntry> entries;std::error_code error;
    for(auto it=fs::directory_iterator(folder,fs::directory_options::skip_permission_denied,error);!error&&it!=fs::directory_iterator();it.increment(error)){
        std::error_code ec;bool directory=it->is_directory(ec);if(ec)continue;
        auto extension=it->path().extension().string();std::transform(extension.begin(),extension.end(),extension.begin(),[](unsigned char c){return char(std::tolower(c));});
        bool supported=app.picker_kind==1?(extension==".cue"||extension==".bin"||extension==".chd"):app.picker_kind==2?(extension==".bin"||extension==".rom"||extension==".zip"):app.picker_kind==5?extension==".toml":(extension==".mcd"||extension==".mcr"||extension==".mc"||extension==".bin");
        if(!directory&&!supported)continue;
        entries.push_back({it->path(),(directory?"[Folder] ":"")+it->path().filename().u8string(),directory});}
    std::sort(entries.begin(),entries.end(),[](const auto& a,const auto& b){if(a.folder!=b.folder)return a.folder>b.folder;return a.label<b.label;});
    app.files.insert(app.files.end(),entries.begin(),entries.end());if(error)app.notice="Could not read this folder. Choose Parent folder or Drives.";
}
static void pick_file(int kind){
    app.picker_kind=kind;
    go(Page::Files);browse(app.root.parent_path());
}
static bool start_process(const fs::path& executable,const std::vector<std::wstring>& args,const fs::path& cwd,bool importing){
    if(app.child)return false;
    const auto logs=app.root/"data/games"/app.games[app.settings.selected].id/"logs";fs::create_directories(logs);
    const auto log=logs/(importing?"import.log":"runtime.log");
    SECURITY_ATTRIBUTES attributes{sizeof(attributes),nullptr,TRUE};
    HANDLE file=CreateFileW(log.c_str(),GENERIC_WRITE,FILE_SHARE_READ|FILE_SHARE_WRITE,&attributes,CREATE_ALWAYS,FILE_ATTRIBUTE_NORMAL,nullptr);
    if(file==INVALID_HANDLE_VALUE){app.notice="Could not open the session log.";return false;}
    std::wstring command=quote_arg(executable.wstring());for(const auto& a:args)command+=L" "+quote_arg(a);
    STARTUPINFOW startup{};startup.cb=sizeof(startup);startup.dwFlags=STARTF_USESTDHANDLES;startup.hStdOutput=file;startup.hStdError=file;startup.hStdInput=GetStdHandle(STD_INPUT_HANDLE);
    PROCESS_INFORMATION process{};
    const bool ok=CreateProcessW(executable.c_str(),command.data(),nullptr,nullptr,TRUE,CREATE_NO_WINDOW,nullptr,cwd.c_str(),&startup,&process);
    const DWORD launch_error=ok?ERROR_SUCCESS:GetLastError();
    CloseHandle(file);
    if(!ok){app.notice="Launch failed (Windows error "+std::to_string(launch_error)+"). See the session log.";return false;}
    CloseHandle(process.hThread);app.child=process.hProcess;app.importing=importing;
    if(!importing){app.music_volume=0;release_window();}
    return true;
}
static void start_import(int kind,const std::string& path){
    if(app.child)return;
    const auto& game=app.games[app.settings.selected];
    const auto python=app.root/"toolchain/python/python.exe";
    if(!fs::is_regular_file(python)){app.notice="The bundled import tools are missing. Reinstall the complete collection package.";return;}
    std::vector<std::wstring> args={(app.root/"tools/import_game.py").wstring(),L"--root",app.root.wstring(),L"--game",fs::path(game.id).wstring(),kind==1?L"--disc":kind==2?L"--bios":kind==5?L"--preferences":L"--card",fs::u8path(path).wstring()};
    if(kind==3||kind==4){args.push_back(L"--slot");args.push_back(kind==3?L"1":L"2");}
    if(start_process(python,args,app.root,true))app.notice="Checking and preparing your files. Originals are preserved.";
}
static void choose_file(int index){
    if(index<0||index>=int(app.files.size()))return;auto entry=app.files[index];
    if(entry.folder){browse(entry.path);return;}
    const int kind=app.picker_kind;if(!app.history.empty())app.history.pop_back();show(Page::Setup);start_import(kind,entry.path.u8string());
}
static void launch_verified_game(){
    const auto& g=app.games[app.settings.selected];auto ready=readiness(app.root,g);
    if(ready!="Ready to play"){app.notice=ready;go(Page::Setup);return;}
    const auto user=app.root/"data/games"/g.id;
    try{prepare_game_display(user,app.settings.experimental_widescreen.at(g.id),app.settings.deck);}
    catch(const std::exception& error){app.notice=std::string("Display preference could not be saved: ")+error.what();return;}
    const auto executable=within(app.root,g.executable);
    std::vector<std::wstring> args={L"--game",within(app.root,g.config).wstring(),L"--bios",within(app.root,g.bios).wstring(),L"--disc",within(app.root,g.disc).wstring(),L"--no-launcher",L"--user-data-dir",user.wstring(),L"--collection-mode"};
    args.push_back(L"--debug-port");args.push_back(g.id=="jf1"?L"4391":g.id=="jf2"?L"4392":L"4393");
    if(app.settings.deck)args.push_back(L"--deck-profile");
    start_process(executable,args,user,false);
}
static void play(){
    if(app.child)return;
    const auto& g=app.games[app.settings.selected];auto ready=readiness(app.root,g);
    if(ready!="Ready to play"){app.notice=ready;go(Page::Setup);return;}
    app.pending_play=true;
    const auto python=app.root/"toolchain/python/python.exe";
    std::vector<std::wstring> args={(app.root/"tools/import_game.py").wstring(),L"--root",app.root.wstring(),L"--game",fs::path(g.id).wstring(),L"--verify"};
    if(!start_process(python,args,app.root,true))app.pending_play=false;
    else app.notice="Verifying your game files before launch...";
}
static void poll_child(){
    if(!app.child || WaitForSingleObject(app.child,0)!=WAIT_OBJECT_0)return;
    DWORD code=0;const BOOL exit_code_available=GetExitCodeProcess(app.child,&code);const DWORD exit_status_error=exit_code_available?ERROR_SUCCESS:GetLastError();CloseHandle(app.child);app.child=nullptr;
    const bool succeeded=process_exit_succeeded(exit_code_available!=FALSE,code);
    if(app.pending_play){app.pending_play=false;app.importing=false;if(succeeded){launch_verified_game();return;}
        app.notice=exit_code_available?"Game verification failed. See this game's logs/import.log; use Prepare game files to repair it.":"Could not read the game verification result (Windows error "+std::to_string(exit_status_error)+"). See this game's logs/import.log.";return;}
    if(app.importing){app.notice=succeeded?(app.picker_kind==5?"Compatible preferences copied; previous preferences were backed up.":app.picker_kind>=3?"Memory card copied; previous cards were backed up.":"Files verified. Your game is ready when both disc and BIOS are installed."):!exit_code_available?"Could not read the preparation result (Windows error "+std::to_string(exit_status_error)+"). See this game's logs/import.log.":"Preparation failed. Your existing files were preserved.";
        if(exit_code_available && code!=0){std::ifstream log(app.root/"data/games"/app.games[app.settings.selected].id/"logs/import.log");std::string line;
            while(std::getline(log,line))if(line.rfind("Import failed:",0)==0){app.notice=line.substr(0,600);break;}}}
    else {initialize_window();SDL_RaiseWindow(app.window);load_gallery();app.notice=succeeded?"Welcome back, Robbit.":!exit_code_available?"The game closed, but Windows could not provide its exit status (error "+std::to_string(exit_status_error)+"). See this game's logs/runtime.log.":"The game stopped unexpectedly. Your memory cards are preserved; see this game's logs/runtime.log.";go(Page::Game);}
    app.importing=false;
}
static void open_pad(){
    if(app.pad || (app.child&&!app.importing))return;
    int count=0;SDL_JoystickID* ids=SDL_GetGamepads(&count);if(count>0)app.pad=SDL_OpenGamepad(ids[0]);SDL_free(ids);
}
static void activate(){
    if(app.child)return;
    if(app.page==Page::Home){go(Page::Game);return;}
    if(app.page==Page::Game){if(app.focus==0)play();else if(app.focus==1)go(Page::Controls);else if(app.focus==2)go(Page::Gallery);else go(Page::Setup);return;}
    if(app.page==Page::Controls&&app.focus>=4&&app.focus<=7){rebind(app.focus-4);return;}
    if(app.page==Page::Settings&&app.focus==5){
        auto& wide=app.settings.experimental_widescreen.at(app.games[app.settings.selected].id);
        wide=!wide;write_preferences();return;}
    if(app.page==Page::Setup){pick_file(app.focus+1);return;}
    if(app.page==Page::Files){choose_file(app.focus);return;}
}
static void back(){if(app.child)return;if(app.page==Page::Home){app.done=true;return;}if(app.history.empty())show(Page::Home);else{auto previous=app.history.back();app.history.pop_back();show(previous);}}
static void navigate(int x,int y){
    if(app.page==Page::Home){if(x)select_game(x);return;}
    if(app.page==Page::Game&&x){select_game(x);return;}
    if(app.page==Page::Files){if(y&&!app.files.empty()){app.focus=(app.focus+y+int(app.files.size()))%int(app.files.size());app.scroll_selection=true;}if(x<0)browse(app.picker_directory.parent_path());return;}
    if(app.page==Page::Gallery){if(!app.gallery.empty())app.gallery_index=(app.gallery_index+x+int(app.gallery.size()))%int(app.gallery.size());return;}
    if(app.page==Page::Credits){if(y)app.credits_scroll+=y*100;return;}
    const int count=app.page==Page::Game?4:app.page==Page::Setup?5:app.page==Page::Controls?8:6;
    if(y)app.focus=(app.focus+y+count)%count;
    if(app.page==Page::Settings){
        if(app.focus==0&&x)app.settings.volume=std::clamp(app.settings.volume+x*5,0,100);
        if(app.focus==1&&x)app.settings.muted=!app.settings.muted;
        if(app.focus==2&&x)app.settings.reduced_motion=!app.settings.reduced_motion;
        if(app.focus==3&&x){app.settings.fullscreen=!app.settings.fullscreen;SDL_SetWindowFullscreen(app.window,app.settings.fullscreen);}
        if(app.focus==4&&x)app.settings.deck=!app.settings.deck;
        if(app.focus==5&&x){auto& wide=app.settings.experimental_widescreen.at(app.games[app.settings.selected].id);wide=!wide;}
        if(x)write_preferences();
    }
    if(app.page==Page::Controls&&x){if(app.focus==0)app.controls.modern=!app.controls.modern;
        if(app.focus==1)app.controls.deadzone=std::clamp(app.controls.deadzone+x*2,5,40);
        if(app.focus==2)app.controls.sensitivity=std::clamp(app.controls.sensitivity+x*10,10,300);
        if(app.focus==3)app.controls.invert_y=!app.controls.invert_y;
        collection_input::save(controls_path(),app.controls);}
}
static void events(){
    SDL_Event e;while(SDL_PollEvent(&e)){
        if(!app.input_ready&&(e.type==SDL_EVENT_KEY_DOWN||e.type==SDL_EVENT_MOUSE_BUTTON_DOWN||e.type==SDL_EVENT_GAMEPAD_BUTTON_DOWN))continue;
        ImGui_ImplSDL3_ProcessEvent(&e);
        if(e.type==SDL_EVENT_MOUSE_BUTTON_DOWN||e.type==SDL_EVENT_MOUSE_MOTION&&(std::abs(e.motion.xrel)>2||std::abs(e.motion.yrel)>2))app.controller=false;
        if(app.rebinding>=0){
            if(e.type==SDL_EVENT_KEY_DOWN&&e.key.scancode==SDL_SCANCODE_ESCAPE){app.rebinding=-1;app.notice.clear();continue;}
            if(app.rebind_ready&&e.type==SDL_EVENT_GAMEPAD_BUTTON_DOWN){
                if(e.gbutton.button==SDL_GAMEPAD_BUTTON_BACK){app.rebinding=-1;app.notice.clear();continue;}
                if(e.gbutton.button==SDL_GAMEPAD_BUTTON_START){app.notice="Menu stays assigned to pause. Choose another button or trigger.";continue;}
                action_binding(app.rebinding)=e.gbutton.button;collection_input::save(controls_path(),app.controls);app.rebinding=-1;app.notice="Binding saved.";continue;}
            if(app.rebind_ready&&e.type==SDL_EVENT_GAMEPAD_AXIS_MOTION&&e.gaxis.axis>=SDL_GAMEPAD_AXIS_LEFT_TRIGGER&&e.gaxis.value>22000){
                action_binding(app.rebinding)=32+e.gaxis.axis;collection_input::save(controls_path(),app.controls);app.rebinding=-1;app.notice="Trigger binding saved.";continue;}
            if(e.type==SDL_EVENT_GAMEPAD_BUTTON_DOWN||e.type==SDL_EVENT_KEY_DOWN)continue;
        }
        if(e.type==SDL_EVENT_QUIT){if(!app.child)app.done=true;}
        if(e.type==SDL_EVENT_WINDOW_FOCUS_LOST||e.type==SDL_EVENT_GAMEPAD_ADDED)app.input_ready=false;
        if(e.type==SDL_EVENT_GAMEPAD_REMOVED&&app.pad&&SDL_GetGamepadID(app.pad)==e.gdevice.which){app.input_ready=false;SDL_CloseGamepad(app.pad);app.pad=nullptr;}
        if(e.type==SDL_EVENT_KEY_DOWN&&!e.key.repeat&&!ImGui::GetIO().WantTextInput){app.controller=false;
            const auto sc=e.key.scancode;
            if(sc==SDL_SCANCODE_LEFT||sc==SDL_SCANCODE_A||sc==SDL_SCANCODE_KP_4)navigate(-1,0);
            if(sc==SDL_SCANCODE_RIGHT||sc==SDL_SCANCODE_D||sc==SDL_SCANCODE_KP_6)navigate(1,0);
            if(sc==SDL_SCANCODE_UP||sc==SDL_SCANCODE_W||sc==SDL_SCANCODE_KP_8)navigate(0,-1);
            if(sc==SDL_SCANCODE_DOWN||sc==SDL_SCANCODE_S||sc==SDL_SCANCODE_KP_2)navigate(0,1);
            if(e.key.scancode==SDL_SCANCODE_RETURN||e.key.scancode==SDL_SCANCODE_SPACE)activate();
            if(e.key.scancode==SDL_SCANCODE_ESCAPE||e.key.scancode==SDL_SCANCODE_BACKSPACE)back();
            if(e.key.scancode==SDL_SCANCODE_F1)go(Page::Settings);if(e.key.scancode==SDL_SCANCODE_F2)go(Page::Credits);
        }
        if(e.type==SDL_EVENT_GAMEPAD_BUTTON_DOWN){app.controller=true;
            switch(e.gbutton.button){case SDL_GAMEPAD_BUTTON_SOUTH:activate();break;case SDL_GAMEPAD_BUTTON_EAST:back();break;
            case SDL_GAMEPAD_BUTTON_DPAD_LEFT:navigate(-1,0);break;case SDL_GAMEPAD_BUTTON_DPAD_RIGHT:navigate(1,0);break;
            case SDL_GAMEPAD_BUTTON_DPAD_UP:navigate(0,-1);break;case SDL_GAMEPAD_BUTTON_DPAD_DOWN:navigate(0,1);break;
            case SDL_GAMEPAD_BUTTON_LEFT_SHOULDER:select_game(-1);break;case SDL_GAMEPAD_BUTTON_RIGHT_SHOULDER:select_game(1);break;
            case SDL_GAMEPAD_BUTTON_START:go(Page::Settings);break;case SDL_GAMEPAD_BUTTON_BACK:go(Page::Credits);break;default:break;}
        }
    }
    open_pad();
    if(!app.input_ready){const bool* keys=SDL_GetKeyboardState(nullptr);bool neutral=true;
        neutral&=SDL_GetMouseState(nullptr,nullptr)==0;
        for(auto sc:{SDL_SCANCODE_RETURN,SDL_SCANCODE_SPACE,SDL_SCANCODE_ESCAPE,SDL_SCANCODE_LEFT,SDL_SCANCODE_RIGHT,SDL_SCANCODE_UP,SDL_SCANCODE_DOWN,
            SDL_SCANCODE_A,SDL_SCANCODE_D,SDL_SCANCODE_W,SDL_SCANCODE_S,SDL_SCANCODE_KP_4,SDL_SCANCODE_KP_6,SDL_SCANCODE_KP_8,SDL_SCANCODE_KP_2})neutral&=!keys[sc];
        if(app.pad){for(int b=0;b<SDL_GAMEPAD_BUTTON_COUNT;++b)neutral&=!SDL_GetGamepadButton(app.pad,(SDL_GamepadButton)b);
            neutral&=std::abs(SDL_GetGamepadAxis(app.pad,SDL_GAMEPAD_AXIS_LEFTX))<16000&&std::abs(SDL_GetGamepadAxis(app.pad,SDL_GAMEPAD_AXIS_LEFTY))<16000;}
        app.input_ready=neutral;}
    if(app.rebinding>=0&&app.pad){bool neutral=true;for(int b=0;b<SDL_GAMEPAD_BUTTON_COUNT;++b)neutral&=!SDL_GetGamepadButton(app.pad,(SDL_GamepadButton)b);
        neutral&=SDL_GetGamepadAxis(app.pad,SDL_GAMEPAD_AXIS_LEFT_TRIGGER)<6000&&SDL_GetGamepadAxis(app.pad,SDL_GAMEPAD_AXIS_RIGHT_TRIGGER)<6000;
        if(neutral)app.rebind_ready=true;}
    if(app.pad&&app.input_ready&&app.rebinding<0&&SDL_GetTicks()>=app.nav_repeat){float x=SDL_GetGamepadAxis(app.pad,SDL_GAMEPAD_AXIS_LEFTX)/32767.f,y=SDL_GetGamepadAxis(app.pad,SDL_GAMEPAD_AXIS_LEFTY)/32767.f;
        if(std::abs(x)>.55f||std::abs(y)>.55f){app.controller=true;navigate(std::abs(x)>std::abs(y)?(x>0?1:-1):0,std::abs(y)>=std::abs(x)?(y>0?1:-1):0);app.nav_repeat=SDL_GetTicks()+220;}}
}

static void island(ImDrawList* d,float x,float y,float width,int game,bool selected,float t){
    const ImU32 top[]={rgba(80,203,165),rgba(250,199,84),rgba(234,127,181)};
    float bob=app.settings.reduced_motion?0:std::sin(t*.8f+game*1.7f)*7;
    y+=bob;float h=width*.17f;
    if(selected){d->AddEllipseFilled(point(x,y+42),point(width*.62f,width*.38f),rgba(133,230,232,35));}
    ImVec2 rock[]={point(x-width*.47f,y),point(x-width*.28f,y+h),point(x-width*.09f,y+h*2.2f),point(x+width*.17f,y+h*1.7f),point(x+width*.48f,y)};
    d->AddConvexPolyFilled(rock,5,rgba(77,95,133));
    ImVec2 facet[]={rock[0],rock[1],rock[2],point(x,y)};d->AddConvexPolyFilled(facet,4,rgba(94,115,157));
    d->AddEllipseFilled(point(x,y-4),point(width*.5f,h*.62f),top[game]);
    d->AddEllipse(point(x,y-4),point(width*.5f,h*.62f),rgba(225,255,220,120),0,0,2);
    if(game==0){for(int i=0;i<3;++i){float bx=x-width*.22f+i*width*.23f,by=y-35-i%2*26;d->AddRectFilled(point(bx-15,by-45),point(bx+15,by+15),rgba(240,225,173),4);d->AddTriangleFilled(point(bx-24,by-44),point(bx+24,by-44),point(bx,by-66),rgba(245,112,118));}}
    else if(game==1){d->AddRectFilled(point(x-40,y-80),point(x+40,y-10),rgba(116,123,189),4);d->AddTriangleFilled(point(x-52,y-77),point(x+52,y-77),point(x,y-114),rgba(240,93,141));for(int i=0;i<3;++i)d->AddRectFilled(point(x-27+i*24,y-60),point(x-17+i*24,y-32),rgba(247,222,142),2);}
    else {d->AddRectFilled(point(x-34,y-90),point(x+34,y-8),rgba(205,232,239),10);d->AddRectFilled(point(x-44,y-62),point(x+44,y-48),rgba(77,134,168),5);d->AddCircleFilled(point(x,y-74),8,rgba(251,216,120));d->AddRectFilled(point(x-13,y-40),point(x+13,y-10),rgba(96,149,177),3);}
    for(int i=0;i<2;++i){float tx=x+(i?1:-1)*width*.34f;d->AddRectFilled(point(tx-3,y-45),point(tx+3,y),rgba(114,110,117));d->AddCircleFilled(point(tx,y-45),width*.07f,rgba(71,145,120));}
}
static void robbit(ImDrawList* d,float x,float y,float scale,float t){
    float bob=app.settings.reduced_motion?0:std::sin(t*.7f)*5;
    y+=bob;auto P=[&](float a,float b){return point(x+a*scale,y+b*scale);};
    d->AddEllipseFilled(P(0,88),point(62*scale,14*scale),rgba(6,40,78,35));
    d->AddRectFilled(P(-40,-100),P(-22,-12),rgba(253,238,182),12*scale);
    d->AddRectFilled(P(22,-112),P(40,-12),rgba(253,238,182),12*scale);
    d->AddRectFilled(P(-35,-88),P(-27,-32),rgba(239,120,119),3*scale);d->AddRectFilled(P(27,-100),P(35,-32),rgba(239,120,119),3*scale);
    d->AddRectFilled(P(-51,-30),P(51,45),rgba(252,239,190),22*scale);d->AddRect(P(-51,-30),P(51,45),rgba(175,132,128),22*scale,0,2*scale);
    d->AddRectFilled(P(-44,-6),P(44,19),rgba(53,93,131),10*scale);
    d->AddCircleFilled(P(-18,6),7*scale,rgba(127,231,231));d->AddCircleFilled(P(18,6),7*scale,rgba(127,231,231));
    d->AddRectFilled(P(-35,45),P(35,68),rgba(233,184,117),8*scale);d->AddEllipseFilled(P(-40,68),point(22*scale,12*scale),rgba(250,235,184));d->AddEllipseFilled(P(40,68),point(22*scale,12*scale),rgba(250,235,184));
    d->AddCircleFilled(P(0,35),5*scale,rgba(242,112,112));
}
static void background(float w,float h,float t){
    auto* d=ImGui::GetBackgroundDrawList();
    d->AddRectFilledMultiColor(point(0,0),point(w,h),rgba(19,57,100),rgba(27,85,133),rgba(123,199,209),rgba(91,172,190));
    float px=app.settings.reduced_motion||!ImGui::IsMousePosValid()?0:std::clamp((ImGui::GetIO().MousePos.x-w/2)*.012f,-8.f,8.f);
    if(app.sky.id){float scale=std::max(w/app.sky.w,h/app.sky.h)*1.035f;
        art_image(d,app.sky,w/2+px,h/2,app.sky.w*scale);
        d->AddRectFilledMultiColor(point(0,0),point(w,h),rgba(5,33,71,30),rgba(5,33,71,30),rgba(5,33,71,0),rgba(5,33,71,0));
        d->AddRectFilled(point(0,h-70),point(w,h),rgba(10,40,72,210));return;}
    for(int i=0;i<9;++i){float x=std::fmod(i*193.f+75.f+px,w+150)-75,y=h*(.16f+.048f*(i%4));d->AddEllipseFilled(point(x,y),point(100+float(i%3)*18,17),rgba(220,240,239,22));}
    for(int i=0;i<5;++i){float x=(i+.1f)*w/4.5f+px,y=h*.69f+std::sin(float(i))*28;island(d,x,y,100+float(i%2)*38,i%3,false,t);}
    d->AddRectFilled(point(0,h-70),point(w,h),rgba(10,40,72,160));
}
static bool button(const char* label,int index,float width=0,float height=46){
    if(app.focus==index){ImGui::PushStyleColor(ImGuiCol_Button,ImVec4(.19f,.27f,.54f,1));ImGui::PushStyleColor(ImGuiCol_Border,ImVec4(1,.88f,.49f,1));}
    bool result=ImGui::Button(label,ImVec2(width,height));
    auto a=ImGui::GetItemRectMin(),b=ImGui::GetItemRectMax();auto* d=ImGui::GetWindowDrawList();
    d->AddRect(point(a.x+4,a.y+4),point(b.x-4,b.y-4),rgba(62,84,155));
    if(app.focus==index){float y=(a.y+b.y)/2;d->AddTriangleFilled(point(a.x-16,y-5),point(a.x-16,y+5),point(a.x-9,y),rgba(255,226,126));ImGui::PopStyleColor(2);}
    return result;
}
static void selected_field(int index){
    if(ImGui::IsItemClicked())app.focus=index;
    if(app.focus!=index)return;
    auto a=ImGui::GetItemRectMin(),b=ImGui::GetItemRectMax();auto* d=ImGui::GetWindowDrawList();
    float y=(a.y+b.y)/2;d->AddTriangleFilled(point(a.x-16,y-5),point(a.x-16,y+5),point(a.x-9,y),rgba(255,226,126));
}
static void chrome(float w,float h){
    auto* d=ImGui::GetForegroundDrawList();
    text(d,app.small,16,44,26,rgba(196,223,221),"ROBBIT'S THREE GREAT ADVENTURES");
    const auto pad_type=app.pad?SDL_GetGamepadType(app.pad):SDL_GAMEPAD_TYPE_UNKNOWN;
    const bool playstation=pad_type==SDL_GAMEPAD_TYPE_PS3||pad_type==SDL_GAMEPAD_TYPE_PS4||pad_type==SDL_GAMEPAD_TYPE_PS5;
    const char* prompts=!app.controller?"ARROWS / WASD  SELECT     ENTER  OPEN     ESC  BACK     F1  SETTINGS":playstation?"CROSS  SELECT     CIRCLE  BACK     L1 / R1  SWITCH     OPTIONS  SETTINGS":"A  SELECT     B  BACK     LB / RB  SWITCH GAME     MENU  SETTINGS";
    text(d,app.small,16,44,h-45,rgba(220,238,231),prompts);
    text(d,app.small,16,w-234,h-44,rgba(190,220,219),"TEST PREVIEW 0.3.0");
    ImGui::SetNextWindowPos(point(w-310,16));ImGui::SetNextWindowSize(point(284,58));
    ImGui::PushStyleVar(ImGuiStyleVar_WindowPadding,point(8,4));ImGui::PushStyleVar(ImGuiStyleVar_FramePadding,point(8,6));ImGui::PushFont(app.small);
    ImGui::Begin("top",nullptr,ImGuiWindowFlags_NoDecoration|ImGuiWindowFlags_NoBackground|ImGuiWindowFlags_NoMove);
    if(ImGui::SmallButton("Settings"))go(Page::Settings);ImGui::SameLine();if(ImGui::SmallButton("Credits"))go(Page::Credits);ImGui::End();ImGui::PopFont();ImGui::PopStyleVar(2);
}
static void home(float w,float h,float t){
    auto* d=ImGui::GetBackgroundDrawList();float sx=std::min(w/1280.f,h/800.f),sy=h/800.f;
    text(d,app.logo,56*sx,48*sx,80*sy,rgba(253,240,189),"JUMPING FLASH!");
    text(d,app.heading,24*sx,50*sx,154*sy,rgba(222,243,231),"COLLECTOR'S EDITION");
    text(d,app.body,20*sx,50*sx,207*sy,rgba(211,233,231),"Three worlds of wonder. One giant leap.");
    if(app.mascot.id)art_image(d,app.mascot,w*.88f,h*.20f+(!app.settings.reduced_motion?std::sin(t*.7f)*4:0),h*.27f*app.mascot.w/app.mascot.h);
    else robbit(d,w-190*sx,180*sy,1.05f*sx,t);
    for(int i=0;i<3;++i){float x=w*(.185f+.315f*i),y=h*.535f;bool selected=i==app.settings.selected;
        const float target=selected?1.f:0.f;
        app.emphasis[i]=app.settings.reduced_motion?target:app.emphasis[i]+(target-app.emphasis[i])*(1-std::exp(-12*ImGui::GetIO().DeltaTime));
        float width=std::min(w*.263f,h*.42f)*(1+app.emphasis[i]*.055f);
        float bob=app.settings.reduced_motion?0:std::sin(t*.7f+i*1.7f)*6;
        d->AddEllipseFilled(point(x,y+105*sy),point(width*.45f,28*sy),rgba(10,62,97,22));
        if(app.islands[i].id)art_image(d,app.islands[i],x,y+bob-app.emphasis[i]*8,width,rgba(255,255,255,selected?255:235));
        else island(d,x,y,260*sx,i,selected,t);
        float label_y=h*.79f,label_w=std::min(w*.28f,360*sx);
        console_menu::panel(d,point(std::round(x-label_w/2),std::round(label_y-16*sy)),point(std::round(x+label_w/2),std::round(label_y+69*sy)),selected);
        if(selected)d->AddTriangleFilled(point(x-label_w/2+12*sx,label_y+7*sy),point(x-label_w/2+12*sx,label_y+19*sy),point(x-label_w/2+20*sx,label_y+13*sy),rgba(255,226,126));
        text(d,app.heading,24*sx,x-label_w/2+28*sx,label_y,selected?rgba(255,245,198):rgba(222,238,234),app.games[i].name);
        text(d,app.small,16*sx,x-label_w/2+28*sx,label_y+35*sy,rgba(208,232,228),app.games[i].subtitle);
        ImGui::SetNextWindowPos(point(x-label_w/2,y-160*sy));ImGui::SetNextWindowSize(point(label_w,label_y+70*sy-(y-160*sy)));
        ImGui::Begin(("game"+std::to_string(i)).c_str(),nullptr,ImGuiWindowFlags_NoDecoration|ImGuiWindowFlags_NoBackground|ImGuiWindowFlags_NoMove|ImGuiWindowFlags_NoSavedSettings);
        if(ImGui::InvisibleButton("select",point(label_w-20*sx,label_y+50*sy-(y-160*sy)))){app.settings.selected=i;write_preferences();go(Page::Game);}ImGui::End();
    }
}
static void content(float w,float h){
    const auto& g=app.games[app.settings.selected];
    ImGui::SetNextWindowPos(point(w*.07f,h*.13f));ImGui::SetNextWindowSize(point(w*.86f,h*.73f));
    ImGui::Begin("content",nullptr,ImGuiWindowFlags_NoDecoration|ImGuiWindowFlags_NoMove|ImGuiWindowFlags_NoSavedSettings);
    auto a=ImGui::GetWindowPos(),size=ImGui::GetWindowSize();auto* frame=ImGui::GetWindowDrawList();
    frame->PushClipRect(a,point(a.x+size.x,a.y+size.y),false);
    console_menu::panel(frame,a,point(a.x+size.x,a.y+size.y));frame->PopClipRect();
    if(app.page==Page::Credits&&app.credits_scroll){ImGui::SetScrollY(ImGui::GetScrollY()+app.credits_scroll);app.credits_scroll=0;}
    ImGui::PushFont(app.heading);ImGui::TextUnformatted(app.page==Page::Credits?"The people behind the adventure":app.page==Page::Settings?"Make yourself at home":g.name.c_str());ImGui::PopFont();ImGui::Spacing();
    if(app.page==Page::Game){
        ImGui::TextColored(ImVec4(.76f,.88f,.86f,1),"%s",g.region.c_str());ImGui::Spacing();ImGui::TextWrapped("%s",g.introduction.c_str());ImGui::Spacing();ImGui::Separator();ImGui::Spacing();
        ImGui::BeginGroup();if(button("Play",0,220))play();if(button("Game settings",1,220))go(Page::Controls);if(button("Gallery",2,220))go(Page::Gallery);if(button("Prepare files",3,220))go(Page::Setup);ImGui::EndGroup();
        ImGui::SameLine(275);const ImVec2 detail_origin=ImGui::GetCursorScreenPos();ImGui::BeginGroup();ImGui::TextUnformatted(readiness(app.root,g).c_str());ImGui::Spacing();
        ImGui::TextUnformatted("ENHANCEMENT QUALIFICATION");ImGui::Text("Modern gamepad: %s",g.gamepad?"Qualified":"Testing in progress");ImGui::TextUnformatted("Experimental widescreen: optional; qualification deferred");ImGui::Text("Smooth 60 FPS: %s",g.smooth?"Qualified":"Testing in progress");
        ImGui::Spacing();ImGui::TextWrapped("Normal memory-card saves preserve your progress. Play opens the original title menu; choose Continue or Load inside the game.");ImGui::EndGroup();
        if(!app.gallery.empty()&&w>=1100){
            const auto& image=app.gallery.front();const float width=192;
            const float height=std::min(144.f,width*image.h/image.w);
            const float fitted_width=height*image.w/image.h;
            const float x=ImGui::GetWindowPos().x+ImGui::GetWindowSize().x-width-28;
            const float y=detail_origin.y+20;
            ImGui::GetWindowDrawList()->AddImage((ImTextureID)(intptr_t)image.id,
                point(x,y),point(x+fitted_width,y+height));
            ImGui::GetWindowDrawList()->AddText(app.small,14,point(x,y+height+8),rgba(208,232,228),"Captured from the game");
        }
    }else if(app.page==Page::Settings){
        ImGui::TextUnformatted("COLLECTION");bool changed=false;
        ImGui::Text("Selected row: %d   Left/right adjusts",app.focus+1);
        changed|=ImGui::SliderInt("Menu volume",&app.settings.volume,0,100);selected_field(0);
        changed|=ImGui::Checkbox("Mute menu music",&app.settings.muted);selected_field(1);
        changed|=ImGui::Checkbox("Reduced motion",&app.settings.reduced_motion);selected_field(2);
        if(ImGui::Checkbox("Fullscreen",&app.settings.fullscreen)){SDL_SetWindowFullscreen(app.window,app.settings.fullscreen);changed=true;}selected_field(3);
        changed|=ImGui::Checkbox("Steam Deck profile",&app.settings.deck);selected_field(4);
        ImGui::Text("Game: %s",g.name.c_str());
        changed|=ImGui::Checkbox("Experimental widescreen",&app.settings.experimental_widescreen.at(g.id));selected_field(5);
        ImGui::TextWrapped("Off: original 4:3 gameplay. On: experimental 16:9 (16:10 with Deck profile), applied next launch. May show missing scenery or visual artifacts.");
        ImGui::Spacing();ImGui::Separator();ImGui::Spacing();ImGui::TextUnformatted("GAME CONTROLS AND GRAPHICS");
        ImGui::TextWrapped("Game settings: controls, sensitivity, inversion and bindings. Each game keeps its own preferences.");
        ImGui::TextWrapped("Desktop: 1080p. Deck: 720-line rendering at 1280x800. Original 4:3 is the release default; smooth 60 FPS awaits qualification.");if(changed)write_preferences();
    }else if(app.page==Page::Controls){
        ImGui::PushStyleVar(ImGuiStyleVar_ItemSpacing,point(14,8));ImGui::PushStyleVar(ImGuiStyleVar_FramePadding,point(18,7));
        bool changed=false;int preset=app.controls.modern?1:0;
        ImGui::Text("Row %d: left/right adjusts; confirm rebinds actions; back returns",app.focus+1);
        if(ImGui::Combo("Control preset",&preset,"Authentic\0Modern\0")){app.controls.modern=preset;changed=true;}selected_field(0);
        changed|=ImGui::SliderInt("Stick deadzone (%)",&app.controls.deadzone,5,40);selected_field(1);
        changed|=ImGui::SliderInt("Aim sensitivity (%)",&app.controls.sensitivity,10,300);selected_field(2);
        bool inverted=app.controls.invert_y;if(ImGui::Checkbox("Invert Y",&inverted)){app.controls.invert_y=inverted;changed=true;}selected_field(3);
        const char* labels[]={"Jump","Primary","Secondary","Special"};
        for(int i=0;i<4;++i){int binding=action_binding(i);const char* name=binding==37?"Right trigger":binding==36?"Left trigger":binding>=32?"Axis":SDL_GetGamepadStringForButton((SDL_GamepadButton)binding);
            std::string label=std::string(labels[i])+": "+(name?name:"Unknown")+"##bind"+std::to_string(i);
            if(button(label.c_str(),i+4,360,36))rebind(i);}
        if(changed)collection_input::save(controls_path(),app.controls);
        ImGui::TextWrapped("Modern: left stick moves/strafes, right stick aims; keyboard and mouse remain active. Menu pauses; View/F8 opens collection return controls.");
        if(g.id=="jf1")ImGui::TextWrapped("JF1: WASD strafe, Space jump, mouse primary/secondary, F special, E secondary. Click to capture; Esc releases; F6 selects mouse mode. Use Start/Menu in original title/world menus. Broader world/boss testing is pending.");
        else if(g.id=="jf2")ImGui::TextWrapped("JF2: WASD move/strafe, Space jump, mouse primary/secondary, F special. Click to capture; Esc releases. Modern aim currently covers the verified PAL first-world overlay; broader testing is pending.");
        else ImGui::TextWrapped("Robbit: WASD move/strafe, Space jump, E special, F secondary. Click to capture; Esc releases; F6 selects mouse mode. Broader mission and physical-controller testing is pending.");
        ImGui::PopStyleVar(2);
    }else if(app.page==Page::Gallery){
        if(app.gallery.empty()){ImGui::TextWrapped("Gameplay screenshots will appear here after they are captured from your imported game. No game art is downloaded.");}
        else{auto& image=app.gallery[app.gallery_index];float width=std::min(w*.70f,(h*.48f)*image.w/image.h);ImGui::Image((ImTextureID)(intptr_t)image.id,point(width,width*image.h/image.w));
            if(ImGui::Button("Previous"))navigate(-1,0);ImGui::SameLine();ImGui::Text("%d / %zu",app.gallery_index+1,app.gallery.size());ImGui::SameLine();if(ImGui::Button("Next"))navigate(1,0);}
    }else if(app.page==Page::Setup){
        ImGui::TextWrapped("Select this game's disc and the matching BIOS. The collection verifies their identities and makes private copies; your original files stay unchanged.");ImGui::Spacing();
        ImGui::BeginDisabled(app.child!=nullptr);if(button("Import disc image",0,260))pick_file(1);if(button("Import BIOS",1,260))pick_file(2);
        if(button("Copy memory card 1",2,260))pick_file(3);if(button("Copy memory card 2",3,260))pick_file(4);ImGui::EndDisabled();
        ImGui::BeginDisabled(app.child!=nullptr);if(button("Copy preferences",4,320))pick_file(5);ImGui::EndDisabled();
        ImGui::Text("Game: %s",g.serial.c_str());ImGui::Text("Status: %s",readiness(app.root,g).c_str());
    }else if(app.page==Page::Files){
        ImGui::Text("Choose %s",app.picker_kind==1?"a disc image":app.picker_kind==2?"a BIOS file or archive":app.picker_kind==5?"existing runtime settings.toml":"a raw PlayStation memory card");
        ImGui::TextWrapped("%s",app.picker_directory.empty()?"Select a drive":app.picker_directory.u8string().c_str());
        int selected=-1;ImGui::BeginChild("files",point(0,h*.43f),ImGuiChildFlags_Borders);
        for(int i=0;i<int(app.files.size());++i){if(ImGui::Selectable(app.files[i].label.c_str(),app.focus==i,0,point(0,30)))selected=i;
            if(app.focus==i&&app.scroll_selection){ImGui::SetScrollHereY(.5f);app.scroll_selection=false;}}
        ImGui::EndChild();if(selected>=0)choose_file(selected);
        ImGui::TextWrapped("D-pad / arrows: select. A / Enter: open. B / Escape: cancel. Left: parent folder.");
    }else if(app.page==Page::Credits){
        ImGui::TextWrapped("Original games: Sony Computer Entertainment, Exact, and the original development teams. Robbit Mon Dieu: Sugar & Rockets.");
        ImGui::Spacing();ImGui::TextWrapped("English fan translation of Robbit Mon Dieu: washingtonxan. Japanese voices remain. Translation integration does not imply authorship of the patch.");
        ImGui::Spacing();ImGui::TextWrapped("Native runtime and recovery: PSXRecomp / RetroPortingToolKit. Native UI: recomp-ui, SDL3, Dear ImGui, stb_image and toml11. See bundled notices for component licenses.");
        ImGui::Spacing();ImGui::TextWrapped("Presentation and integration inspiration: Dusklight, Ship of Harkinian, Zelda64Recomp and OpenGOAL. This is an independent fan collection; those teams do not maintain this project.");
        ImGui::Spacing();ImGui::TextWrapped("Collection illustrations: AI-generated fan artwork created for this project. The title-specific Robbit/cast cards use box-art references; the original scans are not bundled. Exact prompts and provenance: assets/artwork/prompts.json and prompts-v2.json.");
        ImGui::Spacing();ImGui::TextWrapped("This development preview is not a full-game compatibility claim. Complete-release gates include all three campaigns, graphics parity, and real Steam Deck testing.");
    }
    if(!app.notice.empty()){ImGui::Spacing();ImGui::Separator();ImGui::TextWrapped("%s",app.notice.c_str());}
    ImGui::End();
}
static void initialize_window(){
    SDL_GL_SetAttribute(SDL_GL_CONTEXT_MAJOR_VERSION,3);SDL_GL_SetAttribute(SDL_GL_CONTEXT_MINOR_VERSION,3);SDL_GL_SetAttribute(SDL_GL_CONTEXT_PROFILE_MASK,SDL_GL_CONTEXT_PROFILE_CORE);
    app.window=SDL_CreateWindow("Jumping Flash! Collector's Edition",1280,800,SDL_WINDOW_OPENGL|SDL_WINDOW_RESIZABLE);
    if(!app.window)throw std::runtime_error(SDL_GetError());app.context=SDL_GL_CreateContext(app.window);if(!app.context)throw std::runtime_error(SDL_GetError());SDL_GL_SetSwapInterval(1);
    if(app.settings.fullscreen)SDL_SetWindowFullscreen(app.window,true);
    IMGUI_CHECKVERSION();ImGui::CreateContext();auto& io=ImGui::GetIO();io.IniFilename=nullptr;
    std::vector<console_menu::GlyphRect> glyphs;
    app.small=console_menu::font(io.Fonts,16,glyphs);app.body=console_menu::font(io.Fonts,20,glyphs);
    app.heading=console_menu::font(io.Fonts,28,glyphs);app.logo=console_menu::font(io.Fonts,56,glyphs);
    console_menu::rasterize(io.Fonts,glyphs);io.FontDefault=app.body;console_menu::style();
    ImGui_ImplSDL3_InitForOpenGL(app.window,app.context);ImGui_ImplOpenGL3_Init("#version 330");
    ImGui_ImplOpenGL3_CreateFontsTexture();
    glBindTexture(GL_TEXTURE_2D,(GLuint)(intptr_t)io.Fonts->TexID);
    glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_NEAREST);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_NEAREST);
    const auto catalog=toml::parse((app.root/"catalog.toml").string());
    if(catalog.contains("artwork")){
        const auto artwork=toml::find(catalog,"artwork");
        app.sky=load_texture(within(app.root,toml::find<std::string>(artwork,"background")));
        app.mascot=load_texture(within(app.root,toml::find<std::string>(artwork,"mascot")));}
    for(int i=0;i<3;++i)if(!app.games[i].artwork.empty())app.islands[i]=load_texture(within(app.root,app.games[i].artwork));
    SDL_AudioSpec spec{SDL_AUDIO_F32,2,48000};app.audio=SDL_OpenAudioDeviceStream(SDL_AUDIO_DEVICE_DEFAULT_PLAYBACK,&spec,music_callback,&app);if(app.audio)SDL_ResumeAudioStreamDevice(app.audio);
    write_preferences();
}
int main(int argc,char** argv){
    try{
        wchar_t file[32768];GetModuleFileNameW(nullptr,file,32768);app.root=fs::path(file).parent_path();
        for(int i=1;i<argc;++i){if(std::string(argv[i])=="--root"&&i+1<argc)app.root=fs::absolute(fs::u8path(argv[++i]));}
        app.games=load_catalog(app.root);app.settings=load_settings(app.root/"data/collection.toml");
        for(int i=1;i<argc;++i){if(std::string(argv[i])=="--windowed")app.settings.fullscreen=false;if(std::string(argv[i])=="--deck"){app.settings.deck=true;app.settings.fullscreen=true;}}
        if(!SDL_Init(SDL_INIT_VIDEO|SDL_INIT_AUDIO|SDL_INIT_GAMEPAD))throw std::runtime_error(SDL_GetError());initialize_window();
        while(!app.done){poll_child();if(app.child&&!app.importing){SDL_Delay(50);continue;}events();
            ImGui_ImplOpenGL3_NewFrame();ImGui_ImplSDL3_NewFrame();ImGui::NewFrame();float w=ImGui::GetIO().DisplaySize.x,h=ImGui::GetIO().DisplaySize.y,t=float(SDL_GetTicks()/1000.);
            background(w,h,t);if(app.page==Page::Home)home(w,h,t);else content(w,h);chrome(w,h);ImGui::Render();int fw,fh;SDL_GetWindowSizeInPixels(app.window,&fw,&fh);glViewport(0,0,fw,fh);glClearColor(.1f,.25f,.3f,1);glClear(GL_COLOR_BUFFER_BIT);ImGui_ImplOpenGL3_RenderDrawData(ImGui::GetDrawData());SDL_GL_SwapWindow(app.window);
        }
        release_window();SDL_Quit();return 0;
    }catch(const std::exception& error){MessageBoxA(nullptr,error.what(),"Jumping Flash! Collection",MB_OK|MB_ICONERROR);return 1;}
}
int WINAPI WinMain(HINSTANCE,HINSTANCE,LPSTR,int){return main(__argc,__argv);}
