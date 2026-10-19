import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from static_source_set import verify_static_sources


def sha(data):
    return hashlib.sha256(data).hexdigest()


class StaticSourceSetTest(unittest.TestCase):
    def fixture(self, root):
        source = root / "static"
        source.mkdir()
        main = b"static dispatcher fixture\n"
        part = b"static shard fixture\n"
        (source / "overlays_static.c").write_bytes(main)
        (source / "overlays_static_0000.c").write_bytes(part)
        audit = {
            "static": True,
            "game_id": "SCPS-10103",
            "recipe_input_sha256": "7" * 64,
            "recipe_count": 1,
            "disc_recipe_count": 1,
            "bios_recipe_count": 0,
            "game_installed_recipe_count": 0,
            "all_pairs_valid": True,
            "all_guards_match_known_input_bytes": True,
            "full_static_coverage_proven": False,
            "image_coverage": [{"name": "image-1", "required_entries_verified": 1,
                                 "native_entries": 1, "guarded_variants": 1}],
            "variants": [{"entry": "0x80001000", "crc": "0x89ABCDEF",
                          "matched_recipe": "image-1"}],
            "published_variants": 1,
            "files": {"overlays_static.c": sha(main),
                      "overlays_static_0000.c": sha(part)},
        }
        expected = {
            "audit_sha256": sha(json.dumps(audit).encode()),
            "game_id": audit["game_id"],
            "image_names": ["image-1"],
            "recipe_input_sha256": audit["recipe_input_sha256"],
            "recipe_count": audit["recipe_count"],
            "recipe_counts": {"disc": 1, "bios": 0, "game_installed": 0},
        }
        audit_path = root / "AOT_STATIC_AUDIT.json"
        audit_path.write_text(json.dumps(audit), encoding="utf-8")
        return audit_path, source, audit, expected

    def test_returns_exact_source_set_and_rejects_drift(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            audit_path, source, audit, expected = self.fixture(root)
            result = verify_static_sources(audit_path, source, expected)
            self.assertEqual([row["name"] for row in result["sources"]],
                             ["overlays_static.c", "overlays_static_0000.c"])
            self.assertFalse(result["objects_verified"])
            self.assertFalse(result["executable_verified"])
            self.assertFalse(result["full_static_coverage_proven"])
            self.assertFalse(result["generation_chain_provenance_verified"])

            for label in ("changed file", "missing split", "extra split", "path traversal",
                          "wrong title", "wrong audit pin", "failed guard audit",
                          "missing per-image audit", "unknown matched recipe",
                          "zero native coverage", "boolean recipe count"):
                with self.subTest(label=label):
                    with tempfile.TemporaryDirectory() as isolated:
                        case_root = Path(isolated)
                        path, case_source, original, pins = self.fixture(case_root)
                        if label == "changed file":
                            (case_source / "overlays_static_0000.c").write_bytes(b"changed")
                        elif label == "missing split":
                            (case_source / "overlays_static_0000.c").unlink()
                        elif label == "extra split":
                            (case_source / "overlays_static_0001.c").write_bytes(b"extra")
                        elif label == "path traversal":
                            original["files"]["../overlays_static_0000.c"] = original["files"].pop("overlays_static_0000.c")
                        elif label == "failed guard audit":
                            original["all_guards_match_known_input_bytes"] = False
                        elif label == "missing per-image audit":
                            original.pop("image_coverage")
                        elif label == "unknown matched recipe":
                            original["variants"][0]["matched_recipe"] = "not-audited-image"
                        elif label == "zero native coverage":
                            original["image_coverage"][0]["native_entries"] = 0
                        elif label == "boolean recipe count":
                            original["disc_recipe_count"] = True
                        if label == "wrong title":
                            pins["game_id"] = "wrong-title"
                        elif label == "wrong audit pin":
                            pins["audit_sha256"] = "0" * 64
                        elif label in ("path traversal", "failed guard audit", "missing per-image audit",
                                       "unknown matched recipe", "zero native coverage", "boolean recipe count"):
                            pins["audit_sha256"] = sha(json.dumps(original).encode())
                        path.write_text(json.dumps(original), encoding="utf-8")
                        with self.assertRaises(ValueError):
                            verify_static_sources(path, case_source, pins)


if __name__ == "__main__":
    unittest.main()
