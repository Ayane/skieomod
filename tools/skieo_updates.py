"""Small background release checks, keyed by the installed Steam revision."""
from __future__ import annotations
import json
import os
from pathlib import Path
import subprocess
import sys
import time

if __package__ == 'tools':
    from . import skieo_install as desktop, skieo_loader as loader
    from .custom_maps import semver_compare
else:
    import skieo_install as desktop, skieo_loader as loader
    from custom_maps import semver_compare

CHECK_INTERVAL = 24 * 60 * 60
RETRY_INTERVAL = 60 * 60
LOCK_SECONDS = 60


def game_revision(config):
    app = config.get('app_id')
    if app not in desktop.APP_IDS or not config.get('game_dir'):
        return None
    game = Path(config['game_dir']).expanduser().resolve()
    library = Path(config.get('steamapps_dir') or game.parent.parent)
    manifest = desktop.read_vdf(library / ('appmanifest_' + app + '.acf')).get('AppState', {})
    build = manifest.get('buildid')
    if (manifest.get('installdir') != game.name or not isinstance(build, str)
            or not build.isascii() or not build.isdecimal()):
        return None
    return {'app_id': app, 'build_id': build, 'game_dir': str(game)}


def read_status():
    path = desktop.config_directory() / 'update-status.json'
    try:
        if path.stat().st_size > 1024 * 1024:
            return {}
        status = json.loads(path.read_text(encoding='utf-8'))
        return status if isinstance(status, dict) and status.get('version') == 1 else {}
    except (OSError, ValueError):
        return {}


def check_due(config, status, *, now=None):
    revision = game_revision(config)
    if not revision:
        return False
    if status.get('game') != revision:
        return True
    now = time.time() if now is None else now
    interval = RETRY_INTERVAL if status.get('failed') else CHECK_INTERVAL
    last = status.get('attempted', 0)
    return not isinstance(last, (int, float)) or not 0 <= now - last < interval


def _claim_lock():
    path = desktop.config_directory() / 'update-check.lock'
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        if time.time() - path.stat().st_mtime > LOCK_SECONDS:
            path.unlink(missing_ok=True)
    except FileNotFoundError:
        pass
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return None
    with os.fdopen(fd, 'w') as stream:
        stream.write(str(os.getpid()))
    return path


def check_now(*, force=False, claimed=False):
    """Never change the installation or block a game/map action on networking."""
    lock = desktop.config_directory() / 'update-check.lock' if claimed else None
    try:
        config = desktop.load_config()
        status = read_status()
        if not game_revision(config) or not force and not check_due(config, status):
            return status
        if not claimed:
            lock = _claim_lock()
            if lock is None:
                return status
        revision = game_revision(config)
        next_status = {'version': 1, 'game': revision, 'attempted': time.time()}
        try:
            feed = loader.fetch_feed(timeout=5)
            next_status.update(feed=feed, failed=False)
        except Exception:
            # Preserve the last successful answer for this installation. A
            # network outage remains silent and is retried after one hour.
            if status.get('game') == revision and status.get('feed'):
                next_status['feed'] = status['feed']
            next_status['failed'] = True
        desktop.atomic_json(desktop.config_directory() / 'update-status.json', next_status)
        return next_status
    except (OSError, ValueError, desktop.ManifestError):
        return {}
    finally:
        if lock is not None:
            lock.unlink(missing_ok=True)


def start_check(*, force=False):
    """Detach a bounded metadata query so even short CLI commands can finish."""
    lock = None
    try:
        config = desktop.load_config()
        if not game_revision(config) or not force and not check_due(config, read_status()):
            return None
        lock = _claim_lock()
        if lock is None:
            return None
        code = ('import sys;sys.path.insert(0,sys.argv[1]);'
                'from skieo_updates import check_now;check_now(force=' + repr(force) + ',claimed=True)')
        kwargs = {'stdin': subprocess.DEVNULL, 'stdout': subprocess.DEVNULL,
                  'stderr': subprocess.DEVNULL, 'start_new_session': True}
        if sys.platform == 'win32':
            kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW
        return subprocess.Popen([sys.executable, '-c', code, str(Path(__file__).resolve().parent)], **kwargs)
    except (OSError, ValueError, desktop.ManifestError):
        if lock is not None:
            lock.unlink(missing_ok=True)
        return None


def notices(config=None):
    """Cached release and revision information; this function performs no HTTP."""
    try:
        config = desktop.load_config() if config is None else config
        revision = game_revision(config)
        if not revision:
            return []
        record = loader.installed_record(Path(config.get('ue4ss_mods', '')) / loader.NAME)
        installed = record['release'] if record else 'unknown'
        tested = (record or {}).get('game_builds', {}).get(revision['app_id'])
        messages = []
        if tested and tested != revision['build_id']:
            messages.append('Steam revision ' + revision['build_id'] + ' has not been verified with '
                            'Custom Map ' + installed + ' (tested revision ' + tested + ').')
        status = read_status()
        feed = status.get('feed') if status.get('game') == revision else None
        if not feed:
            return messages
        available = loader.validate_record(feed['loader'])['release']
        if semver_compare(loader.VERSION, available) < 0:
            messages.append('skieomod ' + available + ' is available. Upgrade with: '
                            'pipx upgrade skieo-custom-map --pip-args="--index-url '
                            + loader.DOWNLOAD_BASE + 'pypi/"')
        if not record or semver_compare(installed, available) < 0:
            messages.append('Custom Map ' + available + ' is available. Run: skieomod update')
        return messages
    except (OSError, ValueError, KeyError, TypeError, desktop.ManifestError):
        return []
