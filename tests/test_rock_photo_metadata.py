from datetime import datetime, timedelta, timezone
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image, TiffImagePlugin

from tools.rock_photo_metadata import coordinate, geographic_anchors, project_geographic, read_metadata, solar_enu


class PhotoMetadataTests(unittest.TestCase):
    def test_coordinates_validate_components_and_hemisphere(self):
        self.assertAlmostEqual(coordinate([44, 53, 49], 'N', 'N', 'S'), 44.8969444444)
        self.assertAlmostEqual(coordinate([5, 33, 25], b'W', 'E', 'W'), -5.5569444444)
        for parts, hemisphere in [([44, 60, 0], 'N'), ([44, 0, -1], 'N'),
                                 ([44, 0, float('nan')], 'N'), ([44, 0], 'N'), ([44, 0, 0], 'E')]:
            with self.assertRaises(ValueError):
                coordinate(parts, hemisphere, 'N', 'S')

    def test_real_exif_gps_time_is_utc_and_altitude_is_not_used(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)/'gps.jpg'
            rational = TiffImagePlugin.IFDRational
            exif = Image.Exif()
            exif[274] = 6  # The returned dimensions follow the oriented image.
            exif[34853] = {1: 'N', 2: tuple(map(rational, [44, 53, 49])),
                3: 'E', 4: tuple(map(rational, [5, 33, 25])), 5: b'\x01', 6: rational(0),
                7: tuple(map(rational, [9, 30, 35])), 29: '2025:01:18'}
            exif[34665] = {36867: '2025:01:18 10:30:53', 41989: 26, 37386: rational(4.2)}
            Image.new('RGB', (20, 10)).save(source, exif=exif)
            metadata = read_metadata(source)
            self.assertEqual(metadata['image_size'], [10, 20])
            self.assertEqual(metadata['gps_datetime_utc'], '2025-01-18T09:30:35+00:00')
            self.assertEqual(metadata['camera_datetime_local'], '2025:01:18 10:30:53')
            self.assertFalse(metadata['gps_altitude_used'])
            self.assertEqual(metadata['focal_equivalent_35mm'], 26)
            Image.new('RGB', (20, 10)).save(source)
            self.assertEqual(read_metadata(source), {'image_size': [20, 10]})

    def test_solar_vector_timezone_invariance_and_equinox(self):
        utc = datetime(2025, 3, 20, 12, tzinfo=timezone.utc)
        noon = solar_enu(0, 0, utc)
        self.assertGreater(noon[2], 0.999)
        np.testing.assert_allclose(np.linalg.norm(noon), 1, atol=1e-12)
        np.testing.assert_allclose(solar_enu(0, 0, utc.astimezone(timezone(timedelta(hours=2)))), noon)
        self.assertGreater(solar_enu(0, 0, utc-timedelta(hours=3))[0], 0)
        self.assertLess(solar_enu(0, 0, utc+timedelta(hours=3))[0], 0)
        self.assertLess(solar_enu(0, 0, utc-timedelta(hours=12))[2], -0.99)
        with self.assertRaises(ValueError):
            solar_enu(0, 0, utc.replace(tzinfo=None))

    def test_projection_error_is_actionable(self):
        with self.assertRaises(ValueError):
            project_geographic([(44, 5)], 'untrusted projection')
        with patch('tools.rock_photo_metadata.subprocess.run',
                   side_effect=subprocess.CalledProcessError(1, ['cs2cs'])):
            with self.assertRaisesRegex(ValueError, 'PROJ'):
                project_geographic([(44, 5)], 'EPSG:2154')

    @unittest.skipUnless(shutil.which('cs2cs'), 'GPS reprojection requires PROJ cs2cs')
    def test_gps_matches_map_axes_and_solar_grid_convergence(self):
        metadata = {'latitude': 44.89694444444444, 'longitude': 5.5569444444444445,
            'gps_datetime_utc': '2025-01-18T09:30:35+00:00', 'gps_altitude_meters': 0,
            'focal_equivalent_35mm': 26, 'image_size': [4032, 2268]}
        result = geographic_anchors(metadata, {'projection': 'EPSG:2154',
            'center': {'easting': 901000, 'northing': 6424000}})
        np.testing.assert_allclose(result['position_xy_meters'], [820.9909, -1240.9074], atol=0.02)
        direction = np.array(result['light_direction_world'])
        self.assertTrue(np.all(direction > 0))  # Sun east, south and above the horizon.
        self.assertAlmostEqual(np.linalg.norm(direction), 1, places=12)
        self.assertAlmostEqual(result['sun_altitude_degrees'], 17.34365, places=4)
        self.assertAlmostEqual(result['sun_azimuth_degrees'], 146.57960, places=4)
        true_direction = solar_enu(metadata['latitude'], metadata['longitude'],
                                  datetime.fromisoformat(metadata['gps_datetime_utc']))
        self.assertGreater(abs(direction[0]-true_direction[0]), 0.01)  # Lambert convergence matters.
        self.assertEqual(result['initial_focal_pixels'], 2912)


if __name__ == '__main__':
    unittest.main()
