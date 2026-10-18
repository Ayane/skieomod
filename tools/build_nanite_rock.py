#!/usr/bin/env python3
"""Build a derived Windows Nanite pak with a source-built Linux Unreal editor.

Engine dependencies and the matching native toolchain must already be present.
The engine is a build tool; its resources are not copied into the portable map.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess


def validate_mesh(path: Path) -> dict:
    info = json.loads(path.read_text())
    if info.get('version') != 1 or info.get('coordinate_system') != 'east-south-up-metres':
        raise ValueError('unsupported portable mesh')
    if info.get('winding') != 'counterclockwise':
        raise ValueError('unsupported mesh winding')
    for field, maximum in (('vertices', 1_000_000), ('triangles', 2_000_000)):
        if type(info.get(field)) is not int or not 1 <= info[field] <= maximum:
            raise ValueError(f'invalid {field} budget')
    origin = info.get('origin_meters')
    if (not isinstance(origin, list) or len(origin) != 3
            or not all(type(v) in (int, float) and math.isfinite(v) for v in origin)):
        raise ValueError('invalid map origin')
    for name, components, count in [('positions', 3, info['vertices']),
                                    ('normals', 3, info['vertices']),
                                    ('uvs', 2, info['vertices']),
                                    ('indices', 3, info['triangles'])]:
        entry = info['buffers'][name]
        relative = Path(entry['file'])
        if relative.name != entry['file']:
            raise ValueError('buffer paths must be local filenames')
        contents = (path.parent/relative).read_bytes()
        if (len(contents) != count*components*4 or entry['bytes'] != len(contents)
                or hashlib.sha256(contents).hexdigest() != entry['sha256']):
            raise ValueError(f'{name} buffer changed; regenerate the portable mesh')
    return info


def convert_iostore(report_path: Path, retoc: Path) -> dict:
    report = json.loads(report_path.read_text())
    info = validate_mesh(Path(report['input_mesh']))
    output = report_path.resolve().parent
    name = info['package'].rsplit('/', 1)[-1]
    stage = output/'legacy'/name
    destination = stage/'SkiResortSimulator/Content'/info['package'][6:]
    destination.parent.mkdir(parents=True, exist_ok=True)
    source = Path(report['cooked_uasset'])
    for suffix in ('.uasset', '.uexp', '.ubulk', '.uptnl'):
        path = source.with_suffix(suffix)
        target = destination.with_suffix(suffix)
        if path.exists(): shutil.copyfile(path, target)
        else: target.unlink(missing_ok=True)
    container = output/('SkiEO-'+name+'_P.utoc')
    with (output/'iostore.log').open('w') as log:
        # UE 5.8 uses file version 1018, Zen version 3 and container header 5,
        # matching retoc's UE5_7 profile. The import-layout patch is required.
        subprocess.run([str(retoc.resolve()), 'to-zen', str(stage), str(container),
                        '--version', 'UE5_7', '--no-parallel'], stdout=log,
                       stderr=subprocess.STDOUT, check=True)
        subprocess.run([str(retoc.resolve()), 'verify', str(container)], stdout=log,
                       stderr=subprocess.STDOUT, check=True)
    files = {suffix[1:]: container.with_suffix(suffix) for suffix in ('.pak', '.utoc', '.ucas')}
    if not all(path.is_file() for path in files.values()):
        raise ValueError('IoStore conversion did not produce all three container files')
    report['iostore'] = {key: {'file': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
                         for key, path in files.items()}
    report['game_render_verified'] = False
    report_path.write_text(json.dumps(report, indent=2)+'\n')
    return report


def build(engine: Path, mesh: Path, output: Path, toolchain: Path | None, jobs: int,
          retoc: Path | None = None, project_stage: Path | None = None) -> dict:
    if not 1 <= jobs <= 4:
        raise ValueError('use between 1 and 4 compilation jobs')
    mesh, engine, output = mesh.resolve(), engine.resolve(), output.resolve()
    info = validate_mesh(mesh)
    version = json.loads((engine/'Engine/Build/Build.version').read_text())
    if (version['MajorVersion'], version['MinorVersion']) != (5, 8):
        raise ValueError('the installed game requires Unreal 5.8 assets')
    build_script = engine/'Engine/Build/BatchFiles/RunUBT.sh'
    dotnet = engine/'Engine/Binaries/ThirdParty/DotNet'
    if not build_script.exists() or not dotnet.exists():
        raise ValueError('Unreal dependencies are missing; run official GitDependencies first')
    template = Path(__file__).resolve().parents[1]/'native/SkiEONanite'
    # A streamed massif can reuse one compiled editor project while keeping
    # separate reports/containers. Calls sharing this stage must be serial.
    stage = project_stage.resolve() if project_stage is not None else output/'project'
    output.mkdir(parents=True, exist_ok=True)
    if template.resolve() == stage or template.resolve() in stage.parents:
        raise ValueError('stage the Unreal project outside its source directory')
    shutil.copytree(template, stage, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns('Binaries', 'Intermediate', 'Saved', 'DerivedDataCache'))
    project = stage/'SkiEONanite.uproject'
    env = os.environ.copy()
    env['DOTNET_CLI_HOME'] = str(output/'dotnet-home')
    env['UE_SDKS_ROOT'] = str(output/'AutoSDKs')
    # Epic's Windows target has no AutoSDK path: this permits geometry-only
    # cooking from Linux without claiming a Windows C++/shader toolchain exists.
    (output/'AutoSDKs').mkdir(exist_ok=True)
    if toolchain:
        env['LINUX_MULTIARCH_ROOT'] = str(toolchain.resolve())
    common = [f'-MaxParallelActions={jobs}', '-NoUBA', '-NoUBTMakefiles']
    state_file = output/'state.json'

    def run(label: str, command: list[str]):
        state_file.write_text(json.dumps({'status': label, 'mesh': str(mesh),
                                        'engine_version': version}, indent=2)+'\n')
        print(label, flush=True)
        with (output/(label+'.log')).open('w') as log:
            subprocess.run(command, cwd=engine, env=env, stdout=log,
                           stderr=subprocess.STDOUT, check=True)

    try:
        run('compile', ['bash', str(build_script), 'SkiEONaniteEditor', 'Linux', 'Development',
                        f'-Project={project}', *common])
        run('compile-unrealpak', ['bash', str(build_script), 'UnrealPak', 'Linux', 'Development', *common])
        editor = engine/'Engine/Binaries/Linux/UnrealEditor'
        report_path = output/'cook-report.json'
        report_path.unlink(missing_ok=True)
        run('cook', [str(editor), str(project), '-run=SkiEONanite', f'-Input={mesh}',
                     f'-Report={report_path}', '-nullrhi', '-unattended', '-nosound', '-stdout',
                     '-FullStdOutLogOutput', '-NoShaderCompile', f'-corelimit={jobs}', '-DDC=(Local)',
                     f'-LocalDataCachePath={output / "derived-data"}'])
        report = json.loads(report_path.read_text())
        if (report.get('nanite_built') is not True or report.get('target_platform') != 'Windows'
                or report.get('nanite_clusters', 0) < 1):
            raise ValueError('cooker did not confirm Windows Nanite resources')
        if report.get('asset') != info['package']+'.'+info['package'].rsplit('/', 1)[-1]:
            raise ValueError('cooker returned a different asset package')
        asset = Path(report['cooked_uasset'])
        mount = '../../../SkiResortSimulator/Content/'+info['package'][6:]
        entries = []
        for suffix in ('.uasset', '.uexp', '.ubulk', '.uptnl'):
            source = asset.with_suffix(suffix)
            if source.exists():
                if '"' in str(source):
                    raise ValueError('UnrealPak response paths cannot contain quotes')
                entries.append(f'"{source}" "{mount}{suffix}"')
        response = output/'pak-response.txt'
        response.write_text('\n'.join(entries)+'\n')
        pak = output/'SkiEO-Veymont-NaniteProof.pak'
        # UnrealPak deliberately refuses to overwrite an existing container.
        # This is our generated artifact in the selected build directory.
        pak.unlink(missing_ok=True)
        run('package', [str(engine/'Engine/Binaries/Linux/UnrealPak'), str(pak), f'-Create={response}'])
        run('verify-pak', [str(engine/'Engine/Binaries/Linux/UnrealPak'), str(pak), '-Test'])
        report.update({'pak': str(pak), 'pak_sha256': hashlib.sha256(pak.read_bytes()).hexdigest(),
                       'input_mesh': str(mesh),
                       'input_sha256': hashlib.sha256(mesh.read_bytes()).hexdigest(),
                       'engine_version': version, 'game_render_verified': False})
        report_path.write_text(json.dumps(report, indent=2)+'\n')
        if retoc:
            state_file.write_text(json.dumps({'status': 'convert-iostore'})+'\n')
            report = convert_iostore(report_path, retoc)
        state_file.write_text(json.dumps({'status': 'cooked-awaiting-game-validation',
                                          'report': str(report_path)}, indent=2)+'\n')
        return report
    except (subprocess.CalledProcessError, ValueError, OSError) as error:
        state_file.write_text(json.dumps({'status': 'failed', 'error': str(error)}, indent=2)+'\n')
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mesh', type=Path)
    parser.add_argument('--engine', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--toolchain', type=Path)
    parser.add_argument('--jobs', type=int, default=2)
    parser.add_argument('--retoc', type=Path, help='Unreal 5.8 compatible retoc with the included import-layout patch')
    parser.add_argument('--project-stage',type=Path,help='Reuse one compiled editor project; builds must be serial')
    args = parser.parse_args()
    try:
        print(json.dumps(build(args.engine, args.mesh, args.output_dir, args.toolchain, args.jobs, args.retoc,args.project_stage), indent=2))
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(1, str(error)+'\n')


if __name__ == '__main__':
    main()
