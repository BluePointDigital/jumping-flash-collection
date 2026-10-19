from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


REPO = Path(__file__).resolve().parents[2]
TOOLS = REPO / "collection/tools"
sys.path.insert(0, str(TOOLS))


def load_tool(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


generator = load_tool("generate_palette_native_integration_target", TOOLS / "generate_palette_native.py")
patcher = load_tool("patch_palette_native_integration_target", TOOLS / "patch_palette_native.py")

STAGE = REPO / "collection/.workbench/static-recomp/staged/luna-static-coverage/host-linked-native-dispatch"
EMITTER = REPO / "collection/.workbench/emitters/psxrecomp-game.exe"
ACCESSOR_C = REPO / "collection/runtime/native_instruction_word_access.c"
ACCESSOR_H = REPO / "collection/runtime/native_instruction_word_access.h"
RECORDS = {
    "jf1": REPO / "collection/.workbench/static-recomp/aot/jf1-jm3-coherent-bootstrap/records.json",
    "jf2": REPO / "collection/.workbench/static-recomp/aot/jf2-c41-current-controls-all-worlds/records.json",
}
LAYOUTS = {
    "jf1": REPO / "collection/runtime/jf1_initialized_images.json",
    "jf2": REPO / "collection/runtime/jf2_initialized_images.json",
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class PaletteNativeReplayIntegrationTests(unittest.TestCase):
    def test_replayed_emitter_pipeline_bundle_installs_through_schema2(self) -> None:
        old_receipt = json.loads((STAGE / "receipt.json").read_bytes())
        replay_rows = old_receipt["entries"]
        self.assertEqual(len(replay_rows), 108)
        for row in replay_rows:
            raw = (STAGE / row["emitted_c"]).read_bytes()
            self.assertEqual(sha256(raw), row["emitted_c_sha256"])

        self.assertEqual(sha256(EMITTER.read_bytes()), generator.EXPECTED_EMITTER_SHA256)
        self.assertEqual(sha256(ACCESSOR_C.read_bytes()), generator.ACCESSOR_C_SHA256)
        self.assertEqual(sha256(ACCESSOR_H.read_bytes()), generator.ACCESSOR_H_SHA256)

        with tempfile.TemporaryDirectory(prefix="palette-native-replay-") as temporary:
            root = Path(temporary).resolve()
            toolkit = root / "tiny-toolkit"
            (toolkit / "runtime/include").mkdir(parents=True)
            (toolkit / "runtime/include/fixture.h").write_text("/* replay fixture */\n", encoding="utf-8")
            output = root / "generated-bundle"
            project = root / "project"
            framework = project / "psxrecomp"
            (framework / "runtime/src").mkdir(parents=True)
            shutil.copyfile(
                REPO / "collection/.workbench/native/jf1/psxrecomp/runtime/src/dirty_ram_interp.c",
                framework / "runtime/src/dirty_ram_interp.c")
            shutil.copyfile(REPO / "collection/.workbench/native/jf1/CMakeLists.txt", project / "CMakeLists.txt")

            call_index = 0

            def replay_run(command, *, cwd, env, text, capture_output, check):
                nonlocal call_index
                self.assertLess(call_index, len(replay_rows))
                row = replay_rows[call_index]
                call_index += 1
                self.assertTrue(Path(command[0]).is_absolute())
                self.assertEqual(Path(command[0]).resolve(), EMITTER.resolve())
                self.assertEqual(Path(cwd).resolve(), toolkit.parent.resolve())
                self.assertEqual(env.get("PSX_CPS"), "1")
                self.assertTrue(text and capture_output and check is False)
                input_exe = Path(command[1])
                seed = Path(command[command.index("--seeds") + 1])
                outdir = Path(command[command.index("--out-dir") + 1])
                project_root = Path(command[command.index("--project-root") + 1])
                self.assertTrue(input_exe.is_absolute() and seed.is_absolute() and outdir.is_absolute())
                self.assertEqual(project_root.resolve(), toolkit.resolve())
                self.assertEqual(int(seed.read_text(encoding="ascii").strip(), 16), int(row["entry"], 16))
                exe = input_exe.read_bytes()
                self.assertEqual(struct.unpack_from("<I", exe, 16)[0], int(row["entry"], 16))
                raw = (STAGE / row["emitted_c"]).read_bytes()
                self.assertEqual(sha256(raw), row["emitted_c_sha256"])
                outdir.mkdir(parents=True, exist_ok=True)
                (outdir / "input.exe_full.c").write_bytes(raw)
                return subprocess.CompletedProcess(command, 0, "replayed captured emitter output", "")

            def enough_disk(_path):
                return SimpleNamespace(free=generator.MIN_FREE_BYTES + 1)

            with mock.patch.object(generator.subprocess, "run", side_effect=replay_run), \
                    mock.patch.object(generator.shutil, "disk_usage", side_effect=enough_disk):
                receipt = generator.generate(
                    RECORDS, LAYOUTS, emitter=EMITTER, toolkit=toolkit,
                    accessor_source=ACCESSOR_C, accessor_header=ACCESSOR_H, output_dir=output)

            self.assertEqual(call_index, 108)
            self.assertEqual(receipt["function_count"], 108)
            self.assertEqual(receipt["unique_entry_segment_owners"], 72)
            self.assertEqual(receipt["dispatch_keys"], 216)
            self.assertEqual(receipt["ambiguous_dispatch_key_count"], 0)
            self.assertEqual(receipt["emitted_functions_sha256"], patcher.EMITTED_C_SHA256)
            self.assertEqual(receipt["host_dispatch_sha256"], patcher.HOST_BUNDLE_SHA256)

            evidence = patcher.prepare(
                framework, project / "CMakeLists.txt", output,
                accessor_source=ACCESSOR_C, accessor_header=ACCESSOR_H,
                game="jf1", cps_enabled=True)
            self.assertEqual(evidence["evidence_schema"], 2)
            self.assertEqual(evidence["generated_bundle_sha256"], patcher.EMITTED_C_SHA256)
            self.assertEqual(evidence["dispatcher_sha256"], patcher.HOST_BUNDLE_SHA256)
            generated_receipt = json.loads((output / "receipt.json").read_bytes())
            self.assertEqual(generated_receipt["function_count"], 108)
            self.assertEqual(generated_receipt["unique_entry_segment_owners"], 72)
            self.assertEqual(generated_receipt["dispatch_keys"], 216)
            self.assertEqual(generated_receipt["ambiguous_dispatch_key_count"], 0)


if __name__ == "__main__":
    unittest.main()
