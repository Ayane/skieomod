#!/usr/bin/env python3
"""Smoke-test a released wheel in an isolated environment without repository imports.

Usage: python3 tests/check_skieomod_distribution.py path/to/skieo_custom_map-*.whl
Requires pip in the current Python installation; installs only the supplied wheel.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import subprocess
import struct
import sys
import tempfile
import venv
import zipfile
import zlib


def check(wheel, loader_archive=None, online=False):
    with tempfile.TemporaryDirectory(prefix='skieomod-distribution-') as temporary:
        root = Path(temporary)
        environment = root / 'venv'
        venv.EnvBuilder(with_pip=False).create(environment)
        scripts = environment / ('Scripts' if os.name == 'nt' else 'bin')
        python = scripts / ('python.exe' if os.name == 'nt' else 'python')
        command = scripts / ('skieomod.exe' if os.name == 'nt' else 'skieomod')
        env = {key: value for key, value in os.environ.items() if key not in {'PYTHONPATH', 'PYTHONHOME'}}
        env['SKIEOMOD_CONFIG_DIR'] = str(root / 'unused-config')
        # Protocol registration from setup/update must stay in this sandbox.
        env['XDG_DATA_HOME'] = str(root / 'desktop-data')
        env['XDG_CONFIG_HOME'] = str(root / 'desktop-config')
        subprocess.run([sys.executable, '-m', 'pip', '--disable-pip-version-check', '--no-cache-dir',
            '--python', str(python), 'install', '--no-index', '--no-deps', str(wheel)],
            cwd=root, env=env, check=True)

        def run(*arguments):
            # Windows protocol registration uses HKCU, outside the temporary
            # environment. The registry adapter has its own unit tests.
            if os.name == 'nt' and arguments[0] in {'setup', 'update'}:
                arguments = (*arguments, '--no-editor-link')
            return subprocess.check_output([str(command), *map(str, arguments)],
                cwd=root, env=env, text=True, encoding='utf-8')

        version = run('--version').strip().split()[-1]
        assert version in wheel.name, 'CLI version differs from wheel version'
        assert run() == run('help') == run('--help')
        for topic in ('editor', 'uri', 'create', 'new', 'build', 'test', 'run', 'publish', 'pack', 'list',
                      'install', 'play', 'setup', 'update', 'uninstall-self', 'config', 'help'):
            assert run('help', topic) == run(topic, '--help'), topic
        assert not (root / 'unused-config').exists(), 'help created a configuration'

        # Resolve the loader from the installed wheel, with no source checkout nearby.
        data = json.loads(subprocess.check_output([str(python), '-c',
            'import json, sysconfig; from skieo_install import bundled_loader; '
            'print(json.dumps({"loader": str(bundled_loader()), "data": sysconfig.get_path("data")}))'],
            cwd=root, env=env, text=True))
        loader = Path(data['loader'])
        share = Path(data['data']) / 'share/skieomod'
        assert loader == share / 'SkiEO-CustomMaps'
        for filename in ('main.lua', 'api.lua', 'compatibility.lua', 'compatibility_contracts.lua', 'trail_ratings.lua', 'object_edits.lua', 'object_catalog.lua', 'scene_objects.lua', 'native_terrain.lua', 'loading_view.lua', 'ui_assets.lua', 'ui_logo.lua', 'skieo_repository.dll', 'skieo_native_terrain.dll', 'skieo_trail_ratings.dll'):
            assert (loader / 'Scripts' / filename).is_file(), filename
        assert (loader / 'LICENSE').is_file()
        assert (loader / 'LICENSE-MINHOOK.md').is_file()
        for filename in ('CHANGELOG.md', 'discord-releases.md', 'getting-started.md', 'large-maps.md', 'terrain-repairs.md', 'vegetation.md', 'custom-map-cli.md', 'custom-map-format.md', 'steam-workshop.md', 'editor.md', 'editor-tutorial.md', 'scripts-and-scenarios.md', 'mapmods.md', 'mapmod-tutorial.md'):
            assert (share / 'docs' / filename).is_file(), filename
        assert not (share / 'examples').exists(), 'wheel bundles example maps'
        assert not list(loader.rglob('*.skieomap')), 'loader bundles map payloads'
        assert (loader / 'Scripts/featured.lua').is_file()
        assert (loader / 'getting-started.md').is_file()
        assert subprocess.check_output([str(python), '-c',
            'from importlib.metadata import metadata; print(metadata("skieo-custom-map")["Author"])'],
            cwd=root, env=env, text=True).strip() == 'Albatar (Élie Millon)'
        for filename in ('custom-map.schema.json', 'custom-mod.schema.json', 'workshop-client.schema.json', 'vegetation.schema.json', 'triggers.schema.json', 'resources.schema.json', 'scene.schema.json'):
            assert (share / 'schemas' / filename).is_file(), filename

        for kind in ('map', 'mod', 'mapmod'):
            project = root / ('project ' + kind)
            run('create', kind, '--output', project, '--name', 'My station', '--author', 'Author')
            assert (project / 'docs/scripting.md').is_file()
            assert (project / 'docs/terrain.md').exists() == (kind == 'map')
            if kind == 'map':
                assert (project / 'docs/vegetation.md').is_file()
                trees = b'[{"x":10.5,"y":-20},{"x":0,"y":0}]\n'
                (project / 'Vegetation/forest.json').write_bytes(trees)
            run('build', project)
            archive = next((project / 'bin').glob('*'))
            before = archive.read_bytes()
            run('build', project)
            assert archive.read_bytes() == before, 'build is not reproducible'
            run('test', project)
            run('test', archive)
            run('publish', project, '--prepare')
            request = json.loads((project / 'bin/workshop/publish-request.json').read_text())
            assert request['visibility'] == 'private'
            assert (project / 'bin/workshop/content/Scripts' / ('skieomod-generated-vegetation.lua' if kind == 'map' else 'main.lua')).is_file()
            with zipfile.ZipFile(archive) as package:
                assert not any(name.startswith('docs/') for name in package.namelist())
                if kind == 'map':
                    assert package.read('Vegetation/Generated/forest.skxy') == struct.pack('<4sIIffff', b'SKXY', 1, 2, 1050, -2000, 0, 0)
                    assert 'Vegetation/forest.json' not in package.namelist()
                    assert b'api:load_forest_skxy' in package.read('Scripts/skieomod-generated-vegetation.lua')
                    assert 'build' not in json.loads(package.read('custom-map.json'))
        run('new', 'mapmod', '--output', root / 'legacy-alias')
        # A creator can test their own raw heightmap with only a file and spacing.
        minimal = root / 'minimal-raw'
        run('create', 'map', '--output', minimal)
        raw = struct.pack('<9H', *range(1000, 10000, 1000))
        (minimal / 'Terrain/source.r16').write_bytes(raw)
        source = minimal / 'custom-map.json'
        metadata = json.loads(source.read_text())
        metadata['build'] = {'heightmap': {'file': 'Terrain/source.r16', 'spacing_meters': 8}}
        source.write_text(json.dumps(metadata))
        output = run('build', minimal)
        assert 'assumed square' in output and 'Real altitudes are unknown' in output
        calculated = json.loads(source.read_text())
        assert calculated['terrain']['source']['vertices'] == [3, 3]
        assert calculated['terrain']['elevation_meters'] == [0, 1000]
        assert 'vertices' not in calculated['build']['heightmap']
        assert (minimal / 'Terrain/heightmap.r16').read_bytes() == raw
        run('test', minimal)
        run('test', next((minimal / 'bin').glob('*.skieomap')))
        native = json.loads(subprocess.check_output([str(python), '-c',
            'import importlib.util, json, sys; from skieo_editor import EditorProject; '
            'd = EditorProject(sys.argv[1]); '
            'print(json.dumps({"size": [d.width, d.height], "elevation": d.elevation, '
            '"ui": importlib.util.find_spec("skieo_editor_ui") is not None}))', str(minimal)],
            cwd=root, env=env, text=True))
        assert native == {'size': [3, 3], 'elevation': [0, 1000], 'ui': True}
        # Compile authoring sources with the installed headless build. Qt is
        # intentionally absent in this isolated environment.
        subprocess.run([str(python), '-c',
            'from pathlib import Path; import sys; from skieo_editor import EditorProject; '
            'from skieo_authoring import new_trigger, OBJECTS; '
            'p=Path(sys.argv[1]); obj=p/"office.obj"; '
            'obj.write_text("v 0 0 0\\nv 2 0 0\\nv 0 2 1\\nf 1 2 3\\n"); '
            'd=EditorProject(p); d.import_resource(obj,"office","model"); '
            'd.queue_authoring("triggers",{"version":1,"triggers":[new_trigger()]}); '
            'd.queue_authoring("objects",[{"object":OBJECTS[0]["class"],"field":"MeshComponent.StaticMesh","type":"model","value":"asset:office"}]); '
            'd.save()', str(minimal)], cwd=root, env=env, check=True)
        run('build', minimal); run('test', minimal)
        with zipfile.ZipFile(next((minimal / 'bin').glob('*.skieomap'))) as archive:
            built=json.loads(archive.read('custom-map.json'))
            assert built['script']['entry']=='Scripts/skieomod-generated-authoring.lua'
            assert b'apply_object_edits' in archive.read(built['script']['entry'])
            assert 'Objects/overrides.csv' not in archive.namelist()
        # Exercise PNG conversion through the installed command, independently
        # of checkout imports and optional image libraries.
        heightmap_project = root / 'png-map'
        run('create', 'map', '--output', heightmap_project)
        def chunk(tag, payload):
            return struct.pack('>I', len(payload)) + tag + payload + struct.pack('>I', zlib.crc32(tag + payload))
        values = [0, 10000, 20000, 30000, 40000, 50000, 60000, 65000, 65535]
        image = (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 3, 3, 16, 0, 0, 0, 0))
                 + chunk(b'IDAT', zlib.compress(b''.join(b'\0' + struct.pack('>3H', *values[y:y+3]) for y in (0, 3, 6))))
                 + chunk(b'IEND', b''))
        (heightmap_project / 'Terrain/source.png').write_bytes(image)
        source = heightmap_project / 'custom-map.json'
        metadata = json.loads(source.read_text())
        metadata['build'] = {'heightmap': {'file': 'Terrain/source.png', 'spacing_meters': 8, 'elevation_meters': [800, 2200]}}
        source.write_text(json.dumps(metadata))
        before = source.read_bytes()
        run('test', heightmap_project)
        assert source.read_bytes() == before, 'test changed heightmap source metadata'
        run('build', heightmap_project)
        calculated = json.loads(source.read_text())['terrain']
        assert calculated['source']['vertices'] == [3, 3]
        assert calculated['size_meters'] == [16, 16]
        assert calculated['elevation_meters'] == [800, 2200]
        converted = struct.pack('<9H', *values)
        assert (heightmap_project / 'Terrain/heightmap.r16').read_bytes() == converted
        package = next((heightmap_project / 'bin').glob('*.skieomap'))
        with zipfile.ZipFile(package) as archive:
            assert archive.read('Terrain/heightmap.r16') == converted
            assert 'build' not in json.loads(archive.read('custom-map.json'))
            assert 'Terrain/source.png' not in archive.namelist()
        saved_package = package.read_bytes()
        run('build', heightmap_project)
        assert package.read_bytes() == saved_package, 'PNG build is not reproducible'
        metadata = json.loads(source.read_text())
        metadata['build']['heightmap']['processing'] = {'thermal_erosion': {'iterations': 2, 'talus_degrees': 20, 'max_delta_meters': 1}}
        metadata['build']['vegetation'] = {'biome': {'tree_line_meters': 2200, 'alpine_line_meters': 2600},
            'trees': {'seed': 42, 'density_per_hectare': 2000}, 'ground_cover': {'texture_size': 16}}
        source.write_text(json.dumps(metadata))
        run('build', heightmap_project)
        run('test', heightmap_project)
        with zipfile.ZipFile(package) as archive:
            built = json.loads(archive.read('custom-map.json'))
            assert built['script']['entry'].endswith('skieomod-generated-vegetation.lua')
            assert len(built['terrain']['textures']['albedo']['mips']) == 4
            trees = archive.read('Vegetation/Generated/forest.skxy')
            assert trees[:4] == b'SKXY'
            assert 'Vegetation/forest.json' not in archive.namelist()
            assert 'load_forest_json' not in archive.read(built['script']['entry']).decode()
            assert 'processing' in json.loads(archive.read('Terrain/Generated/build-report.json'))
        previous = package.read_bytes()
        run('build', heightmap_project)
        assert package.read_bytes() == previous, 'processed vegetation build is not reproducible'
        for filename in ('api.lua', 'runtime.lua', 'vegetation.lua'):
            assert 'load_forest_json' not in (loader / 'Scripts' / filename).read_text()
        assert 'function Vegetation.load_json' not in (loader / 'Scripts/vegetation.lua').read_text()
        large = root / 'large-map'
        run('create', 'map', '--output', large, '--size', '16000', '12000', '--spacing', '8')
        run('build', large)
        run('test', large)
        terrain = json.loads((large / 'custom-map.json').read_text())['terrain']
        assert terrain['source']['vertices'] == [2001, 1501]
        assert (large / 'Terrain/heightmap.r16').stat().st_size == 2001 * 1501 * 2
        assert (root / 'legacy-alias/README.md').is_file()
        assert not (root / 'unused-config').exists(), 'offline commands created a configuration'
        # Simulate a legacy installation without touching the real game or UE4SS.
        mods = root / 'game-mods'
        destination = mods / 'SkiEO-CustomMaps'
        (destination / 'Scripts').mkdir(parents=True)
        (destination / 'Scripts/main.lua').write_text('-- previous loader')
        (destination / 'Scripts/workshop.json').write_text('{"custom":"preserved"}')
        config = root / 'unused-config/config.json'
        config.parent.mkdir()
        config.write_text(json.dumps({'version': 1, 'ue4ss_mods': str(mods)}))
        before = (destination / 'Scripts/main.lua').read_bytes()
        run('update', '--bundled', '--check')
        assert (destination / 'Scripts/main.lua').read_bytes() == before
        assert not (destination / '.skieomod-backups').exists()
        run('update', '--bundled')
        assert (destination / 'Scripts/main.lua').read_bytes() == (loader / 'Scripts/main.lua').read_bytes()
        assert (destination / 'Scripts/workshop.json').read_text() == '{"custom":"preserved"}'
        assert json.loads((destination / 'loader-release.json').read_text())['release'] == version
        assert next((destination / '.skieomod-backups').rglob('main.lua')).read_bytes() == before
        if loader_archive:
            run('update', '--archive', loader_archive, '--check')
            run('update', '--archive', loader_archive)
            assert (destination / 'Scripts/workshop.json').read_text() == '{"custom":"preserved"}'
        if online:
            state = (destination / 'loader-release.json').read_bytes()
            run('update', '--check')
            assert (destination / 'loader-release.json').read_bytes() == state
            run('update')
            assert (destination / 'Scripts/workshop.json').read_text() == '{"custom":"preserved"}'
            print('OK: public VPS update; installed loader ' + json.loads((destination / 'loader-release.json').read_text())['release'])
        # Exercise the real installed setup command with a fake game and an
        # existing UE4SS, so it cannot download or touch the tester's real game.
        game = root / 'fake-game'
        binary = game / 'SkiResortSimulator/Binaries/Win64'
        (binary / 'ue4ss').mkdir(parents=True)
        (game / 'SkiResortSimulator/Content/Paks').mkdir(parents=True)
        (binary / 'dwmapi.dll').write_bytes(b'fake existing proxy')
        (binary / 'ue4ss/UE4SS.dll').write_bytes(b'fake existing UE4SS')
        run('setup', '--game-dir', game, '--app-id', '5012760')
        maps = game / 'SkiResortSimulator/Content/Paks/~mods'
        assert not list(maps.glob('*.skieomap')), 'setup installed a map before Play'
        installed = binary / 'ue4ss/Mods/SkiEO-CustomMaps'
        state = (installed / 'loader-release.json').read_bytes()
        assert not list(installed.rglob('*.skieomap')), 'loader installation bundles maps'
        if loader_archive:
            with zipfile.ZipFile(loader_archive) as archive:
                assert not any(name.endswith('.skieomap') for name in archive.namelist())
        run('update', '--bundled', '--check')
        assert (installed / 'loader-release.json').read_bytes() == state
        sample = maps / 'community.veymont-0.6.1.skieomap'
        sample.write_bytes(b'local map to preserve')
        saved_sample = sample.read_bytes()
        run('setup', '--game-dir', game, '--app-id', '5012760')
        assert sample.read_bytes() == saved_sample, 'setup overwrote a modified sample'
        run('uninstall-self', '--mod-only', '--check')
        assert installed.is_dir(), 'uninstall preview removed the loader'
        run('uninstall-self', '--mod-only')
        assert not installed.exists(), 'uninstall kept the active loader'
        backup = next((installed.parent / '.skieomod-backups').glob('uninstall-*/SkiEO-CustomMaps'))
        assert (backup / 'Scripts/main.lua').is_file(), 'uninstall did not back up the loader'
        assert sample.read_bytes() == saved_sample, 'uninstall removed a map'
        assert (binary / 'ue4ss/UE4SS.dll').is_file(), 'uninstall removed shared UE4SS'
        assert run('--version').strip() == 'skieomod ' + version, 'mod-only uninstall removed the CLI'
        run('uninstall-self', '--mod-only')
        print(f'OK: skieomod {version}; isolated install, help, all templates, builds, Workshop preparation, loader updates, map-free setup and uninstall-self')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('wheel', type=Path)
    parser.add_argument('--loader-archive', type=Path, help='also verify offline updates from the versioned loader ZIP')
    parser.add_argument('--online', action='store_true', help='also verify update --check and update against the public VPS')
    args = parser.parse_args()
    check(args.wheel.resolve(), args.loader_archive.resolve() if args.loader_archive else None, args.online)
