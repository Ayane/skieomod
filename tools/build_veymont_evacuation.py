#!/usr/bin/env python3
"""Apply the surveyed forest exits to Veymont, sampling its shipped terrain."""
from __future__ import annotations

import json
from pathlib import Path

from tools.build_veymont_geodata import Grid, load_r16, sample_height

ROOT = Path(__file__).resolve().parents[1]


def apply(manifest, survey, grid, heights):
    if survey['format'] != 'skieo-veymont-evacuation-survey':
        raise ValueError('Unknown evacuation survey')
    lifts = {d['name']: d for d in manifest['extensions']['community.surface-lifts']['lifts']}
    for definition in lifts.values():
        definition.pop('evacuation_routes', None)
    for record in survey['routes']:
        path = []
        for x, y, _ in record['route']:
            if not (grid.origin_x <= x <= grid.origin_x + (grid.width - 1) * grid.spacing_cm
                    and grid.origin_y <= y <= grid.origin_y + (grid.height - 1) * grid.spacing_cm):
                raise ValueError('Evacuation exit outside terrain')
            path.append([x, y, round(sample_height(heights, x, y, grid), 3)])
        if len(path) < 2 or path[-1][2] >= path[0][2] or any(b[2] > a[2] + 500 for a, b in zip(path, path[1:])):
            raise ValueError('Evacuation exit must descend; maximum local terrain rise is 5 m')
        lifts[record['lift']].setdefault('evacuation_routes', []).append(path)
    return manifest


def main():
    manifest_path = ROOT / 'mod/SkiEO-Veymont/custom-map.json'
    manifest = json.loads(manifest_path.read_text())
    grid = Grid.read(json.loads((ROOT / 'maps/veymont/map.json').read_text()), manifest)
    heights = load_r16(manifest_path.parent / manifest['terrain']['source']['file'], grid)
    survey = json.loads((ROOT / 'maps/veymont/evacuation-routes.json').read_text())
    apply(manifest, survey, grid, heights)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    print('Applied 2 Pré Levé corner exits and 1 Pierre Blanche forest exit')


if __name__ == '__main__':
    main()
