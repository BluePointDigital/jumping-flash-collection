import json
import hashlib
import io
from contextlib import redirect_stdout
from unittest.mock import patch
from pathlib import Path
import sys
import tempfile
import unittest

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
from aot_release_inventory import verify_release_cache_inventory
from verify_package import check


class ReleaseCacheProvenanceTests(unittest.TestCase):
    def test_release_gate_requires_exact_audited_inventory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            namespace = Path("SERIAL/gcc/win-x64/cg22_abc_f0")
            active = root / namespace
            active.mkdir(parents=True)
            audited = active / "00001000_11111111.dll"
            audited.write_bytes(b"audited")
            audited_ranges = audited.with_suffix(".ranges")
            audited_ranges.write_bytes(b"audited ranges")
            pairs = [dict(dll=audited.name)]
            args = (root, namespace, pairs)
            self.assertEqual(verify_release_cache_inventory(*args),
                             {"audited_dlls": 1, "audited_sidecars": 1})

            compatible = active / "seg-kuseg/00002000_22222222.dll"
            compatible.parent.mkdir()
            compatible.write_bytes(b"compatible seed")
            compatible.with_suffix(".ranges").write_bytes(b"seed ranges")
            # A valid-looking seed ledger is intentionally irrelevant to a
            # complete release's exact-audit inventory.
            (root / "COMPATIBLE_SEED.json").write_text(json.dumps({"pairs": ["claimed"]}))
            with self.assertRaisesRegex(ValueError, "inventory differs"):
                verify_release_cache_inventory(*args)
            compatible.unlink()
            compatible.with_suffix(".ranges").unlink()

            for suffix in (".resident", ".ranges", ".DLL"):
                with self.subTest(suffix=suffix):
                    extra = active / f"00003000_33333333{suffix}"
                    extra.write_bytes(b"unlisted artifact")
                    with self.assertRaisesRegex(ValueError, "inventory differs"):
                        verify_release_cache_inventory(*args)
                    extra.unlink()

            resident = audited.with_suffix(".resident")
            resident.write_bytes(b"audited resident")
            with self.assertRaisesRegex(ValueError, "inventory differs"):
                verify_release_cache_inventory(*args)
            resident.unlink()

    def test_linked_segment_directory_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            namespace = Path("SERIAL/gcc/win-x64/cg22_abc_f0")
            active = root / namespace
            active.mkdir(parents=True)
            outside = root / "outside"
            outside.mkdir()
            link = active / "seg-kseg1"
            try:
                link.symlink_to(outside, target_is_directory=True)
            except OSError as error:
                self.skipTest(f"Directory symlinks unavailable: {error}")
            else:
                with self.assertRaisesRegex(ValueError, "symlink or junction"):
                    verify_release_cache_inventory(root, namespace, [])

    def test_strict_inventory_flag_requires_successful_aot_mode_before_io(self):
        with self.assertRaisesRegex(ValueError, "requires the ordinary AOT audit"):
            check(Path("missing-package"), require_audited_native_cache=True)

    def test_verifier_runs_inventory_and_binds_the_successful_audit(self):
        # Only the prior native semantic audit and namespace lookup are mocked;
        # the package caller, file reads and exact inventory gate execute here.
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'package-manifest.json').write_text('{"schema":1,"files":{}}')
            (root / 'catalog.toml').write_text(
                '[[games]]\nid="jf1"\nconfig="runtime/jf1/game.toml"\n')
            runtime = root / 'runtime/jf1'; runtime.mkdir(parents=True)
            (runtime / 'boot.exe').write_bytes(b'fixture boot')
            (runtime / 'game.toml').write_text(
                '[game]\nexe="boot.exe"\ndisc="../../disc.bin"\n')
            cache = root / 'data/games/jf1/cache'
            namespace = Path('SERIAL/gcc/win-x64/cg_fixture')
            active = cache / namespace; active.mkdir(parents=True)
            dll = active / '00001000_11111111.dll'; dll.write_bytes(b'fixture')
            dll.with_suffix('.ranges').write_bytes(b'fixture ranges')
            audit_path = cache / 'AOT_CACHE_AUDIT.json'
            audit_path.write_text(json.dumps({'pairs': [{'dll': dll.name}]}))
            summary = dict(pairs=1, recipes=1,
                           audit_sha256=hashlib.sha256(audit_path.read_bytes()).hexdigest())
            with patch('aot_package.verify_runtime_limits', return_value=None), \
                 patch('aot_package.verify_aot', return_value=summary) as prior, \
                 patch('verify_package.namespace', return_value=namespace), \
                 redirect_stdout(io.StringIO()):
                check(root, require_aot=True, require_audited_native_cache=True)
                prior.assert_called_once()
                extra = active / '00002000_22222222.dll'; extra.write_bytes(b'unlisted')
                check(root, require_aot=True)  # Existing preview behavior.
                with self.assertRaisesRegex(ValueError, 'inventory differs'):
                    check(root, require_aot=True, require_audited_native_cache=True)
                extra.unlink()

                def replaced_audit(*_):
                    audit_path.write_text('{"pairs":[]}')
                    return dict(summary, audit_sha256=hashlib.sha256(audit_path.read_bytes()).hexdigest())

                prior.side_effect = replaced_audit
                with self.assertRaisesRegex(ValueError, 'AOT audit changed'):
                    check(root, require_aot=True, require_audited_native_cache=True)


if __name__ == "__main__":
    unittest.main()
