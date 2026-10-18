"""Project templates and reproducible developer builds, without a repository upload."""
from __future__ import annotations
from array import array
import copy
import contextlib
import hashlib
import io
import json
import math
from pathlib import Path
import re
import struct
import sys
import shutil
import tempfile
import zlib

if __package__ == 'tools':
    from .custom_packages import ManifestError, MANIFESTS, pack_package, inspect_package, validate_mod
    from .custom_maps import validate_manifest, referenced_paths
    from .skieo_templates import MAP_SCRIPT, MAP_FOREST_SCRIPT, UE4SS_SCRIPT, documentation
    from . import skieo_heightmap as heightmaps, skieo_authoring as authoring
else:
    from custom_packages import ManifestError, MANIFESTS, pack_package, inspect_package, validate_mod
    from custom_maps import validate_manifest, referenced_paths
    from skieo_templates import MAP_SCRIPT, MAP_FOREST_SCRIPT, UE4SS_SCRIPT, documentation
    import skieo_heightmap as heightmaps
    import skieo_authoring as authoring


def project_manifest(path):
    path = Path(path).resolve()
    if path.is_file():
        if path.name not in MANIFESTS.values():
            raise ManifestError('Expected custom-map.json or custom-mod.json')
        return path
    choices = [path / name for name in MANIFESTS.values() if (path / name).is_file()]
    if len(choices) != 1:
        raise ManifestError('No unique project manifest. Run skieomod create map, create mod or create mapmod in an empty directory.')
    return choices[0]


MAX_TEMPLATE_SAMPLES = 16 * 1024 * 1024
TARGET_MESH_CELLS = 512 * 512


def starter_terrain(size_meters=None, spacing_meters=None):
    """Size and source resolution are independent of the native game cache."""
    size = list(size_meters) if size_meters is not None else [1024, 1024]
    spacing = spacing_meters if spacing_meters is not None else 16
    if (len(size) != 2 or any(isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or value <= 0 for value in [*size, spacing])):
        raise ManifestError('Map size and spacing must be finite positive numbers in metres')
    ratios = [value / spacing for value in size]
    if any(not math.isfinite(value) or value > 16383 for value in ratios):
        raise ManifestError('Source grids support at most 16384 vertices per axis; increase --spacing')
    cells = [round(value) for value in ratios]
    if any(value < 1 for value in cells) or any(
            abs(size[axis] - cells[axis] * spacing) > 1e-6 for axis in range(2)):
        raise ManifestError('Each map dimension must be an integer multiple of --spacing')
    width, height = [value + 1 for value in cells]
    if width * height > MAX_TEMPLATE_SAMPLES:
        raise ManifestError('Starter heightmap exceeds 32 MiB; choose a larger --spacing')
    ripple = [12 * math.cos(x * 2 * math.pi / (width - 1)) for x in range(width)]
    heights = array('H')
    for y in range(height):
        base = 250 - y * 192 / (height - 1)
        heights.extend(round((base + value) * 100) for value in ripple)
    low, high = min(heights) / 100, max(heights) / 100
    preview_columns = [round(index * (width - 1) / 8) for index in range(9)]
    preview_rows = [round(index * (height - 1) / 8) for index in range(9)]
    terrain = {
        'size_meters': size, 'elevation_meters': [low, high],
        'origin_centimeters': [-size[0] * 50, -size[1] * 50, 0],
        'source': {'file': 'Terrain/heightmap.r16', 'format': 'r16le', 'vertices': [width, height],
                   'spacing_meters': spacing, 'row_order': 'north_to_south',
                   'height_scale_meters': .01, 'height_offset_meters': 0},
        # Keep the first test session modest even for a large starter map.
        'runtime': {'sample_step': max(1, math.ceil(math.sqrt(cells[0] * cells[1] / TARGET_MESH_CELLS))),
                    'tile_quads': 32, 'snow_offset_centimeters': 30},
        'preview': {'samples': [[round((heights[y * width + x] / 100 - low) / (high - low), 4)
                                for x in preview_columns] for y in preview_rows]},
    }
    if sys.byteorder != 'little':
        heights.byteswap()
    return terrain, heights.tobytes()


