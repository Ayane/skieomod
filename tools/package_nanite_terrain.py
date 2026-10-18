#!/usr/bin/env python3
"""Package game-validated Nanite terrain sections as an optional derived cache."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import shutil
import zlib

from tools.build_nanite_rock import validate_mesh


def package(reports: list[Path], output: Path) -> dict:
    if not 1 <= len(reports) <= 128:
        raise ValueError('package between 1 and 128 terrain sections')
    common = None
    sections, containers = [], []
    for path in reports:
        report = json.loads(path.read_text())
        if (report.get('nanite_built') is not True or report.get('game_render_verified') is not True
                or report.get('target_platform') != 'Windows' or report.get('nanite_clusters', 0) < 1):
            raise ValueError('a game-validated Windows Nanite cook is required')
        mesh_path = Path(report['input_mesh'])
        if hashlib.sha256(mesh_path.read_bytes()).hexdigest() != report['input_sha256']:
            raise ValueError('portable mesh metadata changed after cooking')
        info = validate_mesh(mesh_path)
        covered = info.get('source_sections', [info.get('source_section')])
        if (not isinstance(covered, list) or not covered or len(covered)>64
                or any(type(section) is not int or section<0 for section in covered)
                or len(set(covered))!=len(covered)):
            raise ValueError('use an exported complete terrain section')
        layer = info.get('layer', 'terrain')
        if layer not in ('terrain','snow','snow_deposits','snow_transition'):
            raise ValueError('invalid terrain cache layer')
        auxiliary = layer in ('snow_deposits','snow_transition')
        if auxiliary:
            bounds = info.get('snow_uv_bounds')
            if (info.get('mesh_algorithm') != 3 or info.get('coat_material') != '/Game/Materials/Backgrounds/M_Snow.M_Snow'
                    or not isinstance(bounds,list) or len(bounds)!=2
                    or any(not isinstance(row,list) or len(row)!=2 for row in bounds)
                    or any(type(v) not in (int,float) or not math.isfinite(v) or not 0<=v<=1 for row in bounds for v in row)
                    or any(bounds[0][i]>bounds[1][i] for i in range(2))):
                raise ValueError('invalid snow coat material or bounds')
        source = Path(info['source_file']).read_bytes()
        if hashlib.sha256(source).hexdigest() != info['source_r16_sha256']:
            raise ValueError('terrain changed after geometry preparation')
        signature = {'version': 1, 'map_id': info['map_id'], 'target_platform': 'Windows',
            'engine_family': '5.8', 'mesh_algorithm': info.get('mesh_algorithm',1), 'game_render_verified': True,
            'source': dict(info['source_definition'], row_order=info['source_definition'].get('row_order', 'north_to_south')),
            'source_origin_centimeters': info['source_origin_centimeters'],
            'source_crc32': f'{zlib.crc32(source):08x}', 'source_sha256': info['source_r16_sha256'],
            'sample_step': info['sample_step'], 'tile_quads': info['tile_quads'],
            'uv_tile_meters': info['uv_tile_meters']}
        if signature['mesh_algorithm'] in (2,3):
            signature['snow_offset_centimeters']=info.get('snow_offset_centimeters',30)
        # Paired layers and all partitions must share the same transition and
        # snow slope model. A mixture of old and new cooks would reopen a
        # visible lighting or snow-coverage boundary despite matching R16s.
        for key in ('surface_transition','snow_retention_normals'):
            if key in info:
                signature[key]=info[key]
        if common is not None and common != signature:
            raise ValueError('sections use different terrain sources or settings')
        common = signature
        expected = info['package']+'.'+info['package'].rsplit('/', 1)[-1]
        if report['asset'] != expected:
            raise ValueError('cooked asset does not match its portable mesh')
        # The shipping game requires an IoStore TOC; a legacy pak alone is
        # silently ignored (pak.AllowMissingUToc=0).
        files = report.get('iostore', {})
        if set(files) != {'pak', 'utoc', 'ucas'}:
            raise ValueError('a verified IoStore pak/utoc/ucas bundle is required')
        name = 'SkiEO-'+info['package'].rsplit('/', 1)[-1]+'_P'
        bundled = {}
        for kind in ('pak', 'utoc', 'ucas'):
            source_path = Path(files[kind]['file'])
            if hashlib.sha256(source_path.read_bytes()).hexdigest() != files[kind]['sha256']:
                raise ValueError('cooked IoStore '+kind+' changed after verification')
            filename = name+'.'+kind
            bundled[kind] = {'file': filename, 'sha256': files[kind]['sha256']}
            containers.append((source_path, filename))
        algorithm=info.get('mesh_algorithm',1)
        if algorithm==3:
            if (len(covered)!=1 or type(info.get('parts')) is not int or not 1<=info['parts']<=32
                    or type(info.get('part')) is not int or not 0<=info['part']<info['parts']):
                raise ValueError('invalid Nanite partition')
        if any(entry.get('layer','terrain')==layer
               and set(entry.get('source_sections',[entry['section']]))&set(covered)
               and (algorithm!=3 or entry['part']==info['part']) for entry in sections):
            raise ValueError('duplicate terrain section')
        entry={'section': min(covered), 'asset': report['asset'],
                         'origin_meters': info['origin_meters'], 'iostore': bundled,
                         'nanite_clusters': report['nanite_clusters']}
        if algorithm in (2,3):
            entry.update(source_sections=sorted(covered),layer=layer)
        if algorithm==3:
            entry.update(part=info['part'],parts=info['parts'])
        if auxiliary:
            entry.update(snow_uv_bounds=info['snow_uv_bounds'],coat_material=info['coat_material'])
        sections.append(entry)
    if common['mesh_algorithm'] in (2,3):
        layers={layer:set() for layer in ('terrain','snow')}
        for entry in sections:
            if entry['layer'] in layers: layers[entry['layer']].update(entry['source_sections'])
        if any(not set(e['source_sections'])<=layers['terrain'] for e in sections):
            raise ValueError('snow coats require paired terrain partitions')
        if not layers['terrain'] or layers['terrain']!=layers['snow']:
            raise ValueError('massif must replace both rock and snow')
        if common['mesh_algorithm']==3:
            for section in layers['terrain']:
                groups={layer:[e for e in sections if e['layer']==layer and section in e['source_sections']]
                        for layer in ('terrain','snow')}
                total=groups['terrain'][0]['parts']
                for coat in [e for e in sections if e['layer'] not in layers and section in e['source_sections']]:
                    if coat['parts']!=total:
                        raise ValueError('snow coat partition count differs from terrain')
                for entries in groups.values():
                    if any(e['parts']!=total for e in entries) or {e['part'] for e in entries}!=set(range(total)):
                        raise ValueError('massif requires every rock and snow partition')
    if len(sections)>64 and common['mesh_algorithm']!=3:
        raise ValueError('expanded caches require partitioned terrain')
    cache = dict(common, sections=sorted(sections, key=lambda entry: entry['section']))
    if len(json.dumps(cache,indent=2).encode())>131072:
        raise ValueError('Nanite cache metadata exceeds 128 KiB')
    # Validate every source before creating any distributable output.
    output.mkdir(parents=True, exist_ok=True)
    for source_path, name in containers:
        shutil.copyfile(source_path, output/name)
    (output/'cache.json').write_text(json.dumps(cache, indent=2)+'\n')
    return cache


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('reports', type=Path, nargs='+')
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    try:
        result = package(args.reports, args.output_dir)
    except (ValueError, OSError, KeyError) as error:
        parser.error(str(error))
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
