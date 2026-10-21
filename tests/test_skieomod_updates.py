import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from urllib.error import URLError

from tools import custom_map as cli, skieo_install as desktop, skieo_loader as loader, skieo_project as projects
from tools.custom_packages import ManifestError


class LoaderUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        env = patch.dict(os.environ, {'SKIEOMOD_CONFIG_DIR': str(self.root / 'config')})
        env.start()
        self.addCleanup(env.stop)
        self.protocol = patch.object(desktop, 'register_protocol').start()
        self.addCleanup(patch.stopall)
        self.destination = self.root / 'Mods' / loader.NAME
        self.destination.mkdir(parents=True)
        self.files = {name: ('old ' + name).encode() for name in loader.REQUIRED}
        self.files['Scripts/obsolete.lua'] = b'old obsolete module'
        for name, data in self.files.items():
            path = self.destination / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        self.record = loader.manifest(self.files, '1.4.0')
        desktop.atomic_json(self.destination / loader.RECORD, self.record)
        self.config = {'version': 1, 'ue4ss_mods': str(self.destination.parent),
                       'workshop_app_id': '5012760', 'workshop_client': '/my/client',
                       'repositories': ['https://my-old-repository.example']}
        desktop.save_config(self.config)

    def release(self, version='1.5.0'):
        files = {name: ('new ' + name).encode() for name in loader.REQUIRED}
        files['Scripts/added.lua'] = b'new module'
        return files, loader.manifest(files, version)

    def archive(self, files=None, record=None):
        if files is None: files, record = self.release()
        path = self.root / 'CustomMap-Mod.zip'
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr(loader.NAME + '/' + loader.RECORD, json.dumps(record))
            for name, data in files.items():
                archive.writestr(loader.NAME + '/' + name, data)
        return path

    def snapshot(self):
        return {path.relative_to(self.root).as_posix(): path.read_bytes()
                for path in self.root.rglob('*') if path.is_file()}

    def test_cli_archive_update_preserves_settings_maps_and_user_changes(self):
        config_before = (self.root / 'config/config.json').read_bytes()
        states = {'Scripts/workshop.json': '{"custom":"paths"}',
                  'Scripts/repositories.json': '{"user":"repository"}',
                  'Scripts/skieomod-installed.json': '{"user":"maps"}',
                  'Scripts/launch-request.json': '{"request":"preserve"}',
                  'Scripts/my-local-module.lua': '-- authored module', 'enabled.txt': ''}
        for name, text in states.items(): (self.destination / name).write_text(text)
        maps = self.root / 'maps/author.map.skieomap'
        maps.parent.mkdir()
        maps.write_bytes(b'local map')
        (self.destination.parent / 'OtherMod').mkdir()
        (self.destination.parent / 'OtherMod/custom.lua').write_text('-- another mod')
        with patch.object(desktop, 'install_ue4ss', side_effect=AssertionError('must not reinstall UE4SS')), \
             patch.object(cli.workshop, 'call', side_effect=AssertionError('must not use Workshop')), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(cli.main(['update', '--archive', str(self.archive())]), 0)
        self.protocol.assert_called_once_with()
        self.assertIn('1.4.0 -> 1.5.0', output.getvalue())
        self.assertEqual((self.root / 'config/config.json').read_bytes(), config_before)
        for name, text in states.items(): self.assertEqual((self.destination / name).read_text(), text)
        self.assertEqual(maps.read_bytes(), b'local map')
        self.assertEqual((self.destination.parent / 'OtherMod/custom.lua').read_text(), '-- another mod')
        self.assertFalse((self.destination / 'Scripts/obsolete.lua').exists())
        self.assertTrue((self.destination / 'Scripts/added.lua').is_file())
        self.assertEqual(loader.installed_record(self.destination)['release'], '1.5.0')
        backup = next((self.destination / '.skieomod-backups').iterdir())
        self.assertEqual((backup / 'Scripts/main.lua').read_bytes(), self.files['Scripts/main.lua'])
        self.assertEqual((backup / 'Scripts/obsolete.lua').read_bytes(), self.files['Scripts/obsolete.lua'])

    def test_check_has_no_writes_and_repeating_update_is_a_noop(self):
        files, record = self.release()
        before = self.snapshot()
        plan = loader.update(self.destination, files, record, check=True)
        self.assertIn('Scripts/obsolete.lua', plan['removed'])
        self.assertEqual(self.snapshot(), before)
        loader.update(self.destination, files, record)
        before = self.snapshot()
        result = loader.update(self.destination, files, record)
        self.assertIsNone(result['backup'])
        self.assertEqual(self.snapshot(), before)

    def test_modified_obsolete_file_is_retained_and_replaced_edits_are_backed_up(self):
        obsolete = self.destination / 'Scripts/obsolete.lua'
        obsolete.write_text('-- authored obsolete module')
        (self.destination / 'Scripts/main.lua').write_text('-- local customization')
        files, record = self.release()
        result = loader.update(self.destination, files, record)
        self.assertIn('Scripts/obsolete.lua', result['retained'])
        self.assertEqual(obsolete.read_text(), '-- authored obsolete module')
        self.assertEqual((Path(result['backup']) / 'Scripts/main.lua').read_text(), '-- local customization')

    def test_write_failure_restores_previous_files_and_manifest(self):
        files, record = self.release()
        original_replace = os.replace
        def replace(source, target):
            if 'next' in Path(source).parts and Path(target).name == 'skieo_repository.dll':
                raise PermissionError('game has locked the DLL')
            return original_replace(source, target)
        with patch.object(loader.os, 'replace', side_effect=replace), self.assertRaises(PermissionError):
            loader.update(self.destination, files, record)
        self.assertEqual(loader.installed_record(self.destination), self.record)
        for name, data in self.files.items(): self.assertEqual((self.destination / name).read_bytes(), data)
        self.assertFalse((self.destination / 'Scripts/added.lua').exists())

    def test_legacy_installation_can_update_without_removing_unknown_files(self):
        (self.destination / loader.RECORD).unlink()
        files, record = self.release()
        result = loader.update(self.destination, files, record)
        self.assertIn('legacy', result['installed'])
        self.assertTrue((self.destination / 'Scripts/obsolete.lua').exists())
        self.assertEqual(loader.installed_record(self.destination), record)

    def test_previous_test_release_can_be_reapplied(self):
        files, record = self.release()
        loader.update(self.destination, files, record)
        loader.update(self.destination, self.files, self.record)
        self.assertEqual(loader.installed_record(self.destination), self.record)
        self.assertFalse((self.destination / 'Scripts/added.lua').exists())

    def test_invalid_archive_rejected_before_any_installation_write(self):
        files, record = self.release()
        cases = [({**files, 'Scripts/main.lua': b'tampered'}, record),
                 ({**files, 'Scripts/workshop.json': b'{}'}, record),
                 ({**files, '../escape.lua': b'bad'}, record),
                 ({name: data for name, data in files.items() if name != 'Scripts/main.lua'}, record)]
        for payload, metadata in cases:
            with self.subTest(files=list(payload)):
                archive = self.archive(payload, metadata)
                before = self.snapshot()
                with contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(cli.main(['update', '--archive', str(archive)]), 2)
                self.assertEqual(self.snapshot(), before)

    def test_default_update_uses_bundled_loader_and_check_preserves_config(self):
        source = desktop.bundled_loader()
        before = self.snapshot()
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(['update', '--bundled', '--check']), 0)
        self.protocol.assert_not_called()
        self.assertEqual(self.snapshot(), before)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(['update', '--bundled']), 0)
        self.assertEqual((self.destination / 'Scripts/main.lua').read_bytes(), (source / 'Scripts/main.lua').read_bytes())
        self.assertEqual(desktop.load_config(), self.config)

    def test_headless_update_skips_desktop_registration(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(['update', '--bundled', '--no-editor-link']), 0)
        self.protocol.assert_not_called()
        self.assertEqual(loader.installed_record(self.destination)['release'], loader.VERSION)

    def test_update_requires_an_existing_installation(self):
        (self.destination / 'Scripts/main.lua').unlink()
        before = self.snapshot()
        with contextlib.redirect_stderr(io.StringIO()) as errors:
            self.assertEqual(cli.main(['update', '--bundled']), 2)
        self.assertIn('setup first', errors.getvalue())
        self.assertEqual(self.snapshot(), before)

    def test_only_the_in_game_worker_executable_is_managed(self):
        self.assertEqual(loader.managed_path('Scripts/skieo_updater.exe'), 'Scripts/skieo_updater.exe')
        for name in ('Scripts/arbitrary.exe', 'skieo_updater.exe', 'Scripts/../skieo_updater.exe',
                     'Scripts/skieo_updater.exe.bat', '.skieomod-updates/worker.exe'):
            with self.subTest(name=name), self.assertRaises(ManifestError):
                loader.managed_path(name)
        files, record = self.release()
        files['Scripts/skieo_updater.exe'] = b'test PE payload'
        record = loader.manifest(files, '1.24.7')
        path = self.archive(files, record)
        self.assertEqual(loader.read_archive(path), (files, record))

    def example_release(self):
        projects.create('map', self.root / 'example', 'Veymont', 'community.veymont', 'Albatar (Élie Millon)')
        files, _ = self.release(loader.VERSION)
        files.update(loader.example_files(self.root / 'example'))
        self.config['maps_dir'] = str(self.root / 'maps')
        desktop.save_config(self.config)
        return files, loader.manifest(files)

    def test_legacy_archive_update_never_auto_installs_its_example(self):
        files, record = self.example_release()
        archive = self.archive(files, record)
        before = self.snapshot()
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(['update', '--archive', str(archive), '--check']), 0)
        self.assertEqual(self.snapshot(), before)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(['update', '--archive', str(archive)]), 0)
        self.assertFalse((self.root / 'maps').exists())
        maps = self.root / 'maps'; maps.mkdir()
        sample = maps / 'community.veymont-0.1.0.skieomap'
        sample.write_bytes(b'my edited map')
        before = self.snapshot()
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(['update', '--archive', str(archive)]), 0)
        self.assertEqual(self.snapshot(), before)

    def test_bundled_loader_excludes_legacy_example_payloads(self):
        files, record = self.example_release()
        for name, data in files.items():
            target = self.destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        collected = desktop.bundled_loader_files(self.destination)
        self.assertFalse(any(name.startswith('Examples/') for name in collected))

    def test_example_archives_are_only_managed_inside_the_examples_directory(self):
        self.assertEqual(loader.managed_path('Examples/Veymont-0.5.1.skieomap'), 'Examples/Veymont-0.5.1.skieomap')
        for path in ('my-map.skieomap', 'Scripts/local.skieomap', 'Examples/settings.json', 'Examples/nested/map.skieomap'):
            with self.subTest(path=path), self.assertRaises(ManifestError):
                loader.managed_path(path)

    def test_featured_catalog_checks_separate_archive_and_rejects_corruption(self):
        projects.create('map', self.root / 'featured-source', 'Veymont', 'community.veymont', 'Albatar (Élie Millon)')
        files = loader.featured_files(self.root / 'featured-source')
        for name, data in files.items():
            (self.root / name).write_bytes(data)
        catalog = self.root / 'featured-maps.json'
        packages = loader.read_featured_catalog(catalog)
        self.assertEqual([name for path, name in packages], ['community.veymont-0.1.0.skieomap'])
        self.assertFalse(any(name.startswith('Examples/') for name in files))
        packages[0][0].write_bytes(b'corrupt map')
        with self.assertRaisesRegex(ManifestError, 'size/SHA-256 mismatch'):
            loader.read_featured_catalog(catalog)

    def test_featured_catalog_contains_both_maps_and_rejects_duplicate_ids(self):
        first, second = self.root / 'featured-first', self.root / 'featured-second'
        projects.create('map', first, 'Veymont', 'community.veymont', 'Albatar')
        projects.create('map', second, 'Super Saint-Bernard', 'community.super-saint-bernard', 'SkiEO Community')
        files = loader.featured_files([first, second])
        for name, data in files.items():
            (self.root / name).write_bytes(data)
        packages = loader.read_featured_catalog(self.root / 'featured-maps.json')
        self.assertEqual({name for path, name in packages},
                         {'community.veymont-0.1.0.skieomap', 'community.super-saint-bernard-0.1.0.skieomap'})
        self.assertEqual(len(files), 3)
        with self.assertRaisesRegex(ManifestError, 'Duplicate'):
            loader.featured_files([first, first])

    def test_featured_archive_compiles_graphs_and_catalogues_the_runtime_manifest(self):
        from tools import skieo_authoring as authoring, skieo_editor as editor
        source = self.root / 'featured-graph'
        projects.create('map', source, 'Scenario', 'community.scenario', blank=True)
        document = editor.EditorProject(source)
        document.queue_authoring('triggers', {'version': 1, 'triggers': [authoring.new_trigger()]})
        document.save()
        before = {p.relative_to(source): p.read_bytes() for p in source.rglob('*') if p.is_file()}
        files = loader.featured_files(source)
        release = json.loads(files['featured-maps.json'])['packages'][0]
        with zipfile.ZipFile(io.BytesIO(files['community.scenario-0.1.0.skieomap'])) as archive:
            manifest = json.loads(archive.read('custom-map.json'))
            self.assertEqual(release['manifest'], manifest)
            self.assertEqual(manifest['script']['entry'], authoring.GENERATED_SCRIPT)
            self.assertIn('api:log', archive.read(authoring.GENERATED_SCRIPT).decode())
            self.assertNotIn('Triggers/triggers.json', archive.namelist())
        self.assertEqual(before, {p.relative_to(source): p.read_bytes() for p in source.rglob('*') if p.is_file()})

    def responses(self, feed, data):
        responses = []
        for url, body in [(loader.UPDATE_URL, json.dumps(feed).encode()), (feed['url'], data)]:
            response = io.BytesIO(body)
            response.geturl = lambda url=url: url
            responses.append(response)
        return responses

    def test_default_cli_update_fetches_versioned_release_from_vps(self):
        path = self.archive()
        _, record = loader.read_archive(path)
        # The filename of the immutable artifact identifies its exact version.
        versioned = path.with_name('CustomMap-Mod-' + record['release'] + '.zip')
        versioned.write_bytes(path.read_bytes())
        feed = loader.update_feed(versioned, record)
        with patch.object(loader, 'urlopen', side_effect=self.responses(feed, path.read_bytes())) as network, \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(['update']), 0)
        self.assertEqual(network.call_count, 2)
        self.assertEqual(network.call_args_list[0].args[0].full_url, loader.UPDATE_URL)
        self.assertEqual(network.call_args_list[1].args[0].full_url, feed['url'])
        self.assertEqual(loader.installed_record(self.destination)['release'], '1.5.0')

    def test_network_or_download_integrity_errors_leave_installation_untouched(self):
        path = self.archive()
        _, record = loader.read_archive(path)
        versioned = path.with_name('CustomMap-Mod-' + record['release'] + '.zip')
        versioned.write_bytes(path.read_bytes())
        feed = loader.update_feed(versioned, record)
        before = self.snapshot()
        for failure in (URLError('server unavailable'), self.responses(feed, b'corrupt archive')):
            with self.subTest(failure=type(failure).__name__), \
                 patch.object(loader, 'urlopen', side_effect=failure), \
                 contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(cli.main(['update']), 2)
            self.assertEqual(self.snapshot(), before)

    def test_feed_rejects_foreign_urls_and_incompatible_cli_before_download(self):
        path = self.archive()
        _, record = loader.read_archive(path)
        feed = {
            'format': 'skieomod-loader-update', 'version': 1, 'release': '1.5.0',
            'loader': record, 'url': loader.DOWNLOAD_BASE + 'CustomMap-Mod-1.5.0.zip',
            'minimum_cli': '1.5.0', 'size': path.stat().st_size,
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        for overrides in ({'url': 'http://other.example/loader.zip'}, {'minimum_cli': '99.0.0'}):
            invalid = {**feed, **overrides}
            with self.subTest(overrides=overrides), \
                 patch.object(loader, 'urlopen', side_effect=self.responses(invalid, b'')) as network, \
                 self.assertRaises(ManifestError):
                loader.fetch_release()
            self.assertEqual(network.call_count, 1)

    def test_larger_release_exceeds_old_limit_and_remains_bounded(self):
        files, _ = self.release('1.7.0')
        files['Scripts/large.lua'] = b'--' + b'x' * (17 * 1024 * 1024)
        record = loader.manifest(files, '1.7.0')
        path = self.archive(files, record)
        self.assertGreater(path.stat().st_size, 16 * 1024 * 1024)
        self.assertEqual(loader.read_archive(path), (files, record))
        versioned = path.with_name('CustomMap-Mod-1.7.0.zip')
        path.rename(versioned)
        feed = loader.update_feed(versioned, record)
        with patch.object(loader, 'urlopen', side_effect=self.responses(feed, versioned.read_bytes())):
            self.assertEqual(loader.fetch_release(), (files, record))
        oversize = self.root / 'too-big.zip'
        with oversize.open('wb') as output:
            output.truncate(loader.MAX_ARCHIVE_BYTES + 1)
        with self.assertRaisesRegex(ManifestError, '64 MiB'):
            loader.read_archive(oversize)


if __name__ == '__main__':
    unittest.main()
