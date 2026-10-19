import base64,hashlib,struct,sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from game_installed_aot import installed_game_records,initialized_image_record,initialized_compile_record,PALETTE_LAYOUTS


class GameInstalledTests(unittest.TestCase):
    def test_initialized_guidance_retains_only_unchanged_observed_prefixes_as_hints(self):
        import copy
        body=self.fixture();source=dict(producer='verified_psx_exe_lz1',producer_name='JM1/MAIN.PEX',
            load_addr='0x800B0000',size=len(body),bytes_b64=base64.b64encode(body).decode(),executed_pcs=[],
            dispatch_entry_pcs=[],static_dispatch_entry_pcs=[],function_entry_pcs=['0x800F4A6C'])
        with patch.dict(PALETTE_LAYOUTS['jf1'],{'JM1/MAIN.PEX':self.layout(body)}):
            initialized,_=initialized_image_record('jf1',source,'verified source')
        before=copy.deepcopy(initialized);source['executed_pcs']=['0x800F27F0','0x800F68B0']
        result,proof=initialized_compile_record(initialized,source)
        self.assertEqual(initialized,before);self.assertEqual(result['bytes_b64'],initialized['bytes_b64'])
        self.assertEqual(result['executed_pcs'],['0x800F27F0']);self.assertIn('0x800F27F0',result['dispatch_entry_segments']['kseg0'])
        self.assertEqual(result['function_entry_pcs'],initialized['function_entry_pcs'])
        self.assertEqual(result['static_dispatch_entry_pcs'],initialized['static_dispatch_entry_pcs'])
        self.assertEqual(proof['excluded_changed_prefixes'],['0x800F68B0'])
        for pc in ['0x800A0000','0x800F27F1','0x80100000']:
            with self.assertRaises(ValueError):initialized_compile_record(initialized,dict(source,executed_pcs=[pc]))

    def test_initialized_guidance_rejects_incompatible_image_metadata(self):
        source=dict(producer='verified_psx_exe_lz1',load_addr='0x80010000',size=16,bytes_b64=base64.b64encode(bytes(16)).decode())
        installed=dict(source,producer='verified_game_installed_code',producer_name='GAME/X-INITIALIZED-80140000')
        for field,value in [('producer','unverified'),('load_addr','0x80020000'),('size',20),('bytes_b64','AA==')]:
            with self.assertRaises(ValueError):initialized_compile_record(dict(installed,**{field:value}),source)

    def fixture(self):
        body=bytearray(0x50000);load=0x800b0000
        writer=(0x27bdfffc,0xafbf0000,0x3c02800f,0x244268b0,0xa4440004,0x00042402,0xa4440000,
                0x00402021,0x0c039dc7,0,0x24840004,0x0c039dc7,0,0x8fbf0000,0x27bd0004,0x03e00008,0)
        struct.pack_into('<17I',body,0x800f42f4-load,*writer)
        struct.pack_into('<4I',body,0x800e5398-load,0x3c048014,0x24841c88,0x0c03d0bd,0)
        struct.pack_into('<2I',body,0x800f68b0-load,0x3c080000,0x35080000)
        return bytes(body)

    def derive(self,body):
        with patch.dict(PALETTE_LAYOUTS['jf1'],{'JM1/MAIN.PEX':self.layout(body)}):
            return installed_game_records('jf1','JM1/MAIN.PEX','verified disc file',0x800b0000,body)

    def layout(self,body):
        return dict(PALETTE_LAYOUTS['jf1']['JM1/MAIN.PEX'],body_sha256=hashlib.sha256(body).hexdigest(),
            template_sha256=hashlib.sha256(self.fixture()[0x468b0:0x46928]).hexdigest())

    def test_literal_constructor_changes_only_two_halfwords(self):
        body=self.fixture();records,proofs=self.derive(body);record=records[0]
        original=body[0x468b0:0x46928];constructed=base64.b64decode(record['bytes_b64'])
        self.assertEqual(struct.unpack_from('<2I',constructed),(0x3c088014,0x35081c88))
        self.assertEqual(constructed[8:],original[8:])
        self.assertEqual(record['executed_pcs'],[]);self.assertEqual(record['function_entry_pcs'],[])
        self.assertEqual(record['dispatch_entry_segments']['kseg1'],['0xA00F68B0'])
        self.assertFalse(proofs[0]['runtime_capture_used'])
        self.assertEqual(proofs[0]['argument'],'0x80141c88')

    def test_changed_writer_argument_template_or_identity_cannot_authorize_variant(self):
        body=self.fixture()
        with self.assertRaises(ValueError):installed_game_records('jf1','JM1/MAIN.PEX','source',0x800b0000,body)
        for offset in [0x442f4,0x44304,0x4430c,0x35398,0x3539c,0x353a0,0x468b0,0x468b4,0x468c0]:
            changed=bytearray(body);changed[offset]^=1
            with self.subTest(offset=hex(offset)),self.assertRaises(ValueError):self.derive(changed)
        self.assertEqual(installed_game_records('jf2','JM1/MAIN.PEX','',0,b''),([],[]))
        self.assertEqual(installed_game_records('jf1','OTHER.PEX','',0,b''),([],[]))

    def test_initialized_image_preserves_every_other_byte_and_static_metadata(self):
        body=self.fixture()
        source=dict(producer='verified_psx_exe_lz1',producer_name='JM1/MAIN.PEX',
            load_addr='0x800B0000',size=len(body),bytes_b64=base64.b64encode(body).decode(),
            executed_pcs=[],dispatch_entry_pcs=['0x800F568C'],static_dispatch_entry_pcs=['0x800F568C'],
            function_entry_pcs=['0x800F4A6C'],static_alias_ranges=[dict(entry='0x800F568C',start='0x800F568C',end='0x800F5DDC')])
        with patch.dict(PALETTE_LAYOUTS['jf1'],{'JM1/MAIN.PEX':self.layout(body)}):
            record,proof=initialized_image_record('jf1',source,'verified disc file')
            changed=base64.b64decode(record['bytes_b64']);expected=bytearray(body)
            struct.pack_into('<H',expected,0x468b0,0x8014);struct.pack_into('<H',expected,0x468b4,0x1c88)
            self.assertEqual(changed,bytes(expected))
            self.assertEqual(record['function_entry_pcs'],source['function_entry_pcs'])
            self.assertEqual(record['static_alias_ranges'],source['static_alias_ranges'])
            self.assertEqual(record['executed_pcs'],[])
            self.assertEqual(set(record['dispatch_entry_segments']),{'kseg0'})
            self.assertIn('0x800F568C',record['dispatch_entry_segments']['kseg0'])
            self.assertIn('0x800F4A6C',record['dispatch_entry_segments']['kseg0'])
            self.assertEqual(set(record['required_entry_pcs']),{'0x000F68B0','0x800F68B0','0xA00F68B0'})
            self.assertEqual(proof['code_sha256'],hashlib.sha256(changed).hexdigest())
            self.assertNotIn('0x800F68B0',source['dispatch_entry_pcs'])
            source['executed_pcs']=['0x800F568C']
            with self.assertRaises(ValueError):initialized_image_record('jf1',source,'verified disc file')

    def test_initialized_image_preserves_source_requested_segment_views(self):
        body=self.fixture();source=dict(producer='verified_psx_exe_lz1',producer_name='JM1/MAIN.PEX',
            load_addr='0x800B0000',size=len(body),bytes_b64=base64.b64encode(body).decode(),executed_pcs=[],
            function_entry_pcs=['0x800F4A6C'],dispatch_entry_pcs=['0x800F568C'],static_dispatch_entry_pcs=['0x800F568C'],
            dispatch_entry_segments=dict(kuseg=[],kseg0=['0x800F568C'],kseg1=['0xA00F568C']))
        with patch.dict(PALETTE_LAYOUTS['jf1'],{'JM1/MAIN.PEX':self.layout(body)}):
            record,_=initialized_image_record('jf1',source,'source')
        self.assertEqual(set(record['dispatch_entry_segments']),{'kseg0','kseg1'})
        self.assertIn('0xA00F568C',record['dispatch_entry_segments']['kseg1'])
        self.assertIn('0xA00F68B0',record['dispatch_entry_segments']['kseg1'])
        self.assertEqual(source['dispatch_entry_segments']['kseg1'],['0xA00F568C'])

    def test_empty_segment_map_inherits_all_source_nominations_in_their_original_views(self):
        body=self.fixture();source=dict(producer='verified_psx_exe_lz1',producer_name='JM1/MAIN.PEX',
            load_addr='0x800B0000',size=len(body),bytes_b64=base64.b64encode(body).decode(),executed_pcs=[],
            function_entry_pcs=['0x800F4A6C'],dispatch_entry_pcs=['0x800F568C'],
            static_dispatch_entry_pcs=['0x800F568C','0xA00F5700'],dispatch_entry_segments={})
        with patch.dict(PALETTE_LAYOUTS['jf1'],{'JM1/MAIN.PEX':self.layout(body)}):
            record,proof=initialized_image_record('jf1',source,'source')
        self.assertEqual(set(record['dispatch_entry_segments']),{'kseg0','kseg1'})
        self.assertEqual(set(record['dispatch_entry_segments']['kseg0']),{'0x800F4A6C','0x800F568C','0x800F68B0'})
        self.assertEqual(set(record['dispatch_entry_segments']['kseg1']),{'0xA00F5700','0xA00F68B0'})
        self.assertEqual(source['dispatch_entry_segments'],{})
        self.assertEqual(record['executed_pcs'],[])

    def test_other_world_literal_with_signed_low_halfword_keeps_exact_value(self):
        body=bytearray(self.fixture());struct.pack_into('<4I',body,0x35398,0x3c048014,0x2484e4d0,0x0c03d0bd,0)
        layout=dict(self.layout(body),argument='0x8013e4d0',
            constructor_sha256=hashlib.sha256(body[0x35398:0x353a8]).hexdigest())
        with patch.dict(PALETTE_LAYOUTS['jf1'],{'JM1B/MAIN.PEX':layout}):
            records,_=installed_game_records('jf1','JM1B/MAIN.PEX','source',0x800b0000,body)
        self.assertEqual(records[0]['producer_name'],'GAME/JM1B-PALETTE-8013E4D0')
        self.assertEqual(struct.unpack_from('<2I',base64.b64decode(records[0]['bytes_b64'])),(0x3c088013,0x3508e4d0))

    def test_jf2_uses_its_own_source_layout_and_cannot_share_jf1_identity(self):
        body=self.fixture();layout=self.layout(body)
        with patch.dict(PALETTE_LAYOUTS['jf2'],{'JF2_W1/MAIN.PEX':layout}):
            records,proofs=installed_game_records('jf2','JF2_W1/MAIN.PEX','PAL source',0x800b0000,body)
            self.assertEqual(records[0]['producer_name'],'GAME/JF2_W1-PALETTE-80141C88')
            self.assertEqual(proofs[0]['source_executable_sha256'],'PAL source')
            self.assertEqual(installed_game_records('jf1','JF2_W1/MAIN.PEX','',0,b''),([],[]))


if __name__=='__main__':unittest.main()
