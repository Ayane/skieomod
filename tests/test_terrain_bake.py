import contextlib
import io
import json
import math
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from tools import skieo_bake as bake, skieo_project as projects
from tests.test_heightmap_build import png16


def decode_forest(data):
    magic, version, count = struct.unpack('<4sII', data[:12])
    assert magic == b'SKXY' and version == 1 and len(data) == 12 + count * 8
    return [{'x': x / 100, 'y': y / 100} for x, y in struct.iter_unpack('<ff', data[12:])]


class ProcessingTests(unittest.TestCase):
    def test_smoothing_reduces_spike_and_respects_budget_and_perimeter(self):
        values = [100.] * 81
        values[40] = 140.
        result, report = bake.terrain_processing(values, 9, 9, 1,
            {'smoothing': {'iterations': 20, 'strength': .8, 'max_delta_meters': 3}})
        self.assertEqual(result[40], 137.)
        self.assertGreater(result[39], 100)
        self.assertLessEqual(report['measured_max_delta_meters'], 3)
        self.assertEqual(list(result[:9]), values[:9])

    def test_erosion_moves_material_downhill_and_conserves_mass(self):
        values = [100.] * 81
        values[40] = 140.
        for method in ['thermal_erosion', 'hydraulic_erosion']:
            with self.subTest(method=method):
                result, report = bake.terrain_processing(values, 9, 9, 8,
                    {method: {'iterations': 10, 'strength': .5, 'max_delta_meters': 4}})
                self.assertLess(result[40], values[40])
                self.assertTrue(any(a > b for a, b in zip(result, values)))
                self.assertAlmostEqual(sum(result), sum(values), places=8)
                self.assertLessEqual(report['measured_max_delta_meters'], 4 + 1e-10)

    def test_drainage_uses_steepest_descent_and_accumulates_downstream(self):
        values = [100 - x for y in range(5) for x in range(5)]
        targets, slopes, area = bake.drainage(values, 5, 5, 2, 2)
        self.assertEqual(targets[11], 12)
        self.assertEqual(slopes[11], .5)
        self.assertEqual(area[13], 3)
        self.assertEqual(targets[14], -1)
        self.assertEqual(area[14], 4)

    def test_noise_is_seeded_bounded_and_preserves_border(self):
        values = [100.] * 81
        options = {'noise': {'amplitude_meters': 2, 'wavelength_meters': 4, 'seed': 42}}
        result, _ = bake.terrain_processing(values, 9, 9, 1, options)
        other, _ = bake.terrain_processing(values, 9, 9, 1, options)
        self.assertEqual(result, other)
        self.assertLessEqual(max(abs(a - b) for a, b in zip(result, values)), 2)
        self.assertEqual(list(result[:9]), values[:9])
        options['noise']['seed'] = 43
        self.assertNotEqual(result, bake.terrain_processing(values, 9, 9, 1, options)[0])

    def test_coarse_correction_retains_fine_source_detail(self):
        values = [100 + (20 if x % 2 else 0) for y in range(65) for x in range(65)]
        result, report = bake.terrain_processing(values, 65, 65, 1,
            {'resolution': 33, 'smoothing': {'iterations': 2}})
        self.assertEqual(report['analysis_vertices'], [33, 33])
        self.assertEqual(list(result), values)  # coarse vertices are flat; fine teeth survive


