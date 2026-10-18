"""Shared Qt controls, vector toolbar icons and accessible workshop styling."""
from __future__ import annotations
from pathlib import Path
from PySide6 import QtCore as C, QtGui as G, QtWidgets as W
from PySide6.QtSvg import QSvgRenderer

STYLE = '''
QWidget { background:#f4f6fa; color:#26364a; font-family:"Inter","Segoe UI","DejaVu Sans"; font-size:13px; }
QMainWindow, QDialog { background:#f4f6fa; }
QToolBar { background:white; border:0; border-bottom:1px solid #dce3ed; spacing:6px; padding:10px; }
QToolBar QToolButton { background:white; border:0; border-radius:8px; padding:10px 12px; }
QToolButton:hover, QPushButton:hover { background:#e9eef7; }
QToolButton:checked { background:#dcefe8; color:#08785d; }
QPushButton { background:white; border:1px solid #d4dce7; border-radius:7px; padding:9px 13px; }
QPushButton#primary { background:#087f67; color:white; border:0; font-weight:600; }
QPushButton#primary:hover { background:#096a58; }
QPushButton:disabled, QToolButton:disabled, QPushButton#primary:disabled { color:#8b98a8; background:#e8edf3; border-color:#e0e6ee; }
QLabel#heading { font-size:20px; font-weight:600; }
QLabel#muted { color:#697a8c; background:transparent; }
QLabel#section { font-weight:600; font-size:14px; margin-top:10px; }
QLineEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox { background:white; border:1px solid #d4dce7; border-radius:6px; padding:7px; selection-background-color:#c8e4dc; }
QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus { border:1px solid #158972; }
QComboBox QAbstractItemView { background:white; selection-background-color:#dcefe8; }
QGroupBox { background:white; border:1px solid #dce3ed; border-radius:10px; margin-top:16px; padding:16px 10px 10px; }
QGroupBox::title { subcontrol-origin:margin; left:12px; padding:0 5px; font-weight:600; }
QGroupBox QLabel { background:transparent; }
QTabWidget::pane { border:0; background:#f4f6fa; }
QTabBar::tab { background:transparent; padding:12px 17px; border-bottom:3px solid transparent; }
QTabBar::tab:selected { border-bottom:3px solid #087f67; color:#087f67; font-weight:600; }
QScrollArea, QScrollArea>QWidget>QWidget { border:0; background:#f4f6fa; }
QScrollBar:vertical { background:transparent; width:10px; margin:2px; }
QScrollBar::handle:vertical { background:#b9c6d5; border-radius:4px; min-height:30px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background:transparent; }
QListWidget, QTreeWidget, QTableWidget { background:white; border:1px solid #dce3ed; border-radius:8px; alternate-background-color:#f7f9fc; }
QListWidget::item { padding:12px; border-bottom:1px solid #edf1f7; }
QListWidget::item:selected, QTreeWidget::item:selected, QTableWidget::item:selected { background:#e0f0ea; color:#08654f; }
QHeaderView::section { background:#edf2f7; padding:9px; border:0; font-weight:600; }
QStatusBar { background:white; border-top:1px solid #dce3ed; }
QSplitter::handle { background:#e5eaf1; }
QToolTip { background:#26364a; color:white; padding:7px; border:0; }
'''

PATHS = {
    'new': '<path d="M12 5v14M5 12h14"/>',
    'open': '<path d="M3 7h7l2 2h9v11H3zM3 7V4h7l2 3h9v2"/>',
    'save': '<path d="M4 3h14l3 3v15H3V3zM7 3v6h10V3M7 21v-8h10v8"/>',
    'import': '<path d="M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5"/>',
    'select': '<path d="m5 3 14 10-7 1-3 7z"/>',
    'raise': '<path d="m3 20 6-8 4 5 3-4 5 7M12 3v8m-3-5 3-3 3 3"/>',
    'lower': '<path d="m3 20 6-8 4 5 3-4 5 7M12 3v8m-3-3 3 3 3-3"/>',
    'flatten': '<path d="M3 16h18M5 20h14M6 3v8m-3-3 3 3 3-3M18 11V3m-3 3 3-3 3 3"/>',
    'smooth': '<path d="M3 16c3-10 5 10 9 0s6 0 9-3M3 7h18"/>',
    'trees': '<path d="m12 2-6 7h3l-5 7h6v6h4v-6h6l-5-7h3z"/>',
    'erase_trees': '<path d="m12 2-6 7h3l-5 7h6v6h4M16 14l6 6m0-6-6 6"/>',
    'graph': '<rect x="2" y="3" width="7" height="5" rx="1"/><rect x="15" y="16" width="7" height="5" rx="1"/><path d="M9 5h5v14h1M9 19H2v-5h7z"/>',
    'assets': '<path d="M3 3h18v18H3zM3 17l6-6 4 4 3-3 5 5"/><circle cx="16" cy="7" r="2"/>',
    'objects': '<path d="m12 2 10 5v11l-10 5-10-5V7zM2 7l10 5 10-5M12 12v11"/>',
    'build': '<path d="m14 3 7 7-4 4-2-2-9 9-3-3 9-9-2-2z"/>',
    'test': '<path d="m5 12 4 4L20 5M20 12v8H3V3h9"/>',
    'play': '<path d="m7 3 14 9L7 21z"/>',
    'fit': '<path d="M3 9V3h6m6 0h6v6M3 15v6h6m6 0h6v-6M8 12h8m-4-4v8"/>',
    'undo': '<path d="M4 9h10a7 7 0 0 1 0 14M4 9l5-5M4 9l5 5"/>',
    'redo': '<path d="M20 9H10a7 7 0 0 0 0 14M20 9l-5-5M20 9l-5 5"/>',
    'delete': '<path d="M3 6h18M9 6V3h6v3M6 6l1 15h10l1-15M10 10v7m4-7v7"/>',
    'help': '<circle cx="12" cy="12" r="10"/><path d="M9 8a3 3 0 0 1 6 0c0 3-3 2-3 5M12 17v.1"/>',
}


