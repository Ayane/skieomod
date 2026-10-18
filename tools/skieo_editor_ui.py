"""Qt desktop workshop: local source projects, 3D terrain and authoring editors."""
from __future__ import annotations
import copy
import json
import math
import os
from pathlib import Path
import queue
import re
import subprocess
import sys
import threading
import secrets
import time
import numpy as np
from PySide6 import QtCore as C, QtGui as G, QtWidgets as W
if __package__ == "tools":
    from . import skieo_updates as updates
    from . import skieo_editor as editor, skieo_project as projects, skieo_install as desktop, skieo_authoring as authoring
    from .skieo_editor_widgets import STYLE, icon, label, button, row, FilePicker, Spin, Combo, scroll, editor_font
    from .skieo_editor_3d import TerrainView
    from .skieo_editor_scene import ScenePanel
    from .skieo_editor_config import TERRAIN_FORMATS, ELEVATIONS, PROCESSING, VEGETATION, EditorPreferences, STARTUP_CHOICES
    from .skieo_editor_graph import TriggerEditor
    from .skieo_editor_resources import ResourceEditor, ObjectEditor
else:
    import skieo_updates as updates
    import skieo_editor as editor, skieo_project as projects, skieo_install as desktop, skieo_authoring as authoring
    from skieo_editor_widgets import STYLE, icon, label, button, row, FilePicker, Spin, Combo, scroll, editor_font
    from skieo_editor_3d import TerrainView
    from skieo_editor_scene import ScenePanel
    from skieo_editor_config import TERRAIN_FORMATS, ELEVATIONS, PROCESSING, VEGETATION, EditorPreferences, STARTUP_CHOICES
    from skieo_editor_graph import TriggerEditor
    from skieo_editor_resources import ResourceEditor, ObjectEditor


class HeightmapSettings(W.QWidget):
    def __init__(self,parent=None):
        super().__init__(parent)
        box=W.QVBoxLayout(self);box.setContentsMargins(0,0,0,0)
        form=W.QFormLayout();form.setFieldGrowthPolicy(W.QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow);form.setRowWrapPolicy(W.QFormLayout.RowWrapPolicy.WrapAllRows);box.addLayout(form)
        self.spacing=Spin(8,.001,1000000,3,' m')
        self.mode=Combo(ELEVATIONS)
        self.low=Spin(0,-20000,20000);self.high=Spin(1000,-20000,20000)
        self.scale=Spin(.01,.000000001,1000000,9);self.offset=Spin(0,-20000,20000)
        self.range_row=row(self.low,self.high);self.export_row=row(self.scale,self.offset)
        form.addRow('Sample spacing',self.spacing);form.addRow('Elevation',self.mode)
        self.form=form
        form.addRow('Lowest / highest (m)',self.range_row);form.addRow('Scale / offset',self.export_row)
        self.note=label('For a first test, relative relief is enough. Real altitudes require your export metadata.','muted');box.addWidget(self.note)
        advanced=W.QGroupBox('File encoding • advanced');advanced.setCheckable(True);advanced.setChecked(False)
        af=W.QFormLayout(advanced);af.setRowWrapPolicy(W.QFormLayout.RowWrapPolicy.WrapAllRows)
        self.format=Combo(TERRAIN_FORMATS);self.width=W.QLineEdit();self.height=W.QLineEdit()
        for field in (self.width,self.height): field.setPlaceholderText('Automatic');field.setValidator(G.QIntValidator(2,16384,field))
        self.row_order=Combo(['north_to_south','south_to_north']);self.stride=W.QLineEdit();self.stride.setPlaceholderText('Automatic');self.stride.setValidator(G.QIntValidator(1,64,self.stride))
        af.addRow('Format',self.format);af.addRow('Samples across / down',row(self.width,self.height));af.addRow('First row',self.row_order);af.addRow('Mesh stride',self.stride)
        af.addRow(label('PNG dimensions come from its header. Square raw R16 can omit dimensions; rectangular R16 needs at least one side.','muted'))
        self.advanced=advanced;box.addWidget(advanced)
        def advanced_controls(visible):
            for index in range(af.rowCount()): af.setRowVisible(index,visible)
        advanced.toggled.connect(advanced_controls);advanced_controls(False)
        self.mode.currentIndexChanged.connect(self.elevation_controls);self.elevation_controls()
    def elevation_controls(self,*args):
        self.form.setRowVisible(self.range_row,self.mode.currentIndex()==1);self.form.setRowVisible(self.export_row,self.mode.currentIndex()==2)
    def load(self,settings,elevation=None):
        self.spacing.setValue(settings.get('spacing_meters',8))
        self.format.setCurrentText(next((name for name,fmt in TERRAIN_FORMATS.items() if fmt==settings.get('format')),'Automatic'))
        dims=settings.get('vertices',[None,None])
        self.width.setText('' if dims[0] is None else str(dims[0]));self.height.setText('' if dims[1] is None else str(dims[1]))
        self.row_order.setCurrentText(settings.get('row_order','north_to_south'));self.stride.setText(str(settings.get('sample_step','')))
        self.mode.setCurrentIndex(1 if 'elevation_meters' in settings else 2 if 'height_scale_meters' in settings else 0)
        low,high=settings.get('elevation_meters',elevation or [0,1000]);self.low.setValue(low);self.high.setValue(high)
        self.scale.setValue(settings.get('height_scale_meters',.01));self.offset.setValue(settings.get('height_offset_meters',0))
    def values(self,original=None):
        for field in (self.width,self.height,self.stride):
            if field.text() and not field.hasAcceptableInput(): raise ValueError('Complete the sample dimensions and stride, or leave them automatic.')
        if self.mode.currentIndex()==1 and self.high.value()<=self.low.value(): raise ValueError('The highest elevation must be above the lowest.')
        settings=copy.deepcopy(original or {})
        settings['spacing_meters']=self.spacing.value();settings['row_order']=self.row_order.currentText()
        fmt=TERRAIN_FORMATS[self.format.currentText()]
        if fmt: settings['format']=fmt
        else: settings.pop('format',None)
        dims=[int(field.text()) if field.text() else None for field in (self.width,self.height)]
        if any(v is not None for v in dims): settings['vertices']=dims
        else: settings.pop('vertices',None)
        if self.stride.text(): settings['sample_step']=int(self.stride.text())
        else: settings.pop('sample_step',None)
        for key in ('elevation_meters','height_scale_meters','height_offset_meters'): settings.pop(key,None)
        if self.mode.currentIndex()==1: settings['elevation_meters']=[self.low.value(),self.high.value()]
        elif self.mode.currentIndex()==2: settings.update(height_scale_meters=self.scale.value(),height_offset_meters=self.offset.value())
        return settings