class ForestCompilationTests(unittest.TestCase):
    def test_json_is_compiled_to_float32_centimetres(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'forest.json'
            source.write_text('\ufeff[{"x":10.5,"y":-20},{"x":0,"y":0}]')
            binary, count = bake.compile_forest(root, {'file': 'forest.json'})
            self.assertEqual(count, 2)
            self.assertEqual(binary, struct.pack('<4sIIffff', b'SKXY', 1, 2, 1050, -2000, 0, 0))
            self.assertEqual(bake.encode_forest([]), struct.pack('<4sII', b'SKXY', 1, 0))

    def test_invalid_json_and_unsafe_source_paths_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'forest.json'
            cases = ['{}', '[null]', '[12]', '[{"x":"1","y":2}]', '[{"x":true,"y":2}]',
                '[{"x":1}]', '[{"x":1,"y":2,"z":3}]', '[{"x":1e999,"y":2}]',
                '[{"x":1e37,"y":2}]', '[{"x":1,"x":2,"y":3}]', '[{"x":NaN,"y":2}]',
                '[{"x":1,"y":2},]']
            for text in cases:
                with self.subTest(text=text):
                    source.write_text(text)
                    with self.assertRaises(ValueError):
                        bake.compile_forest(root, {'file': 'forest.json'})
            with self.assertRaises(ValueError):
                bake.compile_forest(root, {'file': '../forest.json'})


class BakeBuildTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.project = Path(self.temporary.name) / 'project'
        projects.create('map', self.project, 'Baked terrain', 'test.baked')
        self.width, self.height = 65, 49
        self.values = [round(65535 * (x + y) / (self.width + self.height - 2))
                       for y in range(self.height) for x in range(self.width)]
        self.source = self.project / 'Terrain/source.png'
        self.source.write_bytes(png16(self.width, self.height, self.values))
        self.metadata = self.project / 'custom-map.json'
        self.manifest = json.loads(self.metadata.read_text())
        self.manifest['build'] = {
            'heightmap': {'file': 'Terrain/source.png', 'spacing_meters': 8, 'elevation_meters': [800, 900],
                         'processing': {'thermal_erosion': {'iterations': 2, 'talus_degrees': 2, 'max_delta_meters': 1}}},
            'vegetation': {'biome': {'tree_line_meters': 1000, 'alpine_line_meters': 1300, 'moisture': 1},
                'trees': {'seed': 42, 'density_per_hectare': 500, 'min_spacing_meters': 4,
                          'patchiness': 0, 'tree_line_fade_meters': 10, 'max_slope_degrees': 30},
                'ground_cover': {'texture_size': 32}}}

    def build(self, **options):
        self.metadata.write_text(json.dumps(self.manifest))
        with contextlib.redirect_stdout(io.StringIO()):
            return projects.build(self.project, **options)

    def test_package_contains_baked_trees_ground_cover_and_complete_mips(self):
        original_script = (self.project / 'Scripts/main.lua').read_bytes()
        original_forest = (self.project / 'Vegetation/forest.json').read_bytes()
        path, release = self.build()
        with zipfile.ZipFile(path) as package:
            trees = decode_forest(package.read('Vegetation/Generated/forest.skxy'))
            self.assertGreater(len(trees), 100)
            for p in trees:
                self.assertLess(abs(p['x']), 256)
                self.assertLess(abs(p['y']), 192)
            self.assertNotIn('Vegetation/forest.json', package.namelist())
            definition = release['manifest']['terrain']['textures']['albedo']
            self.assertEqual(len(definition['mips']), 5)
            for level, file in enumerate([definition['file'], *definition['mips']]):
                self.assertEqual(struct.unpack('>II', package.read(file)[16:24]), (32 >> level,) * 2)
            runtime = release['manifest']['terrain']['runtime']
            self.assertEqual(runtime['uv_tile_meters'], 512)
            self.assertIn('M_Prop_albtex', runtime['material'])
            report = json.loads(package.read('Terrain/Generated/build-report.json'))
            self.assertEqual(report['vegetation']['tree_count'], len(trees))
            self.assertNotIn('build', release['manifest'])
        self.assertEqual((self.project / 'Scripts/main.lua').read_bytes(), original_script)
        self.assertEqual((self.project / 'Vegetation/forest.json').read_bytes(), original_forest)
        working = json.loads(self.metadata.read_text())
        self.assertEqual(working['script']['entry'], 'Scripts/main.lua')
        self.assertNotIn('textures', working['terrain'])

    def test_final_terrain_encoding_matches_processed_physical_heights_and_preview(self):
        path, release = self.build()
        terrain = release['manifest']['terrain']
        encoded = struct.unpack('<' + 'H' * len(self.values), (self.project / 'Terrain/heightmap.r16').read_bytes())
        scale, offset = terrain['source']['height_scale_meters'], terrain['source']['height_offset_meters']
        expected, _ = bake.terrain_processing([800 + v * 100 / 65535 for v in self.values], self.width, self.height, 8,
                                             self.manifest['build']['heightmap']['processing'])
        self.assertLessEqual(max(abs(v * scale + offset - e) for v, e in zip(encoded, expected)), scale / 2 + 1e-9)
        self.assertEqual(terrain['elevation_meters'], [min(expected), max(expected)])
        self.assertEqual(terrain['preview']['samples'][8][8], round(encoded[24 * 65 + 32] / 65535, 5))

    def test_trees_obey_spacing_exclusions_and_tree_line(self):
        self.manifest['build']['vegetation']['trees']['exclude'] = [[-50, -192, 50, 192]]
        self.manifest['build']['vegetation']['biome']['tree_line_meters'] = 860
        _, release = self.build()
        trees = decode_forest((self.project / 'Vegetation/Generated/forest.skxy').read_bytes())
        self.assertGreater(len(trees), 10)
        terrain = release['manifest']['terrain']
        samples = struct.unpack('<' + 'H' * len(self.values), (self.project / 'Terrain/heightmap.r16').read_bytes())
        for i, point in enumerate(trees):
            self.assertFalse(-50 <= point['x'] <= 50)
            sample = bake.interpolate(samples, 65, 49, (point['x'] + 256) / 8, (point['y'] + 192) / 8)
            self.assertLess(sample * terrain['source']['height_scale_meters'] + terrain['source']['height_offset_meters'], 860)
            for other in trees[i + 1:]:
                self.assertGreaterEqual(math.hypot(point['x'] - other['x'], point['y'] - other['y']), 4 - .001)

    def test_row_order_does_not_mirror_generated_forest(self):
        self.manifest['build']['heightmap'].pop('processing')
        self.build()
        first = (self.project / 'Vegetation/Generated/forest.skxy').read_bytes()
        reverse = [v for y in range(self.height - 1, -1, -1) for v in self.values[y * self.width:(y + 1) * self.width]]
        self.source.write_bytes(png16(self.width, self.height, reverse))
        self.manifest['build']['heightmap']['row_order'] = 'south_to_north'
        self.build()
        self.assertEqual((self.project / 'Vegetation/Generated/forest.skxy').read_bytes(), first)

    def test_repeated_build_and_test_are_reproducible_and_read_only(self):
        path, _ = self.build()
        before = path.read_bytes()
        files = [self.metadata, self.source, *(self.project / 'Terrain/Generated').glob('*'),
                 *(self.project / 'Vegetation/Generated').glob('*'), self.project / 'Terrain/heightmap.r16']
        original = {p: p.read_bytes() for p in files}
        backups = len(list((self.project / '.heightmap-backups').iterdir()))
        with contextlib.redirect_stdout(io.StringIO()):
            projects.build(self.project)
            projects.build(self.project, Path(self.temporary.name) / 'readonly.skieomap', save_build_metadata=False)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(len(list((self.project / '.heightmap-backups').iterdir())), backups)
        for file, data in original.items():
            self.assertEqual(file.read_bytes(), data)

    def test_disable_vegetation_restores_material_and_clears_unconfigured_forest(self):
        self.build()
        self.manifest['build']['vegetation']['trees']['enabled'] = False
        self.manifest['build']['vegetation']['ground_cover']['enabled'] = False
        path, release = self.build()
        self.assertIn('skieomod-generated-vegetation.lua', release['manifest']['script']['entry'])
        self.assertNotIn('textures', release['manifest']['terrain'])
        with zipfile.ZipFile(path) as package:
            self.assertEqual(len(decode_forest(package.read('Vegetation/Generated/forest.skxy'))), 0)
            self.assertNotIn('Terrain/Generated/albedo.png', package.namelist())

    def test_disabled_automatic_trees_compile_manual_source_again(self):
        self.manifest['build']['forest'] = {'file': 'Vegetation/forest.json'}
        self.build()
        self.manifest['build']['vegetation']['trees']['enabled'] = False
        path, _ = self.build()
        with zipfile.ZipFile(path) as package:
            self.assertEqual(len(decode_forest(package.read('Vegetation/Generated/forest.skxy'))), 3)

    def test_tree_limit_returns_deterministic_subset(self):
        self.manifest['build']['vegetation']['trees']['max_trees'] = 17
        self.build()
        forest = (self.project / 'Vegetation/Generated/forest.skxy').read_bytes()
        report = json.loads((self.project / 'Terrain/Generated/build-report.json').read_text())
        self.assertEqual(len(decode_forest(forest)), 17)
        self.assertTrue(report['vegetation']['tree_limit_reached'])
        self.build()
        self.assertEqual((self.project / 'Vegetation/Generated/forest.skxy').read_bytes(), forest)

    def test_capped_forest_covers_entire_rectangular_heightmap(self):
        width, height = 33, 97
        values = [round(65535 * (x + y) / (width + height - 2))
                  for y in range(height) for x in range(width)]
        self.source.write_bytes(png16(width, height, values))
        self.manifest['build']['heightmap'].pop('processing')
        self.manifest['build']['vegetation']['trees']['max_trees'] = 80
        self.build()
        points = decode_forest((self.project / 'Vegetation/Generated/forest.skxy').read_bytes())
        report = json.loads((self.project / 'Terrain/Generated/build-report.json').read_text())
        self.assertTrue(report['vegetation']['tree_limit_reached'])
        self.assertEqual(len(points), 80)
        manifest = json.loads(self.metadata.read_text())
        size_x, size_y = manifest['terrain']['size_meters']
        self.assertEqual([size_x, size_y], [256, 768])
        for axis, extent in [('x', size_x), ('y', size_y)]:
            coords = [point[axis] for point in points]
            self.assertGreater(max(coords) - min(coords), extent * .85)
            self.assertGreaterEqual(min(coords), -extent / 2)
            self.assertLessEqual(max(coords), extent / 2)
        # A heightmap's shorter side must not clip the longer side to a square;
        # nor may max_trees keep only the first rows scanned by the generator.
        self.assertTrue(any(p['y'] < -size_x / 2 for p in points))
        self.assertTrue(any(p['y'] > size_x / 2 for p in points))
        for band in range(3):
            self.assertTrue(any(-size_y / 2 + band * size_y / 3 <= p['y']
                                < -size_y / 2 + (band + 1) * size_y / 3 for p in points))

    def test_invalid_options_are_rejected_before_source_mutation(self):
        cases = [('processing', {'thermal_erosion': {'strength': 1.1}}), ('processing', {'smoothing': {'iterations': True}}),
                 ('processing', {'unknown': {}}), ('vegetation', {'trees': {'density_per_hectare': -1}}),
                 ('vegetation', {'trees': {'seed': True}}), ('vegetation', {'ground_cover': {'texture_size': 33}}),
                 ('vegetation', {'biome': {'moisture': float('nan')}}), ('vegetation', {'biome': {'tree_line_meters': 3000}}),
                 ('vegetation', {'trees': {'exclude': [[0, 0, -1, 1]]}}), ('vegetation', {'trees': {'enabled': 1}})]
        for location, value in cases:
            with self.subTest(value=value):
                if location == 'processing':
                    self.manifest['build']['heightmap']['processing'] = value
                    self.manifest['build'].pop('vegetation', None)
                else:
                    self.manifest['build']['heightmap'].pop('processing', None)
                    self.manifest['build']['vegetation'] = value
                original = (self.project / 'Terrain/heightmap.r16').read_bytes()
                with self.assertRaises(ValueError):
                    self.build()
                self.assertEqual((self.project / 'Terrain/heightmap.r16').read_bytes(), original)
                self.assertFalse((self.project / '.heightmap-backups').exists())

    def test_archive_commit_failure_rolls_back_all_baked_assets(self):
        path, _ = self.build()
        files = [self.metadata, path, *(self.project / 'Terrain/Generated').glob('*'),
                 *(self.project / 'Vegetation/Generated').glob('*'), self.project / 'Terrain/heightmap.r16']
        self.manifest['build']['vegetation']['trees']['seed'] = 43
        self.metadata.write_text(json.dumps(self.manifest))
        before = {p: p.read_bytes() for p in files}
        replace = Path.replace
        def fail_archive(file, target):
            if file.name.endswith('.part'):
                raise OSError('simulated archive commit failure')
            return replace(file, target)
        with patch.object(Path, 'replace', fail_archive), self.assertRaises(OSError):
            with contextlib.redirect_stdout(io.StringIO()):
                projects.build(self.project)
        for file, data in before.items():
            self.assertEqual(file.read_bytes(), data)

    @unittest.skipUnless(shutil.which('lua'), 'Lua interpreter unavailable')
    def test_generated_script_works_in_loader_sandbox_and_loads_once_per_session(self):
        self.build()
        wrapper = self.project / 'Scripts/skieomod-generated-vegetation.lua'
        harness = '''
package.path = "mod/SkiEO-CustomMaps/Scripts/?.lua;" .. package.path
local Api = require("api")
local allowed = {type=type, error=error, ipairs=ipairs, pairs=pairs, math=math, string=string, table=table}
local script = assert(loadfile(arg[1], "t", allowed))()
local count, logs = 0, 0
local host = {log=function() logs=logs+1 end, load_forest_skxy=function(bytes,session,options,done)
    assert(bytes == "generated trees"); count=count+1; done()
end}
for session=1,2 do
    local api = Api.new(host, {id="test.baked",script={permissions={"gameplay"}},
        content={assets={"Vegetation/Generated/forest.skxy"}},__read=function(path)
            assert(path=="Vegetation/Generated/forest.skxy"); return "generated trees"
        end})
    script(api)
    api:_emit("map.ready",{})
    assert(count==session, "forest loaded twice or not loaded")
end
assert(logs==2, "authored callbacks lost")
'''
        harness_path = Path(self.temporary.name) / 'harness.lua'
        harness_path.write_text(harness)
        subprocess.run(['lua', str(harness_path), str(wrapper)], check=True, capture_output=True)


if __name__ == '__main__':
    unittest.main()
