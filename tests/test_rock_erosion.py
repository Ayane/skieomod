import json
from pathlib import Path
import unittest

import numpy as np
from scipy.ndimage import binary_fill_holes

from tools.erode_implicit_cliff import erode_field, validate_erosion


class RockErosionTests(unittest.TestCase):
    def setUp(self):
        self.profile = json.loads(Path('maps/veymont/limestone-erosion.json').read_text())
        self.profile.update(depth_meters=.12,curvature_radius_meters=.2,iterations=12,
                            face_rate=0,exposure_floor=1)
        self.axis = np.linspace(-1,1,41)
        self.grid = np.stack(np.meshgrid(self.axis,self.axis,self.axis,indexing='ij'),axis=-1)
        self.spacing = np.full(3,.05)

    def test_disabled_erosion_keeps_the_field_exactly(self):
        field = np.linalg.norm(self.grid,axis=-1).astype(np.float32)-.6
        eroded,metrics = erode_field(field,self.spacing,dict(self.profile,depth_meters=0))
        np.testing.assert_array_equal(eroded,field)
        self.assertEqual(metrics['grid_estimated_removed_volume_m3'],0)

    def test_convex_volume_loses_material_and_its_interior_stays_solid(self):
        field = np.linalg.norm(self.grid,axis=-1)-.6
        eroded,metrics = erode_field(field,self.spacing,self.profile)
        self.assertTrue((eroded>=field.astype(np.float32)).all(),'erosion added material')
        self.assertGreater(metrics['grid_estimated_removed_volume_m3'],.01)
        self.assertLess(eroded[20,20,20],0,'the protected core vanished')
        self.assertGreater(eroded[20,20,31],0,'the exposed convex surface was not eroded')
        self.assertLess(eroded[20,20,28],0,'erosion exceeded its narrow retreat band')

    def test_flat_faces_are_preserved_by_edge_only_erosion(self):
        field = self.grid[...,2]
        eroded,_ = erode_field(field,self.spacing,self.profile)
        np.testing.assert_allclose(eroded,field.astype(np.float32),atol=1e-7)

    def test_concave_faces_are_not_smoothed_by_adding_material(self):
        field = .6-np.linalg.norm(self.grid,axis=-1)
        eroded,_ = erode_field(field,self.spacing,self.profile)
        band = np.abs(field)<.15
        np.testing.assert_allclose(eroded[band],field.astype(np.float32)[band],atol=1e-7)

    def test_box_edges_wear_before_the_middle_of_its_faces(self):
        field = np.abs(self.grid).max(axis=-1)-.6
        eroded,_ = erode_field(field,self.spacing,self.profile)
        edge = eroded[31,31,20]-field[31,31,20]
        face = eroded[31,20,20]-field[31,20,20]
        self.assertGreater(edge,.03)
        self.assertLess(abs(face),self.spacing.min()*.1)
        self.assertGreater(edge,6*abs(face))

    def test_exposure_changes_retreat_on_a_flat_face(self):
        field = self.grid[...,2]
        parameters = dict(self.profile,face_rate=1,exposure_floor=.2)
        exposed,_ = erode_field(field,self.spacing,dict(parameters,weather_direction_local=[0,0,1]))
        sheltered,_ = erode_field(field,self.spacing,dict(parameters,weather_direction_local=[0,0,-1]))
        self.assertGreater(exposed[20,20,20]-field[20,20,20],
                           2*(sheltered[20,20,20]-field[20,20,20]))

    def test_fixed_boundary_keeps_position_and_its_neighbouring_samples(self):
        field = np.abs(self.grid).max(axis=-1)-.6
        fade = np.ones(field.shape[:2])
        fade[:2,:]=0;fade[-2:,:]=0;fade[:,:2]=0;fade[:,-2:]=0
        eroded,_ = erode_field(field,self.spacing,self.profile,fade)
        np.testing.assert_array_equal(eroded[:2],field[:2].astype(np.float32))
        np.testing.assert_array_equal(eroded[:,:2],field[:,:2].astype(np.float32))

    def test_inward_weathering_keeps_a_real_overhang(self):
        axis = np.linspace(0,4,41)
        d = np.linspace(-2,2,41)
        u,v,z = np.meshgrid(axis,axis,d,indexing='ij')
        block = np.maximum.reduce([1-u,u-3,1-v,v-3,.7*u-2.5-z,z-.7*u+1.7])
        field = np.minimum(z+1,block)
        eroded,_ = erode_field(field,np.full(3,.1),dict(self.profile,depth_meters=.1,face_rate=.1))
        ray = eroded[28,20]<0
        self.assertEqual(np.count_nonzero(ray[1:]!=ray[:-1]),3)

    def test_invalid_parameters_and_excessive_removal_are_rejected(self):
        for update in [{'depth_meters':True},{'iterations':129},{'weather_direction_local':[0,0,0]},
                       {'face_rate':1.1}]:
            with self.subTest(update=update),self.assertRaises(ValueError):
                validate_erosion(dict(self.profile,**update))
        field = np.linalg.norm(self.grid,axis=-1)-.6
        with self.assertRaisesRegex(ValueError,'volume budget'):
            erode_field(field,self.spacing,dict(self.profile,maximum_removed_volume_m3=.01))

    def test_erosion_never_starts_closed_air_pockets_inside_solid_rock(self):
        field = np.abs(self.grid).max(axis=-1)-.6
        eroded,_ = erode_field(field,self.spacing,dict(self.profile,face_rate=.2))
        solid = eroded<0
        self.assertFalse((binary_fill_holes(solid) & ~solid).any())


if __name__=='__main__':
    unittest.main()
