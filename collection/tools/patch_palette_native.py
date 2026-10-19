"""Install the reviewed palette native dispatcher into an explicit CPS project copy.

This is an opt-in source preparation step. It never runs automatically from the
normal framework patch pipeline and does not generate palette code; callers
must provide a separately generated, hash-pinned bundle. Portable schema-2
bundles carry their semantic catalog and input provenance alongside the code.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from palette_native_sources import CATALOG_SHA256


HOST_BUNDLE_SHA256 = "34d268ccf92c5923bbeea401e2a71d8d2c0376fd95526cf9087650b75c001701"
HOST_RECEIPT_SHA256 = "bce528cff4dbc4cc7dafc42df212e73f49501bc204069f94151124f72cb9279e"
EMITTED_C_SHA256 = "d1bf58938fb2da9a5e5a147e7234d03a9305be6f031edc58462e1b20142bac69"
BUNDLE_RECEIPT_SHA256 = "32d528895343b574f7048935f8d74a1487404c9da1d8395466469cff4c9fa3bd"
FAMILY_AUDIT_SHA256 = "87e0410c4ac1ddce670febbb64038e882a2c2d2c4a4ff368673aedee3db239e3"
ACCESSOR_C_SHA256 = "93e608b6560c77de3ec1375d503815fb85cde60a31195c7228f65507cfa57f28"
ACCESSOR_H_SHA256 = "dca9116ff71be5d33d607ac3a55836044572ccaf52efaf2618f3902addcc138f"
EMITTER_SHA256 = "1316d5c8e6df229e1d2cd09cdb5ad45e2fe9ea4d41f7ef2c0739f14a92ded77c"
FAMILY_HASHES = {
    "jf1": "ac65052c9c32c4a8d7e77a929c7eb1e65487fa9ec07807fd1fd406fdb3bc33bc",
    "jf2": "3184275559fc14498f9432044dc19715ad265f0bccb9b744da6c19fc46b0b16c",
}
RECORD_HASHES = {
    "jf1": "e0b484ea8f814ec887bffffdd0b3c17b23e03814b2750f228c87722cea9944a6",
    "jf2": "d906c240824dedf0379a734e8f6465f8af514814fc255a54a7d91eff27bf6a57",
}
DIRTY_BASE_HASHES = {
    "jf1": "4dda313ef722f50da6f7e61f099b4ec91299c76750d76052591550016f7a6b05",
    "jf2": "75a53e72c055fd78fbb4592a19cec9ddae3ced1ee9591e69995992f444db6825",
}
DIRTY_BASE_LF_HASHES = {
    "jf1": "1f711832d61cd7f38bbdc171ce35608da17e7efe7424597dc0f7545b9a28346e",
    "jf2": "bcb4513cf3a115b87befaa17bdaf6a881bbe743696db69b4888738c8f24d12c1",
}
DIRTY_PATCHED_HASHES = {
    "jf1": "2413ccf559f7929d6477c71a02a014527cb81f2d88051c9bc9af163e1ac1f93c",
    "jf2": "17ffdbea89c4c4553b81796dc3dc394e0b4cff405f7bfe5adc5e2a4123dd4a6f",
}

MAIN_ANCHOR = """    {
        extern int overlay_loader_dispatch(CPUState *cpu, uint32_t addr);
        if (!forced && overlay_loader_dispatch(cpu, addr)) {"""
LOCAL_ANCHOR = "                if (overlay_loader_is_candidate(target_phys)) {"
MAIN_HOOK = """#if !defined(PSX_ORACLE_BUILD)
    {
        extern int overlay_loader_get_native_exec(void);
        extern int g_psx_cps_mode;
        extern int psx_palette_native_try_dispatch(CPUState*,uint32_t,int,int,int);
        if (!g_precise_mode && !g_ls_replay_active && psx_palette_native_try_dispatch(cpu,addr,forced,overlay_loader_get_native_exec(),g_psx_cps_mode)) {
            if (_ovfp) overlay_fp_log(addr, _in_regs, cpu, 1);
            return 1;
        }
    }
#endif
"""
LOCAL_HOOK = """#if !defined(PSX_ORACLE_BUILD)
                {
                    extern int overlay_loader_get_native_exec(void);
                    extern int g_psx_cps_mode;
                    extern int psx_palette_native_try_dispatch(CPUState*,uint32_t,int,int,int);
                    if (!g_precise_mode && !g_ls_replay_active && psx_palette_native_try_dispatch(cpu,target,(int)span_forced(target_phys),overlay_loader_get_native_exec(),g_psx_cps_mode)) {
                        g_dirty_ram_native_handoffs++;
                        g_dirty_ram_blocks_run++;
                        if (pc_entry) pc_entry->insns += (uint64_t)insns_executed;
                        g_dirty_interp_chain_target = cpu->pc;
                        OV_FPLOG_RET1();
                    }
                }
#endif
"""
MARKER = "# COLLECTION_PALETTE_NATIVE_CPS_V1"
CMAKE_BLOCK = f"""\n{MARKER}\n# Explicit opt-in: generated from the verified 36-image palette family catalog.\ntarget_sources(psx-runtime PRIVATE\n    \"${{PSXRECOMP_ROOT}}/runtime/src/palette_native_dispatch.c\"\n    \"${{PSXRECOMP_ROOT}}/runtime/src/native_instruction_word_access.c\")\ntarget_compile_definitions(psx-runtime PRIVATE COLLECTION_PALETTE_NATIVE_CPS=1)\n"""


class PreparationError(RuntimeError):
    """Raised when inputs or destinations do not match the reviewed contract."""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_pinned(path: Path, expected: str, label: str) -> bytes:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise PreparationError(f"missing {label}: {path}") from exc
    actual = sha256_bytes(data)
    if actual != expected:
        raise PreparationError(f"{label} SHA-256 mismatch: expected {expected}, got {actual}")
    return data


def _read_json(path: Path, label: str) -> tuple[bytes, dict[str, Any]]:
    try:
        raw = path.read_bytes()
        value = json.loads(raw)
    except (OSError, ValueError) as exc:
        raise PreparationError(f"cannot read {label}: {path}") from exc
    if not isinstance(value, dict):
        raise PreparationError(f"{label} must be a JSON object")
    return raw, value


def _validate_portable_evidence(bundle: Path, receipt_raw: bytes,
                                receipt: dict[str, Any], game: str) -> dict[str, Any]:
    """Validate portable provenance while keeping the reviewed C identities exact."""
    if receipt.get("kind") != "palette-native-generated-bundle":
        raise PreparationError("unknown portable palette bundle kind")
    semantic_raw = _read_pinned(bundle / "semantic-catalog.json", CATALOG_SHA256,
                                "portable palette semantic catalog")
    catalog = json.loads(semantic_raw)
    provenance_raw, provenance = _read_json(bundle / "input-provenance.json", "palette input provenance")
    host_raw, host = _read_json(bundle / "host_dispatch_receipt.json", "portable dispatcher receipt")
    _read_pinned(bundle / "host_dispatch_candidate.c", HOST_BUNDLE_SHA256, "native dispatcher")
    _read_pinned(bundle / "all_36x3_specialized.c", EMITTED_C_SHA256, "generated native bundle")
    semantic_sha = sha256_bytes(semantic_raw)
    provenance_sha = sha256_bytes(provenance_raw)
    if (receipt.get("semantic_catalog_sha256") != semantic_sha
            or receipt.get("input_provenance_sha256") != provenance_sha
            or provenance.get("semantic_catalog_sha256") != semantic_sha):
        raise PreparationError("portable source catalog/provenance binding changed")
    if (receipt.get("emitter_sha256") != EMITTER_SHA256
            or receipt.get("emitted_functions_sha256") != EMITTED_C_SHA256
            or receipt.get("host_dispatch_sha256") != HOST_BUNDLE_SHA256):
        raise PreparationError("portable bundle emitter or generated C identity changed")
    if (host.get("schema") != 2 or host.get("host_dispatch_sha256") != HOST_BUNDLE_SHA256
            or host.get("accessor_sha256") != ACCESSOR_C_SHA256
            or host.get("accessor_header_sha256") != ACCESSOR_H_SHA256
            or host.get("semantic_catalog_sha256") != semantic_sha
            or host.get("input_provenance_sha256") != provenance_sha):
        raise PreparationError("portable dispatcher provenance or accessor identity changed")
    if receipt.get("host_dispatch_receipt_sha256") != sha256_bytes(host_raw):
        raise PreparationError("portable dispatcher receipt hash changed")
    if (receipt.get("accessor_sha256") != ACCESSOR_C_SHA256
            or receipt.get("accessor_header_sha256") != ACCESSOR_H_SHA256):
        raise PreparationError("portable bundle accessor identity changed")
    for proof in (receipt, host):
        if (proof.get("function_count") != 108
                or proof.get("unique_entry_segment_owners") != 72
                or proof.get("dispatch_keys") != 216
                or proof.get("ambiguous_dispatch_key_count") != 0
                or proof.get("family_hashes") != FAMILY_HASHES):
            raise PreparationError("portable dispatcher counts, ambiguity or families changed")
    for field in ("emitter_sha256", "toolkit_tree_sha256", "emitted_functions_sha256"):
        value = receipt.get(field)
        if (not isinstance(value, str) or len(value) != 64
                or any(char not in "0123456789abcdef" for char in value)
                or host.get(field) != value):
            raise PreparationError(f"portable dispatcher {field} binding changed")
    for field in ("emitter_sha256", "toolkit_tree_sha256", "generator_sha256", "source_audit_tool_sha256"):
        value = receipt.get(field)
        if (not isinstance(value, str) or len(value) != 64
                or any(char not in "0123456789abcdef" for char in value)
                or host.get(field) != value or provenance.get(field) != value):
            raise PreparationError(f"portable input provenance {field} binding changed")
    files = provenance.get("toolkit_files")
    if (not isinstance(files, list) or not files
            or provenance.get("toolkit_file_count") != len(files)):
        raise PreparationError("portable toolkit file inventory is missing or incomplete")
    tree_digest = hashlib.sha256()
    paths = []
    for item in files:
        try:
            path, file_sha = item["path"], item["sha256"]
            if (not isinstance(path, str) or not path or "\\" in path or ":" in path
                    or any(part in ("", ".", "..") for part in path.split("/"))
                    or not isinstance(file_sha, str) or len(file_sha) != 64
                    or any(char not in "0123456789abcdef" for char in file_sha)):
                raise PreparationError("malformed portable toolkit file identity")
            relative = path.encode("utf-8")
            tree_digest.update(len(relative).to_bytes(4, "little"))
            tree_digest.update(relative)
            tree_digest.update(bytes.fromhex(file_sha))
            paths.append(path)
        except (TypeError, KeyError) as exc:
            raise PreparationError("malformed portable toolkit file inventory") from exc
    if paths != sorted(set(paths)) or tree_digest.hexdigest() != receipt["toolkit_tree_sha256"]:
        raise PreparationError("portable toolkit tree hash or inventory order changed")
    if host.get("duplicate_owner_bodies_identical") is not True:
        raise PreparationError("portable dispatcher owner coherence was not established")
    if receipt.get("segment_names") != ["kuseg", "kseg0", "kseg1"]:
        raise PreparationError("portable bundle segment inventory changed")
    if receipt.get("legal_entry_offsets_by_family") != {
            name: catalog["families"][name]["legal_entry_offsets"] for name in FAMILY_HASHES}:
        raise PreparationError("portable bundle continuation inventory changed")
    expected = {}
    source_images = {(row["game"], row["image"]): row for row in catalog["images"]}
    for row in catalog["images"]:
        for segment, base in (("kuseg", 0), ("kseg0", 0x80000000), ("kseg1", 0xA0000000)):
            expected[(row["game"], row["image"], segment)] = (
                (int(row["entry"], 16) & 0x1FFFFFFF) | base, row["family_sha256"])
    entries = receipt.get("entries")
    if not isinstance(entries, list) or len(entries) != 108:
        raise PreparationError("portable bundle must have exactly 108 entry records")
    seen = set()
    functions = set()
    for row in entries:
        try:
            key = (row["game"], row["image"], row["segment"])
            identity = (int(row["entry"], 16), row["family_sha256"])
            if key in seen or expected.get(key) != identity:
                raise PreparationError("portable bundle entry/segment source identity changed")
            image = source_images[key[:2]]
            function = "palette_" + re.sub(r"[^A-Za-z0-9_]+", "_", "_".join(key)).strip("_").lower()
            if (row.get("body_sha256") != image["body_sha256"]
                    or row.get("template_sha256") != image["template_sha256"]
                    or row.get("legal_entry_offsets") != catalog["families"][key[0]]["legal_entry_offsets"]
                    or row.get("function") != function
                    or row["function"] in functions):
                raise PreparationError("portable bundle source-body or continuation identity changed")
            seen.add(key)
            functions.add(row["function"])
        except (KeyError, TypeError, ValueError) as exc:
            raise PreparationError("malformed portable bundle entry record") from exc
    if seen != set(expected):
        raise PreparationError("portable bundle image/segment inventory changed")
    inputs = provenance.get("inputs")
    if not isinstance(inputs, dict) or set(inputs) != set(FAMILY_HASHES):
        raise PreparationError("portable source provenance must identify both titles")
    for name in FAMILY_HASHES:
        item = inputs[name]
        if not isinstance(item, dict) or any(
                not isinstance(item.get(field), str) or len(item[field]) != 64
                or any(char not in "0123456789abcdef" for char in item[field])
                for field in ("records_sha256", "layout_sha256")):
            raise PreparationError(f"malformed portable source hash for {name}")
    return {
        "evidence_schema": 2,
        "dispatcher_sha256": HOST_BUNDLE_SHA256,
        "dispatcher_receipt_sha256": sha256_bytes(host_raw),
        "generated_bundle_sha256": EMITTED_C_SHA256,
        "bundle_receipt_sha256": sha256_bytes(receipt_raw),
        "semantic_catalog_sha256": semantic_sha,
        "input_provenance_sha256": provenance_sha,
        "toolkit_tree_sha256": receipt["toolkit_tree_sha256"],
        "selected_game": game,
        "selected_family_sha256": FAMILY_HASHES[game],
        "selected_record_sha256": inputs[game]["records_sha256"],
        "emitter_sha256": EMITTER_SHA256,
        "catalog_image_count": 36,
        "catalog_title_counts": {"jf1": 12, "jf2": 24},
    }


def validate_evidence(bundle: Path, family_audit: Path | None, game: str) -> dict[str, Any]:
    if game not in FAMILY_HASHES:
        raise PreparationError("game must be exactly 'jf1' or 'jf2'")
    receipt_raw, candidate = _read_json(bundle / "receipt.json", "generated bundle receipt")
    if candidate.get("schema") == 2:
        return _validate_portable_evidence(bundle, receipt_raw, candidate, game)
    if family_audit is None:
        raise PreparationError("legacy bundles require an explicit pinned family audit")
    host_receipt = json.loads(_read_pinned(bundle / "host_dispatch_receipt.json", HOST_RECEIPT_SHA256, "dispatcher receipt"))
    bundle_receipt_raw = _read_pinned(bundle / "receipt.json", BUNDLE_RECEIPT_SHA256, "generated bundle receipt")
    bundle_receipt = json.loads(bundle_receipt_raw)
    audit_raw = _read_pinned(family_audit, FAMILY_AUDIT_SHA256, "36-image family audit")
    audit = json.loads(audit_raw)
    _read_pinned(bundle / "host_dispatch_candidate.c", HOST_BUNDLE_SHA256, "native dispatcher")
    _read_pinned(bundle / "all_36x3_specialized.c", EMITTED_C_SHA256, "generated native bundle")

    if host_receipt.get("host_dispatch_sha256") != HOST_BUNDLE_SHA256:
        raise PreparationError("dispatcher receipt does not identify the reviewed source")
    if host_receipt.get("accessor_sha256") != ACCESSOR_C_SHA256 or host_receipt.get("accessor_header_sha256") != ACCESSOR_H_SHA256:
        raise PreparationError("dispatcher receipt accessor hashes drifted")
    if host_receipt.get("emitted_functions") != 108 or host_receipt.get("unique_entry_segment_owners") != 72 or host_receipt.get("dispatch_keys") != 216 or host_receipt.get("ambiguous_dispatch_key_count") != 0:
        raise PreparationError("dispatcher receipt counts or ambiguity status drifted")
    if bundle_receipt.get("emitter_sha256") != EMITTER_SHA256 or bundle_receipt.get("family_audit_sha256") != FAMILY_AUDIT_SHA256:
        raise PreparationError("generated bundle is not bound to the pinned emitter/family audit")
    if bundle_receipt.get("function_count") != 108 or bundle_receipt.get("segment_names") != ["kuseg", "kseg0", "kseg1"]:
        raise PreparationError("generated bundle function or segment inventory changed")
    if bundle_receipt.get("source_record_sha256") != RECORD_HASHES:
        raise PreparationError("bundle source record hashes do not match the reviewed profiles")
    if host_receipt.get("family_hashes") != FAMILY_HASHES:
        raise PreparationError("dispatcher families do not match the reviewed JF1/JF2 templates")
    if audit.get("image_count") != 36 or len(audit.get("images", [])) != 36 or audit.get("family_count") != 2:
        raise PreparationError("family catalog is not the reviewed 36-image/two-family catalog")
    counts = {name: sum(row.get("game") == name for row in audit["images"]) for name in FAMILY_HASHES}
    if counts != {"jf1": 12, "jf2": 24}:
        raise PreparationError(f"family catalog title counts changed: {counts}")
    catalog_keys = {(row["game"], row["image"]) for row in audit["images"]}
    if len(catalog_keys) != 36:
        raise PreparationError("family catalog contains duplicate or missing image identities")
    for name, expected_record_hash in RECORD_HASHES.items():
        if audit.get("inputs", {}).get(name, {}).get("records_sha256") != expected_record_hash:
            raise PreparationError(f"family audit source-record binding changed for {name}")
    if any(row.get("normalized_family_sha256") != FAMILY_HASHES.get(row.get("game")) for row in audit["images"]):
        raise PreparationError("one or more catalog images no longer match the pinned family")
    entries = bundle_receipt.get("entries", [])
    if len(entries) != 108:
        raise PreparationError("generated bundle must contain exactly 108 image/segment entry records")
    entry_keys = {(row.get("game"), row.get("image")) for row in entries}
    if entry_keys != catalog_keys:
        raise PreparationError("generated bundle image set differs from the pinned 36-image catalog")
    for key in catalog_keys:
        group = [row for row in entries if (row.get("game"), row.get("image")) == key]
        if sorted(row.get("segment") for row in group) != ["kseg0", "kseg1", "kuseg"]:
            raise PreparationError(f"generated bundle segment entries changed for {key}")
        expected_family = FAMILY_HASHES[key[0]]
        if any(row.get("family_sha256") != expected_family for row in group):
            raise PreparationError(f"generated bundle family identity changed for {key}")
    for name, family_hash in FAMILY_HASHES.items():
        if audit.get("families", {}).get(name, {}).get("sha256") != family_hash:
            raise PreparationError(f"{name} family hash changed")
    if not any(row.get("game") == game for row in audit["images"]):
        raise PreparationError(f"family catalog contains no {game} images")
    return {
        "dispatcher_sha256": HOST_BUNDLE_SHA256,
        "dispatcher_receipt_sha256": HOST_RECEIPT_SHA256,
        "generated_bundle_sha256": EMITTED_C_SHA256,
        "bundle_receipt_sha256": BUNDLE_RECEIPT_SHA256,
        "family_audit_sha256": FAMILY_AUDIT_SHA256,
        "selected_game": game,
        "selected_family_sha256": FAMILY_HASHES[game],
        "selected_record_sha256": RECORD_HASHES[game],
        "emitter_sha256": EMITTER_SHA256,
        "catalog_image_count": 36,
        "catalog_title_counts": counts,
    }


def patch_dirty_source(source: str) -> str:
    current_hash = sha256_bytes(source.encode("utf-8"))
    if current_hash in DIRTY_PATCHED_HASHES.values():
        return source
    if MARKER in source or "psx_palette_native_try_dispatch" in source:
        raise PreparationError("dirty interpreter contains a partial or unknown palette hook")
    if source.count(MAIN_ANCHOR) != 1 or source.count(LOCAL_ANCHOR) != 1:
        raise PreparationError("dirty interpreter hook anchors changed")
    source = source.replace(MAIN_ANCHOR, MAIN_HOOK + MAIN_ANCHOR, 1)
    source = source.replace(LOCAL_ANCHOR, LOCAL_HOOK + LOCAL_ANCHOR, 1)
    if source.count("!g_precise_mode && !g_ls_replay_active && psx_palette_native_try_dispatch(") != 2:
        raise PreparationError("both guarded native hook sites were not installed")
    if source.index("psx_palette_native_try_dispatch(cpu,addr") > source.index("overlay_loader_dispatch(cpu, addr)"):
        raise PreparationError("main hook must precede dynamic overlay dispatch")
    if source.index("psx_palette_native_try_dispatch(cpu,target") > source.index("overlay_loader_dispatch(cpu, target)"):
        raise PreparationError("local-transfer hook must precede dynamic overlay dispatch")
    out_hash = sha256_bytes(source.encode("utf-8"))
    if out_hash not in DIRTY_PATCHED_HASHES.values():
        raise PreparationError("transformed dirty interpreter differs from the reviewed v3 hook candidate")
    return source


def _counter_candidate(data: bytes) -> bytes:
    text = data.decode("utf-8")
    old = """    e->fn(cpu); /* Preserve the emitter's CPS PC/RA/cycle contract verbatim. */
    (void)offset;palette_dispatch_hits++;return 1;"""
    new = """    palette_dispatch_hits++; /* Count accepted handler entry before reentrant safe points. */
    e->fn(cpu); /* Preserve the emitter's CPS PC/RA/cycle contract verbatim. */
    (void)offset;return 1;"""
    if text.count(new) == 1:
        return data
    if text.count(old) != 1:
        raise PreparationError("dispatcher accepted-entry counter anchor changed")
    return text.replace(old, new, 1).encode("utf-8")


def _expect_destination(path: Path, content: bytes, label: str) -> bool:
    """Validate a destination, returning True only when it needs creation."""
    if not path.exists():
        return True
    if not path.is_file() or path.read_bytes() != content:
        raise PreparationError(f"refusing to overwrite conflicting {label}: {path}")
    return False


def prepare(framework: Path, project_cmake: Path, bundle: Path, family_audit: Path | None = None,
            *, accessor_source: Path, accessor_header: Path, game: str,
            cps_enabled: bool) -> dict[str, Any]:
    """Validate the complete plan, then install it into a copied CPS project."""
    if game not in FAMILY_HASHES or cps_enabled is not True:
        raise PreparationError("explicit game jf1/jf2 and cps_enabled=True are required")
    framework = framework.resolve()
    project_cmake = project_cmake.resolve()
    bundle = bundle.resolve()
    family_audit = family_audit.resolve() if family_audit is not None else None
    accessor_source = accessor_source.resolve()
    accessor_header = accessor_header.resolve()
    if not framework.is_dir() or not project_cmake.is_file():
        raise PreparationError("framework directory and caller CMakeLists.txt must exist")

    evidence = validate_evidence(bundle, family_audit, game)
    dirty_path = framework / "runtime/src/dirty_ram_interp.c"
    dirty_raw = dirty_path.read_bytes()
    normalized_dirty = dirty_raw.decode("utf-8").replace("\r\n", "\n")
    normalized_hash = sha256_bytes(normalized_dirty.encode("utf-8"))
    if (sha256_bytes(dirty_raw) != DIRTY_BASE_HASHES[game]
            and normalized_hash != DIRTY_BASE_LF_HASHES[game]
            and normalized_hash != DIRTY_PATCHED_HASHES[game]):
        raise PreparationError("dirty interpreter does not match the pinned clean title source")
    dirty_decoded = dirty_raw.decode("utf-8")
    dirty_newline = "\r\n" if "\r\n" in dirty_decoded else "\n"
    dirty_text = patch_dirty_source(dirty_decoded.replace("\r\n", "\n"))
    dirty_out = dirty_text.replace("\n", dirty_newline).encode("utf-8")

    dispatcher_out = _counter_candidate((bundle / "host_dispatch_candidate.c").read_bytes())
    accessor = _read_pinned(accessor_source, ACCESSOR_C_SHA256, "raw instruction accessor")
    accessor_header = _read_pinned(accessor_header, ACCESSOR_H_SHA256, "raw instruction accessor header")
    cmake_raw = project_cmake.read_bytes()
    cmake_decoded = cmake_raw.decode("utf-8")
    cmake_newline = "\r\n" if "\r\n" in cmake_decoded else "\n"
    cmake_text = cmake_decoded.replace("\r\n", "\n")
    psxroot_forms = (
        'set(PSXRECOMP_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/psxrecomp")',
        'set(PSXRECOMP_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/psxrecomp" CACHE PATH',
    )
    if sum(cmake_text.count(anchor) for anchor in psxroot_forms) != 1 or (project_cmake.parent / "psxrecomp").resolve() != framework:
        raise PreparationError("caller CMakeLists.txt PSXRECOMP_ROOT does not resolve to the supplied framework")
    if cmake_text.count("psxrecomp_add_game_runtime(psx-runtime\n") != 1:
        raise PreparationError("caller CMakeLists.txt does not define exactly one psx-runtime target")
    if MARKER in cmake_text:
        if cmake_text.count(CMAKE_BLOCK) != 1:
            raise PreparationError("caller CMakeLists.txt has a partial or unknown palette block")
        cmake_out = cmake_raw
    else:
        cmake_out = (cmake_text.rstrip() + CMAKE_BLOCK).replace("\n", cmake_newline).encode("utf-8")

    outputs = {
        dirty_path: (dirty_out, "dirty interpreter"),
        framework / "runtime/src/palette_native_dispatch.c": (dispatcher_out, "native dispatcher"),
        framework / "runtime/src/native_instruction_word_access.c": (accessor, "instruction accessor"),
        framework / "runtime/src/native_instruction_word_access.h": (accessor_header, "source accessor header"),
        framework / "runtime/include/native_instruction_word_access.h": (accessor_header, "runtime accessor header"),
        project_cmake: (cmake_out, "caller CMakeLists.txt"),
    }
    receipt_path = framework / "runtime/palette_native_patch_receipt.json"
    receipt = {
        "schema": 1,
        "kind": "explicit-cps-palette-native-host-dispatch",
        **evidence,
        "cps_enabled": True,
        "counter_semantics": "accepted native handler entries; incremented before handler safe points",
        "outputs": {path.relative_to(project_cmake.parent).as_posix(): sha256_bytes(content)
                    for path, (content, _) in outputs.items()},
    }
    receipt_out = (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode("utf-8")
    outputs[receipt_path] = (receipt_out, "preparation receipt")

    # Validate every input, anchor, and destination before the first write.
    pending: list[tuple[Path, bytes]] = []
    for path, (content, label) in outputs.items():
        if path == dirty_path and normalized_hash == DIRTY_BASE_LF_HASHES[game]:
            pending.append((path, content))
        elif path == project_cmake and MARKER not in project_cmake.read_text(encoding="utf-8"):
            pending.append((path, content))
        elif _expect_destination(path, content, label):
            pending.append((path, content))
    for path, content in pending:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game", choices=("jf1", "jf2"), required=True)
    parser.add_argument("--cps", action="store_true", help="explicitly assert the caller project uses CPS")
    parser.add_argument("--framework", type=Path, required=True, help="copied psxrecomp framework directory")
    parser.add_argument("--project-cmake", type=Path, required=True, help="caller project CMakeLists.txt")
    parser.add_argument("--bundle", type=Path, required=True, help="reviewed 36x3 generated-bundle directory")
    parser.add_argument("--family-audit", type=Path, help="required only for legacy schema-1 bundles")
    parser.add_argument("--accessor-source", type=Path, required=True, help="reviewed raw instruction accessor C source")
    parser.add_argument("--accessor-header", type=Path, required=True, help="reviewed raw instruction accessor header")
    args = parser.parse_args()
    result = prepare(args.framework, args.project_cmake, args.bundle, args.family_audit,
                     accessor_source=args.accessor_source, accessor_header=args.accessor_header,
                     game=args.game, cps_enabled=args.cps)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
