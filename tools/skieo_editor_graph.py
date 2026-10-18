"""Visual trigger graph: typed pins, draggable nodes, links and undo history."""
from __future__ import annotations
import copy
import math
from PySide6 import QtCore as C, QtGui as G, QtWidgets as W
if __package__ == 'tools':
    from . import skieo_authoring as authoring
    from .skieo_editor_widgets import label, button, row, Spin, Combo, editor_font, LuaHighlighter, scroll
else:
    import skieo_authoring as authoring
    from skieo_editor_widgets import label, button, row, Spin, Combo, editor_font, LuaHighlighter, scroll

COLORS={'exec':'#d7e0ef','number':'#68dcb2','boolean':'#e78599','string':'#b8a0ec','any':'#e4bd73'}


class Pin(W.QGraphicsEllipseItem):
    def __init__(self,node,name,direction,type,y):
        super().__init__(-6,-6,12,12,node)
        self.node,self.name,self.direction,self.type=node,name,direction,type
        self.setPos(0 if direction=='in' else 240,y)
        connected=direction=='out' or any(e['target']==node.data['id'] and e['input']==name for e in node.graph.document['edges'])
        self.setBrush(G.QColor(COLORS[type] if connected else '#28394e'));self.setPen(G.QPen(G.QColor(COLORS[type]),2))
        self.setToolTip(name+' • '+type+(' • Connect a constant or value node' if direction=='in' and type!='exec' else ''))
        self.setZValue(3)
    def mousePressEvent(self,event):
        if self.direction=='out': self.node.graph.start_link(self,event.scenePos())
        event.accept()


class Node(W.QGraphicsRectItem):
    def __init__(self,graph,data):
        spec=authoring.NODES[data['kind']]
        length=max(len(spec['inputs']),len(spec['outputs']),1)
        super().__init__(0,0,240,64+length*29)
        self.graph,self.data,self.pins=graph,data,{}
        self.setBrush(G.QColor('#28394e'));self.setPen(G.QPen(G.QColor('#455b74'),1.3))
        self.setFlags(W.QGraphicsItem.GraphicsItemFlag.ItemIsMovable|W.QGraphicsItem.GraphicsItemFlag.ItemIsSelectable|W.QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)
        tint='#20866c' if data['kind']=='entry' else '#9455ab' if data['kind'] in ('branch','compare') else '#376ba1'
        header=W.QGraphicsRectItem(0,0,240,36,self);header.setBrush(G.QColor(tint));header.setPen(G.QPen(C.Qt.PenStyle.NoPen))
        title=W.QGraphicsSimpleTextItem(spec['title'],self);title.setBrush(G.QColor('white'));title.setPos(14,8)
        font=G.QFont();font.setBold(True);title.setFont(font)
        if data['kind'] in ('number','text','boolean'):
            value=data.get('params',{}).get('value',spec['defaults']['value'])
            shown=('true' if value else 'false') if isinstance(value,bool) else format(value,'g') if isinstance(value,(int,float)) else '"'+str(value)+'"'
            font=editor_font();font.setBold(True)
            text=W.QGraphicsSimpleTextItem(G.QFontMetrics(font).elidedText(shown,C.Qt.TextElideMode.ElideRight,160),self)
            text.setFont(font);text.setBrush(G.QColor(COLORS[spec['outputs']['value']]));text.setPos(14,48);text.setToolTip(shown)
        for direction,fields in [('in',spec['inputs']),('out',spec['outputs'])]:
            for i,(name,type) in enumerate(fields.items()):
                y=59+i*29
                pin=Pin(self,name,direction,type,y);self.pins[direction,name]=pin
                text=W.QGraphicsSimpleTextItem(('▶ ' if type=='exec' else '')+name,self)
                text.setBrush(G.QColor('#d8e3ee'));text.setPos(14 if direction=='in' else 226-text.boundingRect().width(),y-9)
        self.setPos(*data.get('position',[0,0]))
    def itemChange(self,change,value):
        if change==W.QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            self.data['position']=[round(value.x(),1),round(value.y(),1)]
            self.graph.update_links()
        return super().itemChange(change,value)


