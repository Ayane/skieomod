-- The free camera's native Tick rebuilds FollowCamera from its cached UE5
-- FRotator at +0x700. Actor/component/control rotation alone lasts one frame.
-- Reviewed Tick reads +0x700/+0x708/+0x710 on executable fingerprints for
-- Steam 26143813 (RVA 0x50994bb) and 26178224 (RVA 0x509afbb).
local Camera={}
local class='/Script/SkiResortSimulator.SkiResortCameraPawn'
local reviewed={['26143813']=true,['26178224']=true}
local fields={'SkiEOViewPitchBits','SkiEOViewYawBits','SkiEOViewRollBits'}
local registered=false
local function finite(n)return type(n)=='number'and n==n and math.abs(n)<math.huge end
local function bits(n)return string.unpack('<i8',string.pack('<d',n))end
local function number(n)return string.unpack('<d',string.pack('<i8',n))end
function Camera.set(pawn,rotation)
    assert(type(rotation)=='table'and finite(rotation.Pitch)and finite(rotation.Yaw)
        and finite(rotation.Roll or 0),'Invalid camera rotation')
    local version=require('game_version').poll()
    assert(version.supported and reviewed[version.build],'Camera orientation needs a reviewed game executable')
    assert(pawn and pawn:IsValid()and pawn:IsA(class),'Native free camera is unavailable')
    if not registered then
        require('compatibility').require('camera.private_view',{classes={[class]={
            FollowCamera={type='ObjectProperty',offset=0x328},
            CameraPositionLagSpeed={type='FloatProperty',offset=0x478},
            OrbitMaxPitch={type='FloatProperty',offset=0x5d8},
            OrbitMinPitch={type='FloatProperty',offset=0x5dc},
        }}})
        for i,name in ipairs(fields)do
            RegisterCustomProperty({Name=name,Type=PropertyTypes.UInt64Property,
                BelongsToClass=class,OffsetInternal=0x6f8+i*8})
        end
        registered=true
    end
    -- Check the old state and all new values before any camera memory write.
    local old={}
    for i,name in ipairs(fields)do
        old[i]=number(pawn[name]);assert(finite(old[i])and math.abs(old[i])<=36000,'Changed native camera view state')
    end
    assert(math.abs(old[1])<=90,'Changed native camera pitch')
    local minimum,maximum=pawn.OrbitMinPitch,pawn.OrbitMaxPitch
    assert(finite(minimum)and finite(maximum)and minimum<maximum and minimum>=-90 and maximum<=90,
        'Changed native camera pitch limits')
    assert(rotation.Pitch>=minimum and rotation.Pitch<=maximum and math.abs(rotation.Roll or 0)<=180,
        'Camera rotation is outside native limits')
    local values={bits(rotation.Pitch),bits((rotation.Yaw+180)%360-180),bits(rotation.Roll or 0)}
    for i,name in ipairs(fields)do pawn[name]=values[i]end
end
return Camera
