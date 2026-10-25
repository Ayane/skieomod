"""Installer isolation, error handling, packaging and desktop launch behaviour."""
import contextlib
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import zipfile

from installers import bootstrap
from tools import build_installers

ROOT=Path(__file__).resolve().parents[1]


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name)/'User space É';self.root.mkdir()
        self.bin=self.root/'app bin';self.bin.mkdir()
        self.commands=[]

    def execute(self,command,*,capture=False):
        self.commands.append(command)
        if command[-3:]==['environment','--value','PIPX_BIN_DIR']:return str(self.bin)+'\n'
        if 'venv' in command:
            scripts=Path(command[-1])/('Scripts'if sys.platform=='win32'else'bin')
            scripts.mkdir(parents=True)
            for name in ['python.exe','pipx.exe']if sys.platform=='win32'else['python','pipx']:
                (scripts/name).write_text('test launcher')
        if 'install'in command and 'skieo-custom-map'in command:
            (self.bin/('skieomod.exe'if sys.platform=='win32'else'skieomod')).write_text('test executable')
        return ''if capture else None

    def test_existing_pipx_installs_for_selected_python_and_runs_setup_by_absolute_path(self):
        with patch.object(bootstrap.shutil,'which',return_value='existing-pipx'), \
             patch.object(bootstrap,'usable_pipx',return_value=True), \
             patch.object(bootstrap,'run',side_effect=self.execute):
            executable=bootstrap.install()
        self.assertEqual(self.commands[-1],[str(executable),'setup'])
        install=next(c for c in self.commands if 'skieo-custom-map'in c)
        self.assertEqual(install[install.index('--python')+1],sys.executable)
        self.assertIn('--force',install)
        self.assertEqual(install[install.index('--index-url')+1],bootstrap.INDEX)
        self.assertFalse(any('venv'in c for c in self.commands),'existing pipx was replaced')

    def test_missing_pipx_uses_an_owned_environment_and_exposes_its_launcher(self):
        with patch.dict(os.environ,{'XDG_DATA_HOME':str(self.root/'data'),'LOCALAPPDATA':str(self.root/'local')}), \
             patch.object(bootstrap.shutil,'which',return_value=None), \
             patch.object(bootstrap,'usable_pipx',return_value=False), \
             patch.object(bootstrap,'run',side_effect=self.execute):
            executable=bootstrap.install(tools_only=True)
        create=next(c for c in self.commands if 'venv'in c)
        self.assertTrue(Path(create[-1]).is_relative_to(self.root))
        self.assertTrue((self.bin/('pipx.exe'if sys.platform=='win32'else'pipx')).exists())
        self.assertNotIn([str(executable),'setup'],self.commands)
        self.assertFalse(any('--break-system-packages'in c for c in self.commands))
        for command in self.commands:
            if 'pip'in command:self.assertTrue(Path(command[0]).is_relative_to(self.root))

    def test_failed_tools_installation_does_not_start_game_setup(self):
        def fail(command,**kw):
            if 'skieo-custom-map'in command:raise subprocess.CalledProcessError(1,command)
            return self.execute(command,**kw)
        with patch.object(bootstrap,'pipx_command',return_value=['pipx']), \
             patch.object(bootstrap,'run',side_effect=fail), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(bootstrap.main([]),1)
        self.assertFalse(any('setup'in c for c in self.commands))

    def test_old_or_broken_pipx_is_not_accepted(self):
        for version,code,expected in [('1.8.0',0,True),('0.16.4',0,False),('',1,False)]:
            with patch.object(bootstrap.subprocess,'run',return_value=subprocess.CompletedProcess([],code,version)):
                self.assertEqual(bootstrap.usable_pipx(['pipx']),expected)

    def test_launchers_are_self_contained_reproducible_and_preserve_unix_modes(self):
        output=build_installers.build(self.root/'download')
        expected=ROOT/'repository/web/public/install'
        for name in ['Install-SkiEO-Windows.cmd','Install-SkiEO-Linux.sh','Install-SkiEO-Linux.zip']:
            self.assertEqual((output/name).read_bytes(),(expected/name).read_bytes(),name)
        with zipfile.ZipFile(output/'Install-SkiEO-Linux.zip')as archive:
            for name in ['Install-SkiEO-Linux.sh','Install-SkiEO.desktop']:
                info=archive.getinfo(name)
                self.assertEqual(info.create_system,3)
                self.assertEqual((info.external_attr>>16)&0o111,0o111)
        script=(output/'Install-SkiEO-Linux.sh').read_bytes()
        self.assertNotIn(b'\r\n',script)
        if shutil.which('bash'):subprocess.run(['bash','-n',str(output/'Install-SkiEO-Linux.sh')],check=True)

    @unittest.skipUnless(sys.platform.startswith('linux'),'Linux desktop launch')
    def test_desktop_launcher_handles_spaces_quotes_and_shell_characters(self):
        try:
            from gi.repository import Gio
        except ImportError:self.skipTest('GIO is unavailable')
        folder=self.root/'spaces "quotes" $dollar';folder.mkdir()
        (folder/'Install-SkiEO-Linux.sh').write_text('#!/bin/bash\nprintf ok > "$(dirname "$0")/result"\n')
        desktop=folder/'Install-SkiEO.desktop'
        desktop.write_text((ROOT/'installers/Install-SkiEO.desktop').read_text().replace('Terminal=true','Terminal=false'))
        app=Gio.DesktopAppInfo.new_from_filename(str(desktop))
        self.assertIsNotNone(app)
        self.assertTrue(app.launch([],None))
        for _ in range(100):
            if(folder/'result').exists():break
            time.sleep(.01)
        self.assertEqual((folder/'result').read_text(),'ok')


if __name__=='__main__':unittest.main()
