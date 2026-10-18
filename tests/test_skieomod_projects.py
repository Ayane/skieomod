import contextlib
import io
import json
import os
from pathlib import Path
import struct
import re
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from tools import custom_map as cli, skieo_project as projects, skieo_install as desktop
from tools.custom_packages import inspect_package, ManifestError


class ProjectTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_map_template_builds_reproducibly_and_registers_lua_callback(self):
        manifest = projects.create('map', self.root, 'Starter slope', 'author.starter', 'Author')
        archive, release = projects.build(self.root)
        self.assertEqual(archive.parent, self.root / 'bin')
        self.assertEqual(inspect_package(archive)[0], 'map')
        with zipfile.ZipFile(archive) as package:
            self.assertEqual(len(package.read('Terrain/heightmap.r16')), 65 * 65 * 2)
            self.assertIn(b'api:on("map.ready"', package.read('Scripts/skieomod-generated-vegetation.lua'))
            self.assertNotIn('README.md', package.namelist())
        data = archive.read_bytes()
        self.assertEqual(projects.build(manifest)[0].read_bytes(), data)
        self.assertEqual(release['version'], '0.1.0')

    def test_mod_template_builds_as_dependency(self):
        projects.create('mapmod', self.root, 'Snow tools')
        archive, release = projects.build(self.root)
        self.assertEqual(archive.suffix, '.skieomod')
        self.assertEqual(inspect_package(archive)[1]['runtime'], 'map-api')
        self.assertEqual(release['manifest']['files'], ['Scripts/main.lua'])

    def test_tree_positions_are_editable_json_compiled_to_binary_by_build(self):
        source = projects.create('map', self.root, size_meters=[128, 64])
        manifest = json.loads(source.read_text())
        self.assertEqual(manifest['build']['forest']['file'], 'Vegetation/forest.json')
        self.assertIn('Vegetation/Generated/forest.skxy', manifest['content']['assets'])
        self.assertEqual(manifest['script']['permissions'], ['gameplay'])
        trees = json.loads((self.root / 'Vegetation/forest.json').read_text())
        for point in trees:
            self.assertTrue(-64 <= point['x'] <= 64 and -32 <= point['y'] <= 32)
        edited = b'[{"x":12.25,"y":-20},{"x":-31,"y":0}]\n'
        (self.root / 'Vegetation/forest.json').write_bytes(edited)
        archive, _ = projects.build(self.root)
        with zipfile.ZipFile(archive) as package:
            self.assertEqual(package.read('Vegetation/Generated/forest.skxy'), struct.pack('<4sIIffff', b'SKXY', 1, 2, 1225, -2000, -3100, 0))
            self.assertNotIn('Vegetation/forest.json', package.namelist())
            self.assertEqual((self.root / 'Vegetation/forest.json').read_bytes(), edited)
            self.assertIn(b'api:load_forest_skxy("Vegetation/Generated/forest.skxy")', package.read('Scripts/skieomod-generated-vegetation.lua'))

    def test_ue4ss_mod_template(self):
        projects.create('mod', self.root, 'Snow tools')
        archive, release = projects.build(self.root)
        self.assertEqual(inspect_package(archive)[1]['runtime'], 'ue4ss')
        self.assertEqual(release['manifest']['install_directory'], 'SkiEO-local-snow-tools')
        self.assertNotIn('script', release['manifest'])

    def test_all_templates_include_self_contained_docs_and_commented_scripts(self):
        for kind in ('map', 'mod', 'mapmod'):
            with self.subTest(kind=kind):
                project = self.root / kind
                projects.create(kind, project, 'Station des Écrins', 'author.' + kind, 'Créateur')
                readme = (project / 'README.md').read_text(encoding='utf-8')
                self.assertIn('Station des Écrins', readme)
                guides = ['manifest', 'scripting', 'development', 'workshop']
                if kind == 'map': guides.extend(['terrain', 'vegetation'])
                docs = [project / 'README.md', *(project / 'docs' / (guide + '.md') for guide in guides)]
                for doc in docs:
                    text = doc.read_text(encoding='utf-8')
                    self.assertTrue(text.startswith('# '))
                    for target in re.findall(r'\[[^\]]+\]\(([^)]+)\)', text):
                        if '://' not in target:
                            self.assertTrue((doc.parent / target).is_file(), f'Broken documentation link: {doc}: {target}')
                script = (project / 'Scripts/main.lua').read_text(encoding='utf-8')
                self.assertIn('docs/scripting.md', script)
                self.assertIn('game', script)
                self.assertIn('UE4SS entry point' if kind == 'mod' else 'return function(api)', script)
                if kind == 'map':
                    self.assertIn('8450', (project / 'docs/terrain.md').read_text())
                if kind == 'mapmod':
                    self.assertIn('obj/mapmod-preview', (project / 'docs/development.md').read_text())
                archive, _ = projects.build(project)
                with zipfile.ZipFile(archive) as package:
                    self.assertFalse(any(name.startswith('docs/') for name in package.namelist()))
                    self.assertNotIn('README.md', package.namelist())

    def test_mapmod_preview_resolves_local_dependency_without_publication(self):
        projects.create('mapmod', self.root, 'Snow tools')
        _, mod = projects.build(self.root)
        preview, release = projects.preview_map(self.root, mod)
        with patch('tools.skieo_workshop.call') as network:
            closure = cli.check_dependencies(release['manifest'], 'map', [mod])
            network.assert_not_called()
        self.assertEqual({p['id'] for p in closure}, {mod['id'], release['id']})
        self.assertEqual(inspect_package(preview)[0], 'map')

    def test_mapmod_run_installs_local_mod_and_launches_preview(self):
        project = self.root / 'project'
        projects.create('mapmod', project, 'Snow tools')
        config = self.game_config()
        scripts = Path(config['ue4ss_mods']) / desktop.LOADER_NAME / 'Scripts'
        with patch('tools.custom_map.desktop.configure', return_value=config), patch('tools.custom_map.desktop.setup', return_value=config), patch('tools.skieo_install.launch_game') as steam, patch('tools.skieo_workshop.call') as network, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(['run', str(project)]), 0)
            network.assert_not_called()
        request = json.loads((scripts / 'launch-request.json').read_text())
        self.assertEqual(request['id'], 'local.preview-local-snow-tools')
        ledger = json.loads((scripts / 'skieomod-installed.json').read_text())
        self.assertEqual({p['kind'] for p in ledger['packages']}, {'map', 'mod'})
        steam.assert_called_once_with(config)

    def test_ue4ss_run_updates_local_mod_with_backup_and_enables_it(self):
        project = self.root / 'project'
        projects.create('mod', project, 'Snow tools')
        config = self.game_config()
        mods = Path(config['ue4ss_mods'])
        (mods / 'mods.txt').write_text('SkiEO-local-snow-tools : 0\n')
        with patch('tools.custom_map.desktop.configure', return_value=config), patch('tools.custom_map.desktop.setup', return_value=config), patch('tools.skieo_install.launch_game') as steam, patch('tools.skieo_workshop.call') as network, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(['run', str(project)]), 0)
            installed = mods / 'SkiEO-local-snow-tools/Scripts/main.lua'
            previous = installed.read_text()
            self.assertEqual(previous, (project / 'Scripts/main.lua').read_text())
            self.assertEqual((mods / 'mods.txt').read_text(), 'SkiEO-local-snow-tools : 1\n')
            (project / 'Scripts/main.lua').write_text(previous + '\n-- modified local mod\n')
            self.assertEqual(cli.main(['run', str(project)]), 0)
            self.assertIn('modified local mod', installed.read_text())
            saved = list((mods / '.skieomod-backups').rglob('main.lua'))
            self.assertEqual(len(saved), 1)
            self.assertEqual(saved[0].read_text(), previous)
            network.assert_not_called()
            self.assertEqual(steam.call_count, 2)

    def game_config(self):
        game = self.root / 'game'
        (game / 'SkiResortSimulator/Content/Paks').mkdir(parents=True, exist_ok=True)
        (game / 'SkiResortSimulator/Binaries/Win64').mkdir(parents=True, exist_ok=True)
        config = desktop.game_paths(game, '5012760')
        (Path(config['ue4ss_mods']) / desktop.LOADER_NAME / 'Scripts').mkdir(parents=True, exist_ok=True)
        return config

    def test_new_refuses_to_overwrite_and_validates_before_writing(self):
        (self.root / 'README.md').write_text('keep me')
        with self.assertRaises(ManifestError): projects.create('map', self.root)
        self.assertEqual(list(self.root.iterdir()), [self.root / 'README.md'])
        with self.assertRaises(ManifestError): projects.create('map', self.root / 'bad', identifier='../../bad')
        self.assertFalse((self.root / 'bad').exists())

    def test_documentation_symlink_cannot_write_outside_project(self):
        project = self.root / 'project'
        project.mkdir()
        outside = self.root / 'outside'
        outside.mkdir()
        try:
            (project / 'docs').symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest('directory symlinks are unavailable')
        with self.assertRaisesRegex(ManifestError, 'symbolic link'):
            projects.create('map', project)
        self.assertEqual(list(outside.iterdir()), [])
        self.assertEqual(list(project.iterdir()), [project / 'docs'])

    def test_failed_build_preserves_previous_artifact_and_source(self):
        source = projects.create('map', self.root)
        archive, _ = projects.build(self.root)
        before = archive.read_bytes()
        (self.root / 'Terrain/heightmap.r16').write_bytes(b'invalid')
        with self.assertRaises(ManifestError): projects.build(self.root)
        self.assertEqual(archive.read_bytes(), before)
        with self.assertRaises(ManifestError): projects.build(source, source)
        self.assertTrue(source.is_file())

    def test_run_builds_installs_and_requests_local_map_without_upload(self):
        project = self.root / 'project'
        projects.create('map', project, 'My slope')
        game = self.root / 'game'
        (game / 'SkiResortSimulator/Content/Paks').mkdir(parents=True)
        (game / 'SkiResortSimulator/Binaries/Win64').mkdir(parents=True)
        config = desktop.game_paths(game, '5012760')
        scripts = Path(config['ue4ss_mods']) / desktop.LOADER_NAME / 'Scripts'
        scripts.mkdir(parents=True)
        with patch('tools.custom_map.desktop.configure', return_value=config), patch('tools.custom_map.desktop.setup', return_value=config) as setup, patch('tools.skieo_install.launch_game') as steam, patch('tools.skieo_workshop.call') as network, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(['run', str(project)]), 0)
            network.assert_not_called()
            steam.assert_called_once_with(config)
            self.assertFalse(setup.call_args.kwargs['protocol'])
            request = json.loads((scripts / 'launch-request.json').read_text())
            self.assertEqual(request['id'], 'local.my-slope')
            self.assertEqual(request['map_version'], '0.1.0')
            archive = (scripts / request['package_path']).resolve()
            self.assertTrue(archive.is_file())
            self.assertEqual(inspect_package(archive)[0], 'map')
            # Iteration at the same local version replaces a previous local build.
            source = project / 'Scripts/main.lua'
            source.write_text(source.read_text() + '\n-- next local iteration\n')
            self.assertEqual(cli.main(['run', str(project)]), 0)
            ledger = json.loads((scripts / 'skieomod-installed.json').read_text())
            self.assertEqual(len(ledger['packages']), 1)
            with zipfile.ZipFile(archive) as package: self.assertIn(b'next local iteration', package.read('Scripts/skieomod-generated-vegetation.lua'))

    def test_current_directory_workflow(self):
        previous = Path.cwd()
        try:
            os.chdir(self.root)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cli.main(['new', 'map']), 0)
                self.assertEqual(cli.main(['build']), 0)
                self.assertEqual(cli.main(['test']), 0)
        finally: os.chdir(previous)


if __name__ == '__main__': unittest.main()
