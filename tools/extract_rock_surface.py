#!/usr/bin/env python3
"""Estimate rock normals and a bounded mesh correction from calibrated photos.

A single image is constrained by the source geometry, not a unique 3D
measurement. Three registered views with independent known lights support
Lambertian photometric stereo. Neither mode assumes image brightness is depth.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageOps

try:
    from rock_registration import Camera, sample_photo, visible_surface
except ModuleNotFoundError:
    from tools.rock_registration import Camera, sample_photo, visible_surface


def unit(values: np.ndarray) -> np.ndarray:
    return values / np.maximum(np.linalg.norm(values, axis=-1, keepdims=True), 1e-12)


def linear_srgb(values: np.ndarray) -> np.ndarray:
    return np.where(values <= 0.04045, values / 12.92, ((values + 0.055) / 1.055) ** 2.4)


def srgb(values: np.ndarray) -> np.ndarray:
    values = np.clip(values, 0, 1)
    return np.where(values <= 0.0031308, values * 12.92, 1.055 * values ** (1 / 2.4) - 0.055)


def normals_of_mesh(points: np.ndarray, basis: np.ndarray) -> np.ndarray:
    # Image rows run down; the second surface axis runs up.
    rows, columns = np.gradient(points, axis=(0, 1))
    world = unit(np.cross(columns, -rows))
    world = np.where((world @ basis[:, 2])[..., None] < 0, -world, world)
    return world @ basis


def limit_normals(prior: np.ndarray, estimated: np.ndarray, degrees: float) -> np.ndarray:
    cosine = np.clip(np.sum(prior * estimated, axis=-1), -1, 1)
    angle = np.arccos(cosine)
    tangent = unit(estimated - cosine[..., None] * prior)
    angle = np.minimum(angle, math.radians(degrees))
    result = np.cos(angle)[..., None] * prior + np.sin(angle)[..., None] * tangent
    return unit(np.where((np.linalg.norm(tangent, axis=-1) < 1e-8)[..., None], prior, result))


def snow_orientation_cue(prior: np.ndarray, estimated: np.ndarray, mask: np.ndarray,
                         up: np.ndarray, minimum_up_cosine: float, weight: float,
                         max_angle: float) -> np.ndarray:
    """Soft evidence of an upward-facing shelf, not a snow => horizontal rule."""
    up = np.asarray(up, dtype=float)
    if up.shape != (3,) or not np.isfinite(up).all() or np.linalg.norm(up) < 1e-8:
        raise ValueError('snow up_direction must be a finite nonzero three-component vector')
    if not 0 <= weight <= 1 or not 0 <= minimum_up_cosine <= 1:
        raise ValueError('snow weight and minimum_up_cosine must be within 0..1')
    up = unit(up)
    cosine = np.sum(estimated*up, axis=-1)
    target = max(0, minimum_up_cosine)
    perpendicular = unit(estimated-cosine[..., None]*up)
    desired = target*up+math.sqrt(1-target*target)*perpendicular
    blended = unit((1-weight)*estimated+weight*desired)
    active = mask & (cosine < target)
    blended = np.where(active[..., None], blended, estimated)
    return limit_normals(prior, blended, max_angle)


def estimate_normals(images: np.ndarray, lights: np.ndarray, prior: np.ndarray,
                     mask: np.ndarray, gains: list[float | None], ambient: np.ndarray,
                     reference_albedo: float, max_angle: float) -> tuple[np.ndarray, np.ndarray, dict]:
    lights = np.asarray(lights, dtype=np.float64)
    if lights.shape != (len(images), 3) or not np.isfinite(lights).all():
        raise ValueError('each view needs a finite three-component light_direction')
    if np.any(np.linalg.norm(lights, axis=1) < 1e-8):
        raise ValueError('light_direction cannot be zero')
    lights = unit(lights)
    if len(images) == 2:
        raise ValueError('use one prior-constrained photo or at least three registered photos')
    valid = mask.copy()
    corrected, used_gains = [], []
    for image, light, gain, offset in zip(images, lights, gains, ambient, strict=True):
        predicted = np.sum(prior * light, axis=-1)
        available = mask & (predicted > 0.15) & (image > offset)
        if gain is None:
            if not available.any():
                if len(images) == 1:
                    return prior.copy(), np.zeros_like(mask), {
                        'mode': 'geometry-prior-without-usable-rock-radiometry',
                        'normals_identifiable_under_model': False,
                        'exposure_gains': [], 'exposure_estimated_from_prior': False,
                        'radiometry_rejection': 'no sufficiently lit samples for automatic exposure calibration'}
                raise ValueError('no lit rock samples are available to estimate exposure gain')
            gain = float(np.median((image[available] - offset)
                                   / (reference_albedo * predicted[available])))
        if not math.isfinite(gain) or gain <= 0:
            raise ValueError('exposure_gain must be finite and positive')
        used_gains.append(gain)
        measured = (image - offset) / gain
        # Deep shadow and an impossible cosine are unsuitable observations.
        valid &= (measured > reference_albedo * 0.1) & (predicted > 0.05)
        corrected.append(measured)
    intensities = np.asarray(corrected)
    if len(images) == 1:
        light = lights[0]
        cosine = intensities[0] / reference_albedo
        projection = np.sum(prior * light, axis=-1)
        perpendicular = prior - projection[..., None] * light
        perpendicular_length = np.linalg.norm(perpendicular, axis=-1)
        # Light exactly parallel to the prior leaves tilt direction undefined.
        valid &= (perpendicular_length > 0.05) & (cosine < 1)
        cosine = np.clip(cosine, 0, 1)
        estimated = (cosine[..., None] * light
                     + np.sqrt(1-cosine*cosine)[..., None] * unit(perpendicular))
        information = {'mode': 'single-photo-with-geometry-prior',
                       'normals_identifiable_under_model': False}
    else:
        if np.linalg.matrix_rank(lights, tol=1e-5) != 3:
            raise ValueError('lighting directions do not span three dimensions')
        condition = float(np.linalg.cond(lights))
        if condition > 50:
            raise ValueError('lighting directions are too similar for reliable stereo')
        vector = np.einsum('ij,jhw->hwi', np.linalg.pinv(lights), intensities)
        estimated = unit(vector)
        albedo = np.linalg.norm(vector, axis=-1)
        predictions = np.einsum('ij,hwj->ihw', lights, vector)
        residual = np.sqrt(np.mean((predictions-intensities)**2, axis=0))
        valid &= (albedo > 0.05) & (albedo <= 1.2) & (residual < 0.1)
        valid &= np.all(predictions > 0, axis=0)
        information = {'mode': 'calibrated-photometric-stereo',
                       'normals_identifiable_under_model': True, 'light_condition_number': condition}
    valid &= estimated[..., 2] > 0.2
    estimated = limit_normals(prior, estimated, max_angle)
    estimated = np.where(valid[..., None], estimated, prior)
    information['exposure_gains'] = used_gains
    information['exposure_estimated_from_prior'] = any(gain is None for gain in gains)
    return estimated, valid, information


def edge_fade(mask: np.ndarray, pixels: int) -> np.ndarray:
    remaining = np.pad(mask, 1)
    result = np.zeros(mask.shape, dtype=np.float64)
    for _ in range(max(1, pixels)):
        remaining[1:-1, 1:-1] = (remaining[1:-1, 1:-1] & remaining[:-2, 1:-1]
            & remaining[2:, 1:-1] & remaining[1:-1, :-2] & remaining[1:-1, 2:])
        result += remaining[1:-1, 1:-1]
    weight = result / max(1, pixels)
    return weight*weight*(3-2*weight)


def integrate_correction(prior: np.ndarray, estimated: np.ndarray, mask: np.ndarray,
                         spacing: tuple[float, float], detail_scale: float,
                         max_displacement: float, fade_pixels: int) -> np.ndarray:
    # A screened least-squares integration anchors long wavelengths to the
    # original geometry. Unknown gradient components receive minimum energy.
    prior_z = np.maximum(prior[..., 2], 0.2)
    estimated_z = np.maximum(estimated[..., 2], 0.2)
    px = -(estimated[..., 0]/estimated_z - prior[..., 0]/prior_z)
    py = estimated[..., 1]/estimated_z - prior[..., 1]/prior_z
    weight = edge_fade(mask, fade_pixels)
    height, width = mask.shape
    dx = (np.exp(2j*np.pi*np.fft.fftfreq(width))-1) / spacing[0]
    dy = (np.exp(2j*np.pi*np.fft.fftfreq(height))-1) / spacing[1]
    screen = (2*math.pi/detail_scale)**2
    spectrum = ((np.conj(dx)[None, :] * np.fft.fft2(px*weight)
                 + np.conj(dy)[:, None] * np.fft.fft2(py*weight))
                / (np.abs(dx)[None, :]**2 + np.abs(dy)[:, None]**2 + screen))
    displacement = np.fft.ifft2(spectrum).real * weight
    peak = float(np.max(np.abs(displacement)))
    if peak > max_displacement:
        displacement *= max_displacement / peak
    return displacement


def procedural_detail(displacement: np.ndarray, spacing: tuple[float, float],
                      seed: int, amplitude: float, angle: float) -> tuple[np.ndarray, np.ndarray]:
    # Retain the estimated spatial spectrum and replace its phases. The result
    # is periodic, reproducible detail rather than a fixed photographic facade.
    noise = np.fft.fft2(np.random.default_rng(seed).normal(size=displacement.shape))
    spectrum = np.abs(np.fft.fft2(displacement)) * noise / np.maximum(np.abs(noise), 1e-12)
    spectrum[0, 0] = 0
    detail = np.fft.ifft2(spectrum).real
    gx = (np.roll(detail, -1, axis=1)-np.roll(detail, 1, axis=1))/(2*spacing[0])
    gy = (np.roll(detail, -1, axis=0)-np.roll(detail, 1, axis=0))/(2*spacing[1])
    scale = min(1, amplitude/max(float(np.max(np.abs(detail))), 1e-12),
                math.tan(math.radians(angle))/max(float(np.max(np.hypot(gx, gy))), 1e-12))
    detail *= scale
    normal = unit(np.stack([-gx*scale, gy*scale, np.ones(detail.shape)], axis=-1))
    return detail, normal


class Heightfield:
    def __init__(self, manifest: Path):
        definition = json.loads(manifest.read_text(encoding='utf-8'))['terrain']
        source = definition['source']
        if source['format'] not in ['r16le', 'r16be']:
            raise ValueError('heightmap source must be r16le or r16be')
        width, height = source['vertices']
        self.source_path = manifest.parent/source['file']
        self.source_sha256 = hashlib.sha256(self.source_path.read_bytes()).hexdigest()
        transform = {'origin_centimeters': definition.get('origin_centimeters'),
            'size_meters': definition['size_meters'],
            'source': {key: source.get(key) for key in ['vertices', 'spacing_meters',
                'height_scale_meters', 'height_offset_meters', 'row_order', 'format']}}
        self.geometry_sha256 = hashlib.sha256(json.dumps(transform, sort_keys=True).encode()).hexdigest()
        data = np.fromfile(self.source_path,
                           dtype='<u2' if source['format'] == 'r16le' else '>u2')
        if data.size != width*height:
            raise ValueError('heightmap byte count does not match its declared dimensions')
        self.values = data.reshape(height, width).astype(np.float64)
        if source.get('row_order') == 'south_to_north':
            self.values = self.values[::-1]
        origin = definition.get('origin_centimeters',
                                [-definition['size_meters'][0]*50,
                                 -definition['size_meters'][1]*50, 0])
        self.origin = np.asarray(origin, dtype=np.float64)/100
        self.spacing = source['spacing_meters']
        self.values = (self.values*source['height_scale_meters']
                       + source['height_offset_meters'] + self.origin[2])

    def sample(self, points: np.ndarray) -> np.ndarray:
        x = (points[..., 0]-self.origin[0])/self.spacing
        y = (points[..., 1]-self.origin[1])/self.spacing
        h, w = self.values.shape
        valid = (x >= 0) & (y >= 0) & (x <= w-1) & (y <= h-1)
        x, y = np.clip(x, 0, w-1), np.clip(y, 0, h-1)
        x0, y0 = np.floor(x).astype(int), np.floor(y).astype(int)
        x1, y1 = np.minimum(x0+1, w-1), np.minimum(y0+1, h-1)
        tx, ty = x-x0, y-y0
        value = ((self.values[y0, x0]*(1-tx)+self.values[y0, x1]*tx)*(1-ty)
                 + (self.values[y1, x0]*(1-tx)+self.values[y1, x1]*tx)*ty)
        return np.where(valid, value, np.nan)

    def project(self, plane: np.ndarray, normal: np.ndarray, distance: float,
                ray_step: float) -> tuple[np.ndarray, np.ndarray]:
        steps = math.ceil(2*distance/ray_step)
        if not 1 <= steps <= 512:
            raise ValueError('heightmap projection needs 1..512 ray steps')
        front = np.full(plane.shape[:2], distance)
        result = np.full(plane.shape[:2], np.nan)
        previous = plane[..., 2]+normal[2]*distance-self.sample(plane+normal*distance)
        previous_distance = distance
        for current_distance in np.linspace(distance, -distance, steps+1)[1:]:
            point = plane+normal*current_distance
            value = point[..., 2]-self.sample(point)
            hit = np.isnan(result) & (previous >= 0) & (value <= 0)
            front[hit] = previous_distance
            result[hit] = current_distance
            previous, previous_distance = value, current_distance
        valid = np.isfinite(result)
        back = np.where(valid, result, front)
        for _ in range(12):
            midpoint = (front+back)/2
            point = plane+normal*midpoint[..., None]
            outside = point[..., 2]-self.sample(point) >= 0
            front = np.where(valid & outside, midpoint, front)
            back = np.where(valid & ~outside, midpoint, back)
        depth = np.where(valid, (front+back)/2, 0)
        return plane+normal*depth[..., None], valid


def write_obj(path: Path, points: np.ndarray, normals: np.ndarray,
              mask: np.ndarray, basis: np.ndarray) -> int:
    height, width = mask.shape
    faces = 0
    with path.open('w', encoding='utf-8') as output:
        output.write('# Portable rock patch; map coordinates in metres\n')
        for point in points.reshape(-1, 3):
            output.write('v %.7f %.7f %.7f\n' % tuple(point))
        for row in range(height):
            for column in range(width):
                output.write(f'vt {column/(width-1):.7f} {1-row/(height-1):.7f}\n')
        for normal in (normals @ basis.T).reshape(-1, 3):
            output.write('vn %.7f %.7f %.7f\n' % tuple(normal))
        for row in range(height-1):
            for column in range(width-1):
                if not mask[row:row+2, column:column+2].all():
                    continue
                a = row*width+column+1
                for triangle in [(a, a+width, a+1), (a+1, a+width, a+width+1)]:
                    output.write('f '+' '.join(f'{i}/{i}/{i}' for i in triangle)+'\n')
                    faces += 1
    return faces


def save_normal(path: Path, values: np.ndarray) -> None:
    Image.fromarray(np.rint(np.clip(values*0.5+0.5, 0, 1)*255).astype('uint8')).save(path)


def extract(profile_path: Path, output: Path, photo_override: Path | None = None) -> dict:
    profile = json.loads(profile_path.read_text(encoding='utf-8'))
    if profile.get('version') != 1:
        raise ValueError('surface extraction profile version must be 1')
    views = profile['views']
    if not 1 <= len(views) <= 8:
        raise ValueError('provide 1..8 registered views')
    if len(views) == 2:
        raise ValueError('use one prior-constrained photo or at least three registered photos')
    if photo_override is not None:
        if len(views) != 1:
            raise ValueError('--photo applies only to a single-view profile')
        views[0]['file'] = str(photo_override.resolve())
    width, height = profile.get('size', [128, 128])
    if any(type(n) is not int or not 8 <= n <= 512 for n in [width, height]):
        raise ValueError('output dimensions must be integers within 8..512')
    surface = profile['surface']
    def positive(name: str, default: float) -> float:
        value = float(surface.get(name, default))
        if not math.isfinite(value) or value <= 0:
            raise ValueError(name+' must be finite and positive')
        return value
    extent = np.asarray(surface['extent_meters'], dtype=float)
    if extent.shape != (2,) or not np.isfinite(extent).all() or np.any(extent <= 0):
        raise ValueError('extent_meters must contain two finite positive lengths')
    spacing = (extent[0]/(width-1), extent[1]/(height-1))
    angle = positive('max_angle_degrees', 20)
    if angle > 60:
        raise ValueError('max_angle_degrees must not exceed 60')
    amplitude = positive('max_displacement_meters', 0.5)
    detail_scale = positive('detail_scale_meters', 10)
    fade_pixels = min(64, max(2, math.ceil(positive('edge_fade_meters', 3)/min(spacing))))
    albedo = positive('reference_albedo', 0.75)
    if albedo > 1:
        raise ValueError('reference_albedo must not exceed 1')
    axes = np.asarray(surface.get('axes', [[1, 0, 0], [0, 1, 0]]), dtype=float)
    if axes.shape != (2, 3) or not np.isfinite(axes).all() or np.any(np.linalg.norm(axes, axis=1) < 1e-8):
        raise ValueError('axes must contain two finite nonzero vectors')
    axes = unit(axes)
    if abs(np.dot(*axes)) > 1e-6:
        raise ValueError('surface axes must be orthogonal')
    basis = np.column_stack([axes[0], axes[1], np.cross(*axes)])
    origin = np.asarray(surface.get('origin_meters', [0, 0, 0]), dtype=float)
    if origin.shape != (3,) or not np.isfinite(origin).all():
        raise ValueError('origin_meters must contain three finite coordinates')
    x, y = np.meshgrid(np.linspace(0, extent[0], width), np.linspace(extent[1], 0, height))
    plane = origin+x[..., None]*axes[0]+y[..., None]*axes[1]
    baseline, geometric_valid = plane, np.ones((height, width), dtype=bool)
    terrain = profile.get('heightmap')
    heightfield = None
    if terrain:
        distance = float(terrain.get('ray_distance_meters', 100))
        ray_step = float(terrain.get('ray_step_meters', 4))
        if not all(math.isfinite(v) and v > 0 for v in [distance, ray_step]):
            raise ValueError('ray distance and step must be finite and positive')
        heightfield = Heightfield(profile_path.parent/terrain['manifest'])
        baseline, geometric_valid = heightfield.project(
            plane, basis[:, 2], distance, ray_step)
    prior = normals_of_mesh(baseline, basis)
    geometric_valid &= prior[..., 2] > 0.2
    channel = profile.get('channel', 'luminance')
    if channel not in ['red', 'green', 'blue', 'luminance']:
        raise ValueError('channel must be red, green, blue or luminance')
    images, clips, sources, photo_pixels, visibility, cameras = [], [], [], [], [], []
    crop_preview, first_rgb = None, None
    for view in views:
        source = (profile_path.parent/view['file']).resolve()
        with Image.open(source) as image:
            image = ImageOps.exif_transpose(image).convert('RGB')
            camera_definition = view.get('camera')
            camera_registration = None
            if view.get('camera_file'):
                if camera_definition is not None:
                    raise ValueError('choose camera or camera_file, not both')
                camera_registration = json.loads((profile_path.parent/view['camera_file']).read_text(encoding='utf-8'))
                camera_definition = camera_registration['camera']
                if camera_registration.get('photo_sha256') and hashlib.sha256(source.read_bytes()).hexdigest() != camera_registration['photo_sha256']:
                    raise ValueError('camera registration belongs to a different source photo; recalibrate it')
            if camera_definition is not None:
                if heightfield is None:
                    raise ValueError('perspective photo projection requires a source heightmap')
                if camera_registration:
                    if camera_registration.get('heightmap_sha256', heightfield.source_sha256) != heightfield.source_sha256:
                        raise ValueError('camera registration belongs to a different heightmap; recalibrate it')
                    if camera_registration.get('heightmap_geometry_sha256', heightfield.geometry_sha256) != heightfield.geometry_sha256:
                        raise ValueError('heightmap transform changed since camera registration; recalibrate it')
                if 'crop' in view:
                    raise ValueError('camera intrinsics refer to the full oriented photo; omit crop')
                camera = Camera(camera_definition, image.size)
                pixels, in_frame = camera.project(baseline)
                raw, in_bounds = sample_photo(np.asarray(image, dtype=float)/255, pixels)
                visible = visible_surface(heightfield, baseline, camera, prior @ basis.T,
                    view.get('occlusion_samples', 512), float(view.get('occlusion_tolerance_meters', 0.25)))
                visible &= in_frame & in_bounds & geometric_valid
                cameras.append({'camera': camera.definition(), 'visible_pixels': int(visible.sum()),
                    'registration': camera_registration,
                    'occlusion_samples': view.get('occlusion_samples', 512)})
                image = Image.fromarray(np.rint(raw*255).astype('uint8'))
            else:
                crop = view.get('crop', [0, 0, image.width, image.height])
                if len(crop) != 4 or not (0 <= crop[0] < crop[2] <= image.width
                                         and 0 <= crop[1] < crop[3] <= image.height):
                    raise ValueError('photo crop must lie inside its original image')
                image = image.crop(crop).resize((width, height), Image.Resampling.LANCZOS)
                raw = np.asarray(image, dtype=float)/255
                px, py = np.meshgrid(np.linspace(crop[0], crop[2]-1, width),
                                     np.linspace(crop[1], crop[3]-1, height))
                pixels = np.stack([px, py], axis=-1)
                visible = np.ones((height, width), dtype=bool)
                cameras.append(None)
            if crop_preview is None:
                crop_preview = image.copy()
            if first_rgb is None:
                first_rgb = raw
            values = linear_srgb(raw)
            if channel == 'luminance':
                clips.append(np.max(raw, axis=-1) < 250/255)
                images.append(values @ [0.2126, 0.7152, 0.0722])
            else:
                index = ['red', 'green', 'blue'].index(channel)
                clips.append(raw[..., index] < 250/255)
                images.append(values[..., index])
            sources.append(str(source))
            photo_pixels.append(pixels)
            visibility.append(visible)
    mask_image = Image.new('L', (width, height), 0)
    polygons = profile.get('rock_polygons_uv')
    if not polygons:
        raise ValueError('rock_polygons_uv must explicitly select the rock surface, excluding sky')
    draw = ImageDraw.Draw(mask_image)
    for polygon in polygons:
        points = np.asarray(polygon, dtype=float)
        if points.ndim != 2 or points.shape[1] != 2 or len(points) < 3 or not np.isfinite(points).all():
            raise ValueError('each rock polygon needs at least three finite UV points')
        if np.any((points < 0) | (points > 1)):
            raise ValueError('rock polygon UV points must lie within 0..1')
        draw.polygon([tuple(p) for p in points*[width-1, height-1]], fill=255)
    for polygon in profile.get('exclude_polygons_uv', []):
        points = np.asarray(polygon, dtype=float)
        if (points.ndim != 2 or points.shape[1] != 2 or len(points) < 3
            or not np.isfinite(points).all() or np.any((points < 0) | (points > 1))):
            raise ValueError('excluded polygons need at least three finite UV points within 0..1')
        draw.polygon([tuple(p) for p in points*[width-1, height-1]], fill=0)
    # Keep the original mesh where radiometry is unreliable. Snow supplies a
    # separate geometric cue even when its bright pixels cannot be shaded-fit.
    mesh_mask = (np.asarray(mask_image) > 0) & geometric_valid
    rock_mask = mesh_mask.copy()
    color_gate = profile.get('rock_color_gate', {})
    for name, denominator in [('red_over_blue_min', 2), ('red_over_green_min', 1)]:
        if name in color_gate:
            ratio = float(color_gate[name])
            if not math.isfinite(ratio) or ratio <= 0:
                raise ValueError('rock color gate ratios must be finite and positive')
            rock_mask &= first_rgb[..., 0] >= ratio*first_rgb[..., denominator]
    snow = profile.get('snow_cue')
    snow_mask = np.zeros((height, width), dtype=bool)
    snow_weight = 0.0
    if snow:
        snow_weight = float(snow.get('weight', 0.35))
        if not math.isfinite(snow_weight) or not 0 <= snow_weight <= 1:
            raise ValueError('snow weight must be within 0..1')
        polygons = snow.get('polygons_uv')
        if polygons:
            snow_image = Image.new('L', (width, height), 0)
            snow_draw = ImageDraw.Draw(snow_image)
            for polygon in polygons:
                points = np.asarray(polygon, dtype=float)
                if (points.ndim != 2 or points.shape[1] != 2 or len(points) < 3
                    or not np.isfinite(points).all() or np.any((points < 0) | (points > 1))):
                    raise ValueError('snow polygons need at least three UV points within 0..1')
                snow_draw.polygon([tuple(p) for p in points*[width-1, height-1]], fill=255)
            snow_mask = np.asarray(snow_image) > 0
        else:
            brightness = float(snow.get('min_brightness_srgb', 0.65))
            ratio = float(snow.get('max_red_over_blue', 1.6))
            if not math.isfinite(brightness) or not 0 <= brightness <= 1 or not math.isfinite(ratio) or ratio <= 0:
                raise ValueError('snow brightness must be within 0..1 and its color ratio positive')
            snow_mask = ((np.min(first_rgb, axis=-1) >= brightness)
                         & (first_rgb[..., 0] <= ratio*first_rgb[..., 2]))
        snow_mask &= mesh_mask & visibility[0]
        # Snow must not be interpreted as the diffuse color of the bare rock.
        rock_mask &= ~snow_mask
    mask = rock_mask & np.all(clips, axis=0) & np.all(visibility, axis=0)
    ambient = np.asarray([v.get('ambient_linear', 0) for v in views], dtype=float)
    if not np.isfinite(ambient).all() or np.any(ambient < 0):
        raise ValueError('ambient_linear must be finite and nonnegative')
    if mask.any():
        estimated, photometric_valid, information = estimate_normals(np.asarray(images),
            np.asarray([v['light_direction'] for v in views]), prior, mask,
            [v.get('exposure_gain') for v in views], ambient, albedo, angle)
    else:
        estimated, photometric_valid = prior.copy(), np.zeros_like(mask)
        information = {'mode': 'geometry-prior-without-usable-rock-radiometry',
                       'normals_identifiable_under_model': False, 'exposure_gains': [],
                       'exposure_estimated_from_prior': False}
    snow_up = np.asarray([0, 0, 1]) @ basis
    if snow:
        snow_up = np.asarray(snow.get('up_direction', snow_up), dtype=float)
        minimum_up = float(snow.get('minimum_up_cosine', 0.6))
        estimated = snow_orientation_cue(prior, estimated, snow_mask,
                                         snow_up, minimum_up, snow_weight, angle)
    valid = photometric_valid | (snow_mask & (snow_weight > 0))
    if np.count_nonzero(valid) < 64:
        raise ValueError('fewer than 64 usable surface cues; check mask, projection and lighting calibration')
    displacement = integrate_correction(prior, estimated, valid, spacing,
                                        detail_scale, amplitude, fade_pixels)
    # Angle limiting the estimated normals is insufficient: integration and
    # boundary blending can change the final geometry. Bound the actual mesh.
    for _ in range(24):
        corrected = baseline+basis[:, 2]*displacement[..., None]
        applied = normals_of_mesh(corrected, basis)
        delta = np.degrees(np.arccos(np.clip(np.sum(prior*applied, axis=-1), -1, 1)))
        if np.max(delta[geometric_valid]) <= angle+1e-6:
            break
        displacement *= 0.75
    else:
        raise ValueError('could not respect the geometry angle limit')
    rgb_albedo = np.asarray(surface.get('albedo_srgb', [0.9, 0.9, 0.87]), dtype=float)
    roughness = float(surface.get('roughness', 0.85))
    if rgb_albedo.shape != (3,) or not np.isfinite(rgb_albedo).all() or np.any((rgb_albedo < 0) | (rgb_albedo > 1)):
        raise ValueError('albedo_srgb must contain three values within 0..1')
    if not math.isfinite(roughness) or not 0 <= roughness <= 1:
        raise ValueError('roughness must be within 0..1')
    seed = profile.get('procedural_seed', 0)
    if type(seed) is not int or seed < 0:
        raise ValueError('procedural_seed must be a nonnegative integer')
    detail, detail_normal = procedural_detail(displacement, spacing, seed, amplitude, angle)
    output.mkdir(parents=True, exist_ok=True)
    crop_preview.save(output/'photo-crop.png')
    Image.fromarray(valid.astype('uint8')*255).save(output/'validity.png')
    Image.fromarray(mesh_mask.astype('uint8')*255).save(output/'geometry-mask.png')
    Image.fromarray(photometric_valid.astype('uint8')*255).save(output/'photometric-validity.png')
    Image.fromarray(snow_mask.astype('uint8')*255).save(output/'snow-cue-mask.png')
    Image.fromarray(np.all(visibility, axis=0).astype('uint8')*255).save(output/'photo-visibility.png')
    save_normal(output/'normal-estimated.png', estimated)
    save_normal(output/'normal-applied.png', applied)
    encoded = np.rint(np.clip(0.5+displacement/(2*amplitude), 0, 1)*65535).astype('<u2')
    encoded.tofile(output/'displacement.r16')
    Image.fromarray(encoded).save(output/'displacement.png')
    faces = write_obj(output/'patch.obj', corrected, applied, mesh_mask, basis)
    write_obj(output/'patch-base.obj', baseline, prior, mesh_mask, basis)
    if not faces:
        raise ValueError('no contiguous usable rock cells remain to export')
    for name, light in [('left', [0.75, 0.35, 0.65]), ('right', [-0.75, 0.35, 0.65])]:
        shade = np.maximum(0, np.sum(applied*unit(np.asarray(light)), axis=-1))
        rgb = srgb(linear_srgb(rgb_albedo)*(0.15+0.85*shade[..., None]))
        rgb[~mesh_mask] = [0.12, 0.15, 0.18]
        Image.fromarray(np.rint(rgb*255).astype('uint8')).save(output/f'relit-{name}.png')
        tile_shade = np.maximum(0, np.sum(detail_normal*unit(np.asarray(light)), axis=-1))
        tile_rgb = srgb(linear_srgb(rgb_albedo)*(0.15+0.85*tile_shade[..., None]))
        Image.fromarray(np.rint(tile_rgb*255).astype('uint8')).save(output/f'procedural-relit-{name}.png')
    detail_encoded = np.rint(np.clip(0.5+detail/(2*amplitude), 0, 1)*65535).astype('<u2')
    detail_encoded.tofile(output/'procedural-displacement.r16')
    Image.fromarray(detail_encoded).save(output/'procedural-displacement.png')
    save_normal(output/'procedural-normal.png', detail_normal)
    np.savez_compressed(output/'surface-data.npz', base_meters=baseline,
        corrected_meters=corrected, normal_prior=prior, normal_estimated=estimated,
        normal_applied=applied, valid=valid, photometric_valid=photometric_valid,
        snow_cue_mask=snow_mask, geometry_mask=mesh_mask,
        photo_pixels=np.asarray(photo_pixels), photo_visible=np.asarray(visibility),
        displacement_meters=displacement, procedural_displacement_meters=detail,
        procedural_normal=detail_normal)
    information.update({'version': 1, 'sources': sources, 'size': [width, height],
        'calibration': profile.get('calibration', 'assumed'), 'heightmap_projected': bool(terrain),
        'perspective_projection': any(camera is not None for camera in cameras), 'views': cameras,
        'valid_pixels': int(valid.sum()), 'valid_fraction': float(np.mean(valid)),
        'geometry_pixels': int(mesh_mask.sum()),
        'photometric_valid_pixels': int(photometric_valid.sum()),
        'snow_cue': {'pixels': int(snow_mask.sum()), 'weight': snow_weight,
                     'up_direction_local': snow_up.tolist(),
                     'minimum_up_cosine': float(snow.get('minimum_up_cosine', 0.6)) if snow else None,
                     'inferred_horizontal_surface': False},
        'mesh_triangles': faces, 'spacing_meters': list(spacing),
        'max_applied_displacement_meters': float(np.max(np.abs(displacement))),
        'max_applied_angle_degrees': float(np.max(delta[geometric_valid])),
        'displacement_encoding': {'format': 'r16le', 'scale_meters': 2*amplitude/65535,
                                  'offset_meters': -amplitude},
        'normal_encoding': 'linear RGB = (normal_u, normal_v, normal_front) * 0.5 + 0.5',
        'material': {'albedo_srgb': rgb_albedo.tolist(), 'roughness': roughness,
                     'measured_albedo_or_roughness': False},
        'basis_columns': basis.tolist(), 'origin_meters': origin.tolist(),
        'detail_scale_meters': detail_scale, 'max_displacement_meters': amplitude,
        'procedural': {'method': 'phase-randomized-estimated-displacement-spectrum',
                       'seed': seed, 'periodic': True,
                       'max_displacement_meters': float(np.max(np.abs(detail)))},
        'limitations': ['Photos must depict the same registered surface patch.',
            'Single-view orientation retains the unconstrained direction from the geometry prior.',
            'Clipped highlights, cast shadows, snow, variable albedo and camera processing can bias estimates.',
            'A photographic patch needs calibrated geometric registration before map integration.',
            'Normal/displacement inference does not measure material roughness.']})
    if snow:
        information['limitations'].append(
            'Snow is soft orientation evidence: wind, frost and accumulation thickness can cover steep surfaces.')
    if any(camera is not None for camera in cameras):
        information['limitations'].append(
            'Heightfield visibility is sampled; trees, overhangs and camera lens distortion are not modeled.')
    (output/'surface.json').write_text(json.dumps(information, indent=2)+'\n', encoding='utf-8')
    return information


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('profile', type=Path)
    parser.add_argument('--photo', type=Path, help='override the photo of a single-view profile')
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    try:
        report = extract(args.profile.resolve(), args.output_dir, args.photo)
    except (ValueError, KeyError, OSError) as error:
        parser.error(str(error))
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
