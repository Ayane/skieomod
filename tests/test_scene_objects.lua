package.path='mod/SkiEO-CustomMaps/Scripts/?.lua;'..package.path
local world={IsValid=function() return true end,GetAddress=function() return 1 end}
local calls,actors={},{}
local function array(values)
    return {ForEach=function(_,fn) for i,v in ipairs(values) do fn(i,{get=function() return v end}) end end}
end
local prior={IsValid=function() return true end,GetAddress=function() return 99 end}
local values={Buildings=array({prior}),Lifts=array({}),Snowblowers=array({})}
local registry=setmetatable({IsValid=function() return true end,GetFullName=function() return 'Registry World' end,GetWorld=function() return world end},
    {__index=function(_,key) return values[key] end,__newindex=function(_,key,v) values[key]=array(v) end})
local function actor(kind)
    local o={bIsPreview=false,IsValid=function(self) return not self.dead end,GetAddress=function() return #actors+1 end}
    local address=#actors+1;o.GetAddress=function() return address end
    o.PlaceableComponent={GenerateNewId=function() calls[#calls+1]='id' end}
    o.IsA=function(_,path) return path=='/Script/SkiResortSimulator.PlaceableActor' or path=='/Script/SkiResortSimulator.'..(kind=='lift' and 'LiftActor' or 'BuildingActor') end
    o.SetPreviewMode=function(_,a,b) assert(a and b);calls[#calls+1]='preview' end
    o.SetInstanceName=function(_,name) assert(name=='Office' or name=='Lift') end
    o.Initialize=function(self,bottom,top) assert(bottom.Z==154 and top.Z==174);assert(self.HubId==nil);calls[#calls+1]='initialize' end
    o.GenerateTowers=function(self) assert(self.HubId.A==1);calls[#calls+1]='towers' end
    o.Finalize=function() calls[#calls+1]='finalize' end
    o.FinalizePlacement=function(self) self.bIsPreview=false;calls[#calls+1]='placement' end
    o.ApplyVariant=function(self,value)
        assert(self.bIsPreview,'variant applied after native finalization')
        self.VariantId={ToString=function() return value end};calls[#calls+1]='variant'
    end
    o.K2_DestroyActor=function(self) self.dead=true end
    return o
end
local statics={BeginDeferredActorSpawnFromClass=function(_,w,cls,transform,a,b,c)
    assert(w==world and transform.Translation.Z==154 and a==1 and b==nil and c==0);calls[#calls+1]='begin'
    local o=actor(cls.kind);actors[#actors+1]=o;return o
end,FinishSpawningActor=function(_,o) assert(o.bIsPreview);calls[#calls+1]='finish';return o end}
package.preload.UEHelpers=function() return {GetWorld=function() return world end,GetGameplayStatics=function() return statics end,FindOrAddFName=function(v) return v end} end
package.preload.terrain=function() return {surface_height_at=function(x,y) return 100+x+y end} end
LoadAsset=function(path) return {IsValid=function() return true end,kind=path=='lift' and 'lift' or 'building'} end
FindAllOf=function(kind) return kind=='PlaceableRegistrySubsystem' and {registry} or {} end
FText=function(value) return value end
local Scene=require('scene_objects');local callbacks={}
local api={on=function(_,name,fn) callbacks[name]=fn end,log=function() end}
local definition={id='office',name='Office',class='office',kind='building',position_cm={20,30},offset_cm=4,yaw=90,guid={A=11},hub={A=1}}
Scene.place(api,{definition});assert(#actors==1 and not actors[1].bIsPreview and actors[1].PlaceableComponent.PlaceableId.A==11)
local n=0;registry.Buildings:ForEach(function() n=n+1 end);assert(n==2,'Existing native buildings must remain registered')
callbacks['map.unloading']();assert(actors[1].dead);n=0;registry.Buildings:ForEach(function(_,o) assert(o:get()==prior);n=n+1 end);assert(n==1)
api._restoring=true;Scene.place(api,{definition});assert(#actors==1);api._restoring=false
calls={};definition.name='Lift';definition.class='lift';definition.kind='lift';definition.end_position_cm={20,50};definition.top_hub={A=2}
Scene.place(api,{definition});assert(table.concat(calls,',')=='begin,finish,preview,id,initialize,towers,finalize,placement')
callbacks['map.unloading']();assert(actors[2].dead)
calls={};definition.name='Office';definition.class='office';definition.kind='decoration';definition.variant='Expert'
Scene.place(api,{definition})
assert(actors[3].VariantId:ToString()=='Expert' and table.concat(calls,',')=='begin,finish,preview,id,variant,placement')
callbacks['map.unloading']()
print('Scene grounding, native lift lifecycle, registry preservation, restoration and cleanup passed')
