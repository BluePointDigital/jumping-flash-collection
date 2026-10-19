"""Only speculative work is budgeted; required execution and audits stay intact."""
from pathlib import Path
import importlib.util
import json
import os
import sys
import tempfile
import unittest
import struct
from unittest.mock import patch as environment_patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from patch_compiler import patch,patch_inclusive_switch
from prepare_runtimes import PROJECTS


class CompilerBudgetTests(unittest.TestCase):
    def test_configured_instruction_hook_suppresses_duplicate_manual_callback(self):
        include=ROOT/'.workbench/native/jf1/psxrecomp/runtime/include'
        self.compiler.load_dispatch_preamble(str(include))
        for label in ('','block_800A2778:\n'):
            source=('#include "psx_runtime.h"\nvoid func_800A2778(CPUState* cpu)\n{\n'+label+
                    '    psx_mod_instruction(cpu, 0x800A2778u, 0x27BDFFB8u);\n    return;\n}\n')
            for static in (False,True):
                with self.subTest(label=label,static=static):
                    if static:result=self.compiler.patch_generated_c_static(source,0x80052000,0x80000)[0]
                    else:result=self.compiler.patch_generated_c(source,0x80052000,0x80000)
                    self.assertNotIn('if(psx_mod_function_entry(cpu,0x800A2778u))return;',result)
                    self.assertEqual(result.count('psx_mod_instruction(cpu, 0x800A2778u, 0x27BDFFB8u);'),1)

    def coherent_fixture(self):
        import zlib
        base=0x80010000;body=struct.pack('<8I',0x03e00008,0,0,0,0x03e00008,0,0,0)
        def row(offset,correct=True):
            return (base+offset,zlib.crc32(body[offset:offset+8])^(0 if correct else 1),[(base+offset,8)])
        return base,body,row

    def test_partial_bundle_does_not_suppress_primary_or_fragment_preparation(self):
        base,body,row=self.coherent_fixture();first=row(0);stale=row(16,False)
        with tempfile.TemporaryDirectory() as directory:
            bad=Path(directory)/'00010000_AAAAAAAA.ranges';bad.write_text('fixture')
            with environment_patch.object(self.compiler,'load_shard_func_ids',return_value=[first,stale]):
                source=self.compiler.load_region_current_variant_func_ids(directory,0x10000,body,base,len(body),30)
                served=self.compiler.load_region_current_variant_func_ids(directory,0x10000,body,base,len(body),30,coherent_only=True)
                self.assertEqual(source,[first])
                self.assertEqual(served,[])
                self.assertTrue(self.compiler.current_variant_identities_cover([first],source))
                self.assertFalse(self.compiler.current_variant_identities_cover([first],served))
                self.assertEqual(self.compiler.load_region_current_variant_coverage(directory,0x10000,body,base,len(body),30),(set(),[]))

    def test_coherent_island_restores_coverage_without_erasing_source_authority(self):
        base,body,row=self.coherent_fixture();first=row(0);stale=row(16,False)
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory)/'00010000_AAAAAAAA.ranges').write_text('partial')
            (Path(directory)/'00010000_BBBBBBBB.ranges').write_text('coherent island')
            def load(path,abi,include_supplemental=True):
                self.assertEqual(abi,30)
                return [first,stale] if 'AAAAAAAA' in path else [first]
            with environment_patch.object(self.compiler,'load_shard_func_ids',side_effect=load) as read:
                self.assertEqual(self.compiler.load_region_current_variant_coverage(directory,0x10000,body,base,len(body),30),({0x10000},[(0x10000,0x10008)]))
                ids=self.compiler.load_region_current_variant_func_ids(directory,0x10000,body,base,len(body),30,include_supplemental=False,coherent_only=True)
                self.assertEqual(ids,[first]);self.assertFalse(read.call_args.kwargs['include_supplemental'])
                source=self.compiler.load_region_current_variant_func_ids(directory,0x10000,body,base,len(body),30)
                self.assertEqual(source.count(first),2)

    def test_coherent_bundle_revalidates_every_guard_for_each_image(self):
        base,body,row=self.coherent_fixture();ids=[row(0),row(16)]
        self.assertEqual(self.compiler.coherent_variant_func_ids(ids,body,base,len(body)),ids)
        changed=bytearray(body);changed[16]^=1
        self.assertEqual(self.compiler.current_variant_func_ids(ids,changed,base,len(body)),ids[:1])
        self.assertEqual(self.compiler.coherent_variant_func_ids(ids,changed,base,len(body)),[])
        self.assertEqual(self.compiler.coherent_variant_func_ids(ids,body,base,len(body)),ids)
        self.assertEqual(self.compiler.coherent_variant_func_ids([],body,base,len(body)),[])

    def test_alias_at_own_callable_start_preserves_root_but_interior_does_not(self):
        base=0x80010000;entry=base+16
        words=[0x03e00008,0,0,0,0x27bdfff0,0xafbf000c,
               0x8fbf000c,0x27bd0010,0x03e00008,0]
        body=struct.pack('<10I',*words)
        record=dict(schema='psxrecomp overlay capture v3',load_addr=hex(base),
            size=len(body),function_entry_pcs=[hex(base),hex(entry)],
            dispatch_entry_pcs=[hex(base),hex(entry)],
            static_dispatch_entry_pcs=[hex(base),hex(entry)],
            static_alias_ranges=[dict(entry=hex(entry),start=hex(entry),end=hex(base+40))])
        seeds,audit=self.compiler.classify_overlay_seeds(record,body,base,len(body),0,{})
        self.assertNotEqual(audit['included_reasons'].get(entry),'DISPATCH_INTERIOR')
        self.assertIn(entry,self.compiler.walk_root_seed_entries(seeds))
        # A real suffix of that function still uses the overlapping alias path.
        suffix=entry+4
        record['dispatch_entry_pcs'].append(hex(suffix))
        record['static_alias_ranges'].append(dict(entry=hex(suffix),start=hex(entry),end=hex(base+40)))
        seeds,audit=self.compiler.classify_overlay_seeds(record,body,base,len(body),0,{})
        self.assertEqual(audit['included_reasons'].get(suffix),'DISPATCH_INTERIOR')
        self.assertNotIn(suffix,self.compiler.walk_root_seed_entries(seeds))

    def test_shared_guard_body_is_audited_once_without_losing_aliases(self):
        import zlib
        base=0x80010000;data=bytes(32);crc=zlib.crc32(data)&0xffffffff
        ids=[(base,crc,[(base,32)]),(base+4,crc,[(base,32)]),(base+8,crc,[[base,32]])]
        original=self.compiler.audit_func_id_delay_slots
        with environment_patch.object(self.compiler,'audit_func_id_delay_slots',wraps=original) as audit:
            self.assertEqual(self.compiler.current_variant_func_ids(ids,data,base,len(data)),ids)
            self.assertEqual(audit.call_count,1)

    def test_guard_memo_is_not_reused_after_source_bytes_change(self):
        import zlib
        base=0x80010000;data=bytearray(32);crc=zlib.crc32(data)&0xffffffff
        ids=[(base,crc,[(base,32)]),(base+4,crc^1,[(base,32)]),(base+8,crc,[(base,16)])]
        self.assertEqual(self.compiler.current_variant_func_ids(ids,data,base,len(data)),ids[:1])
        data[0]=1
        self.assertEqual(self.compiler.current_variant_func_ids(ids,data,base,len(data)),[])

    def test_primary_skip_rejects_same_crc_from_a_different_guard_layout(self):
        import zlib
        base=0x80010000;data=bytearray(64);entry=base+24
        struct.pack_into('<I',data,36,0x24020001)
        crc=zlib.crc32(bytes(16))&0xffffffff
        required=(entry,crc,[(base+16,16)])
        stale=(entry,crc,[(base+24,16)])
        # The old entry/CRC-only gate incorrectly considers these identical.
        self.assertEqual(required[:2],stale[:2])
        self.assertEqual(self.compiler.current_variant_func_ids([stale],data,base,len(data)),[])
        self.assertEqual(self.compiler.current_variant_func_ids([required],data,base,len(data)),[required])
        covers=self.compiler.current_variant_identities_cover
        self.assertFalse(covers([required],[stale]))
        self.assertTrue(covers([required],[stale,required]))
        self.assertFalse(covers([],[]))
        self.assertFalse(covers([required],[(entry,crc^1,required[2])]))

    def inclusive_fixture(self,load=0x80010000):
        data=bytearray(128);entry=load+32;targets=[entry+44,entry+52,entry+60]
        struct.pack_into('<3I',data,0,*targets)
        struct.pack_into('<11I',data,32,0x34020002,0x0043102b,0x1440000c,0x00031080,
            0x3c010000|((load+0x8000)>>16),0x24210000|(load&0xffff),0x00220821,0x8c220000,0,0x00400008,0)
        for target in targets:struct.pack_into('<2I',data,target-load,0x03e00008,0)
        return load,data,entry,targets

    def test_primary_cfg_owns_inclusive_switch_and_exact_bound_reinstating_backedge(self):
        for load in (0x80010000,0x80018000):
            load,data,entry,targets=self.inclusive_fixture(load);proof=[]
            resolve=lambda:self.compiler._find_jump_table_targets(data,load,len(data),entry,entry+68,entry+36,2,proof_out=proof)
            self.assertEqual(resolve(),set(targets));self.assertEqual(proof[0]['count'],3)
            struct.pack_into('<2I',data,targets[1]-load,0x08000000|((entry+4)>>2&0x03ffffff),0x34020002)
            self.assertEqual(resolve(),set(targets))

    def test_primary_inclusive_guard_rejects_bypass_and_wrong_delay_bound(self):
        load,data,entry,targets=self.inclusive_fixture()
        for target,slot in [(entry+4,0),(entry+4,0x34020003),(entry+12,0x34020002),(entry+20,0x34020002)]:
            changed=bytearray(data);struct.pack_into('<2I',changed,targets[1]-load,
                0x08000000|(target>>2&0x03ffffff),slot)
            self.assertEqual(self.compiler._find_jump_table_targets(changed,load,len(changed),entry,entry+68,entry+36,2),set())
        for offset,value in [(32,0x34021000),(36,0x0043102a),(40,0x1040000c),(44,0x000310c0),
                             (60,0x8c220004),(64,0x24020001),(72,0x24020001)]:
            changed=bytearray(data);struct.pack_into('<I',changed,offset,value)
            self.assertEqual(self.compiler._find_jump_table_targets(changed,load,len(changed),entry,entry+68,entry+36,2),set())

    def test_primary_inclusive_switch_with_separate_safe_delay_move(self):
        load=0x80010000;entry=load+32;targets=[entry+48,entry+56,entry+64]
        data=bytearray(160);struct.pack_into('<3I',data,0,*targets)
        struct.pack_into('<12I',data,32,0x34020002,0x0043102b,0x1440000d,0x00a02021,
            0x00031080,0x3c018001,0x24210000,0x00220821,0x8c220000,0,0x00400008,0)
        for target in targets:struct.pack_into('<2I',data,target-load,0x03e00008,0)
        resolve=lambda body:self.compiler._find_jump_table_targets(body,load,len(body),entry,entry+76,entry+40,2)
        self.assertEqual(resolve(data),set(targets))
        for delay in (0,0x00a02021):
            changed=bytearray(data);struct.pack_into('<I',changed,44,delay)
            self.assertEqual(resolve(changed),set(targets))
        for delay in (0x00a01821,0x10000000,0x00a42021):
            changed=bytearray(data);struct.pack_into('<I',changed,44,delay)
            self.assertEqual(resolve(changed),set())

    def test_inclusive_v2_reapplication_rejects_partial_or_changed_helper(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'compiler.py';data=self.script.read_text()
            path.write_text(data);patch_inclusive_switch(path)
            self.assertEqual(path.read_text(),data)
            for altered in (data.replace('# COLLECTION_INCLUSIVE_SWITCH_V2\n','',1),
                            data.replace('start=jr_pc-36','start=jr_pc-32',1)):
                path.write_text(altered)
                with self.assertRaises(ValueError):patch_inclusive_switch(path)
    def test_offline_callback_budget_keeps_default_and_hard_extent_limits(self):
        load=0x80010000;body=bytearray(2052*4)
        struct.pack_into('<I',body,0,0x24020001)
        struct.pack_into('<2I',body,len(body)-8,0x03e00008,0)
        check=self.compiler.plausible_callable_target
        self.assertFalse(check(body,load,len(body),load,load+len(body)))
        self.assertTrue(check(body,load,len(body),load,load+len(body),instruction_budget=2053))
        self.assertFalse(check(body,load,len(body),load,load+len(body)-8,instruction_budget=2053))
        body[-8:]=b'\0'*8
        self.assertFalse(check(body,load,len(body),load,load+len(body),instruction_budget=2053))
        for budget in (0,4098):
            with self.assertRaises(ValueError):check(body,load,len(body),load,load+len(body),instruction_budget=budget)

    @classmethod
    def setUpClass(cls):
        cls.temporary=tempfile.TemporaryDirectory()
        cls.script=Path(cls.temporary.name)/'compile_overlays.py'
        source=PROJECTS['jf2'][0]/'psxrecomp/tools/compile_overlays.py'
        cls.script.write_bytes(source.read_bytes());patch(cls.script)
        spec=importlib.util.spec_from_file_location('budget_fixture',cls.script)
        cls.compiler=importlib.util.module_from_spec(spec);spec.loader.exec_module(cls.compiler)
    @classmethod
    def tearDownClass(cls):cls.temporary.cleanup()
    def test_budget_never_defers_live_forced_or_interval_roots(self):
        allow=self.compiler.collection_static_attempt_allowed
        budget=[1];job=dict(executed={1},forced={2},static_interval_demands={3})
        self.assertTrue(allow([10],job,budget));self.assertEqual(budget,[0])
        self.assertFalse(allow([11,12],job,budget))
        for root in (1,2,3):self.assertTrue(allow([root],job,budget))
        self.assertEqual(budget,[0]);self.assertTrue(allow([99],job,[None]))
    def test_proven_alias_needs_exact_entry_even_inside_a_native_range(self):
        select=self.compiler.select_fragment_orphans
        entry=0x80010010;covered=[(0x10000,0x10040)]
        self.assertEqual(select({entry},set(),set(),set(),{entry},{0x10000},covered),[entry])
        self.assertEqual(select({entry},set(),set(),set(),{entry},{0x10010},covered),[])
        self.assertEqual(select({entry},set(),set(),set(),set(),{0x10000},covered),[])
        self.assertEqual(select({entry},{entry},set(),set(),set(),{0x10000},covered),[entry])
    def test_early_unsupported_rejection_matches_existing_audit(self):
        for src in ('void func_80010000(CPUState* cpu)\n{ return; }',
                    '// TODO: unsupported instruction 0x80010000: ABCD',
                    '// TODO: placeholder\n// 0x80010000:',
                    '// TODO: unsupported 0x80010000: A\n// TODO: unsupported 0x80010004: B'):
            expected=self.compiler.audit_generated_c(src,0x80010000,64,0,{})['unsupported_todo_addrs']
            self.assertEqual(self.compiler.collection_unsupported_addresses(src),expected)
    def test_failure_retention_defaults_to_small_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            with environment_patch.dict(os.environ,{'PSX_RETAIN_FAILED_C':'0'}):
                self.compiler.collection_retain_fragment_failure(directory,0x10000,[0x80010000],
                    'large C source',0x80010000,4,b'abcd',{0x80010004},set())
            self.assertFalse(list(Path(directory).glob('*.c')))
            receipt=json.loads(next(Path(directory).glob('*.json')).read_text())
            self.assertFalse(receipt['full_c_retained']);self.assertEqual(receipt['size'],4)
            with environment_patch.dict(os.environ,{'PSX_RETAIN_FAILED_C':'1'}):
                self.compiler.collection_retain_fragment_failure(directory,0x10000,[0x80010000],
                    'large C source',0x80010000,4,b'abcd',{0x80010004},set())
            self.assertEqual(next(Path(directory).glob('*.c')).read_text(),'large C source')
            self.assertTrue(json.loads(next(Path(directory).glob('*.json')).read_text())['full_c_retained'])
    def test_reapplication_does_not_duplicate_helpers(self):
        before=self.script.read_bytes();patch(self.script);self.assertEqual(before,self.script.read_bytes())
    def test_signed_addi_sdk_prologue_is_a_real_call_boundary(self):
        # Verified SELECT.PEX 0x800E7F60..: padding separates this ADDI frame
        # from the previous JR, so the old ADDIU-only recognizer rejected it.
        words=[0x03e00008,0x27bd0078,0x80010000,0x23bdfffc,0xafbf0000,0x3c048000,
            0x0000000c,0x10400003,0,0x0040f809,0,0x8fbf0000,0x23bd0004,0x03e00008,0]
        body=struct.pack('<'+str(len(words))+'I',*words);load=0x800e7f60
        self.assertTrue(self.compiler._callable_direct_jal_target(body,load,load+12))
        for word in (0x23bdfffc,0x27bdffe8):self.assertTrue(self.compiler._is_addiu_sp_neg(word))
        for word in (0x23bd0004,0x23bcfffc,0x201dfffc,0):self.assertFalse(self.compiler._is_addiu_sp_neg(word))
        words[2]=0x10000001 # A stack adjustment in a branch delay slot is not an entry.
        body=struct.pack('<'+str(len(words))+'I',*words)
        self.assertFalse(self.compiler._callable_direct_jal_target(body,load,load+12))
    def test_debris_scan_is_bounded_per_pair_per_invocation(self):
        with tempfile.TemporaryDirectory() as directory:
            dll=str(Path(directory)/'entry.dll')
            with environment_patch.object(self.compiler.glob,'glob',return_value=[]) as scan:
                self.compiler._cleanup_old_pair_debris(dll)
                self.compiler._cleanup_old_pair_debris(dll)
                self.assertEqual(scan.call_count,1)
                self.compiler._cleanup_old_pair_debris(str(Path(directory)/'other.dll'))
                self.assertEqual(scan.call_count,2)
    def test_new_transaction_recovers_after_prior_housekeeping_scan(self):
        import hashlib
        with tempfile.TemporaryDirectory() as directory:
            dll=Path(directory)/'entry.dll';ranges=dll.with_suffix('.ranges')
            self.compiler._cleanup_old_pair_debris(str(dll))
            token='a'*32
            backup_dll=Path(str(dll)+'.pair-txn.'+token+'.old-dll')
            backup_ranges=Path(str(dll)+'.pair-txn.'+token+'.old-ranges')
            backup_dll.write_bytes(b'old dll');backup_ranges.write_bytes(b'old ranges')
            dll.write_bytes(b'new dll');ranges.write_bytes(b'incomplete new ranges')
            journal=Path(self.compiler._shard_pair_paths(str(dll))[3])
            digest=lambda value:hashlib.sha256(value).hexdigest()
            journal.write_text(json.dumps(dict(schema='psxrecomp shard pair transaction v1',token=token,
                backup_dll=str(backup_dll),backup_ranges=str(backup_ranges),
                new_dll_sha256=digest(b'new dll'),new_ranges_sha256=digest(b'new ranges'),
                old_dll_sha256=digest(b'old dll'),old_ranges_sha256=digest(b'old ranges'))))
            self.compiler._recover_shard_pair_locked(str(dll))
            self.assertEqual(dll.read_bytes(),b'old dll');self.assertEqual(ranges.read_bytes(),b'old ranges')
            self.assertFalse(journal.exists())
    def test_collection_capacity_contract_matches_abi_and_is_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            include=Path(directory)
            (include/'overlay_api.h').write_text('#define PSX_OVERLAY_CANDIDATE_CAP 32768\n#define PSX_OVERLAY_ABI_VERSION 30\n')
            self.assertEqual(self.compiler.overlay_candidate_cap(directory),32768)
            limits=dict(schema=1,profile='collection-v1',candidate_capacity=65536,abi_version=30)
            (include/'collection_overlay_limits.json').write_text(json.dumps(limits))
            self.assertEqual(self.compiler.overlay_candidate_cap(directory),65536)
            (include/'collection_overlay_limits.json').write_text(json.dumps(dict(limits,candidate_capacity=131072)))
            self.assertEqual(self.compiler.overlay_candidate_cap(directory),131072)
            (include/'collection_overlay_limits.json').write_text(json.dumps(dict(limits,candidate_capacity=262144)))
            self.assertEqual(self.compiler.overlay_candidate_cap(directory),262144)
            (include/'collection_overlay_limits.json').write_text(json.dumps(dict(limits,candidate_capacity=524288)))
            self.assertEqual(self.compiler.overlay_candidate_cap(directory),524288)
            for key,value in (('schema',2),('profile','unknown'),('candidate_capacity',65537),
                              ('candidate_capacity',1048576),('candidate_capacity',524288.0),('abi_version',31)):
                (include/'collection_overlay_limits.json').write_text(json.dumps(dict(limits,**{key:value})))
                with self.assertRaises(SystemExit):self.compiler.overlay_candidate_cap(directory)

if __name__=='__main__':unittest.main()
