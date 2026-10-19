import base64,sys,tempfile,unittest,zlib
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from native_entry_coverage import entry_coverage,audited_native_rows


class NativeEntryCoverageTests(unittest.TestCase):
    def test_sealed_pair_read_never_recovers_journal_and_rejects_drift(self):
        from import_game import sha
        with tempfile.TemporaryDirectory() as temp:
            cache=Path(temp);dll=cache/'00010000_12345678.dll';dll.write_bytes(b'native fixture')
            manifest=dll.with_suffix('.ranges');manifest.write_text('fixture manifest',encoding='ascii')
            journal=dll.with_suffix('.journal');journal.write_bytes(b'pending transaction')
            backup=dll.with_suffix('.bak');backup.write_bytes(b'old pair')
            rows=[(0x80010000,123,[(0x80010000,8)])]
            pair=dict(dll=dll.name,dll_sha256=sha(dll),manifest_sha256=sha(manifest),functions=1)
            calls=[]
            def parse(text,**kwargs):
                calls.append((text,kwargs));return 7,rows
            def recover(*args):raise AssertionError('Read-only coverage invoked recovery')
            compiler=SimpleNamespace(parse_runtime_shard_manifest=parse,cache_dir_segment=lambda path:0x80000000,
                _dll_runtime_exports_match=lambda *args:True,load_shard_func_ids=recover)
            before={p.name:p.read_bytes() for p in cache.iterdir()}
            self.assertEqual(audited_native_rows(cache,compiler,30,pair),rows)
            self.assertEqual(calls,[('fixture manifest',dict(require_pair=False,expected_segment=0x80000000))])
            self.assertEqual({p.name:p.read_bytes() for p in cache.iterdir()},before)
            compiler._dll_runtime_exports_match=lambda *args:False
            with self.assertRaisesRegex(ValueError,'exports'):audited_native_rows(cache,compiler,30,pair)
            compiler._dll_runtime_exports_match=lambda *args:True
            with self.assertRaisesRegex(ValueError,'exports'):audited_native_rows(cache,compiler,30,dict(pair,functions=2))
            def change_during_inspection(*args):dll.write_bytes(b'changed');return True
            compiler._dll_runtime_exports_match=change_during_inspection
            with self.assertRaisesRegex(ValueError,'during inspection'):audited_native_rows(cache,compiler,30,pair)
            with self.assertRaisesRegex(ValueError,'pair changed'):audited_native_rows(cache,compiler,30,pair)

    def fixture(self):
        body=bytes(range(64));load=0x80010000
        record=dict(load_addr=hex(load),size=len(body),bytes_b64=base64.b64encode(body).decode(),
            function_entry_pcs=[hex(load+8),hex(load+16)],static_dispatch_entry_pcs=[hex(load+40)])
        def row(offset,correct=True):return (load+offset,zlib.crc32(body[offset:offset+8])^(0 if correct else 1),[(load+offset,8)])
        return record,load,row

    def test_byte_match_does_not_authorize_an_incoherent_sibling_bundle(self):
        record,load,row=self.fixture()
        result=entry_coverage(record,[(load&0x1fffffff,[row(8),row(32,False)]),(load&0x1fffffff,[row(16)]),
                                      (load&0x1fffffff,[row(40,False)])])
        self.assertEqual(result['byte_matched_entries'],2)
        self.assertEqual(result['whole_bundle_byte_matched_entries'],1)
        self.assertEqual(result['incoherent_bundle_only_pcs'],['0x80010008'])
        self.assertEqual(result['missing_byte_variant_pcs'],['0x80010028'])

    def test_virtual_aliases_empty_guards_and_other_producers_do_not_count(self):
        record,load,row=self.fixture();record['function_entry_pcs']=['0xA0010010'];record['static_dispatch_entry_pcs']=[]
        self.assertEqual(entry_coverage(record,[(load&0x1fffffff,[row(16)])])['byte_matched_entries'],0)
        alias=(0xa0010010,row(16)[1],row(16)[2])
        self.assertEqual(entry_coverage(record,[(load&0x1fffffff,[alias])])['whole_bundle_byte_matched_entries'],1)
        self.assertEqual(entry_coverage(record,[(0x20000,[alias]),(0x10000,[(0xa0010010,0,[])])])['byte_matched_entries'],0)

    def test_changed_bounds_and_invalid_nominations_fail_closed(self):
        record,load,row=self.fixture();record['size']+=4
        with self.assertRaises(ValueError):entry_coverage(record,[])
        record['size']-=4;record['static_dispatch_entry_pcs']=['0x80020000']
        with self.assertRaises(ValueError):entry_coverage(record,[])


if __name__=='__main__':unittest.main()
