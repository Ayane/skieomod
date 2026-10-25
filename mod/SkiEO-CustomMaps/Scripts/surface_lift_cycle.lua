-- Conserved detachable hangers use native boarding events and travelled cable
-- distance. Returning hangers keep their identity through the guide and FIFO
-- stock. Fixed grips bypass storage and always follow the cable.
local G=require('surface_lift_geometry')
local C={pitch=30,stock=4}
function C.exit(definition) return definition.kind=='detachable_platter' and (definition.drive=='covered' and 940 or 490) or 0 end
function C.boarding(definition)return definition.kind=='fixed_platter' and 600 or C.exit(definition)end
function C.path(t,tail)
    local arc=math.pi*160;local s=math.max(0,math.min(1,t))*(arc+tail)
    if s<arc then
        local a=s/160
        return -160*math.sin(a),160*math.cos(a),math.pi+a
    end
    return s-arc,-160,0
end
function C.queue(exit,index,phase)
    local t=math.max(0,math.min(1,(phase-.85)/.15));t=t*t*(3-2*t)
    return exit-300-C.stock*C.pitch+(index-1+t)*C.pitch,-160
end
function C.world(item,x,y,z,yaw)
    local b=item.supports[1];local c,s=math.cos(b.yaw),math.sin(b.yaw)
    y=y*(b.mirror or 1)
    return {x=b.x+x*c-y*s,y=b.y+x*s+y*c,z=b.z+b.height+z,yaw=b.yaw+(yaw or 0)}
