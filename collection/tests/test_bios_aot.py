import base64,hashlib,struct,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from bios_aot import installed_records,SIO_INSTALLER,SIO_WORDS,VECTOR_INSTALLER,VECTOR_WORDS
from patch_aot_audit import patch as patch_audit


class BiosAotTests(unittest.TestCase):
    def fixture(self):
        data=bytearray(0x80000)
        struct.pack_into('<19I',data,0x15ebc,*SIO_INSTALLER)
        struct.pack_into('<4I',data,0x15f08,*SIO_WORDS)
        struct.pack_into('<11I',data,0x109b0,*VECTOR_INSTALLER)
        struct.pack_into('<4I',data,0x10a0c,*VECTOR_WORDS)
        return data

    def test_exact_constructor_and_all_segment_roots(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'bios.bin';data=self.fixture();digest=hashlib.sha256(data).hexdigest();path.write_bytes(data)
            with patch('bios_aot.SUPPORTED_BIOS',{digest}):
                records,proofs=installed_records(path,digest)
                record,evidence=records[0],proofs[0]
                self.assertEqual(len(records),2)
            self.assertEqual(struct.unpack('<4I',base64.b64decode(record['bytes_b64'])),SIO_WORDS)
            self.assertEqual(record['executed_pcs'],[])
            self.assertEqual(record['dispatch_entry_segments'],dict(kuseg=['0x00000CF0'],kseg0=['0x80000CF0'],kseg1=['0xA0000CF0']))
            self.assertFalse(evidence['runtime_capture_used'])
            self.assertEqual(record['size'],16)

    def test_hash_size_constructor_and_payload_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'bios.bin';data=self.fixture();digest=hashlib.sha256(data).hexdigest();path.write_bytes(data)
            with self.assertRaises(ValueError):installed_records(path,digest)
            for offset in [0x15ebc,0x15ed0,0x15ed4,0x15ee8,0x15f08,0x15f0c,0x15f10,0x109b0,0x109d4,0x10a0c,0x10a14]:
                damaged=bytearray(data);damaged[offset]^=1;bad=hashlib.sha256(damaged).hexdigest();path.write_bytes(damaged)
                with patch('bios_aot.SUPPORTED_BIOS',{bad}),self.assertRaises(ValueError):installed_records(path,bad)
            path.write_bytes(data[:-4])
            with patch('bios_aot.SUPPORTED_BIOS',{digest}),self.assertRaises(ValueError):installed_records(path,digest)

    def test_segment_audit_patch_is_idempotent_and_rejects_drift(self):
        source=Path(__file__).resolve().parents[2]/'jumping-flash-1/.workbench/psxrecomp/tools/audit_aot_cache.py'
        with tempfile.TemporaryDirectory() as temp:
            framework=Path(temp);directory=framework/'tools';directory.mkdir()
            target=directory/'audit_aot_cache.py';target.write_bytes(source.read_bytes())
            patch_audit(framework);before=target.read_bytes();patch_audit(framework)
            self.assertEqual(before,target.read_bytes())
            compile(before,str(target),'exec')
            self.assertIn(b"served = {item[0] for item in compatible}",before)
            function=before.decode().split('    def contains_shard_base(',1)[1].split('\n    def within_bounds',1)[0]
            namespace={};exec('def contains_shard_base('+function,namespace)
            contains=namespace['contains_shard_base']
            self.assertTrue(contains(0x80010000,bytes(64),0x10020))
            self.assertFalse(contains(0x80010000,bytes(64),0x10040))
            self.assertFalse(contains(0x80010000,bytes(64),0xfffc))
            self.assertTrue(contains(0x80010000,bytes(64),None))
            self.assertIn(b'known and len(compiler.current_variant_func_ids(ids, data, load, len(data))) == len(ids)',before)
            target.write_text('# upstream drift',encoding='utf-8')
            with self.assertRaises(ValueError):patch_audit(framework)


if __name__=='__main__':unittest.main()
