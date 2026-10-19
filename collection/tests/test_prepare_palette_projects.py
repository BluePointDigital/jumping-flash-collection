from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock


ROOT = next(parent for parent in Path(__file__).resolve().parents
            if (parent / "collection/tools/patch_palette_native.py").is_file())
SCRIPT = ROOT / "collection/tools/prepare_palette_projects.py"
SPEC = importlib.util.spec_from_file_location("maintained_prepare_palette_projects", SCRIPT)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)

BUNDLE = ROOT / "collection/.workbench/static-recomp/staged/root-palette-native-real-emitter-20261016/generated-bundle"
ACCESSOR_C = ROOT / "collection/runtime/native_instruction_word_access.c"
ACCESSOR_H = ROOT / "collection/runtime/native_instruction_word_access.h"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class PaletteProjectPreparationTests(unittest.TestCase):
    def test_terminal_jf1_audit_and_missing_required_entry_are_enforced(self) -> None:
        actual = ROOT / "collection/.workbench/static-recomp/aot/jf1-jm3-coherent-bootstrap"
        proof = module.validate_terminal_preparation("jf1", actual)
        self.assertEqual(proof["recipe_count"], 42)
        self.assertEqual(proof["published_pairs"], 1549)

        with tempfile.TemporaryDirectory(prefix="palette-terminal-audit-") as temporary:
            prep = Path(temporary)
            records = prep / "records.json"
            inventory = prep / "inventory.json"
            provenance = prep / "provenance.json"
            audit = prep / "AOT_CACHE_AUDIT.json"
            records.write_text("{}\n", encoding="utf-8")
            inventory.write_text(json.dumps({"jobs": [{"name": "one", "required_entries": [4096, 4100]}]}),
                                 encoding="utf-8")
            provenance.write_text(json.dumps({"game": "jf1", "records_sha256": sha(records)}),
                                  encoding="utf-8")
            audit.write_text(json.dumps({
                "recipe_input_sha256": sha(inventory),
                "guidance_provenance_sha256": sha(provenance),
                "all_pairs_valid": True,
                "all_guards_match_known_input_bytes": True,
                "recipe_count": 1,
                "image_coverage": [{"name": "one", "required_entries_verified": 1,
                                    "native_entries": 1, "guarded_variants": 1}],
            }), encoding="utf-8")
            with self.assertRaisesRegex(module.PreparationError, "complete required-entry guard proof"):
                module.validate_terminal_preparation("jf1", prep)

    def test_same_project_rejected_before_generation_without_file_changes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="palette-overlap-") as temporary:
            root = Path(temporary)
            framework = root / "psxrecomp"
            (framework / "runtime/src").mkdir(parents=True)
            dirty = framework / "runtime/src/dirty_ram_interp.c"
            dirty.write_text("sentinel\n", encoding="utf-8")
            cmake = root / "CMakeLists.txt"
            cmake.write_text("sentinel cmake\n", encoding="utf-8")
            before = {path: sha(path) for path in (dirty, cmake)}
            projects = {"jf1": (framework, cmake), "jf2": (framework, cmake)}

            with mock.patch.object(module, "generate") as generate:
                with self.assertRaisesRegex(module.PreparationError, "project/framework targets overlap"):
                    module.prepare_both(
                        {"jf1": root / "unused-jf1", "jf2": root / "unused-jf2"},
                        {"jf1": root / "unused-layout-jf1", "jf2": root / "unused-layout-jf2"},
                        emitter=root / "unused-emitter", toolkit=root / "unused-toolkit",
                        bundle_output=root / "unused-bundle", projects=projects,
                        accessor_source=root / "unused-accessor.c",
                        accessor_header=root / "unused-accessor.h", cps_enabled=True)
                generate.assert_not_called()
            self.assertEqual({path: sha(path) for path in before}, before)

    def test_one_pinned_bundle_installs_with_distinct_title_family_receipts(self) -> None:
        receipt = json.loads((BUNDLE / "receipt.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt["function_count"], 108)
        self.assertEqual(receipt["unique_entry_segment_owners"], 72)
        self.assertEqual(receipt["dispatch_keys"], 216)
        self.assertEqual(receipt["ambiguous_dispatch_key_count"], 0)

        with tempfile.TemporaryDirectory(prefix="palette-normal-projects-") as temporary:
            temp = Path(temporary)
            projects = {}
            for game in ("jf1", "jf2"):
                original = ROOT / f"collection/.workbench/native/{game}"
                project = temp / game
                framework = project / "psxrecomp"
                (framework / "runtime/src").mkdir(parents=True)
                (framework / "runtime/include").mkdir(parents=True)
                shutil.copyfile(original / "psxrecomp/runtime/src/dirty_ram_interp.c",
                                framework / "runtime/src/dirty_ram_interp.c")
                cmake = project / "CMakeLists.txt"
                shutil.copyfile(original / "CMakeLists.txt", cmake)
                projects[game] = (framework, cmake)

            installed = module.install_existing_bundle(
                BUNDLE, projects, accessor_source=ACCESSOR_C, accessor_header=ACCESSOR_H)
            for game in ("jf1", "jf2"):
                framework, cmake = projects[game]
                actual = json.loads((framework / "runtime/palette_native_patch_receipt.json").read_text(encoding="utf-8"))
                self.assertEqual(actual["selected_game"], game)
                self.assertEqual(actual["selected_family_sha256"], module.install.__globals__["FAMILY_HASHES"][game])
                self.assertEqual(actual["dispatcher_sha256"], receipt["host_dispatch_sha256"])
                self.assertIn(module.install.__globals__["MARKER"], cmake.read_text(encoding="utf-8"))
                self.assertEqual(sha(framework / "runtime/src/palette_native_dispatch.c"),
                                 actual["outputs"]["psxrecomp/runtime/src/palette_native_dispatch.c"])
                self.assertEqual(installed[game]["dispatcher_sha256"], receipt["host_dispatch_sha256"])
                self.assertEqual(actual["catalog_title_counts"], {"jf1": 12, "jf2": 24})


if __name__ == "__main__":
    unittest.main()
