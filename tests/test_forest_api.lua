package.path='mod/SkiEO-CustomMaps/Scripts/?.lua;'..package.path
local Api=require('api')
assert(Api.load_forest_json==nil, 'runtime still supports JSON forests')
local bytes=string.pack('<c4I4I4ff','SKXY',1,1,1000,-2000)
local calls,complete,finished=0,nil,{}
local host={log=function() end,load_forest_skxy=function(text,api,options,done)
    assert(text==bytes and options==nil)
    calls=calls+1;complete=done
end,loading_finished=function(_,success,message) finished[#finished+1]={success,message} end}
local map={id='test.forest',script={permissions={'gameplay'}},
    content={assets={'forest.skxy'}},__read=function(path) assert(path=='forest.skxy');return bytes end}
local api=Api.new(host,map)
assert(not pcall(api.load_forest_skxy,api,'../outside.skxy'))
assert(calls==0 and api._loading_pending==0)
api:load_forest_skxy('forest.skxy')
api:_terrain_ready()
assert(calls==1 and api._loading_pending==1 and #finished==0)
assert(not pcall(api.load_forest_skxy,api,'forest.skxy'),'concurrent forest replacement accepted')
complete();assert(finished[1][1] and api._loading_pending==0)
complete();assert(#finished==1,'completion ran twice')

local denied=Api.new(host,{id='test.denied',content=map.content,__read=map.__read})
assert(not pcall(denied.load_forest_skxy,denied,'forest.skxy') and calls==1)
local failing=Api.new({log=function() end,load_forest_skxy=function() error('invalid SKXY') end,
    loading_finished=host.loading_finished},map)
assert(not pcall(failing.load_forest_skxy,failing,'forest.skxy'))
assert(failing._loading_pending==0 and finished[2][1]==false and finished[2][2]:find('invalid SKXY',1,true))
local cancelled=Api.new(host,map)
cancelled:load_forest_skxy('forest.skxy');cancelled:_stop();complete()
assert(#finished==2,'old forest callback finished a new map load')

-- Execute ordinary sandboxed map and mapmod scripts through the real runtime.
-- Their assets stay scoped while holds and insertion timers use the map API.
package.preload.UEHelpers=function() return {} end
package.preload.terrain=function() return {unload=function() end} end
package.preload.catalog=function() return {} end
package.preload.loading=function() return {} end
local renderer_api,renderer_text
package.preload.vegetation=function() return {load_skxy=function(text,session,_,done)
    renderer_api,renderer_text,complete=session,text,done
end} end
ExecuteInGameThread=function() end
ExecuteWithDelay=function() end
local Runtime=require('runtime')
local function script_source()
    return [[assert(require==nil and io==nil)
        return function(api)
            api:on('map.ready',function() api:load_forest_skxy('forest.skxy') end)
        end]]
end
local source_map={id='test.map',metadata={name='Map',version='0.1.0'},
    script={entry='main.lua',permissions={'gameplay'}},content=map.content,__manifest_path='test-map',
    __read=function(path) if path=='main.lua' then return script_source() end;return bytes end}
assert(Runtime.start(source_map));Runtime.emit('map.ready')
assert(renderer_text==bytes and renderer_api==Runtime.active_api)
assert(Runtime.active_api._loading_pending==1)
complete();assert(Runtime.active_api._loading_pending==0)

local mod_bytes=string.pack('<c4I4I4ff','SKXY',1,1,3000,4000)
local dependency={id='test.mod',metadata={name='Mod',version='0.1.0'},runtime='map-api',
    script=source_map.script,content=map.content,__manifest_path='test-mod',
    __read=function(path) if path=='main.lua' then return script_source() end;return mod_bytes end}
Runtime.mods={dependency}
source_map.script=nil;source_map.dependencies={{id='test.mod',version='0.1.0'}}
assert(Runtime.start(source_map));Runtime.emit('map.ready')
assert(renderer_text==mod_bytes and renderer_api==Runtime.active_api,'mapmod lost asset or session scope')
assert(Runtime.active_api._loading_pending==1)
complete();assert(Runtime.active_api._loading_pending==0)
print('SKXY forest API: sandbox access, permissions, assets, loading holds, errors and mapmod scope OK')
