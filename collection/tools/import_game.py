"""Verified transactional game/BIOS imports using bundled stdlib-only Python."""
from pathlib import Path
import argparse
import datetime
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import tomllib
import zipfile

def sha(path, algorithm='sha256'):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, algorithm).hexdigest()

def game_from_catalog(root, identity):
    document=tomllib.loads((root/'catalog.toml').read_text(encoding='utf-8'))
    if document.get('schema')!=1:
        raise ValueError('Unsupported catalog')
    games=[g for g in document['games'] if g['id']==identity]
    if len(games)!=1 or identity not in ('jf1','jf2','robbit'):
        raise ValueError('Unknown or duplicate game')
    return games[0]

def raw_disc(source, temporary, root):
    source=source.resolve()
    if source.suffix.lower()=='.chd':
        sys.path.insert(0,str(root/'tools'))
        from psx_chd import ChdDisc,LibChdr,extract
        with ChdDisc(source,LibChdr(root/'tools/libchdr.dll')) as disc:
            cue=extract(disc,temporary,'source.cue',layout='single')
        source=cue
    if source.suffix.lower()=='.cue':
        cue=source.read_text(encoding='utf-8-sig')
        files=re.findall(r'^\s*FILE\s+"([^"]+)"\s+BINARY\s*$',cue,re.M|re.I)
        tracks=re.findall(r'^\s*TRACK\s+\d+\s+(\S+)',cue,re.M|re.I)
        if len(files)!=1 or [track.upper() for track in tracks]!=['MODE2/2352'] or not re.search(r'INDEX\s+01\s+00:00:00',cue,re.I):
            raise ValueError('This collection currently supports the verified single-track MODE2/2352 layout')
        name=Path(files[0])
        if name.is_absolute() or '..' in name.parts:
            raise ValueError('CUE file references must stay alongside the selected disc')
        source=source.parent/name
    if source.suffix.lower()!='.bin' or not source.is_file():
        raise ValueError('Select a supported BIN/CUE or CHD disc')
    if source.stat().st_size%2352:
        raise ValueError('Disc size is not a complete sequence of raw sectors')
    return source

def receipt(root,game):
    path=root/'data/games'/game['id']/'import-receipt.json'
    old=json.loads(path.read_text()) if path.exists() else {'schema':1,'game':game['id']}
    return path,old

def commit_folder(staged,destination):
    """Replace only one imported component; rollback a failed replacement."""
    destination.parent.mkdir(parents=True,exist_ok=True)
    backup=destination.with_name(destination.name+'.previous')
    if backup.exists():
        # A previous import remains recoverable; never overwrite its backup.
        backup=destination.with_name(destination.name+'.previous-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    moved=False
    try:
        if destination.exists():
            destination.rename(backup);moved=True
        staged.rename(destination)
    except BaseException:
        if moved and not destination.exists():backup.rename(destination)
        raise

def update_receipt(root,game,component,info):
    path,document=receipt(root,game)
    document[component]=info
    document['updated_utc']=datetime.datetime.now(datetime.timezone.utc).isoformat()
    temporary=path.with_suffix('.tmp');temporary.write_text(json.dumps(document,indent=2),encoding='utf-8');os.replace(temporary,path)

def import_disc(root,game,source):
    home=root/'data/games'/game['id'];home.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='disc-import-',dir=home) as folder:
        staging=Path(folder);raw=raw_disc(source,staging,root)
        expected=game['disc_sha256'];source_hash=sha(raw)
        required=raw.stat().st_size*2+64*1024*1024
        if shutil.disk_usage(home).free<required:
            raise ValueError(f'Not enough space to prepare the disc safely; need {required//1024//1024} MiB free')
        ready=staging/'ready';ready.mkdir()
        if source_hash==expected:
            shutil.copy2(raw,ready/'game.bin');patched=False
        elif game['id']=='robbit' and sha(raw,'sha1')==game['original_disc_sha1']:
            sys.path.insert(0,str(root/'tools'))
            from bps import apply_bps
            patch=root/'tools/Robbit-English-v0.4.bps'
            if sha(patch)!=game['translation_patch_sha256']:
                raise ValueError('English patch identity does not match the collection catalog')
            (ready/'game.bin').write_bytes(apply_bps(raw.read_bytes(),patch.read_bytes()));patched=True
        else:
            raise ValueError(f'Wrong disc for {game["name"]}: SHA256 {source_hash}')
        output_hash=sha(ready/'game.bin')
        if output_hash!=expected:raise ValueError('Prepared disc verification failed')
        (ready/'game.cue').write_text('FILE "game.bin" BINARY\n  TRACK 01 MODE2/2352\n    INDEX 01 00:00:00\n',encoding='ascii')
        commit_folder(ready,home/'disc')
        update_receipt(root,game,'disc',dict(sha256=output_hash,source_sha256=source_hash,english_patch_applied=patched,bytes=(home/'disc/game.bin').stat().st_size))
        if game['id']=='robbit':
            update_receipt(root,game,'translation',dict(author='washingtonxan',patch_sha256=game['translation_patch_sha256'],
                original_disc_sha1=game['original_disc_sha1'],translated_disc_sha256=expected,applied_in_this_import=patched))
    print(f'Verified and imported {game["name"]} disc')

