"""Add native-runtime captures to the private collection, retaining provenance."""
from pathlib import Path
import datetime
import json
import shutil
import tomllib
from import_game import sha

ROOT = Path(__file__).resolve().parents[1]


def stage():
    captures = {
        'jf1': ROOT/'.workbench/headless/jf1-no-defer/smoke.png',
        'jf2': ROOT/'.workbench/relocation-smoke/jf2/smoke.png',
        'robbit': ROOT/'.workbench/relocation-smoke/robbit/smoke.png',
    }
    catalog = tomllib.loads((ROOT/'catalog.toml').read_text(encoding='utf-8'))
    for game in catalog['games']:
        source = captures[game['id']]
        if not source.is_file():
            continue
        home = ROOT/'dist/data/games'/game['id']/'gallery'
        home.mkdir(parents=True, exist_ok=True)
        target = home/'02-native-software-preview.png'
        shutil.copy2(source, target)
        if sha(source) != sha(target):
            raise ValueError('Gallery capture copy verification failed')
        receipt = dict(schema=1, game=game['id'], imported_disc_sha256=game['disc_sha256'],
                       image=target.name, image_sha256=sha(target),
                       source='Native runtime screenshot_file diagnostic command',
                       renderer='software', graphical_qualification=False,
                       raw_video_pixels=True, display_aspect='4:3',
                       captured_from_imported_game=True,
                       prepared_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
        (home/'capture-receipt.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
        print(f'Gallery capture verified: {game["id"]}')


if __name__ == '__main__':
    stage()
