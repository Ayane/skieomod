"""Remove Custom Map and the installed CLI while preserving authored content."""
from __future__ import annotations
from importlib import metadata, util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

if __package__ == 'tools':
    from . import skieo_install as desktop
    from .custom_packages import ManifestError
else:
    import skieo_install as desktop
    from custom_packages import ManifestError

PACKAGE = 'skieo-custom-map'


def cli_command():
    """Use the manager of this installation, including pipx's exposed launcher."""
    try:
        distribution = metadata.distribution(PACKAGE)
    except metadata.PackageNotFoundError:
        return None
    # A wheel build leaves source .egg-info on sys.path when running tools/*.py.
    # It has no installation record and must not trigger a package uninstall.
    if not distribution.read_text('RECORD') and not distribution.read_text('installed-files.txt'):
        return None
    prefix = Path(sys.prefix)
    record = prefix / 'pipx_metadata.json'
    if record.is_file():
        main = json.loads(record.read_text(encoding='utf-8')).get('main_package', {})
        if re.sub(r'[-_.]+', '-', main.get('package') or '').lower() == PACKAGE:
            executable = shutil.which('pipx')
            if not executable:
                raise ManifestError('pipx is required to remove this installation. Restore pipx on PATH, then retry.')
            # The venv name includes any pipx installation suffix.
            env = dict(os.environ)
            env['PIPX_HOME'] = str(prefix.parent.parent)
            launcher = Path(sys.argv[0]).expanduser().absolute()
            name = 'skieomod' + main.get('suffix', '')
            if launcher.name in (name, name + '.exe') and launcher.is_file() and not launcher.is_relative_to(prefix):
                # A custom pipx bin directory may no longer be set in this shell.
                env['PIPX_BIN_DIR'] = str(launcher.parent)
            return [executable, 'uninstall', prefix.name], env
    if util.find_spec('pip') is None:
        raise ManifestError('pip is required to remove this installation. Install pip in this Python environment, then retry.')
    return [sys.executable, '-m', 'pip', 'uninstall', '--yes', PACKAGE], None


def loader_locations(args):
    """Resolve installed copies without setup, downloads or configuration writes."""
    if args.ue4ss_mods:
        # An explicit Mods folder needs no saved configuration or Steam detection.
        return [args.ue4ss_mods.expanduser().resolve() / desktop.LOADER_NAME]
    config = desktop.load_config()
    if args.game_dir:
        game = desktop.game_paths(args.game_dir, args.app_id)
        if game['game_dir'] != config.get('game_dir'):
            config = game
        else:
            copies = config.get('custom_map_locations', []) + game['custom_map_locations']
            config = {**game, **config, 'custom_map_locations': copies}
    elif config.get('game_dir'):
        try:
            game = desktop.game_paths(config['game_dir'], config.get('app_id'))
            copies = config.get('custom_map_locations', []) + game['custom_map_locations']
            config = {**game, **config, 'custom_map_locations': copies}
        except ManifestError:
            pass  # Remembered Mods paths still work after Steam removes the game.
    elif not config.get('ue4ss_mods'):
        games = desktop.detect_games()
        if games:
            config = desktop.choose_game(games)
    candidates = [Path(path) for path in config.get('custom_map_locations', [])]
    for key in ('ue4ss_mods', 'maps_dir'):
        if config.get(key):
            candidates.append(Path(config[key]) / desktop.LOADER_NAME)
    if config.get('ue4ss_dir'):
        candidates.append(Path(config['ue4ss_dir']) / 'Mods' / desktop.LOADER_NAME)
    locations = []
    for path in candidates:
        if path.name != desktop.LOADER_NAME:
            raise ManifestError('Invalid Custom Map installation path: ' + str(path))
        # Resolve the parent, retaining a final symlink so it can be unlinked safely.
        path = path.expanduser().parent.resolve() / path.name
        if path not in locations:
            locations.append(path)
    return locations


