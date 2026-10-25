#!/usr/bin/env python3
"""Build the public Custom Map tools and game mod distribution archives."""
from pathlib import Path
import sys
import subprocess
import re
import argparse
import tempfile
import zipfile
import json
import shutil
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.custom_maps import write_zip_member
from tools.skieo_loader import featured_files, managed_path, manifest as loader_manifest, update_feed, read_archive, NAME as LOADER_NAME, RECORD as LOADER_RECORD
from tools.skieo_install import UE4SS_ARCHIVE, read_ue4ss_archive

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--loader-ref', help='package the game loader from this Git revision, preserving uncommitted game work')
parser.add_argument('--loader-archive', type=Path, help='reuse verified loader code from an existing release instead of working-tree game changes')
parser.add_argument('--loader-overlay', type=Path, help='apply explicitly selected managed loader files over the verified archive')
parser.add_argument('--tools-only', action='store_true', help='build only loader/CLI artifacts; keep the existing featured catalogue on the server')
parser.add_argument('--no-build-isolation', action='store_true', help='use already installed setuptools/wheel to build without downloading build dependencies')
parser.add_argument('--output-dir', type=Path, default=ROOT / 'build/custom-map-downloads', help='directory for release artifacts')
parser.add_argument('--ue4ss-archive', type=Path, help='local copy of the tested UE4SS ZIP; defaults to the versioned archive in the output directory')
args = parser.parse_args()
if args.loader_archive and args.loader_ref:
    parser.error('--loader-archive and --loader-ref are mutually exclusive')
if args.loader_overlay and not args.loader_archive:
    parser.error('--loader-overlay requires --loader-archive')
OUTPUT = args.output_dir.resolve()
ue4ss_archive = OUTPUT / UE4SS_ARCHIVE
ue4ss_source = args.ue4ss_archive or ue4ss_archive
if not ue4ss_source.is_file():
    parser.error('Retain the tested UE4SS build and pass --ue4ss-archive PATH: ' + UE4SS_ARCHIVE)
ue4ss_data = read_ue4ss_archive(ue4ss_source)
if ue4ss_archive.exists() and ue4ss_archive.read_bytes() != ue4ss_data:
    parser.error('Refusing to replace a different versioned UE4SS archive: ' + str(ue4ss_archive))
OUTPUT.mkdir(parents=True, exist_ok=True)
if not ue4ss_archive.exists():
    ue4ss_archive.write_bytes(ue4ss_data)
MODULES = ('custom_map.py', 'custom_maps.py', 'custom_packages.py', 'skieo_http.py', 'skieo_install.py', 'skieo_uninstall.py', 'skieo_loader.py', 'skieo_updates.py',
           'skieo_project.py', 'skieo_templates.py', 'skieo_workshop.py', 'skieo_repository.py', 'skieo_heightmap.py', 'skieo_bake.py', 'skieo_authoring.py', 'skieo_game_catalog.py', 'skieo_scene.py', 'skieo_editor_scene.py', 'skieo_editor.py', 'skieo_editor_ui.py',
           'skieo_editor_widgets.py', 'skieo_editor_config.py', 'skieo_editor_3d.py', 'skieo_editor_graph.py', 'skieo_editor_resources.py')
PACKAGE_FILES = ('LICENSE', 'THIRD_PARTY_NOTICES.md', 'pyproject.toml', 'MANIFEST.in', 'CHANGELOG.md', 'docs/discord-releases.md', 'docs/getting-started.md', 'docs/large-maps.md', 'docs/terrain-repairs.md', 'docs/vegetation.md', 'docs/editor.md', 'docs/editor-tutorial.md', 'docs/custom-map-cli.md',
                 'docs/custom-map-repository.md', 'docs/custom-map-format.md', 'docs/steam-workshop.md', 'docs/scripts-and-scenarios.md', 'docs/mapmods.md', 'docs/surface-lifts.md', 'docs/surface-lifts-tutorial.md', 'docs/mapmod-tutorial.md',
                 'native/SkiEORepository/LICENSE', 'tools/build_custom_map_release.py',
                 'tests/check_skieomod_distribution.py', 'deployment/publish_loader_updates.py', 'deployment/release_custom_map.py', 'deployment/discord_releases.py',
                 'tools/repair_heightmap.py', 'maps/veymont/map.json')
version = re.search(r'(?m)^version = "([^"]+)"$', (ROOT / 'pyproject.toml').read_text())[1]
loader_files = {}
if args.loader_ref:
    names = subprocess.check_output(['git', 'ls-tree', '-r', '--name-only', args.loader_ref, 'mod/SkiEO-CustomMaps'], cwd=ROOT, text=True).splitlines()
    for name in names:
        loader_files[name] = subprocess.check_output(['git', 'show', args.loader_ref + ':' + name], cwd=ROOT)
else:
    for path in sorted((ROOT / 'mod/SkiEO-CustomMaps').rglob('*')):
        if path.is_file() and path.name != 'workshop.json' and path.suffix not in {'.status', '.job', '.part', '.response'} and '.skieomod-backups' not in path.parts and not path.name.startswith(('native_entity_snow.', 'repository-', 'launch-request', 'launch-result', 'skieomod-installed', 'network.', 'inflate.')):
            loader_files[str(path.relative_to(ROOT))] = path.read_bytes()
