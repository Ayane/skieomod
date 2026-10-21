#!/usr/bin/env python3
"""Qualify an installed game against recorded native and UE4SS contracts.

No network, installation, publication or automatic approval of a new build.
Exit codes: 0 fully reviewed, 1 incompatible, 2 incomplete/invalid evidence.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import secrets
import shutil
import struct
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tools import skieo_install as desktop, skieo_loader as loader, skieo_updates as updates
from tools import trail_rating_profile
from tools import native_layouts
from tools.custom_packages import inspect_package
from tools.compare_scenario_checkpoints import differences as checkpoint_differences


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


class PEImage:
    """Read bounded file-backed executable sections; never load native code."""
    def __init__(self, data):
        self.data = data
        if len(data) < 64 or data[:2] != b'MZ':
            raise ValueError('not a PE executable')
        pe = struct.unpack_from('<I', data, 0x3C)[0]
        if pe + 24 > len(data) or data[pe:pe+4] != b'PE\0\0':
            raise ValueError('invalid PE header')
        machine, count = struct.unpack_from('<HH', data, pe + 4)
        optional = struct.unpack_from('<H', data, pe + 20)[0]
        first = pe + 24 + optional
        if machine != 0x8664 or not 0 < count <= 96 or optional < 112 or first + count * 40 > len(data):
            raise ValueError('unsupported/truncated x64 PE header')
        if struct.unpack_from('<H', data, pe + 24)[0] != 0x20B:
            raise ValueError('PE32+ required')
        self.sections = []
        for index in range(count):
            offset = first + index * 40
            virtual_size, rva, size, raw = struct.unpack_from('<IIII', data, offset + 8)
            flags = struct.unpack_from('<I', data, offset + 36)[0]
            if raw + size > len(data):
                raise ValueError('truncated PE section')
            self.sections.append((rva, min(size, virtual_size), raw, bool(flags & 0x20000000)))

    def read(self, rva, size):
        for start, length, raw, executable in self.sections:
            if executable and start <= rva and rva + size <= start + length:
                return self.data[raw+rva-start:raw+rva-start+size]
        return b''

    def find(self, pattern):
        found = []
        for rva, size, raw, executable in self.sections:
            if not executable:
                continue
            cursor = raw
            while len(found) < 32:
                offset = self.data.find(pattern, cursor, raw + size)
                if offset < 0:
                    break
                found.append(rva + offset - raw)
                cursor = offset + 1
        return found


def check(report, name, status, detail, *, required=True, **evidence):
    assert status in {'pass', 'fail', 'pending', 'blocked'}
    report['checks'].append(dict(id=name, status=status, required=required, detail=detail, **evidence))


def verdict(report):
    checks = report['checks']
    if any(item['required'] and item['status'] == 'fail' for item in checks):
        return 'incompatible', 1
    if not checks or any(item['required'] and item['status'] != 'pass' for item in checks):
        return 'unverified', 2
    return 'compatible', 0


def inspect_guards(image, guards):
    results = []
    ratings = None
    for guard in guards:
        expected = bytes.fromhex(guard['bytes'])
        if guard.get('mode') == 'normalized_unique':
            locations = native_layouts.resolve(image, guard, guards)
            matched = len(locations) == 1
            results.append(dict(id='native.' + guard['id'], status='pass' if matched else 'fail', required=True,
                detail='unique reviewed code layout matched' if matched else 'missing, changed or ambiguous native code layout',
                expected_rva=guard['rva'], candidate_rvas=[hex(n) for n in locations],
                resolved_rva=hex(locations[0]) if matched else None,
                relocated=bool(matched and locations[0] != int(guard['rva'], 0))))
            continue
        if guard.get('mode') == 'rating_semantic':
            names={'trail_ratings.classifier':'calculate','trail_ratings.palette':'palette','trail_ratings.color':'color'}
            name=names.get(guard['id'])
            if not name or expected != trail_rating_profile.guards()[name]:
                raise ValueError('unreviewed semantic rating guard '+guard['id'])
            if ratings is None:
                ratings=trail_rating_profile.resolve(trail_rating_profile.pe_sections(image))
            rva=ratings[name]
            results.append(dict(id='native.'+guard['id'],status='pass' if rva else 'fail',required=True,
                detail='unique reviewed code and cross-references matched' if rva else 'missing, changed or ambiguous native rating contract',
                expected_rva=guard['rva'],candidate_rvas=[hex(rva)] if rva else [],
                resolved_rva=hex(rva) if rva else None,style_cache_rva=hex(ratings['style']) if ratings['style'] else None,
                relocated=bool(rva and (rva!=int(guard['rva'],0) or image.read(rva,len(expected))!=expected))))
            continue
        if len(expected) < 8 or guard.get('mode') not in {'rva', 'unique'}:
            raise ValueError('invalid native guard ' + guard['id'])
        rva = int(guard['rva'], 0)
        actual = image.read(rva, len(expected))
        locations = image.find(expected) if actual != expected or guard['mode'] == 'unique' else [rva]
        matched = len(locations) == 1 if guard['mode'] == 'unique' else actual == expected
        results.append(dict(id='native.' + guard['id'], status='pass' if matched else 'fail', required=True,
                            detail='signature matched' if matched else 'unsupported native entry point; relocation is diagnostic only',
                            expected_rva=hex(rva), actual=actual.hex(), expected=expected.hex(),
                            candidate_rvas=[hex(n) for n in locations]))
    return results


def asset_names(listing):
    names = {}
    for line in listing.splitlines():
        match = re.search(r'(\.\./\.\./\.\./.+\.uasset)\s*$', line)
        if not match:
            continue
        path = match[1].replace('../../../SkiResortSimulator/Content/', '/Game/', 1).replace('../../../Engine/Content/', '/Engine/', 1)
        # Plugin mount names depend on their descriptors. Preserve the actual
        # cooked path instead of guessing an Unreal package mount point.
        prefix = line[:match.start()].split()
        # --hash puts a full IoStore chunk hash before the path. Older path-only
        # inventories remain usable; absent content hashes are never invented.
        hashes = [word.lower() for word in prefix if re.fullmatch(r'(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})', word)]
        names[path] = hashes[-1] if hashes else None
    return names


def asset_diff(before, after):
    return {'added': sorted(after.keys() - before.keys()), 'removed': sorted(before.keys() - after.keys()),
            'changed': sorted(k for k in after.keys() & before.keys()
                              if before[k] is not None and after[k] is not None and before[k] != after[k])}


def loader_identity(source):
    files = loader.collect(source)
    return hashlib.sha256(json.dumps({k: hashlib.sha256(v).hexdigest() for k, v in sorted(files.items())},
                                     sort_keys=True).encode()).hexdigest()


def validate_contract(contract):
    if not isinstance(contract, dict) or contract.get('format') != 'skieo-compatibility-contract' or contract.get('version') != 1:
        raise ValueError('unsupported compatibility contract')
    for key in ('guards', 'maps', 'assets'):
        if not isinstance(contract.get(key), list) or not contract[key]:
            raise ValueError('empty or missing contract ' + key)
    guards = [item['id'] for item in contract['guards']]
    if len(guards) != len(set(guards)):
        raise ValueError('duplicate native guard identifiers')
    groups = {name.split('.')[0] for name in guards}
    if not {'hubs', 'staff', 'skiability', 'hub_names', 'navigation', 'snow_cpu', 'trail_ratings'} <= groups:
        raise ValueError('missing native feature guards')
    classes = contract.get('classes')
    if not isinstance(classes, dict) or not {'PlaceableActor', 'BuildingActor', 'LiftActor', 'SkiResortSaveGame'} <= classes.keys():
        raise ValueError('missing required reflected class contracts')
    maps = [item['id'] for item in contract['maps']]
    if len(maps) != len(set(maps)) or not {'community.veymont', 'community.super-saint-bernard'} <= set(maps):
        raise ValueError('both map contracts with unique identities are required')
    fields = {'buildings', 'decorations', 'lifts', 'trails', 'hubs', 'staff', 'trees'}
    for definition in contract['maps']:
        expected = definition.get('expected', {})
        if not fields <= expected.keys() or any(type(expected[key]) is not int or expected[key] < 0 for key in fields):
            raise ValueError('missing/invalid map measurements')
    if set(contract.get('manual_checks', [])) != {'rendering', 'native_save_roundtrip'}:
        raise ValueError('rendering and native save/reload reviews are mandatory')
    return contract


def inspect_static(config, contract, report, output, retoc=None, previous=None):
    binary = Path(config['binary_dir']) / 'skieogame.exe'
    ue = Path(config['ue4ss_dir']) / 'UE4SS.dll'
    utoc = Path(config['game_dir']) / 'SkiResortSimulator/Content/Paks/SkiResortSimulator-Windows.utoc'
    revision = updates.game_revision(config)
    report['game'] = revision
    report['inputs'] = {'executable': str(binary), 'utoc': str(utoc), 'ue4ss': str(ue)}
    report['fingerprints'] = {'executable': sha256(binary), 'loader': loader_identity(ROOT / 'mod/SkiEO-CustomMaps'),
                              'ue4ss': sha256(ue), 'utoc': sha256(utoc)}
    check(report, 'identity.ue4ss', 'pass' if sha256(ue) == contract['ue4ss_sha256'] else 'pending',
          'UE4SS binary must match the recorded framework build')
    check(report, 'identity.steam', 'pass' if revision else 'fail', 'Steam build and game directory must agree')
    check(report, 'identity.build', 'pass' if revision and revision['build_id'] == contract['reference_build'] else 'pending',
          'reference build: ' + contract['reference_build'] + '; a new build needs qualification', required=False)
    helper = ROOT / 'mod/SkiEO-CustomMaps/Scripts/skieo_native_terrain.dll'
    synced = sha256(helper) == contract['native_helper_sha256'] and all(
        sha256(ROOT / name) == digest for name, digest in contract['native_sources'].items())
    synced = synced and all((ROOT / name).is_file() and sha256(ROOT / name) == digest
                            for name, digest in contract.get('native_helpers', {}).items())
    check(report, 'native.contract', 'pass' if synced else 'pending',
          'recorded guards must be reviewed whenever the native helper or its sources change')
    image = PEImage(binary.read_bytes())
    report['checks'].extend(inspect_guards(image, contract['guards']))
    if retoc:
        result = subprocess.run([str(retoc), 'list', '--path', '--hash', str(utoc)],
                                capture_output=True, text=True, timeout=120, check=True)
        (output / 'assets.list').write_text(result.stdout)
        assets = asset_names(result.stdout)
        if not assets:
            raise ValueError('retoc returned no asset paths')
        missing = sorted(set(contract['assets']) - assets.keys())
        check(report, 'assets.required', 'fail' if missing else 'pass',
              f'{len(assets)} assets; {len(missing)} required resources missing', missing=missing)
        report['assets'] = assets
        if previous:
            report['asset_diff'] = asset_diff(previous.get('assets', {}), assets)
            report['asset_diff_content_coverage'] = sum(previous['assets'][name] is not None and assets[name] is not None
                for name in assets.keys() & previous['assets'].keys())
    else:
        check(report, 'assets.required', 'pending', 'supply --retoc to inspect required cooked resources')
    for definition in [*contract['maps'], *contract.get('dependencies', [])]:
        archive = ROOT / definition['archive']
        try:
            _, manifest, _ = inspect_package(archive, definition.get('kind', 'map'))
            matched = manifest['id'] == definition['id'] and manifest['metadata']['version'] == definition['version']
            report['fingerprints']['package.' + definition['id']] = sha256(archive)
            check(report, 'package.' + definition['id'], 'pass' if matched else 'fail',
                  'validated archive identity', sha256=sha256(archive))
        except (OSError, ValueError) as error:
            check(report, 'package.' + definition['id'], 'fail', str(error))


def windows_path(path):
    value = str(Path(path).resolve()).replace('\\', '/')
    return 'Z:' + value if sys.platform.startswith('linux') else value


def prepare_live(config, contract, report, output, allow_maps, interactive=False):
    """Put the executable, UE4SS, loader and saves in a fresh owned directory."""
    original = Path(config['game_dir'])
    if output.resolve().is_relative_to(original.resolve()):
        raise ValueError('the live test directory must be outside the installed game')
    game = output / 'game'
    binary = game / 'SkiResortSimulator/Binaries/Win64'
    binary.mkdir(parents=True)
    for part in ('Engine', 'SkiResortSimulator/Content', 'SkiResortSimulator/Plugins'):
        source, target = original / part, game / part
        if source.exists():
            target.symlink_to(source, target_is_directory=True)
    for source in Path(config['binary_dir']).iterdir():
        if source.is_file() and source.suffix.lower() in {'.exe', '.dll', '.txt'} and not source.name.startswith('api-ms-'):
            shutil.copy2(source, binary / source.name)
        elif source.name == 'D3D12':
            shutil.copytree(source, binary / source.name)
    ue = binary / 'ue4ss'
    ue.mkdir()
    for name in ('UE4SS.dll', 'UE4SS-settings.ini'):
        shutil.copy2(Path(config['ue4ss_dir']) / name, ue / name)
    settings = (ue / 'UE4SS-settings.ini').read_text(encoding='utf-8-sig')
    settings = re.sub(r'^[ \t]*[+-]ModsFolderPaths[^\n]*\n?', '', settings, flags=re.M)
    settings = re.sub(r'^([ \t]*(?:ModsFolderPath|ControllingModsTxt)[ \t]*=)[^\n]*', r'\1', settings, flags=re.M)
    (ue / 'UE4SS-settings.ini').write_text(settings)
    mods = ue / 'Mods'
    mods.mkdir()
    shutil.copytree(Path(config['ue4ss_dir']) / 'Mods/shared', mods / 'shared')
    source = ROOT / 'mod/SkiEO-CustomMaps'
    destination = mods / loader.NAME
    for name, data in loader.collect(source).items():
        path = destination / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    (destination / 'enabled.txt').touch()
    # The dependency is local and pinned; no Workshop download is allowed here.
    for definition in contract.get('dependencies', []):
        dependency = ROOT / definition['archive']
        shutil.copy2(dependency, mods / dependency.name)
    spec = dict(json.loads(json.dumps(contract)), run_id=report['run_id'], allow_maps=allow_maps,
                root=windows_path(output) + '/', settle_seconds=15, map_timeout=300, interactive=interactive)
    if sys.platform.startswith('linux'):
        # The native SaveDumpLibrary ignores Unreal's -UserDir and uses
        # LocalAppData. A separate Proton prefix isolates that path too.
        directory = output / 'compatdata/pfx/drive_c/users/steamuser/AppData/Local/Ski-E-O/SaveGames'
        directory.mkdir(parents=True)
        marker = '.skieo-compatibility-' + report['run_id'] + '.json'
        (directory / marker).write_text(json.dumps({'run_id': report['run_id']}))
        spec['save_isolation'] = {
            'directory': 'C:/users/steamuser/AppData/Local/Ski-E-O/SaveGames', 'marker': marker,
        }
    (output / 'packages').mkdir()
    (output / 'review').mkdir()
    for definition in spec['maps']:
        source = ROOT / definition['archive']
        target = output / 'packages' / source.name
        shutil.copy2(source, target)
        definition['archive'] = windows_path(target)
    (output / 'live-spec.json').write_text(json.dumps(spec))
    probe = output / 'ue4ss_probe.lua'
    shutil.copy2(ROOT / 'compatibility/ue4ss_probe.lua', probe)
    entry = destination / 'Scripts/main.lua'
    with entry.open('a') as stream:
        stream.write('\nassert(loadfile(' + json.dumps(windows_path(probe), ensure_ascii=False)
                     + '))()(Runtime,' + json.dumps(windows_path(output / 'live-spec.json'), ensure_ascii=False) + ')\n')
    return {**config, 'game_dir': str(game), 'binary_dir': str(binary)}, ue


def ingest_live(report, data, contract):
    """Validate required evidence independently of the probe's overall status."""
    if not isinstance(data, dict) or data.get('run_id') != report['run_id'] or data.get('complete') is not True:
        check(report, 'live.session', 'fail', 'missing, incomplete or stale UE4SS result')
        return
    items = data.get('checks', [])
    expected = {'live.reflection', 'live.heartbeat', 'live.isolation'}
    if data.get('error'):
        check(report, 'live.exception', 'fail', str(data['error']))
    if data.get('maps_enabled') is True:
        expected |= {'live.' + definition['id'] + '.' + stage for definition in contract['maps']
                     for stage in ('counts', 'variants', 'gc')}
    else:
        check(report, 'live.maps', 'blocked', 'native preflight failed; no map was started')
    valid = {}
    for item in items:
        if isinstance(item, dict) and item.get('id') in expected and item.get('status') in {'pass', 'fail'}:
            if item['id'] in valid:
                check(report, 'live.session', 'fail', 'duplicate live evidence')
                return
            valid[item['id']] = item
    for name in sorted(expected):
        item = valid.get(name)
        if not item:
            check(report, name, 'fail', 'probe did not provide this required measurement')
        else:
            check(report, name, item['status'], item.get('detail', ''), evidence=item.get('evidence'))


