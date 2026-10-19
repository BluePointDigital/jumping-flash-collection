"""Exercise the actual bounded timing reader without a GL context."""
from pathlib import Path
import subprocess
import sys
import tempfile

source = Path(sys.argv[1]).read_text(encoding="utf-8")
start = source.index("int gl_renderer_perf_samples(")
end = source.index("int gl_renderer_perf_aggregate(", start)
program = '''#include <stdint.h>
#include <assert.h>
#define GL_RT_SYNC(x) ((void)0)
#define GLPERF_RING 256
typedef struct { uint64_t frame; double total_ms, present_wall_ms; } GlPerfSample;
static int s_pf_on;
static uint64_t s_pf_ring_seq;
static GlPerfSample s_pf_ring[GLPERF_RING];
FUNCTION
int main(void) {
 uint64_t seq[256], frames[256]; double ms[256], present[256];
 assert(!gl_renderer_perf_samples(0,seq,frames,ms,present,256));
 s_pf_on=1;
 assert(!gl_renderer_perf_samples(0,seq,frames,ms,present,256));
 for(uint64_t i=0;i<300;++i) s_pf_ring[i%256]=(GlPerfSample){i+1000,20.0+i,0.75};
 s_pf_ring_seq=300;
 assert(gl_renderer_perf_samples(0,seq,frames,ms,present,256)==256);
 assert(seq[0]==45 && seq[255]==300 && frames[0]==1044 && ms[255]==319 && present[255]==.75);
 assert(gl_renderer_perf_samples(298,seq,frames,ms,present,256)==2 && seq[0]==299);
 assert(!gl_renderer_perf_samples(300,seq,frames,ms,present,256));
 assert(!gl_renderer_perf_samples(UINT64_MAX,seq,frames,ms,present,256));
 assert(gl_renderer_perf_samples(0,seq,frames,ms,present,1)==1);
 assert(!gl_renderer_perf_samples(0,seq,frames,ms,present,0));
 assert(!gl_renderer_perf_samples(0,0,frames,ms,present,256));
 assert(!gl_renderer_perf_samples(0,seq,frames,ms,0,256));
}
'''.replace("FUNCTION", source[start:end])
with tempfile.TemporaryDirectory(prefix="jf2-perf-test-") as directory:
    fixture = Path(directory) / "samples.c"
    exe = Path(directory) / "samples.exe"
    fixture.write_text(program, encoding="utf-8")
    subprocess.run([sys.argv[2], "-std=c11", str(fixture), "-o", str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
print("PASS: timing reader handles empty, wrapped, incremental and bounded reads")
