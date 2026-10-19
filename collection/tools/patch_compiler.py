"""Maintain collection compiler hooks, bounded recovery and cache housekeeping."""
from pathlib import Path

def patch(path):
    path=Path(path);text=path.read_text(encoding='utf-8')
    old="r'^void func_([0-9A-Fa-f]{8})\\(CPUState\\* cpu\\)$'"
    new="r'^void func_([0-9A-Fa-f]{8})\\(CPUState\\* cpu\\);?$'"
    text=text.replace(old,new)
    text=text.replace("(void)psx_mod_function_entry(cpu,0x{address:08X}u);","if(psx_mod_function_entry(cpu,0x{address:08X}u))return;")
    anchor="os.path.isfile(os.path.join(d, 'gcc'))):"
    text=text.replace(anchor,"os.path.isfile(os.path.join(d, 'gcc')) or\n                  os.path.isfile(os.path.join(d, 'clang.exe'))):")
    # Direct calls within a native DLL bypass the runtime's dispatcher. Forward
    # the existing guarded title callbacks at the same pre-instruction sites.
    if '# COLLECTION_NATIVE_CAMERA_HOOKS' not in text:
        anchor='    # 4. Add dllexport to every in-overlay func_XXXXXXXX definition.'
        addition='''    # COLLECTION_NATIVE_CAMERA_HOOKS
    camera_sites = {0xe1528,0xe7f1c,0xe2b4c,0xe2550,0xe2b90,0xf3a44,
                    0xa2778,0xa441c,0xa24b4,0x99c0c}
    def add_camera_hook(match):
        address=int(match.group(1),16)
        if (address & 0x1fffffff) not in camera_sites:return match.group(0)
        return match.group(0) + f'\\n    if(psx_mod_function_entry(cpu,0x{address:08X}u))return;'
    src = re.sub(r'^block_([0-9A-Fa-f]{8}):$',add_camera_hook,src,flags=re.MULTILINE)

'''
        if text.count(anchor)!=1:raise ValueError('Native compiler hook anchor changed')
        text=text.replace(anchor,addition+anchor)
    # JF1 sites are generated from all verified regional world/boss layouts.
    from pathlib import Path as _Path
    import re
    profiles=(_Path(__file__).resolve().parents[1]/'runtime/jf1_profiles.h').read_text()
    sites=set()
    for row in re.findall(r'\{"JM[^\n]+',profiles):
        sites.update(int(v,16)&0x1fffffff for v in re.findall(r'0x([0-9a-f]{8})u',row)[:4])
    # Keep the site list before lazily inserted helpers on every application.
    anchor=('    existing_instruction_addresses = None'
            if '# COLLECTION_CONFIGURED_SITE_DEDUP_V2' in text
            else '    def add_camera_hook(match):')
    text=re.sub(r'    # COLLECTION_JF1_NATIVE_SITES\n    camera_sites.update\(\{[^\n]+\}\)\n','',text)
    text=text.replace(anchor,'    # COLLECTION_JF1_NATIVE_SITES\n    camera_sites.update({'+','.join(hex(s) for s in sorted(sites))+'})\n'+anchor)
    if '# COLLECTION_NATIVE_ENTRY_HOOKS' not in text:
        anchor='    # 4. Add dllexport'
        entry='''    # COLLECTION_NATIVE_ENTRY_HOOKS
    # Callable entries need not have a block label (CPS and ordinary emitters).
    def add_entry_hook(match):
        address=int(match.group(2),16)
        if (address & 0x1fffffff) not in camera_sites or f'block_{address:08X}:' in src:return match.group(0)
        return match.group(0)+f'\\n    if(psx_mod_function_entry(cpu,0x{address:08X}u))return;'
    src=re.sub(r'^(void func_([0-9A-Fa-f]{8})\\(CPUState\\* cpu\\)\\s*\\n\\{)',add_entry_hook,src,flags=re.MULTILINE)

'''
        text=text.replace(anchor,entry+anchor,1)
    # CPS/interpreter fallback fragments use the static patching path even
    # when linked into a DLL. Install the same hooks there as in full overlays.
    start=text.index('    # COLLECTION_NATIVE_CAMERA_HOOKS\n')
    end=text.index('    # 4. Add dllexport',start)
    hooks=text[start:end]
    anchor='    # 4. Collect in-overlay function definition addresses'
    if '# COLLECTION_STATIC_CAMERA_HOOKS' in text:
        begin=text.index('    # COLLECTION_STATIC_CAMERA_HOOKS\n');end=text.index(anchor,begin)
        text=text[:begin]+text[end:]
    text=text.replace(anchor,'    # COLLECTION_STATIC_CAMERA_HOOKS\n'+hooks+anchor)
    path.write_text(text,encoding='utf-8')
    patch_budget(path)
    patch_hosted_budget(path)
    patch_debris_scan(path)
    patch_capacity_profile(path)
    patch_stack_allocations(path)
    patch_exact_aliases(path)
    patch_callback_budget(path)
    patch_inclusive_switch(path)
    patch_current_variant_identity_coverage(path)
    patch_current_variant_guard_memo(path)
    patch_alias_at_callable_boundary(path)
    patch_coherent_coverage(path)
    patch_instruction_hook_dedup(path)
    patch_combined_hook_scan(path)
    patch_monotonic_publisher(path)
    patch_generated_audit_counts(path)
    patch_hosted_identity_diagnostics(path)
    patch_static_duplicate_namespaces(path)


def patch_static_duplicate_namespaces(path):
    """Emit identical static namespace bodies once without losing variants."""
    import hashlib
    path=Path(path);text=path.read_text(encoding='utf-8')
    start=text.find('def write_static_outputs(')
    end=text.find('\n\ndef main():',start)
    if start<0 or end<0:
        raise ValueError('Static output writer anchor changed')
    writer=text[start:end]
    digest=lambda value:hashlib.sha256((value+'\n').encode('utf-8')).hexdigest()
    current=digest(writer)
    helper='''def _collection_deduplicate_static_parts(parts):
    """Keep first exact namespace/body, preserving every dispatcher variant.

    The dispatcher still receives the complete variants list from the caller.
    This only prevents two translation units from defining the same strong C
    symbols. A namespace collision with different C or symbol ownership is a
    hard error; choosing one would silently discard native behavior.
    """
    unique=[]
    seen={}
    for part in parts:
        namespace=part.get('namespace')
        source=part.get('src')
        if not isinstance(namespace,str) or not namespace or not isinstance(source,str):
            raise ValueError('Static part lacks a namespace or C source')
        signature=(source,tuple(sorted(part.get('func_addrs',()))),
                   tuple(sorted(part.get('symbols',{}).items())))
        previous=seen.get(namespace)
        if previous is None:
            seen[namespace]=signature
            unique.append(part)
        elif previous!=signature:
            raise ValueError(f'Conflicting static bodies for namespace {namespace}')
    return unique


'''
    helper_def='def _collection_deduplicate_static_parts(parts):'
    if current=='d9e524030dbb4ba383f6bac19e996aeee2e382f739415e61b1c5d3a49c007537':
        if text.count(helper_def)!=1:
            raise ValueError('Patched static writer has missing or duplicate dedup helper')
        helper_start=text.index(helper_def)
        if helper_start>start or text[helper_start:start]!=helper:
            raise ValueError('Static dedup helper body drifted; refusing idempotent acceptance')
        return
    if current!='8b4864a959546b597aedde37a22dab546ae0aa507fb0a42442d1d80ba2f951dc':
        raise ValueError('Static output writer source drifted; refusing namespace dedup patch')

    anchor='    stale = static_part_paths(static_out)'
    if writer.count(anchor)!=1:
        raise ValueError('Static output writer preflight anchor changed')
    updated=writer.replace(anchor,
        '    # COLLECTION_STATIC_DUPLICATE_NAMESPACES_V1\n'
        '    parts = _collection_deduplicate_static_parts(parts)\n'+anchor,1)
    if text.count('def _collection_deduplicate_static_parts('):
        raise ValueError('Partial static namespace patch found; refusing')
    patched=text[:start]+helper+updated+text[end:]
    new_start=patched.index('def write_static_outputs(')
    new_end=patched.index('\n\ndef main():',new_start)
    if digest(patched[new_start:new_end])!='d9e524030dbb4ba383f6bac19e996aeee2e382f739415e61b1c5d3a49c007537':
        raise ValueError('Static namespace transform produced unexpected writer source')
    path.write_text(patched,encoding='utf-8')


