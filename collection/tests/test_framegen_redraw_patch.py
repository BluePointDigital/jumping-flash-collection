import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'collection/tools'))
from patch_graphics import framegen_completion_source, framegen_origin_cost_source, patch_framegen_redraw


class FramegenRedrawPatchTests(unittest.TestCase):
    def source(self, game='jf1'):
        path = ROOT / 'collection/.workbench/native' / game / 'psxrecomp/runtime/src/gpu_gl_renderer.c'
        if not path.is_file():
            self.skipTest('prepared runtime source is unavailable')
        return path.read_text(encoding='utf-8')

    def test_all_titles_prepare_idempotently_without_diagnostic_instrumentation(self):
        for game in ('jf1', 'jf2', 'robbit'):
            with self.subTest(game=game):
                original = self.source(game)
                candidate = framegen_origin_cost_source(framegen_completion_source(original))
                self.assertEqual(framegen_origin_cost_source(candidate), candidate)
                self.assertEqual(framegen_completion_source(candidate), candidate)
                self.assertNotIn('FG_GENERATE_REJECT', candidate)
                self.assertNotIn('origin_rebases', candidate)

    def test_changed_or_partial_render_implementation_fails_closed(self):
        original = self.source()
        candidate = framegen_origin_cost_source(original)
        invalid = (
            original.replace('if (s_hiw) return 0;', 'if (s_hiw) return 1;'),
            original.replace('if (!a->valid || !b->valid || s_hiw) return 0;',
                             'if (!a->valid || !b->valid || s_hiw) return 1;'),
            candidate.replace('L->wide_off != b->wide_off', 'L->wide_off == b->wide_off'),
            candidate.replace('s_fg_q_success[qi] = ok;', 's_fg_q_success[qi] = 1;'),
        )
        for changed in invalid:
            if changed == original:
                continue
            with self.subTest(change=changed[-40:]), self.assertRaises(ValueError):
                framegen_origin_cost_source(changed)

    def test_file_adapter_applies_both_fixes_and_preserves_bytes_on_second_pass(self):
        with tempfile.TemporaryDirectory() as folder:
            framework = Path(folder)
            path = framework / 'runtime/src/gpu_gl_renderer.c'
            path.parent.mkdir(parents=True)
            original = self.source()
            path.write_text(original, encoding='utf-8')
            patch_framegen_redraw(framework)
            expected = framegen_origin_cost_source(framegen_completion_source(original))
            self.assertEqual(path.read_text(encoding='utf-8'), expected)
            first = path.read_bytes()
            patch_framegen_redraw(framework)
            self.assertEqual(path.read_bytes(), first)


if __name__ == '__main__':
    unittest.main()
