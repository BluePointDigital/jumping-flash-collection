"""Keep future preparation tied to the canary-tested diagnostic handlers."""
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from patch_diagnostics import patch_range_serializer, _RANGE_SIGNATURE


class RangeSerializerTests(unittest.TestCase):
    def source(self, game):
        return (ROOT / '.workbench/native' / game / 'psxrecomp/runtime/src/debug_server.c').read_text()

    def test_all_titles_receive_the_verified_handler_idempotently(self):
        for game in ('jf1', 'jf2', 'robbit'):
            with self.subTest(game=game), tempfile.TemporaryDirectory() as directory:
                framework = Path(directory)
                path = framework / 'runtime/src/debug_server.c'
                path.parent.mkdir(parents=True)
                path.write_text(self.source(game))
                patch_range_serializer(framework)
                result = path.read_text()
                start = result.index(_RANGE_SIGNATURE)
                end = result.index('\n}\n', start) + 2
                self.assertEqual(hashlib.sha256(result[start:end].encode()).hexdigest(),
                    'b981b3cc7584ae3272965762ca826f14d68c9e3ed9c9b43fc8220cbcede9532a')
                self.assertIn('"max ranges reached (%d)", WTRACE_MAX_RANGES', result)
                before = path.read_bytes()
                patch_range_serializer(framework)
                self.assertEqual(path.read_bytes(), before)

    def test_unknown_handler_is_rejected_before_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            framework = Path(directory)
            path = framework / 'runtime/src/debug_server.c'
            path.parent.mkdir(parents=True)
            # Select the serializer's body explicitly; unrelated earlier 2048
            # buffers do not establish drift of this handler.
            text = self.source('jf1')
            start = text.index(_RANGE_SIGNATURE)
            text = text[:start] + text[start:].replace('BUF_SZ = 2048', 'BUF_SZ = 2049', 1)
            path.write_text(text)
            before = path.read_bytes()
            with self.assertRaisesRegex(ValueError, 'source drifted'):
                patch_range_serializer(framework)
            self.assertEqual(path.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
