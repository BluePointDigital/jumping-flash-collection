from __future__ import annotations

import copy
import json
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock
from pathlib import Path

STAGE = Path(__file__).resolve().parent
TOOLS = STAGE
sys.path.insert(0, str(TOOLS))
import robbit_static_recipes as recipes  # noqa: E402


def find_repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "collection/.workbench/static-recomp/aot/robbit-worldmap-static/provenance.json").is_file():
            return parent
    raise RuntimeError("could not locate repository AOT evidence")


class OptionalSdkTailRecipeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = find_repo_root()
        cls.catalog_path = STAGE.parent / "runtime/robbit_static_source_catalog.json"
        cls.catalog, cls.catalog_sha = recipes.load_catalog(cls.catalog_path)
        cls.aot = cls.repo / "collection/.workbench/static-recomp/aot/robbit-worldmap-static"
        cls.provenance_bytes = (cls.aot / "provenance.json").read_bytes()
        cls.provenance = json.loads(cls.provenance_bytes)
        specs = cls.catalog["disc"]["sdk_tail_72"]["entries"]
        cls.records = recipes._load_record_batch(
            cls.aot / "records.json", [spec["recipe"] for spec in specs],
        )

    def test_all_72_exact_records_prepare_as_source_coverage(self):
        identity = recipes.validate_aot_provenance(
            self.provenance, self.catalog, include_sdk_tail=True,
        )
        prepared, jobs = recipes.prepare_sdk_tail_records(self.records, self.catalog)
        self.assertEqual(len(prepared), 72)
        self.assertEqual(len(jobs), 72)
        self.assertEqual(identity["sdk_tail_72"]["recipe_count"], 72)
        self.assertEqual(
            len({job["required_entries"][0] for job in jobs}), 43,
        )
        self.assertEqual(
            len({record["producer_name"] for record in prepared}), 72,
        )
        coverage = [row for record in prepared for row in record["source_coverage_entries"]]
        sdk_rows = [row for row in coverage if "entry_guard_bytes" in row]
        self.assertEqual(len(sdk_rows), 72)
        self.assertTrue(all(row["entry_guard_bytes"] == 116 for row in sdk_rows))
        self.assertTrue(all(row["runtime_reachability_proven"] is False for row in sdk_rows))
        self.assertTrue(all(job["requirement_kind"] == "static_source_coverage" for job in jobs))

    def test_changed_capture_pointer_or_provenance_is_rejected(self):
        changed_records = copy.deepcopy(self.records)
        changed_records[0]["size"] -= 4
        with self.assertRaisesRegex(ValueError, "decoded image bytes differ|capture size"):
            recipes.prepare_sdk_tail_records(changed_records, self.catalog)

        changed_catalog = copy.deepcopy(self.catalog)
        first = changed_catalog["disc"]["sdk_tail_72"]["entries"][0]
        first["literal_continuation_pointer_pair"]["computed_target_pc"] = "0x80000000"
        with self.assertRaisesRegex(ValueError, "LUI/ADDIU pair"):
            recipes.prepare_sdk_tail_records(self.records, changed_catalog)

        changed_catalog = copy.deepcopy(self.catalog)
        first = changed_catalog["disc"]["sdk_tail_72"]["entries"][0]
        first["source_coverage_entry_pc"] = f"0x{int(first['source_coverage_entry_pc'], 16) + 4:08X}"
        with self.assertRaisesRegex(ValueError, "source entry word differs"):
            recipes.prepare_sdk_tail_records(self.records, changed_catalog)

        changed_provenance = copy.deepcopy(self.provenance)
        row = next(row for row in changed_provenance["inputs"] if row["path"] == self.records[0]["producer_name"])
        row["source_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "SDK-tail AOT provenance identity"):
            recipes.validate_aot_provenance(changed_provenance, self.catalog, include_sdk_tail=True)

    def test_duplicates_and_missing_recipes_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "duplicate SDK-tail capture"):
            recipes.prepare_sdk_tail_records(self.records + [self.records[0]], self.catalog)
        with self.assertRaisesRegex(ValueError, "missing captures"):
            recipes.prepare_sdk_tail_records(self.records[:-1], self.catalog)
        with self.assertRaisesRegex(ValueError, "uncataloged captures"):
            recipes.prepare_sdk_tail_records(self.records + [{"producer_name": "UNEXPECTED.PEX"}], self.catalog)

    def test_sdk_batch_is_optional_and_defaults_stay_two_records(self):
        wm = recipes._load_one_record(self.aot / "record-080.json", "WM/WORLDMAP.PEX")
        bios = (self.repo / "collection/.workbench/native/robbit/psxrecomp/bios/SCPH5500.BIN").read_bytes()
        boot = (self.repo / "collection/.workbench/native/robbit/disc/SCPS_101.03").read_bytes()
        prepared = recipes.prepare_static_source_coverage(
            wm, bios, boot, self.catalog, self.catalog_sha, self.provenance,
            recipes._sha(self.provenance_bytes),
        )
        self.assertEqual(len(prepared["records"]), 2)
        self.assertEqual(len(prepared["jobs"]), 2)
        self.assertFalse(prepared["runtime_reachability_proven"])

    def test_optional_sdk_batch_integrates_without_changing_default_shape(self):
        wm = recipes._load_one_record(self.aot / "record-080.json", "WM/WORLDMAP.PEX")
        bios = (self.repo / "collection/.workbench/native/robbit/psxrecomp/bios/SCPH5500.BIN").read_bytes()
        boot = (self.repo / "collection/.workbench/native/robbit/disc/SCPS_101.03").read_bytes()
        prepared = recipes.prepare_static_source_coverage(
            wm, bios, boot, self.catalog, self.catalog_sha, self.provenance,
            recipes._sha(self.provenance_bytes), sdk_tail_records=self.records,
        )
        self.assertEqual(len(prepared["records"]), 74)
        self.assertEqual(len(prepared["jobs"]), 74)
        self.assertEqual(prepared["input_provenance"]["verified_aot_input_identity"]["sdk_tail_72"]["recipe_count"], 72)
        self.assertFalse(prepared["full_static_coverage_proven"])
        self.assertFalse(prepared["runtime_reachability_proven"])
        with self.assertRaisesRegex(ValueError, "provenance file digest"):
            recipes.prepare_static_source_coverage(
                wm, bios, boot, self.catalog, self.catalog_sha, self.provenance,
                "0" * 64, sdk_tail_records=self.records,
            )

    def test_combined_memcard_m01_and_sdk_batch_merges_overlapping_m01(self):
        wm = recipes._load_one_record(self.aot / "records.json", "WM/WORLDMAP.PEX")
        memcard = recipes._load_one_record(self.aot / "records.json", "WM/MEMCARD.PEX")
        m01 = recipes._load_one_record(self.aot / "records.json", "EVENT/00/M01.PEX")
        bios = (self.repo / "collection/.workbench/native/robbit/psxrecomp/bios/SCPH5500.BIN").read_bytes()
        boot = (self.repo / "collection/.workbench/native/robbit/disc/SCPS_101.03").read_bytes()

        prepared = recipes.prepare_static_source_coverage(
            wm, bios, boot, self.catalog, self.catalog_sha, self.provenance,
            recipes._sha(self.provenance_bytes), memcard_record=memcard,
            m01_record=m01, sdk_tail_records=self.records,
        )
        records = prepared["records"]
        jobs = prepared["jobs"]
        record_names = [record["producer_name"] for record in records]
        job_names = [job["name"] for job in jobs]
        self.assertEqual(len(records), 75)  # 2 base + MEMCARD + M01 + 71 non-overlapping SDK images
        self.assertEqual(len(jobs), 75)
        self.assertEqual(len(record_names), len(set(record_names)))
        self.assertEqual(len(job_names), len(set(job_names)))

        m01_prepared = next(row for row in records if row["producer_name"] == "EVENT/00/M01.PEX")
        m01_job = next(row for row in jobs if row["name"] == "EVENT/00/M01.PEX")
        m01_entries = {0x80058BD8, 0x80064B90, 0x800906B4, 0x8009E8F0}
        self.assertEqual(set(m01_job["required_entries"]), m01_entries)
        self.assertTrue(m01_entries <= {int(value, 16) for value in m01_prepared["dispatch_entry_pcs"]})
        self.assertTrue(m01_entries <= {int(value, 16) for value in m01_prepared["static_dispatch_entry_pcs"]})
        self.assertEqual(
            m01_entries,
            {int(row["entry_pc"], 16) for row in m01_prepared["source_coverage_entries"]},
        )
        sdk_spec = next(
            row for row in self.catalog["disc"]["sdk_tail_72"]["entries"]
            if row["recipe"] == "EVENT/00/M01.PEX"
        )
        sdk_coverage = next(
            row for row in m01_prepared["source_coverage_entries"]
            if int(row["entry_pc"], 16) == recipes._number(sdk_spec["source_coverage_entry_pc"])
        )
        self.assertEqual(sdk_coverage["owner_entry_pc"], sdk_spec["owner_entry_pc"])
        self.assertEqual(sdk_coverage["literal_continuation_pointer_pair"], sdk_spec["literal_continuation_pointer_pair"])
        self.assertEqual(sdk_coverage["entry_guard_sha256"], sdk_spec["tail_entry_guard"]["sha256"])
        self.assertEqual(
            prepared["input_provenance"]["verified_aot_input_identity"]["sdk_tail_72"]["recipe_count"], 72,
        )
        self.assertEqual(
            prepared["input_provenance"]["verified_aot_input_identity"]["m01_source_coverage_entries"],
            recipes.validate_aot_provenance(
                self.provenance, self.catalog, include_m01=True,
            )["m01_source_coverage_entries"],
        )
        self.assertTrue(set(m01["function_entry_pcs"]) <= set(m01_prepared["function_entry_pcs"]))
        self.assertTrue(set(m01["seeds"]) <= set(m01_prepared["seeds"]))
        for field in ("size", "load_addr", "bytes_b64"):
            self.assertEqual(m01_prepared[field], m01[field], f"M01 captured bytes changed in {field}")

        memcard_job = next(row for row in jobs if row["name"] == "WM/MEMCARD.PEX")
        self.assertEqual(memcard_job["required_entries"], [0x800A8C14])
        self.assertFalse(prepared["runtime_reachability_proven"])
        self.assertFalse(prepared["full_static_coverage_proven"])

    def test_combined_cli_emits_one_record_and_job_per_recipe(self):
        boot_path = self.repo / "collection/.workbench/native/robbit/disc/SCPS_101.03"
        bios_path = self.repo / "collection/.workbench/native/robbit/psxrecomp/bios/SCPH5500.BIN"
        with tempfile.TemporaryDirectory(dir=STAGE) as temp_dir:
            output_path = Path(temp_dir) / "prepared-combined.json"
            argv = [
                "robbit_static_recipes.py",
                "--catalog", str(self.catalog_path),
                "--worldmap-record", str(self.aot / "records.json"),
                "--memcard-record", str(self.aot / "records.json"),
                "--m01-record", str(self.aot / "records.json"),
                "--sdk-tail-records", str(self.aot / "records.json"),
                "--aot-provenance", str(self.aot / "provenance.json"),
                "--boot-exe", str(boot_path),
                "--bios", str(bios_path),
                "--output", str(output_path),
            ]
            with mock.patch.object(sys, "argv", argv), redirect_stdout(io.StringIO()):
                self.assertEqual(recipes.main(), 0)
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            records = payload["records"]
            jobs = payload["jobs"]
            names = [row["producer_name"] for row in records]
            self.assertEqual(len(records), len(set(names)))
            self.assertEqual(len(jobs), len({row["name"] for row in jobs}))
            m01 = next(row for row in jobs if row["name"] == "EVENT/00/M01.PEX")
            self.assertEqual(set(m01["required_entries"]), {0x80058BD8, 0x80064B90, 0x800906B4, 0x8009E8F0})
            self.assertEqual(len(records), 75)
            self.assertFalse(payload["runtime_reachability_proven"])

    def test_optional_cli_selects_sdk_batch_and_writes_preparation_only(self):
        boot_path = self.repo / "collection/.workbench/native/robbit/disc/SCPS_101.03"
        bios_path = self.repo / "collection/.workbench/native/robbit/psxrecomp/bios/SCPH5500.BIN"
        with tempfile.TemporaryDirectory(dir=STAGE) as temp_dir:
            output_path = Path(temp_dir) / "prepared.json"
            argv = [
                "robbit_static_recipes.py",
                "--catalog", str(self.catalog_path),
                "--worldmap-record", str(self.aot / "record-080.json"),
                "--sdk-tail-records", str(self.aot / "records.json"),
                "--aot-provenance", str(self.aot / "provenance.json"),
                "--boot-exe", str(boot_path),
                "--bios", str(bios_path),
                "--output", str(output_path),
            ]
            with mock.patch.object(sys, "argv", argv), redirect_stdout(io.StringIO()):
                self.assertEqual(recipes.main(), 0)
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(len(payload["records"]), 74)
            self.assertEqual(len(payload["jobs"]), 74)
            self.assertFalse(payload["runtime_reachability_proven"])


if __name__ == "__main__":
    unittest.main()
