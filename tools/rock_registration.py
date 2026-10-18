"""Photo projection in portable map coordinates (east, south, up).

These axes match the loader's Unreal coordinates. Camera right is up cross
forward; using forward cross up would mirror a photograph horizontally.
"""
from __future__ import annotations

import math
import numpy as np


def vector(value, label: str) -> np.ndarray:
    result = np.asarray(value, dtype=float)
    if result.shape != (3,) or not np.isfinite(result).all():
        raise ValueError(label+' must contain three finite components')
    return result


def normalized(value: np.ndarray) -> np.ndarray:
    length = np.linalg.norm(value)
    if length < 1e-8:
        raise ValueError('camera orientation vectors cannot be zero or parallel')
    return value/length


class Camera:
    def __init__(self, definition: dict, image_size: tuple[int, int]):
        self.position = vector(definition['position_meters'], 'camera position')
        self.forward = normalized(vector(definition['forward'], 'camera forward'))
        up = normalized(vector(definition.get('up', [0, 0, 1]), 'camera up'))
        self.right = normalized(np.cross(up, self.forward))
        self.up = normalized(np.cross(self.forward, self.right))
        focal = np.asarray(definition['focal_pixels'], dtype=float)
        if focal.shape == ():
            focal = np.repeat(focal, 2)
        if focal.shape != (2,) or not np.isfinite(focal).all() or np.any(focal <= 0):
            raise ValueError('focal_pixels must contain one or two positive focal lengths')
        principal = np.asarray(definition.get('principal_pixels',
                                   [image_size[0]/2, image_size[1]/2]), dtype=float)
        if principal.shape != (2,) or not np.isfinite(principal).all():
            raise ValueError('principal_pixels must contain two finite pixel coordinates')
        self.focal, self.principal = focal, principal
        self.image_size = image_size

    def project(self, points: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        relative = points-self.position
        depth = relative @ self.forward
        safe_depth = np.where(depth > 1e-8, depth, 1)
        x = self.principal[0]+self.focal[0]*(relative @ self.right)/safe_depth
        y = self.principal[1]-self.focal[1]*(relative @ self.up)/safe_depth
        pixels = np.stack([x, y], axis=-1)
        valid = ((depth > 1e-8) & np.isfinite(pixels).all(axis=-1)
                 & (x >= 0) & (x <= self.image_size[0]-1)
                 & (y >= 0) & (y <= self.image_size[1]-1))
        return pixels, valid

    def rays(self, pixels: np.ndarray) -> np.ndarray:
        x = (pixels[..., 0]-self.principal[0])/self.focal[0]
        y = (self.principal[1]-pixels[..., 1])/self.focal[1]
        direction = self.forward+x[..., None]*self.right+y[..., None]*self.up
        return direction/np.linalg.norm(direction, axis=-1, keepdims=True)

    def definition(self) -> dict:
        return {'position_meters': self.position.tolist(), 'forward': self.forward.tolist(),
                'up': self.up.tolist(), 'focal_pixels': self.focal.tolist(),
                'principal_pixels': self.principal.tolist()}


def sample_photo(rgb: np.ndarray, pixels: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Bilinear RGB sampling, with invalid coordinates kept out of all fits."""
    h, w = rgb.shape[:2]
    x, y = pixels[..., 0], pixels[..., 1]
    valid = np.isfinite(pixels).all(axis=-1) & (x >= 0) & (x <= w-1) & (y >= 0) & (y <= h-1)
    x = np.clip(np.where(valid, x, 0), 0, w-1)
    y = np.clip(np.where(valid, y, 0), 0, h-1)
    x0, y0 = np.floor(x).astype(int), np.floor(y).astype(int)
    x1, y1 = np.minimum(x0+1, w-1), np.minimum(y0+1, h-1)
    tx, ty = (x-x0)[..., None], (y-y0)[..., None]
    result = ((rgb[y0, x0]*(1-tx)+rgb[y0, x1]*tx)*(1-ty)
              + (rgb[y1, x0]*(1-tx)+rgb[y1, x1]*tx)*ty)
    return np.where(valid[..., None], result, 0), valid


def visible_surface(field, points: np.ndarray, camera: Camera, normals_world: np.ndarray,
                    samples: int = 512, tolerance_meters: float = 0.25) -> np.ndarray:
    """Reject back faces and terrain between the camera and a projected patch.

    Sampling is bounded and only tests the supplied heightfield; trees and
    sub-grid overhangs are not occluders in this model.
    """
    if type(samples) is not int or not 8 <= samples <= 1024:
        raise ValueError('occlusion_samples must be an integer within 8..1024')
    if not math.isfinite(tolerance_meters) or tolerance_meters < 0:
        raise ValueError('occlusion_tolerance_meters must be finite and nonnegative')
    to_camera = camera.position-points
    distance = np.linalg.norm(to_camera, axis=-1)
    valid = np.sum(normals_world*to_camera, axis=-1) > 0.05*distance
    # Leave the final tolerance-sized segment at the surface out of the test.
    last = np.maximum(0, 1-(tolerance_meters+1e-3)/np.maximum(distance, 1e-8))
    for fraction in np.linspace(0, 1, samples):
        sample = camera.position+(points-camera.position)*(last*fraction)[..., None]
        elevation = field.sample(sample)
        valid &= ~(sample[..., 2] < elevation-tolerance_meters)
        if not valid.any():
            break
    return valid


def intersect_photo_rays(field, camera: Camera, pixels: np.ndarray, far_meters: float = 4000,
                         step_meters: float = 4) -> tuple[np.ndarray, np.ndarray]:
    """Locate photographic rays on the unchanged heightfield for patch selection."""
    if not all(math.isfinite(value) and value > 0 for value in [far_meters, step_meters]):
        raise ValueError('ray distance and step must be finite and positive')
    count = math.ceil(far_meters/step_meters)
    if count > 2048:
        raise ValueError('photo ray intersection exceeds 2048 steps')
    direction = camera.rays(np.asarray(pixels, dtype=float))
    shape = direction.shape[:-1]
    front = np.zeros(shape)
    back = np.full(shape, np.nan)
    previous = camera.position[2]-field.sample(camera.position)
    previous_distance = 0
    for distance in np.linspace(0, far_meters, count+1)[1:]:
        point = camera.position+direction*distance
        value = point[..., 2]-field.sample(point)
        hit = np.isnan(back) & (previous >= 0) & (value <= 0)
        front = np.where(hit, previous_distance, front)
        back = np.where(hit, distance, back)
        previous, previous_distance = value, distance
        if np.isfinite(back).all():
            break
    valid = np.isfinite(back)
    back = np.where(valid, back, 0)
    for _ in range(16):
        middle = (front+back)/2
        point = camera.position+direction*middle[..., None]
        outside = point[..., 2]-field.sample(point) >= 0
        front = np.where(valid & outside, middle, front)
        back = np.where(valid & ~outside, middle, back)
    points = camera.position+direction*((front+back)/2)[..., None]
    return np.where(valid[..., None], points, np.nan), valid


def projected_skyline(points: np.ndarray, camera: Camera, bin_pixels: float = 2) -> tuple[np.ndarray, np.ndarray]:
    """Top of a terrain grid's projected triangles at pixel-bin centres.

    A flat point cloud retains the historical point-bin approximation. A
    structured [rows, columns, 3] grid connects vertices instead: otherwise
    even a straight ridge produces false notches between sparse samples.
    """
    if not math.isfinite(bin_pixels) or bin_pixels <= 0:
        raise ValueError('skyline bin width must be positive')
    points = np.asarray(points, dtype=float)
    if points.ndim not in [2, 3] or points.shape[-1] != 3 or not np.isfinite(points).all():
        raise ValueError('skyline terrain must be finite [points,3] or [rows,columns,3] coordinates')
    relative = points-camera.position
    depth = relative @ camera.forward
    safe_depth = np.maximum(depth, 1e-8)
    x = camera.principal[0]+camera.focal[0]*(relative @ camera.right)/safe_depth
    y = camera.principal[1]-camera.focal[1]*(relative @ camera.up)/safe_depth
    valid = (depth > 1e-8) & (x >= 0) & (x < camera.image_size[0]) & np.isfinite(y)
    count = math.ceil(camera.image_size[0]/bin_pixels)
    top = np.full(count, np.inf)
    if points.ndim == 2:
        np.minimum.at(top, (x[valid]/bin_pixels).astype(int), y[valid])
    else:
        if min(points.shape[:2]) < 2:
            raise ValueError('skyline grid must have at least two vertices on each axis')
        # Each cell uses the same diagonal as the portable terrain mesh. At
        # fixed screen X the top of a projected triangle lies on an edge.
        screen = np.stack([x, y, depth], axis=-1)
        first = np.concatenate([screen[:, :-1].reshape(-1, 3),
            screen[:-1, :].reshape(-1, 3), screen[:-1, 1:].reshape(-1, 3)])
        second = np.concatenate([screen[:, 1:].reshape(-1, 3),
            screen[1:, :].reshape(-1, 3), screen[1:, :-1].reshape(-1, 3)])
        usable = ((first[:, 2] > 1e-8) & (second[:, 2] > 1e-8)
            & (np.maximum(first[:, 0], second[:, 0]) >= 0)
            & (np.minimum(first[:, 0], second[:, 0]) < camera.image_size[0])
            & (np.minimum(first[:, 1], second[:, 1]) <= camera.image_size[1]-1))
        first, second = first[usable], second[usable]
        lo = np.maximum(0, np.ceil(np.minimum(first[:, 0], second[:, 0])/bin_pixels-0.5)).astype(int)
        hi = np.minimum(count-1, np.floor(np.maximum(first[:, 0], second[:, 0])/bin_pixels-0.5)).astype(int)
        lengths = np.maximum(0, hi-lo+1)
        # Bound temporary arrays even if edges span the entire photograph.
        budget = 250_000
        edge = 0
        while edge < len(first):
            stop = edge+int(np.searchsorted(np.cumsum(lengths[edge:]), budget, side='right'))
            stop = max(edge+1, stop)
            spans = lengths[edge:stop]
            ids = np.repeat(np.arange(edge, stop), spans)
            starts = np.repeat(lo[edge:stop], spans)
            offsets = np.arange(len(ids))-np.repeat(np.cumsum(spans)-spans, spans)
            bins = starts+offsets
            dx = second[ids, 0]-first[ids, 0]
            fraction = np.divide((bins+0.5)*bin_pixels-first[ids, 0], dx,
                                 out=np.zeros_like(dx), where=np.abs(dx)>1e-12)
            rows = first[ids, 1]+fraction*(second[ids, 1]-first[ids, 1])
            rows = np.where(np.abs(dx)>1e-12, rows, np.minimum(first[ids, 1], second[ids, 1]))
            np.minimum.at(top, bins, rows)
            edge = stop
    covered = np.isfinite(top)
    return (np.arange(count)[covered]+0.5)*bin_pixels, top[covered]
