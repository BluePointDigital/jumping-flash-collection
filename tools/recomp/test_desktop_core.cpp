#include "jf2_desktop_core.h"
#include <cassert>
int main() {
    jf2::TitleInputGate gate;
    assert(!gate.update(0x800)); // Intro skip held at entry.
    assert(!gate.update(0x800));
    assert(!gate.update(0));
    assert(gate.update(0x800)); // A fresh title selection is accepted.
    assert(jf2::strafe_arrows(0xff7f,true)==0xfbff);
    assert(jf2::strafe_arrows(0xffdf,true)==0xf7ff);
    assert(jf2::strafe_arrows(0xff7f,false)==0xff7f);
    auto forward=jf2::movement(0xffef,4090);
    assert(forward.angle==4090 && forward.active);
    assert(jf2::movement(0xf7ff,0).angle==1024);
    assert(jf2::movement(0xfbff,0).angle==3072);
    assert(jf2::movement(0xf7ef,0).angle==512);
    assert(!jf2::movement(0xffaf,0).active); // Opposite keys cancel.
    assert(!jf2::movement(0xf3ff,0).active);
    assert(!jf2::movement(0xffff,0).active); // Shift alone never moves.
    assert(jf2::movement(0xf7ff,INT32_MAX).angle==1023);
    assert(!jf2::lateral_command(0xffef)); // Native forward jumps bypass the adapter.
    assert(!jf2::lateral_command(0xbfaf)); // Native backward/jump also bypass it.
    assert(jf2::lateral_command(0xf7ef));
    assert(jf2::movement_pad(0x500c,true)==0x1000); // No native L1 run modifier.
    assert(jf2::movement_pad(0x504c,false)==0x40); // Jump is retained, movement released.
    assert(jf2::ground_boost(18,false,false,175)==18);
    assert(jf2::grounded(1,0,0));
    assert(!jf2::grounded(0,0,0));
    assert(!jf2::grounded(1,1,-104448)); // Initial jump with stale floor contact.
    assert(!jf2::grounded(1,0,2048));
    assert(jf2::ground_boost(18,true,true,175)==18); // Air control never boosted.
    assert(jf2::ground_boost(18,true,false,175)==31);
    assert(jf2::host_pad(0x1000)==0xffef);
    assert(jf2::host_pad(0x0004)==0xfbff);
    assert(jf2::title_hit(300,425)==5);
    assert(jf2::title_hit(300,437)==5);
    assert(jf2::title_hit(300,438)==-1);
    assert(jf2::title_hit(95,300)==-1);
    jf2::MouseLook m;
    m.move(20, 10);
    assert(m.update(4090, 0, 1, 100, false) == 34);
    assert(m.pitch == 20 && m.dx == 0 && m.dy == 0);
    m.move(5, 5);
    assert(m.update(34, 700, 1, 100, false) == 34);
    assert(m.dx == 5 && m.pitch == 20); // A repeated hook does not consume another delta.
    assert(m.update(34, 700, 2, 100, true) == 44 && m.pitch == 10);
    m.move(-10000, 10000);
    assert(m.update(0, 0, 3, 300, false) >= 0 && m.pitch == 760);
    m.clear();
    assert(!m.initialized && m.dx == 0);
    assert(m.update(100, -880, 4, 100, false) == 100 && m.pitch == -880);
    int x = 0, y = 0, w = 1920, h = 1080;
    jf2::integer_rect(1920, 1080, 320, 240, x, y, w, h);
    assert(w == 1280 && h == 960 && x == 320 && y == 60);
    jf2::integer_rect(120, 90, 320, 240, x, y, w, h);
    assert(w == 1280); // Caller retains its existing fit below native size.
}
