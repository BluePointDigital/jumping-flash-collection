"""Exercise the restore upgrade on existing and clean collection renderers."""
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'collection/tools'))
from patch_graphics import framegen_restore_source,patch_history


class FrameRestorePatchTests(unittest.TestCase):
    def source(self,game):
        path=ROOT/'collection/.workbench/native'/game/'psxrecomp/runtime/src/gpu_gl_renderer.c'
        if not path.is_file():self.skipTest('prepared renderer source unavailable')
        return path.read_text(encoding='utf-8')

    def test_three_title_upgrade_is_idempotent_and_preserves_owned_buffer(self):
        for game in ('jf1','jf2','robbit'):
            with self.subTest(game=game),tempfile.TemporaryDirectory() as folder:
                original=self.source(game)
                expected=framegen_restore_source(original)
                path=Path(folder)/'runtime/src/gpu_gl_renderer.c'
                path.parent.mkdir(parents=True);path.write_text(original,encoding='utf-8')
                patch_history(Path(folder))
                self.assertEqual(path.read_text(encoding='utf-8'),expected)
                before=path.read_bytes();patch_history(Path(folder))
                self.assertEqual(before,path.read_bytes())
                start=expected.index('static void fg_reset_discontinuity(void) {')
                reset=expected[start:expected.index('\n}',start)+2]
                self.assertNotIn('s_fg_real_p',reset)
                self.assertNotIn('s_fg_real_cap',reset)
                self.assertNotIn('fg_flush(',reset)
                self.assertNotIn('fg_present_real(',reset)
                self.assertIn('s_fg_pending = 0;',reset)
                self.assertIn('s_fg_real_kept = 0;',reset)

    def test_changed_or_partial_restore_patch_is_rejected(self):
        source=self.source('jf1')
        changed=source.replace('    interp_reset_history();\n','    changed_reset();\n')
        with self.assertRaisesRegex(ValueError,'anchor changed'):
            framegen_restore_source(changed)
        candidate=framegen_restore_source(source)
        partial=candidate.replace('    s_fg_real_kept = 0;\n','')
        with self.assertRaisesRegex(ValueError,'incomplete or changed'):
            framegen_restore_source(partial)

    def test_clean_title_history_preparation_keeps_restore_upgrade(self):
        sources=('jumping-flash-1/.workbench',
                 '.jf2-workbench/recomp/JumpingFlash2Recomp','robbit-mon-dieu/.workbench')
        for source in sources:
            with self.subTest(source=source),tempfile.TemporaryDirectory() as folder:
                original=ROOT/source/'psxrecomp/runtime/src/gpu_gl_renderer.c'
                if not original.is_file():self.skipTest('clean source unavailable')
                path=Path(folder)/'runtime/src/gpu_gl_renderer.c'
                path.parent.mkdir(parents=True);path.write_bytes(original.read_bytes())
                patch_history(Path(folder))
                result=path.read_text(encoding='utf-8')
                self.assertIn('// COLLECTION_FRAME_HISTORY_V3',result)
                self.assertEqual(result.count('    fg_reset_discontinuity();'),1)
                self.assertEqual(result,framegen_restore_source(result))


if __name__=='__main__':unittest.main()
