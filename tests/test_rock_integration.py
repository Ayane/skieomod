import unittest

import numpy as np

from tools.embed_rock_sculpture import audit, clip_polygon, sample_native, splice


class RockIntegrationTests(unittest.TestCase):
    def fixture(self, offset=0):
        x,y=np.meshgrid([-2.,2.,6.],[-2.,2.,6.])
        points=np.column_stack([x.ravel(),y.ravel(),np.zeros(9)])
        faces=np.array([[0,1,3],[1,4,3],[1,2,4],[2,5,4],
                        [3,4,6],[4,7,6],[4,5,7],[5,8,7]])
        normals=np.tile([0.,0.,1.],(9,1))
        u,v=np.meshgrid(np.linspace(0,4,9),np.linspace(0,4,9))
        patch=np.column_stack([u.ravel()+.5,v.ravel()+.5,
            (.4*np.sin(u*np.pi/4)**2*np.sin(v*np.pi/4)**2+offset).ravel()])
        start=np.arange(81).reshape(9,9)[:-1,:-1].ravel()
        patch_faces=np.column_stack([start,start+1,start+9,
            start+1,start+10,start+9]).reshape(-1,3)
        info={'origin_meters':[.5,.5,0],'basis_columns':np.eye(3).tolist(),
              'reference':{'extent_meters':[4,4]},'profile':{'edge_fade_meters':1}}
        return points,normals,points[:,:2]/20,faces,patch,np.tile([0,0,1.],(81,1)),patch_faces,np.full((9,9),offset),info

    def test_splice_cuts_actual_triangles_and_preserves_open_boundary(self):
        args=self.fixture()
        points,normals,uvs,faces,report=splice(*args)
        self.assertTrue(report['outer_boundary_unchanged'])
        self.assertEqual(audit(points,faces)['nonmanifold_edges'],0)
        self.assertGreater(report['interface_knots'],0)
        self.assertAlmostEqual(points[:,2].max(),.4)
        self.assertTrue(np.isfinite(normals).all())
        for corner in args[0]:
            if not ((corner[:2]>=.5) & (corner[:2]<=4.5)).all():
                self.assertTrue(np.any(np.linalg.norm(points-corner,axis=1)<1e-7))

    def test_reference_sampling_error_is_corrected_without_erasing_sculpture(self):
        points,_,_,faces,report=splice(*self.fixture(.04))
        self.assertAlmostEqual(report['maximum_native_reference_correction_meters'],.04)
        self.assertAlmostEqual(points[:,2].max(),.4)
        self.assertEqual(audit(points,faces)['nonmanifold_edges'],0)

    def test_unrelated_source_and_patch_are_rejected(self):
        with self.assertRaisesRegex(ValueError,'differs from the native'):
            splice(*self.fixture(.2))
        args=list(self.fixture())
        args[8]=dict(args[8],origin_meters=[30,30,0])
        args[4]=args[4]+[29.5,29.5,0]
        with self.assertRaisesRegex(ValueError,'does not intersect'):
            splice(*args)

    def test_reversed_sculpture_front_is_repaired_from_native_neighbours(self):
        args=list(self.fixture())
        args[6][20]=args[6][20,[0,2,1]]
        _,_,_,_,report=splice(*args)
        self.assertGreater(report['inconsistent_shared_edges_before'],0)
        self.assertEqual(report['reoriented_triangles'],1)
        self.assertEqual(report['connected_surface_components'],1)

    def test_native_orientation_error_is_rejected(self):
        args=list(self.fixture())
        args[3][0]=args[3][0,[0,2,1]]
        with self.assertRaisesRegex(ValueError,'native source has inconsistent'):
            splice(*args)

    def test_native_attributes_match_at_the_boundary(self):
        args=list(self.fixture())
        # Native shading can differ from the volumetric patch's own normals.
        args[1]=np.tile([.6,0,.8],(9,1))
        points,normals,uvs,_,_=splice(*args)
        border=((abs(points[:,0]-.5)<1e-7) | (abs(points[:,0]-4.5)<1e-7) |
                (abs(points[:,1]-.5)<1e-7) | (abs(points[:,1]-4.5)<1e-7))
        np.testing.assert_allclose(normals[border],np.tile([.6,0,.8],(int(border.sum()),1)),atol=1e-8)
        np.testing.assert_allclose(uvs[border],points[border,:2]/20,atol=1e-8)

    def test_clipping_interpolates_depth_normals_and_uvs(self):
        triangle=np.array([[-1,0,2,1,0,0,0,0],[1,0,4,0,1,0,1,0],[1,2,6,0,0,1,1,1.]])
        clipped=clip_polygon(triangle,0,0,1)
        self.assertEqual(len(clipped),4)
        np.testing.assert_allclose(clipped[clipped[:,0]==0,2],[3,4])
        np.testing.assert_allclose(clipped[clipped[:,0]==0,6],.5)

    def test_multiple_native_surfaces_in_one_projection_are_rejected(self):
        triangle=np.array([[0,0,0,0,0,1,0,0],[2,0,0,0,0,1,1,0],[0,2,0,0,0,1,0,1.]])
        second=triangle.copy();second[:,2]=1
        with self.assertRaisesRegex(ValueError,'folds over'):
            sample_native(np.array([[.5,.5]]),[triangle,second])


if __name__=='__main__':
    unittest.main()
