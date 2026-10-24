from __future__ import annotations
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.parse import urlencode
from urllib.error import HTTPError
import zipfile

from tools import custom_map as cli
from tools import skieo_install as desktop
from tools.custom_packages import ManifestError
from tools.custom_maps import inspect_archive


class InstallationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.env = patch.dict(os.environ, {'SKIEOMOD_CONFIG_DIR': str(self.root / 'config'), 'XDG_DATA_HOME': str(self.root / 'desktop'), 'XDG_CONFIG_HOME': str(self.root / 'xdg-config')})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.addCleanup(self.temporary.cleanup)

    def game(self, library='Steam', directory='skieogame_demo', identifier='5012760'):
        steam = self.root / library
        game = steam / 'steamapps/common' / directory
        (game / 'SkiResortSimulator/Content/Paks').mkdir(parents=True)
        (game / 'SkiResortSimulator/Binaries/Win64').mkdir(parents=True)
        (steam / 'steamapps' / ('appmanifest_' + identifier + '.acf')).write_text('"AppState" { "appid" "' + identifier + '" "installdir" "' + directory + '" }')
        return desktop.game_paths(game)

    def args(self, **values):
        return argparse.Namespace(game_dir=None, maps_dir=None, ue4ss_mods=None, app_id=None, **values)

    def test_secondary_steam_library_and_escaped_windows_paths(self):
        game = self.game('Other Library')
        primary = self.root / 'Steam'; (primary / 'steamapps').mkdir(parents=True)
        (primary / 'steamapps/libraryfolders.vdf').write_text('"libraryfolders" { "0" { "path" "' + str(primary) + '" } "1" { "path" "' + str(self.root / 'Other Library') + '" } }')
        self.assertEqual(desktop.detect_games([primary]), [game])
        vdf = self.root / 'windows.vdf'
        vdf.write_text(r'"libraryfolders" { "1" { "path" "D:\\Steam Library" } }')
        self.assertEqual(desktop.read_vdf(vdf)['libraryfolders']['1']['path'], 'D:\\Steam Library')

    def test_detection_and_remembered_paths_need_no_prompt(self):
        game = self.game()
        with patch.object(desktop, 'detect_games', return_value=[game]), patch('builtins.input') as question:
            config = desktop.configure(self.args(), desktop.PRIMARY_REPOSITORY)
            question.assert_not_called()
        self.assertEqual(config['maps_dir'], game['maps_dir'])
        with patch.object(desktop, 'detect_games', side_effect=AssertionError('must use saved paths')):
            self.assertEqual(desktop.configure(self.args(), desktop.PRIMARY_REPOSITORY)['game_dir'], game['game_dir'])
        self.assertEqual(json.loads((self.root / 'config/config.json').read_text())['ue4ss_mods'], game['ue4ss_mods'])

    def test_ambiguity_and_missing_game_ask_user(self):
        first, second = self.game(), self.game('Second', 'skieogame', '4493130')
        with patch('sys.stdin.isatty', return_value=True), patch('builtins.input', return_value='2') as question:
            self.assertEqual(desktop.choose_game([first, second]), second)
            question.assert_called_once()
        with patch('sys.stdin.isatty', return_value=True), patch('builtins.input', return_value=first['game_dir']):
            self.assertEqual(desktop.choose_game([]), first)

    def test_ue4ss_first_install_hash_and_existing_proxy_protection(self):
        game = self.game()
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('dwmapi.dll', b'proxy')
            archive.writestr('ue4ss/UE4SS.dll', b'loader')
        data = stream.getvalue()
        with patch.object(desktop, 'urlopen', return_value=io.BytesIO(data)), patch.object(desktop, 'UE4SS_SHA256', '0' * 64), self.assertRaisesRegex(ManifestError, 'SHA-256'):
            desktop.install_ue4ss(game)
        self.assertFalse((Path(game['binary_dir']) / 'dwmapi.dll').exists())
        with patch.object(desktop, 'urlopen', return_value=io.BytesIO(data)), patch.object(desktop, 'UE4SS_SHA256', hashlib.sha256(data).hexdigest()):
            desktop.install_ue4ss(game)
        self.assertEqual((Path(game['binary_dir']) / 'dwmapi.dll').read_bytes(), b'proxy')
        with patch.object(desktop, 'urlopen', side_effect=AssertionError('must reuse UE4SS')):
            desktop.install_ue4ss(game)
        (Path(game['ue4ss_mods']).parent / 'UE4SS.dll').unlink()
        with self.assertRaisesRegex(ManifestError, 'incomplete'):
            desktop.install_ue4ss(game)

    def test_known_leaking_ue4ss_upgrade_preserves_settings_and_other_mods(self):
        game = self.game()
        loader = Path(game['ue4ss_dir']); loader.mkdir(parents=True)
        dll = loader / 'UE4SS.dll'; dll.write_bytes(b'old leaking loader')
        (Path(game['binary_dir']) / 'dwmapi.dll').write_bytes(b'original proxy')
        settings = loader / 'UE4SS-settings.ini'; settings.write_text('user settings')
        other = loader / 'Mods/OtherMod/main.lua'; other.parent.mkdir(parents=True); other.write_text('user mod')
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            archive.writestr('dwmapi.dll', b'new proxy')
            archive.writestr('ue4ss/UE4SS.dll', b'fixed loader')
            archive.writestr('ue4ss/UE4SS-settings.ini', b'default settings')
        data = stream.getvalue()
        missing = HTTPError(desktop.UE4SS_URL, 404, 'not mirrored yet', None, None)
        with patch.object(desktop, 'UE4SS_LEAKING_DLL_SHA256', hashlib.sha256(dll.read_bytes()).hexdigest()), \
                patch.object(desktop, 'UE4SS_SHA256', hashlib.sha256(data).hexdigest()), \
                patch.object(desktop, 'urlopen', side_effect=[missing, io.BytesIO(data)]) as download:
            desktop.install_ue4ss(game)
            self.assertEqual(download.call_args.args[0], desktop.UE4SS_UPSTREAM_URL)
        self.assertEqual(dll.read_bytes(), b'fixed loader')
        self.assertEqual((loader / 'UE4SS.dll.1152-e3ba1016.bak').read_bytes(), b'old leaking loader')
        self.assertEqual(settings.read_text(), 'user settings')
        self.assertEqual(other.read_text(), 'user mod')
        self.assertEqual((Path(game['binary_dir']) / 'dwmapi.dll').read_bytes(), b'original proxy')

    def test_ue4ss_bad_upgrade_archive_leaves_existing_dll_untouched(self):
        game = self.game(); loader = Path(game['ue4ss_dir']); loader.mkdir(parents=True)
        dll = loader / 'UE4SS.dll'; dll.write_bytes(b'old leaking loader')
        (Path(game['binary_dir']) / 'dwmapi.dll').write_bytes(b'original proxy')
        with patch.object(desktop, 'UE4SS_LEAKING_DLL_SHA256', hashlib.sha256(dll.read_bytes()).hexdigest()), \
                patch.object(desktop, 'urlopen', return_value=io.BytesIO(b'wrong download')), \
                self.assertRaisesRegex(ManifestError, 'SHA-256'):
            desktop.install_ue4ss(game)
        self.assertEqual(dll.read_bytes(), b'old leaking loader')
        self.assertFalse((loader / 'UE4SS.dll.1152-e3ba1016.bak').exists())

    def test_loader_install_preserves_repositories_and_backs_up_changed_files(self):
        game = self.game()
        loader = Path(game['ue4ss_mods']).parent; loader.mkdir(parents=True)
        (loader / 'UE4SS.dll').write_bytes(b'existing')
        (Path(game['binary_dir']) / 'dwmapi.dll').write_bytes(b'existing')
        Path(game['ue4ss_mods']).mkdir()
        (Path(game['ue4ss_mods']) / 'mods.txt').write_text('OtherMod : 1\nSkiEO-CustomMaps : 0\n')
        location = desktop.install_loader(game)
        self.assertTrue((location / 'Scripts/launch.lua').is_file())
        self.assertTrue((location / 'enabled.txt').is_file())
        self.assertFalse(list(Path(game['maps_dir']).glob('*.skieomap')))
        self.assertFalse(list(location.rglob('*.skieomap')))
        self.assertTrue((location / 'Scripts/featured.lua').is_file())
        # A previously downloaded or authored map remains untouched by setup.
        sample = Path(game['maps_dir']) / 'community.veymont-0.6.1.skieomap'
        sample.write_bytes(b'local edits')
        sample_before = sample.read_bytes()
        (location / 'Scripts/repositories.json').write_text('{"custom":"preserved"}')
        (location / 'Scripts/main.lua').write_text('-- authored change')
        desktop.install_loader(game)
        self.assertEqual(sample.read_bytes(), sample_before)
        self.assertEqual((location / 'Scripts/repositories.json').read_text(), '{"custom":"preserved"}')
        self.assertEqual(next((location / '.skieomod-backups').rglob('main.lua')).read_text(), '-- authored change')
        self.assertIn('SkiEO-CustomMaps : 1', (Path(game['ue4ss_mods']) / 'mods.txt').read_text())

    def test_proton_override_preserves_other_values_and_is_idempotent(self):
        game = self.game()
        registry = Path(game['steamapps_dir']) / 'compatdata/5012760/pfx/user.reg'
        registry.parent.mkdir(parents=True)
        registry.write_text('WINE REGISTRY Version 2\n\n' + r'[Software\\Wine\\DllOverrides]' + '\n"dxgi"="native"\n"dwmapi"="builtin"\n\n[Other]\n"key"="value"\n')
        with patch('sys.platform', 'linux'):
            desktop.configure_proton(game)
            first = registry.read_bytes()
            desktop.configure_proton(game)
        self.assertEqual(first, registry.read_bytes())
        self.assertIn(b'"dwmapi"="native,builtin"', first)
        self.assertIn(b'"dxgi"="native"', first)
        self.assertIn(b'"key"="value"', first)
        self.assertEqual(len(list(registry.parent.glob('user.reg.skieomod-backup-*'))), 1)

    def test_protocol_registration_has_no_shell_and_uses_current_interpreter(self):
        with patch('sys.platform', 'linux'), patch.object(desktop.subprocess, 'run') as run, patch.object(desktop.shutil, 'which', return_value=None):
            run.return_value.stdout = 'skieomod.desktop\n'
            desktop.register_protocol()
        entry = (self.root / 'desktop/applications/skieomod.desktop').read_text()
        self.assertIn('-m custom_map uri %u', entry)
        self.assertIn('Terminal=false', entry)
        run.assert_any_call(['xdg-mime', 'default', 'skieomod.desktop', 'x-scheme-handler/skieomod'], check=True)
        self.assertTrue((self.root / 'xdg-config').is_dir())

    def test_windows_protocol_is_per_user_and_quotes_the_uri(self):
        writes = []
        class Key:
            def __init__(self, path): self.path = path
            def __enter__(self): return self
            def __exit__(self, *args): pass
        registry = SimpleNamespace(HKEY_CURRENT_USER='HKCU', REG_SZ=1,
            CreateKey=lambda hive, path: Key(hive + '\\' + path),
            SetValueEx=lambda key, name, reserved, kind, value: writes.append((key.path, name, value)))
        with patch('sys.platform', 'win32'), patch.dict('sys.modules', {'winreg': registry}):
            desktop.register_protocol()
        self.assertTrue(all(path.startswith('HKCU\\Software\\Classes\\skieomod') for path, _, _ in writes))
        command = writes[-1][2]
        self.assertIn('-m custom_map uri', command)
        self.assertTrue(command.endswith(' "%1"'))
        self.assertNotIn('cmd.exe', command)

    def test_custom_ue4ss_mods_folder_is_detected_from_settings(self):
        game = self.game()
        loader = Path(game['ue4ss_dir']); loader.mkdir(parents=True)
        (loader / 'UE4SS-settings.ini').write_text('[Overrides]\nModsFolderPath = ../Shared Mods\n')
        detected = desktop.game_paths(game['game_dir'])
        self.assertEqual(Path(detected['ue4ss_mods']), (loader / '../Shared Mods').resolve())
        (loader / 'UE4SS-settings.ini').write_text('[Overrides]\nModsFolderPath =\n\n; Additional directories\n[General]\n')
        self.assertEqual(Path(desktop.game_paths(game['game_dir'])['ue4ss_mods']), loader / 'Mods')

    def test_existing_duplicate_loaders_select_last_folder_and_disable_other_copy(self):
        game = self.game()
        loader = Path(game['ue4ss_dir']); loader.mkdir(parents=True)
        (loader / 'UE4SS.dll').write_bytes(b'existing')
        (Path(game['binary_dir']) / 'dwmapi.dll').write_bytes(b'existing')
        primary = loader / 'Mods/SkiEO-CustomMaps/Scripts'
        legacy = Path(game['maps_dir']) / 'SkiEO-CustomMaps/Scripts'
        for folder in [primary, legacy]:
            folder.mkdir(parents=True)
            (folder / 'main.lua').write_text('-- previous loader')
        (loader / 'UE4SS-settings.ini').write_text('[Overrides]\n+ModsFolderPaths = ../../../Content/Paks/~mods\n')
        detected = desktop.game_paths(game['game_dir'])
        self.assertEqual(Path(detected['ue4ss_mods']), Path(game['maps_dir']))
        desktop.install_loader(detected)
        self.assertTrue((legacy / 'launch.lua').is_file())
        self.assertFalse((primary / 'main.lua').exists())
        self.assertEqual(next(primary.glob('main.lua.skieomod-disabled-*')).read_text(), '-- previous loader')
        self.assertTrue((legacy / 'main.lua').exists())

    def test_protocol_parameters_reject_untrusted_repositories_and_injection(self):
        query = urlencode({'repository': desktop.PRIMARY_REPOSITORY, 'version': '1.2.3'})
        self.assertEqual(desktop.parse_protocol('skieomod://play/test.alpine?' + query), ('play', 'test.alpine', '1.2.3', desktop.PRIMARY_REPOSITORY))
        invalid = ['skieomod://shell/test.alpine', 'skieomod://install/../../file', 'skieomod://play/test.alpine?version=--help',
                   'skieomod://play/test.alpine?version=1.0.0&version=2.0.0', 'skieomod://play/test.alpine?maps-dir=/tmp',
                   'skieomod://play/test.alpine?repository=https://unknown.example', 'skieomod://play/test.alpine#evil',
                   'skieomod://play/test.alpine?repository=http://skieomod.emillon.fr']
        for uri in invalid:
            with self.subTest(uri=uri), self.assertRaises(ManifestError):
                desktop.parse_protocol(uri)

    def test_play_handoff_uses_exact_installed_map_then_opens_steam(self):
        game = self.game()
        package = Path(game['maps_dir']) / 'test.alpine-1.2.3.skieomap'
        package.parent.mkdir(); package.write_bytes(b'verified by the installer')
        with patch.object(desktop, 'launch_game') as launch:
            desktop.request_play(game, {'kind': 'map', 'id': 'test.alpine', 'version': '1.2.3'})
        launch.assert_called_once_with(game)
        path = Path(game['ue4ss_mods']) / desktop.LOADER_NAME / 'Scripts/launch-request.json'
        request = json.loads(path.read_text())
        self.assertEqual((path.parent / request['package_path']).resolve(), package)
        self.assertEqual(request['map_version'], '1.2.3')
        with self.assertRaises(ManifestError):
            desktop.request_play(game, {'kind': 'mod', 'id': 'test.mod', 'version': '1.0.0'})

    def test_cli_play_uses_workshop_id_and_existing_steam_session(self):
        game = self.game()
        with patch.object(desktop, 'configure', return_value=game), patch.object(cli.workshop, 'call', return_value={'message': 'ready'}) as call, patch('sys.stdout', io.StringIO()):
            self.assertEqual(cli.main(['play', '123456789']), 0)
        request = call.call_args.args[0]
        self.assertEqual(request['published_file_id'], '123456789')
        self.assertEqual(request['method'], 'play')
        self.assertTrue(request['include_required_items'])
        self.assertNotIn('repository', request)


if __name__ == '__main__':
    unittest.main()