def create(kind, directory, name=None, identifier=None, author='Your name', *, size_meters=None, spacing_meters=None, blank=False):
    if kind not in {'map', 'mod', 'mapmod'}:
        raise ManifestError('Unknown template: choose map, mod or mapmod')
    if kind != 'map' and (size_meters is not None or spacing_meters is not None):
        raise ManifestError('--size and --spacing only apply to create map')
    package_kind = 'map' if kind == 'map' else 'mod'
    directory = Path(directory).resolve()
    name = name or directory.name or ('My map' if kind == 'map' else 'My mod')
    slug = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-') or kind
    identifier = identifier or 'local.' + slug
    metadata = {'name': name, 'version': '0.1.0', 'authors': [author],
                'description': 'A new Ski-E-O! creation.', 'language': 'en', 'license': 'MIT'}
    manifest = {'format': {'name': 'skieo-' + package_kind, 'version': '1.4.0' if kind == 'map' else '1.0.0'},
                'id': identifier, 'metadata': metadata, 'dependencies': [],
                'script': {'language': 'lua', 'api': '1.0', 'entry': 'Scripts/main.lua', 'permissions': ['gameplay']}}
    files = {'Scripts/main.lua': MAP_SCRIPT.encode('utf-8'),
             '.gitignore': b'# Generated archives and local preview projects\nbin/\nobj/\n# Incomplete builds\n*.part\n'}
    if kind == 'map':
        manifest['terrain'], source_bytes = starter_terrain(size_meters, spacing_meters)
        manifest['content'] = {'assets': [] if blank else ['Vegetation/Generated/forest.skxy']}
        manifest['build'] = {} if blank else {'forest': {'file': 'Vegetation/forest.json'}}
        files['Terrain/heightmap.r16'] = source_bytes
        files['Scripts/main.lua'] = (MAP_SCRIPT if blank else MAP_FOREST_SCRIPT).encode('utf-8')
        size_x, size_y = manifest['terrain']['size_meters']
        trees = [{'x': round(x * size_x, 2), 'y': round(y * size_y, 2)}
                 for x, y in [(-.1, -.05), (0, 0), (.1, .05)]]
        if not blank:
            files['Vegetation/forest.json'] = (json.dumps(trees, indent=2) + '\n').encode('utf-8')
    elif kind == 'mapmod':
        manifest.update(runtime='map-api', files=['Scripts/main.lua'])
    else:
        manifest.pop('script')
        manifest.update(runtime='ue4ss', files=['Scripts/main.lua'],
                        install_directory='SkiEO-' + re.sub('[^A-Za-z0-9_-]', '-', identifier))
        files['Scripts/main.lua'] = UE4SS_SCRIPT.encode('utf-8')
    files.update(documentation(kind, manifest))
    files['workshop.json'] = (json.dumps({'version': 1, 'app_id': '4493130',
        'published_file_id': '0', 'visibility': 'private', 'preview_file': 'preview.png'}, indent=2) + '\n').encode()
    # A valid generated preview keeps every template publishable. Creators can
    # replace it with their own screenshot without adding it to game content.
    def chunk(tag, data):
        return struct.pack('>I', len(data)) + tag + data + struct.pack('>I', zlib.crc32(tag + data))
    pixels = b''.join(b'\0' + bytes([240 - y, 248 - y // 2, 255 - y // 3]) * 128 for y in range(128))
    files['preview.png'] = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 128, 128, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(pixels)) + chunk(b'IEND', b'')
    files[MANIFESTS[package_kind]] = (json.dumps(manifest, ensure_ascii=False, indent=2) + '\n').encode()
    # Validate the entire template before touching the user's project directory.
    import tempfile
    with tempfile.TemporaryDirectory(prefix='skieomod-template-') as temporary:
        stage = Path(temporary)
        for relative, content in files.items():
            target = stage / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        if kind == 'map':
            with contextlib.redirect_stdout(io.StringIO()):
                build(stage, stage / 'test.zip')
            # Include the validated starter binary; subsequent builds always
            # compile the editable JSON again, never reuse this snapshot.
            if not blank:
                files['Vegetation/Generated/forest.skxy'] = (stage / 'Vegetation/Generated/forest.skxy').read_bytes()
        else:
            pack_package(stage / MANIFESTS[package_kind], stage / 'test.zip')
    collisions = [relative for relative in files if (directory / relative).exists()]
    if collisions:
        raise ManifestError('Refusing to overwrite existing project files: ' + ', '.join(collisions))
    if any((directory / candidate).exists() for candidate in MANIFESTS.values()):
        raise ManifestError('This directory already contains a map/mod project')
    for relative in files:
        if not (directory / relative).resolve().is_relative_to(directory):
            raise ManifestError('Template paths cannot traverse a symbolic link outside the project')
    for relative, content in files.items():
        target = directory / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('xb') as stream:
            stream.write(content)
    return directory / MANIFESTS[package_kind]


def preview_map(project, mod_release):
    """A local map-api mod needs a map session; scaffold its private test harness."""
    directory = project_manifest(project).parent / 'obj' / 'mapmod-preview'
    identifier = 'local.preview-' + mod_release['id'].replace('.', '-')
    if not (directory / MANIFESTS['map']).exists():
        create('map', directory, 'Preview: ' + mod_release['manifest']['metadata']['name'], identifier)
    source = directory / MANIFESTS['map']
    manifest = json.loads(source.read_text(encoding='utf-8'))
    manifest['dependencies'] = [{'id': mod_release['id'], 'version': '=' + mod_release['version']}]
    source.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return build(directory)


def build(path='.', output=None, *, save_build_metadata=True):
    source = project_manifest(path)
    manifest = json.loads(source.read_text(encoding='utf-8'))
    kind = 'map' if source.name == MANIFESTS['map'] else 'mod'
    original_manifest = manifest
    bake_report = {}
    manifest, terrain_bytes = heightmaps.prepare_map(source.parent, manifest, report=bake_report)
    working = dict(original_manifest)
    if kind == 'map':
        # Persist derived physical terrain data. Vegetation rendering overrides
        # live in the package so disabling a bake restores authored settings.
        working['terrain'] = copy.deepcopy(manifest['terrain'])
    generated = {}
    forest_settings = original_manifest.get('build', {}).get('forest')
    if forest_settings is not None:
        heightmaps.bake.object_settings(forest_settings, 'build.forest', ('file',))
        if not isinstance(forest_settings.get('file'), str):
            raise ManifestError('build.forest.file must be a project-relative JSON path')
    if 'vegetation' in original_manifest.get('build', {}):
        manifest, vegetation_files, vegetation_report = heightmaps.bake.vegetation(
            source.parent, manifest, terrain_bytes, original_manifest['build']['vegetation'])
        generated.update(vegetation_files)
        bake_report['vegetation'] = vegetation_report
    if forest_settings is not None and 'Vegetation/Generated/forest.skxy' not in generated:
        if kind != 'map':
            raise ManifestError('build.forest applies to map projects')
        forest_bytes, count = heightmaps.bake.compile_forest(source.parent, forest_settings)
        generated['Vegetation/Generated/forest.skxy'] = forest_bytes
        bake_report['forest'] = {'source': forest_settings['file'], 'tree_count': count}
    if (kind == 'map' and 'Vegetation/Generated/forest.skxy' in manifest['content'].get('assets', [])
            and 'Vegetation/Generated/forest.skxy' not in generated):
        # Reserved output must never silently reuse a previous automatic bake
        # when generation is disabled and no manual source is configured.
        generated['Vegetation/Generated/forest.skxy'] = heightmaps.bake.encode_forest([])
        bake_report['forest'] = {'tree_count': 0, 'source': None}
    if kind == 'map' and generated:
        manifest = copy.deepcopy(manifest)
        manifest.pop('build', None)
        if forest_settings:
            manifest['content']['assets'] = [p for p in manifest['content'].get('assets', []) if p != forest_settings['file']]
        if 'Vegetation/Generated/forest.skxy' in generated:
            heightmaps.bake.attach_forest(source.parent, manifest, generated)
    authoring_inputs = []
    if any(key in original_manifest.get('build', {}) for key in ('triggers', 'resources', 'objects', 'scene')):
        if kind != 'map':
            raise ManifestError('Trigger/resource/object authoring currently applies to map projects')
        manifest, authoring_inputs = authoring.prepare(source.parent, manifest, generated,
            source_build=original_manifest.get('build', {}))
    if bake_report:
        bake_report.update(algorithm='skieomod-bake-1', elevation_meters=manifest['terrain']['elevation_meters'])
        if terrain_bytes is not None:
            bake_report['source_sha256'] = hashlib.sha256(
                (source.parent / original_manifest['build']['heightmap']['file']).read_bytes()).hexdigest()
        generated['Terrain/Generated/build-report.json'] = (json.dumps(bake_report, indent=2) + '\n').encode('utf-8')
        assets = manifest['content'].setdefault('assets', [])
        for relative in ['Terrain/Generated/build-report.json', 'Vegetation/Generated/ground-cover.png']:
            if relative in generated and relative not in assets:
                assets.append(relative)
    extension = '.skieomap' if kind == 'map' else '.skieomod'
    # Validate identifiers before using them in output paths.
    (validate_manifest if kind == 'map' else validate_mod)(manifest)
    target = Path(output).resolve() if output else source.parent / 'bin' / (manifest['id'] + '-' + manifest['metadata']['version'] + extension)
    inputs = referenced_paths(original_manifest) if kind == 'map' else manifest['files']
    inputs.extend(authoring_inputs)
    build_source = original_manifest.get('build', {}).get('heightmap', {}).get('file')
    if build_source:
        inputs.append(build_source)
    if forest_settings is not None:
        inputs.append(forest_settings['file'])
    if build_source and build_source in generated:
        raise ManifestError('The original heightmap cannot use a generated output path')
    if target == source or target in [source.parent / f for f in inputs]:
        raise ManifestError('Build output cannot overwrite project source')
    if target in [source.parent / relative for relative in generated]:
        raise ManifestError('Build output cannot overwrite generated assets')
    target.parent.mkdir(parents=True, exist_ok=True)
    stage = target.with_name(target.name + '.part')
    try:
        if terrain_bytes is None and not generated:
            pack_package(source, stage)
        else:
            with tempfile.TemporaryDirectory(prefix='skieomod-terrain-') as temporary:
                prepared = Path(temporary)
                (prepared / MANIFESTS['map']).write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
                for relative in referenced_paths(manifest):
                    destination = prepared / relative
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    if terrain_bytes is not None and str(relative) == manifest['terrain']['source']['file']:
                        destination.write_bytes(terrain_bytes)
                    elif str(relative) in generated:
                        destination.write_bytes(generated[str(relative)])
                    else:
                        origin = (source.parent / relative).resolve(strict=True)
                        if not origin.is_relative_to(source.parent):
                            raise ManifestError('Source assets must stay inside the project')
                        shutil.copyfile(origin, destination)
                pack_package(prepared / MANIFESTS['map'], stage)
        inspect_package(stage, kind)
        with heightmaps.save_generated(source.parent, source, working, terrain_bytes if save_build_metadata else None,
                                      generated if save_build_metadata else None):
            stage.replace(target)
    finally:
        stage.unlink(missing_ok=True)
    release = {'id': manifest['id'], 'kind': kind, 'version': manifest['metadata']['version'],
               'manifest': manifest, 'sha256': hashlib.sha256(target.read_bytes()).hexdigest(),
               'size': target.stat().st_size}
    if terrain_bytes is not None:
        terrain = manifest['terrain']
        print('Terrain: ' + ' x '.join(map(str, terrain['source']['vertices'])) + ' samples; ' +
              ' x '.join(f'{value:g}' for value in terrain['size_meters']) + ' m; ' +
              ' to '.join(f'{value:g}' for value in terrain['elevation_meters']) + ' m elevation; portable R16LE')
        for assumption in bake_report.get('heightmap', {}).get('assumptions', []):
            print('Heightmap: ' + assumption)
        if 'processing' in bake_report:
            print(f"Terrain processing: maximum change {bake_report['processing']['measured_max_delta_meters']:.3f} m")
        if 'vegetation' in bake_report:
            vegetation_report = bake_report['vegetation']
            print(f"Vegetation: {vegetation_report['tree_count']} trees; ground cover {'baked' if vegetation_report['ground_cover'] else 'disabled'}")
            if vegetation_report['tree_limit_reached']:
                print('Tree count limited by max_trees; a seeded, uniform subset was retained.')
    return target, release