class SaveFolder(W.QFileDialog):
    """A folder chooser whose acceptance is limited to an empty destination."""
    def __init__(self, parent):
        super().__init__(parent, 'Save new map • choose an empty folder', str(Path.cwd()))
        self.setOption(W.QFileDialog.Option.DontUseNativeDialog)
        self.setFileMode(W.QFileDialog.FileMode.Directory)
        self.setOption(W.QFileDialog.Option.ShowDirsOnly)
        self.setAcceptMode(W.QFileDialog.AcceptMode.AcceptSave)
        self.setLabelText(W.QFileDialog.DialogLabel.Accept, 'Save map here')
        self.hint=label('Choose an empty folder, or create one here.','muted')
        self.layout().addWidget(self.hint, self.layout().rowCount(), 0, 1, self.layout().columnCount())
        self.currentChanged.connect(self.check);self.directoryEntered.connect(self.check)
        for control in self.findChildren(W.QLineEdit): control.textChanged.connect(self.check)
        self.check()
    def check(self,*args):
        files=self.selectedFiles();folder=Path(files[0]) if files else None
        try:
            available=bool(folder and folder.is_dir() and not any(folder.iterdir()) and os.access(folder,os.W_OK))
        except OSError: available=False
        self.hint.setText('Save your map in this folder.' if available else 'Choose an empty writable folder, or create one here.')
        for box in self.findChildren(W.QDialogButtonBox):
            for control in box.buttons():
                if box.buttonRole(control) in (W.QDialogButtonBox.ButtonRole.AcceptRole,W.QDialogButtonBox.ButtonRole.YesRole): control.setEnabled(available)
        return available
    def accept(self):
        if self.check(): super().accept()


class ImportHeightmap(W.QDialog):
    checked=C.Signal(object)
    def __init__(self,workshop,file=None):
        super().__init__(workshop);self.workshop=workshop;self.generation=0;self.prepared=None
        self.setWindowTitle('Import heightmap');self.resize(680,640)
        box=W.QVBoxLayout(self);box.addWidget(label('Import your heightmap','heading'))
        box.addWidget(label('Choose a source and preview its dimensions before importing. The original file is preserved.','muted'))
        self.file=FilePicker('Choose your original heightmap','Heightmaps (*.r16 *.raw *.png);;All files (*)',value=file or '')
        box.addWidget(self.file);self.settings=HeightmapSettings();self.settings.spacing.setValue(workshop.document.spacing)
        box.addWidget(scroll(self.settings),1)
        self.feedback=label('Choose a heightmap.','muted');box.addWidget(self.feedback)
        self.import_button=button('Import heightmap',self.import_file,'import',True);self.import_button.setEnabled(False)
        box.addWidget(row(button('Cancel',self.reject),self.import_button))
        self.timer=C.QTimer(self);self.timer.setSingleShot(True);self.timer.timeout.connect(self.preflight)
        self.checked.connect(self.validation_finished);self.file.changed.connect(self.schedule)
        for widget in self.settings.findChildren(W.QWidget):
            signal=widget.textChanged if isinstance(widget,W.QLineEdit) else widget.valueChanged if isinstance(widget,W.QDoubleSpinBox) else widget.currentTextChanged if isinstance(widget,W.QComboBox) else None
            if signal: signal.connect(self.schedule)
        self.schedule()
    def schedule(self,*args):
        self.generation+=1;self.prepared=None;self.import_button.setEnabled(False);self.timer.start(180)
    def preflight(self):
        generation=self.generation;path=self.file.value()
        if not path: self.feedback.setText('Choose a heightmap.');return
        try: settings=self.settings.values()
        except ValueError as error: self.feedback.setText(str(error));return
        self.feedback.setText('Reading heightmap…');manifest=copy.deepcopy(self.workshop.document.manifest)
        def work():
            try: result=(path,settings,editor.inspect_source(manifest,path,settings));error=None
            except (ValueError,OSError,editor.ManifestError) as failure: result=None;error=str(failure)
            try: self.checked.emit((generation,result,error))
            except RuntimeError: pass
        threading.Thread(target=work,daemon=True).start()
    def validation_finished(self,payload):
        generation,result,error=payload
        if generation!=self.generation: return
        self.prepared=result;self.import_button.setEnabled(result is not None)
        if error: self.feedback.setText(error);return
        terrain=result[2][0];width,height=terrain['source']['vertices']
        self.feedback.setText(f'{width:,} × {height:,} samples • {terrain["size_meters"][0]:g} × {terrain["size_meters"][1]:g} m • ready to import')
    def import_file(self):
        if not self.prepared: return
        path,settings,prepared=self.prepared
        self.workshop.document.import_heightmap(path,settings,prepared=prepared)
        self.workshop.load_forms();self.workshop.view.setCurrentIndex(0);self.workshop.viewer.built=False
        self.workshop.render();self.workshop.viewer.fit_map();self.accept()


class Overview(W.QLabel):
    def __init__(self,workshop):
        super().__init__();self.workshop=workshop;self.setMinimumHeight(140);self.setMaximumHeight(180);self.setAlignment(C.Qt.AlignmentFlag.AlignCenter)
        self.setToolTip('Click to move the camera to this part of the map')
    def mousePressEvent(self,event):
        if not self.workshop.document or self.pixmap() is None: return
        pix=self.pixmap();x=(self.width()-pix.width())/2;y=(self.height()-pix.height())/2
        u=(event.position().x()-x)/pix.width();v=(event.position().y()-y)/pix.height()
        if 0<=u<=1 and 0<=v<=1:
            sx,sy=self.workshop.document.extent;xx=(u-.5)*sx;yy=(v-.5)*sy
            self.workshop.viewer.opts['center']=G.QVector3D(xx,-yy,self.workshop.viewer.height_at(xx,yy));self.workshop.viewer.update()


class PreferencesDialog(W.QDialog):
    def __init__(self,workshop):
        super().__init__(workshop);self.setWindowTitle('Preferences');self.setMinimumWidth(420)
        box=W.QVBoxLayout(self);form=W.QFormLayout();box.addLayout(form)
        self.startup=Combo([])
        for value,title in STARTUP_CHOICES.items(): self.startup.addItem(title,value)
        self.startup.setCurrentIndex(self.startup.findData(workshop.preferences.startup))
        form.addRow('At startup',self.startup)
        box.addWidget(label('This choice applies next time you open the workshop. A project passed on the command line opens directly.','muted'))
        buttons=W.QDialogButtonBox(W.QDialogButtonBox.StandardButton.Save|W.QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject);box.addWidget(buttons)


