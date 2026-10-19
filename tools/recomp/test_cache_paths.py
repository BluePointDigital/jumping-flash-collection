"""Compile the actual cache duplicate check, including Windows normalization."""
from pathlib import Path
import subprocess
import sys
import tempfile

source = Path(sys.argv[1]).read_text(encoding="utf-8")
normalization = source[source.index("static int cache_path_char_equal("):source.index("static int cache_path_has_root(")]
lookup = source[source.index("static uint64_t cache_path_hash("):source.index("/* Cache discovery is idempotent")]
assert source.count("e->path_hash = 0;") == 2, "Both cache insertion paths must reset recycled hashes"
program = r'''#include <stdint.h>
#include <string.h>
#include <ctype.h>
#include <assert.h>
#ifdef TEST_POSIX_PATHS
#undef _WIN32
#endif
typedef struct { uint64_t path_hash; char path[768]; } CacheEntry;
static CacheEntry s_cache_idx[4]; static int s_cache_idx_count;
NORMALIZATION
LOOKUP
int main(void) {
 strcpy(s_cache_idx[0].path,"C:/CACHE/a.dll"); s_cache_idx_count=1;
 assert(cache_idx_has_path("C:/CACHE/a.dll"));
 assert(!cache_idx_has_path("C:/CACHE/b.dll"));
#ifdef _WIN32
 assert(cache_idx_has_path("c:\\cache\\A.DLL"));
#else
 assert(!cache_idx_has_path("c:/cache/a.dll"));
#endif
 s_cache_idx[0].path_hash=cache_path_hash("C:/CACHE/b.dll");
 assert(!cache_idx_has_path("C:/CACHE/b.dll")); /* Deliberate hash collision. */
 strcpy(s_cache_idx[1].path,"C:/CACHE/b.dll"); s_cache_idx_count=2;
 assert(cache_idx_has_path("C:/CACHE/b.dll"));
 assert(!cache_idx_has_path("C:/CACHE/b.dll.repair"));
 /* Recycled entries cannot retain a hash from the deleted artifact. */
 s_cache_idx_count=1; s_cache_idx[0].path_hash=0;
 strcpy(s_cache_idx[0].path,"C:/CACHE/replacement.dll");
 assert(cache_idx_has_path("C:/CACHE/replacement.dll"));
 assert(!cache_idx_has_path("C:/CACHE/a.dll"));
}
'''.replace("NORMALIZATION", normalization).replace("LOOKUP", lookup)
with tempfile.TemporaryDirectory(prefix="jf2-cache-path-test-") as directory:
    fixture = Path(directory) / "paths.c"
    fixture.write_text(program, encoding="utf-8")
    for windows in (False, True):
        exe = Path(directory) / ("windows.exe" if windows else "posix.exe")
        cmd = [sys.argv[2], "-std=c11", "-DJF2_DESKTOP=1", str(fixture), "-o", str(exe)]
        if windows:
            cmd.append("-D_WIN32=1")
        else:
            cmd.append("-DTEST_POSIX_PATHS=1")
        subprocess.run(cmd, check=True)
        subprocess.run([str(exe)], check=True)
print("PASS: cache duplicate checks preserve path normalization and reject hash collisions")
