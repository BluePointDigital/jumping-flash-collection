"""Build exact, immutable JF1 SDK slices without inheriting mutable CPS owners."""
import base64
from collections import deque
import hashlib
from pathlib import Path
import struct
import tomllib
from types import SimpleNamespace

from game_installed_aot import PALETTE_LAYOUTS, LAYOUTS_SHA
from static_dispatches import _extractor


TAIL_SIGNATURE = struct.pack('<8I', 0x3252b3ff, 0x1494ffe7, 0x2484001c,
                             0x4840f800, 0x8fbf0000, 0x27bd0004, 0x03e00008, 0)


def instruction_closure(co, body, load, entry, opaque, budget=4097):
    """Follow direct calls as well as branches; keep indirect calls explicit."""
    if load % 4 or len(body) % 4 or entry % 4 or not load <= entry < load + len(body):
        raise ValueError('Source slice has invalid image/entry bounds')
    for start, size in opaque:
        if start % 4 or size <= 0 or size % 4 or not load <= start < start + size <= load + len(body):
            raise ValueError('Source slice opaque range outside image')
    def inside(pc):
        return load <= pc < load + len(body) and not any(a <= pc < a + n for a, n in opaque)
    def word(pc):
        if pc % 4 or not inside(pc):
            raise ValueError(f'Source slice instruction outside immutable image: {pc:08X}')
        value = struct.unpack_from('<I', body, pc - load)[0]
        if not co._is_valid_mips_word(value):
            raise ValueError(f'Source slice has invalid instruction: {pc:08X}')
        return value
    pending = deque([entry]); seen = set(); edges = []; calls = []; external = set()
    def visit(pc):
        value = word(pc)
        seen.add(pc)
        if len(seen) > budget:
            raise ValueError('Source slice exceeds instruction budget')
        return value
    while pending:
        pc = pending.popleft()
        if pc in seen:
            continue
        if not inside(pc):
            external.add(pc)
            continue
        value = visit(pc)
        kind, target = co._classify_cf(pc, value)
        if kind == 'normal':
            pending.append(pc + 4)
            continue
        if kind == 'branch_never_likely':
            pending.append(pc + 8)
            continue
        if co._is_control_flow(visit(pc + 4)):
            raise ValueError('Source slice has a control transfer in a delay slot')
        if kind in ('branch', 'j'):
            edges.append((pc, target)); pending.append(target)
            if kind == 'branch':
                pending.append(pc + 8)
        elif kind == 'branch_never':
            pending.append(pc + 8)
        elif kind in ('jal', 'jalr'):
            calls.append((pc, kind, target)); pending.append(pc + 8)
            if kind == 'jal':
                pending.append(target)
        elif kind != 'jr_ra':
            raise ValueError(f'Source slice has an unresolved tail transfer: {pc:08X} {kind}')
    spans = []
    for pc in sorted(seen):
        if spans and spans[-1][0] + spans[-1][1] == pc:
            spans[-1][1] += 4
        else:
            spans.append([pc, 4])
    entries = {entry, *(a for a, n in spans)}
    entries.update(target for pc, target in edges if target in seen)
    entries.update(target for pc, kind, target in calls if kind == 'jal' and target in seen)
    entries.update(pc + 8 for pc, kind, target in calls if pc + 8 in seen)
    return dict(ranges=spans, entry_points=sorted(entries), source_instructions=len(seen),
                external_boundaries=sorted(external),
                indirect_call_sites=[pc for pc, kind, target in calls if kind == 'jalr'])


def source_slice_plans(game, records, framework, only_images=(), repair_entries=()):
    # Entry repair already selects its own bounded guards; never expand its scope.
    if game != 'jf1' or repair_entries:
        return []
    co = _extractor(str(Path(framework).resolve()))['co']
    plans = []
    for record in records:
        name = record['producer_name']
        if record.get('producer') != 'verified_psx_exe_lz1' or name not in PALETTE_LAYOUTS['jf1']:
            continue
        if only_images and name not in only_images:
            continue
        layout = PALETTE_LAYOUTS['jf1'][name]
        body = base64.b64decode(record['bytes_b64'], validate=True)
        load = int(record['load_addr'], 16)
        if (load != int(layout['load_addr'], 16) or len(body) != record['size'] or
                hashlib.sha256(body).hexdigest() != layout['body_sha256']):
            raise ValueError('SDK slice requires the exact verified JF1 source image')
        template, size = int(layout['template'], 16), layout['size']
        offset = template - load
        if (offset < 0 or offset + size > len(body) or
                hashlib.sha256(body[offset:offset + size]).hexdigest() != layout['template_sha256']):
            raise ValueError('SDK slice mutable template fingerprint changed')
        positions = [i for i in range(0, len(body) - len(TAIL_SIGNATURE) + 1, 4)
                     if body[i:i + len(TAIL_SIGNATURE)] == TAIL_SIGNATURE]
        if len(positions) != 1:
            raise ValueError('SDK slice requires one exact tail signature')
        entry = load + positions[0]
        if template != entry + 0x1e64:
            raise ValueError('SDK slice template/tail layout changed')
        graph = instruction_closure(co, body, load, entry, [(template, size)])
        plans.append(dict(image=name, source_sha256=layout['body_sha256'],
                          layout_sha256=LAYOUTS_SHA['jf1'], tail_entry=entry,
                          opaque_template=[template, size], **graph))
    return plans


