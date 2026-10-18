#!/usr/bin/env python3
"""Stream finite rock CSG over native terrain triangles.

The small study's angular solids and exposed-parent cutters are reused as a
style, not as repeated meshes. World face seeds and neighbour halos make the
field independent of extraction batches. Triangular prisms keep the exact
native reference; a canonical diagonal gives neighbouring volumes one edge.
This is a procedural interpretation, not a reconstruction from photographs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import resource
import time

import numpy as np
from scipy.spatial import cKDTree

from tools.implicit_rock import angular_volume, unit, smooth
from tools.prepare_nanite_tile import refine_walls, mesh_normals
from tools.embed_rock_sculpture import audit


FRONT = unit(np.array([.5925205463743324, -.8055553377169458, 0.]))
UP = np.array([0., 0., 1.])


def stone_frame(normal, angle):
    across = unit(np.cross(UP, normal))
    up = unit(np.cross(normal, across))
    return np.column_stack([across*np.cos(angle)+up*np.sin(angle),
                            up*np.cos(angle)-across*np.sin(angle), normal])


def rock_weight(points, normals, bounds):
    """Only front-facing cliffs, continuous fade at the massif's outer edge."""
    edge = np.minimum(points[:, :2]-bounds[0], bounds[1]-points[:, :2]).min(axis=1)
    return (smooth(edge/12)*smooth((points[:, 2]-1760)/80)
            *(1-smooth((normals[:, 2]-.30)/.40))
            *smooth((normals@FRONT-.25)/.30))


class IndexedSculpture:
    def __init__(self, chunks, cutters, profile):
        self.chunks, self.cutters, self.profile = chunks, cutters, profile

    def signed(self, points, base):
        result = np.asarray(base, dtype=float).copy()-self.profile['sculpture']['mass_offset_meters']
        tree = cKDTree(points)
        for additive, solids in ((True, self.chunks), (False, self.cutters)):
            for solid in solids:
                center = solid.bounds.mean(axis=0)
                radius = np.linalg.norm(solid.bounds[1]-solid.bounds[0])/2
                ids = np.asarray(tree.query_ball_point(center, radius+1e-8), dtype=int)
                if not len(ids):
                    continue
                q = points[ids]
                ids = ids[((q>=solid.bounds[0]-1e-8) & (q<=solid.bounds[1]+1e-8)).all(axis=1)]
                if not len(ids):
                    continue
                sample = solid.raw(points[ids])
                result[ids] = (np.minimum(result[ids], sample) if additive else np.maximum(result[ids], -sample))
        return np.clip(result, np.asarray(base)-self.profile['maximum_outset_meters'],
                       np.asarray(base)+self.profile['core_recession_meters'])

    def project(self, points):
        offsets = np.linspace(-self.profile['core_recession_meters']-.3,
                              self.profile['maximum_outset_meters']+.3, 41)
        rays = points[:, None, :]+offsets[None, :, None]*FRONT
        values = self.signed(rays.reshape(-1, 3), np.broadcast_to(offsets, rays.shape[:2]).ravel()).reshape(len(points), -1)
        crossing = (values[:, :-1]<0) & (values[:, 1:]>=0)
        last = np.where(crossing, np.arange(len(offsets)-1), -1).max(axis=1)
        if np.any(last<0):
            raise ValueError('parent rock surface has no outer crossing')
        lo, hi = offsets[last].copy(), offsets[last+1].copy()
        for _ in range(9):
            mid = (lo+hi)/2
            inside = self.signed(points+mid[:, None]*FRONT, mid)<0
            lo[inside], hi[~inside] = mid[inside], mid[~inside]
        return points+((lo+hi)/2)[:, None]*FRONT


