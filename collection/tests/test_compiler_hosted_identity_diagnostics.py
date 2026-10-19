"""Hosted identity failures remain rejected while retaining bounded evidence."""
from pathlib import Path
import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch as environment_patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from patch_compiler import patch
from prepare_runtimes import PROJECTS


class HostedIdentityDiagnosticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory()
        cls.script=Path(cls.temp.name)/'compile_overlays.py'
        source=PROJECTS['jf2'][0]/'psxrecomp/tools/compile_overlays.py'
        cls.script.write_bytes(source.read_bytes())
        patch(cls.script)
        spec=importlib.util.spec_from_file_location('hosted_diag_fixture',cls.script)
        cls.compiler=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.compiler)
        cls.compiler.DISPATCH_PREAMBLE=''

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def fixture(self):
        host=0x80010000;target=0x80010010;crc=0x12345678
        expected=(host,crc,[(host,32)])
        specs={target:dict(host=host,owner_identity=expected,host_reason='DISPATCH_ENTRY')}
        return host,target,crc,expected,specs

    def test_crc_and_range_failures_stay_rejected_and_retention_is_opt_in(self):
        host,target,crc,expected,specs=self.fixture()
        validate=self.compiler.validate_hosted_fragment_ids
        explain=self.compiler.collection_hosted_identity_mismatches
        generated={host,target}
        crc_ids=[expected,(target,crc^1,[(host,32)])]
        range_ids=[expected,(target,crc,[(host+4,28)])]
        for ids in (crc_ids,range_ids):
            with self.subTest(ids=ids):
                self.assertIn('changed selected owner CRC/range identity',
                    validate({target},specs,ids,generated,allow_missing_targets=True))
        self.assertEqual(explain({target},specs,crc_ids,generated)['mismatches'][0]['reason'],'crc-mismatch')
        self.assertEqual(explain({target},specs,range_ids,generated)['mismatches'][0]['reason'],'range-mismatch')
        many_ranges=[(host+i*8,8) for i in range(20)]
        specs_many={target:dict(host=host,owner_identity=(host,crc,many_ranges),
            host_reason='DISPATCH_ENTRY')}
        bounded=explain({target},specs_many,
            [(host,crc,many_ranges),(target,crc,many_ranges)],generated)
        self.assertTrue(bounded['aliases'][0]['owner_identity']['ranges_truncated'])
        self.assertEqual(len(bounded['aliases'][0]['owner_identity']['ranges']),16)

        with tempfile.TemporaryDirectory() as directory:
            raw_ranges=b'raw emitted range manifest\n'
            source_dir=Path(directory)/'source';source_dir.mkdir()
            ranges=source_dir/'generated.ranges';ranges.write_bytes(raw_ranges)
            with environment_patch.dict(os.environ,{'PSX_RETAIN_FAILED_C':'0'}):
                self.compiler.collection_retain_fragment_failure(directory,0x10000,[target],
                    'patched generated C',host,32,b'input',set(),set(),
                    hosted_identity=explain({target},specs,range_ids,generated),
                    ranges_path=str(ranges),provenance={'manifest':'fixture'},recipe={'cps':True})
            self.assertFalse(list(Path(directory).glob('*.c')))
            self.assertFalse(list(Path(directory).glob('*.ranges')))
            receipt=json.loads(next(Path(directory).glob('*.json')).read_text())
            self.assertFalse(receipt['full_c_retained'])
            self.assertFalse(receipt['ranges_retained'])
            self.assertEqual(receipt['hosted_identity']['mismatches'][0]['reason'],'range-mismatch')

        with tempfile.TemporaryDirectory() as directory:
            raw_ranges=b'raw emitted range manifest\n'
            source_dir=Path(directory)/'source';source_dir.mkdir()
            ranges=source_dir/'generated.ranges';ranges.write_bytes(raw_ranges)
            with environment_patch.dict(os.environ,{'PSX_RETAIN_FAILED_C':'1'}):
                self.compiler.collection_retain_fragment_failure(directory,0x10000,[target],
                    'patched generated C',host,32,b'input',set(),set(),
                    hosted_identity=explain({target},specs,range_ids,generated),ranges_path=str(ranges))
            self.assertEqual(next(Path(directory).glob('*.c')).read_text(),'patched generated C')
            self.assertEqual(next(Path(directory).glob('*.ranges')).read_bytes(),raw_ranges)
            self.assertTrue(json.loads(next(Path(directory).glob('*.json')).read_text())['ranges_retained'])

    def test_compile_fragment_batch_records_rejected_seed_recipe(self):
        host,target,crc,expected,specs=self.fixture()
        data=bytes(32);generated_c=(
            'void func_80010000(CPUState* cpu)\n{\n    return;\n}\n'
            'void func_80010010(CPUState* cpu)\n{\n    return;\n}\n')
        actual_ids=[expected,(target,crc^1,[(host,32)])]
        expected_result=(None,'hosted-entry-audit: hosted entry 0x80010010 changed selected owner CRC/range identity')
        validator_error=self.compiler.validate_hosted_fragment_ids(
            {target},specs,actual_ids,{host,target},allow_missing_targets=True)
        self.assertEqual(expected_result[1],'hosted-entry-audit: '+validator_error)
        with tempfile.TemporaryDirectory() as directory:
            config=Path(directory)/'game.toml';config.write_text('[game]\nid = "FIXTURE"\n')
            config_sha=hashlib.sha256(config.read_bytes()).hexdigest()
            args=SimpleNamespace(recompiler='fixture-emitter',game_toml=str(config),
                project_root=None,runtime_include=None,cps=True,flavor='fixture',force=True)
            calls=[]
            def mocked_emitter(command,**kwargs):
                seeds=Path(command[command.index('--seeds')+1]).read_bytes()
                output=Path(command[command.index('--out-dir')+1])
                calls.append(seeds)
                (output/'fixture_full.c').write_text(generated_c)
                (output/'fixture_full.ranges').write_bytes(b'raw ranges for fixture')
                return SimpleNamespace(returncode=0,stdout='',stderr='')
            with environment_patch.object(self.compiler.subprocess,'run',side_effect=mocked_emitter), \
                 environment_patch.object(self.compiler,'parse_overlay_func_ids',return_value=actual_ids), \
                 environment_patch.object(self.compiler,'audit_func_id_delay_slots',return_value=[]):
                with environment_patch.dict(os.environ,{'PSX_RETAIN_FAILED_C':'0'}):
                    result=self.compiler.compile_fragment_batch([target],data,host,len(data),
                        host&0x1fffffff,directory,args,{}, {},hosted_owners=specs,
                        manifest_provenance='hosted-v1',guard_bytes=0)
                self.assertEqual(result,expected_result)
                default_json=next(Path(directory).glob('*.json'))
                default=json.loads(default_json.read_text())
                self.assertEqual(default['provenance']['seeds_sha256'],hashlib.sha256(calls[-1]).hexdigest())
                self.assertEqual(default['provenance']['game_toml_sha256'],config_sha)
                self.assertIn('normalized_config_sha256',default['provenance'])
                self.assertFalse(default['full_c_retained'])
                self.assertFalse(default['ranges_retained'])
                self.assertFalse(default['seeds_retained'])
                self.assertFalse(list(Path(directory).glob('*.c')))
                self.assertFalse(list(Path(directory).glob('*.ranges')))
                self.assertFalse(list(Path(directory).glob('*.seeds')))
                with environment_patch.dict(os.environ,{'PSX_RETAIN_FAILED_C':'1'}):
                    result=self.compiler.compile_fragment_batch([target],data,host,len(data),
                        host&0x1fffffff,directory,args,{}, {},hosted_owners=specs,
                        manifest_provenance='hosted-v1',guard_bytes=0)
                self.assertEqual(result,expected_result)
            retained_json=[p for p in Path(directory).glob('*.json') if p!=default_json]
            self.assertEqual(len(retained_json),1)
            retained=json.loads(retained_json[0].read_text())
            self.assertTrue(retained['full_c_retained'])
            self.assertTrue(retained['ranges_retained'])
            self.assertTrue(retained['seeds_retained'])
            stem=retained_json[0].with_suffix('')
            self.assertTrue(stem.with_suffix('.c').exists())
            self.assertEqual(stem.with_suffix('.ranges').read_bytes(),b'raw ranges for fixture')
            self.assertEqual(stem.with_suffix('.seeds').read_bytes(),calls[-1])


if __name__=='__main__':
    unittest.main()
