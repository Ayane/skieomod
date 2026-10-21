from pathlib import Path
import hashlib,json,struct,subprocess,sys,time,os
# Run explicitly on a Linux host with the configured Windows game and Proton.
# All writes/processes use --output, never the configured game or user prefix.
import argparse
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
parser=argparse.ArgumentParser(description='Windows updater integration in a disposable Proton prefix')
parser.add_argument('--output',type=Path,required=True)
options=parser.parse_args()
from tools import skieo_install
out=options.output.resolve();out.mkdir(parents=True,exist_ok=False);(out/'compatdata').mkdir()
source=ROOT/'native/SkiEOUpdater';scripts=ROOT/'mod/SkiEO-CustomMaps/Scripts'
# Test the shipped binaries; compile only the harness and fault-injection worker.
common=['x86_64-w64-mingw32-gcc','-O2','-s','-municode','-Wl,--no-insert-timestamp','-I',str(source)]
subprocess.run(common+[str(ROOT/'tests/updater_harness.c'),'-o',str(out/'harness.exe'),'-lbcrypt'],check=True)
subprocess.run(common+['-DSKIEO_UPDATER_TEST',str(source/'updater.c'),'-o',str(out/'fault-worker.exe'),'-lbcrypt'],check=True)
payload=out/'payload.c';payload.write_text('__declspec(dllexport) int value(void) { return PAYLOAD_VERSION; }\n')
for version in (1,2):
 subprocess.run(['x86_64-w64-mingw32-gcc','-shared','-O2','-s','-Wl,--no-insert-timestamp',f'-DPAYLOAD_VERSION={version}',str(payload),'-o',str(out/f'payload-{version}.dll')],check=True)
config=skieo_install.load_config();args,env,cwd=skieo_install.editor_launch_plan(config,'b'*32)
args=args[:2]+[str(out/'harness.exe')];env['STEAM_COMPAT_DATA_PATH']=str(out/'compatdata');env['WINEDEBUG']='-all'
# Every process inherits this isolated prefix; restart invokes the captured harness.
def win(path):return 'Z:'+str(path).replace('/','\\')
def wait_for(fn,seconds=60):
 end=time.monotonic()+seconds
 while time.monotonic()<end:
  if fn():return
  time.sleep(.2)
 raise AssertionError('deadline')
results=[]
for name,mode in [('restart','restart'),('normal-quit','quit'),('rollback','quit'),('power-cut','quit'),('tampered-stage','tamper'),('invalid-path','quit'),('hash-mismatch','quit')]:
 mod=out/name/'SkiEO-CustomMaps';(mod/'Scripts').mkdir(parents=True)
 initial={'Scripts/main.lua':b'-- stable main','Scripts/entry.lua':b'-- old entry','Scripts/payload.lua':b'old payload','Scripts/payload.dll':(out/'payload-1.dll').read_bytes(),
          'Scripts/skieo_update_bootstrap.dll':(scripts/'skieo_update_bootstrap.dll').read_bytes(),
          'Scripts/skieo_updater.exe':(out/'fault-worker.exe').read_bytes() if name in ['rollback','power-cut'] else (scripts/'skieo_updater.exe').read_bytes()}
 for n,b in initial.items():(mod/n).write_bytes(b)
 (mod/'Scripts/settings.json').write_text('USER SETTINGS');(mod/'Scripts/removed.lua').write_bytes(b'original obsolete')
 (mod/'Scripts/modified.lua').write_bytes(b'USER MODIFICATION')
 old={'format':'skieomod-loader','version':1,'release':'1.24.7','files':{n:hashlib.sha256(b).hexdigest() for n,b in initial.items()}}
 (mod/'loader-release.json').write_text(json.dumps(old))
 next_files=dict(initial);next_files['Scripts/entry.lua']=b'-- new entry';next_files['Scripts/payload.lua']=b'new payload';next_files['Scripts/payload.dll']=(out/'payload-2.dll').read_bytes()
 record={'format':'skieomod-loader','version':1,'release':'1.24.8','files':{n:hashlib.sha256(b).hexdigest() for n,b in next_files.items()}}
 raw=json.dumps(record).encode();obsolete=[('Scripts/removed.lua',hashlib.sha256(b'original obsolete').digest()),('Scripts/modified.lua',hashlib.sha256(b'old upstream file').digest())]
 bundle=bytearray(struct.pack('<4sIIII',b'SKUP',1,len(next_files),len(obsolete),len(raw))+raw)
 for n,b in sorted(next_files.items()):
  if name=='invalid-path' and n=='Scripts/payload.lua':n='Scripts/../escape.lua'
  sha=hashlib.sha256(b).digest()
  if name=='hash-mismatch' and n=='Scripts/payload.lua':sha=bytes(32)
  encoded=n.encode();bundle+=struct.pack('<H',len(encoded))+encoded+sha+struct.pack('<I',len(b))+b
 for n,sha in obsolete:
  encoded=n.encode();bundle+=struct.pack('<H',len(encoded))+encoded+sha
 (mod/'Scripts/loader-update.bundle').write_bytes(bundle)
 if name=='rollback':(mod/'inject-update-failure').touch()
 if name=='power-cut':(mod/'inject-update-crash').touch()
 with (out/(name+'.log')).open('w') as log:
  process=subprocess.Popen(args+[win(mod),mode],cwd=cwd,env=env,stdout=log,stderr=subprocess.STDOUT)
  code=process.wait(timeout=120)
 if name in ['invalid-path','hash-mismatch']:
  assert code==5,(name,code)
  assert (mod/'Scripts/payload.lua').read_bytes()==b'old payload'
  assert not (mod/'escape.lua').exists()
 else:
  assert code==0,(name,code)
  assert (mod/'ready-before-exit.txt').is_file()
  status=mod/'Scripts/loader-update.status'
  wait_for(lambda: status.exists() and status.read_text().split()[0] in (['applying'] if name=='power-cut' else ['applied','failed']))
  if name=='power-cut':
   time.sleep(1)
   with (out/(name+'-recover.log')).open('w') as log:
    code=subprocess.run(args+[win(mod),'recover'],cwd=cwd,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=120).returncode
   assert code==0 and status.read_text().startswith('failed'),(name,code,status.read_text())
   assert (mod/'native-payload-value.txt').read_text()=='1'
  expected=b'old payload' if name in ['rollback','power-cut','tampered-stage'] else b'new payload'
  assert (mod/'Scripts/payload.lua').read_bytes()==expected,(name,status.read_text())
  assert (mod/'Scripts/payload.dll').read_bytes()==(out/('payload-1.dll' if expected==b'old payload' else 'payload-2.dll')).read_bytes()
  if name=='restart':
   wait_for(lambda:(mod/'restarted.txt').exists())
   assert (mod/'restarted.txt').read_text()!=(mod/'original-pid.txt').read_text()
   assert (mod/'native-payload-value.txt').read_text()=='2'
  if name in ['restart','normal-quit']:assert not (mod/'Scripts/removed.lua').exists()
  else:assert (mod/'Scripts/removed.lua').read_bytes()==b'original obsolete'
 assert (mod/'Scripts/settings.json').read_text()=='USER SETTINGS'
 assert (mod/'Scripts/modified.lua').read_bytes()==b'USER MODIFICATION'
 if name not in ['restart']:assert not (mod/'restarted.txt').exists()
 results.append({'case':name,'passed':True});print(name,'OK',flush=True)
(out/'results.json').write_text(json.dumps(results,indent=2)+'\n')
