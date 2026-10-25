"""Keep surveyed emergency exits at both Pré Levé bends and on the terrain."""
import copy
import json
import math
from pathlib import Path
import unittest

from tools.build_veymont_evacuation import apply
from tools.build_veymont_geodata import Grid, load_r16

ROOT = Path(__file__).resolve().parents[1]


class VeymontEvacuationTests(unittest.TestCase):
    def test_published_routes_match_survey_and_terrain(self):
        manifest = json.loads((ROOT / 'mod/SkiEO-Veymont/custom-map.json').read_text())
        survey = json.loads((ROOT / 'maps/veymont/evacuation-routes.json').read_text())
        grid = Grid.read(json.loads((ROOT / 'maps/veymont/map.json').read_text()), manifest)
        heights = load_r16(ROOT / 'mod/SkiEO-Veymont' / manifest['terrain']['source']['file'], grid)
        rebuilt = apply(copy.deepcopy(manifest), survey, grid, heights)
        self.assertEqual(rebuilt, manifest, 'Regenerate Veymont exits after changing the survey or terrain')
        pre = [r for r in survey['routes'] if r['lift'] == 'Pré Levé']
        self.assertEqual([(r['entry_pylon'], r['joins']) for r in pre], [(6, 'Les Bouquetins'), (9, 'Les Tétras')])
        bends = [(-102726.91, -82598.23), (-122454.12, -85000.24)]
        for record, bend in zip(pre, bends, strict=True):
            self.assertLess(math.dist(record['route'][0][:2], bend), 500)
        lifts = {d['name']: d for d in manifest['extensions']['community.surface-lifts']['lifts']}
        self.assertEqual(len(lifts['Pré Levé']['evacuation_routes']), 2)
        self.assertEqual(len(lifts['Pierre Blanche']['evacuation_routes']), 1)
        for d in lifts.values():
            self.assertGreaterEqual(d['service_offset_m'] - d['service_width_m'] / 2, 1)
            for route in d.get('evacuation_routes', []):
                self.assertLess(route[-1][2], route[0][2])
                self.assertLess(max(b[2] - a[2] for a, b in zip(route, route[1:])), 500)


if __name__ == '__main__':
    unittest.main()