end
function C.position(item,p,d,lane,yaw)
    local exit=C.exit(item.definition)
    local b=item.supports[1];local dx,dy=p.X-b.x,p.Y-b.y
    local x=dx*math.cos(b.yaw)+dy*math.sin(b.yaw)
    local y=(-dx*math.sin(b.yaw)+dy*math.cos(b.yaw))*(b.mirror or 1)
    if x<0 and d<200 then
        local a=math.atan(-x,y)
        local q=G.station_guide(b,a,exit>0 and exit-300-C.stock*C.pitch or 0)
        if exit==0 then q.z=q.z+10 end
        return q
    elseif exit>0 and lane<0 and d<exit then
        local t=math.max(0,d/exit)
        local q=C.world(item,exit-300+300*t^(exit/300),-160,-10,0)
        if item.supports.guides then
            local at=G.nearest(item.route,q.x,q.y)
            local p=G.cable(item.route,item.supports,at,-160)
            q.x,q.y,q.z=p.x,p.y,p.z-10*(1-t)
        end
        return q
    end
    local top=item.supports[#item.supports]
    if top~=b and d>item.route.length-200 then
        local tx,ty=p.X-top.x,p.Y-top.y
        local forward=tx*math.cos(top.yaw)+ty*math.sin(top.yaw)
        local side=(-tx*math.sin(top.yaw)+ty*math.cos(top.yaw))*(top.mirror or 1)
        if forward>0 then
            local a=math.atan(side,forward);local q=G.wheel(top,a);q.yaw=top.yaw+a+math.pi/2
            if exit>0 then q.z=q.z-10 end
            return q
        end
    end
end
-- Individual detachable hangers are conserved. Virtual native carriers remain
-- available to the game's queue, but an empty slot never takes a hanger out.
function C.rail(item,surface)
 local points={};local b=item.supports[1]
 local board=C.boarding(item.definition);local p=G.sample(item.route,board)
 local x,y=p.x-p.nx*160,p.y-p.ny*160
 local seat={X=x-math.cos(p.yaw)*22,Y=y-math.sin(p.yaw)*22,Z=surface(x,y)+87}
 local front=G.detachable_clamp(item.route,item.supports,board,-160,seat).distance
 local function add(p)
  local previous=points[#points];p.s=previous and previous.s+math.sqrt((p.x-previous.x)^2+(p.y-previous.y)^2+(p.z-previous.z)^2)or 0
  points[#points+1]=p
 end
 for i=0,8 do local p=G.cable(item.route,item.supports,200*(1-i/8),160);p.z=p.z-10*(i/8)^2;add(p)end
 for i=1,48 do local p=G.wheel(b,math.pi/2+i*math.pi/48);p.z=p.z-10;add(p)end
 for i=1,math.ceil(front/25)do local d=math.min(front,i*25);local p=G.cable(item.route,item.supports,d,-160)
  p.z=p.z-10*math.min(1,(front-d)/100);add(p)
 end
 return {points=points,length=points[#points].s,front=front}
end
function C.at(rail,s)
 s=math.max(0,math.min(rail.length,s));local points=rail.points;local lo,hi=1,#points
 while hi-lo>1 do local m=(hi+lo)//2;if points[m].s>s then hi=m else lo=m end end
 local a,b=points[lo],points[hi];local t=(s-a.s)/math.max(.001,b.s-a.s)
 return{x=a.x+(b.x-a.x)*t,y=a.y+(b.y-a.y)*t,z=a.z+(b.z-a.z)*t,yaw=math.atan(b.y-a.y,b.x-a.x)}
end
function C.create(count,rail,minimum)
 assert(count>=1 and count<=512,'Too many detachable carriers')
 local s={poles={},rail_length=rail.length,minimum=minimum,pitch=math.min(9,rail.length/(count+5)),travel=0,order=count+4,dispatches=0,returns=0}
 for i=1,count+4 do s.poles[i]={id=i,state='stock',s=rail.length-(i-1)*s.pitch,order=i}end
 return s
end
function C.carrier(s,index)
 C.lookup(s);return s.carriers[index]
end
function C.guest(s,key)
 C.lookup(s);return s.guests[key]
end
function C.lookup(s)
 if s.carriers then return end
 s.carriers={};s.guests={}
 for _,p in ipairs(s.poles)do if p.state=='line'then
  s.carriers[p.index]=p;if p.guest then s.guests[p.guest]=p end
 end end
end
function C.release(s,p)
 if p.guest and s.guests then s.guests[p.guest]=nil end
 p.guest=nil
end
function C.advance(s,rail,step)
 s.rail_length=rail.length
 step=math.max(0,step);s.travel=s.travel+step
 if step==0 then return end
 local queue={};for _,p in ipairs(s.poles)do if p.state~='line'then queue[#queue+1]=p end end
 table.sort(queue,function(a,b)return a.order<b.order end)
 for i,p in ipairs(queue)do
  local target=rail.length-(i-1)*s.pitch
  p.s=math.min(target,p.s+step*.85)
  if target-p.s<.01 then p.state='stock'else p.state='rail'end
 end
end
function C.dispatch(s,rail,index,guest,recovered,clearance)
 -- A rider keeps its carrier. Simulation and ISM updates need not occur in
 -- the same tick; choosing the nearest slot again can swap adjacent hangers.
 local existing=C.guest(s,guest);if existing then return existing end
 if C.carrier(s,index)then return nil,'occupied native slot'end
 if not recovered and ((clearance and clearance<s.minimum-.5)or(not clearance and s.last_dispatch and s.travel-s.last_dispatch<s.minimum-.5))then return nil,'minimum separation'end
 local first
 for _,p in ipairs(s.poles)do if p.state=='stock'and(not first or p.order<first.order)then first=p end end
 if not first or not recovered and first.s<rail.length-.1 then return nil,'stock not ready'end
 first.state='line';first.index=index;first.guest=guest;first.anchor=C.at(rail,first.s);first.launching=not recovered;first.s=nil
 first.launch_travel=s.travel;s.carriers[index]=first;s.guests[guest]=first
 if not recovered then
  s.last_dispatch=s.travel;s.last_id=first.id;s.dispatches=s.dispatches+1
  if clearance and clearance<math.huge then s.minimum_observed=math.min(s.minimum_observed or math.huge,clearance)end
 end
 return first
end
function C.arrive(s,index,progress)
 local p=C.carrier(s,index);if not p then return end
 s.carriers[index]=nil;C.release(s,p)
 p.state='rail';p.index=nil;p.anchor=nil;p.launching=nil;p.launch_travel=nil;s.order=s.order+1;p.order=s.order;p.s=math.max(0,progress or 0);s.returns=s.returns+1
 return p
end
function C.anchor(p,target,travel,seat,yaw)
 if not p or not p.launching then return target end
 local a=p.anchor;local dx,dy,dz=target.x-a.x,target.y-a.y,target.z-a.z
 -- Absolute travelled distance includes time outside the visual LOD. Rendering
 -- a hanger twice or after a camera cut must not change its mechanical phase.
 local distance=math.sqrt(dx*dx+dy*dy+dz*dz);local move=math.max(0,travel-p.launch_travel)*2
 if distance<=move+.001 then p.launching=false;p.anchor=target;return target end
 if move>0 then a={x=a.x+dx*move/distance,y=a.y+dy*move/distance,z=a.z+dz*move/distance} end
 -- Recovery must not turn a towing pole into a trailing pole, even when the
 -- first boarding observation arrives after the skier has left the station.
 if seat and (a.x-seat.X)*math.cos(yaw)+(a.y-seat.Y)*math.sin(yaw)<60 then
  p.launching=false;p.anchor=target;return target
 end
 return a
end
-- Compact slot-bound mementos stay within the loader's 32 KiB state limit.
-- Queue order is implicit; transient transforms and unbounded travel are omitted.
local alphabet='ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/'
local function base64(bytes)
 local out={}
 for i=1,#bytes,3 do
  local a,b,c=bytes:byte(i,i+2);local n=(a<<16)|((b or 0)<<8)|(c or 0)
  out[#out+1]=alphabet:sub((n>>18)+1,(n>>18)+1)..alphabet:sub(((n>>12)&63)+1,((n>>12)&63)+1)
   ..(b and alphabet:sub(((n>>6)&63)+1,((n>>6)&63)+1)or'=')..(c and alphabet:sub((n&63)+1,(n&63)+1)or'=')
 end
 return table.concat(out)
end
local function unbase64(text)
 assert(type(text)=='string'and #text<=32768 and #text%4==0 and not text:find('[^%w+/=]'),'Invalid hanger memento')
 local out={}
 for i=1,#text,4 do
  local n=0;local padding=0
  for j=0,3 do local c=text:sub(i+j,i+j);local at=alphabet:find(c,1,true)
   if c=='='then padding=padding+1;at=1 end
   assert(at and padding<=2,'Invalid hanger encoding');n=(n<<6)|(at-1)
  end
  out[#out+1]=string.char((n>>16)&255)..(padding<2 and string.char((n>>8)&255)or'')..(padding<1 and string.char(n&255)or'')
 end
 return table.concat(out)
end
function C.encode(s)
 local queue,line={},{}
 for _,p in ipairs(s.poles)do if p.state=='line'then line[#line+1]=p else queue[#queue+1]=p end end
 table.sort(queue,function(a,b)return a.order<b.order end);table.sort(line,function(a,b)return a.id<b.id end)
 local parts={string.pack('<c4I2I4I4I2f','SKH2',#s.poles,s.dispatches,s.returns,s.last_id or 0,assert(s.rail_length))}
 for _,p in ipairs(queue)do parts[#parts+1]=string.pack('<I2Bf',p.id,p.state=='stock'and 0 or 1,p.s)end
 for _,p in ipairs(line)do
  parts[#parts+1]=string.pack('<I2BI2',p.id,p.guest and 3 or 2,p.index)
  if p.guest then local words={};for word in p.guest:gmatch('[^-]+')do words[#words+1]=tonumber(word:sub(-8),16)end
   assert(#words==4,'Invalid retained passenger GUID');parts[#parts+1]=string.pack('<I4I4I4I4',table.unpack(words))
  end
 end
 return base64(table.concat(parts))
end
function C.decode(text,rail,minimum)
 local bytes=unbase64(text);local magic,n,dispatches,returns,last_id,at=string.unpack('<c4I2I4I4I2',bytes)
 assert((magic=='SKHP'or magic=='SKH2')and n>=1 and n<=516 and last_id<=n,'Invalid retained hangers')
 local previous_length
 if magic=='SKH2' then
  previous_length,at=string.unpack('<f',bytes,at)
  assert(previous_length==previous_length and previous_length>0 and previous_length<1e6,'Invalid retained hanger rail length')
 end
 local s={poles={},rail_length=rail.length,minimum=minimum,pitch=math.min(9,rail.length/(n+1)),travel=0,order=0,dispatches=dispatches,returns=returns}
 if last_id>0 then s.last_id=last_id end
 local seen={}
 for _=1,n do
  local id,tag;id,tag,at=string.unpack('<I2B',bytes,at)
  assert(id>=1 and id<=n and not seen[id]and tag<=3,'Invalid hanger identity');seen[id]=true
  local p={id=id}
  if tag<2 then
   p.s,at=string.unpack('<f',bytes,at);assert(p.s==p.s and p.s>=0 and p.s<=(previous_length or rail.length+1000)+.1,'Stored hanger is outside its rail')
   p.state=tag==0 and'stock'or'rail';s.order=s.order+1;p.order=s.order
  else
   p.state='line';p.index,at=string.unpack('<I2',bytes,at)
   if tag==3 then local words={}
    for _=1,4 do local word;word,at=string.unpack('<I4',bytes,at);if word>=0x80000000 then word=word-0x100000000 end;words[#words+1]=string.format('%08x',word)end
    p.guest=table.concat(words,'-')
   end
  end
  s.poles[#s.poles+1]=p
 end
 assert(at==#bytes+1,'Trailing hanger memento bytes')
 -- Snow changes the clamp's boarding reach and thus the station rail length.
 -- Preserve hanger identities/FIFO order while rebasing their rail progress.
 -- Legacy saves omitted the length; a stocked front hanger anchors a modest
 -- contraction (up to 10 m), otherwise the current rail is the safe baseline.
 if not previous_length then
  previous_length=rail.length
  for _,p in ipairs(s.poles)do if p.s then previous_length=math.max(previous_length,p.s)end end
 end
 for _,p in ipairs(s.poles)do if p.s then p.s=math.min(rail.length,p.s*rail.length/previous_length)end end
 return s
end
return C