def patch_generated_audit_counts(path):
    """Audit each distinct target once while preserving call multiplicity."""
    path=Path(path);text=path.read_text(encoding='utf-8')
    begin=text.index('def audit_generated_c(')
    end=text.index('\n\ndef print_generated_c_audit(',begin)
    body=text[begin:end]
    if '# COLLECTION_AUDIT_COUNTS_V1' in body:return
    replacements=[
        (r'''    defs = {int(x, 16) for x in re.findall(
        r'^void func_([0-9A-Fa-f]{8})\(CPUState\* cpu\);?$', src, re.MULTILINE)}
    decls = {int(x, 16) for x in re.findall(
        r'^void func_([0-9A-Fa-f]{8})\(CPUState\* cpu\);$', src, re.MULTILINE)}''',
         r'''    # COLLECTION_AUDIT_COUNTS_V1
    signatures = re.findall(
        r'^void func_([0-9A-Fa-f]{8})\(CPUState\* cpu\)(;?)$', src, re.MULTILINE)
    defs = {int(address, 16) for address, _ in signatures}
    decls = {int(address, 16) for address, suffix in signatures if suffix}'''),
        ('''    for addr in direct_calls:
        if not in_overlay(addr):''',
         '''    direct_counts = Counter(direct_calls)
    literal_counts = Counter(literal_cba)
    direct_inside = 0
    for addr, count in direct_counts.items():
        if not in_overlay(addr):'''),
        ('''        elif addr not in defs:
            missing_direct.add(addr)
            unknown_bad.add(addr)''',
         '''        else:
            direct_inside += count
            if addr not in defs:
                missing_direct.add(addr)
                unknown_bad.add(addr)'''),
        ('''    for addr in literal_cba:
        cls = _classify_target(addr, load_addr, size, game_text)
        cba_classes[cls] += 1''',
         '''    for addr, count in literal_counts.items():
        cls = _classify_target(addr, load_addr, size, game_text)
        cba_classes[cls] += count'''),
        ("'direct_inside': sum(1 for a in direct_calls if in_overlay(a)),",
         "'direct_inside': direct_inside,"),
        ("'external_cba': sum(1 for a in literal_cba if not in_overlay(a)),",
         "'external_cba': sum(count for a, count in literal_counts.items() if not in_overlay(a)),"),
    ]
    for old,new in replacements:
        if body.count(old)!=1:raise ValueError('Generated-C audit count anchor changed')
        body=body.replace(old,new,1)
    path.write_text(text[:begin]+body+text[end:],encoding='utf-8')


def patch_monotonic_publisher(path):
    """Allow only a strictly richer, identity-preserving shard replacement."""
    import hashlib
    path=Path(path);text=path.read_text(encoding='utf-8')
    if text.count('def publish_shard_pair(')!=1:
        raise ValueError('Expected one publish_shard_pair definition')
    start=text.index('def publish_shard_pair(')
    end=text.find('\n\ndef ',start)
    if end<0:raise ValueError('publish_shard_pair end anchor changed')
    function=text[start:end]
    digest=lambda value:hashlib.sha256((value+'\n').encode('utf-8')).hexdigest()
    current=digest(function)
    if current=='208772ed85a34be3030c1a22d67457d76b91b2da81f2c09901b1742061c23c91':return
    if current!='839de1dab9b497c32fa9dc2ceec6bcec4ce079858a97ae650ab10bc377c3c9de':
        raise ValueError('publish_shard_pair source drifted; refusing monotonic patch')

    old_doc='''    """Commit a staged pair, optionally preserving a valid concurrent winner.

    Region DLL names are keyed only by whole-region CRC. Two processes can
    compile the same bytes with different discovery evidence; the later,
    poorer writer must not overwrite a richer pair after that richer process
    has used its own result to suppress fragment repair. First valid publisher
    wins, while each process's post-pass re-reads the actual winner and emits
    any exact-demand fragments it still lacks.
    """'''
    new_doc='''    """Commit a staged pair, preserving winners unless safely enriching one.

    Region DLL names are keyed only by whole-region CRC. Two processes can
    compile the same bytes with different discovery evidence; the later,
    poorer writer must not overwrite a richer pair after that richer process
    has used its own result to suppress fragment repair. A strictly richer
    pair may replace a valid winner only when it preserves every normalized
    entry/CRC/range identity and its own pair-ID and exports validate.
    """'''
    old_branch='''            if (preserve_existing and _runtime_valid_shard_pair_locked(
                    dll, ranges, expected_existing_abi)):
                return False'''
    new_branch='''            if (preserve_existing and _runtime_valid_shard_pair_locked(
                    dll, ranges, expected_existing_abi)):
                # Same-image captures can accumulate roots over time. Do not
                # let a poorer concurrent writer replace a richer pair, but
                # allow a proven strict superset to enrich a seeded pair.
                try:
                    with open(ranges, encoding='ascii', newline='') as source:
                        old_manifest = source.read()
                    with open(staged_ranges, encoding='ascii', newline='') as source:
                        new_manifest = source.read()
                    expected_segment = cache_dir_segment(os.path.dirname(dll))
                    old_pair, old_funcs = parse_runtime_shard_manifest(
                        old_manifest, require_pair=True,
                        expected_segment=expected_segment)
                    new_pair, new_funcs = parse_runtime_shard_manifest(
                        new_manifest, require_pair=True,
                        expected_segment=expected_segment)
                    old_ids = {_normalized_func_identity(func)
                               for func in old_funcs}
                    new_ids = {_normalized_func_identity(func)
                               for func in new_funcs}
                    staged_is_valid = (
                        bool(new_ids) and
                        _dll_runtime_exports_match(
                            staged_dll, expected_existing_abi, new_pair,
                            {entry for entry, _crc, _ranges in new_funcs}))
                    monotonic_upgrade = (
                        old_pair is not None and new_pair is not None and
                        bool(old_ids) and old_ids < new_ids and
                        staged_is_valid)
                except (OSError, UnicodeError, TypeError, ValueError):
                    monotonic_upgrade = False
                if not monotonic_upgrade:
                    return False'''
    if function.count(old_doc)!=1 or function.count(old_branch)!=1:
        raise ValueError('publish_shard_pair patch anchors changed')
    updated=function.replace(old_doc,new_doc,1).replace(old_branch,new_branch,1)
    if digest(updated)!='208772ed85a34be3030c1a22d67457d76b91b2da81f2c09901b1742061c23c91':
        raise ValueError('monotonic publisher transform produced unexpected source')
    path.write_text(text[:start]+updated+text[end:],encoding='utf-8')


