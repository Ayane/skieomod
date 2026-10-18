#!/usr/bin/env python3
"""Publish tested loader/CLI artifacts to the VPS; switch the latest feed last."""
from __future__ import annotations
import argparse
import hashlib
import io
import json
from pathlib import Path
import shlex
import subprocess
import sys
import tarfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.skieo_loader import read_archive, read_featured_catalog, update_feed
from tools.skieo_install import UE4SS_ARCHIVE, UE4SS_SHA256, read_ue4ss_archive

MAX_MEMBER_BYTES = 64 * 1024 * 1024
MAX_TOOLS_BYTES = 128 * 1024 * 1024
MAX_MAP_BYTES = 512 * 1024 * 1024
MAX_MOD_BYTES = 256 * 1024 * 1024


def publication_files(folder, release):
    files = [(folder / ('CustomMap-Mod-' + release + '.zip'), 'CustomMap-Mod-' + release + '.zip'),
            (folder / ('skieo_custom_map-' + release + '-py3-none-any.whl'), 'skieo_custom_map-' + release + '-py3-none-any.whl'),
            (folder / 'CustomMap-Tools.zip', 'CustomMap-Tools-' + release + '.zip'),
            (folder / ('Getting-Started-' + release + '.md'), 'Getting-Started-' + release + '.md'),
            (folder / 'loader-latest.json', 'loader-latest.json')]
    changelog = folder / ('Changelog-' + release + '.md')
    if changelog.is_file():
        files.append((changelog, changelog.name))
    catalog = folder / 'featured-maps.json'
    if catalog.exists():
        files.extend(read_featured_catalog(catalog))
        files.append((catalog, catalog.name))
    return files


def validate_publication_files(files):
    for path, name in files:
        if not path.is_file() or path.is_symlink():
            raise ValueError('Publication requires a regular file: ' + str(path))
        limit = MAX_MAP_BYTES if name.endswith('.skieomap') else MAX_MOD_BYTES if name.endswith('.skieomod') else MAX_TOOLS_BYTES if name.startswith('CustomMap-Tools-') and name.endswith('.zip') else MAX_MEMBER_BYTES
        size = path.stat().st_size
        if size > limit:
            raise ValueError(f'Publication file {name} has {size:,} bytes; limit is {limit:,} bytes')


