"""Compare static entry nominations with audited native guards, without running a game."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import zlib


def audited_native_rows(cache,compiler,abi,pair):
    """Read a sealed pair without the compiler's journal-recovery side effects."""
    from aot_package import artifact_path
    from import_game import sha
    cache=Path(cache).resolve();dll=artifact_path(cache,pair['dll'])
    manifest=dll.with_suffix('.ranges')
    if cache not in manifest.resolve().parents:raise ValueError('Native manifest escapes cache')
    def unchanged():
        return sha(dll)==pair['dll_sha256'] and sha(manifest)==pair['manifest_sha256']
    if not unchanged():raise ValueError(f'Audited native pair changed: {dll.name}')
    pair_id,rows=compiler.parse_runtime_shard_manifest(manifest.read_text(encoding='ascii'),
        require_pair=False,expected_segment=compiler.cache_dir_segment(str(dll.parent)))
    if (not rows or len(rows)!=pair['functions'] or not compiler._dll_runtime_exports_match(
            str(dll),abi,pair_id,{row[0] for row in rows})):
        raise ValueError(f'Native pair has no valid guarded exports: {dll.name}')
    if not unchanged():raise ValueError(f'Audited native pair changed during inspection: {dll.name}')
    return rows


def entry_coverage(record,bundles):
    body=base64.b64decode(record['bytes_b64'],validate=True)
    load=int(record['load_addr'],16)&0x1fffffff
    if len(body)!=record['size'] or not body or load+len(body)>0x200000:
        raise ValueError('Invalid source image bounds')
    nominated={int(pc,16) for key in ('function_entry_pcs','static_dispatch_entry_pcs') for pc in record.get(key,[])}
    if any(pc%4 or not load<=pc&0x1fffffff<load+len(body) for pc in nominated):
        raise ValueError('Static entry outside source image')
    byte_entries=set();coherent_entries=set();memo={}

    def matches(row):
        entry,crc,ranges=row
        key=(entry,crc,tuple(tuple(span) for span in ranges))
        if key in memo:return memo[key]
        actual=0;valid=bool(ranges)
        for start,size in ranges:
            offset=(start&0x1fffffff)-load
            if start%4 or size<=0 or size%4 or offset<0 or offset+size>len(body):valid=False;break
            actual=zlib.crc32(body[offset:offset+size],actual)
        result=valid and actual==crc;memo[key]=result
        return result

    for physical,rows in bundles:
        if not load<=physical<load+len(body) or not any(row[0] in nominated for row in rows):continue
        matched={row[0] for row in rows if matches(row)}
        byte_entries.update(matched&nominated)
        if rows and all(matches(row) for row in rows):coherent_entries.update(matched&nominated)
    return dict(nominated_exact_entries=len(nominated),byte_matched_entries=len(byte_entries),
        whole_bundle_byte_matched_entries=len(coherent_entries),
        missing_byte_variant_pcs=[f'0x{pc:08X}' for pc in sorted(nominated-byte_entries)],
        incoherent_bundle_only_pcs=[f'0x{pc:08X}' for pc in sorted(byte_entries-coherent_entries)])


def report(package,game_id,preparation,output):
    from aot_package import verify_aot,artifact_path
    from cache_identity import compiler_module,namespace
    from import_game import game_from_catalog,sha
    package=Path(package).resolve();preparation=Path(preparation).resolve();output=Path(output).resolve()
    if output.exists():raise ValueError('Refusing to overwrite an existing coverage receipt')
    game=game_from_catalog(package,game_id)
    verification=verify_aot(package,game,preparation)
    audit_path=preparation/'AOT_CACHE_AUDIT.json';audit=json.loads(audit_path.read_text(encoding='utf-8'))
    inventory=preparation/'inventory.json'
    if sha(inventory)!=audit['recipe_input_sha256']:raise ValueError('Preparation inventory changed after audit')
    compiler=compiler_module(package/'toolchain');abi=compiler.overlay_abi_tag(str(package/'toolchain/include'),0)
    cache=preparation/'cache'/namespace(package,game);bundles=[]
    for pair in audit['pairs']:
        dll=artifact_path(cache,pair['dll']);rows=audited_native_rows(cache,compiler,abi,pair)
        bundles.append((int(dll.stem.split('_')[0],16),rows))
    images=[]
    for job in json.loads(inventory.read_text(encoding='utf-8'))['jobs']:
        # Inventory paths may refer to the original checkout; use the retained
        # record beside this verified inventory and bind its original bytes.
        path=preparation/Path(job['input']).name
        record=json.loads(path.read_text(encoding='utf-8'))[0]
        if record.get('producer') not in ('verified_psx_exe_lz1','verified_game_installed_code'):continue
        if hashlib.sha256(base64.b64decode(record['bytes_b64'],validate=True)).hexdigest()!=job['sha256']:
            raise ValueError('Source record bytes changed after audit')
        images.append(dict(image=job['name'],record_sha256=sha(path),**entry_coverage(record,bundles)))
    receipt=dict(schema=1,game=game_id,preparation=str(preparation),verified_preparation=verification,
        inventory_sha256=sha(inventory),tool_sha256=sha(Path(__file__)),images=images,
        semantics='Exact static nominations versus source-matched native guards; whole-bundle byte coherence only',
        limitations=['Missing exact labels may execute inside their native host; these are preparation candidates, not proven interpreter executions',
            'Whole-bundle byte matching does not prove delay-slot admission, runtime slot ownership, capacity, execution semantics or gameplay coverage',
            'Per-image totals repeat common code and do not estimate unique native variants or loader capacity'],
        full_static_coverage_proven=False,campaign_qualified=False,physical_deck_qualified=False)
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(game=game_id,images=len(images),
        per_image_missing_byte_variants=sum(len(row['missing_byte_variant_pcs']) for row in images),
        per_image_incoherent_bundle_only=sum(len(row['incoherent_bundle_only_pcs']) for row in images),output=str(output))))
    return receipt


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package',type=Path,required=True)
    parser.add_argument('--game',choices=('jf1','jf2','robbit'),required=True)
    parser.add_argument('--preparation',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();report(args.package,args.game,args.preparation,args.output)
