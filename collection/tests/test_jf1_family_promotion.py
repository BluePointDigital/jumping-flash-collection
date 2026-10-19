"""Focused regressions for the optional JF1 source-preparation path."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import family_promotion as family
import prepare_runtimes as runtimes


class FamilyPreparationTests(unittest.TestCase):
    def test_bundle_can_be_verified_from_maintained_location(self):
        manifest = family.verify_bundle()
        self.assertTrue(manifest['sources'])
        self.assertTrue(manifest['supplemental_artifacts'])

    def test_complete_focus_function_is_replaced(self):
        original = '''static bool host_hotkey_input_focused(void) {
    /* old-body-sentinel: nested braces and a quoted closing brace. */
    if (sdl_window) { const char *brace = "}"; return brace[0] != 0; }
    return true;
}
extern "C" void psx_frontend_on_savestate_loaded(void) {
    saved();
}
extern "C" void psx_frontend_on_rb_snap_loaded(void) {
    restored();
}
static void following_function() { untouched(); }
'''
        result = family.patch_main(original)
        self.assertNotIn('old-body-sentinel', result)
        self.assertEqual(result.count('static bool host_hotkey_input_focused(void)'), 1)
        self.assertIn('static void following_function() { untouched(); }', result)
        self.assertEqual(family.patch_main(result), result)
        incomplete = result.replace('        psx_jf1_owner_correlation_reset();', '')
        with self.assertRaisesRegex(ValueError, 'incomplete focus'):
            family.patch_main(incomplete)

    def test_family_cmake_has_one_source_set(self):
        original = 'target_compile_definitions(psx-runtime PRIVATE JF1_DESKTOP=1)\n'
        result = family.patch_cmake(original)
        self.assertEqual(result.count('/runtime/jf1_family/src/'), 12)
        self.assertEqual(family.patch_cmake(result), result)

    def test_invalid_order_fails_before_existing_project_changes(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(runtimes, 'ROOT', Path(tmp)):
            target = Path(tmp) / '.workbench/native/jf1'
            target.mkdir(parents=True)
            cmake = target / 'CMakeLists.txt'
            cmake.write_text('preserve existing project')
            with self.assertRaisesRegex(ValueError, 'source-only'):
                runtimes.prepare('jf1', source_only=False, jf1_family_source=True)
            with self.assertRaisesRegex(ValueError, 'JF1-only'):
                runtimes.prepare('jf2', source_only=True, jf1_family_source=True)
            (target / 'psxrecomp/runtime/jf1_family').mkdir(parents=True)
            with self.assertRaisesRegex(ValueError, 'fresh private target'):
                runtimes.prepare('jf1', source_only=True, jf1_family_source=True)
            with self.assertRaisesRegex(ValueError, 'cannot be reset'):
                runtimes.prepare('jf1', source_only=True)
            self.assertEqual(cmake.read_text(), 'preserve existing project')


if __name__ == '__main__':
    unittest.main()
