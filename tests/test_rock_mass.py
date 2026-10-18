import json
from pathlib import Path
import unittest

import numpy as np

from tools.prepare_rock_mass import carve, recession, smooth, stone_noise


class RockMassTests(unittest.TestCase):
    def setUp(self):
        self.profile=json.loads(Path('maps/veymont/limestone-geometry.json').read_text())
        self.profile['outer_blend_meters']=2
        self.profile['horizontal_axis']=[0, -1]
        u,z=np.meshgrid(np.linspace(0,180,91),np.linspace(2200,2000,101))
        self.points=np.column_stack([(.05*(z-2000)).ravel(),u.ravel(),z.ravel()])
        self.prior=np.broadcast_to([-1.,0,.05],self.points.shape).copy()
        self.prior/=np.linalg.norm(self.prior,axis=1,keepdims=True)
        a=np.arange(101*91).reshape(101,91)[:-1,:-1].ravel()
        self.faces=np.column_stack([a,a+1,a+91,a+1,a+92,a+91]).reshape(-1,3)

    def test_character_changes_geometry_at_metre_scale_and_makes_ledges(self):
        changed,normals,metrics=carve(self.points,self.prior,self.faces,self.profile)
        self.assertGreater(metrics['maximum_recession_meters'],4)
        self.assertGreater(metrics['vertices_with_metre_relief'],1000)
        self.assertGreater(metrics['maximum_normal_change_degrees'],45)
        self.assertGreater(normals[:,2].max(),.5,'no upward facing cornice was created')
        np.testing.assert_array_equal(changed[:,2],self.points[:,2])
        self.assertTrue(np.isfinite(normals).all())

    def test_original_perimeter_and_flat_ground_remain_exact(self):
        self.prior[4000:4050]=[0,0,1]
        changed,normals,_=carve(self.points,self.prior,self.faces,self.profile)
        perimeter=(self.points[:,0]==0)|(self.points[:,0]==10)|(self.points[:,1]==0)|(self.points[:,1]==180)
        np.testing.assert_array_equal(changed[perimeter],self.points[perimeter])
        np.testing.assert_array_equal(changed[4000:4050],self.points[4000:4050])
        # Quintic fading has zero derivative at both ends: no sharp seam strip.
        self.assertLess(smooth(.001),1e-7)
        self.assertLess(1-smooth(.999),1e-7)

    def test_shared_uv_vertices_receive_identical_positions_and_normals(self):
        # Duplicate an entire half surface as an independent projection UV set.
        points=np.concatenate([self.points,self.points])
        prior=np.concatenate([self.prior,self.prior])
        faces=np.concatenate([self.faces,self.faces+len(self.points)])
        changed,normals,_=carve(points,prior,faces,self.profile)
        np.testing.assert_array_equal(changed[:len(self.points)],changed[len(self.points):])
        np.testing.assert_allclose(normals[:len(self.points)],normals[len(self.points):],atol=1e-12)

    def test_field_does_not_reset_at_a_tile_boundary(self):
        whole=recession(self.points,self.profile)
        left=self.points[:,1]<=90
        np.testing.assert_array_equal(recession(self.points[left],self.profile),whole[left])
        np.testing.assert_array_equal(recession(self.points[~left],self.profile),whole[~left])
        middle=(abs(self.points[:,1]-90)<1e-8)&(self.points[:,0]>3)&(self.points[:,0]<7)
        changed,_,_=carve(self.points,self.prior,self.faces,self.profile)
        self.assertGreater(np.linalg.norm(changed[middle]-self.points[middle],axis=1).max(),1,
                           'the internal join still fades to the smooth heightfield')

    def test_massive_upper_faces_receive_local_detail_without_a_grid_jump(self):
        points=self.points.copy();points[:,2]+=300
        detailed=recession(points,self.profile)
        self.profile['surface_recession_meters']=0
        plain=recession(points,self.profile)
        self.assertGreater(np.ptp(detailed-plain),.5)
        around=stone_noise(np.array([9-1e-5,9+1e-5]),np.array([2300,2300]),9,17)
        self.assertLess(abs(around[1]-around[0]),1e-6)


if __name__=='__main__': unittest.main()