def patch_instruction_hook_dedup(path):
    """Precompute generated-source dedup lookups once before adding native hooks."""
    path=Path(path);text=path.read_text(encoding='utf-8')
    if '# COLLECTION_CONFIGURED_SITE_DEDUP_V2' in text:return
    if '# COLLECTION_CONFIGURED_SITE_DEDUP_V1' in text:
        legacy_scan="        if re.search(r'\\bpsx_mod_instruction\\s*\\(\\s*cpu,\\s*0x%08x[uU]?\\s*,' % address,src,re.I):return match.group(0)"
        if text.count('# COLLECTION_CONFIGURED_SITE_DEDUP_V1')!=1 or text.count(legacy_scan)!=4:
            raise ValueError('Legacy configured-site scan patch drifted; refusing upgrade')
        text=text.replace(legacy_scan+'\n','',4)
        text=text.replace('# COLLECTION_CONFIGURED_SITE_DEDUP_V1\n','',1)
    precompute=(
        "    existing_instruction_addresses = None\n"
        "    existing_block_literals = None\n"
        "    def has_existing_instruction(address):\n"
        "        nonlocal existing_instruction_addresses\n"
        "        if existing_instruction_addresses is None:\n"
        "            existing_instruction_addresses = {int(m.group(1), 16) for m in "
        "re.finditer(r'\\bpsx_mod_instruction\\s*\\(\\s*cpu,\\s*0x([0-9A-Fa-f]{8})[uU]?\\s*,', src, re.I)}\n"
        "        return address in existing_instruction_addresses\n"
        "    def has_existing_block_literal(address):\n"
        "        nonlocal existing_block_literals\n"
        "        if existing_block_literals is None:\n"
        "            existing_block_literals = set(re.findall(r'block_[0-9A-F]{8}:', src))\n"
        "        return f'block_{address:08X}:' in existing_block_literals\n"
    )
    camera_definition='    def add_camera_hook(match):'
    if text.count(camera_definition)!=2:
        raise ValueError('Expected two native camera hook definitions for overlay and static patchers')
    text=text.replace(camera_definition,precompute+camera_definition)
    for anchor in ('        if (address & 0x1fffffff) not in camera_sites:return match.group(0)',
                   "        if (address & 0x1fffffff) not in camera_sites or f'block_{address:08X}:' in src:return match.group(0)"):
        if text.count(anchor)!=2:raise ValueError('Configured native hook dedup anchor changed')
        replacement=anchor
        if "or f'block_{address:08X}:' in src" in anchor:
            replacement=anchor.replace("f'block_{address:08X}:' in src",
                                       "has_existing_block_literal(address)")
        check='        if has_existing_instruction(address):return match.group(0)'
        text=text.replace(anchor,replacement+'\n'+check)
    path.write_text('# COLLECTION_CONFIGURED_SITE_DEDUP_V2\n'+text,encoding='utf-8')


def patch_combined_hook_scan(path):
    """Apply block-label and callable-entry hooks in one source pass."""
    path=Path(path);text=path.read_text(encoding='utf-8')
    if '# COLLECTION_COMBINED_NATIVE_HOOK_SCAN_V1' in text:return
    block="    src = re.sub(r'^block_([0-9A-Fa-f]{8}):$',add_camera_hook,src,flags=re.MULTILINE)\n"
    entry="    src=re.sub(r'^(void func_([0-9A-Fa-f]{8})\\(CPUState\\* cpu\\)\\s*\\n\\{)',add_entry_hook,src,flags=re.MULTILINE)\n"
    combined='''    # COLLECTION_COMBINED_NATIVE_HOOK_SCAN_V1
    def add_combined_hook(match):
        if match.group(1) is not None:
            return add_camera_hook(match)
        address=int(match.group(2),16)
        if (address & 0x1fffffff) not in camera_sites or has_existing_block_literal(address):return match.group(0)
        if has_existing_instruction(address):return match.group(0)
        return match.group(0)+f'\\n    if(psx_mod_function_entry(cpu,0x{address:08X}u))return;'
    src=re.sub(r'^(?:block_([0-9A-Fa-f]{8}):$|void func_([0-9A-Fa-f]{8})\\(CPUState\\* cpu\\)\\s*\\n\\{)',
               add_combined_hook,src,flags=re.MULTILINE)
'''
    if text.count(block)!=2 or text.count(entry)!=2:
        raise ValueError('Combined hook scan anchors changed')
    text=text.replace(block,'',2).replace(entry,combined,2)
    path.write_text('# COLLECTION_COMBINED_NATIVE_HOOK_SCAN_V1\n'+text,encoding='utf-8')


def patch_coherent_coverage(path):
    """Partial byte matches remain source evidence, never proof of callable coverage."""
    path=Path(path);text=path.read_text(encoding='utf-8')
    if '# COLLECTION_COHERENT_COVERAGE_V1' in text:return
    anchor='def load_region_current_variant_func_ids('
    helper='''# COLLECTION_COHERENT_COVERAGE_V1
def coherent_variant_func_ids(func_ids, data, load_addr, size):
    """Require every directly owned function to match before counting coverage."""
    matching = current_variant_func_ids(func_ids, data, load_addr, size)
    return matching if len(matching) == len(func_ids) else []


'''
    if text.count(anchor)!=1:raise ValueError('Current variant identity helper anchor changed')
    text=text.replace(anchor,helper+anchor,1)
    replacements=[
        ('''        shard_entries, shard_ranges = current_variant_func_id_coverage(
            load_shard_func_ids(dll_path, expected_abi), data, load_addr, size)''',
         '''        shard_entries, shard_ranges = current_variant_func_id_coverage(
            coherent_variant_func_ids(
                load_shard_func_ids(dll_path, expected_abi), data, load_addr, size),
            data, load_addr, size)'''),
        ('''                                         include_supplemental: bool = True
                                         ) -> list:
    """Complete runtime-valid identities matching one captured byte recipe."""
    out = []''',
         '''                                         include_supplemental: bool = True,
                                         coherent_only: bool = False
                                         ) -> list:
    """Byte-validated source identities; optionally require complete modules."""
    out = []
    filter_ids = coherent_variant_func_ids if coherent_only else current_variant_func_ids'''),
        ('''        out.extend(current_variant_func_ids(
            load_shard_func_ids(''',
         '''        out.extend(filter_ids(
            load_shard_func_ids('''),
        ('''                    current_variant_func_id_coverage(
                        load_shard_func_ids(dll_path, expected_abi),
                        data, load_addr, size))''',
         '''                    current_variant_func_id_coverage(
                        coherent_variant_func_ids(
                            load_shard_func_ids(dll_path, expected_abi),
                            data, load_addr, size),
                        data, load_addr, size))'''),
        ('''                        overlay_abi_tag(args.runtime_include, args.flavor)))
            if fully_covered:''',
         '''                        overlay_abi_tag(args.runtime_include, args.flavor),
                        coherent_only=True))
            if fully_covered:'''),
        ('''                include_supplemental=False)
            current_variant_entries, current_variant_ranges''',
         '''                include_supplemental=False, coherent_only=True)
            current_variant_entries, current_variant_ranges'''),
        ('''                job['size'], expected_abi)
            for job in merged_jobs
        ]
        initial_authority_ids''',
         '''                job['size'], expected_abi, coherent_only=True)
            for job in merged_jobs
        ]
        initial_authority_ids'''),
    ]
    for old,new in replacements:
        if text.count(old)!=1:raise ValueError('Coherent coverage anchor changed: '+old[:90])
        text=text.replace(old,new,1)
    path.write_text(text,encoding='utf-8')


def patch_alias_at_callable_boundary(path):
    """A branch to a function's own start must not erase its callable root."""
    path=Path(path);text=path.read_text(encoding='utf-8')
    if '# COLLECTION_ALIAS_CALLABLE_BOUNDARY_V1' in text:return
    old="    for addr, _range_lo, _range_hi in static_alias_ranges:\n        if region(addr):\n            included[addr] = 'DISPATCH_INTERIOR'"
    new="""    # COLLECTION_ALIAS_CALLABLE_BOUNDARY_V1
    for addr, range_lo, _range_hi in static_alias_ranges:
        if (region(addr) and not (
                addr == range_lo and
                _callable_direct_jal_target(data, load_addr, addr))):
            included[addr] = 'DISPATCH_INTERIOR'"""
    if text.count(old)!=1:raise ValueError('Static alias boundary anchor changed')
    path.write_text(text.replace(old,new,1),encoding='utf-8')


