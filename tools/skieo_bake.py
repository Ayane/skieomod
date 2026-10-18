"""Deterministic, dependency-free terrain processing and vegetation baking.

These bounded heightfield models are authoring tools, not a climate or water
simulation. Heights and distances are metres; every bake starts from source.
"""
from __future__ import annotations

from array import array
import copy
import json
import math
from pathlib import PurePosixPath
import random
import struct
import zlib


def object_settings(value, label, allowed):
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object.")
    unknown = set(value) - set(allowed)
    if unknown:
        raise ValueError(f"Unknown {label} setting: {', '.join(sorted(unknown))}.")
    return value


def number(settings, name, default, low, high, *, integer=False):
    value = settings.get(name, default)
    kind = int if integer else (int, float)
    if isinstance(value, bool) or not isinstance(value, kind) or not low <= value <= high or not math.isfinite(value):
        raise ValueError(f"{name} must be {'an integer' if integer else 'a finite number'} between {low} and {high}.")
    return value


def flag(settings, name, default=True):
    value = settings.get(name, default)
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be true or false.")
    return value


def mix(a, b, fraction):
    return a + (b - a) * fraction


def clamp(value, low=0., high=1.):
    return max(low, min(high, value))


def interpolate(values, width, height, x, y):
    x, y = clamp(x, 0, width - 1), clamp(y, 0, height - 1)
    left, top = int(x), int(y)
    right, bottom = min(left + 1, width - 1), min(top + 1, height - 1)
    return mix(mix(values[top * width + left], values[top * width + right], x - left),
               mix(values[bottom * width + left], values[bottom * width + right], x - left), y - top)


def grid(values, width, height, spacing, resolution):
    ratio = min(1., (resolution - 1) / max(width - 1, height - 1))
    w, h = max(2, round((width - 1) * ratio) + 1), max(2, round((height - 1) * ratio) + 1)
    result = array('d', (interpolate(values, width, height, x * (width - 1) / (w - 1), y * (height - 1) / (h - 1))
                        for y in range(h) for x in range(w)))
    return result, w, h, spacing * (width - 1) / (w - 1), spacing * (height - 1) / (h - 1)


def neighbours(width, height, sx, sy):
    return [(dx, dy, math.hypot(dx * sx, dy * sy)) for dy in (-1, 0, 1) for dx in (-1, 0, 1) if dx or dy]


def drainage(values, width, height, sx, sy):
    """D8 steepest-descent routing; depressions retain water, edges are outlets."""
    target = array('i', [-1]) * len(values)
    slopes = array('d', [0.]) * len(values)
    offsets = neighbours(width, height, sx, sy)
    for y in range(1, height - 1):
        for x in range(1, width - 1):
            i = y * width + x
            for dx, dy, distance in offsets:
                j = i + dy * width + dx
                slope = (values[i] - values[j]) / distance
                if slope > slopes[i]:
                    target[i], slopes[i] = j, slope
    accumulation = array('d', [1.]) * len(values)
    for i in sorted(range(len(values)), key=values.__getitem__, reverse=True):
        if target[i] >= 0:
            accumulation[target[i]] += accumulation[i]
    return target, slopes, accumulation


