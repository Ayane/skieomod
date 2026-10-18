#!/usr/bin/env python3
"""Fit a candidate photo camera to a terrain skyline within a known viewpoint area.

A skyline fit is a registration proposal, not a unique measurement of camera
pose or cliff geometry. Inspect the overlay and add independent landmarks
before applying small photographic features to the map.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

try:
    from extract_rock_surface import Heightfield
    from rock_registration import Camera, intersect_photo_rays, projected_skyline
    from rock_photo_metadata import geographic_anchors, read_metadata
except ModuleNotFoundError:
    from tools.extract_rock_surface import Heightfield
    from tools.rock_registration import Camera, intersect_photo_rays, projected_skyline
    from tools.rock_photo_metadata import geographic_anchors, read_metadata


def bounds(value, count: int, label: str) -> np.ndarray:
    result = np.asarray(value, dtype=float)
    if result.shape != (count, 2) or not np.isfinite(result).all() or np.any(result[:, 0] >= result[:, 1]):
        raise ValueError(label+' must give finite increasing bounds for each parameter')
    return result


def terrain_points(field: Heightfield, window: list, step: int, *, grid: bool = False) -> np.ndarray:
    window = np.asarray(window, dtype=float)
    if (window.shape != (4,) or not np.isfinite(window).all()
            or np.any(window[:2] >= window[2:])):
        raise ValueError('terrain_window_meters must be [min_x,min_y,max_x,max_y]')
    if type(step) is not int or not 1 <= step <= 8:
        raise ValueError('grid_step must be an integer within 1..8 source samples')
    h, w = field.values.shape
    first = np.maximum(0, np.floor((window[:2]-field.origin[:2])/field.spacing).astype(int))
    last = np.minimum([w-1, h-1], np.ceil((window[2:]-field.origin[:2])/field.spacing).astype(int))
    if np.any(first >= last):
        raise ValueError('terrain window does not overlap the heightmap')
    rows, columns = np.meshgrid(np.arange(first[1], last[1]+1, step),
                               np.arange(first[0], last[0]+1, step), indexing='ij')
    if rows.size > 1_000_000:
        raise ValueError('terrain window exceeds one million points; reduce the window or increase grid_step')
    points = np.stack([field.origin[0]+columns*field.spacing,
                     field.origin[1]+rows*field.spacing, field.values[rows, columns]], axis=-1)
    return points if grid else points.reshape(-1, 3)


def camera_from_parameters(parameters: np.ndarray, field: Heightfield, search: dict,
                           image_size: tuple[int, int]) -> Camera:
    x, y, yaw_offset, pitch, focal = parameters[:5]
    aim = np.asarray(search['aim_meters'], dtype=float)
    if aim.shape != (3,) or not np.isfinite(aim).all():
        raise ValueError('aim_meters must contain three finite coordinates')
    elevation = float(field.sample(np.array([x, y, 0])))
    eye_height = float(search.get('height_above_ground_meters', 1.7))
    if not math.isfinite(eye_height) or not 0 < eye_height <= 10:
        raise ValueError('height_above_ground_meters must be within 0..10')
    yaw = math.atan2(aim[1]-y, aim[0]-x)+yaw_offset
    camera = Camera({'position_meters': [x, y, elevation+eye_height],
        'forward': [math.cos(pitch)*math.cos(yaw), math.cos(pitch)*math.sin(yaw), math.sin(pitch)],
        'focal_pixels': focal}, image_size)
    if len(parameters) == 6:
        definition = camera.definition()
        definition['up'] = (camera.up*math.cos(parameters[5])+camera.right*math.sin(parameters[5])).tolist()
        camera = Camera(definition, image_size)
    return camera


def fit_camera(field: Heightfield, points: np.ndarray, observed: np.ndarray,
               image_size: tuple[int, int], search: dict) -> tuple[Camera, dict, np.ndarray]:
    from scipy.optimize import differential_evolution, minimize
    observed = np.asarray(observed, dtype=float)
    if observed.ndim != 2 or observed.shape[1] != 2 or len(observed) < 12 or not np.isfinite(observed).all():
        raise ValueError('skyline_pixels needs at least twelve finite [x,y] observations')
    if (np.any(observed < 0) or np.any(observed >= image_size)
            or np.ptp(observed[:, 0]) < image_size[0]*0.25):
        raise ValueError('skyline observations must lie in the photo and span at least a quarter of its width')
    xy = bounds(search['position_xy_bounds_meters'], 2, 'camera XY bounds')
    angle = bounds([search.get('yaw_offset_degrees', [-15, 15]),
                    search.get('pitch_degrees', [0, 30])], 2, 'camera angle bounds')*math.pi/180
    focal = bounds([search['focal_pixels']], 1, 'focal length bounds')
    if focal[0, 0] <= 0 or np.any(np.abs(angle) >= math.pi/2):
        raise ValueError('focal length must be positive and camera angle bounds within -90..90 degrees')
    search_bounds = np.vstack([xy, angle, focal])
    if 'roll_degrees' in search:
        roll = bounds([search['roll_degrees']], 1, 'camera roll bounds')*math.pi/180
        if np.any(np.abs(roll) > math.pi/12):
            raise ValueError('camera roll bounds must stay within -15..15 degrees')
        search_bounds = np.vstack([search_bounds, roll])
    iterations = search.get('iterations', 100)
    seed = search.get('seed', 5)
    if type(iterations) is not int or not 1 <= iterations <= 200 or type(seed) is not int or seed < 0:
        raise ValueError('iterations must be within 1..200 and seed a nonnegative integer')
    min_elevation = float(search.get('minimum_elevation_meters', -1e6))
    if not math.isfinite(min_elevation):
        raise ValueError('minimum_elevation_meters must be finite')
    # Optional point correspondences complement the ambiguous silhouette.
    landmarks = search.get('landmarks', [])
    landmark_world = np.array([item['world_meters'] for item in landmarks], dtype=float).reshape(-1, 3)
    landmark_pixels = np.array([item['photo_pixels'] for item in landmarks], dtype=float).reshape(-1, 2)
    if not np.isfinite(landmark_world).all() or not np.isfinite(landmark_pixels).all():
        raise ValueError('landmark correspondences must be finite')

    def evaluate(parameters):
        try:
            camera = camera_from_parameters(parameters, field, search, image_size)
        except ValueError:
            return float('inf'), None, None
        if camera.position[2] < min_elevation:
            return float('inf'), camera, None
        xs, ys = projected_skyline(points, camera)
        if len(xs) < 2 or xs[0] > observed[:, 0].min() or xs[-1] < observed[:, 0].max():
            return float('inf'), camera, None
        predicted = np.interp(observed[:, 0], xs, ys)
        error = predicted-observed[:, 1]
        score = float(np.mean(error*error))
        if len(landmarks):
            pixels, valid = camera.project(landmark_world)
            if not valid.all():
                return float('inf'), camera, None
            score += float(np.mean(np.sum((pixels-landmark_pixels)**2, axis=-1)))
        return score, camera, predicted

    # Finite rejection costs keep Powell's line-search arithmetic defined.
    def objective(parameters):
        return min(evaluate(parameters)[0], 1e12)

    result = differential_evolution(objective, search_bounds,
        seed=seed, popsize=12, maxiter=iterations, tol=0.001, polish=False, workers=1)
    if not math.isfinite(evaluate(result.x)[0]):
        raise ValueError('no camera in the search area covers the observed skyline')
    refined = minimize(objective, result.x, method='Powell',
                       bounds=search_bounds, options={'maxiter': 8, 'xtol': 1e-4})
    if not math.isfinite(evaluate(refined.x)[0]) or refined.fun > result.fun:
        refined = result
    score, camera, predicted = evaluate(refined.x)
    error = predicted-observed[:, 1]
    relative = (refined.x-search_bounds[:, 0])/(search_bounds[:, 1]-search_bounds[:, 0])
    report = {'status': 'candidate', 'verified': False,
        'method': 'terrain-skyline-with-bounded-ground-camera',
        'skyline_rms_pixels': float(np.sqrt(np.mean(error*error))),
        'skyline_max_error_pixels': float(np.max(np.abs(error))),
        'skyline_observations': len(observed), 'landmark_observations': len(landmarks),
        'near_search_boundary': bool(np.any((relative < 0.02) | (relative > 0.98))),
        'search_parameters': refined.x.tolist(), 'search': search, 'objective': score,
        'limitations': ['A skyline alone does not uniquely identify the camera or internal cliff correspondence.',
            'Source heightfield resolution limits the modeled silhouette; vegetation and lens distortion are absent.',
            'Independent landmarks and visual inspection are needed before map integration.']}
    if len(landmarks):
        pixels, _ = camera.project(landmark_world)
        report['landmark_rms_pixels'] = float(np.sqrt(np.mean(np.sum((pixels-landmark_pixels)**2, axis=-1))))
    return camera, report, predicted


def surface_profile(template: dict, field: Heightfield, camera: Camera, pixel: list,
                    extent: list, photo: Path, manifest: Path, camera_file: Path,
                    light_world: list | None = None) -> dict:
    """Build a world-anchored wall patch, with image sampling through the camera."""
    pixel = np.asarray(pixel, dtype=float)
    extent = np.asarray(extent, dtype=float)
    if pixel.shape != (2,) or not np.isfinite(pixel).all() or np.any(pixel < 0) or np.any(pixel >= camera.image_size):
        raise ValueError('patch pixel must lie inside the source photo')
    if extent.shape != (2,) or not np.isfinite(extent).all() or np.any(extent <= 0):
        raise ValueError('patch extent must contain two finite positive lengths')
    target, valid = intersect_photo_rays(field, camera, pixel[None, :])
    if not valid[0]:
        raise ValueError('selected patch pixel does not intersect the heightfield')
    target = target[0]
    step = field.spacing
    dx = (field.sample(target+[step, 0, 0])-field.sample(target-[step, 0, 0]))/(2*step)
    dy = (field.sample(target+[0, step, 0])-field.sample(target-[0, step, 0]))/(2*step)
    slope = float(np.hypot(dx, dy))
    if not math.isfinite(slope) or slope < 1:
        raise ValueError('selected patch pixel must depict steep terrain for a vertical-wall patch')
    front = np.array([-dx/slope, -dy/slope, 0])
    u, v = np.array([-front[1], front[0], 0]), np.array([0, 0, 1])
    origin = target-u*extent[0]/2-v*extent[1]/2
    result = copy.deepcopy(template)
    if result.get('version') != 1 or len(result.get('views', [])) != 1:
        raise ValueError('surface template must be a version 1 single-photo profile')
    view = result['views'][0]
    for key in ['crop', 'camera']:
        view.pop(key, None)
    view.update(file=str(photo.resolve()), camera_file=str(camera_file.resolve()))
    if light_world is not None:
        light = np.asarray(light_world, dtype=float)
        if light.shape != (3,) or not np.isfinite(light).all() or np.linalg.norm(light) < 1e-8:
            raise ValueError('light_direction_world must contain three finite nonzero components')
        view['light_direction'] = (np.column_stack([u, v, front]).T @ light).tolist()
    result['heightmap'] = {'manifest': str(manifest.resolve()),
                          'ray_distance_meters': 100, 'ray_step_meters': step}
    result['surface'].update(origin_meters=origin.tolist(), axes=[u.tolist(), v.tolist()],
                             extent_meters=extent.tolist())
    # The ROI is now the selected world patch; the original photo-crop masks
    # are in a different coordinate system and must not be silently reused.
    result['rock_polygons_uv'] = [[[0, 0], [1, 0], [1, 1], [0, 1]]]
    result.pop('exclude_polygons_uv', None)
    if result.get('snow_cue'):
        result['snow_cue'].pop('polygons_uv', None)
    result['calibration'] = 'candidate terrain-skyline camera; photographic detail correspondences and lighting remain unverified'
    result['patch_selection'] = {'photo_pixel': pixel.tolist(), 'heightfield_point_meters': target.tolist(),
                                 'source_slope_degrees': math.degrees(math.atan(slope))}
    return result


def register(profile_path: Path, output: Path, photo_override: Path | None = None,
             preview: bool = False) -> dict:
    profile = json.loads(profile_path.read_text(encoding='utf-8'))
    if profile.get('version') != 1:
        raise ValueError('photo registration profile version must be 1')
    photo = photo_override.resolve() if photo_override else (profile_path.parent/profile['photo']).resolve()
    manifest = (profile_path.parent/profile['heightmap_manifest']).resolve()
    field = Heightfield(manifest)
    metadata = read_metadata(photo)
    search = copy.deepcopy(profile['camera_search'])
    anchors = None
    if search.get('from_exif'):
        exif_settings = search['from_exif']
        georeference = json.loads((profile_path.parent/exif_settings['map_georeference']).read_text(encoding='utf-8'))
        anchors = geographic_anchors(metadata, georeference)
        radius = float(exif_settings.get('gps_radius_meters', 40))
        if not math.isfinite(radius) or not 0 < radius <= 500:
            raise ValueError('GPS search radius must be within 0..500 metres')
        xy = np.array(anchors['position_xy_meters'])
        search['position_xy_bounds_meters'] = np.stack([xy-radius, xy+radius], axis=-1).tolist()
        if 'focal_pixels' not in search:
            if 'initial_focal_pixels' not in anchors:
                raise ValueError('photo has no equivalent focal length; specify focal_pixels bounds')
            uncertainty = float(exif_settings.get('focal_relative_uncertainty', 0.2))
            if not math.isfinite(uncertainty) or not 0 < uncertainty < 1:
                raise ValueError('focal_relative_uncertainty must be within 0..1')
            focal = anchors['initial_focal_pixels']
            search['focal_pixels'] = [focal*(1-uncertainty), focal*(1+uncertainty)]
    points = terrain_points(field, search['terrain_window_meters'], search.get('grid_step', 2), grid=True)
    with Image.open(photo) as image:
        image = ImageOps.exif_transpose(image).convert('RGB')
        camera, report, predicted = fit_camera(field, points, profile['skyline_pixels'], image.size, search)
        report.update({'version': 1, 'camera': camera.definition(), 'image_size': list(image.size),
            'source_photo': str(photo), 'heightmap_manifest': str(manifest),
            'photo_sha256': hashlib.sha256(photo.read_bytes()).hexdigest(),
            'terrain_points': int(points.size//3), 'profile': profile, 'photo_metadata': metadata,
            'geographic_anchors': anchors})
        report['skyline_geometry'] = 'connected heightfield triangles'
        report['heightmap_sha256'] = field.source_sha256
        report['heightmap_geometry_sha256'] = field.geometry_sha256
        output.mkdir(parents=True, exist_ok=True)
        if preview:
            import matplotlib
            matplotlib.use('Agg')
            import matplotlib.pyplot as plt
            figure, axis = plt.subplots(figsize=(14, 7.6))
            axis.imshow(image)
            observations = np.array(profile['skyline_pixels'])
            axis.plot(*observations.T, color='cyan', linewidth=1.5, label='Photographed ridge (manual landmarks)')
            axis.plot(observations[:, 0], predicted, color='lime', linewidth=1.5, label='Projected terrain ridge')
            axis.legend(loc='upper left')
            axis.set_axis_off()
            axis.set_title(f"Candidate registration — RMS error {report['skyline_rms_pixels']:.1f} pixels", fontsize=12)
            figure.text(0.5, 0.02, 'Silhouette only: internal fractures are not yet verified correspondences.', ha='center', fontsize=9)
            figure.tight_layout(rect=[0, 0.04, 1, 1])
            figure.savefig(output/'skyline-overlay.png', dpi=120)
            plt.close(figure)
    (output/'camera.json').write_text(json.dumps(report, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    if profile.get('patch'):
        patch = profile['patch']
        template = json.loads((profile_path.parent/patch['surface_template']).read_text(encoding='utf-8'))
        light = patch.get('light_direction_world')
        if patch.get('light_direction_from_exif'):
            if not anchors or 'light_direction_world' not in anchors or anchors['sun_altitude_degrees'] <= 0:
                raise ValueError('EXIF daylight requires a GPS position and UTC timestamp with the sun above the horizon')
            light = anchors['light_direction_world']
        extraction = surface_profile(template, field, camera, patch['photo_pixel'],
            patch['extent_meters'], photo, manifest, output/'camera.json', light)
        extraction['photographic_anchors'] = anchors
        if patch.get('light_direction_from_exif'):
            extraction['calibration'] = 'EXIF GPS-bounded camera candidate; NOAA solar direction from GPS UTC time; exposure and internal cliff correspondences remain unverified'
        (output/'registered-surface.json').write_text(json.dumps(extraction, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('profile', type=Path)
    parser.add_argument('--photo', type=Path)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--preview', action='store_true', help='write a diagnostic plot (requires matplotlib)')
    args = parser.parse_args()
    try:
        report = register(args.profile.resolve(), args.output_dir, args.photo, args.preview)
    except (ValueError, KeyError, OSError, ImportError) as error:
        parser.error(str(error))
    print(json.dumps({key: report[key] for key in ['status', 'skyline_rms_pixels',
        'skyline_max_error_pixels', 'near_search_boundary', 'camera']}, indent=2))


if __name__ == '__main__':
    main()
