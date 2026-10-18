"""OpenGL terrain viewport with game-style camera gestures and terrain picking."""
from __future__ import annotations
import math
import numpy as np
from PySide6 import QtCore as C, QtGui as G, QtWidgets as W
import pyqtgraph.opengl as gl
from pyqtgraph.opengl import shaders

if __package__ == 'tools':
    from . import skieo_bake as bake
else:
    import skieo_bake as bake


def terrain_shader():
    return shaders.ShaderProgram('skieo-workshop', [
        shaders.VertexShader('''
            uniform mat4 u_mvp;
            attribute vec4 a_position;
            attribute vec3 a_normal;
            attribute vec4 a_color;
            varying vec3 normal;
            varying vec4 colour;
            void main() { normal=normalize(a_normal); colour=a_color; gl_Position=u_mvp*a_position; }
        '''),
        shaders.FragmentShader('''
            #ifdef GL_ES
            precision mediump float;
            #endif
            varying vec3 normal;
            varying vec4 colour;
            void main() {
                float light=.56+.44*max(0.,dot(normalize(normal),normalize(vec3(.4,-.3,1.))));
                gl_FragColor=vec4(colour.rgb*light,colour.a);
            }
        ''')])


def view_ray(view, point):
    viewport=(0,0,view.width(),view.height())
    projection=np.asarray(view.projectionMatrix(viewport,viewport).copyDataTo(),dtype=float).reshape(4,4)
    model=np.asarray(view.viewMatrix().copyDataTo(),dtype=float).reshape(4,4)
    try: inverse=np.linalg.inv(projection@model)
    except np.linalg.LinAlgError: return None
    x=point.x()/view.width()*2-1;y=1-point.y()/view.height()*2
    near=inverse@np.array([x,y,-1,1]);far=inverse@np.array([x,y,1,1])
    origin=near[:3]/near[3]
    end=far[:3]/far[3]
    direction=end-origin;direction/=np.linalg.norm(direction)
    return origin,direction


def plane_hit(view, point, height):
    ray=view_ray(view,point)
    if ray is None or abs(ray[1][2])<1e-8: return None
    origin,direction=ray
    distance=(height-origin[2])/direction[2]
    if distance<0: return None
    return origin+direction*distance


def pan_grab(view, point, anchor):
    if anchor is None: return
    hit=plane_hit(view,point,float(anchor[2]))
    if hit is not None:
        delta=anchor-hit
        view.opts['center']+=G.QVector3D(*map(float,delta))
        view.update()