def terrain_processing(values, width, height, spacing, settings):
    settings = object_settings(settings, 'build.heightmap.processing',
        ('resolution', 'smoothing', 'thermal_erosion', 'hydraulic_erosion', 'noise'))
    resolution = number(settings, 'resolution', 513, 33, 1025, integer=True)
    result, w, h, sx, sy = grid(values, width, height, spacing, resolution)
    original = array('d', result)
    stats = {'analysis_vertices': [w, h], 'techniques': {}}
    offsets = neighbours(w, h, sx, sy)
    for method in ('smoothing', 'thermal_erosion', 'hydraulic_erosion'):
        if method not in settings:
            continue
        allowed = ['iterations', 'strength', 'max_delta_meters']
        if method == 'thermal_erosion':
            allowed.append('talus_degrees')
        if method == 'hydraulic_erosion':
            allowed.append('rainfall')
        options = object_settings(settings[method], method, allowed)
        iterations = number(options, 'iterations', 2 if method == 'smoothing' else 8, 0, 50, integer=True)
        strength = number(options, 'strength', .2, 0, 1)
        budget = number(options, 'max_delta_meters', 2 if method == 'smoothing' else 5, 0, 100)
        talus = math.tan(math.radians(number(options, 'talus_degrees', 35, 0, 89))) if method == 'thermal_erosion' else 0
        rainfall = number(options, 'rainfall', 1, 0, 10) if method == 'hydraulic_erosion' else 1
        before = array('d', result)
        for _ in range(iterations):
            delta = array('d', [0.]) * len(result)
            if method == 'hydraulic_erosion':
                targets, slopes, accumulation = drainage(result, w, h, sx, sy)
            for y in range(1, h - 1):
                for x in range(1, w - 1):
                    i = y * w + x
                    if method == 'smoothing':
                        mean = (result[i - 1] + result[i + 1] + result[i - w] + result[i + w]) / 4
                        delta[i] = clamp((mean - result[i]) * strength,
                            before[i] - budget - result[i], before[i] + budget - result[i])
                        continue
                    if method == 'thermal_erosion':
                        excess, j = 0., -1
                        for dx, dy, distance in offsets:
                            # Fixed perimeter: transfer only between interior vertices.
                            if not (0 < x + dx < w - 1 and 0 < y + dy < h - 1):
                                continue
                            other = i + dy * w + dx
                            drop = result[i] - result[other] - talus * distance
                            if drop > excess:
                                excess, j = drop, other
                        amount = excess * .5 * strength
                    else:
                        j = targets[i]
                        if j < 0 or j % w in (0, w - 1) or j // w in (0, h - 1):
                            continue
                        amount = .5 * (result[i] - result[j]) * strength * min(4., math.sqrt(accumulation[i] * sx * sy * rainfall / 10000))
                    if j >= 0:
                        # Both source and recipient respect a cumulative displacement
                        # budget; every transfer conserves the summed heightfield.
                        amount = max(0., min(amount, result[i] + delta[i] - (before[i] - budget),
                                             before[j] + budget - (result[j] + delta[j])))
                        delta[i] -= amount
                        delta[j] += amount
            for i in range(len(result)):
                result[i] += delta[i]
        stats['techniques'][method] = {'iterations': iterations, 'strength': strength,
            'max_delta_meters': budget, 'measured_max_delta_meters': max(abs(a - b) for a, b in zip(result, before))}
    if 'noise' in settings:
        options = object_settings(settings['noise'], 'noise', ('amplitude_meters', 'wavelength_meters', 'seed'))
        amplitude = number(options, 'amplitude_meters', .25, 0, 20)
        wavelength = number(options, 'wavelength_meters', 64, .01, 1000000)
        seed = number(options, 'seed', 1, 0, 4294967295, integer=True)
        if wavelength < 2 * max(sx, sy):
            raise ValueError('noise.wavelength_meters must cover at least two processing grid intervals; raise processing.resolution or the wavelength.')
        for y in range(1, h - 1):
            for x in range(1, w - 1):
                result[y * w + x] += amplitude * (2 * value_noise(x * sx / wavelength, y * sy / wavelength, seed) - 1)
        stats['techniques']['noise'] = {'amplitude_meters': amplitude, 'wavelength_meters': wavelength, 'seed': seed}
    delta = array('d', (a - b for a, b in zip(result, original)))
    # Interpolate corrections, not the coarse surface: retain source detail.
    processed = array('d', (values[y * width + x] + interpolate(delta, w, h, x * (w - 1) / (width - 1), y * (h - 1) / (height - 1))
                           for y in range(height) for x in range(width)))
    stats['measured_max_delta_meters'] = max(abs(a - b) for a, b in zip(processed, values))
    return processed, stats


