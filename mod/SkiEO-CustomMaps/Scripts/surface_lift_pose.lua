-- Native equipped skeleton, posed only for nearby towing passengers. Native
-- crowd rendering takes over again at alighting or outside the detailed LOD.
local Mesh=require('portable_mesh')
local P=require('surface_lift_pose_math')
local UE=require('UEHelpers')
local Pose={}
local function valid(o)return o and o:IsValid()end
local function vector(v)return{X=v.X,Y=v.Y,Z=v.Z}end
local function transform(t)return{Translation=vector(t.Translation),Rotation={X=t.Rotation.X,Y=t.Rotation.Y,Z=t.Rotation.Z,W=t.Rotation.W},Scale3D=vector(t.Scale3D)}end
local function materials(state)
    if state.pose_materials then return state.pose_materials end
    -- The crowd's VAT normal texture does not describe a posed skeleton.
    -- This cooked native material has a real skeletal-mesh shader permutation.
    local base=Mesh.load('/InterchangeAssets/gltf/MaterialInstances/MI_Default_Opaque.MI_Default_Opaque')
    local library=Mesh.load('/Script/Engine.Default__KismetMaterialLibrary')
    local retain=require('native_terrain').retain_texture
    local colors={{.025,.10,.18},{.55,.015,.025},{.025,.18,.09},{.12,.025,.18},
        {.8,.25,.015},{.03,.28,.32},{.55,.07,.20},{.18,.22,.025}}
    local sets={}
    for variant=1,#colors do
        local palette={colors[variant],colors[variant%#colors+1],colors[(variant+2)%#colors+1],
            {.02,.022,.028},{.5,.24,.12},{.01,.018,.025},colors[variant%#colors+1]}
        local set={}
        for section,color in ipairs(palette)do
            local m=library:CreateDynamicMaterialInstance(UE.GetWorld(),base,UE.FindOrAddFName('TowSkier'..variant..'_'..section),0)
            retain(m)
            m:SetVectorParameterValue(UE.FindOrAddFName('BaseColorFactor'),{R=color[1],G=color[2],B=color[3],A=1})
            m:SetScalarParameterValue(UE.FindOrAddFName('MetallicFactor'),0)
            m:SetScalarParameterValue(UE.FindOrAddFName('RoughnessFactor'),.8)
            set[section]=m
        end
        sets[variant]=set
    end
    state.pose_materials=sets;return sets
end
function Pose.prepare(state,discipline)
    discipline=discipline or 0;state.pose_sources=state.pose_sources or {}
    if state.pose_sources[discipline]then return state.pose_sources[discipline]end
    local a=Mesh.actor();local c=a:AddComponentByClass(Mesh.load('/Script/Engine.SkeletalMeshComponent'),false,Mesh.transform({0,0,0}),false)
    local source={actor=a,component=c,started=state.clock_seconds}
    state.pose_sources[discipline]=source
    local asset=discipline==1 and 'Skier_Rig_Snowboard' or 'SK_Skier_Equipped'
    local mesh=Mesh.load('/Game/Characters/Meshes/'..asset..'.'..asset)
    c:SetSkeletalMeshAsset(mesh)
    local bounds=mesh:GetImportedBounds()
    source.sole_z=bounds.Origin.Z-bounds.BoxExtent.Z
    assert(source.sole_z>=-20 and source.sole_z<=10,'Changed native equipment sole bounds')
    c:SetCollisionEnabled(0);c.VisibilityBasedAnimTickOption=0;c:SetVisibility(false,false)
    local animation=discipline==1 and 'Skier_Anim_Snowboard_Intermediate' or 'Skier_Anim_Stand'
    c:PlayAnimation(Mesh.load('/Game/Characters/Meshes/'..animation..'.'..animation),false)
    c:SetPlayRate(0)
    state.poses=state.poses or {}
    return source
end
local function entry(state,index,discipline,source)
    state.pose_pool=state.pose_pool or {};local key=discipline..':'..index
    if state.pose_pool[key]then return state.pose_pool[key]end
    local a=Mesh.actor();local c=a:AddComponentByClass(Mesh.load('/Script/Engine.PoseableMeshComponent'),false,Mesh.transform({0,0,0}),false)
    c:SetSkinnedAssetAndUpdate(source.component:GetSkeletalMesh_DEPRECATED(),true)
    c:SetCollisionEnabled(0);c:CopyPoseFromSkeletalComponent(source.component)
    c:SetEvaluateWorldPositionOffset(false)
    materials(state)
    -- The original two sticks share a material section. Replace that section
    -- with a single pair carried in the free hand; native skis stay on the rig.
    if discipline==0 then c:ShowMaterialSection(7,7,false,0)end
    local e={actor=a,component=c,bones={},discipline=discipline,sole_z=source.sole_z,bundle=Mesh.component(a,state.models.poles_bundle,state.material)}
    for _,name in ipairs({'Hip','Belly','UpperArm_L','LowerArm_L','Hand_L','UpperArm_R','LowerArm_R','Hand_R',
        'UpperLeg_L','LowerLeg_L','Foot_L','UpperLeg_R','LowerLeg_R','Foot_R'})do
        local n=UE.FindOrAddFName(name);e.bones[name]={name=n,t=transform(source.component:GetBoneTransform(n,2))}
    end
    if discipline==1 then local n=UE.FindOrAddFName('Snowboard');e.bones.Snowboard={name=n,t=transform(source.component:GetBoneTransform(n,2))}end
    local hand=state.pose_sources[0].component:GetBoneTransform(UE.FindOrAddFName(discipline==1 and 'Hand_L'or'Hand_R'),2)
    e.holding_rotation=transform(hand).Rotation
    if discipline==1 then
        -- This rig's torso faces +Y while its board follows +X. Rotate the
        -- closed left glove from the standing rig into that sideways stance.
        e.holding_rotation=P.mul({X=0,Y=0,Z=math.sqrt(.5),W=math.sqrt(.5)},e.holding_rotation)
    end
    state.pose_pool[key]=e;state.poses[#state.poses+1]=e;return e
end
function Pose.place(state,index,rider,yaw,surface)
    local source=Pose.prepare(state,rider.discipline)
    if state.clock_seconds-source.started<.2 then return nil end
    if rider.discipline==1 and state.clock_seconds-Pose.prepare(state,0).started<.2 then return nil end
    local e=entry(state,index,rider.discipline,source);local legs={};materials(state);e.rider_key=rider.key;e.frame=state.clock_seconds
    local board_z,board_q
    if rider.discipline==1 then
        board_z,board_q=P.board_frame(rider.X,rider.Y,yaw,surface,e.sole_z)
    end
    for _,side in ipairs({'L','R'})do
        local upper=e.bones['UpperLeg_'..side];local lower=e.bones['LowerLeg_'..side];local foot=e.bones['Foot_'..side]
        local target,q,sole
        if board_q then
            local f=foot.t.Translation;target=P.rotate(board_q,f);target.Z=target.Z+board_z;q=board_q
            local p=P.rotate(board_q,{X=f.X,Y=f.Y,Z=e.sole_z});local c,s=math.cos(yaw),math.sin(yaw)
            sole={X=rider.X+c*p.X-s*p.Y,Y=rider.Y+s*p.X+c*p.Y,Z=board_z+p.Z}
        else target,q,sole=P.ski_contact(foot.t.Translation,rider.X,rider.Y,yaw,surface,e.sole_z)end
        legs[#legs+1]={side=side,upper=upper,lower=lower,bone=foot,hip=upper.t.Translation,knee=lower.t.Translation,
            foot=foot.t.Translation,target=target,q=q,sole=sole}
    end
    local z=P.grounded_root(legs)
    local qz={X=0,Y=0,Z=math.sin(yaw/2),W=math.cos(yaw/2)}
    -- Keep the torso upright. Tilting the whole skeleton with the piste leans
    -- its shoulders downhill and puts the towing shaft beyond arm reach.
    -- The equipped skis follow the slope through their native foot bones.
    e.root={Translation={X=rider.X,Y=rider.Y,Z=z},Rotation=qz,Scale3D={X=1,Y=1,Z=1}}
    if not e.visible then
        e.component:SetVisibility(true,false);e.bundle:SetVisibility(rider.discipline==0,false);e.visible=true
    end
    e.component:K2_SetWorldTransform(e.root,false,{},true)
    if board_q then
        local b=e.bones.Snowboard;local p=P.rotate(board_q,b.t.Translation);p.Z=p.Z+board_z-z
        e.component:SetBoneTransformByName(b.name,{Translation=p,Rotation=P.mul(board_q,b.t.Rotation),Scale3D=b.t.Scale3D},1)
    end
    e.contacts={}
    local front_thigh
    for _,leg in ipairs(legs)do
        local target={X=leg.target.X,Y=leg.target.Y,Z=leg.target.Z-z}
        local knee,ankle,uq,lq=P.arm(leg.hip,leg.knee,leg.foot,target,
            e.discipline==1 and {X=0,Y=1,Z=0} or {X=1,Y=0,Z=0})
        for _,v in ipairs({{leg.upper,leg.hip,P.mul(uq,leg.upper.t.Rotation)},
            {leg.lower,knee,P.mul(lq,leg.lower.t.Rotation)},
            {leg.bone,ankle,P.mul(leg.q,leg.bone.t.Rotation)}})do
            e.component:SetBoneTransformByName(v[1].name,{Translation=v[2],Rotation=v[3],Scale3D=v[1].t.Scale3D},1)
        end
        e.contacts[#e.contacts+1]=leg.sole
        if rider.discipline==1 and leg.side=='L'then
            front_thigh=P.add(P.scale(leg.hip,.75),P.scale(knee,.25))
            front_thigh.Z=front_thigh.Z-18
        end
    end
    local color=0
    for n in (rider.key or tostring(rider.color or 0)):gmatch('.')do color=(color*31+n:byte())%8 end
    if e.palette~=color then
        for i,m in ipairs(state.pose_materials[color+1])do e.component:SetMaterial(i-1,m)end
        e.palette=color
    end
    local hip=e.bones.Hip.t.Translation
    -- The disc rests behind the thighs. Its bent neck passes below the crotch;
    -- aiming at the hip joint puts the disc and shaft inside the trousers.
    local seat=P.point(e.root,front_thigh or {X=hip.X-22,Y=0,Z=hip.Z-24})
    return e,seat
end
local function arm(e,side,target,hand_rotation)
    local bones=e.arm_bones or e.bones
    local upper=bones['UpperArm_'..side];local lower=bones['LowerArm_'..side];local hand=bones['Hand_'..side]
    local elbow,wrist,uq,lq=P.arm(upper.t.Translation,lower.t.Translation,hand.t.Translation,target,{X=-.3,Y=side=='R' and 1 or -1,Z=-.2})
    for _,v in ipairs({{upper,upper.t.Translation,P.mul(uq,upper.t.Rotation)},{lower,elbow,P.mul(lq,lower.t.Rotation)},{hand,wrist,hand_rotation or P.mul(lq,hand.t.Rotation)}})do
        e.component:SetBoneTransformByName(v[1].name,{Translation=v[2],Rotation=v[3],Scale3D=v[1].t.Scale3D},1)
    end
    return wrist
end
function Pose.grip(e,perch,length,bend_height)
    -- Intersect the straight lower shaft with the hand's comfortable height.
    -- The bent end points back under the pelvis, leaving the shaft in front,
    -- between the thighs, rather than up the skier's back.
    local a=P.local_point(e.root,P.point(perch,{X=-12,Y=0,Z=-80}))
    local b=P.local_point(e.root,P.point(perch,{X=-12,Y=0,Z=-(length or 409)+(bend_height or 29)}))
    local alignment=P.between({X=0,Y=0,Z=1},P.sub(a,b))
    local offset=P.rotate(alignment,e.discipline==1 and {X=-8,Y=-5,Z=3}or{X=-5,Y=3,Z=0})
    local belly=e.bones.Belly;local pivot=belly.t.Translation
    local holding=e.discipline==1 and 'L' or 'R'
    local shoulder=e.bones['UpperArm_'..holding].t.Translation
    local elbow=e.bones['LowerArm_'..holding].t.Translation;local hand=e.bones['Hand_'..holding].t.Translation
    local reach=P.length(P.sub(elbow,shoulder))+P.length(P.sub(hand,elbow))-1
    a=P.add(a,offset);b=P.add(b,offset)
    local q,grip
    -- The skier leans from the waist when a low fixed cable pulls forward.
    -- Feet and pelvis stay at their solved contact positions.
    for degrees=0,55 do
        local angle=math.rad(degrees);q={X=0,Y=math.sin(angle/2),Z=0,W=math.cos(angle/2)}
        local tilted=P.add(pivot,P.rotate(q,P.sub(shoulder,pivot)))
        grip=P.shaft_grip(a,b,tilted,reach,150)
        if P.length(P.sub(grip,tilted))<=reach+.001 then break end
    end
    e.arm_bones={}
    for _,side in ipairs({'L','R'})do for _,part in ipairs({'UpperArm_','LowerArm_','Hand_'})do
        local name=part..side;local bone=e.bones[name];local t=bone.t
        e.arm_bones[name]={name=bone.name,t={Translation=P.add(pivot,P.rotate(q,P.sub(t.Translation,pivot))),
            Rotation=P.mul(q,t.Rotation),Scale3D=t.Scale3D}}
    end end
    e.component:SetBoneTransformByName(belly.name,{Translation=pivot,Rotation=P.mul(q,belly.t.Rotation),Scale3D=belly.t.Scale3D},1)
    local rotation=e.holding_rotation and P.mul(alignment,e.holding_rotation)
    local right=arm(e,holding,grip,rotation)
    e.math_grip_error=P.length(P.sub(right,grip))
    e.lean_degrees=math.deg(2*math.atan(q.Y,q.W))
    e.grip_target=P.point(e.root,grip)
    local actual=e.component:GetBoneTransformByName(UE.FindOrAddFName('Hand_'..holding),0).Translation
    e.grip_error=P.length(P.sub(vector(actual),e.grip_target))
    if e.discipline==1 then arm(e,'R',{X=-45,Y=5,Z=125})
    else
        local left=arm(e,'L',{X=18,Y=-45,Z=135})
        e.bundle:K2_SetWorldTransform({Translation=P.point(e.root,left),Rotation=e.root.Rotation,Scale3D={X=1,Y=1,Z=1}},false,{},true)
    end
end
function Pose.hide_unused(state,count)
    for _,e in ipairs(state.poses or{})do if e.visible and e.frame~=state.clock_seconds then
        e.component:SetVisibility(false,false);e.bundle:SetVisibility(false,false)
        e.visible=false
    end end
end
function Pose.dispose(state)
    for _,e in ipairs(state.poses or {})do if valid(e.actor)then e.actor:K2_DestroyActor()end end
    for _,source in pairs(state.pose_sources or{})do if valid(source.actor)then source.actor:K2_DestroyActor()end end
end
return Pose
