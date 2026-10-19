"""Compile the real bridge and title-specific transition refill."""
from pathlib import Path
import subprocess
import sys
import tempfile

source = Path(sys.argv[1]).read_text(encoding="utf-8")
start = source.index("static void jf2_audio_refill(")
refill = source[start:source.index("\n}", start) + 2]
program = '''#include <assert.h>
#define RECOMP_AUDIO_DRC_IMPL
#include "recomp_audio_drc.h"
REFILL
int main(void) {
 rab_config cfg; rab_config_defaults(&cfg); rab_bridge b;
 assert(!rab_init(&b,&cfg));
 float *ring=b.ring,*coeffs=b.coeffs;
 b.primed=1;b.gain=1;b.last_out[0]=b.last_out[1]=-0.9f;
 b.in_count=9000;b.out_pos=8990;b.corr=b.corr_i=b.err_lp=.005;
 b.stats.underrun_events=123;
 jf2_audio_refill(&b);
 assert(b.ring==ring && b.coeffs==coeffs && b.cfg.target_ms==cfg.target_ms);
 assert(!b.primed && !b.in_count && b.out_pos==b.half-1 && !b.corr_i);
 assert(b.stats.underrun_events==123);
 int16_t out[2048],pcm[1764];
 rab_pull(&b,out,1024);
 for(int i=0;i<2048;++i) assert(!out[i]);
 assert(b.stats.underrun_events==123);
 for(int i=0;i<1764;++i) pcm[i]=2000;
 for(int i=0;i<10;++i) rab_push(&b,pcm,882);
 rab_pull(&b,out,1024);
 assert(b.primed && out[2046]>1800 && b.stats.underrun_events==123);
 rab_free(&b);
}
'''.replace("REFILL", refill)
with tempfile.TemporaryDirectory(prefix="jf2-audio-test-") as directory:
    fixture = Path(directory) / "refill.c"
    exe = Path(directory) / "refill.exe"
    fixture.write_text(program, encoding="utf-8")
    subprocess.run([sys.argv[2], "-std=c11", str(fixture),
                    "-I" + str(Path(sys.argv[1]).parent), "-o", str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
print("PASS: refill discards stale PCM, retains configuration and counters, primes fresh audio")
