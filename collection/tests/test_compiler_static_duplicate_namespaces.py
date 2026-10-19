from __future__ import annotations

import ast
import os
from pathlib import Path
import re
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from patch_compiler import patch_static_duplicate_namespaces

REFERENCE = (ROOT / '.workbench/static-recomp/maintained-source-20261016-v1/'
             'robbit/psxrecomp/tools/compile_overlays.py')


def load_writer(source_path: Path):
    patch_static_duplicate_namespaces(source_path)
    tree = ast.parse(source_path.read_text(encoding='utf-8'))
    selected = [node for node in tree.body
                if isinstance(node, ast.FunctionDef) and node.name in {
                    '_collection_deduplicate_static_parts', 'write_static_outputs'}]
    module = ast.Module(body=selected, type_ignores=[])
    env = {
        'os': os,
        're': re,
        'STATIC_HEADER': '/* static */\n',
        '_STATIC_PART_RE': re.compile(r'_(\d{4})\.c$'),
        'static_part_paths': lambda _path: [],
    }

    def write_if_changed(path, text):
        Path(path).write_text(text, encoding='utf-8', newline='\n')
        return True

    env['_write_if_changed'] = write_if_changed
    exec(compile(module, str(source_path), 'exec'), env)
    return env['write_static_outputs']


def part(namespace, source, entry, crc, ranges):
    symbol = f'{namespace}_func_{entry:08X}'
    return {
        'namespace': namespace,
        'src': source,
        'func_addrs': {entry},
        'symbols': {entry: symbol},
        'variants': [{'addr': entry, 'symbol': symbol, 'crc': crc,
                      'ranges': ranges}],
    }


class StaticDuplicateNamespaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source = Path(self.temp.name) / 'compile_overlays.py'
        self.source.write_bytes(REFERENCE.read_bytes())

    def test_patch_is_idempotent_and_refuses_writer_drift_before_write(self):
        patch_static_duplicate_namespaces(self.source)
        first = self.source.read_bytes()
        self.assertIn(b'COLLECTION_STATIC_DUPLICATE_NAMESPACES_V1', first)
        patch_static_duplicate_namespaces(self.source)
        self.assertEqual(self.source.read_bytes(), first)

        drifted = Path(self.temp.name) / 'drifted.py'
        text = first.decode('utf-8').replace(
            '    stale = static_part_paths(static_out)',
            '    stale = static_part_paths(static_out)  # drift', 1)
        drifted.write_text(text, encoding='utf-8')
        before = drifted.read_bytes()
        with self.assertRaisesRegex(ValueError, 'source drifted'):
            patch_static_duplicate_namespaces(drifted)
        self.assertEqual(drifted.read_bytes(), before)

    def test_patched_writer_requires_unique_unchanged_helper(self):
        patch_static_duplicate_namespaces(self.source)
        applied=self.source.read_text(encoding='utf-8')
        start=applied.index('def _collection_deduplicate_static_parts(parts):')
        end=applied.index('def write_static_outputs(',start)
        helper=applied[start:end]
        for name,altered in (
            ('missing',applied[:start]+applied[end:]),
            ('body-drift',applied.replace('    unique=[]','    unique = []',1)),
            ('duplicate',applied[:start]+helper+applied[start:])):
            path=Path(self.temp.name)/(name+'.py')
            path.write_text(altered,encoding='utf-8')
            before=path.read_bytes()
            with self.subTest(name=name):
                with self.assertRaisesRegex(ValueError,'dedup helper|helper body'):
                    patch_static_duplicate_namespaces(path)
                self.assertEqual(path.read_bytes(),before)

    def test_exact_duplicate_retains_variants_in_split_and_single_file_modes(self):
        writer = load_writer(self.source)
        ns_a = 'ov_00058000_7C8FAF6E_DC177664'
        ns_b = 'ov_00059000_12345678_ABCDEF01'
        body_a = f'void {ns_a}_func_80001000(CPUState *cpu) {{ (void)cpu; }}\n'
        body_b = f'void {ns_b}_func_80002000(CPUState *cpu) {{ (void)cpu; }}\n'
        first = part(ns_a, body_a, 0x80001000, 0x11111111,
                     [(0x80001000, 8)])
        duplicate = part(ns_a, body_a, 0x80001000, 0x22222222,
                         [(0x80001000, 12)])
        other = part(ns_b, body_b, 0x80002000, 0x33333333,
                     [(0x80002000, 4)])
        variants = [first['variants'][0], duplicate['variants'][0],
                    other['variants'][0]]
        dispatcher = '/* all three exact guard variants remain dispatched */\n'

        split_out = Path(self.temp.name) / 'split' / 'overlays_static.c'
        split_out.parent.mkdir()
        written = writer(str(split_out), [first, duplicate, other], variants,
                         dispatcher, single_file=False)
        parts = sorted(split_out.parent.glob('overlays_static_*.c'))
        self.assertEqual(len(parts), 2)
        self.assertEqual(written, [str(split_out), *(str(p) for p in parts)])
        self.assertEqual(parts[0].read_text(encoding='utf-8').count(body_a), 1)
        self.assertEqual(parts[1].read_text(encoding='utf-8').count(body_b), 1)
        self.assertIn(dispatcher, split_out.read_text(encoding='utf-8'))
        self.assertEqual(len(variants), 3)

        single_out = Path(self.temp.name) / 'single' / 'overlays_static.c'
        single_out.parent.mkdir()
        writer(str(single_out), [first, duplicate, other], variants,
               dispatcher, single_file=True)
        single = single_out.read_text(encoding='utf-8')
        self.assertEqual(single.count(body_a), 1)
        self.assertEqual(single.count(body_b), 1)
        self.assertIn(dispatcher, single)

    def test_conflicting_same_namespace_fails_before_any_output(self):
        writer = load_writer(self.source)
        namespace = 'ov_00058000_7C8FAF6E_DC177664'
        first = part(namespace, f'void {namespace}_func_80001000(CPUState *c) {{}}\n',
                     0x80001000, 1, [(0x80001000, 4)])
        conflict = part(namespace, f'void {namespace}_func_80001000(CPUState *c) {{ c->pc++; }}\n',
                        0x80001000, 1, [(0x80001000, 4)])
        for single_file in (False, True):
            out_dir = Path(self.temp.name) / ('single-conflict' if single_file
                                              else 'split-conflict')
            out_dir.mkdir()
            out = out_dir / 'overlays_static.c'
            with self.subTest(single_file=single_file):
                with self.assertRaisesRegex(ValueError, 'Conflicting static bodies'):
                    writer(str(out), [first, conflict], first['variants'], '',
                           single_file=single_file)
                self.assertEqual(list(out_dir.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
