"""Capture the real map workshop and rebuild its downloadable practice source.

Run with the editor's Python environment under xvfb-run (QT_QPA_PLATFORM=xcb and
PYOPENGL_PLATFORM=glx on a Wayland host). Configuration and source
work stay in a temporary directory; this never installs or launches the game.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DEST = ROOT / 'repository/web/public/tutorials/editor'
HEIGHTMAP = ROOT / 'repository/web/public/tutorials/heightmap/downloads/alpine-valley.png'


def main():
    from PySide6 import QtCore as C, QtWidgets as W
    from tools import skieo_editor as editor
    from tools.skieo_editor_ui import ImportHeightmap, MapEditor
    from tools.skieo_editor_widgets import STYLE

    (DEST / 'images').mkdir(parents=True, exist_ok=True)
    (DEST / 'files').mkdir(parents=True, exist_ok=True)
    C.QCoreApplication.setAttribute(C.Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    qt = W.QApplication.instance() or W.QApplication([])
    qt.setStyle('Fusion')
    qt.setStyleSheet(STYLE)

    def pump(until=lambda: True, timeout=90):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            qt.processEvents()
            if until():
                return
            time.sleep(.02)
        raise RuntimeError('Workshop operation timed out')

    def frame(widget, name):
        # Let OpenGL finish rendering before grabbing the actual Qt window.
        deadline = time.monotonic() + .4
        pump(lambda: time.monotonic() >= deadline)
        if not widget.grab().save(str(DEST / 'images' / name)):
            raise RuntimeError('Screenshot failed: ' + name)

    with tempfile.TemporaryDirectory(prefix='skieomod-editor-tutorial-') as temp, \
            patch.dict(os.environ, {'SKIEOMOD_CONFIG_DIR': str(Path(temp) / 'config')}), \
            patch('tools.skieo_editor_ui.updates.start_check', return_value=None), \
            patch('tools.skieo_editor_ui.updates.notices', return_value=[]):
        app = MapEditor(editor.EditorProject.new())
        app.resize(1500, 980)
        app.show()
        pump()
        if not app.viewer.isValid():
            raise RuntimeError('An OpenGL display is required for terrain captures')
        frame(app, 'new-map.png')

        source = Path(temp) / 'alpine-valley.png'
        source.write_bytes(HEIGHTMAP.read_bytes())
        dialog = ImportHeightmap(app, str(source))
        dialog.settings.spacing.setValue(8)
        dialog.settings.mode.setCurrentText('Known lowest / highest')
        dialog.settings.low.setValue(800)
        dialog.settings.high.setValue(2200)
        dialog.show()
        pump(lambda: dialog.prepared is not None)
        frame(dialog, 'import-heightmap.png')
        dialog.import_file()
        pump()
        if app.document.extent != (4096, 4096):
            raise RuntimeError('Practice terrain has unexpected dimensions')

        app.tabs.setCurrentIndex(2)
        for key, value in {
            'name': 'Alpine Valley Workshop', 'authors': 'SkiEO Community',
            'id': 'tutorial.alpine-valley-workshop', 'version': '0.1.0', 'license': 'MIT',
        }.items():
            app.fields['map.' + key].setText(value)
        app.description.setPlainText('A practice map made with the graphical workshop. Terrain: CC0.')
        if not app.apply():
            raise RuntimeError(app.validation_problem)
        app.document.save_to(Path(temp) / 'alpine-valley-workshop')
        app.load_forms()
        app.render()
        app.viewer.fit_map()
        app.tabs.setCurrentIndex(0)
        app.choose_tool('smooth')
        frame(app, 'source-terrain.png')

        app.tabs.setCurrentIndex(1)
        app.forest_mode.setCurrentText('Automatic')
        app.fields['vegetation.biome.tree_line_meters'].setValue(1900)
        app.fields['vegetation.trees.density_per_hectare'].setValue(12)
        app.fields['vegetation.trees.max_trees'].setValue(10000)
        # A clearing beside the practice lift's lower terminal; units are metres.
        app.exclude.setPlainText('[[-450, 880, 180, 1300]]')
        if not app.apply():
            raise RuntimeError(app.validation_problem)

        panel = app.scene_panel
        panel.search.setText('Ticket Office')
        panel.begin()
        panel.clicked((-350, 1150, app.document.height_at(-350, 1150)))
        panel.cancel()
        # Catalogue display names can evolve; the game's class remains stable.
        panel.search.setText('')
        lift_index = next(i for i in range(panel.palette.count())
                          if panel.palette.itemData(i)['class'].endswith('BP_FixedChair1_C'))
        panel.palette.setCurrentIndex(lift_index)
        panel.begin()
        panel.clicked((0, 1000, app.document.height_at(0, 1000)))
        panel.clicked((-900, -700, app.document.height_at(-900, -700)))
        panel.cancel()
        panel.select(1)
        app.viewer.fit_map()
        app.resize(1500, 1100)
        frame(app, 'place-objects.png')
        app.tabs.setCurrentIndex(1)
        app.resize(1500, 1280)
        frame(app, 'nature-settings.png')
        app.resize(1500, 980)

        folder = app.document.folder
        (folder / 'CREDITS.txt').write_text(
            'Alpine Valley practice heightmap: CC0 1.0.\n'
            'https://creativecommons.org/publicdomain/zero/1.0/\n'
            'Generated project code: MIT.\n', encoding='utf-8')
        app.command('build')
        pump(lambda: not app.busy)
        if not list((folder / 'bin').glob('*.skieomap')):
            raise RuntimeError(app.log.toPlainText())
        frame(app, 'built-map.png')
        app.command('test')
        pump(lambda: not app.busy)
        if app.statusBar().currentMessage() != 'Project validation passed.':
            raise RuntimeError(app.log.toPlainText())
        with zipfile.ZipFile(DEST / 'files/alpine-valley-workshop.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
            for file in sorted(folder.rglob('*')):
                if file.is_file() and not any(part.startswith('.') or part in ('bin', 'obj')
                                              for part in file.relative_to(folder).parts):
                    archive.write(file, 'alpine-valley-workshop/' + file.relative_to(folder).as_posix())
        app.document.dirty = False
        app.form_dirty = False
        app.close()
    print('Captured 6 real Qt windows; practice source built, validated and archived.')


if __name__ == '__main__':
    main()