def crash_files(ue, output):
    return [path for root in (ue, output / 'userdata') for path in root.rglob('*')
            if path.is_file() and path.suffix.lower() in {'.dmp', '.mdmp'}]


def inspect_native_log(report, log_path, maps_ran):
    if not maps_ran:
        check(report, 'live.native_errors', 'blocked', 'native map operations were not reached')
    elif not log_path.is_file():
        check(report, 'live.native_errors', 'pending', 'native runtime log is missing')
    else:
        lines = [line for line in log_path.read_text(errors='replace').splitlines()
                 if re.search(r'unsupported .*layout|unsupported .*build|terrain loading failed|map script failed', line, re.I)]
        check(report, 'live.native_errors', 'fail' if lines else 'pass',
              'native guard and map-loader errors', lines=lines[-30:])


def run_live(config, contract, report, output, *, timeout=900, interactive=False):
    allow_maps = not any(x['required'] and x['status'] != 'pass' for x in report['checks'])
    live_config, ue = prepare_live(config, contract, report, output, allow_maps, interactive)
    token = secrets.token_hex(16)
    arguments, environment, cwd = desktop.editor_launch_plan(live_config, token)
    desktop.ensure_editor_steam(environment)
    if sys.platform.startswith('linux'):
        environment['STEAM_COMPAT_DATA_PATH'] = str(output / 'compatdata')
    arguments += ['-windowed', '-ResX=1280', '-ResY=720', '-nosplash', '-NoSound',
                  '-stdout', '-FullStdOutLogOutput',
                  '-UserDir=' + windows_path(output / 'userdata') + '/']
    # Avoid Steam Cloud / native slot reuse by verifying the actual save path
    # in the UE4SS probe before it is allowed to open a map.
    environment['WINEDEBUG'] = '-all'
    process = None
    keep_open = False
    maps_ran = False
    started = time.monotonic()
    try:
        with (output / 'process.log').open('w') as log:
            process = subprocess.Popen(arguments, env=environment, cwd=cwd, stdout=log,
                                       stderr=subprocess.STDOUT, start_new_session=True)
        while time.monotonic() - started < timeout:
            if crash_files(ue, output):
                check(report, 'live.crash', 'fail', 'new crash dump in the isolated test process')
                break
            result = output / 'live-result.json'
            if result.is_file():
                try:
                    data = json.loads(result.read_text())
                except (ValueError, OSError):
                    data = {}
                if data.get('complete'):
                    ingest_live(report, data, contract)
                    maps_ran = data.get('maps_enabled') is True
                    keep_open = interactive and data.get('maps_enabled') is True and all(
                        item['status'] == 'pass' or not item['required'] for item in report['checks'])
                    break
            # Proton can exit while its detached game is still starting.
            if process.poll() is not None and time.monotonic() - started > 60:
                if not desktop.editor_game_pids(token, Path(live_config['binary_dir']) / 'skieogame.exe'):
                    check(report, 'live.process', 'fail', 'game exited before completing the protocol', exit_code=process.poll())
                    break
            time.sleep(0.5)
        else:
            check(report, 'live.timeout', 'fail', 'bounded UE4SS protocol timeout')
    finally:
        # Only our own token/executable/process group may be terminated.
        if process and not keep_open:
            desktop.stop_editor_launch(process, token=token, binary=Path(live_config['binary_dir']) / 'skieogame.exe')
        if (ue / 'UE4SS.log').is_file():
            shutil.copy2(ue / 'UE4SS.log', output / 'UE4SS.log')
    if crash_files(ue, output) and not any(x['id'] == 'live.crash' for x in report['checks']):
        check(report, 'live.crash', 'fail', 'game crashed during protocol shutdown')
    result = output / 'live-result.json'
    if not result.exists():
        check(report, 'live.result', 'fail', 'UE4SS did not produce a result')
    log_path = output / 'UE4SS.log'
    inspect_native_log(report, log_path, maps_ran)
    if keep_open:
        if any(item['required'] and item['status'] == 'fail' for item in report['checks']):
            desktop.stop_editor_launch(process, token=token, binary=Path(live_config['binary_dir']) / 'skieogame.exe')
            return
        print('Isolated game retained for manual review. Close with --close --output ' + str(output), flush=True)