def value_noise(x, y, seed):
    def hashed(a, b):
        v = (a * 374761393 + b * 668265263 + seed * 1274126177) & 0xffffffff
        v = ((v ^ (v >> 13)) * 1274126177) & 0xffffffff
        return (v ^ (v >> 16)) / 4294967295
    a, b = math.floor(x), math.floor(y)
    fx, fy = x - a, y - b
    fx, fy = fx * fx * (3 - 2 * fx), fy * fy * (3 - 2 * fy)
    return mix(mix(hashed(a, b), hashed(a + 1, b), fx), mix(hashed(a, b + 1), hashed(a + 1, b + 1), fx), fy)


def png_rgb(side, pixels):
    def chunk(tag, data):
        return struct.pack('>I', len(data)) + tag + data + struct.pack('>I', zlib.crc32(tag + data))
    rows = b''.join(b'\0' + pixels[y * side * 3:(y + 1) * side * 3] for y in range(side))
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', side, side, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(rows, 9)) + chunk(b'IEND', b'')


def texture_chain(side, pixels):
    files, paths, level = {}, [], 0
    while True:
        path = 'Terrain/Generated/albedo' + (f'-mip{level}' if level else '') + '.png'
        files[path] = png_rgb(side, pixels)
        paths.append(path)
        if side == 1:
            break
        smaller = bytearray()
        for y in range(0, side, 2):
            for x in range(0, side, 2):
                for c in range(3):
                    smaller.append(round(sum(pixels[((y + dy) * side + x + dx) * 3 + c] for dy in (0, 1) for dx in (0, 1)) / 4))
        pixels, side, level = smaller, side // 2, level + 1
    return files, {'file': paths[0], 'mips': paths[1:], 'color_space': 'srgb'}


def encode_forest(points):
    """Compile authoring metres into SKXY v1 float32 centimetres."""
    if not isinstance(points, list) or len(points) > 1000000:
        raise ValueError('Forest JSON must be an array of at most 1,000,000 {x, y} points.')
    output = bytearray(struct.pack('<4sII', b'SKXY', 1, len(points)))
    for i, point in enumerate(points):
        if not isinstance(point, dict) or set(point) != {'x', 'y'}:
            raise ValueError(f'Forest point {i + 1} must contain exactly x and y in world metres.')
        for name in ('x', 'y'):
            value = point[name]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or abs(value) > 3.4028234663852886e36 or not math.isfinite(value):
                raise ValueError(f'Forest point {i + 1}: {name} must fit a finite float32 coordinate in centimetres.')
        output.extend(struct.pack('<ff', point['x'] * 100, point['y'] * 100))
    return bytes(output)


def compile_forest(project, settings):
    settings = object_settings(settings, 'build.forest', ('file',))
    if __package__ == 'tools':
        from .custom_maps import safe_relative_path
    else:
        from custom_maps import safe_relative_path
    relative = safe_relative_path(settings.get('file'), 'build.forest.file')
    path = (project / relative).resolve(strict=True)
    if not path.is_relative_to(project) or path.suffix.lower() != '.json':
        raise ValueError('build.forest.file must be a JSON source inside the project.')
    if path.stat().st_size > 32 * 1024 * 1024:
        raise ValueError('Forest JSON exceeds 32 MiB.')
    def strict_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f'Duplicate forest JSON field: {key}.')
            result[key] = value
        return result
    def reject_constant(value):
        raise ValueError(f'Invalid forest JSON number: {value}.')
    points = json.loads(path.read_text(encoding='utf-8-sig'), object_pairs_hook=strict_object, parse_constant=reject_constant)
    return encode_forest(points), len(points)


