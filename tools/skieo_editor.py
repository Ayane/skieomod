"""Source-project model for the native skieomod map editor (no GUI imports)."""
from __future__ import annotations

from array import array
import copy
import json
import math
import os
from pathlib import Path
import random
import re
import struct
import sys
import tempfile
import secrets

if __package__ == 'tools':
    from . import skieo_project as projects, skieo_heightmap as heightmaps, skieo_bake as bake, skieo_authoring as authoring
    from .custom_packages import ManifestError
    from .custom_maps import safe_relative_path, validate_manifest
else:
    import skieo_project as projects
    import skieo_heightmap as heightmaps
    import skieo_bake as bake
    import skieo_authoring as authoring
    from custom_packages import ManifestError
    from custom_maps import safe_relative_path, validate_manifest


def decode_terrain(terrain, data):
    samples = array('H')
    samples.frombytes(data)
    if sys.byteorder != 'little':
        samples.byteswap()
    source = terrain['source']
    width, height = source['vertices']
    if len(samples) != width * height:
        raise ValueError('Terrain byte count does not match its sample dimensions.')
    values = array('d', (sample * source['height_scale_meters'] + source['height_offset_meters'] for sample in samples))
    if source.get('row_order', 'north_to_south') == 'south_to_north':
        values = array('d', (v for row in range(height - 1, -1, -1) for v in values[row * width:(row + 1) * width]))
    return width, height, source['spacing_meters'], values


def inspect_source(manifest, file, settings):
    """Use the builder's decoder and unit rules, without processing or writes."""
    file = Path(file).resolve(strict=True)
    if file.stat().st_size > 64 * 1024 * 1024:
        raise ValueError('Heightmaps must be at most 64 MiB.')
    data = file.read_bytes()
    source = copy.deepcopy(manifest)
    settings = copy.deepcopy(settings)
    settings.pop('processing', None)
    settings['file'] = 'input' + file.suffix.lower()
    source['build'] = {'heightmap': settings}
    report = {}
    with tempfile.TemporaryDirectory(prefix='skieomod-editor-preview-') as temporary:
        folder = Path(temporary)
        (folder / settings['file']).write_bytes(data)
        portable, raw = heightmaps.prepare_map(folder, source, report=report)
    return portable['terrain'], raw, data, report['heightmap']['assumptions']


