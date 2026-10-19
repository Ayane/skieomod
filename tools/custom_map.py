#!/usr/bin/env python3
"""skieomod: create, build, run and publish Ski-E-O! maps and mods."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from urllib.error import URLError
import zipfile

if __package__ == "tools":
    from .custom_packages import ManifestError, inspect_package, pack_package, resolve, MANIFESTS
    from . import skieo_install as desktop, skieo_project as projects, skieo_workshop as workshop
    from .skieo_loader import VERSION, installed_mapmods, fetch_mapmod_dependencies
    from . import skieo_updates as updates
    from . import skieo_repository as web_repository
else:
    from custom_packages import ManifestError, inspect_package, pack_package, resolve, MANIFESTS
    import skieo_install as desktop
    import skieo_project as projects
    import skieo_workshop as workshop
    from skieo_loader import VERSION, installed_mapmods, fetch_mapmod_dependencies
    import skieo_updates as updates
    import skieo_repository as web_repository


def prepare(path, temporary):
    if path.is_dir():
        path = projects.project_manifest(path)
    if path.suffix.lower() == ".json":
        archive = Path(temporary) / "package.zip"
        projects.build(path, archive, save_build_metadata=False)
        return archive
    return path


def check_scripts(path):
    compiler = shutil.which("luac5.4") or shutil.which("luac")
    if not compiler or 'Lua 5.4' not in subprocess.check_output([compiler, '-v'], text=True, stderr=subprocess.STDOUT):
        raise ManifestError("install Lua 5.4 / luac to use --check-scripts")
    with zipfile.ZipFile(path) as archive, tempfile.TemporaryDirectory(prefix="custom-map-lua-") as directory:
        for index, item in enumerate(archive.infolist()):
            if item.filename.endswith(".lua"):
                target = Path(directory) / f"{index}.lua"
                target.write_bytes(archive.read(item))
                result = subprocess.run([compiler, "-p", str(target)], capture_output=True, text=True)
                if result.returncode:
                    raise ManifestError(f"{item.filename}: {result.stderr.strip()}")


def check_dependencies(manifest, kind, packages=()):
    root = {"id": manifest["id"], "kind": kind, "version": manifest["metadata"]["version"], "manifest": manifest}
    return resolve([root, *packages], root["id"], "=" + root["version"])


def install(args, packages, local_archive):
    local_archives = local_archive if isinstance(local_archive, dict) else {args.id: local_archive} if local_archive else {}
    if not isinstance(packages, list) or not 1 <= len(packages) <= 64:
        raise ManifestError("invalid dependency closure")
    roots = [package for package in packages if package['id'] == args.id]
    if len(roots) != 1:
        raise ManifestError('Resolved root package is missing or ambiguous')
    if args.command == 'play' and roots[0]['kind'] != 'map':
        raise ManifestError('Playing requires a map; use skieomod install for a mod.')
    if any(item["kind"] == "mod" and item["manifest"].get("runtime") == "ue4ss" for item in packages) and not args.ue4ss_mods:
        raise ManifestError("UE4SS dependencies require --ue4ss-mods pointing to UE4SS/Mods; restart the game after installation")
    args.maps_dir.mkdir(parents=True, exist_ok=True)
    planned = []
    with tempfile.TemporaryDirectory(prefix="custom-map-install-") as directory:
        for release in packages:
            local = release['id'] in local_archives
            if local:
                path = Path(local_archives[release['id']])
                _, manifest, _ = inspect_package(path, release['kind'])
                if manifest != release['manifest'] or hashlib.sha256(path.read_bytes()).hexdigest() != release['sha256']:
                    raise ManifestError('Local build changed during installation')
            else:
                raise ManifestError("Missing validated local artifact for " + release["id"])
            extension = ".skieomap" if release["kind"] == "map" else ".skieomod"
            target = args.maps_dir / (manifest["id"] + "-" + manifest["metadata"]["version"] + extension)
            if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() != release["sha256"] and not local:
                raise ManifestError(f"refusing to overwrite modified package: {target}")
            if release["kind"] == "mod" and manifest.get("runtime") == "ue4ss":
                destination = args.ue4ss_mods / manifest["install_directory"]
                if destination.exists():
                    installed_manifest = destination / "custom-mod.json"
                    if not installed_manifest.is_file() or json.loads(installed_manifest.read_text()).get("id") != manifest["id"]:
                        raise ManifestError(f"refusing to overwrite existing mod directory: {destination}")
                    if json.loads(installed_manifest.read_text())["metadata"]["version"] != release["version"] and not local:
                        raise ManifestError(f"remove or back up the previous mod version before installing: {destination}")
                planned.append((path, target, destination, manifest))
            else:
                planned.append((path, target, None, manifest))
        # Every local artifact is validated before writing to the game installation.
        for path, target, destination, manifest in planned:
            staged = target.with_suffix(target.suffix + ".part")
            shutil.copyfile(path, staged)
            os.replace(staged, target)
            if destination and (not destination.exists() or manifest['id'] in local_archives):
                destination.parent.mkdir(parents=True, exist_ok=True)
                staged_directory = Path(tempfile.mkdtemp(prefix=".custom-map-", dir=destination.parent))
                saved = None
                try:
                    with zipfile.ZipFile(path) as archive:
                        archive.extractall(staged_directory)
                    (staged_directory / "enabled.txt").touch()
                    if destination.exists():
                        backups = destination.parent / '.skieomod-backups'
                        backups.mkdir(exist_ok=True)
                        saved = backups / (destination.name + '-' + staged_directory.name.removeprefix('.'))
                        os.replace(destination, saved)
                    os.replace(staged_directory, destination)
                except OSError:
                    if saved and saved.exists() and not destination.exists():
                        os.replace(saved, destination)
                    raise
                finally:
                    if staged_directory.exists():
                        shutil.rmtree(staged_directory)
            if destination:
                (destination / 'enabled.txt').touch()
                mods_file = destination.parent / 'mods.txt'
                if mods_file.is_file():
                    text = mods_file.read_text(encoding='utf-8-sig')
                    updated = re.sub(r'(?m)^([ \t]*' + re.escape(destination.name) + r'[ \t]*:[ \t]*)0([ \t]*\r?)$', r'\g<1>1\2', text)
                    if updated != text:
                        backup = destination.parent / '.skieomod-backups'
                        backup.mkdir(exist_ok=True)
                        shutil.copy2(mods_file, backup / ('mods-' + Path(directory).name + '.txt'))
                        mods_file.write_text(updated, encoding='utf-8')
            print(f"Installed {manifest['id']} {manifest['metadata']['version']}: {target}")
    lock = args.maps_dir / "custom-map.lock.json"
    staged_lock = lock.with_suffix(".json.part")
    staged_lock.write_text(json.dumps({"source": "local-development", "root": args.id, "packages": packages}, ensure_ascii=False, indent=2) + "\n")
    os.replace(staged_lock, lock)
    if args.ue4ss_mods:
        scripts = args.ue4ss_mods / desktop.LOADER_NAME / 'Scripts'
        if scripts.is_dir():
            ledger = scripts / 'skieomod-installed.json'
            previous = json.loads(ledger.read_text(encoding='utf-8')) if ledger.is_file() else {'format': 'skieomod-installed', 'version': 1, 'packages': []}
            entries = {(entry['id'], entry['version']): entry for entry in previous['packages']}
            for release in packages:
                if release['kind'] == 'mod' and release['manifest'].get('runtime') == 'ue4ss':
                    continue
                suffix = '.skieomap' if release['kind'] == 'map' else '.skieomod'
                installed = args.maps_dir / (release['id'] + '-' + release['version'] + suffix)
                try:
                    location = os.path.relpath(installed, scripts).replace('\\', '/')
                except ValueError:  # Windows paths on separate volumes.
                    location = str(installed)
                entries[(release['id'], release['version'])] = {'id': release['id'], 'version': release['version'], 'kind': release['kind'], 'path': location}
            previous['packages'] = list(entries.values())
            desktop.atomic_json(ledger, previous)
    if any(destination for _, _, destination, _ in planned):
        print("Restart the game to activate the installed UE4SS dependencies.")
    return roots[0]


def path_arguments(parser):
    parser.add_argument('--game-dir', type=Path, help='Ski-E-O! game folder; detected from Steam and remembered by default')
    parser.add_argument('--maps-dir', type=Path, help='override the configured maps folder')
    parser.add_argument('--ue4ss-mods', type=Path, help='override the configured UE4SS Mods folder')
    parser.add_argument('--app-id', choices=desktop.APP_IDS, help='Steam game/demo AppID')


def create_parser():
    parser = argparse.ArgumentParser(prog="skieomod", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''Quick start:
  skieomod create map --output my-map --name "My station" --author "Your name"
  skieomod editor my-map
  skieomod build my-map
  skieomod test my-map
  skieomod run my-map
  skieomod publish my-map --prepare

Use skieomod help COMMAND or skieomod COMMAND --help for details.
Projects include a README and guides in docs/. Python 3.10+ is required.
Local creation, builds and Workshop preparation work without a Steamworks client.
Remote Workshop commands require a separately supplied native Steamworks client.
Custom Maps and the Featured Veymont map: Albatar (Élie Millon).
Contributions: ReymanHG (ground-cover textures and night lighting).
Credits: https://github.com/Ayane/skieomod#credits''')
    parser.add_argument("--version", action="version", version="skieomod " + VERSION)
    parser.add_argument('--steam-client', type=Path, help='native Steamworks client executable implementing the Workshop JSON protocol')
    commands = parser.add_subparsers(dest="command", title='commands', metavar='COMMAND')

    def command_parser(name, description, examples, **kwargs):
        return commands.add_parser(name, help=description, description=description,
            epilog=examples, formatter_class=argparse.RawDescriptionHelpFormatter, **kwargs)

    editor_parser = command_parser('editor', 'open the native desktop editor for a local map source project',
        '''Examples:
  skieomod editor
  skieomod editor my-map
  skieomod editor my-map/custom-map.json

Create/open source projects, import R16/RAW or PNG16 heightmaps, sculpt terrain,
paint manual trees, configure erosion and automatic vegetation, and Build/Test/Play.
Save keeps authoring files and backups; build derives the portable map metadata.
The desktop editor uses Qt with OpenGL, visual trigger graphs, resources and
map-scoped object CSV overrides. Its dependencies are installed with skieomod.
Preferences choose whether startup reopens the last map, creates a new map,
or shows recent maps with no document open. An explicit project takes precedence.
A graphical desktop with OpenGL is required. Help/build work headlessly.''')
    editor_parser.add_argument('project', nargs='?', type=Path, help='map project folder or custom-map.json (default: editor startup preference)')
    uri_parser = command_parser('uri', 'open the desktop editor from a skieomod link',
        'Example:\n  skieomod uri skieomod://editor\n\nUsed by the Editor button in New Game > Custom Map. Only the editor link is accepted.')
    uri_parser.add_argument('url', help='skieomod://editor')

    new = command_parser('create', 'initialize a documented map, UE4SS mod or mapmod project',
        '''Templates:
  map     Independent world with an R16 slope, editable JSON trees and a Map API script (1 km by default).
  mod     UE4SS script loaded when the game starts; restart after changes.
  mapmod  Map API dependency; run creates a local preview map to test it.

Examples:
  skieomod create map --output my-map --name "My station" --id author.my-map
  skieomod create map --output large-map --size 16000 12000 --spacing 8
  skieomod create mod --output my-mod --author "Your name"
  skieomod create mapmod --output snow-tools

Existing files are never overwritten. 'new' is an alias for 'create'.''', aliases=['new'])
    new.add_argument('kind', choices=['map', 'mod', 'mapmod'], help='project template (see below)')
    new.add_argument('--output', '-o', type=Path, default=Path('.'), help='project directory (default: current directory)')
    new.add_argument('--name', help='display name (default: project directory name)')
    new.add_argument('--id', help='namespaced package identifier, e.g. author.my-map (default: local.NAME)')
    new.add_argument('--author', default='Your name', help='author credit (default: Your name)')
    new.add_argument('--size', '--size-meters', nargs=2, type=float, metavar=('WIDTH', 'LENGTH'),
                     help='map extent in metres, including sizes above 8 km (map only; default: 1024 1024)')
    new.add_argument('--spacing', '--spacing-meters', type=float,
                     help='source sample spacing in metres; must divide both dimensions (map only; default: 16)')
    descriptions = {
        'build': 'validate and build a reproducible local ZIP into bin/',
        'test': 'validate a project, manifest or existing archive without installing it',
        'run': 'build, install and run the local project through Steam',
        'publish': 'publish to the web catalogue or prepare Steam Workshop content',
    }
    examples = {
        'build': '''Examples:
  skieomod build
  skieomod build my-map
  skieomod build my-map --output releases/my-map.skieomap
  skieomod build --check-scripts --check-dependencies

Set build.heightmap in custom-map.json to use headerless unsigned R16LE/R16BE
or non-interlaced 16-bit grayscale PNG. No extra packages are required.
The JSON supplies the source path and spacing_meters. PNG dimensions are read
automatically; raw input assumes a square grid when the file size permits it.
For rectangular raw input supply vertices: [width, height], or one side and null.
Supply elevation_meters or the exporter's height_scale_meters and
height_offset_meters for real altitudes. Without them, build reports a relative
0 to 1000 m test relief. Build calculates dimensions, size, elevation range,
centred origin and preview, and converts the package terrain to portable R16LE.
The original heightmap stays intact. Successful builds update derived metadata
and generated R16 in the project; previous files are kept in .heightmap-backups/.
Optional build.heightmap.processing adds smoothing, thermal/hydraulic erosion
and seeded noise. build.vegetation bakes biome-based ground cover and trees.
build.forest.file compiles manual JSON tree positions into SKXY; automatic
trees are written directly in SKXY. The game reads binary forests only.
See https://skieomod.emillon.fr/tutorials/heightmap/ for the JSON examples.''',
        'test': 'Examples:\n  skieomod test\n  skieomod test my-map --check-scripts\n  skieomod test bin/author.my-map-0.1.0.skieomap\n\nScript checks require Lua 5.4 / luac. Dependency checks read installed Workshop content.',
        'run': 'Examples:\n  skieomod run\n  skieomod run my-map --game-dir "PATH TO GAME"\n\nRequires an installed game and Steam. A mapmod runs in obj/mapmod-preview.\nClose the game first when testing a UE4SS mod. Replaced local mods are backed up.',
        'publish': 'Examples:\n  skieomod publish my-map\n  skieomod publish bin/author.my-map-0.1.0.skieomap\n  skieomod publish my-map --prepare\n  skieomod --steam-client PATH publish my-map --steam\n\nWeb publishing uses CUSTOM_MAP_TOKEN from https://skieomod.emillon.fr/account.\n--prepare stages Steam Workshop content offline in bin/workshop/.\n--steam requires a separately supplied native Steamworks client.',
    }
    for command in ['build', 'test', 'run', 'publish']:
        sub = command_parser(command, descriptions[command], examples[command])
        sub.add_argument('project', nargs='?', type=Path, default=Path('.'), help='project directory or manifest' + (' or archive' if command == 'test' else '') + ' (default: current directory)')
        sub.add_argument('--check-scripts', action='store_true', help='check all packaged Lua scripts with Lua 5.4 / luac')
        if command in {'build', 'test', 'run'}:
            sub.add_argument('--dependency', action='append', type=Path, default=[],
                             help='local mod project or .skieomod to resolve separately (repeatable)')
        if command in {'build', 'test'}:
            sub.add_argument('--check-dependencies', action='store_true', help='check installed Workshop dependency manifests')
        if command == 'build':
            sub.add_argument('--output', '-o', type=Path, help='archive output path (default: PROJECT/bin/ID-VERSION.skieomap or .skieomod)')
        if command == 'run':
            path_arguments(sub)
            sub.add_argument('--editor-session', help=argparse.SUPPRESS)
        if command == 'publish':
            sub.add_argument('--repository', help='web repository origin (default: CUSTOM_MAP_REPOSITORY or https://skieomod.emillon.fr)')
            sub.add_argument('--steam', action='store_true', help='publish through the separately supplied Steamworks client')
            sub.add_argument('--prepare', action='store_true', help='only stage content and the Steamworks publication request')
            sub.add_argument('--app-id', help='consumer Steam AppID (defaults to workshop.json or the full game)')
            sub.add_argument('--item-id', help='existing PublishedFileId to update (decimal string)')
            sub.add_argument('--preview', type=Path, help='preview image path (default: workshop.json preview_file)')
            sub.add_argument('--visibility', choices=['public', 'friends', 'private', 'unlisted'], help='Workshop visibility (default: workshop.json, initially private)')
            sub.add_argument('--changenote', default='', help='description of this Workshop update')
    pack = command_parser('pack', 'create a reproducible local map/mod ZIP',
        'Example:\n  skieomod pack my-map/custom-map.json releases/my-map.skieomap\n\nOnly files referenced by the manifest are included. Prefer build for project workflows.')
    pack.add_argument('manifest', type=Path, help='custom-map.json or custom-mod.json source')
    pack.add_argument('output', type=Path, help='archive output path (.skieomap or .skieomod)')
    browse = command_parser('list', 'list Steam Workshop articles or the local Steam inventory',
        'Examples:\n  skieomod list --installed\n  skieomod list --installed --kind mod\n  skieomod --steam-client PATH list --kind map --search snow\n\nRemote queries require a native Steamworks client; --installed works offline.')
    browse.add_argument('--kind', choices=['map', 'mod'], help='filter by package kind (mapmod is a mod)')
    browse.add_argument('--search', default='', help='filter by title')
    browse.add_argument('--page', type=int, default=1, help='Workshop results page, starting at 1 (default: 1)')
    browse.add_argument('--installed', action='store_true', help='read installed Steam Workshop manifests without a native client')
    browse.add_argument('--app-id', help='Workshop consumer AppID (default: saved configuration or full game)')
    for command in ['install', 'play']:
        sub = command_parser(command, 'subscribe/download a Workshop item' if command == 'install' else 'download the Workshop map and dependencies, then play',
            f'Example:\n  skieomod --steam-client PATH {command} 1234567890\n\nRequires a native Steamworks client, which is not included.\nUse a Workshop article ID, as shown in its Steam URL (?id=...).')
        sub.add_argument('item_id', help='Steam PublishedFileId, not a package name or a release version')
        path_arguments(sub)
    setup = command_parser('setup', 'install Custom Map/UE4SS and the Veymont example, and remember Steam paths',
        'Examples:\n  skieomod setup\n  skieomod setup --game-dir "PATH TO GAME" --app-id 5012760\n\nOn Linux/Proton, start the game once in Steam, then close it before setup.\nGame/demo paths are detected from Steam; ambiguous installations prompt for a choice.\nVeymont is a Featured map: choose New Game > Custom Map > Veymont > Play to download it if missing or outdated.')
    path_arguments(setup)
    setup.add_argument('--workshop-app-id', help='Workshop consumer AppID when explicitly different from the game/demo')
    setup.add_argument('--no-editor-link', action='store_true', help='skip desktop Editor link registration (for headless installations)')
    uninstall = command_parser('uninstall-self', 'remove Custom Map and the skieomod command',
        '''Examples:
  skieomod uninstall-self --check
  skieomod uninstall-self
  skieomod uninstall-self --mod-only --game-dir "PATH TO GAME"
  skieomod uninstall-self --cli-only

Close the game and editor first. By default, removes both the Custom Map mod
and this CLI installation, using pipx or the current Python environment's pip.
The mod folder is moved to Mods/.skieomod-backups/uninstall-TIMESTAMP/.
Maps, source projects, CLI configuration and UE4SS remain available.
Legacy skieomod:// links to this CLI are unregistered when removing the CLI.
--check reports the planned removal without writing files or running uninstallers.''')
    uninstall.add_argument('--game-dir', type=Path, help='game directory (default: saved installation or Steam detection)')
    uninstall.add_argument('--ue4ss-mods', type=Path, help='remove Custom Map only from this UE4SS Mods directory')
    uninstall.add_argument('--app-id', choices=desktop.APP_IDS, help='Steam game/demo AppID when overriding the game directory')
    uninstall.add_argument('--check', action='store_true', help='show what would be removed without changing anything')
    uninstall_scope = uninstall.add_mutually_exclusive_group()
    uninstall_scope.add_argument('--mod-only', action='store_true', help='remove Custom Map and keep the CLI installed')
    uninstall_scope.add_argument('--cli-only', action='store_true', help='remove the CLI and keep Custom Map installed')
    update = command_parser('update', 'update the installed Custom Map loader before Workshop is available',
        '''Examples:
  skieomod update --check
  skieomod update
  skieomod update --archive CustomMap-Mod-1.5.0.zip
  skieomod update --bundled

Close the game before updating. Downloads the latest loader from
https://skieomod.emillon.fr/downloads/loader-latest.json and checks SHA-256.
--archive applies a downloaded, versioned loader release without updating the CLI.
--bundled applies the loader shipped with the installed CLI, without networking.
Configuration and local maps stay in place. Replaced files are backed up.
Included example maps are installed if missing; existing copies are preserved.
--check only reports versions and planned changes; it does not modify anything.''')
    update_source = update.add_mutually_exclusive_group()
    update_source.add_argument('--archive', type=Path, help='versioned CustomMap-Mod ZIP distributed for testing')
    update_source.add_argument('--bundled', action='store_true', help='apply the loader bundled with the installed CLI without accessing the VPS')
    update.add_argument('--check', action='store_true', help='report the installed/available versions and changes without writing files')
    update.add_argument('--game-dir', type=Path, help='game directory (default: saved installation)')
    update.add_argument('--ue4ss-mods', type=Path, help='UE4SS Mods directory (default: saved installation)')
    update.add_argument('--app-id', choices=desktop.APP_IDS, help='Steam game/demo AppID when overriding the game directory')
    update.add_argument('--no-editor-link', action='store_true', help='skip desktop Editor link registration (for headless installations)')
    config_parser = command_parser('config', 'show or configure saved game and Workshop paths',
        'Examples:\n  skieomod config\n  skieomod config --game-dir "PATH TO GAME"\n  skieomod --steam-client PATH config\n\nWithout options, reads the configuration without changing it.\nWindows: %APPDATA%/skieomod/config.json\nLinux: $XDG_CONFIG_HOME/skieomod/config.json or ~/.config/skieomod/config.json')
    path_arguments(config_parser)
    help_parser = command_parser('help', 'show general help or help for a command',
        'Examples:\n  skieomod help\n  skieomod help create\n  skieomod create map --help\n  skieomod help publish')
    help_parser.add_argument('topic', nargs='?', choices=commands.choices, help='command to explain (default: general help)')
    return parser, commands.choices


def main(argv=None):
    parser, command_parsers = create_parser()
    args = parser.parse_args(argv)
    if args.command is None or args.command == 'help':
        topic = getattr(args, 'topic', None)
        (command_parsers[topic] if topic else parser).print_help()
        return 0
    if args.command not in {'update', 'uninstall-self'}:
        updates.start_check()
        for message in updates.notices():
            print(message, file=sys.stderr)
    try:
        if args.command in {'editor', 'uri'}:
            if args.command == 'uri' and args.url not in {'skieomod://editor', 'skieomod://editor/'}:
                raise ManifestError('Invalid editor link; expected skieomod://editor')
            if __package__ == 'tools':
                from . import skieo_editor
            else:
                import skieo_editor
            return skieo_editor.launch(args.project if args.command == 'editor' else None)
        elif args.command in {'create', 'new'}:
            source = projects.create(args.kind, args.output, args.name, args.id, args.author,
                                     size_meters=args.size, spacing_meters=args.spacing)
            print(f'Created {args.kind} project: {source}\nDocumentation: {source.parent / "README.md"}\n'
                  f'Next: skieomod build "{source.parent}", then skieomod run "{source.parent}"')
        elif args.command in {'build', 'test', 'run'}:
            with tempfile.TemporaryDirectory(prefix='skieomod-build-') as temporary:
                if args.command == 'test':
                    archive = prepare(args.project, temporary)
                    kind, manifest, _ = inspect_package(archive)
                    release = {'id': manifest['id'], 'kind': kind, 'version': manifest['metadata']['version'], 'manifest': manifest}
                else:
                    archive, release = projects.build(args.project, getattr(args, 'output', None))
                print(f"Valid {release['kind']} {release['id']} {release['version']}: {archive}")
                if args.check_scripts:
                    check_scripts(archive)
                if getattr(args, 'check_dependencies', False) or args.command == 'run' or args.dependency:
                    config = desktop.configure(args) if args.command == 'run' else desktop.load_config()
                    installed, _ = workshop.installed(config, temporary)
                    installed.extend(installed_mapmods(config))
                    local_releases = {release['id']: release}
                    local_archives = {release['id']: archive}
                    for index, dependency in enumerate(args.dependency):
                        stage = Path(temporary) / ('dependency-' + str(index))
                        stage.mkdir()
                        path = prepare(dependency, stage)
                        kind, manifest, _ = inspect_package(path, 'mod')
                        if manifest['id'] in local_releases:
                            raise ManifestError('Duplicate local dependency: ' + manifest['id'])
                        local_releases[manifest['id']] = {'id': manifest['id'], 'kind': kind,
                            'version': manifest['metadata']['version'], 'manifest': manifest, 'archive': path,
                            'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
                        local_archives[manifest['id']] = path
                    root = release
                    if args.command == 'run' and release['kind'] == 'mod' and release['manifest'].get('runtime', 'map-api') == 'map-api':
                        preview, root = projects.preview_map(args.project, release)
                        local_archives[root['id']] = preview
                        local_releases[root['id']] = root
                        print(f"Testing mapmod in local preview map: {root['id']}")
                    candidates = [r for r in local_releases.values() if r['id'] != root['id']] + installed
                    if args.command == 'run':
                        closure = fetch_mapmod_dependencies(root, candidates, Path(temporary) / 'downloads')
                        for candidate in closure:
                            if candidate.get('archive') and not candidate.get('workshop_id'):
                                local_releases[candidate['id']] = candidate
                                local_archives[candidate['id']] = candidate['archive']
                    else:
                        closure = check_dependencies(root['manifest'], root['kind'], candidates)
                    if args.command == 'run':
                        config = desktop.setup(args, protocol=False)
                        args.maps_dir, args.ue4ss_mods = Path(config['maps_dir']), Path(config['ue4ss_mods'])
                        args.id, args.version = root['id'], root['version']
                        # Steam content remains managed by Steam. Local development
                        # installs only local builds; external mapmods load directly
                        # from their Workshop directories through the game adapter.
                        local_closure = [{k: v for k, v in local_releases[p['id']].items() if k != 'archive'}
                                         for p in closure if p['id'] in local_releases]
                        install(args, local_closure, local_archives)
                        if root['kind'] == 'map': desktop.request_play(config, root, editor_session=args.editor_session)
                        else: desktop.launch_game(config)
        elif args.command == 'pack':
            source_manifest = json.loads(args.manifest.read_text(encoding='utf-8'))
            if any(key in source_manifest.get('build', {}) for key in ('heightmap', 'forest', 'vegetation', 'triggers', 'resources', 'objects', 'scene')):
                projects.build(args.manifest, args.output)
                kind, manifest, size = inspect_package(args.output)
            else:
                kind, manifest, size = pack_package(args.manifest, args.output)
            print(f"Packed {kind} {manifest['id']} ({size} bytes unpacked): {args.output}")
        elif args.command == 'publish':
            if not args.prepare and not args.steam:
                if any((args.app_id, args.item_id, args.preview, args.visibility, args.changenote, args.steam_client)):
                    raise ManifestError('Steam options require --steam or --prepare')
                with tempfile.TemporaryDirectory(prefix='skieomod-publish-') as temporary:
                    archive = prepare(args.project, temporary)
                    if args.check_scripts: check_scripts(archive)
                    result = web_repository.publish(archive, args.repository)
                print('Published ' + result['id'] + ' ' + result['version'] + '; find it in New Game > Custom Map > Web')
                return 0
            source = projects.project_manifest(args.project)
            archive, _ = projects.build(source)
            if args.check_scripts: check_scripts(archive)
            output, payload = workshop.prepare(archive, source.parent, app=args.app_id, published_id=args.item_id,
                preview=args.preview, visibility=args.visibility, changenote=args.changenote)
            print('Prepared Steam Workshop content: ' + str(output))
            if not args.prepare:
                result = workshop.publish(payload, source.parent, args.steam_client)
                identifier = result['published_file_id']
                print('https://steamcommunity.com/sharedfiles/filedetails/?id=' + identifier)
                if result.get('needs_legal_agreement'):
                    print('Accept the Steam Workshop legal agreement to make the item available.')
        elif args.command == 'list':
            config = desktop.load_config()
            app = args.app_id or config.get('workshop_app_id') or config.get('app_id') or workshop.APP_ID
            if args.page < 1: raise ManifestError('Workshop pages start at 1')
            if args.installed:
                if args.app_id: config['workshop_app_id'] = workshop.app_id(args.app_id)
                with tempfile.TemporaryDirectory(prefix='skieomod-installed-') as temporary:
                    items, _ = workshop.installed(config, temporary)
                    for item in items:
                        metadata = item['manifest']['metadata']
                        if (not args.kind or item['kind'] == args.kind) and args.search.lower() in metadata['name'].lower():
                            print(f"{item['kind']:3}  {item['workshop_id']}  {metadata['name']}  [installed; package {item['version']}]")
            else:
                result = workshop.call(workshop.request('query', app, kind=args.kind, search=args.search, page=args.page), args.steam_client, config)
                for item in result.get('items', []):
                    print(f"{item.get('kind', '?'):3}  {workshop.item_id(item['published_file_id'])}  {item['title']}")
        elif args.command in {'install', 'play'}:
            config = desktop.configure(args)
            app = config.get('workshop_app_id') or config.get('app_id') or workshop.APP_ID
            result = workshop.call(workshop.request(args.command, app, published_file_id=workshop.item_id(args.item_id), include_required_items=True), args.steam_client, config)
            print(result.get('message', 'Steam Workshop operation completed'))
        elif args.command == 'setup':
            desktop.setup(args, protocol=not args.no_editor_link)
        elif args.command == 'update':
            desktop.update_loader(args)
        elif args.command == 'uninstall-self':
            if __package__ == 'tools':
                from . import skieo_uninstall
            else:
                import skieo_uninstall
            skieo_uninstall.uninstall(args)
        elif args.command == 'config':
            config = desktop.configure(args) if any([args.game_dir, args.maps_dir, args.ue4ss_mods, args.app_id]) else desktop.load_config()
            if args.steam_client:
                config['workshop_client'] = str(args.steam_client.expanduser().resolve())
                desktop.save_config(config)
            print(json.dumps(config, ensure_ascii=False, indent=2))
    except (ManifestError, OSError, ValueError, KeyError, URLError, subprocess.SubprocessError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
