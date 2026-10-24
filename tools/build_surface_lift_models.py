"""Rebuild original Poma-inspired models: blender -b -t 2 --python this_file.

Metres in Blender, centimetres in SKPM. Photos are references only, never assets.
The .blend authoring scene is saved in build/surface-lifts/models.blend.
"""
import bpy, math, struct
from pathlib import Path
from mathutils import Vector
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'mod/SkiEO-SurfaceLifts/Assets';OUT.mkdir(parents=True,exist_ok=True)
bpy.ops.object.select_all(action='SELECT');bpy.ops.object.delete(use_global=False)
PALETTE=[(.46,.53,.56,1),(.12,.15,.17,1),(.87,.9,.88,1),(.12,.38,.51,1),(.63,.32,.12,1),(.24,.12,.055,1),(.93,.32,.06,1),(.035,.045,.05,1)]
mats=[]
for i,c in enumerate(PALETTE):
 m=bpy.data.materials.new(f'Palette_{i}');m.diffuse_color=c;mats.append(m)
img=bpy.data.images.new('Lift palette',width=8,height=8);img.pixels=[v for _ in range(8) for c in PALETTE for v in c];img.filepath_raw=str(OUT/'palette.png');img.file_format='PNG';img.save()
parts=[]
def finish(o,name,mat):
 o.name=name;o.data.materials.append(mats[mat]);parts.append(o);return o

def box(name,p,size,mat=0):
 bpy.ops.mesh.primitive_cube_add(size=1,location=p);o=bpy.context.object;o.scale=size
 return finish(o,name,mat)

def rod(name,a,b,r=.04,mat=0,verts=8):
 a,b=Vector(a),Vector(b);d=b-a
 bpy.ops.mesh.primitive_cylinder_add(vertices=verts,radius=r,depth=d.length,location=(a+b)*.5)
 o=bpy.context.object;o.rotation_euler=d.to_track_quat('Z','Y').to_euler();return finish(o,name,mat)

def ring(name,p,r,axis='Z',mat=0,thick=.04,segments=20):
 p=Vector(p)
 def point(t):
  v=(r*math.cos(t),r*math.sin(t),0) if axis=='Z' else (r*math.cos(t),0,r*math.sin(t))
  return p+Vector(v)
 for i in range(segments):rod(name,point(i*math.tau/segments),point((i+1)*math.tau/segments),thick,mat,6)
 for i in range(6):rod(name+' spoke',p,point(i*math.tau/6),thick*.7,mat,6)
 rod(name+' hub',p-Vector((0,0,.07) if axis=='Z' else (0,.07,0)),p+Vector((0,0,.07) if axis=='Z' else (0,.07,0)),.12,mat)

def ladder(x,y,h):
 for dx in [-.19,.19]:rod('ladder rail',(x+dx,y,.5),(x+dx,y,h),.022)
 for i in range(int((h-.5)/.3)):rod('rung',(x-.19,y,.5+i*.3),(x+.19,y,.5+i*.3),.018,0,6)

def bent_tip(x=0,y=0,z=0):
 # Smooth double bend; both terminal tangents remain parallel to the shaft.
 # The disc normal is exactly that same shaft axis, also under traction.
 p=[Vector((x-.12,y,z+.18)),Vector((x-.12,y,z-.02)),
    Vector((x-.60,y,z+.18)),Vector((x-.60,y,z+.03))]
 previous=p[0]
 for i in range(1,17):
  t=i/16;u=1-t;q=p[0]*u**3+p[1]*3*u*u*t+p[2]*3*u*t*t+p[3]*t**3
  rod('curved platter neck',previous,q,.027);previous=q
 rod('perpendicular platter',(x-.60,y,z),(x-.60,y,z+.06),.15,7,16)

def pole(x=0,y=0,z=0,stored=False):
 box('grip',(x,y,z),(.24,.12,.13),1)
 rod('suspension',(x,y,z),(x-.12,y,z-.65),.065,1)
 rod('fixed tube',(x-.12,y,z-.6),(x-.12,y,z-2.82),.029)
 bent_tip(x,y,z-3.00)

def hut(x,y):
 box('operator chalet',(x,y,1.05),(2.1,1.8,2.1),4)
 for z in [.25,.5,.75,1,1.25,1.5,1.75,2]:box('timber course',(x,y-.906,z),(2.1,.025,.018),5)
 box('door',(x+.4,y-.92,.85),(.65,.04,1.7),5)
 box('window',(x-.48,y-.94,1.45),(.65,.05,.6),3)
 for side in [-1,1]:
  o=box('pitched roof',(x,y+side*.54,2.25),(2.4,1.15,.12),1);o.rotation_euler.x=-side*.3

