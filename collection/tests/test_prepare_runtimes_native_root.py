from __future__ import annotations

import tempfile
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = next(parent for parent in Path(__file__).resolve().parents
            if (parent / 'collection/tools/prepare_runtimes.py').is_file())
TOOLS = ROOT / 'collection/tools'
sys.path.insert(0, str(TOOLS))
import prepare_runtimes as module


class NativeRootPreparationTests(unittest.TestCase):
    def setUp(self) -> None:
        for name in ('ROOT', 'REPO', 'PROJECTS'):
            value = getattr(module, name)
            self.addCleanup(setattr, module, name, value)

    def test_default_and_custom_roots_select_per_game_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            module.ROOT = temp / 'collection'
            module.PROJECTS = {
                'jf1': (temp / 'standalone/jf1/source', 'bios'),
                'jf2': (temp / 'standalone/jf2/source', 'bios'),
            }
            self.assertEqual(module._native_target('jf1'),
                             (module.ROOT / '.workbench/native/jf1').resolve())
            self.assertEqual(module._native_target('jf2', temp / 'private-native'),
                             (temp / 'private-native/jf2').resolve())

    def test_rejects_custom_target_ancestor_and_descendant_of_standalone_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            module.PROJECTS = {
                'jf1': (temp / 'standalone/jf1/source', 'bios'),
                'jf2': (temp / 'standalone/jf2/source', 'bios'),
            }
            # target = native_root/game is an ancestor of the source tree.
            with self.assertRaisesRegex(ValueError, 'overlaps standalone source'):
                module._native_target('jf1', temp / 'standalone')
            # target is below the standalone source tree.
            with self.assertRaisesRegex(ValueError, 'overlaps standalone source'):
                module._native_target('jf1', temp / 'standalone/jf1/source/private')

    def test_api_rejects_custom_native_build_before_writing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            native_root = Path(directory) / 'not-created'
            with mock.patch.object(module.shutil, 'copytree') as copytree, \
                 mock.patch.object(module.subprocess, 'run') as process_run:
                with self.assertRaisesRegex(ValueError, 'requires --source-only'):
                    module.prepare('jf1', native_root=native_root)
                self.assertFalse(native_root.exists())
                copytree.assert_not_called()
                process_run.assert_not_called()

    def test_source_only_cli_prepares_custom_project_without_native_or_emitter_builds(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            collection = temp / 'repo/collection'
            source = temp / 'standalone/jf1'
            native_root = temp / 'private-native'
            for relative in ('psxrecomp/runtime/src', 'psxrecomp/runtime/include',
                             'psxrecomp/tools', 'recomp-ui', 'generated'):
                (source / relative).mkdir(parents=True, exist_ok=True)
            (source / 'psxrecomp/runtime/src/main.cpp').write_text('int main(){}\n', encoding='utf-8')
            (source / 'psxrecomp/runtime/include/overlay_api.h').write_text(
                '#define PSX_OVERLAY_ABI_VERSION 7\n', encoding='utf-8')
            (source / 'CMakeLists.txt').write_text('project(test)\n', encoding='utf-8')
            (source / 'game.toml').write_text('[game]\nexe = "game.exe"\n', encoding='utf-8')
            (source / 'game.exe').write_bytes(b'fixture')
            (collection / 'runtime').mkdir(parents=True)
            (collection / 'runtime/collection_overlay_limits.h').write_text(
                '#define COLLECTION_OVERLAY_CANDIDATE_CAP 4\n'
                '#define COLLECTION_OVERLAY_LIMITS_SCHEMA 2\n', encoding='utf-8')
            module.ROOT = collection
            module.REPO = temp / 'repo'
            module.PROJECTS = {'jf1': (source, 'OpenBIOS;SCPH1001')}

            patchers = ('adapt', 'patch_trace_storage', 'patch', 'patch_runtime', 'patch_performance',
                        'patch_static', 'patch_aot_audit', 'patch_emitter', 'patch_host_messages')
            with mock.patch.multiple(module, **{name: mock.DEFAULT for name in patchers}) as mocks, \
                 mock.patch.object(module.subprocess, 'run') as process_run, \
                 mock.patch.object(module, 'build_emitters') as emitter_build:
                self.assertEqual(module.main(['--game', 'jf1', '--source-only',
                                              '--native-root', str(native_root)]), 0)
                target = native_root / 'jf1'
                self.assertTrue((target / 'game.toml').is_file())
                self.assertIn((collection / 'runtime').as_posix(),
                              (target / 'CMakeLists.txt').read_text(encoding='utf-8'))
                self.assertTrue((target / 'CMakeLists.txt').read_text(encoding='utf-8').startswith(
                    'set(PSXRECOMP_BIOS_STEMS "OpenBIOS;SCPH1001" CACHE STRING '))
                self.assertEqual(mocks['adapt'].call_args.args[0], target / 'psxrecomp')
                mocks['patch_trace_storage'].assert_called_once_with(target / 'psxrecomp', 'jf1')
                mocks['patch_host_messages'].assert_called_once_with(target, 'jf1')
                process_run.assert_not_called()
                emitter_build.assert_not_called()

                with self.assertRaises(SystemExit):
                    module.main(['--game', 'jf1', '--native-root', str(native_root)])
                emitter_build.assert_not_called()
                process_run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
