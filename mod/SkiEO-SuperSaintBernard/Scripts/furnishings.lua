-- Authored amenities around existing geographic anchors, not a historical inventory.
-- Stable IDs let native saves retain moved, changed and removed furniture.
local function definitions(namespace)
    local result={}
    local function add(key,kind,x,y,variant,yaw,label)
        local hash=5381
        for i=1,#key do hash=(hash*33+key:byte(i))%2147483647 end
        result[#result+1]={id=key,kind='decoration',
            class='/Game/Blueprints/Decorations/BP_'..kind..'.BP_'..kind..'_C',
            name=label or '',position_cm={x,y},offset_cm=20,yaw=yaw or 0,variant=variant,
            guid={A=namespace,B=0,C=0,D=hash},hub={A=0,B=0,C=0,D=0}}
    end
    local function cluster(key,x,y,yaw,restaurant,dx,dy)
        -- Keep a clear forecourt outside the native building footprint.
        dx,dy=dx or 1,dy or 0
        add(key..'-rack','SkiRack',x+dx*3500-dy*800,y+dy*3500+dx*800,'TwoSided',yaw)
        add(key..'-bench','ParkBench',x+dx*3500+dy*800,y+dy*3500-dx*800,nil,yaw)
        if restaurant then
            add(key..'-table-a','FrenchTable',x+dx*5000-dy*800,y+dy*5000+dx*800,nil,yaw)
            add(key..'-table-b','UmbrellaTable',x+dx*5000+dy*800,y+dy*5000-dx*800,nil,yaw)
        end
    end
    local function markers(key,name,difficulty,a,b,width)
        local dx,dy=b[1]-a[1],b[2]-a[2]
        local length=math.sqrt(dx*dx+dy*dy)
        if length<1 then return end
        local variant=difficulty==0 and 'Beginner' or difficulty==1 and 'Intermediate' or 'Expert'
        local distance=(width or 2400)/2+150
        local yaw=math.atan(dy,dx)*180/math.pi-90
        for _,side in ipairs({-1,1}) do
            add(key..'-marker-'..(side==1 and 'right' or 'left'),'TrailMarkers',
                a[1]-dy/length*distance*side,a[2]+dx/length*distance*side,variant,yaw,name)
        end
    end
    return result,add,cluster,markers
end
return function(data)
    local result,add,cluster,markers=definitions(0x53464E53)
    for _,a in ipairs(data.objects) do
        if a.id=='TicketOffice' or a.id=='FrenchChaletRestaurant' then
            cluster(a.id,a.position_cm[1],a.position_cm[2],a.yaw or 0,a.id=='FrenchChaletRestaurant',0,a.id=='FrenchChaletRestaurant' and -1 or 1)
        end
    end
    for index,trail in ipairs(data.trails) do
        markers('trail-'..index,trail.name,trail.difficulty,trail.points[1],trail.points[2],trail.width)
    end
    return result
end