def export(name):
 global parts
 bpy.context.view_layer.update();vertices=[];indices=[]
 for o in parts:
  mesh=o.data;mesh.calc_loop_triangles();normal_matrix=o.matrix_world.to_3x3().inverted().transposed()
  color=mats.index(mesh.materials[0]);u=(color+.5)/8
  for tri in mesh.loop_triangles:
   # Reflect Y into Unreal's left-handed coordinates. UE procedural meshes use
   # clockwise front faces; the reflection supplies that winding conversion.
   for j in [0,1,2]:
    v=mesh.vertices[tri.vertices[j]];p=o.matrix_world@v.co;n=(normal_matrix@tri.normal).normalized()
    indices.append(len(vertices));vertices.append((p.x*100,-p.y*100,p.z*100,n.x,-n.y,n.z,u,.5))
 with (OUT/(name+'.skpm')).open('wb') as f:
  f.write(struct.pack('<4sIII',b'SKPM',1,len(vertices),len(indices)))
  for v in vertices:f.write(struct.pack('<8f',*v))
  f.write(struct.pack('<'+'I'*len(indices),*indices))
 collection=bpy.data.collections.new(name);bpy.context.scene.collection.children.link(collection)
 for o in parts:
  for c in list(o.users_collection):c.objects.unlink(o)
  collection.objects.link(o)
 collection.hide_render=True;collection.hide_viewport=True
 print(name,len(vertices),'vertices');parts=[]

pole();export('platter')
# TKD: the slim upper rod slides into the larger lower spring casing.
# The casing travels with the handle; its seal stays away from the holding hand.
box('detachable grip',(0,0,0),(.24,.12,.13),1)
rod('suspension',(0,0,0),(-.12,0,-.65),.065,1)
export('platter-upper')
rod('exposed sliding tube',(-.12,0,0),(-.12,0,-.01),.025)
export('platter-shaft')
rod('lower spring casing',(-.12,0,.18),(-.12,0,1.73),.042)
rod('upper casing seal',(-.12,0,1.69),(-.12,0,1.77),.048,1)
bent_tip()
export('platter-lower')
# Two ski poles carried together in the free hand, origins at the grips.
for y in [-.035,.035]:
 rod('carried pole grip',(.025,y,.06),(-.025,y,-.06),.025,1,10)
 rod('carried pole shaft',(-.025,y,-.06),(-.50,y,-1.12),.009,0,8)
 rod('carried pole basket',(-.475,y,-1.06),(-.485,y,-1.08),.045,1,10)
export('poles-bundle')
# Compact fixed-platter station: no storage rail for detachable perches.
rod('fixed mast',(-1.9,0,0),(-1.9,0,5.2),.22)
rod('fixed head',(-1.9,0,5.2),(0,0,5.2),.14)
ladder(-2.12,0,5.4);hut(-1,-4)
export('fixed-drive')
# Blanchon's elevated glazed motor room and open upper return (1979 photos).
for drive in [True,False]:
 for x in [-2.8,2.8]:
  for y in [-2.6,2.6]:rod('chair station column',(x,y,0),(x,y,8.05),.22)
  box('station beam',(x,0,7.9),(.3,6.1,.3))
 for y in [-2.7,2.7]:box('longitudinal beam',(0,y,7.9),(7,.22,.3))
 if drive:
  box('glass motor room',(0,0,9.1),(4.8,4.9,2),3)
  for y in [-2.5,2.5]:
   for x in [-2.5,-1.25,0,1.25,2.5]:box('white window mullion',(x,y,9.1),(.075,.08,2.15),2)
   for z in [8.05,10.15]:box('white window rail',(0,y,z),(5.1,.08,.09),2)
  box('motor room roof',(0,0,10.25),(5.4,5.4,.2),2)
 else:
  box('maintenance platform',(0,0,8.1),(5.8,3.6,.1))
  for y in [-1.9,1.9]:rod('guardrail',(-2.8,y,9.15),(2.8,y,9.15),.04)
 ladder(-2.8,-2.9,8.45)
 hut(-1,-6)
 export('blanchon-drive' if drive else 'blanchon-return')
