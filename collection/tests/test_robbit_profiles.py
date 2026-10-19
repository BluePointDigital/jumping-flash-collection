import base64
import copy
import hashlib
import json
from pathlib import Path
import struct
import sys
import tempfile
import tomllib
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from robbit_profiles import (normalized,address_pair,fnv64,source_functions,recover,
    derive_profile,profile_roots,render_headers,hook_config,TEMPLATES,REFERENCE)


class RobbitProfileTests(unittest.TestCase):
    def test_candidate_mask_preserves_stack_branch_and_register_roles(self):
        first=[0x27bdfff0,0x3c03800e,0x2471bc00,0x8e220014,0x0c026703,0x10400002]
        relocated=[0x27bdfff0,0x3c03800f,0x247176c8,0x8e220014,0x0c027703,0x10400002]
        self.assertEqual(normalized(first),normalized(relocated))
        for i,value in [(0,0x27bdffe0),(3,0x8e420014),(5,0x10400003)]:
            changed=list(first);changed[i]=value
            self.assertNotEqual(normalized(first),normalized(changed))

    def test_pointer_pair_signed_low_and_intervening_register_write(self):
        words=[0x3c03800e,0xafb10024,0x2471bc00]
        self.assertEqual(address_pair(words,0,2),0x800dbc00)
        for changed in ([0x3c03800e,0x24630004,0x2471bc00],
                        [0x3c03800e,0xafb10024,0x2451bc00],
                        [0x3c030000,0xafb10024,0x24710000]):
            with self.assertRaises(ValueError):address_pair(changed,0,2)

    def test_guard_hash_has_known_little_endian_bytes(self):
        self.assertEqual(fnv64(b'hello'),0xa430d84680aabd0b)
        self.assertNotEqual(fnv64(struct.pack('<I',0x12345678)),fnv64(struct.pack('>I',0x12345678)))

    def test_source_bounds_and_analysis_identity_fail_closed(self):
        data=struct.pack('<2I',0x03e00008,0);record=dict(bytes_b64=base64.b64encode(data).decode(),load_addr='0x80010000',size=8)
        analysis=dict(schema='psxrecomp static analysis v1',static_only=True,load_address=0x80010000,image_size=8,
            functions=[dict(addr=0x80010000,end=0x80010008,is_data=False,partial=False)])
        self.assertEqual(source_functions(record,analysis)[1][0x80010000],(0x03e00008,0))
        for field,value in [('static_only',False),('load_address',0x80020000),('image_size',12)]:
            with self.assertRaises(ValueError):source_functions(record,dict(analysis,**{field:value}))
        for end in (0x80010009,0x8001000c):
            bad=copy.deepcopy(analysis);bad['functions'][0]['end']=end
            with self.assertRaises(ValueError):source_functions(record,bad)

    def test_configured_hooks_preserve_existing_sites_and_other_title_rejected(self):
        text='[game]\nid="SCPS-10103"\n[recompiler]\nstrict=true\nmod_instruction_sites = [\n"0x80012340"\n]\n[runtime]\noverlay_cache=true\n'
        updated=hook_config(text)
        parsed=tomllib.loads(updated)
        self.assertTrue(parsed['runtime']['overlay_cache']);self.assertTrue(parsed['recompiler']['strict'])
        self.assertIn('0x80012340',parsed['recompiler']['mod_instruction_sites'])
        self.assertEqual(hook_config(updated),updated)
        self.assertGreaterEqual(len(parsed['recompiler']['mod_instruction_sites']),168)
        with self.assertRaises(ValueError):hook_config(text.replace('SCPS-10103','SCUS-94103'))
        with self.assertRaises(ValueError):hook_config(text.replace('0x80012340','0x80012341'))

    def test_preparation_hash_is_checked_before_discovery(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)
            (path/'records.json').write_text('[]')
            (path/'provenance.json').write_text(json.dumps(dict(game='robbit',
                disc_sha256='90981ce0353dfb8b335629504e3f2bb58acd82ddb1bc19db934cc7abdfbad282',records_sha256='0'*64)))
            with self.assertRaisesRegex(ValueError,'records changed'):recover(path)


