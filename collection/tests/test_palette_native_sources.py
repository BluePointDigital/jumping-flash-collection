from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPO = Path(__file__).resolve().parents[2]
TOOL = REPO / "collection/tools/palette_native_sources.py"
SPEC = importlib.util.spec_from_file_location("palette_native_sources", TOOL)
sources = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(sources)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def dump(path: Path, value: object) -> bytes:
    data = json.dumps(value, separators=(",", ":")).encode()
    path.write_bytes(data)
    return data


def fixture(root: Path) -> tuple[Path, dict[str, Path], dict[str, Path]]:
    reference = json.loads(sources.CATALOG.read_text(encoding="utf-8"))
    catalog = {"schema": 1, "evidence_record_sha256": {}, "layout_sha256": {},
               "families": reference["families"], "images": []}
    records_paths, layout_paths = {}, {}
    for game in sources.GAMES:
        expected_images = [r for r in reference["images"] if r["game"] == game]
        records, layouts = [], {"schema": 1, "game": game, "images": {}}
        words = [int(w, 16) for w in catalog["families"][game]["words"]]
        for i, expected in enumerate(expected_images):
            inst = words.copy()
            inst[0] |= (0x1000 + i) & 0xFFFF
            inst[1] |= (0x2000 + i) & 0xFFFF
            body = struct.pack("<30I", *inst)
            image = f"{game.upper()}_{i:02d}/MAIN.PEX"
            load = 0x80000000 + i * 0x1000
            record = {"producer": "verified_psx_exe_lz1", "producer_name": image,
                      "load_addr": f"0x{load:08x}", "bytes_b64": base64.b64encode(body).decode()}
            records.append(record)
            layouts["images"][image] = {"body_sha256": digest(body), "load_addr": f"0x{load:08x}",
                                         "template": f"0x{load:08x}", "size": 120,
                                         "template_sha256": digest(body)}
            catalog["images"].append({"game": game, "image": image, "body_sha256": digest(body),
                                      "load_addr": f"0x{load:08x}", "entry": f"0x{load:08x}",
                                      "entry_offset": 0, "template_sha256": digest(body),
                                      "family_sha256": catalog["families"][game]["sha256"], "size": 120})
        game_dir = root / game
        game_dir.mkdir(parents=True)
        rp, lp = game_dir / "records.json", game_dir / "layout.json"
        catalog["evidence_record_sha256"][game] = digest(dump(rp, records))
        catalog["layout_sha256"][game] = digest(dump(lp, layouts))
        records_paths[game], layout_paths[game] = rp, lp
    cp = root / "catalog.json"
    cp.write_text(json.dumps(catalog, indent=2) + "\n", encoding="utf-8")
    raw = cp.read_bytes().replace(b"\r\n", b"\n")
    cp.write_bytes(raw.replace(b"\n", b"\r\n"))
    return cp, records_paths, layout_paths


class PaletteNativeSourceTests(unittest.TestCase):
    def test_relocation_keeps_semantics_and_corrupt_body_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            catalog, records, layouts = fixture(root / "one")
            catalog_lf = catalog.read_bytes().replace(b"\r\n", b"\n")
            with mock.patch.object(sources, "CATALOG", catalog), mock.patch.object(
                    sources, "CATALOG_SHA256", digest(catalog_lf)):
                sem1, prov1 = root / "one-out/semantic.json", root / "one-out/provenance.json"
                sources.prepare(records, layouts, semantic_output=sem1, provenance_output=prov1)
                records2, layouts2 = {}, {}
                for game in sources.GAMES:
                    folder = root / "relocated" / game
                    folder.mkdir(parents=True)
                    records2[game], layouts2[game] = folder / "records.json", folder / "layout.json"
                    record_data = json.loads(records[game].read_text(encoding="utf-8"))
                    layout_data = json.loads(layouts[game].read_text(encoding="utf-8"))
                    for record in record_data:
                        record["rebuild_note"] = "different harmless metadata"
                    layout_data["container_note"] = "different formatting and metadata"
                    records2[game].write_text(json.dumps(record_data, indent=4) + "\n", encoding="utf-8")
                    layouts2[game].write_text(json.dumps(layout_data, indent=4) + "\n", encoding="utf-8")
                sem2, prov2 = root / "two-out/semantic.json", root / "two-out/provenance.json"
                sources.prepare(records2, layouts2, semantic_output=sem2, provenance_output=prov2)
                self.assertEqual(sem1.read_bytes(), sem2.read_bytes())
                self.assertNotEqual(prov1.read_bytes(), prov2.read_bytes())

                data = json.loads(records["jf1"].read_text(encoding="utf-8"))
                damaged = bytearray(base64.b64decode(data[0]["bytes_b64"]))
                damaged[0] ^= 1
                data[0]["bytes_b64"] = base64.b64encode(damaged).decode()
                dump(records["jf1"], data)
                out_sem, out_prov = root / "bad/semantic.json", root / "bad/provenance.json"
                with self.assertRaises(sources.SourceAuditError):
                    sources.prepare(records, layouts, semantic_output=out_sem, provenance_output=out_prov)
                self.assertFalse(out_sem.exists())
                self.assertFalse(out_prov.exists())


if __name__ == "__main__":
    unittest.main()
