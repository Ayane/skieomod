import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from tools.prepare_nanite_tile import prepare, surface_detail
from tools.build_nanite_rock import validate_mesh
from tools.package_nanite_terrain import package


class NaniteTileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root/'source'
        self.source.mkdir()
        # Four adjacent triangles with deliberately duplicated UV seams.
        xy = np.array([[0, 0], [2, 0], [0, 2], [2, 2], [4, 0], [4, 2]], float)
        grid = np.column_stack([xy, 5*xy[:, 0]+.2*xy[:, 1]+.1*xy[:, 0]*xy[:, 1]])
        self.points = grid[np.array([[0, 1, 2], [1, 3, 2], [1, 4, 3], [4, 5, 3]])].reshape(-1, 3)
        faces = np.arange(12).reshape(-1, 3)
        normals = np.tile([-5, -.2, 1.], (12, 1))
        normals /= np.linalg.norm(normals, axis=-1, keepdims=True)
        np.savetxt(self.source/'positions.txt', self.points)
        np.savetxt(self.source/'normals.txt', normals)
        np.savetxt(self.source/'uvs.txt', self.points[:, :2])
        np.savetxt(self.source/'indices.txt', faces, fmt='%d')
        self.r16 = self.root/'heightmap.r16'
        self.r16.write_bytes(b'\0\0')
        self.info = {'version': 1, 'coordinate_system': 'east-south-up-metres',
                     'winding': 'counterclockwise', 'origin_meters': [100., 200., 500.],
                     'vertices': 12, 'triangles': 4, 'source_section': 42,
                     'source_file': str(self.r16), 'map_id': 'test.veymont',
                     'sample_step': 4, 'tile_quads': 63, 'uv_tile_meters': 20,
                     'source_definition': {'format': 'r16le', 'vertices': [1, 1],
                         'spacing_meters': 4, 'height_scale_meters': .025,
                         'height_offset_meters': 724}, 'source_origin_centimeters': [0, 0, 0]}
        self.write_info()

    def write_info(self):
        (self.source/'tile-source.json').write_text(json.dumps(self.info))

    def read(self, directory, name, width):
        return np.fromfile(directory/(name+'.bin'), dtype='<u4' if name == 'indices' else '<f4').reshape(-1, width)

    def test_tile_borders_and_uv_seams_stay_closed(self):
        plain, detailed = self.root/'plain', self.root/'detailed'
        prepare(self.source, plain, levels=2, amplitude=0)
        info = prepare(self.source, detailed, levels=2)
        self.assertEqual(info['triangles'], 64)
        self.assertEqual(validate_mesh(detailed/'mesh.json')['origin_meters'], [100., 200., 500.])
        before, after = self.read(plain, 'positions', 3), self.read(detailed, 'positions', 3)
        border = (before[:, 0] == 0)|(before[:, 0] == 4)|(before[:, 1] == 0)|(before[:, 1] == 2)
        np.testing.assert_array_equal(before[border], after[border])
        # Every copy of a geometric vertex must receive exactly the same displacement.
        _, weld = np.unique(before, axis=0, return_inverse=True)
        for index in np.unique(weld):
            copies = after[weld == index]
            np.testing.assert_array_equal(copies, np.broadcast_to(copies[0], copies.shape))
        normals = self.read(detailed, 'normals', 3)
        self.assertTrue(np.allclose(np.linalg.norm(normals, axis=-1), 1, atol=1e-6))
        self.assertLessEqual(np.linalg.norm(after-before, axis=-1).max(), .025001)
        self.assertFalse(info['nanite_built'])

    def test_refinement_keeps_front_faces_and_valid_indices(self):
        output = self.root/'output'
        prepare(self.source, output)
        positions, faces = self.read(output, 'positions', 3), self.read(output, 'indices', 3)
        cross = np.cross(positions[faces[:, 1]]-positions[faces[:, 0]],
                         positions[faces[:, 2]]-positions[faces[:, 0]])
        self.assertTrue(np.all(cross[:, 2] > 0))
        self.assertEqual(len(np.unique(faces)), len(positions))

    def test_subdivision_without_relief_preserves_source_shading(self):
        output = self.root/'smooth'
        prepare(self.source, output, amplitude=0)
        prior = np.loadtxt(self.source/'normals.txt')[0]
        result = self.read(output, 'normals', 3)
        np.testing.assert_allclose(result, np.broadcast_to(prior, result.shape), atol=1e-6)

    def test_adaptive_edges_follow_3d_wall_length_and_close_uv_seams(self):
        output = self.root/'adaptive'
        prepare(self.source, output, levels=0, amplitude=0, edge_spacing=2)
        positions, faces = self.read(output, 'positions', 3), self.read(output, 'indices', 3)
        edges = np.stack([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]], axis=1).reshape(-1, 2)
        self.assertLessEqual(np.linalg.norm(positions[edges[:, 1]]-positions[edges[:, 0]], axis=-1).max(), 2.00001)
        # After welding the UV copies, every interior edge is shared exactly
        # twice: no T-junction remains when adjacent triangles refine differently.
        welded_positions, weld = np.unique(positions, axis=0, return_inverse=True)
        unique, count = np.unique(np.sort(weld[edges], axis=1), axis=0, return_counts=True)
        self.assertTrue(np.all(count <= 2))
        boundary = welded_positions[unique[count == 1]]
        on_border = (np.all(boundary[:, :, 0] == 0, axis=1) | np.all(boundary[:, :, 0] == 4, axis=1)
            | np.all(boundary[:, :, 1] == 0, axis=1) | np.all(boundary[:, :, 1] == 2, axis=1))
        self.assertTrue(np.all(on_border))
        cross = np.cross(positions[faces[:, 1]]-positions[faces[:, 0]], positions[faces[:, 2]]-positions[faces[:, 0]])
        self.assertTrue(np.all(cross[:, 2] > 0))

    def test_photo_style_is_periodic_and_bounded(self):
        profile = self.root/'profile'
        profile.mkdir()
        signal = np.tile(.1*np.sin(np.arange(8)*np.pi/4), (8, 1))
        np.savez(profile/'surface-data.npz', procedural_displacement_meters=signal)
        report = {'basis_columns': np.eye(3).tolist(), 'spacing_meters': [1., 1.],
                  'procedural': {'periodic': True, 'method': 'test-spectrum'}}
        (profile/'surface.json').write_text(json.dumps(report))
        values, metadata = surface_detail(np.array([[.3, .5, 0], [8.3, 8.5, 20]]), profile)
        np.testing.assert_allclose(values[0], values[1], atol=1e-12)
        self.assertFalse(metadata['measured_fractures'])
        self.assertLessEqual(abs(values).max(), .1)
        np.savez(profile/'surface-data.npz', procedural_displacement_meters=signal*10)
        with self.assertRaisesRegex(ValueError, 'bounded surface'):
            prepare(self.source, self.root/'unsafe-profile', surface=profile)
        self.assertFalse((self.root/'unsafe-profile').exists())

    def test_invalid_input_is_rejected_before_export(self):
        with self.assertRaises(ValueError):
            prepare(self.source, self.root/'bad', levels=4)
        self.info['winding'] = 'clockwise'
        self.write_info()
        with self.assertRaisesRegex(ValueError, 'coordinates'):
            prepare(self.source, self.root/'bad')
        self.assertFalse((self.root/'bad').exists())

    def test_packaging_requires_game_validation_and_unchanged_sources(self):
        output = self.root/'mesh'
        info = prepare(self.source, output)
        pak = self.root/'tile.pak'
        pak.write_bytes(b'synthetic packaging fixture')
        report = {'nanite_built': True, 'game_render_verified': False,
                  'target_platform': 'Windows', 'nanite_clusters': 2,
                  'input_mesh': str(output/'mesh.json'),
                  'input_sha256': hashlib.sha256((output/'mesh.json').read_bytes()).hexdigest(),
                  'pak': str(pak), 'pak_sha256': hashlib.sha256(pak.read_bytes()).hexdigest(),
                  'asset': info['package']+'.SM_Terrain_T42', 'origin_meters': info['origin_meters']}
        path = self.root/'report.json'
        path.write_text(json.dumps(report))
        with self.assertRaisesRegex(ValueError, 'game-validated'):
            package([path], self.root/'cache')
        self.assertFalse((self.root/'cache').exists())
        report['game_render_verified'] = True
        path.write_text(json.dumps(report))
        with self.assertRaisesRegex(ValueError, 'IoStore'):
            package([path], self.root/'cache')
        report['iostore'] = {}
        for kind in ('pak', 'utoc', 'ucas'):
            container = self.root/('tile.'+kind)
            container.write_bytes(('synthetic '+kind).encode())
            report['iostore'][kind] = {'file': str(container),
                'sha256': hashlib.sha256(container.read_bytes()).hexdigest()}
        path.write_text(json.dumps(report))
        cache = package([path], self.root/'cache')
        self.assertEqual(cache['sections'][0]['section'], 42)
        self.assertEqual(cache['source_crc32'], '41d912ff')
        for kind in ('pak', 'utoc', 'ucas'):
            self.assertTrue((self.root/'cache'/('SkiEO-SM_Terrain_T42_P.'+kind)).is_file())
        (self.root/'tile.ucas').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'IoStore ucas changed'):
            package([path], self.root/'tampered')
        self.assertFalse((self.root/'tampered').exists())
        self.r16.write_bytes(b'\1\0')
        with self.assertRaisesRegex(ValueError, 'terrain changed'):
            package([path], self.root/'stale')
        self.assertFalse((self.root/'stale').exists())

    def test_massif_packaging_requires_matching_rock_and_snow_coverage(self):
        reports=[]
        for layer in ('terrain','snow'):
            output=self.root/layer
            info=prepare(self.source,output)
            info.update(mesh_algorithm=2,layer=layer,source_sections=[34,42])
            info['package']='/Game/CustomMaps/Veymont/Nanite/SM_Mass'+layer
            mesh=output/'mesh.json';mesh.write_text(json.dumps(info))
            report={'nanite_built':True,'game_render_verified':True,'target_platform':'Windows',
                    'nanite_clusters':2,'input_mesh':str(mesh),
                    'input_sha256':hashlib.sha256(mesh.read_bytes()).hexdigest(),
                    'asset':info['package']+'.'+info['package'].rsplit('/',1)[-1],
                    'origin_meters':info['origin_meters'],'iostore':{}}
            for kind in ('pak','utoc','ucas'):
                file=output/('synthetic.'+kind);file.write_bytes((layer+kind).encode())
                report['iostore'][kind]={'file':str(file),'sha256':hashlib.sha256(file.read_bytes()).hexdigest()}
            path=output/'report.json';path.write_text(json.dumps(report));reports.append(path)
        with self.assertRaisesRegex(ValueError,'both rock and snow'):
            package(reports[:1],self.root/'incomplete')
        self.assertFalse((self.root/'incomplete').exists())
        result=package(reports,self.root/'complete')
        self.assertEqual(result['mesh_algorithm'],2)
        self.assertEqual(result['snow_offset_centimeters'],30)
        self.assertEqual([r['source_sections'] for r in result['sections']],[[34,42],[34,42]])
        self.assertEqual({r['layer'] for r in result['sections']},{'terrain','snow'})

    def test_partitioned_packaging_rejects_missing_and_duplicate_parts(self):
        reports=[]
        for layer in ('terrain','snow'):
            for part in range(2):
                output=self.root/f'{layer}-{part}'
                info=prepare(self.source,output)
                info.update(mesh_algorithm=3,layer=layer,source_sections=[42],part=part,parts=2)
                info['package']=f'/Game/CustomMaps/Veymont/Nanite/SM_Part{layer}{part}'
                mesh=output/'mesh.json';mesh.write_text(json.dumps(info))
                report={'nanite_built':True,'game_render_verified':True,'target_platform':'Windows',
                    'nanite_clusters':2,'input_mesh':str(mesh),'input_sha256':hashlib.sha256(mesh.read_bytes()).hexdigest(),
                    'asset':info['package']+'.'+info['package'].rsplit('/',1)[-1],'iostore':{}}
                for kind in ('pak','utoc','ucas'):
                    file=output/('synthetic.'+kind);file.write_bytes((layer+str(part)+kind).encode())
                    report['iostore'][kind]={'file':str(file),'sha256':hashlib.sha256(file.read_bytes()).hexdigest()}
                path=output/'report.json';path.write_text(json.dumps(report));reports.append(path)
        with self.assertRaisesRegex(ValueError,'every rock and snow partition'):
            package(reports[:-1],self.root/'missing')
        self.assertFalse((self.root/'missing').exists())
        with self.assertRaisesRegex(ValueError,'duplicate terrain section'):
            package(reports+[reports[0]],self.root/'duplicate')
        result=package(reports,self.root/'complete')
        self.assertEqual(result['mesh_algorithm'],3)
        self.assertEqual(len(result['sections']),4)
        for path in reports:
            report=json.loads(path.read_text());mesh=Path(report['input_mesh'])
            info=json.loads(mesh.read_text())
            info['surface_transition']={'width_meters':24.,'curve':'smootherstep'}
            info['snow_retention_normals']='sculpted-geometric-slope-with-native-transition'
            mesh.write_text(json.dumps(info))
            report['input_sha256']=hashlib.sha256(mesh.read_bytes()).hexdigest()
            path.write_text(json.dumps(report))
        complete=package(reports,self.root/'transition-complete')
        self.assertEqual(complete['surface_transition']['width_meters'],24.)
        # Coats are optional for partitions with no ledges, but can never
        # substitute for missing primary rock/snow or reference another tile.
        coat_report=json.loads(reports[0].read_text())
        coat_mesh=Path(coat_report['input_mesh']).with_name('coat.json')
        coat_info=json.loads(Path(coat_report['input_mesh']).read_text())
        coat_info.update(layer='snow_deposits',snow_uv_bounds=[[.2,.5],[.3,.6]],
            coat_material='/Game/Materials/Backgrounds/M_Snow.M_Snow',
            package='/Game/CustomMaps/Veymont/Nanite/SM_Coat')
        coat_mesh.write_text(json.dumps(coat_info))
        coat_report.update(input_mesh=str(coat_mesh),
            input_sha256=hashlib.sha256(coat_mesh.read_bytes()).hexdigest(),
            asset=coat_info['package']+'.SM_Coat')
        coat_path=coat_mesh.with_name('coat-report.json');coat_path.write_text(json.dumps(coat_report))
        coated=package(reports+[coat_path],self.root/'coated')
        self.assertEqual(len(coated['sections']),5)
        self.assertEqual(coated['sections'][-1]['snow_uv_bounds'],[[.2,.5],[.3,.6]])
        with self.assertRaisesRegex(ValueError,'every rock and snow partition'):
            package(reports[:-1]+[coat_path],self.root/'coat-with-missing-primary')
        coat_info['parts']=3;coat_mesh.write_text(json.dumps(coat_info))
        coat_report['input_sha256']=hashlib.sha256(coat_mesh.read_bytes()).hexdigest()
        coat_path.write_text(json.dumps(coat_report))
        with self.assertRaisesRegex(ValueError,'coat partition count'):
            package(reports+[coat_path],self.root/'coat-mismatch')
        coat_info['parts']=2;coat_info['snow_uv_bounds'][0][0]=float('nan')
        coat_mesh.write_text(json.dumps(coat_info))
        coat_report['input_sha256']=hashlib.sha256(coat_mesh.read_bytes()).hexdigest()
        coat_path.write_text(json.dumps(coat_report))
        with self.assertRaisesRegex(ValueError,'snow coat material or bounds'):
            package(reports+[coat_path],self.root/'invalid-coat')
        self.assertFalse((self.root/'invalid-coat').exists())
        report=json.loads(reports[-1].read_text());mesh=Path(report['input_mesh'])
        info=json.loads(mesh.read_text());info['surface_transition']['width_meters']=12.
        mesh.write_text(json.dumps(info));report['input_sha256']=hashlib.sha256(mesh.read_bytes()).hexdigest()
        reports[-1].write_text(json.dumps(report))
        with self.assertRaisesRegex(ValueError,'different terrain sources or settings'):
            package(reports,self.root/'transition-mismatch')
        self.assertFalse((self.root/'transition-mismatch').exists())


if __name__ == '__main__':
    unittest.main()
