"""Validate source images against the frozen palette-native family catalog."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import struct
from pathlib import Path
from typing import Any


CATALOG = Path(__file__).resolve().parents[1] / "runtime/palette_native_source_catalog.json"
CATALOG_SHA256 = "6750dc0c0089322740031bda4661ca49f7988621b91437cede7494d976a3dbc6"
GAMES = ("jf1", "jf2")


class SourceAuditError(ValueError):
    """Input source bytes do not match the reviewed palette family contract."""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json(path: Path, label: str) -> tuple[bytes, Any]:
    try:
        raw = path.read_bytes()
        return raw, json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise SourceAuditError(f"cannot read {label}: {path}") from exc


def _load_catalog() -> dict[str, Any]:
    raw, catalog = _json(CATALOG, "supported palette catalog")
    if sha256(raw.replace(b"\r\n", b"\n")) != CATALOG_SHA256:
        raise SourceAuditError("supported palette catalog hash changed")
    return catalog


def _validate_game_data(game: str, records_raw: bytes, records: Any,
                        layout_raw: bytes, layout_data: Any,
                        catalog: dict[str, Any]) -> tuple[dict[str, str], dict[str, dict[str, Any]]]:
    if not isinstance(records, list) or layout_data.get("game") != game:
        raise SourceAuditError(f"{game} records/layout schema mismatch")

    expected = {row["image"]: row for row in catalog["images"] if row["game"] == game}
    layouts = layout_data.get("images")
    if len(expected) != (12 if game == "jf1" else 24) or not isinstance(layouts, dict) or set(layouts) != set(expected):
        raise SourceAuditError(f"{game} image inventory differs from the frozen catalog")
    by_name: dict[str, dict[str, Any]] = {}
    for record in records:
        name = record.get("producer_name")
        if name in expected:
            if name in by_name:
                raise SourceAuditError(f"duplicate source record for {game}:{name}")
            by_name[name] = record
    if set(by_name) != set(expected):
        raise SourceAuditError(f"{game} records do not cover every frozen image")

    family = catalog["families"][game]
    family_words = [int(word, 16) for word in family["words"]]
    if len(family_words) != 30 or family["mutable_immediate_word_indices"] != [0, 1]:
        raise SourceAuditError(f"{game} family definition has unsupported mutable fields")
    entry_offsets = family["legal_entry_offsets"]
    if entry_offsets != ([0, 32, 92] if game == "jf1" else [0, 32, 88]):
        raise SourceAuditError(f"{game} legal entry mapping changed")

    for name, pinned in expected.items():
        record, layout = by_name[name], layouts[name]
        if record.get("producer") != "verified_psx_exe_lz1":
            raise SourceAuditError(f"unsupported source producer for {game}:{name}")
        try:
            body = base64.b64decode(record["bytes_b64"], validate=True)
            load = int(record["load_addr"], 16)
            layout_load = int(layout["load_addr"], 16)
            entry = int(layout["template"], 16)
        except (KeyError, TypeError, ValueError) as exc:
            raise SourceAuditError(f"malformed source identity for {game}:{name}") from exc
        if (sha256(body) != pinned["body_sha256"] or layout.get("body_sha256") != pinned["body_sha256"]
                or load != layout_load or record["load_addr"].lower() != pinned["load_addr"].lower()
                or layout.get("template") != pinned["entry"] or layout.get("size") != 120
                or layout.get("template_sha256") != pinned["template_sha256"]
                or entry - load != pinned["entry_offset"]):
            raise SourceAuditError(f"source bytes or extent changed for {game}:{name}")
        offset = entry - load
        if offset < 0 or offset + 120 > len(body):
            raise SourceAuditError(f"palette template is outside source extent for {game}:{name}")
        words = list(struct.unpack_from("<30I", body, offset))
        normalized = words.copy()
        for index in family["mutable_immediate_word_indices"]:
            if words[index] & 0xFFFF0000 != family_words[index] & 0xFFFF0000:
                raise SourceAuditError(f"mutable immediate opcode/register changed for {game}:{name}")
            normalized[index] &= 0xFFFF0000
        if normalized != family_words:
            raise SourceAuditError(f"fixed palette instruction body changed for {game}:{name}")
        raw_template = body[offset:offset + 120]
        if sha256(raw_template) != pinned["template_sha256"]:
            raise SourceAuditError(f"palette template hash changed for {game}:{name}")
    return ({"records_sha256": sha256(records_raw), "layout_sha256": sha256(layout_raw)}, by_name)


def _build_outputs(records: dict[str, Path], layouts: dict[str, Path], *,
                   retain_audited_records: bool) -> tuple[bytes, bytes, dict[str, dict[str, dict[str, Any]]]]:
    catalog = _load_catalog()
    if set(records) != set(GAMES) or set(layouts) != set(GAMES):
        raise SourceAuditError("explicit records and layouts are required for both jf1 and jf2")
    inputs: dict[str, dict[str, str]] = {}
    audited_records: dict[str, dict[str, dict[str, Any]]] = {}
    for game in GAMES:
        records_raw, parsed_records = _json(records[game], f"{game} records")
        layout_raw, parsed_layout = _json(layouts[game], f"{game} layout")
        checked, relevant = _validate_game_data(
            game, records_raw, parsed_records, layout_raw, parsed_layout, catalog)
        inputs[game] = {
            "records_sha256": checked["records_sha256"],
            "records_path": str(records[game].resolve()),
            "layout_sha256": checked["layout_sha256"],
            "layout_path": str(layouts[game].resolve()),
        }
        if retain_audited_records:
            audited_records[game] = relevant
        del records_raw, parsed_records, layout_raw, parsed_layout, relevant
    semantic = json.dumps(catalog, indent=2, ensure_ascii=True).encode("utf-8") + b"\n"
    provenance = {
        "schema": 1,
        "semantic_catalog_sha256": sha256(semantic),
        "audited_image_count": len(catalog["images"]),
        "audited_title_counts": {g: sum(row["game"] == g for row in catalog["images"]) for g in GAMES},
        "inputs": inputs,
    }
    provenance_bytes = json.dumps(provenance, indent=2, ensure_ascii=True).encode("utf-8") + b"\n"
    return semantic, provenance_bytes, audited_records


def build_outputs(records: dict[str, Path], layouts: dict[str, Path]) -> tuple[bytes, bytes]:
    """Return stable semantic catalog bytes and path-specific input provenance bytes."""
    semantic, provenance, _ = _build_outputs(records, layouts, retain_audited_records=False)
    return semantic, provenance


def build_outputs_with_audited_records(
        records: dict[str, Path], layouts: dict[str, Path]
) -> tuple[bytes, bytes, dict[str, dict[str, dict[str, Any]]]]:
    """Return outputs plus only the source records that passed image validation."""
    return _build_outputs(records, layouts, retain_audited_records=True)


def _write_new_or_identical(path: Path, data: bytes) -> None:
    if path.exists():
        if not path.is_file() or path.read_bytes() != data:
            raise SourceAuditError(f"refusing to overwrite conflicting output: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def prepare(records: dict[str, Path], layouts: dict[str, Path], *,
            semantic_output: Path, provenance_output: Path) -> tuple[str, str]:
    if semantic_output.resolve() == provenance_output.resolve():
        raise SourceAuditError("semantic and provenance outputs must be different files")
    semantic, provenance = build_outputs(records, layouts)
    # Validate both destinations before creating either output.
    for path, data in ((semantic_output, semantic), (provenance_output, provenance)):
        if path.exists() and (not path.is_file() or path.read_bytes() != data):
            raise SourceAuditError(f"refusing to overwrite conflicting output: {path}")
    _write_new_or_identical(semantic_output, semantic)
    _write_new_or_identical(provenance_output, provenance)
    return sha256(semantic), sha256(provenance)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for game in GAMES:
        parser.add_argument(f"--records-{game}", type=Path, required=True)
        parser.add_argument(f"--layout-{game}", type=Path, required=True)
    parser.add_argument("--semantic-output", type=Path, required=True)
    parser.add_argument("--provenance-output", type=Path, required=True)
    args = parser.parse_args()
    semantic_sha, provenance_sha = prepare(
        {g: getattr(args, f"records_{g}") for g in GAMES},
        {g: getattr(args, f"layout_{g}") for g in GAMES},
        semantic_output=args.semantic_output, provenance_output=args.provenance_output)
    print(json.dumps({"images": 36, "title_counts": {"jf1": 12, "jf2": 24},
                      "semantic_catalog_sha256": semantic_sha,
                      "provenance_sha256": provenance_sha}))


if __name__ == "__main__":
    main()
