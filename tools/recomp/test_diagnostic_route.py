"""Compile actual route sampling and its desktop booster adapter."""
from pathlib import Path
import subprocess
import sys
import tempfile

source = Path(sys.argv[1]).read_text(encoding="utf-8")
start = source.index("#define INPUT_ROUTE_MAX_STEPS")
route = source[start:source.index("/* ---- Frontend turbo override", start)]
sampling = source[source.index("int debug_server_get_input_override(void)"):
                  source.index("int debug_server_get_input_override_port2(void)")]
desktop = Path(sys.argv[2]).read_text(encoding="utf-8")
start = desktop.index('extern "C" int debug_server_get_input_boost(void);')
adapter = desktop[start:desktop.index("\n}", start) + 2]
program = '''#include <stdint.h>
#include <assert.h>
#define JF2_DESKTOP 1
#define PSX_BSS
static int s_input_override=-1,s_input_frames;
extern "C" {
ROUTE
SAMPLING
}
static int jf2_injected_pad=-1;
static bool jf2_boost_held=false;
static struct { bool jf2_boost; } jf2_settings={true};
ADAPTER
int main() {
 s_input_route[0]={1,0xFFEF,1}; s_input_route[1]={1,0xFFFF,0};
 s_input_route_count=2;s_input_route_active=1;s_input_route_remaining=1;
 jf2_desktop_input_source(debug_server_get_input_override());
 assert(jf2_boost_held && jf2_injected_pad==0xFFEF && s_input_route_index==1);
 jf2_desktop_input_source(debug_server_get_input_override());
 assert(!jf2_boost_held && jf2_injected_pad==0xFFFF && !s_input_route_active);
 assert(debug_server_get_input_override()==-1 && !debug_server_get_input_boost());
 jf2_settings.jf2_boost=false;s_input_route_boost=1;jf2_desktop_input_source(0xFFEF);
 assert(!jf2_boost_held);
 jf2_boost_held=true;jf2_desktop_input_source(-1);assert(jf2_boost_held);
}
'''.replace("ROUTE", route).replace("SAMPLING", sampling).replace("ADAPTER", adapter)
with tempfile.TemporaryDirectory(prefix="jf2-route-test-") as directory:
    fixture = Path(directory) / "route.cpp"
    exe = Path(directory) / "route.exe"
    fixture.write_text(program, encoding="utf-8")
    subprocess.run([sys.argv[3], "-std=c++17", str(fixture), "-o", str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
print("PASS: last-frame boost, release, disabled preference and native ownership")