class NativeMassif:
    def __init__(self, sources):
        arrays = [[], [], [], []]
        count = 0
        self.first = None
        self.sections = []
        self.face_sections = []
        self.fingerprints = []
        for source in sources:
            info = json.loads((source/'tile-source.json').read_text())
            if info.get('coordinate_system')!='east-south-up-metres' or info.get('winding')!='counterclockwise':
                raise ValueError('invalid native source coordinates')
            if self.first is None:
                self.first = info
            for key in ('map_id', 'source_file', 'source_definition', 'source_origin_centimeters',
                        'sample_step', 'tile_quads', 'uv_tile_meters'):
                if info[key]!=self.first[key]:
                    raise ValueError('native source sections differ')
            if info['source_section'] in self.sections:
                raise ValueError('duplicate native source section')
            p = np.round(np.loadtxt(source/'positions.txt').reshape(-1, 3)+info['origin_meters'], 8)
            n = np.loadtxt(source/'normals.txt').reshape(-1, 3)
            uv = np.loadtxt(source/'uvs.txt').reshape(-1, 2)
            f = np.loadtxt(source/'indices.txt', dtype=np.uint32).reshape(-1, 3)
            if len(p)!=info['vertices'] or len(f)!=info['triangles'] or f.max()>=len(p) or not all(np.isfinite(a).all() for a in (p, n, uv)):
                raise ValueError('invalid native source buffers')
            for target, value in zip(arrays, (p, n, uv, f+count)):
                target.append(value)
            count += len(p)
            self.sections.append(info['source_section'])
            self.face_sections.extend([info['source_section']]*len(f))
            self.fingerprints.append(hashlib.sha256((source/'positions.txt').read_bytes()).hexdigest())
        self.points, self.normals, self.uvs, self.faces = [np.concatenate(a) for a in arrays]
        self.face_sections = np.array(self.face_sections)
        _, first, weld = np.unique(self.points, axis=0, return_index=True, return_inverse=True)
        # UV projection duplicates must agree on the field, not just positions.
        sums = np.zeros((len(first), 3))
        np.add.at(sums, weld, self.normals)
        self.normals = unit(sums[weld])
        self.bounds = np.array([self.points[:, :2].min(0), self.points[:, :2].max(0)])
        self.weights = rock_weight(self.points, self.normals, self.bounds)
        triangles = self.points[self.faces]
        self.centers = triangles.mean(axis=1)
        self.radii = np.linalg.norm(triangles-self.centers[:, None], axis=2).max(axis=1)
        self.tree = cKDTree(self.centers)
        cross = np.cross(triangles[:, 1]-triangles[:, 0], triangles[:, 2]-triangles[:, 0])
        self.area = np.linalg.norm(cross, axis=1)/2
        self.face_normals = unit(cross)
        # A single outward prism axis cannot represent reverse-facing charts.
        # Pin their shared reference vertices, tapering naturally through the
        # neighbouring front charts instead of folding the extrusion volume.
        reverse = self.face_normals@FRONT<=.12
        self.weights[np.unique(self.faces[reverse])] = 0
        # Finite CSG is generated on exactly the same eligible native faces in
        # every batch; no RNG state or cell phase depends on the output part.
        self.active = (self.weights[self.faces].max(axis=1)>0) & (self.face_normals@FRONT>.12)

    def near_faces(self, low, high, halo):
        center = (low+high)/2
        radius = np.linalg.norm(high-low)/2
        ids = np.asarray(self.tree.query_ball_point(center, radius+self.radii.max()+halo), dtype=int)
        tri = self.points[self.faces[ids]]
        hit = (tri.max(axis=1)>=low-halo).all(axis=1) & (tri.min(axis=1)<=high+halo).all(axis=1)
        return np.sort(ids[hit & self.active[ids]])

    def sculpture(self, low, high, profile):
        settings = profile['sculpture']
        ids = self.near_faces(low, high, 9.)
        chunks, cutters = [], []
        totals = []
        for level_id, level in enumerate(settings['levels']):
            seeds = []
            # An independently seeded sampler for every native triangle and
            # scale; order and extraction region cannot change a rock shape.
            for fid in ids:
                rng = np.random.default_rng(np.random.SeedSequence([profile['seed'], int(fid), level_id]))
                target = self.area[fid]/level['spacing_meters']**2*level['density']
                number = int(np.floor(target))+int(rng.random()<target%1)
                bary = rng.dirichlet([1, 1, 1], size=number)
                points = bary@self.points[self.faces[fid]]
                normals = unit(bary@self.normals[self.faces[fid]])
                weights = bary@self.weights[self.faces[fid]]
                for serial, (p, n, weight) in enumerate(zip(points, normals, weights)):
                    if weight>0 and (p>=low-8).all() and (p<=high+8).all():
                        seeds.append((p, n, int(fid), serial))
            if len(seeds)>24000:
                raise ValueError('microbatch sculpture budget exceeded')
            anchors = np.array([s[0] for s in seeds]).reshape(-1, 3)
            if level_id and len(seeds):
                anchors = IndexedSculpture(chunks, cutters, profile).project(anchors)
            totals.append(len(seeds))
            for anchor, (_, normal, fid, serial) in zip(anchors, seeds):
                rng = np.random.default_rng(np.random.SeedSequence([profile['seed'], fid, level_id, serial, 712]))
                frame = stone_frame(normal, rng.uniform(-.35, .35))
                radii = np.array(level['radii_meters'])*rng.uniform(.7, 1.25, 3)
                depth = level['cut_depth_meters']*rng.uniform(.55, 1.25)
                tilt = rng.uniform(-.32, .32)
                frame = frame@np.array([[np.cos(tilt), 0, np.sin(tilt)], [0, 1, 0], [-np.sin(tilt), 0, np.cos(tilt)]])
                seed = int(rng.integers(2**31))
                cutters.append(angular_volume(anchor+frame[:, 2]*(radii[2]-depth), frame,
                    radii, rng, settings['edge_rounding_meters'], seed))
                if level_id==0 and rng.random()<settings['protruding_fraction']:
                    root = settings['root_depth_meters']
                    front = settings['protrusion_meters']*rng.uniform(.6, 1.1)
                    chunk_radii = np.array([radii[0]*.8, radii[1]*.85, (root+front)/2])
                    chunks.append(angular_volume(anchor+frame[:, 2]*(front-root)/2, frame,
                        chunk_radii, rng, settings['edge_rounding_meters'], seed+1, lean=.4))
        def keep(solid):
            return (solid.bounds[1]>=low-.8).all() and (solid.bounds[0]<=high+.8).all()
        return IndexedSculpture([s for s in chunks if keep(s)], [s for s in cutters if keep(s)], profile), totals


