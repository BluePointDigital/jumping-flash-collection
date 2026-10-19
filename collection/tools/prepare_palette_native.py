"""Explicitly generate and install palette helpers into an already copied CPS project.

Ordinary runtime preparation stays unchanged. Every source, tool and destination
is supplied by the caller; standalone projects and existing AOT caches are not
selected implicitly.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from generate_palette_native import GenerationError, generate
from palette_native_sources import GAMES, SourceAuditError
from patch_palette_native import (
    ACCESSOR_C_SHA256, ACCESSOR_H_SHA256, PreparationError, _read_pinned,
    prepare as install,
)


def prepare(records: dict[str, Path], layouts: dict[str, Path], *, emitter: Path,
            toolkit: Path, output_dir: Path, framework: Path, project_cmake: Path,
            accessor_source: Path, accessor_header: Path, game: str,
            cps_enabled: bool) -> dict:
    if game not in GAMES or cps_enabled is not True:
        raise PreparationError("explicit game jf1/jf2 and CPS assertion are required")
    if not framework.is_dir() or not project_cmake.is_file():
        raise PreparationError("supply an existing copied framework and its project CMakeLists.txt")
    _read_pinned(accessor_source, ACCESSOR_C_SHA256, "instruction accessor")
    _read_pinned(accessor_header, ACCESSOR_H_SHA256, "instruction accessor header")
    bundle = generate(records, layouts, emitter=emitter, toolkit=toolkit,
                      accessor_source=accessor_source, accessor_header=accessor_header,
                      output_dir=output_dir)
    installed = install(framework, project_cmake, output_dir, accessor_source=accessor_source,
                        accessor_header=accessor_header, game=game, cps_enabled=True)
    return {
        "schema": 2, "game": game, "output_dir": str(output_dir.resolve()),
        "function_count": bundle["function_count"],
        "unique_entry_segment_owners": bundle["unique_entry_segment_owners"],
        "dispatch_keys": bundle["dispatch_keys"],
        "generated_bundle_sha256": installed["generated_bundle_sha256"],
        "dispatcher_sha256": installed["dispatcher_sha256"],
        "semantic_catalog_sha256": installed["semantic_catalog_sha256"],
        "input_provenance_sha256": installed["input_provenance_sha256"],
        "patch_receipt": str((framework / "runtime/palette_native_patch_receipt.json").resolve()),
        "native_build_performed": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for game in GAMES:
        parser.add_argument(f"--records-{game}", type=Path, required=True)
        parser.add_argument(f"--layout-{game}", type=Path, required=True)
    for name in ("emitter", "toolkit", "output-dir", "framework", "project-cmake",
                 "accessor-source", "accessor-header"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--game", choices=GAMES, required=True)
    parser.add_argument("--cps", action="store_true", required=True)
    args = parser.parse_args()
    try:
        result = prepare(
            {game: getattr(args, f"records_{game}") for game in GAMES},
            {game: getattr(args, f"layout_{game}") for game in GAMES},
            emitter=args.emitter, toolkit=args.toolkit, output_dir=args.output_dir,
            framework=args.framework, project_cmake=args.project_cmake,
            accessor_source=args.accessor_source, accessor_header=args.accessor_header,
            game=args.game, cps_enabled=args.cps)
    except (GenerationError, SourceAuditError, PreparationError, OSError) as exc:
        parser.exit(2, f"Palette preparation failed: {exc}\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