def patch_current_variant_guard_memo(path):
    """Aliases share guard bodies; validate each body once per immutable image."""
    path=Path(path);text=path.read_text(encoding='utf-8')
    if '# COLLECTION_CURRENT_GUARD_MEMO_V1' in text:return
    begin=text.index('def current_variant_func_ids(')
    end=text.index('\n\ndef load_region_current_variant_func_ids(',begin)
    helper=text[begin:end]
    loop='    for entry, expected_crc, ranges in func_ids:\n        crc = 0'
    if helper.count('    valid_ids = []')!=1 or helper.count(loop)!=1 or helper.count('    return valid_ids')!=1:
        raise ValueError('Current-byte guard filtering anchors changed')
    helper=helper.replace('    valid_ids = []','    valid_ids = []\n    checked = {}',1)
    helper=helper.replace(loop,'''    for entry, expected_crc, ranges in func_ids:
        key = (expected_crc & 0xFFFFFFFF, tuple(tuple(span) for span in ranges))
        cached = checked.get(key)
        if cached is not None:
            if cached:valid_ids.append((entry, expected_crc, ranges))
            continue
        previous_count = len(valid_ids)
        crc = 0''',1)
    helper=helper.replace('    return valid_ids','        checked[key] = len(valid_ids) > previous_count\n    return valid_ids',1)
    path.write_text(text[:begin]+'# COLLECTION_CURRENT_GUARD_MEMO_V1\n'+helper+text[end:],encoding='utf-8')


def patch_current_variant_identity_coverage(path):
    """Equal entry/CRC values can describe different relocated alias hosts."""
    path=Path(path);text=path.read_text(encoding='utf-8')
    if '# COLLECTION_CURRENT_VARIANT_IDENTITIES_V1' in text:return
    anchor='def load_region_current_variant_coverage('
    gate="            if fully_covered:\n                print(f'  SKIP: all {len(this_set)} function(s) already '"
    if text.count(anchor)!=1 or text.count(gate)!=1:raise ValueError('Current-byte primary coverage anchors changed')
    helper='''# COLLECTION_CURRENT_VARIANT_IDENTITIES_V1
def current_variant_identities_cover(required_ids, current_byte_ids):
    """Require exact ordered guard identities from byte-validated candidates."""
    return bool(required_ids) and {
        _normalized_func_identity(item) for item in required_ids
    } <= {_normalized_func_identity(item) for item in current_byte_ids}


'''
    text=text.replace(anchor,helper+anchor,1)
    text=text.replace(gate,'''            if fully_covered:
                # A relocated host can share entry/CRC with an invalid alias.
                # The cheap global set is only a prefilter, never skip authority.
                fully_covered = current_variant_identities_cover(
                    this_ids, load_region_current_variant_func_ids(
                        seg_cache_dir, phys_addr, data, load_addr, size,
                        overlay_abi_tag(args.runtime_include, args.flavor)))
'''+gate,1)
    path.write_text(text,encoding='utf-8')


def patch_inclusive_switch(path):
    """Insert, upgrade, or verify the bounded inclusive-switch recognizer."""
    import hashlib
    path=Path(path);text=path.read_text(encoding='utf-8')
    v1_marker='# COLLECTION_INCLUSIVE_SWITCH_V1'
    v2_marker='# COLLECTION_INCLUSIVE_SWITCH_V2'
    anchor='def _find_jump_table_targets('
    call=('    inclusive=_collection_inclusive_switch(data,load_addr,size,entry,hard_cap,\n'
          '        jr_pc,jr_rs,producer_range,proof_out)\n'
          '    if inclusive is not None:return inclusive\n')
    if text.count(anchor)!=1:
        raise ValueError('Inclusive switch function anchor changed')
    call_count=text.count(call)
    start=text.find(v1_marker)
    has_v1=start>=0
    has_v2=v2_marker in text
    if text.count(v1_marker)>1 or text.count(v2_marker)>1:
        raise ValueError('Inclusive switch marker duplicated')
    helper_start=text.find(v1_marker)
    helper_end=text.index(anchor)
    existing=text[helper_start:helper_end] if helper_start>=0 else ''
    if has_v2:
        if (call_count!=1 or not has_v1 or text.count('def _collection_inclusive_switch(')!=1 or
            existing!=_COLLECTION_INCLUSIVE_SWITCH_V2):
            raise ValueError('V2 inclusive switch block is partial or drifted')
        return
    if has_v1:
        if (call_count!=1 or text.count('def _collection_inclusive_switch(')!=1 or
            hashlib.sha256(existing.encode('utf-8')).hexdigest()!=
            '1f1c0399cbf966163c3996c3afc3fe63950252bad7321772c0ba4d2362639886'):
            raise ValueError('V1 inclusive switch block is unknown or drifted')
        text=text[:helper_start]+_COLLECTION_INCLUSIVE_SWITCH_V2+text[helper_end:]
    else:
        body='    lo = load_addr\n    hi = load_addr + size\n    if not (entry <= jr_pc < hard_cap and 0 < jr_rs < 31):'
        if (call_count or 'def _collection_inclusive_switch(' in text or
            '# COLLECTION_INCLUSIVE_SWITCH_' in text):
            raise ValueError('Partial inclusive switch insertion')
        if text.count(body)!=1:raise ValueError('Inclusive switch body anchor changed')
        text=text.replace(anchor,_COLLECTION_INCLUSIVE_SWITCH_V2+anchor,1)
        text=text.replace(body,call+body,1)
    path.write_text(text,encoding='utf-8')


