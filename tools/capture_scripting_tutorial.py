"""Rebuild the small tutorial project and capture the real Qt Trigger Editor.

Run with the workshop's Python environment, for example under xvfb-run.
No game launch or installed user project is changed.
"""
from __future__ import annotations
import json
from pathlib import Path
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import skieo_authoring as authoring, skieo_editor as editor, skieo_project as projects

DEST = ROOT / 'repository/web/public/tutorials/scripts'
SOURCE = ROOT / 'mod/SkiEO-SuperSaintBernard'


def practice_project(folder):
    projects.create('map', folder, 'My first season', 'tutorial.first-season',
                    'SkiEO Community', size_meters=(1024, 1024), spacing_meters=16, blank=True)
    manifest = json.loads((folder / 'custom-map.json').read_text())
    manifest['script']['api'] = '1.1'
    manifest['build']['triggers'] = {'file': 'Triggers/triggers.json'}
    (folder / 'custom-map.json').write_text(json.dumps(manifest, indent=2) + '\n')
    (folder / 'Scripts/main.lua').write_bytes((DEST / 'files/first-season.lua').read_bytes())
    triggers = json.loads((SOURCE / 'Triggers/triggers.json').read_text())
    setup = triggers['triggers'][0]
    setup['graph']['nodes'][1]['params']['rules_module'] = ''
    setup['lua'] = "api.game:configure({currency = 'CHF', start_year = 2003, starting_balance = 250000, ticket_price = 38})"
    notice = authoring.new_trigger('april-reminder', 'April reminder')
    notice['event'] = 'calendar.month_changed'
    notice['graph'] = {
        'nodes': [
            {'id': 'event', 'kind': 'entry', 'position': [40, 40]},
            {'id': 'branch', 'kind': 'branch', 'position': [710, 40]},
            {'id': 'month', 'kind': 'event_value', 'position': [40, 200], 'params': {'key': 'month', 'fallback': 0}},
            {'id': 'april', 'kind': 'number', 'position': [40, 360], 'params': {'value': 4}},
            {'id': 'compare', 'kind': 'compare', 'position': [380, 200], 'params': {'operator': '=='}},
            {'id': 'message', 'kind': 'log', 'position': [1050, 40]},
            {'id': 'text', 'kind': 'text', 'position': [710, 250], 'params': {'value': 'April: check your cash reserve.'}},
        ],
        'edges': [
            {'source': 'event', 'port': 'then', 'target': 'branch', 'input': 'in'},
            {'source': 'month', 'port': 'value', 'target': 'compare', 'input': 'a'},
            {'source': 'april', 'port': 'value', 'target': 'compare', 'input': 'b'},
            {'source': 'compare', 'port': 'value', 'target': 'branch', 'input': 'condition'},
            {'source': 'branch', 'port': 'true', 'target': 'message', 'input': 'in'},
            {'source': 'text', 'port': 'value', 'target': 'message', 'input': 'message'},
        ],
    }
    notice['lua'] = "if (event.month or 0) == 4 then\n    api:log('April: check your cash reserve.')\nend"
    triggers['triggers'].append(notice)
    authoring.compile_triggers(triggers)
    (folder / 'Triggers').mkdir()
    (folder / 'Triggers/triggers.json').write_text(json.dumps(triggers, indent=2) + '\n')
    (DEST / 'files/starting-economy.json').write_bytes((SOURCE / 'Triggers/triggers.json').read_bytes())
    (DEST / 'files/april-reminder.json').write_text(json.dumps({'version': 1, 'triggers': [notice]}, indent=2) + '\n')
    with zipfile.ZipFile(DEST / 'files/first-season-project.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
        for file in sorted(folder.rglob('*')):
            if file.is_file(): archive.write(file, 'first-season/' + file.relative_to(folder).as_posix())


def main():
    from PySide6 import QtCore as C, QtWidgets as W
    from tools.skieo_editor_graph import TriggerEditor
    from tools.skieo_editor_widgets import STYLE
    with tempfile.TemporaryDirectory(prefix='skieomod-tutorial-') as temp:
        folder = Path(temp) / 'first-season'
        practice_project(folder)
        C.QCoreApplication.setAttribute(C.Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
        qt = W.QApplication.instance() or W.QApplication([])
        qt.setStyle('Fusion'); qt.setStyleSheet(STYLE)
        # The dialog only needs the project; avoid network checks and terrain rendering.
        host = W.QWidget()
        host.document = editor.EditorProject(SOURCE)
        dialog = TriggerEditor(host)
        dialog.resize(1500, 960); dialog.show(); qt.processEvents()
        def frame(name, node=None):
            if node:
                dialog.graph.nodes[node].setSelected(True)
            qt.sendPostedEvents(None, C.QEvent.Type.DeferredDelete)
            qt.processEvents()
            dialog.graph.fitInView(dialog.graph.scene().itemsBoundingRect().adjusted(-50,-50,50,50), C.Qt.AspectRatioMode.KeepAspectRatio)
            qt.processEvents()
            if not dialog.grab().save(str(DEST / 'images' / name)): raise RuntimeError('Screenshot failed')
        frame('starting-economy.png', 'starting_balance')
        dialog.list.setCurrentRow(len(dialog.document['triggers']))
        qt.processEvents(); dialog.grab().save(str(DEST / 'images/project-initialization.png'))
        dialog.close()
        host.document = editor.EditorProject(folder)
        dialog = TriggerEditor(host); dialog.resize(1780, 900); dialog.show(); qt.processEvents()
        dialog.list.setCurrentRow(1); frame('april-condition.png', 'compare')
        dialog.close(); host.close()
    print('Captured 3 real Qt windows; practice source ZIP and graph examples rebuilt.')


if __name__ == '__main__': main()
