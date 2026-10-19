#include "model.h"
#include <toml.hpp>
#include <algorithm>
#include <fstream>
#include <stdexcept>
#include <set>
namespace collection {
fs::path within(const fs::path& root,const fs::path& relative) {
    if(relative.empty() || relative.is_absolute() || relative.has_root_name()) throw std::runtime_error("Catalog path must be relative");
    const auto result=(root/relative).lexically_normal();
    for(const auto& part:relative) if(part=="..") throw std::runtime_error("Catalog path escapes the collection");
    return result;
}
std::vector<Game> load_catalog(const fs::path& root) {
    const auto document=toml::parse((root/"catalog.toml").string());
    if(toml::find<int>(document,"schema")!=1) throw std::runtime_error("Unsupported collection catalog");
    std::vector<Game> games;
    std::set<std::string> ids;
    for(const auto& item:toml::find<toml::array>(document,"games")) {
        Game g;
        g.id=toml::find<std::string>(item,"id");
        if(g.id!="jf1" && g.id!="jf2" && g.id!="robbit") throw std::runtime_error("Unknown game ID");
        if(!ids.insert(g.id).second) throw std::runtime_error("Duplicate game ID");
        g.name=toml::find<std::string>(item,"name");g.subtitle=toml::find<std::string>(item,"subtitle");
        g.serial=toml::find<std::string>(item,"serial");g.region=toml::find<std::string>(item,"region");
        g.introduction=toml::find<std::string>(item,"introduction");
        g.disc_hash=toml::find<std::string>(item,"disc_sha256");g.bios_hash=toml::find<std::string>(item,"bios_sha256");
        g.executable=toml::find<std::string>(item,"executable");g.config=toml::find<std::string>(item,"config");
        g.bios=toml::find<std::string>(item,"bios");g.disc=toml::find<std::string>(item,"disc");
        g.artwork=toml::find_or<std::string>(item,"artwork","");if(!g.artwork.empty())within(root,g.artwork);
        within(root,g.executable);within(root,g.config);within(root,g.bios);within(root,g.disc);
        g.wide=toml::find<bool>(item,"widescreen_qualified");g.smooth=toml::find<bool>(item,"smooth_60_qualified");g.gamepad=toml::find<bool>(item,"modern_gamepad_qualified");
        games.push_back(g);
    }
    if(games.size()!=3) throw std::runtime_error("The collection catalog must contain three games");
    return games;
}
Settings load_settings(const fs::path& path) {
    Settings s;
    if(!fs::is_regular_file(path)) return s;
    auto v=toml::parse(path.string());
    s.selected=std::clamp(toml::find_or<int>(v,"selected",0),0,2);
    s.volume=std::clamp(toml::find_or<int>(v,"volume",25),0,100);
    s.muted=toml::find_or<bool>(v,"muted",false);s.reduced_motion=toml::find_or<bool>(v,"reduced_motion",false);
    s.fullscreen=toml::find_or<bool>(v,"fullscreen",true);s.deck=toml::find_or<bool>(v,"deck",false);
    for(auto& entry:s.experimental_widescreen)
        entry.second=toml::find_or<bool>(v,"experimental_widescreen_"+entry.first,false);
    return s;
}
void save_settings(const fs::path& path,const Settings& s) {
    fs::create_directories(path.parent_path());
    const auto temporary=fs::path(path.string()+".tmp");
    {std::ofstream out(temporary);if(!out) throw std::runtime_error("Cannot write collection settings");
    out<<"schema = 1\nselected = "<<s.selected<<"\nvolume = "<<s.volume<<"\nmuted = "<<(s.muted?"true":"false")
        <<"\nreduced_motion = "<<(s.reduced_motion?"true":"false")<<"\nfullscreen = "<<(s.fullscreen?"true":"false")<<"\ndeck = "<<(s.deck?"true":"false")<<"\n";
    for(const auto& entry:s.experimental_widescreen)
        out<<"experimental_widescreen_"<<entry.first<<" = "<<(entry.second?"true":"false")<<"\n";
    out.flush();if(!out) throw std::runtime_error("Collection settings write failed");}
    // Keep the previous file recoverable if replacement is interrupted.
    if(fs::exists(path)) fs::copy_file(path,path.string()+".bak",fs::copy_options::overwrite_existing);
    fs::copy_file(temporary,path,fs::copy_options::overwrite_existing);fs::remove(temporary);
}
void prepare_game_display(const fs::path& user,bool experimental_widescreen,bool deck) {
    const auto path=user/"settings.toml";
    auto values=fs::is_regular_file(path)?toml::parse(path.string()):toml::value(toml::table{});
    values["video"]["aspect_ratio"]=experimental_widescreen?(deck?"16:10":"16:9"):"4:3";
    fs::create_directories(user);
    const auto temporary=fs::path(path.string()+".tmp");
    {std::ofstream out(temporary);if(!out)throw std::runtime_error("Cannot write game display preference");
        out<<values;out.flush();if(!out)throw std::runtime_error("Game display preference write failed");}
    if(fs::exists(path))fs::copy_file(path,path.string()+".bak",fs::copy_options::overwrite_existing);
    fs::copy_file(temporary,path,fs::copy_options::overwrite_existing);fs::remove(temporary);
}
std::string readiness(const fs::path& root,const Game& g) {
    if(!fs::is_regular_file(within(root,g.executable))) return "Native build not installed";
    if(!fs::is_regular_file(within(root,g.config))) return "Runtime configuration missing";
    if(!fs::is_regular_file(within(root,g.disc))) return "Import your game disc";
    if(!fs::is_regular_file(within(root,g.bios))) return "Import the matching BIOS";
    if(!fs::is_regular_file(root/"data/games"/g.id/"import-receipt.json")) return "Verify game files before playing";
    return "Ready to play";
}
bool process_exit_succeeded(bool exit_code_available,unsigned long exit_code) noexcept {
    return exit_code_available && exit_code==0;
}
std::wstring quote_arg(const std::wstring& a) {
    // Microsoft CRT argument escaping; never concatenate into a shell command.
    std::wstring out=L"\"";size_t slashes=0;
    for(wchar_t c:a) {
        if(c==L'\\') {++slashes;continue;}
        if(c==L'\"') {out.append(slashes*2+1,L'\\');out+=c;slashes=0;continue;}
        out.append(slashes,L'\\');slashes=0;out+=c;
    }
    out.append(slashes*2,L'\\');out+=L'\"';return out;
}
}
