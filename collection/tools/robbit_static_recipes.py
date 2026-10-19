"""Prepare hash-bound Robbit static source-coverage recipes.

This emits capture records and job requirements for a later static-source
build. It does not compile, audit, launch, or assert runtime reachability.
"""

from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import json
import struct
import zlib
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG = ROOT / "runtime" / "robbit_static_source_catalog.json"
PSX_EXE_HEADER_BYTES = 2048


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _number(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError("boolean is not an address or count")
    return int(value, 0) if isinstance(value, str) else int(value)


def _word_at(data: bytes, offset: int) -> int:
    if offset < 0 or offset + 4 > len(data):
        raise ValueError("word is outside the supplied bytes")
    return struct.unpack_from("<I", data, offset)[0]


def load_catalog(path: Path = DEFAULT_CATALOG) -> tuple[dict[str, Any], str]:
    raw = Path(path).read_bytes()
    catalog = json.loads(raw)
    if catalog.get("schema") != "robbit-static-source-coverage-catalog-v1":
        raise ValueError("unsupported static source catalog schema")
    if catalog.get("scope", {}).get("kind") != "static_source_coverage":
        raise ValueError("catalog scope must be static_source_coverage")
    if catalog["scope"].get("runtime_reachability_proven") is not False:
        raise ValueError("catalog must not claim runtime reachability")
    return catalog, _sha(raw)


def _validate_disc_entry(
    record: dict[str, Any], spec: dict[str, Any], label: str,
) -> tuple[bytes, int, int, bytes]:
    """Validate one bounded captured disc image and its cataloged owner bytes."""
    if record.get("producer_name") != spec["recipe"]:
        raise ValueError(f"{label} recipe name differs from catalog")
    if _number(record.get("load_addr")) != _number(spec["load_addr"]):
        raise ValueError(f"{label} load address differs from catalog")
    body = base64.b64decode(record["bytes_b64"], validate=True)
    expected_capture_sha = spec.get("captured_body_sha256", spec["decoded_image_sha256"])
    if len(body) != spec["decoded_image_bytes"] or _sha(body) != expected_capture_sha:
        raise ValueError(f"{label} decoded image bytes differ from catalog")
    if record.get("size") != len(body):
        raise ValueError(f"{label} capture size differs from decoded image")

    entry = _number(spec["source_coverage_entry_pc"])
    owner_entry = _number(spec.get("owner_entry_pc", entry))
    load = _number(spec["load_addr"])
    extent = spec["owner_extent_bytes"]
    offset = owner_entry - load
    if offset < 0 or offset + extent > len(body):
        raise ValueError(f"{label} owner extent is outside the verified image")
    if not owner_entry <= entry < owner_entry + extent:
        raise ValueError(f"{label} requested entry is outside its cataloged owner extent")
    owner = body[offset:offset + extent]
    if _sha(owner) != spec["owner_extent_sha256"]:
        raise ValueError(f"{label} owner bytes differ from catalog")
    expected_crc = spec.get("owner_guard_crc32")
    if expected_crc is not None and (zlib.crc32(owner) & 0xFFFFFFFF) != _number(expected_crc):
        raise ValueError(f"{label} owner guard CRC differs from catalog")
    expected_word = spec.get("source_coverage_word")
    if expected_word is not None and _word_at(body, entry - load) != _number(expected_word):
        raise ValueError(f"{label} source entry word differs from catalog")
    return body, entry, owner_entry, owner


def _prepare_disc_entry_record(
    record: dict[str, Any], spec: dict[str, Any], label: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    body, entry, owner_entry, _owner = _validate_disc_entry(record, spec, label)
    load = _number(spec["load_addr"])
    extent = spec["owner_extent_bytes"]
    coverage_kind = spec.get("source_coverage_kind", "static_source_coverage")
    if coverage_kind != "static_source_coverage":
        raise ValueError(f"{label} catalog entry is not static source coverage")

    prepared = copy.deepcopy(record)
    for field in ("dispatch_entry_pcs", "static_dispatch_entry_pcs", "function_entry_pcs", "seeds"):
        values = prepared.setdefault(field, [])
        if not isinstance(values, list):
            raise ValueError(f"{label} capture field is not a list: {field}")
        by_value = {_number(value): value for value in values}
        # The requested interior continuation is a dispatch/source root, while
        # function_entry_pcs and seeds identify the actual containing owner.
        value = owner_entry if owner_entry != entry and field in ("function_entry_pcs", "seeds") else entry
        by_value.setdefault(value, f"0x{value:08X}")
        prepared[field] = [by_value[key] for key in sorted(by_value)]
    prepared.setdefault("source_coverage_entries", [])
    coverage_row = {
        "entry_pc": f"0x{entry:08X}",
        "source_entry_word": f"0x{_word_at(body, entry - load):08X}",
        "kind": coverage_kind,
        "owner_extent_bytes": extent,
        "owner_extent_sha256": spec["owner_extent_sha256"],
        "runtime_reachability_proven": False,
    }
    if owner_entry != entry:
        coverage_row["owner_entry_pc"] = f"0x{owner_entry:08X}"
    if coverage_row not in prepared["source_coverage_entries"]:
        prepared["source_coverage_entries"].append(coverage_row)

    job = {
        "name": spec["recipe"],
        "known_ranges": [[load, load + len(body)]],
        "required_entries": [entry],
        "requirement_kind": coverage_kind,
    }
    return prepared, job


def prepare_worldmap_record(record: dict[str, Any], catalog: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate an AOT capture of the exact WM image, then add one source root."""
    return _prepare_disc_entry_record(record, catalog["disc"]["wm_save"], "WM Save")


def prepare_memcard_record(record: dict[str, Any], catalog: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate the exact optional WM/MEMCARD image and add its source root."""
    return _prepare_disc_entry_record(record, catalog["disc"]["memcard_load"], "MEMCARD Load")


def prepare_m01_record(record: dict[str, Any], catalog: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate exact M01 bytes and add all cataloged continuations as source coverage."""
    base = catalog["disc"]["m01_interior_continuation"]
    image_fields = {
        key: value for key, value in base.items()
        if key != "additional_continuations"
    }
    continuations = [image_fields]
    continuations.extend({**image_fields, **entry} for entry in base.get("additional_continuations", []))

    prepared = copy.deepcopy(record)
    jobs = []
    for index, spec in enumerate(continuations):
        prepared, job = _prepare_disc_entry_record(
            prepared, spec, f"M01 continuation {index + 1}",
        )
        jobs.append(job)
    entries = sorted({entry for job in jobs for entry in job["required_entries"]})
    return prepared, {
        "name": base["recipe"],
        "known_ranges": jobs[0]["known_ranges"],
        "required_entries": entries,
        "requirement_kind": jobs[0]["requirement_kind"],
    }


def prepare_sdk_tail_records(
    records: list[dict[str, Any]], catalog: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Prepare exact 72-image SDK-tail entries as static source coverage."""
    batch = catalog.get("disc", {}).get("sdk_tail_72")
    if not isinstance(batch, dict) or batch.get("schema") != "robbit-sdk-tail-static-source-coverage-v1":
        raise ValueError("catalog has no supported SDK-tail source batch")
    specs = batch.get("entries")
    if (catalog.get("scope", {}).get("runtime_reachability_proven") is not False
            or batch.get("runtime_reachability_proven") is not False
            or not isinstance(specs, list) or len(specs) != 72):
        raise ValueError("SDK-tail catalog must contain exactly 72 image entries")
    by_name: dict[str, dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("SDK-tail record batch contains a non-object")
        name = record.get("producer_name")
        if name in by_name:
            raise ValueError(f"duplicate SDK-tail capture: {name}")
        by_name[name] = record
    expected_names = [spec.get("recipe") for spec in specs]
    if len(set(expected_names)) != 72:
        raise ValueError("SDK-tail catalog recipe names are not unique")
    missing = sorted(set(expected_names) - set(by_name))
    if missing:
        raise ValueError(f"SDK-tail batch is missing captures: {', '.join(missing[:4])}")
    unexpected = sorted(set(by_name) - set(expected_names))
    if unexpected:
        raise ValueError(f"SDK-tail batch contains uncataloged captures: {', '.join(unexpected[:4])}")

    prepared_records = []
    jobs = []
    for spec in specs:
        label = f"SDK tail {spec['recipe']}"
        record = by_name[spec["recipe"]]
        body, entry, owner_entry, _owner = _validate_disc_entry(record, spec, label)
        load = _number(spec["load_addr"])
        template_base = _number(spec["template_base_pc"])
        template_size = spec["template_bytes"]
        template_offset = template_base - load
        template = body[template_offset:template_offset + template_size]
        if len(template) != template_size or _sha(template) != spec["template_sha256"]:
            raise ValueError(f"{label} template identity differs from catalog")

        pair = spec["literal_continuation_pointer_pair"]
        lui_offset = template_offset + pair["lui_offset"]
        addiu_offset = template_offset + pair["addiu_offset"]
        lui_word = _word_at(body, lui_offset)
        addiu_word = _word_at(body, addiu_offset)
        if (lui_word != _number(pair["lui_word"])
                or addiu_word != _number(pair["addiu_word"])):
            raise ValueError(f"{label} literal continuation words differ from catalog")
        lui_rt = (lui_word >> 16) & 31
        addiu_rs = (addiu_word >> 21) & 31
        addiu_rt = (addiu_word >> 16) & 31
        signed_imm = struct.unpack("<h", struct.pack("<H", addiu_word & 0xFFFF))[0]
        decoded_target = (((lui_word & 0xFFFF) << 16) + signed_imm) & 0xFFFFFFFF
        if (pair.get("register") != "ra" or pair.get("destination_register") != 31
                or lui_rt != addiu_rs or addiu_rt != 31
                or decoded_target != entry
                or decoded_target != _number(pair["computed_target_pc"])):
            raise ValueError(f"{label} LUI/ADDIU pair does not construct the cataloged RA target")

        guard = spec["tail_entry_guard"]
        guard_offset = entry - load
        guard_bytes = body[guard_offset:guard_offset + guard["bytes"]]
        if (guard["bytes"] != 116 or len(guard_bytes) != 116
                or _sha(guard_bytes) != guard["sha256"]
                or (zlib.crc32(guard_bytes) & 0xFFFFFFFF) != _number(guard["crc32"])
                or _word_at(body, guard_offset) != _number(spec["source_coverage_word"])):
            raise ValueError(f"{label} tail entry guard differs from catalog")

        prepared, job = _prepare_disc_entry_record(record, spec, label)
        coverage = next(
            row for row in prepared["source_coverage_entries"]
            if _number(row["entry_pc"]) == entry
        )
        coverage.update({
            "template_base_pc": f"0x{template_base:08X}",
            "template_bytes": template_size,
            "template_sha256": spec["template_sha256"],
            "literal_continuation_pointer_pair": copy.deepcopy(pair),
            "entry_guard_bytes": guard["bytes"],
            "entry_guard_sha256": guard["sha256"],
            "entry_guard_crc32": guard["crc32"],
            "runtime_reachability_proven": False,
        })
        # Preserve the function boundary as a real function seed; the resume is
        # only an additional dispatch/source-coverage entry.
        if owner_entry != entry and f"0x{owner_entry:08X}" not in prepared["function_entry_pcs"]:
            raise ValueError(f"{label} containing function entry was not retained")
        prepared_records.append(prepared)
        jobs.append(job)
    if len(prepared_records) != 72:
        raise ValueError("SDK-tail preparation did not produce 72 records")
    return prepared_records, jobs


def _merge_source_coverage_record(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    """Merge source roots for two recipes that refer to the same captured image."""
    for field in ("producer_name", "load_addr", "size", "bytes_b64"):
        if existing.get(field) != incoming.get(field):
            raise ValueError(f"overlapping source recipes disagree on captured image field: {field}")
    merged = copy.deepcopy(existing)
    for field in ("dispatch_entry_pcs", "static_dispatch_entry_pcs", "function_entry_pcs", "seeds"):
        left = merged.get(field, [])
        right = incoming.get(field, [])
        if not isinstance(left, list) or not isinstance(right, list):
            raise ValueError(f"overlapping source recipe field is not a list: {field}")
        by_value = {_number(value): value for value in left}
        for value in right:
            by_value.setdefault(_number(value), value)
        merged[field] = [by_value[key] for key in sorted(by_value)]

    rows = merged.setdefault("source_coverage_entries", [])
    if not isinstance(rows, list) or not isinstance(incoming.get("source_coverage_entries", []), list):
        raise ValueError("overlapping source recipe coverage entries are not lists")
    by_entry = {_number(row["entry_pc"]): row for row in rows}
    for row in incoming.get("source_coverage_entries", []):
        entry = _number(row["entry_pc"])
        prior = by_entry.get(entry)
        if prior is None:
            copied = copy.deepcopy(row)
            rows.append(copied)
            by_entry[entry] = copied
            continue
        for key, value in row.items():
            if key in prior and prior[key] != value:
                raise ValueError(f"overlapping source recipe coverage differs at {row['entry_pc']}: {key}")
            prior[key] = copy.deepcopy(value)
    rows.sort(key=lambda row: _number(row["entry_pc"]))
    return merged


def _merge_source_coverage_job(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    if (existing.get("name") != incoming.get("name")
            or existing.get("known_ranges") != incoming.get("known_ranges")
            or existing.get("requirement_kind") != incoming.get("requirement_kind")):
        raise ValueError("overlapping source recipes disagree on job identity or range")
    merged = copy.deepcopy(existing)
    merged["required_entries"] = sorted({
        _number(value) for value in existing.get("required_entries", [])
    } | {
        _number(value) for value in incoming.get("required_entries", [])
    })
    return merged


def _append_or_merge_source_recipe(
    records: list[dict[str, Any]], jobs: list[dict[str, Any]],
    record: dict[str, Any], job: dict[str, Any],
) -> None:
    name = record.get("producer_name")
    if not name or job.get("name") != name:
        raise ValueError("source recipe record/job names differ")
    record_matches = [index for index, current in enumerate(records) if current.get("producer_name") == name]
    job_matches = [index for index, current in enumerate(jobs) if current.get("name") == name]
    if len(record_matches) != len(job_matches) or len(record_matches) > 1:
        raise ValueError(f"source recipe has duplicate or unmatched record/job: {name}")
    if record_matches:
        records[record_matches[0]] = _merge_source_coverage_record(records[record_matches[0]], record)
        jobs[job_matches[0]] = _merge_source_coverage_job(jobs[job_matches[0]], job)
    else:
        records.append(record)
        jobs.append(job)


def validate_aot_provenance(
    provenance: dict[str, Any], catalog: dict[str, Any], *,
    include_memcard: bool = False, include_m01: bool = False,
    include_sdk_tail: bool = False,
) -> dict[str, Any]:
    """Bind requested captures to the same verified-disc preparation receipt."""
    if provenance.get("game") != catalog["game_id"]:
        raise ValueError("AOT preparation provenance is for another game")
    if provenance.get("disc_sha256") != catalog["disc"]["sha256"]:
        raise ValueError("AOT preparation disc digest differs from catalog")
    inputs = provenance.get("inputs")
    if not isinstance(inputs, list):
        raise ValueError("AOT provenance is missing its decoded input ledger")
    wm = catalog["disc"]["wm_save"]
    boot = catalog["disc"]["boot_executable"]
    wm_rows = [row for row in inputs if row.get("path") == wm["recipe"]]
    boot_rows = [row for row in inputs if row.get("path") == boot["name"]]
    if len(wm_rows) != 1 or len(boot_rows) != 1:
        raise ValueError("AOT provenance must contain one WM image and one boot executable")
    wm_row, boot_row = wm_rows[0], boot_rows[0]
    if (wm_row.get("source_sha256") != wm["source_file_sha256"] or
            wm_row.get("decoded_sha256") != wm["decoded_executable_sha256"] or
            _number(wm_row.get("load")) != _number(wm["load_addr"]) or
            wm_row.get("bytes") != wm["decoded_image_bytes"]):
        raise ValueError("WM source identity differs from verified AOT provenance")
    if (boot_row.get("source_sha256") != boot["sha256"] or
            _number(boot_row.get("load")) != _number(boot["load_addr"]) or
            _number(boot_row.get("entry")) != _number(boot["entry_pc"]) or
            boot_row.get("bytes") != boot["decoded_body_bytes"]):
        raise ValueError("boot executable identity differs from verified AOT provenance")
    identity = {
        "game": provenance["game"],
        "disc_sha256": provenance["disc_sha256"],
        "wm_source_sha256": wm_row["source_sha256"],
        "wm_decoded_sha256": wm_row["decoded_sha256"],
        "boot_executable_sha256": boot_row["source_sha256"],
    }
    if include_memcard:
        memcard = catalog["disc"]["memcard_load"]
        memcard_rows = [row for row in inputs if row.get("path") == memcard["recipe"]]
        if len(memcard_rows) != 1:
            raise ValueError("AOT provenance must contain one MEMCARD image when requested")
        row = memcard_rows[0]
        if (row.get("source_sha256") != memcard["source_file_sha256"] or
                row.get("decoded_sha256") != memcard["decoded_executable_sha256"] or
                _number(row.get("load")) != _number(memcard["load_addr"]) or
                row.get("bytes") != memcard["decoded_image_bytes"]):
            raise ValueError("MEMCARD source identity differs from verified AOT provenance")
        identity["memcard_source_sha256"] = row["source_sha256"]
        identity["memcard_decoded_sha256"] = row["decoded_sha256"]
        identity["memcard_decoded_image_sha256"] = memcard["decoded_image_sha256"]
        identity["memcard_load_addr"] = f"0x{_number(memcard['load_addr']):08X}"
        identity["memcard_decoded_image_bytes"] = memcard["decoded_image_bytes"]
    if include_m01:
        m01 = catalog["disc"]["m01_interior_continuation"]
        m01_rows = [row for row in inputs if row.get("path") == m01["recipe"]]
        if len(m01_rows) != 1:
            raise ValueError("AOT provenance must contain one M01 image when requested")
        row = m01_rows[0]
        if (row.get("source_sha256") != m01["source_file_sha256"] or
                row.get("decoded_sha256") != m01["decoded_executable_sha256"] or
                _number(row.get("load")) != _number(m01["load_addr"]) or
                _number(row.get("entry")) != _number(m01["executable_entry_pc"]) or
                row.get("bytes") != m01["decoded_image_bytes"]):
            raise ValueError("M01 source identity differs from verified AOT provenance")
        identity["m01_source_sha256"] = row["source_sha256"]
        identity["m01_decoded_sha256"] = row["decoded_sha256"]
        identity["m01_decoded_image_sha256"] = m01["decoded_image_sha256"]
        identity["m01_load_addr"] = f"0x{_number(m01['load_addr']):08X}"
        identity["m01_executable_entry_pc"] = f"0x{_number(m01['executable_entry_pc']):08X}"
        identity["m01_source_coverage_entry_pc"] = f"0x{_number(m01['source_coverage_entry_pc']):08X}"
        identity["m01_owner_entry_pc"] = f"0x{_number(m01['owner_entry_pc']):08X}"
        identity["m01_decoded_image_bytes"] = m01["decoded_image_bytes"]
        identity["m01_source_coverage_entries"] = [
            {
                "entry_pc": f"0x{_number(spec['source_coverage_entry_pc']):08X}",
                "owner_entry_pc": f"0x{_number(spec.get('owner_entry_pc', spec['source_coverage_entry_pc'])):08X}",
                "owner_extent_bytes": spec["owner_extent_bytes"],
                "owner_extent_sha256": spec["owner_extent_sha256"],
                "source_coverage_word": f"0x{_number(spec['source_coverage_word']):08X}",
            }
            for spec in [m01, *m01.get("additional_continuations", [])]
        ]
    if include_sdk_tail:
        batch = catalog.get("disc", {}).get("sdk_tail_72")
        if not isinstance(batch, dict) or len(batch.get("entries", [])) != 72:
            raise ValueError("catalog has no complete SDK-tail provenance set")
        sdk_identities = []
        for spec in batch["entries"]:
            rows = [row for row in inputs if row.get("path") == spec["recipe"]]
            if len(rows) != 1:
                raise ValueError(f"AOT provenance must contain one SDK-tail image: {spec['recipe']}")
            row = rows[0]
            if (row.get("source_sha256") != spec["source_file_sha256"]
                    or row.get("decoded_sha256") != spec["decoded_executable_sha256"]
                    or _number(row.get("load")) != _number(spec["load_addr"])
                    or _number(row.get("entry")) != _number(spec["executable_entry_pc"])
                    or row.get("bytes") != spec["decoded_image_bytes"]):
                raise ValueError(f"SDK-tail AOT provenance identity differs: {spec['recipe']}")
            sdk_identities.append({
                "recipe": spec["recipe"],
                "source_sha256": row["source_sha256"],
                "decoded_executable_sha256": row["decoded_sha256"],
                "load_addr": f"0x{_number(row['load']):08X}",
                "executable_entry_pc": f"0x{_number(row['entry']):08X}",
                "decoded_image_bytes": row["bytes"],
            })
        identity["sdk_tail_72"] = {
            "recipe_count": len(sdk_identities),
            "identity_rows": sdk_identities,
            "runtime_reachability_proven": False,
        }
    return identity


def _psx_exe_body_and_load(raw: bytes, spec: dict[str, Any]) -> tuple[bytes, int]:
    if len(raw) != spec["bytes"] or _sha(raw) != spec["sha256"]:
        raise ValueError("boot executable identity differs from catalog")
    if raw[:8] != b"PS-X EXE" or len(raw) < PSX_EXE_HEADER_BYTES:
        raise ValueError("boot executable is not a bounded PS-X EXE")
    entry_pc, _gp, load_addr, body_size = struct.unpack_from("<IIII", raw, 16)
    if load_addr != _number(spec["load_addr"]) or entry_pc != _number(spec["entry_pc"]):
        raise ValueError("boot executable header identity differs from catalog")
    if body_size != len(raw) - PSX_EXE_HEADER_BYTES:
        raise ValueError("boot executable header size does not match file bytes")
    return raw[PSX_EXE_HEADER_BYTES:], load_addr


def _verify_guest_patch_writer(raw_exe: bytes, catalog: dict[str, Any]) -> dict[str, Any]:
    spec = catalog["guest_patch_writer"]
    body, load = _psx_exe_body_and_load(raw_exe, catalog["disc"]["boot_executable"])
    load_phys = load & 0x1FFFFFFF
    words = []
    actual = {}
    for item in spec["instructions"]:
        pc = _number(item["pc"])
        offset = (pc & 0x1FFFFFFF) - load_phys
        if offset < 0 or offset + 4 > len(body):
            raise ValueError(f"writer PC is outside boot executable: {item['pc']}")
        word = _word_at(body, offset)
        if word != _number(item["word"]):
            raise ValueError(f"guest patch-writer instruction differs at {item['pc']}")
        actual[item["pc"]] = word
        words.append({"pc": item["pc"], "word": f"0x{word:08X}", "file_offset": PSX_EXE_HEADER_BYTES + offset})

    setup = actual[spec["instructions"][0]["pc"]]
    call = actual[spec["instructions"][1]["pc"]]
    store = actual[spec["instructions"][2]["pc"]]
    if setup != 0x20431988 or (setup >> 26) != 0x08 or ((setup >> 16) & 31) != 3:
        raise ValueError("writer setup is not the cataloged ADDI v1,v0,0x1988")
    call_pc = _number(spec["instructions"][1]["pc"])
    jal_target = ((call_pc + 4) & 0xF0000000) | ((call & 0x03FFFFFF) << 2)
    if (call >> 26) != 3 or jal_target != _number(spec["instructions"][1]["target_pc"]):
        raise ValueError("writer JAL target differs from catalog")
    if store != 0xAC600000 or (store >> 26) != 0x2B or ((store >> 21) & 31) != 3 or ((store >> 16) & 31) != 0:
        raise ValueError("writer delay slot is not SW zero,0(v1)")

    observed_v0 = _number(spec["observed_v0_value"])
    immediate = struct.unpack("<h", struct.pack("<H", setup & 0xFFFF))[0]
    computed_target = (observed_v0 + immediate) & 0xFFFFFFFF
    if computed_target != _number(spec["computed_v1_target"]):
        raise ValueError("cataloged writer value does not compute the cataloged target")
    return {
        "boot_executable_sha256": _sha(raw_exe),
        "writer_instructions": words,
        "reviewed_v0_value": f"0x{observed_v0:08X}",
        "computed_store_target": f"0x{computed_target:08X}",
        "runtime_reachability_proven": False,
        "runtime_value_basis": "fixed value from the cataloged reviewed writer evidence; no live RAM input",
    }


def derive_bios_copy_window(bios: bytes, boot_exe: bytes, catalog: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Reconstruct the BIOS copy window from original inputs, applying one store."""
    spec = catalog["bios_copy_window"]
    bios_sha = _sha(bios)
    if len(bios) != spec["bios_bytes"] or bios_sha != spec["bios_sha256"]:
        raise ValueError("BIOS identity differs from static source catalog")
    writer_proof = _verify_guest_patch_writer(boot_exe, catalog)
    start, end = spec["source_rom_range"]
    if not (0 <= start < end <= len(bios)) or end - start != spec["destination_bytes"]:
        raise ValueError("BIOS copy window bounds differ from catalog")
    body = bytearray(bios[start:end])
    patch = spec["changed_word"]
    copy_offset = patch["copy_offset"]
    rom_offset = patch["rom_offset"]
    old_word = _number(patch["original_word"])
    new_word = _number(patch["derived_word"])
    if rom_offset != start + copy_offset:
        raise ValueError("BIOS ROM/copy offsets do not correspond")
    if _word_at(bios, rom_offset) != old_word or _word_at(body, copy_offset) != old_word:
        raise ValueError("original BIOS word differs from catalog")
    if _number(writer_proof["computed_store_target"]) != _number(patch["ram_pc"]):
        raise ValueError("verified guest writer target does not match BIOS patch PC")
    struct.pack_into("<I", body, copy_offset, new_word)
    derived = bytes(body)
    derived_sha = _sha(derived)
    if derived_sha != spec["derived_bytes_sha256"]:
        raise ValueError("derived BIOS copy-window digest differs from catalog")

    entry = _number(spec["entry_pc"])
    load = _number(spec["destination_load_addr"])
    record = {
        "schema": "psxrecomp overlay capture v3",
        "producer": "bios_resident_manifest",
        "producer_name": spec["producer_name"],
        "bios_sha256": bios_sha,
        "load_addr": f"0x{load:08X}",
        "size": len(derived),
        "bytes_b64": base64.b64encode(derived).decode("ascii"),
        "executed_pcs": [],
        "dispatch_entry_pcs": [f"0x{entry:08X}"],
        "static_dispatch_entry_pcs": [f"0x{entry:08X}"],
        "function_entry_pcs": [f"0x{entry:08X}"],
        "seeds": [f"0x{entry:08X}"],
        "dispatch_entry_segments": {"kuseg": [f"0x{entry:08X}"]},
        "producer_ranges": [{"start": f"0x{load:08X}", "end": f"0x{load + len(derived):08X}"}],
        "source_coverage_entries": [{
            "entry_pc": f"0x{entry:08X}",
            "kind": "static_source_coverage",
            "runtime_reachability_proven": False,
        }],
        "source_provenance": {
            "recipe": "verified-bios-copy-window-with-reviewed-guest-store",
            "bios_sha256": bios_sha,
            "boot_executable_sha256": writer_proof["boot_executable_sha256"],
            "copy_rom_range": [f"0x{start:08X}", f"0x{end:08X}"],
            "patched_rom_offset": f"0x{rom_offset:08X}",
            "patched_ram_pc": patch["ram_pc"],
            "original_word": patch["original_word"],
            "derived_word": patch["derived_word"],
            "derived_bytes_sha256": derived_sha,
            "writer": writer_proof,
            "private_ram_dump_used": False,
            "runtime_reachability_proven": False,
        },
    }
    job = {
        "name": spec["producer_name"],
        "known_ranges": [[load, load + len(derived)]],
        "required_entries": [entry],
        "requirement_kind": "static_source_coverage",
    }
    return record, job


def prepare_static_source_coverage(
    worldmap_record: dict[str, Any], bios: bytes, boot_exe: bytes,
    catalog: dict[str, Any], catalog_sha256: str,
    aot_provenance: dict[str, Any], aot_provenance_sha256: str,
    memcard_record: dict[str, Any] | None = None,
    m01_record: dict[str, Any] | None = None,
    sdk_tail_records: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if sdk_tail_records is not None:
        sdk_batch = catalog.get("disc", {}).get("sdk_tail_72", {})
        expected_provenance_sha = sdk_batch.get("evidence", {}).get("aot_provenance_sha256")
        if not expected_provenance_sha or aot_provenance_sha256 != expected_provenance_sha:
            raise ValueError("SDK-tail AOT provenance file digest differs from catalog")
    disc_provenance = validate_aot_provenance(
        aot_provenance, catalog, include_memcard=memcard_record is not None,
        include_m01=m01_record is not None, include_sdk_tail=sdk_tail_records is not None,
    )
    wm_record, wm_job = prepare_worldmap_record(worldmap_record, catalog)
    bios_record, bios_job = derive_bios_copy_window(bios, boot_exe, catalog)
    records = [wm_record, bios_record]
    jobs = [wm_job, bios_job]
    if memcard_record is not None:
        memcard_prepared, memcard_job = prepare_memcard_record(memcard_record, catalog)
        records.append(memcard_prepared)
        jobs.append(memcard_job)
    if m01_record is not None:
        m01_prepared, m01_job = prepare_m01_record(m01_record, catalog)
        records.append(m01_prepared)
        jobs.append(m01_job)
    if sdk_tail_records is not None:
        sdk_prepared, sdk_jobs = prepare_sdk_tail_records(sdk_tail_records, catalog)
        for sdk_record, sdk_job in zip(sdk_prepared, sdk_jobs, strict=True):
            _append_or_merge_source_recipe(records, jobs, sdk_record, sdk_job)
    return {
        "schema": "robbit-static-source-coverage-preparation-v1",
        "scope": "static_source_coverage_only",
        "runtime_reachability_proven": False,
        "full_static_coverage_proven": False,
        "catalog_sha256": catalog_sha256,
        "records": records,
        "jobs": jobs,
        "input_provenance": {
            "disc_sha256": catalog["disc"]["sha256"],
            "aot_provenance_sha256": aot_provenance_sha256,
            "verified_aot_input_identity": disc_provenance,
            "boot_executable_sha256": _sha(boot_exe),
            "bios_sha256": _sha(bios),
            "private_ram_dump_used": False,
        },
    }


def _load_one_record(path: Path, recipe: str) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(value, list):
        matches = [row for row in value if isinstance(row, dict) and row.get("producer_name") == recipe]
    elif isinstance(value, dict):
        matches = [value] if value.get("producer_name") == recipe else []
    else:
        raise ValueError("worldmap record input must be an object or an array of objects")
    if len(matches) != 1:
        raise ValueError(f"record input must contain exactly one cataloged recipe: {recipe}")
    return matches[0]


def _load_record_batch(path: Path, recipes: list[str]) -> list[dict[str, Any]]:
    """Select one capture for every requested recipe from a JSON object/list."""
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(value, dict):
        rows = [value]
    elif isinstance(value, list):
        rows = value
    else:
        raise ValueError("SDK-tail record input must be an object or an array of objects")
    expected = set(recipes)
    selected: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("SDK-tail record collection contains a non-object row")
        name = row.get("producer_name")
        if name not in expected:
            continue
        if name in selected:
            raise ValueError(f"SDK-tail record input contains duplicate recipe: {name}")
        selected[name] = row
    missing = sorted(expected - set(selected))
    if missing:
        raise ValueError(f"SDK-tail record input is missing recipe: {missing[0]}")
    return [selected[name] for name in recipes]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--worldmap-record", type=Path, required=True,
                        help="one AOT capture record produced from a separately verified disc preparation")
    parser.add_argument("--memcard-record", type=Path,
                        help="optional MEMCARD AOT capture from the same verified-disc preparation")
    parser.add_argument("--m01-record", type=Path,
                        help="optional exact EVENT/00/M01.PEX capture from the same verified-disc preparation")
    parser.add_argument("--sdk-tail-records", type=Path,
        help="optional record JSON/list; selects the cataloged 72 EVENT SDK-tail images and ignores unrelated named recipes")
    parser.add_argument("--aot-provenance", type=Path, required=True,
                        help="provenance.json from the same verified-disc AOT preparation")
    parser.add_argument("--boot-exe", type=Path, required=True,
                        help="the imported original SCPS_101.03 executable")
    parser.add_argument("--bios", type=Path, required=True,
                        help="the imported original SCPH5500 BIOS")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    catalog, catalog_sha = load_catalog(args.catalog)
    wm_record = _load_one_record(args.worldmap_record, catalog["disc"]["wm_save"]["recipe"])
    memcard_record = (
        _load_one_record(args.memcard_record, catalog["disc"]["memcard_load"]["recipe"])
        if args.memcard_record else None
    )
    m01_record = (
        _load_one_record(args.m01_record, catalog["disc"]["m01_interior_continuation"]["recipe"])
        if args.m01_record else None
    )
    sdk_tail_records = None
    if args.sdk_tail_records:
        sdk_specs = catalog.get("disc", {}).get("sdk_tail_72", {}).get("entries", [])
        sdk_tail_records = _load_record_batch(
            args.sdk_tail_records, [spec["recipe"] for spec in sdk_specs],
        )
    aot_provenance_bytes = args.aot_provenance.read_bytes()
    aot_provenance = json.loads(aot_provenance_bytes)
    prepared = prepare_static_source_coverage(
        wm_record, args.bios.read_bytes(), args.boot_exe.read_bytes(), catalog, catalog_sha,
        aot_provenance, _sha(aot_provenance_bytes), memcard_record, m01_record,
        sdk_tail_records,
    )
    output = args.output.resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite existing preparation output: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(prepared, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": "prepared-static-source-coverage-records",
        "output": str(output),
        "records": len(prepared["records"]),
        "required_entries": sum(len(job["required_entries"]) for job in prepared["jobs"]),
        "sdk_tail_recipes": len(sdk_tail_records) if sdk_tail_records is not None else 0,
        "runtime_reachability_proven": False,
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
