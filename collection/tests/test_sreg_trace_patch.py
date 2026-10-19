"""Keep future preparations aligned with the function tested in native JF2."""
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from patch_diagnostics import (digest, function_span, patch_sreg_trace_fastpath,
                               sreg_trace_fastpath_source, _SREG_SIGNATURE,
                               _SREG_BEFORE, _SREG_AFTER)
from prepare_runtimes import PROJECTS


class SregTracePatchTests(unittest.TestCase):
    def test_clean_titles_preserve_other_source_and_repeat_safely(self):
        for game, (project, _) in PROJECTS.items():
            with self.subTest(game=game), tempfile.TemporaryDirectory() as tmp:
                source = project / 'psxrecomp/runtime/src/debug_server.c'
                original = source.read_text(encoding='utf-8')
                a, b = function_span(original, _SREG_SIGNATURE)
                self.assertEqual(digest(original[a:b]), _SREG_BEFORE)
                candidate = sreg_trace_fastpath_source(original)
                c, d = function_span(candidate, _SREG_SIGNATURE)
                self.assertEqual(digest(candidate[c:d]), _SREG_AFTER)
                self.assertEqual(original[:a], candidate[:c])
                self.assertEqual(original[b:], candidate[d:])
                self.assertEqual(sreg_trace_fastpath_source(candidate), candidate)
                path = Path(tmp) / 'runtime/src/debug_server.c'
                path.parent.mkdir(parents=True)
                path.write_text(original, encoding='utf-8')
                patch_sreg_trace_fastpath(tmp)
                self.assertEqual(path.read_text(encoding='utf-8'), candidate)
                first = path.read_bytes()
                patch_sreg_trace_fastpath(tmp)
                self.assertEqual(path.read_bytes(), first)
                self.assertEqual(source.read_text(encoding='utf-8'), original)

    def test_selected_source_reproduces_exact_native_candidate(self):
        base = ROOT / '.workbench/static-recomp/staged'
        selected = base / 'luna-widescreen/jf2-pacer-observer-v2/source/runtime/src/debug_server.c'
        native = base / 'root-jf2-sreg-fastpath-child-v1/source/debug_server.c'
        self.assertEqual(digest(selected.read_text(encoding='utf-8')),
                         '309b013bc53b5258ea46ac1871d56ca19a4e22226d3dde82d13be06716997f48')
        self.assertEqual(digest(native.read_text(encoding='utf-8')),
                         '637064c5881e77d51f6215a40ae04b9c15854625136525dbc86e833a2c12ef29')
        self.assertEqual(sreg_trace_fastpath_source(selected.read_text(encoding='utf-8')),
                         native.read_text(encoding='utf-8'))

    def test_original_patched_missing_and_duplicate_drift_fail_closed(self):
        original = PROJECTS['jf2'][0].joinpath('psxrecomp/runtime/src/debug_server.c').read_text(encoding='utf-8')
        patched = sreg_trace_fastpath_source(original)
        for changed in (original.replace('if (!cpu) return;', 'if (cpu == NULL) return;'),
                        patched.replace('if (!focus_func) return;', 'if (focus_func == 0) return;'),
                        original.replace(_SREG_SIGNATURE, 'static void changed(uint32_t func_addr)'),
                        original + '\n' + _SREG_SIGNATURE + '{}'):
            with self.subTest(tail=changed[-80:]), self.assertRaises(ValueError):
                sreg_trace_fastpath_source(changed)


if __name__ == '__main__':
    unittest.main()