class EditorProject:
    """An editable document; save source files, and let build derive runtime data."""
    @classmethod
    def new(cls):
        workspace = tempfile.TemporaryDirectory(prefix='skieomod-unsaved-')
        try:
            projects.create('map', workspace.name, 'Untitled map', 'local.map-' + secrets.token_hex(6),
                            os.environ.get('USERNAME', os.environ.get('USER', 'Map creator')), blank=True)
            document = cls(workspace.name)
            document.workspace = workspace
            document.has_folder = False
            document.built = None
            return document
        except Exception:
            workspace.cleanup()
            raise

    def __init__(self, path):
        self.workspace = None
        self.has_folder = True
        self.path = projects.project_manifest(path)
        if self.path.name != 'custom-map.json':
            raise ValueError('The map editor opens map projects containing custom-map.json.')
        self.folder = self.path.parent
        self.manifest = json.loads(self.path.read_text(encoding='utf-8-sig'))
        self.expected = {self.path.name: self.path.read_bytes()}
        self.pending = {}
        self.dirty = False
        self.terrain_dirty = False
        self.forest_dirty = False
        current = self.manifest.get('build', {}).get('heightmap', {}).get('file', '')
        self.edited_source = current if current.startswith('Terrain/Editor/heightmap') and current.endswith('.r16') else None
        self.history, self.future = [], []
        self._stroke = None
        self.assumptions = []
        self.built = None
        self.built_trees = []
        self._load_terrain()
        self.trees = []
        forest = self.manifest.get('build', {}).get('forest')
        if forest:
            file = self.source_path(forest['file'])
            compiled, _ = bake.compile_forest(self.folder, forest)
            self.trees = self.decode_forest(compiled)
            self.remember(forest['file'])
        script = self.manifest.get('script', {}).get('entry')
        self.script_path = script
        self.script = self.source_path(script).read_text(encoding='utf-8') if script else ''
        if script:
            self.remember(script)
        self.triggers = self.read_authoring('triggers', {'version': 1, 'triggers': []})
        self.resources = self.read_authoring('resources', {'version': 1, 'assets': []})
        object_source = self.manifest.get('build', {}).get('objects', {}).get('file')
        if object_source:
            self.remember(object_source)
            self.object_edits = authoring.parse_edits(self.source_path(object_source).read_bytes(),
                {a['id']: a for a in self.resources['assets']})
        else:
            self.object_edits = []
        self.scene = self.read_authoring('scene', {'version': 1, 'objects': []})
        self.refresh_built()

    def read_authoring(self, key, default):
        relative = self.manifest.get('build', {}).get(key, {}).get('file')
        if not relative: return copy.deepcopy(default)
        self.remember(relative)
        return authoring.read_json(self.folder, relative)

    def queue_authoring(self, key, document):
        defaults = {'triggers': 'Triggers/triggers.json', 'resources': 'Resources/assets.json', 'objects': 'Objects/overrides.csv', 'scene': 'Scene/objects.json'}
        setting = self.manifest.setdefault('build', {}).get(key)
        if setting is None:
            relative = self.unique_file(defaults[key])
            self.manifest['build'][key] = {'file': relative}
        else:
            relative = setting['file']
        self.remember(relative)
        self.pending[relative] = authoring.csv_bytes(document) if key == 'objects' else (json.dumps(document, ensure_ascii=False, allow_nan=False, indent=2) + '\n').encode('utf-8')
        setattr(self, {'objects': 'object_edits'}.get(key, key), copy.deepcopy(document))
        self.dirty = True

    def change_scene(self, document):
        stub = copy.deepcopy(self.manifest)
        stub['terrain']['source']['vertices'] = [self.width, self.height]
        stub['terrain']['source']['spacing_meters'] = self.spacing
        authoring.compile_scene(document, stub)
        if document == self.scene: return
        ids={item['id'] for item in document['objects']}
        edits=[edit for edit in self.object_edits if not edit.get('instance') or edit['instance'] in ids]
        self.history.append({'kind': 'scene', 'before': copy.deepcopy(self.scene), 'after': copy.deepcopy(document),
                             'edits_before': copy.deepcopy(self.object_edits), 'edits_after': copy.deepcopy(edits)})
        self.history = self.history[-40:];self.future.clear()
        self.queue_authoring('scene', document)
        if edits!=self.object_edits: self.queue_authoring('objects',edits)

    def change_instance_property(self, identifier, field, kind, value, default):
        item=next(item for item in self.scene['objects'] if item['id']==identifier)
        edits=[edit for edit in self.object_edits if (edit['object'],edit.get('instance'),edit['field'])!=(item['class'],identifier,field)]
        if value!=default: edits.append({'object':item['class'],'instance':identifier,'field':field,'type':kind,'value':value})
        authoring.parse_edits(authoring.csv_bytes(edits),{asset['id']:asset for asset in self.resources['assets']})
        if edits==self.object_edits: return
        self.history.append({'kind':'object_edits','before':copy.deepcopy(self.object_edits),'after':copy.deepcopy(edits)})
        self.history=self.history[-40:];self.future.clear();self.queue_authoring('objects',edits)

    def scene_default_name(self, item):
        if __package__ == 'tools':
            from .skieo_scene import DEFAULT_NAMES
        else:
            from skieo_scene import DEFAULT_NAMES
        name=DEFAULT_NAMES.get(item['class'],item['kind'].capitalize())
        relative='Objects/game-defaults.json'
        try:
            data=self.pending.get(relative) or (self.folder/relative).read_bytes()
            for obj in json.loads(data).get('objects',[]):
                if obj['class']==item['class']:
                    name=obj.get('fields',{}).get('DisplayName',{}).get('default') or name
        except (OSError,ValueError,KeyError): pass
        for edit in self.object_edits:
            if edit['object']==item['class'] and not edit.get('instance') and edit['field'] in ('DisplayName','InstanceName') and edit['value']:
                name=edit['value']
        return name

    def scene_display_name(self, item):
        if __package__ == 'tools':
            from .skieo_scene import DEFAULT_NAMES
        else:
            from skieo_scene import DEFAULT_NAMES
        name=item.get('name','')
        return self.scene_default_name(item) if not name or name==DEFAULT_NAMES.get(item['class']) else name

    def import_resource(self, file, identifier, kind, **options):
        path = Path(file).resolve(strict=True)
        if path.stat().st_size > 32 * 1024 * 1024:
            raise ValueError('Resource files must be at most 32 MiB')
        if not re.fullmatch(r'[a-z0-9][a-z0-9._-]{0,79}', identifier):
            raise ValueError('Use a resource ID with lowercase letters, numbers, dots or hyphens')
        if any(a['id'] == identifier for a in self.resources['assets']):
            raise ValueError('This resource ID already exists')
        data = path.read_bytes()
        if kind == 'model': authoring.parse_obj(data, options.get('units', 'meters'), options.get('up_axis', 'z'))
        relative = self.unique_file('Resources/Files/' + path.name)
        self.remember(relative)
        self.pending[relative] = data
        draft = copy.deepcopy(self.resources)
        draft['assets'].append({'id': identifier, 'kind': kind, 'file': relative, **options})
        self.queue_authoring('resources', draft)
        return draft['assets'][-1]

    def source_path(self, relative):
        relative = safe_relative_path(relative, 'editor source')
        path = self.folder / relative
        if path.is_symlink() or not path.resolve().is_relative_to(self.folder):
            raise ValueError('Editor source paths must stay inside the project.')
        return path

    def remember(self, relative):
        if relative not in self.expected:
            path = self.source_path(relative)
            self.expected[relative] = path.read_bytes() if path.exists() else None

    def _load_terrain(self):
        settings = self.manifest.get('build', {}).get('heightmap')
        if settings:
            terrain, raw, _, self.assumptions = inspect_source(self.manifest, self.source_path(settings['file']), settings)
            self.remember(settings['file'])
        else:
            terrain = self.manifest['terrain']
            source = terrain['source']
            # Reuse the same decoder for old projects with a generated source.
            options = {'vertices': source['vertices'], 'spacing_meters': source['spacing_meters'],
                       'height_scale_meters': source['height_scale_meters'], 'height_offset_meters': source['height_offset_meters'],
                       'row_order': source.get('row_order', 'north_to_south'), 'format': source.get('format', 'r16le')}
            terrain, raw, _, self.assumptions = inspect_source(self.manifest, self.source_path(source['file']), options)
            self.remember(source['file'])
        self.width, self.height, self.spacing, self.heights = decode_terrain(terrain, raw)

    @staticmethod
    def decode_forest(data):
        if len(data) < 12:
            raise ValueError('Truncated SKXY forest.')
        magic, version, count = struct.unpack_from('<4sII', data)
        if magic != b'SKXY' or version != 1 or count > 1000000 or len(data) != 12 + count * 8:
            raise ValueError('Invalid SKXY forest.')
        return [{'x': x / 100, 'y': y / 100} for x, y in struct.iter_unpack('<ff', data[12:])]

    def refresh_built(self):
        """Keep the built view separate from the editable original heightmap."""
        self.built, self.built_trees = None, []
        try:
            manifest = json.loads(self.path.read_text(encoding='utf-8-sig'))
            source = manifest['terrain']['source']
            self.built = decode_terrain(manifest['terrain'], self.source_path(source['file']).read_bytes())
            forest = self.source_path('Vegetation/Generated/forest.skxy')
            if forest.exists():
                self.built_trees = self.decode_forest(forest.read_bytes())
        except (ValueError, KeyError, OSError):
            pass

    @property
    def extent(self):
        return (self.width - 1) * self.spacing, (self.height - 1) * self.spacing

    @property
    def elevation(self):
        return min(self.heights), max(self.heights)

    def height_at(self, x, y):
        width, length = self.extent
        return bake.interpolate(self.heights, self.width, self.height,
                                (x + width / 2) / self.spacing, (y + length / 2) / self.spacing)

    def unique_file(self, name):
        path = Path(name)
        for number in range(10000):
            candidate = path if number == 0 else path.with_name(f'{path.stem}-{number}{path.suffix}')
            relative = candidate.as_posix()
            if not self.source_path(relative).exists() and relative not in self.pending:
                return relative
        raise ValueError('Could not find an unused source filename.')

    def import_heightmap(self, file, settings, *, prepared=None):
        terrain, raw, original, assumptions = prepared or inspect_source(self.manifest, file, settings)
        path = Path(file).resolve()
        if path.is_relative_to(self.folder) and path != self.folder / 'Terrain/heightmap.r16':
            relative = path.relative_to(self.folder).as_posix()
        else:
            relative = self.unique_file('Terrain/source-' + path.name)
            self.pending[relative] = original
        self.remember(relative)
        options = copy.deepcopy(settings)
        options['file'] = relative
        self.manifest.setdefault('build', {})['heightmap'] = options
        self.width, self.height, self.spacing, self.heights = decode_terrain(terrain, raw)
        self.assumptions = assumptions
        self.history.clear()
        self.future.clear()
        self.terrain_dirty = False
        self.edited_source = None
        self.dirty = True

    def ensure_source(self):
        build = self.manifest.setdefault('build', {})
        if 'heightmap' not in build:
            source = self.manifest['terrain']['source']
            relative = self.unique_file('Terrain/source-heightmap.r16')
            self.pending[relative] = self.source_path(source['file']).read_bytes()
            self.remember(relative)
            build['heightmap'] = {key: copy.deepcopy(source[key]) for key in
                ('format', 'vertices', 'spacing_meters', 'row_order', 'height_scale_meters', 'height_offset_meters') if key in source}
            build['heightmap']['file'] = relative
        return build['heightmap']

    def encoding_changed(self, settings):
        old = self.manifest.get('build', {}).get('heightmap')
        def normalized(options):
            result = dict(options or {})
            result.setdefault('format', 'png16' if Path(result.get('file', '')).suffix.lower() == '.png' else 'r16le')
            result.setdefault('row_order', 'north_to_south')
            dimensions = result.get('vertices', [None, None])
            result['vertices'] = [value if value is not None else known for value, known in zip(dimensions, (self.width, self.height))]
            return result
        before, after = normalized(old), normalized(settings)
        def same(left, right):
            if isinstance(left,(int,float)) and isinstance(right,(int,float)):
                return math.isclose(left,right,rel_tol=1e-7,abs_tol=1e-12)
            return left == right
        return any(not same(after.get(key),before.get(key)) for key in
                   ('file', 'format', 'vertices', 'spacing_meters', 'elevation_meters', 'height_scale_meters', 'height_offset_meters', 'row_order'))

    def update_settings(self, manifest):
        """Validate a draft before replacing settings; preserve painted relief."""
        draft = copy.deepcopy(manifest)
        validate_manifest(draft)
        if draft.get('build', {}).get('vegetation') or draft.get('build', {}).get('heightmap', {}).get('processing'):
            if 'heightmap' not in draft.setdefault('build', {}):
                draft['build']['heightmap'] = copy.deepcopy(self.ensure_source())
        settings = draft.get('build', {}).get('heightmap')
        changed = self.encoding_changed(settings)
        if changed and self.terrain_dirty:
            raise ValueError('Save the painted terrain before changing its dimensions or elevation encoding.')
        if settings and changed:
            terrain, raw, assumptions = self.prepare_draft(draft)
            if changed:
                self.width, self.height, self.spacing, self.heights = decode_terrain(terrain, raw)
                self.history.clear()
                self.future.clear()
            self.assumptions = assumptions
        if draft != self.manifest:
            self.manifest = draft
            self.dirty = True

    def prepare_draft(self, manifest):
        with tempfile.TemporaryDirectory(prefix='skieomod-editor-validate-') as temporary:
            root = Path(temporary)
            draft = copy.deepcopy(manifest)
            settings = draft['build']['heightmap']
            relative = settings['file']
            data = self.pending.get(relative)
            if data is None:
                data = self.source_path(relative).read_bytes()
            file = root / ('input' + Path(relative).suffix)
            file.write_bytes(data)
            settings['file'] = file.name
            terrain, raw, _, assumptions = inspect_source(draft, file, settings)
        return terrain, raw, assumptions

    def begin_stroke(self, tool):
        if self._stroke is not None:
            raise ValueError('Finish the current stroke first.')
        self._stroke = {'kind': 'trees' if tool in ('trees', 'erase_trees') else 'terrain', 'before': {}}
        if self._stroke['kind'] == 'trees':
            self._stroke['before'] = copy.deepcopy(self.trees)

    def paint(self, x, y, tool, radius, strength=5, target=None, tree_spacing=12):
        if not self._stroke:
            raise ValueError('Begin a stroke before painting.')
        for value in (x, y, radius, strength, tree_spacing):
            if not math.isfinite(value):
                raise ValueError('Brush values must be finite.')
        if radius <= 0 or strength < 0 or tree_spacing <= 0:
            raise ValueError('Brush radius and tree spacing must be positive.')
        size_x, size_y = self.extent
        if abs(x) > size_x / 2 or abs(y) > size_y / 2:
            return
        if tool in ('trees', 'erase_trees'):
            self._paint_trees(x, y, radius, tree_spacing, tool == 'erase_trees')
            return
        if tool not in ('raise', 'lower', 'flatten', 'smooth'):
            raise ValueError('Unknown terrain brush.')
        gx, gy = (x + size_x / 2) / self.spacing, (y + size_y / 2) / self.spacing
        cells = radius / self.spacing
        left, right = max(0, math.floor(gx - cells)), min(self.width - 1, math.ceil(gx + cells))
        top, bottom = max(0, math.floor(gy - cells)), min(self.height - 1, math.ceil(gy + cells))
        if (right - left + 1) * (bottom - top + 1) > 250000:
            raise ValueError('Reduce the brush radius: a dab can affect at most 250,000 samples.')
        if target is None:
            target = self.height_at(x, y)
        if not math.isfinite(target):
            raise ValueError('Flatten height must be finite.')
        changes = {}
        for row in range(top, bottom + 1):
            for col in range(left, right + 1):
                distance = math.hypot(col - gx, row - gy) / cells
                if distance >= 1:
                    continue
                index = row * self.width + col
                previous = self.heights[index]
                amount = strength * (1 - distance * distance) ** 2
                if tool == 'raise':
                    value = previous + amount
                elif tool == 'lower':
                    value = previous - amount
                else:
                    wanted = target if tool == 'flatten' else sum(
                        self.heights[r * self.width + c] for r, c in
                        ((max(0, row - 1), col), (min(self.height - 1, row + 1), col),
                         (row, max(0, col - 1)), (row, min(self.width - 1, col + 1)))) / 4
                    value = previous + max(-amount, min(amount, wanted - previous))
                if value != previous:
                    self._stroke['before'].setdefault(index, previous)
                    changes[index] = value
        for index, value in changes.items():
            self.heights[index] = value

    def _paint_trees(self, x, y, radius, spacing, erase):
        if erase:
            self.trees = [p for p in self.trees if math.hypot(p['x'] - x, p['y'] - y) > radius]
            return
        if radius / spacing > 40:
            raise ValueError('Reduce the tree radius or increase spacing (maximum 40 intervals per dab).')
        cells = {}
        for point in self.trees:
            cells.setdefault((math.floor(point['x'] / spacing), math.floor(point['y'] / spacing)), []).append(point)
        randomizer = random.Random(f'{x:.4f},{y:.4f},{len(self.trees)}')
        size_x, size_y = self.extent
        for gy in range(math.floor((y - radius) / spacing), math.ceil((y + radius) / spacing) + 1):
            for gx in range(math.floor((x - radius) / spacing), math.ceil((x + radius) / spacing) + 1):
                px, py = (gx + randomizer.uniform(.25, .75)) * spacing, (gy + randomizer.uniform(.25, .75)) * spacing
                if math.hypot(px - x, py - y) > radius or abs(px) > size_x / 2 or abs(py) > size_y / 2:
                    continue
                key = math.floor(px / spacing), math.floor(py / spacing)
                nearby = [p for dy in (-1, 0, 1) for dx in (-1, 0, 1) for p in cells.get((key[0] + dx, key[1] + dy), [])]
                if any(math.hypot(p['x'] - px, p['y'] - py) < spacing for p in nearby):
                    continue
                if len(self.trees) >= 1000000:
                    raise ValueError('Manual forests support at most 1,000,000 trees.')
                point = {'x': round(px, 4), 'y': round(py, 4)}
                self.trees.append(point)
                cells.setdefault(key, []).append(point)

    def end_stroke(self, cancel=False):
        stroke, self._stroke = self._stroke, None
        if not stroke:
            return False
        if stroke['kind'] == 'terrain':
            stroke['after'] = {index: self.heights[index] for index in stroke['before']}
        else:
            stroke['after'] = copy.deepcopy(self.trees)
        if cancel:
            if stroke['kind'] == 'terrain':
                for index, value in stroke['before'].items():
                    self.heights[index] = value
            else:
                self.trees = stroke['before']
            return False
        if stroke['after'] == stroke['before'] or not stroke['after'] and not stroke['before']:
            return False
        self.history.append(stroke)
        self.future.clear()
        # Limit histories on large LiDAR sources; preserve at least the last stroke.
        while len(self.history) > 1 and (len(self.history) > 40 or sum(len(item['before']) + len(item['after']) for item in self.history) > 1000000):
            self.history.pop(0)
        self._changed(stroke['kind'])
        return True

    def _changed(self, kind):
        self.dirty = True
        if kind == 'terrain':
            self.terrain_dirty = True
        else:
            self.forest_dirty = True
            self.set_forest_mode('Manual')

    def _apply_history(self, stroke, key):
        if stroke['kind'] == 'scene':
            if 'edits_'+key in stroke and stroke['edits_'+key]!=self.object_edits: self.queue_authoring('objects',stroke['edits_'+key])
            self.queue_authoring('scene', stroke[key]);return
        if stroke['kind'] == 'object_edits':
            self.queue_authoring('objects',stroke[key]);return
        if stroke['kind'] == 'terrain':
            for index, value in stroke[key].items():
                self.heights[index] = value
        else:
            self.trees = copy.deepcopy(stroke[key])
        self._changed(stroke['kind'])

    def undo(self):
        if not self.history:
            return False
        stroke = self.history.pop()
        self._apply_history(stroke, 'before')
        self.future.append(stroke)
        return True

    def redo(self):
        if not self.future:
            return False
        stroke = self.future.pop()
        self._apply_history(stroke, 'after')
        self.history.append(stroke)
        return True

    def set_forest_mode(self, mode):
        if mode not in ('None', 'Manual', 'Automatic'):
            raise ValueError('Unknown forest mode.')
        build = self.manifest.setdefault('build', {})
        if mode == 'Manual':
            if 'forest' not in build:
                relative = self.unique_file('Vegetation/editor-forest.json')
                build['forest'] = {'file': relative}
                self.remember(relative)
                self.forest_dirty = True
        elif mode == 'None':
            build.pop('forest', None)
        if mode == 'Automatic':
            self.ensure_source()
            build.setdefault('vegetation', {}).setdefault('trees', {})['enabled'] = True
        elif 'vegetation' in build:
            build['vegetation'].setdefault('trees', {})['enabled'] = False
        self.dirty = True

    @property
    def forest_mode(self):
        build = self.manifest.get('build', {})
        if 'vegetation' in build and build['vegetation'].get('trees', {}).get('enabled', True):
            return 'Automatic'
        return 'Manual' if 'forest' in build else 'None'

    def set_script(self, text):
        if not self.script_path:
            raise ValueError('This project has no script entry point.')
        if text != self.script:
            self.pending[self.script_path] = text.encode('utf-8')
            self.script = text
            self.dirty = True

    def save_to(self, directory):
        """Give an unsaved document a source folder without losing queued edits."""
        directory = Path(directory).expanduser().resolve()
        if directory.exists() and (not directory.is_dir() or any(directory.iterdir())):
            raise ValueError('Choose an empty folder for this new map.')
        self.save()
        directory.mkdir(parents=True, exist_ok=True)
        written = []
        try:
            for source in self.folder.rglob('*'):
                if not source.is_file() or any(part in ('obj', 'bin', '.skieomod-backups', '.heightmap-backups') for part in source.relative_to(self.folder).parts):
                    continue
                target = directory / source.relative_to(self.folder)
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open('xb') as stream:
                    written.append(target)
                    stream.write(source.read_bytes())
        except Exception:
            for target in reversed(written): target.unlink(missing_ok=True)
            self.dirty = True
            raise
        workspace = self.workspace
        self.folder = directory
        self.path = directory / 'custom-map.json'
        self.has_folder = True
        self.workspace = None
        if workspace: workspace.cleanup()

    def save(self):
        if self._stroke:
            raise ValueError('Finish the current brush stroke before saving.')
        draft = copy.deepcopy(self.manifest)
        pending = dict(self.pending)
        if self.terrain_dirty:
            low, high = self.elevation
            if high == low: high = low + 1
            scale = (high - low) / 65535
            samples = array('H', (max(0, min(65535, round((height - low) / scale))) for height in self.heights))
            if sys.byteorder != 'little':
                samples.byteswap()
            relative = self.edited_source or 'Terrain/Editor/heightmap.r16'
            # Never take over an existing unrelated authoring file.
            current = self.manifest.get('build', {}).get('heightmap', {}).get('file')
            if self.edited_source is None and (self.source_path(relative).exists() or relative in pending):
                relative = self.unique_file('Terrain/Editor/heightmap.r16')
            self.remember(relative)
            options = draft.setdefault('build', {}).setdefault('heightmap', {})
            options.pop('elevation_meters', None)
            options.update(file=relative, format='r16le', vertices=[self.width, self.height], spacing_meters=self.spacing,
                           row_order='north_to_south', height_scale_meters=scale, height_offset_meters=low)
            pending[relative] = samples.tobytes()
        if self.forest_dirty and 'forest' in draft.get('build', {}):
            relative = draft['build']['forest']['file']
            bake.encode_forest(self.trees)
            self.remember(relative)
            pending[relative] = (json.dumps(self.trees, indent=2) + '\n').encode('utf-8')
        validate_manifest(draft)
        if draft.get('build', {}).get('heightmap'):
            # Validation must include any imports/painted source not on disk yet.
            saved = self.pending
            self.pending = pending
            try:
                self.prepare_draft(draft)
            finally:
                self.pending = saved
        for relative in [self.path.name, *pending]:
            target = self.source_path(relative)
            self.remember(relative)
            actual = target.read_bytes() if target.exists() else None
            if actual != self.expected[relative]:
                raise ValueError(f'{relative} changed outside the editor. Reopen the project before saving.')
        with heightmaps.save_generated(self.folder, self.path, draft, None, pending, save_manifest=True):
            pass
        self.manifest = draft
        if self.terrain_dirty:
            self.edited_source = draft['build']['heightmap']['file']
        for relative in [self.path.name, *pending]:
            self.expected[relative] = self.source_path(relative).read_bytes()
        self.pending.clear()
        self.dirty = self.terrain_dirty = self.forest_dirty = False

    def accept_build(self):
        self.manifest = json.loads(self.path.read_text(encoding='utf-8-sig'))
        self.expected[self.path.name] = self.path.read_bytes()
        self.refresh_built()


