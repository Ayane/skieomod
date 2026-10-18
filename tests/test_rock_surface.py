from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('rock_surface', ROOT/'tools/extract_rock_surface.py')
rock = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(rock)


class RockSurfaceTests(unittest.TestCase):
    def test_unlit_single_photo_cannot_calibrate_exposure_or_invent_normals(self):
        prior = np.zeros((8, 8, 3)); prior[..., 2] = 1
        estimated, valid, report = rock.estimate_normals(np.ones((1, 8, 8))*0.5,
            np.array([[0, 0, -1]]), prior, np.ones((8, 8), dtype=bool),
            [None], np.array([0]), 0.75, 15)
        np.testing.assert_array_equal(estimated, prior)
        self.assertFalse(valid.any())
        self.assertEqual(report['mode'], 'geometry-prior-without-usable-rock-radiometry')
        self.assertFalse(report['exposure_estimated_from_prior'])

    def test_calibrated_stereo_recovers_known_normals(self):
        y, x = np.mgrid[-0.2:0.2:16j, -0.2:0.2:16j]
        normal = rock.unit(np.stack([x, y, np.ones(x.shape)], axis=-1))
        prior = np.zeros_like(normal); prior[..., 2] = 1
        lights = rock.unit(np.array([[1, 0, 1], [0, 1, 1], [-1, -1, 1]], dtype=float))
        images = 0.6*np.einsum('ij,hwj->ihw', lights, normal)
        estimated, valid, info = rock.estimate_normals(images, lights, prior,
            np.ones(x.shape, bool), [1, 1, 1], np.zeros(3), 0.6, 30)
        self.assertTrue(valid.all())
        np.testing.assert_allclose(estimated, normal, atol=1e-12)
        self.assertTrue(info['normals_identifiable_under_model'])
        self.assertFalse(info['exposure_estimated_from_prior'])

    def test_single_view_retains_prior_on_ambiguous_direction(self):
        prior = np.zeros((8, 8, 3)); prior[..., 2] = 1
        light = rock.unit(np.array([[1, 0, 1]], dtype=float))
        target = rock.unit(np.array([0.15, 0, 1]))
        image = np.full((1, 8, 8), 0.6*np.dot(light[0], target))
        estimated, valid, info = rock.estimate_normals(image, light, prior,
            np.ones((8, 8), bool), [1], np.zeros(1), 0.6, 30)
        np.testing.assert_allclose(estimated[valid], np.broadcast_to(target, (64, 3)), atol=1e-12)
        self.assertFalse(info['normals_identifiable_under_model'])
        # Frontal light cannot tell which direction a tilted surface faces.
        _, valid, _ = rock.estimate_normals(image, np.array([[0, 0, 1]]), prior,
            np.ones((8, 8), bool), [1], np.zeros(1), 0.6, 30)
        self.assertFalse(valid.any())

    def test_stereo_rejects_degenerate_lighting_and_two_views(self):
        prior = np.zeros((8, 8, 3)); prior[..., 2] = 1
        for count in [2, 3]:
            with self.assertRaises(ValueError):
                rock.estimate_normals(np.ones((count, 8, 8))*0.5,
                    np.tile([0, 0, 1], (count, 1)), prior,
                    np.ones((8, 8), bool), [1]*count, np.zeros(count), 0.6, 30)

    def test_snow_is_soft_upward_evidence_with_an_angle_limit(self):
        prior = np.zeros((8, 8, 3)); prior[..., 2] = 1
        mask = np.zeros((8, 8), bool); mask[2:6, 2:6] = True
        result = rock.snow_orientation_cue(prior, prior, mask, np.array([0, 1, 0]),
                                           0.6, 0.35, 25)
        self.assertTrue(np.all(result[mask, 1] > 0))
        self.assertTrue(np.all(result[mask, 1] < 0.6))
        np.testing.assert_array_equal(result[~mask], prior[~mask])
        np.testing.assert_allclose(np.linalg.norm(result, axis=-1), 1)
        capped = rock.snow_orientation_cue(prior, prior, mask, np.array([0, 1, 0]),
                                           0.9, 1, 10)
        self.assertLessEqual(np.max(np.degrees(np.arccos(capped[..., 2]))), 10+1e-8)
        disabled = rock.snow_orientation_cue(prior, prior, mask, np.array([0, 1, 0]),
                                             0.6, 0, 25)
        np.testing.assert_array_equal(disabled, prior)
        upward = np.broadcast_to(rock.unit(np.array([0, 0.8, 0.6])), prior.shape)
        unchanged = rock.snow_orientation_cue(upward, upward, mask, np.array([0, 1, 0]),
                                              0.6, 0.35, 25)
        np.testing.assert_allclose(unchanged, upward)

    def test_snow_evidence_survives_clipped_radiometry_and_changes_mesh(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            light = rock.unit(np.array([0.6, 0.15, 0.8]))
            green = int(round(float(rock.srgb(np.array(0.6*light[2])))*255))
            image = np.broadcast_to(np.array([230, green, 100], dtype='uint8'), (32, 32, 3)).copy()
            image[10:20, 4:28] = 255
            Image.fromarray(image).save(root/'photo.png')
            profile = {'version': 1, 'size': [32, 32], 'channel': 'green',
                'views': [{'file': 'photo.png', 'light_direction': light.tolist(), 'exposure_gain': 1}],
                'rock_polygons_uv': [[[0, 0], [1, 0], [1, 1], [0, 1]]],
                'snow_cue': {'weight': 0.35, 'minimum_up_cosine': 0.6,
                             'min_brightness_srgb': 0.9, 'max_red_over_blue': 1.1},
                'surface': {'axes': [[1, 0, 0], [0, 0, 1]], 'extent_meters': [10, 10],
                    'reference_albedo': 0.6, 'detail_scale_meters': 20, 'edge_fade_meters': 0.1,
                    'max_angle_degrees': 10, 'max_displacement_meters': 0.1}}
            (root/'profile.json').write_text(json.dumps(profile))
            report = rock.extract(root/'profile.json', root/'snow')
            data = np.load(root/'snow/surface-data.npz')
            snow = data['snow_cue_mask']
            self.assertEqual(int(snow.sum()), 240)
            self.assertTrue(np.all(data['geometry_mask'][snow]))
            self.assertTrue(np.all(data['valid'][snow]))
            self.assertFalse(np.any(data['photometric_valid'][snow]))
            self.assertTrue(np.all(data['normal_estimated'][snow, 1] > 0))
            self.assertGreater(np.max(np.abs(data['displacement_meters'][snow])), 0.001)
            self.assertLessEqual(report['max_applied_angle_degrees'], 10+1e-6)
            np.testing.assert_allclose(report['snow_cue']['up_direction_local'], [0, 1, 0])
            self.assertFalse(report['snow_cue']['inferred_horizontal_surface'])
            profile['snow_cue']['weight'] = 0
            (root/'profile.json').write_text(json.dumps(profile))
            rock.extract(root/'profile.json', root/'disabled')
            disabled = np.load(root/'disabled/surface-data.npz')
            self.assertFalse(np.any(disabled['valid'][snow]))
            np.testing.assert_array_equal(disabled['normal_estimated'][snow], disabled['normal_prior'][snow])
            self.assertFalse(np.any(disabled['displacement_meters'][snow]))

    def test_normal_integration_has_correct_sign_and_pinned_edges(self):
        y, x = np.mgrid[0:64, 0:64]
        height = 0.1*np.sin(2*np.pi*x/64)*np.cos(2*np.pi*y/64)
        dx = np.roll(height, -1, axis=1)-height
        dy = np.roll(height, -1, axis=0)-height
        estimated = rock.unit(np.stack([-dx, dy, np.ones(x.shape)], axis=-1))
        prior = np.zeros_like(estimated); prior[..., 2] = 1
        mask = np.ones(x.shape, bool)
        result = rock.integrate_correction(prior, estimated, mask, (1, 1), 10000, 0.2, 2)
        self.assertGreater(np.corrcoef(result[8:-8, 8:-8].ravel(), height[8:-8, 8:-8].ravel())[0, 1], 0.99)
        self.assertTrue(np.all(result[[0, -1]] == 0))
        self.assertTrue(np.all(result[:, [0, -1]] == 0))
        bounded = rock.integrate_correction(prior, estimated, mask, (1, 1), 10000, 0.02, 2)
        self.assertLessEqual(np.max(np.abs(bounded)), 0.02+1e-12)

    def test_heightfield_projection_preserves_datum_and_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            y, x = np.mgrid[0:17, 0:17]
            raw = (200-10*x+5*y).astype('<u2')
            raw.tofile(root/'heightmap.r16')
            original = (root/'heightmap.r16').read_bytes()
            definition = {'terrain': {'size_meters': [16, 16],
                'origin_centimeters': [0, 0, 1000],
                'source': {'file': 'heightmap.r16', 'format': 'r16le', 'vertices': [17, 17],
                    'spacing_meters': 1, 'height_scale_meters': 0.1, 'height_offset_meters': 800}}}
            (root/'map.json').write_text(json.dumps(definition))
            field = rock.Heightfield(root/'map.json')
            np.testing.assert_allclose(field.sample(np.array([[8, 4, 0]])), [824])
            u, v = np.meshgrid(np.linspace(2, 6, 8), np.linspace(828, 820, 8))
            plane = np.stack([np.full(u.shape, 8), u, v], axis=-1)
            result, valid = field.project(plane, np.array([1, 0, 0]), 8, 1)
            self.assertTrue(valid.all())
            np.testing.assert_allclose(result[..., 2], field.sample(result), atol=0.001)
            self.assertEqual((root/'heightmap.r16').read_bytes(), original)
            # Endian/row order must not invert the cliff or its datum.
            raw[::-1].astype('>u2').tofile(root/'heightmap.r16')
            definition['terrain']['source'].update(format='r16be', row_order='south_to_north')
            (root/'map.json').write_text(json.dumps(definition))
            other = rock.Heightfield(root/'map.json')
            np.testing.assert_allclose(other.values, field.values)

    def test_procedural_detail_is_reproducible_and_bounded(self):
        y, x = np.mgrid[0:32, 0:32]
        source = np.sin(x*0.3)*np.cos(y*0.4)
        first, normal = rock.procedural_detail(source, (0.1, 0.2), 42, 0.05, 10)
        again, _ = rock.procedural_detail(source, (0.1, 0.2), 42, 0.05, 10)
        other, _ = rock.procedural_detail(source, (0.1, 0.2), 43, 0.05, 10)
        np.testing.assert_array_equal(first, again)
        self.assertFalse(np.array_equal(first, other))
        self.assertLessEqual(np.max(np.abs(first)), 0.05+1e-12)
        self.assertLessEqual(np.max(np.degrees(np.arccos(normal[..., 2]))), 10+1e-8)
        np.testing.assert_allclose(np.linalg.norm(normal, axis=-1), 1, atol=1e-12)
        self.assertAlmostEqual(float(first.mean()), 0, places=12)

    def test_photo_correction_on_an_actual_heightfield_patch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            y, x = np.mgrid[0:33, 0:33]
            (3000-50*x+10*y).astype('<u2').tofile(root/'heightmap.r16')
            source_before = (root/'heightmap.r16').read_bytes()
            manifest = {'terrain': {'size_meters': [32, 32], 'origin_centimeters': [0, 0, 0],
                'source': {'file': 'heightmap.r16', 'format': 'r16le', 'vertices': [33, 33],
                    'spacing_meters': 1, 'height_scale_meters': 0.01, 'height_offset_meters': 0}}}
            (root/'map.json').write_text(json.dumps(manifest))
            basis = np.array([[0, 0, 1], [1, 0, 0], [0, 1, 0]], dtype=float)
            u, v = np.meshgrid(np.linspace(4, 12, 24), np.linspace(26, 20, 24))
            plane = np.stack([np.full(u.shape, 12), u, v], axis=-1)
            base, valid = rock.Heightfield(root/'map.json').project(plane, basis[:, 2], 20, 1)
            self.assertTrue(valid.all())
            desired = 0.1*np.sin(2*np.pi*(u-4)/8)*np.sin(2*np.pi*(v-20)/6)
            normal = rock.normals_of_mesh(base+basis[:, 2]*desired[..., None], basis)
            lights = rock.unit(np.array([[1, 0.8, 1], [-1, 0.8, 1], [0, -0.1, 1]], dtype=float))
            views = []
            for i, light in enumerate(lights):
                intensity = 0.6*np.sum(normal*light, axis=-1)
                pixels = np.rint(rock.srgb(intensity)*255).astype('uint8')
                Image.fromarray(pixels).convert('RGB').save(root/f'photo{i}.png')
                views.append({'file': f'photo{i}.png', 'light_direction': light.tolist(), 'exposure_gain': 1})
            profile = {'version': 1, 'size': [24, 24], 'views': views,
                'rock_polygons_uv': [[[0, 0], [1, 0], [1, 1], [0, 1]]],
                'heightmap': {'manifest': 'map.json', 'ray_distance_meters': 20, 'ray_step_meters': 1},
                'surface': {'origin_meters': [12, 4, 20], 'axes': [[0, 1, 0], [0, 0, 1]],
                    'extent_meters': [8, 6], 'reference_albedo': 0.6, 'edge_fade_meters': 0.25,
                    'detail_scale_meters': 20, 'max_angle_degrees': 10, 'max_displacement_meters': 0.2}}
            (root/'profile.json').write_text(json.dumps(profile))
            report = rock.extract(root/'profile.json', root/'out')
            data = np.load(root/'out/surface-data.npz')
            self.assertTrue(report['heightmap_projected'])
            self.assertGreater(report['max_applied_angle_degrees'], 0.1)
            np.testing.assert_allclose(data['base_meters'], base, atol=1e-8)
            self.assertGreater(np.corrcoef(data['displacement_meters'][4:-4, 4:-4].ravel(),
                                          desired[4:-4, 4:-4].ravel())[0, 1], 0.98)
            self.assertEqual((root/'heightmap.r16').read_bytes(), source_before)

    def test_full_extraction_changes_geometry_without_baking_lighting(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            y, x = np.mgrid[0:32, 0:32]
            normal = rock.unit(np.stack([0.15*np.sin(x*0.3), 0.1*np.cos(y*0.2), np.ones(x.shape)], axis=-1))
            lights = rock.unit(np.array([[1, 0, 1], [0, 1, 1], [-1, -1, 1]], dtype=float))
            views = []
            for i, light in enumerate(lights):
                intensity = 0.6*np.sum(normal*light, axis=-1)
                pixels = np.rint(rock.srgb(intensity)*255).astype('uint8')
                Image.fromarray(pixels).convert('RGB').save(root/f'view{i}.png')
                views.append({'file': f'view{i}.png', 'light_direction': light.tolist(), 'exposure_gain': 1})
            profile = {'version': 1, 'size': [32, 32], 'calibration': 'calibrated', 'views': views,
                'rock_polygons_uv': [[[0, 0], [1, 0], [1, 1], [0, 1]]],
                'surface': {'extent_meters': [10, 10], 'reference_albedo': 0.6,
                    'max_displacement_meters': 0.05, 'max_angle_degrees': 5,
                    'edge_fade_meters': 0.5}}
            (root/'profile.json').write_text(json.dumps(profile))
            report = rock.extract(root/'profile.json', root/'out')
            self.assertLessEqual(report['max_applied_displacement_meters'], 0.05+1e-12)
            self.assertLessEqual(report['max_applied_angle_degrees'], 5+1e-6)
            self.assertGreater(report['max_applied_displacement_meters'], 0.001)
            self.assertGreater(report['mesh_triangles'], 0)
            self.assertNotEqual((root/'out/patch.obj').read_bytes(), (root/'out/patch-base.obj').read_bytes())
            self.assertNotEqual((root/'out/relit-left.png').read_bytes(), (root/'out/relit-right.png').read_bytes())
            self.assertFalse(report['material']['measured_albedo_or_roughness'])
            displacement = np.fromfile(root/'out/displacement.r16', dtype='<u2').reshape(32, 32)
            encoding = report['displacement_encoding']
            recovered = displacement*encoding['scale_meters']+encoding['offset_meters']
            data = np.load(root/'out/surface-data.npz')
            np.testing.assert_allclose(recovered, data['displacement_meters'],
                                       atol=encoding['scale_meters']/2+1e-12)
            self.assertFalse(np.any(data['displacement_meters'][~data['valid']]))
            # Photograph rejection keeps the base geometry, not missing faces.
            image = np.asarray(Image.open(root/'view0.png')).copy()
            image[8:12, 8:12] = 255
            Image.fromarray(image).save(root/'view0.png')
            report = rock.extract(root/'profile.json', root/'clipped')
            data = np.load(root/'clipped/surface-data.npz')
            self.assertFalse(np.any(data['valid'][8:12, 8:12]))
            self.assertTrue(np.all(data['geometry_mask'][8:12, 8:12]))


if __name__ == '__main__':
    unittest.main()