# Real flanges surround an open running groove: the cable must remain visible
# between them rather than being buried inside a solid torus.
def grooved_wheel(radius,axle,segments):
 profile=[(-.06,-.07),(-.06,.04),(-.035,.04),(-.025,0),(-.015,-.016),
          (.015,-.016),(.025,0),(.035,.04),(.06,.04),(.06,-.07)]
 vertices=[];faces=[]
 for i in range(segments):
  a=i*math.tau/segments
  for z,delta in profile:vertices.append(((radius+delta)*math.cos(a),(radius+delta)*math.sin(a),z))
 n=len(profile)
 for i in range(segments):
  for j in range(n):faces.append((i*n+j,((i+1)%segments)*n+j,((i+1)%segments)*n+(j+1)%n,i*n+(j+1)%n))
 mesh=bpy.data.meshes.new('grooved rim');mesh.from_pydata(vertices,[],faces);mesh.update()
 obj=bpy.data.objects.new('grooved rim',mesh);bpy.context.scene.collection.objects.link(obj);finish(obj,'grooved rim',0)
 for i in range(8):
  a=i*math.tau/8;rod('wheel spoke',(0,0,0),((radius-.06)*math.cos(a),(radius-.06)*math.sin(a),0),.045)
 rod('wheel hub',(0,0,-.09),(0,0,.09),.15)
grooved_wheel(2,.6,64);export('inclined-wheel')
grooved_wheel(.8,.35,48);export('guide-wheel')
# Blanchon's tower frames are separate from their inclined moving roller trains.
box('chair tower footing',(0,0,.15),(1.25,1.25,.3),2)
rod('chair tubular mast',(0,0,.3),(0,0,9),.26,0,16)
ladder(.26,.25,9.2)
export('chair-tower')
for y in [-3.45,3.45]:
 rod('chair crossarm',(0,0,-.24),(0,y,-.24),.16)
 rod('chair walkway rail',(-1.5,y,.8),(1.5,y,.8),.035)
box('chair maintenance walkway',(0,0,0),(3.1,6.8,.09),0)
box('chair tower number',(0,-.29,.45),(.6,.08,.45),2)
export('chair-head')
# Static motor/reducer assembly, independent of the rotating wheel.
rod('bullwheel shaft',(0,0,-.35),(0,0,.72),.12)
box('reducer cast housing',(0,0,.74),(.68,.62,.45),0)
for x in [-.25,.25]:
 for y in [-.24,.24]:rod('reducer cover bolt',(x,y,.94),(x,y,1),.025,7,8)
rod('input coupling',(.28,0,.83),(.72,0,.83),.095,7)
rod('electric motor body',(.72,0,.83),(1.67,0,.83),.23,3,16)
for i in range(10):
 x=.77+i*.085;rod('motor cooling fin',(x,0,.83),(x+.025,0,.83),.265,3,16)
rod('fan cowling',(1.65,0,.83),(1.86,0,.83),.26,1,16)
for y in [-.14,0,.14]:rod('fan grille',(1.87,y,.65),(1.87,y,1.01),.012,0,6)
box('terminal box',(1.08,0,1.12),(.32,.3,.16),3)
for x in [.84,1.52]:box('motor mounting foot',(x,0,.55),(.24,.72,.1),0)
box('motor baseplate',(.82,0,.43),(2,.85,.12),1)
export('motor')
# Standard Poma tubular support, cable lanes at +/-1.6 m, hanger height 6 m.
for turn in [False,True]:
 for y in [0]:
  box('concrete footing',(0,y,.12),(.85,.85,.24),2)
  rod('galvanised mast',(0,y,0),(0,y,6.55),.19,0,12)
  rod('orange protection',(0,y,.1),(0,y,1.2),.25,6,12)
  ladder(.18,y-.2,6.6)
 rod('uphill crossarm',(0,0,6.8),(0,1.65,6.8),.09)
 rod('diagonal brace',(0,0,4.8),(0,1.6,6.5),.06)
 box('number plate',(0,0,6.9),(.5,.08,.38),2)
 export('angle-tower' if turn else 'tower')

# Return sheaves exist only on supports actually used by the high return.
for style in ['fixed','support','angle']:
 h=6 if style=='fixed' else 9
 if style!='fixed':
  rod('raised return mast',(0,0,6.1),(0,0,h+.55),.15)
 rod('return arm',(0,0,h+.55),(0,-1.65,h+.55),.09)
 rod('return brace',(0,0,h-1.2),(0,-1.6,h+.3),.06)
 export('fixed-return-support' if style=='fixed' else 'return-'+style)

