"""Exercise real import/rollback boundaries without game data or BIOS dumps."""
from pathlib import Path
import hashlib
import json
import sys
import tempfile
import unittest
from unittest import mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from import_game import import_disc,import_bios,import_card,import_preferences,commit_folder,verify
import tomllib

class Imports(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.disc=self.root/'source.bin';self.disc.write_bytes(bytes(range(256))*9+bytes(48))
        self.bios=self.root/'source.rom';self.bios.write_bytes(b'B'*524288)
        self.game=dict(id='jf1',name='Fixture',disc_sha256=hashlib.sha256(self.disc.read_bytes()).hexdigest(),
                      bios_sha256=hashlib.sha256(self.bios.read_bytes()).hexdigest(),disc='data/games/jf1/disc/game.cue',bios='data/games/jf1/bios/test.bin')
    def tearDown(self):self.temp.cleanup()
    def test_roundtrip_and_source_preservation(self):
        original=self.disc.read_bytes();import_disc(self.root,self.game,self.disc);import_bios(self.root,self.game,self.bios)
        verify(self.root,self.game);self.assertEqual(original,self.disc.read_bytes())
        self.assertEqual((self.root/'data/games/jf1/disc/game.bin').read_bytes(),original)
    def test_wrong_disc_preserves_installed_component(self):
        import_disc(self.root,self.game,self.disc);wrong=self.root/'wrong.bin';wrong.write_bytes(b'X'*2352)
        with self.assertRaisesRegex(ValueError,'Wrong disc'):import_disc(self.root,self.game,wrong)
        self.assertEqual((self.root/'data/games/jf1/disc/game.bin').read_bytes(),self.disc.read_bytes())
    def test_wrong_bios_does_not_create_component(self):
        wrong=self.root/'wrong.rom';wrong.write_bytes(b'X'*524288)
        with self.assertRaisesRegex(ValueError,'Wrong BIOS'):import_bios(self.root,self.game,wrong)
        self.assertFalse((self.root/'data/games/jf1/bios').exists())
    def test_replacement_retains_previous(self):
        import_disc(self.root,self.game,self.disc);import_disc(self.root,self.game,self.disc)
        self.assertTrue((self.root/'data/games/jf1/disc.previous/game.bin').exists())
    def test_low_space_preserves_existing(self):
        with mock.patch('import_game.shutil.disk_usage',return_value=shutil_usage(1)):
            with self.assertRaisesRegex(ValueError,'Not enough space'):import_disc(self.root,self.game,self.disc)
        self.assertFalse((self.root/'data/games/jf1/disc').exists())
    def test_rename_failure_rolls_back(self):
        dest=self.root/'installed';dest.mkdir();(dest/'good').write_text('original')
        staged=self.root/'staged';staged.mkdir();(staged/'new').write_text('replacement')
        rename=Path.rename
        def failing(path,target):
            if path==staged:raise OSError('Simulated interruption')
            return rename(path,target)
        with mock.patch.object(Path,'rename',failing):
            with self.assertRaisesRegex(OSError,'Simulated'):commit_folder(staged,dest)
        self.assertEqual((dest/'good').read_text(),'original')
    def test_memory_card_copy_keeps_source_and_previous(self):
        card=self.root/'standalone.mcd';payload=b'MC'+bytes(131070);card.write_bytes(payload)
        import_card(self.root,self.game,card,1)
        card.write_bytes(b'MC'+b'X'*131070);import_card(self.root,self.game,card,1)
        installed=self.root/'data/games/jf1/saves/card1.mcd'
        self.assertEqual(installed.read_bytes(),card.read_bytes())
        self.assertEqual(list(installed.parent.glob('card1.mcd.previous-*'))[0].read_bytes(),payload)
    def test_runtime_state_cannot_replace_memory_card(self):
        state=self.root/'state.bin';state.write_bytes(b'STATE'+bytes(131067))
        with self.assertRaisesRegex(ValueError,'runtime states'):import_card(self.root,self.game,state,1)
        self.assertFalse((self.root/'data/games/jf1/saves/card1.mcd').exists())
    def test_card_commit_failure_restores_previous(self):
        card=self.root/'standalone.mcd';card.write_bytes(b'MC'+bytes(131070));import_card(self.root,self.game,card,2)
        rename=Path.rename
        def failing(path,target):
            if path.name=='card.mcd':raise OSError('Simulated card commit failure')
            return rename(path,target)
        with mock.patch.object(Path,'rename',failing):
            with self.assertRaisesRegex(OSError,'Simulated'):import_card(self.root,self.game,card,2)
        self.assertEqual((self.root/'data/games/jf1/saves/card2.mcd').read_bytes(),card.read_bytes())
    def test_preferences_copy_filters_paths_and_unqualified_graphics(self):
        home=self.root/'data/games/jf1';home.mkdir(parents=True)
        existing='[video]\naspect_ratio = "4:3"\nframe_generation = false\n[paths]\nbios = "collection-bios"\n'
        (home/'settings.toml').write_text(existing)
        source=self.root/'standalone-settings.toml'
        original='[desktop]\ncontrol_style = "classic"\nmouse_sensitivity = 140\ninvert_y = true\n[video]\ninternal_resolution = "1080p"\naspect_ratio = "16:9"\nframe_generation = true\n[paths]\nbios = "standalone-bios"\n'
        source.write_text(original);import_preferences(self.root,self.game,source)
        result=tomllib.loads((home/'settings.toml').read_text());controls=tomllib.loads((home/'host-input.toml').read_text())
        self.assertEqual(source.read_text(),original);self.assertEqual(result['paths']['bios'],'collection-bios')
        self.assertEqual(result['video']['aspect_ratio'],'4:3');self.assertFalse(result['video']['frame_generation'])
        self.assertEqual(result['video']['internal_resolution'],'1080p')
        self.assertEqual(controls['modern'],0);self.assertEqual(controls['sensitivity'],140);self.assertEqual(controls['invert_y'],1)
        self.assertEqual(list(home.glob('settings.toml.previous-*'))[0].read_text(),existing)
    def test_preferences_second_commit_failure_restores_both_files(self):
        home=self.root/'data/games/jf1';home.mkdir(parents=True)
        old='[desktop]\nmouse_sensitivity = 100\n';(home/'settings.toml').write_text(old)
        old_host='modern = 1\nsensitivity = 100\n';(home/'host-input.toml').write_text(old_host)
        source=self.root/'standalone.toml';source.write_text('[desktop]\nmouse_sensitivity = 200\n')
        import os
        replace=os.replace
        def failing(staged,destination):
            if Path(destination).name=='host-input.toml':raise OSError('Interrupted preference commit')
            return replace(staged,destination)
        with mock.patch('import_game.os.replace',side_effect=failing):
            with self.assertRaisesRegex(OSError,'Interrupted'):import_preferences(self.root,self.game,source)
        self.assertEqual((home/'settings.toml').read_text(),old);self.assertEqual((home/'host-input.toml').read_text(),old_host)
    def test_preferences_without_compatible_values_preserve_destination(self):
        source=self.root/'wrong.toml';source.write_text('[paths]\nbios = "other"\n')
        with self.assertRaisesRegex(ValueError,'No compatible'):import_preferences(self.root,self.game,source)
        self.assertFalse((self.root/'data/games/jf1/settings.toml').exists())

def shutil_usage(free):
    import shutil
    return shutil._ntuple_diskusage(100,99,free)

if __name__=='__main__':unittest.main()
