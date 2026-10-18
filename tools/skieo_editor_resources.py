"""Resource library, native asset chooser and map-scoped object differences."""
from __future__ import annotations
import copy
import json
from pathlib import Path
import re
import numpy as np
from PySide6 import QtCore as C, QtGui as G, QtWidgets as W
import pyqtgraph.opengl as gl
if __package__ == 'tools':
    from . import skieo_authoring as authoring, skieo_install as desktop
    from .skieo_editor_widgets import label, button, row, FilePicker, Combo, Spin, scroll, icon
    from .skieo_game_catalog import DEFAULTS
    from .skieo_editor_3d import plane_hit, pan_grab, terrain_shader
else:
    import skieo_authoring as authoring, skieo_install as desktop
    from skieo_editor_widgets import label, button, row, FilePicker, Combo, Spin, scroll, icon
    from skieo_game_catalog import DEFAULTS
    from skieo_editor_3d import plane_hit, pan_grab, terrain_shader


class ResourceImport(W.QDialog):
    def __init__(self,workshop):
        super().__init__(workshop);self.workshop=workshop;self.result_asset=None
        self.setWindowTitle('Import resource');self.resize(610,430)
        layout=W.QVBoxLayout(self);layout.addWidget(label('Import a resource','heading'))
        layout.addWidget(label('Files are copied into your map project. Portable OBJ models are compiled by Build.','muted'))
        form=W.QFormLayout();layout.addLayout(form)
        self.file=FilePicker('Choose resource','Supported resources (*.obj *.png *.jpg *.jpeg *.wav *.ogg);;All files (*)')
        self.id=W.QLineEdit();self.kind=Combo(['model','image','sound']);self.units=Combo(['meters','centimeters']);self.axis=Combo(['z','y']);self.license=W.QLineEdit()
        form.addRow('Source',self.file);form.addRow('Resource ID',self.id);form.addRow('Type',self.kind)
        form.addRow('OBJ units',self.units);form.addRow('OBJ up axis',self.axis);form.addRow('Licence / credit',self.license)
        self.file.changed.connect(self.selected_file);self.kind.currentTextChanged.connect(self.controls)
        self.feedback=label('Choose a source file.','muted');layout.addWidget(self.feedback)
        self.import_button=button('Import',self.import_file,'import',True);layout.addStretch();layout.addWidget(row(button('Cancel',self.reject),self.import_button))
        self.cache=None
        for control in (self.id,self.license): control.textChanged.connect(self.validate)
        for control in (self.units,self.axis): control.currentTextChanged.connect(self.validate)
        self.controls()
    def selected_file(self,path):
        file=Path(path);self.id.setText(re.sub(r'[^a-z0-9._-]+','-',file.stem.lower()).strip('-') or 'resource')
        self.kind.setCurrentText('model' if file.suffix.lower()=='.obj' else 'sound' if file.suffix.lower() in ('.wav','.ogg') else 'image');self.validate()
    def controls(self,*args):
        for widget in (self.units,self.axis): widget.setVisible(self.kind.currentText()=='model')
        form=self.layout().itemAt(2).layout()
        if isinstance(form,W.QFormLayout):
            form.setRowVisible(self.units,self.kind.currentText()=='model');form.setRowVisible(self.axis,self.kind.currentText()=='model')
        self.validate()
    def validate(self,*args):
        if not hasattr(self,'import_button'): return False
        problem=None
        try:
            path=Path(self.file.value())
            if not self.file.value() or not path.is_file(): raise ValueError('Choose a source file.')
            if path.stat().st_size>32*1024*1024: raise ValueError('Choose a file of at most 32 MiB.')
            if not re.fullmatch(r'[a-z0-9][a-z0-9._-]{0,79}',self.id.text()): raise ValueError('Enter a resource ID using lowercase letters, numbers, dots or hyphens.')
            if len(self.workshop.document.resources['assets'])>=1024: raise ValueError('The resource library is full.')
            if any(a['id']==self.id.text() for a in self.workshop.document.resources['assets']): raise ValueError('This resource ID is already used.')
            if self.kind.currentText()=='model':
                if path.suffix.lower()!='.obj': raise ValueError('Choose an OBJ model.')
                signature=(str(path),path.stat().st_mtime_ns,self.units.currentText(),self.axis.currentText())
                if self.cache!=signature: authoring.parse_obj(path.read_bytes(),self.units.currentText(),self.axis.currentText());self.cache=signature
        except (ValueError,OSError,authoring.ManifestError) as error: problem=str(error)
        self.feedback.setText(problem or 'Ready to import.');self.import_button.setEnabled(problem is None);return problem is None
    def import_file(self):
        if not self.validate(): return
        try:
            options={'license':self.license.text()}
            if self.kind.currentText()=='model': options.update(units=self.units.currentText(),up_axis=self.axis.currentText())
            self.result_asset=self.workshop.document.import_resource(self.file.value(),self.id.text(),self.kind.currentText(),**options)
            self.workshop.mark_dirty();self.accept()
        except (ValueError,OSError,authoring.ManifestError) as error: self.workshop.error(error)


