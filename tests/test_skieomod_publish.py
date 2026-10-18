import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from deployment import publish_loader_updates as publication
from deployment.publish_loader_updates import REMOTE
from tools import skieo_install as desktop, skieo_loader as loader


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.downloads = self.root / 'downloads'
        self.downloads.mkdir()
        self.previous = b'{"release":"previous"}\n'
        (self.downloads / 'loader-latest.json').write_bytes(self.previous)
        self.version = loader.VERSION
        self.archive_name = 'CustomMap-Mod-' + self.version + '.zip'
        archive = self.root / self.archive_name
        archive.write_bytes(b'test artifact')
        files = {name: b'source' for name in loader.REQUIRED}
        self.feed = loader.update_feed(archive, loader.manifest(files))
        self.ue4ss_name = desktop.UE4SS_ARCHIVE
        self.ue4ss_data = b'tested UE4SS build'
        self.payload = {
            self.archive_name: archive.read_bytes(),
            'skieo_custom_map-' + self.version + '-py3-none-any.whl': b'test wheel',
            'CustomMap-Tools-' + self.version + '.zip': b'test source archive',
            'Getting-Started-' + self.version + '.md': b'# SkiEO Custom Maps\n',
            'loader-latest.json': json.dumps(self.feed).encode(),
            self.ue4ss_name: self.ue4ss_data,
            'ue4ss-release.json': json.dumps({'name': self.ue4ss_name,
                'sha256': hashlib.sha256(self.ue4ss_data).hexdigest(),
                'size': len(self.ue4ss_data)}).encode(),
        }

    def publish(self, payload):
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode='w') as archive:
            for name, content in payload.items():
                item = tarfile.TarInfo(name)
                item.size = len(content)
                archive.addfile(item, io.BytesIO(content))
        return subprocess.run([sys.executable, '-c', REMOTE, str(self.downloads)],
                              input=stream.getvalue(), capture_output=True)

    def test_publish_keeps_previous_pointer_and_versioned_artifacts(self):
        result = self.publish(self.payload)
        self.assertEqual(result.returncode, 0, result.stderr)
        for name, data in self.payload.items():
            if name != 'ue4ss-release.json':
                self.assertEqual((self.downloads / name).read_bytes(), data)
        self.assertFalse((self.downloads / 'ue4ss-release.json').exists())
        self.assertEqual((self.downloads / 'loader-latest.previous.json').read_bytes(), self.previous)
        for alias, target in [('CustomMap-Mod.zip', self.archive_name),
                              ('CustomMap-Tools.zip', 'CustomMap-Tools-' + self.version + '.zip'),
                              ('getting-started.md', 'Getting-Started-' + self.version + '.md')]:
            self.assertTrue((self.downloads / alias).is_symlink())
            self.assertEqual(os.readlink(self.downloads / alias), target)
            self.assertEqual((self.downloads / alias).read_bytes(), self.payload[target])
        index = (self.downloads / 'pypi/skieo-custom-map/index.html').read_text()
        self.assertIn('skieo_custom_map-' + self.version + '-py3-none-any.whl#sha256=', index)
        self.assertEqual(self.publish(self.payload).returncode, 0)
        self.assertEqual((self.downloads / 'loader-latest.previous.json').read_bytes(), self.previous)

    def test_stable_links_and_index_follow_the_next_release(self):
        self.assertEqual(self.publish(self.payload).returncode, 0)
        next_version = '9.0.0'
        payload = {name.replace(self.version, next_version): data for name, data in self.payload.items()}
        feed = {**self.feed, 'release': next_version,
                'url': loader.DOWNLOAD_BASE + 'CustomMap-Mod-' + next_version + '.zip'}
        payload['loader-latest.json'] = json.dumps(feed).encode()
        self.assertEqual(self.publish(payload).returncode, 0)
        self.assertEqual(os.readlink(self.downloads / 'CustomMap-Mod.zip'), 'CustomMap-Mod-9.0.0.zip')
        self.assertEqual(os.readlink(self.downloads / 'CustomMap-Tools.zip'), 'CustomMap-Tools-9.0.0.zip')
        index = (self.downloads / 'pypi/skieo-custom-map/index.html').read_text()
        self.assertIn('skieo_custom_map-9.0.0-py3-none-any.whl', index)
        self.assertNotIn('skieo_custom_map-' + self.version, index)
        self.assertTrue((self.downloads / self.archive_name).is_file())

    def test_existing_regular_download_aliases_are_saved_on_migration(self):
        for name in ('CustomMap-Tools.zip', 'CustomMap-Mod.zip'):
            (self.downloads / name).write_bytes(b'legacy public archive')
        self.assertEqual(self.publish(self.payload).returncode, 0)
        for name in ('CustomMap-Tools.zip', 'CustomMap-Mod.zip'):
            self.assertEqual((self.downloads / name.replace('.zip', '.previous.zip')).read_bytes(), b'legacy public archive')
            self.assertTrue((self.downloads / name).is_symlink())

    def test_corruption_or_different_version_bytes_cannot_change_latest_pointer(self):
        invalid = {**self.payload, self.archive_name: b'corrupt'}
        self.assertNotEqual(self.publish(invalid).returncode, 0)
        self.assertEqual((self.downloads / 'loader-latest.json').read_bytes(), self.previous)
        self.assertEqual(list(self.downloads.iterdir()), [self.downloads / 'loader-latest.json'])
        existing = self.downloads / self.archive_name
        existing.write_bytes(b'previously published bytes')
        self.assertNotEqual(self.publish(self.payload).returncode, 0)
        self.assertEqual((self.downloads / 'loader-latest.json').read_bytes(), self.previous)
        self.assertEqual(existing.read_bytes(), b'previously published bytes')

    def test_archive_paths_cannot_escape_upload_directory(self):
        invalid = {**self.payload, '../escape': b'bad'}
        self.assertNotEqual(self.publish(invalid).returncode, 0)
        self.assertFalse((self.downloads / 'escape').exists())
        self.assertFalse((self.root / 'escape').exists())
        self.assertEqual((self.downloads / 'loader-latest.json').read_bytes(), self.previous)

    def test_missing_or_corrupt_ue4ss_cannot_publish_the_cli(self):
        missing_archive = {name: data for name, data in self.payload.items() if name != self.ue4ss_name}
        missing_record = {name: data for name, data in self.payload.items() if name != 'ue4ss-release.json'}
        for payload in (missing_archive, missing_record,
                        {**self.payload, self.ue4ss_name: b'corrupt dependency'}):
            with self.subTest(files=list(payload)):
                result = self.publish(payload)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(list(self.downloads.iterdir()), [self.downloads / 'loader-latest.json'])
                self.assertEqual((self.downloads / 'loader-latest.json').read_bytes(), self.previous)

    def test_published_ue4ss_cannot_be_replaced_even_with_a_matching_digest(self):
        self.assertEqual(self.publish(self.payload).returncode, 0)
        before = {path.relative_to(self.downloads): path.read_bytes()
                  for path in self.downloads.rglob('*') if path.is_file()}
        changed = b'another UE4SS build'
        payload = {**self.payload, self.ue4ss_name: changed,
                   'ue4ss-release.json': json.dumps({'name': self.ue4ss_name,
                       'sha256': hashlib.sha256(changed).hexdigest(), 'size': len(changed)}).encode()}
        self.assertNotEqual(self.publish(payload).returncode, 0)
        self.assertEqual({path.relative_to(self.downloads): path.read_bytes()
                          for path in self.downloads.rglob('*') if path.is_file()}, before)

    def test_new_tested_ue4ss_build_retains_the_previous_archive(self):
        self.assertEqual(self.publish(self.payload).returncode, 0)
        version = '9.0.0'
        payload = {name.replace(self.version, version): data for name, data in self.payload.items()}
        payload['loader-latest.json'] = json.dumps({**self.feed, 'release': version,
            'url': loader.DOWNLOAD_BASE + 'CustomMap-Mod-' + version + '.zip'}).encode()
        new_name = 'UE4SS_v3.0.1-1161-g6eb3d9bc.zip'
        new_data = b'new tested UE4SS build'
        del payload[self.ue4ss_name]
        payload[new_name] = new_data
        payload['ue4ss-release.json'] = json.dumps({'name': new_name,
            'sha256': hashlib.sha256(new_data).hexdigest(), 'size': len(new_data)}).encode()
        result = self.publish(payload)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.downloads / self.ue4ss_name).read_bytes(), self.ue4ss_data)
        self.assertEqual((self.downloads / new_name).read_bytes(), new_data)

    def test_local_publication_rejects_an_unpinned_dependency_before_ssh(self):
        for name, data in self.payload.items():
            (self.downloads / name).write_bytes(data)
        files = {name: b'source' for name in loader.REQUIRED}
        (self.downloads / 'CustomMap-Tools.zip').write_bytes(b'test source archive')
        args = SimpleNamespace(directory=self.downloads, ssh_config=None, known_hosts=None,
                               host='unused', remote_directory='/unused')
        with patch.object(publication, 'read_archive', return_value=(files, loader.manifest(files))), \
             patch.object(publication.subprocess, 'run') as transport:
            with self.assertRaisesRegex(ValueError, 'UE4SS SHA-256 mismatch'):
                publication.publish(args)
            transport.assert_not_called()

    def featured_payload(self):
        from tests.test_repository import archive_bytes, map_manifest
        manifest = map_manifest()
        manifest['id'] = 'community.veymont'
        name = manifest['id'] + '-' + manifest['metadata']['version'] + '.skieomap'
        data = archive_bytes(manifest)
        package = {'id': manifest['id'], 'kind': 'map', 'version': manifest['metadata']['version'],
                   'manifest': manifest, 'size': len(data), 'unpacked_size': 20000,
                   'sha256': hashlib.sha256(data).hexdigest(), 'download_url': loader.DOWNLOAD_BASE + name}
        return {**self.payload, name: data, 'featured-maps.json': json.dumps(
            {'format': 'skieo-registry', 'version': 1, 'packages': [package]}).encode()}, name

    def test_featured_publication_serves_maps_separately_and_is_repeatable(self):
        payload, name = self.featured_payload()
        result = self.publish(payload)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.downloads / name).read_bytes(), payload[name])
        self.assertEqual((self.downloads / 'featured-maps.json').read_bytes(), payload['featured-maps.json'])
        self.assertEqual(self.publish(payload).returncode, 0)

    def test_corrupt_or_missing_featured_maps_cannot_publish_catalogue(self):
        payload, name = self.featured_payload()
        missing = {key: value for key, value in payload.items() if key != name}
        for invalid in ({**payload, name: b'corrupt'}, missing):
            with self.subTest(files=list(invalid)):
                self.assertNotEqual(self.publish(invalid).returncode, 0)
                self.assertFalse((self.downloads / 'featured-maps.json').exists())
                self.assertEqual((self.downloads / 'loader-latest.json').read_bytes(), self.previous)

    def test_mapmod_versions_stay_discoverable_across_publications(self):
        payload, _ = self.featured_payload()
        map_catalog = json.loads(payload['featured-maps.json'])
        for version in ('0.1.0', '0.2.0'):
            name = 'test.foxes-' + version + '.skieomod'
            data = ('mapmod ' + version).encode()
            mod = {'id': 'test.foxes', 'kind': 'mod', 'version': version,
                   'size': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
                   'download_url': loader.DOWNLOAD_BASE + name}
            catalog = {**map_catalog, 'packages': [*map_catalog['packages'], mod]}
            update = {**payload, name: data, 'featured-maps.json': json.dumps(catalog).encode()}
            for _ in range(2):
                result = self.publish(update)
                self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((self.downloads/name).read_bytes(), data)
        retained = json.loads((self.downloads/'featured-maps.json').read_text())['packages']
        self.assertEqual({p['version'] for p in retained if p['kind'] == 'mod'}, {'0.1.0', '0.2.0'})
        previous = (self.downloads/'featured-maps.json').read_bytes()
        (self.downloads/'test.foxes-0.1.0.skieomod').write_bytes(b'corrupt')
        result = self.publish(update)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b'Retained mapmod checksum mismatch', result.stderr)
        self.assertEqual((self.downloads/'featured-maps.json').read_bytes(), previous)


if __name__ == '__main__':
    unittest.main()
