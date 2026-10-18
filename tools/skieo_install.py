"""Local Ski-E-O! installation, persistent paths and desktop URI integration."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import signal
import shutil
import subprocess
import sys
import sysconfig
import tempfile
import time
from urllib.parse import parse_qs, urlparse
from urllib.request import urlopen
import zipfile

if __package__ == 'tools':
    from .custom_packages import ManifestError
    from .custom_maps import safe_relative_path
    from . import skieo_loader as loader_release
else:
    from custom_packages import ManifestError
    from custom_maps import safe_relative_path
    import skieo_loader as loader_release

PRIMARY_REPOSITORY = 'https://skieomod.emillon.fr'
APP_IDS = ('4493130', '5012760')
LOADER_NAME = 'SkiEO-CustomMaps'
# Retain the tested UE 5.8 build on our server: upstream's rolling tag deletes assets.
UE4SS_ARCHIVE = 'UE4SS_v3.0.1-1152-ge3ba1016.zip'
UE4SS_URL = PRIMARY_REPOSITORY + '/downloads/' + UE4SS_ARCHIVE
UE4SS_SHA256 = 'af8ea9d8975e8eff7967423f43b8b50875e66a29a0f434cffce6e0867ea17252'
UE4SS_MAX_BYTES = 16 * 1024 * 1024
STEAM_START_TIMEOUT = 120
EDITOR_LAUNCH_TIMEOUT = 120


def read_ue4ss_archive(path):
    """Read only the retained, tested build when preparing or publishing a release."""
    with Path(path).open('rb') as source:
        data = source.read(UE4SS_MAX_BYTES + 1)
    if len(data) > UE4SS_MAX_BYTES:
        raise ManifestError('UE4SS download exceeds its limit')
    if hashlib.sha256(data).hexdigest() != UE4SS_SHA256:
        raise ManifestError('UE4SS SHA-256 mismatch')
    return data


def config_directory():
    if os.environ.get('SKIEOMOD_CONFIG_DIR'):
        return Path(os.environ['SKIEOMOD_CONFIG_DIR']).expanduser()
    if sys.platform == 'win32':
        return Path(os.environ.get('APPDATA', str(Path.home() / 'AppData/Roaming'))) / 'skieomod'
    if sys.platform == 'darwin':
        return Path.home() / 'Library/Application Support/skieomod'
    return Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home() / '.config'))) / 'skieomod'


def load_config():
    path = config_directory() / 'config.json'
    if not path.exists():
        return {'version': 1}
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict) or data.get('version') != 1:
        raise ManifestError('Unsupported skieomod configuration; run skieomod config to inspect it.')
    return data


def atomic_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    staged = path.with_name(path.name + '.' + secrets.token_hex(6) + '.part')
    try:
        staged.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        os.replace(staged, path)
    finally:
        staged.unlink(missing_ok=True)


def save_config(data):
    atomic_json(config_directory() / 'config.json', data)


def read_vdf(path):
    if not path.is_file():
        return {}
    text = path.read_text(encoding='utf-8-sig', errors='replace')
    if len(text) > 16 * 1024 * 1024:
        raise ManifestError('Steam configuration is too large')
    tokens = iter(re.findall(r'"(?:\\.|[^"\\])*"|[{}]|//[^\n]*', text))
    def value(token):
        return re.sub(r'\\(["\\])', r'\1', token[1:-1])
    def section(depth=0):
        if depth > 32:
            raise ManifestError('Steam configuration is too deeply nested')
        result = {}
        for token in tokens:
            if token.startswith('//'):
                continue
            if token == '}':
                break
            if not token.startswith('"'):
                raise ManifestError('Invalid Steam configuration')
            child = next(tokens, '')
            result[value(token)] = section(depth + 1) if child == '{' else value(child)
        return result
    return section()


def steam_roots():
    home = Path.home()
    paths = [home / '.steam/steam', home / '.steam/root', home / '.local/share/Steam',
             home / '.var/app/com.valvesoftware.Steam/.local/share/Steam', home / 'Library/Application Support/Steam']
    if sys.platform == 'win32':
        import winreg
        for hive, key, field in [(winreg.HKEY_CURRENT_USER, r'Software\Valve\Steam', 'SteamPath'),
                                  (winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\WOW6432Node\Valve\Steam', 'InstallPath')]:
            try:
                with winreg.OpenKey(hive, key) as entry:
                    paths.append(Path(winreg.QueryValueEx(entry, field)[0]))
            except OSError:
                pass
        for name in ['PROGRAMFILES(X86)', 'PROGRAMFILES']:
            if os.environ.get(name):
                paths.append(Path(os.environ[name]) / 'Steam')
    return list(dict.fromkeys(path.resolve() for path in paths if path.is_dir()))


def steam_libraries(roots=None):
    libraries = []
    for root in steam_roots() if roots is None else roots:
        root = Path(root).resolve()
        libraries.append(root)
        for config in [root / 'steamapps/libraryfolders.vdf', root / 'config/libraryfolders.vdf']:
            try:
                for entry in read_vdf(config).get('libraryfolders', {}).values():
                    path = entry.get('path') if isinstance(entry, dict) else entry
                    if path and Path(path).is_dir():
                        libraries.append(Path(path).resolve())
            except (OSError, ValueError, ManifestError):
                continue
    return list(dict.fromkeys(libraries))


def game_paths(root, app_id=None):
    root = Path(root).expanduser().resolve()
    # Accept the game folder or its SkiResortSimulator subfolder.
    if root.name == 'SkiResortSimulator':
        root = root.parent
    project = root / 'SkiResortSimulator'
    binary = project / 'Binaries/Win64'
    if not (project / 'Content/Paks').is_dir() or not binary.is_dir():
        raise ManifestError('This folder does not contain the Windows edition of Ski-E-O! (SkiResortSimulator/Content/Paks and Binaries/Win64).')
    loader = binary / 'ue4ss'
    if (binary / 'override.txt').is_file():
        override = (binary / 'override.txt').read_text(encoding='utf-8-sig').strip().strip('"')
        location = Path(override)
        loader = (location if location.is_absolute() else binary / location).resolve().parent
    elif (binary / 'UE4SS.dll').is_file():
        loader = binary
    library = root.parent.parent if root.parent.name == 'common' and root.parent.parent.name == 'steamapps' else None
    if library and not app_id:
        for identifier in APP_IDS:
            manifest = read_vdf(library / ('appmanifest_' + identifier + '.acf')).get('AppState', {})
            if manifest.get('installdir') == root.name:
                app_id = identifier
                break
    mods = loader / 'Mods'
    settings = loader / 'UE4SS-settings.ini'
    settings_text = settings.read_text(encoding='utf-8-sig') if settings.is_file() else ''
    def mods_path(value):
        value = value.strip().strip('"')
        if sys.platform.startswith('linux'):
            value = value.replace('\\', '/')
            if re.match(r'(?i)^z:/', value):
                value = value[2:]
        path = Path(value)
        return (path if path.is_absolute() else loader / path).resolve()
    if settings.is_file():
        match = re.search(r'(?m)^ModsFolderPath[ \t]*=[ \t]*([^\r\n]*)', settings_text)
        if match and match[1].strip():
            mods = mods_path(match[1])
    folders = [mods.resolve()]
    for sign, value in re.findall(r'(?m)^([+-])ModsFolderPaths[ \t]*=[ \t]*([^\r\n]+)', settings_text):
        path = mods_path(value)
        if sign == '+':
            folders.append(path)
        else:
            folders = [folder for folder in folders if folder != path]
    existing = [folder for folder in folders if (folder / LOADER_NAME / 'Scripts/main.lua').is_file()]
    if existing:
        mods = existing[-1]  # UE4SS gives the last matching mod folder precedence.
    return {'game_dir': str(root), 'maps_dir': str(project / 'Content/Paks/~mods'),
            'ue4ss_mods': str(mods.resolve()), 'ue4ss_dir': str(loader), 'binary_dir': str(binary), 'app_id': app_id,
            'custom_map_locations': list(dict.fromkeys(str(folder / LOADER_NAME) for folder in existing)),
            'steamapps_dir': str(library) if library else None}


def detect_games(roots=None):
    result = {}
    for library in steam_libraries(roots):
        for identifier in APP_IDS:
            try:
                manifest = read_vdf(library / 'steamapps' / ('appmanifest_' + identifier + '.acf')).get('AppState', {})
                directory = manifest.get('installdir')
                if not directory or '/' in directory or '\\' in directory or directory in {'.', '..'}:
                    continue
                game = game_paths(library / 'steamapps/common' / directory, identifier)
                result[game['game_dir']] = game
            except (OSError, ValueError, ManifestError):
                continue
    return list(result.values())


def choose_game(candidates):
    if len(candidates) == 1:
        return candidates[0]
    lines = ['Select your Ski-E-O! installation:']
    lines += [f"{index}. {entry['game_dir']} ({'demo' if entry['app_id'] == '5012760' else 'game'})" for index, entry in enumerate(candidates, 1)]
    prompt = '\n'.join(lines) + '\nNumber or game directory path: '
    if sys.stdin.isatty():
        answer = input(prompt).strip().strip('"')
    else:
        try:
            from tkinter import Tk, simpledialog
            window = Tk(); window.withdraw()
            answer = simpledialog.askstring('skieomod', prompt, parent=window)
            window.destroy()
        except Exception as error:
            raise ManifestError('Installation missing or ambiguous. Run skieomod setup --game-dir "PATH TO GAME".') from error
        if answer is None:
            raise ManifestError('Configuration cancelled')
    if answer.isdecimal() and 1 <= int(answer) <= len(candidates):
        return candidates[int(answer) - 1]
    if not answer:
        raise ManifestError('A game directory is required')
    return game_paths(answer)


def configure(args, repository=None):
    config = load_config()
    if getattr(args, 'game_dir', None):
        game = game_paths(args.game_dir, getattr(args, 'app_id', None))
    elif config.get('game_dir'):
        try:
            game = game_paths(config['game_dir'], config.get('app_id'))
        except ManifestError:
            game = choose_game(detect_games())
    else:
        game = choose_game(detect_games())
    for key in ['maps_dir', 'ue4ss_mods']:
        explicit = getattr(args, key, None)
        saved = config.get(key) if game['game_dir'] == config.get('game_dir') else None
        game[key] = str(Path(explicit or saved or game[key]).expanduser().resolve())
    if getattr(args, 'app_id', None):
        game['app_id'] = args.app_id
    config.update(game)
    if repository is not None:  # Reading old configuration remains supported.
        repositories = config.setdefault('repositories', [])
        if repository not in repositories:
            repositories.append(repository)
    else:
        config.pop('repositories', None)
    if getattr(args, 'workshop_app_id', None):
        config['workshop_app_id'] = args.workshop_app_id
    save_config(config)
    return config


def install_ue4ss(config):
    binary = Path(config['binary_dir'])
    loader = Path(config['ue4ss_dir'])
    if (loader / 'UE4SS.dll').is_file() and (binary / 'dwmapi.dll').is_file():
        return
    if (loader / 'UE4SS.dll').exists() or (binary / 'dwmapi.dll').exists():
        raise ManifestError('UE4SS installation is incomplete or a dwmapi.dll proxy already exists. Complete the UE4SS installation before running skieomod setup again.')
    print('Installing UE4SS (compatible with UE 5.8)…')
    with tempfile.TemporaryDirectory(prefix='skieomod-ue4ss-') as folder:
        archive_path = Path(folder) / 'ue4ss.zip'
        digest = hashlib.sha256()
        with urlopen(UE4SS_URL, timeout=120) as source, archive_path.open('wb') as target:
            count = 0
            while chunk := source.read(1024 * 1024):
                count += len(chunk)
                if count > UE4SS_MAX_BYTES:
                    raise ManifestError('UE4SS download exceeds its limit')
                digest.update(chunk); target.write(chunk)
        if digest.hexdigest() != UE4SS_SHA256:
            raise ManifestError('UE4SS SHA-256 mismatch')
        with zipfile.ZipFile(archive_path) as archive:
            infos = [item for item in archive.infolist() if not item.is_dir()]
            if sum(item.file_size for item in infos) > 128 * 1024 * 1024:
                raise ManifestError('Invalid UE4SS archive')
            for item in infos:
                safe_relative_path(item.filename, 'UE4SS file', allow_cooked=True)
            if not {'dwmapi.dll', 'ue4ss/UE4SS.dll'} <= {item.filename for item in infos}:
                raise ManifestError('Unexpected UE4SS archive layout')
            # Validate every CRC before modifying the game folder.
            if archive.testzip():
                raise ManifestError('UE4SS CRC mismatch')
            for item in infos:
                destination = binary / item.filename
                if destination.exists():
                    raise ManifestError(f'Refusing to overwrite existing UE4SS file: {destination}')
            archive.extractall(binary)


def bundled_loader():
    installed = Path(sysconfig.get_path('data')) / 'share/skieomod' / LOADER_NAME
    source = Path(__file__).resolve().parents[1] / 'mod' / LOADER_NAME
    for location in [installed, source]:
        if (location / 'Scripts/main.lua').is_file():
            return location
    raise ManifestError('Custom Map files are missing; reinstall skieomod.')


def bundled_loader_files(source=None):
    source = Path(source) if source else bundled_loader()
    files = loader_release.collect(source)
    guide = source.parents[1] / 'docs/getting-started.md'
    if guide.is_file():
        files['getting-started.md'] = guide.read_bytes()
    return files


def configure_proton(config):
    if not sys.platform.startswith('linux') or not config.get('steamapps_dir') or config.get('app_id') not in APP_IDS:
        return
    registry = Path(config['steamapps_dir']) / 'compatdata' / config['app_id'] / 'pfx/user.reg'
    if not registry.is_file():
        raise ManifestError('Launch Ski-E-O! once through Steam to create its Proton prefix, then run skieomod setup again.')
    text = registry.read_text(encoding='utf-8')
    header = r'[Software\\Wine\\DllOverrides]'
    match = re.search(r'(?m)^' + re.escape(header) + r'[^\n]*\n', text)
    line = '"dwmapi"="native,builtin"\n'
    if match:
        tail = text[match.end():]
        end = re.search(r'(?m)^\[', tail)
        section = tail[:end.start()] if end else tail
        if re.search(r'(?m)^"dwmapi"="(?:native,builtin|native|n,b|n)"\s*$', section):
            return
        updated = re.sub(r'(?m)^"dwmapi"=.*\n?', line, section) if '"dwmapi"=' in section else section.rstrip() + '\n' + line + '\n'
        text = text[:match.end()] + updated + tail[len(section):]
    else:
        text += '\n' + header + ' ' + str(int(time.time())) + '\n' + line
    backup = registry.with_name('user.reg.skieomod-backup-' + str(time.time_ns()))
    shutil.copy2(registry, backup)
    staged = registry.with_name('user.reg.skieomod.part')
    staged.write_text(text, encoding='utf-8'); os.replace(staged, registry)


def install_loader(config):
    source, destination = bundled_loader(), Path(config['ue4ss_mods']) / LOADER_NAME
    files = bundled_loader_files(source)
    install_ue4ss(config)
    destination.mkdir(parents=True, exist_ok=True)
    backup = destination / '.skieomod-backups' / (str(time.time_ns()))
    initial_files = dict(files)
    repositories = source / 'Scripts/repositories.json'
    if repositories.is_file():
        initial_files['Scripts/repositories.json'] = repositories.read_bytes()
    for relative, data in sorted(initial_files.items()):
        target = destination / relative
        # Keep repository choices and previous installations' authored files.
        if target.exists() and relative == 'Scripts/repositories.json':
            continue
        if target.is_file() and target.read_bytes() == data:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            saved = backup / relative; saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, saved)
        staged = target.with_name(target.name + '.skieomod.part')
        staged.write_bytes(data); os.replace(staged, target)
    (destination / 'enabled.txt').touch()
    for previous in config.get('custom_map_locations', []):
        previous = Path(previous)
        if previous.resolve() != destination.resolve() and (previous / 'Scripts/main.lua').is_file():
            old = previous / 'Scripts/main.lua'
            old.rename(old.with_name('main.lua.skieomod-disabled-' + str(time.time_ns())))
            print('Previous copy preserved and disabled: ' + str(previous))
    settings = Path(config['ue4ss_dir']) / 'UE4SS-settings.ini'
    if Path(config['ue4ss_mods']).resolve() != (Path(config['ue4ss_dir']) / 'Mods').resolve():
        location = str(Path(config['ue4ss_mods']).resolve()).replace('\\', '/')
        if sys.platform.startswith('linux'):
            location = 'Z:' + location
        if any(char in location for char in '\r\n'):
            raise ManifestError('Invalid UE4SS Mods folder')
        text = settings.read_text(encoding='utf-8-sig') if settings.exists() else '[Overrides]\n'
        line = '+ModsFolderPaths = ' + location
        if line not in text:
            if settings.exists():
                backup.mkdir(parents=True, exist_ok=True)
                shutil.copy2(settings, backup / 'UE4SS-settings.ini')
            section = re.search(r'(?m)^\[Overrides\]\s*\n', text)
            text = text[:section.end()] + line + '\n' + text[section.end():] if section else '[Overrides]\n' + line + '\n\n' + text
            settings.write_text(text, encoding='utf-8')
    mods_file = destination.parent / 'mods.txt'
    if mods_file.is_file():
        text = mods_file.read_text(encoding='utf-8-sig')
        # enabled.txt is ignored if mods.txt explicitly disables this mod.
        if re.search(r'(?m)^\s*SkiEO-CustomMaps\s*:\s*0\s*$', text):
            text = re.sub(r'(?m)^(\s*SkiEO-CustomMaps\s*:\s*)0(\s*)$', r'\g<1>1\2', text)
            mods_file.write_text(text, encoding='utf-8')
    Path(config['maps_dir']).mkdir(parents=True, exist_ok=True)
    atomic_json(destination / loader_release.RECORD,
                loader_release.manifest(files))
    print('Custom Map installed: ' + str(destination))
    return destination


def update_loader(args):
    # Read remembered paths without rewriting Workshop choices or user settings.
    config = load_config()
    if getattr(args, 'game_dir', None):
        config.update(game_paths(args.game_dir, getattr(args, 'app_id', None)))
    if getattr(args, 'ue4ss_mods', None):
        config['ue4ss_mods'] = str(args.ue4ss_mods.expanduser().resolve())
    if not config.get('ue4ss_mods'):
        raise ManifestError('No configured installation; run skieomod setup first or specify --game-dir.')
    destination = Path(config['ue4ss_mods']) / LOADER_NAME
    if not (destination / 'Scripts/main.lua').is_file():
        raise ManifestError('Custom Map is not installed here; run skieomod setup first.')
    if getattr(args, 'archive', None):
        files, record = loader_release.read_archive(args.archive)
    elif getattr(args, 'bundled', False):
        files = bundled_loader_files()
        record = loader_release.manifest(files)
    elif args.check:
        files, record = None, loader_release.fetch_feed()['loader']
    else:
        files, record = loader_release.fetch_release()
    result = loader_release.update(destination, files, record, check=args.check)
    if not args.check and not getattr(args, 'no_editor_link', False):
        register_protocol()
    print(f"Custom Map: {result['installed']} -> {result['available']}")
    print(f"{len(result['changed'])} file(s) to replace, {len(result['removed'])} obsolete file(s).")
    if result['retained']:
        print('Modified obsolete files preserved: ' + ', '.join(result['retained']))
    if args.check:
        print('Check only; no files modified.')
    elif result['backup']:
        print('Backup: ' + result['backup'])
        print('Custom Map updated. Restart the game to load this version.')
    else:
        print('Custom Map is already up to date.')
    return result


def parse_protocol(uri):
    if len(uri) > 2048:
        raise ManifestError('skieomod URL is too long')
    parsed = urlparse(uri)
    if parsed.scheme != 'skieomod' or parsed.netloc not in {'install', 'play'} or parsed.fragment or parsed.params:
        raise ManifestError('Invalid skieomod URL action')
    identifier = parsed.path.removeprefix('/')
    if len(identifier) > 120 or not re.fullmatch(r'[a-z0-9]+[._-][a-z0-9._-]{1,118}', identifier):
        raise ManifestError('Invalid package identifier in skieomod URL')
    query = parse_qs(parsed.query, keep_blank_values=True, strict_parsing=True)
    if set(query) - {'repository', 'version'} or any(len(value) != 1 for value in query.values()):
        raise ManifestError('Invalid skieomod URL parameters')
    version = query.get('version', ['*'])[0]
    if version != '*' and not re.fullmatch(r'\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?', version):
        raise ManifestError('Invalid version in skieomod URL')
    repository = query.get('repository', [PRIMARY_REPOSITORY])[0]
    origin = urlparse(repository)
    if origin.scheme != 'https' or not origin.netloc or origin.username or origin.password or origin.path not in {'', '/'} or origin.query or origin.fragment:
        raise ManifestError('Invalid repository in skieomod URL')
    repository = repository.rstrip('/')
    if repository not in load_config().get('repositories', [PRIMARY_REPOSITORY]):
        raise ManifestError('Configure this repository with skieomod --repository URL setup before opening its links.')
    return parsed.netloc, identifier, version, repository


def desktop_quote(value):
    # Desktop Entry escaping, no shell interpreter is used.
    value = str(value).replace('\\', '\\\\\\\\').replace('"', '\\\\"').replace('`', '\\\\`').replace('$', '\\\\$').replace('%', '%%')
    return '"' + value + '"'


def register_protocol():
    if sys.platform == 'win32':
        import winreg
        command = subprocess.list2cmdline([sys.executable, '-m', 'custom_map', 'uri']) + ' "%1"'
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r'Software\Classes\skieomod') as key:
            winreg.SetValueEx(key, '', 0, winreg.REG_SZ, 'URL:skieomod Protocol')
            winreg.SetValueEx(key, 'URL Protocol', 0, winreg.REG_SZ, '')
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r'Software\Classes\skieomod\shell\open\command') as key:
            winreg.SetValueEx(key, '', 0, winreg.REG_SZ, command)
        return
    if sys.platform == 'darwin':
        raise ManifestError('The UE4SS loader targets the Windows edition of the game. Use Windows or Linux/Proton.')
    directory = Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local/share'))) / 'applications'
    directory.mkdir(parents=True, exist_ok=True)
    Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home() / '.config'))).mkdir(parents=True, exist_ok=True)
    path = directory / 'skieomod.desktop'
    path.write_text('[Desktop Entry]\nType=Application\nName=skieomod\nNoDisplay=true\nTerminal=false\nExec=' + desktop_quote(sys.executable) + ' -m custom_map uri %u\nMimeType=x-scheme-handler/skieomod;\n', encoding='utf-8')
    subprocess.run(['xdg-mime', 'default', 'skieomod.desktop', 'x-scheme-handler/skieomod'], check=True)
    registered = subprocess.run(['xdg-mime', 'query', 'default', 'x-scheme-handler/skieomod'], text=True, capture_output=True, check=True)
    if registered.stdout.strip() != 'skieomod.desktop':
        raise ManifestError('Could not register the skieomod protocol; check xdg-utils and your desktop configuration.')
    if shutil.which('update-desktop-database'):
        subprocess.run(['update-desktop-database', str(directory)], check=True)


def launch_game(config):
    identifier = config.get('app_id')
    if identifier not in APP_IDS:
        raise ManifestError('Steam AppID not found. Run skieomod setup --app-id 5012760 (demo) or 4493130 (game).')
    uri = 'steam://rungameid/' + identifier
    if sys.platform == 'win32':
        os.startfile(uri)
    else:
        subprocess.Popen(['xdg-open', uri], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def editor_launch_plan(config, token):
    """Start a separate game process; Steam's run URI cannot create a second instance."""
    if not re.fullmatch(r'[0-9a-f]{32}', token): raise ManifestError('Invalid editor session identifier')
    if config.get('app_id') not in APP_IDS: raise ManifestError('Configure the game in the Game menu to enable Play.')
    binary = Path(config.get('binary_dir', '')) / 'skieogame.exe'
    if not binary.is_file(): raise ManifestError('Configure the Steam game folder in the Game menu to enable Play.')
    environment = {**os.environ, 'SKIEOMOD_EDITOR_SESSION': token,
                   'SteamAppId': config['app_id'], 'SteamGameId': config['app_id']}
    arguments = [str(binary), '-SkiEOEditorSession=' + token]
    if sys.platform.startswith('linux'):
        roots = steam_roots()
        library = Path(config.get('steamapps_dir') or binary.parents[4])
        prefix = library / 'compatdata' / config['app_id']
        if not (prefix / 'pfx').is_dir(): raise ManifestError('Launch the game once in Steam to prepare Proton before using Play.')
        selected = None
        for root in roots:
            data = read_vdf(root / 'config/config.vdf')
            mapping = data.get('InstallConfigStore', {}).get('Software', {}).get('Valve', {}).get('Steam', {}).get('CompatToolMapping', {})
            selected = mapping.get(config['app_id'], mapping.get('0', {})).get('name') or selected
        previous = None
        record = prefix / 'config_info'
        if record.is_file() and record.stat().st_size < 65536:
            for line in record.read_text(encoding='utf-8', errors='replace').splitlines():
                if '/files/' in line:
                    candidate = Path(line.split('/files/', 1)[0])
                    if (candidate / 'proton').is_file(): previous = candidate.resolve();break
        candidates = []
        for root in dict.fromkeys([*roots, library.parent]):
            for parent in (root / 'steamapps/common', root / 'compatibilitytools.d'):
                if not parent.is_dir(): continue
                for folder in parent.iterdir():
                    if not (folder / 'proton').is_file(): continue
                    definition = folder / 'compatibilitytool.vdf'
                    text = definition.read_text(encoding='utf-8-sig') if definition.is_file() else ''
                    # Valve's tool manifests allow bare keys and platform
                    # conditions, unlike the quoted configuration subset.
                    matching = bool(selected and re.search(r'(?:^|\s)"?' + re.escape(selected) + r'"?\s*\{', text))
                    aliases={'proton_experimental':'Proton - Experimental','proton_hotfix':'Proton Hotfix'}
                    major=re.fullmatch(r'proton_(\d+)',selected or '')
                    matching=matching or aliases.get(selected)==folder.name or bool(major and folder.name.startswith('Proton ' + major[1] + '.'))
                    candidates.append((3 if matching else 2 if previous==folder.resolve() else 0, folder))
        if not candidates: raise ManifestError('Install Proton through Steam to enable editor Play.')
        _, proton = max(candidates, key=lambda item: (item[0], item[1].stat().st_mtime, str(item[1])))
        client = next((root for root in roots if (root / 'config').is_dir()), None)
        if client is None: raise ManifestError('The Steam client folder could not be found.')
        environment.update(STEAM_COMPAT_DATA_PATH=str(prefix), STEAM_COMPAT_CLIENT_INSTALL_PATH=str(client))
        override = environment.get('WINEDLLOVERRIDES', '')
        environment['WINEDLLOVERRIDES'] = override + (';' if override else '') + 'dwmapi=n,b'
        # runinprefix skips Proton's prefix setup, including the native DLL
        # overrides that enable DXVK/VKD3D. It can silently start WineD3D
        # instead and give editor tests a different renderer from Steam.
        # run initializes the selected Proton tool and still starts a separate
        # process, with this editor's session token passed to the game.
        arguments = [str(proton / 'proton'), 'run', *arguments]
    elif sys.platform != 'win32':
        raise ManifestError('Editor Play requires Windows or the Windows game running through Proton.')
    return arguments, environment, binary.parent