class TerrainView(gl.GLViewWidget):
    selected = C.Signal(object)
    stroke = C.Signal(str, object)
    moved = C.Signal(object)
    cancelled = C.Signal()
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setBackgroundColor('#192936')
        self.setMouseTracking(True)
        self.setFocusPolicy(C.Qt.FocusPolicy.StrongFocus)
        self.document, self.built, self.tool = None, False, 'select'
        self.radius = 60
        self.last = None
        self.painting = False
        self.grab_anchor = None
        self.scene_items=[];self.scene_labels=[];self.scene_selected=None
        self.rendered_tree_count = 0
        self.points = self.faces = None
        self.height_grid = None
        self.mesh=gl.GLMeshItem(smooth=True,shader=terrain_shader(),computeNormals=True,glOptions='opaque')
        self.trees=gl.GLMeshItem(smooth=False,shader=terrain_shader(),glOptions='opaque')
        self.cursor=gl.GLLinePlotItem(pos=np.zeros((0,3)),color=(.98,.84,.38,1),width=2,antialias=True)
        self.addItem(self.mesh);self.addItem(self.trees);self.addItem(self.cursor)
        self.mesh.setVisible(False);self.trees.setVisible(False)

    def data(self):
        if self.built and self.document.built: return self.document.built
        d=self.document
        return d.width,d.height,d.spacing,d.heights

    def set_document(self, document, fit=True):
        self.document=document
        self.rebuild()
        if fit: self.fit_map()

    def height_at(self, x, y):
        width,height,spacing,values=self.data()
        gx=(x+(width-1)*spacing/2)/spacing;gy=(y+(height-1)*spacing/2)/spacing
        ix=max(0,min(len(self.columns)-2,int(np.searchsorted(self.columns,gx)-1)))
        iy=max(0,min(len(self.rows)-2,int(np.searchsorted(self.rows,gy)-1)))
        u=max(0,min(1,(gx-self.columns[ix])/(self.columns[ix+1]-self.columns[ix])))
        v=max(0,min(1,(gy-self.rows[iy])/(self.rows[iy+1]-self.rows[iy])))
        a,b=self.height_grid[iy,ix],self.height_grid[iy+1,ix]
        c,d=self.height_grid[iy,ix+1],self.height_grid[iy+1,ix+1]
        return float(a+(c-a)*u+(b-a)*v if u+v<=1 else d+(b-d)*(1-u)+(c-d)*(1-v))

    def rebuild(self):
        if not self.document: return
        width,height,spacing,values=self.data()
        xs=np.unique(np.linspace(0,width-1,min(width,193)).round().astype(int))
        ys=np.unique(np.linspace(0,height-1,min(height,193)).round().astype(int))
        self.columns,self.rows=xs,ys
        self.height_grid=np.asarray(values).reshape(height,width)[np.ix_(ys,xs)].astype(np.float32)
        x=(xs-(width-1)/2)*spacing
        y=-(ys-(height-1)/2)*spacing
        xx,yy=np.meshgrid(x,y)
        self.points=np.column_stack((xx.ravel(),yy.ravel(),self.height_grid.ravel())).astype(np.float32)
        nx,ny=len(xs),len(ys)
        a=(np.arange(ny-1)[:,None]*nx+np.arange(nx-1)[None,:]).ravel()
        self.faces=np.concatenate((np.column_stack((a,a+nx,a+1)),np.column_stack((a+1,a+nx,a+nx+1)))).astype(np.uint32)
        normalized=(self.height_grid.ravel()-self.height_grid.min())/max(1,float(np.ptp(self.height_grid)))
        stops=np.array([[.16,.34,.25,1],[.36,.53,.34,1],[.59,.63,.48,1],[.69,.72,.70,1],[.90,.93,.94,1]])
        colors=np.column_stack([np.interp(normalized,np.linspace(0,1,len(stops)),stops[:,c]) for c in range(4)]).astype(np.float32)
        self.mesh.setMeshData(vertexes=self.points,faces=self.faces,vertexColors=colors)
        self.mesh.setVisible(True)
        forest=self.document.built_trees if self.built else self.document.trees
        step=max(1,math.ceil(len(forest)/4000))
        samples=forest[::step]
        self.rendered_tree_count=len(samples)
        if not samples:
            self.trees.setVisible(False)
        else:
            vertices=[];faces=[];colours=[]
            for tree in samples:
                x,y=tree['x'],-tree['y'];z=self.height_at(x,-y)
                height_m=6+2*math.sin(x*.11+y*.13);radius=height_m*.24
                base=len(vertices)
                vertices.extend([[x-radius,y-radius,z+1],[x+radius,y-radius,z+1],[x+radius,y+radius,z+1],[x-radius,y+radius,z+1],[x,y,z+height_m], [x,y,z]])
                faces.extend([[base,base+1,base+4],[base+1,base+2,base+4],[base+2,base+3,base+4],[base+3,base,base+4], [base,base+5,base+1],[base+2,base+5,base+3]])
                colours.extend([[.07,.25,.19,1]]*6)
            self.trees.setMeshData(vertexes=np.asarray(vertices,dtype=np.float32),faces=np.asarray(faces,dtype=np.uint32),vertexColors=np.asarray(colours,dtype=np.float32))
            self.trees.setVisible(True)
        self.rebuild_scene()
        self.update()

    def rebuild_scene(self):
        for item in self.scene_items: self.removeItem(item)
        self.scene_items=[]
        for widget,_ in self.scene_labels: widget.hide();widget.deleteLater()
        self.scene_labels=[]
        if not self.document or self.points is None: return
        for instance in self.document.scene['objects']:
            positions=[instance['position']]+([instance['end_position']] if instance['kind']=='lift' else [])
            points=[]
            colour=(1,.8,.24,1) if instance['id']==self.scene_selected else (.2,.85,.85,1)
            for x,y in positions:
                z=self.height_at(x,y)+instance.get('height_offset_meters',0);points.append([x,-y,z+5])
                vertices=np.asarray([[x-4,-y-4,z],[x+4,-y-4,z],[x+4,-y+4,z],[x-4,-y+4,z],[x-4,-y-4,z+5],[x+4,-y-4,z+5],[x+4,-y+4,z+5],[x-4,-y+4,z+5]],dtype=np.float32)
                theta=math.radians(instance.get('rotation_degrees',0));rotation=np.array([[math.cos(theta),-math.sin(theta)],[math.sin(theta),math.cos(theta)]])
                vertices[:,:2]=(vertices[:,:2]-[x,-y])@rotation+[x,-y]
                mesh=gl.GLMeshItem(vertexes=vertices,faces=np.asarray([[0,1,4],[1,5,4],[1,2,5],[2,6,5],[2,3,6],[3,7,6],[3,0,7],[0,4,7],[4,5,6],[4,6,7]],dtype=np.uint32),color=colour,shader=terrain_shader(),smooth=False)
                self.addItem(mesh);self.scene_items.append(mesh)
            text=W.QLabel(self.document.scene_display_name(instance),self);text.setAttribute(C.Qt.WidgetAttribute.WA_TransparentForMouseEvents);text.setStyleSheet('color: white; background: rgba(19,35,47,210); border-radius: 4px; padding: 3px 6px; font-size: 11px;');text.adjustSize()
            self.scene_labels.append((text,np.append(np.asarray(points[0])+[0,0,6],1)))
            if len(points)>1:
                line=gl.GLLinePlotItem(pos=np.asarray(points),color=colour,width=3,antialias=True);self.addItem(line);self.scene_items.append(line)

    def paintEvent(self,event):
        super().paintEvent(event)
        if not self.scene_labels or not self.width() or not self.height(): return
        viewport=(0,0,self.width(),self.height())
        matrix=np.asarray(self.projectionMatrix(viewport,viewport).copyDataTo()).reshape(4,4)@np.asarray(self.viewMatrix().copyDataTo()).reshape(4,4)
        for widget,position in self.scene_labels:
            projected=matrix@position
            ndc=projected[:3]/projected[3] if projected[3]>0 else np.array([2,2,2])
            visible=bool(np.all(np.abs(ndc)<=1))
            if visible:
                widget.move(int((ndc[0]+1)*self.width()/2)+8,int((1-ndc[1])*self.height()/2)-widget.height());widget.raise_()
            widget.setVisible(visible)

    def fit_map(self):
        if not self.document: return
        width,height,spacing,values=self.data()
        centre=G.QVector3D(0,0,(min(values)+max(values))/2)
        self.setCameraPosition(pos=centre,distance=max((width-1)*spacing,(height-1)*spacing)*1.35,elevation=42,azimuth=-55)

    def pick(self, point):
        """Ray intersection against the exact triangles displayed by OpenGL."""
        if self.points is None or self.width()<1 or self.height()<1: return None
        ray=view_ray(self,point)
        if ray is None: return None
        origin,direction=ray
        triangles=self.points[self.faces]
        a,b,c=triangles[:,0],triangles[:,1],triangles[:,2]
        e1=b-a;e2=c-a;p=np.cross(np.broadcast_to(direction,e2.shape),e2)
        determinant=np.einsum('ij,ij->i',e1,p)
        mask=np.abs(determinant)>1e-9
        inv=np.divide(1,determinant,out=np.zeros_like(determinant),where=mask)
        offset=origin-a;u=np.einsum('ij,ij->i',offset,p)*inv
        q=np.cross(offset,e1);v=np.einsum('j,ij->i',direction,q)*inv
        distance=np.einsum('ij,ij->i',e2,q)*inv
        valid=mask & (u>=0) & (v>=0) & (u+v<=1) & (distance>0)
        if not valid.any(): return None
        position=origin+direction*distance[valid].min()
        return float(position[0]),float(-position[1]),float(position[2])

    def cursor_at(self, position):
        if position is None or self.tool in ('select','place') or self.built:
            self.cursor.setData(pos=np.zeros((0,3)));return
        x,y,_=position
        points=[]
        for angle in np.linspace(0,2*math.pi,65):
            xx=x+self.radius*math.cos(angle);yy=y+self.radius*math.sin(angle)
            points.append([xx,-yy,self.height_at(xx,yy)+.25])
        self.cursor.setData(pos=np.asarray(points,dtype=np.float32))

    def mousePressEvent(self, event):
        self.setFocus();self.last=event.position()
        if event.button()==C.Qt.MouseButton.MiddleButton:
            position=self.pick(event.position())
            self.grab_anchor=np.array([position[0],-position[1],position[2]]) if position is not None else plane_hit(self,event.position(),self.opts['center'].z())
            self.setCursor(C.Qt.CursorShape.ClosedHandCursor)
        if event.button()==C.Qt.MouseButton.LeftButton:
            position=self.pick(event.position())
            if position is not None:
                if self.tool in ('select','place') or self.built: self.selected.emit(position)
                else: self.painting=True;self.stroke.emit('begin',position)
        event.accept()

    def mouseMoveEvent(self, event):
        position=event.position()
        if self.last is not None:
            delta=position-self.last
            if event.buttons() & C.Qt.MouseButton.MiddleButton:
                pan_grab(self,position,self.grab_anchor)
            elif event.buttons() & C.Qt.MouseButton.RightButton:
                self.orbit(-delta.x()*.5,delta.y()*.5)
            elif event.buttons() & C.Qt.MouseButton.LeftButton and self.painting:
                point=self.pick(position)
                if point is not None: self.stroke.emit('dab',point)
        self.last=position
        if not event.buttons() or self.painting:
            point=self.pick(position);self.cursor_at(point)
            if point is not None: self.moved.emit(point)
        event.accept()

    def mouseReleaseEvent(self, event):
        if event.button()==C.Qt.MouseButton.MiddleButton:
            self.grab_anchor=None;self.unsetCursor()
        if event.button()==C.Qt.MouseButton.LeftButton and self.painting:
            self.painting=False;self.stroke.emit('end',None)
        self.last=None;event.accept()

    def wheelEvent(self, event):
        if self.document:
            distance=self.opts['distance']*math.exp(-event.angleDelta().y()/120*.12)
            self.setCameraPosition(distance=max(2,min(1e7,distance)))
        event.accept()

    def keyPressEvent(self,event):
        if event.key()==C.Qt.Key.Key_Escape and self.painting:
            self.painting=False;self.stroke.emit('cancel',None);event.accept()
        elif event.key()==C.Qt.Key.Key_Escape:
            self.cancelled.emit();event.accept()
        else: super().keyPressEvent(event)