def forest_script(source):
    """Embed the authored script without modifying it or requiring loader changes."""
    return ('''-- Generated by skieomod: automatic forest takes precedence over manual SKXY imports.
local original = (function()
''' + source + '''
end)()
local original_register = type(original) == "table" and original.register or original
local function register(api)
    local importer = api.load_forest_skxy
    local loaded = false
    api.load_forest_skxy = function(self, relative, options)
        if loaded then return end
        loaded = true
        return importer(self, "Vegetation/Generated/forest.skxy", options)
    end
    if type(original_register) == "function" then original_register(api) end
    api:on("map.ready", function() api:load_forest_skxy() end)
end
if type(original) == "table" then
    original.register = register
    return original
end
if original ~= nil and type(original) ~= "function" then error("Invalid map script return value") end
return register
''').encode('utf-8')


def attach_forest(project, portable, files):
    """Register the binary forest while preserving the authored entry point."""
    original = portable.get('script')
    original_source = ''
    if original:
        entry = PurePosixPath(original['entry'])
        wrapper = str(entry.parent / 'skieomod-generated-vegetation.lua')
        if original['entry'] == wrapper:
            raise ValueError('The generated vegetation script cannot be the authored script.entry.')
        path = (project / entry).resolve(strict=True)
        if not path.is_relative_to(project):
            raise ValueError('The authored script must stay inside the project.')
        original_source = path.read_text(encoding='utf-8-sig')
    else:
        wrapper = 'Scripts/skieomod-generated-vegetation.lua'
    files[wrapper] = forest_script(original_source)
    script = copy.deepcopy(original or {'language': 'lua', 'api': '1.0', 'permissions': []})
    script['entry'] = wrapper
    permissions = script.setdefault('permissions', [])
    if 'gameplay' not in permissions and 'skieo.unrestricted' not in permissions:
        permissions.append('gameplay')
    portable['script'] = script
    assets = portable['content'].setdefault('assets', [])
    if 'Vegetation/Generated/forest.skxy' not in assets:
        assets.append('Vegetation/Generated/forest.skxy')


