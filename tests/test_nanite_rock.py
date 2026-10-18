import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from tools.prepare_nanite_rock import prepare
from tools.build_nanite_rock import validate_mesh


class NaniteRockTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root/'surface'
        self.source.mkdir()
        rows, columns = np.mgrid[0:9, 0:9]
        self.base = np.stack([columns, 8-rows, np.zeros_like(rows)], axis=-1).astype(float)
        self.mask = np.ones((9, 9), dtype=bool)
        self.write_source()

    def write_source(self):
        corrected = self.base.copy()
        corrected[..., 2] += .30
        np.savez(self.source/'surface-data.npz', base_meters=self.base,
                 corrected_meters=corrected, geometry_mask=self.mask)
        (self.source/'surface.json').write_text(json.dumps({
            'spacing_meters': [1, 1], 'basis_columns': np.eye(3).tolist(),
            'material': {'albedo_srgb': [.85, .85, .82], 'roughness': .8},
            'calibration': 'synthetic test',
        }))

    def test_relief_is_deterministic_and_bounded_on_actual_mesh(self):
        info = prepare(self.source, self.root/'a', .25, .025)
        other = prepare(self.source, self.root/'b', .25, .025)
        self.assertEqual(info['buffers'], other['buffers'])
        self.assertLessEqual(info['procedural']['maximum_displacement_meters'], .025)
        self.assertLessEqual(info['procedural']['maximum_normal_change_degrees'], 20)
        self.assertFalse(info['nanite_built'])
        self.assertFalse(info['photographic_correction_applied'])
        points = np.fromfile(self.root/'a/positions.bin', dtype='<f4').reshape(-1, 3)
        faces = np.fromfile(self.root/'a/indices.bin', dtype='<u4').reshape(-1, 3)
        normals = np.fromfile(self.root/'a/normals.bin', dtype='<f4').reshape(-1, 3)
        geometric = np.cross(points[faces[:, 1]]-points[faces[:, 0]],
                             points[faces[:, 2]]-points[faces[:, 0]])
        self.assertTrue(np.all(geometric[:, 2] > 0))
        self.assertTrue(np.all(np.sum(geometric*normals[faces[:, 0]], axis=-1) > 0))
        self.assertTrue(np.allclose(np.linalg.norm(normals, axis=-1), 1, atol=1e-6))

    def test_correction_is_explicit_and_preserves_position(self):
        base = prepare(self.source, self.root/'a', amplitude=0)
        corrected = prepare(self.source, self.root/'b', amplitude=0, corrected=True)
        self.assertAlmostEqual(corrected['origin_meters'][2]-base['origin_meters'][2], .30)
        self.assertTrue(corrected['photographic_correction_applied'])

    def test_subdivision_does_not_bridge_mask_holes(self):
        self.mask[4, 4] = False
        self.write_source()
        info = prepare(self.source, self.root/'a', .25, 0)
        points = np.fromfile(self.root/'a/positions.bin', dtype='<f4').reshape(-1, 3)
        points += info['origin_meters']
        faces = np.fromfile(self.root/'a/indices.bin', dtype='<u4').reshape(-1, 3)
        centers = points[faces].mean(axis=1)
        self.assertFalse(np.any((abs(centers[:, 0]-4) < 1)&(abs(centers[:, 1]-4) < 1)))

    def test_budgets_and_source_files_are_guarded(self):
        original = (self.source/'surface-data.npz').read_bytes()
        for kwargs in ({'spacing': .001}, {'amplitude': 1}, {'max_vertices': 10},
                       {'package': '/Game/../../Bad'}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                prepare(self.source, self.root/'a', **kwargs)
        with self.assertRaises(ValueError):
            prepare(self.source, self.source/'generated')
        self.assertEqual(original, (self.source/'surface-data.npz').read_bytes())

    def test_cooker_rejects_stale_buffers_and_malformed_origin(self):
        output = self.root/'a'
        prepare(self.source, output)
        self.assertEqual(validate_mesh(output/'mesh.json')['vertices'], 1089)
        buffer = output/'positions.bin'
        contents = buffer.read_bytes()
        buffer.write_bytes(bytes([contents[0]^1])+contents[1:])
        with self.assertRaisesRegex(ValueError, 'positions buffer changed'):
            validate_mesh(output/'mesh.json')
        prepare(self.source, output)
        info = json.loads((output/'mesh.json').read_text())
        info['origin_meters'] = [0, float('nan'), 0]
        (output/'mesh.json').write_text(json.dumps(info))
        with self.assertRaisesRegex(ValueError, 'invalid map origin'):
            validate_mesh(output/'mesh.json')


if __name__ == '__main__':
    unittest.main()
