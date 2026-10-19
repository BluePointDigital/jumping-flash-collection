import base64,hashlib,struct,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from sdk_aot import installed_sdk_records,INSTALLER,PAYLOAD


class SdkAotTests(unittest.TestCase):
    def robbit_fixture(self):
        from bios_aot import SIO_INSTALLER,SIO_WORDS,VECTOR_INSTALLER,VECTOR_WORDS
        bios=bytearray(0x80000)
        for offset,words in [(0x15ebc,SIO_INSTALLER),(0x15f08,SIO_WORDS),
                (0x109b0,VECTOR_INSTALLER),(0x10a0c,VECTOR_WORDS),
                (0x104cc,(0x65c,0x668)),(0x1015c,(0x3c020000,0x03e00008,0x24420674,0x3c020000,0x03e00008,0x24420874)),
                (0x1018c,(0xc80,)),(0x104e0,(0x43d0,))]:
            struct.pack_into(f'<{len(words)}I',bios,offset,*words)
        exe=bytearray(2048+0x10000);exe[:8]=b'PS-X EXE';struct.pack_into('<I',exe,0x18,0x80014800)
        for pc,words in [(0x8001e380,(0x3c02a001,0x2442dfac,0x00400008,0,0)),
                        (0x8001e394,(0x3c08a001,0x2508df80,0x0100f809,0,0)),
                        (0x8001e310,tuple(range(28)))]:
            struct.pack_into(f'<{len(words)}I',exe,2048+pc-0x80014800,*words)
        return bytes(bios),bytes(exe)

    def derive_robbit(self,root,bios,exe):
        import sdk_aot
        path=root/'bios.bin';path.write_bytes(bios);digest=hashlib.sha256(bios).hexdigest()
        payloads=list(sdk_aot.ROBBIT_PAYLOADS)
        payloads[2]=(*payloads[2][:4],hashlib.sha256(struct.pack('<28I',*range(28))).hexdigest())
        with patch('sdk_aot.JP_BIOS_SHA',digest),patch('sdk_aot.ROBBIT_BOOT_SHA',hashlib.sha256(exe).hexdigest()),\
             patch('sdk_aot.ROBBIT_INSTALLER_SHA',hashlib.sha256(bytes(0x138)).hexdigest()),\
             patch('sdk_aot.ROBBIT_PAYLOADS',payloads),patch('bios_aot.SUPPORTED_BIOS',{digest}):
            return installed_sdk_records('robbit',exe,path,digest)

    def test_robbit_hooks_keep_both_driver_entries_and_joint_source_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            bios,exe=self.robbit_fixture();records,proofs=self.derive_robbit(Path(temp),bios,exe)
            self.assertEqual([r['size'] for r in records],[20,20,112])
            self.assertEqual(records[2]['dispatch_entry_segments']['kseg1'],['0xA000DF80','0xA000DFAC'])
            self.assertEqual(records[2]['function_entry_pcs'],['0x8000DF80','0x8000DFAC'])
            self.assertTrue(all(not r['executed_pcs'] for r in records))
            self.assertTrue(all(p['source_executable_sha256']==hashlib.sha256(exe).hexdigest() and not p['runtime_capture_used'] for p in proofs))

    def test_robbit_constructor_payload_lookup_and_sio_dependency_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            bios,exe=self.robbit_fixture();root=Path(temp)
            for pc in [0x8001e3c8,0x8001e480,0x8001e4d0,0x8001e380,0x8001e394,0x8001e310]:
                changed=bytearray(exe);changed[2048+pc-0x80014800]^=1
                with self.subTest(pc=hex(pc)),self.assertRaises(ValueError):self.derive_robbit(root,bios,bytes(changed))
            for offset in [0x104cc,0x104d0,0x10164,0x10170,0x1018c,0x104e0,0x15ed4,0x15f0c]:
                changed=bytearray(bios);changed[offset]^=1
                with self.subTest(offset=hex(offset)),self.assertRaises(ValueError):self.derive_robbit(root,bytes(changed),exe)
    def fixture(self):
        bios=bytearray(0x80000)
        struct.pack_into('<I',bios,0x104cc,0x65c)
        struct.pack_into('<3I',bios,0x1015c,0x3c020000,0x03e00008,0x24420674)
        struct.pack_into('<I',bios,0x1018c,0xc80)
        exe=bytearray(2048+188416);exe[:8]=b'PS-X EXE'
        struct.pack_into('<I',exe,0x18,0x80018000)
        struct.pack_into('<26I',exe,2048+0x27fbc-0x18000,*INSTALLER)
        struct.pack_into('<14I',exe,2048+0x28024-0x18000,*PAYLOAD)
        return bytes(bios),bytes(exe)

    def derive(self,root,bios,exe):
        path=root/'bios.bin';path.write_bytes(bios)
        bios_sha=hashlib.sha256(bios).hexdigest();source_sha=hashlib.sha256(exe).hexdigest()
        with patch('sdk_aot.PAL_BIOS_SHA',bios_sha),patch('sdk_aot.JF2_BOOT_SHA',source_sha):
            return installed_sdk_records('jf2',exe,path,bios_sha)

    def test_constructor_payload_and_bios_lookup_prove_all_aliases(self):
        with tempfile.TemporaryDirectory() as temp:
            bios,exe=self.fixture();records,proofs=self.derive(Path(temp),bios,exe)
            self.assertEqual(len(records),1);record=records[0];proof=proofs[0]
            self.assertEqual(struct.unpack('<12I',base64.b64decode(record['bytes_b64'])),PAYLOAD[2:])
            self.assertEqual(record['producer_ranges'],[dict(start='0x80000C88',end='0x80000CB8')])
            self.assertEqual(record['dispatch_entry_segments']['kuseg'],['0x00000C88'])
            self.assertEqual(record['dispatch_entry_segments']['kseg1'],['0xA0000C88'])
            self.assertEqual(record['executed_pcs'],[]);self.assertFalse(proof['runtime_capture_used'])
            self.assertEqual(proof['source_executable_sha256'],hashlib.sha256(exe).hexdigest())

    def test_constructor_payload_and_lookup_mutations_fail_even_with_hashes_updated(self):
        with tempfile.TemporaryDirectory() as temp:
            bios,exe=self.fixture();root=Path(temp)
            for offset in [2048+0x27fd4-0x18000,2048+0x27fe0-0x18000,2048+0x27ff8-0x18000,2048+0x28054-0x18000]:
                changed=bytearray(exe);changed[offset]^=1
                with self.subTest(exe_offset=offset),self.assertRaises(ValueError):self.derive(root,bios,bytes(changed))
            for offset in [0x104cc,0x1015c,0x10164,0x1018c]:
                changed=bytearray(bios);changed[offset]^=1
                with self.subTest(bios_offset=offset),self.assertRaises(ValueError):self.derive(root,bytes(changed),exe)

    def test_unsupported_identity_and_missing_source_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            bios,exe=self.fixture();path=Path(temp)/'bios.bin';path.write_bytes(bios)
            with self.assertRaises(ValueError):installed_sdk_records('jf2',exe,path,hashlib.sha256(bios).hexdigest())
            with self.assertRaises(ValueError):installed_sdk_records('jf2',None,path,hashlib.sha256(bios).hexdigest())
            self.assertEqual(installed_sdk_records('jf1',None,path,''),([],[]))


if __name__=='__main__':unittest.main()
