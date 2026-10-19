"""Future preparation must retain existing guards when enriching native pairs."""
from pathlib import Path
import hashlib
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from patch_compiler import patch_monotonic_publisher


class PublisherPatchTests(unittest.TestCase):
    def source(self, game):
        return (ROOT / '.workbench/native' / game / 'psxrecomp/tools/compile_overlays.py').read_text()

    def test_all_titles_use_identical_idempotent_publication_guard(self):
        for game in ('jf1', 'jf2', 'robbit'):
            with self.subTest(game=game), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'compiler.py'
                path.write_text(self.source(game))
                patch_monotonic_publisher(path)
                result = path.read_text()
                start = result.index('def publish_shard_pair(')
                end = result.index('\n\ndef ', start)
                self.assertEqual(hashlib.sha256((result[start:end] + '\n').encode()).hexdigest(),
                    '208772ed85a34be3030c1a22d67457d76b91b2da81f2c09901b1742061c23c91')
                before = path.read_bytes()
                patch_monotonic_publisher(path)
                self.assertEqual(path.read_bytes(), before)

    def test_unreviewed_publisher_drift_is_rejected_without_a_write(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'compiler.py'
            source = self.source('jf2').replace('    token = uuid.uuid4().hex',
                '    token = uuid.uuid4().hex  # source drift', 1)
            path.write_text(source)
            before = path.read_bytes()
            with self.assertRaisesRegex(ValueError, 'source drifted'):
                patch_monotonic_publisher(path)
            self.assertEqual(path.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
