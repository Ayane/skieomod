"""Native placeable palette and scene instance controls."""
import copy
import json
from PySide6 import QtCore as C, QtWidgets as W
if __package__ == 'tools':
    from . import skieo_authoring as a
    from .skieo_editor_widgets import label, button, row, Spin, Combo
    from .skieo_editor_resources import ValueDelegate,ResourcePicker
    from .skieo_game_catalog import DEFAULTS
    from .skieo_scene import DEFAULT_NAMES
else:
    import skieo_authoring as a
    from skieo_editor_widgets import label, button, row, Spin, Combo
    from skieo_editor_resources import ValueDelegate,ResourcePicker
    from skieo_game_catalog import DEFAULTS
    from skieo_scene import DEFAULT_NAMES


class ScenePanel(W.QWidget):
    def __init__(self, workshop):
        super().__init__();self.workshop=workshop;self.loading=False;self.placing=None;self.start=None;self.moving=False;self.selected=None
        box=W.QVBoxLayout(self);box.addWidget(label('Place game objects','section'))
        self.search=W.QLineEdit();self.search.setPlaceholderText('Search buildings, lifts, decorations…');box.addWidget(self.search)
        self.palette=Combo([]);box.addWidget(self.palette)
        for item in a.OBJECTS:
            if item.get('placeable',item['kind'] not in ('skier','vehicle','system')): self.palette.addItem(item['name']+' • '+item['kind'],item)
        self.search.textChanged.connect(self.filter_palette)
        self.place_button=button('Place on terrain',self.begin,'objects',True);box.addWidget(self.place_button)
        self.palette.currentIndexChanged.connect(self.update_controls)
        self.hint=label('One click places a building. Lifts use two clicks for their lower and upper terminals. Escape cancels.','muted');box.addWidget(self.hint)
        box.addWidget(label('Objects in this map','section'));self.list=W.QListWidget();box.addWidget(self.list,1);self.list.currentRowChanged.connect(self.select)
        self.name=W.QLineEdit();self.name.setMaxLength(256);self.name.setMinimumWidth(130);self.x=Spin(0,-1e6,1e6,2,' m');self.y=Spin(0,-1e6,1e6,2,' m');self.end_x=Spin(0,-1e6,1e6,2,' m');self.end_y=Spin(0,-1e6,1e6,2,' m');self.end_row=row(self.end_x,self.end_y);self.yaw=Spin(0,-36000,36000,1,'°');self.offset=Spin(0,-36000,36000,2,' m')
        self.details=W.QWidget();form=W.QFormLayout(self.details);self.form=form;box.addWidget(self.details)
        self.default_label=label('','muted');self.reset_name_button=button('Reset name',self.reset_name,'undo')
        form.addRow('Default name',self.default_label);form.addRow('Name',self.name);form.addRow(self.reset_name_button);form.addRow('East / south',row(self.x,self.y));form.addRow('Upper terminal',self.end_row);form.addRow('Rotation',self.yaw);form.addRow('Height offset',self.offset)
        self.property_search=W.QLineEdit();self.property_search.setPlaceholderText('Search selected object properties…');form.addRow(self.property_search)
        self.property_table=W.QTableWidget(0,3);self.property_table.setHorizontalHeaderLabels(['Property','Default','This object'])
        self.property_table.verticalHeader().hide();self.property_table.setAlternatingRowColors(True);self.property_table.setMinimumHeight(180)
        self.property_table.horizontalHeader().setSectionResizeMode(W.QHeaderView.ResizeMode.Stretch)
        self.property_table.setItemDelegateForColumn(2,ValueDelegate(self.property_table));form.addRow(self.property_table)
        self.reset_property_button=button('Reset value',self.reset_property,'undo');self.resource_button=button('Resource…',self.choose_resource,'assets');form.addRow(row(self.reset_property_button,self.resource_button))
        self.property_table.itemChanged.connect(self.property_changed);self.property_table.itemSelectionChanged.connect(self.property_controls)
        self.property_table.cellDoubleClicked.connect(lambda r,c:self.choose_resource() if c==2 and self.property_table.item(r,c).data(C.Qt.ItemDataRole.UserRole) in ('model','asset','sound') else None)
        self.property_search.textChanged.connect(self.filter_properties);self.property_fields={}
        for field in (self.name,self.x,self.y,self.end_x,self.end_y,self.yaw,self.offset): field.editingFinished.connect(self.edit)
        self.move_button=button('Move…',self.move,'select');self.delete_button=button('Delete',self.delete,'delete');box.addWidget(row(self.move_button,self.delete_button))
        box.addWidget(label('Game assets appear as labelled footprints here. Build creates the actual game actors and grounds them on the final terrain.','muted'))
    def update_controls(self,*args):
        if not hasattr(self,'place_button'): return
        doc=self.workshop.document;active=bool(doc and not self.workshop.busy and not self.workshop.viewer.built)
        self.place_button.setEnabled(active and self.palette.currentData() is not None and len(doc.scene['objects'])<1024)
        for control in (self.move_button,self.delete_button): control.setEnabled(active and self.selected is not None)
        self.details.setVisible(self.selected is not None);self.details.setEnabled(active)
        if doc:
            for widget,maximum in ((self.x,doc.extent[0]/2),(self.end_x,doc.extent[0]/2),(self.y,doc.extent[1]/2),(self.end_y,doc.extent[1]/2)): widget.setRange(-maximum,maximum)

    def filter_palette(self,text):
        current=self.palette.currentData();self.palette.clear()
        for item in a.OBJECTS:
            if item.get('placeable',item['kind'] not in ('skier','vehicle','system')) and text.lower() in (item['name']+' '+item['kind']).lower(): self.palette.addItem(item['name']+' • '+item['kind'],item)
        if current:
            for i in range(self.palette.count()):
                if self.palette.itemData(i)['class']==current['class']: self.palette.setCurrentIndex(i)
    def begin(self,item=None):
        if not isinstance(item,dict): item=self.palette.currentData()
        if not item or not self.place_button.isEnabled(): return
        self.placing=item;self.start=None;self.moving=False
        self.workshop.view.setCurrentIndex(0);self.workshop.choose_tool('place');self.workshop.tabs.setCurrentWidget(self)
        self.hint.setText('Click the lower terminal, then the upper terminal.' if item['kind']=='lift' else 'Click the terrain to place '+item['name']+'. Escape cancels.')
    def cancel(self):
        self.placing=None;self.start=None;self.moving=False;self.workshop.choose_tool('select');self.hint.setText('Placement cancelled. Choose an object to place another.')
    def commit(self,draft):
        self.workshop.document.change_scene(draft);self.workshop.mark_dirty();self.workshop.render();self.reload()
    def clicked(self,point):
        doc=self.workshop.document
        if self.workshop.viewer.built or self.workshop.busy: return
        x,y,_=point
        if abs(x)>doc.extent[0]/2 or abs(y)>doc.extent[1]/2: return
        if self.moving and self.selected:
            draft=copy.deepcopy(doc.scene);item=next(o for o in draft['objects'] if o['id']==self.selected)
            delta=[x-item['position'][0],y-item['position'][1]];item['position']=[x,y]
            if item['kind']=='lift': item['end_position']=[v+d for v,d in zip(item['end_position'],delta)]
            if item['kind']=='lift' and any(abs(item['end_position'][i])>doc.extent[i]/2 for i in (0,1)):
                self.hint.setText('Choose a position where both lift terminals remain on the terrain.');return
            self.commit(draft);self.cancel()
            return
        if self.placing:
            if len(doc.scene['objects'])>=1024: self.cancel();return
            if self.start is not None and ((x-self.start[0])**2+(y-self.start[1])**2)<4:
                self.hint.setText('Place the upper terminal at least 2 metres from the lower terminal.');return
            if self.placing['kind']=='lift' and self.start is None:
                self.start=[x,y];self.hint.setText('Now click the upper terminal.');return
            item=self.placing;draft=copy.deepcopy(doc.scene);ids={o['id'] for o in draft['objects']};number=1
            while 'object-'+str(number) in ids: number+=1
            placed={'id':'object-'+str(number),'class':item['class'],'kind':item['kind'],'name':item['name'],
                    'position':self.start or [x,y],'rotation_degrees':0,'height_offset_meters':0}
            if item['kind']=='lift': placed['end_position']=[x,y]
            draft['objects'].append(placed)
            self.selected=placed['id'];self.commit(draft);self.start=None;self.hint.setText('Placed '+item['name']+'. Click to place another, or Escape to select.')
            return
        candidates=[(min(((p[0]-x)**2+(p[1]-y)**2)**.5 for p in [o['position']]+([o['end_position']] if o['kind']=='lift' else [])),i) for i,o in enumerate(doc.scene['objects'])]
        if candidates:
            distance,index=min(candidates)
            if distance<max(15,self.workshop.viewer.opts['distance']*.02): self.list.setCurrentRow(index);self.workshop.tabs.setCurrentWidget(self)
    def reload(self):
        if not self.workshop.document: return
        self.loading=True;self.list.clear()
        for item in self.workshop.document.scene['objects']:
            entry=W.QListWidgetItem(self.display_name(item));entry.setData(C.Qt.ItemDataRole.UserRole,item['id']);self.list.addItem(entry)
        index=next((i for i in range(self.list.count()) if self.list.item(i).data(C.Qt.ItemDataRole.UserRole)==self.selected),-1)
        self.loading=False;self.list.setCurrentRow(index);self.select(index)
    def select(self,index):
        if self.loading: return
        objects=self.workshop.document.scene['objects'] if self.workshop.document else []
        item=objects[index] if 0<=index<len(objects) else None;self.selected=item['id'] if item else None
        self.loading=True
        for field in (self.name,self.x,self.y,self.end_x,self.end_y,self.yaw,self.offset): field.setEnabled(item is not None)
        if item:
            default=self.default_name(item);self.default_label.setText(default);self.name.setText(self.display_name(item));font=self.name.font();font.setBold(self.name.text()!=default);self.name.setFont(font);self.reset_name_button.setEnabled(self.name.text()!=default)
            self.x.setValue(item['position'][0]);self.y.setValue(item['position'][1]);self.yaw.setValue(item.get('rotation_degrees',0));self.offset.setValue(item.get('height_offset_meters',0))
        self.form.setRowVisible(self.end_row,bool(item and item['kind']=='lift'))
        self.form.setRowVisible(self.yaw,bool(item and item['kind']!='lift'))
        if item and item['kind']=='lift': self.end_x.setValue(item['end_position'][0]);self.end_y.setValue(item['end_position'][1]);self.yaw.setEnabled(False)
        self.load_properties(item);self.loading=False;self.workshop.viewer.scene_selected=self.selected;self.workshop.viewer.rebuild_scene();self.update_controls();self.property_controls()
    def edit(self):
        if self.loading or not self.selected: return
        draft=copy.deepcopy(self.workshop.document.scene);item=next(o for o in draft['objects'] if o['id']==self.selected)
        old=item['position'];new=[self.x.value(),self.y.value()];name=self.name.text().strip();item.update(name='' if not name or name==self.default_name(item) else name,position=new,rotation_degrees=self.yaw.value(),height_offset_meters=self.offset.value())
        if item['kind']=='lift':
            end=[self.end_x.value(),self.end_y.value()]
            item['end_position']=end if end!=item['end_position'] else [v+n-o for v,n,o in zip(item['end_position'],new,old)]
        if len(item['name'])>256: self.name.setText(item['name'][:256]);return
        if item['kind']=='lift':
            if any(abs(item['end_position'][i])>self.workshop.document.extent[i]/2 for i in (0,1)) or sum((item['position'][i]-item['end_position'][i])**2 for i in (0,1))<4:
                self.hint.setText('Both terminals must stay on the map and be at least 2 metres apart.');self.reload();return
        self.commit(draft)
    def move(self):
        if not self.selected: return
        self.placing=None;self.moving=True;self.workshop.view.setCurrentIndex(0);self.workshop.choose_tool('place');self.hint.setText('Click the new position. Escape cancels.')
    def delete(self):
        if not self.selected: return
        draft=copy.deepcopy(self.workshop.document.scene);draft['objects']=[o for o in draft['objects'] if o['id']!=self.selected];self.selected=None;self.commit(draft)

    def descriptors(self,item):
        fields=copy.deepcopy(next((o['fields'] for o in DEFAULTS['objects'] if o['class']==item['class']),{}))
        doc=self.workshop.document;relative='Objects/game-defaults.json'
        try:
            data=doc.pending.get(relative) or (doc.folder/relative).read_bytes()
            for obj in json.loads(data).get('objects',[]):
                if obj['class']==item['class']: fields.update(obj.get('fields') or {})
        except (OSError,ValueError,KeyError): pass
        return fields

    def default_name(self,item):
        return self.workshop.document.scene_default_name(item)

    def display_name(self,item):
        return self.workshop.document.scene_display_name(item)

    def reset_name(self):
        if not self.selected: return
        item=next(o for o in self.workshop.document.scene['objects'] if o['id']==self.selected)
        self.name.setText(self.default_name(item));self.edit()

    def load_properties(self,item):
        self.property_fields={};self.property_table.setRowCount(0)
        if not item: return
        doc=self.workshop.document;fields=self.descriptors(item)
        inherited={edit['field']:edit['value'] for edit in doc.object_edits if edit['object']==item['class'] and not edit.get('instance')}
        own={edit['field']:edit['value'] for edit in doc.object_edits if edit['object']==item['class'] and edit.get('instance')==item['id']}
        # Identity, preview and burial flags are runtime state; geometry and
        # instance naming have dedicated controls above the property table.
        omitted={'InstanceName','bIsPreview','bIsBuried'}
        self.property_fields={key:{**field,'default':inherited.get(key,field.get('default'))} for key,field in fields.items() if key not in omitted and isinstance(field,dict) and 'default' in field}
        self.property_table.setRowCount(len(self.property_fields))
        display=lambda v:'true' if v is True else 'false' if v is False else str(v)
        for index,(key,field) in enumerate(sorted(self.property_fields.items())):
            default=field['default'];value=own.get(key,default)
            for column,text in enumerate((key,display(default),display(value))):
                cell=W.QTableWidgetItem(text);cell.setToolTip(text);cell.setFlags(C.Qt.ItemFlag.ItemIsEnabled|C.Qt.ItemFlag.ItemIsSelectable)
                if column==2:
                    cell.setData(C.Qt.ItemDataRole.UserRole,field['type']);font=cell.font();font.setBold(value!=default);cell.setFont(font)
                    if field['type'] not in ('model','asset','sound'): cell.setFlags(cell.flags()|C.Qt.ItemFlag.ItemIsEditable)
                self.property_table.setItem(index,column,cell)
        self.filter_properties()

    def filter_properties(self,*args):
        for index in range(self.property_table.rowCount()): self.property_table.setRowHidden(index,self.property_search.text().lower() not in self.property_table.item(index,0).text().lower())

    def property_controls(self):
        index=self.property_table.currentRow();cell=self.property_table.item(index,2) if index>=0 else None
        active=bool(self.selected and not self.workshop.busy and not self.workshop.viewer.built)
        self.reset_property_button.setEnabled(bool(active and cell and cell.font().bold()));self.resource_button.setEnabled(bool(active and cell and cell.data(C.Qt.ItemDataRole.UserRole) in ('model','asset','sound')))

    def property_changed(self,cell):
        if self.loading or not self.selected or cell.column()!=2: return
        key=self.property_table.item(cell.row(),0).text();field=self.property_fields[key];kind=field['type'];text=cell.text()
        try:
            value=int(text) if kind=='integer' else float(text) if kind=='number' else text=='true' if kind=='boolean' and text in ('true','false') else text
            self.workshop.document.change_instance_property(self.selected,key,kind,value,field['default'])
            self.workshop.mark_dirty();self.reload();self.workshop.render()
        except (ValueError,a.ManifestError) as error: self.hint.setText(str(error));self.reload()

    def reset_property(self):
        index=self.property_table.currentRow()
        if index<0: return
        key=self.property_table.item(index,0).text();value=self.property_fields[key]['default']
        self.property_table.item(index,2).setText('true' if value is True else 'false' if value is False else str(value))

    def choose_resource(self):
        index=self.property_table.currentRow()
        if index<0: return
        cell=self.property_table.item(index,2);kind=cell.data(C.Qt.ItemDataRole.UserRole)
        if kind not in ('model','asset','sound'): return
        key=self.property_table.item(index,0).text();picker=ResourcePicker(self.workshop,kind,self.property_fields[key]['default'])
        if picker.exec(): cell.setText(picker.value)