# A loader update contains only managed code/docs, never local settings or state.
release_files = {'LICENSE': (ROOT / 'LICENSE').read_bytes(),
                 'LICENSE-miniz.txt': (ROOT / 'native/SkiEORepository/LICENSE').read_bytes(),
                 'getting-started.md': (ROOT / 'docs/getting-started.md').read_bytes()}
for name, data in loader_files.items():
    relative = name.removeprefix('mod/' + LOADER_NAME + '/')
    if relative.startswith('Examples/'):
        continue
    try:
        managed_path(relative)
    except ValueError:
        continue
    release_files[relative] = data
featured_sources = [ROOT / 'mod/SkiEO-Veymont', ROOT / 'mod/SkiEO-SuperSaintBernard',
                    ROOT / 'mod/SkiEO-Foxes', ROOT / 'mod/SkiEO-SurfaceLifts']
featured = {} if args.tools_only else featured_files(featured_sources)
if args.loader_archive:
    release_files, _ = read_archive(args.loader_archive)
    release_files = {name: data for name, data in release_files.items() if not name.startswith('Examples/')}
    release_files['getting-started.md'] = (ROOT / 'docs/getting-started.md').read_bytes()
    if args.loader_overlay:
        overlay = args.loader_overlay.resolve(strict=True)
        for path in sorted(overlay.rglob('*')):
            if path.is_file():
                if path.is_symlink() or not path.resolve().is_relative_to(overlay):
                    parser.error('Loader overlay must not traverse symlinks')
                relative = path.relative_to(overlay).as_posix()
                managed_path(relative)
                if not relative.startswith('Scripts/'):
                    parser.error('Loader overlays are restricted to explicitly selected script files')
                release_files[relative] = path.read_bytes()
release_record = loader_manifest(release_files, version)
loader_files = {'mod/' + LOADER_NAME + '/' + name: data for name, data in release_files.items()}
with tempfile.TemporaryDirectory(prefix='custom-map-wheel-') as directory:
    stage = Path(directory)
    (stage / 'README.md').write_bytes((ROOT / 'docs/getting-started.md').read_bytes())
    for relative in PACKAGE_FILES:
        target = stage / relative; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes((ROOT / relative).read_bytes())
    for path in sorted((ROOT / 'schemas').glob('*.json')):
        target = stage / 'schemas' / path.name; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(path.read_bytes())
    for name in MODULES:
        target = stage / 'tools' / name; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes((ROOT / 'tools' / name).read_bytes())
    for name, data in loader_files.items():
        target = stage / name; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(data)
    wheel_command = [sys.executable, '-m', 'pip', '--disable-pip-version-check', '--no-cache-dir',
                     'wheel', '--no-deps', '--wheel-dir', str(OUTPUT)]
    if args.no_build_isolation:
        wheel_command.extend(['--no-build-isolation', '--no-index'])
    subprocess.run([*wheel_command, str(stage)], check=True)
with zipfile.ZipFile(OUTPUT / 'CustomMap-Tools.zip', 'w') as archive:
    write_zip_member(archive, 'README.md', (ROOT / 'docs/getting-started.md').read_bytes())
    write_zip_member(archive, 'build/custom-map-downloads/' + UE4SS_ARCHIVE, ue4ss_data)
    paths = [ROOT / 'tools' / name for name in MODULES]
    paths += list((ROOT / 'schemas').glob('*.json'))
    paths += [ROOT / relative for relative in PACKAGE_FILES]
    for path in sorted(paths):
        if path.is_file() and '__pycache__' not in path.parts:
            write_zip_member(archive, str(path.relative_to(ROOT)), path.read_bytes())
    # The tools ZIP is also a complete, installable source distribution.
    # pyproject.toml references these loader assets when building its wheel.
    for name, data in sorted(loader_files.items()):
        write_zip_member(archive, name, data)
    wheels = sorted(OUTPUT.glob('skieo_custom_map-' + version + '-*.whl'))
    for wheel in wheels:
        write_zip_member(archive, wheel.name, wheel.read_bytes())
artifacts = [*wheels, OUTPUT / 'CustomMap-Tools.zip', ue4ss_archive]
loader_archive = OUTPUT / ('CustomMap-Mod-' + version + '.zip')
with zipfile.ZipFile(loader_archive, 'w') as archive:
    write_zip_member(archive, LOADER_NAME + '/' + LOADER_RECORD,
                     (json.dumps(release_record, indent=2) + '\n').encode('utf-8'))
    for name, data in sorted(release_files.items()):
        write_zip_member(archive, LOADER_NAME + '/' + name, data)
shutil.copyfile(loader_archive, OUTPUT / 'CustomMap-Mod.zip')
artifacts.extend([loader_archive, OUTPUT / 'CustomMap-Mod.zip'])
feed = OUTPUT / 'loader-latest.json'
feed.write_text(json.dumps(update_feed(loader_archive, release_record), indent=2) + '\n', encoding='utf-8')
artifacts.append(feed)
guide = OUTPUT / ('Getting-Started-' + version + '.md')
guide.write_bytes((ROOT / 'docs/getting-started.md').read_bytes())
shutil.copyfile(guide, OUTPUT / 'getting-started.md')
artifacts.extend([guide, OUTPUT / 'getting-started.md'])
changelog = OUTPUT / ('Changelog-' + version + '.md')
changelog.write_bytes((ROOT / 'CHANGELOG.md').read_bytes())
artifacts.append(changelog)
for name, data in featured.items():
    target = OUTPUT / name
    target.write_bytes(data)
    artifacts.append(target)
for path in artifacts: print(f'{path.name}: {path.stat().st_size} bytes')
