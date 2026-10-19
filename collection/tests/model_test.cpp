#include "model.h"
#include "host_input.h"
#include <iostream>
#include <stdexcept>
#include <fstream>
#include <toml.hpp>
#define CHECK(x) do {if(!(x)){std::cerr<<"FAIL "<<#x<<"\n";return 1;}}while(0)
int main(int argc,char** argv) {
    using namespace collection;
    if(argc!=2) return 2;
    auto root=fs::absolute(argv[1]).parent_path();
    const auto games=load_catalog(root);
    CHECK(games.size()==3);CHECK(games[0].id=="jf1");CHECK(games[1].id=="jf2");CHECK(games[2].id=="robbit");
    for(const auto& game:games) CHECK(!game.wide && !game.smooth && !game.gamepad);
    for(const auto& game:games) CHECK(fs::is_regular_file(within(root,game.artwork)));
    bool rejected=false;try{within(root,"../../other/card.mcd");}catch(const std::exception&){rejected=true;}CHECK(rejected);
    rejected=false;try{within(root,"C:/other/card.mcd");}catch(const std::exception&){rejected=true;}CHECK(rejected);
    CHECK(quote_arg(L"C:\\My Games\\")==L"\"C:\\My Games\\\\\"");
    CHECK(quote_arg(L"a\"b")==L"\"a\\\"b\"");
    CHECK(!process_exit_succeeded(false,0));CHECK(process_exit_succeeded(true,0));CHECK(!process_exit_succeeded(true,1));
    CHECK(readiness(root,games[0])!="Ready to play");
    auto temp=fs::temp_directory_path()/"jumping-flash-collection-model-test";
    Settings s;s.selected=2;s.volume=42;s.reduced_motion=true;s.deck=true;
    for(const auto& entry:s.experimental_widescreen)CHECK(!entry.second);
    s.experimental_widescreen.at("jf2")=true;
    save_settings(temp/"settings.toml",s);auto roundtrip=load_settings(temp/"settings.toml");
    CHECK(roundtrip.selected==2 && roundtrip.volume==42 && roundtrip.reduced_motion && roundtrip.deck);
    CHECK(!roundtrip.experimental_widescreen.at("jf1")&&roundtrip.experimental_widescreen.at("jf2")&&!roundtrip.experimental_widescreen.at("robbit"));
    {std::ofstream legacy(temp/"legacy.toml");legacy<<"selected = 1\n";}
    for(const auto& entry:load_settings(temp/"legacy.toml").experimental_widescreen)CHECK(!entry.second);
    for(const auto& game:games){
        const auto user=temp/game.id;
        CHECK(!fs::exists(user));
        prepare_game_display(user,false,true);
        CHECK(toml::find<std::string>(toml::parse((user/"settings.toml").string()),"video","aspect_ratio")=="4:3");
        CHECK(!fs::exists(user/"settings.toml.bak"));
        {std::ofstream preferences(user/"settings.toml");preferences<<"[video]\naspect_ratio = \"16:9\"\npresent_thread = true\n[desktop]\nmouse_sensitivity = 137\n";}
        prepare_game_display(user,false,true);
        auto display=toml::parse((user/"settings.toml").string());
        CHECK(toml::find<std::string>(display,"video","aspect_ratio")=="4:3");
        CHECK(toml::find<bool>(display,"video","present_thread"));
        CHECK(toml::find<int>(display,"desktop","mouse_sensitivity")==137);
        CHECK(toml::find<std::string>(toml::parse((user/"settings.toml.bak").string()),"video","aspect_ratio")=="16:9");
        prepare_game_display(user,true,true);
        CHECK(toml::find<std::string>(toml::parse((user/"settings.toml").string()),"video","aspect_ratio")=="16:10");
        prepare_game_display(user,true,false);
        CHECK(toml::find<std::string>(toml::parse((user/"settings.toml").string()),"video","aspect_ratio")=="16:9");
        prepare_game_display(user,false,false);
        CHECK(toml::find<std::string>(toml::parse((user/"settings.toml").string()),"video","aspect_ratio")=="4:3");
        fs::remove(user/"settings.toml");fs::remove(user/"settings.toml.bak");fs::remove(user);
    }
    fs::remove(temp/"legacy.toml");
    collection_input::Config controls;controls.deadzone=24;controls.fire=2;controls.invert_y=1;
    collection_input::save(temp/"host-input.toml",controls);auto loaded=collection_input::load(temp/"host-input.toml");
    CHECK(loaded.deadzone==24&&loaded.fire==2&&loaded.invert_y==1);
    CHECK(collection_input::axis(5000,18)==0);CHECK(collection_input::axis(-32768,18)==-1);
    collection_input::Sample held;held.buttons[0]=true;held.axes[2]=.8f;collection_input::ReleaseGate gate;gate.arm(held);
    for(int i=0;i<1000;++i){auto blocked=gate.clean(held);CHECK(!blocked.buttons[0]&&blocked.axes[2]==0);}
    gate.clean({});auto fresh=gate.clean(held);CHECK(fresh.buttons[0]&&fresh.axes[2]==.8f);
    fs::remove(temp/"host-input.toml");fs::remove(temp/"host-input.toml.bak");
    fs::remove(temp/"settings.toml");fs::remove(temp/"settings.toml.bak");fs::remove(temp/"settings.toml.tmp");fs::remove(temp);
    std::cout<<"PASS: three-game catalog, path isolation, process quoting and preference persistence\n";
}
