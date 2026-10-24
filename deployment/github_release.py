#!/usr/bin/env python3
"""GitHub Actions helpers for publishing a new checked source version."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.request import urlopen
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from deployment.discord_releases import release_notes
from deployment.github_autopublish import version_key
from tools.skieo_install import UE4SS_ARCHIVE, UE4SS_URL, UE4SS_UPSTREAM_URL, read_ue4ss_archive


def gh(*arguments):
    return subprocess.check_output(['gh', *arguments], cwd=ROOT, text=True)


def source_version():
    version = re.search(r'(?m)^version = "([^"]+)"$', (ROOT / 'pyproject.toml').read_text())[1]
    version_key(version)
    loader = re.search(r"(?m)^VERSION = '([^']+)'$", (ROOT / 'tools/skieo_loader.py').read_text())
    if not loader or loader[1] != version:
        raise ValueError('Project and loader versions must match')
    release_notes(ROOT / 'CHANGELOG.md', version)
    return version


def select():
    version = source_version()
    releases = json.loads(gh('api', '--paginate', '--slurp', 'repos/{owner}/{repo}/releases?per_page=100'))
    existing = [item for page in releases for item in page if not item['draft'] and not item['prerelease']]
    newer = all(version_key(item['tag_name'].removeprefix('v')) < version_key(version) for item in existing)
    print(f'Version {version}: ' + ('prepare publication' if newer else 'already published or superseded'))
    with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
        output.write(f'version={version}\npublish={str(newer).lower()}\n')


def dependency():
    target = ROOT / 'build/custom-map-downloads' / UE4SS_ARCHIVE
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        response = urlopen(UE4SS_URL, timeout=120)
    except HTTPError as error:
        if error.code not in (404, 410):
            raise
        # The first release using a new pinned build also populates its mirror.
        # Fetch that exact upstream asset; read_ue4ss_archive checks its digest.
        response = urlopen(UE4SS_UPSTREAM_URL, timeout=120)
    with response:
        data = response.read(64 * 1024 * 1024 + 1)
    if len(data) > 64 * 1024 * 1024:
        raise ValueError('UE4SS download is too large')
    target.write_bytes(data)
    read_ue4ss_archive(target)


def publish():
    version = source_version()
    folder = ROOT / 'build' / ('release-' + version)
    notes = folder / 'github-release-notes.md'
    notes.write_text(release_notes(ROOT / 'CHANGELOG.md', version) + '\n')
    tag = 'v' + version
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    # Keep an interrupted upload private; retries replace only draft assets.
    releases = json.loads(gh('api', '--paginate', '--slurp', 'repos/{owner}/{repo}/releases?per_page=100'))
    existing = [item for page in releases for item in page if item['tag_name'] == tag]
    if existing and not existing[0]['draft']:
        raise ValueError('Refusing to replace an already published release')
    refs = json.loads(gh('api', 'repos/{owner}/{repo}/git/matching-refs/tags/' + tag))
    tagged = [item for item in refs if item['ref'] == 'refs/tags/' + tag]
    if tagged and tagged[0]['object']['sha'] != commit:
        raise ValueError('Release tag points to a different commit')
    if not tagged:
        gh('api', '--method', 'POST', 'repos/{owner}/{repo}/git/refs',
           '-f', 'ref=refs/tags/' + tag, '-f', 'sha=' + commit)
    if not existing:
        gh('release', 'create', tag, '--verify-tag', '--title', 'skieomod ' + version,
           '--notes-file', str(notes), '--draft')
    assets = [ROOT / 'build' / f'skieomod-server-{version}.tar.gz',
              folder / f'CustomMap-Mod-{version}.zip', folder / 'CustomMap-Tools.zip',
              folder / f'skieo_custom_map-{version}-py3-none-any.whl', folder / 'loader-latest.json',
              folder / f'Getting-Started-{version}.md', folder / f'Changelog-{version}.md']
    gh('release', 'upload', tag, *map(str, assets), '--clobber')
    gh('release', 'edit', tag, '--draft=false', '--latest', '--notes-file', str(notes))
    print('Published GitHub release ' + tag)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['select', 'dependency', 'publish'])
    args = parser.parse_args()
    {'select': select, 'dependency': dependency, 'publish': publish}[args.action]()
