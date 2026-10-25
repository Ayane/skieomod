package.path = 'mod/SkiEO-CustomMaps/Scripts/?.lua;' .. package.path
local world = {IsValid=function() return true end,GetAddress=function() return 1 end}
local source_queries, outside = 0, false
package.preload.terrain=function() return {surface_height_at=function(x)
    source_queries=source_queries+1
    if outside then return nil end
    return x/2
end} end
local valid_object={IsValid=function() return true end}
local actors, callbacks, seen = {}, {}, {}
local inserted, copy_work, refreshes, fail_refresh = 0, 0, 0, false
local expected_y, native_manager
local cleared_indices={}
local draw_instancing=1
local system={IsValid=function() return true end,
    GetConsoleVariableIntValue=function(_,name) assert(name=='r.MeshDrawCommands.DynamicInstancing');return draw_instancing end,
    ExecuteConsoleCommand=function(_,w,command)
        assert(w==world);draw_instancing=assert(tonumber(command:match(' (%d+)$')))
    end}
local gameplay={BeginDeferredActorSpawnFromClass=function()
    local actor={destroyed=false,components={}}
    function actor:IsValid() return not self.destroyed end
    function actor:GetWorld() return world end
    function actor:SetActorHiddenInGame() end
    function actor:K2_DestroyActor() self.destroyed=true end
    function actor:AddComponentByClass()
        local component={count=0}
        function component:IsValid() return not actor.destroyed end
        function component:SetStaticMesh() return true end
        function component:SetCollisionEnabled() end
        function component:SetCullDistances() end
        function component:AddInstances(transforms,indices,world_space,navigation)
            assert(not indices and world_space and not navigation)
            assert(#transforms<=512,'native insertion exceeded callback budget')
            self.count=self.count+#transforms
            assert(self.count<=8192,'native render buffer grew beyond its bounded capacity')
            copy_work=copy_work+self.count
            for _,t in ipairs(transforms) do
                local x=t.Translation.X
                assert(not seen[x],'duplicate source point after partitioning')
                assert(t.Translation.Z==x/2,'tree root differs from the rendered surface')
                if expected_y then
                    assert(t.Translation.Y==expected_y,'JSON metre conversion changed Y')
                    assert(t.Scale3D.X==1 and t.Scale3D.Y==1 and t.Scale3D.Z==1)
                end
                seen[x]=true;inserted=inserted+1
                self.first=self.first or t
            end
        end
        function component:GetInstanceTransform(_,output)
            if fail_refresh then return false end
            for k,v in pairs(self.first) do output[k]=v end
            return true
        end
        function component:UpdateInstanceTransform(index,transform,_,dirty)
            if dirty then refreshes=refreshes+1;copy_work=copy_work+self.count
            else
                assert(index>=0 and index<self.count,'clearing changed an invalid native slot')
                assert(transform.Scale3D.X==0,'cleared tree remains visible')
                cleared_indices[#cleared_indices+1]=index
            end
            if index==0 then self.first=transform end
            return true
        end
        self.components[#self.components+1]=component
        return component
    end
    actors[#actors+1]=actor
    return actor
end,FinishSpawningActor=function(_,actor) return actor end}
gameplay.IsValid=function() return true end
package.preload.UEHelpers=function() return {
    GetWorld=function() return world end,GetGameplayStatics=function() return gameplay end,
    GetKismetSystemLibrary=function() return system end,GetPlayerController=function() return valid_object end,
} end
StaticFindObject=function() return valid_object end
FindAllOf=function(class) return class=='ObstacleDataManager'and native_manager and {native_manager}or{} end
ExecuteInGameThread=function(fn) fn() end
local api={}
function api:after(delay,callback) assert(delay>0);callbacks[#callbacks+1]=callback end
function api:every(_,callback) self.visibility=callback end
function api:log() end
function api:loading_progress(_,fraction) assert(fraction==fraction and fraction>=0.95 and fraction<=0.99) end
local Vegetation=require('vegetation')
local function source(count)
    local records={string.pack('<c4I4I4','SKXY',1,count)}
    for i=1,count do records[#records+1]=string.pack('<ff',i,0) end
    return table.concat(records)
end
local function tick()
    local before=source_queries
    assert(#callbacks>0)
    table.remove(callbacks,1)()
    assert(source_queries-before<=512,'off-terrain scan exceeded callback budget')
end
local function drain() while #callbacks>0 do tick() end end
local completed=0
Vegetation.load_skxy(source(255667),api,{batch_size=512},function(message,count,total)
    assert(not message and count==255667 and total==255667, tostring(message));completed=completed+1
end)
assert(inserted==0,'insertion did not yield after map.ready')
drain()
assert(completed==1 and inserted==255667)
assert(draw_instancing==0,'portable forest retained unstable draw-command merging')
assert(#Vegetation.components==32 and refreshes==32)
assert(copy_work<3000000,'forest repeatedly copied the full map-sized native buffer')
for i=1,255667 do assert(seen[i],'source point dropped at component boundary') end

-- A wholly outside source must still yield regularly and complete.
outside=true
Vegetation.load_skxy(source(2049),api,{batch_size=512},function(message,count,total)
    assert(not message and count==0 and total==2049);completed=completed+1
end)
assert(actors[1].destroyed,'previous forest retained during world replacement')
drain();assert(completed==2)
outside=false

-- Travel cancels pending insertion and destroys every component's owner.
seen={};inserted=0
Vegetation.load_skxy(source(20000),api,{},function() error('cancelled load completed') end)
tick();local old=Vegetation.actor;local count=inserted
Vegetation.unload();drain()
assert(draw_instancing==1,'unloading did not restore the original render setting')
assert(old.destroyed and inserted==count and #Vegetation.components==0)
assert(api.visibility()==false,'old visibility timer survived travel')

-- A render refresh failure releases the partial forest and completes the hold
-- with an error, rather than leaving Creating Forest stuck indefinitely.
seen={};fail_refresh=true
Vegetation.load_skxy(source(65),api,{},function(message)
    assert(message:find('first vegetation transform',1,true));completed=completed+1
end)
drain();assert(completed==3 and actors[#actors].destroyed)
fail_refresh=false
Vegetation.load_skxy(source(0),api,{},function(message,count,total)
    assert(not message and count==0 and total==0);completed=completed+1
end)
drain();assert(completed==4)

-- The runtime accepts only compiled SKXY; malformed binary data is rejected
-- before replacing the renderer or scheduling insertion.
assert(Vegetation.load_json == nil and Vegetation.parse_json == nil)
local previous=Vegetation.actor
for _,bytes in ipairs({'[]',string.pack('<c4I4I4','SKXY',2,0),source(1):sub(1,-2),string.pack('<c4I4I4','SKXY',1,1000001)}) do
    assert(not pcall(Vegetation.load_skxy,bytes,api))
    assert(Vegetation.actor==previous and #callbacks==0)
end
Vegetation.unload()
draw_instancing=0;seen={}
Vegetation.load_skxy(source(1),api,{},function(message) assert(not message) end)
drain();Vegetation.unload();assert(draw_instancing==0,'user-disabled optimization was unexpectedly enabled')

-- The native save owns the cleared zones. Apply existing zones before the
-- load completes, then observe new zones without shifting renderer indices.
local zones={}
local native_zones=setmetatable({GetArrayNum=function()return #zones end},{__index=zones})
native_manager={IsValid=function()return true end,GetWorld=function()return world end,ClearedZones=native_zones}
local function cleared_zone(x,r)
    return {Center={X=x,Y=0},Radius=r,EndOffset={X=0,Y=0},Outline={ForEach=function()end}}
end
zones[1]=cleared_zone(500,1)
seen={};cleared_indices={};local settled=false
Vegetation.load_skxy(source(3000),api,{},function(message)assert(not message,message);settled=true end)
assert(not settled);drain()
assert(settled and #cleared_indices==3,'saved clearing was not applied before load completion')
zones[2]=cleared_zone(2999,0)
api.visibility();drain()
assert(#cleared_indices==4 and cleared_indices[4]==2998,'live native clearing missed the stable instance slot')
api.visibility();drain();assert(#cleared_indices==4,'unchanged zones cleared trees twice')
Vegetation.unload();seen={};cleared_indices={}
Vegetation.load_skxy(source(3000),api,{},function(message)assert(not message,message)end)
drain();assert(#cleared_indices==4,'trees regrew when the saved forest was reconstructed')
Vegetation.unload()
print('Portable forest: SKXY only, grounding, bounded buffers, source validation and cancellation OK')