class ModelPreview(gl.GLViewWidget):
    def __init__(self,parent=None):
        super().__init__(parent);self.setBackgroundColor('#192936')
        self.mesh=gl.GLMeshItem(smooth=False,shader=terrain_shader(),color=(.55,.75,.72,1));self.mesh.setVisible(False);self.addItem(self.mesh)
        self.setMinimumHeight(280)
    def show_mesh(self,mesh):
        points=np.asarray(mesh['vertices'],dtype=np.float32)/100
        self.mesh.setMeshData(vertexes=points,faces=np.asarray(mesh['triangles'],dtype=np.uint32).reshape(-1,3))
        self.mesh.setVisible(True)
        centre=(points.min(axis=0)+points.max(axis=0))/2
        self.setCameraPosition(pos=G.QVector3D(*map(float,centre)),distance=max(1,float(np.ptp(points,axis=0).max())*2),elevation=25,azimuth=-55)
    def mouseMoveEvent(self,event):
        position=event.position();old=getattr(self,'last',position);delta=position-old;self.last=position
        if event.buttons()&C.Qt.MouseButton.RightButton: self.orbit(-delta.x(),delta.y())
        elif event.buttons()&C.Qt.MouseButton.MiddleButton: pan_grab(self,position,getattr(self,'grab_anchor',None))
        event.accept()
    def mousePressEvent(self,event):
        self.last=event.position()
        if event.button()==C.Qt.MouseButton.MiddleButton: self.grab_anchor=plane_hit(self,event.position(),self.opts['center'].z())
        event.accept()


