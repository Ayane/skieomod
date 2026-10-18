package.path='mod/SkiEO-CustomMaps/Scripts/?.lua;'..package.path
local world={IsValid=function() return true end}
local actors={}
local gameplay={IsValid=function() return true end,
    GetAllActorsOfClass=function(_,w,class,out)
        assert(w==world and class.name=='/Script/SkiResortSimulator.CrowdRenderingActor')
        for _,actor in ipairs(actors) do out[#out+1]={get=function() return actor end} end
    end}
package.preload.UEHelpers=function() return {
    GetWorld=function() return world end,GetGameplayStatics=function() return gameplay end,
} end
StaticFindObject=function(path) return {name=path,IsValid=function() return true end} end
local Terrain=require('terrain')
Terrain.active={runtime={}}
Terrain.height_at=function() return 1000 end
local updated=0
local function actor(destroyed)
    local component={IsValid=function() return true end,GetInstanceCount=function() return 1 end,
        GetInstanceTransform=function(_,index,out,world_space)
            assert(index==0 and world_space)
            out.Rotation={X=0,Y=0,Z=0,W=1}
            out.Translation={X=10,Y=20,Z=100}
            out.Scale3D={X=1,Y=1,Z=1}
            return true
        end,
        UpdateInstanceTransform=function(_,index,transform,world_space,dirty,teleport)
            assert(index==0 and transform.Translation.Z==1162)
            assert(world_space and dirty and teleport);updated=updated+1
        end}
    return {IsValid=function() return true end,IsActorBeingDestroyed=function() return destroyed end,
        CrowdISM=component}
end
actors={actor(false),actor(false),actor(true)}
assert(Terrain.align_people_rendering()==2 and updated==2,'consolidated staff renderer was skipped')
actors={actor(false),actor(false),actor(false),actor(false)}
assert(Terrain.align_people_rendering()==4 and updated==6,'legacy per-role renderers were skipped')
Terrain.active=nil
assert(Terrain.align_people_rendering()==0 and updated==6,'inactive map was modified')
print('Crowd rendering: current-world actors, consolidated/legacy staff, destroyed actors and inactive maps OK')
