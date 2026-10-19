#define FRAME_PACING_PURE_ONLY
#include "frame_pacing.c"
#include <assert.h>
int main(void) {
    assert(frame_pacing_sleep_ms(120,100,1000,20)==0);
    assert(frame_pacing_late_deadline(240,100,20)==260); // No seven-frame burst after a hitch.
    assert(frame_pacing_late_deadline(101,100,20)==120); // Recover tiny scheduling jitter.
    assert(frame_pacing_late_deadline(105,100,20)==124); // Recovery capped to 1 ms per PAL frame.
    assert(frame_pacing_late_deadline(120,100,20)==140); // A full-frame stall is discarded.
    for (uint64_t now=100; now<120; ++now) {
        uint64_t next=frame_pacing_late_deadline(now,100,20);
        assert(next>=now+19 && next<=now+20); // No burst of unpaced frames.
    }
    assert(frame_pacing_sleep_ms(100,120,1000,20)==19); // Normal PAL period retained.
    FramePacer pacer={100,0};
    frame_pacing_advance(&pacer,90,20);
    assert(pacer.next_deadline==100 && !pacer.recovery_debt);
    frame_pacing_advance(&pacer,105,20);
    assert(pacer.next_deadline==124 && pacer.recovery_debt==4);
    for(int i=0;i<4;++i) {
        uint64_t now=pacer.next_deadline;
        frame_pacing_advance(&pacer,now,20);
        assert(pacer.next_deadline>=now+19 && pacer.next_deadline<=now+20);
    }
    assert(pacer.next_deadline==200 && !pacer.recovery_debt);
    pacer=(FramePacer){100,17};
    frame_pacing_advance(&pacer,120,20);
    assert(pacer.next_deadline==140 && !pacer.recovery_debt);
    pacer=(FramePacer){100,0};
    for(int i=0;i<1000;++i) {
        uint64_t now=pacer.next_deadline+(i%40==0?5:0);
        frame_pacing_advance(&pacer,now,20);
        assert(pacer.next_deadline>=now+19 && pacer.next_deadline<=now+20);
    }
    assert(pacer.next_deadline==20100 && !pacer.recovery_debt);
}
