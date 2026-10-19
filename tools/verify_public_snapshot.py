"""Verify the source-preview boundary and publication manifest (Python 3.11+)."""
from pathlib import Path
import ast, hashlib, json, re, tomllib

ROOT = Path(__file__).resolve().parents[1]
BLOCKED = {'.exe','.dll','.bin','.cue','.chd','.iso','.rom','.obj','.o','.a','.lib','.mcd','.mcr','.state','.ram','.vram','.bps','.log'}

def check():
    manifest = json.loads((ROOT/'PUBLICATION-MANIFEST.json').read_text(encoding='utf-8'))
    actual = {f.relative_to(ROOT).as_posix():f for f in ROOT.rglob('*') if f.is_file() and '.git' not in f.relative_to(ROOT).parts and '__pycache__' not in f.parts}
    expected = {v['path']:v for v in manifest['files']}
    assert set(actual) == set(expected) | {'PUBLICATION-MANIFEST.json'}, 'Unexpected or missing public file'
    for name,f in actual.items():
        assert f.suffix.lower() not in BLOCKED, f'Forbidden payload: {name}'
        assert not any(x in f.relative_to(ROOT).parts for x in ('.workbench','.jf2-workbench','references','generated')), name
        data=f.read_bytes()
        assert not data.startswith((b'MZ', b'\x7fELF', b'PS-X EXE', b'BPS1')), name
        if name in expected:
            assert hashlib.sha256(data).hexdigest()==expected[name]['sha256'], f'Changed: {name}'
        if f.suffix=='.py': ast.parse(data.decode('utf-8-sig'), filename=name)
        elif f.suffix=='.json': json.loads(data.decode('utf-8-sig'))
        elif f.suffix=='.toml': tomllib.loads(data.decode('utf-8-sig'))
        if f.suffix=='.md':
            text=data.decode('utf-8')
            for link in re.findall(r'\]\(([^)]+)\)', text)+re.findall(r'src="([^"]+)"', text):
                if re.match(r'^[a-z]+:',link) or link.startswith('#'): continue
                link=link.split('#',1)[0]
                if link: assert (f.parent/link).exists(), f'Broken local link in {name}: {link}'
    print(f'PASS: {len(actual)} source-preview files; hashes, formats, links and forbidden payload checks')

if __name__=='__main__': check()
