"""Preserve audit reports while avoiding repeated classification of targets."""
from pathlib import Path
from collections import Counter
import re
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from patch_compiler import patch_generated_audit_counts

BASE = r'''
def audit_generated_c(src: str, load_addr: int, size: int,
                      crc32: int, toml_doc: dict) -> dict:
    defs = {int(x, 16) for x in re.findall(
        r'^void func_([0-9A-Fa-f]{8})\(CPUState\* cpu\);?$', src, re.MULTILINE)}
    decls = {int(x, 16) for x in re.findall(
        r'^void func_([0-9A-Fa-f]{8})\(CPUState\* cpu\);$', src, re.MULTILINE)}
    direct_calls = [int(x, 16) for x in re.findall(
        r'\bfunc_([0-9A-Fa-f]{8})\(cpu\)', src)]
    literal_cba = [int(x, 16) for x in re.findall(
        r'\bcall_by_address\(cpu,\s*0x([0-9A-Fa-f]{8})u?\)', src)]
    unsupported_todo_addrs = {int(x, 16) for x in re.findall(
        r'TODO:[^\n]*?0x([0-9A-Fa-f]{8}):', src)}
    game_text = _game_text_range(toml_doc)
    ov_lo = load_addr & 0x1FFFFFFF
    ov_hi = ov_lo + size
    def in_overlay(addr: int) -> bool:
        phys = addr & 0x1FFFFFFF
        return ov_lo <= phys < ov_hi
    unknown_bad = set()
    missing_direct = set()
    direct_outside = set()
    for addr in direct_calls:
        if not in_overlay(addr):
            direct_outside.add(addr)
            unknown_bad.add(addr)
        elif addr not in defs:
            missing_direct.add(addr)
            unknown_bad.add(addr)
    cba_classes = Counter()
    for addr in literal_cba:
        cls = _classify_target(addr, load_addr, size, game_text)
        cba_classes[cls] += 1
        if cls == 'UNKNOWN_BAD':
            unknown_bad.add(addr)
    decl_without_def = {a for a in decls if in_overlay(a) and a not in defs}
    called_decl_without_def = decl_without_def & set(direct_calls)
    if called_decl_without_def:
        unknown_bad.update(called_decl_without_def)
    report = {
        'defs': defs, 'decls': decls, 'direct_calls': direct_calls,
        'literal_cba': literal_cba,
        'direct_inside': sum(1 for a in direct_calls if in_overlay(a)),
        'external_cba': sum(1 for a in literal_cba if not in_overlay(a)),
        'bios_calls': cba_classes.get('BIOS', 0),
        'syscall_uses': len(re.findall(r'\bpsx_syscall\s*\(', src)),
        'unknown_dispatch_uses': len(re.findall(r'\bpsx_unknown_dispatch\s*\(', src)),
        'unsupported_todo_addrs': unsupported_todo_addrs,
        'unknown_bad': unknown_bad, 'direct_outside': direct_outside,
        'missing_direct': missing_direct, 'decl_without_def': decl_without_def,
        'called_decl_without_def': called_decl_without_def, 'cba_classes': cba_classes,
    }
    return report

def print_generated_c_audit():
    pass
'''


class AuditCountTests(unittest.TestCase):
    def test_reports_equal_and_transform_fails_closed(self):
        calls = []

        def classify(address, load, size, game):
            calls.append(address)
            physical = address & 0x1FFFFFFF
            if load <= physical < load + size: return 'INSIDE_OVERLAY'
            if game[0] <= physical < game[1]: return 'MAIN_EXE'
            if 0x1FC00000 <= physical < 0x1FC80000: return 'BIOS'
            return 'UNKNOWN_BAD'

        def load(source):
            ns = {'re': re, 'Counter': Counter, '_classify_target': classify,
                  '_game_text_range': lambda _: (0x20000, 0x20100)}
            exec(compile(source, 'audit-fixture', 'exec'), ns)
            return ns['audit_generated_c']

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'compiler.py'
            path.write_text(BASE, encoding='utf-8')
            patch_generated_audit_counts(path)
            optimized = path.read_text(encoding='utf-8')
            patch_generated_audit_counts(path)
            self.assertEqual(path.read_text(encoding='utf-8'), optimized)
            changed = BASE.replace("cba_classes[cls] += 1", "cba_classes[cls] += 2")
            path.write_text(changed, encoding='utf-8')
            with self.assertRaises(ValueError): patch_generated_audit_counts(path)
            self.assertEqual(path.read_text(encoding='utf-8'), changed)
        legacy, new = load(BASE), load(optimized)
        generated = '''void func_80010000(CPUState* cpu)
void func_80010004(CPUState* cpu);
void func_80010008(CPUState* cpu); 
'''
        generated += '\n'.join(f'func_{a}(cpu);' for a in
            ('80010000', '80010004', '80010008', '80010100', '80020000', 'BFC00000')) * 17
        generated += '\n'.join(f'call_by_address(cpu, 0x{a}u);' for a in
            ('80010000', 'A0010000', '80010100', '80020000', 'BFC00000', '90000000')) * 23
        generated += '\npsx_syscall (cpu); psx_unknown_dispatch(cpu); /* TODO: at 0x80010008: bad */'
        old_report = legacy(generated, 0x10000, 0x100, 0, {})
        old_calls = len(calls); calls.clear()
        self.assertEqual(new(generated, 0x10000, 0x100, 0, {}), old_report)
        self.assertEqual(len(calls), len(set(old_report['literal_cba'])))
        self.assertLess(len(calls), old_calls)
        self.assertEqual(new('', 0x10000, 0x100, 0, {}), legacy('', 0x10000, 0x100, 0, {}))


if __name__ == '__main__':
    unittest.main()
