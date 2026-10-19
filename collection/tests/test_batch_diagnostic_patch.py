"""Check the independent counter endpoint against all clean title sources."""
from pathlib import Path
import json,re,sys,unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from patch_diagnostics import batch_diagnostic_source,_BATCH_HANDLER
from prepare_runtimes import PROJECTS


class BatchDiagnosticTests(unittest.TestCase):
    def test_all_clean_titles_idempotent_with_bounded_counter_response(self):
        for game,(source,_) in PROJECTS.items():
            with self.subTest(game=game):
                original=(source/'psxrecomp/runtime/src/debug_server.c').read_text(encoding='utf-8')
                candidate=batch_diagnostic_source(original)
                self.assertEqual(batch_diagnostic_source(candidate),candidate)
                self.assertEqual(candidate.replace(_BATCH_HANDLER,'').replace(
                    '    { "gl_batch_diag",     handle_gl_batch_diag },\n',''),original)
        body=_BATCH_HANDLER
        self.assertLess(body.index('collection_diagnostic_enabled('),body.index('gl_renderer_batch_diag(counts)'))
        self.assertNotIn('gl_renderer_perf_aggregate',body)
        self.assertNotIn('glQuery',body)
        encoded=re.search(r'send_fmt\("((?:\\.|[^"\\])*)"',body).group(1)
        fmt=bytes(encoded,'utf-8').decode('unicode_escape').replace('%llu','%d')
        values=[0,1,255,65535,2**32,2**40,2**48,2**56,2**64-1]
        response=(fmt%(7,*values))+'\n'  # send_fmt delegates to send_line, which adds LF.
        self.assertLess(len(response),256)
        self.assertEqual(json.loads(response),dict(id=7,ok=True,batch_diag=values))

    def test_missing_duplicate_and_modified_anchors_fail_closed(self):
        source=next(iter(PROJECTS.values()))[0]
        original=(source/'psxrecomp/runtime/src/debug_server.c').read_text(encoding='utf-8')
        candidate=batch_diagnostic_source(original)
        for changed in (original.replace('gl_renderer_batch_diag(br);',''),
                        original.replace('static void handle_frame_perf','static void changed_frame_perf'),
                        candidate.replace('uint64_t counts[9];','uint64_t counts[8];'),
                        candidate+_BATCH_HANDLER,
                        candidate+'    {"gl_batch_diag", handle_gl_batch_diag},\n'):
            with self.subTest(changed=changed[-40:]),self.assertRaises(ValueError):
                batch_diagnostic_source(changed)


if __name__=='__main__':unittest.main()
