package.path='mod/SkiEO-CustomMaps/Scripts/?.lua;'..package.path
local function valid(self) return not self.dead end
local invalid={IsValid=function() return false end}
local function name(value) return {ToString=function() return value end} end
local function class(label,properties,parent)
    local c={IsValid=valid,GetFName=function() return name(label) end,GetSuperStruct=function() return parent or invalid end}
    c.ForEachProperty=function(_,callback) for _,p in ipairs(properties or {}) do if callback(p) then break end end end
    c.IsChildOf=function(self,other) return self==other or parent and parent:IsChildOf(other) end
    return c
end
PropertyTypes={ObjectProperty='object'}
local static_class=class('StaticMesh');local component_class=class('StaticMeshComponent');local proc_class=class('ProceduralMeshComponent')
local function prop(label,kind,resource)
    return {GetFName=function() return name(label) end,GetClass=function() return class(kind) end,IsA=function(_,type) return type=='object' and kind=='ObjectProperty' end,GetPropertyClass=function() return resource end}
end
local ticket_path='/Game/Blueprints/Buildings/BP_TicketOffice.BP_TicketOffice_C'
local ticket_class=class('BP_TicketOffice_C',{prop('BaseCost','IntProperty'),prop('MeshComponent','ObjectProperty',component_class),prop('bAllowQueueing','BoolProperty'),prop('InstanceName','TextProperty'),prop('VariantId','NameProperty')})
local mesh_props=class('StaticMeshComponent',{prop('StaticMesh','ObjectProperty',static_class)})
local old_mesh={IsValid=valid,GetClass=function() return static_class end,GetFullName=function() return 'StaticMesh /Game/Buildings/Office.Office' end}
local new_mesh={IsValid=valid,GetClass=function() return static_class end,GetFullName=function() return 'StaticMesh /Game/Buildings/New.New' end}
local function component()
    return {IsValid=valid,StaticMesh=old_mesh,visible=true,GetClass=function() return mesh_props end,
        IsA=function(_,path) return path=='/Script/Engine.StaticMeshComponent' end,
        IsVisible=function(self) return self.visible end,SetVisibility=function(self,v,children) assert(children==false);self.visible=v end,
        GetMaterial=function() return 'stock-material' end,SetStaticMesh=function(self,v) self.StaticMesh=v;return true end}
