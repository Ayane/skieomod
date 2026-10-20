"""The UI warning and CLI must name the executable reviewed by the protocol."""
import json
from pathlib import Path
import re
import unittest

from tools.skieo_loader import TESTED_GAME_BUILDS

ROOT = Path(__file__).resolve().parents[1]


class SupportedBuildTests(unittest.TestCase):
    def test_runtime_recognition_matches_qualified_contract_and_cli(self):
        contract = json.loads((ROOT / 'compatibility/game-contract.json').read_text())
        source = (ROOT / 'mod/SkiEO-CustomMaps/Scripts/supported_game_builds.lua').read_text()
        entries = re.findall(r'\["([0-9a-f]{64})"\] = \{app_id="(\d+)", build="(\d+)"\}', source)
        self.assertIn((contract['reference_executable_sha256'], '5012760', contract['reference_build']), entries)
        self.assertEqual({app: build for _, app, build in entries}, TESTED_GAME_BUILDS)
