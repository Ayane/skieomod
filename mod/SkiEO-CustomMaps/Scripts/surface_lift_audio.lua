-- Original procedural sounds rendered by Unreal's audio mixer. They use the
-- game's SFX class and spatial attenuation, so the player's sound settings apply.
local Mesh=require('portable_mesh')
local A={}
local function valid(o) return o and o:IsValid() end
local function synth(owner,kind,p)
    local c=owner:AddComponentByClass(Mesh.load('/Script/Synthesis.ModularSynthComponent'),false,
        Mesh.transform(p),false)
    assert(valid(c),'Could not create lift audio component')
    c:K2_SetWorldLocation({X=p.x,Y=p.y,Z=p.z},false,{},true)
    c.bAutoDestroy=false;c.bStopWhenOwnerDestroyed=true;c.bAllowSpatialization=true
    c.SoundClass=Mesh.load('/Game/Sounds/SoundClasses/SC_SFX.SC_SFX')
    c.AttenuationSettings=Mesh.load('/Game/Sounds/Attenuation/SA_Buildings.SA_Buildings')
    c:SetEnablePolyphony(kind~='motor');c:SetStereoDelayIsEnabled(false);c:SetChorusEnabled(false)
    c:SetGainDb(kind=='motor' and -14 or -7)
    c:SetOscType(0,kind=='motor' and 1 or kind=='roller' and 2 or 0)
    c:SetOscType(1,kind=='arrival' and 0 or 4)
    c:SetOscGain(0,.8);c:SetOscGain(1,kind=='motor' and .07 or .3)
    c:SetOscSemitones(1,kind=='arrival' and 7.3 or 0)
    c:SetFilterFrequency(kind=='motor' and 260 or kind=='roller' and 1700 or 4800)
    c:SetFilterQ(.8);c:SetAttackTime(kind=='motor' and 250 or 1)
    c:SetDecayTime(kind=='arrival' and 170 or 65)
    c:SetSustainGain(kind=='motor' and .9 or 0);c:SetReleaseTime(kind=='motor' and 180 or 80)
    c:SetVolumeMultiplier(0);c:Start()
    return c
end
function A.create(item) return {events={motor=0,arrival=0,roller=0}} end
function A.silence(a)
    if not a then return end
    if a.motor then a.motor:SetVolumeMultiplier(0);a.arrival:SetVolumeMultiplier(0);a.roller:SetVolumeMultiplier(0) end
    if a.playing then a.motor:NoteOff(31,true,false);a.playing=false end
end
local function gain(p,camera,radius)
    local d=math.sqrt((p.x-camera.x)^2+(p.y-camera.y)^2+(p.z-camera.z)^2)
    return math.max(0,1-d/radius)^2
end
function A.update(a,item,camera,phase,seconds,paused)
    if not a or not camera then return end
    local bottom=item.supports[1];local length=item.lift.CableSpline:GetSplineLength()
    local step=a.phase and (phase-a.phase)%length or 0
    local dt=a.seconds and seconds-a.seconds or 0
    a.phase=phase;a.seconds=seconds
    local moving=not paused and item.lift:IsLiftRunning() and not item.snow_blocked
    local near,near_distance
    for i,p in ipairs(item.supports) do
        local d=(p.x-camera.x)^2+(p.y-camera.y)^2
        if not near_distance or d<near_distance then near=i;near_distance=d end
    end
    if not moving or near_distance>10000^2 then A.silence(a);return end
    if not a.motor then
        local p={x=bottom.x,y=bottom.y,z=bottom.z+250}
        a.motor=synth(item.visual,'motor',p);a.arrival=synth(item.visual,'arrival',p)
        a.roller=synth(item.visual,'roller',p)
    end
    a.motor:SetVolumeMultiplier(gain(bottom,camera,10000))
    if not a.playing then a.motor:NoteOn(31,85,-1);a.playing=true;a.events.motor=a.events.motor+1 end
    if dt<=0 or dt>2 or step<=.01 or step>1500 then return end
    local count=item.lift.ChairISM:GetInstanceCount();if count==0 then return end
    local spacing=length/count
    -- Compare unwrapped native carrier distance with each contact point. Initial
    -- discovery, camera jumps and save loads cannot generate a burst of impacts.
    local function crossed(distance)
        return math.floor((phase-distance)/spacing)~=math.floor((phase-step-distance)/spacing)
    end
    local arrivals
    if item.cycle then
        arrivals=a.returns and item.cycle.returns>a.returns
        a.returns=item.cycle.returns
    else arrivals=crossed(0)end
    if arrivals then
        a.arrival:SetVolumeMultiplier(gain(bottom,camera,7000))
        a.arrival:NoteOn(item.definition.kind=='fixed_platter' and 57 or 72,95,.12)
        a.events.arrival=a.events.arrival+1
    end
    if near>1 and near<#item.supports then
        local p=item.supports[near];local spline=item.lift.CableSpline
        local key=spline:FindInputKeyClosestToWorldLocation({X=p.x-p.nx*160,Y=p.y-p.ny*160,Z=p.z})
        local distance=spline:GetDistanceAlongSplineAtSplineInputKey(key)
        local passage
        if item.cycle then
            for _,pole in ipairs(item.cycle.poles)do if pole.state=='line'then
                local carrier=(phase+pole.index*spacing)%length
                if (carrier-distance)%length<step or (carrier-(length-distance))%length<step then passage=true;break end
            end end
        else passage=crossed(distance)or crossed(length-distance)end
        if passage then
            a.roller:K2_SetWorldLocation({X=p.x,Y=p.y,Z=p.z+p.height},false,{},true)
            a.roller:SetVolumeMultiplier(gain(p,camera,7000));a.roller:NoteOn(43,90,.045)
            a.events.roller=a.events.roller+1
        end
    end
end
function A.dispose(a)
    A.silence(a)
    for _,key in ipairs({'motor','arrival','roller'}) do if valid(a[key]) then a[key]:Stop() end end
end
return A
