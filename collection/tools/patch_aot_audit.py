"""Keep all RAM-segment shards and BIOS recipes inside the independent audit."""
from pathlib import Path


def patch(framework):
    path=Path(framework)/'tools/audit_aot_cache.py';text=path.read_text(encoding='utf-8')
    if '# COLLECTION_AOT_SEGMENTS_V1' in text:
        patch_subimages(path)
        patch_game_installed(path)
        patch_static_batch(path, Path(__file__).with_name('batch_static_guards.py'))
        return
    replacements={
        "sorted(cache.glob('*' + compiler.overlay_ext()))":"sorted(cache.rglob('*' + compiler.overlay_ext()))",
        '    for dll in dlls:\n        ids =':'''    for dll in dlls:
        relative=dll.relative_to(cache)
        assert len(relative.parts)==1 or (len(relative.parts)==2 and relative.parts[0] in ('seg-kuseg','seg-kseg1')), f'Unexpected shard directory: {relative}'
        assert cache.resolve() in dll.resolve().parents, f'Shard outside cache: {relative}'
        ids =''',
        'dict(dll=dll.name, functions=':'dict(dll=dll.relative_to(cache).as_posix(), functions=',
        "{entry & 0x1fffffff for entry in job.get('required_entries', [])}":"set(job.get('required_entries', []))",
        'served = {item[0] & 0x1fffffff for item in compatible}':'served = {item[0] for item in compatible}',
        "image_coverage.append(dict(name=name,":"image_coverage.append(dict(name=name, producer=records_by_name[name].get('producer','verified_disc'), bios_sha256=records_by_name[name].get('bios_sha256'),",
        'recipe_count=len(recipes), published_pairs=len(pairs),':'''recipe_count=len(recipes),
                   bios_recipe_count=sum(record.get('producer')=='bios_resident_manifest' for record in records_by_name.values()),
                   disc_recipe_count=sum(record.get('producer')!='bios_resident_manifest' for record in records_by_name.values()),
                   published_pairs=len(pairs),''',
    }
    for old,new in replacements.items():
        if text.count(old)!=1:raise ValueError(f'AOT segment audit anchor changed: {old}')
        text=text.replace(old,new,1)
    path.write_text('# COLLECTION_AOT_SEGMENTS_V1\n'+text,encoding='utf-8')
    patch_subimages(path)
    patch_game_installed(path)
    patch_static_batch(path, Path(__file__).with_name('batch_static_guards.py'))


def patch_subimages(path):
    path=Path(path);text=path.read_text(encoding='utf-8')
    if '# COLLECTION_AOT_SUBIMAGES_V1' in text:return
    anchor='    def within_bounds(ranges, bounds):'
    helper='''    # COLLECTION_AOT_SUBIMAGES_V1
    def contains_shard_base(load, data, physical):
        return physical is None or (load & 0x1fffffff) <= physical < (load & 0x1fffffff) + len(data)

'''
    replacements={anchor:helper+anchor,
        'if (load & 0x1fffffff) != physical:':'if not contains_shard_base(load, data, physical):',
        'if physical is not None and physical != (load & 0x1fffffff):':'if not contains_shard_base(load, data, physical):'}
    for old,new in replacements.items():
        if text.count(old)!=1:raise ValueError(f'AOT subimage audit anchor changed: {old}')
        text=text.replace(old,new,1)
    path.write_text(text,encoding='utf-8')


def patch_game_installed(path):
    path=Path(path);text=path.read_text(encoding='utf-8')
    if '# COLLECTION_AOT_GAME_INSTALLED_V1' in text:return
    old="disc_recipe_count=sum(record.get('producer')!='bios_resident_manifest' for record in records_by_name.values()),"
    new="""# COLLECTION_AOT_GAME_INSTALLED_V1
                   game_installed_recipe_count=sum(record.get('producer')=='verified_game_installed_code' for record in records_by_name.values()),
                   disc_recipe_count=sum(record.get('producer') not in ('bios_resident_manifest','verified_game_installed_code') for record in records_by_name.values()),"""
    anchor="bios_sha256=records_by_name[name].get('bios_sha256'),"
    if text.count(old)!=1 or text.count(anchor)!=1:raise ValueError('AOT installed-game audit anchors changed')
    text=text.replace(old,new,1).replace(anchor,anchor+" source_executable_sha256=records_by_name[name].get('source_executable_sha256'),",1)
    path.write_text(text,encoding='utf-8')


