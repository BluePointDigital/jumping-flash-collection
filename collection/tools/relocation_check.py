"""Copy a preview and verify it using only its bundled Python from another cwd."""
from pathlib import Path
import argparse
import datetime
import json
import os
import shutil
import subprocess


def check(source, destination, verify_only=False):
    source, destination = source.resolve(), destination.resolve()
    if (destination.exists() and not verify_only) or source == destination or source in destination.parents:
        raise ValueError('Choose a new destination outside the source package')
    measured_root = destination if verify_only else source
    total = sum(file.stat().st_size for file in measured_root.rglob('*') if file.is_file())
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not verify_only and shutil.disk_usage(destination.parent).free < total + 128*1024*1024:
        raise ValueError('Not enough space to copy the complete package')
    if not verify_only:
        shutil.copytree(source, destination)
    environment = os.environ.copy()
    # No developer Python, Clang, CMake or PowerShell directory in PATH.
    system_root = next(value for key, value in environment.items() if key.lower() == 'systemroot')
    for key in list(environment):
        if key.lower() in ('path', 'pythonpath', 'pythonhome', 'psxrecomp_toolchain_dir', 'psx_overlay_compiler'):
            environment.pop(key)
    environment['PATH'] = str(Path(system_root)/'System32')
    arguments=['--games']
    if (destination/'toolchain/include/collection_overlay_limits.json').is_file():
        arguments+=['--aot','--runtime-contract']
    result = subprocess.run([str(destination/'toolchain/python/python.exe'),
                             str(destination/'tools/verify_package.py'), *arguments],
                            cwd=destination.parent, env=environment,
                            capture_output=True, text=True, timeout=120)
    report = dict(schema=1, created_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  source=str(source), destination=str(destination), bytes_copied=total,
                  verification_exit_code=result.returncode, output=result.stdout, error=result.stderr,
                  developer_tools_removed_from_path=True,
                  verification_arguments=arguments,
                  graphical_launch_and_proton_qualified=False)
    (destination.parent/'relocation-receipt.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(result.stdout, end='')
    if result.returncode:
        raise RuntimeError(result.stderr or 'Relocated package verification failed')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--verify-only', action='store_true', help='Verify a previously copied folder without replacing files')
    args = parser.parse_args()
    check(args.source, args.destination, args.verify_only)
