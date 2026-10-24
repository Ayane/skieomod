-- The CPU snow tiles miss narrow compressed tracks and local grading. Measure
-- the rendered terrain itself for ski contact. One small depth-only view
-- covers the nearest detailed passengers at 2 Hz. Readbacks
-- happen after the capture frame; the native bridge returns packed floats,
-- never one Lua UObject/table per pixel. No disk capture or UI focus is used.
local M=require('portable_mesh')
local P=require('surface_lift_pose_math')
local T=require('terrain')
local H=require('UEHelpers')
local Contact={}
local directory=debug.getinfo(1,'S').source:match('^@(.*[/\\])[^/\\]+$')
local loader,reader,library
local function prepare()
    if loader then return end
    reader=M.load('/Script/Engine.KismetRenderingLibrary:ReadRenderTargetRawPixelArea')
    local fields={WorldContextObject={0,'ObjectProperty'},TextureRenderTarget={8,'ObjectProperty'},
        MinX={16,'IntProperty'},MinY={20,'IntProperty'},MaxX={24,'IntProperty'},MaxY={28,'IntProperty'},
        bNormalize={32,'BoolProperty'},ReturnValue={40,'ArrayProperty'}}
    reader:ForEachProperty(function(p)
        local name=p:GetFName():ToString();local field=fields[name]
        assert(field and p:GetOffset_Internal()==field[1] and p:GetClass():GetFName():ToString()==field[2],
            'Changed rendered surface readback field: '..name)
        field.seen=true
    end)
    for name,field in pairs(fields)do assert(field.seen,'Missing rendered surface readback field: '..name)end
    library=M.load('/Script/Engine.Default__KismetRenderingLibrary')
    loader=assert(package.loadlib(directory..'skieo_surface_lifts.dll','skieo_surface_contact'))
end
local function create(side,width,interval)
    prepare()
    local a=M.actor();local c=a:AddComponentByClass(M.load('/Script/Engine.SceneCaptureComponent2D'),false,M.transform({0,0,0}),false)
    local rt=library:CreateRenderTarget2D(H.GetWorld(),side,side,9,{R=0,G=0,B=0,A=0},false,false)
    assert(rt and rt:IsValid(),'Could not allocate rendered surface contact target')
    c.TextureTarget=rt;c.CaptureSource=4;c.ProjectionType=1;c.OrthoWidth=width
    c.bAutoCalculateOrthoPlanes=false;c.bUpdateOrthoPlanes=false
    c.bCaptureEveryFrame=false;c.bCaptureOnMovement=false;c.PrimitiveRenderMode=2
    return {actor=a,component=c,rt=rt,side=side,width=width,interval=interval,next=0}
end
local function read(view)
    local f=assert(io.open(directory..'surface-contact.job','wb'))
    f:write(string.pack('<c4I4I4I4I8I8I8I8I8I8I8','SKSC',1,view.side,0,
        H.GetWorld():GetAddress(),library:GetAddress(),library:GetClass():GetAddress(),
        view.rt:GetAddress(),view.rt:GetClass():GetAddress(),reader:GetAddress(),reader:GetClass():GetAddress()))
    f:close();loader()
    f=assert(io.open(directory..'surface-contact.bin','rb'));local bytes=f:read('*a');f:close()
    assert(#bytes==view.side*view.side*4,'Rendered surface readback failed')
    view.bytes=bytes;view.eye=view.pending;view.pending=nil
end
local function tick(view,x,y,z,now,paused)
    if view.pending and now>=view.read_at then read(view);view.next=now+view.interval end
    local moved=not view.eye or (x-view.eye.X)^2+(y-view.eye.Y)^2>(view.width*.12)^2
    if view.pending or now<view.next or (paused and not moved)then return end
    local c=view.component
    -- Snow sections can be refined when a building or lift is constructed.
    c:ClearShowOnlyComponents();c:ShowOnlyComponent(T.component);c:ShowOnlyComponent(T.snow_component)
    for _,component in ipairs(T.active.nanite_components or{})do if component:IsValid()then c:ShowOnlyComponent(component)end end
    local eye={X=x,Y=y,Z=z+30000}
    c:K2_SetWorldLocationAndRotation(eye,{Pitch=-90,Yaw=0,Roll=0},false,{},true)
    c:CaptureScene();view.pending=eye;view.read_at=now+.10
end
function Contact.update(state,camera,passengers,now,paused)
    if not camera then return end
    local closest,distance
    for _,group in pairs(passengers)do for _,r in ipairs(group)do
        local d=(r.X-camera.x)^2+(r.Y-camera.y)^2+(r.Z-(camera.z or r.Z))^2
        if d<6000^2 and (r.discipline==0 or r.discipline==1) and (not distance or d<distance)then closest=r;distance=d end
    end end
    if not closest then return end
    -- The large overview captured over a million pixels, including for far
    -- riders rendered by the native crowd. Keep 25 cm contact precision near
    -- the camera; other soles use the cached snow profile on the local terrain.
    if not state.contact then state.contact={create(128,3200,.5)}end
    tick(state.contact[1],closest.X,closest.Y,closest.Z,now,paused)
end
function Contact.sample(state,x,y)
    for _,view in ipairs(state.contact or{})do
        if view.bytes then
            local z=P.depth_height(view.bytes,view.side,view.width,view.eye,x,y)
            if z then return z,z end
        end
    end
end
function Contact.dispose(state)
    for _,view in ipairs(state.contact or{})do
        view.component.TextureTarget=nil;library:ReleaseRenderTarget2D(view.rt)
        view.actor:K2_DestroyActor();view.bytes=nil
    end
    state.contact=nil
end
return Contact
