"""Steam Workshop staging and the versioned Steamworks client boundary.

Steam owns article IDs, subscriptions, downloads and updates. ZIP packages are
local build artifacts; SetItemContent receives an unpacked directory.
"""
from __future__ import annotations
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import zipfile

if __package__ == 'tools':
    from .custom_packages import ManifestError, inspect_package, pack_package
    from . import skieo_install as desktop
else:
    from custom_packages import ManifestError, inspect_package, pack_package
    import skieo_install as desktop

APP_ID = '4493130'
FORMAT = 'skieomod-workshop'


def item_id(value, *, create=False):
    if create and value == '0':
        return value
    if not isinstance(value, str) or not re.fullmatch(r'[1-9][0-9]{0,19}', value) or int(value) >= 2**64 - 1:
        raise ManifestError('Workshop IDs must be nonzero uint64 decimal strings')
    return value


def app_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[1-9][0-9]{0,9}', value) or int(value) >= 2**32:
        raise ManifestError('Invalid Steam AppID')
    return value


def request(method, app, **fields):
    return {'format': FORMAT, 'version': 1, 'method': method, 'app_id': app_id(app), **fields}


def call(payload, executable=None, config=None):
    """A native client uses the running Steam session, never website tokens.

    stdin/stdout JSON, one operation per process; it must finish its Steam async
    operation before replying. No shell, password or arbitrary URL is involved.
    """
    executable = executable or (config or desktop.load_config()).get('workshop_client')
    if not executable:
        raise ManifestError('Steamworks client is not connected yet. Use publish --prepare; '
                            'install/play are available through Steam Workshop once the game enables it.')
    result = subprocess.run([str(executable)], input=json.dumps(payload), text=True,
                            capture_output=True, timeout=900, check=False)
    if result.returncode or len(result.stdout.encode()) > 16 * 1024**2:
        raise ManifestError('Steamworks client failed: ' + result.stderr.strip()[:2000])
    data = json.loads(result.stdout)
    if not isinstance(data, dict) or data.get('format') != FORMAT or data.get('version') != 1 or data.get('app_id') != payload['app_id']:
        raise ManifestError('Invalid Steamworks client response')
    if data.get('ok') is not True:
        raise ManifestError(str(data.get('error', 'Steam Workshop operation failed')))
    if payload['method'] == 'query':
        items = data.get('items')
        if not isinstance(items, list) or len(items) > 50 or not isinstance(data.get('has_more'), bool):
            raise ManifestError('Invalid Steam Workshop query page')
        for item in items:
            if not isinstance(item, dict) or item.get('app_id') != payload['app_id'] or item.get('result') != 1 or item.get('banned'):
                raise ManifestError('Invalid or unavailable Workshop query item')
            item_id(item.get('published_file_id'))
            if item.get('kind') not in {'map', 'mod'} or not isinstance(item.get('title'), str) or not isinstance(item.get('description'), str):
                raise ManifestError('Invalid Workshop item metadata')
    if payload['method'] == 'publish':
        item_id(data.get('published_file_id'))
        if not isinstance(data.get('needs_legal_agreement', False), bool):
            raise ManifestError('Invalid Workshop legal agreement state')
    if payload['method'] in {'install', 'play'}:
        if data.get('published_file_id') != payload['published_file_id']:
            raise ManifestError('Workshop operation returned a different article ID')
    return data


def content_roots(config):
    app = app_id(config.get('workshop_app_id') or config.get('app_id') or APP_ID)
    steamapps = [Path(p) / 'steamapps' for p in desktop.steam_libraries()]
    if config.get('steamapps_dir'):
        steamapps.insert(0, Path(config['steamapps_dir']))
    return app, list(dict.fromkeys(p / 'workshop/content' / app for p in steamapps))


def installed(config, temporary):
    """Read only items listed as installed by Steam, including secondary libraries.

    This offline view makes no assertion about subscriptions or update status.
    Live state and installation completion must come from ISteamUGC.
    """
    app, roots = content_roots(config)
    releases, archives, seen = [], {}, set()
    for root in roots:
        acf = root.parent.parent / ('appworkshop_' + app + '.acf')
        items = desktop.read_vdf(acf).get('AppWorkshop', {})
        if items.get('appid') != app:
            continue
        for published_id in items.get('WorkshopItemsInstalled', {}):
            item_id(published_id)
            folder = root / published_id
            if published_id in seen or not folder.is_dir() or folder.is_symlink():
                continue
            seen.add(published_id)
            manifests = [folder / name for name in ('custom-map.json', 'custom-mod.json') if (folder / name).is_file()]
            if len(manifests) != 1:
                continue
            archive = Path(temporary) / (published_id + '.zip')
            pack_package(manifests[0], archive)
            kind, manifest, _ = inspect_package(archive)
            release = {'id': manifest['id'], 'kind': kind, 'version': manifest['metadata']['version'],
                       'manifest': manifest, 'workshop_id': published_id, 'archive': archive}
            releases.append(release)
            archives[published_id] = archive
    return releases, archives