def icon(name, colour='#3c5c78'):
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="{colour}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">{PATHS.get(name, PATHS["objects"])}</svg>'
    pixmap = G.QPixmap(48, 48); pixmap.fill(C.Qt.GlobalColor.transparent)
    painter = G.QPainter(pixmap)
    QSvgRenderer(C.QByteArray(svg.encode())).render(painter)
    painter.end()
    return G.QIcon(pixmap)


def label(text, style=None, wrap=True):
    widget = W.QLabel(text)
    widget.setWordWrap(wrap)
    if style: widget.setObjectName(style)
    return widget


def button(text, action, name=None, primary=False):
    widget = W.QPushButton(icon(name) if name else G.QIcon(), text)
    if primary: widget.setObjectName('primary')
    widget.clicked.connect(action)
    return widget


def scroll_parent(widget, event):
    parent = widget.parentWidget()
    while parent is not None:
        if isinstance(parent, W.QScrollArea):
            bar = parent.verticalScrollBar()
            delta = event.pixelDelta().y() or event.angleDelta().y() / 120 * bar.singleStep() * 3
            bar.setValue(bar.value() - round(delta));event.accept();return
        parent = parent.parentWidget()
    event.ignore()


class Spin(W.QDoubleSpinBox):
    def __init__(self, value=0, minimum=-1e9, maximum=1e9, decimals=3, suffix='', parent=None):
        super().__init__(parent)
        self.setRange(minimum, maximum);self.setDecimals(decimals);self.setValue(value);self.setSuffix(suffix)
        self.setFocusPolicy(C.Qt.FocusPolicy.StrongFocus)
    def wheelEvent(self, event): scroll_parent(self, event)


class Combo(W.QComboBox):
    def __init__(self, choices=(), parent=None):
        super().__init__(parent);self.addItems(choices)
        self.setFocusPolicy(C.Qt.FocusPolicy.StrongFocus)
    def wheelEvent(self, event): scroll_parent(self, event)


class FilePicker(W.QWidget):
    changed = C.Signal(str)
    def __init__(self, title='Choose file', filter='All files (*)', directory=False, value='', parent=None):
        super().__init__(parent)
        self.title, self.filter, self.directory = title, filter, directory
        layout = W.QHBoxLayout(self);layout.setContentsMargins(0,0,0,0)
        self.path = W.QLineEdit(value);self.path.setReadOnly(True);self.path.setPlaceholderText('Choose a folder…' if directory else 'Choose a file…')
        self.path.setToolTip(value)
        self.choose_button = button('Browse…', self.choose, 'open')
        layout.addWidget(self.path, 1);layout.addWidget(self.choose_button)
    def choose(self):
        value = W.QFileDialog.getExistingDirectory(self, self.title, self.path.text()) if self.directory else W.QFileDialog.getOpenFileName(self, self.title, self.path.text(), self.filter)[0]
        if value: self.set_value(value);self.changed.emit(value)
    def value(self): return self.path.text()
    def set_value(self, value): self.path.setText(str(value));self.path.setToolTip(str(value))


def scroll(widget):
    area = W.QScrollArea();area.setWidgetResizable(True);area.setWidget(widget)
    area.setHorizontalScrollBarPolicy(C.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    return area


def row(*widgets):
    result=W.QWidget();layout=W.QHBoxLayout(result);layout.setContentsMargins(0,0,0,0)
    for widget in widgets: layout.addWidget(widget)
    return result


def editor_font():
    font=G.QFont('JetBrains Mono');font.setStyleHint(G.QFont.StyleHint.Monospace);font.setPointSize(11)
    return font


class LuaHighlighter(G.QSyntaxHighlighter):
    def highlightBlock(self, text):
        formats=[]
        for pattern, colour in [(r'\b(?:local|function|end|if|then|else|elseif|for|while|do|return|true|false|nil|and|or|not|in)\b','#9260b5'),
                                (r'\b\d+(?:\.\d+)?\b','#b36c25'), (r'"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'','#158567'), (r'--.*$','#8190a3')]:
            fmt=G.QTextCharFormat();fmt.setForeground(G.QColor(colour))
            expression=C.QRegularExpression(pattern);matches=expression.globalMatch(text)
            while matches.hasNext():
                match=matches.next();self.setFormat(match.capturedStart(),match.capturedLength(),fmt)
