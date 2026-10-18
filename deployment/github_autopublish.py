#!/usr/bin/env python3
"""Poll public GitHub releases and atomically deploy a checked server bundle."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

REPOSITORY = 'Ayane/skieomod'
ORIGIN = 'https://skieomod.emillon.fr'
MAX_BUNDLE = 512 * 1024 * 1024
MAX_EXPANDED = 2 * 1024 * 1024 * 1024


def version_key(version):
    if not isinstance(version, str) or not re.fullmatch(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)', version):
        raise ValueError('Expected a stable X.Y.Z version')
    return tuple(map(int, version.split('.')))


def request(url):
    return Request(url, headers={'User-Agent': 'skieomod-autopublish', 'Cache-Control': 'no-cache',
                                 'Accept': 'application/vnd.github+json'})


def read_json(url):
    with urlopen(request(url), timeout=30) as response:
        content = response.read(4 * 1024 * 1024 + 1)
    if len(content) > 4 * 1024 * 1024:
        raise ValueError('JSON response is too large')
    return json.loads(content)


def select_asset(release):
    if release.get('draft') or release.get('prerelease'):
        raise ValueError('Only published stable releases can be deployed')
    version = release['tag_name'].removeprefix('v')
    version_key(version)
    if release['tag_name'] != 'v' + version:
        raise ValueError('Expected a vX.Y.Z release tag')
    name = 'skieomod-server-' + version + '.tar.gz'
    assets = [asset for asset in release['assets'] if asset['name'] == name]
    if len(assets) != 1:
        raise ValueError('Release needs exactly one server bundle: ' + name)
    asset = assets[0]
    expected_url = f'https://github.com/{REPOSITORY}/releases/download/v{version}/{name}'
    if (asset.get('state') != 'uploaded' or asset.get('browser_download_url') != expected_url
            or not isinstance(asset.get('size'), int) or not 0 < asset['size'] <= MAX_BUNDLE
            or not re.fullmatch(r'sha256:[0-9a-f]{64}', asset.get('digest') or '')):
        raise ValueError('Invalid GitHub bundle URL, size or SHA-256 digest')
    return version, asset


def download(asset, path):
    digest = hashlib.sha256()
    size = 0
    with urlopen(request(asset['browser_download_url']), timeout=120) as response, path.open('xb') as target:
        while chunk := response.read(1024 * 1024):
            size += len(chunk)
            if size > asset['size']:
                raise ValueError('Bundle exceeds its declared size')
            digest.update(chunk)
            target.write(chunk)
    if size != asset['size'] or 'sha256:' + digest.hexdigest() != asset['digest']:
        raise ValueError('Bundle size or checksum mismatch')


def extract_bundle(path, target, version):
    total = 0
    names = set()
    with tarfile.open(path, 'r:gz') as archive:
        for member in archive:
            relative = PurePosixPath(member.name)
            if (not member.isfile() or relative.is_absolute() or '..' in relative.parts
                    or not relative.parts or relative.parts[0] not in {
                        'release.json', 'deployment', 'repository', 'tools', 'schemas', 'docs',
                        'pyproject.toml', 'LICENSE', 'THIRD_PARTY_NOTICES.md', 'release-artifacts'}
                    or relative.as_posix() in names):
                raise ValueError('Unsafe or duplicate bundle member: ' + member.name)
            names.add(relative.as_posix())
            total += member.size
            if total > MAX_EXPANDED or len(names) > 20000:
                raise ValueError('Expanded bundle is too large')
            destination = target.joinpath(*relative.parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.extractfile(member) as source, destination.open('xb') as output:
                shutil.copyfileobj(source, output)
            destination.chmod(0o644)
    metadata = json.loads((target / 'release.json').read_text())
    if (metadata.get('format') != 'skieomod-server-v1' or metadata.get('version') != version
            or not re.fullmatch(r'[0-9a-f]{40}', metadata.get('commit') or '')):
        raise ValueError('Server bundle does not match its GitHub release')
    for name in ['repository/web/dist/browser/index.html', 'repository/server/app.py',
                 'repository/server/requirements.txt', 'deployment/custom-map.service',
                 'deployment/nginx.conf', 'deployment/publish_loader_updates.py']:
        if not (target / name).is_file():
            raise ValueError('Missing server file: ' + name)
    return metadata


def run(*command):
    subprocess.run(list(map(str, command)), check=True)


def switch_link(current, destination):
    temporary = current.with_name('.current-next')
    temporary.unlink(missing_ok=True)
    temporary.symlink_to(destination)
    os.replace(temporary, current)


def verify_publication(version):
    for attempt in range(10):
        try:
            if read_json(ORIGIN + '/api/v1/health').get('status') != 'ok':
                raise ValueError('Repository health check failed')
            if read_json(ORIGIN + '/downloads/loader-latest.json').get('release') != version:
                raise ValueError('Public feed differs from deployed release')
            with urlopen(request(ORIGIN + '/'), timeout=30) as response:
                if response.status != 200:
                    raise ValueError('Website health check failed')
            return
        except (OSError, ValueError):
            if attempt == 9:
                raise
            time.sleep(2)


def activate(stage, current, *, service=Path('/etc/systemd/system/custom-map.service'),
             nginx=Path('/etc/nginx/sites-available/custom-map')):
    """Keep both the old environment and the old downloads available for rollback."""
    previous = current.resolve(strict=True)
    old_service, old_nginx = service.read_bytes(), nginx.read_bytes()
    try:
        service.write_bytes((stage / 'deployment/custom-map.service').read_bytes())
        nginx.write_bytes((stage / 'deployment/nginx.conf').read_bytes())
        run('nginx', '-t')
        switch_link(current, stage)
        run('systemctl', 'daemon-reload')
        run('systemctl', 'restart', 'custom-map.service')
        run('systemctl', 'reload', 'nginx')
        verify_publication(json.loads((stage / 'release.json').read_text())['version'])
    except BaseException:
        switch_link(current, previous)
        service.write_bytes(old_service)
        nginx.write_bytes(old_nginx)
        run('systemctl', 'daemon-reload')
        run('nginx', '-t')
        run('systemctl', 'restart', 'custom-map.service')
        run('systemctl', 'reload', 'nginx')
        print('Deployment failed; previous release restored.', file=sys.stderr, flush=True)
        raise


def publish(root, state, check_only=False):
    try:
        release = read_json(f'https://api.github.com/repos/{REPOSITORY}/releases/latest')
    except HTTPError as error:
        if error.code == 404:
            print('No stable GitHub release published yet.', flush=True)
            return
        raise
    version, asset = select_asset(release)
    current = root / 'current'
    installed = json.loads((current / 'downloads/loader-latest.json').read_text())['release']
    if version_key(version) <= version_key(installed):
        print(f'Up to date: {installed}; GitHub: {version}.', flush=True)
        return
    print(f'New checked release: {installed} -> {version}.', flush=True)
    if check_only:
        return
    stage = root / 'releases' / ('github-' + version + '-' + str(asset['id']))
    if stage.exists():
        # A previous failed attempt is never active; rebuild its staging directory.
        if stage.resolve() == current.resolve():
            raise ValueError('Refusing to overwrite the active release')
        shutil.rmtree(stage)
    stage.mkdir(parents=True)
    try:
        with tempfile.TemporaryDirectory(dir=state) as temporary:
            bundle = Path(temporary) / 'server.tar.gz'
            download(asset, bundle)
            metadata = extract_bundle(bundle, stage, version)
        shutil.copytree(current / 'downloads', stage / 'downloads', symlinks=True, copy_function=os.link)
        run(sys.executable, stage / 'deployment/publish_loader_updates.py', stage / 'release-artifacts',
            '--local-directory', stage / 'downloads')
        run(sys.executable, '-m', 'venv', stage / '.venv')
        run(stage / '.venv/bin/python', '-m', 'pip', 'install', '--disable-pip-version-check',
            '-r', stage / 'repository/server/requirements.txt')
        activate(stage, current)
        receipt = {**metadata, 'release_id': release['id'], 'asset_id': asset['id'], 'digest': asset['digest']}
        temporary = state / 'last-success.tmp'
        temporary.write_text(json.dumps(receipt, indent=2) + '\n')
        os.replace(temporary, state / 'last-success.json')
        print(f'Published {version} from {metadata["commit"]}.', flush=True)
    finally:
        if stage.exists() and stage.resolve() != current.resolve():
            shutil.rmtree(stage)


def main(argv=None):
    import fcntl  # The polling service runs on Linux; helpers can be tested elsewhere.
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('/opt/custom-map'))
    parser.add_argument('--state', type=Path, default=Path('/var/lib/skieomod-autopublish'))
    parser.add_argument('--check', action='store_true', help='report the available version without deploying')
    args = parser.parse_args(argv)
    args.state.mkdir(parents=True, exist_ok=True)
    with (args.state / 'publish.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print('A publication is already running.', flush=True)
            return 0
        try:
            publish(args.root, args.state, args.check)
        except (OSError, ValueError, KeyError, tarfile.TarError, subprocess.CalledProcessError) as error:
            print('Publication stopped: ' + str(error), file=sys.stderr, flush=True)
            return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
