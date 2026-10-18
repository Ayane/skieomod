"""Background checks stay small and react immediately to a Steam revision."""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import URLError
from tools import skieo_install as desktop, skieo_loader as loader, skieo_updates as updates, custom_map as cli


class PeriodicUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        env = patch.dict(os.environ, {'SKIEOMOD_CONFIG_DIR': str(self.root / 'config')})
        env.start(); self.addCleanup(env.stop)
        self.library = self.root / 'steamapps'; self.library.mkdir()
        self.game = self.library / 'common/skieogame_demo'; self.game.mkdir(parents=True)
        self.config = {'version': 1, 'app_id': '5012760', 'steamapps_dir': str(self.library),
                       'game_dir': str(self.game), 'ue4ss_mods': str(self.root / 'mods')}
        desktop.save_config(self.config)
        self.revision('25808900')
        self.destination = self.root / 'mods' / loader.NAME
        self.files = {name: b'old' for name in loader.REQUIRED}
        for name, data in self.files.items():
            p = self.destination / name; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(data)
        self.installed = loader.manifest(self.files, '1.16.1', game_builds={'5012760': '25808900'})
        desktop.atomic_json(self.destination / loader.RECORD, self.installed)
        self.newer_cli = str(int(loader.VERSION.split('.')[0]) + 1) + '.0.0'
        self.record = loader.manifest({name: b'new' for name in loader.REQUIRED}, self.newer_cli,
                                      game_builds={'5012760': '25809999'})
        self.feed = {'format': 'skieomod-loader-update', 'version': 1, 'release': self.newer_cli,
                     'minimum_cli': self.newer_cli, 'url': loader.DOWNLOAD_BASE + 'CustomMap-Mod-' + self.newer_cli + '.zip',
                     'size': 1024, 'sha256': 'a' * 64, 'loader': self.record}

    def revision(self, build, directory='skieogame_demo'):
        (self.library / 'appmanifest_5012760.acf').write_text(
            '"AppState" { "appid" "5012760" "installdir" "' + directory + '" "buildid" "' + build + '" }')

    def response(self):
        response = io.BytesIO(json.dumps(self.feed).encode()); response.geturl = lambda: loader.UPDATE_URL
        return response

    def test_check_downloads_only_metadata_and_newer_cli_is_reported(self):
        before = {p: p.read_bytes() for p in self.destination.rglob('*') if p.is_file()}
        with patch.object(loader, 'urlopen', return_value=self.response()) as network:
            status = updates.check_now()
        self.assertFalse(status['failed']); self.assertEqual(network.call_count, 1)
        self.assertEqual(network.call_args.args[0].full_url, loader.UPDATE_URL)
        self.assertEqual(network.call_args.kwargs['timeout'], 5)
        self.assertEqual(before, {p: p.read_bytes() for p in self.destination.rglob('*') if p.is_file()})
        self.assertTrue(any('skieomod ' + self.newer_cli in s for s in updates.notices()))
        self.assertTrue(any('skieomod update' in s for s in updates.notices()))

    def test_recent_success_skips_check_but_game_revision_forces_it(self):
        with patch.object(loader, 'fetch_feed', return_value=self.feed) as network:
            first = updates.check_now(); updates.check_now()
            self.assertEqual(network.call_count, 1)
            self.assertFalse(updates.check_due(self.config, first, now=first['attempted'] + 3600))
            self.assertTrue(updates.check_due(self.config, first, now=first['attempted'] + updates.CHECK_INTERVAL))
            self.revision('25809999'); updates.check_now()
            self.assertEqual(network.call_count, 2)
        self.assertIn('25809999', updates.notices()[0])

    def test_offline_retry_is_throttled_and_last_success_is_preserved(self):
        with patch.object(loader, 'fetch_feed', return_value=self.feed): updates.check_now()
        with patch.object(loader, 'fetch_feed', side_effect=URLError('offline')) as network:
            status = updates.check_now(force=True); updates.check_now()
            self.assertEqual(network.call_count, 1)
        self.assertTrue(status['failed']); self.assertEqual(status['feed'], self.feed)
        self.assertTrue(updates.check_due(self.config, status, now=status['attempted'] + updates.RETRY_INTERVAL))

    def test_background_worker_is_detached_and_parallel_checks_are_deduplicated(self):
        with patch.object(updates.subprocess, 'Popen') as launch:
            self.assertIsNotNone(updates.start_check()); updates.start_check(force=True)
            self.assertEqual(launch.call_count, 1)
            self.assertTrue(launch.call_args.kwargs['start_new_session'])
            self.assertEqual(launch.call_args.kwargs['stdout'], updates.subprocess.DEVNULL)
        with patch.object(loader, 'fetch_feed', return_value=self.feed): updates.check_now(claimed=True)
        self.assertFalse((self.root / 'config/update-check.lock').exists())

    def test_failed_worker_launch_releases_lock_and_corrupt_cache_is_ignored(self):
        (self.root / 'config/update-status.json').write_text('{invalid')
        with patch.object(updates.subprocess, 'Popen', side_effect=OSError('cannot start')):
            self.assertIsNone(updates.start_check())
        self.assertFalse((self.root / 'config/update-check.lock').exists())
        self.assertEqual(updates.read_status(), {})

    def test_unrelated_or_missing_steam_manifest_does_not_check(self):
        self.revision('25808900', directory='another-game')
        with patch.object(loader, 'fetch_feed') as network, patch.object(updates.subprocess, 'Popen') as process:
            updates.check_now(force=True); updates.start_check(force=True)
            network.assert_not_called(); process.assert_not_called()
        self.assertEqual(updates.notices(), [])

    def test_online_cli_check_does_not_download_archive_or_write_files(self):
        with patch.object(loader, 'urlopen', return_value=self.response()) as network, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(['update', '--check']), 0)
        self.assertEqual(network.call_count, 1)
        self.assertEqual(loader.installed_record(self.destination), self.installed)
        self.assertFalse((self.root / 'config/update-status.json').exists())

    def test_tested_revisions_reject_invalid_release_metadata(self):
        for builds in ([], {'5012760': True}, {'bad-app': '25808900'}, {'5012760': 'NaN'}):
            with self.subTest(builds=builds), self.assertRaises(desktop.ManifestError):
                loader.validate_record({**self.record, 'game_builds': builds})


if __name__ == '__main__': unittest.main()
