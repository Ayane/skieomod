"""Rectangular geographic preparation and forest preservation, without downloads."""
from array import array
import json
from pathlib import Path
import struct
import tempfile
import unittest

from tools.build_veymont_geodata import Grid, world_xy, sample_height, fill_polygon, write_forest

try:
    from tools import prepare_heightmap as preparation
except ModuleNotFoundError:
    preparation = None


class GeographicGridTests(unittest.TestCase):
    def test_rectangular_projection_height_interpolation_and_forest_mask(self):
        grid = Grid(3, 4, 400, 900000, 6424000, -400, -600, 10000, 2)
        heights = array('H', range(12))
        self.assertEqual(world_xy((900008, 6423988), grid), (400, 600))
        self.assertEqual(sample_height(heights, 400, 600, grid), 10022)
        self.assertEqual(sample_height(heights, -200, 0, grid), 10010)
        mask = bytearray(12)
        fill_polygon(mask, [(0, 2), (3, 2), (3, 4), (0, 4)], 1, grid)
        self.assertEqual(mask, b'\0' * 6 + b'\1' * 6)

    def test_forest_expansion_retains_points_and_adds_only_outside_old_extent(self):
        grid = Grid(5, 9, 400, 0, 0, -800, -1600, 0, 1)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            old = root / 'old.skxy'
            points = struct.pack('<ffff', 30, 20, -400, -400)
            old.write_bytes(struct.pack('<4sII', b'SKXY', 1, 2) + points)
            previous = root / 'previous.json'
            previous.write_text(json.dumps({'terrain': {'origin_centimeters': [-800, -800, 0],
                                                       'size_meters': [16, 16]}}))
            target = root / 'expanded.skxy'
            eligible = array('I', range(45))
            self.assertEqual(write_forest(target, eligible, grid, 102, old, previous), 2)
            data = target.read_bytes()
            self.assertEqual(data[12:28], points)
            for x, y in struct.iter_unpack('<ff', data[28:]):
                self.assertTrue(-800 <= x <= 800 and -1600 <= y <= 1600)
                self.assertGreater(abs(y), 800)
            write_forest(target, eligible, grid, 102, old, previous)
            self.assertEqual(target.read_bytes(), data)
            invalid = root / 'invalid.skxy'
            with self.assertRaises(ValueError):
                write_forest(invalid, eligible, grid, 1, old, previous)
            self.assertFalse(invalid.exists())


@unittest.skipIf(preparation is None, 'LiDAR preparation requires NumPy and GDAL')
class RasterPreparationTests(unittest.TestCase):
    def test_rectangular_extent_is_configurable_and_mismatch_is_rejected(self):
        config = {'terrain': {'vertices_x': 2001, 'vertices_y': 1501, 'spacing_meters': 8,
                              'extent_meters': [16000, 12000],
                              'bounds_east_north': [900000, 6400000, 916000, 6412000]}}
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'map.json'
            path.write_text(json.dumps(config))
            result = preparation.read_config(path)
            self.assertEqual(preparation.expected_geotransform(result),
                             (899996, 8, 0, 6412004, 0, -8))
            for extent in ([16000, 16000], [16000, float('nan')]):
                config['terrain']['extent_meters'] = extent
                path.write_text(json.dumps(config))
                with self.assertRaises(ValueError): preparation.read_config(path)

    def test_rectangular_r16_encoding_preserves_elevations_and_declared_spacing(self):
        import numpy as np
        values = np.array([[800, 850, 900], [1000, 1200, 2100]])
        encoded, metadata = preparation.encode_unreal(values, spacing=8)
        self.assertEqual(encoded.shape, (2, 3))
        self.assertEqual(len(encoded.tobytes()), 12)
        self.assertEqual(metadata['landscape_scale_x_y'], 800)
        decoded = metadata['actor_location_z_centimeters'] / 100 + (
            encoded.astype(float) - 32768) * metadata['landscape_scale_z'] / 12800
        self.assertLess(float(np.abs(decoded - values).max()), .02)


if __name__ == '__main__':
    unittest.main()
