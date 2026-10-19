#!/usr/bin/env python3
"""Opt in one audited JF2 static TU in an already-prepared private project.

Run after the verified static TU is selected by the private project, before
CMake configure. This verifies the known TU/header recipe, not full static coverage. The script only updates the private project CMakeLists and installs
the reviewed candidate header under that project's private PSXRECOMP_ROOT.
The generated CMake option remains OFF until explicitly enabled at configure.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import tomllib
from pathlib import Path

GAME_ID = "SCES-00111"
TU_NAME = "overlays_static_0036.c"
TU_SHA256 = "87dfe67c292d3728fc6587bf046e2a7d1585a81b09f0082aa1676e04f80115ce"
FAST_SHA256 = "cdeda37c3c3a05e0f8ff7808f6f9619571bc96d75a5f0efd32899fac8238c3c7"
BASE_SHA256 = "b2645f7f09369a209ea8b78a7e2aa299c45c2bcdeb276bdc65b78e77d0c62da6"
MARKER = "# COLLECTION_JF2_TU0036_FASTPREFIX_V4"
RECEIPT_NAME = ".collection-jf2-tu0036-fastprefix-v4.json"
HEADER_NAME = "collection_jf2_charge_fastprefix_psx_cyc.h"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def require_sha(data: bytes, expected: str, label: str) -> None:
    actual = sha(data)
    if actual != expected:
        raise ValueError(f"{label} SHA-256 mismatch: {actual}")


def _expand_path(value: str, project: Path) -> Path:
    value = value.replace("${CMAKE_CURRENT_SOURCE_DIR}", str(project))
    if "${" in value or "$<" in value:
        raise ValueError(f"unsupported variable in pinned path: {value}")
    path = Path(value)
    return (path if path.is_absolute() else project / path).resolve()


def _framework_root(cmake_text: str, project: Path) -> Path:
    match = re.search(r'(?m)^[ \t]*set\(PSXRECOMP_ROOT[ \t]+"([^"]+)"', cmake_text)
    value = match.group(1) if match else "${CMAKE_CURRENT_SOURCE_DIR}/psxrecomp"
    root = _expand_path(value, project)
    if project != root and project not in root.parents:
        raise ValueError("PSXRECOMP_ROOT must be inside the private prepared project")
    return root


def _repo_root() -> Path | None:
    for parent in Path(__file__).resolve().parents:
        if (parent / "collection").is_dir() and (parent / ".jf2-workbench").is_dir():
            return parent
    return None


def _reject_standalone_write(project: Path, framework: Path) -> None:
    repo = _repo_root()
    if repo is None:
        return
    standalone = (repo / ".jf2-workbench/recomp/JumpingFlash2Recomp").resolve()
    for label, path in (("project", project), ("framework", framework)):
        if path == standalone or standalone in path.parents or path in standalone.parents:
            raise ValueError(f"refusing to modify the standalone JF2 {label} tree")


def _aot_tu_from_list(cmake_text: str, project: Path) -> Path:
    matches = re.findall(r'(?ms)^set\(_JF2_AUDITED_STATIC_SOURCES\s*\n(.*?)^\)', cmake_text)
    if len(matches) != 1:
        raise ValueError("prepared project must declare one _JF2_AUDITED_STATIC_SOURCES list")
    quoted = re.findall(r'"([^"]+)"', matches[0])
    paths = [_expand_path(value, project) for value in quoted
             if Path(value.replace("\\", "/")).name.lower() == TU_NAME.lower()]
    if len(paths) != 1:
        raise ValueError(f"audited source list must contain exactly one {TU_NAME}, found {len(paths)}")
    return paths[0]


def _cmake_block() -> str:
    return f'''{MARKER}
option(COLLECTION_JF2_TU0036_FASTPREFIX
    "Use the reviewed fastprefix for the exact audited JF2 TU0036" OFF)
if(COLLECTION_JF2_TU0036_FASTPREFIX)
    if(NOT EXISTS "${{PSXRECOMP_ROOT}}/runtime/include/{HEADER_NAME}")
        message(FATAL_ERROR "JF2 TU0036 fastprefix header is missing")
    endif()
    file(STRINGS "${{CMAKE_CURRENT_SOURCE_DIR}}/game.toml" _collection_jf2_fastprefix_game_id
        REGEX "^[ \\t]*id[ \\t]*=[ \\t]*\\\"{GAME_ID}\\\"[ \\t]*$")
    if(NOT _collection_jf2_fastprefix_game_id)
        message(FATAL_ERROR "JF2 TU0036 fastprefix requires game id {GAME_ID}")
    endif()
    set(_collection_jf2_fastprefix_source "")
    foreach(_collection_jf2_fastprefix_candidate IN LISTS _JF2_AUDITED_STATIC_SOURCES)
        get_filename_component(_collection_jf2_fastprefix_name
            "${{_collection_jf2_fastprefix_candidate}}" NAME)
        if(_collection_jf2_fastprefix_name STREQUAL "{TU_NAME}")
            if(_collection_jf2_fastprefix_source)
                message(FATAL_ERROR "multiple audited {TU_NAME} entries")
            endif()
            set(_collection_jf2_fastprefix_source "${{_collection_jf2_fastprefix_candidate}}")
        endif()
    endforeach()
    if(NOT _collection_jf2_fastprefix_source)
        message(FATAL_ERROR "audited static source list lacks {TU_NAME}")
    endif()
    get_target_property(_collection_jf2_runtime_sources psx-runtime SOURCES)
    list(FIND _collection_jf2_runtime_sources "${{_collection_jf2_fastprefix_source}}"
        _collection_jf2_fastprefix_target_index)
    if(_collection_jf2_fastprefix_target_index EQUAL -1)
        message(FATAL_ERROR "audited {TU_NAME} is not a source of psx-runtime")
    endif()
    set(_collection_jf2_fastprefix_base
        "${{PSXRECOMP_ROOT}}/runtime/include/psx_cyc.h")
    set(_collection_jf2_fastprefix_header
        "${{PSXRECOMP_ROOT}}/runtime/include/{HEADER_NAME}")
    file(SHA256 "${{_collection_jf2_fastprefix_source}}" _collection_jf2_fastprefix_tu_sha)
    file(SHA256 "${{_collection_jf2_fastprefix_base}}" _collection_jf2_fastprefix_base_sha)
    file(SHA256 "${{_collection_jf2_fastprefix_header}}" _collection_jf2_fastprefix_header_sha)
    if(NOT _collection_jf2_fastprefix_tu_sha STREQUAL "{TU_SHA256}" OR
       NOT _collection_jf2_fastprefix_base_sha STREQUAL "{BASE_SHA256}" OR
       NOT _collection_jf2_fastprefix_header_sha STREQUAL "{FAST_SHA256}")
        message(FATAL_ERROR "JF2 TU0036 fastprefix fingerprint drift")
    endif()
    set_property(SOURCE "${{_collection_jf2_fastprefix_source}}"
        APPEND PROPERTY COMPILE_OPTIONS "-include" "${{_collection_jf2_fastprefix_header}}")
endif()
'''


def _append_newline_style(existing: bytes, block: str) -> bytes:
    newline = b"\r\n" if b"\r\n" in existing else b"\n"
    addition = block.replace("\n", newline.decode("ascii")).encode("utf-8")
    prefix = b"" if not existing or existing.endswith((b"\n", b"\r")) else newline
    return existing + prefix + addition


def _validate_project(project: Path, candidate_header: Path) -> dict:
    cmake_path = project / "CMakeLists.txt"
    game_path = project / "game.toml"
    if not cmake_path.is_file() or not game_path.is_file():
        raise ValueError("project must contain CMakeLists.txt and game.toml")
    cmake_bytes = cmake_path.read_bytes()
    cmake_text = cmake_bytes.decode("utf-8")
    game = tomllib.loads(game_path.read_text(encoding="utf-8"))
    if game.get("game", {}).get("id") != GAME_ID:
        raise ValueError("project game.id is not the pinned JF2 title")
    if "psxrecomp_add_game_runtime(psx-runtime" not in cmake_text:
        raise ValueError("expected psx-runtime target declaration is missing")
    if "set_source_files_properties(${_JF2_AUDITED_STATIC_SOURCES} PROPERTIES" not in cmake_text:
        raise ValueError("prepared post-AOT source-property tail is missing")
    tu_path = _aot_tu_from_list(cmake_text, project)
    if not tu_path.is_file():
        raise ValueError("audited TU0036 source is missing")
    require_sha(tu_path.read_bytes(), TU_SHA256, TU_NAME)
    framework = _framework_root(cmake_text, project)
    base_header = framework / "runtime/include/psx_cyc.h"
    require_sha(base_header.read_bytes(), BASE_SHA256, "prepared project's original psx_cyc.h")
    header = candidate_header.resolve()
    header_bytes = header.read_bytes()
    require_sha(header_bytes, FAST_SHA256, "candidate fastprefix header")
    _reject_standalone_write(project, framework)
    return {"cmake_path": cmake_path, "cmake_bytes": cmake_bytes, "framework": framework,
            "header_bytes": header_bytes, "header_path": framework / "runtime/include" / HEADER_NAME,
            "tu_path": tu_path}

def apply(project_root: Path, candidate_header: Path, *, write: bool) -> dict:
    project = project_root.resolve()
    validated = _validate_project(project, candidate_header)
    cmake_path: Path = validated["cmake_path"]
    current: bytes = validated["cmake_bytes"]
    receipt_path = project / RECEIPT_NAME
    block = _cmake_block()
    if MARKER.encode() in current:
        if not receipt_path.is_file():
            raise ValueError("fastprefix marker exists without its integrity receipt")
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        block_bytes = block.replace("\n", "\r\n" if b"\r\n" in current else "\n").encode("utf-8")
        append_bytes = receipt.get("append_bytes")
        if not isinstance(append_bytes, int) or append_bytes < len(block_bytes) or append_bytes > len(current):
            raise ValueError("fastprefix integrity receipt has an invalid appended length")
        suffix = current[-append_bytes:]
        if (not suffix.endswith(block_bytes) or current.count(MARKER.encode()) != 1 or
                sha(suffix) != receipt.get("append_sha256")):
            raise ValueError("fastprefix CMake marker is not the exact final appended block")
        base = current[:-append_bytes]
        if (receipt.get("parent_cmake_sha256") != sha(base) or
                receipt.get("current_cmake_sha256") != sha(current) or
                receipt.get("tu_sha256") != TU_SHA256 or
                receipt.get("header_sha256") != FAST_SHA256):
            raise ValueError("fastprefix applied CMake or inputs drifted since preparation")
        installed = validated["header_path"]
        require_sha(installed.read_bytes(), FAST_SHA256, "installed fastprefix header")
        return {"state": "already-prepared-integrity-verified", "cmake": str(cmake_path)}
    if receipt_path.exists():
        raise ValueError("fastprefix integrity receipt exists without CMake marker")
    new_cmake = _append_newline_style(current, block)
    header_path: Path = validated["header_path"]
    if header_path.exists() and header_path.read_bytes() != validated["header_bytes"]:
        raise ValueError("refusing to overwrite a different installed fastprefix header")
    appended = new_cmake[len(current):]
    receipt = {"schema": "private JF2 TU0036 fastprefix integration v4",
               "parent_cmake_sha256": sha(current), "current_cmake_sha256": sha(new_cmake),
               "append_sha256": sha(appended), "append_bytes": len(appended), "tu_sha256": TU_SHA256,
               "header_sha256": FAST_SHA256, "original_header_sha256": BASE_SHA256, "applied_option_default": False}
    if write:
        header_path.parent.mkdir(parents=True, exist_ok=True)
        if not header_path.exists():
            shutil.copyfile(candidate_header, header_path)
        require_sha(header_path.read_bytes(), FAST_SHA256, "installed fastprefix header")
        temp_cmake = cmake_path.with_name(cmake_path.name + ".fastprefix-tmp")
        temp_receipt = receipt_path.with_name(receipt_path.name + ".tmp")
        temp_cmake.write_bytes(new_cmake)
        temp_receipt.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        os.replace(temp_cmake, cmake_path)
        os.replace(temp_receipt, receipt_path)
        return {"state": "private-prepared-opt-in-off", "cmake": str(cmake_path),
                "receipt": str(receipt_path), "configure_option":
                "-DCOLLECTION_JF2_TU0036_FASTPREFIX=ON"}
    return {"state": "validated-dry-run", "cmake": str(cmake_path),
            "parent_cmake_sha256": receipt["parent_cmake_sha256"],
            "candidate_cmake_sha256": receipt["current_cmake_sha256"],
            "configure_option": "-DCOLLECTION_JF2_TU0036_FASTPREFIX=ON"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--candidate-header", required=True, type=Path)
    parser.add_argument("--apply", action="store_true", help="modify only the validated private project")
    args = parser.parse_args(argv)
    print(json.dumps(apply(args.project_root, args.candidate_header, write=args.apply), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
