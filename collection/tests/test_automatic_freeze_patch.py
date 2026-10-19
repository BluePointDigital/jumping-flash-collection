"""Check the automatic-only gate across supported title sources."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from prepare_runtimes import PROJECTS
from patch_diagnostics import automatic_freeze_dump_source, function_span


class AutomaticFreezePatchTests(unittest.TestCase):
    def test_title_sources_are_idempotent_and_fatal_handler_is_unchanged(self):
        paths = [source / 'psxrecomp/runtime/src/freeze_heartbeat.c'
            for source, _ in PROJECTS.values()]
        paths.append(ROOT / '.workbench/native/jf1/psxrecomp/runtime/src/freeze_heartbeat.c')
        for path in paths:
            with self.subTest(path=path):
                original = path.read_text(encoding='utf-8')
                result = automatic_freeze_dump_source(original)
                self.assertEqual(result, automatic_freeze_dump_source(result))
                sig = 'void freeze_heartbeat_fatal_dump(const char *reason)'
                a, b = function_span(original, sig)
                c, d = function_span(result, sig)
                self.assertEqual(original[a:b], result[c:d])
                self.assertIn('wedge_kind == 0 ||', result)

    def test_changed_policy_anchor_rejects(self):
        source = (ROOT / '.workbench/native/jf1/psxrecomp/runtime/src/freeze_heartbeat.c').read_text()
        source = source.replace('if (!s_wedge_classification_paused &&',
            'if (s_wedge_classification_paused &&', 1)
        with self.assertRaisesRegex(ValueError, 'automatic freeze-dump policy'):
            automatic_freeze_dump_source(source)


if __name__ == '__main__':
    unittest.main()
