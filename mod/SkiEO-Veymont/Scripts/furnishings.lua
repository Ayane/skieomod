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
    local result,add,cluster,markers=definitions(0x56464E53)
    cluster('gresse-ticket',data.ticket_office.X,data.ticket_office.Y,data.ticket_office_yaw,false)
    add('gresse-planter-west','Planter',data.ticket_office.X+3500,data.ticket_office.Y+2000,'LowBox')
    add('gresse-planter-east','Planter',data.ticket_office.X+3500,data.ticket_office.Y-2000,'LowBox')
    for _,a in ipairs(data.amenities) do
        if a.kind=='hot_cocoa_cart' or a.kind=='waffle_stand' or a.kind=='warming_hut' then
            cluster(a.kind,a.position.X,a.position.Y,a.yaw,a.kind~='warming_hut',a.kind=='warming_hut' and -1 or 1,0)
        end
    end
    for index,trail in ipairs(data.trails) do
        local curve=trail.curves[1]
        if curve then markers('trail-'..index,trail.name,trail.difficulty,
            {curve.start.X,curve.start.Y},{curve.control.X,curve.control.Y},trail.width) end
    end
    return result
end