def curve(start,end):
    path=G.QPainterPath(start)
    distance=max(60,abs(end.x()-start.x())*.5)
    path.cubicTo(start+C.QPointF(distance,0),end-C.QPointF(distance,0),end)
    return path


class Snapshot(G.QUndoCommand):
    def __init__(self,view,before,after,name):
        super().__init__(name);self.view,self.before,self.after=view,before,after
    def undo(self): self.view.restore(self.before)
    def redo(self): self.view.restore(self.after)


class GraphScene(W.QGraphicsScene):
    def __init__(self,view):
        super().__init__(view);self.view=view;self.before=None
    def mousePressEvent(self,event):
        self.before=copy.deepcopy(self.view.document)
        super().mousePressEvent(event)
    def mouseMoveEvent(self,event):
        if self.view.pending_pin:
            self.view.draft_link.setPath(curve(self.view.pending_pin.scenePos(),event.scenePos()))
            event.accept()
        else: super().mouseMoveEvent(event)
    def mouseReleaseEvent(self,event):
        if self.view.pending_pin:
            targets=[item for item in self.items(event.scenePos()) if isinstance(item,Pin) and item.direction=='in']
            source=self.view.pending_pin
            self.view.cancel_link()
            if targets: self.view.connect_pins(source,targets[0])
            event.accept()
        else:
            super().mouseReleaseEvent(event)
            if self.before is not None and self.before!=self.view.document:
                self.view.record(self.before,'Move node')
        self.before=None


