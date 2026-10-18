#!/usr/bin/env python3
"""Prepare, check and publish a versioned Custom Map release through SSH."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.custom_maps import semver_compare
from tools.skieo_install import UE4SS_ARCHIVE, read_ue4ss_archive
from tools.skieo_loader import read_archive, update_feed
from deployment.publish_loader_updates import publication_files, validate_publication_files
from deployment import discord_releases as discord

HOST = 'root@skieomod.emillon.fr'
REMOTE_DIRECTORY = '/opt/custom-map/current/downloads'
PUBLIC_FEED = 'https://skieomod.emillon.fr/downloads/loader-latest.json'


def parser():
    command = argparse.ArgumentParser(description=__doc__, epilog='Example: python3 deployment/release_custom_map.py 1.17.1')
    command.add_argument('version', help='new release version, for example 1.17.1')
    mode = command.add_mutually_exclusive_group()
    mode.add_argument('--prepare-only', action='store_true', help='update versions, build and check without contacting the server')
    mode.add_argument('--publish-only', action='store_true', help='check and publish existing artifacts without changing sources or rebuilding')
    command.add_argument('--output-dir', type=Path, help='artifact directory (default: build/release-VERSION)')
    command.add_argument('--ue4ss-archive', type=Path, help='tested UE4SS ZIP (default: retained ZIP in build/custom-map-downloads)')
    command.add_argument('--no-build-isolation', action='store_true', help='build offline with installed setuptools>=77 and wheel')
    command.add_argument('--host', default=HOST, help='SSH destination (default: %(default)s)')
    command.add_argument('--remote-directory', default=REMOTE_DIRECTORY, help='served downloads directory (default: %(default)s)')
    command.add_argument('--ssh-config', type=Path, help='SSH configuration file passed to ssh -F')
    command.add_argument('--known-hosts', type=Path, help='known-hosts file; SSH host verification stays enabled')
    command.add_argument('--public-feed', default=PUBLIC_FEED, help='HTTPS feed to verify after publication')
    command.add_argument('--skip-discord', action='store_true', help='skip announcements even when a webhook is configured')
    return command


def local_path(path):
    return path.expanduser().resolve()


def run(arguments, title):
    print('\n' + title, flush=True)
    subprocess.run(list(map(str, arguments)), cwd=ROOT, check=True)


def version_changes(version):
    """Validate both version declarations before changing either source file."""
    changes = []
    for path, pattern in [(ROOT / 'pyproject.toml', r'(?m)^(version = ")([^"\r\n]+)(")$'),
                          (ROOT / 'tools/skieo_loader.py', r"(?m)^(VERSION = ')([^'\r\n]+)(')$")]:
        before = path.read_bytes()
        text = before.decode('utf-8')
        matches = list(re.finditer(pattern, text))
        if len(matches) != 1:
            raise ValueError('Expected exactly one release version in ' + str(path))
        match = matches[0]
        if semver_compare(version, match[2]) < 0:
            raise ValueError('Refusing to reduce the version in ' + str(path))
        after = (text[:match.start(2)] + version + text[match.end(2):]).encode('utf-8')
        changes.append((path, before, after))
    return changes


def write_versions(changes):
    updated = []
    try:
        for path, before, after in changes:
            if path.read_bytes() != before:
                raise ValueError('Version source changed during preparation: ' + str(path))
            if before != after:
                path.write_bytes(after)
                updated.append((path, before, after))
    except Exception:
        for path, before, after in reversed(updated):
            if path.read_bytes() == after:
                path.write_bytes(before)
        raise


def ssh_arguments(args):
    command = ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10']
    if args.ssh_config:
        command += ['-F', str(local_path(args.ssh_config))]
    if args.known_hosts:
        command += ['-o', 'UserKnownHostsFile=' + str(local_path(args.known_hosts))]
    return command


def preflight(args):
    """Read server state before building; never change server permissions."""
    source = '''import json, os, pathlib, sys
directory = pathlib.Path(sys.argv[1]).resolve(strict=True)
if not directory.is_dir() or not os.access(directory, os.W_OK):
    raise RuntimeError("Downloads directory is not writable")
index = directory / "pypi" / "skieo-custom-map"
parent = index
while not parent.exists():
    parent = parent.parent
if not parent.is_dir() or not os.access(parent, os.W_OK):
    raise RuntimeError("Package index directory is not writable")
feed = directory / "loader-latest.json"
print(json.dumps({"release": json.loads(feed.read_text())["release"] if feed.is_file() else None}))
'''
    print('\nChecking SSH access and the published version on ' + args.host, flush=True)
    remote = 'python3 -c ' + shlex.quote(source) + ' ' + shlex.quote(args.remote_directory)
    result = subprocess.run([*ssh_arguments(args), args.host, remote], cwd=ROOT, check=True, stdout=subprocess.PIPE, text=True)
    release = json.loads(result.stdout)['release']
    if release and semver_compare(args.version, release) < 0:
        raise ValueError('Server already publishes a newer version: ' + release)
    return release


def check_artifacts(folder, version):
    feed = json.loads((folder / 'loader-latest.json').read_text(encoding='utf-8'))
    if feed.get('release') != version:
        raise ValueError('Artifacts do not match requested version ' + version)
    archive = folder / ('CustomMap-Mod-' + version + '.zip')
    _, record = read_archive(archive)
    if update_feed(archive, record) != feed:
        raise ValueError('Release feed differs from the checked loader archive')
    for name in ('skieo_custom_map-' + version + '-py3-none-any.whl', 'CustomMap-Tools.zip', 'Getting-Started-' + version + '.md'):
        if not (folder / name).is_file():
            raise ValueError('Missing release artifact: ' + name)
    read_ue4ss_archive(folder / UE4SS_ARCHIVE)
    validate_publication_files(publication_files(folder, version))
    return feed


def verify_publication(url, expected):
    print('\nChecking the public HTTPS release feed', flush=True)
    for attempt in range(3):
        try:
            request = Request(url, headers={'Cache-Control': 'no-cache', 'User-Agent': 'skieomod-release/' + expected['release']})
            with urlopen(request, timeout=30) as response:
                data = response.read(1024 * 1024 + 1)
            if len(data) > 1024 * 1024 or json.loads(data) != expected:
                raise ValueError('Public release feed differs from the local release')
            return
        except (URLError, OSError, ValueError) as error:
            if attempt == 2:
                raise RuntimeError('Publication completed, but HTTPS verification failed: ' + str(error)) from error
            time.sleep(2)


def release(args):
    if not re.fullmatch(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)', args.version):
        raise ValueError('Use a release version such as 1.17.1 or 1.18.0')
    semver_compare(args.version, args.version)
    if not args.public_feed.startswith('https://'):
        raise ValueError('--public-feed must use HTTPS')
    folder = local_path(args.output_dir) if args.output_dir else ROOT / 'build' / ('release-' + args.version)
    changelog = folder / ('Changelog-' + args.version + '.md')
    notes_source = changelog if args.publish_only and changelog.is_file() else ROOT / 'CHANGELOG.md'
    # Missing notes must fail before version changes or server publication.
    discord.release_notes(notes_source, args.version)
    build = ROOT / 'tools/build_custom_map_release.py'
    checker = ROOT / 'tests/check_skieomod_distribution.py'
    publisher = ROOT / 'deployment/publish_loader_updates.py'
    for script in (checker, publisher, *([] if args.publish_only else [build])):
        if not script.is_file():
            raise ValueError('Missing release script: ' + str(script))
    if not args.publish_only:
        changes = version_changes(args.version)
        ue4ss = local_path(args.ue4ss_archive) if args.ue4ss_archive else ROOT / 'build/custom-map-downloads' / UE4SS_ARCHIVE
        if not ue4ss.is_file() and (folder / UE4SS_ARCHIVE).is_file() and not args.ue4ss_archive:
            ue4ss = folder / UE4SS_ARCHIVE
        read_ue4ss_archive(ue4ss)
    else:
        check_artifacts(folder, args.version)
    if not args.prepare_only:
        preflight(args)
    if not args.publish_only:
        write_versions(changes)
        print('Source versions: ' + args.version, flush=True)
        command = [sys.executable, build, '--output-dir', folder, '--ue4ss-archive', ue4ss]
        if args.no_build_isolation:
            command.append('--no-build-isolation')
        run(command, 'Building loader, tools, wheel and separate featured maps')
    expected = check_artifacts(folder, args.version)
    run([sys.executable, checker, folder / ('skieo_custom_map-' + args.version + '-py3-none-any.whl'),
         '--loader-archive', folder / ('CustomMap-Mod-' + args.version + '.zip')], 'Checking the distribution in an isolated environment')
    folder.mkdir(parents=True, exist_ok=True)
    if not changelog.is_file():
        changelog.write_bytes(notes_source.read_bytes())
    preview = discord.payload(changelog, args.version)
    (folder / 'discord-announcement-preview.json').write_text(json.dumps(preview, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    if args.prepare_only:
        print('\nRelease ' + args.version + ' prepared and checked in ' + str(folder) + '. Nothing published.', flush=True)
        return
    command = [sys.executable, publisher, folder, '--host', args.host, '--remote-directory', args.remote_directory]
    if args.ssh_config:
        command += ['--ssh-config', local_path(args.ssh_config)]
    if args.known_hosts:
        command += ['--known-hosts', local_path(args.known_hosts)]
    run(command, 'Publishing release through SSH')
    verify_publication(args.public_feed, expected)
    print('\nRelease ' + args.version + ' published and verified on ' + args.host, flush=True)
    if os.environ.get(discord.WEBHOOK_ENV) and not args.skip_discord:
        try:
            receipt = discord.announce(args.version, changelog)
        except (OSError, ValueError, discord.NotificationError) as error:
            raise RuntimeError('Release ' + args.version + ' is already published and verified; '
                               'Discord announcement failed: ' + str(error) + '. '
                               'Retry deployment/discord_releases.py without republishing the release.') from error
        print('Discord announcement confirmed: ' + receipt['message_id'], flush=True)
    else:
        print('Discord announcement skipped: no webhook configured or --skip-discord selected.', flush=True)


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        release(args)
    except subprocess.CalledProcessError as error:
        print('Release stopped: command failed (exit ' + str(error.returncode) + ').', file=sys.stderr)
        return 1
    except (OSError, ValueError, RuntimeError) as error:
        print('Release stopped: ' + str(error), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print('Release interrupted.', file=sys.stderr)
        return 130
    return 0


if __name__ == '__main__':
    sys.exit(main())
