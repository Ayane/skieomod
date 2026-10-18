from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
from PIL import Image

from tools import extract_rock_surface as rock
from tools.rock_registration import Camera, intersect_photo_rays, projected_skyline, sample_photo, visible_surface
from tools.register_rock_photo import camera_from_parameters, fit_camera, surface_profile, terrain_points


def field_fixture(root: Path, values: np.ndarray, scale: float = 0.01):
    h, w = values.shape
    np.rint(values/scale).astype('<u2').tofile(root/'heightmap.r16')
    definition = {'terrain': {'size_meters': [w-1, h-1], 'origin_centimeters': [0, 0, 0],
        'source': {'file': 'heightmap.r16', 'format': 'r16le', 'vertices': [w, h],
                   'spacing_meters': 1, 'height_scale_meters': scale, 'height_offset_meters': 0}}}
    (root/'map.json').write_text(json.dumps(definition))
    return rock.Heightfield(root/'map.json')


class RockRegistrationTests(unittest.TestCase):
    def test_connected_skyline_bridges_sparse_vertices_without_false_notches(self):
        camera = Camera({'position_meters': [0, 0, 0], 'forward': [1, 0, 0],
                         'focal_pixels': 20}, (64, 64))
        grid = np.array([[[10, -10, 3], [20, -10, 3]],
                         [[10, 10, 3], [20, 10, 3]]], dtype=float)
        xs, ys = projected_skyline(grid, camera)
        np.testing.assert_allclose(xs, np.arange(13, 52, 2))
        np.testing.assert_allclose(ys, 26)
        sparse_x, _ = projected_skyline(grid.reshape(-1, 3), camera)
        self.assertLess(len(sparse_x), len(xs))
        outside = grid.copy(); outside[..., 0] *= -1
        self.assertEqual(len(projected_skyline(outside, camera)[0]), 0)

    def test_bounded_camera_roll_rotates_photo_projection_about_its_center(self):
        with tempfile.TemporaryDirectory() as directory:
            field = field_fixture(Path(directory), np.ones((17, 17))*20)
            search = {'aim_meters': [15, 8, 20]}
            baseline = camera_from_parameters(np.array([8, 8, 0, 0, 100]), field, search, (128, 128))
            rotated = camera_from_parameters(np.array([8, 8, 0, 0, 100, np.pi/12]), field, search, (128, 128))
            point = np.array([baseline.position+[10, 1, 0]])
            before, _ = baseline.project(point); after, _ = rotated.project(point)
            np.testing.assert_allclose(before, [[74, 64]])
            np.testing.assert_allclose(after, [[64+10*np.cos(np.pi/12), 64-10*np.sin(np.pi/12)]])
            np.testing.assert_allclose(rotated.position, baseline.position)

    def test_selected_photo_pixel_produces_a_world_anchored_wall_patch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            y, x = np.mgrid[0:33, 0:33]
            field = field_fixture(root, 60-1.5*x)
            camera = Camera({'position_meters': [30, 16, 34], 'forward': [-1, 0, 0],
                             'focal_pixels': 100}, (128, 128))
            template = {'version': 1, 'surface': {'max_displacement_meters': 0.3},
                'views': [{'file': 'unused', 'crop': [0, 0, 10, 10]}],
                'exclude_polygons_uv': [[[0, 0], [1, 0], [1, 1]]],
                'snow_cue': {'weight': 0.35, 'polygons_uv': [[[0, 0], [1, 0], [1, 1]]]}}
            profile = surface_profile(template, field, camera, [64, 64], [8, 6],
                root/'photo.png', root/'map.json', root/'camera.json', [1, 0, 0.2])
            target = profile['patch_selection']['heightfield_point_meters']
            np.testing.assert_allclose(target, [26/1.5, 16, 34], atol=1e-5)
            np.testing.assert_allclose(profile['surface']['axes'], [[0, 1, 0], [0, 0, 1]])
            np.testing.assert_allclose(profile['views'][0]['light_direction'], [0, 0.2, 1])
            self.assertNotIn('crop', profile['views'][0])
            self.assertNotIn('exclude_polygons_uv', profile)
            self.assertNotIn('polygons_uv', profile['snow_cue'])
            self.assertEqual(template['views'][0]['crop'], [0, 0, 10, 10])
            field.values[:] = 0
            with self.assertRaisesRegex(ValueError, 'does not intersect'):
                surface_profile(template, field, camera, [64, 64], [8, 6],
                    root/'photo.png', root/'map.json', root/'camera.json')

    def test_camera_matches_east_south_up_and_round_trips_rays(self):
        camera = Camera({'position_meters': [0, 0, 10], 'forward': [1, 0, 0],
                         'focal_pixels': 100, 'principal_pixels': [50, 40]}, (100, 80))
        points = np.array([[10, 1, 10], [10, 0, 11], [10, -1, 9], [-10, 0, 10]])
        pixels, valid = camera.project(points)
        np.testing.assert_allclose(pixels[:3], [[60, 40], [50, 30], [40, 50]])
        np.testing.assert_array_equal(valid, [True, True, True, False])
        direction = points[:3]-camera.position
        direction /= np.linalg.norm(direction, axis=-1, keepdims=True)
        np.testing.assert_allclose(camera.rays(pixels[:3]), direction)
        # West-facing photographs have north (negative map Y) on their right.
        west = Camera({'position_meters': [10, 0, 10], 'forward': [-1, 0, 0],
                       'focal_pixels': 100, 'principal_pixels': [50, 40]}, (100, 80))
        pixel, valid = west.project(np.array([[0, -1, 10]]))
        np.testing.assert_allclose(pixel, [[60, 40]])
        self.assertTrue(valid.all())

    def test_camera_rejects_invalid_intrinsics_and_parallel_axes(self):
        basic = {'position_meters': [0, 0, 10], 'forward': [1, 0, 0], 'focal_pixels': 100}
        for update in [{'focal_pixels': 0}, {'focal_pixels': [100, float('nan')]},
                       {'forward': [0, 0, 1]}, {'position_meters': [0, float('nan'), 0]}]:
            with self.assertRaises(ValueError):
                Camera(basic | update, (100, 80))

    def test_bilinear_photo_sampling_never_uses_outside_pixels(self):
        y, x = np.mgrid[0:4, 0:4]
        rgb = np.stack([x/4, y/4, np.ones(x.shape)], axis=-1)
        sampled, valid = sample_photo(rgb, np.array([[1.5, 2.5], [-1, 0], [float('nan'), 0]]))
        np.testing.assert_allclose(sampled[0], [0.375, 0.625, 1])
        np.testing.assert_array_equal(valid, [True, False, False])
        self.assertFalse(sampled[1:].any())

    def test_visibility_rejects_a_foreground_ridge_and_back_faces(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            values = np.zeros((9, 9))
            field = field_fixture(root, values)
            camera = Camera({'position_meters': [0, 4, 2], 'forward': [1, 0, -0.25],
                             'focal_pixels': 100}, (100, 80))
            point = np.array([[[8, 4, 0]]], dtype=float)
            normal = np.array([[[0, 0, 1]]], dtype=float)
            self.assertTrue(visible_surface(field, point, camera, normal, 32).all())
            self.assertFalse(visible_surface(field, point, camera, -normal, 32).any())
            field.values[:, 4] = 3
            self.assertFalse(visible_surface(field, point, camera, normal, 32).any())

    def test_photo_rays_intersect_the_heightfield_without_moving_it(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            field = field_fixture(root, np.zeros((17, 17)))
            camera = Camera({'position_meters': [0, 4, 2], 'forward': [1, 0, -0.25],
                             'focal_pixels': 100}, (100, 80))
            before = (root/'heightmap.r16').read_bytes()
            points, valid = intersect_photo_rays(field, camera, np.array([[50, 40], [50, 0]]), 16, 0.5)
            np.testing.assert_allclose(points[0], [8, 4, 0], atol=1e-5)
            np.testing.assert_array_equal(valid, [True, False])
            self.assertTrue(np.isnan(points[1]).all())
            self.assertEqual((root/'heightmap.r16').read_bytes(), before)

    @unittest.skipUnless(importlib.util.find_spec('scipy'), 'camera optimization requires scipy')
    def test_camera_fit_recovers_a_known_view_with_independent_landmarks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            y, x = np.mgrid[0:17, 0:17]
            field = field_fixture(root, 18+3*np.sin(x/3)*np.sin(y/4))
            eye = [15, 8, float(field.sample(np.array([15, 8, 0])))+1.7]
            true = Camera({'position_meters': eye, 'forward': [-np.cos(0.2), 0, np.sin(0.2)],
                           'focal_pixels': 90}, (128, 128))
            points = terrain_points(field, [0, 0, 12, 16], 1)
            sx, sy = projected_skyline(points, true)
            indices = np.linspace(0, len(sx)-1, 16).astype(int)
            observed = np.stack([sx[indices], sy[indices]], axis=-1)
            locations = np.array([[3, 2, 0], [7, 4, 0], [4, 8, 0], [8, 9, 0], [10, 10, 0], [2, 14, 0]], dtype=float)
            locations[:, 2] = field.sample(locations)
            pixels, valid = true.project(locations)
            self.assertTrue(valid.all())
            search = {'position_xy_bounds_meters': [[14.7, 15.3], [7.7, 8.3]],
                'aim_meters': [5, 8, 20], 'yaw_offset_degrees': [-3, 3],
                'pitch_degrees': [8, 14], 'focal_pixels': [88, 92], 'iterations': 60,
                'landmarks': [{'world_meters': point.tolist(), 'photo_pixels': pixel.tolist()}
                              for point, pixel in zip(locations, pixels)]}
            fitted, report, predicted = fit_camera(field, points, observed, (128, 128), search)
            self.assertLess(report['skyline_rms_pixels'], 0.1)
            self.assertLess(report['landmark_rms_pixels'], 0.1)
            np.testing.assert_allclose(fitted.position, true.position, atol=0.1)
            self.assertFalse(report['verified'])
            self.assertEqual(report['status'], 'candidate')

    def test_extraction_projects_the_heightfield_into_the_full_photo(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            y, x = np.mgrid[0:33, 0:33]
            field_fixture(root, 30-0.5*x+0.1*y)
            original = (root/'heightmap.r16').read_bytes()
            camera = {'position_meters': [30, 8, 26], 'forward': [-1, 0, 0], 'focal_pixels': 100}
            normal = rock.unit(np.array([-0.1, 1, 0.5]))
            lights = rock.unit(np.array([[1, 0.8, 1], [-1, 0.8, 1], [0, -0.1, 1]], dtype=float))
            views = []
            for i, light in enumerate(lights):
                value = int(round(float(rock.srgb(np.array(0.6*np.dot(normal, light))))*255))
                Image.new('RGB', (128, 128), (value, value, value)).save(root/f'photo{i}.png')
                views.append({'file': f'photo{i}.png', 'camera': camera,
                              'light_direction': light.tolist(), 'exposure_gain': 1, 'occlusion_samples': 32})
            profile = {'version': 1, 'size': [24, 24], 'views': views,
                'rock_polygons_uv': [[[0, 0], [1, 0], [1, 1], [0, 1]]],
                'heightmap': {'manifest': 'map.json', 'ray_distance_meters': 20, 'ray_step_meters': 1},
                'surface': {'origin_meters': [12, 4, 20], 'axes': [[0, 1, 0], [0, 0, 1]],
                    'extent_meters': [8, 6], 'reference_albedo': 0.6, 'max_angle_degrees': 10,
                    'max_displacement_meters': 0.2, 'edge_fade_meters': 0.25}}
            (root/'profile.json').write_text(json.dumps(profile))
            report = rock.extract(root/'profile.json', root/'out')
            data = np.load(root/'out/surface-data.npz')
            expected_pixels, expected_valid = Camera(camera, (128, 128)).project(data['base_meters'])
            np.testing.assert_allclose(data['photo_pixels'][0], expected_pixels)
            np.testing.assert_array_equal(data['photo_visible'][0], expected_valid)
            self.assertTrue(report['perspective_projection'])
            self.assertTrue(report['heightmap_projected'])
            self.assertGreater(report['photometric_valid_pixels'], 400)
            self.assertLess(report['max_applied_angle_degrees'], 1)
            self.assertEqual((root/'heightmap.r16').read_bytes(), original)
            registration = {'camera': camera, 'heightmap_sha256': 'different-source'}
            (root/'camera.json').write_text(json.dumps(registration))
            profile['views'][0].pop('camera')
            profile['views'][0]['camera_file'] = 'camera.json'
            (root/'profile.json').write_text(json.dumps(profile))
            with self.assertRaisesRegex(ValueError, 'different heightmap'):
                rock.extract(root/'profile.json', root/'stale')
            registration['heightmap_sha256'] = rock.Heightfield(root/'map.json').source_sha256
            registration['heightmap_geometry_sha256'] = 'different-transform'
            (root/'camera.json').write_text(json.dumps(registration))
            with self.assertRaisesRegex(ValueError, 'transform changed'):
                rock.extract(root/'profile.json', root/'stale-transform')
            registration.pop('heightmap_geometry_sha256')
            (root/'camera.json').write_text(json.dumps(registration))
            profile['views'][0]['crop'] = [0, 0, 100, 100]
            (root/'profile.json').write_text(json.dumps(profile))
            with self.assertRaisesRegex(ValueError, 'omit crop'):
                rock.extract(root/'profile.json', root/'bad')


if __name__ == '__main__':
    unittest.main()
