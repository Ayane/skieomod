#!/usr/bin/env python3
"""Build the tutorial's editable map and separate Surface Lifts source project."""
from pathlib import Path
import contextlib
import io
import json
import shutil
import struct
import sys
import tempfile
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools import skieo_project as projects
from tools.custom_map import check_dependencies
from tools.custom_maps import write_zip_member

FILES=ROOT/'repository/web/public/tutorials/surface-lifts/files'
OPTIONS={'lifts':[{'name':'Practice platter','kind':'detachable_platter',
    'route':[[-8000,24000,0],[-8000,0,0],[-8000,-24000,0]],
    'speed_mps':2.5,'capacity_per_hour':600,'pylons':4,
    'drive':'open','return_station':'floating','ascent_side':'left'}]}
SCENE={'version':1,'objects':[
    {'id':'practice-platter','name':'Practice platter','kind':'lift',
     'class':'/Game/Blueprints/Lifts/BP_FixedChair1.BP_FixedChair1_C',
     'position':[-80,240],'end_position':[-80,-240]},
    {'id':'ticket-office','name':'Practice ticket office','kind':'building',
     'class':'/Game/Blueprints/Buildings/BP_TicketOffice.BP_TicketOffice_C',
     'position':[-45,260]}]}


CUSTOM_OPTIONS=json.loads(json.dumps(OPTIONS))
CUSTOM_OPTIONS['lifts'][0]['models']={
    'drive':'Assets/blue-drive.skpm','tower':'Assets/blue-tower.skpm',
    'platter_lower':'Assets/blue-platter-lower.skpm','palette':'Assets/lift-palette.png'}
CUSTOM_OPTIONS['lifts'][0]['pylon_models']=[{'index':2,'models':{
    'tower':'Assets/orange-tower.skpm','guide_wheel':'Assets/orange-guide-wheel.skpm'}}]
CUSTOM_OPTIONS['lifts'].append(dict(OPTIONS['lifts'][0],name='Default platter',
    route=[[8000,24000,0],[8000,0,0],[8000,-24000,0]]))


def colour_variant(data,colour):
    """Keep geometry/anchors intact; change only the grey palette entries."""
    result=bytearray(data)
    for i in range(struct.unpack_from('<I',data,8)[0]):
        offset=16+i*32+24
        if abs(struct.unpack_from('<f',data,offset)[0]-.5/8)<1e-6:
            struct.pack_into('<f',result,offset,(colour+.5)/8)
    return bytes(result)


def custom_models_example(root,mountain,output):
    project=root/'practice-custom-models'
    shutil.copytree(mountain,project,ignore=shutil.ignore_patterns('bin','obj'))
    p=project/'custom-map.json';manifest=json.loads(p.read_text())
    manifest['id']='tutorial.surface-lift-models'
    manifest['metadata']['name']='Surface lift custom models'
    manifest['metadata']['description']='Two lifts using one shared mapmod, with per-lift and per-pylon cosmetic variants. Requires loader 1.27.0+.'
    manifest['extensions']['community.surface-lifts']=CUSTOM_OPTIONS
    source=ROOT/'mod/SkiEO-SurfaceLifts'
    assets=project/'Assets';assets.mkdir(exist_ok=True)
    for target,original,colour in [('blue-drive','poma-drive',3),('blue-tower','tower',3),
            ('blue-platter-lower','platter-lower',3),('orange-tower','tower',6),('orange-guide-wheel','guide-wheel',6)]:
        (assets/(target+'.skpm')).write_bytes(colour_variant((source/'Assets'/(original+'.skpm')).read_bytes(),colour))
    shutil.copyfile(source/'Assets/palette.png',assets/'lift-palette.png')
    names=['Assets/'+path.name for path in sorted(assets.iterdir())]
    manifest['metadata']['license']='MIT (map); BSD-3-Clause (model variants)'
    manifest['content'].setdefault('assets',[]).extend(names)
    for name in ['LICENSE','CREDITS.txt']:
        target='MODEL-LICENSE.txt'if name=='LICENSE'else'MODEL-CREDITS.txt'
        shutil.copyfile(source/name,project/target)
        manifest['content']['assets'].append(target)
    p.write_text(json.dumps(manifest,indent=2)+'\n')
    scene=json.loads(json.dumps(SCENE))
    scene['objects'].append(dict(SCENE['objects'][0],id='default-platter',name='Default platter',
                                 position=[80,240],end_position=[80,-240]))
    (project/'Scene/objects.json').write_text(json.dumps(scene,indent=2)+'\n')
    with contextlib.redirect_stdout(io.StringIO()):archive,_=projects.build(project)
    shutil.copyfile(archive,output/'tutorial.surface-lift-models-0.1.0.skieomap')
    with zipfile.ZipFile(output/'surface-lift-custom-models.zip','w')as archive:
        write_zip_member(archive,'README.txt',b'Loader 1.27.0+ is required. Extract beside the original surface-lifts project. Build and run practice-custom-models with --dependency surface-lifts. Read https://skieomod.emillon.fr/tutorials/surface-lifts/#models\n')
        write_zip_member(archive,'surface-lifts-tutorial.md',(ROOT/'docs/surface-lifts-tutorial.md').read_bytes())
        for path in sorted(project.rglob('*')):
            if path.is_file()and path.relative_to(project).parts[0]not in {'bin','obj'}:
                write_zip_member(archive,project.name+'/'+path.relative_to(project).as_posix(),path.read_bytes())
    (output/'custom-models-options.json').write_text(json.dumps(CUSTOM_OPTIONS,indent=2)+'\n')


