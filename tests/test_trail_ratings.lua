package.path='mod/SkiEO-CustomMaps/Scripts/?.lua;'..package.path
local Json=require('json')
local world={IsValid=function()return true end,GetAddress=function()return 1 end}
package.preload.UEHelpers=function()return {GetWorld=function()return world end}end
local ribbons=0
package.preload.terrain=function()return {active=true,actor=world,
    rebuild_trail_visuals=function(preserve)assert(preserve);ribbons=ribbons+1 end}end
local function object(fields)
    fields.IsValid=function()return true end
    fields.GetFullName=fields.GetFullName or function()return 'Live subsystem' end
    return fields
end
local refreshed,labels=0,0
local map=object({RegisteredTrails={ForEach=function(_,f)
    for _,id in ipairs({4,9}) do f({get=function()return id end}) end
end}})
local live=object({GetWorld=function()return world end,TrailMapSubsystem=map,
    OnTrailRegistered=function(_,id)assert(id==4 or id==9);refreshed=refreshed+1 end,
    RefreshLabels=function()labels=labels+1 end})
local foreign=object({GetWorld=function()return {IsValid=function()return true end,GetAddress=function()return 2 end}end,
    OnTrailRegistered=function()error('foreign world touched')end})
local cdo=object({GetFullName=function()return 'Default__TrailVisualizationSubsystem' end})
FindAllOf=function(name)assert(name=='TrailVisualizationSubsystem');return {cdo,foreign,live}end
local root='mod/SkiEO-CustomMaps/Scripts/'
local calls,last,reject=0,nil,false
local capability_report={thresholds=true,style=true,colors=true,detail='checked',addresses={color=1234}}
local loadlib=package.loadlib
package.loadlib=function(path,symbol)
    if symbol=='skieo_trail_ratings_capabilities' then
        assert(path==root..'skieo_trail_ratings.dll')
        return function()
            local f=assert(io.open(root..'native_trail_ratings.capabilities.json','wb'))
            f:write(Json.encode(capability_report));f:close()
        end
    end
    assert(path==root..'skieo_trail_ratings.dll' and symbol=='skieo_trail_ratings')
    return function()
        calls=calls+1
        local f=assert(io.open(root..'native_trail_ratings.job','rb'));local bytes=f:read('*a');f:close()
        assert(#bytes==52)
        local magic,version,enabled,style,count,a,b,c,mask,c0,c1,c2,c3=string.unpack('<c4I4I4i4I4fffI4I4I4I4I4',bytes)
        assert(magic=='SKRT' and version==2)
        last={enabled=enabled,style=style,count=count,degrees={a,b,c},mask=mask,colors={c0,c1,c2,c3}}
        f=assert(io.open(root..'native_trail_ratings.status','wb'));f:write(reject and 'error: unsupported native slope classification' or 'ok');f:close()
    end
end
local Ratings=require('trail_ratings')
local Api=require('api')
local function api(permissions)
    return Api.new({log=function()end,scenario_action=function(session,name,options)
        if name=='trail_rating_system' then return Ratings.set(session,options) end
        if name=='get_trail_rating_capabilities' then return Ratings.capabilities() end
        assert(name=='get_trail_rating_system');return Ratings.get(session)
    end},{id='test.ratings',script={permissions=permissions or {'gameplay'}}})
end
local a=api()
assert(a.game:get_trail_rating_system()==nil)
local config={style='european',thresholds_percent={25,40}}
local result=a.game:set_trail_rating_system(config)
assert(last.enabled==1 and last.style==2 and last.count==2 and last.degrees[3]==0)
assert(math.abs(last.degrees[1]-14.036243)<0.00001 and math.abs(last.degrees[2]-21.801409)<0.00001)
config.thresholds_percent[1]=1;result.style='japanese'
assert(a.game:get_trail_rating_system().style=='european' and a.game:get_trail_rating_system().thresholds_percent[1]==25)
assert(refreshed==2 and labels==1,'existing trail visuals were not refreshed')
assert(ribbons==1,'source terrain ribbons retained the old palette')
local before=calls
for _,bad in ipairs({{}, {style='austria'}, {style=2}, {style=false}, {thresholds_percent={0,40}},
    {thresholds_percent={40,25}}, {thresholds_percent={25,25}}, {thresholds_percent={25}},
    {thresholds_degrees={10,20,30,40}}, {thresholds_degrees={10,91}},
    {thresholds_degrees={0/0,30}}, {thresholds_percent={25,math.huge}},
    {thresholds_degrees={10,20},thresholds_percent={25,40}},
    {thresholds_degrees={[1]=10,[2]=20,typo=30}}, {palette='european'},
    {style='european',thresholds_percent=false}, {style='european',thresholds_degrees=10},
    {colors=false}, {colors={}}, {colors={easy='#FF0000'}}, {colors={'#FF0000'}},
    {colors={beginner='red'}}, {colors={beginner='#fff'}}, {colors={beginner='#FF0000FF'}},
    {colors={beginner='#GG0000'}}, {colors={beginner=0xFF0000}},
    {colors={beginner='#FF0000\n'}}, {colors={beginner=false}}}) do
    assert(not pcall(a.game.set_trail_rating_system,a.game,bad),'invalid rating options accepted')
end
assert(calls==before,'invalid configuration reached native code')
local b=api()
assert(not pcall(b.game.set_trail_rating_system,b.game,{style='japanese'}),'another map stole the active policy')
reject=true
assert(not pcall(a.game.set_trail_rating_system,a.game,{style='japanese'}))
assert(a.game:get_trail_rating_system().style=='european','failed native update changed API state')
reject=false
a.game:set_trail_rating_system({thresholds_degrees={12,25,35}})
assert(last.style==-1 and last.count==3 and last.degrees[3]==35)
a:_emit('map.ready');assert(labels==3)
a:_stop();assert(last.enabled==0 and last.style==-1 and last.count==0)
assert(a.game:get_trail_rating_system()==nil)
b.game:set_trail_rating_system({style='japanese'});assert(last.style==3 and last.count==0)
b.game:set_trail_rating_system(nil);assert(last.enabled==0)
b.game:set_trail_rating_system({style='north_american'});assert(last.style==1)
b:_stop();assert(last.enabled==0,'explicit reset prevented later cleanup')
local denied=api({})
assert(not pcall(denied.game.set_trail_rating_system,denied.game,{style='european'}))
assert(not pcall(denied.game.get_trail_rating_system,denied.game))
assert(not pcall(denied.game.get_trail_rating_capabilities,denied.game))
local scoped=api();scoped._session=a
scoped.game:set_trail_rating_system({style='european'})
assert(a.game:get_trail_rating_system().style=='european','mapmod lost session ownership')
a:_stop();assert(last.enabled==0)
local c=api()
local palette={beginner='#0080fF',intermediate='#ff0000',expert='#000000',extreme='#FF8000'}
local custom=c.game:set_trail_rating_system({colors=palette})
assert(last.style==-1 and last.count==0 and last.mask==15)
assert(last.colors[1]==0x0080FF and last.colors[2]==0xFF0000 and last.colors[3]==0 and last.colors[4]==0xFF8000)
palette.beginner='#FFFFFF';custom.colors.expert='#FFFFFF'
local saved=c.game:get_trail_rating_system();saved.colors.intermediate='#FFFFFF'
assert(c.game:get_trail_rating_system().colors.beginner=='#0080fF')
assert(c.game:get_trail_rating_system().colors.expert=='#000000')
assert(c.game:get_trail_rating_system().colors.intermediate=='#ff0000','palette was not copied deeply')
c.game:set_trail_rating_system({style='japanese',colors={expert='#8844CC'},thresholds_degrees={10,20,30}})
assert(last.style==3 and last.count==3 and last.mask==4 and last.colors[3]==0x8844CC)
assert(last.colors[1]==0 and last.colors[2]==0 and last.colors[4]==0,'partial palette leaked previous colors')
c.game:set_trail_rating_system({style='european'});assert(last.mask==0)
c.game:set_trail_rating_system({colors={beginner='#FFFFFF'}})
c:_stop();assert(last.enabled==0 and last.mask==0,'custom colors leaked after map stop')
local before_calls=calls
local capabilities=c.game:get_trail_rating_capabilities()
assert(capabilities.thresholds and capabilities.style and capabilities.colors and not capabilities.addresses)
capabilities.colors=false
assert(c.game:get_trail_rating_capabilities().colors,'capability result was not copied')
capability_report={thresholds=false,style=true,colors=true}
assert(not c.game:get_trail_rating_capabilities().thresholds and c.game:get_trail_rating_capabilities().colors)
capability_report={thresholds='bad',style=true,colors=true}
assert(not c.game:get_trail_rating_capabilities().colors,'malformed native capability report was trusted')
package.loadlib=function()return nil,'helper missing' end
assert(not c.game:get_trail_rating_capabilities().style,'absent helper was reported as supported')
assert(calls==before_calls,'read-only capability probe changed native configuration')
package.loadlib=loadlib
os.remove(root..'native_trail_ratings.job');os.remove(root..'native_trail_ratings.status')
os.remove(root..'native_trail_ratings.capabilities.json')
print('Trail ratings: API permissions, units, colors, validation, native failure, refresh, ownership, mapmods and unload restoration OK')