_COLLECTION_INCLUSIVE_SWITCH_V2='''# COLLECTION_INCLUSIVE_SWITCH_V1
# COLLECTION_INCLUSIVE_SWITCH_V2
def _collection_inclusive_switch(data, load_addr, size, entry, hard_cap,
                                 jr_pc, jr_rs, producer_range, proof_out):
    # Keep the original 11-word schedule unchanged: SLL occupies BNE's delay.
    start=jr_pc-36
    if not (0<jr_rs<31 and entry<=start and jr_pc+8<=hard_cap):return None
    words=[_word_at(data,load_addr,start+4*i) for i in range(11)]
    if any(word is None for word in words):return None
    bound,compare,reject,scale,upper,lower,add,deref,load_slot,jump,jump_slot=words
    limit=bound>>16&31;index=compare>>16&31;condition=compare>>11&31
    scaled=scale>>11&31;base_reg=upper>>16&31;address=add>>11&31
    if (bound>>26==13 and bound>>21&31==0 and limit and bound&0xffff<4096 and
        index and index!=limit and condition and condition!=index and
        compare==(limit<<21|index<<16|condition<<11|0x2b) and
        reject>>26==5 and reject>>21&31==condition and reject>>16&31==0 and
        scale==(index<<16|scaled<<11|2<<6) and scaled and
        upper>>26==15 and upper>>21&31==0 and base_reg and base_reg!=scaled and
        lower>>26==9 and lower>>21&31==base_reg and lower>>16&31==base_reg and
        address and add in (base_reg<<21|scaled<<16|address<<11|0x21,
                            scaled<<21|base_reg<<16|address<<11|0x21) and
        deref==(0x8c000000|address<<21|jr_rs<<16) and not load_slot and
        jump==(jr_rs<<21|8) and not jump_slot):
        return _collection_inclusive_switch_finish(data,load_addr,size,entry,hard_cap,
            jr_pc,jr_rs,producer_range,proof_out,start,bound,reject,upper,lower)

    # Some SDK builds put a live register move in BNE's delay slot and shift
    # SLL one word later. Only NOP or ADDU rd,rs,$zero is safe here, and it may
    # not overwrite the checked table index before scaling.
    start=jr_pc-40
    if not (0<jr_rs<31 and entry<=start and jr_pc+8<=hard_cap):return None
    words=[_word_at(data,load_addr,start+4*i) for i in range(12)]
    if any(word is None for word in words):return None
    (bound,compare,reject,delay,scale,upper,lower,add,deref,
     load_slot,jump,jump_slot)=words
    limit=bound>>16&31;index=compare>>16&31;condition=compare>>11&31
    scaled=scale>>11&31;base_reg=upper>>16&31;address=add>>11&31
    delay_rd=delay>>11&31;delay_rs=delay>>21&31
    delay_ok=(delay==0 or (delay==(delay_rs<<21|delay_rd<<11|0x21) and delay_rd!=index))
    if not (bound>>26==13 and bound>>21&31==0 and limit and bound&0xffff<4096 and
        index and index!=limit and condition and condition!=index and
        compare==(limit<<21|index<<16|condition<<11|0x2b) and
        reject>>26==5 and reject>>21&31==condition and reject>>16&31==0 and
        delay_ok and scale==(index<<16|scaled<<11|2<<6) and scaled and
        upper>>26==15 and upper>>21&31==0 and base_reg and base_reg!=scaled and
        lower>>26==9 and lower>>21&31==base_reg and lower>>16&31==base_reg and
        address and add in (base_reg<<21|scaled<<16|address<<11|0x21,
                            scaled<<21|base_reg<<16|address<<11|0x21) and
        jr_rs not in (0,31) and deref==(0x8c000000|address<<21|jr_rs<<16) and
        not load_slot and jump==(jr_rs<<21|8) and not jump_slot):
        return None
    return _collection_inclusive_switch_finish(data,load_addr,size,entry,hard_cap,
        jr_pc,jr_rs,producer_range,proof_out,start,bound,reject,upper,lower,
        guard='inclusive_ori_sltu_delay_move')


def _collection_inclusive_switch_finish(data,load_addr,size,entry,hard_cap,
        jr_pc,jr_rs,producer_range,proof_out,start,bound,reject,upper,lower,
        guard='inclusive_ori_sltu'):
    if start>entry and _is_control_flow(_word_at(data,load_addr,start-4)):return set()
    lo,hi=producer_range or (load_addr,load_addr+size)
    low=lower&0xffff;low=low-0x10000 if low&0x8000 else low
    base=(((upper&0xffff)<<16)+low)&0xffffffff;count=(bound&0xffff)+1
    default=_branch_target(start+8,reject)
    if (not entry<=default<hard_cap or start<=default<jr_pc+8 or
        base%4 or not lo<=base<base+4*count<=hi or
        not (base+4*count<=entry or base>=hard_cap)):return set()
    targets={_word_at(data,load_addr,base+4*i) for i in range(count)}
    if any(target is None or target%4 or target<jr_pc+8 or target>=hard_cap or
        not lo<=target<hi or not _is_valid_mips_word(_word_at(data,load_addr,target))
        for target in targets):return set()
    # An inbound edge may not bypass ORI or SLTU. A back edge to SLTU is
    # allowed only when its delay reinstates the bound before comparison.
    for pc in range(entry,hard_cap,4):
        word=_word_at(data,load_addr,pc)
        if word is None:return set()
        kind,target=_classify_cf(pc,word)
        if kind in ('branch','j','jal') and start<target<=jr_pc:
            if kind=='jal' or target!=start+4 or _word_at(data,load_addr,pc+4)!=bound:return set()
    if proof_out is not None:
        proof_out.append(dict(host_entry=entry,jr_pc=jr_pc,table_base=base,count=count,
            targets=sorted(targets),guard=guard))
    return targets


'''

def patch_callback_budget(path):
    """Offline callbacks can prove larger, analyzer-bounded returning bodies."""
    path=Path(path);text=path.read_text(encoding='utf-8')
    if '# COLLECTION_CALLBACK_BUDGET_V1' in text:return
    start=text.index('def plausible_callable_target(')
    end=text.index('\n\ndef _frameless_dispatch_root_proven',start)
    helper=text[start:end]
    old='target: int, producer_hi: int) -> bool:'
    new='target: int, producer_hi: int, *, instruction_budget: int = 2048) -> bool:'
    if helper.count(old)!=1 or helper.count('len(visited) < 2048')!=2:
        raise ValueError('Callback CFG verifier changed')
    helper=helper.replace(old,new).replace('len(visited) < 2048','len(visited) < instruction_budget')
    anchor='    first = _word_at(data, load_addr, target)'
    helper=helper.replace(anchor,"    if not isinstance(instruction_budget,int) or not 1 <= instruction_budget <= 4097:\n        raise ValueError('Callback instruction budget outside bounded image probe')\n"+anchor,1)
    path.write_text(text[:start]+'# COLLECTION_CALLBACK_BUDGET_V1\n'+helper+text[end:],encoding='utf-8')


def patch_exact_aliases(path):
    """A byte-covered CPS interior can still lack a callable native resume."""
    path=Path(path);text=path.read_text(encoding='utf-8')
    if '# COLLECTION_EXACT_STATIC_ALIASES_V1' in text:return
    start=text.index('def select_fragment_orphans(')
    end=text.index('\n\ndef select_batchable_strong_roots',start)
    helper=text[start:end]
    unused='''    def current_region_contains(addr):
        phys = addr & 0x1FFFFFFF
        return any(start <= phys < end for start, end in current_variant_ranges)

'''
    old='(addr in static_interval and not current_region_contains(addr))'
    if helper.count(unused)!=1 or helper.count(old)!=1:raise ValueError('Static alias coverage selector changed')
    helper='# COLLECTION_EXACT_STATIC_ALIASES_V1\n'+helper.replace(unused,'').replace(old,
        '(addr in static_interval and\n              (addr & 0x1FFFFFFF) not in current_variant_entries)')
    text=text[:start]+helper+text[end:]
    text=text.replace('''        # Alias recipes describe entry labels inside a normal-mode host.  They
        # need an isolated body only when the stricter shared analysis leaves
        # the label outside every current code interval; aliases already inside
        # a guarded body remain candidates for the future exact-resume pass.''','''        # Alias recipes describe proven entry labels, not new function roots.
        # A guarded code interval does not prove its CPS entry switch accepts
        # that label. Repair missing exact admissions in isolated fragments.''')
    path.write_text(text,encoding='utf-8')


def patch_stack_allocations(path):
    """JF1's verified SELECT SDK uses ADDI, not ADDIU, for its stack frame."""
    path=Path(path);text=path.read_text(encoding='utf-8')
    if '# COLLECTION_ADDI_FRAME_V1' in text:return
    start=text.index('def _is_addiu_sp_neg(word) -> bool:')
    end=text.index('\n\ndef _is_control_flow',start)
    helper=text[start:end]
    old='return ((word >> 26) & 0x3F) == 0x09 \\'
    new='return ((word >> 26) & 0x3F) in (0x08, 0x09) \\'
    if helper.count(old)!=1:raise ValueError('Stack-allocation classifier anchor changed')
    helper='# COLLECTION_ADDI_FRAME_V1\n# Both signed ADDI and ADDIU allocate real SDK stack frames; retain all boundary gates.\n'+helper.replace(old,new)
    path.write_text(text[:start]+helper+text[end:],encoding='utf-8')


def patch_capacity_profile(path):
    path=Path(path);text=path.read_text(encoding='utf-8')
    if '# COLLECTION_CAPACITY_PROFILE_V4' in text:return
    begin=text.index('def overlay_candidate_cap(runtime_include: str) -> int:')
    end=text.index('\n\ndef codegen_hash(',begin)
    function='''# COLLECTION_CAPACITY_PROFILE_V4
def overlay_candidate_cap(runtime_include: str) -> int:
    """Use the loader's versioned collection budget or the standalone default."""
    hdr=os.path.join(runtime_include,'overlay_api.h')
    with open(hdr) as source:api=source.read()
    match=re.search(r'#define\\s+PSX_OVERLAY_CANDIDATE_CAP\\s+(\\d+)',api)
    if not match:raise SystemExit(f'PSX_OVERLAY_CANDIDATE_CAP not found in {hdr}')
    value=int(match.group(1))
    if value<=0:raise SystemExit(f'invalid PSX_OVERLAY_CANDIDATE_CAP in {hdr}: {value}')
    descriptor=os.path.join(runtime_include,'collection_overlay_limits.json')
    if not os.path.isfile(descriptor):return value
    with open(descriptor) as source:limits=json.load(source)
    abi=re.search(r'#define\\s+PSX_OVERLAY_ABI_VERSION\\s+(\\d+)',api)
    if (limits.get('schema')!=1 or limits.get('profile')!='collection-v1' or
        type(limits.get('candidate_capacity')) is not int or
        limits.get('candidate_capacity') not in (65536,131072,262144,524288) or not abi or
        limits.get('abi_version')!=int(abi.group(1))):
        raise SystemExit(f'Invalid collection loader/publisher resource contract: {descriptor}')
    return limits['candidate_capacity']
'''
    path.write_text(text[:begin]+function+text[end:],encoding='utf-8')


