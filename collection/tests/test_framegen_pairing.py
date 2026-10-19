import sys
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'collection/tools'))
from patch_graphics import framegen_fit_source,framegen_pair_source,framegen_camera_source,patch_camera_fit


class FramegenPairingTests(unittest.TestCase):
    def source(self,game='jf1'):
        path=ROOT/'collection/.workbench/native'/game/'psxrecomp/runtime/src/frame_gen.c'
        if not path.is_file():self.skipTest('prepared runtime source is unavailable')
        return path.read_text(encoding='utf-8')

    def test_all_title_adapters_match_verified_candidate_and_are_idempotent(self):
        for game in ('jf1','jf2','robbit'):
            with self.subTest(game=game),tempfile.TemporaryDirectory() as folder:
                framework=Path(folder);path=framework/'runtime/src/frame_gen.c'
                path.parent.mkdir(parents=True);path.write_text(self.source(game),encoding='utf-8')
                patch_camera_fit(framework)
                candidate=path.read_text(encoding='utf-8')
                self.assertEqual(framegen_camera_source(candidate),candidate)
                first=path.read_bytes();patch_camera_fit(framework)
                self.assertEqual(path.read_bytes(),first)

    def test_sort_drift_and_partial_pairing_transform_fail_closed(self):
        source=framegen_fit_source(self.source())
        for changed in (source.replace('qsort(', 'changed_sort('),
                        source.replace('uint32_t np = 0;', 'uint32_t np = 0, sa_cursor = 0;'),
                        source+'\n'):
            self.assertNotEqual(changed,source)
            with self.assertRaisesRegex(ValueError,'pairing implementation'):
                framegen_pair_source(changed)


if __name__=='__main__':unittest.main()
