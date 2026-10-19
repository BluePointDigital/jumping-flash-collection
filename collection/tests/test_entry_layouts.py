import binascii,hashlib,json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from entry_layouts import nominations


class EntryLayoutTests(unittest.TestCase):
    def fixture(self):
        body=bytes(range(64));crc=binascii.crc32(body[:32])
        row=dict(entry='0x80010004',code_crc32=hex(crc),ranges=[['0x80010000',32]])
        document=dict(schema=1,game='jf1',disc_sha256='disc',images={'SELECT.PEX':dict(body_sha256=hashlib.sha256(body).hexdigest(),nominations=[row])})
        return body,document

    def test_full_guard_binding_and_segment_identity(self):
        body,document=self.fixture()
        document['images']['SELECT.PEX']['nominations'].append(dict(document['images']['SELECT.PEX']['nominations'][0],entry='0xA0010004'))
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'profile.json';path.write_text(json.dumps(document))
            self.assertEqual(nominations('jf1','disc','SELECT.PEX',0x80010000,body,path),[0x80010004,0xa0010004])
            self.assertEqual(nominations('jf1','disc','OTHER.PEX',0x80010000,body,path),[])
            self.assertEqual(nominations('robbit','disc','SELECT.PEX',0x80010000,body,path),[])
            with self.assertRaises(ValueError):nominations('jf1','wrong disc','SELECT.PEX',0x80010000,body,path)
            with self.assertRaises(ValueError):nominations('jf1','disc','SELECT.PEX',0x80010000,b'wrong',path)

    def test_crc_bounds_alignment_and_entry_containment_rejected(self):
        for change in [dict(code_crc32='0'),dict(ranges=[]),dict(ranges=[['0x8000FFFF',32]]),
                       dict(ranges=[['0x80010000',68]]),dict(entry='0x40010004'),dict(entry='0x80010040'),dict(entry='0x80010002')]:
            with self.subTest(change=change),tempfile.TemporaryDirectory() as temp:
                body,document=self.fixture();document['images']['SELECT.PEX']['nominations'][0].update(change)
                path=Path(temp)/'profile.json';path.write_text(json.dumps(document))
                with self.assertRaises(ValueError):nominations('jf1','disc','SELECT.PEX',0x80010000,body,path)


if __name__=='__main__':unittest.main()