def launch(path=None):
    """Import desktop libraries only when invoked; build remains headless."""
    try:
        from PySide6 import QtWidgets as W, QtGui as G, QtCore as C
        if __package__ == 'tools':
            from .skieo_editor_ui import MapEditor, STYLE
        else:
            from skieo_editor_ui import MapEditor, STYLE
    except ImportError as error:
        raise ManifestError('The editor needs the Qt/OpenGL dependencies. Reinstall or upgrade skieo-custom-map with dependencies enabled (PySide6-Essentials, pyqtgraph, PyOpenGL and numpy).') from error
    if sys.platform.startswith('linux') and not any(os.environ.get(key) for key in ('DISPLAY', 'WAYLAND_DISPLAY', 'QT_QPA_PLATFORM')):
        raise ManifestError('Run skieomod editor in a graphical desktop session with OpenGL available.')
    format=G.QSurfaceFormat();format.setDepthBufferSize(24);format.setSamples(4);G.QSurfaceFormat.setDefaultFormat(format)
    C.QCoreApplication.setAttribute(C.Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    desktop=W.QApplication.instance() or W.QApplication([])
    desktop.setStyle('Fusion');desktop.setStyleSheet(STYLE)
    app = MapEditor(path=path)
    app.show()
    return desktop.exec()
