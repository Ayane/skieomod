import json
from pathlib import Path
import unittest

import numpy as np

from tools.prepare_sculpted_massif import contour_prisms, FRONT, stone_frame, weather, IndexedSculpture, microbatch
from tools.export_sculpted_massif import (geometry_sums, simplify, validate_perimeter,
    interior_backing, SurfaceTransition, surface_normals)
from tools.assemble_sculpted_massif import conform
from tools.implicit_rock import angular_volume


class SculptedMassifTests(unittest.TestCase):
    def setUp(self):
        across = np.cross([0,0,1.],FRONT)
        self.points=np.array([across*0,across*4,[0,0,4],across*4+[0,0,4]],float)
        self.prior=np.broadcast_to(FRONT,self.points.shape).copy()
        self.uv=np.array([[0,0],[4,0],[0,4],[4,4]],float)
        self.faces=np.array([[0,1,2],[1,3,2]],dtype=np.uint32)
        self.offsets=np.linspace(-2.5,1.5,17)

    def contour(self,faces,field):
        return contour_prisms(self.points,self.prior,self.uv,faces,field,self.offsets)

    def test_untouched_native_plane_and_front_winding_are_exact(self):
        field=np.broadcast_to(self.offsets,(4,17))
        p,n,uv,f,base=self.contour(self.faces,field)
        np.testing.assert_allclose(p,base,atol=1e-12)
        _,_,_,border,_,_=geometry_sums(p,base,f)
        self.assertEqual(len(f),2)
        self.assertEqual(len(border),4)
        cross=np.cross(p[f[:,1]]-p[f[:,0]],p[f[:,2]]-p[f[:,0]])
        self.assertTrue(np.all(cross@FRONT>0))

    def test_adjacent_prisms_share_exact_relief_edges_regardless_of_vertex_order(self):
        field=self.offsets[None,:]-.4*np.sin(self.uv[:,0,None]/3)-.3*np.cos(self.uv[:,1,None]/2)
        a=self.contour(self.faces[:1],field)
        b=self.contour(self.faces[1:][:,[1,2,0]],field)
        def border(result):
            g,_,_,edges,_,_=geometry_sums(result[0],result[4],result[3])
            return {tuple(sorted((tuple(g[x]),tuple(g[y])))) for x,y in edges}
        shared=border(a)&border(b)
        self.assertGreater(len(shared),1,'relief edge has no matching subdivision')
        p=np.concatenate([a[0],b[0]]);base=np.concatenate([a[4],b[4]])
        f=np.concatenate([a[3],b[3]+len(a[0])])
        geometry_sums(p,base,f) # Rejects inconsistent fronts or >2 shared faces.

    def test_volume_can_have_undersides_and_multiple_outer_crossings(self):
        w=self.offsets[None,:]
        # An anchored lip: its underside is a real opposite-facing surface.
        field=np.broadcast_to(np.minimum(w+.8,np.maximum(w-.5,-(w+.4))),(4,17)).copy()
        p,n,uv,f,base=self.contour(self.faces,field)
        cross=np.cross(p[f[:,1]]-p[f[:,0]],p[f[:,2]]-p[f[:,0]])
        self.assertTrue(np.any(cross@FRONT<0),'underside collapsed into a displacement mesh')
        self.assertTrue(np.any(cross@FRONT>0))
        geometry_sums(p,base,f)

    def test_weathering_never_adds_material_and_zero_depth_is_identity(self):
        profile=json.loads(Path('maps/veymont/limestone-sculpture.json').read_text())
        erosion=json.loads(Path('maps/veymont/limestone-erosion.json').read_text())
        rng=np.random.default_rng(4)
        chunk=angular_volume([0,0,0],np.eye(3),[1,1,1],rng,.035,4)
        sculpture=IndexedSculpture([chunk],[],profile)
        points=np.array([[.9,0,0],[0,.8,.8],[0,0,1.1]])
        offsets=np.array([.1,.2,.4]);prior=np.tile(FRONT,(3,1))
        initial=sculpture.signed(points,offsets)
        eroded,advance=weather(sculpture,points,offsets,prior,np.ones(3),erosion)
        self.assertTrue(np.all(eroded>=initial))
        erosion['depth_meters']=0
        disabled,_=weather(sculpture,points,offsets,prior,np.ones(3),erosion)
        np.testing.assert_array_equal(initial,disabled)

    def test_frames_follow_wall_and_are_right_handed(self):
        frame=stone_frame(FRONT,.22)
        np.testing.assert_allclose(frame.T@frame,np.eye(3),atol=1e-12)
        self.assertAlmostEqual(np.linalg.det(frame),1.)
        np.testing.assert_array_equal(frame[:,2],FRONT)

    def test_envelope_retains_outer_field_surface_with_native_topology(self):
        profile=json.loads(Path('maps/veymont/limestone-sculpture.json').read_text())
        erosion=json.loads(Path('maps/veymont/limestone-erosion.json').read_text())
        erosion['depth_meters']=0
        class Native:
            pass
        native=Native();native.points=self.points+[0,0,2100]
        native.normals=self.prior;native.faces=self.faces;native.uvs=self.uv
        native.weights=np.ones(4);native.bounds=np.array([[-100,-100],[100,100]])
        native.sculpture=lambda *args:(IndexedSculpture([],[],profile),[0,0,0])
        result,metrics=microbatch(native,np.array([0,1]),profile,erosion,1.5,'envelope')
        p,n,uv,f,base=result
        np.testing.assert_allclose(p-base, np.tile(FRONT*.2,(len(p),1)),atol=1e-11)
        np.testing.assert_array_equal(p[:,2],base[:,2])
        geometry_sums(p,base,f)
        cross=np.cross(p[f[:,1]]-p[f[:,0]],p[f[:,2]]-p[f[:,0]])
        self.assertTrue(np.all(cross@FRONT>0))
        self.assertEqual(metrics['surface_mode'],'envelope')

    def test_curved_reference_edge_is_shared_after_removing_simplifier_cap(self):
        base=np.array([[0,0,0],[1,1,3],[2,2,4],[0,2,2],[2,0,2]],float)
        points=base.copy();points[1,2]+=1
        faces=np.array([[0,2,3],[0,1,2],[2,1,4],[1,0,4]],dtype=np.uint32)
        labels=np.array([0,0,1,1],dtype=np.uint8)
        result,repair,tags=conform(points,np.tile([0,0,1.],(5,1)),base[:,:2],faces,base,labels)
        g,_,_,border,_,_=geometry_sums(result[0],result[4],result[3])
        self.assertEqual(len(border),4)
        self.assertEqual(repair['removed_zero_reference_area_triangles'],1)
        self.assertEqual(repair['conformed_edges'],1)
        self.assertEqual(set(tags),{0,1})
        self.assertTrue(np.any(np.all(g==points[1],axis=1)))

    def test_outer_perimeter_accepts_subdivision_and_rejects_an_internal_hole(self):
        class Native: pass
        native=Native();native.points=np.array([[0,0,0],[1,0,0],[1,1,0],[0,1,0]],float)
        native.faces=np.array([[0,1,2],[0,2,3]],dtype=np.uint32)
        points=np.concatenate([native.points,[[.5,0,0]]])
        faces=np.array([[0,4,2],[4,1,2],[0,2,3]],dtype=np.uint32)
        def edges(f):
            g,_,_,border,_,_=geometry_sums(points,points,f)
            return {tuple(sorted((tuple(g[a]),tuple(g[b])))) for a,b in border}
        opened=edges(faces)
        self.assertEqual(validate_perimeter(opened,{e:e for e in opened},native,np.zeros(3)),4)
        opened=edges(faces[:2])
        with self.assertRaisesRegex(ValueError,'inside the massif'):
            validate_perimeter(opened,{e:e for e in opened},native,np.zeros(3))

    def test_interior_skin_is_continuous_and_stays_behind_the_deepest_cut(self):
        class Native: pass
        native=Native();native.points=self.points+[0,0,2100]
        native.faces=self.faces;native.normals=self.prior;native.sections=[34,42]
        native.face_normals=np.tile(FRONT,(2,1))
        native.first={'source_origin_centimeters':[0,0,0],'uv_tile_meters':20}
        p,n,uv,f,base=interior_backing(native,34,0)
        depth=(p-base)@FRONT
        self.assertTrue(np.all(depth<-2.2))
        self.assertEqual(len(f),len(self.faces))
        geometry_sums(p,base,f)
        self.assertEqual(len(interior_backing(native,34,1)[3]),0)
        self.assertEqual(len(interior_backing(native,42,0)[3]),0)

    def test_transition_uses_wall_distance_and_has_no_partition_phase(self):
        class Native: pass
        native=Native();native.points=np.array([[0,0,0],[0,0,24.]])
        native.weights=np.array([0.,1.])
        taper=SurfaceTransition(native,24.)
        # These points have identical DEM XY, but rise along a vertical wall.
        points=np.array([[0,0,0],[0,0,6.],[0,0,12.],[0,0,24.]])
        expected=np.array([0.,.103515625,.5,1.])
        np.testing.assert_allclose(taper.weight(points),expected)
        np.testing.assert_array_equal(taper.weight(points)[1:3],taper.weight(points[1:3]))
        near=taper.weight(np.array([[0,0,.001],[0,0,23.999]]))
        self.assertLess(near[0],1e-8)
        self.assertLess(1-near[1],1e-8)

    def test_native_lighting_matches_at_join_and_snow_sees_new_shelf(self):
        prior=np.tile(FRONT,(3,1))
        base=np.tile(FRONT,(3,1))
        geometric=np.tile([0,0,1.],(3,1))
        rock,snow=surface_normals(prior,base,geometric,np.arange(3),np.array([0.,.5,1.]))
        np.testing.assert_allclose(rock[0],FRONT)
        np.testing.assert_allclose(snow[0],FRONT)
        np.testing.assert_allclose(snow[-1],[0,0,1.],atol=1e-12)
        self.assertGreater(snow[1,2],snow[0,2])
        self.assertLess(snow[1,2],snow[-1,2])
        # The geological shading prior can tilt away from a new shelf. The
        # snow shell must still expose the real upward orientation to M_Snow.
        tilted=np.tile((FRONT+[0,0,.4])/np.sqrt(1.16),(3,1))
        _,snow=surface_normals(tilted,base,geometric,np.arange(3),np.ones(3))
        np.testing.assert_allclose(snow,geometric,atol=1e-12)


if __name__=='__main__': unittest.main()
