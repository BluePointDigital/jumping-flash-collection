"""Verify audited static C sources only; this does not prove compile or link."""
from pathlib import Path
import argparse
import hashlib
import json
import re

_SHA = re.compile(r"^[0-9a-f]{64}$")
_STATIC_C = re.compile(r"^overlays_static(?:_[0-9]{4})?\.c$")


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def verify_static_sources(audit_path, source_dir, expected):
    """Return hash-bound source inputs after comparing them with trusted expected identity."""
    audit_path = Path(audit_path).resolve(strict=True)
    source_dir = Path(source_dir).resolve(strict=True)
    audit_bytes = audit_path.read_bytes()
    audit = json.loads(audit_bytes)

    required_expected = {
        "audit_sha256", "game_id", "recipe_input_sha256", "recipe_count",
        "recipe_counts", "image_names",
    }
    _require(required_expected <= expected.keys(), "trusted expected identity is incomplete")
    _require(isinstance(expected["audit_sha256"], str) and _SHA.fullmatch(expected["audit_sha256"]),
             "trusted audit SHA-256 is invalid")
    _require(_sha(audit_bytes) == expected["audit_sha256"], "audit SHA-256 differs from trusted pin")
    _require(audit.get("static") is True, "audit is not a static-dispatch audit")
    _require(audit.get("all_pairs_valid") is True and
             audit.get("all_guards_match_known_input_bytes") is True,
             "static guard audit did not pass")
    _require(audit.get("full_static_coverage_proven") is False,
             "source audit must not claim full static coverage")

    for key in ("game_id", "recipe_input_sha256", "recipe_count"):
        _require(audit.get(key) == expected[key], f"audit identity mismatch: {key}")
        if key.endswith("sha256"):
            _require(isinstance(expected[key], str) and _SHA.fullmatch(expected[key]),
                     f"trusted identity has invalid SHA-256: {key}")
        if key == "recipe_count":
            _require(type(audit.get(key)) is int and type(expected[key]) is int and
                     audit[key] >= 0, "recipe count must be an exact nonnegative integer")

    counts = expected["recipe_counts"]
    _require(set(counts) == {"disc", "bios", "game_installed"} and
             all(type(value) is int and value >= 0 for value in counts.values()),
             "trusted recipe counts are invalid")
    _require(all(type(audit.get(field)) is int for field in
                 ("disc_recipe_count", "bios_recipe_count", "game_installed_recipe_count")),
             "audited recipe counts must be exact integers")
    _require(audit.get("disc_recipe_count") == counts["disc"] and
             audit.get("bios_recipe_count") == counts["bios"] and
             audit.get("game_installed_recipe_count") == counts["game_installed"] and
             audit.get("recipe_count") == sum(counts.values()) == expected["recipe_count"],
             "audit recipe counts mismatch")

    coverage = audit.get("image_coverage")
    _require(isinstance(coverage, list) and len(coverage) == expected["recipe_count"],
             "per-image required-entry audit is missing")
    names = []
    for row in coverage:
        _require(isinstance(row, dict) and isinstance(row.get("name"), str) and row["name"],
                 "malformed per-image coverage row")
        names.append(row["name"])
        for field in ("required_entries_verified", "native_entries", "guarded_variants"):
            _require(type(row.get(field)) is int and row[field] >= 0,
                     f"per-image coverage missing {field}: {row.get('name')}")
        _require(row["native_entries"] > 0 and row["guarded_variants"] > 0,
                 f"per-image native guarded coverage is empty: {row['name']}")
    name_set = set(names)
    _require(len(names) == len(name_set) and name_set == set(expected["image_names"]),
             "per-image required-entry identities mismatch")

    variants = audit.get("variants")
    _require(type(audit.get("published_variants")) is int and
             isinstance(variants, list) and len(variants) == audit["published_variants"] > 0,
             "static variant list/count is missing")
    for row in variants:
        _require(isinstance(row, dict) and
                 re.fullmatch(r"0x[0-9a-fA-F]{8}", str(row.get("entry", ""))) and
                 re.fullmatch(r"0x[0-9a-fA-F]{8}", str(row.get("crc", ""))) and
                 isinstance(row.get("matched_recipe"), str) and row["matched_recipe"],
                 "malformed static entry/guard audit row")
        _require(row["matched_recipe"] in name_set,
                 "static guard witness names an unaudited source image")

    files = audit.get("files")
    _require(isinstance(files, dict) and files and "overlays_static.c" in files,
             "static source hashes are missing")
    _require(all(isinstance(name, str) and _STATIC_C.fullmatch(name) and
                 isinstance(digest, str) and _SHA.fullmatch(digest)
                 for name, digest in files.items()), "unsafe static source name/hash")
    expected_names = set(files)
    actual_names = {p.name for p in source_dir.iterdir()
                    if p.name.startswith("overlays_static") and p.suffix == ".c"}
    _require(actual_names == expected_names, "static dispatcher/split source set has missing or extra files")

    sources = []
    for name in sorted(files):
        path = source_dir / name
        _require(not path.is_symlink() and path.is_file() and path.resolve().parent == source_dir,
                 f"static source path is not a regular file under source root: {name}")
        digest = _sha(path.read_bytes())
        _require(digest == files[name], f"static source hash mismatch: {name}")
        sources.append({"name": name, "path": str(path), "sha256": digest})

    return {
        "kind": "audited-static-source-set-only",
        "game_id": audit["game_id"],
        "audit_path": str(audit_path),
        "audit_sha256": _sha(audit_bytes),
        "recipe_input_sha256": audit["recipe_input_sha256"],
        "source_count": len(sources),
        "sources": sources,
        "static_variants": audit["published_variants"],
        "required_images": len(coverage),
        "source_set_verified": True,
        "generation_chain_provenance_verified": False,
        "missing_generation_chain_provenance": [
            "game config/profile and original-disc digests",
            "emitter/codegen/cache identity and compiler/tool hashes",
            "CPS/runtime-build identity and actual CMake-selected sources",
        ],
        "objects_verified": False,
        "executable_verified": False,
        "package_verified": False,
        "full_static_coverage_proven": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--expected", type=Path, required=True,
                        help="trusted identity JSON prepared independently of the audit")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    expected = json.loads(args.expected.read_text(encoding="utf-8"))
    result = verify_static_sources(args.audit, args.source_dir, expected)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: result[key] for key in
                      ("game_id", "source_count", "static_variants", "source_set_verified")}))


if __name__ == "__main__":
    main()
