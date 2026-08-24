from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtWidgets import QOpenGLWidget
from PyQt5.QtGui import QSurfaceFormat
import numpy as np
import math
import colorsys

_PREFS_VERSION = 2   # bump when defaults change to force a reset
##TODO: get sub_on_startup working at some point
_PREFS = {
    'contextual_rendering': True,
    'medium_threshold': 6000,
    'low_threshold': 10000,
    'advanced_on_startup': False,
    # 'sub_on_startup': False,
}
##fancy graphics changes, which can be changed if you're wanting to create HUGE tilings
_antialias = True
_current_msaa = 8


def _load_prefs():
    s = QtCore.QSettings("HyperTiler", "HyperTiler")
    if s.value('prefs_version', 0, type=int) < _PREFS_VERSION:
        s.clear()
        s.setValue('prefs_version', _PREFS_VERSION)
        return                          # keep code defaults as-is
    for key, default in _PREFS.items():
        val = s.value(key, default)
        if isinstance(default, bool):
            _PREFS[key] = val if isinstance(val, bool) else str(val).lower() in ('true', '1', 'yes')
        elif isinstance(default, int):
            try:
                _PREFS[key] = int(val)
            except (ValueError, TypeError):
                _PREFS[key] = default


def _save_prefs():
    s = QtCore.QSettings("HyperTiler", "HyperTiler")
    s.setValue('prefs_version', _PREFS_VERSION)
    for key, val in _PREFS.items():
        s.setValue(key, val)


def _estimate_tile_count(n_vectors, n_grids):
    n_combs = n_vectors * (n_vectors - 1) // 2
    return int(n_combs * (n_grids ** 2) * 0.3)


def _quality_for_count(count):
    if not _PREFS['contextual_rendering']:
        return 'high'
    if count > _PREFS['low_threshold']:
        return 'low'
    if count > _PREFS['medium_threshold']:
        return 'medium'
    return 'high'


def _apply_quality(plot_widget, quality):
    global _antialias, _current_msaa
    samples = {'high': 8, 'medium': 4, 'low': 0}[quality]
    _antialias = (quality != 'low')
    if samples != _current_msaa:
        fmt = QSurfaceFormat()
        fmt.setSamples(samples)
        vp = QOpenGLWidget()
        vp.setFormat(fmt)
        plot_widget.setViewport(vp)
        _current_msaa = samples

##the colour scheme etc.

