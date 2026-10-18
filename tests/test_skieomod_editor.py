import contextlib
import copy
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from tools import custom_map as cli, skieo_editor as editor, skieo_project as projects
from tests.test_heightmap_build import png16


class EditorProjectTests(unittest.TestCase):
    def test_editor_link_uses_startup_preference_without_configuring_game(self):
        for url in ('skieomod://editor', 'skieomod://editor/'):
            with self.subTest(url=url), patch.object(editor, 'launch', return_value=0) as launch, \
                 patch.object(cli.desktop, 'configure', side_effect=AssertionError('must not configure Steam')):
                self.assertEqual(cli.main(['uri', url]), 0)
                launch.assert_called_once_with(None)

    def test_editor_link_rejects_paths_parameters_and_other_actions(self):
        for url in ('skieomod://editor/my-map', 'skieomod://editor?project=/tmp/map',
                    'skieomod://editor#fragment', 'skieomod://editor/../../tmp',
                    'skieomod://install/test.map', 'https://editor', 'skieomod://editor;anything'):
            with self.subTest(url=url), patch.object(editor, 'launch') as launch, \
                 contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(cli.main(['uri', url]), 2)
                launch.assert_not_called()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.folder = self.root / 'map with spaces'
        projects.create('map', self.folder, 'My Mountain', 'test.mountain')
        self.document = editor.EditorProject(self.folder)

    def test_unsaved_map_keeps_sculpt_scene_triggers_assets_and_overrides_on_first_save(self):
        from tools import skieo_authoring as a
        from tests.test_authoring_build import OBJ
        doc=editor.EditorProject.new();self.addCleanup(doc.workspace.cleanup)
        self.assertFalse(doc.has_folder);self.assertFalse(doc.trees);self.assertIsNone(doc.built)
        doc.heights=type(doc.heights)('d',[123.]*len(doc.heights));doc.terrain_dirty=doc.dirty=True
        doc.change_scene({'version':1,'objects':[{'id':'office','class':a.OBJECTS[0]['class'],'kind':'building','name':'Office','position':[0,0]}]})
        asset=self.root/'office.obj';asset.write_bytes(OBJ);doc.import_resource(asset,'office','model')
        doc.queue_authoring('objects',[{'object':a.OBJECTS[0]['class'],'field':'BaseCost','type':'integer','value':123}])
        doc.queue_authoring('triggers',{'version':1,'triggers':[a.new_trigger()]})
        folder=self.root/'new map';doc.save_to(folder)
        self.assertTrue(doc.has_folder);reopened=editor.EditorProject(folder)
        self.assertEqual(reopened.elevation,(123.,123.));self.assertEqual(len(reopened.scene['objects']),1)
        self.assertEqual(len(reopened.resources['assets']),1);self.assertEqual(reopened.object_edits[0]['value'],123)
        self.assertEqual(len(reopened.triggers['triggers']),1)
        with contextlib.redirect_stdout(io.StringIO()): archive,_=projects.build(folder)
        self.assertTrue(archive.is_file());self.assertEqual(asset.read_bytes(),OBJ)

    def source(self, width=9, height=9, suffix='.png'):
        values = [(row * width + col) * 600 for row in range(height) for col in range(width)]
        path = self.root / ('input' + suffix)
        path.write_bytes(png16(width, height, values) if suffix == '.png' else struct.pack('<' + 'H' * len(values), *values))
        return path

    def brush(self, tool='raise', **options):
        self.document.begin_stroke(tool)
        self.document.paint(0, 0, tool, options.pop('radius', 40), **options)
        self.document.end_stroke()

    def test_open_does_not_change_source_files(self):
        before = {p.relative_to(self.folder): p.read_bytes() for p in self.folder.rglob('*') if p.is_file()}
        doc = editor.EditorProject(self.folder / 'custom-map.json')
        self.assertFalse(doc.dirty)
        self.assertEqual(doc.extent, (1024, 1024))
        self.assertEqual(doc.forest_mode, 'Manual')
        self.assertEqual(before, {p.relative_to(self.folder): p.read_bytes() for p in self.folder.rglob('*') if p.is_file()})

    def test_import_png_preserves_original_and_uses_builder_dimensions(self):
        source = self.source(5, 9)
        original = source.read_bytes()
        self.document.import_heightmap(source, {'spacing_meters': 8})
        self.assertEqual((self.document.width, self.document.height), (5, 9))
        self.assertEqual(self.document.extent, (32, 64))
        self.assertEqual(self.document.elevation, (0, 1000))
        self.assertFalse(any(self.folder.glob('Terrain/source-*')))
        self.document.save()
        relative = self.document.manifest['build']['heightmap']['file']
        self.assertEqual((self.folder / relative).read_bytes(), original)
        self.assertEqual(source.read_bytes(), original)
        with contextlib.redirect_stdout(io.StringIO()):
            archive, record = projects.build(self.folder)
        self.assertEqual(record['manifest']['terrain']['source']['vertices'], [5, 9])
        self.assertEqual(record['manifest']['terrain']['elevation_meters'], [0, 1000])

    def test_square_raw_optional_dimensions_and_rectangular_partial_dimensions(self):
        self.document.import_heightmap(self.source(suffix='.r16'), {'spacing_meters': 8})
        self.assertEqual((self.document.width, self.document.height), (9, 9))
        self.assertIn('assumed square', self.document.assumptions[0])
        self.document.import_heightmap(self.source(5, 9, '.r16'), {'spacing_meters': 8, 'vertices': [5, None]})
        self.assertEqual((self.document.width, self.document.height), (5, 9))

    def test_failed_import_does_not_replace_document(self):
        before = copy.deepcopy(self.document.manifest)
        heights = self.document.heights[:]
        with self.assertRaisesRegex(ValueError, 'not a square'):
            self.document.import_heightmap(self.source(5, 9, '.r16'), {'spacing_meters': 8})
        self.assertEqual(self.document.manifest, before)
        self.assertEqual(self.document.heights, heights)
        self.assertFalse(self.document.pending)

    def test_south_to_north_rows_and_big_endian_import(self):
        path = self.root / 'north.r16'
        values = list(range(10, 25))
        path.write_bytes(struct.pack('>15H', *values))
        self.document.import_heightmap(path, {'spacing_meters': 8, 'vertices': [3, 5], 'format': 'r16be',
            'row_order': 'south_to_north', 'height_scale_meters': .1, 'height_offset_meters': 100})
        self.assertAlmostEqual(self.document.heights[0], 102.2)
        self.assertAlmostEqual(self.document.heights[-1], 101.2)

    def test_whole_brush_stroke_undo_redo_and_cancel(self):
        doc = self.document
        before = doc.heights[:]
        doc.begin_stroke('raise')
        doc.paint(0, 0, 'raise', 80, 10)
        doc.paint(8, 8, 'raise', 80, 10)
        doc.end_stroke()
        after = doc.heights[:]
        self.assertNotEqual(before, after)
        self.assertEqual(len(doc.history), 1)
        doc.undo()
        self.assertEqual(doc.heights, before)
        doc.redo()
        self.assertEqual(doc.heights, after)
        doc.begin_stroke('lower')
        doc.paint(0, 0, 'lower', 80, 20)
        doc.end_stroke(cancel=True)
        self.assertEqual(doc.heights, after)
        self.assertEqual(len(doc.history), 1)

    def test_cancelled_first_stroke_keeps_document_clean(self):
        doc = self.document
        before = doc.heights[:]
        doc.begin_stroke('raise')
        doc.paint(0, 0, 'raise', 80, 10)
        doc.end_stroke(cancel=True)
        self.assertFalse(doc.dirty)
        self.assertEqual(doc.heights, before)

    def test_level_and_smooth_move_only_within_brush_budget(self):
        doc = self.document
        before = doc.heights[:]
        self.brush('flatten', radius=40, strength=3, target=200)
        self.assertTrue(all(abs(a - b) <= 3.00001 for a, b in zip(before, doc.heights)))
        self.assertEqual(before[0], doc.heights[0])
        doc.undo()
        self.brush('smooth', radius=40, strength=2)
        self.assertTrue(all(abs(a - b) <= 2.00001 for a, b in zip(before, doc.heights)))

    def test_painted_heightmap_is_separate_and_reopens_with_same_units(self):
        doc = self.document
        source = self.source()
        original = source.read_bytes()
        doc.import_heightmap(source, {'spacing_meters': 8, 'elevation_meters': [800, 2200]})
        self.brush(strength=30)
        chosen = doc.heights[:]
        doc.save()
        self.assertEqual(source.read_bytes(), original)
        self.assertEqual((self.folder / 'Terrain/source-input.png').read_bytes(), original)
        settings = doc.manifest['build']['heightmap']
        self.assertTrue(settings['file'].startswith('Terrain/Editor/'))
        self.assertNotIn('elevation_meters', settings)
        reopened = editor.EditorProject(self.folder)
        for expected, actual in zip(chosen, reopened.heights):
            self.assertAlmostEqual(expected, actual, delta=(max(chosen) - min(chosen)) / 65535)
        self.assertEqual(reopened.extent, (64, 64))

    def test_repeated_save_reuses_edited_source_and_keeps_collision(self):
        doc = self.document
        collision = self.folder / 'Terrain/Editor/heightmap.r16'
        collision.parent.mkdir()
        collision.write_bytes(b'authored source')
        self.brush()
        doc.save()
        source = doc.manifest['build']['heightmap']['file']
        self.assertNotEqual(source, 'Terrain/Editor/heightmap.r16')
        self.brush()
        doc.save()
        self.assertEqual(source, doc.manifest['build']['heightmap']['file'])
        self.assertEqual(collision.read_bytes(), b'authored source')

    def test_manual_trees_stay_within_rectangle_and_compile_at_build(self):
        doc = self.document
        doc.import_heightmap(self.source(5, 9), {'spacing_meters': 8})
        doc.trees = []
        self.brush('trees', radius=100, tree_spacing=12)
        self.assertTrue(doc.trees)
        self.assertTrue(all(abs(p['x']) <= 16 and abs(p['y']) <= 32 for p in doc.trees))
        points = copy.deepcopy(doc.trees)
        doc.undo()
        self.assertEqual(doc.trees, [])
        doc.redo()
        self.assertEqual(doc.trees, points)
        doc.save()
        with contextlib.redirect_stdout(io.StringIO()):
            archive, _ = projects.build(self.folder)
        with zipfile.ZipFile(archive) as package:
            data = package.read('Vegetation/Generated/forest.skxy')
            self.assertEqual(struct.unpack_from('<I', data, 8)[0], len(points))
            self.assertNotIn('Vegetation/forest.json', package.namelist())

    def test_switch_to_automatic_preserves_manual_source_and_canonical_terrain(self):
        doc = self.document
        original = (self.folder / 'Terrain/heightmap.r16').read_bytes()
        self.brush('trees', radius=30)
        doc.set_forest_mode('Automatic')
        doc.save()
        self.assertEqual((self.folder / 'Terrain/heightmap.r16').read_bytes(), original)
        self.assertIn('forest', doc.manifest['build'])
        self.assertEqual(json.loads((self.folder / 'Vegetation/forest.json').read_text()), doc.trees)
        with contextlib.redirect_stdout(io.StringIO()):
            archive, _ = projects.build(self.folder)
        doc.accept_build()
        self.assertEqual(doc.forest_mode, 'Automatic')
        doc.set_forest_mode('None')
        doc.save()
        with contextlib.redirect_stdout(io.StringIO()):
            archive, _ = projects.build(self.folder)
        with zipfile.ZipFile(archive) as package:
            self.assertEqual(len(package.read('Vegetation/Generated/forest.skxy')), 12)

    def test_source_preview_avoids_applying_erosion_twice(self):
        doc = self.document
        source = self.source()
        options = {'spacing_meters': 8, 'elevation_meters': [800, 2200], 'processing': {'thermal_erosion': {'iterations': 2, 'max_delta_meters': 1}}}
        doc.import_heightmap(source, options)
        plain = editor.EditorProject(self.folder)
        plain.import_heightmap(source, {'spacing_meters': 8, 'elevation_meters': [800, 2200]})
        self.assertEqual(doc.heights, plain.heights)
        doc.save()
        with contextlib.redirect_stdout(io.StringIO()):
            projects.build(self.folder)
        doc.accept_build()
        self.assertNotEqual(doc.built[3], doc.heights)

    def test_save_preserves_metadata_and_script_and_detects_external_changes(self):
        doc = self.document
        doc.manifest['metadata']['tags'] = ['native-editor', 'mountain']
        doc.set_script(doc.script + '\n-- Authored in the desktop editor\n')
        doc.save()
        self.assertIn('Authored in the desktop editor', (self.folder / doc.script_path).read_text())
        self.assertEqual(json.loads(doc.path.read_text())['metadata']['tags'], ['native-editor', 'mountain'])
        doc.path.write_text(doc.path.read_text() + ' ')
        external = doc.path.read_bytes()
        self.brush()
        with self.assertRaisesRegex(ValueError, 'changed outside'):
            doc.save()
        self.assertEqual(doc.path.read_bytes(), external)
        self.assertFalse((self.folder / 'Terrain/Editor/heightmap.r16').exists())

    def test_source_path_traversal_and_invalid_dimensions_are_rejected(self):
        with self.assertRaises(ValueError):
            self.document.source_path('../escape.r16')
        draft = copy.deepcopy(self.document.manifest)
        self.document.ensure_source()
        draft = copy.deepcopy(self.document.manifest)
        draft['build']['heightmap']['vertices'] = [5, 9]
        before = copy.deepcopy(self.document.manifest)
        with self.assertRaises(ValueError):
            self.document.update_settings(draft)
        self.assertEqual(before, self.document.manifest)

    def test_default_options_can_be_applied_after_painting(self):
        source = self.source()
        doc = self.document
        doc.import_heightmap(source, {'spacing_meters': 8})
        self.brush()
        draft = copy.deepcopy(doc.manifest)
        draft['build']['heightmap'].update(format='png16', row_order='north_to_south', vertices=[9, 9])
        doc.update_settings(draft)
        doc.save()


class EditorCommandTests(unittest.TestCase):
    def test_editor_dispatch_does_not_configure_game(self):
        with patch.object(editor, 'launch', return_value=0) as launch, patch.object(cli.desktop, 'configure', side_effect=AssertionError('editor must not configure Steam')):
            self.assertEqual(cli.main(['editor', 'my project']), 0)
            launch.assert_called_once_with(Path('my project'))

    def test_editor_without_project_uses_startup_preferences_even_in_a_project_folder(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder=Path(temporary);projects.create('map',folder)
            with patch.object(editor,'launch',return_value=0) as launch, patch.object(cli.Path,'cwd',return_value=folder):
                self.assertEqual(cli.main(['editor']),0)
                launch.assert_called_once_with(None)


if __name__ == '__main__':
    unittest.main()
