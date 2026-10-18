import unittest
import numpy as np

from tools.prepare_snow_deposits import coat_surface


class SnowDepositsTests(unittest.TestCase):
    def test_ledges_retain_snow_and_their_edges_are_buried(self):
        points = np.array([[0., 0., 0.], [1., 0., 0.], [0., 1., 0.]])
        normals = np.array([[0., 0., 1.], [1., 0., 0.], [0., 0., 1.]])
        p, n, f, used = coat_surface(points, normals, np.array([[0, 1, 2]]),
                                     np.ones(3), 'snow_deposits')
        depth = ((p-points[used])*n).sum(axis=1)
        self.assertGreater(depth[0], 0)
        self.assertAlmostEqual(depth[1], -.04)
        self.assertTrue(np.all(depth <= .10))
        self.assertEqual(f.tolist(), [[0, 1, 2]])
        _, _, wall, _ = coat_surface(points, np.tile([1., 0., 0.], (3, 1)),
                                    np.array([[0, 1, 2]]), np.ones(3), 'snow_deposits')
        self.assertEqual(len(wall), 0)
        _, _, wall, _ = coat_surface(
            np.array([[0.,0.,0.],[0.,0.,1.],[0.,1.,0.]]),
            np.tile([0.,0.,1.],(3,1)),np.array([[0,1,2]]),np.ones(3),'snow_deposits')
        self.assertEqual(len(wall),0,'smoothed upward normals painted an actual vertical wall')

    def test_rim_is_local_and_shared_vertices_do_not_depend_on_partition(self):
        points = np.array([[0., 0., 0.], [1., 0., 0.], [0., 1., 0.], [1., 1., 0.]])
        # The transition coat bridges steep faces; ordinary slopes already
        # receive the native snow shell.
        points[:, 2] = points[:, 1]*2
        normals = np.tile([0., -2/np.sqrt(5), 1/np.sqrt(5)], (4, 1))
        fade = np.array([0., .15, .15, 1.])
        a, _, _, ia = coat_surface(points, normals, np.array([[0, 1, 2]]), fade, 'snow_transition')
        order=np.array([2, 0, 1])
        b, _, _, ib = coat_surface(points[order], normals[order], np.array([[0, 1, 2]]), fade[order], 'snow_transition')
        ib=order[ib]
        self.assertLess(((a-points[ia])*normals[ia]).sum(axis=1)[np.where(ia==0)[0][0]], 0)
        _, _, outside, _ = coat_surface(points,normals,np.array([[1,3,2]]),np.ones(4),'snow_transition')
        self.assertEqual(len(outside),0)
        for index in (1, 2):
            np.testing.assert_array_equal(a[np.where(ia==index)[0][0]], b[np.where(ib==index)[0][0]])


if __name__ == '__main__':
    unittest.main()