def import_bios(root,game,source):
    expected=game['bios_sha256'];payload=None
    if source.suffix.lower()=='.zip':
        with zipfile.ZipFile(source) as archive:
            for member in archive.infolist():
                if member.file_size==524288:
                    data=archive.read(member)
                    if hashlib.sha256(data).hexdigest()==expected:payload=data;break
    else:
        if source.stat().st_size==524288:
            data=source.read_bytes()
            if hashlib.sha256(data).hexdigest()==expected:payload=data
    if payload is None:raise ValueError(f'Wrong BIOS for {game["name"]}; expected SHA256 {expected}')
    home=root/'data/games'/game['id'];home.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='bios-import-',dir=home) as folder:
        staged=Path(folder)/'ready';staged.mkdir()
        basename=Path(game['bios']).name
        (staged/basename).write_bytes(payload)
        if sha(staged/basename)!=expected:raise ValueError('BIOS write verification failed')
        commit_folder(staged,home/'bios')
        update_receipt(root,game,'bios',dict(sha256=expected,bytes=len(payload)))
    print(f'Verified and imported {game["name"]} BIOS')

def verify(root,game):
    path,document=receipt(root,game)
    if not path.exists():raise ValueError('Import receipt missing')
    disc=root/game['disc']
    raw=raw_disc(disc,disc.parent,root)
    if sha(raw)!=game['disc_sha256']:raise ValueError('Disc changed since import')
    if sha(root/game['bios'])!=game['bios_sha256']:raise ValueError('BIOS changed since import')
    if document.get('disc',{}).get('sha256')!=game['disc_sha256'] or document.get('bios',{}).get('sha256')!=game['bios_sha256']:
        raise ValueError('Incomplete import receipt')
    print(f'PASS: {game["name"]} imported disc and BIOS verified')

