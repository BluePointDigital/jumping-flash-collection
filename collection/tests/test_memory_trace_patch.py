"""Exercise reviewed memory-trace guards with both preparation orders."""
import hashlib
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from prepare_runtimes import PROJECTS
from patch_diagnostics import (ambient_memory_trace_source, range_serializer_source,
    function_span, HOOK_SIGNATURE, HOOK_AFTER)


class MemoryTracePatchTests(unittest.TestCase):
    def test_all_clean_and_prepared_sources_compose_and_remain_idempotent(self):
        sources = {game: source / 'psxrecomp/runtime/src/debug_server.c'
            for game, (source, _) in PROJECTS.items()}
        sources['prepared'] = ROOT / '.workbench/native/robbit/psxrecomp/runtime/src/debug_server.c'
        sources['metadata'] = ROOT / '.workbench/static-recomp/staged/luna-widescreen/wide-margin-atomic-meta-v1/host/debug_server.c'
        for game, path in sources.items():
            with self.subTest(game=game):
                original = path.read_text()
                result = ambient_memory_trace_source(range_serializer_source(original))
                self.assertEqual(result, range_serializer_source(ambient_memory_trace_source(original)))
                self.assertEqual(result, ambient_memory_trace_source(result))
                self.assertEqual(result, range_serializer_source(result))
                start, end = function_span(result, HOOK_SIGNATURE)
                self.assertEqual(hashlib.sha256(result[start:end].encode()).hexdigest(), HOOK_AFTER)

    def test_hook_drift_and_tampered_markers_are_rejected(self):
        source = (ROOT / '.workbench/native/robbit/psxrecomp/runtime/src/debug_server.c').read_text()
        with self.assertRaisesRegex(ValueError, 'write-hook source drift'):
            ambient_memory_trace_source(source.replace(
                'fp_record_write(phys, new_val, g_debug_last_store_pc);',
                'fp_record_write(phys, old_val, g_debug_last_store_pc);', 1))
        applied = ambient_memory_trace_source(source)
        with self.assertRaisesRegex(ValueError, 'marker/helper drift'):
            ambient_memory_trace_source(applied.replace('strcmp(e, "off") != 0;',
                'strcmp(e, "off") == 0;', 1))


if __name__ == '__main__':
    unittest.main()
