"""Run the portable native towing history regression used by the shipped hook."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('cc'), 'C compiler unavailable')
class TowTrackTests(unittest.TestCase):
    def test_native_history_handles_reordered_batches_stops_and_teleports(self):
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / 'tow-tracks'
            subprocess.run(['cc', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                            str(ROOT / 'tests/test_surface_lift_tracks.c'), '-lm', '-o', str(executable)],
                           check=True, capture_output=True)
            result = subprocess.run([str(executable)], check=True, capture_output=True, text=True)
            self.assertIn('changing batches, GUIDs, velocity, stops, teleports and pauses OK', result.stdout)
