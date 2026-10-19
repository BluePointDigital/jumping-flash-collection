import base64
import copy
import hashlib
import json
from pathlib import Path
import struct
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from source_slices import instruction_closure, source_slice_plans, compile_source_slices, TAIL_SIGNATURE
from static_dispatches import _extractor
from game_installed_aot import PALETTE_LAYOUTS


@unittest.skipUnless((ROOT / '.workbench/native/jf1/psxrecomp').is_dir(), 'Native compiler required')
class SourceSliceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.framework = ROOT / '.workbench/native/jf1/psxrecomp'
        cls.co = _extractor(str(cls.framework.resolve()))['co']

    def fixture(self):
        load = 0x80010000; body = bytearray(128)
        # The direct callee tail-branches into code preceding the initial root.
        struct.pack_into('<2I', body, 0, 0x03e00008, 0)
        struct.pack_into('<4I', body, 32, 0x0c000000 | ((load + 64) >> 2 & 0x3ffffff),
                         0, 0x03e00008, 0)
        struct.pack_into('<2I', body, 64, 0x08000000 | (load >> 2 & 0x3ffffff), 0)
        return load, body

    def test_direct_callee_nonlocal_tail_and_call_return_are_included(self):
        load, body = self.fixture()
        graph = instruction_closure(self.co, body, load, load + 32, [])
        self.assertEqual(graph['ranges'], [[load, 8], [load + 32, 16], [load + 64, 8]])
        self.assertEqual(graph['entry_points'], [load, load + 32, load + 40, load + 64])
        self.assertEqual(graph['source_instructions'], 8)
        self.assertEqual(graph['external_boundaries'], [])

    def test_mutable_callee_stays_opaque_but_return_path_is_retained(self):
        load, body = self.fixture()
        graph = instruction_closure(self.co, body, load, load + 32, [(load + 64, 8)])
        self.assertEqual(graph['ranges'], [[load + 32, 16]])
        self.assertEqual(graph['external_boundaries'], [load + 64])

    def test_rejects_invalid_bounds_budget_instruction_slot_and_tail(self):
        load, body = self.fixture()
        for kwargs in [dict(entry=load + 1), dict(opaque=[(load + 128, 4)]), dict(budget=1)]:
            args = dict(entry=load + 32, opaque=[]); args.update(kwargs)
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                instruction_closure(self.co, body, load, **args)
        for offset, word in [(64, 0xffffffff), (36, 0x03e00008), (64, 0x01000008)]:
            changed = bytearray(body); struct.pack_into('<I', changed, offset, word)
            with self.subTest(offset=offset, word=word), self.assertRaises(ValueError):
                instruction_closure(self.co, changed, load, load + 32, [])
        with self.assertRaises(ValueError):
            instruction_closure(self.co, body, load, load + 32, [(load + 36, 4)])

    def test_indirect_calls_are_recorded_without_guessing_targets(self):
        load, body = self.fixture(); struct.pack_into('<I', body, 32, 0x0320f809)
        graph = instruction_closure(self.co, body, load, load + 32, [])
        self.assertEqual(graph['indirect_call_sites'], [load + 32])
        self.assertEqual(graph['ranges'], [[load + 32, 16]])

    def test_plan_scope_keeps_repairs_other_titles_and_unselected_images_out(self):
        load, body = self.fixture()
        record = dict(producer='verified_psx_exe_lz1', producer_name='JM1/MAIN.PEX',
                      load_addr=hex(load), size=len(body), bytes_b64=base64.b64encode(body).decode())
        for game, selection, repair in [('jf2', [], []), ('robbit', [], []),
                                       ('jf1', ['TITLE.PEX'], []), ('jf1', [], [load])]:
            self.assertEqual(source_slice_plans(game, [record], self.framework, selection, repair), [])

    def test_plan_requires_exact_source_template_and_unique_signature(self):
        load = 0x80010000; body = bytearray(0x2000)
        body[:32] = TAIL_SIGNATURE
        layout = dict(load_addr=hex(load), body_sha256=hashlib.sha256(body).hexdigest(),
                      template=hex(load + 0x1e64), size=120,
                      template_sha256=hashlib.sha256(body[0x1e64:0x1edc]).hexdigest())
        def record(data):
            return dict(producer='verified_psx_exe_lz1', producer_name='JM1/MAIN.PEX',
                        load_addr=hex(load), size=len(data), bytes_b64=base64.b64encode(data).decode())
        changed = bytearray(body); changed[40] ^= 1
        with patch.dict(PALETTE_LAYOUTS['jf1'], {'JM1/MAIN.PEX':layout}), self.assertRaises(ValueError):
            source_slice_plans('jf1', [record(changed)], self.framework)
        for data, overrides in [(body, dict(template_sha256='0'*64)),
                                (body, dict(template=hex(load + 0x3000))),
                                (bytes(len(body)), {}),
                                (TAIL_SIGNATURE + TAIL_SIGNATURE + body[64:], {})]:
            candidate = dict(layout, body_sha256=hashlib.sha256(data).hexdigest(), **overrides)
            with patch.dict(PALETTE_LAYOUTS['jf1'], {'JM1/MAIN.PEX':candidate}), self.assertRaises(ValueError):
                source_slice_plans('jf1', [record(data)], self.framework)

    def test_actual_twelve_world_plans_match_reviewed_source_proof(self):
        prep = ROOT / '.workbench/static-recomp/aot/jf1-inclusive-emitter-all-worlds/records.json'
        proof = ROOT.parent / 'optimizations/evidence/jf1-all-world-gte-call-closed-slices.json'
        if not prep.is_file() or not proof.is_file():
            self.skipTest('Local verified images/source proof required')
        records = json.loads(prep.read_text()); before = copy.deepcopy(records)
        plans = source_slice_plans('jf1', records, self.framework)
        expected = {row['image']:row for row in json.loads(proof.read_text())['images']}
        self.assertEqual({plan['image'] for plan in plans}, set(expected))
        self.assertEqual(len(plans), 12)
        for plan in plans:
            row = expected[plan['image']]
            self.assertEqual(plan['source_sha256'], row['source_sha256'])
            self.assertEqual(plan['ranges'], [[int(pc,16), n] for pc,n in row['ranges']])
            self.assertEqual(plan['entry_points'], [int(pc,16) for pc in row['entry_points']])
            self.assertEqual(plan['source_instructions'], 2474)
            self.assertEqual(len(plan['entry_points']), 312)
        self.assertEqual(records, before)

    def test_publisher_dedupes_only_exact_slices_and_audit_never_compiles(self):
        load, body = self.fixture()
        plan = instruction_closure(self.co, body, load, load + 32, [])
        plan.update(image='JM1/MAIN.PEX', source_sha256=hashlib.sha256(body).hexdigest())
        other = dict(plan, image='JM1B/MAIN.PEX')
        records = [dict(producer_name=p['image'], load_addr=hex(load),
                        bytes_b64=base64.b64encode(body).decode()) for p in (plan, other)]
        # Only the publisher is substituted; assert its public arguments and all
        # required post-publication checks independently of native compilation.
        calls = []; ids = [(pc, 123, [(pc, 4)]) for pc in plan['entry_points']]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); framework = root/'native/psxrecomp'; framework.mkdir(parents=True)
            (framework.parent/'game.toml').write_text('[game]\nid="SCUS-94103"\n')
            def publish(entries, data, lo, size, physical, cache, args, env, document, **kw):
                calls.append(entries)
                self.assertEqual(entries, plan['entry_points']); self.assertEqual(lo, load)
                self.assertEqual(data, body[:72]); self.assertEqual(kw['guard_bytes'], 0)
                self.assertEqual(kw['producer_ranges'], [(a,a+n) for a,n in plan['ranges']])
                dll = Path(cache)/'00010000_00000001.dll'; dll.write_bytes(b'native')
                dll.with_suffix('.ranges').write_text('manifest')
                return ids, 'built'
            api = SimpleNamespace(load_dispatch_preamble=lambda p:None,
                verify_recompiler_matches_tag=lambda *a:None, codegen_hash=lambda p:1,
                cache_tag=lambda *a:'tag', cache_arch_abi=lambda:'win-x64', overlay_abi_tag=lambda *a:30,
                compile_fragment_batch=publish, current_variant_func_ids=lambda *a:ids,
                fragment_shard_key=lambda i:1, load_shard_func_ids=lambda *a:ids)
            with patch('source_slices._extractor', return_value={'co':api}):
                results = compile_source_slices([plan,other], records, framework, 'recompiler', 'clang', root/'out', {})
                self.assertEqual(len(calls), 1)
                self.assertEqual(results[1]['status'], 'reused-exact-source-slice')
                self.assertEqual(results[1]['image'], 'JM1B/MAIN.PEX')
                results = compile_source_slices([plan], records, framework, 'recompiler', 'clang', root/'out', {}, audit_only=True)
                self.assertEqual(results[0]['status'], 'audited-existing'); self.assertEqual(len(calls), 1)
                api.current_variant_func_ids = lambda *a:[]
                with self.assertRaisesRegex(ValueError, 'failed to publish all entries'):
                    compile_source_slices([plan], records, framework, 'recompiler', 'clang', root/'out', {}, audit_only=True)

    def test_publisher_rejects_guard_expansion_into_a_source_gap(self):
        load, body = self.fixture()
        plan = instruction_closure(self.co, body, load, load + 32, [])
        plan.update(image='JM1/MAIN.PEX', source_sha256=hashlib.sha256(body).hexdigest())
        record = dict(producer_name=plan['image'], load_addr=hex(load), bytes_b64=base64.b64encode(body).decode())
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); framework=root/'native/psxrecomp';framework.mkdir(parents=True)
            (framework.parent/'game.toml').write_text('[game]\nid="SCUS-94103"\n')
            api=SimpleNamespace(load_dispatch_preamble=lambda *a:None, verify_recompiler_matches_tag=lambda *a:None,
                codegen_hash=lambda *a:1,cache_tag=lambda *a:'tag',cache_arch_abi=lambda:'win-x64',
                overlay_abi_tag=lambda *a:30,compile_fragment_batch=lambda *a,**k:(
                    [(pc,123,[(load,72)]) for pc in plan['entry_points']],'built'))
            with patch('source_slices._extractor',return_value={'co':api}), self.assertRaisesRegex(ValueError,'unproven or mutable'):
                compile_source_slices([plan],[record],framework,'recompiler','clang',root/'out',{})


if __name__ == '__main__':
    unittest.main()