def remove_loader(location, *, check=False):
    mods_file = location.parent / 'mods.txt'
    text = mods_file.read_text(encoding='utf-8-sig') if mods_file.is_file() else ''
    updated = re.sub(r'(?m)^[ \t]*SkiEO-CustomMaps[ \t]*:[^\r\n]*(?:\r?\n|$)', '', text)
    present = location.exists() or location.is_symlink()
    if not present and text == updated:
        return False
    if check:
        if present:
            print('Would remove Custom Map: ' + str(location))
        if text != updated:
            print('Would remove Custom Map entry: ' + str(mods_file))
        return True
    backup = None
    if present:
        if location.is_symlink():
            location.unlink()
        elif location.is_dir():
            backup_root = location.parent / '.skieomod-backups'
            if backup_root.is_symlink():
                raise ManifestError('The uninstall backup directory must not be a symlink: ' + str(backup_root))
            backup = backup_root / ('uninstall-' + str(time.time_ns()))
            backup.mkdir(parents=True)
            location.rename(backup / desktop.LOADER_NAME)
        else:
            raise ManifestError('Custom Map installation is not a directory: ' + str(location))
        print('Custom Map removed: ' + str(location))
        if backup:
            print('Mod files and settings backed up: ' + str(backup / desktop.LOADER_NAME))
    if text != updated:
        if backup:
            shutil.copy2(mods_file, backup / 'mods.txt')
        mods_file.write_text(updated, encoding='utf-8')
    return True


def unregister_protocol(*, check=False):
    """Remove legacy URI registrations belonging to the current interpreter."""
    if sys.platform == 'win32':
        import winreg
        root = r'Software\Classes\skieomod'
        expected = subprocess.list2cmdline([sys.executable, '-m', 'custom_map', 'uri']) + ' "%1"'
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, root + r'\shell\open\command') as key:
                command = winreg.QueryValueEx(key, '')[0]
        except FileNotFoundError:
            return
        if command != expected:
            return
        if not check:
            def delete(path):
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
                    children = [winreg.EnumKey(key, i) for i in range(winreg.QueryInfoKey(key)[0])]
                for child in children:
                    delete(path + '\\' + child)
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
            delete(root)
        print(('Would remove' if check else 'Removed') + ' skieomod:// registration')
        return
    if sys.platform == 'darwin':
        return
    data = Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local/share')))
    config = Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home() / '.config')))
    entry = data / 'applications/skieomod.desktop'
    if not entry.is_file():
        return
    expected = 'Exec=' + desktop.desktop_quote(sys.executable) + ' -m custom_map uri %u'
    if expected not in entry.read_text(encoding='utf-8').splitlines():
        return
    if not check:
        for directory in (config, entry.parent):
            for path in directory.glob('*mimeapps.list'):
                lines = path.read_text(encoding='utf-8').splitlines(keepends=True)
                updated = []
                for line in lines:
                    if re.match(r'^[ \t]*x-scheme-handler/skieomod[ \t]*=', line):
                        prefix, value = line.split('=', 1)
                        handlers = [item for item in value.strip().split(';') if item]
                        if entry.name not in handlers:
                            updated.append(line)
                            continue
                        handlers = [item for item in handlers if item != entry.name]
                        if handlers:
                            updated.append(prefix + '=' + ';'.join(handlers) + ';\n')
                    else:
                        updated.append(line)
                if updated != lines:
                    path.write_text(''.join(updated), encoding='utf-8')
        entry.unlink()
        if shutil.which('update-desktop-database'):
            subprocess.run(['update-desktop-database', str(entry.parent)], check=True)
    print(('Would remove' if check else 'Removed') + ' skieomod:// registration')


def uninstall(args):
    # Resolve the package manager before changing the game installation.
    command = cli_command() if not args.mod_only else None
    locations = loader_locations(args) if not args.cli_only else []
    if not args.cli_only:
        found = False
        for location in locations:
            found = remove_loader(location, check=args.check) or found
        if not found:
            print('Custom Map is already absent.')
    if not args.mod_only:
        unregister_protocol(check=args.check)
        if command:
            argv, env = command
            print(('Would run: ' if args.check else 'Removing CLI: ') + subprocess.list2cmdline(argv), flush=True)
            if not args.check:
                subprocess.run(argv, env=env, check=True)
        else:
            print('The CLI package is not installed in this Python environment; source files are preserved.')