class ResourceEditor(W.QDialog):
    def __init__(self,workshop):
        super().__init__(workshop);self.workshop=workshop
        self.setWindowTitle('Resource Editor • SkiEO');self.resize(1000,720)
        box=W.QVBoxLayout(self);box.addWidget(label('Resource Editor','heading'))
        box.addWidget(label('Keep authoring models, textures and sounds together. A game reference points to an already cooked asset.','muted'))
        split=W.QSplitter();box.addWidget(split,1)
        left=W.QWidget();layout=W.QVBoxLayout(left)
        layout.addWidget(row(button('Import…',self.import_resource,'import'),button('Game reference…',self.game_resource,'new')))
        self.list=W.QListWidget();layout.addWidget(self.list,1);left.setMinimumWidth(300)
        self.remove_button=button('Remove from library',self.remove,'delete');layout.addWidget(self.remove_button);split.addWidget(left)
        right=W.QWidget();layout=W.QVBoxLayout(right)
        self.title=label('Select a resource','heading');layout.addWidget(self.title)
        self.info=label('','muted');self.info.setTextInteractionFlags(C.Qt.TextInteractionFlag.TextSelectableByMouse);layout.addWidget(self.info)
        self.stack=W.QStackedWidget();layout.addWidget(self.stack,1)
        self.empty=label('Select a resource to see its preview.','muted');self.empty.setAlignment(C.Qt.AlignmentFlag.AlignCenter)
        self.image=W.QLabel();self.image.setAlignment(C.Qt.AlignmentFlag.AlignCenter)
        self.model=ModelPreview();self.stack.addWidget(self.empty);self.stack.addWidget(self.image);self.stack.addWidget(self.model)
        layout.addWidget(label('OBJ uses the replaced component’s game material. Images and sounds can be packaged as source resources; cooked Unreal references retain their game format.','muted'))
        split.addWidget(right);split.setSizes([330,650])
        box.addWidget(button('Close',self.accept));self.list.currentRowChanged.connect(self.select);self.reload()
    def reload(self):
        selected=self.list.currentRow();self.list.clear()
        for item in self.workshop.document.resources['assets']:
            self.list.addItem(W.QListWidgetItem(icon('objects' if item['kind']=='model' else 'assets'),item['id']+'\n'+item['kind']))
        if self.list.count(): self.list.setCurrentRow(max(0,min(selected,self.list.count()-1)))
    def import_resource(self):
        dialog=ResourceImport(self.workshop)
        if dialog.exec(): self.reload();self.list.setCurrentRow(self.list.count()-1)
    def game_resource(self):
        dialog=W.QDialog(self);dialog.setWindowTitle('Game resource reference');form=W.QFormLayout(dialog)
        identifier=W.QLineEdit();path=W.QLineEdit();path.setPlaceholderText('/Game/Folder/Asset.Asset')
        form.addRow('Resource ID',identifier);form.addRow('Cooked asset path',path)
        form.addRow(label('Use a reference exported by the game, or a cooked asset from an installed mod.','muted'))
        feedback=label('Enter a unique resource ID and a cooked asset path.','muted');form.addRow(feedback)
        add=button('Add reference',dialog.accept,'new',True);form.addRow(add)
        def validate():
            available=bool(re.fullmatch(r'[a-z0-9][a-z0-9._-]{0,79}',identifier.text()) and re.fullmatch(r'/(?:Game|Engine)/[A-Za-z0-9_/]+\.[A-Za-z0-9_]+',path.text()))
            available=available and len(self.workshop.document.resources['assets'])<1024 and all(a['id']!=identifier.text() for a in self.workshop.document.resources['assets'])
            add.setEnabled(available);feedback.setText('Ready to add.' if available else 'Enter a unique resource ID and a full /Game/Folder/Asset.Asset path.')
        identifier.textChanged.connect(validate);path.textChanged.connect(validate);validate()
        if not dialog.exec(): return
        try:
            draft=copy.deepcopy(self.workshop.document.resources)
            draft['assets'].append({'id':identifier.text(),'kind':'game','path':path.text()})
            refs={'version':1,'assets':[item for item in draft['assets'] if item['kind']=='game']}
            authoring.validate_resources(self.workshop.document.folder,refs)
            if len({item['id'] for item in draft['assets']})!=len(draft['assets']): raise ValueError('Resource ID already exists')
            self.workshop.document.queue_authoring('resources',draft);self.workshop.mark_dirty();self.reload()
        except (ValueError,authoring.ManifestError) as error: self.workshop.error(error)
    def remove(self):
        index=self.list.currentRow()
        if index<0: return
        doc=self.workshop.document;asset=doc.resources['assets'][index]
        if any(edit['value']=='asset:'+asset['id'] for edit in doc.object_edits): return
        draft=copy.deepcopy(doc.resources);draft['assets'].pop(index)
        doc.queue_authoring('resources',draft);self.workshop.mark_dirty();self.reload();self.stack.setCurrentIndex(0)
    def select(self,index):
        assets=self.workshop.document.resources['assets']
        available=0<=index<len(assets)
        used=available and any(edit['value']=='asset:'+assets[index]['id'] for edit in self.workshop.document.object_edits)
        self.remove_button.setEnabled(available and not used);self.remove_button.setToolTip('Reset the object field that uses this resource before removing it.' if used else 'Remove from library')
        if not available: self.title.setText('Select a resource');self.info.clear();self.stack.setCurrentIndex(0);return
        asset=assets[index];self.title.setText(asset['id']);self.stack.setCurrentIndex(0)
        self.info.setText(asset.get('file',asset.get('path',''))+'\n'+asset.get('license',''))
        if asset['kind']=='game': self.empty.setText('Cooked game reference\nAvailable in the game after loading the owning package.');return
        doc=self.workshop.document
        try:
            data=doc.pending.get(asset['file'])
            if data is None: data=doc.source_path(asset['file']).read_bytes()
            if asset['kind']=='model':
                self.model.show_mesh(authoring.parse_obj(data,asset.get('units','meters'),asset.get('up_axis','z')));self.stack.setCurrentIndex(2)
            elif asset['kind']=='image':
                pixmap=G.QPixmap();pixmap.loadFromData(data)
                self.image.setPixmap(pixmap.scaled(600,450,C.Qt.AspectRatioMode.KeepAspectRatio,C.Qt.TransformationMode.SmoothTransformation));self.stack.setCurrentIndex(1)
            else:
                self.empty.setText('Sound source • '+str(len(data))+' bytes\nChoose a cooked SoundBase reference to override a game sound property.')
        except (ValueError,OSError,authoring.ManifestError) as error: self.workshop.error(error)