@unittest.skipUnless((ROOT/'.workbench/static-recomp/aot/robbit-c41-all-worlds/records.json').is_file(),
                     'Verified local Robbit inputs required')
class VerifiedRobbitProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.prep=ROOT/'.workbench/static-recomp/aot/robbit-c41-all-worlds'
        cls.document=recover(cls.prep)
        cls.records={r['producer_name']:r for r in json.loads((cls.prep/'records.json').read_text())}
        cls.body,cls.functions=source_functions(cls.records[REFERENCE],
            json.loads((cls.prep/'analysis'/REFERENCE/'analysis.json').read_text()))

    def test_all_48_source_profiles_and_staged_field_mapping_agree(self):
        prior=json.loads((ROOT.parent/'optimizations/evidence/robbit-controls-profile-candidates.json').read_text())
        expected={p['image']:p for p in prior['profiles']}
        self.assertEqual(len(self.document['profiles']),48)
        for p in self.document['profiles']:
            before=expected[p['image']]
            self.assertEqual(p['sites'],before['sites']);self.assertEqual(p['functions'],before['functions'])
            for key,value in p['fields'].items():self.assertEqual(value,before['fields'][key])
            self.assertEqual({k:g['sha256'] for k,g in p['guards'].items()},
                             {k:g['sha256'] for k,g in before['guards'].items()})

    def test_exact_body_and_all_guards_authorize_only_real_function_roots(self):
        from aot import guarded_title_seeds
        for p in self.document['profiles']:
            r=self.records[p['image']];body=base64.b64decode(r['bytes_b64']);load=int(r['load_addr'],16)
            roots=profile_roots(p['image'],load,body,self.document)
            self.assertEqual(roots,[int(p['sites'][key],16) for key in ('update','pitch','vector')])
            self.assertEqual(guarded_title_seeds('robbit',load,body,p['image']),roots)
            self.assertNotIn(int(p['sites']['rotation_return'],16),roots)
        r=self.records[REFERENCE];body=bytearray(self.body);body[0]^=1
        with self.assertRaises(ValueError):profile_roots(REFERENCE,int(r['load_addr'],16),body,self.document)
        self.assertEqual(profile_roots('TITLE.PEX',0x80010000,b'',self.document),[])
        bad=copy.deepcopy(self.document);bad['profiles'][0]['guards']['update']['address']='0x80000000'
        with self.assertRaises(ValueError):profile_roots(REFERENCE,int(r['load_addr'],16),self.body,bad)

    def test_coarse_match_cannot_authorize_changed_field_callee_or_mode_mask(self):
        for kind in ('field','callee','flag'):
            functions=dict(self.functions)
            if kind=='field':
                address=TEMPLATES['update'];words=list(functions[address])
                i=next(i for i,w in enumerate(words) if 0x20<=w>>26<=0x2e and w>>21&31==17)
                words[i]^=4
            elif kind=='callee':
                address=TEMPLATES['move1'];words=list(functions[address]);words[(0x800a3f5c-address)//4]^=1
            else:
                address=TEMPLATES['flags'];words=list(functions[address]);words[2]^=1
            functions[address]=tuple(words)
            with self.subTest(kind=kind),self.assertRaises(ValueError):derive_profile(REFERENCE,self.body,functions,self.functions)

    def test_published_headers_are_reproducible_and_japanese_guards_are_recorded(self):
        header,sites=render_headers(self.document)
        self.assertEqual(header,(ROOT/'runtime/robbit_profiles.h').read_text())
        self.assertEqual(sites,(ROOT/'runtime/robbit_control_sites.h').read_text())
        published=json.loads((ROOT/'runtime/robbit_profiles.json').read_text())
        self.assertTrue(all(p.get('original_body_sha256') for p in published['profiles']))
        self.assertEqual({p['image'] for p in published['profiles']},{p['image'] for p in self.document['profiles']})


if __name__=='__main__':unittest.main()
