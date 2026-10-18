import contextlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from tools import skieo_authoring as a, skieo_editor as editor, skieo_project as projects
from tools.custom_maps import ManifestError
from tests.test_heightmap_build import png16

OBJ = b'v 0 0 0\nv 2 0 0\nv 2 3 1\nv 0 3 1\nvt 0 0\nvt 1 0\nvt 1 1\nvt 0 1\nf -4/1 -3/2 -2/3 -1/4\n'

class AuthoringBuildTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.folder=self.root/'source map'
        projects.create('map',self.folder,'Custom Mountain','test.authoring')
        self.doc=editor.EditorProject(self.folder)
    def execute(self,script):
        if not shutil.which('lua'): self.skipTest('Lua interpreter unavailable')
        result=subprocess.run(['lua','-'],input=script,text=True,capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr)
    def test_graph_executes_typed_values_branch_delay_and_utf8(self):
        graph=a.new_trigger()['graph'];graph['nodes'][2]['params']['value']='Snow ⛷\n"go"'
        graph['nodes'] += [{'id':'amount','kind':'event_value','params':{'key':'budget','fallback':20}}, {'id':'sum','kind':'add'}, {'id':'thirty','kind':'number','params':{'value':30}}, {'id':'test','kind':'compare','params':{'operator':'>='}}, {'id':'forty','kind':'number','params':{'value':40}}, {'id':'branch','kind':'branch'}, {'id':'wait','kind':'delay'}, {'id':'seconds','kind':'number','params':{'value':.25}}, {'id':'money','kind':'funds'}]
        for source,port,target,pin in [('thirty','value','sum','b'),('forty','value','test','b'),('seconds','value','wait','seconds'),('amount','value','sum','a'),('sum','value','test','a'),('sum','value','money','amount'),('test','value','branch','condition'),('message','then','branch','in'),('branch','true','wait','in'),('wait','then','money','in')]: graph['edges'].append({'source':source,'port':port,'target':target,'input':pin})
        self.doc.queue_authoring('triggers',{'version':1,'triggers':[{**a.new_trigger(),'graph':graph}]});self.doc.save()
        with contextlib.redirect_stdout(io.StringIO()): path,_=projects.build(self.folder)
        with zipfile.ZipFile(path) as package: script=package.read(a.GENERATED_SCRIPT).decode()
        self.execute('''local callbacks={};local funds,message,delay
local api={game={add_funds=function(_,v) funds=v end},on=function(_,name,fn) callbacks[name]=fn end,log=function(_,v) message=v end,after=function(_,ms,fn) delay=ms;fn() end}
local register=(function()\n'''+script+'''\nend)();register(api);callbacks['map.ready']({budget=20})
assert(funds==50 and delay==250 and message=='''+a.lua('Snow ⛷\n"go"')+''')
assert(not pcall(callbacks['map.ready'],{budget='wrong'}))
''')
    def test_invalid_graphs_and_disconnected_parameters(self):
        graph=a.new_trigger()['graph'];graph['edges'].append({'source':'message','port':'then','target':'message','input':'in'})
        with self.assertRaises(ManifestError): a.compile_graph(graph)
        graph=a.new_trigger()['graph'];graph['nodes'].append({'id':'bad','kind':'funds','params':{'amount':'oops'}})
        with self.assertRaisesRegex(ManifestError,'Connect a constant'): a.compile_graph(graph)
        graph=a.new_trigger()['graph'];graph['nodes'].append({'id':'num','kind':'number'});graph['edges'].append({'source':'num','port':'value','target':'message','input':'in'})
        with self.assertRaises(ManifestError): a.compile_graph(graph)
        with self.assertRaisesRegex(ManifestError,'Duplicate'): a.compile_triggers({'version':1,'triggers':[a.new_trigger(),a.new_trigger()]})

    def test_scenario_graph_configures_before_base_handlers_without_mutating_rules(self):
        source=Path('mod/SkiEO-SuperSaintBernard/Triggers/triggers.json')
        trigger=json.loads(source.read_text())['triggers'][0]
        self.doc.queue_authoring('triggers',{'version':1,'triggers':[trigger]})
        self.doc.set_script('return function(api) api:on("map.ready", function() api:log("base") end) end')
        self.doc.save()
        (self.folder/'Scripts/economy.lua').write_text('return {costs={test=12},loans={test=34},track_lift_rides=true}')
        manifest=json.loads((self.folder/'custom-map.json').read_text())
        manifest['content']['assets'].append('Scripts/economy.lua')
        (self.folder/'custom-map.json').write_text(json.dumps(manifest))
        with contextlib.redirect_stdout(io.StringIO()): path,_=projects.build(self.folder)
        with zipfile.ZipFile(path) as package:
            script=package.read(a.GENERATED_SCRIPT).decode()
            self.assertEqual(json.loads(package.read('custom-map.json'))['script']['api'],'1.1')
        self.execute('''local callbacks,configured={},false
local rules={costs={test=12},loans={test=34},track_lift_rides=true}
package.preload.economy=function() return rules end
local api={load_forest_skxy=function() end,on=function(_,name,fn) callbacks[name]=callbacks[name] or {};table.insert(callbacks[name],fn) end,
    log=function() assert(configured,'base handler ran before scenario configuration') end,
    game={configure=function(_,options)
        assert(not configured,'scenario configured twice');configured=true
        assert(options.currency=='CHF' and options.start_year==2003 and options.starting_balance==250000 and options.ticket_price==38)
        assert(options.costs==rules.costs and options.loans==rules.loans and options.track_lift_rides)
    end}}
local register=(function()\n'''+script+'''\nend)();register(api)
assert(not configured,'configuration ran before map.ready')
for _,fn in ipairs(callbacks['map.ready']) do fn({restored=false}) end
assert(configured and rules.currency==nil,'shared module table was mutated')
''')
        graph=trigger['graph']
        graph['edges']=[e for e in graph['edges'] if e['input']!='starting_balance']
        with self.assertRaisesRegex(ManifestError,'starting_balance'): a.compile_graph(graph)
        with self.assertRaisesRegex(ManifestError,'before_script'):
            a.compile_triggers({'version':1,'triggers':[{**a.new_trigger(),'before_script':'yes'}]})
    def test_shared_data_compiles_to_bounded_lua(self):
        graph=a.new_trigger()['graph'];graph['nodes'].append({'id':'zero','kind':'number'});previous='zero'
        graph['edges']=[e for e in graph['edges'] if e['input']!='message']
        for i in range(80):
            identifier='n'+str(i);graph['nodes'].append({'id':identifier,'kind':'add'})
            if previous:
                for pin in ('a','b'): graph['edges'].append({'source':previous,'port':'value','target':identifier,'input':pin})
            previous=identifier
        graph['edges'].append({'source':previous,'port':'value','target':'message','input':'message'})
        self.assertLess(len(a.compile_graph(graph)),6000)
    def test_amount_requires_visible_constant_and_scene_is_compiled(self):
        graph=a.new_trigger()['graph'];graph['nodes'].append({'id':'funds','kind':'funds','params':{'amount':50000}})
        graph['edges'].append({'source':'message','port':'then','target':'funds','input':'in'})
        a.compile_graph(graph,complete=False)
        with self.assertRaisesRegex(ManifestError,'Connect a constant.*amount'): a.compile_graph(graph)
        graph['nodes'].append({'id':'constant','kind':'number','params':{'value':50000}})
        graph['edges'].append({'source':'constant','port':'value','target':'funds','input':'amount'})
        compiled=a.compile_graph(graph);self.assertIn('50000',compiled);self.assertIn('api.game:add_funds(_v',compiled)
        scene={'version':1,'objects':[{'id':'office','name':'Office','kind':'building','class':a.OBJECTS[0]['class'],'position':[5,10]},
            {'id':'lift','name':'Lift','kind':'lift','class':a.OBJECTS[1]['class'],'position':[20,30],'end_position':[20,200]}]}
        placements=a.compile_scene(scene,self.doc.manifest);self.assertEqual(placements[0]['position_cm'],[500,1000]);self.assertEqual(placements[0]['hub'],placements[1]['hub']);self.assertNotEqual(placements[1]['hub'],placements[1]['top_hub'])
        reordered=a.compile_scene({**scene,'objects':list(reversed(scene['objects']))},self.doc.manifest);self.assertEqual(placements[0]['guid'],reordered[1]['guid']);self.assertEqual(placements[0]['hub'],reordered[1]['hub'])
        self.doc.change_scene(scene);self.assertTrue(self.doc.undo());self.assertEqual(self.doc.scene['objects'],[]);self.doc.redo();self.doc.save()
        with contextlib.redirect_stdout(io.StringIO()): path,_=projects.build(self.folder)
        with zipfile.ZipFile(path) as package:
            self.assertNotIn('Scene/objects.json',package.namelist());script=package.read(a.GENERATED_SCRIPT).decode();self.assertIn('api:place_objects',script)
        self.assertEqual(editor.EditorProject(self.folder).scene,scene)
        for change in ({'position':[float('nan'),0]},{'position':[1e9,0]},{'class':'/Script/Engine.Actor'}):
            with self.assertRaises(ManifestError): a.compile_scene({**scene,'objects':[{**scene['objects'][0],**change}]},self.doc.manifest)

    def test_native_scene_variant_is_preserved_and_validated(self):
        item={'id':'marker','kind':'decoration','class':'/Game/Blueprints/Decorations/BP_TrailMarkers.BP_TrailMarkers_C',
              'position':[5,10],'variant':'Expert'}
        scene={'version':1,'objects':[item]}
        self.assertEqual(a.compile_scene(scene,self.doc.manifest)[0]['variant'],'Expert')
        for value in ('',None,'Expert\n',{},'x'*81):
            with self.assertRaises(ManifestError): a.compile_scene({'version':1,'objects':[{**item,'variant':value}]},self.doc.manifest)

    def test_obj_indices_uv_units_axis_and_invalid_geometry(self):
        mesh=a.parse_obj(OBJ);self.assertEqual(len(mesh['vertices']),6);self.assertEqual(mesh['vertices'][2],[200,300,100]);self.assertEqual(mesh['uv'][2],[1,1])
        self.assertEqual(a.parse_obj(OBJ,'centimeters','y')['vertices'][2],[2,-1,3])
        for invalid in (b'v 0 0 0\nf 1 2 3',b'v nan 0 0\nf 1 1 1',b'v 0 0 0\nf 1 1 1',b'\xff'):
            with self.assertRaises(ManifestError): a.parse_obj(invalid)
    def test_build_composes_forest_lua_objects_and_preserves_sources(self):
        png=self.root/'original.png';png.write_bytes(png16(9,17,[i*350 for i in range(153)]))
        self.doc.import_heightmap(png,{'spacing_meters':8});obj=self.root/'ticket-office.obj';obj.write_bytes(OBJ);self.doc.import_resource(obj,'office','model',units='meters',up_axis='z')
        self.doc.queue_authoring('triggers',{'version':1,'triggers':[a.new_trigger(),{'id':'cash','name':'Cash','mode':'lua','event':'map.ready','lua':'api.game:add_funds(17)'}]})
        edit={'object':a.OBJECTS[0]['class'],'field':'MeshComponent.StaticMesh','type':'model','value':'asset:office'};self.doc.queue_authoring('objects',[edit])
        self.doc.begin_stroke('trees');self.doc.paint(0,0,'trees',12,tree_spacing=8);self.doc.end_stroke();self.doc.save()
        before={p:p.read_bytes() for p in self.folder.rglob('*') if p.is_file()}
        with contextlib.redirect_stdout(io.StringIO()): path,_=projects.build(self.folder)
        first=path.read_bytes()
        with zipfile.ZipFile(path) as package:
            names=set(package.namelist());manifest=json.loads(package.read('custom-map.json'));script=package.read(a.GENERATED_SCRIPT).decode()
            self.assertNotIn('build',manifest);self.assertIn('gameplay',manifest['script']['permissions']);self.assertIn('Vegetation/Generated/forest.skxy',names)
            for source in ('Triggers/triggers.json','Objects/overrides.csv','Resources/assets.json','Resources/Files/ticket-office.obj'): self.assertNotIn(source,names)
        self.execute('''local callbacks={};local calls,forest,money=0,false,0
local api={on=function(_,event,fn) callbacks[event]=callbacks[event] or {};table.insert(callbacks[event],fn) end,load_forest_skxy=function() forest=true end,log=function() end,game={add_funds=function(_,n) money=money+n end},apply_object_edits=function(_,edits,meshes) calls=calls+1;assert(edits[1].value=='asset:office' and #meshes.office.vertices==6) end}
local register=(function()\n'''+script+'''\nend)();register(api)
for _,fn in ipairs(callbacks['map.ready']) do fn({}) end
assert(calls==1 and forest and money==17)
''')
        for file,data in before.items():
            if file.name!='custom-map.json' and file != self.folder/self.doc.manifest['terrain']['source']['file'] and file != self.folder/'Vegetation/Generated/forest.skxy': self.assertEqual(file.read_bytes(),data)
        self.assertEqual(obj.read_bytes(),OBJ);self.assertEqual(png.read_bytes(),before[self.folder/self.doc.manifest['build']['heightmap']['file']])
        self.assertEqual(editor.EditorProject(self.folder).object_edits,[edit])
        with contextlib.redirect_stdout(io.StringIO()): projects.build(self.folder)
        self.assertEqual(first,path.read_bytes())
        oldmanifest=(self.folder/'custom-map.json').read_bytes();oldscript=(self.folder/a.GENERATED_SCRIPT).read_bytes()
        (self.folder/'Triggers/triggers.json').write_text('{"version":1,"triggers":[{}]}')
        with self.assertRaises(ManifestError): projects.build(self.folder)
        self.assertEqual(first,path.read_bytes());self.assertEqual(oldmanifest,(self.folder/'custom-map.json').read_bytes());self.assertEqual(oldscript,(self.folder/a.GENERATED_SCRIPT).read_bytes())
    def test_csv_validation_and_source_overwrite_guard(self):
        edit={'object':a.OBJECTS[0]['class'],'field':'BaseCost','type':'integer','value':500};self.assertEqual(a.parse_edits(a.csv_bytes([edit])),[edit])
        for change in ({'value':True},{'value':2147483648},{'field':'a.b.c'},{'object':'../escape'},{'type':'model','field':'CrowdISM.StaticMesh','value':False}):
            with self.assertRaises(ManifestError): a.parse_edits(a.csv_bytes([{**edit,**change}]))
        edit.update(field='MeshComponent.StaticMesh',type='model',value='asset:game');resolved=a.parse_edits(a.csv_bytes([edit]),{'game':{'kind':'game','path':'/Game/Test/Mesh.Mesh'}});self.assertEqual(resolved[0]['value'],'/Game/Test/Mesh.Mesh')
        self.doc.queue_authoring('objects',[]);self.doc.save()
        with self.assertRaisesRegex(ManifestError,'overwrite'): projects.build(self.folder,self.folder/'Objects/overrides.csv')

    def test_instance_csv_build_identity_and_delete_undo(self):
        cls=a.OBJECTS[0]['class']
        scene={'version':1,'objects':[{'id':'office','class':cls,'kind':'building','name':'Ticket Office','position':[0,0]},
            {'id':'other','class':cls,'kind':'building','name':'Custom office','position':[80,0]}]}
        self.doc.change_scene(scene)
        self.doc.change_instance_property('office','BaseCost','integer',123,500)
        inherited={'object':cls,'field':'BaseCost','type':'integer','value':999}
        self.doc.queue_authoring('objects',self.doc.object_edits+[inherited]);self.doc.save()
        self.assertEqual(a.parse_edits(a.csv_bytes(self.doc.object_edits)),sorted(self.doc.object_edits,key=lambda row:(row['object'],row.get('instance',''),row['field'])))
        self.assertEqual(a.compile_scene(scene,self.doc.manifest)[0]['name'],'')
        with contextlib.redirect_stdout(io.StringIO()): path,_=projects.build(self.folder)
        with zipfile.ZipFile(path) as package:
            script=package.read(a.GENERATED_SCRIPT).decode();self.assertIn('["instance"]={',script);self.assertIn('123',script)
        self.doc.change_scene({**scene,'objects':scene['objects'][1:]})
        self.assertEqual(self.doc.object_edits,[inherited]);self.doc.undo();self.assertEqual(len(self.doc.object_edits),2)
        self.doc.redo();self.assertEqual(self.doc.object_edits,[inherited])
        for value in ['../office','Office','a b']:
            with self.assertRaises(ManifestError): a.parse_edits(a.csv_bytes([{**inherited,'instance':value}]))
        self.doc.queue_authoring('objects',[{**inherited,'instance':'missing'}]);self.doc.save()
        with self.assertRaisesRegex(ManifestError,'instance is missing'): projects.build(self.folder)

if __name__=='__main__': unittest.main()