class GraphView(W.QGraphicsView):
    changed=C.Signal()
    node_selected=C.Signal(object)
    def __init__(self,parent=None):
        super().__init__(parent)
        self.document={'nodes':[],'edges':[]};self.nodes={};self.links=[];self.pending_pin=None;self.draft_link=None
        self.undo=G.QUndoStack(self);self.undo.setUndoLimit(40)
        self.graph_scene=GraphScene(self);self.setScene(self.graph_scene)
        self.graph_scene.selectionChanged.connect(self.selection)
        self.setRenderHints(G.QPainter.RenderHint.Antialiasing|G.QPainter.RenderHint.TextAntialiasing)
        self.setBackgroundBrush(G.QColor('#1b293c'))
        self.setDragMode(W.QGraphicsView.DragMode.RubberBandDrag)
        self.setTransformationAnchor(W.QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setSceneRect(-3000,-3000,6000,6000)
        self.pan_start=None;self.redrawing=False

    def set_document(self,document):
        self.undo.clear();self.document=copy.deepcopy(document);self.redraw()
        if self.nodes: self.fitInView(self.scene().itemsBoundingRect().adjusted(-70,-70,70,70),C.Qt.AspectRatioMode.KeepAspectRatio)
        if self.transform().m11()>1: self.resetTransform()

    def restore(self,document):
        self.document=copy.deepcopy(document);self.redraw();self.changed.emit()

    def record(self,before,name):
        after=copy.deepcopy(self.document)
        if before!=after: self.undo.push(Snapshot(self,before,after,name))

    def redraw(self):
        self.redrawing=True;selected=[item.data['id'] for item in self.scene().selectedItems() if isinstance(item,Node)]
        self.cancel_link();self.nodes={};self.links=[];self.scene().clear()
        for data in self.document['nodes']:
            node=Node(self,data);self.nodes[data['id']]=node;self.scene().addItem(node)
            if data['id'] in selected: node.setSelected(True)
        for index,edge in enumerate(self.document['edges']):
            if edge['source'] not in self.nodes or edge['target'] not in self.nodes: continue
            item=W.QGraphicsPathItem();item.setZValue(-1)
            pin=self.nodes[edge['source']].pins['out',edge['port']]
            item.setPen(G.QPen(G.QColor(COLORS[pin.type]),2.5))
            item.setFlag(W.QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
            item.setData(0,index);self.scene().addItem(item);self.links.append((item,edge))
        self.update_links();self.redrawing=False;self.selection()

    def update_links(self):
        for item,edge in self.links:
            start=self.nodes[edge['source']].pins['out',edge['port']].scenePos()
            end=self.nodes[edge['target']].pins['in',edge['input']].scenePos()
            item.setPath(curve(start,end))

    def selection(self):
        if self.redrawing: return
        selected=[item.data for item in self.scene().selectedItems() if isinstance(item,Node)]
        self.node_selected.emit(selected[0] if selected else None)

    def start_link(self,pin,position):
        self.cancel_link();self.pending_pin=pin
        self.draft_link=W.QGraphicsPathItem(curve(pin.scenePos(),position));self.draft_link.setZValue(-1)
        self.draft_link.setPen(G.QPen(G.QColor(COLORS[pin.type]),2,C.Qt.PenStyle.DashLine))
        self.scene().addItem(self.draft_link)

    def cancel_link(self):
        if self.draft_link: self.scene().removeItem(self.draft_link)
        self.pending_pin=None;self.draft_link=None

    def connect_pins(self,source,target):
        before=copy.deepcopy(self.document)
        edge={'source':source.node.data['id'],'port':source.name,'target':target.node.data['id'],'input':target.name}
        candidate=copy.deepcopy(self.document);candidate['edges'].append(edge)
        try: authoring.compile_graph(candidate,complete=False)
        except (ValueError,authoring.ManifestError) as error:
            self.setToolTip(str(error));return False
        self.document=candidate;self.record(before,'Connect nodes');return True

    def add_node(self,kind,position=None):
        if kind=='entry': return
        before=copy.deepcopy(self.document)
        identifier='node-1';number=1
        while any(n['id']==identifier for n in self.document['nodes']): number+=1;identifier=f'node-{number}'
        position=position or self.mapToScene(self.viewport().rect().center())
        self.document['nodes'].append({'id':identifier,'kind':kind,'params':copy.deepcopy(authoring.NODES[kind].get('defaults',{})), 'position':[position.x(),position.y()]})
        self.record(before,'Add node')
        self.nodes[identifier].setSelected(True)

    def remove_selected(self):
        before=copy.deepcopy(self.document)
        nodes={item.data['id'] for item in self.scene().selectedItems() if isinstance(item,Node) and item.data['kind']!='entry'}
        edges={item.data(0) for item in self.scene().selectedItems() if isinstance(item,W.QGraphicsPathItem)}
        self.document['nodes']=[n for n in self.document['nodes'] if n['id'] not in nodes]
        self.document['edges']=[e for i,e in enumerate(self.document['edges']) if i not in edges and e['source'] not in nodes and e['target'] not in nodes]
        self.record(before,'Remove selection')

    def set_parameter(self,identifier,key,value):
        before=copy.deepcopy(self.document)
        next(n for n in self.document['nodes'] if n['id']==identifier).setdefault('params',{})[key]=value
        self.record(before,'Edit '+key)

    def drawBackground(self,painter,rect):
        super().drawBackground(painter,rect)
        painter.setPen(G.QPen(G.QColor('#26394f'),1))
        step=32
        left=math.floor(rect.left()/step)*step;top=math.floor(rect.top()/step)*step
        for x in range(int(left),int(rect.right())+step,step): painter.drawLine(C.QLineF(x,rect.top(),x,rect.bottom()))
        for y in range(int(top),int(rect.bottom())+step,step): painter.drawLine(C.QLineF(rect.left(),y,rect.right(),y))

    def wheelEvent(self,event):
        factor=1.15 if event.angleDelta().y()>0 else 1/1.15
        if .2<=self.transform().m11()*factor<=2.5: self.scale(factor,factor)
        event.accept()
    def mousePressEvent(self,event):
        if event.button()==C.Qt.MouseButton.MiddleButton:
            self.pan_start=event.position();self.setCursor(C.Qt.CursorShape.ClosedHandCursor);event.accept()
        else: super().mousePressEvent(event)
    def mouseMoveEvent(self,event):
        if self.pan_start is not None:
            delta=event.position()-self.pan_start;self.pan_start=event.position()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value()-int(delta.x()))
            self.verticalScrollBar().setValue(self.verticalScrollBar().value()-int(delta.y()));event.accept()
        else: super().mouseMoveEvent(event)
    def mouseReleaseEvent(self,event):
        if event.button()==C.Qt.MouseButton.MiddleButton: self.pan_start=None;self.unsetCursor();event.accept()
        else: super().mouseReleaseEvent(event)
    def contextMenuEvent(self,event):
        menu=W.QMenu(self);position=self.mapToScene(event.pos())
        for kind,spec in authoring.NODES.items():
            if kind!='entry': menu.addAction(spec['title'],lambda k=kind: self.add_node(k,position))
        menu.exec(event.globalPos())
    def keyPressEvent(self,event):
        if event.matches(G.QKeySequence.StandardKey.Undo): self.undo.undo()
        elif event.matches(G.QKeySequence.StandardKey.Redo): self.undo.redo()
        elif event.key()==C.Qt.Key.Key_Delete: self.remove_selected()
        elif event.key()==C.Qt.Key.Key_Escape: self.cancel_link()
        else: super().keyPressEvent(event)


class TriggerEditor(W.QDialog):
    def __init__(self,workshop):
        super().__init__(workshop)
        self.workshop=workshop;self.document=copy.deepcopy(workshop.document.triggers)
        self.base_source=workshop.document.script;self.current=None;self.loading=True;self.dirty=False
        self.setWindowTitle('Trigger Editor • SkiEO');self.resize(1260,800)
        layout=W.QVBoxLayout(self)
        layout.addWidget(label('Trigger Editor','heading'))
        layout.addWidget(label('Events run connected actions. Drag an output pin to an input; use the node inspector to change values.','muted'))
        split=W.QSplitter();layout.addWidget(split,1)
        left=W.QWidget();left_box=W.QVBoxLayout(left)
        self.new_button=button('New trigger',self.new_trigger,'new');self.remove_button=button('',self.remove_trigger,'delete');left_box.addWidget(row(self.new_button,self.remove_button))
        self.list=W.QListWidget();self.list.setMinimumWidth(230);left_box.addWidget(self.list,1);split.addWidget(left)
        centre=W.QWidget();box=W.QVBoxLayout(centre)
        self.name=W.QLineEdit();self.event=Combo(authoring.EVENTS);self.mode=Combo(['Visual graph','Lua']);self.enabled=W.QCheckBox('Enabled')
        self.before_script=W.QCheckBox('Register before project script')
        self.before_script.setToolTip('Register this event handler before the project initialization registers its own handlers. The action still waits for its selected event.')
        box.addWidget(self.name);box.addWidget(row(self.event,self.mode,self.enabled))
        box.addWidget(self.before_script)
        self.stack=W.QStackedWidget();box.addWidget(self.stack,1)
        self.graph=GraphView();self.stack.addWidget(self.graph)
        self.lua=W.QPlainTextEdit();self.lua.setFont(editor_font());self.highlight=LuaHighlighter(self.lua.document());self.stack.addWidget(self.lua)
        self.add_button=button('Add node…',self.add_node,'new');self.undo_button=button('Undo',self.graph.undo.undo,'undo');self.redo_button=button('Redo',self.graph.undo.redo,'redo');self.delete_button=button('Delete',self.graph.remove_selected,'delete')
        self.graph_tools=row(self.add_button,self.undo_button,self.redo_button,self.delete_button);graph_tools=self.graph_tools
        self.graph.undo.canUndoChanged.connect(self.controls);self.graph.undo.canRedoChanged.connect(self.controls);self.graph.scene().selectionChanged.connect(self.controls)
        box.addWidget(graph_tools);split.addWidget(centre)
        self.properties=W.QWidget();self.properties_box=W.QVBoxLayout(self.properties)
        self.properties.setMinimumWidth(230);self.properties.setMaximumWidth(290)
        self.properties_box.addWidget(label('Node properties','section'));self.properties_box.addStretch()
        split.addWidget(scroll(self.properties));split.setSizes([240,740,250])
        self.feedback=label('','muted');layout.addWidget(self.feedback)
        self.apply_button=button('Apply to project',self.apply,'save',True);layout.addWidget(row(button('Close',self.close),self.apply_button))
        self.list.currentRowChanged.connect(self.select)
        for widget in (self.name,self.event,self.mode):
            (widget.textEdited if isinstance(widget,W.QLineEdit) else widget.currentTextChanged).connect(self.changed)
        self.enabled.toggled.connect(self.changed);self.before_script.toggled.connect(self.changed);self.lua.textChanged.connect(self.changed)
        self.graph.changed.connect(self.graph_changed);self.graph.node_selected.connect(self.inspect_node)
        self.populate();self.loading=False;self.list.setCurrentRow(0)

    def controls(self,*args):
        if not hasattr(self,'apply_button'): return
        base=self.current is None or self.current==len(self.document['triggers'])
        graph=not base and self.mode.currentIndex()==0
        self.graph_tools.setVisible(graph);self.properties.parentWidget().setVisible(graph)
        self.remove_button.setEnabled(not base);self.new_button.setEnabled(len(self.document['triggers'])<256)
        self.add_button.setEnabled(graph and len(self.graph.document['nodes'])<512)
        self.undo_button.setEnabled(graph and self.graph.undo.canUndo());self.redo_button.setEnabled(graph and self.graph.undo.canRedo())
        self.delete_button.setEnabled(graph and any(isinstance(item,W.QGraphicsPathItem) or isinstance(item,Node) and item.data['kind']!='entry' for item in self.graph.scene().selectedItems()))
        try: authoring.compile_triggers(self.document);problem=None
        except (ValueError,authoring.ManifestError) as error: problem=str(error)
        self.feedback.setText(problem or '');self.apply_button.setEnabled(self.dirty and problem is None)

    def populate(self):
        self.list.clear()
        for trigger in self.document['triggers']: self.list.addItem(trigger['name'])
        self.list.addItem('Project initialization • Lua')

    def new_trigger(self):
        if len(self.document['triggers'])>=256: return
        identifier='trigger-1';i=1
        while any(t['id']==identifier for t in self.document['triggers']): i+=1;identifier=f'trigger-{i}'
        self.document['triggers'].append(authoring.new_trigger(identifier,'New trigger'))
        self.loading=True;self.populate();self.loading=False
        self.list.setCurrentRow(len(self.document['triggers'])-1);self.dirty=True;self.controls()

    def remove_trigger(self):
        row=self.list.currentRow()
        if 0<=row<len(self.document['triggers']):
            self.document['triggers'].pop(row);self.loading=True;self.populate();self.loading=False;self.list.setCurrentRow(0);self.dirty=True;self.controls()

    def select(self,index):
        if self.loading or index<0: return
        self.loading=True
        self.current=index
        base=index==len(self.document['triggers'])
        self.event.setEnabled(not base);self.mode.setEnabled(not base);self.enabled.setEnabled(not base)
        self.before_script.setEnabled(not base)
        self.before_script.setChecked(False if base else self.document['triggers'][index].get('before_script',False))
        if base:
            self.name.setText('Project initialization');self.name.setReadOnly(True);self.mode.setCurrentIndex(1);self.lua.setPlainText(self.base_source);self.stack.setCurrentIndex(1)
        else:
            trigger=self.document['triggers'][index]
            self.name.setReadOnly(False);self.name.setText(trigger['name']);self.event.setCurrentText(trigger['event'])
            self.mode.setCurrentIndex(0 if trigger.get('mode','graph')=='graph' else 1)
            self.enabled.setChecked(trigger.get('enabled',True));self.lua.setPlainText(trigger.get('lua','-- api and event are available here\n'))
            if 'graph' not in trigger: trigger['graph']=authoring.new_trigger()['graph']
            self.graph.set_document(trigger['graph']);self.stack.setCurrentIndex(self.mode.currentIndex())
        self.loading=False;self.inspect_node(None);self.controls()

    def changed(self,*args):
        if self.loading or self.current is None: return
        self.dirty=True
        if self.current==len(self.document['triggers']): self.base_source=self.lua.toPlainText();self.controls();return
        trigger=self.document['triggers'][self.current]
        trigger.update(name=self.name.text(),event=self.event.currentText(),enabled=self.enabled.isChecked(),before_script=self.before_script.isChecked(),mode='graph' if self.mode.currentIndex()==0 else 'lua',lua=self.lua.toPlainText())
        self.list.item(self.current).setText(trigger['name']);self.stack.setCurrentIndex(self.mode.currentIndex());self.controls()

    def graph_changed(self):
        if not self.loading and self.current is not None and self.current<len(self.document['triggers']):
            self.document['triggers'][self.current]['graph']=copy.deepcopy(self.graph.document);self.dirty=True;self.controls()

    def inspect_node(self,node):
        while self.properties_box.count():
            item=self.properties_box.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        self.properties_box.addWidget(label(authoring.NODES[node['kind']]['title'] if node else 'Node properties','section'))
        if node:
            params={**authoring.NODES[node['kind']].get('defaults',{}),**node.get('params',{})}
            for key,value in params.items():
                if key in authoring.NODES[node['kind']]['inputs']: continue
                self.properties_box.addWidget(label(key.replace('_',' ').capitalize(),'muted'))
                if key=='operator':
                    widget=Combo(['>=','>','<=','<','==','~=']);widget.setCurrentText(value)
                    widget.currentTextChanged.connect(lambda v,k=key,i=node['id']: self.graph.set_parameter(i,k,v))
                elif isinstance(value,bool):
                    widget=W.QCheckBox('True');widget.setChecked(value);widget.toggled.connect(lambda v,k=key,i=node['id']: self.graph.set_parameter(i,k,v))
                elif isinstance(value,(int,float)):
                    widget=Spin(value);widget.editingFinished.connect(lambda w=widget,k=key,i=node['id']: self.graph.set_parameter(i,k,w.value()))
                else:
                    widget=W.QLineEdit(str(value));widget.editingFinished.connect(lambda w=widget,k=key,i=node['id']: self.graph.set_parameter(i,k,w.text()))
                self.properties_box.addWidget(widget)
            if node['kind']=='entry': self.properties_box.addWidget(label('Choose the event above the graph. Its payload is available through an Event value node.','muted'))
        else: self.properties_box.addWidget(label('Select a node to edit its values. Right-click the graph to add an action or data node.','muted'))
        self.properties_box.addStretch()

    def add_node(self):
        menu=W.QMenu(self)
        for kind,spec in authoring.NODES.items():
            if kind!='entry': menu.addAction(spec['title'],lambda k=kind: self.graph.add_node(k))
        menu.exec(G.QCursor.pos())

    def apply(self):
        self.controls()
        if not self.apply_button.isEnabled(): return
        try:
            authoring.compile_triggers(self.document)
            self.workshop.document.queue_authoring('triggers',self.document)
            self.workshop.document.set_script(self.base_source)
            self.workshop.mark_dirty();self.dirty=False;self.controls();self.workshop.statusBar().showMessage('Triggers applied to source. Save and Build to compile them.')
        except (ValueError,authoring.ManifestError) as error: self.workshop.error(error)

    def closeEvent(self,event):
        if self.dirty:
            answer=W.QMessageBox.question(self,'Unsaved triggers','Apply trigger changes to the project?',W.QMessageBox.StandardButton.Save|W.QMessageBox.StandardButton.Discard|W.QMessageBox.StandardButton.Cancel)
            if answer==W.QMessageBox.StandardButton.Cancel: event.ignore();return
            if answer==W.QMessageBox.StandardButton.Save:
                self.apply()
                if self.dirty: event.ignore();return
        event.accept()
