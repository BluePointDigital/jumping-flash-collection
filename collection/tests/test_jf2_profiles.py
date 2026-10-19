import json
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from jf2_profiles import REFERENCE,ROLES,address_pair,derive,recover,hook_config,render_headers
from robbit_profiles import source_functions


class Jf2ProfileTests(unittest.TestCase):
    def test_address_pair_requires_adjacent_register_role_and_ram(self):
        self.assertEqual(address_pair([0x3c02800b,0x8c42c8e4],0,1),0x800ac8e4)
        for words in ([0x3c02800b,0x8c62c8e4],[0x3c020000,0x8c420010],
                      [0x3c02800b,0x3042c8e4]):
            with self.assertRaises(ValueError):address_pair(words,0,1)
        with self.assertRaises(ValueError):address_pair([0x3c02800b,0,0x8c42c8e4],0,2)

    def test_preparation_identity_precedes_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory);(p/'records.json').write_text('[]')
            (p/'provenance.json').write_text(json.dumps(dict(game='jf2',records_sha256='0'*64)))
            with self.assertRaisesRegex(ValueError,'records changed'):recover(p)

    def test_configured_sites_keep_existing_and_refuse_another_game(self):
        text='[game]\nid="SCES-00111"\n[recompiler]\nmod_instruction_sites=["0x80012340"]\n[runtime]\noverlay_cache=true\n'
        after=hook_config(text)
        self.assertEqual(hook_config(after),after)
        parsed=tomllib.loads(after)
        self.assertIn('0x80012340',parsed['recompiler']['mod_instruction_sites'])
        self.assertTrue(parsed['runtime']['overlay_cache'])
        with self.assertRaises(ValueError):hook_config(text.replace('SCES-00111','SCUS-94103'))
        with self.assertRaises(ValueError):hook_config(text.replace('0x80012340','0x80012341'))


@unittest.skipUnless((ROOT/'.workbench/static-recomp/aot/jf2-c41-all-worlds/records.json').is_file(),
                     'Verified local PAL inputs required')
class VerifiedJf2ProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.prep=ROOT/'.workbench/static-recomp/aot/jf2-c41-all-worlds'
        cls.document=recover(cls.prep)
        records={r['producer_name']:r for r in json.loads((cls.prep/'records.json').read_text())}
        cls.body,cls.functions=source_functions(records[REFERENCE],
            json.loads((cls.prep/'analysis'/REFERENCE/'analysis.json').read_text()))

    def test_24_images_and_known_reference_mapping(self):
        self.assertEqual(len(self.document['profiles']),24)
        self.assertEqual(self.document,json.loads((ROOT/'runtime/jf2_profiles.json').read_text()))
        p=next(p for p in self.document['profiles'] if p['image']==REFERENCE)
        self.assertEqual(p['fields'],dict(actor='0x80136d88',pad='0x801051d0',
            movement_mode='0x801051c8',look_mode='0x801051cc',base_speed='0x80104418',camera_pointer='0x800ac8e4'))
        self.assertEqual(p['camera_return'],'0x800e1b78')
        self.assertFalse(self.document['runtime_installed'])

    def test_generated_headers_are_reproducible(self):
        header,sites=render_headers(self.document)
        self.assertEqual(header,(ROOT/'runtime/jf2_profiles.h').read_text())
        self.assertEqual(sites,(ROOT/'runtime/jf2_control_sites.h').read_text())

    def test_masked_candidate_changes_cannot_authorize_wrong_roles(self):
        for kind in ('field','callee','pad'):
            functions=dict(self.functions)
            role='movement' if kind=='field' else 'update'
            a=ROLES[role];words=list(functions[a])
            if kind=='field':
                index=next(i for i,w in enumerate(words) if 0x20<=w>>26<=0x2e and w>>21&31==16)
            else:index=402 if kind=='callee' else 93
            words[index]^=4;functions[a]=tuple(words)
            with self.assertRaises(ValueError):derive(REFERENCE,self.body,functions,self.functions)


if __name__=='__main__':unittest.main()