def patch_debris_scan(path):
    """Housekeeping scans once per pair; transaction recovery stays per read."""
    path=Path(path);text=path.read_text(encoding='utf-8')
    if '# COLLECTION_DEBRIS_SCAN_V1' in text:return
    old="def _cleanup_old_pair_debris(dll_path: str) -> None:\n    for path in glob.glob(os.path.abspath(dll_path) + '.pair-txn.*.old-*'):\n        _best_effort_unlink(path)\n"
    new="""# COLLECTION_DEBRIS_SCAN_V1
_collection_debris_scanned = set()

def _cleanup_old_pair_debris(dll_path: str) -> None:
    # The caller holds the pair lock. Old loaded-DLL backups can stay locked
    # until game exit; retry them next invocation instead of rescanning the
    # entire directory for every manifest lookup. Journal recovery below is
    # deliberately not memoized and still runs for every read/publication.
    key=os.path.normcase(os.path.abspath(dll_path))
    if key in _collection_debris_scanned:return
    for path in glob.glob(os.path.abspath(dll_path) + '.pair-txn.*.old-*'):
        _best_effort_unlink(path)
    _collection_debris_scanned.add(key)
"""
    if text.count(old)!=1:raise ValueError('Compiler housekeeping anchor changed')
    path.write_text(text.replace(old,new,1),encoding='utf-8')


def patch_budget(path):
    """Bound speculative recovery; never budget executed or forced entries."""
    path=Path(path);text=path.read_text(encoding='utf-8')
    if '# COLLECTION_SPECULATIVE_BUDGET_V1' in text:return
    def once(old,new):
        nonlocal text
        if text.count(old)!=1:raise ValueError('Compiler budget anchor changed: '+old[:100])
        text=text.replace(old,new,1)
    helper='''# COLLECTION_SPECULATIVE_BUDGET_V1
def collection_static_attempt_allowed(entries, job, budget):
    live=set(job.get('executed', ())) | set(job.get('forced', ())) | set(job.get('static_interval_demands', ()))
    if any(entry in live for entry in entries) or budget[0] is None:return True
    if budget[0]<=0:return False
    budget[0]-=1
    return True

def collection_unsupported_addresses(src):
    return {int(a,16) for a in re.findall(r'TODO:[^\\n]*?0x([0-9A-Fa-f]{8}):',src)}

def collection_retain_fragment_failure(cache_dir, phys_addr, requested, src, load, size, data, unsupported, unknown, *, hosted_identity=None, ranges_path=None, seeds_path=None, provenance=None, recipe=None):
    # Normal play retains reproducible metadata; multi-megabyte C requires explicit opt-in.
    try:
        os.makedirs(cache_dir,exist_ok=True)
        key=binascii.crc32(b''.join(struct.pack('<I',entry) for entry in requested)) & 0xffffffff
        retain=os.environ.get('PSX_RETAIN_FAILED_C')=='1'
        if hosted_identity is not None:
            import time
            record=dict(schema=2,kind='hosted-identity-rejection',requested=requested[:64],
                requested_truncated=len(requested)>64,load_addr=load,size=size,
                input_sha256=hashlib.sha256(data).hexdigest(),generated_c_characters=len(src),
                full_c_retained=retain,ranges_retained=bool(retain and ranges_path),
                seeds_retained=bool(retain and seeds_path),
                provenance=provenance or {},recipe=recipe or {},hosted_identity=hosted_identity)
            stem=os.path.join(cache_dir,f'{phys_addr:08X}_{key:08X}_hosted_IDENTITY_FAILED_{time.time_ns()}')
            for suffix in range(100):
                candidate=stem if suffix==0 else f'{stem}_{suffix:02d}'
                names=[candidate+'.json']
                if retain:names.append(candidate+'.c')
                if retain and ranges_path:names.append(candidate+'.ranges')
                if retain and seeds_path:names.append(candidate+'.seeds')
                if any(os.path.exists(name) for name in names):continue
                try:
                    if retain:
                        with open(candidate+'.c','x',encoding='utf-8') as output:output.write(src)
                        if ranges_path:
                            with open(ranges_path,'rb') as source, open(candidate+'.ranges','xb') as output:
                                output.write(source.read())
                        if seeds_path:
                            with open(seeds_path,'rb') as source, open(candidate+'.seeds','xb') as output:
                                output.write(source.read())
                    with open(candidate+'.json','x',encoding='utf-8') as output:
                        json.dump(record,output,separators=(',',':'))
                    return
                except FileExistsError:
                    continue
            return
        stem=os.path.join(cache_dir,f'{phys_addr:08X}_{key:08X}_fragment_FAILED')
        if retain:
            with open(stem+'.c','w',encoding='utf-8') as output:output.write(src)
        with open(stem+'.json','w',encoding='utf-8') as output:
            json.dump(dict(schema=1,requested=requested,load_addr=load,size=size,
                input_sha256=hashlib.sha256(data).hexdigest(),generated_c_characters=len(src),
                unsupported=sorted(unsupported),unknown_bad=sorted(unknown),full_c_retained=retain),output)
    except OSError:pass

'''
    once('def compile_fragment_batch(requested_entries, data: bytes, load_addr: int,',
         helper+'def compile_fragment_batch(requested_entries, data: bytes, load_addr: int,')
    once('    pending_empty_primary = []\n',
         "    pending_empty_primary = []\n    collection_limit=int(os.environ.get('PSX_STATIC_FRAGMENT_ATTEMPTS','32'))\n"
         "    if collection_limit<0:raise ValueError('PSX_STATIC_FRAGMENT_ATTEMPTS must be nonnegative')\n"
         "    collection_speculative_budget=[collection_limit if collection_limit else None]\n")
    once('            def compile_strong_batch(entries):\n                return compile_fragment_batch(',
         "            def compile_strong_batch(entries):\n                if not collection_static_attempt_allowed(entries,job,collection_speculative_budget):\n"
         "                    return None,'speculative-budget: deferred unexecuted static candidates'\n                return compile_fragment_batch(")
    once('                strong_handled.add(entry)\n                if status.startswith(\'candidate-capacity:\'):',
         "                strong_handled.add(entry)\n                if status.startswith('speculative-budget:'):\n                    stats.add_skip();return\n                if status.startswith('candidate-capacity:'):")
    once('            def strong_batch_failure(entries, status):\n                nonlocal candidate_capacity_exhausted\n',
         "            def strong_batch_failure(entries, status):\n                nonlocal candidate_capacity_exhausted\n"
         "                if status.startswith('speculative-budget:'):\n                    strong_handled.update(entries)\n                    for _entry in entries:stats.add_skip()\n"
         "                    print(f'  deferred {len(entries)} unexecuted static candidates: recovery attempt budget exhausted');return\n")
    once('        with open(full_c) as f:\n            src = patch_generated_c(f.read(), load_addr, size)\n',
         "        with open(full_c) as f:raw_src=f.read()\n"
         "        unsupported=collection_unsupported_addresses(raw_src)\n"
         "        if unsupported:\n            collection_retain_fragment_failure(cache_dir,phys_addr,requested,raw_src,load_addr,size,data,unsupported,[])\n"
         "            return None,f'generated-c-audit: {len(unsupported)} unsupported instructions (early rejection)'\n"
         "        src = patch_generated_c(raw_src, load_addr, size)\n")
    begin=text.index("            # RETAIN the failed fragment's C for triage.")
    end=text.index("            return None, (f'generated-c-audit:",begin)
    text=text[:begin]+"            collection_retain_fragment_failure(cache_dir,phys_addr,requested,src,load_addr,size,data,c_audit['unsupported_todo_addrs'],c_audit['unknown_bad'])\n"+text[end:]
    path.write_text(text,encoding='utf-8')