def weather(sculpture, points, offsets, normal_prior, weight, settings):
    """Bounded first-order exposure/curvature erosion of the completed field.

    The massif preview uses one continuous-field step instead of storing 24
    dense evolving volumes. The local reference derivative is shared at native
    edges. Only a narrow interface band changes; material is never added.
    """
    raw = sculpture.signed(points, offsets)
    result = raw.copy()
    ids = np.flatnonzero((np.abs(raw)<.7) & (weight>0))
    if settings['depth_meters']==0 or not len(ids):
        return result, 0.
    p, base = points[ids], offsets[ids]
    n = normal_prior[ids]
    denominator = np.maximum(n@FRONT, .12)
    reference_gradient = n/denominator[:, None]
    eps = settings['curvature_radius_meters']
    pairs = []
    for axis in np.eye(3)*eps:
        delta = reference_gradient@axis
        pairs.append((sculpture.signed(p+axis, base+delta), sculpture.signed(p-axis, base-delta)))
    gradient = np.column_stack([(plus-minus)/(2*eps) for plus, minus in pairs])
    length = np.linalg.norm(gradient, axis=1)
    laplacian = sum(plus+minus-2*raw[ids] for plus, minus in pairs)/eps**2
    convex = np.clip(laplacian*eps/np.maximum(length, 1e-8), 0, 1)
    direction = unit(np.array([.59252, -.80556, .75]))
    exposure = settings['exposure_floor']+(1-settings['exposure_floor'])*np.clip(unit(gradient)@direction, 0, 1)
    rate = exposure*(settings['face_rate']+(1-settings['face_rate'])*convex)
    advance = settings['depth_meters']*rate*length
    # Enforce the original macro envelope after weathering as well. This is a
    # scalar retreat bound; it is not a calibrated metric erosion measurement.
    advance = np.minimum(advance, np.maximum(0, base+sculpture.profile['core_recession_meters']-raw[ids]))
    result[ids] += advance
    return result, float(advance.max(initial=0))


