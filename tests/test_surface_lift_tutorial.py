"""Build the downloadable exercise and verify its native-lift binding inputs."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from tools import build_surface_lift_tutorial as tutorial,skieo_project as projects
from tools.custom_map import check_dependencies
from tools.custom_packages import inspect_package
from tools.skieo_scene import compile_scene

ROOT=Path(__file__).resolve().parents[1]


class SurfaceLiftTutorialTests(unittest.TestCase):
    def test_download_builds_as_two_packages_and_matches_native_terminals(self):
        with tempfile.TemporaryDirectory()as directory:
            root=Path(directory)
            with zipfile.ZipFile(tutorial.FILES/'surface-lift-practice.zip')as archive:
                archive.extractall(root)
            mountain=root/'practice-mountain';mod=root/'surface-lifts'
            manifest=json.loads((mountain/'custom-map.json').read_text())
            scene=json.loads((mountain/'Scene/objects.json').read_text())
            definition=manifest['extensions']['community.surface-lifts']['lifts'][0]
            native=next(o for o in compile_scene(scene,manifest)if o['kind']=='lift')
            self.assertEqual(native['name'],definition['name'])
            self.assertEqual(native['position_cm'],definition['route'][0][:2])
            self.assertEqual(native['end_position_cm'],definition['route'][-1][:2])
            self.assertTrue(native['class'].endswith('BP_FixedChair1_C'))
            with contextlib.redirect_stdout(io.StringIO()):
                mod_archive,dependency=projects.build(mod)
                map_archive,package=projects.build(mountain)
            check_dependencies(package['manifest'],'map',[dependency])
            self.assertEqual(inspect_package(mod_archive)[0],'mod')
            with zipfile.ZipFile(map_archive)as archive:
                self.assertFalse(any(name.endswith(('.skpm','.dll'))for name in archive.namelist()),
                                 'the map embedded its dependency assets')

    def test_options_and_scene_downloads_match_the_practice_project(self):
        self.assertEqual(json.loads((tutorial.FILES/'surface-lifts-options.json').read_text()),tutorial.OPTIONS)
        self.assertEqual(json.loads((tutorial.FILES/'objects.json').read_text()),tutorial.SCENE)
        _,manifest,_=inspect_package(tutorial.FILES/'tutorial.surface-lift-practice-0.1.0.skieomap','map')
        self.assertEqual(manifest['extensions']['community.surface-lifts'],tutorial.OPTIONS)

    def test_custom_models_stay_in_the_map_with_the_original_shared_dependency(self):
        with tempfile.TemporaryDirectory()as directory:
            root=Path(directory)
            with zipfile.ZipFile(tutorial.FILES/'surface-lift-custom-models.zip')as archive:
                archive.extractall(root)
            project=root/'practice-custom-models'
            manifest=json.loads((project/'custom-map.json').read_text())
            self.assertEqual(manifest['dependencies'],[{'id':'community.surface-lifts','version':'=0.1.0'}])
            self.assertEqual(manifest['extensions']['community.surface-lifts'],tutorial.CUSTOM_OPTIONS)
            scene=json.loads((project/'Scene/objects.json').read_text())
            native={o['name']:o for o in compile_scene(scene,manifest)if o['kind']=='lift'}
            self.assertEqual(len(native),2)
            for lift in tutorial.CUSTOM_OPTIONS['lifts']:
                self.assertEqual(native[lift['name']]['position_cm'],lift['route'][0][:2])
                self.assertEqual(native[lift['name']]['end_position_cm'],lift['route'][-1][:2])
                overrides=[lift.get('models',{}),*[p['models']for p in lift.get('pylon_models',[])]]
                for models in overrides:
                    for path in models.values():
                        self.assertIn(path,manifest['content']['assets'])
                        self.assertTrue((project/path).is_file())
            with contextlib.redirect_stdout(io.StringIO()):archive,_=projects.build(project)
            with zipfile.ZipFile(archive)as package:
                self.assertTrue(any(p.endswith('.skpm')for p in package.namelist()))
                self.assertNotIn('custom-mod.json',package.namelist())
                self.assertFalse(any(p.endswith('.dll')for p in package.namelist()))


if __name__=='__main__':unittest.main()