REMOTE = '''
import hashlib, html, json, os, pathlib, re, shutil, sys, tarfile, tempfile
destination = pathlib.Path(sys.argv[1]).resolve(strict=True)
with tempfile.TemporaryDirectory(prefix=".skieomod-upload-", dir=destination) as temporary:
    stage = pathlib.Path(temporary)
    with tarfile.open(fileobj=sys.stdin.buffer, mode="r|*") as archive:
        for member in archive:
            if not member.isfile() or pathlib.PurePosixPath(member.name).name != member.name:
                raise ValueError("Invalid publication member: " + member.name)
            limit = __MAP_LIMIT__ if member.name.endswith(".skieomap") else __MOD_LIMIT__ if member.name.endswith(".skieomod") else __TOOLS_LIMIT__ if member.name.startswith("CustomMap-Tools-") and member.name.endswith(".zip") else __MEMBER_LIMIT__
            if member.size > limit:
                raise ValueError("Publication member " + member.name + " has " + str(member.size) + " bytes; limit is " + str(limit) + " bytes")
            target = stage / member.name
            with target.open("xb") as output:
                with archive.extractfile(member) as source:
                    shutil.copyfileobj(source, output, length=1024 * 1024)
    feed = json.loads((stage / "loader-latest.json").read_text())
    version = feed["release"]
    loader = "CustomMap-Mod-" + version + ".zip"
    wheel = "skieo_custom_map-" + version + "-py3-none-any.whl"
    tools = "CustomMap-Tools-" + version + ".zip"
    guide = "Getting-Started-" + version + ".md"
    changelog = "Changelog-" + version + ".md"
    documentation = [changelog] if (stage / changelog).is_file() else []
    ue4ss = json.loads((stage / "ue4ss-release.json").read_text())
    ue4ss_name = ue4ss["name"]
    if not re.fullmatch(r"UE4SS_v[0-9]+[.][0-9]+[.][0-9]+-[0-9]+-g[0-9a-f]+[.]zip", ue4ss_name):
        raise ValueError("Invalid versioned UE4SS archive name")
    featured_names = []
    if (stage / "featured-maps.json").is_file():
        catalog = json.loads((stage / "featured-maps.json").read_text())
        if catalog.get("format") != "skieo-registry" or catalog.get("version") != 1 or not isinstance(catalog.get("packages"), list) or not 1 <= len(catalog["packages"]) <= 64:
            raise ValueError("Invalid featured catalogue")
        for package in catalog["packages"]:
            if package.get("kind") not in {"map", "mod"} or not re.fullmatch(r"[a-z0-9]+(?:[._-][a-z0-9]+)+", package["id"]) or not re.fullmatch(r"[0-9A-Za-z.+-]+", package["version"]):
                raise ValueError("Invalid featured package")
            name = package["id"] + "-" + package["version"] + ".skieo" + package["kind"]
            if name in featured_names or package.get("download_url") != "https://skieomod.emillon.fr/downloads/" + name:
                raise ValueError("Invalid featured download URL/identity")
            if not (stage / name).is_file() or (stage / name).stat().st_size != package.get("size") or hashlib.sha256((stage / name).read_bytes()).hexdigest() != package.get("sha256"):
                raise ValueError("Uploaded featured checksum mismatch: " + name)
            featured_names.append(name)
    extra = {"featured-maps.json", *featured_names} if featured_names else set()
    if {p.name for p in stage.iterdir()} != {loader, wheel, tools, guide, "loader-latest.json", "ue4ss-release.json", ue4ss_name, *extra, *documentation}:
        raise ValueError("Publication files differ from their version")
    if hashlib.sha256((stage / loader).read_bytes()).hexdigest() != feed["sha256"] or (stage / loader).stat().st_size != feed["size"]:
        raise ValueError("Uploaded loader checksum mismatch")
    if hashlib.sha256((stage / ue4ss_name).read_bytes()).hexdigest() != ue4ss["sha256"] or (stage / ue4ss_name).stat().st_size != ue4ss["size"]:
        raise ValueError("Uploaded UE4SS checksum mismatch")
    for name in (loader, wheel, tools, guide, ue4ss_name, *featured_names, *documentation):
        target = destination / name
        if target.exists() and target.read_bytes() != (stage / name).read_bytes():
            raise ValueError("Versioned artifact already exists with different bytes: " + name)
    # Keep earlier mod versions discoverable for maps that still pin them.
    # Their immutable archives already exist; verify them before switching feeds.
    previous_catalog = destination / "featured-maps.json"
    if featured_names and previous_catalog.is_file():
        previous_catalog = json.loads(previous_catalog.read_text())
        added = False
        for package in previous_catalog["packages"]:
            if package.get("kind") != "mod":
                continue
            if not re.fullmatch(r"[a-z0-9]+(?:[._-][a-z0-9]+)+", package["id"]) or not re.fullmatch(r"[0-9A-Za-z.+-]+", package["version"]):
                raise ValueError("Invalid retained mapmod identity")
            name = package["id"] + "-" + package["version"] + ".skieomod"
            if name in featured_names:
                continue
            existing = destination / name
            if package.get("download_url") != "https://skieomod.emillon.fr/downloads/" + name or not existing.is_file() or existing.is_symlink() or existing.stat().st_size != package.get("size") or hashlib.sha256(existing.read_bytes()).hexdigest() != package.get("sha256"):
                raise ValueError("Retained mapmod checksum mismatch: " + name)
            catalog["packages"].append(package)
            added = True
        if len(catalog["packages"]) > 64:
            raise ValueError("Featured catalogue exceeds 64 retained releases")
        if added:
            (stage / "featured-maps.json").write_text(json.dumps(catalog))
    # Publish the tested dependency before exposing the CLI in the package index.
    for name in (ue4ss_name, *featured_names, loader, wheel, tools, guide, *documentation):
        target = destination / name
        if not target.exists():
            os.chmod(stage / name, 0o644)
            os.replace(stage / name, target)
    # Expose the catalogue only after every immutable map and mod is available.
    if featured_names:
        os.chmod(stage / "featured-maps.json", 0o644)
        os.replace(stage / "featured-maps.json", destination / "featured-maps.json")
    # Stable article links always resolve to the artifacts of this publication.
    aliases = [("CustomMap-Mod.zip", loader), ("CustomMap-Tools.zip", tools), ("getting-started.md", guide)]
    if documentation:
        aliases.append(("changelog.md", changelog))
    for alias, name in aliases:
        target = destination / alias
        if target.is_symlink() and os.readlink(target) == name:
            continue
        if target.is_file() and not target.is_symlink():
            saved = stage / (alias + ".previous")
            shutil.copy2(target, saved)
            previous_name = alias.replace(".zip", ".previous.zip") if alias.endswith(".zip") else alias.removesuffix(".md") + ".previous.md"
            os.replace(saved, destination / previous_name)
        os.symlink(name, stage / alias)
        os.replace(stage / alias, target)
    # pip/pipx need the real versioned wheel filename. A simple package index
    # gives them a stable installation command without renaming the wheel.
    index = destination / "pypi" / "skieo-custom-map"
    index.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256((destination / wheel).read_bytes()).hexdigest()
    content = '<!doctype html><html><head><title>skieo-custom-map</title></head><body>\\n'
    content += '<a href="../../' + html.escape(wheel, quote=True) + '#sha256=' + digest + '">' + html.escape(wheel) + '</a>\\n'
    content += '</body></html>\\n'
    staged_index = stage / "package-index.html"
    staged_index.write_text(content, encoding="utf-8")
    os.chmod(staged_index, 0o644)
    os.replace(staged_index, index / "index.html")
    previous = destination / "loader-latest.json"
    if previous.is_file() and previous.read_bytes() != (stage / "loader-latest.json").read_bytes():
        history = destination / "loader-latest.previous.json"
        staged_history = stage / "previous.json"
        staged_history.write_bytes(previous.read_bytes())
        os.chmod(staged_history, 0o644)
        os.replace(staged_history, history)
    os.chmod(stage / "loader-latest.json", 0o644)
    os.replace(stage / "loader-latest.json", previous)
    print("Published loader " + version + " at " + feed["url"])
'''.replace('__TOOLS_LIMIT__', str(MAX_TOOLS_BYTES)).replace('__MEMBER_LIMIT__', str(MAX_MEMBER_BYTES)).replace('__MAP_LIMIT__', str(MAX_MAP_BYTES)).replace('__MOD_LIMIT__', str(MAX_MOD_BYTES))


