#!/usr/bin/env python3
"""Rebuild the mapmod tutorial's source downloads, without installing anything."""
from pathlib import Path
import contextlib
import io
import json
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import skieo_project as projects
from tools.custom_map import check_dependencies
from tools.custom_maps import write_zip_member

FILES = ROOT / 'repository/web/public/tutorials/mapmods/files'


def write_sources(target, sources):
    with zipfile.ZipFile(target, 'w') as archive:
        for name, data in sorted(sources.items()):
            write_zip_member(archive, name, data)


def build():
    with tempfile.TemporaryDirectory(prefix='mapmod-tutorial-') as temporary:
        root = Path(temporary)
        mod, mountain = root / 'mountain-life', root / 'practice-mountain'
        with contextlib.redirect_stdout(io.StringIO()):
            projects.create('mapmod', mod, 'Mountain life', 'tutorial.mountain-life', 'Albatar (Élie Millon)')
            projects.create('map', mountain, 'Practice mountain', 'tutorial.practice-mountain', 'Albatar (Élie Millon)')
        for path in sorted((FILES / 'mountain-life').rglob('*')):
            if path.is_file():
                target = mod / path.relative_to(FILES / 'mountain-life')
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(path.read_bytes())
        source = mountain / 'custom-map.json'
        manifest = json.loads(source.read_text())
        manifest['dependencies'] = [{'id': 'tutorial.mountain-life', 'version': '=0.1.0'}]
        manifest['extensions'] = {'tutorial.mountain-life': {'enabled': True, 'label': 'Practice mountain'}}
        source.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
        # Check that this exact download builds as two separately resolved packages.
        with contextlib.redirect_stdout(io.StringIO()):
            _, mod_release = projects.build(mod)
            _, map_release = projects.build(mountain)
        check_dependencies(map_release['manifest'], 'map', [mod_release])
        sources = {}
        for project in (mod, mountain):
            for path in sorted(project.rglob('*')):
                relative = path.relative_to(project)
                if path.is_file() and relative.parts[0] not in {'bin', 'obj'}:
                    sources[project.name + '/' + relative.as_posix()] = path.read_bytes()
        sources['README.md'] = b'''# Your first mapmod\n\nTwo source projects: mountain-life (the mod) and practice-mountain (the map).\nFrom this folder:\n\n```sh\nskieomod build mountain-life --check-scripts\nskieomod build practice-mountain --dependency mountain-life --check-scripts\nskieomod run practice-mountain --dependency mountain-life\n```\n\nRead mapmod-tutorial.md for the complete tutorial. The example logs field\nreports; it does not spawn animals. Lua 5.4 / luac is needed for syntax checks.\n'''
        sources['mapmod-tutorial.md'] = (ROOT / 'docs/mapmod-tutorial.md').read_bytes()
        for name in ('mapmods.md', 'steam-workshop.md'):
            sources[name] = (ROOT / 'docs' / name).read_bytes()
        write_sources(FILES / 'first-mapmod-project.zip', sources)

    fox = ROOT / 'mod/SkiEO-Foxes'
    manifest = json.loads((fox / 'custom-mod.json').read_text())
    # Keep the original anatomy archive external; redistribute the credited derivatives.
    sources = {'foxes/' + name: (fox / name).read_bytes()
               for name in ['custom-mod.json', *manifest['files'], 'LICENSE', 'Assets/fox-rig.json']}
    sources['foxes/tools/prepare_fox.py'] = (ROOT / 'tools/prepare_fox.py').read_bytes()
    sources['foxes/docs/mapmods.md'] = (ROOT / 'docs/mapmods.md').read_bytes()
    sources['foxes/docs/mapmod-tutorial.md'] = (ROOT / 'docs/mapmod-tutorial.md').read_bytes()
    sources['foxes/docs/steam-workshop.md'] = (ROOT / 'docs/steam-workshop.md').read_bytes()
    sources['foxes/README.md'] = b'''# Forest foxes source project\n\nRead docs/mapmod-tutorial.md and docs/mapmods.md. From the foxes folder:\n\n```sh\nskieomod build . --check-scripts\nskieomod run .\n```\n\nrun creates a local preview map; F7 cycles through its foxes.\nTo rebuild the animated asset from the original Fox Anatomy Collada ZIP:\n\n```sh\npython3 -m pip install numpy Pillow\npython3 tools/prepare_fox.py /path/to/fox-anatomy.zip --output Assets\n```\n\nThe original anatomy ZIP is not supplied. Keep CREDITS.txt and LICENSE with\nredistributed derivatives: code is MIT; the model and textures are CC BY 4.0.\n'''
    target = FILES / ('foxes-' + manifest['metadata']['version'] + '-project.zip')
    write_sources(target, sources)
    print('Built and validated ' + str(FILES / 'first-mapmod-project.zip'))
    print('Built ' + str(target))


if __name__ == '__main__':
    build()
