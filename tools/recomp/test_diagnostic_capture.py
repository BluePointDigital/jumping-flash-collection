"""Compile the real display-recorder gate for desktop and shared builds."""
from pathlib import Path
import subprocess
import sys
import tempfile

source = Path(sys.argv[1]).read_text(encoding="utf-8")
start = source.index("    static int enabled = -1;", source.index("static void disp_ring_capture(void)"))
end = source.index("    if (!enabled || s_capture_frozen) return;", start)
gate = source[start:end].replace("static int enabled", "int enabled")
gate = gate.replace('getenv("PSX_DISPLAY_RING")', "setting")
program = '''#include <assert.h>
#include <stddef.h>
static int enabled_for(const char *setting) {
GATE
return enabled;
}
int main(void) {
#ifdef JF2_DESKTOP
assert(!enabled_for(NULL)); assert(!enabled_for(""));
#else
assert(enabled_for(NULL)); assert(enabled_for(""));
#endif
assert(!enabled_for("0")); assert(enabled_for("1"));
assert(enabled_for("yes"));
}
'''.replace("GATE", gate)
with tempfile.TemporaryDirectory(prefix="jf2-capture-test-") as directory:
    fixture = Path(directory) / "capture.c"
    fixture.write_text(program, encoding="utf-8")
    for desktop in (False, True):
        exe = Path(directory) / ("desktop.exe" if desktop else "shared.exe")
        cmd = [sys.argv[2], "-std=c11", str(fixture), "-o", str(exe)]
        if desktop:
            cmd.append("-DJF2_DESKTOP=1")
        subprocess.run(cmd, check=True)
        subprocess.run([str(exe)], check=True)
print("PASS: desktop capture is opt-in; shared defaults and explicit choices are preserved")