def publish(args):
    folder = args.directory.resolve()
    feed = json.loads((folder / 'loader-latest.json').read_text(encoding='utf-8'))
    release = feed['release']
    archive = folder / ('CustomMap-Mod-' + release + '.zip')
    _, record = read_archive(archive)
    if update_feed(archive, record) != feed:
        raise ValueError('Publication feed differs from the local loader archive')
    files = publication_files(folder, release)
    validate_publication_files(files)
    ue4ss_data = read_ue4ss_archive(folder / UE4SS_ARCHIVE)
    ue4ss_record = json.dumps({'name': UE4SS_ARCHIVE, 'sha256': UE4SS_SHA256,
                              'size': len(ue4ss_data)}).encode('utf-8')
    payload = io.BytesIO()
    with tarfile.open(fileobj=payload, mode='w') as archive_stream:
        for path, name in files:
            archive_stream.add(path, arcname=name, recursive=False)
        for name, data in [(UE4SS_ARCHIVE, ue4ss_data), ('ue4ss-release.json', ue4ss_record)]:
            item = tarfile.TarInfo(name)
            item.size = len(data)
            archive_stream.addfile(item, io.BytesIO(data))
    command = ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10']
    if args.ssh_config:
        command.extend(['-F', str(args.ssh_config)])
    if args.known_hosts:
        command.extend(['-o', 'UserKnownHostsFile=' + str(args.known_hosts)])
    remote_command = 'python3 -c ' + shlex.quote(REMOTE) + ' ' + shlex.quote(args.remote_directory)
    subprocess.run([*command, args.host, remote_command], input=payload.getvalue(), check=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', nargs='?', type=Path, default=Path('build/custom-map-downloads'))
    parser.add_argument('--host', default='root@skieomod.emillon.fr')
    parser.add_argument('--remote-directory', default='/opt/custom-map/current/downloads')
    parser.add_argument('--ssh-config', type=Path, help='optional SSH configuration file')
    parser.add_argument('--known-hosts', type=Path, help='optional SSH known-hosts file')
    publish(parser.parse_args())
