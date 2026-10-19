#pragma once
#include <filesystem>
#include <map>
#include <string>
#include <vector>
namespace collection {
namespace fs=std::filesystem;
struct Game {
    std::string id,name,subtitle,serial,region,introduction,disc_hash,bios_hash;
    fs::path executable,config,bios,disc,artwork;
    bool wide=false,smooth=false,gamepad=false;
};
struct Settings {
    int selected=0,volume=25;
    bool muted=false,reduced_motion=false,fullscreen=true,deck=false;
    std::map<std::string,bool> experimental_widescreen{{"jf1",false},{"jf2",false},{"robbit",false}};
};
std::vector<Game> load_catalog(const fs::path& root);
fs::path within(const fs::path& root,const fs::path& relative);
Settings load_settings(const fs::path& path);
void save_settings(const fs::path& path,const Settings& settings);
void prepare_game_display(const fs::path& user,bool experimental_widescreen,bool deck);
std::string readiness(const fs::path& root,const Game& game);
std::wstring quote_arg(const std::wstring& argument);
bool process_exit_succeeded(bool exit_code_available,unsigned long exit_code) noexcept;
}
