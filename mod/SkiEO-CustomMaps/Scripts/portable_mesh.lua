-- Small static meshes made in Blender, with a shared palette texture. SKPM is
-- deliberately data-only: no UObject names, bytecode or native pointers.
local Mesh={}
local function finite(x) return type(x)=='number' and x==x and math.abs(x)<1e7 end
function Mesh.decode(bytes)
    assert(type(bytes)=='string' and #bytes>=16 and #bytes<=16*1024*1024,'Invalid SKPM size')
    local magic,version,nv,ni,offset=string.unpack('<c4I4I4I4',bytes)
    assert(magic=='SKPM' and version==1 and nv>=3 and nv<=150000 and ni>=3
        and ni<=450000 and ni%3==0 and #bytes==16+nv*32+ni*4,'Invalid SKPM header')
    local mesh={vertices={},normals={},uv={},triangles={}}
    for i=1,nv do
        local x,y,z,nx,ny,nz,u,v
        x,y,z,nx,ny,nz,u,v,offset=string.unpack('<ffffffff',bytes,offset)
        for _,n in ipairs({x,y,z,nx,ny,nz,u,v}) do assert(finite(n),'Invalid SKPM vertex') end
        assert(nx*nx+ny*ny+nz*nz>.5 and nx*nx+ny*ny+nz*nz<1.5,'Invalid SKPM normal')
        mesh.vertices[i]={X=x,Y=y,Z=z};mesh.normals[i]={X=nx,Y=ny,Z=nz};mesh.uv[i]={X=u,Y=v}
    end
    for i=1,ni do
        local n;n,offset=string.unpack('<I4',bytes,offset);assert(n<nv,'Invalid SKPM triangle');mesh.triangles[i]=n
    end
    return mesh
end
function Mesh.transform(p,yaw,scale)
    local a=(yaw or 0)*math.pi/360
    return {Translation={X=p.x or p.X or p[1],Y=p.y or p.Y or p[2],Z=p.z or p.Z or p[3]},
        Rotation={X=0,Y=0,Z=math.sin(a),W=math.cos(a)},Scale3D=scale or {X=1,Y=1,Z=1}}
end
function Mesh.load(path)
    local o=StaticFindObject(path);if not o or not o:IsValid() then o=LoadAsset(path) end
    assert(o and o:IsValid(),'Surface lift resource unavailable: '..path);return o
end
function Mesh.material(api,path)
    local UE=require('UEHelpers');local retain=require('native_terrain').retain_texture
    local bytes=api:read_asset(path);require('textures').png_size(bytes)
    local directory=debug.getinfo(1,'S').source:match('^@(.*[/\\])[^/\\]+$')
    local file=directory..'surface-lift-palette.png'
    local f=assert(io.open(file,'wb'));f:write(bytes);f:close()
    local ok,texture=pcall(function()
        return Mesh.load('/Script/Engine.Default__KismetRenderingLibrary'):ImportFileAsTexture2D(UE.GetWorld(),file)
    end)
    os.remove(file);assert(ok and texture and texture:IsValid(),'Could not import lift palette')
    local base=Mesh.load('/Game/Materials/M_Prop_albtex_Snowless.M_Prop_albtex_Snowless')
    retain(texture);retain(base)
    local material=Mesh.load('/Script/Engine.Default__KismetMaterialLibrary'):CreateDynamicMaterialInstance(
        UE.GetWorld(),base,UE.FindOrAddFName('SurfaceLiftPalette'),0)
    retain(material);material:SetTextureParameterValue(UE.FindOrAddFName('Albedo'),texture)
    return material
end
function Mesh.actor()
    local UE=require('UEHelpers');local game=UE.GetGameplayStatics()
    local t=Mesh.transform({0,0,0})
    local a=game:BeginDeferredActorSpawnFromClass(UE.GetWorld(),Mesh.load('/Script/Engine.Actor'),t,1,nil,0)
    assert(a and a:IsValid(),'Could not create lift model actor')
    a=game:FinishSpawningActor(a,t,0);a:SetActorEnableCollision(false)
    return a
end
function Mesh.component(actor,model,material,p,yaw,scale)
    local c=actor:AddComponentByClass(Mesh.load('/Script/ProceduralMeshComponent.ProceduralMeshComponent'),
        false,Mesh.transform({0,0,0}),false)
    assert(c and c:IsValid(),'Could not create lift model mesh')
    c:SetMobility(2);c:SetCollisionEnabled(0)
    -- Every piece is positioned in world space. A mirrored, vertically scaled
    -- station can become the actor root; inheriting it shears inclined wheels.
    c:SetAbsolute(true,true,true)
    c:CreateMeshSection(0,model.vertices,model.triangles,model.normals,model.uv,{},{},false)
    c:SetMaterial(0,material)
    c:K2_SetWorldTransform(Mesh.transform(p or {0,0,0},yaw,scale),false,{},true)
    return c
end
return Mesh
