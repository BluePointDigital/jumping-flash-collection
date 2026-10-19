"""Maintain collection fixes in private emitter source trees."""
from pathlib import Path


def patch_break(framework):
    path=Path(framework)/'recompiler/src/code_generator.cpp'
    text=path.read_text(encoding='utf-8')
    old='''                    code = fmt::format("/* break({}) — trap, no-op in recompiler */", break_code);'''
    new='''                    // Keep static/overlay code consistent with the strict
                    // translator and dirty-RAM interpreter. psx_break is a
                    // runtime-fatal diagnostic today; this does not emulate
                    // architectural CP0 exception delivery.
                    code = fmt::format(
                        "psx_break(cpu, 0x{:05X}u, 0x{:08X}u); return;",
                        break_code, runtime_pc(addr));'''
    if text.count(new)==1 and old not in text:
        return
    if text.count(old)!=1 or new in text:
        raise ValueError('Overlay BREAK emitter anchor changed')
    path.write_text(text.replace(old,new,1),encoding='utf-8')


def patch(framework):
    # Run independently of the older inclusive-switch marker, so already
    # prepared private trees also receive the verified trap correction.
    patch_break(framework)
    path=Path(framework)/'recompiler/src/function_analysis.cpp'
    text=path.read_text(encoding='utf-8')
    if '// COLLECTION_INCLUSIVE_EMITTER_V1' in text:return
    anchor='bool resolve_exact_bounded_jump_table(\n'
    begin=text.index(anchor)
    body=text.index('    table = {};',begin)
    if text.count(anchor)!=1:raise ValueError('Inclusive emitter resolver anchor changed')
    text=text[:body]+('    if (collection_inclusive_switch(exe, entry, hard_cap, jr_pc, jr_rs,\n'
        '            table, runtime_to_image, producer_lo, producer_hi)) return true;\n')+text[body:]
    helper=Path(__file__).with_name('inclusive_switch.cpp.inc').read_text(encoding='utf-8')
    path.write_text(text[:begin]+helper+'\n'+text[begin:],encoding='utf-8')
