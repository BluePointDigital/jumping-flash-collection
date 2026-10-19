from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from verify_package import validate_windows_path_budget


class PackagePathBudgetTests(unittest.TestCase):
    def test_windows_boundary(self):
        root = 'C:\\preview'
        prefix = len(root) + 1
        validate_windows_path_budget(root, ['x' * (259 - prefix)], windows=True)
        with self.assertRaisesRegex(ValueError, 'move the package to a shorter folder'):
            validate_windows_path_budget(root, ['x' * (260 - prefix)], windows=True)

    def test_observed_mod_manifest_lengths(self):
        manifest = 'runtime/jf1/mods/bundled/collection.jf1.visuals/1.0.0/manifest.toml'
        for length in (170, 266):
            root = 'C:\\' + 'x' * (length - len(manifest) - 4)
            with self.subTest(length=length):
                if length < 260:
                    validate_windows_path_budget(root, [manifest], windows=True)
                else:
                    with self.assertRaisesRegex(ValueError, '266 characters'):
                        validate_windows_path_budget(root, [manifest], windows=True)

    def test_posix_unchanged(self):
        validate_windows_path_budget('/tmp/preview', ['x' * 400], windows=False)


if __name__ == '__main__':
    unittest.main()
