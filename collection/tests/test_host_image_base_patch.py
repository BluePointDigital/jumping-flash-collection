"""Keep the opt-in sampler independent from explicit address metadata queries."""
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from patch_diagnostics import (function_span, host_image_base_source,
                               patch_host_image_base, _HOST_IMAGE_BASE_SIGNATURE)
from prepare_runtimes import PROJECTS


class HostImageBasePatchTests(unittest.TestCase):
    def test_clean_titles_preserve_other_source_and_repeat_safely(self):
        for game, (project, _) in PROJECTS.items():
            with self.subTest(game=game), tempfile.TemporaryDirectory() as temporary:
                original = (project / 'psxrecomp/runtime/src/host_sampler.c').read_text(encoding='utf-8')
                candidate = host_image_base_source(original)
                a, b = function_span(original, _HOST_IMAGE_BASE_SIGNATURE)
                c, d = function_span(candidate, _HOST_IMAGE_BASE_SIGNATURE)
                self.assertEqual(original[:a], candidate[:c])
                self.assertEqual(original[b:], candidate[d:])
                self.assertEqual(host_image_base_source(candidate), candidate)
                path = Path(temporary) / 'runtime/src/host_sampler.c'
                path.parent.mkdir(parents=True)
                path.write_text(original, encoding='utf-8')
                patch_host_image_base(temporary)
                self.assertEqual(path.read_text(encoding='utf-8'), candidate)
                first = path.read_bytes()
                patch_host_image_base(temporary)
                self.assertEqual(path.read_bytes(), first)

    def test_selected_source_matches_actual_compiled_candidate(self):
        stage = ROOT / '.workbench/static-recomp/staged/luna-frame-pacing'
        original = stage / 'jf2-full-static-gc-host-prep-v1/private-native-root/jf2/psxrecomp/runtime/src/host_sampler.c'
        candidate = stage / 'jf2-cycle-caller-image-base-fix-v1/source/runtime/src/host_sampler.c'
        self.assertEqual(host_image_base_source(original.read_text(encoding='utf-8')),
                         candidate.read_text(encoding='utf-8'))

    def test_unknown_or_duplicate_getter_is_rejected(self):
        original = (PROJECTS['jf2'][0] / 'psxrecomp/runtime/src/host_sampler.c').read_text(encoding='utf-8')
        for text in (original.replace('return (uint64_t)s_image_base;', 'return 0;'),
                     original + '\nuint64_t host_sampler_image_base(void) { return 0; }',
                     original.replace('#include <windows.h>', '#include "windows.h"')):
            with self.subTest(tail=text[-80:]), self.assertRaises(ValueError):
                host_image_base_source(text)


if __name__ == '__main__':
    unittest.main()
