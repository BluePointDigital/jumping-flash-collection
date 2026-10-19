"""Generate synthetic guest code and check the BIOS exception handoff contract."""
from pathlib import Path
import re
import struct
import subprocess
import sys
import tempfile

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    header = bytearray(2048)
    header[:8] = b"PS-X EXE"
    base = 0x80010000
    words = [0x24040001, 0x0000000C, 0x24040002, 0x0000000C,
             0x3C048000, 0x0000000C, 0x03E00008, 0]
    for offset, value in [(0x10, base), (0x18, base), (0x1C, len(words)*4)]:
        struct.pack_into("<I", header, offset, value)
    exe = root / "syscalls.psx"
    exe.write_bytes(header + struct.pack("<8I", *words))
    seeds = root / "seeds.txt"
    seeds.write_text(f"0x{base:08X}\n")
    out = root / "generated"
    compiler = Path(sys.argv[1]).resolve()
    result = subprocess.run([str(compiler), str(exe), "--project-root", str(compiler.parent.parent), "--seeds", str(seeds),
                             "--out-dir", str(out), "--overlay"], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr + result.stdout
    source = "\n".join(p.read_text() for p in out.glob("*_full.c"))
    for offset in (4, 12, 20):
        pattern = rf"cpu->pc = 0x{base+offset:08X}u; if \(psx_syscall\(cpu, 0\)\) return;"
        assert re.search(pattern, source), f"Missing exact EPC/transfer handling at {base+offset:08X}"
print("Syscall EPC and exception-transfer regression passed")
