import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from tools.extract_rock_features import TriangulatedHeightfield, ridge_candidates
from tools.implicit_rock import (Block, CliffField, Fracture, ReferenceSurface,
    make_sculpture, poisson_surface, polygonize_tetrahedra, project_sculpture,
    RockSculpture, visible_clusters)
from tools.prepare_implicit_cliff import consolidate_volume,validate_profile


class ImplicitRockTests(unittest.TestCase):
    def setUp(self):
        self.profile = json.loads(Path('maps/veymont/limestone-blocks.json').read_text())
        self.profile.update(core_recession_meters=3, edge_fade_meters=1,
                            maximum_outset_meters=2, detail_amplitude_meters=0,sample_back_meters=5)
        self.reference = ReferenceSurface(np.zeros((11,9)), [8,10])

    def tilted_block(self):
        # A convex slab leans outward: it joins the core on the left but
        # leaves an air gap underneath the projecting part on the right.
        planes = np.array([[-1,0,0,2],[1,0,0,-6],[0,-1,0,2],[0,1,0,-8],
                           [.7,0,-1,-5],[-.7,0,1,2]])
        planes /= np.linalg.norm(planes[:,:3],axis=1)[:,None]
        return Block(planes,np.array([[1.9,1.9,-3.8],[6.1,8.1,2.3]]),.03,17)

    def test_volume_can_have_an_overhang_and_a_backing_on_the_same_ray(self):
        cliff = CliffField(self.reference,[self.tilted_block()],self.profile)
        d = np.linspace(-5,3,1001)
        ray = np.column_stack([np.full_like(d,5),np.full_like(d,5),d])
        signs = cliff.signed(ray)<0
        self.assertEqual(np.count_nonzero(signs[1:]!=signs[:-1]),3,
                         'this is still just a single displaced heightfield surface')
        below = cliff.normals(np.array([[5,5,-1.5]]),.001)[0]
        self.assertLess(below[2],-.5, 'the overhang has no inward-facing underside')

    def test_boundary_keeps_original_positions_and_first_derivatives(self):
        cliff = CliffField(self.reference,[self.tilted_block()],self.profile)
        points = np.array([[0,5,.1],[8,5,.1],[4,0,.1],[4,10,.1]],dtype=float)
        np.testing.assert_array_equal(cliff.signed(points),points[:,2])
        np.testing.assert_allclose(cliff.normals(points,.00001),[np.array([0,0,1])]*4,atol=1e-8)
        near = np.array([[.001,5,.1]])
        self.assertLess(abs(cliff.signed(near)[0]-.1),1e-6)

    def test_photographic_candidate_warp_changes_geometry_with_correct_sign(self):
        u,v = np.meshgrid(np.linspace(0,8,9),np.linspace(0,10,11))
        detail = ReferenceSurface(.05*u,[8,10])
        cliff = CliffField(self.reference,[],self.profile,[],detail)
        np.testing.assert_allclose(cliff.signed(np.array([[4,5,.2]])),0,atol=1e-10)
        expected = np.array([-.05,0,1]);expected /= np.linalg.norm(expected)
        np.testing.assert_allclose(cliff.normals(np.array([[4,5,.2]]),.001)[0],expected,atol=1e-8)

    def test_short_photographic_trace_does_not_become_a_full_wall_groove(self):
        fracture = Fracture(np.array([4,5,0]),np.array([1.,0,0]),3,
                            np.array([[4,4],[4,6]],dtype=float))
        cliff = CliffField(self.reference,[self.tilted_block()],self.profile,[fracture])
        self.assertEqual(cliff.presence(np.array([[4,5]]))[0],1)
        self.assertEqual(cliff.presence(np.array([[4,0]]))[0],0)
        self.assertEqual(cliff.presence(np.array([[7.5,5]]))[0],0)
        np.testing.assert_allclose(cliff.signed(np.array([[4,0,.2]])),.2)

    def test_finite_fractures_do_not_cut_segments_beyond_the_disk(self):
        fracture = Fracture(np.zeros(3),np.array([1.,0,0]),2)
        a = np.array([[-1,0,0],[-1,3,0],[-1,0,3]])
        b = a+np.array([2,0,0])
        np.testing.assert_array_equal(fracture.crosses(a,b),[True,False,False])

    def test_visibility_clusters_cannot_wrap_around_a_fracture_end(self):
        points = np.random.default_rng(10).uniform(-2,2,(250,3))
        fracture = Fracture(np.zeros(3),np.array([1.,0,0]),1)
        clusters = visible_clusters(points,[fracture],1.6,6)
        self.assertGreater(len(clusters),1)
        for cluster in clusters:
            self.assertFalse(fracture.crosses(cluster[:,None],cluster[None,:]).any())

    def test_poisson_samples_have_actual_metric_separation(self):
        points = poisson_surface(self.reference,1,1200,17,3,1)
        from scipy.spatial import cKDTree
        self.assertGreater(len(points),100)
        self.assertFalse(cKDTree(points).query_pairs(1-1e-10))
        relative = self.reference.signed(points)
        self.assertGreaterEqual(relative.min(),-3)
        self.assertLessEqual(relative.max(),1)

    def test_polygonized_sphere_is_welded_and_closed(self):
        axis = np.linspace(-1.5,1.5,20)
        grid = np.stack(np.meshgrid(axis,axis,axis,indexing='ij'),axis=-1)
        field = np.linalg.norm(grid,axis=-1)-1
        vertices,faces = polygonize_tetrahedra(field,np.full(3,-1.5),np.full(3,3/19),10000,20000)
        self.assertLess(np.abs(np.linalg.norm(vertices,axis=1)-1).max(),.015)
        edges = np.sort(np.concatenate([faces[:,[0,1]],faces[:,[1,2]],faces[:,[2,0]]]),axis=1)
        _,counts = np.unique(edges,axis=0,return_counts=True)
        np.testing.assert_array_equal(counts,np.full(len(counts),2))
        with self.assertRaisesRegex(ValueError,'budget'):
            polygonize_tetrahedra(field,np.full(3,-1.5),np.full(3,3/19),10,20)

    def test_native_diagonal_is_used_instead_of_bilinear_interpolation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            np.array([[0,10],[20,100]],dtype='<u2').tofile(root/'height.r16')
            definition = {'terrain':{'size_meters':[1,1],'origin_centimeters':[0,0,12300],
                'source':{'format':'r16le','file':'height.r16','vertices':[2,2],
                          'spacing_meters':1,'height_scale_meters':1,'height_offset_meters':0}}}
            (root/'map.json').write_text(json.dumps(definition))
            field = TriangulatedHeightfield(root/'map.json')
            np.testing.assert_allclose(field.sample(np.array([[.25,.25,0],[.75,.75,0],[1,1,0]])),
                                       [130.5,180.5,223])

    def test_near_grid_node_intersections_leave_no_interior_mesh_cracks(self):
        axis = np.linspace(0,2,11)
        u,v,d = np.meshgrid(axis,axis,axis,indexing='ij')
        field = d-.8-1e-9+.1*u
        p,f = polygonize_tetrahedra(field,np.zeros(3),np.full(3,.2),5000,10000)
        edges = np.sort(np.concatenate([f[:,[0,1]],f[:,[1,2]],f[:,[2,0]]]),axis=1)
        unique,counts = np.unique(edges,axis=0,return_counts=True)
        self.assertTrue(np.all(counts<=2))
        boundary = p[unique[counts==1],:2]
        outer = np.any(np.all(np.isclose(boundary,0),axis=1) |
                       np.all(np.isclose(boundary,2),axis=1),axis=1)
        self.assertTrue(outer.all())

    def test_dark_ridge_orientation_is_an_observation_not_a_measured_depth(self):
        u,v = np.meshgrid(np.linspace(0,8,65),np.linspace(0,10,81))
        shade = .85-.5*np.exp(-((u-4)/.15)**2)
        rgb = shade[...,None]*np.array([1,.8,.6])
        candidates,_ = ridge_candidates(rgb,np.ones(u.shape,bool),[8,10],np.zeros_like(u))
        self.assertGreater(len(candidates),0)
        self.assertGreater(abs(candidates[0]['normal_local'][0]),.99)
        self.assertFalse(candidates[0]['fracture_verified'])
        self.assertFalse(candidates[0]['depth_measured'])
        empty,_ = ridge_candidates(rgb,np.zeros(u.shape,bool),[8,10],np.zeros_like(u))
        self.assertEqual(empty,[])

    def test_unresolved_surface_detail_and_excessive_budgets_are_rejected(self):
        validate_profile(self.profile)
        for changes in [{'detail_scale_meters':.6},{'max_grid_samples':3000000},
                        {'sample_back_meters':2},{'seed':True}]:
            with self.subTest(changes=changes),self.assertRaises(ValueError):
                validate_profile(dict(self.profile,**changes))


class RockSculptureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profile = json.loads(Path('maps/veymont/limestone-sculpture.json').read_text())
        cls.reference = ReferenceSurface(np.zeros((61,41)),[12,18])
        cls.sculpture,cls.levels = make_sculpture(cls.reference,cls.profile)
        cls.cliff = CliffField(cls.reference,[],cls.profile,[],sculpture=cls.sculpture)
        u,v = np.meshgrid(np.linspace(3,9,21),np.linspace(3,15,41))
        cls.uv = np.stack([u,v],axis=-1).reshape(-1,2)
        cls.depth_axis = np.linspace(-2.2,1.2,103)
        p = np.concatenate([np.broadcast_to(cls.uv[:,None,:],(len(cls.uv),103,2)),
                            np.broadcast_to(cls.depth_axis[None,:,None],(len(cls.uv),103,1))],axis=-1)
        cls.sampled = cls.cliff.signed(p)

    def test_sculpture_breaks_open_faces_without_any_photo_fracture(self):
        # A featureless flat reference and an empty fracture list must still
        # have substantial geometric relief distributed over the face.
        sign = self.sampled<0
        front = np.where(sign,self.depth_axis[None,:],-np.inf).max(axis=1)
        self.assertGreater(np.ptp(front),.9)
        self.assertGreater(np.mean(np.abs(front)>.25),.3)
        self.assertEqual(len(self.levels),3)

    def test_sculpture_has_real_undercuts_not_only_a_height_graph(self):
        sign = self.sampled<0
        crossings = np.count_nonzero(sign[:,1:]!=sign[:,:-1],axis=1)
        self.assertGreater(np.count_nonzero(crossings>=3),5)
        self.assertTrue(sign[:,0].all(),'rock must retain its solid backing')
        self.assertFalse(sign[:,-1].any(),'rock must stay inside the outward envelope')

    def test_sculpture_keeps_the_original_boundary_position_and_tangent(self):
        p = np.array([[0,9,.1],[12,9,.1],[6,0,.1],[6,18,.1]])
        np.testing.assert_array_equal(self.cliff.signed(p),p[:,2])
        np.testing.assert_allclose(self.cliff.normals(p,.00001),[[0,0,1]]*4,atol=1e-8)

    def test_sculpture_volume_budget_is_checked_before_building_shapes(self):
        profile = dict(self.profile,sculpture=dict(self.profile['sculpture'],max_volumes=10))
        with self.assertRaisesRegex(ValueError,'budget exceeded before allocation'):
            make_sculpture(self.reference,profile)

    def test_child_weathering_reaches_the_recessed_parent_face(self):
        # A flat reference has a broad 1.4 m-deep cavity. Weathering tools
        # attached to z=0 would float above its floor and leave it smooth.
        planes = np.array([[1,0,0,-9],[-1,0,0,3],[0,1,0,-13],[0,-1,0,5],
                           [0,0,1,-1.1],[0,0,-1,-1.4]],dtype=float)
        cutter = Block(planes,np.array([[2.9,4.9,-1.5],[9.1,13.1,1.2]]),.02,1)
        sculpture = RockSculpture([], [cutter],self.profile['sculpture'])
        points,normals = project_sculpture(self.reference,sculpture,np.array([[6.,9.]]),self.profile)
        np.testing.assert_allclose(points,[[6,9,-1.4]],atol=1e-4)
        np.testing.assert_allclose(normals,[[0,0,1]],atol=1e-8)

    def test_unresolved_sculpture_and_invalid_style_parameters_are_rejected(self):
        validate_profile(self.profile)
        for update in [{'max_volumes':513},{'root_depth_meters':False},
                       {'levels':[{'spacing_meters':1,'density':1,'cut_depth_meters':.2,
                                   'radii_meters':[.02,.1,.2]}]}]:
            profile = dict(self.profile,sculpture=dict(self.profile['sculpture'],**update))
            with self.subTest(update=update),self.assertRaises(ValueError):
                validate_profile(profile)

    def test_released_spalls_are_removed_but_large_floating_blocks_are_rejected(self):
        field = np.ones((13,13,13))
        field[:,:,:3] = -1
        field[5:7,5:7,8:10] = -1
        metrics = consolidate_volume(field,np.full(3,.2),self.profile)
        self.assertEqual(metrics['unanchored_grid_samples_removed'],8)
        self.assertTrue((field[:,:,:3]<0).all(),'the rooted mass was eroded')
        self.assertTrue((field[5:7,5:7,8:10]>0).all(),'a floating spall remains')
        field[4:8,4:8,8:12] = -1
        with self.assertRaisesRegex(ValueError,'volume budget'):
            consolidate_volume(field,np.full(3,.2),self.profile)

    def test_large_sealed_cavities_are_rejected_for_compact_stone(self):
        field = np.ones((13,13,13))
        field[:,:,:6] = -1
        field[6,6,3] = 1
        metrics = consolidate_volume(field,np.full(3,.2),self.profile)
        self.assertEqual(metrics['enclosed_grid_samples_filled'],1)
        self.assertLess(field[6,6,3],0)
        field[4:7,4:7,2:5] = 1
        with self.assertRaisesRegex(ValueError,'volume budget'):
            consolidate_volume(field,np.full(3,.2),self.profile)

    def test_many_small_spalls_cannot_bypass_the_total_eroded_volume_budget(self):
        field = np.ones((32,32,16))
        field[:,:,:3] = -1
        for x in range(3,30,3):
            for y in (4,10):
                field[x:x+2,y:y+2,8:10] = -1
        with self.assertRaisesRegex(ValueError,'volume budget'):
            consolidate_volume(field,np.full(3,.2),self.profile)


if __name__=='__main__':
    unittest.main()