def patch_hosted_budget(path):
    path=Path(path);text=path.read_text(encoding='utf-8')
    if '# COLLECTION_HOSTED_BUDGET_V1' in text:return
    def once(old,new):
        nonlocal text
        if text.count(old)!=1:raise ValueError('Hosted budget anchor changed: '+old[:100])
        text=text.replace(old,new,1)
    once('            def compile_hosted_batch(specs):\n                return compile_fragment_batch(',
         "            # COLLECTION_HOSTED_BUDGET_V1\n            def compile_hosted_batch(specs):\n"
         "                if not collection_static_attempt_allowed(specs,job,collection_speculative_budget):\n"
         "                    return None,'speculative-budget: deferred unexecuted hosted candidates'\n                return compile_fragment_batch(")
    once('            def hosted_singleton_failure(entry, status):\n                nonlocal candidate_capacity_exhausted\n',
         "            def hosted_singleton_failure(entry, status):\n                nonlocal candidate_capacity_exhausted\n"
         "                if status.startswith('speculative-budget:'):\n                    hosted_rejected.add(_canonical_guest_addr(entry));stats.add_skip();return\n")
    once('            def hosted_batch_failure(batch, status):\n                nonlocal candidate_capacity_exhausted\n',
         "            def hosted_batch_failure(batch, status):\n                nonlocal candidate_capacity_exhausted\n"
         "                if status.startswith('speculative-budget:'):\n                    hosted_rejected.update(_canonical_guest_addr(entry) for entry in batch)\n"
         "                    for _entry in batch:stats.add_skip()\n                    print(f'  deferred {len(batch)} unexecuted hosted candidates: recovery attempt budget exhausted');return\n")
    path.write_text(text,encoding='utf-8')

def patch_hosted_identity_diagnostics(path):
    """Record bounded evidence for hosted identity rejects without changing admission."""
    path=Path(path);text=path.read_text(encoding='utf-8')
    if '# COLLECTION_HOSTED_IDENTITY_DIAGNOSTICS_V1' in text:return
    legacy_signature='def collection_retain_fragment_failure(cache_dir, phys_addr, requested, src, load, size, data, unsupported, unknown):'
    extended_signature='def collection_retain_fragment_failure(cache_dir, phys_addr, requested, src, load, size, data, unsupported, unknown, *, hosted_identity=None, ranges_path=None, seeds_path=None, provenance=None, recipe=None):'
    if legacy_signature in text:
        text=text.replace(legacy_signature,extended_signature,1)
        retain_anchor="        retain=os.environ.get('PSX_RETAIN_FAILED_C')=='1'\n"
        if text.count(retain_anchor)!=1:raise ValueError('Hosted retention helper anchor changed')
        hosted_branch='''        if hosted_identity is not None:
            import time
            record=dict(schema=2,kind='hosted-identity-rejection',requested=requested[:64],
                requested_truncated=len(requested)>64,load_addr=load,size=size,
                input_sha256=hashlib.sha256(data).hexdigest(),generated_c_characters=len(src),
                full_c_retained=retain,ranges_retained=bool(retain and ranges_path),
                seeds_retained=bool(retain and seeds_path),
                provenance=provenance or {},recipe=recipe or {},hosted_identity=hosted_identity)
            stem=os.path.join(cache_dir,f'{phys_addr:08X}_{key:08X}_hosted_IDENTITY_FAILED_{time.time_ns()}')
            for suffix in range(100):
                candidate=stem if suffix==0 else f'{stem}_{suffix:02d}'
                names=[candidate+'.json']
                if retain:names.append(candidate+'.c')
                if retain and ranges_path:names.append(candidate+'.ranges')
                if retain and seeds_path:names.append(candidate+'.seeds')
                if any(os.path.exists(name) for name in names):continue
                try:
                    if retain:
                        with open(candidate+'.c','x',encoding='utf-8') as output:output.write(src)
                        if ranges_path:
                            with open(ranges_path,'rb') as source, open(candidate+'.ranges','xb') as output:
                                output.write(source.read())
                        if seeds_path:
                            with open(seeds_path,'rb') as source, open(candidate+'.seeds','xb') as output:
                                output.write(source.read())
                    with open(candidate+'.json','x',encoding='utf-8') as output:
                        json.dump(record,output,separators=(',',':'))
                    return
                except FileExistsError:
                    continue
            return
'''
        text=text.replace(retain_anchor,retain_anchor+hosted_branch,1)
    elif extended_signature not in text:
        raise ValueError('Hosted failure retention helper unavailable')
    helper='''# COLLECTION_HOSTED_IDENTITY_DIAGNOSTICS_V1
def collection_hosted_identity_mismatches(requested, host_specs, frag_ids, generated_defs):
    """Explain a hosted identity rejection; never participates in admission."""
    def short_identity(identity):
        entry,crc,ranges=identity
        return dict(entry=entry,crc32=crc,ranges=[list(pair) for pair in ranges[:16]],
            ranges_truncated=len(ranges)>16)
    specs={_canonical_guest_addr(entry):spec for entry,spec in host_specs.items()}
    expected_by_entry={};hosts=set();aliases=[]
    for target,spec in sorted(specs.items()):
        host=_canonical_guest_addr(spec['host'])
        expected=_normalized_func_identity(spec['owner_identity'])
        hosts.add(host);expected_by_entry.setdefault(host,expected[1:])
        expected_by_entry[target]=expected[1:]
        aliases.append(dict(target=target,host=host,owner_identity=short_identity(expected)))
    required=sorted(set(specs)|hosts)
    by_entry={}
    for identity in frag_ids:
        normalized=_normalized_func_identity(identity)
        by_entry.setdefault(normalized[0],[]).append(normalized)
    mismatches=[]
    for entry in required:
        matches=by_entry.get(entry,[]);expected=expected_by_entry.get(entry)
        if entry not in generated_defs:reason='entry-not-generated'
        elif not matches:reason='identity-missing'
        elif len(matches)!=1:reason='identity-ambiguous'
        elif expected is None:reason='expected-identity-missing'
        elif matches[0][1]!=expected[0]:reason='crc-mismatch'
        elif matches[0][2]!=expected[1]:reason='range-mismatch'
        else:continue
        mismatches.append(dict(entry=entry,reason=reason,
            expected=short_identity((entry,*expected)) if expected else None,
            actual=[short_identity(identity) for identity in matches[:2]],
            actual_truncated=len(matches)>2))
    return dict(aliases=aliases[:16],aliases_truncated=len(aliases)>16,
        mismatches=mismatches[:8],mismatches_truncated=len(mismatches)>8)

'''
    anchor='def compile_fragment_batch(requested_entries, data: bytes, load_addr: int,'
    if text.count(anchor)!=1:raise ValueError('Hosted identity diagnostics helper anchor changed')
    text=text.replace(anchor,helper+anchor,1)
    old="""        if identity_error:
            return None, f'{identity_error_prefix}: {identity_error}'
"""
    new="""        if identity_error:
            if hosted_specs is not None:
                try:
                    normalized_config_sha256=hashlib.sha256(json.dumps(
                        toml_doc,sort_keys=True,separators=(',',':'),default=str
                    ).encode('utf-8')).hexdigest()
                    with open(seeds_path,'rb') as seed_file:seed_sha256=hashlib.sha256(seed_file.read()).hexdigest()
                    with open(args.game_toml,'rb') as config_file:game_toml_sha256=hashlib.sha256(config_file.read()).hexdigest()
                    identity_detail=collection_hosted_identity_mismatches(
                        requested,hosted_specs,frag_ids,c_audit['defs'])
                    provenance=dict(manifest=manifest_provenance,
                        normalized_config_sha256=normalized_config_sha256,
                        game_toml_sha256=game_toml_sha256,
                        game_toml_path=os.path.abspath(args.game_toml),
                        seeds_sha256=seed_sha256,
                        emitter_path=os.path.abspath(args.recompiler),
                        emitter_sha256=getattr(args,'recompiler_sha256',None),
                        validation_error=str(identity_error)[:512],
                        validation_error_truncated=len(str(identity_error))>512)
                    recipe=dict(requested=requested[:64],requested_truncated=len(requested)>64,
                        producer_ranges=[list(pair) for pair in producer_ranges[:32]],
                        producer_ranges_truncated=len(producer_ranges)>32,
                        cross_call_allow=list(sorted(set(cross_call_allow))[:64]),
                        cross_call_allow_truncated=len(set(cross_call_allow))>64,
                        cps=bool(getattr(args,'cps',False)),flavor=getattr(args,'flavor',None))
                    collection_retain_fragment_failure(cache_dir,phys_addr,requested,src,
                        load_addr,size,data,set(),set(),hosted_identity=identity_detail,
                        ranges_path=ranges_src,seeds_path=seeds_path,
                        provenance=provenance,recipe=recipe)
                except Exception:
                    pass  # Diagnostics can never change a fail-closed rejection.
            return None, f'{identity_error_prefix}: {identity_error}'
"""
    if text.count(old)!=1:raise ValueError('Hosted identity diagnostics rejection anchor changed')
    text=text.replace(old,new,1)
    path.write_text(text,encoding='utf-8')

