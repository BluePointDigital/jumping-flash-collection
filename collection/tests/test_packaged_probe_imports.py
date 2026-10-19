"""The shipped probe must import its helpers without the development checkout."""
import ast
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


class PackagedProbeImportsTests(unittest.TestCase):
    def test_local_probe_dependencies_import_from_packaged_tool_subset(self):
        collection=Path(__file__).resolve().parents[1]
        tree=ast.parse((collection/'tools/package.py').read_text(encoding='utf-8'))
        stage=next(node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name=='stage')
        loop=next(node for node in stage.body if isinstance(node,ast.For) and
            isinstance(node.target,ast.Name) and node.target.id=='filename')
        tools=ast.literal_eval(loop.iter)
        probe=ast.parse((collection/'tools/performance_probe.py').read_text(encoding='utf-8'))
        dependencies=sorted({node.module for node in ast.walk(probe) if isinstance(node,ast.ImportFrom)
            and node.module and (collection/'tools'/(node.module+'.py')).is_file()})
        with tempfile.TemporaryDirectory(prefix='collection probe imports ') as directory:
            target=Path(directory)
            for name in tools:shutil.copy2(collection/'tools'/name,target/name)
            shutil.copy2(collection.parent/'robbit-mon-dieu/tools/diagnostics.py',target/'runtime_diagnostics.py')
            script=('import importlib,sys; sys.path.insert(0,sys.argv[1]); '
                'mods='+repr(['performance_probe',*dependencies])+'; '
                '[importlib.import_module(name) for name in mods]')
            result=subprocess.run([sys.executable,'-I','-B','-c',script,str(target)],
                cwd=target,capture_output=True,text=True,timeout=20)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)


if __name__=='__main__':unittest.main()