class MapEditor(W.QMainWindow):
    def __init__(self,document=None,*,path=None):
        super().__init__()
        self.document=None;self.busy=False;self.form_dirty=False;self.loading=True;self.events=queue.Queue();self.fields={};self.groups={};self.dialogs=[];self.actions={};self.validation_problem=''
        self.test_session=secrets.token_hex(16);self.test_loading=False;self.session_poll=0;self.source_check=None
        self.update_process=None;self.update_poll=0
        self.preferences=EditorPreferences()
        self.refresh_game()
        self.setWindowTitle('SkiEO Map Workshop');self.resize(1500,980);self.setMinimumSize(1100,720)
        self.setWindowIcon(icon('objects','#087f67'));self.setAcceptDrops(True)
        self.toolbar();self.workspace();self.shortcuts()
        self.poll_timer=C.QTimer(self);self.poll_timer.timeout.connect(self.poll);self.poll_timer.start(40)
        self.render_timer=C.QTimer(self);self.render_timer.setSingleShot(True);self.render_timer.timeout.connect(self.render)
        self.loading=False
        self.refresh_recent_projects();self.show_welcome()
        if document: self.loaded(document)
        elif path: self.open_project(path)
        elif self.preferences.startup=='new': self.new_project()
        elif self.preferences.startup=='last' and self.preferences.last_project(): self.open_project(self.preferences.last_project())
        self.check_updates()

    def showEvent(self,event):
        super().showEvent(event)
        # Qt can finish constructing action widgets after the document loads.
        # Reconcile the visible controls against the ready document as well.
        self.refresh_controls()
        C.QTimer.singleShot(0,self.refresh_controls)

    def refresh_controls(self):
        if self.document: self.validate_forms()
        else: self.update_actions()

    def action(self,toolbar,text,name,callback,key=None):
        action=G.QAction(icon(name),text,self);action.setToolTip(text+(f' ({key})' if key else ''));action.triggered.connect(callback)
        if key: action.setShortcut(G.QKeySequence(key))
        toolbar.addAction(action);self.actions[text.lower()]=action;return action

    def toolbar(self):
        bar=self.addToolBar('Workshop');self.workshop_bar=bar;bar.setMovable(False);bar.setIconSize(C.QSize(23,23));bar.setToolButtonStyle(C.Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        self.action(bar,'New','new',self.new_project,'Ctrl+N');self.action(bar,'Open','open',self.open_dialog,'Ctrl+O')
        self.action(bar,'Save','save',self.save,'Ctrl+S');self.action(bar,'Import','import',self.import_dialog,'Ctrl+I')
        bar.addSeparator();self.action(bar,'Undo','undo',self.undo,'Ctrl+Z');self.action(bar,'Redo','redo',self.redo,'Ctrl+Y')
        bar.addSeparator();self.action(bar,'Triggers','graph',lambda: self.open_editor(TriggerEditor))
        self.action(bar,'Resources','assets',lambda: self.open_editor(ResourceEditor));self.action(bar,'Objects','objects',lambda: self.open_editor(ObjectEditor))
        space=W.QWidget();space.setSizePolicy(W.QSizePolicy.Policy.Expanding,W.QSizePolicy.Policy.Preferred);bar.addWidget(space)
        self.action(bar,'Test','test',lambda: self.command('test'));self.action(bar,'Build','build',lambda: self.command('build'));self.action(bar,'Play','play',lambda: self.command('run'),'F5')
        menu=self.menuBar();file=menu.addMenu('File');file.addAction(self.actions['new']);file.addAction(self.actions['open'])
        self.recent_menu=file.addMenu('Recent maps');self.recent_menu.aboutToShow.connect(self.refresh_recent_projects);file.addAction(self.actions['save'])
        self.close_map_action=file.addAction('Close map',self.close_project);self.close_map_action.setShortcut(G.QKeySequence('Ctrl+W'))
        self.reveal_action=file.addAction('Show project folder',self.reveal)
        preferences=menu.addMenu('Preferences');self.preferences_action=preferences.addAction('Settings…',self.configure_preferences)
        game=menu.addMenu('Game');game.addAction('Configure Steam installation…',self.configure_game)
        self.check_updates_action=game.addAction('Check for updates',lambda: self.check_updates(force=True))
        self.update_loader_action=game.addAction('Update Custom Map loader',self.update_loader)
        game.addAction('Upgrade skieomod…',lambda: G.QDesktopServices.openUrl(C.QUrl('https://skieomod.emillon.fr/downloads/getting-started.md')))
        help_menu=menu.addMenu('Help')
        help_menu.addAction('Editor map tutorial',lambda: G.QDesktopServices.openUrl(C.QUrl('https://skieomod.emillon.fr/tutorials/editor/')))
        help_menu.addAction('Heightmap tutorial',lambda: G.QDesktopServices.openUrl(C.QUrl('https://skieomod.emillon.fr/tutorials/heightmap/')))
        help_menu.addAction('Ticket Office model tutorial',lambda: G.QDesktopServices.openUrl(C.QUrl('https://skieomod.emillon.fr/tutorials/ticket-office/')))
        help_menu.addAction('Mapmod tutorial',lambda: G.QDesktopServices.openUrl(C.QUrl('https://skieomod.emillon.fr/tutorials/mapmods/')))

    def workspace(self):
        central=W.QWidget();layout=W.QVBoxLayout(central);layout.setContentsMargins(12,10,12,8);self.setCentralWidget(central)
        split=W.QSplitter();layout.addWidget(split,1)
        self.left=W.QWidget();self.left.setMinimumWidth(190);self.left.setMaximumWidth(240);left=W.QVBoxLayout(self.left);left.setContentsMargins(8,6,12,6)
        left.addWidget(label('TERRAIN TOOLS','section'));self.tools=G.QActionGroup(self);self.tools.setExclusive(True)
        self.tool_buttons={}
        for index,(tool,title) in enumerate([('select','Select'),('place','Place object'),('raise','Raise'),('lower','Lower'),('flatten','Level'),('smooth','Smooth'),('trees','Plant trees'),('erase_trees','Erase trees')]):
            action=G.QAction(icon('objects' if tool=='place' else tool),title,self);action.setCheckable(True);action.setData(tool);action.setToolTip(title+' • '+('P' if tool=='place' else str(1 if tool=='select' else index)))
            self.tools.addAction(action);action.triggered.connect(lambda checked,t=tool: self.choose_tool(t))
            widget=W.QToolButton();widget.setDefaultAction(action);widget.setToolButtonStyle(C.Qt.ToolButtonStyle.ToolButtonTextBesideIcon);widget.setIconSize(C.QSize(24,24));widget.setSizePolicy(W.QSizePolicy.Policy.Expanding,W.QSizePolicy.Policy.Preferred)
            widget.setMinimumHeight(41);self.tool_buttons[tool]=widget;left.addWidget(widget)
        self.tools.actions()[0].setChecked(True)
        self.radius_label=label('Brush radius','section');left.addWidget(self.radius_label);self.radius=Spin(60,.5,5000,1,' m');left.addWidget(self.radius)
        self.strength_label=label('Height per dab','muted');left.addWidget(self.strength_label);self.strength=Spin(5,.001,1000,2,' m');left.addWidget(self.strength)
        self.level_label=label('Level height (m)','muted');self.level=W.QLineEdit();self.level.setValidator(G.QDoubleValidator(-1e9,1e9,6,self.level));self.level.setPlaceholderText('Pick at start of stroke');left.addWidget(self.level_label);left.addWidget(self.level)
        self.level.textChanged.connect(self.update_actions)
        self.spacing_label=label('Tree spacing','muted');self.tree_spacing=Spin(12,.1,1000,1,' m');left.addWidget(self.spacing_label);left.addWidget(self.tree_spacing)
        left.addWidget(label('OVERVIEW','section'));self.overview=Overview(self);left.addWidget(self.overview)
        left.addWidget(label('PROJECT SOURCES','section'));self.files=W.QTreeWidget();self.files.setHeaderHidden(True);left.addWidget(self.files,1)
        self.files.itemDoubleClicked.connect(self.open_source);split.addWidget(self.left)
        centre=W.QWidget();box=W.QVBoxLayout(centre);box.setContentsMargins(0,0,0,0)
        self.header=label('Your mountain starts here','heading');box.addWidget(self.header)
        self.stack=W.QStackedWidget();box.addWidget(self.stack,1)
        welcome=W.QWidget();welcome_box=W.QVBoxLayout(welcome);welcome_box.setContentsMargins(60,40,60,40);welcome_box.addStretch()
        welcome_box.addWidget(label('Choose a map to open','heading'))
        welcome_box.addWidget(label('Pick a recent map, browse to a source project or create a new map.','muted'))
        welcome_box.addWidget(row(button('Create a map',self.new_project,'new',True),button('Open source project',self.open_dialog,'open')))
        welcome_box.addWidget(label('Recent maps','section'))
        self.recent_list=W.QListWidget();self.recent_list.setMinimumHeight(160);welcome_box.addWidget(self.recent_list,1)
        self.recent_list.itemActivated.connect(self.open_recent_item)
        self.recent_open_button=button('Open selected map',self.open_selected_recent,'open');welcome_box.addWidget(self.recent_open_button)
        self.recent_list.currentItemChanged.connect(lambda *args:self.update_recent_controls())
        self.recent_empty=label('No recent maps yet. Open a source project or create and save a map to add it here.','muted');welcome_box.addWidget(self.recent_empty)
        welcome_box.addStretch();self.stack.addWidget(welcome)
        terrain=W.QWidget();terrain_box=W.QVBoxLayout(terrain);terrain_box.setContentsMargins(0,0,0,0)
        self.view=Combo(['Source terrain','Last built terrain']);self.view.currentIndexChanged.connect(self.change_view)
        terrain_box.addWidget(row(self.view,button('Fit map',lambda: self.viewer.fit_map(),'fit')))
        self.viewer=TerrainView();terrain_box.addWidget(self.viewer,1)
        self.viewer.stroke.connect(self.paint);self.viewer.selected.connect(self.scene_click);self.viewer.moved.connect(self.coordinates)
        terrain_box.addWidget(label('Left: select / paint   ·   Middle: grab terrain   ·   Right: orbit   ·   Wheel: zoom','muted'))
        self.summary=label('','muted');terrain_box.addWidget(self.summary);self.stack.addWidget(terrain)
        self.log=W.QPlainTextEdit();self.log.setReadOnly(True);self.log.setFont(editor_font());self.log.setMaximumHeight(135);self.log.setPlaceholderText('Build output appears here.');box.addWidget(self.log)
        split.addWidget(centre)
        self.right=W.QWidget();self.right.setMinimumWidth(340);self.right.setMaximumWidth(400);right=W.QVBoxLayout(self.right);right.setContentsMargins(8,0,0,0)
        self.tabs=W.QTabWidget();right.addWidget(self.tabs,1)
        self.terrain_panel();self.nature_panel();self.map_panel()
        self.scene_panel=ScenePanel(self);self.tabs.addTab(self.scene_panel,'Objects')
        self.viewer.cancelled.connect(self.scene_panel.cancel)
        self.form_feedback=label('','muted');right.addWidget(self.form_feedback)
        self.apply_button=button('Apply settings',self.apply,'test',True);right.addWidget(self.apply_button)
        self.tabs.currentChanged.connect(self.context_controls)
        split.addWidget(self.right);split.setSizes([215,915,360])
        self.progress=W.QProgressBar();self.progress.setRange(0,0);self.progress.setMaximumWidth(200);self.progress.hide();self.statusBar().addPermanentWidget(self.progress)
        self.update_notice=label('','muted');self.statusBar().addPermanentWidget(self.update_notice)
        self.radius.valueChanged.connect(lambda value: setattr(self.viewer,'radius',value));self.choose_tool('select')

    def terrain_panel(self):
        body=W.QWidget();box=W.QVBoxLayout(body);box.addWidget(label('Heightmap source','section'))
        self.source_label=label('','muted');self.source_label.setTextInteractionFlags(C.Qt.TextInteractionFlag.TextSelectableByMouse);box.addWidget(self.source_label)
        box.addWidget(button('Choose another heightmap…',self.import_dialog,'import'))
        self.source=HeightmapSettings();box.addWidget(self.source)
        box.addWidget(label('Surface treatments','section'));self.fields['processing.resolution']=Spin(513,17,1025,0);box.addWidget(label('Processing resolution','muted'));box.addWidget(self.fields['processing.resolution'])
        for method,fields in PROCESSING.items():
            group=W.QGroupBox(method.replace('_',' ').capitalize());group.setCheckable(True);group.setChecked(False);form=W.QFormLayout(group)
            self.groups['processing.'+method]=group
            for key,title,default,low,high,kind in fields:
                widget=Spin(default,low,high,0 if kind is int else 3);self.fields[f'processing.{method}.{key}']=widget;form.addRow(label(title,wrap=True),widget)
            box.addWidget(group)
            def treatments(visible,form=form):
                for index in range(form.rowCount()): form.setRowVisible(index,visible)
            group.toggled.connect(treatments);treatments(False)
        box.addWidget(label('Build always starts from the source; erosion does not accumulate each time.','muted'));box.addStretch();self.tabs.addTab(scroll(body),'Terrain')
        self.track(body)

    def nature_panel(self):
        body=W.QWidget();box=W.QVBoxLayout(body);box.addWidget(label('Forest & ground cover','section'))
        self.forest_mode=Combo(['None','Manual','Automatic']);box.addWidget(self.forest_mode)
        box.addWidget(label('Automatic trees appear after Build. Manual brushes switch the source to Manual.','muted'))
        self.nature_groups={};self.cover=W.QCheckBox('Bake grass / rock ground colours');box.addWidget(self.cover)
        for section,fields in VEGETATION.items():
            group=W.QGroupBox(section.replace('_',' ').capitalize());self.nature_groups[section]=group;form=W.QFormLayout(group)
            for key,title,default,low,high,kind in fields:
                widget=Combo(['16','32','64','128','256','512']) if key=='texture_size' else Spin(default,low,high,0 if kind is int else 3);self.fields[f'vegetation.{section}.{key}']=widget;form.addRow(label(title),widget)
            box.addWidget(group)
        self.exclude_label=label('Automatic forest clearings • [west, north, east, south] metres','muted');box.addWidget(self.exclude_label)
        self.exclude=W.QPlainTextEdit('[]');self.exclude.setMaximumHeight(100);box.addWidget(self.exclude)
        box.addStretch();self.tabs.addTab(scroll(body),'Nature');self.track(body)

    def map_panel(self):
        body=W.QWidget();box=W.QVBoxLayout(body);box.addWidget(label('Map details','section'));form=W.QFormLayout();box.addLayout(form)
        for key,title in [('name','Name'),('authors','Authors'),('id','Package ID'),('version','Version'),('license','Licence')]:
            widget=W.QLineEdit();self.fields['map.'+key]=widget;form.addRow(title,widget)
        self.description=W.QPlainTextEdit();self.description.setMaximumHeight(120);box.addWidget(label('Description','muted'));box.addWidget(self.description)
        for key,title in [('location','Location'),('latitude','Latitude'),('longitude','Longitude'),('dependencies','Dependencies')]:
            widget=W.QLineEdit();self.fields['map.'+key]=widget;form.addRow(title,widget)
        self.fields['map.dependencies'].setPlaceholderText('package.id >=1.0.0; another.id *')
        box.addWidget(label('Triggers, resources and object properties have their own editors in the top toolbar.','muted'));box.addStretch();self.tabs.addTab(scroll(body),'Map');self.track(body)

    def track(self,widget):
        for child in widget.findChildren(W.QWidget):
            signal=child.textEdited if isinstance(child,W.QLineEdit) else child.textChanged if isinstance(child,W.QPlainTextEdit) else child.valueChanged if isinstance(child,W.QDoubleSpinBox) else child.currentIndexChanged if isinstance(child,W.QComboBox) else child.toggled if isinstance(child,(W.QCheckBox,W.QGroupBox)) else None
            if signal is not None: signal.connect(self.form_changed)

    def form_changed(self,*args):
        if not self.loading: self.form_dirty=True;self.mark_dirty();self.validate_forms()
    def mark_dirty(self):
        if self.document:
            dirty=self.document.dirty or self.form_dirty
            self.setWindowTitle(('* ' if dirty else '')+self.document.manifest['metadata']['name']+(' • Unsaved' if not self.document.has_folder else '')+' • SkiEO Map Workshop')
            self.update_actions()

    def loaded(self,doc):
        self.document=doc;self.source_check=None;self.viewer.built=False;self.viewer.set_document(doc);self.stack.setCurrentIndex(1);self.left.setEnabled(True);self.right.setEnabled(True)
        self.loading=True;self.view.setCurrentIndex(0);self.loading=False;self.load_forms();self.choose_tool('select');self.scene_panel.reload();self.render()
        self.statusBar().showMessage('New map ready. Sculpt or add objects; Save will ask for a folder.' if not doc.has_folder else 'Map opened. Source changes are saved in the project folder.')
        self.validate_forms()
        self.remember_project()

    def show_welcome(self):
        self.stack.setCurrentIndex(0);self.header.setText('Open a map');self.update_actions()

    def close_project(self):
        if not self.discard_or_save(): return
        self.document=None;self.form_dirty=False;self.validation_problem='';self.form_feedback.clear()
        self.render_timer.stop();self.viewer.document=None;self.viewer.built=False
        self.scene_panel.selected=None;self.scene_panel.placing=None;self.scene_panel.start=None;self.scene_panel.moving=False
        self.scene_panel.list.clear();self.files.clear();self.overview.clear();self.summary.clear()
        self.setWindowTitle('SkiEO Map Workshop');self.refresh_recent_projects();self.show_welcome()
        self.statusBar().showMessage('Choose a recent map, open a source project or create a new map.')

    def configure_preferences(self):
        dialog=PreferencesDialog(self)
        if dialog.exec()!=W.QDialog.DialogCode.Accepted: return
        previous=self.preferences.startup;self.preferences.startup=dialog.startup.currentData()
        try: self.preferences.save()
        except OSError as error: self.preferences.startup=previous;self.error(error);return
        self.statusBar().showMessage('Preferences saved. The startup choice applies next time.')

    def remember_project(self):
        try: self.preferences.remember(self.document)
        except OSError as error: self.error(error)
        self.refresh_recent_projects()

    def refresh_recent_projects(self):
        self.recent_menu.clear();self.recent_list.clear()
        for project in self.preferences.recent_projects:
            path=project['path'];available=Path(path).is_file();name=project['name']
            title=name if available else name+' (unavailable)'
            action=self.recent_menu.addAction(title,lambda checked=False,p=path:self.open_project(p))
            action.setData(path);action.setToolTip(str(Path(path).parent));action.setEnabled(available)
            item=W.QListWidgetItem(title+'\n'+str(Path(path).parent));item.setData(C.Qt.ItemDataRole.UserRole,path);item.setToolTip(path)
            if not available: item.setFlags(item.flags() & ~C.Qt.ItemFlag.ItemIsEnabled & ~C.Qt.ItemFlag.ItemIsSelectable)
            self.recent_list.addItem(item)
        has_recent=bool(self.preferences.recent_projects);self.recent_empty.setVisible(not has_recent)
        self.recent_list.setVisible(has_recent);self.recent_open_button.setVisible(has_recent)
        if not has_recent: self.recent_menu.addAction('No recent maps').setEnabled(False)
        self.update_recent_controls()

    def update_recent_controls(self):
        item=self.recent_list.currentItem()
        self.recent_open_button.setEnabled(not self.busy and item is not None and bool(item.flags() & C.Qt.ItemFlag.ItemIsEnabled))

    def open_selected_recent(self):
        self.open_recent_item(self.recent_list.currentItem())

    def open_recent_item(self,item):
        if item is not None and item.flags() & C.Qt.ItemFlag.ItemIsEnabled:
            self.open_project(item.data(C.Qt.ItemDataRole.UserRole))

    def load_forms(self):
        self.loading=True;doc=self.document;build=doc.manifest.get('build',{});source=build.get('heightmap',doc.manifest['terrain']['source'])
        self.source_label.setText(build.get('heightmap',{}).get('file','Starter terrain • import your heightmap or sculpt this source'))
        self.source.load(source,doc.elevation)
        processing=source.get('processing',{});self.fields['processing.resolution'].setValue(processing.get('resolution',513))
        for method,fields in PROCESSING.items():
            self.groups['processing.'+method].setChecked(method in processing)
            for key,title,default,low,high,kind in fields: self.fields[f'processing.{method}.{key}'].setValue(processing.get(method,{}).get(key,default))
        vegetation=build.get('vegetation',{});self.forest_mode.setCurrentText(doc.forest_mode);self.cover.setChecked('vegetation' in build and vegetation.get('ground_cover',{}).get('enabled',True))
        for section,fields in VEGETATION.items():
            for key,title,default,low,high,kind in fields:
                if section=='biome' and key in ('tree_line_meters','alpine_line_meters') and 'elevation_meters' not in source and 'height_scale_meters' not in source: default=900 if key=='tree_line_meters' else 1100
                widget=self.fields[f'vegetation.{section}.{key}'];value=vegetation.get(section,{}).get(key,default)
                widget.setCurrentText(str(value)) if isinstance(widget,Combo) else widget.setValue(value)
        self.exclude.setPlainText(json.dumps(vegetation.get('trees',{}).get('exclude',[])))
        metadata=doc.manifest['metadata']
        for key in ('name','version','license'): self.fields['map.'+key].setText(metadata.get(key,''))
        self.fields['map.authors'].setText(', '.join(metadata['authors']));self.fields['map.id'].setText(doc.manifest['id']);self.description.setPlainText(metadata.get('description',''))
        location=doc.manifest.get('location',{})
        self.fields['map.location'].setText(location.get('label',''))
        for key in ('latitude','longitude'): self.fields['map.'+key].setText(str(location.get(key,'')))
        self.fields['map.dependencies'].setText('; '.join(item['id']+' '+item.get('version','*') for item in doc.manifest.get('dependencies',[])))
        self.header.setText(metadata['name']);self.form_dirty=False;self.loading=False;self.refresh_files();self.mark_dirty();self.validate_forms()

    def numbers(self,prefix,fields):
        return {key:kind(self.fields[f'{prefix}.{key}'].currentText()) if isinstance(self.fields[f'{prefix}.{key}'],Combo) else kind(self.fields[f'{prefix}.{key}'].value()) for key,title,default,low,high,kind in fields}

    def form_draft(self):
        doc=self.document;draft=copy.deepcopy(doc.manifest)
        for key in ('name','version','license'): draft['metadata'][key]=self.fields['map.'+key].text().strip()
        draft['metadata']['authors']=[name.strip() for name in self.fields['map.authors'].text().split(',') if name.strip()]
        draft['metadata']['description']=self.description.toPlainText();draft['id']=self.fields['map.id'].text().strip()
        loc={'label':self.fields['map.location'].text().strip()}
        for key in ('latitude','longitude'):
            text=self.fields['map.'+key].text().strip()
            if text: loc[key]=float(text)
        if loc['label'] or len(loc)>1:
            if not all(key in loc for key in ('latitude','longitude')): raise ValueError('Provide both latitude and longitude, or leave the location blank')
            draft['location']={**draft.get('location',{}),**loc}
        else: draft.pop('location',None)
        dependencies=[]
        for item in self.fields['map.dependencies'].text().split(';'):
            if item.strip():
                parts=item.strip().split()
                if len(parts)!=2: raise ValueError('A dependency needs an ID and version, e.g. package.id >=1.0.0')
                dependencies.append({'id':parts[0],'version':parts[1]})
        draft['dependencies']=dependencies
        source=self.source.values(doc.manifest.get('build',{}).get('heightmap') or doc.ensure_source())
        processing=copy.deepcopy(source.get('processing',{}));processing['resolution']=int(self.fields['processing.resolution'].value())
        for method,fields in PROCESSING.items():
            if self.groups['processing.'+method].isChecked(): processing[method]=self.numbers('processing.'+method,fields)
            else: processing.pop(method,None)
        if len(processing)>1: source['processing']=processing
        else: source.pop('processing',None)
        build=draft.setdefault('build',{});build['heightmap']=source
        mode=self.forest_mode.currentText()
        if mode=='Manual' and 'forest' not in build:
            relative=doc.unique_file('Vegetation/editor-forest.json');build['forest']={'file':relative}
        elif mode=='None': build.pop('forest',None)
        vegetation=copy.deepcopy(build.get('vegetation',{}))
        if mode=='Automatic' or self.cover.isChecked() or 'vegetation' in build:
            for section,fields in VEGETATION.items():
                vegetation.setdefault(section,{}).update(self.numbers('vegetation.'+section,fields))
            vegetation['trees']['enabled']=mode=='Automatic';vegetation['ground_cover']['enabled']=self.cover.isChecked()
            vegetation['trees']['exclude']=json.loads(self.exclude.toPlainText());build['vegetation']=vegetation
        editor.validate_manifest(draft)
        if self.source.mode.currentIndex()==1 and self.source.high.value()<=self.source.low.value():
            raise ValueError('The highest elevation must be above the lowest.')
        for field in (self.source.width,self.source.height,self.source.stride):
            if field.text() and not field.hasAcceptableInput(): raise ValueError('Complete the sample dimensions and stride, or leave them automatic.')
        if mode=='Automatic' or self.cover.isChecked():
            if vegetation['biome']['alpine_line_meters']<=vegetation['biome']['tree_line_meters']:
                raise ValueError('The alpine line must be above the tree line.')
            exclusions=vegetation['trees']['exclude']
            if not isinstance(exclusions,list) or len(exclusions)>1000: raise ValueError('Clearings must be a list of at most 1000 rectangles.')
            for bounds in exclusions:
                if not isinstance(bounds,list) or len(bounds)!=4 or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in bounds) or bounds[0]>=bounds[2] or bounds[1]>=bounds[3]:
                    raise ValueError('Each clearing needs [west, north, east, south], with west < east and north < south.')
        return draft

    def validate_forms(self):
        if self.loading or not self.document: return
        try:
            draft=self.form_draft();self.validation_problem=''
            source=draft.get('build',{}).get('heightmap')
            signature=json.dumps(source,sort_keys=True)
            if signature!=self.source_check:
                original=self.document.manifest.get('build',{}).get('heightmap')
                if source!=original:
                    if self.document.terrain_dirty:
                        # Painted heights have their own encoding on Save.
                        changed=self.document.encoding_changed(source)
                        if changed: raise ValueError('Save the painted terrain before changing its dimensions or file encoding.')
                    else: self.document.prepare_draft(draft)
                self.source_check=signature
            scene_manifest=copy.deepcopy(draft)
            scene_manifest['terrain']['source']['vertices']=[self.document.width,self.document.height]
            scene_manifest['terrain']['source']['spacing_meters']=self.document.spacing
            authoring.compile_scene(self.document.scene,scene_manifest)
        except (ValueError,OSError,editor.ManifestError) as error: self.validation_problem=str(error)
        self.form_feedback.setText(self.validation_problem);self.update_actions();self.context_controls()

    def update_actions(self):
        if not hasattr(self,'scene_panel'): return
        active=self.document is not None and not self.busy;valid=active and not self.validation_problem
        self.left.setVisible(self.document is not None);self.right.setVisible(self.document is not None)
        self.left.setEnabled(active);self.right.setEnabled(active)
        for name,action in self.actions.items():
            enabled=not self.busy if name in ('new','open') else valid if name in ('save','build','test','play') else active
            if name=='undo': enabled=active and bool(self.document.history)
            if name=='redo': enabled=active and bool(self.document.future)
            if name=='play': enabled=valid and self.play_problem is None and not self.test_loading
            action.setEnabled(enabled)
            widget=self.workshop_bar.widgetForAction(action)
            if widget: widget.setEnabled(enabled)
            if name=='play': action.setToolTip(self.play_problem or ('The editor test is still loading.' if self.test_loading else 'Play / reload the editor test (F5)'))
        self.reveal_action.setEnabled(active and self.document.has_folder)
        self.close_map_action.setEnabled(active);self.recent_menu.setEnabled(not self.busy);self.preferences_action.setEnabled(not self.busy)
        self.recent_list.setEnabled(not self.busy);self.update_recent_controls()
        self.update_loader_action.setEnabled(not self.busy and bool(self.game_config.get('ue4ss_mods')))
        self.apply_button.setEnabled(valid and self.form_dirty)
        self.view.model().item(1).setEnabled(active and self.document.built is not None)
        for tool,widget in self.tool_buttons.items():
            enabled=active and (tool=='select' or not self.viewer.built)
            if tool=='flatten': enabled=enabled and (not self.level.text() or self.level.hasAcceptableInput())
            widget.defaultAction().setEnabled(enabled)
            widget.setEnabled(enabled)
        self.scene_panel.update_controls()

    def refresh_game(self):
        try:
            self.game_config=desktop.load_config();desktop.editor_launch_plan(self.game_config,self.test_session)
            self.play_problem=None
        except (ValueError,OSError,editor.ManifestError) as error:
            self.play_problem=str(error);self.game_config={}

    def context_controls(self,*args):
        if not hasattr(self,'apply_button'): return
        self.apply_button.setVisible(self.tabs.currentWidget()!=self.scene_panel)
        automatic=self.forest_mode.currentText()=='Automatic';cover=self.cover.isChecked()
        for key,group in self.nature_groups.items(): group.setVisible(automatic or cover if key=='biome' else automatic if key=='trees' else cover)
        self.exclude.setVisible(automatic);self.exclude_label.setVisible(automatic)

    def apply(self,quiet=False):
        if not self.document or self.busy: return False
        self.validate_forms()
        if self.validation_problem: return False
        try:
            doc=self.document;draft=self.form_draft()
            new_forest=draft.get('build',{}).get('forest') and 'forest' not in doc.manifest.get('build',{})
            doc.update_settings(draft)
            if new_forest: doc.forest_dirty=True
            self.form_dirty=False;self.mark_dirty();self.render_timer.start(20)
            if not quiet: self.statusBar().showMessage('Settings applied. Build to preview erosion and generated vegetation.')
            return True
        except (ValueError,OSError,editor.ManifestError) as error:
            self.validation_problem=str(error);self.form_feedback.setText(str(error));self.update_actions();return False

    def save(self):
        if not self.document or self.busy: return False
        try:
            if self.document._stroke: self.document.end_stroke();self.viewer.painting=False
            if not self.apply(True): return False
            if not self.document.has_folder:
                chooser=SaveFolder(self)
                if not chooser.exec(): return False
                self.document.save_to(chooser.selectedFiles()[0])
            else: self.document.save()
            self.load_forms();self.remember_project();self.statusBar().showMessage('Source saved.');return True
        except (ValueError,OSError,editor.ManifestError) as error: self.error(error);return False

    def discard_or_save(self):
        if self.busy: return False
        if not self.document or not (self.document.dirty or self.form_dirty): return True
        answer=W.QMessageBox.question(self,'Unsaved source changes','Save source changes before continuing?',W.QMessageBox.StandardButton.Save|W.QMessageBox.StandardButton.Discard|W.QMessageBox.StandardButton.Cancel)
        return self.save() if answer==W.QMessageBox.StandardButton.Save else answer==W.QMessageBox.StandardButton.Discard

    def new_project(self,file=None):
        if self.discard_or_save(): self.loaded(editor.EditorProject.new())
    def open_dialog(self):
        if self.busy: return
        folder=W.QFileDialog.getExistingDirectory(self,'Open source project containing custom-map.json')
        if folder: self.open_project(folder)
    def open_project(self,path):
        if self.discard_or_save(): self.task('Opening map',lambda: editor.EditorProject(path),self.loaded)
    def import_dialog(self,file=None):
        if self.busy: return
        if not self.document: self.new_project()
        if not self.document: return
        if self.form_dirty and not self.apply(True): return
        ImportHeightmap(self,file if isinstance(file,str) else None).exec()

    def choose_tool(self,tool):
        if tool!='place' and hasattr(self,'scene_panel'):
            self.scene_panel.placing=None;self.scene_panel.start=None;self.scene_panel.moving=False
        if not self.tool_buttons[tool].defaultAction().isEnabled(): return
        self.viewer.tool=tool
        for widget in (self.radius_label,self.radius): widget.setVisible(tool not in ('select','place'))
        for widget in (self.strength_label,self.strength): widget.setVisible(tool in ('raise','lower','smooth'))
        self.level_label.setVisible(tool=='flatten');self.level.setVisible(tool=='flatten')
        self.spacing_label.setVisible(tool in ('trees','erase_trees'));self.tree_spacing.setVisible(tool in ('trees','erase_trees'))
        if hasattr(self,'tool_buttons'): self.tool_buttons[tool].defaultAction().setChecked(True)
        self.viewer.cursor_at(None)
        if tool=='place' and self.document and not self.scene_panel.placing and not self.scene_panel.moving: self.scene_panel.begin()

    def scene_click(self,position):
        self.coordinates(position,True)
        self.scene_panel.clicked(position)

    def place_object(self,item): self.scene_panel.begin(item)

    def paint(self,stage,position):
        if self.busy or not self.document or self.viewer.built: return
        doc=self.document;tool=self.viewer.tool
        if stage=='end': doc.end_stroke();self.render_timer.start(20);self.mark_dirty();return
        if stage=='cancel':
            doc.end_stroke(cancel=True)
            self.loading=True;self.forest_mode.setCurrentText(doc.forest_mode);self.loading=False
            self.render_timer.start(20);self.mark_dirty();return
        try:
            if stage=='begin':
                doc.begin_stroke(tool)
                if tool=='flatten' and self.level.text() and not self.level.hasAcceptableInput(): doc.end_stroke(cancel=True);return
                self.flatten_target=float(self.level.text()) if tool=='flatten' and self.level.text() else doc.height_at(position[0],position[1])
            x,y,_=position
            if tool in ('trees','erase_trees'):
                doc.paint(x,y,tool,self.radius.value(),tree_spacing=self.tree_spacing.value())
                self.loading=True;self.forest_mode.setCurrentText('Manual');self.loading=False
            else: doc.paint(x,y,tool,self.radius.value(),self.strength.value(),target=self.flatten_target)
            self.render_timer.start(35);self.mark_dirty()
        except (ValueError,OSError) as error: doc.end_stroke(cancel=True);self.viewer.painting=False;self.error(error)

    def undo(self):
        if self.document and not self.busy and self.document.undo(): self.scene_panel.reload();self.render();self.mark_dirty()
    def redo(self):
        if self.document and not self.busy and self.document.redo(): self.scene_panel.reload();self.render();self.mark_dirty()
    def change_view(self,index):
        if self.loading or not self.document: return
        if index and self.document.built is None: self.view.setCurrentIndex(0);return
        self.viewer.built=bool(index)
        if index: self.choose_tool('select')
        self.render();self.viewer.fit_map();self.update_actions()

    def render(self):
        if not self.document or self.busy: return
        self.viewer.rebuild();doc=self.document;self.update_actions()
        width,height,spacing,values=self.viewer.data();forest=doc.built_trees if self.viewer.built else doc.trees
        self.summary.setText(f'{width:,} × {height:,} samples  ·  {(width-1)*spacing/1000:g} × {(height-1)*spacing/1000:g} km  ·  {len(forest):,} '+('compiled trees' if self.viewer.built else 'manual trees')+('\n'+ ' • '.join(doc.assumptions) if doc.assumptions else '')+ (f'\nPreview shows {self.viewer.rendered_tree_count:,} trees; the package keeps the complete forest.' if len(forest)>self.viewer.rendered_tree_count else ''))
        heights=self.viewer.height_grid;norm=(heights-heights.min())/max(1,float(np.ptp(heights)))
        rgb=np.stack((70+norm*150,105+norm*120,85+norm*140),axis=-1).astype(np.uint8).copy()
        image=G.QImage(rgb.data,rgb.shape[1],rgb.shape[0],rgb.strides[0],G.QImage.Format.Format_RGB888).copy()
        self.overview.setPixmap(G.QPixmap.fromImage(image).scaled(195,155,C.Qt.AspectRatioMode.KeepAspectRatio,C.Qt.TransformationMode.SmoothTransformation))

    def coordinates(self,position,selected=False):
        x,y,z=position;self.statusBar().showMessage(('Selected terrain • ' if selected else '')+f'East {x:.1f} m  •  South {y:.1f} m  •  Height {z:.1f} m')

    def refresh_files(self):
        self.files.clear()
        if not self.document: return
        doc=self.document;paths=set(doc.pending)
        def visit(folder,depth=0):
            if depth>8 or len(paths)>400: return
            for path in sorted(folder.iterdir()):
                if path.name.startswith('.') or path.name in ('bin','obj') or path.is_symlink(): continue
                if path.is_dir(): visit(path,depth+1)
                else: paths.add(path.relative_to(doc.folder).as_posix())
        visit(doc.folder)
        roots={}
        for relative in sorted(paths,key=lambda p: (p!='custom-map.json',p)):
            parent=self.files.invisibleRootItem();partial=''
            for component in relative.split('/'):
                partial=(partial+'/' if partial else '')+component
                if partial not in roots:
                    item=W.QTreeWidgetItem(parent,[component]);item.setData(0,C.Qt.ItemDataRole.UserRole,partial);roots[partial]=item
                parent=roots[partial]
        self.files.expandToDepth(0)
    def open_source(self,item,column):
        path=item.data(0,C.Qt.ItemDataRole.UserRole)
        if path==self.document.script_path or path.startswith('Triggers/'): self.open_editor(TriggerEditor)
        elif path.startswith('Objects/'): self.open_editor(ObjectEditor)
        elif path.startswith('Resources/'): self.open_editor(ResourceEditor)
        elif path=='custom-map.json': self.tabs.setCurrentIndex(2)
    def open_editor(self,kind):
        if not self.document or self.busy: return
        # Modal source editors keep the map document stable while a window is
        # editing it. Their separate graph/Lua history never consumes terrain undo.
        dialog=kind(self);self.dialogs.append(dialog);dialog.exec();self.dialogs.remove(dialog);self.refresh_files();self.scene_panel.reload();self.render();self.mark_dirty()

    def task(self,title,work,done):
        if self.busy: return
        self.busy=True;self.update_actions();self.progress.show();self.left.setEnabled(False);self.right.setEnabled(False);self.statusBar().showMessage(title+'…')
        def run():
            try: self.events.put(('done',work(),done,title))
            except Exception as error: self.events.put(('error',error))
        threading.Thread(target=run,daemon=True).start()
    def poll(self):
        if time.monotonic()-self.update_poll>60 or self.update_process and self.update_process.poll() is not None:
            self.update_process=None;self.check_updates()
        if time.monotonic()-self.session_poll>1:
            self.session_poll=time.monotonic()
            state=desktop.editor_session_state(self.game_config,self.test_session)
            loading=bool(state and state.get('state')=='loading')
            if loading!=self.test_loading: self.test_loading=loading;self.update_actions()
        try:
            while True:
                item=self.events.get_nowait()
                if item[0]=='log': self.log.appendPlainText(item[1].rstrip());continue
                self.busy=False;self.progress.hide();self.left.setEnabled(self.document is not None);self.right.setEnabled(self.document is not None)
                self.update_actions()
                if item[0]=='error': self.error(item[1])
                else: item[2](item[1])
        except queue.Empty: pass

    def check_updates(self,force=False):
        self.update_poll=time.monotonic()
        if self.update_process is None: self.update_process=updates.start_check(force=force)
        messages=updates.notices(self.game_config)
        self.update_notice.setText('Updates available · Game menu' if any('is available' in m for m in messages)
                                   else 'Game revision changed · Game menu' if messages else '')
        self.update_notice.setToolTip('\n'.join(messages))
        self.check_updates_action.setEnabled(self.update_process is None)
        if force: self.statusBar().showMessage('Checking for updates in the background.' if self.update_process else 'Update check complete.')

    def update_loader(self):
        if self.busy or not self.game_config.get('ue4ss_mods'): return
        def done(code):
            self.check_updates()
            self.statusBar().showMessage('Custom Map updated. Restart the test instance to use it.' if code==0 else 'Update failed. See the output.')
        self.run_cli(self.cli('update'),done,'update')

    def cli(self,command,*args):
        if __package__=='tools': return [sys.executable,'-u',str(Path(__file__).with_name('custom_map.py')),command,*map(str,args)]
        return [sys.executable,'-u','-c','import sys; from custom_map import main; sys.exit(main(sys.argv[1:]))',command,*map(str,args)]
    def run_cli(self,args,done,title):
        self.log.appendPlainText('\n> skieomod '+title)
        def work():
            with subprocess.Popen(args,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace',env={**os.environ,'PYTHONIOENCODING':'utf-8'}) as process:
                for line in process.stdout: self.events.put(('log',line))
                return process.wait()
        self.task(title,work,done)
    def command(self,command):
        self.validate_forms()
        if command=='run' and (self.play_problem or self.test_loading): return
        if not self.save(): return
        if command=='run':
            config=desktop.load_config()
            if not config.get('game_dir') or not Path(config['game_dir']).is_dir(): self.configure_game();return
        def done(code):
            if code: self.statusBar().showMessage(command.title()+' failed. See the build output.');return
            if command in ('build','run'):
                self.document.accept_build();self.load_forms();self.view.setCurrentIndex(1);self.viewer.built=True;self.render();self.viewer.fit_map()
            self.statusBar().showMessage({'build':'Package built. Showing final terrain and compiled forest.','test':'Project validation passed.','run':'Map installed and game launched.'}[command])
        arguments=['--editor-session',self.test_session] if command=='run' else []
        self.run_cli(self.cli(command,self.document.folder,*arguments),done,command)
    def configure_game(self):
        if self.busy: return
        folder=W.QFileDialog.getExistingDirectory(self,'Choose the Steam folder containing SkiResortSimulator')
        if folder:
            try: desktop.game_paths(folder)
            except (ValueError,OSError,editor.ManifestError): self.statusBar().showMessage('Choose the Steam game folder containing SkiResortSimulator/Content/Paks.');return
            def configured(code):
                self.refresh_game();self.update_actions();self.statusBar().showMessage('Game configured. Use Play.' if code==0 else 'Game setup failed. See the output.')
            self.run_cli(self.cli('setup','--game-dir',folder),configured,'setup')
    def reveal(self):
        if self.document: G.QDesktopServices.openUrl(C.QUrl.fromLocalFile(str(self.document.folder)))
    def error(self,error):
        self.statusBar().showMessage(str(error));self.log.appendPlainText(str(error))
    def shortcuts(self):
        for index,tool in enumerate(('select','raise','lower','flatten','smooth','trees','erase_trees'),1):
            shortcut=G.QShortcut(G.QKeySequence(str(index)),self.viewer);shortcut.setContext(C.Qt.ShortcutContext.WidgetShortcut);shortcut.activated.connect(lambda t=tool: self.choose_tool(t))
        shortcut=G.QShortcut(G.QKeySequence('P'),self.viewer);shortcut.setContext(C.Qt.ShortcutContext.WidgetShortcut);shortcut.activated.connect(lambda: self.scene_panel.begin())
    def closeEvent(self,event):
        if self.busy: self.statusBar().showMessage('Wait for the current operation to finish before closing.');event.ignore();return
        if self.discard_or_save(): self.poll_timer.stop();event.accept()
        else: event.ignore()
    def dragEnterEvent(self,event):
        if event.mimeData().hasUrls() and all(url.isLocalFile() for url in event.mimeData().urls()): event.acceptProposedAction()
    def dropEvent(self,event):
        urls=event.mimeData().urls()
        if len(urls)!=1: return
        path=Path(urls[0].toLocalFile())
        if path.is_dir() or path.name=='custom-map.json':
            self.open_project(path)
        elif path.suffix.lower() in ('.r16','.raw','.png'): self.import_dialog(str(path))
        event.acceptProposedAction()
