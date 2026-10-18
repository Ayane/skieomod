"""Compatibility qualification must fail closed on missing/stale evidence."""
import copy
import contextlib
import hashlib
import io
import json
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch, Mock

from tools import check_game_compatibility as protocol


def executable(code=b'abcdefgh01234567', *, executable_section=True):
    data = bytearray(0x600)
    data[:2] = b'MZ'
    struct.pack_into('<I', data, 0x3C, 0x80)
    data[0x80:0x84] = b'PE\0\0'
    struct.pack_into('<HH', data, 0x84, 0x8664, 1)
    struct.pack_into('<H', data, 0x94, 0xF0)
    struct.pack_into('<H', data, 0x98, 0x20B)
    section = 0x188
    struct.pack_into('<IIII', data, section + 8, 0x100, 0x1000, 0x100, 0x400)
    struct.pack_into('<I', data, section + 36, 0x20000000 if executable_section else 0)
    data[0x400:0x400+len(code)] = code
    return bytes(data)


class ExecutableTests(unittest.TestCase):
    def test_fixed_entry_point_move_is_not_auto_accepted(self):
        guard = {'id': 'hubs', 'rva': '0x1000', 'bytes': b'abcdefgh'.hex(), 'mode': 'rva'}
        self.assertEqual(protocol.inspect_guards(protocol.PEImage(executable()), [guard])[0]['status'], 'pass')
        moved = protocol.inspect_guards(protocol.PEImage(executable(b'---abcdefgh')), [guard])[0]
        self.assertEqual(moved['status'], 'fail')
        self.assertEqual(moved['candidate_rvas'], ['0x1003'])

    def test_search_guard_requires_unique_executable_match(self):
        guard = {'id': 'nav', 'rva': '0x1000', 'bytes': b'abcdefgh'.hex(), 'mode': 'unique'}
        for code, expected in [(b'-abcdefgh', 'pass'), (b'abcdefghabcdefgh', 'fail'), (b'bad-layout', 'fail')]:
            with self.subTest(code=code):
                result = protocol.inspect_guards(protocol.PEImage(executable(code)), [guard])[0]
                self.assertEqual(result['status'], expected)
        image = protocol.PEImage(executable(executable_section=False))
        self.assertEqual(image.find(b'abcdefgh'), [])
        self.assertEqual(image.read(0x1000, 8), b'')

    def test_malformed_pe_and_out_of_file_ranges(self):
        valid = executable()
        for data in [b'', b'MZ' * 64, valid[:100], valid[:0x450]]:
            with self.subTest(length=len(data)), self.assertRaises(ValueError):
                protocol.PEImage(data)
        image = protocol.PEImage(valid)
        self.assertEqual(image.read(0x10F8, 16), b'')
        guard = {'id': 'weak', 'rva': '0x1000', 'bytes': '90', 'mode': 'unique'}
        with self.assertRaises(ValueError):
            protocol.inspect_guards(image, [guard])


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.report = {'run_id': 'current-run', 'checks': [], 'fingerprints': {'executable': 'current'}}
        self.contract = {'maps': [{'id': 'test.map'}], 'manual_checks': ['rendering', 'native_save_roundtrip']}

    def test_exit_codes_do_not_treat_unrun_checks_as_success(self):
        self.assertEqual(protocol.verdict(self.report), ('unverified', 2))
        protocol.check(self.report, 'assets', 'pass', 'inspected')
        protocol.check(self.report, 'rendering', 'pending', 'review required')
        self.assertEqual(protocol.verdict(self.report), ('unverified', 2))
        protocol.check(self.report, 'native', 'fail', 'stale address')
        self.assertEqual(protocol.verdict(self.report), ('incompatible', 1))
        self.report['checks'] = []
        protocol.check(self.report, 'tested', 'pass', '')
        protocol.check(self.report, 'build', 'pending', 'new revision', required=False)
        self.assertEqual(protocol.verdict(self.report), ('compatible', 0))

    def test_a_weakened_contract_cannot_omit_required_measurements(self):
        contract = json.loads((protocol.ROOT / 'compatibility/game-contract.json').read_text())
        protocol.validate_contract(contract)
        for mutation in ['guards', 'maps', 'assets', 'classes', 'manual_checks', 'counts', 'duplicate']:
            with self.subTest(mutation=mutation):
                data = copy.deepcopy(contract)
                if mutation in {'guards', 'maps', 'assets', 'classes', 'manual_checks'}: data[mutation] = []
                if mutation == 'counts': data['maps'][0]['expected'] = {}
                if mutation == 'duplicate': data['guards'].append(data['guards'][0])
                with self.assertRaises(ValueError): protocol.validate_contract(data)

    def complete_live(self):
        ids = ['live.reflection', 'live.heartbeat', 'live.isolation']
        ids += ['live.test.map.' + stage for stage in ['counts', 'variants', 'gc']]
        return {'run_id': 'current-run', 'complete': True, 'maps_enabled': True,
                'checks': [{'id': key, 'status': 'pass'} for key in ids]}

    def test_stale_partial_duplicate_and_missing_live_results_fail(self):
        for change in ['stale', 'partial', 'missing_gc', 'duplicate', 'exception']:
            with self.subTest(change=change):
                self.report['checks'] = []
                data = self.complete_live()
                if change == 'stale': data['run_id'] = 'previous-run'
                if change == 'partial': data['complete'] = False
                if change == 'missing_gc': data['checks'].pop()
                if change == 'duplicate': data['checks'].append(data['checks'][0])
                if change == 'exception': data['error'] = 'binding failed'
                protocol.ingest_live(self.report, data, self.contract)
                self.assertEqual(protocol.verdict(self.report), ('incompatible', 1))

    def test_blocked_map_test_cannot_become_green(self):
        data = self.complete_live()
        data['maps_enabled'] = False
        protocol.ingest_live(self.report, data, self.contract)
        self.assertEqual(protocol.verdict(self.report), ('unverified', 2))
        self.assertIn('live.maps', [c['id'] for c in self.report['checks'] if c['status'] == 'blocked'])

    def test_silence_before_native_operations_is_not_a_passing_test(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / 'UE4SS.log'
            protocol.inspect_native_log(self.report, log, False)
            self.assertEqual(self.report['checks'][-1]['status'], 'blocked')
            protocol.inspect_native_log(self.report, log, True)
            self.assertEqual(self.report['checks'][-1]['status'], 'pending')
            log.write_text('error: unsupported staff executable layout\n')
            protocol.inspect_native_log(self.report, log, True)
            self.assertEqual(self.report['checks'][-1]['status'], 'fail')

    def test_manual_review_is_bound_to_run_binary_and_real_artifacts(self):
        self.contract['manual_checks'] = ['rendering']
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            artifact = folder / 'capture.png'
            artifact.write_bytes(b'recorded evidence')
            review = {'run_id': self.report['run_id'], 'fingerprints': self.report['fingerprints'], 'checks': {
                key: {'status': 'pass', 'note': 'Reviewed captured state',
                      'artifacts': [{'path': 'capture.png', 'sha256': protocol.sha256(artifact)}]}
                for key in self.contract['manual_checks']}}
            protocol.apply_review(self.report, self.contract, review, folder)
            self.assertEqual(protocol.verdict(self.report), ('compatible', 0))
            for mutation in ['stale_run', 'wrong_binary', 'missing_file', 'wrong_hash', 'escape', 'no_note']:
                with self.subTest(mutation=mutation):
                    self.report['checks'] = []
                    candidate = copy.deepcopy(review)
                    entry = candidate['checks']['rendering']
                    if mutation == 'stale_run': candidate['run_id'] = 'old'
                    if mutation == 'wrong_binary': candidate['fingerprints']['executable'] = 'different'
                    if mutation == 'missing_file': entry['artifacts'][0]['path'] = 'absent.png'
                    if mutation == 'wrong_hash': entry['artifacts'][0]['sha256'] = '0' * 64
                    if mutation == 'escape': entry['artifacts'][0]['path'] = '../capture.png'
                    if mutation == 'no_note': entry['note'] = ''
                    protocol.apply_review(self.report, self.contract, candidate, folder)
                    self.assertEqual(protocol.verdict(self.report), ('unverified', 2))

    def test_asset_removal_content_change_and_unknown_hash(self):
        before = {'/Game/Removed.uasset': 'a', '/Game/Changed.uasset': 'a', '/Game/Unknown.uasset': None}
        after = {'/Game/Added.uasset': 'b', '/Game/Changed.uasset': 'b', '/Game/Unknown.uasset': 'c'}
        self.assertEqual(protocol.asset_diff(before, after), {
            'added': ['/Game/Added.uasset'], 'removed': ['/Game/Removed.uasset'], 'changed': ['/Game/Changed.uasset']})
        listing = ('Store chunk ExportBundleData ' + 'a' * 40 + ' ../../../SkiResortSimulator/Content/Data/A.uasset\n'
                   'Store chunk BulkData ../../../SkiResortSimulator/Content/Data/A.ubulk\n'
                   'Store chunk ../../../Engine/Content/Maps/Entry.uasset\n')
        self.assertEqual(protocol.asset_names(listing), {'/Game/Data/A.uasset': 'a' * 40, '/Engine/Maps/Entry.uasset': None})
        self.assertEqual(protocol.asset_names('Store ' + 'b' * 64 + ' ExportBundleData ../../../SkiResortSimulator/Content/B.uasset'),
                         {'/Game/B.uasset': 'b' * 64})
        self.assertEqual(protocol.asset_names('Store chunk ../../../Engine/Plugins/X/Content/With Space.uasset'),
                         {'../../../Engine/Plugins/X/Content/With Space.uasset': None})

    def test_native_save_review_requires_both_maps_and_compares_measured_state(self):
        self.contract = {'maps': [{'id': 'test.first', 'version': '1.0.0'}, {'id': 'test.second', 'version': '2.0.0'}],
                         'manual_checks': ['native_save_roundtrip']}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            entry = {'status': 'pass', 'note': 'Saved and reloaded both native slots', 'artifacts': [], 'roundtrips': []}
            for definition in self.contract['maps']:
                snapshot = {'map_id': definition['id'], 'map_version': definition['version'], 'engine_paused': True,
                            'calendar': {'balance': 250000}, 'weather': {}, 'debt': {}, 'ticket_price': 38,
                            'script_state': {'progress': 2}, 'loans': [],
                            'lifts': [{'id': 'lift', 'name': 'lift', 'running': True, 'skiing': True, 'status': 'Operating',
                                       'rides': 0, 'staff': 2, 'bottom_snow': {'packed_cm': 100, 'fresh_cm': 20, 'total_cm': 120},
                                       'top_snow': {'packed_cm': 100, 'fresh_cm': 20, 'total_cm': 120}}]}
                snapshot['compatibility_world'] = dict(buildings=1, decorations=1, lifts=1, trails=1, hubs=1,
                    staff=2, trees=0, variants={'Expert': 1}, saved_variants={'Expert': 1},
                    placeables={'guid': {'class': 'NativeBuilding', 'name': 'Marker', 'variant': 'Expert', 'position': {'X': 1, 'Y': 2, 'Z': 3}}})
                pair = {'map_id': definition['id'], 'slot': 'Compatibility-this-run'}
                for stage in ['before', 'after']:
                    path = definition['id'] + '-' + stage + '.json'
                    (root / path).write_text(json.dumps(snapshot))
                    pair[stage] = path
                    entry['artifacts'].append({'path': path, 'sha256': protocol.sha256(root / path)})
                entry['roundtrips'].append(pair)
            review = {'run_id': self.report['run_id'], 'fingerprints': self.report['fingerprints'],
                      'checks': {'native_save_roundtrip': entry}}
            protocol.apply_review(self.report, self.contract, review, root)
            self.assertEqual(protocol.verdict(self.report), ('compatible', 0))
            self.report['checks'] = []
            changed = root / entry['roundtrips'][0]['after']
            data = json.loads(changed.read_text());data['calendar']['balance'] -= 500
            changed.write_text(json.dumps(data))
            for artifact in entry['artifacts']:
                if artifact['path'] == changed.name: artifact['sha256'] = protocol.sha256(changed)
            protocol.apply_review(self.report, self.contract, review, root)
            self.assertEqual(protocol.verdict(self.report), ('incompatible', 1))
            self.report['checks'] = []
            entry['roundtrips'].pop()
            protocol.apply_review(self.report, self.contract, review, root)
            self.assertTrue(any('both maps' in x['detail'] for x in self.report['checks']))


class IsolationTests(unittest.TestCase):
    def test_static_cli_writes_an_incompatible_report_without_launching_or_modifying_game(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            library = root / 'steamapps'
            game = library / 'common/fixture_game'
            binary = game / 'SkiResortSimulator/Binaries/Win64'
            binary.mkdir(parents=True)
            (binary / 'skieogame.exe').write_bytes(executable())
            ue = binary / 'ue4ss';ue.mkdir()
            (ue / 'UE4SS.dll').write_bytes(b'framework')
            content = game / 'SkiResortSimulator/Content/Paks';content.mkdir(parents=True)
            (content / 'SkiResortSimulator-Windows.utoc').write_bytes(b'io store')
            (library / 'appmanifest_5012760.acf').write_text('"AppState" { "installdir" "fixture_game" "buildid" "new123" }')
            config = root / 'config.json'
            config.write_text(json.dumps({'game_dir': str(game), 'binary_dir': str(binary),
                'ue4ss_dir': str(ue), 'app_id': '5012760', 'steamapps_dir': str(library)}))
            before = {p: p.read_bytes() for p in game.rglob('*') if p.is_file()}
            output = root / 'report'
            previous = root / 'previous.json'
            previous.write_text(json.dumps({'assets': {'/Game/Blueprints/Decorations/BP_StringLights.uasset': None}}))
            def inspect(path, kind):
                name = path.name
                identifier, version = name.rsplit('-', 1)
                version = version.removesuffix('.skieomap').removesuffix('.skieomod')
                return kind, {'id': identifier, 'metadata': {'version': version}}, {}
            with patch.object(protocol.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0,
                    stdout='Store chunk ../../../SkiResortSimulator/Content/Retained.uasset\n')) as retoc, \
                 patch.object(protocol.subprocess, 'Popen') as launch, \
                 patch.object(protocol, 'inspect_package', side_effect=inspect), \
                 contextlib.redirect_stdout(io.StringIO()):
                code = protocol.main(['--config', str(config), '--output', str(output), '--retoc', 'local-retoc', '--previous', str(previous)])
            self.assertEqual(code, 1)
            self.assertEqual(retoc.call_args.args[0][:4], ['local-retoc', 'list', '--path', '--hash'])
            launch.assert_not_called()
            self.assertEqual(before, {p: p.read_bytes() for p in game.rglob('*') if p.is_file()})
            report = json.loads((output / 'report.json').read_text())
            self.assertEqual(report['status'], 'incompatible')
            self.assertTrue(any(c['id'] == 'native.hubs.building' and c['status'] == 'fail' for c in report['checks']))
            self.assertTrue((output / 'contract.json').exists())
            self.assertTrue((output / 'review-template.json').exists())
            self.assertIn('/Game/Blueprints/Decorations/BP_StringLights.uasset', report['asset_diff']['removed'])

    def test_only_the_test_copy_is_modified_and_contract_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary = root / 'installed/SkiResortSimulator/Binaries/Win64'
            ue = binary / 'ue4ss'
            (ue / 'Mods/shared').mkdir(parents=True)
            (binary / 'skieogame.exe').write_bytes(b'game')
            (binary / 'api-ms-win-crt.dll').write_bytes(b'do not shadow Wine runtime')
            (ue / 'UE4SS.dll').write_bytes(b'ue4ss')
            (ue / 'UE4SS-settings.ini').write_text('[Overrides]\n+ModsFolderPaths = original-mods\nModsFolderPath = outside\nControllingModsTxt = outside/mods.txt\n')
            for part in ['Engine', 'SkiResortSimulator/Content', 'SkiResortSimulator/Plugins']:
                (root / 'installed' / part).mkdir(parents=True, exist_ok=True)
            source = root / 'mod/SkiEO-CustomMaps/Scripts'
            source.mkdir(parents=True)
            (source / 'main.lua').write_text('original entry')
            (root / 'compatibility').mkdir()
            (root / 'compatibility/ue4ss_probe.lua').write_text('return function() end')
            (root / 'map.skieomap').write_bytes(b'frozen map archive')
            output = root / 'evidence'
            output.mkdir()
            config = {'game_dir': str(root / 'installed'), 'binary_dir': str(binary), 'ue4ss_dir': str(ue)}
            contract = {'maps': [{'archive': 'map.skieomap'}]}
            before = copy.deepcopy(contract)
            original = {str(p): p.read_bytes() for p in (root / 'installed').rglob('*') if p.is_file()}
            with patch.object(protocol, 'ROOT', root):
                new_config, new_ue = protocol.prepare_live(config, contract, {'run_id': 'unique'}, output, False)
            self.assertEqual(contract, before)
            self.assertEqual(original, {str(p): p.read_bytes() for p in (root / 'installed').rglob('*') if p.is_file()})
            self.assertNotIn('ModsFolderPaths', (new_ue / 'UE4SS-settings.ini').read_text())
            self.assertNotIn('outside', (new_ue / 'UE4SS-settings.ini').read_text())
            self.assertFalse((Path(new_config['binary_dir']) / 'api-ms-win-crt.dll').exists())
            spec = json.loads((output / 'live-spec.json').read_text())
            self.assertFalse(spec['allow_maps'])
            self.assertTrue(spec['root'].endswith('/'))
            if protocol.sys.platform.startswith('linux'):
                marker = output / 'compatdata/pfx/drive_c/users/steamuser/AppData/Local/Ski-E-O/SaveGames' / spec['save_isolation']['marker']
                self.assertEqual(json.loads(marker.read_text()), {'run_id': 'unique'})
            self.assertEqual((output / 'packages/map.skieomap').read_bytes(), b'frozen map archive')
            self.assertIn('ue4ss_probe.lua', (new_ue / 'Mods/SkiEO-CustomMaps/Scripts/main.lua').read_text())

    def test_crash_in_our_process_is_reported_and_cleanup_uses_our_token(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            ue = folder / 'ue'
            ue.mkdir()
            (ue / 'crash_new.dmp').touch()
            process = Mock(pid=12345)
            report = {'checks': [], 'run_id': 'run'}
            with patch.object(protocol, 'prepare_live', return_value=({'binary_dir': str(folder)}, ue)), \
                 patch.object(protocol.desktop, 'editor_launch_plan', return_value=(['game'], {}, folder)), \
                 patch.object(protocol.desktop, 'ensure_editor_steam'), \
                 patch.object(protocol.desktop, 'stop_editor_launch') as stop, \
                 patch.object(protocol.subprocess, 'Popen', return_value=process) as launch:
                protocol.run_live({}, {'maps': []}, report, folder)
            if protocol.sys.platform.startswith('linux'):
                self.assertEqual(launch.call_args.kwargs['env']['STEAM_COMPAT_DATA_PATH'], str(folder / 'compatdata'))
            self.assertEqual(protocol.verdict(report), ('incompatible', 1))
            self.assertIn('live.crash', [x['id'] for x in report['checks']])
            self.assertEqual(stop.call_args.args, (process,))
            self.assertEqual(stop.call_args.kwargs['binary'], folder / 'skieogame.exe')
            self.assertEqual(len(stop.call_args.kwargs['token']), 32)


if __name__ == '__main__':
    unittest.main()