def prepare(archive, project, *, app=None, published_id=None, preview=None, visibility=None, changenote=''):
    project = Path(project).resolve()
    settings_path = project / 'workshop.json'
    settings = json.loads(settings_path.read_text()) if settings_path.is_file() else {}
    if not isinstance(settings, dict) or settings.get('version', 1) != 1:
        raise ManifestError('Unsupported workshop.json settings')
    kind, manifest, _ = inspect_package(archive)
    app = app_id(app or settings.get('app_id') or APP_ID)
    published_id = item_id(published_id or settings.get('published_file_id') or '0', create=True)
    visibility = visibility if visibility is not None else settings.get('visibility', 'private')
    if visibility not in {'public', 'friends', 'private', 'unlisted'}:
        raise ManifestError('Unsupported Workshop visibility')
    children = []
    for dependency in manifest.get('dependencies', []):
        if dependency.get('optional'):
            continue
        child = item_id(dependency.get('workshop_id'))
        if child == published_id:
            raise ManifestError('An article cannot depend on itself')
        if child not in children:
            children.append(child)
    metadata = manifest['metadata']
    tags = list(dict.fromkeys([kind, *(['mapmod'] if manifest.get('runtime', 'map-api') == 'map-api' and kind == 'mod' else []), *metadata.get('tags', [])]))
    if any(not isinstance(tag, str) or not tag or len(tag.encode()) > 255 or ',' in tag or not tag.isprintable() for tag in tags):
        raise ManifestError('Workshop tags must be printable, comma-free and at most 255 UTF-8 bytes')
    # SetItemMetadata has 5000 bytes including its terminator. Full terrain and
    # dependency manifests stay in content; queries return only this summary.
    summary = json.dumps({'format': 'skieomod', 'version': 1, 'kind': kind,
                          'id': manifest['id'], 'package_version': metadata['version'],
                          **({'runtime': manifest.get('runtime', 'map-api')} if kind == 'mod' else {})}, separators=(',', ':'))
    if len(summary.encode()) >= 5000:
        raise ManifestError('Workshop metadata exceeds 4999 UTF-8 bytes')
    if len(metadata['name'].encode()) >= 129 or len(metadata['description'].encode()) >= 8000:
        raise ManifestError('Workshop title/description exceed the Steamworks UTF-8 limits')
    preview = Path(preview or settings.get('preview_file', 'preview.png'))
    preview = preview if preview.is_absolute() else project / preview
    if not preview.is_file() or preview.suffix.lower() not in {'.png', '.jpg', '.jpeg', '.gif'} or preview.stat().st_size >= 1024**2:
        raise ManifestError('Provide a Workshop preview PNG/JPG/GIF smaller than 1 MiB (--preview FILE)')
    output = project / 'bin/workshop'
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.is_symlink():
        raise ManifestError('Workshop output cannot be a symlink')
    stage = Path(tempfile.mkdtemp(prefix='.workshop-', dir=output.parent))
    try:
        content = stage / 'content'
        content.mkdir()
        with zipfile.ZipFile(archive) as package:
            package.extractall(content)  # inspect_package already checked paths/CRC/limits.
        preview_target = 'preview' + preview.suffix.lower()
        shutil.copyfile(preview, stage / preview_target)
        payload = request('publish', app, published_file_id=published_id,
                          content_folder=str(output / 'content'), preview_file=str(output / preview_target),
                          title=metadata['name'], description=metadata['description'], tags=tags,
                          metadata=summary, visibility=visibility, changenote=changenote,
                          required_items=children)
        (stage / 'publish-request.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n')
        # SteamCMD is an explicit developer testing fallback; it cannot set the
        # UGC metadata/tags/children. Do not silently claim those were published.
        vdf = {'appid': app, 'publishedfileid': published_id,
               'contentfolder': payload['content_folder'], 'previewfile': payload['preview_file'],
               'visibility': str({'public': 0, 'friends': 1, 'private': 2, 'unlisted': 3}[visibility]),
               'title': payload['title'], 'description': payload['description'], 'changenote': changenote}
        quote = lambda value: '"' + value.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n').replace('\r', '') + '"'
        (stage / 'workshop.vdf').write_text('"workshopitem"\n{\n' + ''.join('  ' + quote(k) + ' ' + quote(v) + '\n' for k, v in vdf.items()) + '}\n')
        backup = output.with_name('.workshop-previous')
        if backup.exists():
            raise ManifestError('Remove the previous interrupted Workshop build before rebuilding')
        if output.exists():
            output.rename(backup)
        try:
            stage.rename(output)
        except OSError:
            if backup.exists():
                backup.rename(output)
            raise
        if backup.exists():
            shutil.rmtree(backup)
        return output, payload
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def publish(payload, project, executable=None):
    result = call(payload, executable)
    published_id = item_id(result.get('published_file_id'))
    if payload['published_file_id'] != '0' and payload['published_file_id'] != published_id:
        raise ManifestError('Steam returned a different article ID during an update')
    # Keep even a newly created ID requiring legal acceptance to avoid creating
    # duplicate articles on the next publication attempt.
    path = Path(project) / 'workshop.json'
    settings = json.loads(path.read_text()) if path.is_file() else {'version': 1}
    settings.update(app_id=payload['app_id'], published_file_id=published_id)
    desktop.atomic_json(path, settings)
    return result
