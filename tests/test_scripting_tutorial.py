"""Exercise the tutorial's playable evaluator, including native-save restoration."""
from pathlib import Path
import json
import shutil
import subprocess
import unittest
from tools import skieo_authoring as authoring


class ScriptingTutorialTests(unittest.TestCase):
    def test_real_super_saint_bernard_initializes_after_its_graph_configuration(self):
        interpreter = shutil.which('lua5.4') or shutil.which('lua')
        if not interpreter: self.skipTest('Lua interpreter unavailable')
        folder = Path('mod/SkiEO-SuperSaintBernard')
        manifest = json.loads((folder / 'custom-map.json').read_text())
        generated = {}
        authoring.prepare(folder, manifest, generated)
        source = generated[authoring.GENERATED_SCRIPT].decode()
        script = '''package.path='mod/SkiEO-SuperSaintBernard/Scripts/?.lua;mod/SkiEO-CustomMaps/Scripts/?.lua;'..package.path
local register=(function()\n''' + source + '''\nend)()
local callbacks,options,state,scenario,placed,tick={}
local api={game={}}
function api:on(name,fn) callbacks[name]=callbacks[name] or {};table.insert(callbacks[name],fn) end
function api:state(defaults) state=defaults;return state end
function api:read_asset(name) local f=assert(io.open('mod/SkiEO-SuperSaintBernard/'..name));local s=f:read('*a');f:close();return s end
function api:scenario(value) scenario=value end
function api:building_properties() end
function api:resort_panel() end
function api:every(ms,fn) assert(ms==1000);tick=fn end
function api.game:configure(value)
    assert(not options,'scenario configured twice');options=value
    assert(value.currency=='CHF' and value.start_year==2003 and value.starting_balance==250000 and value.ticket_price==38)
    assert(value.costs==require('station').costs and value.class_costs==require('station').class_costs)
    assert(value.loans==require('finance').loans and value.track_lift_rides)
end
function api.game:place_resort(objects,trails)
    assert(options,'resort placement preceded configuration');placed=true
    assert(#objects==7 and #trails==4)
end
function api:place_objects(objects)
    assert(placed,'furniture placement preceded the resort')
    assert(#objects==14)
    for _,object in ipairs(objects) do
        assert(object.kind=='decoration' and object.class:find('/Blueprints/Decorations/',1,true))
    end
end
function api.game:snapshot()
    assert(options and placed,'first snapshot preceded scenario initialization')
    return {year=2003,month=11,day=1,months=16,fiscal_year=1,balance=250000,revenue=0,days_per_month=30,lift_rides={}}
end
function api.game:set_hub_names() end
function api.game:set_weather(weather,temp) assert(weather>=0 and weather<=3 and type(temp)=='number') end
function api.game:placeables() return {{id='decorative-bench',class='/Game/Blueprints/Decorations/BP_ParkBench.BP_ParkBench_C'}} end
function api.game:set_installation() error('decoration was charged as an installation') end
register(api);assert(not options,'configuration did not wait for map.ready')
for _,fn in ipairs(callbacks['map.ready']) do fn({restored=false}) end
assert(placed and tick and state.status=='active' and state.maintenance_paid==0)
assert(scenario.title=='Super Saint-Bernard — The Reprieve' and #scenario.objectives==4)
tick();assert(state.maintenance_paid==0,'same-calendar tick charged maintenance')
assert(not state.assets['decorative-bench'],'decoration acquired an installation condition')
'''
        result = subprocess.run([interpreter, '-'], input=script, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_first_season_checks_deadline_cash_and_terminal_saved_results(self):
        interpreter = shutil.which('lua5.4') or shutil.which('lua')
        if not interpreter: self.skipTest('Lua interpreter unavailable')
        source = Path('repository/web/public/tutorials/scripts/files/first-season.lua').read_text()
        script = '''local initialize=(function()\n''' + source + '''\nend)()
local function session(saved, balance, year, month)
    local now={balance=balance,year=year,month=month}
    local state,definition,ready,tick
    local api={game={snapshot=function() return now end},
        state=function(_,defaults) state=saved or defaults;return state end,
        scenario=function(_,value) definition=value end,
        on=function(_,name,fn) assert(name=='map.ready');ready=fn end,
        every=function(_,ms,fn) assert(ms==1000);tick=fn end}
    initialize(api);ready()
    assert(definition.title=='My first season' and #definition.objectives==2)
    return state,definition,now,tick
end
local state,definition,now,tick=session(nil,250000,2003,11)
assert(state.status=='active' and state.balance==250000)
tick();assert(state.status=='active','unchanged paused calendar advanced the deadline')
now.year,now.month,now.balance=2004,3,120000;tick();assert(state.status=='active')
now.month=4;tick();assert(state.status=='completed')
assert(definition.objectives[1].progress().fraction==1 and definition.objectives[2].progress().fraction==1)
now.balance=-1;tick();assert(state.status=='completed','terminal victory changed')
local restored=session(state,90000,2004,4)
assert(restored==state and restored.balance==90000 and restored.status=='completed','saved state was reset')
local broke=session(nil,-1,2003,12);assert(broke.status=='failed','negative cash did not fail immediately')
local short=session(nil,99999,2004,4);assert(short.status=='failed','deadline accepted insufficient reserve')
local enough=session(nil,100000,2004,4);assert(enough.status=='completed','exact reserve was rejected')
local late=session(nil,100000,2005,1);assert(late.status=='completed','deadline was only tested in April')
local failure=session({status='failed'},250000,2004,4);assert(failure.status=='failed','restoring revived a failed scenario')
'''
        result = subprocess.run([interpreter, '-'], input=script, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
