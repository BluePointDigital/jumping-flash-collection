"""Focused regression for the optional Robbit WM/MEMCARD source recipe."""

from __future__ import annotations

import base64
import hashlib
import json
import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import robbit_static_recipes as recipes


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def make_inputs():
    wm_body = bytes(range(8))
    memcard_body = bytes(range(16))
    wm_owner = wm_body[4:8]
    memcard_owner = memcard_body[8:12]

    boot_body = bytearray(0x100)
    setup_pc, call_pc, store_pc = 0x80010020, 0x80010024, 0x80010028
    target_pc = 0x80010080
    struct.pack_into("<III", boot_body, 0x20,
                     0x20431988,
                     0x0C000000 | ((target_pc >> 2) & 0x03FFFFFF),
                     0xAC600000)
    boot = bytearray(2048 + len(boot_body))
    boot[:8] = b"PS-X EXE"
    struct.pack_into("<IIII", boot, 16, 0x80010000, 0, 0x80010000, len(boot_body))
    boot[2048:] = boot_body
    boot = bytes(boot)

    bios = bytearray(0x20000)
    bios[0x104:0x108] = struct.pack("<I", 0xA0400000)
    derived = bytearray(bios[0x100:0x108])
    derived[4:8] = b"\0\0\0\0"
    catalog = {
        "schema": "robbit-static-source-coverage-catalog-v1",
        "game_id": "robbit",
        "scope": {"kind": "static_source_coverage", "runtime_reachability_proven": False},
        "disc": {
            "sha256": "disc-sha",
            "boot_executable": {
                "name": "SCPS_101.03", "sha256": sha(boot), "bytes": len(boot),
                "decoded_body_bytes": len(boot_body), "load_addr": "0x80010000",
                "entry_pc": "0x80010000",
            },
            "wm_save": {
                "recipe": "WM/WORLDMAP.PEX", "source_file_sha256": "wm-source",
                "decoded_executable_sha256": "wm-executable", "load_addr": "0x8009C000",
                "decoded_image_bytes": len(wm_body), "decoded_image_sha256": sha(wm_body),
                "source_coverage_entry_pc": "0x8009C004", "owner_extent_bytes": len(wm_owner),
                "owner_extent_sha256": sha(wm_owner),
            },
            "memcard_load": {
                "recipe": "WM/MEMCARD.PEX", "source_file_sha256": "memcard-source",
                "decoded_executable_sha256": "memcard-executable", "load_addr": "0x8009C000",
                "decoded_image_bytes": len(memcard_body), "decoded_image_sha256": sha(memcard_body),
                "source_coverage_entry_pc": "0x8009C008", "owner_extent_bytes": len(memcard_owner),
                "owner_extent_sha256": sha(memcard_owner),
                "source_coverage_kind": "static_source_coverage", "runtime_reachability_proven": False,
            },
        },
        "bios_copy_window": {
            "bios_sha256": sha(bytes(bios)), "bios_bytes": len(bios),
            "source_rom_range": [0x100, 0x108], "destination_load_addr": "0x00000500",
            "destination_bytes": 8,
            "changed_word": {"ram_pc": "0x00005D58", "rom_offset": 0x104, "copy_offset": 4,
                             "original_word": "0xA0400000", "derived_word": "0x00000000"},
            "entry_pc": "0x00000500", "derived_bytes_sha256": sha(bytes(derived)),
            "producer_name": "BIOS/TEST",
        },
        "guest_patch_writer": {
            "instructions": [
                {"pc": f"0x{setup_pc:08X}", "word": "0x20431988"},
                {"pc": f"0x{call_pc:08X}", "word": f"0x{0x0C000000 | ((target_pc >> 2) & 0x03FFFFFF):08X}",
                 "target_pc": f"0x{target_pc:08X}"},
                {"pc": f"0x{store_pc:08X}", "word": "0xAC600000"},
            ],
            "observed_v0_value": "0x000043D0", "computed_v1_target": "0x00005D58",
        },
    }
    def record(name, body, load="0x8009C000"):
        return {"producer_name": name, "load_addr": load, "size": len(body),
                "bytes_b64": base64.b64encode(body).decode("ascii"), "source_coverage_entries": []}

    provenance = {
        "game": "robbit", "disc_sha256": "disc-sha",
        "inputs": [
            {"path": "WM/WORLDMAP.PEX", "source_sha256": "wm-source", "decoded_sha256": "wm-executable",
             "load": "0x8009C000", "bytes": len(wm_body)},
            {"path": "WM/MEMCARD.PEX", "source_sha256": "memcard-source", "decoded_sha256": "memcard-executable",
             "load": "0x8009C000", "bytes": len(memcard_body)},
            {"path": "SCPS_101.03", "source_sha256": sha(boot), "decoded_sha256": sha(boot),
             "load": "0x80010000", "entry": "0x80010000", "bytes": len(boot_body)},
        ],
    }
    return catalog, record("WM/WORLDMAP.PEX", wm_body), record("WM/MEMCARD.PEX", memcard_body), bytes(bios), boot, provenance


class OptionalMemcardRecipeTests(unittest.TestCase):
    def test_default_keeps_two_recipes_and_optional_adds_exact_memcard_entry(self):
        catalog, wm, memcard, bios, boot, provenance = make_inputs()
        legacy = recipes.prepare_static_source_coverage(wm, bios, boot, catalog, "catalog", provenance, "prov")
        self.assertEqual(len(legacy["records"]), 2)
        self.assertEqual([job["name"] for job in legacy["jobs"]], ["WM/WORLDMAP.PEX", "BIOS/TEST"])

        extended = recipes.prepare_static_source_coverage(
            wm, bios, boot, catalog, "catalog", provenance, "prov", memcard,
        )
        self.assertEqual(len(extended["records"]), 3)
        self.assertEqual(extended["jobs"][2]["name"], "WM/MEMCARD.PEX")
        self.assertEqual(extended["jobs"][2]["required_entries"], [0x8009C008])
        self.assertEqual(extended["jobs"][2]["requirement_kind"], "static_source_coverage")
        self.assertEqual(extended["input_provenance"]["verified_aot_input_identity"]["memcard_load_addr"], "0x8009C000")
        self.assertFalse(extended["records"][2]["source_coverage_entries"][0]["runtime_reachability_proven"])

    def test_wrong_memcard_record_and_wrong_provenance_are_rejected(self):
        catalog, _wm, memcard, _bios, _boot, provenance = make_inputs()
        wrong_record = dict(memcard, producer_name="WM/OTHER.PEX")
        with self.assertRaisesRegex(ValueError, "recipe name differs"):
            recipes.prepare_memcard_record(wrong_record, catalog)
        wrong_provenance = json.loads(json.dumps(provenance))
        next(row for row in wrong_provenance["inputs"] if row["path"] == "WM/MEMCARD.PEX")["source_sha256"] = "wrong"
        with self.assertRaisesRegex(ValueError, "MEMCARD source identity"):
            recipes.validate_aot_provenance(wrong_provenance, catalog, include_memcard=True)


if __name__ == "__main__":
    unittest.main()
