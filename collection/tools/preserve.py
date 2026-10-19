"""Snapshot the existing native executables, preferences and saves, never move them."""
from pathlib import Path
import datetime
import hashlib
import json
import shutil
import argparse

ROOT = Path(__file__).resolve().parents[2]
SOURCES = {
    'jf2': ROOT / '.jf2-workbench/recomp/JumpingFlash2Recomp',
    'robbit': ROOT / 'robbit-mon-dieu/.workbench',
}

def preserve():
    target = ROOT / 'collection/.workbench/baselines' / datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    target.mkdir(parents=True, exist_ok=False)
    receipt = {'schema': 1, 'games': {}}
    for game, source in SOURCES.items():
        build = source / ('build-desktop' if game == 'jf2' else 'build')
        files = list(build.glob('*Recompiled.exe'))
        files += [p for p in build.glob('*.toml') if p.is_file()]
        files += [p for p in build.glob('*.ini') if p.is_file()]
        files += [p for p in (source / 'saves').rglob('*') if p.is_file()]
        records = []
        for path in files:
            relative = path.relative_to(source)
            output = target / game / relative
            output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, output)
            with path.open('rb') as stream:
                digest = hashlib.file_digest(stream, 'sha256').hexdigest()
            with output.open('rb') as stream:
                assert hashlib.file_digest(stream, 'sha256').hexdigest() == digest
            records.append({'path': relative.as_posix(), 'sha256': digest, 'bytes': path.stat().st_size})
        receipt['games'][game] = records
    (target / 'receipt.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    print(target)

def verify(baseline):
    receipt=json.loads((baseline/'receipt.json').read_text())
    checked=0
    for game,records in receipt['games'].items():
        for record in records:
            path=SOURCES[game]/record['path']
            with path.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
            if digest!=record['sha256']:raise ValueError(f'Standalone baseline changed: {path}')
            checked+=1
    print(f'PASS: {checked} original standalone build/settings/save files unchanged')

if __name__ == '__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--verify',type=Path);args=parser.parse_args()
    verify(args.verify) if args.verify else preserve()
