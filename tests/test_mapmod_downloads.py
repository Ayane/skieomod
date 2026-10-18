import hashlib
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from tools import skieo_loader as loader, skieo_project as projects
from tools import custom_map as cli
from tools.custom_packages import ManifestError, inspect_package


class MapmodDownloadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.map = self.root / 'map'
        projects.create('map', self.map, 'Map', 'test.map', blank=True)
        source = self.map / 'custom-map.json'
        manifest = json.loads(source.read_text())
        manifest['dependencies'] = [{'id': 'test.foxes', 'version': '=0.1.0'}]
        source.write_text(json.dumps(manifest))
        self.mod = self.root / 'foxes'
        projects.create('mapmod', self.mod, 'Foxes', 'test.foxes')
        self.files = loader.featured_files([self.map, self.mod])
        self.catalog = json.loads(self.files['featured-maps.json'])
        self.release = next(r for r in self.catalog['packages'] if r['kind'] == 'mod')
        self.root_release = next(r for r in self.catalog['packages'] if r['kind'] == 'map')
        self.urls = {loader.DOWNLOAD_BASE + name: data for name, data in self.files.items()}
        self.calls = []

    def fetch(self, url, limit, timeout):
        self.calls.append(url)
        return self.urls[url]

    def test_separate_packages_and_verified_catalogue(self):
        for name, data in self.files.items():
            (self.root / name).write_bytes(data)
        self.assertEqual(len(loader.read_featured_catalog(self.root/'featured-maps.json')), 2)
        with zipfile.ZipFile(self.root/'test.map-0.1.0.skieomap') as package:
            self.assertNotIn('custom-mod.json', package.namelist())
            self.assertEqual(json.loads(package.read('custom-map.json'))['dependencies'][0]['version'], '=0.1.0')
        with self.assertRaises(ManifestError):
            loader.featured_files(self.map)

    def test_download_exact_dependency_then_reuse_offline(self):
        with patch.object(loader, '_read_update', self.fetch):
            closure = loader.fetch_mapmod_dependencies(self.root_release, [], self.root/'downloads')
        self.assertEqual([r['id'] for r in closure], ['test.foxes', 'test.map'])
        self.assertEqual(inspect_package(closure[0]['archive'])[1], self.release['manifest'])
        with patch.object(loader, '_read_update', side_effect=AssertionError('unexpected network')):
            reused = loader.fetch_mapmod_dependencies(self.root_release, closure[:1], self.root/'offline')
        self.assertEqual(reused, closure)
        self.assertFalse((self.root/'offline').exists())

    def test_wrong_version_missing_transitive_and_workshop_identity_fail_before_download(self):
        for dependency in [{'id':'test.foxes','version':'=9.0.0'},
                           {'id':'test.foxes','version':'=0.1.0','workshop_id':'123'}]:
            self.root_release['manifest']['dependencies']=[dependency]
            self.calls=[]
            with patch.object(loader, '_read_update', self.fetch), self.assertRaises(ManifestError):
                loader.fetch_mapmod_dependencies(self.root_release, [], self.root/'downloads')
            self.assertEqual(self.calls, [loader.DOWNLOAD_BASE+'featured-maps.json'])

    def test_corrupt_digest_and_foreign_host_are_rejected(self):
        url=self.release['download_url']
        self.urls[url]=b'bad archive'
        with patch.object(loader, '_read_update', self.fetch), self.assertRaisesRegex(ManifestError, 'SHA-256'):
            loader.fetch_mapmod_dependencies(self.root_release, [], self.root/'downloads')
        self.release['download_url']='https://untrusted.example/fox.skieomod'
        self.urls[loader.DOWNLOAD_BASE+'featured-maps.json']=json.dumps(self.catalog).encode()
        with patch.object(loader, '_read_update', self.fetch), self.assertRaisesRegex(ManifestError, 'metadata'):
            loader.fetch_mapmod_dependencies(self.root_release, [], self.root/'downloads')

    def test_versioned_mods_coexist_and_catalogue_resolves_requested_version(self):
        second=self.root/'foxes-new'
        projects.create('mapmod', second, 'Foxes', 'test.foxes')
        source=second/'custom-mod.json'; manifest=json.loads(source.read_text())
        manifest['metadata']['version']='0.2.0';source.write_text(json.dumps(manifest))
        files=loader.featured_files([self.map,self.mod,second])
        for name,data in files.items(): (self.root/name).write_bytes(data)
        self.assertEqual(len(loader.read_featured_catalog(self.root/'featured-maps.json')),3)
        self.urls={loader.DOWNLOAD_BASE+name:data for name,data in files.items()}
        with patch.object(loader,'_read_update',self.fetch):
            closure=loader.fetch_mapmod_dependencies(self.root_release,[],self.root/'downloads')
        self.assertEqual(closure[0]['version'],'0.1.0')

    def test_run_installs_local_downloaded_and_cached_dependencies(self):
        for source in ('local', 'download'):
            config = {'maps_dir': str(self.root/source/'maps'), 'ue4ss_mods': str(self.root/source/'mods')}
            scripts = Path(config['ue4ss_mods'])/loader.NAME/'Scripts'
            scripts.mkdir(parents=True)
            args = ['run', str(self.map)]
            if source == 'local':
                args += ['--dependency', str(self.mod)]
            with self.subTest(source=source), \
                 patch.object(cli.desktop, 'configure', return_value=config), \
                 patch.object(cli.desktop, 'setup', return_value=config), \
                 patch.object(cli.workshop, 'installed', return_value=([], {})), \
                 patch.object(cli.desktop, 'request_play') as play, \
                 patch.object(loader, '_read_update', self.fetch), \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cli.main(args), 0)
                play.assert_called_once()
                installed = Path(config['maps_dir'])/'test.foxes-0.1.0.skieomod'
                self.assertEqual(inspect_package(installed)[1], self.release['manifest'])
                lock = json.loads((Path(config['maps_dir'])/'custom-map.lock.json').read_text())
                self.assertEqual([p['id'] for p in lock['packages']], ['test.foxes', 'test.map'])
                with patch.object(loader, '_read_update', side_effect=AssertionError('unexpected network')):
                    self.assertEqual(cli.main(['run', str(self.map)]), 0)


if __name__ == '__main__':
    unittest.main()
