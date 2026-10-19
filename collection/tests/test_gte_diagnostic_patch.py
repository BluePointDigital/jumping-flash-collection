"""Keep future preparations aligned with the reviewed trace-only candidate."""
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from patch_diagnostics import gte_diagnostic_source, patch_gte_diagnostics
from prepare_runtimes import PROJECTS


class GteDiagnosticPatchTests(unittest.TestCase):
    def test_reviewed_selected_source_and_candidate_match_exactly(self):
        base = ROOT / '.workbench/static-recomp/staged/luna-frame-pacing'
        selected = base / 'jf2-full-static-gc-host-prep-v1/private-native-root/jf2/psxrecomp/runtime/src/gte.cpp'
        candidate = base / 'jf2-gte-diagnostics-default-off-v1/gte.cpp'
        self.assertEqual(hashlib.sha256(selected.read_bytes()).hexdigest(),
                         '97c4a73a25935c7d413a00c680c64197f88419e5ed075328924014379247a6e2')
        self.assertEqual(hashlib.sha256(candidate.read_bytes()).hexdigest(),
                         '7cd81104fb25c04f84b0dd1681e2065066adba38975591d05d37824096335337')
        self.assertEqual(gte_diagnostic_source(selected.read_text()), candidate.read_text())

    def test_each_title_preparation_is_idempotent_and_writes_only_copy(self):
        for game, (source, _) in PROJECTS.items():
            with self.subTest(game=game), tempfile.TemporaryDirectory() as tmp:
                original = (source / 'psxrecomp/runtime/src/gte.cpp').read_text()
                candidate = gte_diagnostic_source(original)
                self.assertEqual(gte_diagnostic_source(candidate), candidate)
                path = Path(tmp) / 'runtime/src/gte.cpp'
                path.parent.mkdir(parents=True)
                path.write_text(original)
                patch_gte_diagnostics(tmp)
                first = path.read_bytes()
                self.assertEqual(path.read_text(), candidate)
                patch_gte_diagnostics(tmp)
                self.assertEqual(path.read_bytes(), first)

    def test_missing_duplicate_or_modified_guards_fail_closed(self):
        source = next(iter(PROJECTS.values()))[0]
        original = (source / 'psxrecomp/runtime/src/gte.cpp').read_text()
        candidate = gte_diagnostic_source(original)
        for changed in (
            original.replace('#include "render_pass_projection.h"', ''),
            original + '\n    uint8_t func = cmd & 0x3F;\n',
            candidate.replace('PSX_DIAG_GTE_RTP', 'PSX_DIAG_CHANGED'),
            candidate.replace('if (trace_intpl) gte_intpl_record', 'if (true) gte_intpl_record'),
        ):
            with self.subTest(case=changed[-60:]), self.assertRaises(ValueError):
                gte_diagnostic_source(changed)


if __name__ == '__main__':
    unittest.main()
