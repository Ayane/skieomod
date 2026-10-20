"""Versioned loader releases, HTTPS downloads and recoverable updates before Workshop."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
import zipfile
from urllib.request import Request, urlopen

if __package__ == 'tools':
    from .custom_packages import inspect_package, pack_package, resolve
    from .custom_maps import ManifestError, inspect_archive, load_manifest, pack, safe_relative_path, semver_compare, validate_manifest, validate_zip
else:
    from custom_packages import inspect_package, pack_package, resolve
    from custom_maps import ManifestError, inspect_archive, load_manifest, pack, safe_relative_path, semver_compare, validate_manifest, validate_zip

VERSION = '1.24.6'
NAME = 'SkiEO-CustomMaps'
RECORD = 'loader-release.json'
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_RELEASE_BYTES = 128 * 1024 * 1024
REQUIRED = {'Scripts/main.lua', 'Scripts/skieo_repository.dll', 'Scripts/skieo_native_terrain.dll'}
DOWNLOAD_BASE = 'https://skieomod.emillon.fr/downloads/'
UPDATE_URL = DOWNLOAD_BASE + 'loader-latest.json'
# Earlier installers compare the exact manifest without game_builds metadata.
# Require the reader that understands verified Steam revisions before download.
MINIMUM_UPDATE_CLI = '1.17.0'
# Steam revisions verified in the game, rather than inferred from UE versions.
TESTED_GAME_BUILDS = {'5012760': '26071000'}


def update_feed(archive, record):
    """Pin an immutable versioned artifact; publish this pointer after the ZIP."""
    return {'format': 'skieomod-loader-update', 'version': 1, 'release': record['release'],
            'minimum_cli': MINIMUM_UPDATE_CLI, 'url': DOWNLOAD_BASE + Path(archive).name,
            'sha256': hashlib.sha256(Path(archive).read_bytes()).hexdigest(),
            'size': Path(archive).stat().st_size, 'loader': record}


def _read_update(url, limit, timeout):
    request = Request(url, headers={'User-Agent': 'skieomod/' + VERSION, 'Cache-Control': 'no-cache'})
    with urlopen(request, timeout=timeout) as response:
        if response.geturl() != url:
            raise ManifestError('Loader updates must not redirect to another URL')
        data = response.read(limit + 1)
        if len(data) > limit:
            raise ManifestError('Loader update download exceeds its limit')
        return data


def fetch_feed(*, timeout=5):
    """Check release metadata without downloading or installing the archive."""
    feed = json.loads(_read_update(UPDATE_URL, 1024 * 1024, timeout))
    if not isinstance(feed, dict) or feed.get('format') != 'skieomod-loader-update' or feed.get('version') != 1:
        raise ManifestError('Invalid loader update feed')
    semver_compare(feed.get('minimum_cli'), feed.get('minimum_cli'))
    record = validate_record(feed.get('loader'))
    if feed.get('release') != record['release'] or feed.get('url') != DOWNLOAD_BASE + 'CustomMap-Mod-' + record['release'] + '.zip':
        raise ManifestError('Invalid loader update release/URL')
    size = feed.get('size')
    if isinstance(size, bool) or not isinstance(size, int) or not 0 < size <= MAX_ARCHIVE_BYTES:
        raise ManifestError('Invalid loader update size')
    digest = feed.get('sha256')
    if not isinstance(digest, str) or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
        raise ManifestError('Invalid loader archive SHA-256')
    return feed


def fetch_release():
    feed = fetch_feed(timeout=30)
    if semver_compare(VERSION, feed['minimum_cli']) < 0:
        raise ManifestError('This release needs a newer skieomod CLI; install the latest wheel first.')
    record, size = feed['loader'], feed['size']
    data = _read_update(feed['url'], size, 30)
    if len(data) != size or hashlib.sha256(data).hexdigest() != feed.get('sha256'):
        raise ManifestError('Loader archive size/SHA-256 mismatch')
    with tempfile.TemporaryDirectory(prefix='skieomod-download-') as temporary:
        path = Path(temporary) / 'loader.zip'
        path.write_bytes(data)
        files, packaged = read_archive(path)
    if packaged != record:
        raise ManifestError('Downloaded loader differs from update feed')
    return files, record


def managed_path(name):
    path = safe_relative_path(name, 'loader release file')
    example = len(path.parts) == 2 and path.parts[0] == 'Examples' and path.suffix == '.skieomap'
    if (not example and path.suffix.lower() not in {'.lua', '.dll', '.md'} and name not in {'LICENSE', 'LICENSE-miniz.txt'}
            or any(part.startswith('.') for part in path.parts)):
        raise ManifestError('Unsupported loader release file: ' + name)
    return str(path)


def example_files(directory):
    """Pack the sample from portable sources, identically in wheels and ZIPs."""
    directory = Path(directory)
    source = directory / 'custom-map.json'
    sample, _ = load_manifest(source, check_files=True)
    name = 'Veymont-' + sample['metadata']['version'] + '.skieomap'
    with tempfile.TemporaryDirectory(prefix='skieomod-example-') as temporary:
        archive = Path(temporary) / name
        pack(source, archive)
        return {'Examples/' + name: archive.read_bytes()}


def featured_files(directory):
    """Build separate map/mod downloads and validate the dependency closure."""
    directories = directory if isinstance(directory, (list, tuple)) else [directory]
    files, releases = {}, []
    for item in directories:
        name, data, release = _featured_archive(item)
        if any((entry['id'], entry['version']) == (release['id'], release['version']) for entry in releases):
            raise ManifestError('Duplicate Featured release: ' + release['id'])
        files[name] = data
        releases.append(release)
    for release in releases:
        resolve(releases, release['id'], '=' + release['version'])
    files['featured-maps.json'] = (json.dumps(
        {'format': 'skieo-registry', 'version': 1, 'packages': releases}, indent=2) + '\n').encode('utf-8')
    return files


def _featured_archive(directory):
    source = Path(directory) / 'custom-map.json'
    kind = 'map' if source.is_file() else 'mod'
    if kind == 'mod':
        source = Path(directory) / 'custom-mod.json'
    sample = json.loads(source.read_text(encoding='utf-8'))
    if kind == 'mod' and sample.get('runtime', 'map-api') != 'map-api':
        raise ManifestError('Featured dependencies must use the map API')
    name = sample['id'] + '-' + sample['metadata']['version'] + '.skieo' + kind
    with tempfile.TemporaryDirectory(prefix='skieomod-featured-') as temporary:
        path = Path(temporary) / name
        if sample.get('build'):
            # Featured source projects need the same graph/resource compiler
            # as the workshop. Raw pack would silently omit their actions.
            if __package__ == 'tools':
                from .skieo_project import build
            else:
                from skieo_project import build
            _, built = build(source, path, save_build_metadata=False)
            sample = built['manifest']
        else:
            pack_package(source, path)
        data = path.read_bytes()
        with zipfile.ZipFile(path) as archive:
            unpacked = sum(info.file_size for info in archive.infolist())
    release = {'id': sample['id'], 'kind': kind, 'version': sample['metadata']['version'],
               'manifest': sample, 'size': len(data), 'unpacked_size': unpacked,
               'sha256': hashlib.sha256(data).hexdigest(), 'download_url': DOWNLOAD_BASE + name}
    return name, data, release


def read_featured_catalog(path):
    """Validate the catalogue and each immutable map before publication."""
    path = Path(path)
    if not path.is_file() or path.is_symlink() or path.stat().st_size > 16 * 1024 * 1024:
        raise ManifestError('Invalid featured catalogue file')
    catalog = json.loads(path.read_text(encoding='utf-8'))
    if (not isinstance(catalog, dict) or catalog.get('format') != 'skieo-registry' or catalog.get('version') != 1
            or not isinstance(catalog.get('packages'), list) or not 1 <= len(catalog['packages']) <= 64):
        raise ManifestError('Invalid featured catalogue')
    files, seen = [], set()
    for release in catalog['packages']:
        if not isinstance(release, dict) or release.get('kind') not in {'map', 'mod'}:
            raise ManifestError('Invalid featured release')
        name = release['id'] + '-' + release['version'] + '.skieo' + release['kind']
        safe_relative_path(name, 'featured map')
        key = (release['id'], release['version'])
        if '/' in name or key in seen or release.get('download_url') != DOWNLOAD_BASE + name:
            raise ManifestError('Invalid featured download URL/identity')
        seen.add(key)
        archive = path.parent / name
        if not archive.is_file() or archive.is_symlink() or not 0 < archive.stat().st_size <= 512 * 1024 * 1024:
            raise ManifestError('Invalid featured map file: ' + name)
        if archive.stat().st_size != release.get('size') or hashlib.sha256(archive.read_bytes()).hexdigest() != release.get('sha256'):
            raise ManifestError('Featured map size/SHA-256 mismatch: ' + name)
        kind, from_manifest, _ = inspect_package(archive, release['kind'])
        if kind == 'mod' and from_manifest.get('runtime', 'map-api') != 'map-api':
            raise ManifestError('Featured dependencies must use the map API')
        if from_manifest['id'] != release['id'] or from_manifest['metadata']['version'] != release['version']:
            raise ManifestError('Featured manifest identity/dependencies mismatch')
        if release['manifest'] != from_manifest:
            raise ManifestError('Featured archive differs from its manifest: ' + name)
        with zipfile.ZipFile(archive) as package:
            if sum(item.file_size for item in package.infolist()) != release.get('unpacked_size'):
                raise ManifestError('Featured unpacked size mismatch: ' + name)
        files.append((archive, name))
    for release in catalog['packages']:
        resolve(catalog['packages'], release['id'], '=' + release['version'])
    return files


def collect(directory):
    """Ship code and docs; maps, runtime JSON and settings stay local."""
    files = {}
    directory = Path(directory).resolve()
    for path in sorted(directory.rglob('*')):
        if not path.is_file():
            continue
        name = path.relative_to(directory).as_posix()
        if name.startswith('Examples/'):
            continue
        try:
            managed_path(name)
        except ManifestError:
            continue
        if not path.resolve().is_relative_to(directory):
            raise ManifestError('Loader release symlink escapes its directory: ' + name)
        files[name] = path.read_bytes()
    return files


def manifest(files, release=VERSION, *, game_builds=None):
    record = {'format': 'skieomod-loader', 'version': 1, 'release': release,
              'files': {name: hashlib.sha256(data).hexdigest() for name, data in sorted(files.items())}}
    if game_builds is None:
        game_builds = TESTED_GAME_BUILDS if release == VERSION else {}
    if game_builds:
        record['game_builds'] = dict(game_builds)
    validate_record(record)
    return record


def validate_record(record):
    if (not isinstance(record, dict) or record.get('format') != 'skieomod-loader'
            or record.get('version') != 1):
        raise ManifestError('Invalid loader release manifest')
    release = record.get('release')
    semver_compare(release, release)
    builds = record.get('game_builds', {})
    if (not isinstance(builds, dict) or len(builds) > 16 or any(
            not isinstance(app, str) or not app.isascii() or not app.isdecimal() or len(app) > 20
            or not isinstance(build, str) or not build.isascii() or not build.isdecimal() or len(build) > 20
            for app, build in builds.items())):
        raise ManifestError('Invalid tested Steam game revisions')
    files = record.get('files')
    if not isinstance(files, dict) or not REQUIRED <= files.keys() or len(files) > 4095:
        raise ManifestError('Loader release is missing required scripts/DLLs')
    if len({name.casefold() for name in files}) != len(files):
        raise ManifestError('Duplicate loader release paths')
    for name, digest in files.items():
        managed_path(name)
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
            raise ManifestError('Invalid loader SHA-256: ' + name)
    return record


def read_archive(path):
    """Validate every member and digest before the updater touches the game."""
    path = Path(path)
    if path.stat().st_size > MAX_ARCHIVE_BYTES:
        raise ManifestError('Loader archive exceeds 64 MiB')
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(validate_zip(archive, max_unpacked=MAX_RELEASE_BYTES))
            prefix = NAME + '/'
            manifest_name = prefix + RECORD
            if manifest_name not in names:
                raise ManifestError('Expected a versioned CustomMap-Mod archive with ' + manifest_name)
            if archive.getinfo(manifest_name).file_size > 1024 * 1024:
                raise ManifestError('Loader release manifest exceeds 1 MiB')
            record = validate_record(json.loads(archive.read(manifest_name)))
            if names != {manifest_name, *(prefix + name for name in record['files'])}:
                raise ManifestError('Loader archive files differ from its release manifest')
            files = {}
            for name, expected in record['files'].items():
                data = archive.read(prefix + name)
                if hashlib.sha256(data).hexdigest() != expected:
                    raise ManifestError('Loader SHA-256 mismatch: ' + name)
                files[name] = data
            return files, record
    except (zipfile.BadZipFile, RuntimeError, EOFError) as error:
        raise ManifestError('Invalid loader archive: ' + str(error)) from error


def installed_record(destination):
    path = Path(destination) / RECORD
    return validate_record(json.loads(path.read_text(encoding='utf-8'))) if path.is_file() else None


def update(destination, files, record, *, check=False):
    """Replace managed files with per-file backups and rollback on write failure."""
    validate_record(record)
    if files is None and not check:
        raise ManifestError('An update requires verified archive files')
    if files is not None and manifest(files, record['release'], game_builds=record.get('game_builds', {})) != record:
        raise ManifestError('Loader files differ from their release manifest')
    destination = Path(destination).resolve()
    if not (destination / 'Scripts/main.lua').is_file():
        raise ManifestError('Custom Map is not installed here; run skieomod setup first.')
    previous = installed_record(destination)
    changes, removed, retained = [], [], []
    for name, expected in record['files'].items():
        target = destination / name
        if not target.resolve().is_relative_to(destination) or target.is_symlink():
            raise ManifestError('Loader target cannot traverse a symbolic link: ' + name)
        if target.exists() and not target.is_file():
            raise ManifestError('Loader target is not a file: ' + name)
        if not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest() != expected:
            changes.append(name)
    for name, expected in (previous['files'] if previous else {}).items():
        if name in record['files']:
            continue
        target = destination / name
        if target.is_file():
            if not target.resolve().is_relative_to(destination) or target.is_symlink():
                raise ManifestError('Loader target cannot traverse a symbolic link: ' + name)
            (removed if hashlib.sha256(target.read_bytes()).hexdigest() == expected else retained).append(name)
    record_path = destination / RECORD
    if record_path.is_symlink():
        raise ManifestError('Loader release manifest cannot be a symbolic link')
    result = {'installed': previous['release'] if previous else 'unknown (legacy installation)',
              'available': record['release'], 'changed': changes, 'removed': removed,
              'retained': retained, 'backup': None}
    if check or not changes and not removed and previous == record:
        return result
    backup_root = destination / '.skieomod-backups'
    if not backup_root.resolve().is_relative_to(destination):
        raise ManifestError('Loader backup directory cannot escape the installation')
    # Prepare all new bytes and snapshot originals before replacing any live file.
    with tempfile.TemporaryDirectory(prefix='.skieomod-update-', dir=destination.parent) as temporary:
        stage = Path(temporary)
        touched = [*changes, *removed, RECORD]
        originals = {}
        for name in touched:
            target = destination / name
            if target.exists():
                saved = stage / 'previous' / name
                saved.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, saved)
                originals[name] = saved
        for name in [*changes, RECORD]:
            staged = stage / 'next' / name
            staged.parent.mkdir(parents=True, exist_ok=True)
            staged.write_bytes(files[name] if name != RECORD else
                               (json.dumps(record, indent=2) + '\n').encode('utf-8'))
        backup = backup_root / str(time.time_ns())
        backup.mkdir(parents=True)
        for name, saved in originals.items():
            target = backup / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(saved, target)
        applied = []
        try:
            for name in removed:
                (destination / name).unlink()
                applied.append(name)
            for name in [*changes, RECORD]:
                target = destination / name
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(stage / 'next' / name, target)
                applied.append(name)
        except OSError:
            for name in reversed(applied):
                target = destination / name
                if name in originals:
                    os.replace(originals[name], target)
                else:
                    target.unlink(missing_ok=True)
            raise
    result['backup'] = str(backup)
    return result


def installed_mapmods(config):
    """Read local CLI packages and the loader's separately downloaded mods."""
    paths = set()
    if config.get('maps_dir'):
        paths.update(Path(config['maps_dir']).glob('*.skieomod'))
    if config.get('ue4ss_mods'):
        paths.update((Path(config['ue4ss_mods']) / NAME / 'Scripts').glob('repository-*.skieomod'))
    releases = []
    for path in sorted(paths):
        if path.is_symlink():
            continue
        try:
            kind, manifest, _ = inspect_package(path, 'mod')
        except ManifestError:
            continue
        if manifest.get('runtime', 'map-api') == 'map-api':
            releases.append({'id': manifest['id'], 'version': manifest['metadata']['version'],
                             'kind': kind, 'manifest': manifest, 'archive': path,
                             'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    return releases


def fetch_mapmod_dependencies(root, installed, directory):
    """Resolve before fetching; validate size, digest and the exact manifest.

    Only the configured project catalogue is trusted for pre-Workshop downloads.
    A manifest cannot send the player to arbitrary hosts. Workshop dependencies
    retain their Workshop identity and cannot be substituted by a web download.
    """
    try:
        return resolve([root, *installed], root['id'], '=' + root['version'])
    except ManifestError:
        pass
    catalog = json.loads(_read_update(DOWNLOAD_BASE + 'featured-maps.json', 16 * 1024**2, 15))
    if (not isinstance(catalog, dict) or catalog.get('format') != 'skieo-registry' or catalog.get('version') != 1
            or not isinstance(catalog.get('packages'), list) or len(catalog['packages']) > 1024):
        raise ManifestError('Invalid mapmod catalogue')
    if __package__ == 'tools':
        from .custom_packages import validate_mod
    else:
        from custom_packages import validate_mod
    available, seen = [], set()
    for release in catalog['packages']:
        if not isinstance(release, dict) or release.get('kind') not in {'mod', 'map'}:
            raise ManifestError('Invalid mapmod release')
        if release['kind'] == 'map':
            continue
        manifest = validate_mod(release['manifest'])
        key = (manifest['id'], manifest['metadata']['version'])
        expected = DOWNLOAD_BASE + key[0] + '-' + key[1] + '.skieomod'
        if (key in seen or key != (release.get('id'), release.get('version'))
                or release.get('download_url') != expected or manifest.get('runtime', 'map-api') != 'map-api'
                or type(release.get('size')) is not int or not 0 < release['size'] <= 256 * 1024**2
                or not isinstance(release.get('sha256'), str) or len(release['sha256']) != 64
                or any(c not in '0123456789abcdef' for c in release['sha256'])):
            raise ManifestError('Invalid mapmod download metadata')
        seen.add(key); available.append(release)
    closure = resolve([root, *installed, *available], root['id'], '=' + root['version'])
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    result = []
    for release in closure:
        if release is root or release.get('archive') or release.get('workshop_id'):
            result.append(release); continue
        data = _read_update(release['download_url'], release['size'], 60)
        if len(data) != release['size'] or hashlib.sha256(data).hexdigest() != release['sha256']:
            raise ManifestError('Mapmod size/SHA-256 mismatch: ' + release['id'])
        path = directory / (release['id'] + '-' + release['version'] + '.skieomod')
        path.write_bytes(data)
        kind, manifest, unpacked = inspect_package(path, 'mod')
        if manifest != release['manifest'] or unpacked != release.get('unpacked_size'):
            path.unlink()
            raise ManifestError('Mapmod archive differs from its release: ' + release['id'])
        result.append({**release, 'archive': path})
    return result
