from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path
import sys


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "collection/tools"))
import palette_native_sources as portable_sources
SPEC = importlib.util.spec_from_file_location("patch_palette_native", REPO / "collection/tools/patch_palette_native.py")
patcher = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(patcher)


STAGE = REPO / "collection/.workbench/static-recomp/staged/luna-static-coverage/host-linked-native-dispatch"
V3_DIRTY = STAGE / "private-host-integration-v3/framework/runtime/src/dirty_ram_interp.c"
REAL_BUNDLE = STAGE
REAL_AUDIT = REPO / "collection/.workbench/static-recomp/staged/root-palette-family-audit/report.json"
ACCESSOR_SOURCE = REPO / "collection/.workbench/static-recomp/staged/luna-static-coverage/jm1-shape-capability/abi31-bridge/instruction_word_access.c"
ACCESSOR_HEADER = REPO / "collection/.workbench/static-recomp/staged/luna-static-coverage/jm1-shape-capability/abi31-bridge/native_instruction_word_access.h"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class PaletteNativePatcherTests(unittest.TestCase):
    def seed(self, root: Path, game: str) -> tuple[Path, Path, Path, Path]:
        framework = root / "psxrecomp"
        dirty = framework / "runtime/src/dirty_ram_interp.c"
        dirty.parent.mkdir(parents=True)

        if game == "jf1":
            # Start from the reviewed v3 hook source, remove only its two exact
            # blocks, and verify the fixture reconstructs the pinned clean input.
            source_raw = V3_DIRTY.read_bytes()
            source = source_raw.decode("utf-8").replace("\r\n", "\n")
            self.assertEqual(source.count(patcher.MAIN_HOOK), 1)
            self.assertEqual(source.count(patcher.LOCAL_HOOK), 1)
            clean_text = source.replace(patcher.MAIN_HOOK, "", 1).replace(patcher.LOCAL_HOOK, "", 1)
            clean_raw = clean_text.replace("\n", "\r\n").encode("utf-8")
            self.assertEqual(hashlib.sha256(clean_raw).hexdigest(), patcher.DIRTY_BASE_HASHES["jf1"])
            dirty.write_bytes(clean_raw)
        else:
            # JF2 uses its pinned clean runtime source as a read-only fixture.
            shutil.copyfile(REPO / "collection/.workbench/native/jf2/psxrecomp/runtime/src/dirty_ram_interp.c", dirty)

        project = root / "CMakeLists.txt"
        shutil.copyfile(REPO / f"collection/.workbench/native/{game}/CMakeLists.txt", root / "CMakeLists.txt")
        project = root / "CMakeLists.txt"
        bundle = root / "bundle"
        bundle.mkdir()
        for name in ("host_dispatch_receipt.json", "receipt.json", "host_dispatch_candidate.c", "all_36x3_specialized.c"):
            shutil.copyfile(REAL_BUNDLE / name, bundle / name)
        audit = root / "family-report.json"
        shutil.copyfile(REAL_AUDIT, audit)
        return framework, project, bundle, audit

    def run_clean_install(self, game: str, lf: bool) -> None:
        with tempfile.TemporaryDirectory() as temp:
            framework, project, bundle, audit = self.seed(Path(temp), game)
            if lf:
                dirty_input = framework / "runtime/src/dirty_ram_interp.c"
                dirty_input.write_bytes(dirty_input.read_bytes().replace(b"\r\n", b"\n"))
            first = patcher.prepare(framework, project, bundle, audit, accessor_source=ACCESSOR_SOURCE,
                                   accessor_header=ACCESSOR_HEADER, game=game, cps_enabled=True)
            dirty = framework / "runtime/src/dirty_ram_interp.c"
            if game == "jf1":
                expected = (patcher.DIRTY_PATCHED_HASHES[game] if lf else
                            "20bcd03cc658e5cac9c0fb7dfb86e21a2b39d92a2a3ecb67a4ecdd2fa9aaf36c")
                self.assertEqual(digest(dirty), expected)
                self.assertEqual(dirty.read_text(encoding="utf-8"), V3_DIRTY.read_text(encoding="utf-8"))
            dispatcher = framework / "runtime/src/palette_native_dispatch.c"
            self.assertIn(b"palette_dispatch_hits++; /* Count accepted handler entry", dispatcher.read_bytes())
            self.assertEqual((framework / "runtime/src/native_instruction_word_access.c").is_file(), True)
            self.assertEqual((framework / "runtime/include/native_instruction_word_access.h").is_file(), True)
            receipt_path = framework / "runtime/palette_native_patch_receipt.json"
            before = {str(p): digest(p) for p in [dirty, dispatcher, project, receipt_path]}
            second = patcher.prepare(framework, project, bundle, audit, accessor_source=ACCESSOR_SOURCE,
                                     accessor_header=ACCESSOR_HEADER, game=game, cps_enabled=True)
            after = {str(p): digest(p) for p in [dirty, dispatcher, project, receipt_path]}
            self.assertEqual(first, second)
            self.assertEqual(before, after)

            moved = Path(temp) / "relocated"
            moved.mkdir()
            moved_framework = moved / "psxrecomp"
            shutil.copytree(framework, moved_framework)
            moved_project = moved / "CMakeLists.txt"
            shutil.copyfile(project, moved_project)
            moved_bundle = moved / "bundle"
            shutil.copytree(bundle, moved_bundle)
            moved_audit = moved / "family-report.json"
            shutil.copyfile(audit, moved_audit)
            moved_accessor = moved / "instruction_word_access.c"
            moved_header = moved / "native_instruction_word_access.h"
            shutil.copyfile(ACCESSOR_SOURCE, moved_accessor)
            shutil.copyfile(ACCESSOR_HEADER, moved_header)
            relocated_receipt = patcher.prepare(
                moved_framework, moved_project, moved_bundle, moved_audit,
                accessor_source=moved_accessor, accessor_header=moved_header,
                game=game, cps_enabled=True)
            self.assertEqual(first, relocated_receipt)
            self.assertEqual(
                (moved_framework / "runtime/palette_native_patch_receipt.json").read_bytes(),
                receipt_path.read_bytes())
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            self.assertEqual(receipt["counter_semantics"], "accepted native handler entries; incremented before handler safe points")

    def test_clean_install_is_idempotent_for_both_supported_titles(self) -> None:
        for game in ("jf1", "jf2"):
            for lf in (False, True):
                with self.subTest(game=game, line_endings="LF" if lf else "CRLF"):
                    self.run_clean_install(game, lf)

    def test_drift_fails_before_any_destination_write(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            framework, project, bundle, audit = self.seed(Path(temp), "jf1")
            dirty = framework / "runtime/src/dirty_ram_interp.c"
            clean = dirty.read_bytes()
            dirty.write_bytes(clean.replace(b"overlay_loader_dispatch", b"overlay_loader_dispatchX", 1))
            paths = [
                framework / "runtime/src/palette_native_dispatch.c",
                framework / "runtime/src/native_instruction_word_access.c",
                framework / "runtime/include/native_instruction_word_access.h",
                framework / "runtime/palette_native_patch_receipt.json",
            ]
            with self.assertRaises(patcher.PreparationError):
                patcher.prepare(framework, project, bundle, audit, accessor_source=ACCESSOR_SOURCE,
                                accessor_header=ACCESSOR_HEADER, game="jf1", cps_enabled=True)
            self.assertTrue(all(not path.exists() for path in paths))
            self.assertNotIn(patcher.MARKER, project.read_text(encoding="utf-8"))

            dirty.write_bytes(clean)
            cmake_original = project.read_bytes()
            project.write_text(cmake_original.decode("utf-8").replace(
                '"${CMAKE_CURRENT_SOURCE_DIR}/psxrecomp"',
                '"${CMAKE_CURRENT_SOURCE_DIR}/other-framework"', 1), encoding="utf-8")
            with self.assertRaises(patcher.PreparationError):
                patcher.prepare(framework, project, bundle, audit, accessor_source=ACCESSOR_SOURCE,
                                accessor_header=ACCESSOR_HEADER, game="jf1", cps_enabled=True)
            self.assertTrue(all(not path.exists() for path in paths))
            self.assertEqual((framework / "runtime/src/dirty_ram_interp.c").read_bytes(), clean)

    def test_portable_evidence_installs_reviewed_code_and_rejects_provenance_drift(self) -> None:
        # Reuse the reviewed C fixture. This checks schema-2 installation, not
        # a fresh emitter run or a claim that the fixture toolkit was rebuilt.
        with tempfile.TemporaryDirectory() as temp:
            framework, project, bundle, _ = self.seed(Path(temp), "jf1")
            catalog = json.loads(portable_sources.CATALOG.read_text(encoding="utf-8"))
            semantic = (json.dumps(catalog, indent=2, ensure_ascii=True) + "\n").encode()
            semantic_sha = hashlib.sha256(semantic).hexdigest()
            self.assertEqual(semantic_sha, portable_sources.CATALOG_SHA256)
            file_path = "runtime/include/fixture.h"
            file_sha = hashlib.sha256(b"fixture toolkit identity").hexdigest()
            tree_sha = hashlib.sha256(len(file_path.encode()).to_bytes(4, "little")
                                      + file_path.encode() + bytes.fromhex(file_sha)).hexdigest()
            tool_sha = hashlib.sha256(b"fixture generator identity").hexdigest()
            provenance = {
                "schema": 1, "semantic_catalog_sha256": semantic_sha,
                "emitter_sha256": patcher.EMITTER_SHA256, "toolkit_tree_sha256": tree_sha,
                "toolkit_file_count": 1, "toolkit_files": [{"path": file_path, "sha256": file_sha}],
                "generator_sha256": tool_sha, "source_audit_tool_sha256": tool_sha,
                "inputs": {game: {"records_sha256": patcher.RECORD_HASHES[game],
                                   "layout_sha256": catalog["layout_sha256"][game],
                                   "records_path": f"relocated/{game}/records.json",
                                   "layout_path": f"relocated/{game}/layout.json"}
                           for game in ("jf1", "jf2")},
            }
            prov_raw = (json.dumps(provenance, indent=2) + "\n").encode()
            common = {
                "schema": 2, "function_count": 108, "unique_entry_segment_owners": 72,
                "dispatch_keys": 216, "ambiguous_dispatch_key_count": 0,
                "family_hashes": patcher.FAMILY_HASHES,
                "host_dispatch_sha256": patcher.HOST_BUNDLE_SHA256,
                "emitted_functions_sha256": patcher.EMITTED_C_SHA256,
                "emitter_sha256": patcher.EMITTER_SHA256,
                "toolkit_tree_sha256": tree_sha,
                "generator_sha256": tool_sha, "source_audit_tool_sha256": tool_sha,
                "semantic_catalog_sha256": semantic_sha,
                "input_provenance_sha256": hashlib.sha256(prov_raw).hexdigest(),
            }
            entries = json.loads((bundle / "receipt.json").read_text())["entries"]
            receipt = {**common, "kind": "palette-native-generated-bundle",
                       "accessor_sha256": patcher.ACCESSOR_C_SHA256,
                       "accessor_header_sha256": patcher.ACCESSOR_H_SHA256,
                       "legal_entry_offsets_by_family": {name: catalog["families"][name]["legal_entry_offsets"]
                                                          for name in ("jf1", "jf2")},
                       "segment_names": ["kuseg", "kseg0", "kseg1"], "entries": entries}
            host = {**common, "accessor_sha256": patcher.ACCESSOR_C_SHA256,
                    "accessor_header_sha256": patcher.ACCESSOR_H_SHA256,
                    "duplicate_owner_bodies_identical": True}
            (bundle / "semantic-catalog.json").write_bytes(semantic)
            (bundle / "input-provenance.json").write_bytes(prov_raw)
            host_raw = json.dumps(host).encode()
            (bundle / "host_dispatch_receipt.json").write_bytes(host_raw)
            receipt["host_dispatch_receipt_sha256"] = hashlib.sha256(host_raw).hexdigest()
            receipt_path = bundle / "receipt.json"
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            dirty = framework / "runtime/src/dirty_ram_interp.c"
            before = (dirty.read_bytes(), project.read_bytes())
            dispatcher = framework / "runtime/src/palette_native_dispatch.c"
            for field, replacement in (("input_provenance_sha256", "0" * 64),
                                       ("function_count", 107)):
                damaged = {**receipt, field: replacement}
                receipt_path.write_text(json.dumps(damaged), encoding="utf-8")
                with self.assertRaises(patcher.PreparationError):
                    patcher.prepare(framework, project, bundle, accessor_source=ACCESSOR_SOURCE,
                                    accessor_header=ACCESSOR_HEADER, game="jf1", cps_enabled=True)
                self.assertEqual(before, (dirty.read_bytes(), project.read_bytes()))
                self.assertFalse(dispatcher.exists())
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            proof = patcher.prepare(framework, project, bundle, accessor_source=ACCESSOR_SOURCE,
                                    accessor_header=ACCESSOR_HEADER, game="jf1", cps_enabled=True)
            self.assertEqual(proof["evidence_schema"], 2)
            self.assertEqual(proof["selected_record_sha256"], patcher.RECORD_HASHES["jf1"])
            self.assertEqual(proof["input_provenance_sha256"], common["input_provenance_sha256"])
            self.assertIn(b"palette_dispatch_hits++; /* Count accepted handler entry", dispatcher.read_bytes())


if __name__ == "__main__":
    unittest.main()