def editor_session_state(config, token):
    path = Path(config.get('ue4ss_mods', '')) / LOADER_NAME / ('Scripts/editor-session-' + token + '.json')
    try:
        if path.stat().st_size > 4096: return None
        data = json.loads(path.read_text(encoding='utf-8'))
        if data.get('session') == token and 0 <= time.time() - data.get('updated', 0) <= 5:
            return data
    except (OSError, ValueError, TypeError): pass
    return None


def steam_client_ready(client):
    """Require a live native client and completion of this client's startup.

    The PID file and FIFO appear before Steam can serve the game's API calls.
    Ignore previous startups in the persistent console log by comparing their
    timestamps with the current PID file, which Steam rewrites on startup.
    """
    for marker in (Path.home() / '.steam/steam.pid', client / 'steam.pid'):
        try:
            pid = int(marker.read_text(encoding='ascii').strip())
            if pid <= 1 or Path('/proc', str(pid), 'comm').read_text().strip() != 'steam':
                continue
            started = marker.stat().st_mtime
            with (client / 'logs/console_log.txt').open('rb') as source:
                # An active client can write more than 64 KiB after startup.
                # Keep only the latest marker while streaming the log; a tail
                # window wrongly treats a long-running client as unready.
                latest = None
                for line in source:
                    if b'System startup time:' in line:
                        latest = line
            if latest:
                stamp = latest[1:20].decode('ascii')
                timestamp = time.mktime(time.strptime(stamp, '%Y-%m-%d %H:%M:%S'))
                return timestamp >= started - 2
        except (OSError, ValueError):
            continue
    return False


