"""Exercise shipped terrain-job parsing in an isolated Windows/Proton process."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools import skieo_install

parser=argparse.ArgumentParser()
parser.add_argument('--output',type=Path,required=True)
out=parser.parse_args().output.resolve()
out.mkdir(parents=True,exist_ok=False)
(out/'compatdata').mkdir()
helper=ROOT/'mod/SkiEO-CustomMaps/Scripts/skieo_native_terrain.dll'
shutil.copy2(helper,out/helper.name)
subprocess.run(['x86_64-w64-mingw32-gcc','-O2','-s','-Wall','-Wextra',
    '-Wl,--no-insert-timestamp',str(ROOT/'tests/height_job_harness.c'),'-o',str(out/'harness.exe')],check=True)
args,env,_=skieo_install.editor_launch_plan(skieo_install.load_config(),'c'*32)
args=args[:2]+[str(out/'harness.exe')]
env.update(STEAM_COMPAT_DATA_PATH=str(out/'compatdata'),WINEDEBUG='-all')
with (out/'process.log').open('w') as log:
    subprocess.run(args,cwd=out,env=env,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=120)
results=json.loads((out/'results.json').read_text())
assert len(results)==15 and all(case['passed'] for case in results)
(out/'identity.json').write_text(json.dumps({'helper_sha256':hashlib.sha256(helper.read_bytes()).hexdigest()},indent=2)+'\n')
print('Native terrain jobs: all 15 cases passed; rejected jobs preserved cache and samples.')
