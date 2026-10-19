#ifdef NDEBUG
#undef NDEBUG
#endif
#include "jf1_controls_core.h"
#include "jf1_profiles.h"
#include <cassert>
int main(){
    assert(jf1::heading(1,0)==1024&&jf1::heading(-1,0)==-1024);
    assert(jf1::heading(1,1)==512&&jf1::magnitude(1,1)==1);
    assert(std::abs(jf1::magnitude(.3f,.4f)-.5f)<.001f);
    assert(jf1::manual(0,1,0,0,0,0,1,0));
    assert(!jf1::manual(1,1,0,0,0,0,1,0)); // Attract/demo playback.
    assert(!jf1::manual(0,1,1,0,0,0,1,0)); // Native pause.
    assert(!jf1::manual(0,1,0,1,0,0,1,0)); // Loading/cut/transition.
    assert(!jf1::manual(0,1,0,0,1,0,1,0)); // Stage completion.
    jf1::Look look;look.move(50,9000);assert(look.update(2040,0,100,false)==-2006&&look.pitch==768);
    look.move(0,-9000);look.update(0,0,100,false);assert(look.pitch==-896);
    look.clear();look.move(0,20);look.update(0,10,100,true);assert(look.pitch==-10);
    look.clear();look.update(0,96,100,false);assert(look.pitch==96); // New scene reinitializes.
    assert(sizeof(jf1_profiles)/sizeof(jf1_profiles[0])==12);
    for(const auto& p:jf1_profiles){assert(p.command==p.movement+0x108&&p.camera==p.update+0x464);
        for(uint32_t site:{p.update,p.movement,p.command,p.camera}){
            assert(jf1_control_site(site)&&jf1_control_site(site&0x1fffffff)&&jf1_control_site(site|0xa0000000));
            assert(!jf1_control_site(site+1));
        }
        for(const auto& g:p.guards)assert(g.address>=0x800b0000&&g.address<0x80200000&&g.words&&g.hash);}
    assert(!jf1_control_site(0)&&!jf1_control_site(0xbfc00000));
}