end
local cdo={IsValid=valid,BaseCost=4321,bAllowQueueing=true,MeshComponent=component(),GetClass=function() return ticket_class end}
ticket_class.GetCDO=function() return cdo end
local world={IsValid=valid,GetAddress=function() return 1 end}
local replacement_count=0
local function actor(address,default,otherworld)
    return {IsValid=valid,BaseCost=4321,bAllowQueueing=true,InstanceName='Office',MeshComponent=component(),GetClass=function() return ticket_class end,
        GetPlaceableId=function() return {A=address,B=0,C=0,D=0} end,
        IsA=function(_,path) return path=='/Script/SkiResortSimulator.PlaceableActor' or path=='/Script/SkiResortSimulator.BuildingActor' end,
        VariantId=name('Beginner'),ApplyVariant=function(self,value) self.VariantId=value;self.variant_calls=(self.variant_calls or 0)+1 end,
        SetInstanceName=function(self,value) self.InstanceName=value;self.name_setter_calls=(self.name_setter_calls or 0)+1 end,
        GetWorld=function() return otherworld or world end,GetAddress=function() return address end,
        GetFullName=function() return default and 'Default__TicketOffice' or 'BP_TicketOffice_C World:PersistentLevel.Office' end,
        AddComponentByClass=function(self,cls,manual,identity,defer)
            assert(cls==proc_class and manual==true and defer==false and identity.Scale3D.X==1)
            replacement_count=replacement_count+1
            local r={IsValid=valid,K2_AttachToComponent=function(_,source,socket,loc,rot,scale,weld) assert(source==self.MeshComponent and loc==2 and rot==2 and scale==2 and not weld) end,
                CreateMeshSection=function(_,index,vertices,triangles,normals,uv,a,b,collision) assert(index==0 and #vertices==3 and vertices[2].X==200 and #triangles==3 and not collision) end,
                SetCollisionEnabled=function(_,mode) assert(mode==0) end,SetMaterial=function(_,slot,mat) assert(slot==0 and mat=='stock-material') end,SetVisibility=function() end,
                K2_DestroyComponent=function(r,owner) assert(owner==self);r.dead=true end}
            self.replacement=r;return r
        end}
end
local one=actor(10);local default=actor(11,true);local foreign=actor(12,false,{IsValid=valid,GetAddress=function() return 2 end});local actors={one,default,foreign}
local resources={['/Script/SkiResortSimulator.PlaceableActor']=class('PlaceableActor'),[ticket_path]=ticket_class,['/Script/ProceduralMeshComponent.ProceduralMeshComponent']=proc_class,['/Game/Buildings/New.New']=new_mesh}
StaticFindObject=function(path) return resources[path] or invalid end;LoadAsset=StaticFindObject
FindAllOf=function(kind) return kind=='BlueprintGeneratedClass' and {} or actors end
package.preload.UEHelpers=function() return {GetWorld=function() return world end,FindOrAddFName=function(s) assert(type(s)=='string');return name(s) end} end
local Objects=require('object_edits')
-- Export the actual CDO fields without writing into the repository.
local captured;local oldopen,oldremove,oldrename=io.open,os.remove,os.rename
io.open=function(path,mode) assert(path:match('object%-defaults.json.part$') and mode=='wb');return {write=function(_,data) captured=data end,close=function() end} end
os.remove=function() end;os.rename=function() return true end
Objects.export();io.open,os.remove,os.rename=oldopen,oldremove,oldrename
-- Live UE4SS wrappers do not own native classes/CDOs. Root the class before
-- obtaining its CDO, and root both before enumerating properties.
local retained={}
StaticConstructObject=function() end
package.loaded.native_terrain={retain_texture=function(o) retained[o]=true end}
local old_cdo=ticket_class.GetCDO
ticket_class.GetCDO=function(self) assert(retained[self],'class released before CDO lookup');return old_cdo(self) end
local old_properties=ticket_class.ForEachProperty
ticket_class.ForEachProperty=function(self,fn) assert(retained[self] and retained[cdo],'CDO released during reflection');return old_properties(self,fn) end
Objects.defaults_exported=nil
io.open=function() return {write=function(_,data) captured=data end,close=function() end} end
os.remove=function() end;os.rename=function() return true end
Objects.export()
io.open,os.remove,os.rename=oldopen,oldremove,oldrename
ticket_class.GetCDO,ticket_class.ForEachProperty=old_cdo,old_properties
StaticConstructObject=nil
local json=require('json');local snapshot=json.decode(captured)
assert(snapshot.objects[1].fields.BaseCost.default==4321 and snapshot.objects[1].fields['MeshComponent.StaticMesh'].default=='/Game/Buildings/Office.Office')
local callbacks,logs={},{}
local api={on=function(_,event,fn) callbacks[event]=fn end,every=function(_,ms,fn) assert(ms==500);callbacks.tick=fn end,log=function(_,message) logs[#logs+1]=message end}
local mesh={vertices={{0,0,0},{200,0,0},{0,200,0}},triangles={0,1,2},normals={{0,0,1},{0,0,1},{0,0,1}},uv={{0,0},{1,0},{0,1}}}
Objects.apply(api,{{object=ticket_path,field='BaseCost',type='integer',value=123},{object=ticket_path,field='MeshComponent.StaticMesh',type='model',value='asset:office'}},{office=mesh})
assert(one.BaseCost==123 and not one.MeshComponent.visible and replacement_count==1)
assert(default.BaseCost==4321 and foreign.BaseCost==4321 and cdo.BaseCost==4321 and cdo.MeshComponent.visible)
callbacks.tick();assert(replacement_count==1)
-- Construction may finish after its actor appears; retry just that field.
local later=actor(20);local missing=later.MeshComponent;later.MeshComponent=invalid;actors[#actors+1]=later
callbacks.tick();assert(later.BaseCost==123 and #logs==1)
later.MeshComponent=missing;callbacks.tick();assert(not later.MeshComponent.visible and replacement_count==2)
callbacks['map.unloading']();assert(one.BaseCost==4321 and one.MeshComponent.visible and one.replacement.dead and later.BaseCost==4321 and later.replacement.dead)
assert(callbacks.tick()==false and cdo.BaseCost==4321)
-- Cooked references replace only the selected instance component and restore it.
Objects.apply(api,{{object=ticket_path,field='MeshComponent.StaticMesh',type='model',value='/Game/Buildings/New.New'}},{})
assert(one.MeshComponent.StaticMesh==new_mesh and cdo.MeshComponent.StaticMesh==old_mesh)
callbacks['map.unloading']();assert(one.MeshComponent.StaticMesh==old_mesh)
FText=function(value) return value end
Objects.apply(api,{{object=ticket_path,field='BaseCost',type='integer',value=100},
    {object=ticket_path,field='BaseCost',type='integer',value=777,instance={A=10,B=0,C=0,D=0}},
    {object=ticket_path,field='InstanceName',type='text',value='Not Ticket Office',instance={A=10,B=0,C=0,D=0}}},{})
assert(one.BaseCost==777 and later.BaseCost==100,'Instance properties must override inherited map values without changing another actor')
assert(one.InstanceName=='Not Ticket Office' and later.InstanceName=='Office' and one.name_setter_calls==1)
callbacks.tick();assert(one.name_setter_calls==1)
callbacks['map.unloading']();assert(one.BaseCost==4321 and one.InstanceName=='Office' and one.name_setter_calls==2)
-- Use the native variant setter for both edits and restoration. FName values
-- from property conversion must not be passed back to the string-only helper.
Objects.apply(api,{{object=ticket_path,field='VariantId',type='name',value='Expert',instance={A=10,B=0,C=0,D=0}}},{})
assert(one.VariantId:ToString()=='Expert' and one.variant_calls==1 and later.VariantId:ToString()=='Beginner')
callbacks.tick();assert(one.variant_calls==1)
callbacks['map.unloading']();assert(one.VariantId:ToString()=='Beginner' and one.variant_calls==2)
print('Object defaults, scoped overrides, future actors, portable OBJ and restoration passed')
