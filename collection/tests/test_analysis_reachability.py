import copy,struct,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from analysis_reachability import terminal_jump_roots


class TerminalJumpTests(unittest.TestCase):
    def fixture(self):
        load=0x80010000;body=bytearray(64)
        struct.pack_into('<2I',body,0,0x08004008,0) # CRT terminal J 80010020; NOP.
        def function(lo,size,reachable,returns):
            return dict(addr=lo,end=lo+size,size=size,reachable=reachable,ends_jr_ra=returns,partial=False,is_data=False)
        analysis=dict(schema='psxrecomp static analysis v1',static_only=True,load_address=load,image_size=64,
            functions=[function(load,8,True,False),function(load+32,16,False,True),function(load+48,16,False,True)])
        edges=dict(schema='psxrecomp call edges v1',edges=[dict(**{'from':load+32,'to':load+48},pc=load+36,kind='address_taken')])
        return load,body,analysis,edges

    def test_crt_jump_reaches_main_and_its_registered_callback(self):
        load,body,analysis,edges=self.fixture()
        roots,proof=terminal_jump_roots(analysis,edges,load,body)
        self.assertEqual(roots,[load+32,load+48]);self.assertEqual(len(proof['terminal_edges']),1)
        self.assertFalse(proof['runtime_evidence_used'])

    def test_interior_control_delay_and_noncode_targets_are_not_roots(self):
        load,body,analysis,edges=self.fixture()
        for target in [load+36,load+64]:
            changed=bytearray(body);struct.pack_into('<I',changed,0,0x08000000|((target>>2)&0x03ffffff))
            self.assertEqual(terminal_jump_roots(analysis,edges,load,changed)[0],[])
        changed=bytearray(body);struct.pack_into('<I',changed,4,0x03e00008)
        self.assertEqual(terminal_jump_roots(analysis,edges,load,changed)[0],[])
        for flag in ['partial','is_data']:
            changed=copy.deepcopy(analysis);changed['functions'][1][flag]=True
            self.assertEqual(terminal_jump_roots(changed,edges,load,body)[0],[])

    def test_stale_image_and_function_bounds_fail_closed(self):
        load,body,analysis,edges=self.fixture()
        changed=copy.deepcopy(analysis);changed['image_size']=60
        with self.assertRaises(ValueError):terminal_jump_roots(changed,edges,load,body)
        changed=copy.deepcopy(analysis);changed['functions'][1]['end']=load+80
        with self.assertRaises(ValueError):terminal_jump_roots(changed,edges,load,body)
        changed=copy.deepcopy(analysis);changed['static_only']=False
        with self.assertRaises(ValueError):terminal_jump_roots(changed,edges,load,body)

    def test_split_preframe_prelude_reaches_frame_and_address_taken_callback(self):
        load,body,analysis,edges=self.fixture()
        analysis['functions'][0].update(end=load+32,size=32)
        struct.pack_into('<8I',body,0,0x30830001,0x00832023,0x8c820000,0x00031b40,0x10400014,0,0x30c20003,0x00c23023)
        roots,proof=terminal_jump_roots(analysis,edges,load,body)
        self.assertEqual(roots,[load+32,load+48]);self.assertEqual(proof['fallthrough_edges'][0]['target'],hex(load+32))
        for offset,word in [(16,0x10000014),(16,0x08004008),(20,0x03e00008),(28,0x03e00008)]:
            changed=bytearray(body);struct.pack_into('<I',changed,offset,word)
            self.assertEqual(terminal_jump_roots(analysis,edges,load,changed)[0],[])
        changed=copy.deepcopy(analysis);changed['functions'][0].update(end=load+28,size=28)
        self.assertEqual(terminal_jump_roots(changed,edges,load,body)[0],[])

    def test_source_proven_method_root_propagates_to_its_callees(self):
        load,body,analysis,edges=self.fixture();struct.pack_into('<2I',body,0,0,0)
        self.assertEqual(terminal_jump_roots(analysis,edges,load,body)[0],[])
        roots,proof=terminal_jump_roots(analysis,edges,load,body,[load+32])
        self.assertEqual(roots,[load+32,load+48]);self.assertEqual(proof['additional_roots'],[hex(load+32)])
        with self.assertRaises(ValueError):terminal_jump_roots(analysis,edges,load,body,[load+36])


if __name__=='__main__':unittest.main()