def ensure_editor_steam(environment):
    """Boot Steam outside the test's Proton environment and process group."""
    if not sys.platform.startswith('linux'):
        return
    client = Path(environment['STEAM_COMPAT_CLIENT_INSTALL_PATH'])
    if steam_client_ready(client):
        return
    executable = shutil.which('steam')
    if executable is None and (client / 'steam.sh').is_file():
        executable = str(client / 'steam.sh')
    if executable is None:
        raise ManifestError('Start Steam and sign in before using editor Play; the Steam launcher could not be found.')
    # Steam inherits these variables when a closed client is booted through
    # Wine's Steam bridge. Its own helpers then register as the game, blocking
    # the relaunch and leaving Steam stuck on "Running".
    excluded = {'SKIEOMOD_EDITOR_SESSION', 'SteamAppId', 'SteamGameId', 'SteamOverlayGameId',
                'WINEPREFIX', 'WINEDLLOVERRIDES', 'WINELOADER', 'WINESERVER', 'WINEDEBUG'}
    clean = {key: value for key, value in os.environ.items()
             if key not in excluded and not key.startswith(('STEAM_COMPAT_', 'PROTON_'))}
    print('Starting Steam; waiting for initialization. Sign in to Steam if prompted.', flush=True)
    try:
        subprocess.Popen([executable, '-silent'], env=clean, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError as error:
        raise ManifestError('Could not start Steam: ' + str(error)) from error
    deadline = time.monotonic() + STEAM_START_TIMEOUT
    while time.monotonic() < deadline:
        if steam_client_ready(client):
            return
        time.sleep(.5)
    raise ManifestError('Steam did not finish initialization. Open Steam, sign in, then retry Play.')


def editor_game_pids(token, binary, *, proc=Path('/proc')):
    """Wine reparents its game process and gives it a separate process group."""
    if not token or not binary:
        return []
    result = []
    try:
        entries = list(proc.iterdir())
    except OSError:
        return result
    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            environment = (entry / 'environ').read_bytes().split(b'\0')
            if ('SKIEOMOD_EDITOR_SESSION=' + token).encode() not in environment:
                continue
            arguments = (entry / 'cmdline').read_bytes().split(b'\0')
            if ('-SkiEOEditorSession=' + token).encode() not in arguments:
                continue
            executable = arguments[0].decode('utf-8', errors='replace').replace('\\', '/')
            if executable[:2].lower() == 'z:':
                executable = executable[2:]
            if Path(executable).resolve() == Path(binary).resolve():
                result.append(int(entry.name))
        except OSError:
            continue
    return result


def stop_editor_launch(process, *, token=None, binary=None):
    """Clean up only the process/group created by this failed Play request."""
    def stop(force=False):
        try:
            if sys.platform.startswith('linux'):
                for pid in editor_game_pids(token, binary):
                    try:
                        os.kill(pid, signal.SIGKILL if force else signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                os.killpg(process.pid, signal.SIGKILL if force else signal.SIGTERM)
            elif process.poll() is None:
                process.kill() if force else process.terminate()
        except ProcessLookupError:
            pass
    stop()
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        stop(force=True)
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            pass
    if sys.platform.startswith('linux'):
        # The Proton helper can exit while Wine's detached game still runs.
        # Recheck both the executable and this editor's token before stopping it.
        for pid in editor_game_pids(token, binary):
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def request_play(config, release, *, editor_session=None):
    if release['kind'] != 'map':
        raise ManifestError('Playing requires a map; use skieomod install for a mod.')
    if config.get('app_id') not in APP_IDS:
        raise ManifestError('Steam AppID not found; use skieomod setup --app-id.')
    plan = editor_launch_plan(config, editor_session) if editor_session else None
    scripts = Path(config['ue4ss_mods']) / LOADER_NAME / 'Scripts'
    suffix = '-' + editor_session if editor_session else ''
    path = scripts / ('launch-request' + suffix + '.json')
    package = Path(config['maps_dir']) / (release['id'] + '-' + release['version'] + '.skieomap')
    if not package.is_file():
        raise ManifestError('The map to launch is not installed')
    try:
        package_path = os.path.relpath(package, path.parent).replace('\\', '/')
    except ValueError:
        package_path = str(package)
    request_id = secrets.token_hex(16)
    request = {'format': 'skieomod-launch', 'version': 1, 'id': release['id'],
               'map_version': release['version'], 'created': int(time.time()), 'request_id': request_id,
               'package_path': package_path}
    if editor_session: request['editor_session'] = editor_session
    state = editor_session_state(config, editor_session) if editor_session else None
    if state and state.get('state') == 'loading': raise ManifestError('The editor test is still loading.')
    if editor_session and not state:
        ensure_editor_steam(plan[1])
    atomic_json(path, request)
    if editor_session:
        process = None
        log_path = config_directory() / 'logs' / ('editor-' + editor_session + '.log')
        try:
            if state:
                print('Reloading the editor test instance with ' + release['id'], flush=True)
            else:
                arguments, environment, directory = plan
                log_path.parent.mkdir(parents=True, exist_ok=True)
                with log_path.open('wb') as log:
                    process = subprocess.Popen(arguments, cwd=directory, env=environment, stdin=subprocess.DEVNULL,
                                               stdout=log, stderr=log, start_new_session=True)
                print('Starting a separate editor test instance with ' + release['id'], flush=True)
                print('Editor launch log: ' + str(log_path), flush=True)
            deadline = time.monotonic() + EDITOR_LAUNCH_TIMEOUT
            result_path = scripts / ('launch-result' + suffix + '.json')
            while time.monotonic() < deadline:
                try:
                    result = json.loads(result_path.read_text(encoding='utf-8'))
                    if result.get('request_id') == request_id:
                        if result.get('status') == 'error': raise ManifestError(result.get('message', 'Editor test failed'))
                        print('Editor test accepted; the map is loading.', flush=True)
                        return
                except (OSError, json.JSONDecodeError): pass
                if process is not None and process.poll() is not None and not editor_session_state(config, editor_session):
                    raise ManifestError(f'The editor test exited before responding (exit code {process.returncode}). '
                                        f'Check {log_path} and the UE4SS log in {config.get("ue4ss_dir", config.get("binary_dir", "the game folder"))}.')
                time.sleep(.25)
            raise ManifestError('The test instance did not respond. '
                                + (f'Check {log_path} and the Custom Maps log.' if process else 'Check the Custom Maps log.'))
        except (OSError, ManifestError, KeyboardInterrupt) as error:
            path.unlink(missing_ok=True)
            if process is not None:
                stop_editor_launch(process, token=editor_session, binary=directory / 'skieogame.exe')
            if isinstance(error, OSError):
                raise ManifestError('Could not start the editor test: ' + str(error)) from error
            raise
    else:
        launch_game(config)
        print('Launching Ski-E-O! with ' + release['id'])


def setup(args, repository=None, *, protocol=False):
    config = configure(args, repository)
    configure_proton(config)
    install_loader(config)
    if __package__ == 'tools':
        from . import skieo_workshop as workshop
    else:
        import skieo_workshop as workshop
    app, roots = workshop.content_roots(config)
    scripts = Path(config['ue4ss_mods']) / LOADER_NAME / 'Scripts'
    locations = []
    for root in roots:
        try:
            locations.append(os.path.relpath(root, scripts).replace('\\', '/'))
        except ValueError:
            locations.append(str(root))
    atomic_json(scripts / 'workshop.json', {'format': 'skieomod-workshop-paths', 'version': 1,
                'app_id': app, 'content_roots': locations})
    if protocol:
        register_protocol()
        config['protocol_registered'] = True
        save_config(config)
    print('Configuration saved: ' + str(config_directory() / 'config.json'))
    return config
