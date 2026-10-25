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


if __name__=='__main__':unittest.main()
