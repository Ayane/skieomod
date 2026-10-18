"""Real Qt/OpenGL integration; run with xvfb-run and the installed GUI dependencies."""
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from tools import skieo_project as projects, skieo_editor as editor, skieo_authoring as a
from tests.test_heightmap_build import png16
from tests.test_authoring_build import OBJ

class NativeEditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY')): raise unittest.SkipTest('Desktop display unavailable')
        try:
            from PySide6 import QtWidgets as W, QtCore as C
            from tools.skieo_editor_widgets import STYLE
        except ImportError as error: raise unittest.SkipTest('Qt dependencies unavailable: '+str(error))
        C.QCoreApplication.setAttribute(C.Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
        cls.qt=W.QApplication.instance() or W.QApplication([]);cls.qt.setStyle('Fusion');cls.qt.setStyleSheet(STYLE)
    def setUp(self):
        from tools.skieo_editor_ui import MapEditor
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.folder=self.root/'mountain project'
        config=patch.dict(os.environ,{'SKIEOMOD_CONFIG_DIR':str(self.root/'config')});config.start();self.addCleanup(config.stop)
        for name,value in [('start_check',None),('notices',[])]:
            mock=patch('tools.skieo_editor_ui.updates.'+name,return_value=value);mock.start();self.addCleanup(mock.stop)
        projects.create('map',self.folder);self.app=MapEditor(editor.EditorProject(self.folder));self.app.show()
        self.errors=[];self.app.error=lambda error:self.errors.append(str(error));self.addCleanup(self.destroy);self.pump()
    def destroy(self):
        for w in list(self.qt.topLevelWidgets()):
            if hasattr(w,'dirty'): w.dirty=False
            if hasattr(w,'document') and isinstance(w.document,editor.EditorProject): w.document.dirty=False;w.form_dirty=False
            w.close();w.deleteLater()
        self.qt.processEvents()
    def pump(self,until=None,timeout=30):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            self.qt.processEvents()
            if until is None or until(): break
            time.sleep(.02)
        if until: self.assertTrue(until(),'UI operation timed out')
        self.assertEqual(self.errors,[])
    def test_real_terrain_pick_brush_save_build_and_test(self):
        from PySide6 import QtCore as C, QtTest as T
        source=self.root/'mountain.png';source.write_bytes(png16(17,29,[(r*17+c)*100 for r in range(29) for c in range(17)]));original=source.read_bytes()
        app=self.app;app.document.import_heightmap(source,{'spacing_meters':8});app.load_forms();app.render();app.viewer.fit_map();self.pump()
        self.assertTrue(app.viewer.isValid());self.assertEqual(app.document.extent,(128,224))
        position=C.QPoint(app.viewer.width()//2,app.viewer.height()//2);self.assertIsNotNone(app.viewer.pick(C.QPointF(position)))
        app.choose_tool('raise');before=app.document.heights[:];T.QTest.mouseClick(app.viewer,C.Qt.MouseButton.LeftButton,pos=position);self.pump()
        self.assertNotEqual(app.document.heights,before);app.undo();self.assertEqual(app.document.heights,before);app.redo()
        app.fields['map.name'].setText('My edited mountain');self.assertTrue(app.save());self.assertEqual(source.read_bytes(),original)
        app.command('build');self.pump(lambda:not app.busy);self.assertTrue(app.viewer.built);self.assertTrue(list((self.folder/'bin').glob('*.skieomap')))
        before=app.document.heights[:];T.QTest.mouseClick(app.viewer,C.Qt.MouseButton.LeftButton,pos=position);self.assertEqual(before,app.document.heights)
        app.command('test');self.pump(lambda:not app.busy);self.assertIn('passed',app.statusBar().currentMessage().lower())
    def test_middle_grab_follows_cursor_after_camera_rotations(self):
        import numpy as np
        from PySide6 import QtCore as C, QtGui as G, QtTest as T
        view=self.app.viewer
        for azimuth in (-150,-55,30,120):
            view.fit_map();view.setCameraPosition(azimuth=azimuth);self.pump()
            start=C.QPoint(view.width()//2,view.height()//2);point=view.pick(C.QPointF(start));self.assertIsNotNone(point)
            anchor=np.array([point[0],-point[1],point[2],1]);T.QTest.mousePress(view,C.Qt.MouseButton.MiddleButton,pos=start)
            for dx,dy in ((100,30),(-90,25),(0,-70)):
                end=start+C.QPoint(dx,dy)
                event=G.QMouseEvent(C.QEvent.Type.MouseMove,C.QPointF(end),C.QPointF(view.mapToGlobal(end)),C.Qt.MouseButton.NoButton,C.Qt.MouseButton.MiddleButton,C.Qt.KeyboardModifier.NoModifier);self.qt.sendEvent(view,event)
                matrix=np.asarray(view.projectionMatrix((0,0,view.width(),view.height()),(0,0,view.width(),view.height())).copyDataTo()).reshape(4,4)@np.asarray(view.viewMatrix().copyDataTo()).reshape(4,4)
                projected=matrix@anchor;projected=projected[:3]/projected[3];pixel=np.array([(projected[0]+1)*view.width()/2,(1-projected[1])*view.height()/2])
                self.assertLess(np.linalg.norm(pixel-[end.x(),end.y()]),.2)
            T.QTest.mouseRelease(view,C.Qt.MouseButton.MiddleButton,pos=end);self.assertIsNone(view.grab_anchor)
    def test_wheel_scrolls_over_form_without_changing_numeric_value(self):
        from PySide6 import QtCore as C, QtGui as G
        self.app.tabs.setCurrentIndex(1);self.app.forest_mode.setCurrentText('Automatic');self.pump()
        area=self.app.tabs.widget(1);spin=self.app.fields['vegetation.biome.tree_line_meters'];before=spin.value();self.assertGreater(area.verticalScrollBar().maximum(),100)
        pos=spin.rect().center();event=G.QWheelEvent(C.QPointF(pos),C.QPointF(spin.mapToGlobal(pos)),C.QPoint(0,0),C.QPoint(0,-120),C.Qt.MouseButton.NoButton,C.Qt.KeyboardModifier.NoModifier,C.Qt.ScrollPhase.NoScrollPhase,False)
        self.qt.sendEvent(spin,event);self.pump();self.assertEqual(spin.value(),before);self.assertGreater(area.verticalScrollBar().value(),0)
    def test_trigger_graph_lua_resource_and_object_windows(self):
        from PySide6 import QtCore as C, QtGui as G, QtTest as T, QtWidgets as W
        from tools.skieo_editor_graph import TriggerEditor
        from tools.skieo_editor_resources import ObjectEditor,ResourceEditor
        app=self.app;t=TriggerEditor(app);t.show();t.new_trigger();self.pump();self.assertEqual(t.mode.currentText(),'Visual graph');self.assertEqual(len(t.graph.document['nodes']),3)
        t.graph.add_node('funds',C.QPointF(700,100));node=next(n for n in t.graph.nodes.values() if n.data['kind']=='funds')
        identifier=node.data['id'];view=t.graph
        view.fitInView(view.scene().itemsBoundingRect().adjusted(-40,-40,40,40),C.Qt.AspectRatioMode.KeepAspectRatio);self.pump()
        start=view.mapFromScene(view.nodes['message'].pins['out','then'].scenePos());end=view.mapFromScene(node.pins['in','in'].scenePos())
        T.QTest.mousePress(view.viewport(),C.Qt.MouseButton.LeftButton,pos=start)
        self.qt.sendEvent(view.viewport(),G.QMouseEvent(C.QEvent.Type.MouseMove,C.QPointF(end),C.QPointF(view.viewport().mapToGlobal(end)),C.Qt.MouseButton.NoButton,C.Qt.MouseButton.LeftButton,C.Qt.KeyboardModifier.NoModifier))
        T.QTest.mouseRelease(view.viewport(),C.Qt.MouseButton.LeftButton,pos=end);self.pump()
        self.assertEqual(len(view.document['edges']),3);node=view.nodes[identifier]
        t.inspect_node(node.data);self.assertFalse(t.properties_box.parentWidget().findChildren(W.QDoubleSpinBox))
        t.graph.add_node('number',C.QPointF(400,300));constant=next(n for n in view.nodes.values() if n.data['kind']=='number')
        t.graph.set_parameter(constant.data['id'],'value',50000)
        view.connect_pins(view.nodes[constant.data['id']].pins['out','value'],view.nodes[identifier].pins['in','amount'])
        self.assertIn('50000',a.compile_graph(view.document));self.assertNotIn('amount',a.NODES['funds']['defaults'])
        t.new_trigger();t.mode.setCurrentIndex(1);t.lua.setPlainText('api:log("Lua works")');t.apply();self.assertFalse(t.dirty);t.close()
        obj=self.root/'office.obj';obj.write_bytes(OBJ);app.document.import_resource(obj,'office','model',units='meters',up_axis='z')
        resources=ResourceEditor(app);resources.show();self.pump();self.assertEqual(resources.stack.currentIndex(),2);self.assertTrue(resources.model.isValid());resources.close()
        objects=ObjectEditor(app);objects.show();objects.use_snapshot(json.dumps({'version':1,'objects':[{'name':'Ticket Office','class':a.OBJECTS[0]['class'],'fields':{'BaseCost':{'type':'integer','default':1111},'MeshComponent.StaticMesh':{'type':'model','default':'/Game/Example/Office.Office'}}}]}).encode())
        index=next(i for i in range(objects.table.rowCount()) if objects.table.item(i,0).text()=='BaseCost');item=objects.table.item(index,2)
        item.setText('2000');self.assertTrue(item.font().bold());self.assertEqual(app.document.object_edits[0]['value'],2000);item.setText('1111');self.assertFalse(item.font().bold());self.assertFalse(objects.edits)
        index=next(i for i in range(objects.table.rowCount()) if objects.table.item(i,0).text()=='MeshComponent.StaticMesh');objects.table.item(index,2).setText('asset:office');self.assertTrue(objects.table.item(index,2).font().bold())
        objects.apply();objects.close();self.assertTrue(app.save());self.assertEqual(obj.read_bytes(),OBJ);app.command('build');self.pump(lambda:not app.busy)
        reopened=editor.EditorProject(self.folder);self.assertEqual(len(reopened.triggers['triggers']),2);self.assertEqual(reopened.object_edits[0]['value'],'asset:office');self.assertTrue((self.folder/a.GENERATED_SCRIPT).exists())
    def test_place_select_move_rotate_delete_and_undo(self):
        from PySide6 import QtCore as C, QtTest as T
        app=self.app;panel=app.scene_panel;panel.begin(a.OBJECTS[0]);self.pump()
        position=C.QPoint(app.viewer.width()//2,app.viewer.height()//2)
        T.QTest.mouseClick(app.viewer,C.Qt.MouseButton.LeftButton,pos=position);self.pump()
        self.assertEqual(len(app.document.scene['objects']),1);self.assertGreater(len(app.viewer.scene_items),0)
        T.QTest.mouseClick(app.tool_buttons['select'],C.Qt.MouseButton.LeftButton);self.assertIsNone(panel.placing)
        T.QTest.mouseClick(app.viewer,C.Qt.MouseButton.LeftButton,pos=position);self.assertEqual(len(app.document.scene['objects']),1)
        panel.select(0);panel.yaw.setValue(45);panel.edit();self.assertEqual(app.document.scene['objects'][0]['rotation_degrees'],45)
        panel.move();panel.clicked((50,40,0));self.assertEqual(app.document.scene['objects'][0]['position'],[50,40])
        panel.delete();self.assertFalse(app.document.scene['objects']);app.undo();self.assertEqual(len(app.document.scene['objects']),1)
        panel.begin(a.OBJECTS[1]);panel.clicked((70,60,0));self.assertEqual(len(app.document.scene['objects']),1);panel.clicked((70,300,0));self.assertEqual(len(app.document.scene['objects']),2)
        panel.cancel();self.assertTrue(app.save());app.command('build');self.pump(lambda:not app.busy)
        self.assertEqual(len(editor.EditorProject(self.folder).scene['objects']),2)

    def test_new_is_immediate_first_save_only_asks_for_folder(self):
        from tools.skieo_editor_ui import SaveFolder
        self.app.new_project();self.pump();doc=self.app.document
        self.assertFalse(doc.has_folder);self.assertFalse(doc.scene['objects']);self.assertFalse(doc.trees)
        self.assertFalse(self.app.actions['undo'].isEnabled());self.assertFalse(self.app.scene_panel.delete_button.isEnabled())
        self.assertTrue(self.app.scene_panel.details.isHidden());self.assertTrue(self.app.radius.isHidden())
        doc.begin_stroke('raise');doc.paint(0,0,'raise',60,10);doc.end_stroke();before=doc.heights[:]
        destination=self.root/'saved map';destination.mkdir()
        with patch.object(SaveFolder,'exec',return_value=1),patch.object(SaveFolder,'selectedFiles',return_value=[str(destination)]): self.assertTrue(self.app.save())
        self.assertEqual(doc.folder,destination);self.assertTrue(doc.has_folder)
        self.assertLess(max(abs(a-b) for a,b in zip(editor.EditorProject(destination).heights,before)),.01)
        with patch.object(SaveFolder,'exec') as chooser: self.assertTrue(self.app.save());chooser.assert_not_called()

    def test_startup_and_open_enable_ready_document_controls(self):
        from tools.skieo_editor_ui import MapEditor
        startup=MapEditor();startup.show();self.pump(lambda:not startup.busy)
        self.assertEqual(startup.document.folder,self.folder)
        for name in ('save','import','triggers','resources','objects','test','build'):
            self.assertTrue(startup.actions[name].isEnabled(),name)
        for name,control in startup.tool_buttons.items(): self.assertTrue(control.isEnabled(),name)
        self.assertTrue(startup.left.isEnabled());self.assertTrue(startup.right.isEnabled())
        startup.open_project(self.folder);self.pump(lambda:not startup.busy)
        self.assertEqual(startup.document.folder,self.folder)
        for name in ('save','import','test','build'): self.assertTrue(startup.actions[name].isEnabled(),name)
        # Document readiness owns the parent and action states, even if a
        # platform disabled their widget containers during startup or travel.
        startup.left.setEnabled(False);startup.right.setEnabled(False)
        startup.actions['save'].setEnabled(False)
        startup.workshop_bar.widgetForAction(startup.actions['import']).setEnabled(False)
        startup.tool_buttons['raise'].setEnabled(False)
        startup.hide();startup.show();self.pump()
        self.assertTrue(startup.left.isEnabled());self.assertTrue(startup.right.isEnabled())
        self.assertTrue(startup.actions['save'].isEnabled())
        self.assertTrue(startup.workshop_bar.widgetForAction(startup.actions['import']).isEnabled())
        self.assertTrue(startup.tool_buttons['raise'].isEnabled())
        startup.document.dirty=False;startup.form_dirty=False;startup.close()

    def test_startup_choices_explicit_project_and_first_launch(self):
        from PySide6 import QtCore as C
        from tools.skieo_editor_ui import MapEditor
        preferences=self.app.preferences
        for mode in ('none','new','last'):
            preferences.startup=mode;preferences.save()
            window=MapEditor();window.show();self.pump(lambda:not window.busy)
            if mode=='none':
                self.assertIsNone(window.document);self.assertEqual(window.stack.currentIndex(),0)
                self.assertFalse(window.actions['save'].isEnabled());self.assertFalse(window.tool_buttons['raise'].isEnabled())
                self.assertTrue(window.actions['new'].isEnabled());self.assertTrue(window.actions['open'].isEnabled())
                self.assertEqual(window.recent_list.item(0).data(C.Qt.ItemDataRole.UserRole),str(self.folder/'custom-map.json'))
            elif mode=='new': self.assertFalse(window.document.has_folder)
            else: self.assertEqual(window.document.folder,self.folder)
            window.close()
        second=self.root/'explicit project';projects.create('map',second)
        window=MapEditor(path=second);window.show();self.pump(lambda:not window.busy)
        self.assertEqual(window.document.folder,second);window.close()
        preferences.recent_projects=[];preferences.startup='last';preferences.save()
        window=MapEditor();window.show();self.pump()
        self.assertIsNone(window.document);self.assertEqual(window.stack.currentIndex(),0);self.assertTrue(window.recent_empty.isVisible())
        self.assertTrue(window.actions['new'].isEnabled());window.close()

    def test_recent_maps_order_close_and_open_from_welcome_and_menu(self):
        from PySide6 import QtCore as C
        app=self.app;second=self.root/'second';projects.create('map',second)
        app.open_project(second);self.pump(lambda:not app.busy)
        app.open_project(self.folder/'custom-map.json');self.pump(lambda:not app.busy)
        expected=[str(self.folder/'custom-map.json'),str(second/'custom-map.json')]
        self.assertEqual([item['path'] for item in app.preferences.recent_projects],expected)
        app.close_project();self.pump();self.assertIsNone(app.document);self.assertEqual(app.stack.currentIndex(),0)
        self.assertEqual([app.recent_list.item(i).data(C.Qt.ItemDataRole.UserRole) for i in range(2)],expected)
        app.recent_list.setCurrentRow(1);self.assertTrue(app.recent_open_button.isEnabled())
        app.recent_open_button.click();self.pump(lambda:not app.busy);self.assertEqual(app.document.folder,second)
        app.recent_menu.actions()[1].trigger();self.pump(lambda:not app.busy);self.assertEqual(app.document.folder,self.folder)
        (second/'custom-map.json').unlink();app.close_project();self.pump()
        self.assertFalse(app.recent_menu.actions()[1].isEnabled())
        self.assertFalse(app.recent_list.item(1).flags() & C.Qt.ItemFlag.ItemIsEnabled)

    def test_preferences_dialog_persists_and_cancel_keeps_previous_choice(self):
        from PySide6 import QtCore as C, QtWidgets as W
        from tools.skieo_editor_ui import PreferencesDialog
        from tools.skieo_editor_config import EditorPreferences
        app=self.app
        def select_startup():
            dialog=self.qt.activeModalWidget()
            dialog.startup.setCurrentIndex(dialog.startup.findData('none'))
            dialog.findChild(W.QDialogButtonBox).button(W.QDialogButtonBox.StandardButton.Save).click()
        C.QTimer.singleShot(0,select_startup);app.preferences_action.trigger()
        self.assertEqual(EditorPreferences().startup,'none');self.assertIsNotNone(app.document)
        with patch.object(PreferencesDialog,'exec',return_value=0): app.configure_preferences()
        self.assertEqual(EditorPreferences().startup,'none')

    def test_failed_recent_open_restores_controls_and_keeps_history(self):
        app=self.app;before=app.preferences.recent_projects[:];errors=[]
        with patch.object(app,'error',side_effect=lambda error:errors.append(str(error))):
            app.open_project(self.root/'missing');self.pump(lambda:not app.busy)
        self.assertEqual(len(errors),1)
        self.assertEqual(app.document.folder,self.folder);self.assertEqual(app.preferences.recent_projects,before)
        self.assertTrue(app.actions['save'].isEnabled());self.assertTrue(app.tool_buttons['raise'].isEnabled())

    def test_first_save_adds_new_map_to_history(self):
        from tools.skieo_editor_ui import SaveFolder
        app=self.app;app.new_project();self.pump()
        self.assertEqual(len(app.preferences.recent_projects),1)
        destination=self.root/'newly saved';destination.mkdir()
        with patch.object(SaveFolder,'exec',return_value=1),patch.object(SaveFolder,'selectedFiles',return_value=[str(destination)]): self.assertTrue(app.save())
        self.assertEqual(app.preferences.recent_projects[0]['path'],str(destination/'custom-map.json'))

    def test_selected_object_name_defaults_and_scoped_properties(self):
        app=self.app;panel=app.scene_panel
        panel.begin(a.OBJECTS[0]);panel.clicked((0,0,0));panel.clicked((80,0,0));panel.cancel();panel.select(0)
        self.assertEqual(panel.default_label.text(),'Ticket Office')
        panel.name.setText('Not Ticket Office');panel.edit()
        self.assertEqual(app.document.scene['objects'][0]['name'],'Not Ticket Office');self.assertTrue(panel.name.font().bold())
        row=next(i for i in range(panel.property_table.rowCount()) if panel.property_table.item(i,0).text()=='BaseCost')
        default=panel.property_fields['BaseCost']['default'];panel.property_table.item(row,2).setText(str(default+123))
        self.assertEqual(app.document.object_edits[0]['instance'],'object-1')
        self.assertEqual(app.document.object_edits[0]['value'],default+123)
        row=next(i for i in range(panel.property_table.rowCount()) if panel.property_table.item(i,0).text()=='BaseCost');self.assertTrue(panel.property_table.item(row,2).font().bold())
        panel.select(1);row=next(i for i in range(panel.property_table.rowCount()) if panel.property_table.item(i,0).text()=='BaseCost')
        self.assertEqual(panel.property_table.item(row,2).text(),str(default));self.assertFalse(panel.property_table.item(row,2).font().bold())
        panel.select(0);panel.reset_name();self.assertEqual(app.document.scene['objects'][0]['name'],'');self.assertFalse(panel.name.font().bold())
        self.assertTrue(app.save());app.command('build');self.pump(lambda:not app.busy)
        reopened=editor.EditorProject(self.folder);self.assertEqual(reopened.object_edits[0]['instance'],'object-1')
        app.view.setCurrentIndex(0);panel.select(0);panel.delete();self.assertFalse(app.document.object_edits)
        app.undo();self.assertEqual(app.document.object_edits[0]['instance'],'object-1')

    def test_heightmap_import_is_prevalidated_and_preserves_other_work(self):
        from tools.skieo_editor_ui import ImportHeightmap
        from PySide6 import QtWidgets as W
        source=self.root/'real relief.png';source.write_bytes(png16(5,9,[i*100 for i in range(45)]));dialog=ImportHeightmap(self.app);dialog.show()
        self.assertFalse(dialog.import_button.isEnabled())
        with patch('PySide6.QtWidgets.QFileDialog.getOpenFileName',return_value=(str(source),'')): dialog.file.choose()
        self.pump(lambda:dialog.import_button.isEnabled());dialog.import_file();self.pump()
        self.assertEqual((self.app.document.width,self.app.document.height),(5,9));self.assertEqual(self.app.document.elevation,(0,1000))
        self.assertFalse(source.read_bytes()==b'')

    def test_invalid_forms_and_context_disable_actions_before_validation(self):
        self.app.fields['map.version'].setText('bad');self.app.form_changed();self.assertFalse(self.app.actions['save'].isEnabled());self.assertFalse(self.app.actions['build'].isEnabled())
        self.assertTrue(self.app.form_feedback.text());self.assertFalse(self.app.save());self.assertEqual(self.errors,[])
        self.app.fields['map.version'].setText('0.1.0');self.app.form_changed();self.assertTrue(self.app.actions['save'].isEnabled())
        self.app.busy=True;self.app.update_actions();self.assertFalse(self.app.actions['new'].isEnabled());self.app.busy=False;self.app.update_actions()

if __name__=='__main__': unittest.main()