APP_STYLESHEET = """
QWidget {
    font-family: 'Segoe UI', Arial, sans-serif;
    font-size: 9pt;
    color: #2c3e50;
}
QGroupBox {
    background-color: #f0f0f0;
    border: 1px solid #dde1e7;
    border-radius: 6px;
    margin-top: 14px;
    padding-top: 6px;
    font-weight: 600;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 8px;
    padding: 0 4px;
    color: #4a6fa5;
}
QPushButton {
    background-color: #4a6fa5;
    color: white;
    border: none;
    border-radius: 4px;
    padding: 5px 12px;
    min-height: 22px;
}
QPushButton:hover { background-color: #3a5a8c; }
QPushButton:pressed { background-color: #2d4a74; }
QPushButton:checked { background-color: #1e6641; }
QPushButton:disabled { background-color: #b0b8c1; color: #7f8c8d; }
QSpinBox, QDoubleSpinBox {
    border: 1px solid #c8cfd8;
    border-radius: 4px;
    padding: 2px 4px;
    background-color: white;
}
QSpinBox:focus, QDoubleSpinBox:focus { border: 1px solid #4a6fa5; }
QComboBox {
    border: 1px solid #c8cfd8;
    border-radius: 4px;
    padding: 2px 8px;
    background-color: white;
    min-height: 22px;
}
QComboBox:focus { border: 1px solid #4a6fa5; }
QComboBox::drop-down { border: none; width: 20px; }
QLineEdit {
    border: 1px solid #c8cfd8;
    border-radius: 4px;
    padding: 2px 6px;
    background-color: white;
}
QLineEdit:focus { border: 1px solid #4a6fa5; }
QLabel { background-color: transparent; }
QMenuBar {
    background-color: #2c3e50;
    color: white;
}
QMenuBar::item { background: transparent; padding: 4px 10px; }
QMenuBar::item:selected { background-color: #4a6fa5; }
QMenu {
    background-color: white;
    border: 1px solid #dde1e7;
    padding: 4px;
}
QMenu::item { padding: 6px 24px 6px 12px; }
QMenu::item:selected { background-color: #4a6fa5; color: white; }
QTableView {
    border: 1px solid #dde1e7;
    gridline-color: #eef0f2;
    background-color: white;
    selection-background-color: #4a6fa5;
    selection-color: white;
}
QHeaderView::section {
    background-color: #eef0f2;
    border: none;
    border-right: 1px solid #dde1e7;
    border-bottom: 1px solid #dde1e7;
    padding: 4px 8px;
    font-weight: 600;
    color: #4a6fa5;
}
QScrollBar:vertical {
    border: none; background: #f0f2f5; width: 8px; border-radius: 4px;
}
QScrollBar::handle:vertical {
    background: #c8cfd8; border-radius: 4px; min-height: 20px;
}
QScrollBar::handle:vertical:hover { background: #a0abb8; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal {
    border: none; background: #f0f2f5; height: 8px; border-radius: 4px;
}
QScrollBar::handle:horizontal {
    background: #c8cfd8; border-radius: 4px; min-width: 20px;
}
QScrollBar::handle:horizontal:hover { background: #a0abb8; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QDockWidget::title {
    background-color: #eef0f2;
    padding: 6px;
    border-bottom: 1px solid #dde1e7;
    font-weight: 600;
}
QCheckBox { spacing: 6px; }
QCheckBox::indicator {
    width: 15px; height: 15px;
    border-radius: 3px;
    border: 1px solid #c8cfd8;
    background-color: white;
}
QCheckBox::indicator:checked {
    background-color: #4a6fa5;
    border-color: #4a6fa5;
}
"""

## a daft idea, but change the icon of the gui to different polygons on startup
def make_app_icon():
    size = 64
    pixmap = QtGui.QPixmap(size, size)
    pixmap.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(pixmap)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    p.setBrush(QtGui.QBrush(QtGui.QColor(74, 111, 165)))
    p.setPen(QtCore.Qt.NoPen)
    p.drawRoundedRect(0, 0, size, size, 12, 12)
    cx, cy = size / 2.0, size / 2.0
    n = np.random.randint(3, 10)
    r_out, r_in = 26, 10
    hues = list(np.random.random(n))
    for i in range(n):
        a1 = 2 * math.pi * i / n - math.pi / 2
        a2 = 2 * math.pi * (i + 1) / n - math.pi / 2
        am = (a1 + a2) / 2
        pts = [
            QtCore.QPointF(cx, cy),
            QtCore.QPointF(cx + r_in * math.cos(a1), cy + r_in * math.sin(a1)),
            QtCore.QPointF(cx + r_out * math.cos(am), cy + r_out * math.sin(am)),
            QtCore.QPointF(cx + r_in * math.cos(a2), cy + r_in * math.sin(a2)),
        ]
        r, g, b = colorsys.hsv_to_rgb(hues[i], 0.55, 1.0)
        p.setBrush(QtGui.QBrush(QtGui.QColor(int(r * 255), int(g * 255), int(b * 255), 220)))
        p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255), 1.0))
        p.drawPolygon(pts)
    p.end()
    return QtGui.QIcon(pixmap)


class PreferencesDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Preferences")
        self.setModal(True)
        self.setFixedWidth(360)
        layout = QtWidgets.QVBoxLayout(self)

        render_grp = QtWidgets.QGroupBox("Rendering")
        render_lay = QtWidgets.QVBoxLayout(render_grp)
        self.contextual_cb = QtWidgets.QCheckBox("Auto-adjust quality for large tilings")
        self.contextual_cb.setChecked(_PREFS['contextual_rendering'])
        render_lay.addWidget(self.contextual_cb)

        thresh_form = QtWidgets.QFormLayout()
        self.medium_spin = QtWidgets.QSpinBox()
        self.medium_spin.setRange(100, 200000)
        self.medium_spin.setSingleStep(500)
        self.medium_spin.setValue(_PREFS['medium_threshold'])
        thresh_form.addRow("Reduce MSAA above (est. tiles):", self.medium_spin)

        self.low_spin = QtWidgets.QSpinBox()
        self.low_spin.setRange(100, 200000)
        self.low_spin.setSingleStep(500)
        self.low_spin.setValue(_PREFS['low_threshold'])
        thresh_form.addRow("Disable AA + MSAA above:", self.low_spin)
        render_lay.addLayout(thresh_form)

        note = QtWidgets.QLabel(
            "Tile count is estimated before rendering.\n"
            "Changes take effect on the next tiling generation.")
        note.setStyleSheet("color: #888; font-size: 8pt;")
        note.setWordWrap(True)
        render_lay.addWidget(note)
        layout.addWidget(render_grp)

        startup_grp = QtWidgets.QGroupBox("Startup")
        startup_lay = QtWidgets.QVBoxLayout(startup_grp)
        self.advanced_startup_cb = QtWidgets.QCheckBox("Show Advanced window on startup")
        self.advanced_startup_cb.setChecked(_PREFS['advanced_on_startup'])
        startup_lay.addWidget(self.advanced_startup_cb)

        # self.sub_startup_cb = QtWidgets.QCheckBox("Show sub window on startup")
        # self.sub_startup_cb.setChecked(_PREFS['sub_on_startup'])
        # startup_lay.addWidget(self.sub_startup_cb)

        layout.addWidget(startup_grp)

        btn_h = QtWidgets.QHBoxLayout()
        reset_btn = QtWidgets.QPushButton("Reset to defaults")
        reset_btn.clicked.connect(self._reset_defaults)
        btn_h.addWidget(reset_btn)
        btn_h.addStretch()
        ok_btn = QtWidgets.QPushButton("OK")
        ok_btn.setDefault(True)
        ok_btn.clicked.connect(self._save_and_accept)
        cancel_btn = QtWidgets.QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_h.addWidget(ok_btn)
        btn_h.addWidget(cancel_btn)
        layout.addLayout(btn_h)

        self.contextual_cb.toggled.connect(self.medium_spin.setEnabled)
        self.contextual_cb.toggled.connect(self.low_spin.setEnabled)
        self.medium_spin.setEnabled(_PREFS['contextual_rendering'])
        self.low_spin.setEnabled(_PREFS['contextual_rendering'])

    def _reset_defaults(self):
        _defaults = {
            'contextual_rendering': True,
            'medium_threshold': 6000,
            'low_threshold': 10000,
            'advanced_on_startup': False,
            # 'sub_on_startup': False,
        }
        self.contextual_cb.setChecked(_defaults['contextual_rendering'])
        self.medium_spin.setValue(_defaults['medium_threshold'])
        self.low_spin.setValue(_defaults['low_threshold'])
        self.advanced_startup_cb.setChecked(_defaults['advanced_on_startup'])
        # self.sub_startup_cb.setChecked(_defaults['sub_on_startup'])

    def _save_and_accept(self):
        _PREFS['contextual_rendering'] = self.contextual_cb.isChecked()
        _PREFS['medium_threshold'] = self.medium_spin.value()
        _PREFS['low_threshold'] = self.low_spin.value()
        _PREFS['advanced_on_startup'] = self.advanced_startup_cb.isChecked()
        # _PREFS['sub_on_startup'] = self.sub_startup_cb.isChecked()
        _save_prefs()
        self.accept()
