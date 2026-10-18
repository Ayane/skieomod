import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools import custom_map as cli, skieo_install as desktop, skieo_uninstall as uninstall
from tools.custom_packages import ManifestError


class UninstallTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        env = patch.dict(os.environ, {
            'SKIEOMOD_CONFIG_DIR': str(self.root / 'config'),
            'XDG_DATA_HOME': str(self.root / 'desktop'),
            'XDG_CONFIG_HOME': str(self.root / 'xdg-config')})
        env.start()
        self.addCleanup(env.stop)
        platform = patch('sys.platform', 'linux')
        platform.start()
        self.addCleanup(platform.stop)
        self.game = self.root / 'game'
        binary = self.game / 'SkiResortSimulator/Binaries/Win64'
        (binary / 'ue4ss/Mods').mkdir(parents=True)
        (self.game / 'SkiResortSimulator/Content/Paks/~mods').mkdir(parents=True)
        (binary / 'dwmapi.dll').write_bytes(b'existing proxy')
        (binary / 'ue4ss/UE4SS.dll').write_bytes(b'existing UE4SS')
        self.config = {'version': 1, **desktop.game_paths(self.game)}
        desktop.save_config(self.config)
        self.location = Path(self.config['ue4ss_mods']) / desktop.LOADER_NAME
        (self.location / 'Scripts').mkdir(parents=True)
        (self.location / 'Scripts/main.lua').write_text('-- loader')
        (self.location / 'Scripts/my-script.lua').write_text('-- authored script')
        (self.location / 'enabled.txt').touch()
        self.maps = Path(self.config['maps_dir']) / 'author.map.skieomap'
        self.maps.write_bytes(b'authored map')
        self.mods_file = self.location.parent / 'mods.txt'
        self.mods_file.write_text('OtherMod : 1\nSkiEO-CustomMaps : 1\n; comment\n')
        (self.location.parent / 'OtherMod/Scripts').mkdir(parents=True)
        (self.location.parent / 'OtherMod/Scripts/main.lua').write_text('-- other mod')
        worker = patch.object(cli.updates, 'start_check', side_effect=AssertionError('uninstall must not start update checks'))
        worker.start()
        self.addCleanup(worker.stop)

    def invoke(self, *args):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(cli.main(['uninstall-self', *args]), 0)
        return output.getvalue()

    def snapshot(self):
        return {path.relative_to(self.root).as_posix(): path.read_bytes()
                for path in self.root.rglob('*') if path.is_file()}

    def test_mod_only_preserves_content_and_other_mods_and_is_repeatable(self):
        before = self.snapshot()
        with patch.object(uninstall, 'cli_command', side_effect=AssertionError('must keep CLI')):
            output = self.invoke('--mod-only')
            self.invoke('--mod-only')
        self.assertFalse(self.location.exists())
        backups = list((self.location.parent / '.skieomod-backups').glob('uninstall-*'))
        self.assertEqual(len(backups), 1)
        for name in ('Scripts/main.lua', 'Scripts/my-script.lua', 'enabled.txt'):
            self.assertEqual((backups[0] / desktop.LOADER_NAME / name).read_bytes(),
                             before[(self.location / name).relative_to(self.root).as_posix()])
        self.assertEqual((backups[0] / 'mods.txt').read_text(), 'OtherMod : 1\nSkiEO-CustomMaps : 1\n; comment\n')
        self.assertEqual(self.mods_file.read_text(), 'OtherMod : 1\n; comment\n')
        for name, data in before.items():
            path = self.root / name
            if self.location not in path.parents and path != self.mods_file:
                self.assertEqual(path.read_bytes(), data)
        self.assertIn('backed up', output)

    def test_default_removes_mod_then_runs_package_manager(self):
        command = ['/usr/bin/pipx', 'uninstall', 'skieo-custom-map']
        def run(argv, **kwargs):
            self.assertFalse(self.location.exists())
            self.assertEqual(self.maps.read_bytes(), b'authored map')
        with patch.object(uninstall, 'cli_command', return_value=(command, {'PIPX_HOME': '/isolated'})), \
             patch.object(uninstall.subprocess, 'run', side_effect=run) as execute:
            self.invoke()
        execute.assert_called_once_with(command, env={'PIPX_HOME': '/isolated'}, check=True)

    def test_check_has_no_writes_or_uninstaller_calls(self):
        self.protocol()
        before = self.snapshot()
        with patch.object(uninstall, 'cli_command', return_value=(['pipx', 'uninstall', uninstall.PACKAGE], None)), \
             patch.object(uninstall.subprocess, 'run', side_effect=AssertionError('check must not run commands')):
            output = self.invoke('--check')
        self.assertEqual(self.snapshot(), before)
        self.assertFalse((self.location.parent / '.skieomod-backups').exists())
        self.assertIn('Would remove Custom Map', output)
        self.assertIn('Would run:', output)
        self.assertIn('skieomod://', output)

    def test_cli_only_needs_no_game_or_valid_config(self):
        config = self.root / 'config/config.json'
        config.write_text('invalid json')
        before = self.snapshot()
        with patch.object(uninstall, 'cli_command', return_value=(['python', '-m', 'pip', 'uninstall', '--yes', uninstall.PACKAGE], None)), \
             patch.object(uninstall.subprocess, 'run') as run:
            self.invoke('--cli-only')
        run.assert_called_once()
        self.assertEqual(self.snapshot(), before)

    def test_manager_missing_fails_before_removing_mod(self):
        before = self.snapshot()
        with patch.object(uninstall, 'cli_command', side_effect=ManifestError('pipx is required')), \
             contextlib.redirect_stderr(io.StringIO()) as errors:
            self.assertEqual(cli.main(['uninstall-self']), 2)
        self.assertIn('pipx is required', errors.getvalue())
        self.assertEqual(self.snapshot(), before)

    def test_failed_package_removal_returns_error_and_keeps_mod_backup(self):
        with patch.object(uninstall, 'cli_command', return_value=(['pipx', 'uninstall', uninstall.PACKAGE], None)), \
             patch.object(uninstall.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, 'pipx')), \
             contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(['uninstall-self']), 2)
        self.assertFalse(self.location.exists())
        self.assertEqual(len(list((self.location.parent / '.skieomod-backups').glob('uninstall-*/SkiEO-CustomMaps/Scripts/main.lua'))), 1)

    def test_saved_and_detected_legacy_copies_are_removed(self):
        legacy = Path(self.config['maps_dir']) / desktop.LOADER_NAME
        (legacy / 'Scripts').mkdir(parents=True)
        (legacy / 'Scripts/main.lua.skieomod-disabled-1').write_text('-- disabled copy')
        extra = self.root / 'extra-mods' / desktop.LOADER_NAME
        (extra / 'Scripts').mkdir(parents=True)
        (extra / 'Scripts/main.lua').write_text('-- additional copy')
        settings = Path(self.config['ue4ss_dir']) / 'UE4SS-settings.ini'
        settings.write_text('[Overrides]\n+ModsFolderPaths = ' + str(extra.parent) + '\n')
        self.config['custom_map_locations'] = [str(legacy)]
        desktop.save_config(self.config)
        self.invoke('--mod-only', '--game-dir', str(self.game))
        for path in (self.location, legacy, extra):
            self.assertFalse(path.exists(), str(path))
        self.assertTrue(settings.is_file())

    def test_explicit_folder_limits_removal_to_that_installation(self):
        extra = self.root / 'extra-mods' / desktop.LOADER_NAME
        (extra / 'Scripts').mkdir(parents=True)
        (extra / 'Scripts/main.lua').write_text('-- additional copy')
        (self.root / 'config/config.json').write_text('invalid json')
        self.invoke('--mod-only', '--ue4ss-mods', str(extra.parent))
        self.assertFalse(extra.exists())
        self.assertTrue(self.location.is_dir())

    def test_another_game_does_not_remove_the_saved_installation(self):
        other = self.root / 'other-game'
        (other / 'SkiResortSimulator/Content/Paks').mkdir(parents=True)
        extra = other / 'SkiResortSimulator/Binaries/Win64/ue4ss/Mods' / desktop.LOADER_NAME
        (extra / 'Scripts').mkdir(parents=True)
        (extra / 'Scripts/main.lua').write_text('-- other game')
        before = (self.root / 'config/config.json').read_bytes()
        self.invoke('--mod-only', '--game-dir', str(other))
        self.assertFalse(extra.exists())
        self.assertTrue(self.location.is_dir())
        self.assertEqual((self.root / 'config/config.json').read_bytes(), before)

    def test_backup_failure_keeps_the_mod_and_enabled_entry(self):
        before = self.snapshot()
        with patch.object(Path, 'rename', side_effect=PermissionError('game is running')), \
             contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(['uninstall-self', '--mod-only']), 2)
        self.assertEqual(self.snapshot(), before)

    def test_missing_game_can_remove_remembered_mod(self):
        self.config['game_dir'] = str(self.root / 'missing-game')
        desktop.save_config(self.config)
        self.invoke('--mod-only')
        self.assertFalse(self.location.exists())

    @unittest.skipIf(sys.platform == 'win32', 'symlinks require special privileges on Windows')
    def test_symlinked_mod_is_unlinked_without_touching_target(self):
        target = self.root / 'mod-source'
        self.location.rename(target)
        self.location.symlink_to(target, target_is_directory=True)
        self.invoke('--mod-only')
        self.assertFalse(self.location.is_symlink())
        self.assertEqual((target / 'Scripts/my-script.lua').read_text(), '-- authored script')

    def protocol(self):
        entry = self.root / 'desktop/applications/skieomod.desktop'
        entry.parent.mkdir(parents=True)
        entry.write_text('[Desktop Entry]\nExec=' + desktop.desktop_quote(sys.executable) + ' -m custom_map uri %u\n')
        return entry

    def test_linux_protocol_cleanup_preserves_other_handlers(self):
        entry = self.protocol()
        config = self.root / 'xdg-config/mimeapps.list'
        config.parent.mkdir()
        config.write_text('[Default Applications]\nx-scheme-handler/skieomod=skieomod.desktop;other.desktop;\ntext/plain=editor.desktop;\n[Added Associations]\nx-scheme-handler/skieomod=skieomod.desktop;\n')
        with patch.object(uninstall, 'cli_command', return_value=None), patch('sys.platform', 'linux'), \
             patch.object(uninstall.shutil, 'which', return_value=None):
            self.invoke('--cli-only')
        self.assertFalse(entry.exists())
        self.assertEqual(config.read_text(), '[Default Applications]\nx-scheme-handler/skieomod=other.desktop;\ntext/plain=editor.desktop;\n[Added Associations]\n')

    def test_protocol_of_another_interpreter_is_preserved(self):
        entry = self.protocol()
        entry.write_text('[Desktop Entry]\nExec="/other/python" -m custom_map uri %u\n')
        with patch.object(uninstall, 'cli_command', return_value=None), patch('sys.platform', 'linux'):
            self.invoke('--cli-only')
        self.assertTrue(entry.is_file())

    def test_windows_protocol_cleanup_is_per_user(self):
        root = r'Software\Classes\skieomod'
        paths = [root, root + r'\shell', root + r'\shell\open', root + r'\shell\open\command']
        deleted = []
        class Key:
            def __init__(self, path): self.path = path
            def __enter__(self): return self
            def __exit__(self, *args): pass
        command = subprocess.list2cmdline([sys.executable, '-m', 'custom_map', 'uri']) + ' "%1"'
        registry = SimpleNamespace(HKEY_CURRENT_USER='HKCU',
            OpenKey=lambda hive, path: Key(path), QueryValueEx=lambda key, name: (command, 1),
            QueryInfoKey=lambda key: (int(key.path != paths[-1]), 0, 0),
            EnumKey=lambda key, i: paths[paths.index(key.path) + 1].rsplit('\\', 1)[-1],
            DeleteKey=lambda hive, path: deleted.append((hive, path)))
        with patch('sys.platform', 'win32'), patch.dict('sys.modules', {'winreg': registry}):
            uninstall.unregister_protocol(check=True)
            self.assertEqual(deleted, [])
            uninstall.unregister_protocol()
        self.assertEqual(deleted, [('HKCU', path) for path in reversed(paths)])


