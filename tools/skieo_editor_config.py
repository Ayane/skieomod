"""Editor preferences and build parameter descriptions shared by native forms."""
import json
from pathlib import Path

if __package__ == 'tools':
    from . import skieo_install as desktop
else:
    import skieo_install as desktop

STARTUP_CHOICES = {'last': 'Open the last map', 'new': 'Create a new map', 'none': 'No map open'}
RECENT_PROJECT_LIMIT = 20


class EditorPreferences:
    """Keep editor state separate from the Steam installation configuration."""
    def __init__(self, path=None):
        self.path = Path(path) if path is not None else desktop.config_directory() / 'editor.json'
        self.startup = 'last'
        self.recent_projects = []
        try:
            data = json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return
        if not isinstance(data, dict):
            return
        if isinstance(data.get('startup'), str) and data['startup'] in STARTUP_CHOICES:
            self.startup = data['startup']
        recent = data.get('recent_projects', [])
        if not isinstance(recent, list):
            return
        seen = set()
        for item in recent:
            if not isinstance(item, dict) or not isinstance(item.get('path'), str) or not item['path']:
                continue
            path = Path(item['path'])
            if not path.is_absolute() or path.name != 'custom-map.json':
                continue
            key = str(path)
            if key in seen:
                continue
            seen.add(key)
            name = item.get('name')
            self.recent_projects.append({'path': key, 'name': name if isinstance(name, str) and name else path.parent.name})
            if len(self.recent_projects) == RECENT_PROJECT_LIMIT:
                break

    def save(self):
        desktop.atomic_json(self.path, {'version': 1, 'startup': self.startup, 'recent_projects': self.recent_projects})

    def remember(self, document):
        if not document.has_folder:
            return
        path = str(document.path.resolve())
        item = {'path': path, 'name': document.manifest['metadata']['name']}
        self.recent_projects = [item] + [old for old in self.recent_projects if old['path'] != path]
        self.recent_projects = self.recent_projects[:RECENT_PROJECT_LIMIT]
        self.save()

    def last_project(self):
        return next((item['path'] for item in self.recent_projects if Path(item['path']).is_file()), None)


TERRAIN_FORMATS = {'Automatic': None, 'R16 little-endian': 'r16le', 'R16 big-endian': 'r16be', 'PNG 16-bit': 'png16'}

ELEVATIONS = ('Relative test: 0–1000 m', 'Known lowest / highest', 'Exporter scale / offset')

PROCESSING = {
    'smoothing': [('iterations', 'Passes', 2, 0, 50, int), ('strength', 'Strength', .15, 0, 1, float), ('max_delta_meters', 'Maximum change (m)', 1, 0, 100, float)],
    'thermal_erosion': [('iterations', 'Passes', 8, 0, 50, int), ('talus_degrees', 'Talus angle (°)', 35, 0, 89, float), ('strength', 'Strength', .2, 0, 1, float), ('max_delta_meters', 'Maximum change (m)', 3, 0, 100, float)],
    'hydraulic_erosion': [('iterations', 'Passes', 4, 0, 50, int), ('strength', 'Strength', .06, 0, 1, float), ('rainfall', 'Rainfall multiplier', 1, 0, 10, float), ('max_delta_meters', 'Maximum change (m)', 1, 0, 100, float)],
    'noise': [('amplitude_meters', 'Amplitude (m)', .25, 0, 20, float), ('wavelength_meters', 'Wavelength (m)', 64, .01, 1000000, float), ('seed', 'Seed', 42, 0, 4294967295, int)],
}

VEGETATION = {
    'biome': [('tree_line_meters', 'Tree line (m)', 1900, -1000, 20000, float), ('alpine_line_meters', 'Alpine line (m)', 2400, -1000, 20000, float),
              ('temperature_sea_level_celsius', 'Sea-level temperature (°C)', 15, -50, 60, float), ('lapse_rate_celsius_per_km', 'Cooling / km (°C)', 6.5, 0, 15, float),
              ('moisture', 'Moisture', .65, 0, 1, float), ('wind_strength', 'Wind exposure', .3, 0, 1, float), ('wind_direction_degrees', 'Wind from (°)', 270, 0, 360, float)],
    'trees': [('seed', 'Seed', 42, 0, 4294967295, int), ('density_per_hectare', 'Trees / hectare', 90, 0, 2000, float),
              ('min_spacing_meters', 'Minimum spacing (m)', 5, .1, 1000, float), ('max_slope_degrees', 'Maximum slope (°)', 32, .1, 89, float),
              ('tree_line_fade_meters', 'Tree-line fade (m)', 150, .01, 5000, float), ('patch_size_meters', 'Patch size (m)', 160, .1, 1000000, float),
              ('patchiness', 'Patchiness', .6, 0, 1, float), ('max_trees', 'Tree limit', 100000, 0, 1000000, int)],
    'ground_cover': [('texture_size', 'Texture resolution', 256, 16, 512, int), ('max_slope_degrees', 'Maximum slope (°)', 45, .1, 89, float)],
}