def apply_review(report, contract, review, output):
    if review is not None and (not isinstance(review, dict) or not isinstance(review.get('checks'), dict)):
        raise ValueError('manual review must contain a checks object')
    for name in contract['manual_checks']:
        entry = (review or {}).get('checks', {}).get(name, {})
        if not isinstance(entry, dict):
            entry = {}
        identity = review and review.get('run_id') == report['run_id'] and review.get('fingerprints') == report['fingerprints']
        artifacts = entry.get('artifacts', [])
        evidence_ok = isinstance(artifacts, list) and bool(artifacts)
        for artifact in artifacts if isinstance(artifacts, list) else []:
            if not isinstance(artifact, dict):
                evidence_ok = False
                break
            if not isinstance(artifact.get('path'), str):
                evidence_ok = False
                break
            path = (output / artifact['path']).resolve()
            if not path.is_relative_to(output.resolve()) or not path.is_file() or sha256(path) != artifact.get('sha256'):
                evidence_ok = False
        if not identity or not evidence_ok or not entry.get('note') or entry.get('status') not in {'pass', 'fail'}:
            check(report, 'review.' + name, 'pending', 'review with this run identity, notes and hashed artifacts required')
        elif name == 'native_save_roundtrip' and entry['status'] == 'pass':
            pairs = entry.get('roundtrips', [])
            required = {m['id']: m['version'] for m in contract['maps']}
            covered, failures = set(), []
            try:
                for pair in pairs:
                    key = pair['map_id']
                    if key not in required or key in covered or not pair.get('slot'):
                        raise ValueError('unexpected/duplicate map or missing native save slot')
                    paths = [pair['before'], pair['after']]
                    if any(path not in [a['path'] for a in artifacts] for path in paths):
                        raise ValueError('checkpoint is not a hashed review artifact')
                    before, after = [json.loads((output / path).read_text()) for path in paths]
                    if before.get('map_id') != key or before.get('map_version') != required[key]:
                        raise ValueError('checkpoint belongs to another map/version')
                    failures.extend(checkpoint_differences(before, after))
                    for label, checkpoint in [('before', before), ('after', after)]:
                        world = checkpoint.get('compatibility_world')
                        if not isinstance(world, dict) or not isinstance(world.get('placeables'), dict):
                            raise ValueError(label + ': missing native world/placeable measurements')
                    a, b = before['compatibility_world'], after['compatibility_world']
                    for field in ('buildings', 'decorations', 'lifts', 'trails', 'hubs', 'staff', 'trees', 'variants', 'saved_variants'):
                        if field not in a or field not in b or a[field] != b[field]:
                            failures.append('world.' + field + ': changed or missing')
                    if a['placeables'].keys() != b['placeables'].keys() or not a['placeables']:
                        failures.append('world.placeables: native identities changed or missing')
                    for identifier in a['placeables'].keys() & b['placeables'].keys():
                        first, second = a['placeables'][identifier], b['placeables'][identifier]
                        for field in ('class', 'name', 'variant'):
                            if first.get(field) != second.get(field):
                                failures.append('placeable ' + identifier + ': ' + field + ' changed')
                        for axis in ('X', 'Y', 'Z'):
                            x, y = first.get('position', {}).get(axis), second.get('position', {}).get(axis)
                            if not isinstance(x, (int, float)) or not isinstance(y, (int, float)) or not abs(x-y) <= 1:
                                failures.append('placeable ' + identifier + ': position.' + axis + ' changed or missing')
                    covered.add(key)
                if covered != required.keys():
                    raise ValueError('native save/reload checkpoints are required for both maps')
            except (OSError, ValueError, KeyError, TypeError) as error:
                failures.append(str(error))
            check(report, 'review.' + name, 'fail' if failures else 'pass',
                  '; '.join(failures) if failures else entry['note'], artifacts=artifacts)
        else:
            check(report, 'review.' + name, entry['status'], entry['note'], artifacts=artifacts)