def import_card(root,game,source,slot):
    if slot not in (1,2):raise ValueError('Choose memory card slot 1 or 2')
    if source.stat().st_size!=131072 or source.read_bytes()[:2]!=b'MC':
        raise ValueError('Select a 128 KiB raw PlayStation memory card (.mcd/.mcr); runtime states cannot be imported as cards')
    expected=sha(source);home=root/'data/games'/game['id'];home.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='card-import-',dir=home) as folder:
        staged=Path(folder)/'card.mcd';shutil.copy2(source,staged)
        if sha(staged)!=expected or sha(source)!=expected:raise ValueError('Memory card changed during copying; close the standalone game and try again')
        destination=home/'saves'/f'card{slot}.mcd';destination.parent.mkdir(parents=True,exist_ok=True)
        backup=destination.with_name(destination.name+'.previous-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
        moved=False
        try:
            if destination.exists():destination.rename(backup);moved=True
            staged.rename(destination)
        except BaseException:
            if moved and not destination.exists():backup.rename(destination)
            raise
        update_receipt(root,game,f'card{slot}',dict(sha256=expected,bytes=131072,previous_card_preserved=moved))
    print(f'Verified and copied memory card {slot} for {game["name"]}')

def set_preference(text,section,key,value):
    rendered=('true' if value else 'false') if isinstance(value,bool) else json.dumps(value,ensure_ascii=False)
    start,end=0,len(text)
    if section:
        header=re.search(r'(?m)^\['+re.escape(section)+r'\][ \t]*(?:#.*)?$',text)
        if not header:
            return text.rstrip()+'\n\n['+section+']\n'+key+' = '+rendered+'\n'
        start=header.end();following=re.search(r'(?m)^\[',text[start:])
        if following:end=start+following.start()
    block=text[start:end];pattern=r'(?m)^[ \t]*'+re.escape(key)+r'[ \t]*=.*$'
    line=key+' = '+rendered
    block=re.sub(pattern,lambda _:line,block,count=1) if re.search(pattern,block) else block.rstrip()+'\n'+line+'\n'
    return text[:start]+block+text[end:]

def import_preferences(root,game,source):
    if source.stat().st_size>256*1024:raise ValueError('Select a runtime settings.toml smaller than 256 KiB')
    payload=source.read_bytes();expected=hashlib.sha256(payload).hexdigest()
    original=tomllib.loads(payload.decode('utf-8-sig'))
    home=root/'data/games'/game['id'];home.mkdir(parents=True,exist_ok=True)
    settings=home/'settings.toml';host=home/'host-input.toml'
    if source.resolve() in (settings.resolve(),host.resolve()):raise ValueError('Choose the standalone source preferences; the collection already owns this destination file')
    text=settings.read_text(encoding='utf-8') if settings.exists() else ''
    tomllib.loads(text)  # Never overwrite a broken existing preferences file.
    controls=host.read_text(encoding='utf-8') if host.exists() else (
        'modern = 1\ndeadzone = 18\nsensitivity = 100\ninvert_y = 0\njump = 0\nfire = 37\nsecondary = 36\nspecial = 3\n')
    tomllib.loads(controls)
    copied=[];skipped=[]
    for section,entries in original.items():
        if not isinstance(entries,dict):continue
        for key,value in entries.items():
            valid=False
            if section=='desktop':
                if key=='control_style':valid=value in ('modern','classic','authentic')
                if key=='mouse_sensitivity':valid=type(value) is int and 10<=value<=300
                if key in ('invert_y','muted','integer_scaling'):valid=type(value) is bool
                if key=='audio_volume':valid=type(value) is int and 0<=value<=100
            if section=='video':
                if key=='renderer':valid=value in ('opengl','software')
                if key=='internal_resolution':
                    if isinstance(value,str):
                        value=value.lower()
                        if value.isdecimal():value=int(value)
                        elif value in ('480p','2160p'):value=int(value[:-1])
                    valid=(type(value) is int and (value in (-1,1) or 2<=value<=8640)) or value in ('native','720p','1080p','1440p','4k','5k','8k','display')
                if key=='window_width':valid=type(value) is int and 640<=value<=3840
                if key=='fullscreen':valid=type(value) in (int,bool) and value in (0,1,2)
                if key=='aspect_ratio':valid=value=='4:3'
            if not valid:skipped.append(section+'.'+key);continue
            if section=='desktop' and key=='control_style' and value=='authentic':value='classic'
            text=set_preference(text,section,key,value);copied.append(section+'.'+key)
            if section=='desktop':
                if key=='control_style':controls=set_preference(controls,None,'modern',int(value=='modern'))
                if key=='mouse_sensitivity':controls=set_preference(controls,None,'sensitivity',value)
                if key=='invert_y':controls=set_preference(controls,None,'invert_y',int(value))
    if not copied:raise ValueError('No compatible controls, audio or display preferences found in this file')
    tomllib.loads(text);tomllib.loads(controls)
    if sha(source)!=expected:raise ValueError('Source preferences changed while reading; close the standalone game and retry')
    required=64*1024+len(text.encode())+len(controls.encode())+sum(p.stat().st_size for p in (settings,host) if p.exists())
    if shutil.disk_usage(home).free<required:raise ValueError('Not enough space to copy preferences and preserve backups')
    timestamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backups={};committed=[]
    with tempfile.TemporaryDirectory(prefix='preferences-import-',dir=home) as folder:
        try:
            for destination,content in ((settings,text),(host,controls)):
                staged=Path(folder)/destination.name;staged.write_text(content,encoding='utf-8')
                digest=sha(staged)
                if destination.exists():
                    backup=destination.with_name(destination.name+'.previous-'+timestamp);shutil.copy2(destination,backup)
                    if sha(backup)!=sha(destination):raise ValueError('Preferences backup verification failed')
                    backups[destination]=backup
                os.replace(staged,destination);committed.append(destination)
                if sha(destination)!=digest:raise ValueError('Preferences copy verification failed')
            update_receipt(root,game,'preferences',dict(source_sha256=expected,settings_sha256=sha(settings),
                host_input_sha256=sha(host),copied=copied,skipped=skipped,
                backups={p.name:b.name for p,b in backups.items()},originals_preserved=True))
        except BaseException:
            for destination in reversed(committed):
                if destination in backups:shutil.copy2(backups[destination],destination)
                else:destination.unlink()
            raise
    print(f'Copied {len(copied)} compatible preferences for {game["name"]}; skipped {len(skipped)} unsupported fields; backups retained')

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,required=True);parser.add_argument('--game',required=True)
    group=parser.add_mutually_exclusive_group(required=True);group.add_argument('--disc',type=Path);group.add_argument('--bios',type=Path);group.add_argument('--card',type=Path);group.add_argument('--preferences',type=Path);group.add_argument('--verify',action='store_true')
    parser.add_argument('--slot',type=int,choices=(1,2),default=1)
    args=parser.parse_args();root=args.root.resolve();game=game_from_catalog(root,args.game)
    if args.verify:verify(root,game)
    elif args.disc:import_disc(root,game,args.disc)
    elif args.card:import_card(root,game,args.card,args.slot)
    elif args.preferences:import_preferences(root,game,args.preferences)
    else:import_bios(root,game,args.bios)

if __name__=='__main__':
    try:main()
    except Exception as error:print(f'Import failed: {error}',file=sys.stderr);raise SystemExit(1)
