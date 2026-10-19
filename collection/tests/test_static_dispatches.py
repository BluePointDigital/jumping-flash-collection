import copy,struct,sys,unittest
from types import SimpleNamespace
from unittest.mock import patch
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from static_dispatches import guarded_jump_tables,syscall_returns,link_branch_dispatches,nullable_function_tables,source_referenced_callbacks,uncached_callbacks,compile_segment_records,masked_return_tables,local_control_entries


class StaticDispatchTests(unittest.TestCase):
    def inclusive_table_fixture(self,load=0x80010000):
        body=bytearray(128);start=load+32;targets=[start+44,start+52,start+60]
        struct.pack_into('<3I',body,0,*targets)
        words=(0x34020002,0x0043102b,0x1440000c,0x00031080,
            0x3c010000|((load+0x8000)>>16),0x24210000|(load&0xffff),
            0x00220821,0x8c220000,0,0x00400008,0)
        struct.pack_into('<11I',body,32,*words)
        for target in targets:struct.pack_into('<2I',body,target-load,0x03e00008,0)
        analysis=dict(schema='psxrecomp static analysis v1',static_only=True,load_address=load,image_size=len(body),
            functions=[dict(addr=start,end=start+68,partial=False,is_data=False)])
        return load,body,analysis,targets

    def test_inclusive_guarded_table_retains_local_labels_and_signed_base(self):
        for load in (0x80010000,0x80018000):
            load,body,analysis,targets=self.inclusive_table_fixture(load)
            entries,aliases,proofs=local_control_entries(analysis,load,body)
            self.assertEqual(entries,set(targets))
            self.assertEqual(aliases,{(target,load+32,load+100) for target in targets})
            self.assertEqual(proofs[0]['kind'],'inclusive_bound_jump_table')
            self.assertEqual(proofs[0]['count'],3);self.assertEqual(proofs[0]['table_base'],hex(load))

    def test_inclusive_table_rejects_wrong_guard_registers_slots_and_targets(self):
        load,body,analysis,targets=self.inclusive_table_fixture()
        bad=[(0,0x34021000),(0,0x34220002),(1,0x0043182b),(2,0x1040000c),(2,0x14400000),
            (3,0x000310c0),(4,0x3c028001),(5,0x34210000),(6,0x00220823),
            (7,0x8c220004),(8,0x24040001),(9,0x03e00008),(10,0x24040001)]
        for word,value in bad:
            changed=bytearray(body);struct.pack_into('<I',changed,32+4*word,value)
            with self.subTest(word=word):self.assertEqual(local_control_entries(analysis,load,changed)[0],set())
        for value in [load,load+36,targets[0]+1,load+128]:
            changed=bytearray(body);struct.pack_into('<I',changed,0,value)
            self.assertEqual(local_control_entries(analysis,load,changed)[0],set())
        changed=bytearray(body);struct.pack_into('<I',changed,28,0x10000000)
        altered=copy.deepcopy(analysis);altered['functions'][0]['addr']=load+28
        self.assertEqual(local_control_entries(altered,load,changed)[0],set())
        for field in ('partial','is_data'):
            altered=copy.deepcopy(analysis);altered['functions'][0][field]=True
            self.assertEqual(local_control_entries(altered,load,body)[0],set())

    def test_inclusive_table_with_separate_safe_delay_move(self):
        load=0x80010000;entry=load+32;targets=[entry+48,entry+56,entry+64]
        data=bytearray(160);struct.pack_into('<3I',data,0,*targets)
        struct.pack_into('<12I',data,32,0x34020002,0x0043102b,0x1440000d,0x00a02021,
            0x00031080,0x3c018001,0x24210000,0x00220821,0x8c220000,0,0x00400008,0)
        for target in targets:struct.pack_into('<2I',data,target-load,0x03e00008,0)
        analysis=dict(schema='psxrecomp static analysis v1',static_only=True,load_address=load,
            image_size=len(data),functions=[dict(addr=entry,end=entry+76,partial=False,is_data=False)])
        entries,aliases,proofs=local_control_entries(analysis,load,data)
        self.assertEqual(entries,set(targets))
        self.assertEqual(aliases,{(target,entry,entry+76) for target in targets})
        self.assertEqual(proofs[0]['kind'],'inclusive_bound_jump_table_delay_move')
        for delay in (0x00a01821,0x10000000,0x00a42021):
            changed=bytearray(data);struct.pack_into('<I',changed,44,delay)
            self.assertEqual(local_control_entries(analysis,load,changed)[0],set())

    def resume_fixture(self,load=0x80010000):
        body=bytearray(64);target=load+24;base=load
        words=(0x3c030000|((target+0x8000)>>16&0xffff),0x24630000|(target&0xffff),
            0x3c020000|((base+0x8000)>>16&0xffff),0x24420000|(base&0xffff),0x00621823,0xa6a30002)
        struct.pack_into('<6I',body,0,*words);struct.pack_into('<I',body,24,0xae2000ec)
        analysis=dict(schema='psxrecomp static analysis v1',static_only=True,load_address=load,image_size=len(body),
            functions=[dict(addr=load,end=load+64,partial=False,is_data=False)])
        return load,body,analysis

    def test_relative_resume_store_preserves_host_and_signed_literal_carry(self):
        for load in (0x80010000,0x80018000):
            load,body,analysis=self.resume_fixture(load)
            entries,aliases,proofs=local_control_entries(analysis,load,body)
            self.assertEqual(entries,{load+24});self.assertEqual(aliases,{(load+24,load,load+64)})
            self.assertEqual(proofs[0]['kind'],'stored_local_resume_pc')
            self.assertEqual(proofs[0]['relative_offset'],24)

    def test_resume_store_requires_exact_next_pc_registers_and_object_field(self):
        load,body,analysis=self.resume_fixture()
        for offset,value in [(0,0x34038001),(4,0x2463001c),(4,0x24640018),(8,0x3c028002),
                (12,0x24420040),(16,0x00621821),(20,0xa6a30004),(20,0xa5030002),(20,0xa6a40002)]:
            changed=bytearray(body);struct.pack_into('<I',changed,offset,value)
            self.assertEqual(local_control_entries(analysis,load,changed)[0],set())
        changed=bytearray(68);changed[4:]=body;struct.pack_into('<I',changed,0,0x08004000)
        moved=copy.deepcopy(analysis);moved.update(image_size=68);moved['functions'][0]['end']+=4
        self.assertEqual(local_control_entries(moved,load,changed)[0],set())

    def test_cross_host_direct_jump_preserves_destination_host_as_alias(self):
        load,body,analysis,_=self.fixture()
        analysis['functions']=[dict(addr=load,end=load+16,partial=False,is_data=False),dict(addr=load+24,end=load+48,partial=False,is_data=False)]
        struct.pack_into('<2I',body,0,0x08004008,0) # J 80010020, inside the second known host.
        entries,aliases,proofs=local_control_entries(analysis,load,body)
        self.assertEqual(entries,{load+32});self.assertEqual(aliases,{(load+32,load+24,load+48)})
        self.assertEqual(proofs[0]['kind'],'direct_j_to_known_code')
        changed=bytearray(body);struct.pack_into('<I',changed,0,0x10000007)
        self.assertEqual(local_control_entries(analysis,load,changed)[0],{load+32})
        for conditional in (0x10200007,0x14200007,0x04200007,0x04210007,0x18200007,0x1c200007):
            changed=bytearray(body);struct.pack_into('<I',changed,0,conditional)
            self.assertEqual(local_control_entries(analysis,load,changed)[0],{load+32})
        for conditional in (0x14000007,0x04000007,0x1c000007,0x18210007):
            changed=bytearray(body);struct.pack_into('<I',changed,0,conditional)
            self.assertEqual(local_control_entries(analysis,load,changed)[0],set())
        for offset,value in [(0,0x08005000),(4,0x03e00008),(4,0x0000000c)]:
            changed=bytearray(body);struct.pack_into('<I',changed,offset,value)
            self.assertEqual(local_control_entries(analysis,load,changed)[0],set())
        changed=copy.deepcopy(analysis);changed['functions'][1]['is_data']=True
        self.assertEqual(local_control_entries(changed,load,body)[0],set())

    def test_local_saved_register_literal_requires_in_host_target_and_matching_jr(self):
        load,body,analysis,_=self.fixture();analysis['functions']=[dict(addr=load,end=load+48,partial=False,is_data=False)]
        struct.pack_into('<4I',body,0,0x3c158001,0x26b50020,0x02a00008,0)
        struct.pack_into('<2I',body,32,0x03e00008,0)
        entries,aliases,proofs=local_control_entries(analysis,load,body)
        self.assertEqual(entries,{load+32});self.assertEqual(aliases,{(load+32,load,load+48)})
        self.assertEqual(proofs[0]['register'],21)
        for offset,value in [(0,0x3c158002),(4,0x26b40020),(4,0x26b50030),(8,0x02800008),(12,0x03e00008)]:
            changed=bytearray(body);struct.pack_into('<I',changed,offset,value)
            self.assertEqual(local_control_entries(analysis,load,changed)[0],set())
        scheduled=bytearray(body);struct.pack_into('<5I',scheduled,0,0x3c028001,0xafb50024,0x24550020,0x02a00008,0)
        self.assertEqual(local_control_entries(analysis,load,scheduled)[0],{load+32})
        for gap in [0x24420001,0x10000000]:
            changed=bytearray(scheduled);struct.pack_into('<I',changed,4,gap)
            self.assertEqual(local_control_entries(analysis,load,changed)[0],set())

    def test_masked_return_table_requires_exact_producer_and_every_possible_stub(self):
        load=0x80010000;body=bytearray(64)
        struct.pack_into('<7I',body,0,0x3c028001,0x2442001c,0x00821823,0x30630018,0x00431021,0x00400008,0)
        for offset in range(28,60,8):struct.pack_into('<2I',body,offset,0x03e00008,0)
        analysis=dict(schema='psxrecomp static analysis v1',static_only=True,load_address=load,image_size=len(body),
            functions=[dict(addr=load,end=load+36,partial=False,is_data=False)])
        entries,aliases,proofs=masked_return_tables(analysis,load,body)
        self.assertEqual(entries,set(range(load+28,load+60,8)))
        self.assertEqual(aliases,{(load+28,load,load+36)});self.assertEqual(proofs[0]['entries'],4)
        for offset in [0,4,8,12,16,20,24,28,36,44,52,56]:
            changed=bytearray(body);changed[offset]^=1
            self.assertEqual(masked_return_tables(analysis,load,changed)[0],set())
        for mask in [0x10,0x1f,0xfff8,0x38]:
            changed=bytearray(body);struct.pack_into('<I',changed,12,0x30630000|mask)
            self.assertEqual(masked_return_tables(analysis,load,changed)[0],set())

    def test_uncached_callback_requires_literal_conversion_and_known_returning_target(self):
        load=0x80010000;body=bytearray(64)
        words=(0x3c028001,0x24420030,0x3c04a000,0x00442025,0x0c004000,0x34050001)
        struct.pack_into('<6I',body,0,*words)
        struct.pack_into('<2I',body,48,0x03e00008,0)
        analysis=dict(schema='psxrecomp static analysis v1',static_only=True,load_address=load,image_size=len(body),functions=[
            dict(addr=load,end=load+32,partial=False,is_data=False,ends_jr_ra=True),
            dict(addr=load+48,end=load+56,partial=False,is_data=False,ends_jr_ra=True)])
        entries,proofs=uncached_callbacks(analysis,load,body)
        self.assertEqual(entries,[0xa0010030]);self.assertEqual(proofs[0]['registration_pc'],hex(load))
        for index,value in [(0,0x3c028002),(1,0x24430030),(2,0x3c04b000),(3,0x00441825),(4,0x08004000),(5,0x03e00008),(5,0x34040001)]:
            changed=bytearray(body);struct.pack_into('<I',changed,index*4,value)
            self.assertEqual(uncached_callbacks(analysis,load,changed)[0],[])
        changed=copy.deepcopy(analysis);changed['functions'][1]['partial']=True
        self.assertEqual(uncached_callbacks(changed,load,body)[0],[])

    def test_uncached_compile_view_has_only_proven_roots_and_preserves_source(self):
        source=dict(load_addr='0x80010000',size=64,bytes_b64='unchanged',executed_pcs=[],
            function_entry_pcs=['0x80010000','0x80010020'],dispatch_entry_segments=dict(kseg0=['0x80010000']),
            static_call_continuation_pcs=['0x80010018'],source_uncached_callback_entries=['0xa0010030'])
        original=copy.deepcopy(source);records=compile_segment_records([source]);self.assertEqual(source,original)
        self.assertEqual(len(records),2);view=records[1]
        self.assertEqual(view['load_addr'],'0xA0010000');self.assertEqual(view['function_entry_pcs'],['0xa0010030'])
        self.assertEqual(view['bytes_b64'],source['bytes_b64']);self.assertEqual(view['executed_pcs'],[])
        self.assertNotIn('dispatch_entry_segments',view);self.assertNotIn('static_call_continuation_pcs',view)
        for entry in ['0x80010030','0xa0010040','0xa0010031']:
            with self.assertRaises(ValueError):compile_segment_records([dict(source,source_uncached_callback_entries=[entry])])

    def test_isolated_callback_pointer_requires_noncode_slot_and_bounded_verification(self):
        load,body,analysis,_=self.fixture()
        function=dict(addr=load+8,end=load+24,partial=False,is_data=False,has_prologue=False,ends_jr_ra=True,sig=dict(leaf=True))
        analysis['functions']=[function];struct.pack_into('<I',body,48,load+8)
        verifier=dict(_callable_boundary=lambda *args:True,co=SimpleNamespace(plausible_callable_target=lambda *args,**kwargs:True))
        with patch('static_dispatches._extractor',return_value=verifier):
            roots,proofs=source_referenced_callbacks('.',analysis,load,body)
            self.assertEqual(roots,[load+8]);self.assertEqual(proofs[0]['pointer_slots'],[hex(load+48)])
            for field,value in [('partial',True),('is_data',True),('ends_jr_ra',False)]:
                changed=copy.deepcopy(analysis);changed['functions'][0][field]=value
                self.assertEqual(source_referenced_callbacks('.',changed,load,body)[0],[])
            changed=copy.deepcopy(analysis);changed['functions'][0].update(has_prologue=True,sig=dict(leaf=False))
            self.assertEqual(source_referenced_callbacks('.',changed,load,body)[0],[load+8])
            verifier['co']=SimpleNamespace(plausible_callable_target=lambda *args,**kwargs:False)
            self.assertEqual(source_referenced_callbacks('.',analysis,load,body)[0],[])
            verifier['co']=SimpleNamespace(plausible_callable_target=lambda *args,**kwargs:True)
            verifier['_callable_boundary']=lambda *args:False
            self.assertEqual(source_referenced_callbacks('.',analysis,load,body)[0],[])
            verifier['_callable_boundary']=lambda *args:True
            changed=bytearray(body);struct.pack_into('<I',changed,48,0);struct.pack_into('<I',changed,16,load+8)
            self.assertEqual(source_referenced_callbacks('.',analysis,load,changed)[0],[])

    def method_fixture(self):
        load=0x80010000;body=bytearray(128);functions=[]
        for offset in range(0,40,8):
            struct.pack_into('<2I',body,offset,0x03e00008,0x24020001)
            functions.append(dict(addr=load+offset,end=load+offset+8,partial=False,is_data=False,ends_jr_ra=True))
        struct.pack_into('<8I',body,80,load+8,load+16,load+24,0,load+32,0,0,0)
        return load,body,dict(schema='psxrecomp static analysis v1',static_only=True,load_address=load,image_size=128,functions=functions)

    def test_dense_method_table_admits_null_padded_known_callable_entries(self):
        load,body,analysis=self.method_fixture()
        roots,proofs=nullable_function_tables(analysis,load,body)
        self.assertEqual(roots,[load+8,load+16,load+24,load+32])
        self.assertEqual(proofs[0]['table_base'],hex(load+80));self.assertEqual(proofs[0]['table_end'],hex(load+100))
        self.assertEqual(proofs[0]['entries'][-1],dict(slot=hex(load+96),target=hex(load+32)))
        changed=copy.deepcopy(analysis);changed['functions'][4]['is_data']=True
        self.assertNotIn(load+32,nullable_function_tables(changed,load,body)[0])

    def test_sparse_interiors_code_and_unbounded_nulls_are_not_method_proofs(self):
        load,body,analysis=self.method_fixture()
        for table in [(load+8,load+8,load+8,0,load+32), (load+8,load+16,0,0,load+32)]:
            changed=bytearray(body);struct.pack_into('<5I',changed,80,*table)
            self.assertEqual(nullable_function_tables(analysis,load,changed)[0],[])
        for tail in [(load+36,load+32,0,0,0),(0,0,0,load+32,0),(0xffffffff,load+32,0,0,0)]:
            changed=bytearray(body);struct.pack_into('<5I',changed,92,*tail)
            self.assertNotIn(load+32,nullable_function_tables(analysis,load,changed)[0])
        changed=copy.deepcopy(analysis);changed['functions'].append(dict(addr=load+80,end=load+112,partial=False,is_data=False,ends_jr_ra=False))
        self.assertEqual(nullable_function_tables(changed,load,body)[0],[])
        changed=copy.deepcopy(analysis);changed['image_size']+=4
        with self.assertRaises(ValueError):nullable_function_tables(changed,load,body)

    def test_conditional_link_branch_supplies_code_entries_not_function_roots(self):
        load,body,analysis,_=self.fixture()
        analysis['functions']=[dict(addr=load+8,end=load+24,partial=False,is_data=False),dict(addr=load+32,end=load+48,partial=False,is_data=False)]
        struct.pack_into('<2I',body,12,0x05d00006,0) # BLTZAL t6,80010028.
        entries,aliases,proofs=link_branch_dispatches(analysis,load,body,{load+8})
        self.assertEqual(entries,{load+20,load+40})
        self.assertEqual(aliases,{(load+20,load+8,load+24),(load+40,load+32,load+48)})
        self.assertEqual(proofs[0]['target'],load+40)
        self.assertEqual(link_branch_dispatches(analysis,load,body,set())[0],set())
        struct.pack_into('<I',body,12,0x05c00006) # Ordinary BLTZ has no link-call proof.
        self.assertEqual(link_branch_dispatches(analysis,load,body,{load+8})[0],set())
    def test_syscall_return_is_an_interior_with_no_new_function_boundary(self):
        load,body,analysis,_=self.fixture();struct.pack_into('<I',body,16,0x0000000c)
        proofs=syscall_returns(analysis,load,body,{load+8})
        self.assertEqual(proofs,[dict(host_entry=load+8,host_end=load+40,syscall_pc=load+16,return_pc=load+20,instruction=12)])
        self.assertEqual(syscall_returns(analysis,load,body,set()),[])
        struct.pack_into('<I',body,12,0x10000000) # Syscall in a branch delay slot needs a different EPC proof.
        self.assertEqual(syscall_returns(analysis,load,body,{load+8}),[])
    def fixture(self):
        load=0x80010000;body=bytearray(64)
        struct.pack_into('<I',body,16,0x00400008)
        struct.pack_into('<2I',body,48,load+24,load+28)
        analysis=dict(schema='psxrecomp static analysis v1',static_only=True,load_address=load,image_size=64,
            functions=[dict(addr=load+8,end=load+40,partial=False,is_data=False)])
        indirect=dict(schema='psxrecomp indirect sites v1',sites=[dict(func=load+8,pc=load+16,kind='jr',reg=2,
            classification='jump_table:guarded',table_base=load+48,table_count=2,targets=[load+24,load+28])])
        return load,body,analysis,indirect

    def test_guarded_table_preserves_interiors_without_inventing_function_roots(self):
        load,body,analysis,indirect=self.fixture()
        targets,aliases,proofs=guarded_jump_tables(analysis,indirect,load,body)
        self.assertEqual(targets,{load+24,load+28});self.assertEqual(aliases,{(load+24,load+8,load+40),(load+28,load+8,load+40)})
        self.assertEqual(proofs[0]['count'],2);self.assertEqual(len(proofs[0]['table_bytes_sha256']),64)

    def test_stale_table_transfer_count_and_extent_fail_closed(self):
        load,body,analysis,indirect=self.fixture()
        for offset in [16,48]:
            changed=bytearray(body);changed[offset]^=1
            with self.subTest(offset=offset),self.assertRaises(ValueError):guarded_jump_tables(analysis,indirect,load,changed)
        for key,value in [('table_count',3),('table_base',load+60),('reg',3),('pc',load+64)]:
            changed=copy.deepcopy(indirect);changed['sites'][0][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):guarded_jump_tables(analysis,changed,load,body)

    def test_unproven_or_cross_function_tables_do_not_gain_entries(self):
        load,body,analysis,indirect=self.fixture()
        changed=copy.deepcopy(indirect);changed['sites'][0]['classification']='unresolved'
        self.assertEqual(guarded_jump_tables(analysis,changed,load,body)[0],set())
        changed=copy.deepcopy(analysis);changed['functions'][0]['is_data']=True
        self.assertEqual(guarded_jump_tables(changed,indirect,load,body)[0],set())
        changed=bytearray(body);struct.pack_into('<I',changed,48,load+44)
        other=copy.deepcopy(indirect);other['sites'][0]['targets'][0]=load+44
        self.assertEqual(guarded_jump_tables(analysis,other,load,changed)[0],set())


if __name__=='__main__':unittest.main()