def vegetation(project, manifest, terrain_bytes, settings):
    settings = object_settings(settings, 'build.vegetation', ('biome', 'trees', 'ground_cover', 'analysis_resolution'))
    biome = object_settings(settings.get('biome', {}), 'biome',
        ('tree_line_meters', 'alpine_line_meters', 'temperature_sea_level_celsius', 'lapse_rate_celsius_per_km', 'moisture', 'wind_strength', 'wind_direction_degrees'))
    tree_line = number(biome, 'tree_line_meters', 2000, -1000, 20000)
    alpine_line = number(biome, 'alpine_line_meters', 2600, -1000, 20000)
    if alpine_line <= tree_line:
        raise ValueError('biome.alpine_line_meters must exceed tree_line_meters.')
    temperature = number(biome, 'temperature_sea_level_celsius', 15, -50, 60)
    lapse = number(biome, 'lapse_rate_celsius_per_km', 6.5, 0, 15)
    moisture = number(biome, 'moisture', .6, 0, 1)
    wind = number(biome, 'wind_strength', .3, 0, 1)
    direction = math.radians(number(biome, 'wind_direction_degrees', 270, 0, 360))
    trees = object_settings(settings.get('trees', {}), 'trees',
        ('enabled', 'seed', 'density_per_hectare', 'min_spacing_meters', 'max_trees', 'max_slope_degrees', 'min_elevation_meters', 'tree_line_fade_meters', 'patch_size_meters', 'patchiness', 'exclude'))
    ground = object_settings(settings.get('ground_cover', {}), 'ground_cover',
        ('enabled', 'texture_size', 'max_slope_degrees', 'grass_color', 'rock_color'))
    trees_enabled, ground_enabled = flag(trees, 'enabled'), flag(ground, 'enabled')
    seed = number(trees, 'seed', 1, 0, 4294967295, integer=True)
    density = number(trees, 'density_per_hectare', 100, 0, 2000)
    min_spacing = number(trees, 'min_spacing_meters', 4, .1, 1000)
    max_trees = number(trees, 'max_trees', 100000, 0, 1000000, integer=True)
    max_slope = number(trees, 'max_slope_degrees', 32, .1, 89)
    min_elevation = number(trees, 'min_elevation_meters', -1000, -1000, 20000)
    fade = number(trees, 'tree_line_fade_meters', 150, .01, 5000)
    patch_size = number(trees, 'patch_size_meters', 160, .1, 1000000)
    patchiness = number(trees, 'patchiness', .6, 0, 1)
    excludes = trees.get('exclude', [])
    if not isinstance(excludes, list) or len(excludes) > 1000:
        raise ValueError('trees.exclude must contain at most 1000 [west, north, east, south] rectangles in world metres.')
    for rectangle in excludes:
        if (not isinstance(rectangle, list) or len(rectangle) != 4
                or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in rectangle)
                or rectangle[0] >= rectangle[2] or rectangle[1] >= rectangle[3]):
            raise ValueError('Each tree exclusion needs finite [west, north, east, south] with west < east and north < south.')
    texture_size = number(ground, 'texture_size', 256, 16, 512, integer=True)
    if texture_size & (texture_size - 1):
        raise ValueError('ground_cover.texture_size must be a power of two from 16 to 512.')
    grass_slope = number(ground, 'max_slope_degrees', 45, .1, 89)
    colors = []
    for name, default in [('grass_color', [77, 101, 49]), ('rock_color', [125, 119, 107])]:
        color = ground.get(name, default)
        if not isinstance(color, list) or len(color) != 3 or any(isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= 255 for v in color):
            raise ValueError(f'{name} must contain three integer sRGB channels from 0 to 255.')
        colors.append(color)
    resolution = number(settings, 'analysis_resolution', 513, 33, 1025, integer=True)
    portable = copy.deepcopy(manifest)
    source = portable['terrain']['source']
    width, height = source['vertices']
    samples = array('H'); samples.frombytes(terrain_bytes)
    import sys
    if sys.byteorder != 'little':
        samples.byteswap()
    scale, offset, spacing = source['height_scale_meters'], source['height_offset_meters'], source['spacing_meters']
    values = array('d', (v * scale + offset for v in samples))
    if source['row_order'] == 'south_to_north':
        values = array('d', (v for y in range(height - 1, -1, -1) for v in values[y * width:(y + 1) * width]))
    analysis, w, h, sx, sy = grid(values, width, height, spacing, resolution)
    _, _, accumulation = drainage(analysis, w, h, sx, sy)
    wetness = array('d', (clamp(math.log1p(v * sx * sy / 10000) / math.log(101)) for v in accumulation))
    size_x, size_y = portable['terrain']['size_meters']
    def habitat(east, south):
        x, y = east / spacing, south / spacing
        elevation = interpolate(values, width, height, x, y)
        x0, x1 = max(0., x - 1), min(width - 1., x + 1)
        y0, y1 = max(0., y - 1), min(height - 1., y + 1)
        dx = (interpolate(values, width, height, x1, y) - interpolate(values, width, height, x0, y)) / ((x1 - x0) * spacing)
        dy = (interpolate(values, width, height, x, y1) - interpolate(values, width, height, x, y0)) / ((y1 - y0) * spacing)
        slope = math.degrees(math.atan(math.hypot(dx, dy)))
        # Compass azimuth is where wind comes FROM: 0 north, 90 east.
        exposure = max(0., -dx * math.sin(direction) + dy * math.cos(direction)) / math.sqrt(1 + dx * dx + dy * dy)
        dampness = clamp(moisture + .3 * interpolate(wetness, w, h, east / sx, south / sy))
        warmth = temperature - lapse * elevation / 1000
        return elevation, slope, dampness, warmth, 1 - wind * exposure
    files, forest, eligible = {}, [], 0
    if trees_enabled:
        cell = math.sqrt(10000 / density) if density else max(size_x, size_y) * 2
        nx, ny = math.ceil(size_x / cell), math.ceil(size_y / cell)
        if nx * ny > 2000000:
            raise ValueError('Tree bake exceeds 2,000,000 candidates; reduce density_per_hectare or split the map.')
        rng, reservoir_rng, occupied = random.Random(seed), random.Random(seed ^ 0x9e3779b9), {}
        for row in range(ny) if density and max_trees else ():
            for column in range(nx):
                east, south = (column + .1 + .8 * rng.random()) * cell, (row + .1 + .8 * rng.random()) * cell
                if east >= size_x or south >= size_y:
                    continue
                world_x, world_y = round(east - size_x / 2, 3), round(south - size_y / 2, 3)
                # Evaluate the exact float32 coordinates the runtime will read.
                world_x, world_y = (v / 100 for v in struct.unpack('<ff', struct.pack('<ff', world_x * 100, world_y * 100)))
                if any(a <= world_x <= c and b <= world_y <= d for a, b, c, d in excludes):
                    continue
                elevation, slope, damp, warm, shelter = habitat(world_x + size_x / 2, world_y + size_y / 2)
                if elevation < min_elevation or elevation >= tree_line or slope >= max_slope:
                    continue
                probability = (clamp((tree_line - elevation) / fade) * clamp(1 - (slope / max_slope) ** 2)
                    * damp * clamp((warm + 5) / 10) * shelter
                    * mix(1., value_noise(east / patch_size, south / patch_size, seed), patchiness))
                if rng.random() >= probability:
                    continue
                bx, by = math.floor(world_x / min_spacing), math.floor(world_y / min_spacing)
                if any((world_x - px) ** 2 + (world_y - py) ** 2 < min_spacing ** 2
                    for oy in (-1, 0, 1) for ox in (-1, 0, 1) for px, py in occupied.get((bx + ox, by + oy), ())):
                    continue
                occupied.setdefault((bx, by), []).append((world_x, world_y))
                eligible += 1
                point = {'x': world_x, 'y': world_y}
                if len(forest) < max_trees:
                    forest.append(point)
                else:
                    replacement = reservoir_rng.randrange(eligible)
                    if replacement < max_trees:
                        forest[replacement] = point
        forest.sort(key=lambda p: (p['y'], p['x']))
        files['Vegetation/Generated/forest.skxy'] = encode_forest(forest)
    if ground_enabled:
        pixels, cover = bytearray(), bytearray()
        extent = max(size_x, size_y)
        for y in range(texture_size):
            for x in range(texture_size):
                east, south = min(size_x, (x + .5) * extent / texture_size), min(size_y, (y + .5) * extent / texture_size)
                elevation, slope, damp, warm, shelter = habitat(east, south)
                growth = clamp((alpine_line - elevation) / 200) * clamp(1 - (slope / grass_slope) ** 2) * damp * clamp((warm + 8) / 12) * shelter
                variation = .93 + .14 * value_noise(east / 35, south / 35, seed + 1)
                pixels.extend(round(clamp(mix(colors[1][c], colors[0][c], growth) * variation, 0, 255)) for c in range(3))
                cover.extend([round(growth * 255)] * 3)
        textures, definition = texture_chain(texture_size, pixels)
        files.update(textures)
        files['Vegetation/Generated/ground-cover.png'] = png_rgb(texture_size, cover)
        portable['terrain'].setdefault('textures', {})['albedo'] = definition
        # Existing loader UVs use one physical length for both axes. Pad the
        # shorter extent and use the same length to map rectangular terrain.
        runtime = portable['terrain'].setdefault('runtime', {})
        runtime.update(uv_tile_meters=extent, material='/Game/Materials/M_Prop_albtex.M_Prop_albtex')
        runtime['material_color'] = [1, 1, 1, 1]
        runtime.setdefault('texture_parameters', {})['albedo'] = 'Albedo'
    report = {'algorithm': 'skieomod-vegetation-1', 'analysis_vertices': [w, h],
        'tree_count': len(forest), 'eligible_tree_count': eligible, 'tree_limit_reached': eligible > max_trees,
        'ground_cover': ground_enabled, 'settings': settings}
    return portable, files, report