for style in ['open','modern','covered']:
 covered=style=='covered'
 for x in ([-4,0,4] if covered else [-1.8,1.8]):
  for y in [-1.8,1.8]:
   box('footing',(x,y,.12),(.8,.8,.24),2)
   rod('station leg',(x,y,0),(x,y,5.85 if covered else 5.35),.11)
  rod('gantry',(x,-1.8,5.85 if covered else 5.35),(x,1.8,5.85 if covered else 5.35),.09)
 length=11 if covered else 6.5
 # Inclined wheel and descending guides are assembled from runtime heights.
 if covered:
  # Low blue barrel canopy and white ribbed fascias, original geometry.
  for y in [-1.8,1.8]:
   box('white fascia',(0,y,5.55),(11,.12,.75),2)
   for z in [5.24,5.4,5.56,5.72,5.88]:box('fascia rib',(0,y*1.01,z),(11,.025,.025),0)
  for i in range(12):
   a=i*math.pi/12;b=(i+1)*math.pi/12
   y=1.8*(math.cos(a)+math.cos(b))*.5;z=5.9+.65*(math.sin(a)+math.sin(b))*.5
   o=box('blue canopy',(0,y,z),(11,.49,.055),3);o.rotation_euler.x=math.atan2(.65*(math.sin(b)-math.sin(a)),1.8*(math.cos(b)-math.cos(a)))
  for x in [-5.5,-3.3,-1.1,1.1,3.3,5.5]:
   for i in range(12):
    a=i*math.pi/12;b=(i+1)*math.pi/12
    rod('canopy rib',(x,1.8*math.cos(a),5.9+.65*math.sin(a)),(x,1.8*math.cos(b),5.9+.65*math.sin(b)),.035)
 if not covered:
  for x in [-2.6,2.6]:
   for y in [-2.05,2.05]:
    # Side bracing stays outside the wheel's swept disc.
    rod('portal diagonal',(x,y,.5),(-x,y,5.35),.045)
  for y in [-1.9,1.9]:
   rod('storage safety rail',(-3.2,y,2),(3.2,y,2),.025)
  if style=='modern':
   for x in [-1.8,1.8]:
    for y in [-1.8,1.8]:box('Pras square column',(x,y,2.7),(.23,.23,5.4))
 hut(1,4 if style=='modern' else -4)
 # The route terminal is the bullwheel centre, not the station envelope centre.
 for obj in parts: obj.location.x += length/2-1.6+2.8
 export('pre-leve-drive' if covered else 'pras-drive' if style=='modern' else 'poma-drive')

# Floating returns hang from tension ropes; the uphill mast carries a weight.
for lattice in [False,True]:
 for y in [-.25,.25]:rod('inclined tension mast',(5,y,0),(3,y,8),.065 if lattice else .17)
 if lattice:
  for i in range(16):
   z=i*.5;x=5-z*.25
   rod('lattice diagonal',(x,-.25,z),(x-.125,.25,z+.5),.025)
   rod('lattice diagonal',(x,.25,z),(x-.125,-.25,z+.5),.025)
 for y in [-1.6,1.6]:
  rod('wheel frame',(-1.7,y,5.65),(1.7,y,5.65),.065)
  rod('suspension rope',(0,y,5.65),(3,0,8),.018,1)
 rod('tension rope',(3,0,8),(5,0,1.8),.018,1)
 box('counterweight',(5,0,1.3),(1,.7,1),2)
 rod('tension rope saddle',(3,-.2,8),(3,.2,8),.09)
 ladder(4,.3,7.7)
 export('lattice-return' if lattice else 'floating-return')
# Pré Levé's guided return with its release mechanism.
for y in [-1.5,1.5]:
 rod('return support',(0,y,0),(0,y,5.8),.16)
 rod('brace',(2,y,0),(0,y,4.7),.1)
rod('upper crossbeam',(0,-1.7,5.8),(0,1.7,5.8),.12)
for y in [-1.6,1.6]:rod('return frame',(-1.6,y,5.55),(2,y,5.55),.09)
for y in [-1.7,1.7]:rod('walkway rail',(-1.6,y,6.2),(2,y,6.2),.035)
ladder(2,1.6,6);hut(2,4)
export('release-return')
# Keep an immediately usable authoring overview; asset origins above stay local.
for index, collection in enumerate(c for c in bpy.data.collections if (OUT/(c.name+'.skpm')).exists()):
 collection.hide_viewport=False;collection.hide_render=False
 for obj in collection.objects: obj.location.x += index*16
for screen in bpy.data.screens:
 for area in screen.areas:
  if area.type=='VIEW_3D':
   area.spaces.active.region_3d.view_location=(48,0,3)
   area.spaces.active.region_3d.view_distance=70
(ROOT/'build/surface-lifts').mkdir(parents=True,exist_ok=True)
bpy.ops.wm.save_as_mainfile(filepath=str(ROOT/'build/surface-lifts/models.blend'))
