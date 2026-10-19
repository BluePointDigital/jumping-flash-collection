"""Focused checks for the optional, exact-image M01 interior entry recipe."""

from __future__ import annotations

import base64
import copy
import json
import sys
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(TOOLS))
import robbit_static_recipes as recipes  # noqa: E402


class OptionalM01RecipeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog, cls.catalog_sha = recipes.load_catalog()
        aot = ROOT / ".workbench/static-recomp/aot/robbit-worldmap-static"
        cls.record = recipes._load_one_record(
            aot / "record-001.json", "EVENT/00/M01.PEX",
        )
        cls.provenance = json.loads((aot / "provenance.json").read_text(encoding="utf-8"))

    def test_actual_m01_record_and_provenance_validate_with_distinct_owner(self):
        identity = recipes.validate_aot_provenance(
            self.provenance, self.catalog, include_m01=True,
        )
        prepared, job = recipes.prepare_m01_record(self.record, self.catalog)
        rows = prepared["source_coverage_entries"]
        by_entry = {row["entry_pc"]: row for row in rows}
        self.assertEqual(identity["m01_source_coverage_entry_pc"], "0x80058BD8")
        self.assertEqual(identity["m01_owner_entry_pc"], "0x80058150")
        self.assertEqual(set(by_entry), {"0x80058BD8", "0x80064B90", "0x800906B4"})
        self.assertEqual(by_entry["0x80058BD8"]["owner_entry_pc"], "0x80058150")
        self.assertEqual(by_entry["0x80058BD8"]["owner_extent_bytes"], 3444)
        self.assertEqual(by_entry["0x80064B90"]["owner_entry_pc"], "0x80064AC4")
        self.assertEqual(by_entry["0x80064B90"]["owner_extent_bytes"], 532)
        self.assertEqual(by_entry["0x80064B90"]["source_entry_word"], "0x96020056")
        self.assertEqual(by_entry["0x800906B4"]["owner_entry_pc"], "0x80090618")
        self.assertEqual(by_entry["0x800906B4"]["owner_extent_bytes"], 832)
        self.assertEqual(by_entry["0x800906B4"]["source_entry_word"], "0x1240009F")
        self.assertEqual(job["required_entries"], [0x80058BD8, 0x80064B90, 0x800906B4])
        self.assertEqual(len({row["owner_entry_pc"] for row in rows}), 3)
        self.assertIn("0x80058BD8", prepared["static_dispatch_entry_pcs"])
        self.assertIn("0x80064B90", prepared["static_dispatch_entry_pcs"])
        self.assertIn("0x800906B4", prepared["static_dispatch_entry_pcs"])
        self.assertIn("0x80058150", prepared["function_entry_pcs"])
        self.assertIn("0x80064AC4", prepared["function_entry_pcs"])
        self.assertIn("0x80090618", prepared["function_entry_pcs"])
        self.assertNotIn("0x80058BD8", prepared["function_entry_pcs"])
        self.assertNotIn("0x80064B90", prepared["function_entry_pcs"])
        self.assertNotIn("0x800906B4", prepared["function_entry_pcs"])
        self.assertTrue(all(row["runtime_reachability_proven"] is False for row in rows))

    def test_changed_new_owner_extent_and_entry_word_are_rejected(self):
        catalog = copy.deepcopy(self.catalog)
        extra = catalog["disc"]["m01_interior_continuation"]["additional_continuations"][0]
        extra["owner_extent_bytes"] += 4
        with self.assertRaisesRegex(ValueError, "owner bytes differ"):
            recipes.prepare_m01_record(self.record, catalog)

        catalog = copy.deepcopy(self.catalog)
        catalog["disc"]["m01_interior_continuation"]["additional_continuations"][1]["source_coverage_word"] = "0x00000000"
        with self.assertRaisesRegex(ValueError, "source entry word differs"):
            recipes.prepare_m01_record(self.record, catalog)

    def test_optional_m01_integrates_with_existing_default_preparation(self):
        aot = ROOT / ".workbench/static-recomp/aot/robbit-worldmap-static"
        wm = recipes._load_one_record(aot / "record-080.json", "WM/WORLDMAP.PEX")
        provenance_bytes = (aot / "provenance.json").read_bytes()
        bios = (ROOT / ".workbench/native/robbit/psxrecomp/bios/SCPH5500.BIN").read_bytes()
        boot = (ROOT / ".workbench/native/robbit/disc/SCPS_101.03").read_bytes()
        prepared = recipes.prepare_static_source_coverage(
            wm, bios, boot, self.catalog, self.catalog_sha, self.provenance,
            recipes._sha(provenance_bytes), m01_record=self.record,
        )
        self.assertEqual(len(prepared["records"]), 3)
        self.assertEqual(prepared["jobs"][-1]["required_entries"], [0x80058BD8, 0x80064B90, 0x800906B4])
        self.assertFalse(prepared["runtime_reachability_proven"])

    def test_default_preparation_does_not_add_optional_m01(self):
        aot = ROOT / ".workbench/static-recomp/aot/robbit-worldmap-static"
        wm = recipes._load_one_record(aot / "record-080.json", "WM/WORLDMAP.PEX")
        provenance_bytes = (aot / "provenance.json").read_bytes()
        bios = (ROOT / ".workbench/native/robbit/psxrecomp/bios/SCPH5500.BIN").read_bytes()
        boot = (ROOT / ".workbench/native/robbit/disc/SCPS_101.03").read_bytes()
        prepared = recipes.prepare_static_source_coverage(
            wm, bios, boot, self.catalog, self.catalog_sha, self.provenance,
            recipes._sha(provenance_bytes),
        )
        self.assertEqual(len(prepared["records"]), 2)
        self.assertEqual(len(prepared["jobs"]), 2)
        self.assertTrue(all("EVENT/00/M01.PEX" not in row.get("producer_name", "") for row in prepared["records"]))

    def test_changed_owner_bytes_are_rejected(self):
        spec = self.catalog["disc"]["m01_interior_continuation"]
        mutated = copy.deepcopy(self.record)
        body = bytearray(base64.b64decode(mutated["bytes_b64"], validate=True))
        owner_offset = int(spec["owner_entry_pc"], 0) - int(spec["load_addr"], 0)
        body[owner_offset + 12] ^= 1
        mutated["bytes_b64"] = base64.b64encode(body).decode("ascii")
        with self.assertRaisesRegex(ValueError, "decoded image bytes differ"):
            recipes.prepare_m01_record(mutated, self.catalog)

    def test_wrong_title_provenance_is_rejected(self):
        wrong = copy.deepcopy(self.provenance)
        wrong["game"] = "jf2"
        with self.assertRaisesRegex(ValueError, "another game"):
            recipes.validate_aot_provenance(wrong, self.catalog, include_m01=True)


if __name__ == "__main__":
    unittest.main()
