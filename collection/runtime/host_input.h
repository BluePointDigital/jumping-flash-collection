#pragma once
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <string>
#include <stdexcept>

namespace collection_input {
struct Config {
    int modern=1,deadzone=18,sensitivity=100,invert_y=0;
    // SDL gamepad buttons 0..20; axes use 32 + SDL axis index.
    int jump=0,fire=37,secondary=36,special=3;
};
inline Config load(const std::filesystem::path& path){
    Config c;std::ifstream file(path);std::string key,equals;int value;
    while(file>>key>>equals>>value){if(equals!="=")continue;
        if(key=="modern")c.modern=value!=0;if(key=="deadzone")c.deadzone=std::clamp(value,5,40);
        if(key=="sensitivity")c.sensitivity=std::clamp(value,10,300);if(key=="invert_y")c.invert_y=value!=0;
        if(value>=0&&(value<=20||(value>=32&&value<=37))){
            if(key=="jump")c.jump=value;if(key=="fire")c.fire=value;
            if(key=="secondary")c.secondary=value;if(key=="special")c.special=value;}}
    return c;
}
inline void save(const std::filesystem::path& path,const Config& c){
    std::filesystem::create_directories(path.parent_path());
    auto temp=std::filesystem::path(path.string()+".tmp");
    {std::ofstream file(temp);file<<"modern = "<<c.modern<<"\ndeadzone = "<<c.deadzone<<"\nsensitivity = "<<c.sensitivity
        <<"\ninvert_y = "<<c.invert_y<<"\njump = "<<c.jump<<"\nfire = "<<c.fire<<"\nsecondary = "<<c.secondary<<"\nspecial = "<<c.special<<"\n";
        file.flush();if(!file)throw std::runtime_error("Unable to save controls");}
    if(std::filesystem::exists(path))std::filesystem::copy_file(path,path.string()+".bak",std::filesystem::copy_options::overwrite_existing);
    std::filesystem::copy_file(temp,path,std::filesystem::copy_options::overwrite_existing);std::filesystem::remove(temp);
}
inline float axis(int raw,int deadzone){float value=std::clamp(raw/32767.f,-1.f,1.f),threshold=deadzone/100.f;
    return std::abs(value)<=threshold?0.f:std::copysign((std::abs(value)-threshold)/(1-threshold),value);}
struct Sample {std::array<bool,21> buttons{};std::array<float,6> axes{};};
inline bool held(const Sample& s,int binding){return binding>=32&&binding<=37?s.axes[binding-32]>.55f:binding>=0&&binding<21&&s.buttons[binding];}
struct ReleaseGate {
    Sample blocked{};
    void arm(const Sample& s){blocked=s;}
    Sample clean(Sample s){for(size_t i=0;i<s.buttons.size();++i){if(!s.buttons[i])blocked.buttons[i]=false;if(blocked.buttons[i])s.buttons[i]=false;}
        for(size_t i=0;i<s.axes.size();++i){if(std::abs(s.axes[i])<.05f)blocked.axes[i]=0;if(blocked.axes[i]!=0)s.axes[i]=0;}return s;}
};
}