class PackageManagerTests(unittest.TestCase):
    def test_pipx_uses_current_environment_and_installation_suffix(self):
        with tempfile.TemporaryDirectory() as temporary:
            prefix = Path(temporary) / 'pipx/venvs/skieo-custom-map-test'
            prefix.mkdir(parents=True)
            (prefix / 'pipx_metadata.json').write_text(json.dumps({'main_package': {'package': 'skieo-custom-map', 'suffix': '-test'}}))
            launcher = Path(temporary) / 'custom-bin/skieomod-test'
            launcher.parent.mkdir()
            launcher.write_text('#!python')
            with patch.object(uninstall.metadata, 'distribution'), patch('sys.prefix', str(prefix)), \
                 patch('sys.argv', [str(launcher), 'uninstall-self']), \
                 patch.object(uninstall.shutil, 'which', return_value='/usr/bin/pipx'):
                command, env = uninstall.cli_command()
            self.assertEqual(command, ['/usr/bin/pipx', 'uninstall', 'skieo-custom-map-test'])
            self.assertEqual(env['PIPX_HOME'], str(prefix.parent.parent))
            self.assertEqual(env['PIPX_BIN_DIR'], str(launcher.parent))
            with patch.object(uninstall.metadata, 'distribution'), patch('sys.prefix', str(prefix)), \
                 patch.object(uninstall.shutil, 'which', return_value=None), self.assertRaisesRegex(ManifestError, 'pipx'):
                uninstall.cli_command()

    def test_pip_uses_current_interpreter_even_with_pipx_on_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(uninstall.metadata, 'distribution'), patch('sys.prefix', temporary), \
                 patch.object(uninstall.util, 'find_spec', return_value=object()), \
                 patch.object(uninstall.shutil, 'which', side_effect=AssertionError('not a pipx install')):
                command, env = uninstall.cli_command()
            self.assertEqual(command, [sys.executable, '-m', 'pip', 'uninstall', '--yes', 'skieo-custom-map'])
            self.assertIsNone(env)

    def test_source_checkout_has_no_package_to_remove(self):
        with patch.object(uninstall.metadata, 'distribution', side_effect=uninstall.metadata.PackageNotFoundError):
            self.assertIsNone(uninstall.cli_command())

    def test_build_metadata_does_not_count_as_an_installed_package(self):
        source = SimpleNamespace(read_text=lambda name: None)
        with patch.object(uninstall.metadata, 'distribution', return_value=source):
            self.assertIsNone(uninstall.cli_command())


if __name__ == '__main__':
    unittest.main()