def save_report(report, output):
    report['status'], code = verdict(report)
    (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    lines = ['# Game compatibility: ' + report['status'], '',
             '- Run: `' + report['run_id'] + '`',
             '- Steam build: ' + str((report.get('game') or {}).get('build_id', 'unknown')), '',
             '| Check | Result | Details |', '| --- | --- | --- |']
    for item in report['checks']:
        detail = item['detail'].replace('|', '\\|').replace('\n', ' ')
        lines.append(f"| {item['id']} | {item['status']} | {detail} |")
    if report.get('asset_diff'):
        lines.extend(['', '## Asset changes', '', 'Content hashes compared: ' + str(report['asset_diff_content_coverage']), ''])
        for category, paths in report['asset_diff'].items():
            lines.extend([f'### {category}: {len(paths)}', ''])
            lines.extend('- ' + path for path in paths[:30])
            if len(paths) > 30:
                lines.append('- Remaining paths are recorded in report.json.')
            lines.append('')
    (output / 'report.md').write_text('\n'.join(lines) + '\n')
    template = output / 'review-template.json'
    if not template.exists():
        pairs = []
        for definition in report.get('tested_maps', []):
            label = definition['id'].replace('.', '_').replace('-', '_')
            pairs.append({'map_id': definition['id'], 'slot': '',
                          'before': 'review/' + label + '_before.json', 'after': 'review/' + label + '_after.json'})
        template.write_text(json.dumps({'run_id': report['run_id'], 'fingerprints': report.get('fingerprints', {}),
            'checks': {'rendering': {'status': 'pending', 'note': '', 'artifacts': []},
                       'native_save_roundtrip': {'status': 'pending', 'note': '', 'artifacts': [], 'roundtrips': pairs}}}, indent=2) + '\n')
    return code


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, help='skieomod config.json (default: installed configuration)')
    parser.add_argument('--contract', type=Path, default=ROOT / 'compatibility/game-contract.json')
    parser.add_argument('--output', type=Path, help='new, empty evidence directory')
    parser.add_argument('--retoc', type=Path, help='local retoc executable; nothing is downloaded')
    parser.add_argument('--previous', type=Path, help='previous report.json for asset deltas')
    parser.add_argument('--live', action='store_true', help='launch a separate UE4SS game with isolated saves')
    parser.add_argument('--interactive', action='store_true', help='keep a successful isolated game open for manual review')
    parser.add_argument('--close', action='store_true', help='ask UE4SS to quit the test game in --output')
    parser.add_argument('--timeout', type=int, default=900, help='live process deadline in seconds')
    parser.add_argument('--review', type=Path, help='finish an existing run using manual evidence; requires --output')
    args = parser.parse_args(argv)
    if args.timeout < 30 or args.timeout > 3600:
        parser.error('--timeout must be 30..3600 seconds')
    if args.interactive and not args.live:
        parser.error('--interactive requires --live')
    if args.close and (not args.output or args.live or args.review):
        parser.error('--close requires --output and cannot run tests or apply a review')
    output = (args.output or ROOT / 'build/compatibility' / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + secrets.token_hex(3))).resolve()
    try:
        if args.close:
            report = json.loads((output / 'report.json').read_text())
            desktop.atomic_json(output / 'stop-request.json', {'run_id': report['run_id']})
            print('UE4SS close request written for ' + report['run_id'])
            return 0
        contract = validate_contract(json.loads(args.contract.read_text()))
        if args.review:
            if not args.output:
                raise ValueError('--review requires the original --output')
            report = json.loads((output / 'report.json').read_text())
            if report['contract_sha256'] != sha256(args.contract):
                raise ValueError('the contract changed since this run')
            report['checks'] = [item for item in report['checks'] if not item['id'].startswith('review.')]
            unchanged = bool(report.get('inputs')) and all(
                Path(path).is_file() and sha256(path) == report['fingerprints'][name] for name, path in report.get('inputs', {}).items())
            check(report, 'review.inputs', 'pass' if unchanged else 'fail', 'input binaries and content still match this run')
            ue = output / 'game/SkiResortSimulator/Binaries/Win64/ue4ss'
            check(report, 'review.crashes', 'fail' if crash_files(ue, output) else 'pass', 'no crash dump appeared during manual review')
            apply_review(report, contract, json.loads(args.review.read_text()), output)
        else:
            if output.exists() and any(output.iterdir()):
                raise ValueError('refusing to reuse a nonempty evidence directory')
            output.mkdir(parents=True, exist_ok=True)
            report = {'format': 'skieo-compatibility-report', 'version': 1, 'run_id': secrets.token_hex(16),
                      'created_utc': datetime.now(timezone.utc).isoformat(), 'contract_sha256': sha256(args.contract), 'checks': [],
                      'tested_maps': [{'id': m['id'], 'version': m['version']} for m in contract['maps']]}
            shutil.copy2(args.contract, output / 'contract.json')
            config = json.loads(args.config.read_text()) if args.config else desktop.load_config()
            previous = json.loads(args.previous.read_text()) if args.previous else None
            if previous is None and contract.get('reference_inventory'):
                inventory = ROOT / contract['reference_inventory']
                if sha256(inventory) != contract['reference_inventory_sha256']:
                    raise ValueError('reference asset inventory changed without review')
                previous = json.loads(inventory.read_text())
            retoc = args.retoc
            default_retoc = ROOT / 'build/nanite/retoc-target/release/retoc'
            if not retoc and default_retoc.is_file():
                retoc = default_retoc
            try:
                inspect_static(config, contract, report, output, retoc, previous)
                if args.live:
                    run_live(config, contract, report, output, timeout=args.timeout, interactive=args.interactive)
                else:
                    check(report, 'live.session', 'pending', 'run with --live for UE4SS reflection, maps and GC')
                unchanged = sha256(Path(config['binary_dir']) / 'skieogame.exe') == report['fingerprints']['executable']
                unchanged &= sha256(Path(config['game_dir']) / 'SkiResortSimulator/Content/Paks/SkiResortSimulator-Windows.utoc') == report['fingerprints']['utoc']
                check(report, 'identity.stable', 'pass' if unchanged else 'fail', 'game files must not change during qualification')
            except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
                check(report, 'execution', 'pending', str(error))
            apply_review(report, contract, None, output)
        code = save_report(report, output)
        print(report['status'] + ': ' + str(output / 'report.md'))
        for item in report['checks']:
            if item['status'] == 'fail':
                print('FAIL ' + item['id'] + ': ' + item['detail'])
        return code
    except (OSError, ValueError, KeyError) as error:
        print('Protocol error: ' + str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
