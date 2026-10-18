-- Cosmetic terrain outside the playable heightfield. No collision, navigation
-- or simulation samples are added. A stitched strip closes the visible seam.
local Heights,Mesh=require('heightmap'),require('terrain_mesh')
local Scenery={}
local function valid(o) return o and o:IsValid() end
local function finite(n) return type(n)=='number' and n==n and math.abs(n)<math.huge end
function Scenery.load(map)
    local def=(map.extensions or {})['community.skieo.scenery']
    if not def then return nil end
    local source=assert(def.source,'scenery source missing')
    local declared=false
    for _,path in ipairs((map.content or {}).assets or {}) do declared=declared or path==source.file end
    assert(declared,'scenery source must be declared in content.assets')
    assert(source.format=='r16le' or source.format=='r16be','unsupported scenery heightmap')
    for _,n in ipairs(source.vertices or {}) do assert(finite(n) and n%1==0 and n>=3 and n<=513,'invalid scenery dimensions') end
    assert(#source.vertices==2 and finite(source.spacing_meters) and source.spacing_meters>=10,'invalid scenery spacing')
    assert(finite(source.height_scale_meters) and source.height_scale_meters>0 and finite(source.height_offset_meters),'invalid scenery vertical encoding')
    for i=1,2 do assert(def.size_meters[i]==(source.vertices[i]-1)*source.spacing_meters,'scenery extent differs from its grid') end
    local state=Heights.load({terrain=def,__read=map.__read})
    state.runtime={sample_step=1,uv_tile_meters=100}
    state.sample_step=1
    state.definition=def
    return state
end
function Scenery.hole(background,playable)
    local spacing=background.spacing_cm
    local function lower(value,origin) return origin+(math.floor((value-origin)/spacing)-1)*spacing end
    local function upper(value,origin) return origin+(math.ceil((value-origin)/spacing)+1)*spacing end
    local bounds={lower(playable.origin_x,background.origin_x),lower(playable.origin_y,background.origin_y),
        upper(playable.origin_x+(playable.width-1)*playable.spacing_cm,background.origin_x),
        upper(playable.origin_y+(playable.height-1)*playable.spacing_cm,background.origin_y)}
    assert(bounds[1]>background.origin_x and bounds[2]>background.origin_y
        and bounds[3]<background.origin_x+(background.width-1)*spacing
        and bounds[4]<background.origin_y+(background.height-1)*spacing,'scenery must surround the playable map')
    return bounds
end
function Scenery.tile(state,hole,columns,rows,x,y)
    local vertices,triangles,normals,uvs=Mesh.build_tile(state,columns,rows,x,y,63,0,false)
    local filtered={}
    for i=1,#triangles,3 do
        local a,b,c=vertices[triangles[i]+1],vertices[triangles[i+1]+1],vertices[triangles[i+2]+1]
        local cx,cy=(a.X+b.X+c.X)/3,(a.Y+b.Y+c.Y)/3
        if cx<hole[1] or cx>hole[3] or cy<hole[2] or cy>hole[4] then
            for j=i,i+2 do filtered[#filtered+1]=triangles[j] end
        end
    end
    return vertices,filtered,normals,uvs
end
function Scenery.seam(background,playable,hole)
    local vertices,triangles,normals,uvs={},{},{},{}
    local x0,y0=playable.origin_x,playable.origin_y
    local x1,y1=x0+(playable.width-1)*playable.spacing_cm,y0+(playable.height-1)*playable.spacing_cm
    local inner={{x0,y0},{x1,y0},{x1,y1},{x0,y1}}
    local outer={{hole[1],hole[2]},{hole[3],hole[2]},{hole[3],hole[4]},{hole[1],hole[4]}}
    local function point(a,b,t) return a[1]+(b[1]-a[1])*t,a[2]+(b[2]-a[2])*t end
    local function vertex(x,y,z)
        vertices[#vertices+1]={X=x,Y=y,Z=assert(z)}
        normals[#normals+1]={X=0,Y=0,Z=1};uvs[#uvs+1]={X=x/10000,Y=y/10000}
    end
    local function triangle(a,b,c)
        local va,vb,vc=vertices[a+1],vertices[b+1],vertices[c+1]
        -- Unreal's upward terrain faces use clockwise winding in XY.
        if (vb.X-va.X)*(vc.Y-va.Y)-(vb.Y-va.Y)*(vc.X-va.X)>0 then b,c=c,b end
        triangles[#triangles+1]=a;triangles[#triangles+1]=b;triangles[#triangles+1]=c
    end
    for side=1,4 do
        local next_side=side%4+1
        local a,b,oa,ob=inner[side],inner[next_side],outer[side],outer[next_side]
        local il=math.abs(b[1]-a[1])+math.abs(b[2]-a[2])
        local ol=math.abs(ob[1]-oa[1])+math.abs(ob[2]-oa[2])
        local fractions={0,1}
        for i=1,math.floor(il/playable.spacing_cm)-1 do fractions[#fractions+1]=i*playable.spacing_cm/il end
        for i=1,math.floor(ol/background.spacing_cm)-1 do fractions[#fractions+1]=i*background.spacing_cm/ol end
        table.sort(fractions)
        local last=-1
        for _,t in ipairs(fractions) do
            if t-last>1e-9 then
                local ix,iy=point(a,b,t);local ox,oy=point(oa,ob,t)
                vertex(ix,iy,Mesh.height_at(playable,ix,iy))
                vertex(ox,oy,Heights.height_at(background,ox,oy))
                if last>=0 then local n=#vertices;triangle(n-4,n-3,n-2);triangle(n-3,n-1,n-2) end
                last=t
            end
        end
    end
    return vertices,triangles,normals,uvs
end
function Scenery.create(map,terrain,schedule,done,log)
    local ok,state=pcall(Scenery.load,map)
    if not ok then done(false,state);return end
    if not state then done(true);return end
    local ok,hole=pcall(Scenery.hole,state,terrain.active)
    if not ok then done(false,hole);return end
    local generation=terrain.generation
    local cls=StaticFindObject('/Script/ProceduralMeshComponent.ProceduralMeshComponent')
    local pose={Rotation={X=0,Y=0,Z=0,W=1},Translation={X=0,Y=0,Z=0},Scale3D={X=1,Y=1,Z=1}}
    local component=terrain.actor:AddComponentByClass(cls,false,pose,false)
    assert(valid(component),'could not create scenery component')
    component:SetCollisionEnabled(0)
    local material=LoadAsset(state.definition.material or '/Game/Materials/Backgrounds/M_Snow.M_Snow')
    assert(valid(material),'scenery material unavailable')
    local columns,rows=Mesh.sampled_indices(state.width,1),Mesh.sampled_indices(state.height,1)
    local tasks={}
    for y=1,#rows-1,63 do for x=1,#columns-1,63 do tasks[#tasks+1]={x,y} end end
    local index,section=1,0
    local function next_tile()
        if terrain.generation~=generation or not valid(component) then return end
        local task=tasks[index]
        local ok,message=pcall(function()
            local vertices,triangles,normals,uvs
            if task then vertices,triangles,normals,uvs=Scenery.tile(state,hole,columns,rows,task[1],task[2])
            else vertices,triangles,normals,uvs=Scenery.seam(state,terrain.active,hole) end
            if #triangles>0 then
                component:CreateMeshSection(section,vertices,triangles,normals,uvs,{},{},false)
                component:SetMaterial(section,material);section=section+1
            end
        end)
        if not ok then component:K2_DestroyComponent(terrain.actor);done(false,message);return end
        if not task then
            log(string.format('regional scenery: %d section(s), no collision, stitched playable perimeter',section))
            done(true);return
        end
        index=index+1
        if terrain.active.progress then terrain.active.progress('Building surrounding landscape',0.92+0.02*(index-1)/#tasks) end
        schedule(1,next_tile)
    end
    schedule(1,next_tile)
end
return Scenery
