import copy
import unittest
from tools.compare_scenario_checkpoints import differences


class CheckpointTests(unittest.TestCase):
    def setUp(self):
        self.before = {'label': 'before', 'engine_paused': True, 'map_id': 'test.map', 'map_version': '0.2.1',
                       'calendar': {'months': 16.3, 'balance': 250000}, 'weather': {'type': 2},
                       'debt': {'outstanding': 40000}, 'ticket_price': 38, 'script_state': {'effort': 2}, 'loans': [],
                       'lifts': [{'id': 'menouve', 'name': 'Menouve', 'running': True, 'skiing': True,
                                  'status': 'Operating', 'rides': 2, 'staff': 2,
                                  'bottom_snow': {'packed_cm': 100, 'fresh_cm': 20, 'total_cm': 120},
                                  'top_snow': {'packed_cm': 100, 'fresh_cm': 20, 'total_cm': 120}}]}

    def test_stable_and_small_readback_rounding(self):
        after = copy.deepcopy(self.before)
        after['label'] = 'after'
        after['lifts'][0]['top_snow']['fresh_cm'] += .25
        self.assertEqual(differences(self.before, after), [])

    def test_detects_snow_and_financial_drift(self):
        after = copy.deepcopy(self.before)
        after['calendar']['balance'] -= 500
        after['lifts'][0]['top_snow']['fresh_cm'] += 2
        self.assertTrue(any('calendar' in f for f in differences(self.before, after)))
        self.assertTrue(any('fresh_cm' in f for f in differences(self.before, after)))

    def test_missing_or_unpaused_measurements_are_rejected(self):
        after = copy.deepcopy(self.before)
        after['engine_paused'] = False
        del after['lifts'][0]['top_snow']
        self.assertGreaterEqual(len(differences(self.before, after)), 4)

    def test_missing_loan_fields_are_rejected(self):
        after = copy.deepcopy(self.before)
        after['loans'] = [[]]
        self.assertIn('loans: missing contract measurements', differences(self.before, after))


if __name__ == '__main__':
    unittest.main()