def compile_source_slices(plans, records, framework, recompiler, compiler, output, env, audit_only=False):
    """Use the guarded publisher once per exact source slice, then audit exports."""
    if not plans:
        return []
    framework, output = Path(framework), Path(output)
    co = _extractor(str(framework.resolve()))['co']
    include = framework / 'runtime/include'; config = framework.parent / 'game.toml'
    co.load_dispatch_preamble(str(include))
    co.verify_recompiler_matches_tag(str(recompiler), co.codegen_hash(str(include)))
    tag = co.cache_tag(str(include), str(recompiler), str(config))
    document = tomllib.loads(config.read_text(encoding='utf-8'))
    cache = output / 'cache' / document['game']['id'] / 'gcc' / co.cache_arch_abi() / tag
    cache.mkdir(parents=True, exist_ok=True)
    args = SimpleNamespace(recompiler=str(recompiler), game_toml=str(config),
                           project_root=str(framework.parent), runtime_include=str(include),
                           cps=False, flavor=0, force=False, compiler='gcc', gcc=str(compiler), tcc='tcc')
    sources = {record['producer_name']: record for record in records}
    results = []; compiled = {}
    for plan in plans:
        record = sources[plan['image']]
        body = base64.b64decode(record['bytes_b64'], validate=True)
        load = int(record['load_addr'], 16)
        if hashlib.sha256(body).hexdigest() != plan['source_sha256']:
            raise ValueError('SDK slice source changed after planning')
        spans = plan['ranges']; entries = plan['entry_points']
        lo = min(a for a, n in spans); hi = max(a + n for a, n in spans)
        data = body[lo - load:hi - load]
        identity = (data, tuple((a, n) for a, n in spans), tuple(entries))
        if identity in compiled:
            results.append(dict(compiled[identity], image=plan['image'], status='reused-exact-source-slice'))
            continue
        abi = co.overlay_abi_tag(str(include), 0)
        if audit_only:
            ids = None; status = 'audited-existing'
            for manifest in sorted(cache.glob(f'{lo & 0x1fffffff:08X}_*.ranges')):
                candidate = co.load_shard_func_ids(str(manifest.with_suffix('.dll')), abi)
                if (candidate and set(entries) <= {entry for entry, crc, ranges in candidate} and
                    all(any(a <= start < start + size <= a + n for a, n in spans)
                        for entry, crc, ranges in candidate for start, size in ranges) and
                    co.current_variant_func_ids(candidate, body, load, len(body)) == candidate):
                    ids = candidate
                    break
        else:
            ids, status = co.compile_fragment_batch(entries, data, lo, len(data), lo & 0x1fffffff,
                str(cache), args, env, document, producer_ranges=[(a, a + n) for a, n in spans], guard_bytes=0)
        if not ids or not set(entries) <= {entry for entry, crc, ranges in ids}:
            raise ValueError(f'SDK source slice failed to publish all entries: {plan["image"]}: {status}')
        if not all(any(a <= start < start + size <= a + n for a, n in spans)
                   for entry, crc, ranges in ids for start, size in ranges):
            raise ValueError('SDK slice guard includes unproven or mutable source bytes')
        if co.current_variant_func_ids(ids, body, load, len(body)) != ids:
            raise ValueError('SDK slice guards do not match its source image')
        key = co.fragment_shard_key(ids)
        dll = cache / f'{lo & 0x1fffffff:08X}_{key:08X}.dll'
        if co.load_shard_func_ids(str(dll), abi) != ids:
            raise ValueError('SDK slice actual native exports/ABI do not match its manifest')
        def sha(path):
            return hashlib.sha256(path.read_bytes()).hexdigest()
        result = dict(image=plan['image'], status=status, native_functions=len(ids),
                      dll=dll.relative_to(output / 'cache').as_posix(), dll_sha256=sha(dll),
                      manifest_sha256=sha(dll.with_suffix('.ranges')), semantic_qualification=False)
        compiled[identity] = result; results.append(result)
        print(f'{plan["image"]}: SDK source slice {status}, {len(ids)} native entries', flush=True)
    return results
