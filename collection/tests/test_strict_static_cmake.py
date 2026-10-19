"""Static release opt-in must not configure without its generated dispatcher."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from patch_static import patch_strict_static_requirement
from prepare_runtimes import PROJECTS

FRAMEWORK=PROJECTS['robbit'][0]/'psxrecomp'
CMAKE=ROOT.parent/'.jf2-workbench/recomp/toolchain/bin/cmake.exe'


class StrictStaticCmakeTests(unittest.TestCase):
    def test_idempotence_and_changed_or_partial_blocks_fail_without_writes(self):
        original=(FRAMEWORK/'runtime/runtime.cmake').read_text(encoding='utf-8')
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'runtime.cmake'
            path.write_text(original,encoding='utf-8')
            self.assertTrue(patch_strict_static_requirement(path))
            patched=path.read_bytes()
            self.assertFalse(patch_strict_static_requirement(path))
            self.assertEqual(path.read_bytes(),patched)
            for bad in (original.replace('GAME_LINKED ${_ov_static_game_linked}',
                                          'GAME_LINKED changed'),
                        patched.decode().replace('AND NOT _ov_static_present','AND FALSE')):
                path.write_text(bad,encoding='utf-8')
                before=path.read_bytes()
                with self.assertRaises(ValueError):patch_strict_static_requirement(path)
                self.assertEqual(path.read_bytes(),before)

    @unittest.skipUnless(CMAKE.is_file(),'bundled CMake unavailable')
    def test_production_resolver_and_guard_in_configure_only_projects(self):
        with tempfile.TemporaryDirectory(prefix='strict static sources ') as temp:
            temp=Path(temp)
            production=temp/'runtime.cmake'
            production.write_bytes((FRAMEWORK/'runtime/runtime.cmake').read_bytes())
            patch_strict_static_requirement(production)
            text=production.read_text(encoding='utf-8')
            start=text.index('# COLLECTION_REQUIRE_STATIC_OVERLAYS_V1')
            end=text.index('\n    if(PSXRT_ORACLE)',start)
            block=text[start:end]
            resolver=FRAMEWORK/'runtime/overlay_static_sources.cmake'
            # Explicit static paths need no profile; profile declarations must
            # retain the existing resolver's agreement checks.
            cases=[('strict-empty',True,False,False,False),
                   ('strict-missing',True,True,False,True),
                   ('default-missing',False,True,False,True),
                   ('strict-present',True,True,True,True),
                   ('strict-direct',True,True,True,False)]
            for name,strict,has_path,present,profile in cases:
                with self.subTest(case=name):
                    source=temp/name/'source';build=temp/name/'build'
                    source.mkdir(parents=True)
                    dispatcher=source/'generated/overlays_static.c'
                    split=source/'generated/overlays_static_0000.c'
                    if present:
                        dispatcher.parent.mkdir()
                        dispatcher.write_text('/* dispatcher fixture */\n')
                        split.write_text('/* split fixture */\n')
                    if profile:
                        (source/'aot').mkdir()
                        (source/'aot/overlays.json').write_text(
                            '{"static_output":"generated/overlays_static.c"}\n')
                    selected=dispatcher.as_posix() if has_path else ''
                    (source/'CMakeLists.txt').write_text('''cmake_minimum_required(VERSION 3.20)
project(strict_static_fixture LANGUAGES NONE)
include("'''+resolver.as_posix()+'''")
set(target fixture)
set(_ov_static_game_linked TRUE)
set(PSXRT_GAME_OVERLAY_STATIC_C "'''+selected+'''")
'''+block+'''
file(WRITE "${CMAKE_BINARY_DIR}/observed.txt" "${_ov_static_present}\n${_ov_static_sources}\n")
''',encoding='utf-8')
                    args=[str(CMAKE),'-S',str(source),'-B',str(build)]
                    if strict:args+=['-DCOLLECTION_REQUIRE_STATIC_OVERLAYS=ON']
                    result=subprocess.run(args,capture_output=True,text=True,timeout=20)
                    if strict and not present:
                        self.assertNotEqual(result.returncode,0)
                        self.assertIn('COLLECTION_REQUIRE_STATIC_OVERLAYS=ON',result.stderr)
                    else:
                        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                        rows=(build/'observed.txt').read_text().splitlines()
                        expected=['TRUE',dispatcher.as_posix()+';'+split.as_posix()] if present else ['FALSE','']
                        self.assertEqual(rows,expected)


if __name__=='__main__':unittest.main()
