#include "robbit_input_core.h"
#include <cassert>
#include <cstdio>
#undef assert
#define assert(condition) do { if (!(condition)) { std::fprintf(stderr,"Input check failed at line %d: %s\n",__LINE__,#condition); return 1; } } while (0)
int main() {
    RobbitKeyPulses<8> pulses;
    uint8_t physical[8] = {};
    pulses.press(3,100);
    assert(pulses.sample(physical,100)[3]);
    assert(pulses.sample(physical,179)[3]);
    assert(!pulses.sample(physical,180)[3]);
    pulses.press(-1,100); pulses.press(8,100);
    physical[5]=1; assert(pulses.sample(physical,200)[5]);
    physical[5]=0; assert(!pulses.sample(physical,200)[5]);
    pulses.press(3,200); pulses.clear(); assert(!pulses.sample(physical,201)[3]);
    physical[3]=1; pulses.block_held(physical);
    assert(!pulses.sample(physical,202)[3]);
    physical[3]=0; assert(!pulses.sample(physical,203)[3]);
    physical[3]=1; assert(pulses.sample(physical,204)[3]);
    physical[3]=0;
    RobbitMouseLook look;
    look.move(10,-20);
    assert(look.update(4090,0,100,false)==9);
    assert(look.pitch==30);
    assert(look.update(9,50,100,false)==9 && look.pitch==30); // No repeated motion or jump recenter.
    look.move(-10,20); assert(look.update(9,0,100,true)==4090 && look.pitch==60);
    look.move(0,10000); look.update(0,0,100,false); assert(look.pitch==-896);
    look.move(0,-10000); look.update(0,0,100,false); assert(look.pitch==896);
    look.clear(); assert(!look.initialized && look.dx==0 && look.dy==0);
    look.move(NAN,INFINITY); assert(look.dx==0 && look.dy==0);
    look.update(0,-3000,100,false); assert(look.pitch==-896);
    assert(robbit_live_flags(0x100000,1,0));
    assert(!robbit_live_flags(0x100008,1,0)); // Pause.
    assert(!robbit_live_flags(0x100010,1,0)); // Native input lock.
    assert(!robbit_live_flags(0x200000,1,0)); // Non-game camera.
    assert(!robbit_live_flags(0x100000,0,0)); // Debug camera.
    assert(!robbit_live_flags(0x100000,1,1)); // Scripted player lock.
    assert(robbit_move_angle(0,1)==0);
    assert(robbit_move_angle(1,1)==512);
    assert(robbit_move_angle(1,0)==1024);
    assert(robbit_move_angle(1,-1)==1536);
    assert(robbit_move_angle(0,-1)==2048);
    assert(robbit_move_angle(-1,-1)==2560);
    assert(robbit_move_angle(-1,0)==3072);
    assert(robbit_move_angle(-1,1)==3584);
    assert(robbit_move_angle(0,0)==0);
}