def build(output=None):
    output=Path(output or FILES);output.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='surface-lift-tutorial-')as temporary:
        root=Path(temporary);mountain=root/'practice-mountain';mod=root/'surface-lifts'
        with contextlib.redirect_stdout(io.StringIO()):
            projects.create('map',mountain,'Surface lift practice','tutorial.surface-lift-practice',
                            'Albatar (Élie Millon)',blank=True)
        manifest_path=mountain/'custom-map.json'
        manifest=json.loads(manifest_path.read_text())
        manifest['metadata']['description']='A small workshop exercise: adapt a native one-seat lift to a platter surface lift.'
        manifest['dependencies']=[{'id':'community.surface-lifts','version':'=0.1.0'}]
        manifest['extensions']={'community.surface-lifts':OPTIONS}
        manifest['script']['api']='1.4'
        manifest['build']['scene']={'file':'Scene/objects.json'}
        manifest_path.write_text(json.dumps(manifest,indent=2)+'\n')
        (mountain/'Scene').mkdir()
        (mountain/'Scene/objects.json').write_text(json.dumps(SCENE,indent=2)+'\n')
        source=ROOT/'mod/SkiEO-SurfaceLifts'
        mod_manifest=json.loads((source/'custom-mod.json').read_text())
        for name in ['custom-mod.json',*mod_manifest['files']]:
            target=mod/name;target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(source/name,target)
        with contextlib.redirect_stdout(io.StringIO()):
            _,dependency=projects.build(mod)
            map_archive,package=projects.build(mountain)
        check_dependencies(package['manifest'],'map',[dependency])
        readme='''# Surface lift practice

Open practice-mountain/custom-map.json in skieomod editor.
The native one-seat lift is named Practice platter. Its scene coordinates are
in metres; the mapmod route uses world centimetres. Z is sampled at runtime.

From this extracted folder, build and play the separate source projects:

    skieomod build surface-lifts
    skieomod build practice-mountain --dependency surface-lifts
    skieomod run practice-mountain --dependency surface-lifts

The two source projects are separate packages. Do not copy mod assets into the map.
Read https://skieomod.emillon.fr/tutorials/surface-lifts/ for the full guide.
Use the ordinary game tools to add trails, staff and the rest of your resort.
'''
        with zipfile.ZipFile(output/'surface-lift-practice.zip','w')as archive:
            write_zip_member(archive,'README.txt',readme.encode())
            write_zip_member(archive,'surface-lifts-tutorial.md',(ROOT/'docs/surface-lifts-tutorial.md').read_bytes())
            for project in [mountain,mod]:
                for path in sorted(project.rglob('*')):
                    relative=path.relative_to(project)
                    if path.is_file()and relative.parts[0]not in {'bin','obj','.heightmap-backups'}:
                        write_zip_member(archive,project.name+'/'+relative.as_posix(),path.read_bytes())
        (output/'surface-lifts-options.json').write_text(json.dumps(OPTIONS,indent=2)+'\n')
        (output/'objects.json').write_text(json.dumps(SCENE,indent=2)+'\n')
        # The test map is also useful for isolated in-game qualification.
        target=output/'tutorial.surface-lift-practice-0.1.0.skieomap'
        shutil.copyfile(map_archive,target)
        custom_models_example(root,mountain,output)
        return {'archive':target,'manifest':package['manifest']}


if __name__=='__main__':
    print(build()['archive'])