def contour_prisms(points, prior, uvs, faces, field, offsets):
    """March triangular prisms with a shared diagonal and affine front normals."""
    # IDs follow geometric lexicographic order, independent of UV duplicates,
    # face order and extraction batches. Every shared vertical quad agrees.
    geometric, representative, weld = np.unique(np.round(points, 8), axis=0, return_index=True, return_inverse=True)
    order = np.argsort(weld[faces], axis=1)
    base_faces = np.take_along_axis(faces, order, axis=1)
    layers = len(offsets)
    edges, references = [], []
    cases = []
    for case in range(1, 15):
        neg = [i for i in range(4) if case & (1<<i)]
        pos = [i for i in range(4) if not case & (1<<i)]
        if len(neg)==1 or len(pos)==1:
            inner, outer = (neg, pos) if len(neg)==1 else (pos, neg)
            pairs = [(inner[0], j) for j in outer]
        else:
            a, b = neg; c, d = pos
            pairs = [(a, c), (a, d), (b, c), (a, d), (b, d), (b, c)]
        cases.append((case, pairs, neg, pos))
    for depth in range(layers-1):
        ids = np.column_stack([base_faces*layers+depth, base_faces*layers+depth+1])
        cube_value = field.ravel()[ids]
        crossing = (cube_value.min(1)<0) & (cube_value.max(1)>=0)
        ids = ids[crossing]
        if not len(ids):
            continue
        for tetra in ((0, 1, 2, 5), (0, 1, 4, 5), (0, 3, 4, 5)):
            tet = ids[:, tetra]
            values = field.ravel()[tet]
            flags = (values<0)@np.array([1, 2, 4, 8])
            for case, pairs, neg, pos in cases:
                selected = tet[flags==case]
                if not len(selected):
                    continue
                triangles = selected[:, pairs].reshape(-1, 3, 2)
                edges.append(triangles)
                node = selected//layers
                q = points[node]+offsets[selected%layers, None]*FRONT
                front = q[:, pos].mean(1)-q[:, neg].mean(1)
                references.append(np.repeat(front, len(pairs)//3, axis=0))
    if not edges:
        raise ValueError('empty prism contour')
    edges = np.concatenate(edges)
    direction = np.concatenate(references)
    if len(edges)>1_800_000:
        raise ValueError('microbatch contour triangle budget exceeded')
    pairs, inverse = np.unique(np.sort(edges.reshape(-1, 2), axis=1), axis=0, return_inverse=True)
    values = field.ravel()[pairs]
    fraction = values[:, 0]/(values[:, 0]-values[:, 1])
    base_ids, depth_ids = pairs//layers, pairs%layers
    nodes = points[base_ids]+offsets[depth_ids, None]*FRONT
    lengths = np.linalg.norm(nodes[:, 1]-nodes[:, 0], axis=1)
    # Crossing classifications were consolidated in the sampled field. Do not
    # snap individual edges afterwards: that can identify only part of a tetra
    # fan and turn an otherwise manifold volume into a branching surface.
    def interpolate(array):
        return array[base_ids[:, 0]]*(1-fraction[:, None])+array[base_ids[:, 1]]*fraction[:, None]
    out = nodes[:, 0]*(1-fraction[:, None])+nodes[:, 1]*fraction[:, None]
    source = interpolate(points)
    normals = unit(interpolate(prior))
    texture = interpolate(uvs)
    faces = inverse.reshape(-1, 3).astype(np.uint32)
    cross = np.cross(out[faces[:, 1]]-out[faces[:, 0]], out[faces[:, 2]]-out[faces[:, 0]])
    usable = np.linalg.norm(cross, axis=1)>1e-14
    reverse = np.sum(cross*direction, axis=1)<0
    faces[reverse] = faces[reverse][:, [0, 2, 1]]
    return out, normals, texture, faces[usable], source


def microbatch(native, ids, profile, erosion, spacing, surface_mode='envelope'):
    used, inverse = np.unique(native.faces[ids], return_inverse=True)
    p, n, uv, f = native.points[used], native.normals[used], native.uvs[used], inverse.reshape(-1, 3).astype(np.uint32)
    # Refinement uses a shared vertex selector. Source-boundary edges make
    # exactly the same split decision in each batch; no regular tile fade.
    attributes = np.column_stack([uv, native.weights[used]])
    p, n, attributes, f = refine_walls(p, n, attributes, f, spacing, native.weights[used])
    uv, weight = attributes[:, :2], attributes[:, 2]
    n = unit(n)
    active = weight[f].max(axis=1)>0
    if not active.any():
        return (p, n, uv, f, p.copy()), dict(samples=0, cutters_by_scale=[0,0,0], maximum_scalar_erosion_advance=0.)
    # All vertices of all batches share the same depth samples. A zero sample
    # keeps untouched ground exactly on its native face, without extra knots.
    offsets = np.arange(-2.5, 1.50001, .25)
    if len(p)*len(offsets)>2_000_000:
        raise ValueError('microbatch volume sample budget exceeded')
    q = p[:, None, :]+offsets[None, :, None]*FRONT
    low, high = q.reshape(-1, 3).min(0), q.reshape(-1, 3).max(0)
    sculpture, counts = native.sculpture(low, high, profile)
    raw, advance = weather(sculpture, q.reshape(-1, 3), np.broadcast_to(offsets, q.shape[:2]).ravel(),
        np.repeat(n, len(offsets), axis=0), np.repeat(weight, len(offsets)), erosion)
    field = offsets[None, :]+(raw.reshape(len(p), -1)-offsets[None, :])*weight[:, None]
    # Treat a sub-millimetre interface crossing as the common grid node. Tiny
    # transition weights otherwise create several nearly coincident surfaces
    # that float32 cannot distinguish. This decision is shared between batches.
    near=(np.abs(field)<.001) & (weight[:,None]>0)
    # Bias active near-zero samples toward air, rather than making two rock
    # pieces touch at an exactly-zero edge. Untouched native vertices keep
    # their exact zero plane, including interfaces with reverse charts.
    field[near]=.0015
    if surface_mode=='envelope':
        # The same CSG and weathering field, with the outermost ray crossing.
        # This view-plane chart can still overhang the terrain's vertical XY
        # heightfield, but does not retain hidden multi-depth sheets/cavities.
        crossing=(field[:,:-1]<0) & (field[:,1:]>=0)
        last=np.where(crossing,np.arange(len(offsets)-1),-1).max(axis=1)
        if np.any(last<0):raise ValueError('rock envelope has no outer crossing')
        row=np.arange(len(p));a=field[row,last];b=field[row,last+1]
        depth=offsets[last]+(-a/(b-a))*(offsets[last+1]-offsets[last])
        return (p+depth[:,None]*FRONT,n,uv,f,p.copy()),dict(samples=int(q.size//3),cutters_by_scale=counts,
            maximum_scalar_erosion_advance=advance,surface_mode=surface_mode)
    result = contour_prisms(p, n, uv, f[active], field, offsets)
    if (~active).any():
        out, normals, texture, contour, source = result
        result = (np.concatenate([out, p]), np.concatenate([normals, n]),
            np.concatenate([texture, uv]), np.concatenate([contour, f[~active]+len(out)]),
            np.concatenate([source, p]))
    return result, dict(samples=int(q.size//3), cutters_by_scale=counts, maximum_scalar_erosion_advance=advance)


def compact(points, normals, uvs, faces, source, origin):
    # Use an identical float32 origin for every part. UV seams remain attribute
    # seams while their encoded geometry is exactly shared. Interface crossings
    # near grid nodes were consolidated before contouring, not rounded blindly.
    p = (points-origin).astype('<f4').astype(float)
    _, first, weld = np.unique(np.column_stack([p, np.round(uvs, 7)]), axis=0, return_index=True, return_inverse=True)
    f = weld[faces]
    keep = np.all(np.diff(np.sort(f, axis=1), axis=1)>0, axis=1)
    f = f[keep]
    cross = np.cross(p[first][f[:, 1]]-p[first][f[:, 0]], p[first][f[:, 2]]-p[first][f[:, 0]])
    f = f[np.linalg.norm(cross, axis=1)>1e-12]
    _, geo = np.unique(p[first], axis=0, return_inverse=True)
    _, unique_face = np.unique(np.sort(geo[f], axis=1), axis=0, return_index=True)
    f = f[np.sort(unique_face)]
    used, remap = np.unique(f, return_inverse=True)
    return p[first][used]+origin, normals[first][used], uvs[first][used], remap.reshape(-1, 3).astype(np.uint32), source[first][used]


def prepare(sources, profile_path, erosion_path, output, spacing=1.5, part=None, simplifier=None,surface_mode='envelope'):
    if not .75<=spacing<=3:
        raise ValueError('massif preview edge spacing must be 0.75..3 m')
    started = time.monotonic()
    native = NativeMassif(sources)
    profile = json.loads(profile_path.read_text())
    erosion = json.loads(erosion_path.read_text())
    if profile.get('model')!='sculpted-implicit-rock':
        raise ValueError('requires the approved angular sculpture profile')
    origin = np.array([-1512., 1008., 2000.])
    r16_sha = hashlib.sha256(Path(native.first['source_file']).read_bytes()).hexdigest()
    manifest = json.loads(Path(native.first['source_manifest']).read_text())
    snow_offset = manifest['terrain'].get('runtime', {}).get('snow_offset_centimeters', 30)
    summaries = []
    generation_key=hashlib.sha256(json.dumps(dict(profile=profile,erosion=erosion,spacing=spacing,surface_mode=surface_mode,
        sources=native.fingerprints,generator=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        refinement=hashlib.sha256(Path('tools/prepare_nanite_tile.py').read_bytes()).hexdigest()),sort_keys=True).encode()).hexdigest()
    def extracted(batch):
        try:
            result, metric=microbatch(native,batch,profile,erosion,spacing,surface_mode)
        except ValueError as error:
            if ('budget' not in str(error) and 'excessive' not in str(error)) or len(batch)==1:
                raise
            centers=native.centers[batch]
            axis=np.ptp(centers,axis=0).argmax()
            order=np.argsort(centers[:,axis]);half=len(batch)//2
            a,ma=extracted(batch[order[:half]]);b,mb=extracted(batch[order[half:]])
            result=tuple(np.concatenate([x,y+len(a[0]) if index==3 else y]) for index,(x,y) in enumerate(zip(a,b)))
            return result,dict(samples=max(ma['samples'],mb['samples']),
                cutters_by_scale=[max(x,y) for x,y in zip(ma['cutters_by_scale'],mb['cutters_by_scale'])],
                maximum_scalar_erosion_advance=max(ma['maximum_scalar_erosion_advance'],mb['maximum_scalar_erosion_advance']))
        if simplifier:
            from tools.export_sculpted_massif import simplify
            p,n,uv,f,base=result
            f,detail=simplify(p-origin,uv,f,simplifier,.04)
            used,remap=np.unique(f,return_inverse=True)
            result=(p[used],n[used],uv[used],remap.reshape(-1,3).astype(np.uint32),base[used])
            metric['simplification']=detail
        return result,metric
    for section in native.sections:
        own = np.flatnonzero(native.face_sections==section)
        low = native.points[native.faces[own]].reshape(-1, 3).min(0)
        high = native.points[native.faces[own]].reshape(-1, 3).max(0)
        xy = np.minimum(((native.centers[own, :2]-low[:2])/(high[:2]-low[:2])*4).astype(int), 3)
        groups = xy[:, 0]+4*xy[:, 1]
        for pid in range(16):
            if part is not None and (section, pid)!=tuple(part):
                continue
            dest = output/f's{section}-p{pid:02d}'
            if (dest/'audit.json').exists():
                previous=json.loads((dest/'audit.json').read_text())
                if previous.get('generation_key')==generation_key:
                    summaries.append(previous)
                    continue
            ids = own[groups==pid]
            if not len(ids):
                raise ValueError('empty native partition')
            arrays = [[], [], [], [], []]
            count = 0
            metrics = []
            # Spatial order keeps neighbour halos small; each extraction volume
            # is released before the next. Native faces belong to one part only.
            c = native.centers[ids]
            cell = np.maximum(0, np.floor((c-c.min(0))/4)).astype(np.uint64)
            morton = np.zeros(len(c), dtype=np.uint64)
            for bit in range(16):
                for axis in range(3):
                    morton |= ((cell[:, axis]>>bit)&1)<<(3*bit+axis)
            order = np.argsort(morton)
            checkpoint=dest/'micro'/generation_key[:16];checkpoint.mkdir(parents=True,exist_ok=True)
            for start in range(0, len(ids), 32):
                batch = ids[order[start:start+32]]
                saved=checkpoint/f'{start:05d}.npz'
                if saved.exists():
                    with np.load(saved,allow_pickle=False) as data:
                        result=tuple(data[k].copy() for k in ('points','normals','uvs','faces','baseline'))
                        metric=json.loads(str(data['metric']))
                else:
                    result, metric = extracted(batch)
                    np.savez(saved,points=result[0],normals=result[1],uvs=result[2],faces=result[3],baseline=result[4],
                        metric=json.dumps(metric))
                for target, value in zip(arrays, (result[0], result[1], result[2], result[3]+count, result[4])):
                    target.append(value)
                count += len(result[0])
                metrics.append(metric)
                print(f'part {section}/{pid} native faces {start+len(batch)}/{len(ids)} output vertices {count}', flush=True)
            p, n, uv, f, baseline = compact(*[np.concatenate(a) for a in arrays], origin)
            if len(p)>1_000_000 or len(f)>2_000_000:
                raise ValueError(f'Nanite partition budget exceeded for {section}/{pid}: {len(p)}/{len(f)}')
            topology = audit(p-origin, f)
            # Envelope batches are intermediate reference charts. Complete
            # every extraction cache before the mandatory conforming assembly
            # repairs simplifier caps and reconciles native UV copies. No
            # cookable mesh is emitted until the separate exporter audits it.
            if surface_mode!='envelope' and (topology['nonmanifold_edges'] or topology['degenerate_triangles']):
                raise ValueError(f'invalid massif partition {section}/{pid}: {topology}')
            dest.mkdir(parents=True, exist_ok=True)
            np.savez(dest/'geometry.npz', points=p, normals=n, uvs=uv, faces=f, baseline=baseline)
            summary = dict(generation_key=generation_key,surface_mode=surface_mode,section=int(section), part=pid, parts=16, vertices=len(p), triangles=len(f),
                original_faces=len(ids), eligible_cliff_area_m2=float(native.area[ids[native.active[ids]]].sum()),
                maximum_outset_meters=float(np.sum((p-baseline)*FRONT, axis=1).max()),
                maximum_recession_meters=float(-np.sum((p-baseline)*FRONT, axis=1).min()),
                maximum_microvolume_samples=max(m['samples'] for m in metrics), topology=topology,
                requires_conforming_assembly=surface_mode=='envelope',
                peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024)
            (dest/'audit.json').write_text(json.dumps(summary, indent=2)+'\n')
            summaries.append(summary)
            print(json.dumps(summary), flush=True)
    report = dict(model='streamed-eroded-angular-csg', scope='front-facing Grand Veymont cliffs',
        status='requires-conforming-assembly' if surface_mode=='envelope' else 'extracted',
        source_sections=native.sections, parts=summaries, edge_spacing_meters=spacing,
        surface_mode=surface_mode,field_depth_spacing_meters=.25, erosion_method='continuous-field first-order exposure/curvature',
        profile_sha256=hashlib.sha256(profile_path.read_bytes()).hexdigest(),
        erosion_sha256=hashlib.sha256(erosion_path.read_bytes()).hexdigest(),
        source_r16_sha256=r16_sha, elapsed_seconds=time.monotonic()-started,
        peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024)
    (output/'generation.json').write_text(json.dumps(report, indent=2)+'\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('sources', nargs='+', type=Path)
    parser.add_argument('--profile', type=Path, default=Path('maps/veymont/limestone-sculpture.json'))
    parser.add_argument('--erosion', type=Path, default=Path('maps/veymont/limestone-erosion.json'))
    parser.add_argument('--output-dir', required=True, type=Path)
    parser.add_argument('--edge-spacing', type=float, default=1.5)
    parser.add_argument('--part', nargs=2, type=int)
    parser.add_argument('--simplifier',type=Path)
    parser.add_argument('--surface-mode',choices=('envelope','volume'),default='envelope')
    args = parser.parse_args()
    resource.setrlimit(resource.RLIMIT_AS, (2*1024**3, 2*1024**3))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    prepare(args.sources, args.profile, args.erosion, args.output_dir, args.edge_spacing, args.part,args.simplifier,args.surface_mode)


if __name__=='__main__':
    main()
