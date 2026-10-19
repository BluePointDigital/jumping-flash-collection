from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "collection/tools"))
SPEC = importlib.util.spec_from_file_location(
    "generate_palette_native", REPO / "collection/tools/generate_palette_native.py")
generator = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(generator)
from palette_native_sources import CATALOG


STAGE = REPO / "collection/.workbench/static-recomp/staged/luna-static-coverage/host-linked-native-dispatch"
EXPECTED_DISPATCH_SHA256 = "34d268ccf92c5923bbeea401e2a71d8d2c0376fd95526cf9087650b75c001701"
EXPECTED_SPECIALIZED_SHA256 = "d1bf58938fb2da9a5e5a147e7234d03a9305be6f031edc58462e1b20142bac69"


class PaletteDispatchBuilderTests(unittest.TestCase):
    def test_toolkit_manifest_uses_case_sensitive_posix_path_order(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "toolkit"
            (root / "tools").mkdir(parents=True)
            (root / "tools" / "a.c").write_text("a\n", encoding="utf-8")
            (root / "tools" / "Z.c").write_text("Z\n", encoding="utf-8")
            digest, manifest = generator._tree_sha256(root, exclude_path=Path(temp) / "out")
            self.assertEqual([row["path"] for row in manifest], ["tools/Z.c", "tools/a.c"])
            self.assertEqual(len(digest), 64)

    def test_verified_emission_builds_same_dispatch_and_rejects_drift(self) -> None:
        catalog = json.loads(CATALOG.read_bytes())
        receipt = json.loads((STAGE / "receipt.json").read_bytes())
        emitted = (STAGE / "all_36x3_specialized.c").read_bytes()
        expected = (STAGE / "host_dispatch_candidate.c").read_bytes()

        candidate, host_receipt = generator.build_dispatch_candidate(emitted, receipt, catalog)
        self.assertEqual(candidate, expected)
        self.assertEqual(generator.sha256(candidate), EXPECTED_DISPATCH_SHA256)
        self.assertEqual(host_receipt["function_count"], 108)
        self.assertEqual(host_receipt["unique_entry_segment_owners"], 72)
        self.assertEqual(host_receipt["dispatch_keys"], 216)
        self.assertEqual(host_receipt["ambiguous_dispatch_key_count"], 0)

        compatible = []
        for entry in receipt["entries"]:
            raw_bytes = (STAGE / entry["emitted_c"]).read_bytes()
            self.assertEqual(generator.sha256(raw_bytes), entry["emitted_c_sha256"])
            owner = generator._extract_function(raw_bytes.decode("utf-8"), int(entry["entry"], 16))
            compatible.append(generator._specialize_function(
                owner, int(entry["entry"], 16), entry["function"], int(entry["operand"], 16)))
        reconstructed = ("\n\n".join(compatible) + "\n").encode("utf-8")
        self.assertEqual(reconstructed, emitted)
        self.assertEqual(generator.sha256(reconstructed), EXPECTED_SPECIALIZED_SHA256)

        damaged = bytearray(emitted)
        damaged[0] ^= 1
        with self.assertRaises(generator.GenerationError):
            generator.build_dispatch_candidate(bytes(damaged), receipt, catalog)


if __name__ == "__main__":
    unittest.main()