class ResourcePicker(W.QDialog):
    def __init__(self,workshop,kind,default=None):
        super().__init__(workshop);self.workshop,self.kind=workshop,kind;self.value=None
        self.setWindowTitle('Choose '+kind+' resource');self.resize(650,450)
        box=W.QVBoxLayout(self);box.addWidget(label('Choose a resource','heading'))
        self.list=W.QListWidget();box.addWidget(self.list,1)
        self.path=W.QLineEdit();self.path.setPlaceholderText('Or paste a cooked /Game/Folder/Asset.Asset reference');box.addWidget(self.path)
        self.use_button=button('Use resource',self.use,'test',True)
        box.addWidget(row(button('Import file…',self.import_file,'import'),button('Cancel',self.reject),self.use_button))
        self.list.currentRowChanged.connect(self.validate);self.path.textChanged.connect(self.validate)
        self.default=default;self.reload();self.list.itemDoubleClicked.connect(lambda _: self.use());self.validate()
    def reload(self):
        self.list.clear()
        for asset in self.workshop.document.resources['assets']:
            if asset['kind']=='game' or self.kind=='model' and asset['kind']=='model':
                item=W.QListWidgetItem(asset['id']+' • '+asset['kind']);item.setData(C.Qt.ItemDataRole.UserRole,'asset:'+asset['id']);self.list.addItem(item)
        if self.default:
            item=W.QListWidgetItem('Game default • '+str(self.default));item.setData(C.Qt.ItemDataRole.UserRole,self.default);self.list.addItem(item)
    def import_file(self):
        dialog=ResourceImport(self.workshop)
        if dialog.exec():
            self.reload()
            for index in range(self.list.count()):
                if self.list.item(index).data(C.Qt.ItemDataRole.UserRole)=='asset:'+dialog.result_asset['id']:
                    self.list.setCurrentRow(index);break
    def validate(self,*args):
        item=self.list.currentItem();path=self.path.text().strip()
        self.use_button.setEnabled(bool(re.fullmatch(r'/(?:Game|Engine)/[A-Za-z0-9_/]+\.[A-Za-z0-9_]+',path)) if path else item is not None)
    def use(self):
        if not self.use_button.isEnabled(): return
        item=self.list.currentItem();value=self.path.text().strip() or (item.data(C.Qt.ItemDataRole.UserRole) if item else '')
        if not value: return
        self.value=value;self.accept()


class ValueDelegate(W.QStyledItemDelegate):
    def createEditor(self,parent,option,index):
        kind=index.data(C.Qt.ItemDataRole.UserRole)
        if kind=='boolean': return Combo(['false','true'],parent)
        if kind in ('number','integer'): return Spin(0,-2147483648,2147483647,0 if kind=='integer' else 5,parent=parent)
        control=super().createEditor(parent,option,index)
        if isinstance(control,W.QLineEdit): control.setMaxLength(4096)
        return control
    def setEditorData(self,editor,index):
        if isinstance(editor,Combo): editor.setCurrentText(index.data() or 'false')
        elif isinstance(editor,Spin): editor.setValue(float(index.data() or 0))
        else: super().setEditorData(editor,index)
    def setModelData(self,editor,model,index):
        if isinstance(editor,Combo): model.setData(index,editor.currentText())
        elif isinstance(editor,Spin): model.setData(index,str(int(editor.value())) if index.data(C.Qt.ItemDataRole.UserRole)=='integer' else str(editor.value()))
        else: super().setModelData(editor,model,index)


