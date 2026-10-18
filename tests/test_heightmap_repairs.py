"""Terrain repairs keep the existing grid, encoding and unaffected samples."""
from pathlib import Path
import tempfile
import unittest

try:
    import numpy as np
    from osgeo import gdal, osr
    from tools.repair_heightmap import replace_region
except ModuleNotFoundError:
    replace_region = None


@unittest.skipIf(replace_region is None, 'Terrain repairs require NumPy and GDAL')
class HeightmapRepairTests(unittest.TestCase):
    def source(self, path, missing=False):
        dataset = gdal.GetDriverByName('GTiff').Create(str(path), 11, 11, 1, gdal.GDT_Float32)
        dataset.SetGeoTransform((-2, 4, 0, 42, 0, -4))
        crs = osr.SpatialReference(); crs.ImportFromEPSG(2154)
        dataset.SetProjection(crs.ExportToWkt())
        elevations = np.full((11, 11), 200, dtype=np.float32)
        if missing: elevations[5, 5] = -32767
        dataset.GetRasterBand(1).SetNoDataValue(-32767)
        dataset.GetRasterBand(1).WriteArray(elevations)
        dataset.FlushCache()

    def test_authoritative_core_smooth_margin_and_unchanged_surroundings(self):
        gdal.UseExceptions()
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'replacement.tif'
            self.source(path)
            original = np.full((11, 11), 100.0)
            result = replace_region(original, (-2, 4, 0, 42, 0, -4), path, [16, 16, 24, 24], 8)
            np.testing.assert_array_equal(result[4:7, 4:7], 200)
            self.assertEqual(result[3, 5], 150)
            self.assertEqual(result[2, 5], 100)
            np.testing.assert_array_equal(result[:3], original[:3])
            np.testing.assert_array_equal(original, 100)

    def test_missing_replacement_data_is_rejected(self):
        gdal.UseExceptions()
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'incomplete.tif'
            self.source(path, missing=True)
            with self.assertRaisesRegex(ValueError, 'missing or invalid'):
                replace_region(np.full((11, 11), 100.0), (-2, 4, 0, 42, 0, -4),
                               path, [16, 16, 24, 24], 8)


if __name__ == '__main__':
    unittest.main()