def patch_runtime(framework):
    framework=Path(framework)
    api=framework/'runtime/include/overlay_api.h'
    text=api.read_text(encoding='utf-8')
    import re
    text=re.sub(r'#define PSX_OVERLAY_CODEGEN_VER (18|19|20|21)\b','#define PSX_OVERLAY_CODEGEN_VER 22',text)
    if text!=api.read_text(encoding='utf-8'):api.write_text(text,encoding='utf-8')
    path=framework/'runtime/src/mod_runtime.cpp';text=path.read_text(encoding='utf-8')
    if '// COLLECTION_NATIVE_CAMERA_HOOKS' not in text:
        anchor='extern "C" int psx_mod_function_entry(CPUState* cpu, uint32_t address) {\n'
        addition='''    // COLLECTION_NATIVE_CAMERA_HOOKS: callbacks retain their executable guards.
#ifdef JF2_DESKTOP
    extern void jf2_desktop_camera(CPUState*,uint32_t);
    if(cpu)jf2_desktop_camera(cpu,address);
#endif
#ifdef ROBBIT_DESKTOP
    extern void robbit_desktop_camera(CPUState*,uint32_t);
    if(cpu)robbit_desktop_camera(cpu,address);
#endif
'''
        if text.count(anchor)!=1:raise ValueError('Runtime entry hook anchor changed')
        text=text.replace(anchor,anchor+addition)
        # Use explicit C linkage at namespace scope to match the title's exported callback.
        declarations='''#ifdef JF2_DESKTOP
extern "C" void jf2_desktop_camera(CPUState*,uint32_t);
#endif
#ifdef ROBBIT_DESKTOP
extern "C" void robbit_desktop_camera(CPUState*,uint32_t);
#endif
'''
        text=text.replace(anchor,declarations+anchor).replace('    extern void jf2_desktop_camera(CPUState*,uint32_t);\n','').replace('    extern void robbit_desktop_camera(CPUState*,uint32_t);\n','')
        path.write_text(text,encoding='utf-8')
    text=path.read_text(encoding='utf-8')
    if 'jf1_desktop_camera' not in text:
        anchor='extern "C" int psx_mod_function_entry(CPUState* cpu, uint32_t address) {\n'
        text=text.replace(anchor,'#ifdef JF1_DESKTOP\nextern "C" void jf1_desktop_camera(CPUState*,uint32_t);\n#endif\n'+anchor+
            '#ifdef JF1_DESKTOP\n    if(cpu)jf1_desktop_camera(cpu,address);\n#endif\n')
        path.write_text(text,encoding='utf-8')
    text=path.read_text(encoding='utf-8')
    if '// COLLECTION_JF2_INSTRUCTION_BRIDGE_V1' not in text:
        anchor='extern "C" void psx_mod_instruction(CPUState* cpu, uint32_t address, uint32_t instruction) {\n'
        addition='''    // COLLECTION_JF2_INSTRUCTION_BRIDGE_V1: exact per-image guards run in the host.
#if defined(JF2_DESKTOP) && defined(COLLECTION_RUNTIME)
    if(cpu&&address<0xC0000000u&&jf2_control_site(address)){
        jf2_desktop_camera(cpu,address);cpu->gpr[0]=0;
    }
#endif
'''
        if text.count(anchor)!=1:raise ValueError('JF2 configured instruction bridge anchor changed')
        text=text.replace(anchor,anchor+addition,1)
        text='#if defined(JF2_DESKTOP) && defined(COLLECTION_RUNTIME)\n#include "jf2_control_sites.h"\n#endif\n'+text
        path.write_text(text,encoding='utf-8')
    text=path.read_text(encoding='utf-8')
    if '// COLLECTION_ROBBIT_INSTRUCTION_BRIDGE_V1' not in text:
        anchor='extern "C" void psx_mod_instruction(CPUState* cpu, uint32_t address, uint32_t instruction) {\n'
        addition='''    // COLLECTION_ROBBIT_INSTRUCTION_BRIDGE_V1: separate from optional mod plugins.
#ifdef ROBBIT_DESKTOP
    if(cpu&&address<0xC0000000u&&robbit_control_site(address)){
        robbit_desktop_camera(cpu,address);cpu->gpr[0]=0;
    }
#endif
'''
        if text.count(anchor)!=1:raise ValueError('Robbit configured instruction bridge anchor changed')
        text=text.replace(anchor,anchor+addition,1)
        text='#ifdef ROBBIT_DESKTOP\n#include "robbit_control_sites.h"\n#endif\n'+text
        path.write_text(text,encoding='utf-8')
    text=path.read_text(encoding='utf-8')
    if '// COLLECTION_INSTRUCTION_DECLARATIONS_V1' not in text:
        declarations='// COLLECTION_INSTRUCTION_DECLARATIONS_V1\n'
        for macro,name in (('JF2_DESKTOP','jf2_desktop_camera'),('ROBBIT_DESKTOP','robbit_desktop_camera')):
            block=f'#ifdef {macro}\nextern "C" void {name}(CPUState*,uint32_t);\n#endif\n'
            if text.count(block)!=1:raise ValueError('Native camera declaration anchor changed')
            text=text.replace(block,'',1);declarations+=block
        anchor='extern "C" void psx_mod_instruction(CPUState* cpu, uint32_t address, uint32_t instruction) {\n'
        if text.count(anchor)!=1:raise ValueError('Instruction callback declaration anchor changed')
        text=text.replace(anchor,declarations+anchor,1)
        path.write_text(text,encoding='utf-8')
    path=framework/'runtime/src/dirty_ram_interp.c';text=path.read_text(encoding='utf-8')
    if '// COLLECTION_JF1_INTERP_HOOK' not in text:
        anchor='    /* A load\'s writeback becomes visible to the instruction AFTER its delay'
        if text.count(anchor)!=1:raise ValueError('JF1 interpreter step anchor changed')
        text=text.replace(anchor,'    // COLLECTION_JF1_INTERP_HOOK\n#ifdef JF1_DESKTOP\n    extern void jf1_desktop_camera(CPUState*,uint32_t);\n    jf1_desktop_camera(cpu,pc);\n#endif\n'+anchor)
        path.write_text(text,encoding='utf-8')