def patch_static_batch(path, helper_source):
    """Install the validated static-only batch helper without changing DLL matching."""
    path=Path(path);helper_source=Path(helper_source)
    helper_target=path.parent/'batch_static_guards.py'
    text=path.read_text(encoding='utf-8')
    marker='# COLLECTION_AOT_STATIC_BATCH_V3'
    helper_bytes=helper_source.read_bytes()
    old_static='''    if args.static_dispatch:
        # Linked-in variants carry no DLL stem, so each must be proven by the
        # recipe whose original bytes its guard was computed from.
        ids = static_dispatch_identities(args.static_dispatch)
        assert ids, f'No static variants in {args.static_dispatch}'
        for item in ids:
            matched = next((name for name, load, data, bounds in recipes
                            if within_bounds(item[2], bounds) and
                            compiler.current_variant_func_ids([item], data, load, len(data))), None)
            assert matched, f'No original-input guard proof for static entry 0x{item[0]:08X}'
            variants.append(dict(entry=f'0x{item[0]:08X}', crc=f'0x{item[1]:08X}', matched_recipe=matched))
            native_ids.append((None, [item]))'''
    new_static='''    if args.static_dispatch:
        # COLLECTION_AOT_STATIC_BATCH_V3
        from batch_static_guards import batched_static_audit
        # Linked-in variants carry no DLL stem, so each must be proven by the
        # recipe whose original bytes its guard was computed from.
        ids = static_dispatch_identities(args.static_dispatch)
        assert ids, f'No static variants in {args.static_dispatch}'
        static_matches, static_compatible = batched_static_audit(ids, recipes, compiler)
        for item, matched in zip(ids, static_matches):
            assert matched, f'No original-input guard proof for static entry 0x{item[0]:08X}'
            variants.append(dict(entry=f'0x{item[0]:08X}', crc=f'0x{item[1]:08X}', matched_recipe=matched))
        del static_matches'''
    old_coverage='''    for name, load, data, bounds in recipes:
        compatible = set()
        for physical, ids in native_ids:
            if not contains_shard_base(load, data, physical):
                continue
            bounded = [item for item in ids if all(
                any(lo <= (start & 0x1fffffff) and (start & 0x1fffffff) + length <= hi
                    for lo, hi in bounds) for start, length in item[2])]
            compatible.update((entry, crc, tuple(tuple(r) for r in ranges))
                              for entry, crc, ranges in compiler.current_variant_func_ids(
                                  bounded, data, load, len(data)))'''
    new_coverage='''    for recipe_index, (name, load, data, bounds) in enumerate(recipes):
        # Release the prior image's large identity set before materializing this one.
        compatible = None
        if args.static_dispatch:
            compatible = static_compatible[recipe_index].materialize()
        else:
            compatible = set()
            for physical, ids in native_ids:
                if not contains_shard_base(load, data, physical):
                    continue
                bounded = [item for item in ids if all(
                    any(lo <= (start & 0x1fffffff) and (start & 0x1fffffff) + length <= hi
                        for lo, hi in bounds) for start, length in item[2])]
                compatible.update((entry, crc, tuple(tuple(r) for r in ranges))
                                  for entry, crc, ranges in compiler.current_variant_func_ids(
                                      bounded, data, load, len(data)))'''
    old_anchor='''                                   guarded_variants=len(compatible)))
    files = {}'''
    new_anchor='''                                   guarded_variants=len(compatible)))
    if args.static_dispatch:
        compatible = served = None
        del static_compatible, ids
    files = {}'''
    if marker in text:
        if (text.count(marker)!=1 or text.count(new_static)!=1 or
            text.count(new_coverage)!=1 or text.count(new_anchor)!=1 or
            old_static in text or old_coverage in text or old_anchor in text):
            raise ValueError('Static-audit batching transform drift or partial state')
        if not helper_target.is_file():
            raise ValueError('Static-audit batching marker exists but helper is missing')
        if helper_target.read_bytes()!=helper_bytes:
            raise ValueError('Static-audit batching helper drift')
        return
    if ('batch_static_guards' in text or 'static_compatible' in text or helper_target.exists()):
        raise ValueError('Partial static-audit batching state; use a fresh framework copy')
    for old in (old_static,old_coverage,old_anchor):
        if text.count(old)!=1:
            raise ValueError('Static-audit batching source drift or partial transform')
    transformed=text.replace(old_static,new_static,1).replace(old_coverage,new_coverage,1).replace(old_anchor,new_anchor,1)
    if transformed==text:
        raise ValueError('Static-audit batching transform made no change')
    helper_target.write_bytes(helper_bytes)
    path.write_text(transformed,encoding='utf-8',newline='\n')
