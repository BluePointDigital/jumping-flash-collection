import struct
import base64
import sys
from pathlib import Path
import unittest
import json,tempfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from aot import decode_executable,guarded_title_seeds,analysis_function_roots,observed_dispatch_entries,runtime_guidance,verified_repair_entries,isolate_repair_record,preserve_compile_log

class AotTests(unittest.TestCase):
    def test_resume_keeps_exact_previous_logs_and_refuses_changed_archives(self):
        with tempfile.TemporaryDirectory() as temp:
            output=Path(temp);log=output/'compile.log'
            self.assertIsNone(preserve_compile_log(output))
            log.write_bytes(b'first compile\r\n\xff')
            first=preserve_compile_log(output);self.assertEqual(first.read_bytes(),log.read_bytes())
            before=first.stat().st_mtime_ns
            self.assertEqual(preserve_compile_log(output),first)
            self.assertEqual(first.stat().st_mtime_ns,before)
            log.write_bytes(b'second compile\n');second=preserve_compile_log(output)
            self.assertNotEqual(first,second);self.assertEqual(first.read_bytes(),b'first compile\r\n\xff')
            second.write_bytes(b'changed archive')
            with self.assertRaisesRegex(ValueError,'archive changed'):preserve_compile_log(output)
            self.assertEqual(log.read_bytes(),b'second compile\n')

    def test_repair_extent_excludes_unrelated_owners_and_keeps_disc_bytes(self):
        import zlib
        with tempfile.TemporaryDirectory() as temp:
            cache=Path(temp);body=bytes(range(64));pc=0x80010008
            record=dict(producer_name='WORLD.PEX',load_addr='0x80010000',size=64,
                bytes_b64=base64.b64encode(body).decode(),dispatch_entry_segments={},
                source_uncached_callback_entries=['0xA0010030'],
                static_alias_ranges=[dict(entry='0x80010030',start='0x80010020',end='0x80010040')],
                static_call_continuation_pcs=['0x80010030'],static_jump_table_proofs=[dict(host_entry='0x80010020')])
            manifest=cache/'part.ranges'
            manifest.write_text(f'F {pc:08X} {zlib.crc32(body[8:24]):08X}\nR {pc:08X} 10\nF 80010030 00000000\nR 80010030 10\n')
            isolated,proof=isolate_repair_record(record,pc,cache)
            self.assertEqual(base64.b64decode(isolated['bytes_b64']),body[8:24])
            self.assertEqual(isolated['function_entry_pcs'],[])
            self.assertEqual(isolated['static_dispatch_entry_pcs'],[])
            self.assertEqual(isolated['executed_pcs'],[f'0x{pc:08X}'])
            self.assertEqual(proof['range'],[hex(pc),hex(pc+16)])
            self.assertFalse(any(key in isolated for key in ('static_alias_ranges','static_call_continuation_pcs','static_jump_table_proofs')))
            from static_dispatches import compile_segment_records
            self.assertNotIn('source_uncached_callback_entries',isolated)
            self.assertEqual(compile_segment_records([isolated]),[isolated])
            changed=bytearray(body);changed[8]^=1
            with self.assertRaisesRegex(ValueError,'no native guard'):
                isolate_repair_record(dict(record,bytes_b64=base64.b64encode(changed).decode()),pc,cache)
    def test_isolated_repair_requires_observed_dispatch_in_one_selected_image(self):
        body=bytes(range(64))
        capture=dict(load_addr='0x80010000',size=64,bytes_b64=base64.b64encode(body).decode(),
            executed_pcs=['0x80010004'],dispatch_entry_pcs=['0x80010004','0x80010008'])
        observed=observed_dispatch_entries([capture],0x80010000,body)
        records=[dict(producer_name='WORLD.PEX',executed_pcs=[hex(pc) for pc in observed])]
        self.assertEqual(verified_repair_entries([0x80010004],['WORLD.PEX'],records),[0x80010004])
        for images,entries in [([], [0x80010004]),(['WORLD.PEX','OTHER.PEX'],[0x80010004]),
                              (['WORLD.PEX'],[0x80010008]),(['WORLD.PEX'],[0x80010005]),
                              (['WORLD.PEX'],[0xa0010004])]:
            with self.subTest(images=images,entries=entries),self.assertRaises(ValueError):
                verified_repair_entries(entries,images,records)
    def image(self,load=0x80010000,entry=0x80010000,size=4):
        header=bytearray(2048);header[:8]=b'PS-X EXE'
        struct.pack_into('<IIII',header,16,entry,0,load,size)
        return bytes(header)+b'abcd'
    def test_exact_bounds_and_decode(self):
        def unexpected(_):raise AssertionError('Uncompressed image must not decode')
        self.assertEqual(decode_executable(self.image(),unexpected),(0x80010000,0x80010000,b'abcd'))
        self.assertEqual(decode_executable(self.image(size=8),lambda _:b'abcdefgh')[2],b'abcdefgh')
    def test_bad_bounds_entry_and_length_rejected(self):
        for raw in (self.image(load=0x801ffffe),self.image(entry=0x80020000),self.image(size=0),b'bad'):
            with self.assertRaises(ValueError):decode_executable(raw,lambda _:b'abcd')
        with self.assertRaises(ValueError):decode_executable(self.image(size=8),lambda _:b'x')
    def test_robbit_roots_require_complete_authored_fingerprint(self):
        load=0x80052000;body=bytearray(0x800d1000-load)
        guards={0x800a2778:0x27bdffb8,0x800a2784:0x2471bc00,0x800a4414:0x0c01e5ae,
            0x800a4554:0xae220010,0x800a24c0:0x2451bc00,0x8008a464:0xa4430d90,
            0x800adac4:0x8c43101c,0x800a3f5c:0x0c026703,0x800a6844:0x0c026703,0x80099c0c:0x10a00016}
        for address,word in guards.items():struct.pack_into('<I',body,address-load,word)
        # The old sparse fingerprint must not authorize a fabricated image.
        # Known requests now require their complete verified source body.
        self.assertEqual(guarded_title_seeds('robbit',load,body),[])
        with self.assertRaises(ValueError):guarded_title_seeds('robbit',load,body,'EVENT/00/M01.PEX')
        self.assertNotIn(0x800a441c,guarded_title_seeds('robbit',load,body))
        self.assertEqual(guarded_title_seeds('jf2',load,body),[])
        self.assertEqual(guarded_title_seeds('robbit',load,body[:64]),[])
        for address in guards:
            damaged=bytearray(body);damaged[address-load]^=1
            self.assertEqual(guarded_title_seeds('robbit',load,damaged),[])
    def test_analyzed_roots_exclude_data_and_validate_extents(self):
        header='addr\tsize\tconfidence\n'
        table=header+'0x80010000\t16\tverified\n0x80010010\t8\thigh\n0x80010018\t8\tdata\n0x80010020\t8\tmedium\n'
        self.assertEqual(analysis_function_roots(table,0x80010000,64),[0x80010000,0x80010010])
        for row in ('0x80010002\t8\thigh\n','0x80010000\t68\tverified\n','0x80010000\t6\thigh\n'):
            with self.assertRaises(ValueError):analysis_function_roots(header+row,0x80010000,64)
        with self.assertRaises(ValueError):analysis_function_roots(header+'0x80010000\t16\tdata\n',0x80010000,64)
        self.assertEqual(analysis_function_roots(header+'0x80010000\t16\tdata\n',0x80010000,64,allow_empty=True),[])
    def test_observed_dispatches_require_exact_static_instruction_prefix(self):
        body=bytes(range(64));record=dict(load_addr='0xA0010000',size=64,
            bytes_b64=base64.b64encode(body).decode(),
            executed_pcs=['0x80010004','0x80010008','0x8001000C'],
            dispatch_entry_pcs=['0xA0010004','0x80010008','0x80010010','0x80010033','0x8001003C','0x80020000'])
        self.assertEqual(observed_dispatch_entries([record],0x80010000,body),[0x80010004,0x80010008])
        damaged=bytearray(body);damaged[8]^=1
        self.assertEqual(observed_dispatch_entries([record],0x80010000,damaged),[])
        with self.assertRaises(ValueError):observed_dispatch_entries([dict(record,size=4)],0x80010000,body)
    def test_guidance_retains_earlier_images_and_rejects_unclean_runs(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);receipt=root/'performance-receipt.json';captures=root/'overlay_captures.json'
            data=dict(game='jf1',exit_code=0,errors=[],final_input=dict(gameplay=1),executable_sha256='a'*64)
            receipt.write_text(json.dumps(data));captures.write_text('[{"image":"world"}]')
            history=root/'overlay_captures.json.d';history.mkdir()
            (history/'earlier.json').write_text('[{"image":"title"}]')
            records,provenance=runtime_guidance(receipt,'jf1')
            self.assertEqual([r['image'] for r in records],['world','title'])
            self.assertEqual(len(provenance['capture_files']),2)
            self.assertEqual(len(provenance['capture_files'][1]['sha256']),64)
            with self.assertRaises(ValueError):runtime_guidance(receipt,'robbit')
            data['exit_code']=86;receipt.write_text(json.dumps(data))
            with self.assertRaises(ValueError):runtime_guidance(receipt,'jf1')

if __name__=='__main__':unittest.main()
