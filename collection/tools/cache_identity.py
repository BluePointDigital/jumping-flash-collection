"""Use the bundled compiler's canonical namespace instead of hardcoded tags."""
import importlib.util
from pathlib import Path
import shutil


def compiler_module(toolchain):
    script=Path(toolchain)/'compile_overlays.py'
    spec=importlib.util.spec_from_file_location('collection_cache_compiler',script)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def namespace(root,game):
    toolchain=Path(root)/'toolchain'
    compiler=compiler_module(toolchain)
    tag=compiler.cache_tag(str(toolchain/'include'),str(toolchain/'psxrecomp-game.exe'),str(Path(root)/game['config']))
    return Path(game['serial'])/'gcc'/compiler.cache_arch_abi()/tag


def seed_cache(root,game,data,allow_empty=False):
    relative=namespace(root,game)
    source=Path(root)/'data/games'/game['id']/'cache'/relative
    count=len(list(source.rglob('*.dll')))
    if not count and not allow_empty:
        raise ValueError(f'No compatible seed cache for {game["id"]}: {relative}. Prepare AOT or explicitly request a cold-cache experiment.')
    if count:shutil.copytree(source,Path(data)/'cache'/relative)
    return dict(namespace=relative.as_posix(),seed_dlls=count,state='shipped' if count else 'empty')
