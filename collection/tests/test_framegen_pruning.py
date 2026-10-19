import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'collection/tools'))
from patch_graphics import framegen_fit_source

LOOP = '''            uint32_t c = 0;
            for (uint32_t i = 0; i < np; i++) c += (uint32_t)is_inlier(m, r.t, a[i], b[i], hb[i], p);
            if (c > best_n) { best_n = c; best_r = r; }'''
CLANG = ROOT / '.jf2-workbench/recomp/toolchain/bin/clang.exe'


class FramegenPruningTests(unittest.TestCase):
    def test_upstream_winner_changes_fail_closed_and_patch_is_idempotent(self):
        patched = framegen_fit_source(LOOP)
        self.assertEqual(framegen_fit_source(patched), patched)
        for invalid in ('', LOOP + LOOP, LOOP.replace('c > best_n', 'c >= best_n')):
            with self.subTest(source=invalid), self.assertRaises(ValueError):
                framegen_fit_source(invalid)

    @unittest.skipUnless(CLANG.is_file(), 'bundled C compiler is unavailable')
    def test_compiled_transformed_loop_preserves_every_small_inlier_pattern(self):
        program = '''#include <stdint.h>
#include <stdio.h>
typedef struct { unsigned id; double t[3]; } Rigid;
typedef struct { unsigned count, id, calls; } Result;
static unsigned flags[12], calls;
static int is_inlier(const double *m, const double *t, const float *a,
                     const float *b, float h, const void *p) {
    (void)m;(void)t;(void)b;(void)h;(void)p;
    calls++; return flags[(unsigned)a[0]];
}
'''
        for name, body in [('reference', LOOP), ('candidate', framegen_fit_source(LOOP))]:
            program += 'static Result ' + name + '''(uint32_t np, uint32_t best_n) {
    Rigid r={2,{0}}, best_r={1,{0}};
    double m[9]={0}; float a[12][3]={{0}}, b[12][3]={{0}}, hb[12]={0};
    const void *p=0;
    for(unsigned i=0;i<np;i++)a[i][0]=(float)i;
    calls=0;
''' + body + '''
    Result result={best_n,best_r.id,calls};return result;
}
'''
        program += '''int main(void) {
    for(unsigned n=0;n<=12;n++)for(unsigned bits=0;bits<(1u<<n);bits++) {
        for(unsigned i=0;i<n;i++)flags[i]=(bits>>i)&1;
        for(unsigned best=0;best<=n;best++) {
            Result a=reference(n,best),b=candidate(n,best);
            if(a.count!=b.count||a.id!=b.id||b.calls>a.calls)return 1;
        }
    }
    puts("All inlier patterns through 12 pairs preserve winner and ties");return 0;
}
'''
        with tempfile.TemporaryDirectory(prefix='framegen-pruning-') as folder:
            source = Path(folder) / 'check.c'
            executable = Path(folder) / 'check.exe'
            source.write_text(program, encoding='utf-8')
            subprocess.run([str(CLANG), '-O2', str(source), '-o', str(executable)], check=True,
                           capture_output=True, text=True)
            result = subprocess.run([str(executable)], check=True, capture_output=True, text=True)
            self.assertIn('preserve winner and ties', result.stdout)


if __name__ == '__main__':
    unittest.main()
