"""Post-AOT coordinator for the maintained JF1/JF2 palette-native pipeline.

Run only after both title preparations have terminal inventory-based audits and
after ``prepare_runtimes.py`` has created the two private project copies. The
shared 36-image bundle is emitted once; the existing installer then validates
and installs it independently into the selected JF1 and JF2 project copies.
This explicit post-AOT phase installs only into the supplied project copies.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys


ROOT = next(parent for parent in Path(__file__).resolve().parents
            if (parent / "collection/tools/prepare_palette_native.py").is_file())
TOOLS = ROOT / "collection/tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from generate_palette_native import GenerationError, generate
from palette_native_sources import GAMES, SourceAuditError
from patch_palette_native import PreparationError, prepare as install
from family_promotion import finish_palette_family


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _required_entries(job: dict) -> set[int]:
    result = set()
    for entry in job.get("required_entries", []):
        if isinstance(entry, bool):
            raise PreparationError("A required guest entry cannot be boolean")
        value = entry if isinstance(entry, int) else int(entry, 0) if isinstance(entry, str) else None
        if value is None or value < 0 or value > 0xFFFFFFFF or value % 4:
            raise PreparationError(f"Invalid required guest entry in {job.get('name')}: {entry!r}")
        result.add(value)
    return result


def _paths_overlap(left: Path, right: Path) -> bool:
    """True when either resolved directory contains the other."""
    return left == right or left in right.parents or right in left.parents


def validate_project_isolation(projects: dict[str, tuple[Path, Path]]) -> dict[str, dict[str, str]]:
    """Reject cross-title aliases/overlaps before generation or installation."""
    if set(projects) != set(GAMES):
        raise PreparationError(f"projects must include exactly {GAMES}")
    resolved = {
        game: (framework.resolve(), project_cmake.resolve())
        for game, (framework, project_cmake) in projects.items()
    }
    roots = {game: cmake.parent.resolve() for game, (_, cmake) in resolved.items()}
    frameworks = {game: framework for game, (framework, _) in resolved.items()}
    for game in GAMES:
        framework, project_cmake = resolved[game]
        if not framework.is_dir() or not project_cmake.is_file():
            raise PreparationError(f"{game} private framework and caller CMakeLists.txt must exist")
        if (roots[game] / "psxrecomp").resolve() != framework:
            raise PreparationError(f"{game} CMake project does not bind the supplied private framework")
    for left, right in ((GAMES[0], GAMES[1]),):
        if (_paths_overlap(roots[left], roots[right])
                or _paths_overlap(frameworks[left], frameworks[right])):
            raise PreparationError(f"{left} and {right} project/framework targets overlap")
    return {game: {"project_root": str(roots[game]),
                   "framework": str(frameworks[game]),
                   "project_cmake": str(resolved[game][1])}
            for game in GAMES}


def validate_project_target(game: str, framework: Path, project_cmake: Path) -> dict[str, str]:
    framework = framework.resolve()
    project_cmake = project_cmake.resolve()
    if not framework.is_dir() or not project_cmake.is_file():
        raise PreparationError(f"{game} private framework and caller CMakeLists.txt must exist")
    if (project_cmake.parent / "psxrecomp").resolve() != framework:
        raise PreparationError(f"{game} CMake project does not bind the supplied private framework")
    dirty_path = framework / "runtime/src/dirty_ram_interp.c"
    dirty_raw = dirty_path.read_bytes()
    dirty_text = dirty_raw.decode("utf-8")
    patcher = install.__globals__
    normalized = dirty_text.replace("\r\n", "\n")
    allowed_hashes = (patcher["DIRTY_BASE_HASHES"][game],
                      patcher["DIRTY_BASE_LF_HASHES"][game],
                      patcher["DIRTY_PATCHED_HASHES"][game])
    if digest(dirty_path) not in allowed_hashes and \
            hashlib.sha256(normalized.encode("utf-8")).hexdigest() not in allowed_hashes:
        raise PreparationError(f"{game} dirty interpreter differs from the pinned collection source")
    patcher["patch_dirty_source"](normalized)
    cmake_raw = project_cmake.read_bytes()
    cmake_text = cmake_raw.decode("utf-8").replace("\r\n", "\n")
    root_forms = ('set(PSXRECOMP_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/psxrecomp")',
                  'set(PSXRECOMP_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/psxrecomp" CACHE PATH')
    if sum(cmake_text.count(anchor) for anchor in root_forms) != 1 or \
            cmake_text.count("psxrecomp_add_game_runtime(psx-runtime\n") != 1:
        raise PreparationError(f"{game} CMake source is not the pinned private CPS project")
    return {"dirty_source_sha256": digest(dirty_path),
            "project_cmake_sha256": digest(project_cmake)}


def validate_terminal_preparation(game: str, preparation: Path) -> dict:
    """Bind palette source input to a complete, inventory-based AOT audit."""
    preparation = preparation.resolve()
    records_path = preparation / "records.json"
    inventory_path = preparation / "inventory.json"
    provenance_path = preparation / "provenance.json"
    audit_path = preparation / "AOT_CACHE_AUDIT.json"
    if not all(path.is_file() for path in (records_path, inventory_path, provenance_path, audit_path)):
        raise PreparationError(f"{game} terminal preparation is missing records, inventory, provenance, or audit")
    records_hash = digest(records_path)
    inventory_hash = digest(inventory_path)
    provenance_hash = digest(provenance_path)
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    jobs = inventory.get("jobs")
    coverage = audit.get("image_coverage")
    if provenance.get("game") != game or provenance.get("records_sha256") != records_hash:
        raise PreparationError(f"{game} records are not bound to their preparation provenance")
    if (audit.get("recipe_input_sha256") != inventory_hash
            or audit.get("guidance_provenance_sha256") != provenance_hash):
        raise PreparationError(f"{game} full audit is not bound to its inventory and provenance")
    if (audit.get("all_pairs_valid") is not True
            or audit.get("all_guards_match_known_input_bytes") is not True
            or audit.get("recipe_count") != len(jobs or [])
            or not isinstance(jobs, list) or not isinstance(coverage, list)
            or len(coverage) != len(jobs)):
        raise PreparationError(f"{game} preparation lacks a complete inventory audit")
    required_by_name = {job["name"]: _required_entries(job) for job in jobs}
    if len(required_by_name) != len(jobs) or len({row.get("name") for row in coverage}) != len(jobs):
        raise PreparationError(f"{game} audit has duplicate or missing recipe identities")
    for row in coverage:
        name = row.get("name")
        required = required_by_name.get(name)
        if (required is None or row.get("required_entries_verified") != len(required)
                or row.get("native_entries", 0) <= 0 or row.get("guarded_variants", 0) <= 0):
            raise PreparationError(f"{game} recipe has no complete required-entry guard proof: {name}")
    return {"game": game, "records_sha256": records_hash,
            "inventory_sha256": inventory_hash, "provenance_sha256": provenance_hash,
            "audit_sha256": digest(audit_path), "recipe_count": len(jobs),
            "published_pairs": audit.get("published_pairs"),
            "required_entry_count": sum(len(value) for value in required_by_name.values())}


def install_existing_bundle(bundle: Path, projects: dict[str, tuple[Path, Path]], *,
                            accessor_source: Path, accessor_header: Path) -> dict[str, dict]:
    """Install a previously generated bundle separately into both title copies."""
    validate_project_isolation(projects)
    before = {game: validate_project_target(game, *projects[game]) for game in GAMES}
    for game in GAMES:
        framework, project_cmake = projects[game]
        dirty_path = framework / "runtime/src/dirty_ram_interp.c"
        if (digest(dirty_path) != before[game]["dirty_source_sha256"]
                or digest(project_cmake) != before[game]["project_cmake_sha256"]):
            raise PreparationError(f"{game} private project changed during bundle validation")
    results = {}
    for game in GAMES:
        framework, project_cmake = projects[game]
        result = install(framework, project_cmake, bundle,
                         accessor_source=accessor_source, accessor_header=accessor_header,
                         game=game, cps_enabled=True)
        if result["selected_game"] != game:
            raise PreparationError(f"installer returned the wrong title identity for {game}")
        results[game] = result
    return results


def prepare_both(preparations: dict[str, Path], layouts: dict[str, Path], *,
                 emitter: Path, toolkit: Path, bundle_output: Path,
                 projects: dict[str, tuple[Path, Path]], accessor_source: Path,
                 accessor_header: Path, cps_enabled: bool) -> dict:
    if cps_enabled is not True:
        raise PreparationError("both projects must explicitly assert CPS mode")
    if set(preparations) != set(GAMES) or set(layouts) != set(GAMES):
        raise PreparationError(f"both title preparations and layouts are required: {GAMES}")
    validate_project_isolation(projects)
    projects = {game: (framework.resolve(), project_cmake.resolve())
                for game, (framework, project_cmake) in projects.items()}
    source_proofs = {game: validate_terminal_preparation(game, preparations[game])
                     for game in GAMES}
    project_proofs = {game: validate_project_target(game, *projects[game]) for game in GAMES}
    bundle = generate(
        {game: Path(preparations[game]).resolve() / "records.json" for game in GAMES},
        layouts, emitter=emitter, toolkit=toolkit,
        accessor_source=accessor_source, accessor_header=accessor_header,
        output_dir=bundle_output)
    for game in GAMES:
        framework, project_cmake = projects[game]
        if (digest(framework / "runtime/src/dirty_ram_interp.c") != project_proofs[game]["dirty_source_sha256"]
                or digest(project_cmake) != project_proofs[game]["project_cmake_sha256"]):
            raise PreparationError(f"{game} private project changed during palette emission")
    install_proofs = install_existing_bundle(
        bundle_output, projects, accessor_source=accessor_source,
        accessor_header=accessor_header)
    family_integration = None
    jf1_framework = projects['jf1'][0]
    if (jf1_framework / 'runtime/jf1_family/include/jf1_desktop.h').is_file():
        family_integration = finish_palette_family(jf1_framework)
    return {"schema": 1, "kind": "post-aot-two-title-palette-preparation",
            "source_preparations": source_proofs,
            "project_sources": project_proofs,
            "bundle": {key: bundle[key] for key in (
                "semantic_catalog_sha256", "input_provenance_sha256", "emitter_sha256",
                "emitted_functions_sha256", "host_dispatch_sha256", "function_count",
                "unique_entry_segment_owners", "dispatch_keys", "ambiguous_dispatch_key_count")},
            "installations": install_proofs,
            "jf1_family_integration": family_integration,
            "native_build_performed": False, "game_run_performed": False,
            "full_static_coverage_proven": False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for game in GAMES:
        parser.add_argument(f"--preparation-{game}", type=Path, required=True)
        parser.add_argument(f"--layout-{game}", type=Path, required=True)
        parser.add_argument(f"--framework-{game}", type=Path, required=True)
        parser.add_argument(f"--project-cmake-{game}", type=Path, required=True)
    for option in ("emitter", "toolkit", "bundle-output", "accessor-source", "accessor-header"):
        parser.add_argument(f"--{option}", type=Path, required=True)
    parser.add_argument("--cps", action="store_true", required=True,
                        help="assert both prepared projects target the CPS dispatcher path")
    args = parser.parse_args()
    try:
        result = prepare_both(
            {game: getattr(args, f"preparation_{game}") for game in GAMES},
            {game: getattr(args, f"layout_{game}") for game in GAMES},
            emitter=args.emitter, toolkit=args.toolkit, bundle_output=args.bundle_output,
            projects={game: (getattr(args, f"framework_{game}"),
                             getattr(args, f"project_cmake_{game}")) for game in GAMES},
            accessor_source=args.accessor_source, accessor_header=args.accessor_header,
            cps_enabled=args.cps)
    except (GenerationError, SourceAuditError, PreparationError, OSError, ValueError) as exc:
        parser.exit(2, f"Palette preparation failed: {exc}\n")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
