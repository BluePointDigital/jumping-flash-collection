#include "config_loader.h"
#include <cassert>
#include <filesystem>
#include <fstream>
int main(int argc,char** argv) {
    assert(argc==2);
    const auto dir=std::filesystem::path(argv[1]);
    std::filesystem::create_directories(dir);
    const auto file=dir/"settings-test.toml";
    PSXRecompV4::UserSettings s;
    s.jf2_has_settings=true;s.jf2_control_style=0;s.jf2_mouse_sensitivity=213;
    s.jf2_invert_y=true;s.jf2_integer_scaling=true;s.jf2_audio_volume=47;s.jf2_muted=true;
    s.jf2_boost=false;s.jf2_boost_percent=190;s.jf2_boost_classic_key=224;s.jf2_boost_modern_key=226;
    s.jf2_arrow_strafe=false;s.jf2_messages=false;s.jf2_native_menu=false;s.jf2_post_aa=2;
    s.has_window_width=true;s.window_width=1280;
    assert(PSXRecompV4::save_user_settings(file,s));
    auto got=PSXRecompV4::load_user_settings(file);
    assert(!got.parse_error && got.jf2_control_style==0 && got.jf2_mouse_sensitivity==213);
    assert(got.jf2_invert_y && got.jf2_integer_scaling && got.jf2_muted && got.jf2_audio_volume==47);
    // The shared launcher reconstructs settings; it must preserve title preferences.
    PSXRecompV4::UserSettings launcher;
    launcher.has_window_width=true;launcher.window_width=960;
    assert(PSXRecompV4::save_user_settings(file,launcher));
    got=PSXRecompV4::load_user_settings(file);
    assert(got.window_width==960 && got.jf2_control_style==0 && got.jf2_mouse_sensitivity==213);
    assert(got.jf2_integer_scaling && got.jf2_muted && got.jf2_audio_volume==47);
    assert(!got.jf2_boost && got.jf2_boost_percent==190 && got.jf2_boost_classic_key==224 && got.jf2_boost_modern_key==226);
    assert(!got.jf2_arrow_strafe && !got.jf2_messages && !got.jf2_native_menu && got.jf2_post_aa==2);
    // Native is encoded as 1; 0 means unset and silently drops the override.
    launcher.has_internal_resolution=true;launcher.internal_resolution=1;
    assert(PSXRecompV4::save_user_settings(file,launcher));
    got=PSXRecompV4::load_user_settings(file);
    assert(got.has_internal_resolution && got.internal_resolution==1);
    std::ofstream(file) << "[desktop]\nmouse_sensitivity = 999999\naudio_volume = -20\n";
    got=PSXRecompV4::load_user_settings(file);
    assert(got.jf2_mouse_sensitivity==300 && got.jf2_audio_volume==0);
    std::ofstream(file) << "[desktop]\nboost_percent = 999999999999\nboost_modern_key = -20\npost_aa = 100\n";
    got=PSXRecompV4::load_user_settings(file);
    assert(got.jf2_boost_percent==200 && got.jf2_boost_modern_key==0 && got.jf2_post_aa==2);
    std::ofstream(file) << "this is invalid TOML = [";
    assert(PSXRecompV4::load_user_settings(file).parse_error);
    std::filesystem::remove(file);
}
