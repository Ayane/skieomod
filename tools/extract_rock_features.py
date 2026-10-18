#!/usr/bin/env python3
"""Extract candidate rock ridges and normals on a small registered DEM patch.

Dark photographic ridges are observations to review, not measured fractures.
The single-view normal estimate retains the DEM prior's ambiguous direction.
No photographic colour or lighting is exported as a rock material.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import resource

import numpy as np
from PIL import Image, ImageDraw, ImageOps
from scipy.ndimage import binary_erosion, gaussian_filter, label

from tools.extract_rock_surface import Heightfield, estimate_normals, linear_srgb, unit
from tools.rock_registration import Camera, sample_photo, visible_surface


class TriangulatedHeightfield(Heightfield):
    """Use the fine runtime mesh diagonal rather than bilinear DEM heights.

    This is suitable only for a patch inside fully refined native terrain
    cells. The report states this assumption; it is not an arbitrary LOD mesh.
    """
    def sample(self, points):
        x = (points[..., 0]-self.origin[0])/self.spacing
        y = (points[..., 1]-self.origin[1])/self.spacing
        h, w = self.values.shape
        valid = (x>=0) & (y>=0) & (x<=w-1) & (y<=h-1)
        x, y = np.clip(x, 0, w-1), np.clip(y, 0, h-1)
        x0, y0 = np.minimum(np.floor(x).astype(int), w-2), np.minimum(np.floor(y).astype(int), h-2)
        tx, ty = x-x0, y-y0
        a,b,c,d = self.values[y0,x0], self.values[y0+1,x0], self.values[y0,x0+1], self.values[y0+1,x0+1]
        value = np.where(tx+ty<=1, a+tx*(c-a)+ty*(b-a),
                         d+(1-tx)*(b-d)+(1-ty)*(c-d))
        return np.where(valid, value, np.nan)


def ridge_candidates(rgb, mask, extent, depth, maximum=12):
    """Finite line candidates from coherent positive-curvature dark ridges."""
    rows, columns = mask.shape
    step = np.array(extent)/np.array([columns-1, rows-1])
    grey = linear_srgb(rgb)@np.array([.2126,.7152,.0722])
    grey = gaussian_filter(grey, sigma=(.45/step[1], .45/step[0]))
    gv, gu = np.gradient(grey, step[1], step[0])
    _, huu = np.gradient(gu, step[1], step[0])
    hvv, huv = np.gradient(gv, step[1], step[0])
    difference = np.sqrt((huu-hvv)**2+4*huv**2)
    large, small = (huu+hvv+difference)/2, (huu+hvv-difference)/2
    angle = .5*np.arctan2(2*huv, huu-hvv)
    normal = np.stack([np.cos(angle), np.sin(angle)], axis=-1)
    projected = gu*normal[..., 0]+gv*normal[..., 1]
    interior = binary_erosion(mask, iterations=max(1, int(np.ceil(.6/step.min()))))
    strength = np.maximum(large, 0)*(1-np.minimum(1, np.abs(small)/np.maximum(large, 1e-12)))
    if not interior.any():
        return [], np.zeros_like(mask)
    threshold = max(1e-5, float(np.percentile(strength[interior], 88)))
    ridge = (interior & (strength>threshold) & (np.abs(projected)<large*step.max()*.9))
    components, count = label(ridge, np.ones((3,3)))
    found = []
    for index in range(1, count+1):
        y,x = np.nonzero(components==index)
        if len(x)<6:
            continue
        points = np.column_stack([x*step[0], y*step[1]])
        center = points.mean(axis=0)
        _, singular, vectors = np.linalg.svd(points-center, full_matrices=False)
        if singular[0]<1e-8 or singular[1]/singular[0]>.35:
            continue
        tangent = vectors[0]
        extent_along = (points-center)@tangent
        length = float(np.ptp(extent_along))
        if not 1.8<=length<=20:
            continue
        endpoints = center+np.array([extent_along.min(), extent_along.max()])[:,None]*tangent
        closest = int(np.argmin(np.linalg.norm(points-center, axis=1)))
        n = np.array([-tangent[1], tangent[0], 0.])
        found.append({'center_local_meters': [*center, float(depth[y[closest], x[closest]])],
            'normal_local': n.tolist(), 'radius_meters': length/2+2,
            'trace_uv_meters': endpoints.tolist(), 'length_meters': length,
            'score': float(strength[y,x].mean()*length),
            'status': 'photographic-ridge-candidate', 'fracture_verified': False,
            'depth_measured': False})
    found.sort(key=lambda item: item['score'], reverse=True)
    selected = []
    for item in found:
        if any(np.linalg.norm(np.array(item['center_local_meters'][:2])-
                              other['center_local_meters'][:2])<2 for other in selected):
            continue
        selected.append(item)
        if len(selected)>=maximum:
            break
    return selected, ridge


def extract(registration_path, output, window, spacing=.25):
    info = json.loads(registration_path.read_text())
    window = np.asarray(window, dtype=float)
    if window.shape!=(4,) or not np.isfinite(window).all() or np.any(window[2:]<=0):
        raise ValueError('window must be u,v,width,height in metres')
    if not .15<=spacing<=1:
        raise ValueError('feature spacing must be within 0.15..1 m')
    extent = window[2:]
    columns,rows = np.ceil(extent/spacing).astype(int)+1
    if columns*rows>100_000:
        raise ValueError('photographic patch sample budget exceeded')
    surface = info['surface']
    basis = np.column_stack([*np.asarray(surface['axes'], dtype=float),
                             np.cross(*np.asarray(surface['axes'], dtype=float))])
    if not np.allclose(basis.T@basis, np.eye(3), atol=1e-6) or np.linalg.det(basis)<.999:
        raise ValueError('invalid registered patch basis')
    origin = np.asarray(surface['origin_meters'])+basis[:,:2]@window[:2]
    u,v = np.meshgrid(np.linspace(0, extent[0], columns), np.linspace(0, extent[1], rows))
    plane = origin+u[...,None]*basis[:,0]+v[...,None]*basis[:,1]
    manifest = (registration_path.parent/info['heightmap']['manifest']).resolve()
    field = TriangulatedHeightfield(manifest)
    points, valid = field.project(plane, basis[:,2], 100, 2)
    if not valid.all():
        raise ValueError('select a complete wall patch below the skyline')
    depth = (points-plane)@basis[:,2]
    dv,du = np.gradient(points, extent[1]/(rows-1), extent[0]/(columns-1), axis=(0,1))
    normals = unit(np.cross(du,dv))
    normals_local = normals@basis
    if normals_local[...,2].min()<.25:
        raise ValueError('patch is not a coherent outward-facing wall')
    view = info['views'][0]
    source = (registration_path.parent/view['file']).resolve()
    camera_path = (registration_path.parent/view['camera_file']).resolve()
    camera_info = json.loads(camera_path.read_text())
    sha = hashlib.sha256(source.read_bytes()).hexdigest()
    if camera_info.get('photo_sha256')!=sha or camera_info.get('heightmap_sha256')!=field.source_sha256:
        raise ValueError('registration source fingerprints do not match')
    if camera_info.get('heightmap_geometry_sha256',field.geometry_sha256)!=field.geometry_sha256:
        raise ValueError('registration belongs to another heightmap transform')
    with Image.open(source) as image:
        rgb_source = np.asarray(ImageOps.exif_transpose(image).convert('RGB'), dtype=float)/255
    camera = Camera(camera_info['camera'], (rgb_source.shape[1], rgb_source.shape[0]))
    pixels, projected = camera.project(points)
    rgb, inside = sample_photo(rgb_source, pixels)
    visible = visible_surface(field, points, camera, normals, samples=256, tolerance_meters=.25)
    # Warm dawn rock remains usable; neutral snow, sky and vegetation do not.
    rock = (visible & inside & projected & (rgb.max(axis=-1)<.95) & (rgb.mean(axis=-1)>.07)
            & (rgb[...,0]>rgb[...,2]*1.12) & (rgb[...,0]>rgb[...,1]*.95))
    features, ridges = ridge_candidates(rgb, rock, extent, depth)
    light = np.asarray(view['light_direction'], dtype=float)
    estimated, confidence, normal_info = estimate_normals(
        linear_srgb(rgb[...,1])[None], light[None], normals_local, rock, [None],
        np.array([view.get('ambient_linear',0)]), surface['reference_albedo'], 25)
    output.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(output/'reference.npz', depth_meters=depth, points_meters=points,
        normals_prior_local=normals_local, normals_candidate_local=estimated,
        normal_candidate_valid=confidence, rock_mask=rock, photo_pixels=pixels,
        photo_rgb=rgb, ridge_mask=ridges)
    image = Image.fromarray(np.rint(rgb[::-1]*255).astype('uint8'))
    image.save(output/'photo-patch.png')
    overlay = image.copy(); draw = ImageDraw.Draw(overlay)
    for number,item in enumerate(features):
        uv = np.asarray(item['trace_uv_meters'])
        xy = np.column_stack([uv[:,0]/extent[0]*(columns-1),
                              (1-uv[:,1]/extent[1])*(rows-1)])
        draw.line([tuple(p) for p in xy], fill=(255,70,30), width=2)
        draw.text(tuple(xy.mean(axis=0)), str(number+1), fill=(255,230,80))
    overlay.save(output/'ridge-candidates.png')
    Image.fromarray((rock[::-1]*255).astype('uint8')).save(output/'rock-mask.png')
    result = {'version':1, 'coordinate_system':'east-south-up-metres',
        'origin_meters':origin.tolist(), 'basis_columns':basis.tolist(),
        'extent_meters':extent.tolist(), 'size':[int(columns),int(rows)],
        'source_photo':str(source), 'photo_sha256':sha,
        'source_heightmap':str(manifest), 'source_r16_sha256':field.source_sha256,
        'runtime_reference':'fully-refined-native-cell-triangles',
        'camera_status':camera_info['status'], 'camera_verified':camera_info['verified'],
        'skyline_rms_pixels':camera_info['skyline_rms_pixels'],
        'rock_fraction':float(rock.mean()), 'normal_candidates':int(confidence.sum()),
        'normal_inference':normal_info, 'fractures':features,
        'photographic_colour_used_as_material':False,
        'metric_fracture_depths_measured':False,
        'limitations':['Dark ridges may be shadows or albedo changes rather than fractures.',
            'The camera has no independently verified internal cliff correspondences.',
            'A single photograph does not uniquely identify surface normals or depths.',
            'The reference assumes fully refined native cells in this small steep patch.']}
    (output/'features.json').write_text(json.dumps(result, indent=2)+'\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('registration', type=Path)
    parser.add_argument('--window', nargs=4, type=float, required=True, metavar=('U','V','WIDTH','HEIGHT'))
    parser.add_argument('--spacing', type=float, default=.25)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    resource.setrlimit(resource.RLIMIT_AS,(1024**3,1024**3))
    resource.setrlimit(resource.RLIMIT_CPU,(120,125))
    resource.setrlimit(resource.RLIMIT_CORE,(0,0))
    try:
        result = extract(args.registration, args.output_dir, args.window, args.spacing)
    except (ValueError, KeyError, OSError) as error:
        parser.error(str(error))
    print(json.dumps({key:result[key] for key in ['size','rock_fraction','normal_candidates',
                                               'camera_verified']}, indent=2))
    print('Photographic ridge candidates:', len(result['fractures']))


if __name__=='__main__':
    main()
