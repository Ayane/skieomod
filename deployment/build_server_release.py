#!/usr/bin/env python3
"""Bundle a checked Git revision, built website and prepared mod for the server."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from deployment.release_custom_map import check_artifacts, version_changes
from deployment.publish_loader_updates import publication_files
from tools.skieo_install import UE4SS_ARCHIVE


def build(folder, output):
    version = json.loads((folder / 'loader-latest.json').read_text())['release']
    # A CI build must already declare its version; never silently bump sources.
    if any(before != after for _, before, after in version_changes(version)):
        raise ValueError('Source and prepared release versions differ')
    check_artifacts(folder, version)
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    if not re.fullmatch(r'[0-9a-f]{40}', commit):
        raise ValueError('Invalid source commit')
    browser = ROOT / 'repository/web/dist/browser'
    if not (browser / 'index.html').is_file():
        raise ValueError('Build the website before bundling the server')
    names = subprocess.check_output(['git', 'ls-files', '-z', '--', 'deployment', 'repository/server',
                                    'tools', 'schemas', 'docs', 'pyproject.toml', 'LICENSE',
                                    'THIRD_PARTY_NOTICES.md'], cwd=ROOT).decode().split('\0')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temporary, tarfile.open(output, 'w:gz') as archive:
        metadata = Path(temporary) / 'release.json'
        metadata.write_text(json.dumps({'format': 'skieomod-server-v1', 'version': version, 'commit': commit}) + '\n')
        archive.add(metadata, arcname='release.json')
        for name in filter(None, names):
            path = ROOT / name
            if path.is_symlink() or not path.is_file():
                raise ValueError('Server source must be a regular file: ' + name)
            archive.add(path, arcname=name, recursive=False)
        for path in sorted(browser.rglob('*')):
            if path.is_symlink():
                raise ValueError('Website must not contain symlinks')
            if path.is_file():
                archive.add(path, arcname=path.relative_to(ROOT), recursive=False)
        for path, _ in [*publication_files(folder, version), (folder / UE4SS_ARCHIVE, UE4SS_ARCHIVE)]:
            archive.add(path, arcname='release-artifacts/' + path.name, recursive=False)
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    print(build(args.directory.resolve(), args.output.resolve()))
