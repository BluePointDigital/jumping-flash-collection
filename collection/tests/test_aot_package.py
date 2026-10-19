from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from aot_package import verify_aot,seed_preparation,artifact_path,verify_candidate_capacity,verified_abi_markers,verify_runtime_executable
from import_game import sha

class AotPackageTests(unittest.TestCase):
    def test_actual_executable_must_match_the_publisher_contract(self):
        from types import SimpleNamespace
        limits=dict(schema=1,profile='collection-v1',candidate_capacity=262144)
        info=dict(overlay_limits_schema=1,overlay_limits_profile='collection-v1',
            overlay_candidate_capacity=262144,overlay_capacity_tables_bytes=184549376)
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);exe=root/'runtime.exe';exe.write_bytes(b'--collection-runtime-info')
            with patch('aot_package.verify_runtime_limits',return_value=limits),patch('aot_package.subprocess.run',return_value=SimpleNamespace(stdout=json.dumps(info))) as run:
                self.assertEqual(verify_runtime_executable(root,exe),info)
                self.assertEqual(run.call_args.args[0],[str(exe),'--collection-runtime-info'])
            for bad in (dict(info,overlay_candidate_capacity=131072),dict(info,overlay_limits_schema=2),
                        dict(info,overlay_limits_profile='other'),dict(info,overlay_capacity_tables_bytes=0),[]):
                with self.subTest(bad=bad),patch('aot_package.verify_runtime_limits',return_value=limits),patch('aot_package.subprocess.run',return_value=SimpleNamespace(stdout=json.dumps(bad))):
                    with self.assertRaisesRegex(ValueError,'contract differ'):verify_runtime_executable(root,exe)
            with patch('aot_package.verify_runtime_limits',return_value=limits),patch('aot_package.subprocess.run',return_value=SimpleNamespace(stdout='not JSON')):
                with self.assertRaisesRegex(ValueError,'Cannot verify'):verify_runtime_executable(root,exe)
            exe.write_bytes(b'old executable without safe info command')
            with patch('aot_package.verify_runtime_limits',return_value=limits),patch('aot_package.subprocess.run') as run:
                with self.assertRaisesRegex(ValueError,'lacks'):verify_runtime_executable(root,exe)
                run.assert_not_called()

    def abi_fixture(self,root,segments=('',)):
        api=root/'toolchain/include/overlay_api.h';api.parent.mkdir(parents=True)
        api.write_text('#define PSX_OVERLAY_ABI_VERSION 30\n')
        provenance=root/'provenance.json';provenance.write_text(json.dumps(dict(preparation_tools=dict(overlay_api_sha256=sha(api)))))
        cache=root/'cache';pairs=[]
        for segment in segments:
            dll=cache/segment/'00010000_12345678.dll';dll.parent.mkdir(parents=True,exist_ok=True)
            dll.write_bytes(b'audited native bytes');dll.with_suffix('.ranges').write_bytes(b'audited manifest')
            dll.with_suffix('.resident').write_bytes(b'audited resident metadata')
            pairs.append(dict(dll=dll.relative_to(cache).as_posix(),dll_sha256=sha(dll),
                manifest_sha256=sha(dll.with_suffix('.ranges')),resident_sha256=sha(dll.with_suffix('.resident'))))
        return cache,provenance,dict(flavor=0,all_pairs_valid=True,all_guards_match_known_input_bytes=True,
            guidance_provenance_sha256=sha(provenance),pairs=pairs)

    def test_verified_copies_reuse_abi_sweep_in_each_validated_segment(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);cache,proof,audit=self.abi_fixture(root,('','seg-kuseg','seg-kseg1'))
            with patch('aot_package.compiler_module',return_value=SimpleNamespace(overlay_abi_tag=lambda include,flavor:30)):
                result=verified_abi_markers(root,cache,audit,proof)
            self.assertEqual(set(result),{'.abi_0000001e.ok','seg-kuseg/.abi_0000001e.ok','seg-kseg1/.abi_0000001e.ok'})
            self.assertTrue(all((cache/name).read_bytes()==b'' for name in result))

    def test_abi_sweep_is_not_blessed_after_tampering_extra_dll_or_api_change(self):
        from types import SimpleNamespace
        for bad in ('dll','ranges','resident','unclaimed-resident','extra','api','provenance','flavor','audit'):
            with self.subTest(bad=bad),tempfile.TemporaryDirectory() as temp:
                root=Path(temp);cache,proof,audit=self.abi_fixture(root)
                dll=cache/audit['pairs'][0]['dll']
                if bad in ('dll','ranges','resident'):dll.with_suffix('.'+bad).write_bytes(b'changed')
                elif bad=='unclaimed-resident':audit['pairs'][0].pop('resident_sha256')
                elif bad=='extra':(cache/'00020000_87654321.dll').write_bytes(b'not audited')
                elif bad=='api':(root/'toolchain/include/overlay_api.h').write_text('#define PSX_OVERLAY_ABI_VERSION 31\n')
                elif bad=='provenance':proof.write_text('{}')
                elif bad=='flavor':audit['flavor']=1
                elif bad=='audit':audit['all_pairs_valid']=False
                with patch('aot_package.compiler_module',return_value=SimpleNamespace(overlay_abi_tag=lambda include,flavor:30)):
                    self.assertEqual(verified_abi_markers(root,cache,audit,proof),[])
                self.assertFalse(list(cache.glob('.abi_*.ok')))

    def test_shared_manifest_capacity_retains_every_physical_limit(self):
        from types import SimpleNamespace
        inventory=[4,8,12,2]
        compiler=SimpleNamespace(RUNTIME_CACHE_FILE_CAP=4)
        limits=dict(candidate_capacity=4,abi_version=30)
        self.assertIsNone(verify_candidate_capacity('.',Path('cache'),None,3))
        with patch('aot_package.compiler_module',return_value=compiler),patch(
            'aot_package._audited_pair_capacity_inventory',side_effect=lambda *args:tuple(inventory)):
            self.assertEqual(verify_candidate_capacity('.',Path('cache'),limits,8,[{}])['candidate_groups'],4)
            for index,value in [(1,9),(2,65),(3,5),(0,5)]:
                before=inventory[index];inventory[index]=value
                with self.subTest(field=index),self.assertRaisesRegex(ValueError,'capacity'):
                    verify_candidate_capacity('.',Path('cache'),limits,8,[{}])
                inventory[index]=before
            with self.assertRaisesRegex(ValueError,'capacity'):verify_candidate_capacity('.',Path('cache'),None,32769)

    def test_capacity_inventory_runs_below_candidate_cap_and_is_read_only(self):
        from types import SimpleNamespace
        inventory=[2,3,65,2]
        compiler=SimpleNamespace(RUNTIME_CACHE_FILE_CAP=4)
        limits=dict(candidate_capacity=4,abi_version=30)
        with patch('aot_package.compiler_module',return_value=compiler),patch(
            'aot_package._audited_pair_capacity_inventory',side_effect=lambda *args:tuple(inventory)):
            with self.assertRaisesRegex(ValueError,'capacity'):
                verify_candidate_capacity('.',Path('cache'),limits,3,[{}])
            inventory[2]=64
            inventory[3]=5
            with self.assertRaisesRegex(ValueError,'capacity'):
                verify_candidate_capacity('.',Path('cache'),limits,3,[{}])
            inventory[3]=4
            self.assertEqual(verify_candidate_capacity('.',Path('cache'),limits,3,[{}]),
                dict(candidate_groups=2,raw_manifest_rows=3,range_links=64,files=4))

    def test_capacity_boundaries_and_verified_pair_deduplication(self):
        from types import SimpleNamespace
        inventory=[4,8,64,4]
        compiler=SimpleNamespace(RUNTIME_CACHE_FILE_CAP=4)
        limits=dict(candidate_capacity=4,abi_version=30)
        with patch('aot_package.compiler_module',return_value=compiler),patch(
            'aot_package._audited_pair_capacity_inventory',side_effect=lambda *args:tuple(inventory)):
            self.assertEqual(verify_candidate_capacity('.',Path('cache'),limits,8,[{}]),
                dict(candidate_groups=4,raw_manifest_rows=8,range_links=64,files=4))
            inventory[2]=65
            with self.assertRaisesRegex(ValueError,'capacity'):
                verify_candidate_capacity('.',Path('cache'),limits,8,[{}])
            inventory[2]=64;inventory[3]=5
            with self.assertRaisesRegex(ValueError,'capacity'):
                verify_candidate_capacity('.',Path('cache'),limits,8,[{}])
            inventory[3]=4;inventory[0]=3
            self.assertEqual(verify_candidate_capacity('.',Path('cache'),limits,8,[{}])['candidate_groups'],3)
            inventory[0]=5
            with self.assertRaisesRegex(ValueError,'capacity'):
                verify_candidate_capacity('.',Path('cache'),limits,8,[{}])
            inventory[0]=4;inventory[1]=9
            with self.assertRaisesRegex(ValueError,'capacity'):
                verify_candidate_capacity('.',Path('cache'),limits,9,[{}])

    def test_readonly_capacity_audit_leaves_pending_pair_journal_untouched(self):
        from cache_identity import compiler_module as load_compiler
        compiler_root=(Path(__file__).resolve().parents[1]/
            '.workbench/native/robbit/psxrecomp/overlay_toolchain')
        compiler=load_compiler(compiler_root)
        with tempfile.TemporaryDirectory() as temp:
            cache=Path(temp)/'cache';cache.mkdir()
            dll=cache/'00001000_12345678.dll';dll.write_bytes(b'audited dll bytes')
            manifest=dll.with_suffix('.ranges')
            manifest.write_text('P 0000000000000001\nF 80001000 12345678\nR 80001000 00000004\n',encoding='ascii')
            duplicate=cache/'00002000_87654321.dll';duplicate.write_bytes(b'audited dll bytes')
            duplicate_manifest=duplicate.with_suffix('.ranges');duplicate_manifest.write_bytes(manifest.read_bytes())
            token='a'*32
            backup_dll=Path(str(dll)+f'.pair-txn.{token}.old-dll')
            backup_ranges=Path(str(dll)+f'.pair-txn.{token}.old-ranges')
            backup_dll.write_bytes(b'old dll')
            backup_ranges.write_bytes(b'old ranges')
            journal=Path(str(dll)+'.pair-txn.json')
            journal.write_text(json.dumps(dict(
                schema='psxrecomp shard pair transaction v1',token=token,
                backup_dll=str(dll.resolve())+f'.pair-txn.{token}.old-dll',
                backup_ranges=str(dll.resolve())+f'.pair-txn.{token}.old-ranges',
                new_dll_sha256=sha(dll),new_ranges_sha256=sha(manifest),
                old_dll_sha256='0'*64,old_ranges_sha256='1'*64)),encoding='utf-8')
            before={path:path.read_bytes() for path in
                (dll,manifest,duplicate,duplicate_manifest,journal,backup_dll,backup_ranges)}
            pairs=[dict(dll=path.name,dll_sha256=sha(path),
                manifest_sha256=sha(path.with_suffix('.ranges')))
                for path in (dll,duplicate)]
            with patch('aot_package.compiler_module',return_value=compiler):
                result=verify_candidate_capacity(temp,cache,
                    dict(candidate_capacity=4,abi_version=30),2,pairs)
            self.assertEqual(result,dict(candidate_groups=1,raw_manifest_rows=2,range_links=2,files=2))
            self.assertEqual({path:path.read_bytes() for path in before},before)

    def test_only_known_segment_artifact_paths_are_allowed(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            for name in ('00000CF0_7BDDFF20.dll','seg-kuseg/00000CF0_7BDDFF20.dll','seg-kseg1/00000CF0_7BDDFF20.dll'):
                self.assertEqual(artifact_path(root,name),root/name)
            for name in ('../00000CF0_7BDDFF20.dll','/00000CF0_7BDDFF20.dll','seg-kuseg/../00000CF0_7BDDFF20.dll','seg-kuseg\\00000CF0_7BDDFF20.dll','unknown/00000CF0_7BDDFF20.dll','a/b/00000CF0_7BDDFF20.dll','00000CF0_7BDDFF20.dll:stream'):
                with self.subTest(name=name),self.assertRaises(ValueError):artifact_path(root,name)

    def test_bios_identity_and_segment_sidecars_survive_seeding(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);preparation=root/'preparation';relative=Path('SCUS-94103/gcc/win-x64/current')
            cache=preparation/'cache'/relative;cache.mkdir(parents=True)
            game=dict(id='jf1',serial='SCUS-94103',disc_sha256='disc',bios_sha256='bios')
            pairs=[]
            for segment in ('','seg-kuseg','seg-kseg1'):
                name=(Path(segment)/'00000CF0_7BDDFF20.dll').as_posix();dll=cache/name;dll.parent.mkdir(exist_ok=True)
                dll.write_text(segment or 'kseg0');dll.with_suffix('.ranges').write_text('guard')
                marker=dll.with_suffix('.resident');marker.write_text(json.dumps(dict(bios_sha256='bios')))
                pairs.append(dict(dll=name,dll_sha256=sha(dll),manifest_sha256=sha(dll.with_suffix('.ranges')),resident_sha256=sha(marker)))
            provenance=preparation/'provenance.json';provenance.write_text(json.dumps(dict(game='jf1',disc_sha256='disc',bios_installed=[dict(bios_sha256='bios')])))
            audit=dict(game_id='SCUS-94103',cache_tag='current',all_pairs_valid=True,all_guards_match_known_input_bytes=True,
                recipe_count=17,disc_recipe_count=16,bios_recipe_count=1,published_pairs=3,manifest_rows=3,pairs=pairs,
                guidance_provenance_sha256=sha(provenance),image_coverage=[{} for _ in range(16)]+[dict(producer='bios_resident_manifest',bios_sha256='bios')])
            path=preparation/'AOT_CACHE_AUDIT.json';path.write_text(json.dumps(audit))
            with patch('aot_package.namespace',return_value=relative):
                data=root/'probe';seed_preparation(root,game,data,preparation)
                for pair in pairs:
                    target=data/'cache'/relative/pair['dll']
                    self.assertEqual(sha(target),pair['dll_sha256'])
                    self.assertEqual(sha(target.with_suffix('.resident')),pair['resident_sha256'])
                with self.assertRaisesRegex(ValueError,'BIOS'):verify_aot(root,dict(game,bios_sha256='wrong bios'),preparation)
                identity=json.loads(provenance.read_text())
                identity['bios_installed'][0]['source_executable_sha256']='verified boot'
                provenance.write_text(json.dumps(identity));audit['guidance_provenance_sha256']=sha(provenance);path.write_text(json.dumps(audit))
                with self.assertRaisesRegex(ValueError,'SDK resident code source'):verify_aot(root,game,preparation)
                identity['inputs']=[dict(source_sha256='verified boot')]
                provenance.write_text(json.dumps(identity));audit['guidance_provenance_sha256']=sha(provenance);path.write_text(json.dumps(audit))
                self.assertEqual(verify_aot(root,game,preparation)['pairs'],3)
                audit['bios_recipe_count']=0;path.write_text(json.dumps(audit))
                with self.assertRaisesRegex(ValueError,'identity'):verify_aot(root,game,preparation)
    def test_pairs_identity_and_tampering(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);base=root/'data/games/jf2/cache';cache=base/'SCES-00111/gcc/win-x64/current'
            cache.mkdir(parents=True)
            dll=cache/'000AC000_12345678.dll';dll.write_bytes(b'fixture dll')
            manifest=dll.with_suffix('.ranges');manifest.write_bytes(b'fixture guard manifest')
            audit=dict(game_id='SCES-00111',cache_tag='current',all_pairs_valid=True,
                all_guards_match_known_input_bytes=True,published_pairs=1,recipe_count=28,
                image_coverage=[{'name':f'fixture{i}'} for i in range(28)],manifest_rows=3,pairs=[dict(dll=dll.name,dll_sha256=sha(dll),manifest_sha256=sha(manifest))])
            path=base/'AOT_CACHE_AUDIT.json';path.write_text(json.dumps(audit))
            game=dict(id='jf2',serial='SCES-00111')
            with patch('aot_package.namespace',return_value=Path('SCES-00111/gcc/win-x64/current')):
                self.assertEqual(verify_aot(root,game)['pairs'],1)
                provenance=base/'AOT_PROVENANCE.json';provenance.write_bytes(b'fixture provenance')
                audit['guidance_provenance_sha256']=sha(provenance);path.write_text(json.dumps(audit))
                self.assertEqual(verify_aot(root,game)['pairs'],1)
                provenance.write_bytes(b'tampered')
                with self.assertRaisesRegex(ValueError,'provenance'):verify_aot(root,game)
                provenance.write_bytes(b'fixture provenance')
                manifest.write_bytes(b'tampered')
                with self.assertRaisesRegex(ValueError,'changed'):verify_aot(root,game)
                audit['cache_tag']='stale';path.write_text(json.dumps(audit))
                with self.assertRaisesRegex(ValueError,'identity'):verify_aot(root,game)
    def test_missing_cache_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaisesRegex(ValueError,'missing'):verify_aot(Path(root),dict(id='robbit'))

    def test_external_preparation_only_copies_audited_pairs(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);preparation=root/'preparation';data=root/'probe'
            relative=Path('SCUS-94103/gcc/win-x64/current');cache=preparation/'cache'/relative
            cache.mkdir(parents=True)
            dll=cache/'000E4000_12345678.dll';dll.write_bytes(b'audited native code')
            manifest=dll.with_suffix('.ranges');manifest.write_bytes(b'audited guards')
            (cache/'unreviewed.dll').write_bytes(b'never copy')
            provenance=preparation/'provenance.json'
            provenance.write_text(json.dumps(dict(game='jf1',disc_sha256='verified disc')))
            audit=dict(game_id='SCUS-94103',cache_tag='current',all_pairs_valid=True,
                all_guards_match_known_input_bytes=True,published_pairs=1,recipe_count=16,
                image_coverage=[{} for _ in range(16)],manifest_rows=3,
                guidance_provenance_sha256=sha(provenance),pairs=[dict(dll=dll.name,
                    dll_sha256=sha(dll),manifest_sha256=sha(manifest))])
            (preparation/'AOT_CACHE_AUDIT.json').write_text(json.dumps(audit))
            game=dict(id='jf1',serial='SCUS-94103',disc_sha256='verified disc')
            with patch('aot_package.namespace',return_value=relative):
                receipt=seed_preparation(root,game,data,preparation)
                self.assertEqual(receipt['pairs'],1)
                self.assertEqual(sha(data/'static-preparation/AOT_CACHE_AUDIT.json'),receipt['audit_sha256'])
                self.assertEqual((data/'cache'/relative/dll.name).read_bytes(),dll.read_bytes())
                self.assertFalse((data/'cache'/relative/'unreviewed.dll').exists())
                identity=json.loads(provenance.read_text());identity['inputs']=[dict(source_sha256='verified executable')]
                identity['game_installed']=[dict(source_executable_sha256='verified executable')]
                provenance.write_text(json.dumps(identity));audit['guidance_provenance_sha256']=sha(provenance)
                audit.update(disc_recipe_count=16,game_installed_recipe_count=1,recipe_count=17)
                audit['image_coverage'].append(dict(producer='verified_game_installed_code',source_executable_sha256='verified executable'))
                (preparation/'AOT_CACHE_AUDIT.json').write_text(json.dumps(audit))
                self.assertEqual(verify_aot(root,game,preparation)['recipes'],17)
                identity['game_installed'][0]['source_executable_sha256']='unverified executable'
                provenance.write_text(json.dumps(identity));audit['guidance_provenance_sha256']=sha(provenance)
                (preparation/'AOT_CACHE_AUDIT.json').write_text(json.dumps(audit))
                with self.assertRaisesRegex(ValueError,'Installed game code source'):verify_aot(root,game,preparation)
                identity['game_installed'][0]['source_executable_sha256']='verified executable'
                provenance.write_text(json.dumps(identity));audit['guidance_provenance_sha256']=sha(provenance)
                (preparation/'AOT_CACHE_AUDIT.json').write_text(json.dumps(audit))
                with self.assertRaisesRegex(ValueError,'input disc'):
                    seed_preparation(root,dict(game,disc_sha256='different disc'),data,preparation)
                dll.write_bytes(b'tampered')
                with self.assertRaisesRegex(ValueError,'changed'):seed_preparation(root,game,data,preparation)

if __name__=='__main__':unittest.main()