class ObjectEditor(W.QDialog):
    def __init__(self,workshop):
        super().__init__(workshop);self.workshop=workshop;self.loading=False
        self.edits=copy.deepcopy(workshop.document.object_edits);self.catalog=copy.deepcopy(authoring.OBJECTS)
        self.dirty=False;self.fields={};self.current=None
        self.merge(DEFAULTS)
        self.setWindowTitle('Object Editor • SkiEO');self.resize(1130,750)
        box=W.QVBoxLayout(self);box.addWidget(label('Object Editor','heading'))
        self.note=label('Changes apply immediately to the project and are bold. Save writes CSV differences. They apply to this map’s instances; class defaults remain in the game.','muted');box.addWidget(self.note)
        self.read_button=button('Read game defaults',self.read_game,'import')
        box.addWidget(row(self.read_button,button('Import defaults…',self.import_defaults,'open')))
        try:
            config=desktop.load_config();roots=[Path(p) for p in config.get('custom_map_locations',[])]
            if config.get('ue4ss_mods'): roots.append(Path(config['ue4ss_mods'])/'SkiEO-CustomMaps')
            available=any((root/'Scripts/object-defaults.json').is_file() for root in roots)
        except (ValueError,OSError): available=False
        self.read_button.setEnabled(available);self.read_button.setToolTip('Read the defaults captured by your game.' if available else 'Play a map once to capture the defaults from your game version.')
        split=W.QSplitter();box.addWidget(split,1)
        left=W.QWidget();left_box=W.QVBoxLayout(left)
        self.object_search=W.QLineEdit();self.object_search.setPlaceholderText('Search game objects…');left_box.addWidget(self.object_search)
        self.category=Combo(['All','building','lift','decoration','park','snowblower','vehicle','system','skier']);left_box.addWidget(self.category)
        self.list=W.QListWidget();self.list.setMinimumWidth(240);left_box.addWidget(self.list,1);split.addWidget(left)
        self.object_search.textChanged.connect(self.filter_objects);self.category.currentTextChanged.connect(self.filter_objects)
        right=W.QWidget();layout=W.QVBoxLayout(right)
        self.title=label('','heading');layout.addWidget(self.title)
        self.filter=W.QLineEdit();self.filter.setPlaceholderText('Search properties…');self.filter.textChanged.connect(self.filter_rows);layout.addWidget(self.filter)
        self.table=W.QTableWidget(0,4);self.table.setHorizontalHeaderLabels(['Property','Game default','Map value','Type'])
        self.table.horizontalHeader().setSectionResizeMode(0,W.QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1,W.QHeaderView.ResizeMode.Stretch);self.table.horizontalHeader().setSectionResizeMode(2,W.QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().hide();self.table.setAlternatingRowColors(True);self.table.setItemDelegateForColumn(2,ValueDelegate(self.table));layout.addWidget(self.table,1)
        self.resource_button=button('Choose resource…',self.choose_resource,'assets');self.reset_button=button('Reset to game default',self.reset,'undo')
        layout.addWidget(row(self.resource_button,self.reset_button));self.table.itemSelectionChanged.connect(self.selection_controls)
        layout.addWidget(label('Double-click a value to edit it. Meshes and sounds open the resource chooser. Missing defaults are labelled until captured from your game version.','muted'))
        split.addWidget(right);split.setSizes([250,850])
        self.place_button=button('Place on map',self.place,'objects',True)
        box.addWidget(row(button('Close',self.close),self.place_button))
        self.list.currentRowChanged.connect(self.select);self.table.itemChanged.connect(self.value_changed)
        self.table.cellDoubleClicked.connect(lambda r,c: self.choose_resource() if c==2 and self.table.item(r,c).data(C.Qt.ItemDataRole.UserRole) in ('model','asset','sound') else None)
        source=workshop.document.folder/'Objects/game-defaults.json'
        if 'Objects/game-defaults.json' in workshop.document.pending:
            self.merge(json.loads(workshop.document.pending['Objects/game-defaults.json']))
        elif source.is_file():
            try: self.merge(json.loads(source.read_text()))
            except (ValueError,OSError): pass
        self.reload_list()
    def merge(self,snapshot):
        if not isinstance(snapshot,dict) or snapshot.get('version')!=1 or not isinstance(snapshot.get('objects'),list): raise ValueError('Not a game defaults snapshot')
        if len(snapshot['objects'])>256: raise ValueError('Too many game objects')
        additions=copy.deepcopy(snapshot['objects'])
        for item in additions:
            if isinstance(item,dict) and item.get('fields')==[]: item['fields']={}
        for item in additions:
            if not isinstance(item,dict) or not isinstance(item.get('name'),str) or not isinstance(item.get('class'),str) or not isinstance(item.get('fields'),dict) or len(item['fields'])>2048: raise ValueError('Invalid game defaults object')
            for name,field in item['fields'].items():
                if not isinstance(field,dict) or 'type' not in field or 'default' not in field: raise ValueError('Invalid game defaults property')
                authoring.parse_edits(authoring.csv_bytes([{'object':item['class'],'field':name,'type':field['type'],'value':field['default']}]))
        by_class={item['class']:item for item in self.catalog}
        for item in additions:
            if item['class'] not in by_class:
                self.catalog.append(item);by_class[item['class']]=item
            else:
                by_class[item['class']]['fields'].update(item['fields'])
                if 'placeable' in item: by_class[item['class']]['placeable']=bool(item['placeable'])
    def reload_list(self):
        self.list.clear()
        for item in self.catalog: self.list.addItem(W.QListWidgetItem(icon('objects'),item['name']))
        self.list.setCurrentRow(0);self.filter_objects()
    def use_snapshot(self,data):
        if len(data)>8*1024*1024: raise ValueError('Game defaults snapshot is too large')
        snapshot=json.loads(data);self.merge(snapshot)
        doc=self.workshop.document;relative='Objects/game-defaults.json';doc.remember(relative);doc.pending[relative]=(json.dumps(snapshot,ensure_ascii=False,indent=2)+'\n').encode();doc.dirty=True
        self.workshop.mark_dirty();self.note.setText('Defaults read from your game. Bold values are map overrides, saved as CSV.');self.reload_list()
    def read_game(self):
        try:
            config=desktop.load_config();roots=[Path(p) for p in config.get('custom_map_locations',[])]
            if config.get('ue4ss_mods'): roots.append(Path(config['ue4ss_mods'])/'SkiEO-CustomMaps')
            file=next((p/'Scripts/object-defaults.json' for p in roots if (p/'Scripts/object-defaults.json').is_file()),None)
            if file is None: raise ValueError('Start a map with Custom Map 1.14 or later, then click Read game defaults. The loader captures real class values when the map starts.')
            self.use_snapshot(file.read_bytes())
        except (ValueError,OSError) as error: self.workshop.error(error)
    def import_defaults(self):
        file=W.QFileDialog.getOpenFileName(self,'Import exported game defaults','','Game defaults (*.json)')[0]
        if file:
            try: self.use_snapshot(Path(file).read_bytes())
            except (ValueError,OSError) as error: self.workshop.error(error)
    def selection_controls(self):
        index=self.table.currentRow();valid=self.current is not None and index>=0
        item=self.table.item(index,2) if valid else None
        self.resource_button.setEnabled(bool(item and item.data(C.Qt.ItemDataRole.UserRole) in ('model','asset','sound')))
        self.reset_button.setEnabled(bool(item and item.font().bold()))
    def select(self,index):
        if index<0 or index>=len(self.catalog):
            self.current=None;self.title.clear();self.table.setRowCount(0);self.place_button.setEnabled(False);self.selection_controls();return
        self.loading=True;self.current=self.catalog[index];self.title.setText(self.current['name']);self.fields=self.current['fields']
        self.table.setRowCount(len(self.fields))
        overrides={e['field']:e for e in self.edits if e['object']==self.current['class'] and not e.get('instance')}
        for row_index,(name,descriptor) in enumerate(sorted(self.fields.items())):
            if isinstance(descriptor,str): descriptor={'type':descriptor}
            kind=descriptor['type'];default=descriptor.get('default');current=overrides.get(name,{}).get('value',default)
            for column,value in enumerate((name,'Not captured' if default is None else self.display(default),'' if current is None else self.display(current),kind+(' • cm/s' if name=='OperatingSpeed' else ' • cm' if name.endswith('Cm') else ' • hours' if name in ('OpenHour','CloseHour') else ''))):
                item=W.QTableWidgetItem(value)
                item.setToolTip(value)
                item.setFlags(C.Qt.ItemFlag.ItemIsEnabled|C.Qt.ItemFlag.ItemIsSelectable)
                if column==2:
                    if kind not in ('model','asset','sound'): item.setFlags(item.flags()|C.Qt.ItemFlag.ItemIsEditable)
                    item.setData(C.Qt.ItemDataRole.UserRole,kind)
                    font=item.font();font.setBold(name in overrides);item.setFont(font)
                self.table.setItem(row_index,column,item)
        self.loading=False;self.filter_rows();self.place_button.setEnabled(self.current.get('placeable',self.current.get('kind') not in ('skier','vehicle','system')) and len(self.workshop.document.scene['objects'])<1024);self.selection_controls()
    @staticmethod
    def display(value): return 'true' if value is True else 'false' if value is False else str(value)
    def value_changed(self,item):
        if self.loading or item.column()!=2 or not self.current: return
        name=self.table.item(item.row(),0).text();descriptor=self.fields[name]
        if isinstance(descriptor,str): descriptor={'type':descriptor}
        kind=descriptor['type']
        try:
            text=item.text()
            value=int(text) if kind=='integer' else float(text) if kind=='number' else text=='true' if kind=='boolean' and text in ('true','false') else text
            edit={'object':self.current['class'],'field':name,'type':kind,'value':value}
            authoring.parse_edits(authoring.csv_bytes([edit]),{a['id']:a for a in self.workshop.document.resources['assets']})
            self.edits=[e for e in self.edits if e.get('instance') or (e['object'],e['field'])!=(edit['object'],name)]
            if 'default' not in descriptor or value!=descriptor['default']: self.edits.append(edit)
            self.loading=True
            font=item.font();font.setBold('default' not in descriptor or value!=descriptor['default']);item.setFont(font)
            self.loading=False;self.apply();self.selection_controls()
        except (ValueError,authoring.ManifestError) as error:
            self.note.setText(str(error));self.select(self.list.currentRow())
    def filter_rows(self,*args):
        text=self.filter.text().lower()
        for index in range(self.table.rowCount()): self.table.setRowHidden(index,text not in self.table.item(index,0).text().lower())
    def choose_resource(self):
        index=self.table.currentRow()
        if index<0: return
        item=self.table.item(index,2);kind=item.data(C.Qt.ItemDataRole.UserRole)
        if kind not in ('model','asset','sound'): return
        descriptor=self.fields[self.table.item(index,0).text()]
        default=descriptor.get('default') if isinstance(descriptor,dict) else None
        picker=ResourcePicker(self.workshop,kind,default)
        if picker.exec(): item.setText(picker.value)
    def reset(self):
        index=self.table.currentRow()
        if index<0: return
        name=self.table.item(index,0).text();cls=self.current['class']
        self.edits=[e for e in self.edits if e.get('instance') or (e['object'],e['field'])!=(cls,name)]
        self.apply();self.select(self.list.currentRow())
    def apply(self):
        try:
            authoring.parse_edits(authoring.csv_bytes(self.edits),{a['id']:a for a in self.workshop.document.resources['assets']})
            self.workshop.document.queue_authoring('objects',self.edits);self.workshop.mark_dirty();self.dirty=False
            self.workshop.statusBar().showMessage('Object differences applied to project. Save and Build to compile them.')
        except (ValueError,authoring.ManifestError) as error: self.workshop.error(error)
    def filter_objects(self,*args):
        text=self.object_search.text().lower();kind=self.category.currentText()
        for i,item in enumerate(self.catalog):
            self.list.item(i).setHidden(text not in item['name'].lower() or kind!='All' and item.get('kind')!=kind)
        if self.list.currentItem() and self.list.currentItem().isHidden():
            self.list.setCurrentRow(next((i for i in range(self.list.count()) if not self.list.item(i).isHidden()),-1))
    def place(self):
        item=self.current
        if item and item.get('placeable',item.get('kind') not in ('skier','vehicle','system')): self.accept();self.workshop.place_object(item)
    def closeEvent(self,event): event.accept()
