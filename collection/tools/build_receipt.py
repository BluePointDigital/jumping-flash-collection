"""Record source, native binaries, toolchain version and per-title cache ABI."""
from pathlib import Path
import datetime
import hashlib
import json
import subprocess
import tomllib

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def generate():
    receipt = dict(schema=1, release='test-preview-0.3.0',
                   created_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                   sources={}, games={}, qualification_complete=False)
    for directory in [ROOT, REPO/'jumping-flash-1']:
        for file in sorted(directory.rglob('*')):
            relative = file.relative_to(directory)
            if any(part in ('.workbench', 'dist', 'releases', 'data', '__pycache__') for part in relative.parts):
                continue
            if file.is_file():
                receipt['sources'][file.relative_to(REPO).as_posix()] = digest(file)
    fingerprint=REPO/'robbit-mon-dieu/tools/robbit_desktop.h'
    receipt['sources'][fingerprint.relative_to(REPO).as_posix()]=digest(fingerprint)
    receipt['aot_tools']={name:digest(ROOT/'.workbench/emitters'/name) for name in
        ('psxrecomp-game.exe','psxrecomp-bios.exe','psxrecomp-analyze.exe')}
    catalog = tomllib.loads((ROOT/'catalog.toml').read_text(encoding='utf-8'))
    for game in catalog['games']:
        native = ROOT/'.workbench/native'/game['id']
        files = [native/'build'/Path(game['executable']).name, native/'game.toml',
                 native/'psxrecomp/runtime/src/main.cpp', native/'psxrecomp/runtime/src/overlay_loader.c',
                 native/'psxrecomp/runtime/src/mod_runtime.cpp', native/'psxrecomp/runtime/src/gpu_gl_renderer.c',
                 native/'psxrecomp/runtime/src/dirty_ram_interp.c',native/'psxrecomp/tools/compile_overlays.py',
                 native/'psxrecomp/runtime/src/debug_server.c',native/'psxrecomp/runtime/src/present_image_ring.c',
                 native/'psxrecomp/runtime/src/frame_pacing.c',native/'psxrecomp/runtime/src/render_thread.c',
                 native/'psxrecomp/runtime/include/overlay_api.h',
                 native/'psxrecomp/runtime/include/overlay_codegen_hash.h']
        for folder in ['desktop', 'generated']:
            files.extend(file for file in (native/folder).rglob('*') if file.is_file())
        files.append(native/'CMakeLists.txt')
        limits=native/'psxrecomp/runtime/include/collection_overlay_limits.json'
        files.append(limits)
        receipt.setdefault('runtime_limits',{})[game['id']]=json.loads(limits.read_text())
        receipt['games'][game['id']] = {file.relative_to(native).as_posix(): digest(file) for file in files}
        receipt.setdefault('build_flags',{})[game['id']]={}
        for line in (native/'build/CMakeCache.txt').read_text().splitlines():
            if line.startswith(('CMAKE_BUILD_TYPE:','PSX_DEBUG_TOOLS:','PSX_ENABLE_VULKAN:','PSX_REWIND:','PSX_SHELLWIN_INTERP:')):
                key,value=line.split('=',1);receipt['build_flags'][game['id']][key]=value
    compiler = REPO/'.jf2-workbench/recomp/toolchain/bin/clang.exe'
    receipt['compiler_version'] = subprocess.check_output([str(compiler), '--version'], text=True).strip()
    receipt['compiler_abi'] = json.loads((ROOT/'.workbench/evidence/compiler-abi.json').read_text())
    receipt['framework_pins'] = json.loads((REPO/'tools/recomp/pins.json').read_text())
    path = ROOT/'.workbench/evidence/build-receipt.json'
    path.write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    print(f'Build receipt: {path}')


if __name__ == '__main__':
    generate()
