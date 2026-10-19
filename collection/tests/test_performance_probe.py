import sys
from pathlib import Path
import unittest
import os
import json
import itertools
import tempfile
from unittest.mock import patch
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from performance_probe import summarize,process_cpu_seconds,probe

class ProbeTests(unittest.TestCase):
    def test_invalid_robbit_functional_options_reject_before_storage_or_cache(self):
        for visible,route,mode in ((False,True,'strict'),(True,False,'strict'),(True,True,'observe')):
            with self.subTest(visible=visible,route=route,mode=mode):
                args=SimpleNamespace(game='robbit',functional_checks=True,visible=visible,
                    gameplay_route=route,static_audit=mode)
                with patch('performance_probe.seed_cache') as seed:
                    with self.assertRaisesRegex(ValueError,'requires --visible'):probe(args)
                    seed.assert_not_called()

    def test_strict_probe_rejects_clean_exit_without_live_gameplay(self):
        for mode,gameplay,expected in (('strict',False,False),('strict',True,True),('observe',False,True)):
            with self.subTest(mode=mode,gameplay=gameplay),tempfile.TemporaryDirectory() as directory:
                base=Path(directory);root=base/'package';root.mkdir()
                (root/'game.exe').write_bytes(b'fixture, never executed')
                (root/'catalog.toml').write_text('[[games]]\nid="jf1"\nexecutable="game.exe"\n'
                    'config="game.toml"\ndisc="game.cue"\nbios="bios.bin"\n',encoding='utf-8')
                args=SimpleNamespace(root=root,data=base/'probe',seconds=5,port=0,game='jf1',
                    aot_only=False,aot_preparation=None,executable=None,allow_empty_cache=True,
                    diagnostics=False,compiler_off=True,metrics_off=False,host_profile=False,
                    static_audit=mode,loader_log=False,gameplay_route=False,start_pulses=False,
                    boot_timeout=10,legacy_telemetry=False,functional_checks=False)
                audit=dict(schema=1,enabled=True,mode=mode,scope='process_lifetime',
                    dirty_instruction_attempts=0,oracle_instruction_attempts=0,compiler_requests=0,
                    first_interpreter=None,no_fallback_observed=True)
                process=SimpleNamespace(pid=1234,returncode=0,_handle=None,running=True)
                process.poll=lambda:None if process.running else 0
                process.wait=lambda **kwargs:0
                frames=itertools.count(0,200)
                def query(command,**kwargs):
                    if command=='frame':return dict(frame=next(frames))
                    if command=='collection_perf':
                        return dict(swap_calls=0,generated_swap_calls=0,samples=[],sample_drops=0)
                    if command=='audio_stats':return dict(out=dict(underruns=0,overflow_drops=0))
                    if command=='collection_input':return dict(gameplay=gameplay)
                    if command=='gpu_state':return dict(display=dict(enabled=False))
                    if command=='collection_static':return audit
                    if command=='quit':
                        process.running=False
                        (args.data/'static-coverage.json').write_text(json.dumps(audit),encoding='utf-8')
                    return {}
                ticks=itertools.count(0,.25)
                with patch('performance_probe.verify_runtime_executable',return_value={}), \
                        patch('performance_probe.seed_cache',return_value={}), \
                        patch('performance_probe.subprocess.Popen',return_value=process), \
                        patch('performance_probe.Client',return_value=SimpleNamespace(query=query)), \
                        patch('performance_probe.process_cpu_seconds',return_value=None), \
                        patch('performance_probe.time.monotonic',side_effect=lambda:next(ticks)), \
                        patch('performance_probe.time.sleep'),patch('builtins.print'):
                    self.assertEqual(probe(args),expected)
                saved=json.loads((args.data/'performance-receipt.json').read_text(encoding='utf-8'))
                self.assertEqual(saved['exit_code'],0)
                self.assertEqual(saved['static_gate']['native_only_observed'],gameplay)
                if not gameplay:self.assertIn('No live gameplay reached',saved['static_gate']['reasons'])

    def test_catalog_parent_paths_do_not_inflate_bios_argument(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);root=base/'package'/('capture-'+'r'*100);root.mkdir(parents=True)
            assets=base/'assets';assets.mkdir()
            bios=assets/('SCPH-'+'b'*100+'.BIN');bios.write_bytes(b'verified BIOS fixture')
            (root/'game.exe').write_bytes(b'fixture, never executed')
            (root/'catalog.toml').write_text('[[games]]\nid="jf1"\nexecutable="game.exe"\n'
                'config="game.toml"\ndisc="../../assets/game.cue"\nbios="../../assets/'+bios.name+'"\n',encoding='utf-8')
            self.assertGreaterEqual(len(str(root/'../../assets'/bios.name)),260)
            args=SimpleNamespace(root=root,data=base/'probe',seconds=5,port=0,game='jf1',
                aot_only=False,aot_preparation=None,executable=None,allow_empty_cache=True,
                diagnostics=False,compiler_off=True,metrics_off=False,host_profile=False,
                static_audit='strict',loader_log=False,gameplay_route=False,start_pulses=False)
            with patch('performance_probe.verify_runtime_executable',return_value={}), \
                    patch('performance_probe.seed_cache',return_value={}), \
                    patch('performance_probe.subprocess.Popen',side_effect=RuntimeError('captured command')) as launch:
                with self.assertRaisesRegex(RuntimeError,'captured command'):probe(args)
            command=launch.call_args.args[0]
            actual=Path(command[command.index('--bios')+1])
            self.assertEqual(actual,bios.resolve())
            self.assertEqual(actual.read_bytes(),b'verified BIOS fixture')
            self.assertNotIn('..',actual.parts)
            self.assertIn('--hidden-window',command)
            args.visible=True;args.data=base/'visible-probe'
            args.runtime_env=['PSX_JF1_F4354_XCULL=1','PSX_JF1_F47B8_XCLIP=1','PSX_OVERLAY_AUTOCOMPILE_OFF=0']
            with patch('performance_probe.verify_runtime_executable',return_value={}), \
                    patch('performance_probe.seed_cache',return_value={}), \
                    patch('performance_probe.subprocess.Popen',side_effect=RuntimeError('captured command')) as launch:
                with self.assertRaisesRegex(RuntimeError,'captured command'):probe(args)
            self.assertNotIn('--hidden-window',launch.call_args.args[0])
            self.assertEqual(launch.call_args.kwargs['env']['PSX_JF1_F47B8_XCLIP'],'1')
            self.assertEqual(launch.call_args.kwargs['env']['PSX_OVERLAY_AUTOCOMPILE_OFF'],'1')
            args.runtime_env=['NOT_A_RUNTIME_SETTING=1'];args.data=base/'invalid-probe'
            with self.assertRaisesRegex(ValueError,'PSX_NAME=VALUE'):probe(args)
            self.assertFalse(args.data.exists())

    def test_budget_mismatch_fails_before_creating_or_seeding_data(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);root=base/'package';root.mkdir()
            (root/'catalog.toml').write_text('[[games]]\nid="jf1"\nexecutable="old.exe"\n',encoding='utf-8')
            args=SimpleNamespace(root=root,data=base/'probe',seconds=5,port=0,game='jf1',
                aot_only=False,aot_preparation=None,executable=None)
            with patch('performance_probe.verify_runtime_executable',side_effect=ValueError('contract differs')),patch('performance_probe.seed_cache') as seed:
                with self.assertRaisesRegex(ValueError,'contract differs'):probe(args)
                seed.assert_not_called()
            self.assertFalse(args.data.exists())

    def test_audited_only_requires_preparation_before_creating_data(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);root=base/'package';root.mkdir()
            (root/'catalog.toml').write_text('[[games]]\nid="jf1"\n',encoding='utf-8')
            args=SimpleNamespace(root=root,data=base/'probe',seconds=5,port=0,game='jf1',
                aot_only=True,aot_preparation=None)
            with self.assertRaisesRegex(ValueError,'independently audited'):probe(args)
            self.assertFalse(args.data.exists())
    def test_counter_meaning_and_missing_samples(self):
        def snapshot(seconds,guest,swaps,rows):
            return dict(seconds=seconds,frame=guest,metrics=dict(swap_calls=swaps,generated_swap_calls=0,
                samples=rows,sample_drops=0),audio=dict(out=dict(underruns=0,overflow_drops=0)))
        result=summarize([snapshot(0,0,0,[]),snapshot(2,100,120,[[1,1000000,1,0],[2,18000000,2,0],[4,50000000,4,0]])])
        self.assertEqual(result['guest_hz'],50)
        self.assertEqual(result['swap_calls_per_second'],60)
        self.assertEqual(result['missing_between_rows'],1)
        self.assertEqual(result['swap_completion_interval_p99_ms'],17)
        self.assertIsNone(result['physical_present_fps'])
        self.assertIsNone(result['world_update_hz'])
    @unittest.skipUnless(os.name=='nt','Windows process counter')
    def test_cpu_clock_is_available_for_owned_process(self):
        import ctypes
        api=ctypes.WinDLL('kernel32').GetCurrentProcess
        api.restype=ctypes.c_void_p
        handle=api()
        first=process_cpu_seconds(handle)
        self.assertIsNotNone(first);self.assertGreaterEqual(process_cpu_seconds(handle),first)

if __name__=='__main__':unittest.main()
