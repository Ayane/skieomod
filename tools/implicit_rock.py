"""Bounded volumetric rock blocks and hierarchical constructive sculpture.

Original implementations. Inspired by Paris et al. (TVC 2020), fracture disks cut a visibility graph of Poisson
samples; convex clusters become implicit half-space intersections. The fields
are composed with an anchored rock core, not displaced heightfield vertices.
The separate sculpture model adds masses and removes finite angular chips,
then projects each smaller weathering scale onto the exposed parent faces.
All coordinates are local metres [across wall, up, outward]. These scalar
fields have a consistent sign but are not exact Euclidean signed distances.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import math

import numpy as np
from scipy.ndimage import map_coordinates
from scipy.spatial import ConvexHull, cKDTree, QhullError


def unit(v):
    return v/np.maximum(np.linalg.norm(v, axis=-1, keepdims=True), 1e-12)


def smooth(v):
    t = np.clip(v, 0, 1)
    return t*t*t*(10+t*(-15+6*t))


@dataclass
class Fracture:
    center: np.ndarray
    normal: np.ndarray
    radius: float
    trace: np.ndarray | None = None

    def crosses(self, a, b):
        da, db = (a-self.center)@self.normal, (b-self.center)@self.normal
        delta = da-db
        t = np.divide(da, delta, out=np.zeros_like(delta), where=np.abs(delta)>1e-12)
        hit = a+t[..., None]*(b-a)
        return (da*db < 0) & (np.linalg.norm(hit-self.center, axis=-1) < self.radius)


class ReferenceSurface:
    def __init__(self, depth, extent):
        self.depth = np.asarray(depth, dtype=float)
        self.extent = np.asarray(extent, dtype=float)
        if (self.depth.ndim != 2 or min(self.depth.shape)<2 or not np.isfinite(self.depth).all()
                or self.extent.shape != (2,) or not np.isfinite(self.extent).all()
                or np.any(self.extent<=0)):
            raise ValueError('invalid reference surface')

    def sample(self, uv):
        rows, columns = self.depth.shape
        uv = np.asarray(uv)
        xy = uv.reshape(-1, 2).T
        coordinates = [xy[1]/self.extent[1]*(rows-1), xy[0]/self.extent[0]*(columns-1)]
        return map_coordinates(self.depth, coordinates, order=1, mode='nearest').reshape(uv.shape[:-1])

    def signed(self, p):
        return p[..., 2]-self.sample(p[..., :2])


def poisson_surface(reference, separation, attempts, seed, back, front):
    """Dart throwing using spatial hashing, with no regular point lattice."""
    rng = np.random.default_rng(seed)
    cell_size = separation/math.sqrt(3)
    points, cells = [], {}
    offsets = np.array(np.meshgrid(*([np.arange(-2, 3)]*3), indexing='ij')).reshape(3, -1).T
    proposals = rng.uniform(size=(attempts, 3))
    proposals[:, :2] *= reference.extent
    proposals[:, 2] = reference.sample(proposals[:, :2])-back+proposals[:, 2]*(back+front)
    for p in proposals:
        cell = np.floor(p/cell_size).astype(int)
        nearby = [i for offset in offsets for i in cells.get(tuple(cell+offset), [])]
        if nearby and np.any(np.linalg.norm(np.array([points[i] for i in nearby])-p, axis=1)<separation):
            continue
        cells.setdefault(tuple(cell), []).append(len(points))
        points.append(p)
        if len(points)>6000:
            raise ValueError('Poisson point budget exceeded; increase separation')
    return np.asarray(points)


def visible_clusters(points, fractures, radius, maximum_diameter):
    """Connected graph clusters, requiring mutual visibility through disks."""
    tree = cKDTree(points)
    if (tree.count_neighbors(tree,radius)-len(points))//2>2_000_000:
        raise ValueError('visibility graph edge budget exceeded')
    edges = tree.query_pairs(radius, output_type='ndarray')
    usable = np.ones(len(edges), bool)
    for disk in fractures:
        usable &= ~disk.crosses(points[edges[:, 0]], points[edges[:, 1]])
    neighbours = [[] for _ in points]
    for a, b in edges[usable]:
        neighbours[a].append(int(b)); neighbours[b].append(int(a))
    taken = np.zeros(len(points), bool)
    clusters = []
    for start in range(len(points)):
        if taken[start]:
            continue
        accepted, queued = [start], {start}
        taken[start] = True
        queue = deque(neighbours[start])
        while queue:
            candidate = queue.popleft()
            if taken[candidate] or candidate in queued:
                continue
            queued.add(candidate)
            members = points[accepted]
            p = points[candidate]
            if np.any(np.linalg.norm(members-p, axis=1)>maximum_diameter):
                continue
            if any(disk.crosses(members, p).any() for disk in fractures):
                continue
            accepted.append(candidate); taken[candidate] = True
            queue.extend(neighbours[candidate])
        if len(accepted)>=12:
            clusters.append(points[accepted])
    return clusters


def noise3(p, scale, seed):
    """Continuous 3D value noise; used only after the block structure exists."""
    q = p/scale
    cell = np.floor(q)
    t = smooth(q-cell)
    value = np.zeros(len(p))
    for x in (0, 1):
        for y in (0, 1):
            for z in (0, 1):
                corner = cell+np.array([x, y, z])
                h = np.mod(np.sin(corner@np.array([127.1, 311.7, 74.7])+seed*19.19)*43758.5453, 1)
                weight = np.prod(np.where([x, y, z], t, 1-t), axis=1)
                value += weight*h
    return 2*value-1


class Block:
    def __init__(self, planes, bounds, rounding, seed):
        self.planes, self.bounds = planes, bounds
        self.rounding, self.seed = rounding, seed

    def raw(self, points, gradient=False, gradient_rounding=None):
        d = points@self.planes[:, :3].T+self.planes[:, 3]
        maximum = d.max(axis=1)
        # Smooth intersection of half-spaces. Its gradient rounds block edges.
        weights = np.exp((d-maximum[:, None])/self.rounding)
        total = weights.sum(axis=1)
        value = maximum+self.rounding*np.log(total)
        if gradient:
            if gradient_rounding is not None and gradient_rounding>self.rounding:
                weights = np.exp((d-maximum[:,None])/gradient_rounding)
                total = weights.sum(axis=1)
            return value, unit(weights@self.planes[:, :3]/total[:, None])
        return value

    def signed(self, points, detail_amplitude, detail_scale):
        # A rapidly turning edge normal can fold the inverse warp. Smooth its
        # direction over a radius larger than the displacement amplitude,
        # while preserving the smaller geometric edge rounding itself.
        value, normal = self.raw(points, gradient=True,
                                 gradient_rounding=max(self.rounding,4*detail_amplitude))
        if detail_amplitude:
            detail = (.7*noise3(points, detail_scale, self.seed)
                      + .3*noise3(points, detail_scale*2.3, self.seed+1))
            value = self.raw(points-normal*(detail_amplitude*detail)[:, None])
        return value


def make_blocks(clusters, reference, normal_candidates, confidence, profile):
    blocks, unsupported = [], 0
    rows, columns = confidence.shape
    for number, points in enumerate(clusters):
        # A detached front fragment cannot be attached by the backing core.
        if reference.signed(points).min()>-profile['core_recession_meters']-.1:
            unsupported += 1
            continue
        try:
            hull = ConvexHull(points)
        except QhullError:
            continue
        planes = np.unique(np.round(hull.equations, 10), axis=0)
        center = points.mean(axis=0)
        x = np.clip(int(round(center[0]/reference.extent[0]*(columns-1))), 0, columns-1)
        y = np.clip(int(round(center[1]/reference.extent[1]*(rows-1))), 0, rows-1)
        # This normal is a prior-constrained photographic candidate, not a
        # uniquely measured normal. Unusable observations leave the DEM prior.
        normal = normal_candidates[y, x]
        if confidence[y, x] and normal[2]>.5:
            point = np.array([center[0], center[1], reference.sample(center[:2])+
                              profile['front_offset_meters']])
            planes = np.vstack([planes, np.r_[normal, -normal@point]])
        margin = profile['rounding_meters']+profile['detail_amplitude_meters']+.1
        blocks.append(Block(planes, np.array([points.min(axis=0)-margin,
                                             points.max(axis=0)+margin]),
                            profile['rounding_meters'], profile['seed']+number*17))
    if not blocks:
        raise ValueError('fracturing produced no supported blocks')
    if len(blocks)>profile['max_blocks']:
        raise ValueError('block budget exceeded; increase Poisson separation')
    return blocks, unsupported


def angular_volume(center, frame, radii, rng, rounding, seed, lean=0.):
    """An irregular convex solid with bevels and several broken face planes.

    Two unequal polygon rings form a volume, not a surface displacement.
    Randomness changes the shape of each solid, rather than its colour.
    """
    # Variable triangles and broken slab footprints, rather than a circular
    # ring which makes the result look like rounded craters.
    footprints = [
        [[-1,-.8],[1,-.6],[-.3,1]],
        [[-1,-.65],[.75,-1],[1,.8],[-.65,1]],
        [[-1,-.65],[-.65,-1],[1,-.8],[.85,1],[-1,.75]]]
    ring = np.array(footprints[int(rng.integers(len(footprints)))],dtype=float)
    ring += rng.uniform(-.12,.12,ring.shape)
    count = len(ring)
    vertices = []
    for side in (-1,1):
        xy = ring*radii[:2]*rng.uniform(.78,1.13,(count,1))
        xy[:,1] += side*lean*radii[1]
        z = side*radii[2]+rng.uniform(-.2,.2,count)*radii[2]
        vertices.extend(np.column_stack([xy,z]))
    vertices = center+np.asarray(vertices)@frame.T
    hull = ConvexHull(vertices)
    planes = np.unique(np.round(hull.equations,10),axis=0)
    return Block(planes,np.array([vertices.min(axis=0)-rounding*2,
                                 vertices.max(axis=0)+rounding*2]),rounding,seed)


def normal_frame(normal, angle):
    normal = unit(normal)
    across = np.cross([0.,1.,0.],normal)
    if np.linalg.norm(across)<1e-6:
        across = np.cross([1.,0.,0.],normal)
    across = unit(across)
    up = np.cross(normal,across)
    across,up = across*np.cos(angle)+up*np.sin(angle),up*np.cos(angle)-across*np.sin(angle)
    return np.column_stack([across,up,normal])


def surface_frame(reference, uv, angle):
    """Frame following the macro wall; its third axis is the outward normal."""
    step = .1
    du = (reference.sample(uv+[step,0])-reference.sample(uv-[step,0]))/(2*step)
    dv = (reference.sample(uv+[0,step])-reference.sample(uv-[0,step]))/(2*step)
    return normal_frame(np.array([-du,-dv,1.]),angle)


class RockSculpture:
    """Add anchored rock masses, then remove angular chips over their faces.

    The procedural sizes are style parameters, not measured photo depths.
    No image ridge is converted into a wall-wide slit. Each cutter is a closed
    finite 3D volume; neighbouring cuts expose irregular residual facets.
    """
    def __init__(self, chunks, cutters, settings):
        self.chunks,self.cutters,self.settings = chunks,cutters,settings

    def signed(self, points, base):
        value = base-self.settings['mass_offset_meters']
        for additive,solids in [(True,self.chunks),(False,self.cutters)]:
            for solid in solids:
                inside = ((points>=solid.bounds[0]) & (points<=solid.bounds[1])).all(axis=1)
                if inside.any():
                    sample = solid.raw(points[inside])
                    if additive:
                        value[inside] = np.minimum(value[inside],sample)
                    else:
                        value[inside] = np.maximum(value[inside],-sample)
        return value


def project_sculpture(reference, sculpture, uv, profile):
    """Attach the next weathering scale to the exposed parent rock surface.

    Use bounded fixed-step rays followed by bisection, not distance marching:
    this field is not a Euclidean SDF. Small tools must reach recessed faces,
    not just the original DEM plane floating in front of those faces.
    """
    def signed(points):
        base = reference.signed(points)
        value = sculpture.signed(points,base)
        return np.minimum(np.maximum(value,base-profile['maximum_outset_meters']),
                          base+profile['core_recession_meters'])
    offsets = np.linspace(-profile['core_recession_meters']-.3,
                          profile['maximum_outset_meters']+.3,81)
    points = np.zeros((len(uv),len(offsets),3))
    points[:,:,:2] = uv[:,None,:]
    points[:,:,2] = reference.sample(uv)[:,None]+offsets
    values = signed(points.reshape(-1,3)).reshape(len(uv),-1)
    crossings = (values[:,:-1]<0) & (values[:,1:]>=0)
    last = np.where(crossings,np.arange(len(offsets)-1)[None,:],-1).max(axis=1)
    if (last<0).any():
        raise ValueError('cannot attach weathering tool to a parent surface')
    lo,hi = points[np.arange(len(uv)),last].copy(),points[np.arange(len(uv)),last+1].copy()
    for _ in range(10):
        mid = (lo+hi)/2
        inside = signed(mid)<0
        lo[inside],hi[~inside] = mid[inside],mid[~inside]
    point = (lo+hi)/2
    epsilon = profile['voxel_spacing_meters']*.15
    normal = unit(np.stack([signed(point+axis)-signed(point-axis)
                            for axis in np.eye(3)*epsilon],axis=-1))
    return point,normal


def make_sculpture(reference, profile):
    """Bounded hierarchical volumes, distributed without a regular grid."""
    settings = profile['sculpture']
    rng = np.random.default_rng(profile['seed'])
    chunks,cutters,levels = [],[],[]
    area = float(np.prod(reference.extent))
    targets = [int(np.ceil(area/(level['spacing_meters']**2)*level['density']))
               for level in settings['levels']]
    if sum(targets)+(targets[0] if settings['protruding_fraction'] else 0)>settings['max_volumes']:
        raise ValueError('sculpture volume budget exceeded before allocation')
    for index,level in enumerate(settings['levels']):
        spacing = level['spacing_meters']
        # Dart throwing in wall coordinates, including overlapping footprints.
        centers = []
        target = targets[index]
        for uv in rng.uniform([0,0],reference.extent,(max(100,target*20),2)):
            if centers and np.min(np.linalg.norm(np.asarray(centers)-uv,axis=1))<spacing*.65:
                continue
            centers.append(uv)
            if len(centers)>=target:
                break
        levels.append({'scale_meters':spacing,'cutters':len(centers)})
        if index:
            parent_points,parent_normals = project_sculpture(reference,
                RockSculpture(chunks,cutters,settings),np.asarray(centers),profile)
            levels[-1]['anchored_to'] = 'exposed-parent-volume'
        else:
            levels[-1]['anchored_to'] = 'native-macro-surface'
        for number,uv in enumerate(centers):
            angle = rng.uniform(-.35,.35)
            if index:
                frame = normal_frame(parent_normals[number],angle)
                point = parent_points[number]
            else:
                frame = surface_frame(reference,uv,angle)
                point = np.r_[uv,reference.sample(uv)]
            radii = np.array(level['radii_meters'])*rng.uniform(.7,1.25,3)
            depth = level['cut_depth_meters']*rng.uniform(.55,1.25)
            # Rotate the removal tool: its back and bevel faces become new
            # rock facets, while finite sides form broken, uneven rims.
            tilt = rng.uniform(-.32,.32)
            rotation = np.array([[np.cos(tilt),0,np.sin(tilt)],
                                 [0,1,0],[-np.sin(tilt),0,np.cos(tilt)]])
            frame = frame@rotation
            center = point+frame[:,2]*(radii[2]-depth)
            cutters.append(angular_volume(center,frame,radii,rng,
                settings['edge_rounding_meters'],profile['seed']+len(cutters)))
            if index==0 and rng.random()<settings['protruding_fraction']:
                # A deep root and a leaning front form small ledges and
                # undersides. These are clipped by the same local envelope.
                root = settings['root_depth_meters']
                front = settings['protrusion_meters']*rng.uniform(.6,1.1)
                chunk_radii = np.array([radii[0]*.8,radii[1]*.85,(root+front)/2])
                center = point+frame[:,2]*(front-root)/2
                chunks.append(angular_volume(center,frame,chunk_radii,rng,
                    settings['edge_rounding_meters'],profile['seed']+4096+len(chunks),lean=.4))
            if len(cutters)+len(chunks)>settings['max_volumes']:
                raise ValueError('sculpture volume budget exceeded')
    return RockSculpture(chunks,cutters,settings),levels


class CliffField:
    def __init__(self, reference, blocks, profile, fractures=None, photographic_detail=None,
                 sculpture=None):
        self.reference, self.blocks, self.profile = reference, blocks, profile
        self.fractures = fractures
        self.photographic_detail = photographic_detail
        self.sculpture = sculpture

    def presence(self, uv):
        if self.fractures is None:
            return np.ones(uv.shape[:-1])
        distance = np.full(uv.shape[:-1],np.inf)
        for fracture in self.fractures:
            if fracture.trace is None:
                continue
            a,b = fracture.trace
            tangent = b-a
            length_squared = tangent@tangent
            t = np.clip((uv-a)@tangent/max(length_squared,1e-12),0,1)
            distance = np.minimum(distance,np.linalg.norm(uv-a-t[...,None]*tangent,axis=-1))
        return 1-smooth(distance/self.profile['fracture_zone_meters'])

    def fade(self, uv):
        distance = np.minimum(uv, self.reference.extent-uv).min(axis=-1)
        return smooth(distance/self.profile['edge_fade_meters'])

    def signed(self, points):
        shape = points.shape[:-1]
        p = np.asarray(points, dtype=float).reshape(-1, 3)
        output = np.empty(len(p))
        for start in range(0, len(p), 8192):
            q = p[start:start+8192]
            raw_base = self.reference.signed(q)
            warped = q.copy()
            if self.photographic_detail is not None:
                warped[:,2] -= self.photographic_detail.sample(q[:,:2])
            base = self.reference.signed(warped)
            if self.sculpture is not None:
                # Sculpture covers faces as well as discontinuities. Small
                # roughness is applied after the constructive solid geometry.
                value = self.sculpture.signed(warped,base)
                value -= self.profile['detail_amplitude_meters']*noise3(warped,
                    self.profile['detail_scale_meters'],self.profile['seed']+7919)
            else:
                value = base+self.profile['core_recession_meters']
                for block in self.blocks:
                    inside = ((warped>=block.bounds[0]) & (warped<=block.bounds[1])).all(axis=1)
                    if inside.any():
                        value[inside] = np.minimum(value[inside], block.signed(warped[inside],
                            self.profile['detail_amplitude_meters'], self.profile['detail_scale_meters']))
                # Keep finite photographic features finite: convex clusters can
                # otherwise extend a short fracture into a long planar groove.
                detail = self.profile['detail_amplitude_meters']*noise3(warped,
                    self.profile['detail_scale_meters'],self.profile['seed']+7919)
                background = base-detail
                presence = self.presence(q[:,:2])
                value = background+(value-background)*presence
            # Preserve the macro envelope; retain a solid, connected backing.
            value = np.maximum(value, raw_base-self.profile['maximum_outset_meters'])
            value = np.minimum(value, raw_base+self.profile['core_recession_meters'])
            fade = self.fade(q[:, :2])
            output[start:start+len(q)] = raw_base+(value-raw_base)*fade
        return output.reshape(shape)

    def normals(self, points, epsilon):
        gradients = []
        for axis in np.eye(3)*epsilon:
            gradients.append(self.signed(points+axis)-self.signed(points-axis))
        return unit(np.stack(gradients, axis=-1))


def polygonize_tetrahedra(field, origin, spacing, max_vertices, max_triangles):
    """Extract only zero-crossing cells, with welded shared tetrahedron edges.

    The six-tetrahedra split shares face diagonals across adjacent cubes. Mesh
    normals are later evaluated on the continuous implicit field, not on its
    triangulation. No volume-sized point/plane matrices are constructed.
    """
    f = np.asarray(field)
    if f.ndim!=3 or min(f.shape)<2 or not np.isfinite(f).all():
        raise ValueError('invalid sampled field')
    corners = np.array([[0,0,0],[1,0,0],[1,1,0],[0,1,0],
                        [0,0,1],[1,0,1],[1,1,1],[0,1,1]])
    slices = [f[x:x+f.shape[0]-1, y:y+f.shape[1]-1, z:z+f.shape[2]-1]
              for x,y,z in corners]
    low, high = np.minimum.reduce(slices), np.maximum.reduce(slices)
    cells = np.argwhere((low<0) & (high>=0))
    # An upper bound on output, checked before allocating intersection arrays.
    if len(cells)*12>max_triangles*4:
        raise ValueError('zero-crossing cell budget exceeded')
    cube_nodes = cells[:, None, :]+corners
    cube_ids = np.ravel_multi_index(np.moveaxis(cube_nodes, -1, 0), f.shape)
    cube_values = f.reshape(-1)[cube_ids]
    tetrahedra = [[0,1,2,6],[0,2,3,6],[0,3,7,6],
                  [0,7,4,6],[0,4,5,6],[0,5,1,6]]
    edges = []
    # Each crossing triangle is represented by three grid-edge endpoint pairs.
    for t in tetrahedra:
        ids, values = cube_ids[:, t], cube_values[:, t]
        flags = (values<0)@np.array([1,2,4,8])
        for case in range(1, 15):
            selected = ids[flags==case]
            if not len(selected):
                continue
            negative = [i for i in range(4) if case & (1<<i)]
            positive = [i for i in range(4) if not case & (1<<i)]
            if len(negative)==1 or len(positive)==1:
                inner, outer = (negative, positive) if len(negative)==1 else (positive, negative)
                pairs = [(inner[0], j) for j in outer]
                edges.append(selected[:, pairs].reshape(-1, 3, 2))
            else:
                a,b = negative; c,d = positive
                pairs = [(a,c),(a,d),(b,c),(a,d),(b,d),(b,c)]
                edges.append(selected[:, pairs].reshape(-1, 3, 2))
    if not edges:
        raise ValueError('no zero surface in the sampled volume')
    edges = np.concatenate(edges)
    if len(edges)>max_triangles:
        raise ValueError(f'triangle budget exceeded: {len(edges)} > {max_triangles}')
    pairs, inverse = np.unique(np.sort(edges.reshape(-1, 2), axis=1), axis=0, return_inverse=True)
    if len(pairs)>max_vertices:
        raise ValueError(f'vertex budget exceeded: {len(pairs)} > {max_vertices}')
    nodes = np.moveaxis(np.asarray(np.unravel_index(pairs, f.shape)), 0, -1)
    values = f.reshape(-1)[pairs]
    fraction = values[:, 0]/(values[:, 0]-values[:, 1])
    length = np.linalg.norm((nodes[:,1]-nodes[:,0])*spacing,axis=1)
    # Unify near-node intersections before dropping collapsed triangles.
    # Otherwise tiny discarded faces leave cracks, and float32 export can
    # collapse edges independently. This perturbation is at most 10 microns.
    fraction = np.where(fraction*length<1e-5,0,fraction)
    fraction = np.where((1-fraction)*length<1e-5,1,fraction)
    points = origin+(nodes[:, 0]+fraction[:, None]*(nodes[:, 1]-nodes[:, 0]))*spacing
    faces = inverse.reshape(-1, 3)
    # Exact grid zeros can produce several edge IDs for the same vertex.
    vertices, weld = np.unique(np.round(points, 10), axis=0, return_inverse=True)
    faces = weld[faces]
    usable = np.all(np.diff(np.sort(faces, axis=1), axis=1)>0, axis=1)
    faces = faces[usable]
    area = np.linalg.norm(np.cross(vertices[faces[:, 1]]-vertices[faces[:, 0]],
                                   vertices[faces[:, 2]]-vertices[faces[:, 0]]), axis=1)
    faces = faces[area>1e-14]
    used, remap = np.unique(faces, return_inverse=True)
    return vertices[used], remap.reshape(-1, 3).astype(np.uint32)
