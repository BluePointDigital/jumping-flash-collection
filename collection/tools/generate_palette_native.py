"""Generate the explicit 36-image CPS palette helper and dispatcher bundle."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import palette_native_sources as source_audit


EXPECTED_EMITTER_SHA256 = "1316d5c8e6df229e1d2cd09cdb5ad45e2fe9ea4d41f7ef2c0739f14a92ded77c"
EXPECTED_SPECIALIZED_C_SHA256 = "d1bf58938fb2da9a5e5a147e7234d03a9305be6f031edc58462e1b20142bac69"
EXPECTED_DISPATCH_C_SHA256 = "34d268ccf92c5923bbeea401e2a71d8d2c0376fd95526cf9087650b75c001701"
ACCESSOR_C_SHA256 = "93e608b6560c77de3ec1375d503815fb85cde60a31195c7228f65507cfa57f28"
ACCESSOR_H_SHA256 = "dca9116ff71be5d33d607ac3a55836044572ccaf52efaf2618f3902addcc138f"
MIN_FREE_BYTES = 4 * 1024 * 1024 * 1024
TOOLKIT_TEXT_SUFFIXES = {
    ".c", ".h", ".cc", ".cpp", ".hpp", ".in", ".inc", ".py", ".toml", ".json",
    ".xml", ".yaml", ".yml", ".cmake", ".txt", ".s", ".S", ".ps1", ".bat", ".sh",
    ".cfg", ".ini", ".def", ".ld", ".asm", ".csv",
}
TOOLKIT_SOURCE_DIRS = {"cmake", "generated", "lib", "mods", "overlay_toolchain", "recompiler", "runtime", "third_party", "tools"}
SEGMENTS = (("kuseg", 0x00000000), ("kseg0", 0x80000000), ("kseg1", 0xA0000000))
SEGMENT_MASKS = {name: value for name, value in SEGMENTS}


class GenerationError(RuntimeError):
    """Raised when source evidence or generated output fails its contract."""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _extract_function(source: str, entry: int) -> str:
    marker = f"void func_{entry:08X}(CPUState* cpu)"
    match = re.search(re.escape(marker) + r"\s*\{", source)
    if not match:
        raise GenerationError(f"pinned emitter omitted owner {marker}")
    brace = source.find("{", match.start())
    depth = 0
    for pos in range(brace, len(source)):
        if source[pos] == "{":
            depth += 1
        elif source[pos] == "}":
            depth -= 1
            if depth == 0:
                body = source[match.start():pos + 1]
                break
    else:
        raise GenerationError(f"unclosed emitter function at {entry:08X}")
    if "psx_native_bad_entry" not in body or f"case 0x{entry:08X}u:" not in body:
        raise GenerationError(f"emitter CPS entry switch missing for {entry:08X}")
    return body


def _specialize_function(body: str, entry: int, name: str, operand: int) -> str:
    lui = re.compile(
        r"(?m)^    cpu->gpr\[8\] = 0x[0-9A-Fa-f]{4} << 16;  /\* 0x[0-9A-Fa-f]{8} \*/\n"
        r"    PGXP_ALU\(0x3C08[0-9A-Fa-f]{4}u, cpu->gpr\[8\], 0u, 0u\);  "
        r"/\* 0x([0-9A-Fa-f]{8}): 0x3C08([0-9A-Fa-f]{4}) \*/")
    ori = re.compile(
        r"(?m)^    \{ uint32_t _pgx1 = cpu->gpr\[8\]; cpu->gpr\[8\] = cpu->gpr\[8\] \| 0x[0-9A-Fa-f]{4};\n"
        r"    PGXP_ALU\(0x3508[0-9A-Fa-f]{4}u, cpu->gpr\[8\], _pgx1, 0x[0-9A-Fa-f]{4}u\); \}  "
        r"/\* 0x([0-9A-Fa-f]{8}): 0x3508([0-9A-Fa-f]{4}) \*/")
    first, second = lui.search(body), ori.search(body)
    if not first or not second or int(first.group(1), 16) != entry or int(second.group(1), 16) != entry + 4:
        raise GenerationError(f"{name}: immediate instructions are not the first two emitted instructions")
    if ((int(first.group(2), 16) << 16) | int(second.group(2), 16)) != operand:
        raise GenerationError(f"{name}: emitter literal differs from the audited source body")
    lui_replacement = (
        f"    uint32_t _pi_{name}_lui=0u; if(!psx_native_instruction_word_host(cpu,0x{entry:08X}u,&_pi_{name}_lui))"
        f"{{cpu->pc=0x{entry:08X}u;psx_native_bad_entry(cpu,0x{entry:08X}u,0x{entry:08X}u);return;}}\n"
        f"    cpu->gpr[8]=(_pi_{name}_lui&0xFFFFu)<<16; PGXP_ALU(_pi_{name}_lui,cpu->gpr[8],0u,0u);")
    ori_replacement = (
        f"    {{uint32_t _pgx1=cpu->gpr[8],_pi_{name}_ori=0u; if(!psx_native_instruction_word_host(cpu,0x{entry+4:08X}u,&_pi_{name}_ori))"
        f"{{cpu->pc=0x{entry+4:08X}u;psx_native_bad_entry(cpu,0x{entry:08X}u,0x{entry+4:08X}u);return;}}\n"
        f"    cpu->gpr[8]|=_pi_{name}_ori&0xFFFFu; PGXP_ALU(_pi_{name}_ori,cpu->gpr[8],_pgx1,_pi_{name}_ori&0xFFFFu);}}")
    result, n_lui = lui.subn(lui_replacement, body, count=1)
    result, n_ori = ori.subn(ori_replacement, result, count=1)
    if (n_lui, n_ori) != (1, 1):
        raise GenerationError(f"{name}: emitter immediate transform anchors changed")
    return result.replace(f"func_{entry:08X}", name, 1)


def _c_function(source: str, name: str) -> str:
    match = re.search(r"\bvoid\s+" + re.escape(name) + r"\s*\(CPUState\*\s*cpu\)\s*\{", source)
    if not match:
        raise GenerationError(f"missing emitted function body: {name}")
    brace, depth = source.find("{", match.start()), 0
    for pos in range(brace, len(source)):
        if source[pos] == "{":
            depth += 1
        elif source[pos] == "}":
            depth -= 1
            if depth == 0:
                return source[match.start():pos + 1]
    raise GenerationError(f"unclosed emitted function body: {name}")


def build_dispatch_candidate(emitted_c: bytes, emission_receipt: dict[str, Any],
                             semantic_catalog: dict[str, Any]) -> tuple[bytes, dict[str, Any]]:
    """Build the owner-coherent 216-key dispatcher without invoking the emitter."""
    rows = emission_receipt.get("entries")
    if (emission_receipt.get("function_count") != 108 or not isinstance(rows, list)
            or len(rows) != 108 or sha256(emitted_c) != emission_receipt.get("c_sha256")):
        raise GenerationError("emitted helper source/receipt mismatch or incomplete inventory")
    images = {(row["game"], row["image"]): row for row in semantic_catalog["images"]}
    if len(images) != 36:
        raise GenerationError("semantic source catalog must contain 36 unique images")
    families = semantic_catalog["families"]
    emitted_text = emitted_c.decode("utf-8")
    owners: dict[tuple[int, str], dict[str, Any]] = {}
    owner_bodies: dict[tuple[int, str], str] = {}
    expected_segments = {name for name, _ in SEGMENTS}
    seen = set()
    for row in rows:
        key_image = (row.get("game"), row.get("image"))
        image = images.get(key_image)
        if image is None:
            raise GenerationError(f"emitted row names unsupported image {key_image}")
        segment = row.get("segment")
        if segment not in expected_segments:
            raise GenerationError(f"unsupported segment in generated row: {segment}")
        base = int(image["entry"], 16) & 0x1FFFFFFF
        expected_entry = base | SEGMENT_MASKS[segment]
        expected_offsets = families[row["game"]]["legal_entry_offsets"]
        if (int(row["entry"], 16) != expected_entry or row.get("body_sha256") != image["body_sha256"]
                or row.get("family_sha256") != image["family_sha256"]
                or row.get("template_sha256") != image["template_sha256"]
                or row.get("legal_entry_offsets") != expected_offsets):
            raise GenerationError(f"generated metadata differs from source catalog for {key_image}/{segment}")
        key = (expected_entry, segment)
        if (key_image, segment) in seen:
            raise GenerationError(f"duplicate emitted image/segment row: {key_image}/{segment}")
        seen.add((key_image, segment))
        function = row.get("function")
        body = _c_function(emitted_text, function)
        normalized = body.replace(function, "<palette_fn>")
        previous = owner_bodies.setdefault(key, normalized)
        if previous != normalized:
            raise GenerationError(f"non-identical emitted owners share entry/segment {key}")
        group = owners.setdefault(key, {"entry": expected_entry, "segment": segment,
                                        "game": row["game"], "function": function, "operands": set()})
        if group["game"] != row["game"]:
            raise GenerationError(f"cross-family owners collide at {key}")
        group["operands"].add(int(row["operand"], 16))
    if len(seen) != 108 or {game: sum(k[0][0] == game for k in seen) for game in ("jf1", "jf2")} != {"jf1": 36, "jf2": 72}:
        raise GenerationError("generated inventory does not cover 36 images × 3 segments")

    entries = sorted(owners.values(), key=lambda row: (row["entry"], row["segment"]))
    by_key = {(row["entry"], row["segment"]): index for index, row in enumerate(entries)}
    keys = []
    for index, row in enumerate(entries):
        for offset in families[row["game"]]["legal_entry_offsets"]:
            keys.append((row["entry"] + offset, index, offset))
    keys.sort()
    family_words = [f"static const uint32_t palette_words_{game}[30]={{{','.join('0x'+word+'u' for word in families[game]['words'])}}};"
                    for game in ("jf1", "jf2")]
    operand_rows = []
    for index, row in enumerate(entries):
        operands = sorted(row["operands"])
        operand_rows.append(f"static const uint32_t palette_operands_{index}[{len(operands)}]={{{','.join(f'0x{x:08X}u' for x in operands)}}};")

    body = '''
#include <stdint.h>
#include <string.h>
#include "psx_runtime.h"
#include "native_instruction_word_access.h"
extern void debug_server_cyc_observe(uint32_t);
extern void psx_native_bad_entry(CPUState*,uint32_t,uint32_t);
typedef void (*PaletteFn)(CPUState*);
typedef struct PaletteEntry { uint32_t pc, segment, family; PaletteFn fn; const uint32_t *operands; uint32_t operand_count; } PaletteEntry;
typedef struct PaletteKey { uint32_t address, owner, offset; } PaletteKey;
'''+"\n".join(family_words)+"\n"+"\n".join(operand_rows)+"\n"+"".join(
        f"void {row['function']}(CPUState*);\n" for row in rows)+"\n"
    entry_rows = []
    for index, row in enumerate(entries):
        family_id = 1 if row["game"] == "jf1" else 2
        mask = SEGMENT_MASKS[row["segment"]]
        entry_rows.append(f"{{0x{row['entry']:08X}u,0x{mask:08X}u,{family_id}u,{row['function']},palette_operands_{index},(uint32_t)(sizeof(palette_operands_{index})/sizeof(palette_operands_{index}[0]))}}")
    body += f"static const PaletteEntry palette_entries[{len(entries)}]={{{',\n'.join(entry_rows)}}};\n"
    body += f"static const PaletteKey palette_keys[{len(keys)}]={{{',\n'.join('{0x%08Xu,%du,%du}' % row for row in keys)}}};\n"
    body += '''
static uint64_t palette_dispatch_attempts, palette_dispatch_hits, palette_shape_rejects, palette_noncatalog_operands;
void psx_palette_native_dispatch_stats(uint64_t *attempts,uint64_t *hits,uint64_t *rejects,uint64_t *noncatalog_operands){if(attempts)*attempts=palette_dispatch_attempts;if(hits)*hits=palette_dispatch_hits;if(rejects)*rejects=palette_shape_rejects;if(noncatalog_operands)*noncatalog_operands=palette_noncatalog_operands;}
static int palette_shape_ok(const PaletteEntry *e){
    const uint32_t *expected=e->family==1u?palette_words_jf1:palette_words_jf2;
    if(e->family!=1u&&e->family!=2u)return 0;
    for(uint32_t i=0;i<30u;i++){uint32_t w=0;if(!psx_native_instruction_word_host(NULL,e->pc+4u*i,&w))return 0;if(i<2u){if((w&0xFFFF0000u)!=(expected[i]&0xFFFF0000u))return 0;}else if(w!=expected[i])return 0;}
    return 1;
}
/* 1 only after executing a fully shape- and PC-guarded CPS helper; 0 leaves CPU untouched for the interpreter. */
int psx_palette_native_try_dispatch(CPUState *cpu,uint32_t address,int forced,int native_enabled,int cps_mode){
    if(!cpu||forced||!native_enabled||!cps_mode)return 0;
    uint32_t lo=0,hi=(uint32_t)(sizeof(palette_keys)/sizeof(palette_keys[0]));
    while(lo<hi){uint32_t mid=lo+(hi-lo)/2u;if(palette_keys[mid].address<address)lo=mid+1u;else hi=mid;}
    uint32_t first=lo, owner=0xFFFFFFFFu, offset=0, matches=0;
    for(uint32_t i=first;i<sizeof(palette_keys)/sizeof(palette_keys[0])&&palette_keys[i].address==address;i++){
        const PaletteKey *k=&palette_keys[i];const PaletteEntry *e=&palette_entries[k->owner];
        if((address&0xE0000000u)!=e->segment)continue;
        palette_dispatch_attempts++;
        if(palette_shape_ok(e)){owner=k->owner;offset=k->offset;matches++;}
    }
    if(matches!=1u){if(matches>1u||first<sizeof(palette_keys)/sizeof(palette_keys[0])&&palette_keys[first].address==address)palette_shape_rejects++;return 0;}
    const PaletteEntry *e=&palette_entries[owner];uint32_t lui=0,ori=0;
    if(!psx_native_instruction_word_host(NULL,e->pc,&lui)||!psx_native_instruction_word_host(NULL,e->pc+4u,&ori)){palette_shape_rejects++;return 0;}
    uint32_t operand=((lui&0xFFFFu)<<16)|(ori&0xFFFFu);int known=0;
    for(uint32_t i=0;i<e->operand_count;i++)if(e->operands[i]==operand){known=1;break;}
    if(!known)palette_noncatalog_operands++;
    cpu->pc=address;
    e->fn(cpu); /* Preserve the emitter's CPS PC/RA/cycle contract verbatim. */
    (void)offset;palette_dispatch_hits++;return 1;
}
'''
    body += "\n" + emitted_text
    source_bytes = body.encode("utf-8")
    ambiguous = sum(keys[i][0] == keys[i - 1][0] for i in range(1, len(keys)))
    receipt = {
        "schema": 2, "kind": "palette-native-host-dispatch",
        "host_dispatch_sha256": sha256(source_bytes), "function_count": len(rows),
        "unique_entry_segment_owners": len(entries), "dispatch_keys": len(keys),
        "ambiguous_dispatch_key_count": ambiguous,
        "duplicate_owner_bodies_identical": True,
        "accessor_sha256": ACCESSOR_C_SHA256, "accessor_header_sha256": ACCESSOR_H_SHA256,
        "family_hashes": {game: families[game]["sha256"] for game in ("jf1", "jf2")},
        "semantic_catalog_sha256": sha256(json.dumps(semantic_catalog, indent=2, ensure_ascii=True).encode("utf-8") + b"\n"),
    }
    return source_bytes, receipt


def _tree_sha256(root: Path, *, exclude_path: Path) -> tuple[str, list[dict[str, str]]]:
    if not root.is_dir():
        raise GenerationError(f"runtime toolkit is not a directory: {root}")
    excluded = {".git", ".cache", "__pycache__", "node_modules"}
    root = root.resolve()
    excluded_path = exclude_path.resolve()
    files = []
    for directory, dirs, names in os.walk(root):
        current = Path(directory)
        dirs[:] = sorted(name for name in dirs
                         if (current != root or name in TOOLKIT_SOURCE_DIRS)
                         and name not in excluded and name.lower() != "build" and not name.lower().startswith("build-")
                         and (current / name).resolve() != excluded_path)
        for name in sorted(names):
            path = current / name
            if path.suffix in TOOLKIT_TEXT_SUFFIXES and path.is_file():
                files.append(path)
    files.sort(key=lambda path: path.relative_to(root).as_posix())
    digest = hashlib.sha256()
    manifest = []
    for path in files:
        relative = path.relative_to(root).as_posix().encode("utf-8")
        raw = path.read_bytes()
        file_sha = sha256(raw)
        manifest.append({"path": relative.decode("utf-8"), "sha256": file_sha})
        digest.update(len(relative).to_bytes(4, "little")); digest.update(relative)
        digest.update(bytes.fromhex(file_sha))
    return digest.hexdigest(), manifest


def generate(records: dict[str, Path], layouts: dict[str, Path], *, emitter: Path,
             toolkit: Path, accessor_source: Path, accessor_header: Path,
             output_dir: Path) -> dict[str, Any]:
    if set(records) != set(source_audit.GAMES) or set(layouts) != set(source_audit.GAMES):
        raise GenerationError(f"records and layouts must contain exactly {source_audit.GAMES}")
    final_output = output_dir.resolve()
    if final_output.exists():
        raise GenerationError(f"output directory must be new: {final_output}")
    def resolved_existing(path: Path, label: str) -> Path:
        try:
            return path.resolve(strict=True)
        except OSError as exc:
            raise GenerationError(f"missing {label}: {path}") from exc
    emitter = resolved_existing(emitter, "emitter")
    toolkit = resolved_existing(toolkit, "runtime toolkit")
    accessor_source = resolved_existing(accessor_source, "instruction accessor source")
    accessor_header = resolved_existing(accessor_header, "instruction accessor header")
    records = {game: resolved_existing(records[game], f"{game} records") for game in source_audit.GAMES}
    layouts = {game: resolved_existing(layouts[game], f"{game} layout") for game in source_audit.GAMES}
    volume_path = final_output.parent
    while not volume_path.is_dir():
        volume_path = volume_path.parent
    free_bytes = shutil.disk_usage(volume_path).free
    if free_bytes < MIN_FREE_BYTES:
        raise GenerationError(f"need at least {MIN_FREE_BYTES} free bytes before emitter start; found {free_bytes}")
    emitter_bytes = emitter.read_bytes()
    emitter_sha = sha256(emitter_bytes)
    if emitter_sha != EXPECTED_EMITTER_SHA256:
        raise GenerationError(f"pinned emitter SHA-256 mismatch: {emitter_sha}")
    semantic_bytes, source_provenance_bytes, record_maps = source_audit.build_outputs_with_audited_records(
        records, layouts)
    semantic_catalog = json.loads(semantic_bytes)
    source_provenance = json.loads(source_provenance_bytes)
    accessor_c_sha, accessor_h_sha = sha256(accessor_source.read_bytes()), sha256(accessor_header.read_bytes())
    if accessor_c_sha != ACCESSOR_C_SHA256 or accessor_h_sha != ACCESSOR_H_SHA256:
        raise GenerationError("instruction accessor does not match the reviewed runtime source/header")
    toolkit_sha, toolkit_files = _tree_sha256(toolkit, exclude_path=final_output)
    functions, entry_rows = [], []
    scratch_parent = final_output.parent
    scratch_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="palette-native-emission-", dir=scratch_parent) as temporary:
        scratch = Path(temporary)
        for image in semantic_catalog["images"]:
            game, image_name = image["game"], image["image"]
            record = record_maps[game][image_name]
            source_body = base64.b64decode(record["bytes_b64"], validate=True)
            load, entry0 = int(image["load_addr"], 16), int(image["entry"], 16)
            offset = entry0 - load
            template = source_body[offset:offset + 120]
            w0, w1 = struct.unpack_from("<II", template)
            operand = ((w0 & 0xFFFF) << 16) | (w1 & 0xFFFF)
            for segment_name, segment_mask in SEGMENTS:
                entry = (entry0 & 0x1FFFFFFF) | segment_mask
                label = re.sub(r"[^A-Za-z0-9_]+", "_", f"{game}_{image_name}_{segment_name}").strip("_").lower()
                outdir = scratch / game / label / "emitted"
                outdir.mkdir(parents=True)
                exe = bytearray(2048 + 120)
                exe[:8] = b"PS-X EXE"
                struct.pack_into("<I", exe, 16, entry)
                struct.pack_into("<I", exe, 24, entry)
                struct.pack_into("<I", exe, 28, 120)
                exe[2048:] = template
                input_exe = outdir.parent / "input.exe"
                input_exe.write_bytes(exe)
                seed = outdir.parent / "seed.txt"
                seed.write_text(f"0x{entry:08X}\n", encoding="ascii", newline="\n")
                env = os.environ.copy()
                env["PSX_CPS"] = "1"
                command = [str(emitter), str(input_exe), "--seeds", str(seed), "--out-dir", str(outdir),
                           "--overlay", "--project-root", str(toolkit)]
                result = subprocess.run(command, cwd=toolkit.parent, env=env, text=True,
                                        capture_output=True, check=False)
                (outdir.parent / "emitter.log").write_text(result.stdout + "\nSTDERR\n" + result.stderr,
                                                            encoding="utf-8", newline="\n")
                if result.returncode:
                    detail = (result.stdout + "\nSTDERR\n" + result.stderr)[-4000:]
                    raise GenerationError(f"{label}: pinned emitter failed ({result.returncode}):\n{detail}")
                c_units = list(outdir.glob("*_full.c"))
                if len(c_units) != 1:
                    detail = (result.stdout + "\nSTDERR\n" + result.stderr)[-3000:]
                    raise GenerationError(f"{label}: expected one emitted C unit, got {len(c_units)};\n{detail}")
                emitted_raw = c_units[0].read_bytes()
                emitted_source = emitted_raw.decode("utf-8")
                owner = _extract_function(emitted_source, entry)
                legal_resume = sorted(int(value.rstrip("u"), 16) - entry for value, _ in re.findall(
                    r"case (0x[0-9A-Fa-f]+u): goto (block_[0-9A-Fa-f]+);", owner)
                    if int(value.rstrip("u"), 16) != entry)
                expected_resume = [32, 92] if game == "jf1" else [32, 88]
                if legal_resume != expected_resume:
                    raise GenerationError(f"{label}: expected CPS resume offsets {expected_resume}, got {legal_resume}")
                function = f"palette_{label}"
                functions.append(_specialize_function(owner, entry, function, operand))
                entry_rows.append({
                    "game": game, "image": image_name, "segment": segment_name,
                    "entry": f"0x{entry:08X}", "family_sha256": image["family_sha256"],
                    "body_sha256": image["body_sha256"], "template_sha256": sha256(template),
                    "operand": f"0x{operand:08X}", "emitted_c_sha256": sha256(emitted_raw),
                    "function": function, "legal_entry_offsets": [0, *expected_resume],
                })
    emitted_functions = ("\n\n".join(functions) + "\n").encode("utf-8")
    if sha256(emitted_functions) != EXPECTED_SPECIALIZED_C_SHA256:
        raise GenerationError("specialized native C differs from the reviewed 108-function candidate")
    dispatch_c, host_receipt = build_dispatch_candidate(
        emitted_functions,
        {"function_count": len(entry_rows), "entries": entry_rows,
         "c_sha256": sha256(emitted_functions)}, semantic_catalog)
    if sha256(dispatch_c) != EXPECTED_DISPATCH_C_SHA256:
        raise GenerationError("host dispatcher C differs from the reviewed 216-key candidate")

    # Do not publish receipts that describe inputs which changed during emission.
    for game in source_audit.GAMES:
        proof = source_provenance["inputs"][game]
        if (sha256(records[game].read_bytes()) != proof["records_sha256"]
                or sha256(layouts[game].read_bytes()) != proof["layout_sha256"]):
            raise GenerationError(f"{game} source inputs changed during emission")
    if sha256(emitter.read_bytes()) != emitter_sha:
        raise GenerationError("pinned emitter changed during generation")
    if (sha256(accessor_source.read_bytes()) != accessor_c_sha
            or sha256(accessor_header.read_bytes()) != accessor_h_sha):
        raise GenerationError("instruction accessor changed during generation")
    final_toolkit_sha, final_toolkit_files = _tree_sha256(toolkit, exclude_path=final_output)
    if final_toolkit_sha != toolkit_sha or final_toolkit_files != toolkit_files:
        raise GenerationError("runtime toolkit source inventory changed during emission")

    source_provenance.update({
        "emitter_sha256": emitter_sha, "emitter_path": str(emitter.resolve()),
        "toolkit_tree_sha256": toolkit_sha, "toolkit_file_count": len(toolkit_files),
        "toolkit_path": str(toolkit.resolve()), "toolkit_files": toolkit_files,
        "toolkit_hash_scope": "recognized source/config suffixes at toolkit root and under cmake/generated/lib/mods/overlay_toolchain/recompiler/runtime/third_party/tools; excludes VCS/cache/build directories and output subtree",
        "accessor_sha256": accessor_c_sha, "accessor_path": str(accessor_source.resolve()),
        "accessor_header_sha256": accessor_h_sha, "accessor_header_path": str(accessor_header.resolve()),
        "generator_sha256": sha256(Path(__file__).read_bytes()),
        "source_audit_tool_sha256": sha256(Path(source_audit.__file__).read_bytes()),
    })
    provenance_bytes = json.dumps(source_provenance, indent=2, ensure_ascii=True).encode("utf-8") + b"\n"
    provenance_sha = sha256(provenance_bytes)
    host_receipt.update({"input_provenance_sha256": provenance_sha, "emitter_sha256": emitter_sha,
                         "toolkit_tree_sha256": toolkit_sha,
                         "generator_sha256": source_provenance["generator_sha256"],
                         "source_audit_tool_sha256": source_provenance["source_audit_tool_sha256"],
                         "emitted_functions_sha256": sha256(emitted_functions),
                         "accessor_sha256": accessor_c_sha, "accessor_header_sha256": accessor_h_sha})
    host_receipt_bytes = json.dumps(host_receipt, indent=2, ensure_ascii=True).encode("utf-8") + b"\n"
    bundle_receipt = {
        "schema": 2, "kind": "palette-native-generated-bundle",
        "semantic_catalog_sha256": sha256(semantic_bytes),
        "input_provenance_sha256": provenance_sha, "emitter_sha256": emitter_sha,
        "toolkit_tree_sha256": toolkit_sha,
        "generator_sha256": source_provenance["generator_sha256"],
        "source_audit_tool_sha256": source_provenance["source_audit_tool_sha256"],
        "emitted_functions_sha256": sha256(emitted_functions),
        "host_dispatch_sha256": sha256(dispatch_c),
        "host_dispatch_receipt_sha256": sha256(host_receipt_bytes),
        "accessor_sha256": accessor_c_sha, "accessor_header_sha256": accessor_h_sha,
        "function_count": len(entry_rows), "unique_entry_segment_owners": host_receipt["unique_entry_segment_owners"],
        "dispatch_keys": host_receipt["dispatch_keys"],
        "ambiguous_dispatch_key_count": host_receipt["ambiguous_dispatch_key_count"],
        "segment_names": [name for name, _ in SEGMENTS],
        "family_hashes": {game: semantic_catalog["families"][game]["sha256"] for game in ("jf1", "jf2")},
        "legal_entry_offsets_by_family": {game: semantic_catalog["families"][game]["legal_entry_offsets"] for game in ("jf1", "jf2")},
        "entries": entry_rows,
    }
    receipt_bytes = json.dumps(bundle_receipt, indent=2, ensure_ascii=True).encode("utf-8") + b"\n"
    files = {
        "semantic-catalog.json": semantic_bytes,
        "input-provenance.json": provenance_bytes,
        "all_36x3_specialized.c": emitted_functions,
        "host_dispatch_candidate.c": dispatch_c,
        "receipt.json": receipt_bytes,
        "host_dispatch_receipt.json": host_receipt_bytes,
    }
    if final_output.exists():
        raise GenerationError(f"output directory appeared during generation: {final_output}")
    with tempfile.TemporaryDirectory(prefix="palette-native-bundle-", dir=scratch_parent) as temporary:
        stage = Path(temporary) / "bundle"
        stage.mkdir()
        for name, content in files.items():
            (stage / name).write_bytes(content)
        if final_output.exists():
            raise GenerationError(f"output directory appeared before bundle publication: {final_output}")
        stage.rename(final_output)
    return bundle_receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for game in source_audit.GAMES:
        parser.add_argument(f"--records-{game}", type=Path, required=True)
        parser.add_argument(f"--layout-{game}", type=Path, required=True)
    parser.add_argument("--emitter", type=Path, required=True)
    parser.add_argument("--toolkit", type=Path, required=True)
    parser.add_argument("--accessor-source", type=Path, required=True)
    parser.add_argument("--accessor-header", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    result = generate(
        {game: getattr(args, f"records_{game}") for game in source_audit.GAMES},
        {game: getattr(args, f"layout_{game}") for game in source_audit.GAMES},
        emitter=args.emitter, toolkit=args.toolkit, accessor_source=args.accessor_source,
        accessor_header=args.accessor_header, output_dir=args.output_dir)
    print(json.dumps({key: result[key] for key in (
        "semantic_catalog_sha256", "input_provenance_sha256", "emitter_sha256",
        "emitted_functions_sha256", "host_dispatch_sha256", "function_count",
        "unique_entry_segment_owners", "dispatch_keys", "ambiguous_dispatch_key_count")}, indent=2))


if __name__ == "__main__":
    main()
