from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QDoubleValidator, QFont, QSurfaceFormat
from PyQt5.QtWidgets import QOpenGLWidget
from pyqtgraph.exporters import ImageExporter
import pyqtgraph as pg
import numpy as np
import math
import colorsys
import json
import os

from .config import (
    _PREFS, _estimate_tile_count, _quality_for_count, _apply_quality,
    APP_STYLESHEET, make_app_icon, PreferencesDialog,
)
from .tiling import TileMaker
from .ink2tile import write_svg
from .graphics import tilePlot, pointPlot, vectorPlotting, edgePlot, gridPlot
from .widgets import LockedViewBox, DecimalDelegate, TableModel, TileSwatchButton, center_on_screen
from .workers import _VertexWorker
from .tools.style_dialog import StyleDialog
from .tools.vertex_finder import VertexFinderWindow
from .tools.network import NetworkBuilderWindow
from .substitution.window import SubstitutionWindow
from .substitution.adapter import _SubstitutionAdapter


def _make_tonal_colors(n, base_hex):
    """n distinct tones/shades around a single base colour, rather than
    the default scheme's full hue-circle spacing. Hue stays close to the
    base; saturation and value are what vary,
    stepped with the golden ratio so nearby indices still look distinct."""
    base_h, _, _, _ = QtGui.QColor(base_hex).getHsvF()
    if base_h < 0:  # QColor reports hue -1 for achromatic (grey) colours
        base_h = 0.0
    colors = []
    g = 0.0
    for i in range(n):
        g = (g + 0.618) % 1.0
        hue = (base_h + (g - 0.5) * 0.12) % 1.0
        sat = 0.35 + 0.35 * ((i * 0.618) % 1.0)
        val = 0.55 + 0.35 * (((i * 0.382) + 0.5) % 1.0)
        r, gg, b = colorsys.hsv_to_rgb(hue, sat, val)
        colors.append((r * 255, gg * 255, b * 255))
    return colors

##for better or worse, all my own design, with variable names, structure etc. cleaned up by Claude. \
# vecPlotFindItemPlease wasn't cutting it for documentation...

class createAdvancedWindow(QtWidgets.QWidget):
    def __init__(self, ui_ref):
        super().__init__()
        self._ui = ui_ref
        # debounced full tiling regeneration while live-editing vectors -
        # a full rebuild can run from tens of ms to well over half a second
        # depending on fold/grid_len, so regenerating on every scroll tick
        # would freeze the UI
        self._live_regen_timer = QtCore.QTimer(self)
        self._live_regen_timer.setSingleShot(True)
        self._live_regen_timer.timeout.connect(self._live_regenerate)
        self._setup()
        ui_ref.windows_open['advancedWindow'] = True

    def _live_regenerate(self):
        # without this, generateTiling() would call _makeColors() again,
        # which picks a fresh random starting hue every time
        ui = self._ui
        if hasattr(ui, 'current_colors'):
            ui._pending_colors = list(ui.current_colors)
        ui.generateTiling()

    def _setup(self):
        font = QFont()
        font.setPointSize(8)
        self.resize(596, 418)
        self.setSizePolicy(QtWidgets.QSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed))

        root = QtWidgets.QVBoxLayout(self)

        top = QtWidgets.QHBoxLayout()

        cust = QtWidgets.QGroupBox("Vector customisation")
        cust_lay = QtWidgets.QVBoxLayout(cust)
        cust_lay.addItem(QtWidgets.QSpacerItem(20, 5, QtWidgets.QSizePolicy.Minimum,
                                               QtWidgets.QSizePolicy.Fixed))
        form = QtWidgets.QFormLayout()
        labels = ["Tile scale:", "Grid scale:", "Angle:", "Grid shift:"]
        validators = [
            QDoubleValidator(-1e10, 1e10, 3),
            QDoubleValidator(-1e10, 1e10, 3),
            QDoubleValidator(0.0, 360.0, 2),
            QDoubleValidator(-1e10, 1e10, 3),
        ]
        self.lineEdits = []
        for i, (lbl, val) in enumerate(zip(labels, validators)):
            le = QtWidgets.QLineEdit()
            le.setMaximumWidth(75)
            val.setNotation(QDoubleValidator.StandardNotation)
            le.setValidator(val)
            form.addRow(lbl, le)
            self.lineEdits.append(le)
        cust_lay.addLayout(form)
        top.addWidget(cust)

        gvp = QtWidgets.QGroupBox("Grid vectors")
        gvp.setFixedSize(310, 320)
        gvp_lay = QtWidgets.QVBoxLayout(gvp)
        self.gridVectorPlot = pg.PlotWidget()
        self.gridVectorPlot.setFixedSize(288, 288)
        self.gridVectorPlot.setBackground('w')
        self.gridVectorPlot.getPlotItem().hideAxis('bottom')
        self.gridVectorPlot.getPlotItem().hideAxis('left')
        self.gridVectorPlot.hideButtons()
        self.gridVectorPlot.getViewBox().setAspectLocked(True)
        self.gridVectorPlot.setMouseEnabled(x=False, y=False)
        self.gridVectorPlot.getViewBox().menu = None
        self.gridVectorPlot.scene().contextMenuEvent = lambda e: None
        gvp_lay.addWidget(self.gridVectorPlot)
        top.addWidget(gvp)
        top.setStretch(1, 2)
        root.addLayout(top)

        bot = QtWidgets.QHBoxLayout()
        self.tableView = QtWidgets.QTableView()
        self.tableView.horizontalHeader().setSectionResizeMode(
            QtWidgets.QHeaderView.Stretch)
        bot.addWidget(self.tableView)

        btn_col = QtWidgets.QVBoxLayout()
        self.pushButton_2 = QtWidgets.QPushButton("New")
        self.pushButton_2.clicked.connect(self.on_new)
        self.pushButton = QtWidgets.QPushButton("Delete")
        self.pushButton.clicked.connect(self.on_delete)
        btn_col.addWidget(self.pushButton_2)
        btn_col.addWidget(self.pushButton)
        btn_col.addStretch()
        bot.addLayout(btn_col)
        bot.setStretch(0, 4)
        bot.setStretch(1, 1)
        root.addLayout(bot)
        root.setStretch(0, 2)
        root.setStretch(1, 3)

        self.current_row = None
        for col, le in enumerate(self.lineEdits):
            le.editingFinished.connect(
                lambda col=col, le=le: self.on_line_edit_finished(col, le))

        vec_item = vectorPlotting(self._ui.vector_data, 'grid')
        self.gridVectorPlot.addItem(vec_item)
        self.gridVectorPlot.enableAutoRange()

    def dataGrab(self):
        self.model = TableModel(
            self._ui.vector_data, ['Tile scale', 'Grid scale', 'Angle', 'Grid shift'])
        self.tableView.setModel(self.model)
        self.tableView.verticalHeader().sectionClicked.connect(self.on_row_header_clicked)
        self.tableView.horizontalHeader().sectionClicked.connect(self.on_col_header_clicked)
        self.tableView.clicked.connect(self.on_cell_clicked)
        self.model.dataChanged.connect(self.on_cell_edited)
        # delegates must be kept alive on self - setItemDelegateForColumn does
        # not take ownership, so a bare temporary gets garbage-collected right
        # after this call and the view is left holding a dangling pointer to
        # it, which segfaults on the next paint/layout pass.
        self._column_delegates = [
            DecimalDelegate(decimals=3, minimum=-1e10, maximum=1e10, step=0.1,
                            live_callback=self.on_live_vector_change),
            DecimalDelegate(decimals=3, minimum=-1e10, maximum=1e10, step=0.1,
                            live_callback=self.on_live_vector_change),
            DecimalDelegate(decimals=2, minimum=0.0, maximum=360.0, step=1.0,
                            live_callback=self.on_live_vector_change),
            DecimalDelegate(decimals=3, minimum=-1e10, maximum=1e10, step=0.1,
                            live_callback=self.on_live_vector_change),
        ]
        for col, delegate in enumerate(self._column_delegates):
            self.tableView.setItemDelegateForColumn(col, delegate)

    def on_live_vector_change(self, row, col, value):
        """Fires on every tick of a vector spin box (scroll, steppers,
        typing). The cheap parts run immediately: redraw the vector arrows,
        and if Grid view is showing, rebuild just the grid lines. The actual tiling is
        expensive (tens of ms to well over half a second depending on
        fold/grid_len), so it's debounced - each tick restarts a timer, and
        the real regenerate only fires once ticks stop arriving for a
        moment, instead of on every single one."""
        self._ui.vector_data[row][col] = value
        self._ui._refreshVectorPlot()
        self.gridVectorPlot.clear()
        self.gridVectorPlot.addItem(vectorPlotting(self._ui.vector_data, 'grid'))
        self.gridVectorPlot.enableAutoRange()

        ui = self._ui
        if ui.plotted and ui.gridView.isChecked():
            grid, _ = TileMaker.build_grid(ui.vector_data, ui.sizeValue.value())
            was_visible = ui.gridItem.isVisible()
            ui.tilingPlot.removeItem(ui.gridItem)
            ui.gridItem = gridPlot(grid, ui.grid_color, ui.grid_width)
            ui.tilingPlot.addItem(ui.gridItem)
            ui.gridItem.setZValue(ui.tileItem.zValue() - 1)
            if not was_visible:
                ui.gridItem.hide()

        # "Random"/"Regular random" shift modes regenerate shifts from
        # scratch on every generateTiling() call (see updateShift()), which
        # would silently overwrite a manually-edited shift before the
        # debounced regen even used it
        if ui.plotted and ui.shiftSelect.currentIndex() not in (2, 3):
            self._live_regen_timer.start(200)

    def _fill_edits(self, row_data):
        for le, val in zip(self.lineEdits, row_data):
            le.setText(val)

    def on_row_header_clicked(self, idx):
        self.current_row = idx
        row_data = [self.model.data(self.model.index(idx, c), Qt.DisplayRole)
                    for c in range(self.model.columnCount())]
        self._fill_edits(row_data)

    def on_col_header_clicked(self, idx):
        col_data = [self.model.data(self.model.index(r, idx), Qt.DisplayRole)
                    for r in range(self.model.rowCount())]
        self._fill_edits(col_data)

    def on_cell_clicked(self, index):
        row_data = [self.model.data(self.model.index(index.row(), c), Qt.DisplayRole)
                    for c in range(self.model.columnCount())]
        self._fill_edits(row_data)

    def on_cell_edited(self, index):
        row_data = [self.model.data(self.model.index(index.row(), c), Qt.DisplayRole)
                    for c in range(self.model.columnCount())]
        for col, (le, val) in enumerate(zip(self.lineEdits, row_data)):
            v = round(float(val), 3)
            le.setText(str(v))
            self._ui.vector_data[index.row()][col] = v
        self._ui.editVector(self._ui.vector_data)

    def on_line_edit_finished(self, col, le):
        row = self.tableView.currentIndex().row()
        value = le.text()
        self.model.setData(self.model.index(row, col), value, Qt.EditRole)
        self._ui.vector_data[row][col] = float(value)
        self._ui.editVector(self._ui.vector_data)

    def on_delete(self):
        sel = self.tableView.selectedIndexes()
        if not sel:
            return
        row = sel[0].row()
        self._ui.vector_data = np.delete(self._ui.vector_data, row, axis=0)
        self._ui.symmetryValue.blockSignals(True)
        self._ui.symmetryValue.setValue(self._ui.symmetryValue.value() - 1)
        self._ui.symmetryValue.blockSignals(False)
        self._refresh_vector_plots()
        self.model.removeRow(row)

    def on_new(self):
        row = [1.0, 1.0, 0.0, 0.0]
        self._ui.vector_data = np.vstack([self._ui.vector_data, row])
        self._ui.symmetryValue.blockSignals(True)
        self._ui.symmetryValue.setValue(self._ui.symmetryValue.value() + 1)
        self._ui.symmetryValue.blockSignals(False)
        idx = self.model.rowCount()
        self.model.insertRow(idx)
        self.model.set_row_data(idx, row)
        self._refresh_vector_plots()

    def _refresh_vector_plots(self):
        for plot, kind in [(self._ui.vectorPlot, 'real'), (self.gridVectorPlot, 'grid')]:
            plot.clear()
            plot.addItem(vectorPlotting(self._ui.vector_data, kind))
            plot.enableAutoRange()


class Ui_MainWindow(object):

    def setupUi(self, MainWindow):
        self._main_window = MainWindow

        MainWindow.setObjectName("HyperTiler")
        MainWindow.resize(1050, 800)
        sp = QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Preferred,
                                   QtWidgets.QSizePolicy.Preferred)
        MainWindow.setSizePolicy(sp)
        MainWindow.setFixedSize(1050, 800)

        screen = QtWidgets.QApplication.desktop().screenGeometry()
        MainWindow.move((screen.width() - 1050) // 2 - 200,
                        (screen.height() - 800) // 3)

        font8 = QFont()
        font8.setPointSize(8)
        self.windows_open = {}
        self.plotted = False
        self.tileItem = None
        self.vertItem = None
        self.edgeItem = None
        self.gridItem = None
        self.edge_was_checked = False
        self._in_sub_mode = False
        self.edge_color = (0, 0, 0)
        self.edge_width = 2.0
        self.point_color = (0, 0, 0)
        self.point_radius = 0.2
        self.grid_color = (100, 149, 237)
        self.grid_width = 2.0

        self.centralwidget = QtWidgets.QWidget(MainWindow)
        root_h = QtWidgets.QHBoxLayout(self.centralwidget)

        # ---- left panel ----
        self.parameterArea = QtWidgets.QFrame()
        self.parameterArea.setFrameShape(QtWidgets.QFrame.StyledPanel)
        left_v = QtWidgets.QVBoxLayout(self.parameterArea)
        left_v.setContentsMargins(-1, 10, -1, -1)

        self.vectorPlot = pg.PlotWidget()
        self.vectorPlot.setFixedSize(288, 288)
        self.vectorPlot.setBackground('w')
        self.vectorPlot.getPlotItem().hideAxis('bottom')
        self.vectorPlot.getPlotItem().hideAxis('left')
        self.vectorPlot.hideButtons()
        self.vectorPlot.getViewBox().setAspectLocked(True)
        left_v.addWidget(self.vectorPlot)
        left_v.addItem(QtWidgets.QSpacerItem(20, 10, QtWidgets.QSizePolicy.Minimum,
                                             QtWidgets.QSizePolicy.Maximum))

        self.parameterGroup = QtWidgets.QGroupBox("Tiling parameters")
        self.parameterGroup.setFont(font8)
        pg_v = QtWidgets.QVBoxLayout(self.parameterGroup)
        pg_v.setContentsMargins(-1, -1, -1, 0)

        shift_h = QtWidgets.QHBoxLayout()
        self.shiftLabel = QtWidgets.QLabel("Grid shifts:")
        self.shiftSelect = QtWidgets.QComboBox()
        for item in ("Regular", "Zero", "Random", "Regular random"):
            self.shiftSelect.addItem(item)
        shift_h.addWidget(self.shiftLabel)
        shift_h.addWidget(self.shiftSelect)
        shift_h.addItem(QtWidgets.QSpacerItem(69, 20, QtWidgets.QSizePolicy.Maximum,
                                              QtWidgets.QSizePolicy.Minimum))
        pg_v.addLayout(shift_h)
        self.shiftSelect.activated.connect(self.updateShift)

        pg_v.addItem(QtWidgets.QSpacerItem(20, 5, QtWidgets.QSizePolicy.Minimum,
                                           QtWidgets.QSizePolicy.Maximum))

        sym_h = QtWidgets.QHBoxLayout()
        self.symmetryLabel = QtWidgets.QLabel("No. of vectors:")
        self.symmetryValue = QtWidgets.QSpinBox()
        self.symmetryValue.setFixedSize(60, 20)
        self.symmetryValue.setMinimum(3)
        sym_h.addWidget(self.symmetryLabel)
        sym_h.addWidget(self.symmetryValue)
        sym_h.addItem(QtWidgets.QSpacerItem(110, 20, QtWidgets.QSizePolicy.Maximum,
                                            QtWidgets.QSizePolicy.Minimum))
        pg_v.addLayout(sym_h)
        self.symmetryValue.valueChanged.connect(self.updateVector)

        size_h = QtWidgets.QHBoxLayout()
        self.sizeLabel = QtWidgets.QLabel("No. of grids:")
        self.sizeValue = QtWidgets.QSpinBox()
        self.sizeValue.setFixedSize(60, 20)
        self.sizeValue.setValue(10)
        size_h.addWidget(self.sizeLabel)
        size_h.addWidget(self.sizeValue)
        size_h.addItem(QtWidgets.QSpacerItem(110, 20, QtWidgets.QSizePolicy.Maximum,
                                             QtWidgets.QSizePolicy.Minimum))
        pg_v.addLayout(size_h)

        pg_v.addItem(QtWidgets.QSpacerItem(20, 10, QtWidgets.QSizePolicy.Minimum,
                                           QtWidgets.QSizePolicy.Fixed))

        self.advancedButton = QtWidgets.QPushButton("Advanced...")
        adv_h = QtWidgets.QHBoxLayout()
        adv_h.addWidget(self.advancedButton)
        pg_v.addLayout(adv_h)

        left_v.addWidget(self.parameterGroup)

        self.tileButton = QtWidgets.QPushButton("Tile!")
        left_v.addWidget(self.tileButton)
        left_v.addItem(QtWidgets.QSpacerItem(20, 240, QtWidgets.QSizePolicy.Minimum,
                                             QtWidgets.QSizePolicy.Fixed))

        self.vector_data = self._vectorSetup(5, 0)
        self.symmetryValue.setValue(5)
        self._refreshVectorPlot()

        self.advancedDock = QtWidgets.QDockWidget("Advanced Settings", MainWindow)
        self.advancedWindow = createAdvancedWindow(self)
        self.advancedDock.setWidget(self.advancedWindow)
        MainWindow.addDockWidget(QtCore.Qt.RightDockWidgetArea, self.advancedDock)
        self.advancedDock.setFeatures(QtWidgets.QDockWidget.DockWidgetClosable)
        self.advancedDock.setFloating(False)
        self.advancedDock.closeEvent = self.closeAdvancedDock
        self.original_size = MainWindow.size()

        ##TODO: you can add a sub on startup similar logic here
        if _PREFS.get('advanced_on_startup', False):
            self.advancedDock.show()
            w = self.original_size.width() + self.advancedDock.sizeHint().width()
            MainWindow.setFixedSize(w, self.original_size.height())
        else:
            self.advancedDock.hide()

        

        self.advancedButton.clicked.connect(self.toggleAdvancedDock)
        self.advancedButton.clicked.connect(self.advancedWindow.dataGrab)
        self.advancedWindow.destroyed.connect(
            lambda: self.updateWindowState('advancedWindow'))
        self.symmetryValue.valueChanged.connect(self.advancedWindow.dataGrab)
        self.shiftSelect.activated.connect(self.advancedWindow.dataGrab)

        root_h.addWidget(self.parameterArea)

        # ---- right panel ----
        self.plotArea = QtWidgets.QFrame()
        self.plotArea.setFrameShape(QtWidgets.QFrame.StyledPanel)
        right_v = QtWidgets.QVBoxLayout(self.plotArea)
        right_v.setContentsMargins(7, 0, -1, 0)

        self.tilingPlot = pg.PlotWidget(self.plotArea, viewBox=LockedViewBox())
        self.tilingPlot.setFixedSize(700, 700)
        self.tilingPlot.setBackground('w')
        self.tilingPlot.getPlotItem().hideAxis('bottom')
        self.tilingPlot.getPlotItem().hideAxis('left')
        self.tilingPlot.hideButtons()
        right_v.addWidget(self.tilingPlot)
        self.tilingPlot.setMouseEnabled(x=True, y=True)
        self.tilingPlot.getViewBox().setMouseMode(pg.ViewBox.PanMode)
        self.tilingPlot.getViewBox().menu = None
        self.tilingPlot.scene().contextMenuEvent = lambda e: None
        def filtered_mouse_press(event):
            if event.button() == QtCore.Qt.MiddleButton:
                return
            pg.ViewBox.mousePressEvent(self.tilingPlot.getViewBox(), event)
        self.tilingPlot.getViewBox().mousePressEvent = filtered_mouse_press
        self.tilingPlot.setViewport(QOpenGLWidget())

        for plot in (self.vectorPlot,):
            plot.setMouseEnabled(x=False, y=False)
            plot.getViewBox().menu = None
            plot.scene().contextMenuEvent = lambda e: None

        btn_h = QtWidgets.QHBoxLayout()
        btn_h.addItem(QtWidgets.QSpacerItem(170, 20, QtWidgets.QSizePolicy.Fixed,
                                            QtWidgets.QSizePolicy.Minimum))
        self.gridView = QtWidgets.QPushButton("Grid view")
        self.gridView.setCheckable(True)
        self.gridView.clicked.connect(self.gridViewButton)
        self.pointView = QtWidgets.QPushButton("Point view")
        self.pointView.setCheckable(True)
        self.pointView.clicked.connect(self.pointViewButton)
        self.editStyle = QtWidgets.QPushButton("Edit style...")
        self.editStyle.clicked.connect(self.editTilingStyle)
        self.saveAs = QtWidgets.QPushButton("Save as...")
        self.saveAs.clicked.connect(self.saveAsTiling)
        for btn in (self.gridView, self.pointView, self.editStyle, self.saveAs):
            btn_h.addWidget(btn)
        btn_h.addStretch()
        self.qualityLabel = QtWidgets.QLabel("")
        self.qualityLabel.setStyleSheet("color: #888; font-size: 8pt; padding-right: 4px;")
        btn_h.addWidget(self.qualityLabel)
        right_v.addLayout(btn_h)
        right_v.setStretch(0, 20)
        right_v.setStretch(1, 1)

        root_h.addWidget(self.plotArea)
        root_h.setStretch(0, 3)
        root_h.setStretch(1, 7)

        self._view_stack = QtWidgets.QStackedWidget()
        self._view_stack.addWidget(self.centralwidget)
        MainWindow.setCentralWidget(self._view_stack)

        

        self.menubar = QtWidgets.QMenuBar(MainWindow)
        self.menubar.setGeometry(QtCore.QRect(0, 0, 1050, 21))
        self.menuFile = QtWidgets.QMenu("File", self.menubar)
        self.menuTools = QtWidgets.QMenu("Tools", self.menubar)
        MainWindow.setMenuBar(self.menubar)
        self.menubar.addAction(self.menuFile.menuAction())
        self.menubar.addAction(self.menuTools.menuAction())
        MainWindow.setWindowTitle("HyperTiler")
        MainWindow.setWindowIcon(make_app_icon())
        QtWidgets.QApplication.instance().setStyleSheet(APP_STYLESHEET)

        self.tileButton.clicked.connect(self.generateTiling)
        QtCore.QMetaObject.connectSlotsByName(MainWindow)

        self.fftAction = QtWidgets.QAction("Compute FFT", MainWindow)
        self.fftAction.triggered.connect(self.computeFFT)
        self.menuTools.addAction(self.fftAction)

        self.vertexAction = QtWidgets.QAction("Vertex types", MainWindow)
        self.vertexAction.triggered.connect(self.computeVertexTypes)
        self.menuTools.addAction(self.vertexAction)

        self.networkAction = QtWidgets.QAction("Network builder", MainWindow)
        self.networkAction.triggered.connect(self.computeNetworkBuilder)
        self.menuTools.addAction(self.networkAction)

        self.menuTools.addSeparator()
        self.subAction = QtWidgets.QAction("Substitution tiling…", MainWindow)
        self.subAction.triggered.connect(self.computeSubstitution)
        self.menuTools.addAction(self.subAction)

        self.saveParamsAction = QtWidgets.QAction("Save parameters...", MainWindow)
        self.saveParamsAction.setShortcut("Ctrl+S")
        self.saveParamsAction.triggered.connect(self.saveParameters)
        self.menuFile.addAction(self.saveParamsAction)

        self.loadParamsAction = QtWidgets.QAction("Load parameters...", MainWindow)
        self.loadParamsAction.setShortcut("Ctrl+O")
        self.loadParamsAction.triggered.connect(self.loadParameters)
        self.menuFile.addAction(self.loadParamsAction)

        self.menuFile.addSeparator()
        self.prefsAction = QtWidgets.QAction("Preferences...", MainWindow)
        self.prefsAction.triggered.connect(self.openPreferences)
        self.menuFile.addAction(self.prefsAction)

    # ------------------------------------------------------------------
    # dock helpers
    # ------------------------------------------------------------------

    def toggleAdvancedDock(self):
        if self.advancedDock.isVisible():
            self.advancedDock.hide()
            self._main_window.setFixedSize(self.original_size)
        else:
            self.advancedDock.show()
            w = self.original_size.width() + self.advancedDock.sizeHint().width()
            self._main_window.setFixedSize(w, self.original_size.height())

    def closeAdvancedDock(self, event):
        self._main_window.setFixedSize(self.original_size)

    def updateWindowState(self, name):
        self.windows_open[name] = False

    def _current_view_mode(self):
        if self.gridView.isChecked():
            return 'grid'
        return 'point' if self.pointView.isChecked() else 'tile'

    def _sync_highlight_visibility(self):
        vw = getattr(self, 'vertex_window', None)
        if vw is None or not vw.isVisible() or not vw.highlight_items:
            return
        visible = not self.gridView.isChecked()
        for item in vw.highlight_items.values():
            item.setVisible(visible)

    def gridViewButton(self, checked):
        if not self.plotted:
            self.gridView.setChecked(False)
            return
        if checked:
            self.pointView.blockSignals(True)
            self.pointView.setChecked(False)
            self.pointView.setText("Point view")
            self.pointView.blockSignals(False)
            self.tileItem.hide()
            self.vertItem.hide()
            if self.edgeItem is not None:
                self.edgeItem.hide()
            self.gridItem.show()
        else:
            self.gridItem.hide()
            self.tileItem.show()
        self._sync_highlight_visibility()
        if hasattr(self, 'style_dialog') and self.style_dialog is not None and \
                self.style_dialog.isVisible():
            mode = self._current_view_mode()
            self.style_dialog.refresh(mode)
            self.style_dialog.adjustSize()

    def computeVertexTypes(self):
        if self._in_sub_mode:
            if hasattr(self, 'substitution_window'):
                self.substitution_window._show_vertices()
            return
        elif not self.plotted:
            return
        if hasattr(self, 'vertex_window') and self.vertex_window is not None:
            self.vertex_window.close()
        self.vertex_window = VertexFinderWindow(self)
        self.vertex_window.show()

    def computeNetworkBuilder(self):
        if self._in_sub_mode:
            if not self._populate_from_substitution():
                return
            sub_vw = getattr(
                getattr(self, 'substitution_window', None), '_vertex_window', None)
            if sub_vw is not None and getattr(sub_vw, '_canon_to_indices', None):
                from types import SimpleNamespace
                type_map = {c: list(idxs)
                            for c, idxs in sub_vw._canon_to_indices.items()}
                idx_to_vert = {i: sub_vw._all_verts[i]
                               for idxs in sub_vw._canon_to_indices.values()
                               for i in idxs}
                self.vertex_window = SimpleNamespace(
                    type_map=type_map, idx_to_vert=idx_to_vert,
                    isVisible=lambda: True)
            else:
                # vertex types not yet computed — show loading window immediately,
                # run vertex worker silently; _refresh_network_builder populates when done
                sub_win = getattr(self, 'substitution_window', None)
                if sub_win is not None:
                    if hasattr(self, 'network_window') and self.network_window is not None:
                        self.network_window.close()
                    self.network_window = NetworkBuilderWindow(self, skip_worker=True)
                    sub_win._show_vertices(silent=True)
                return
        elif not self.plotted:
            return
        if hasattr(self, 'network_window') and self.network_window is not None:
            self.network_window.close()
        self.network_window = NetworkBuilderWindow(self)

    def computeSubstitution(self):
        if self._in_sub_mode:
            sub_vw = getattr(
                getattr(self, 'substitution_window', None), '_vertex_window', None)
            if sub_vw is not None:
                sub_vw.close()
            # clear any SimpleNamespace proxy left by sub-mode network builder
            if not isinstance(getattr(self, 'vertex_window', None), VertexFinderWindow):
                self.vertex_window = None
            if hasattr(self, 'network_window') and self.network_window is not None:
                self.network_window.close()
                self.network_window = None
            self._view_stack.setCurrentIndex(0)
            self._in_sub_mode = False
            self.subAction.setText("Substitution tiling…")
            self._main_window.setWindowTitle("HyperTiler")
            if getattr(self, '_adv_was_visible', False):
                self.advancedDock.show()
                w = self.original_size.width() + self.advancedDock.sizeHint().width()
                self._main_window.setFixedSize(w, self.original_size.height())
            else:
                self._main_window.setFixedSize(self.original_size)
        else:
            if self._view_stack.count() < 2:
                self.substitution_window = SubstitutionWindow(self)
                self._view_stack.addWidget(self.substitution_window)
            self._adv_was_visible = self.advancedDock.isVisible()
            if self._adv_was_visible:
                self.advancedDock.hide()
            self._main_window.setMinimumSize(self.original_size)
            self._main_window.setMaximumSize(QtCore.QSize(16777215, 16777215))
            self._view_stack.setCurrentIndex(1)
            self._in_sub_mode = True
            self.subAction.setText("Grid tiling…")
            self._main_window.setWindowTitle("HyperTiler — Substitution mode")

    # ------------------------------------------------------------------
    # substitution ↔ tool bridge
    # ------------------------------------------------------------------

    def _active_plot_widget(self):
        if self._in_sub_mode and hasattr(self, 'substitution_window'):
            return self.substitution_window._plot
        return self.tilingPlot

    def _populate_from_substitution(self):
        sub = self.substitution_window
        final_tiles = sub._final_tiles
        if not final_tiles:
            return False

        type_order, seen = [], set()
        for tile_type, _ in final_tiles:
            base = tile_type.rsplit('_', 1)[0] if '_' in tile_type else tile_type
            if base not in seen:
                seen.add(base)
                type_order.append(base)
        type_to_idx = {t: i for i, t in enumerate(type_order)}

        poly_areas = []
        for tile_type, _ in final_tiles:
            base = tile_type.rsplit('_', 1)[0] if '_' in tile_type else tile_type
            poly_areas.append(type_to_idx.get(base, 0))

        colors = sub._current_colors()
        current_colors = []
        for t in type_order:
            qc = QtGui.QColor(colors.get(t, '#aaaaaa'))
            current_colors.append((qc.red(), qc.green(), qc.blue()))

        adapter = _SubstitutionAdapter(final_tiles)
        adapter.poly_areas = poly_areas

        self.tiling = adapter
        self.poly_areas = poly_areas
        self.ngon_areas = []
        self.current_colors = current_colors
        self.poly_unq = list(range(len(type_order)))
        self.ngon_unq = []
        self.vertices = np.vstack([c for _, c in final_tiles])
        self.plotted = True
        return True

    # ------------------------------------------------------------------
    # vector helpers
    # ------------------------------------------------------------------

    def _vectorSetup(self, fold, shift_type):
        theta = 2 * np.pi / fold
        angles = [round(np.degrees(theta * i), 2) for i in range(fold)]
        shifts = self._makeShifts(fold, shift_type)
        return np.array([(1.0, 1.0, a, s) for a, s in zip(angles, shifts)])

    @staticmethod
    def _makeShifts(fold, shift_type):
        if shift_type == 0:
            return ([1 / (fold / 2), -1 / (fold / 2)] * (fold // 2)
                    if fold % 2 == 0 else [1 / fold] * fold)
        if shift_type == 1:
            return [0.0] * fold
        if shift_type == 2:
            return list(np.round(np.random.uniform(-1, 1, fold), 3))
        r = np.random.rand(fold)
        r /= r.sum()
        return list(np.round(r, 3))

    def _refreshVectorPlot(self):
        self.vectorPlot.clear()
        self.vectorPlot.addItem(vectorPlotting(self.vector_data))
        self.vectorPlot.enableAutoRange()

    def updateShift(self):
        self.vector_data[:, 3] = self._makeShifts(
            len(self.vector_data), self.shiftSelect.currentIndex())

    def updateVector(self):
        self.vector_data = self._vectorSetup(
            self.symmetryValue.value(), self.shiftSelect.currentIndex())
        self._refreshVectorPlot()
        if not hasattr(self, 'advancedWindow'):
            return
        self.advancedWindow.gridVectorPlot.clear()
        self.advancedWindow.gridVectorPlot.addItem(
            vectorPlotting(self.vector_data, 'grid'))
        self.advancedWindow.gridVectorPlot.enableAutoRange()

    def editVector(self, data):
        self.vector_data = data
        self._refreshVectorPlot()
        self.advancedWindow.gridVectorPlot.clear()
        self.advancedWindow.gridVectorPlot.addItem(vectorPlotting(data, 'grid'))
        self.advancedWindow.gridVectorPlot.enableAutoRange()

    # ------------------------------------------------------------------
    # colour helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _makeColors(n):
        if _PREFS.get('color_scheme') == 'tonal':
            return _make_tonal_colors(n, _PREFS.get('tonal_base_color', '#4a6fa5'))
        h = np.random.rand()
        colors = []
        for _ in range(n):
            h = (h + 0.618) % 1.0
            r, g, b = colorsys.hsv_to_rgb(h, 0.4, 0.8)
            colors.append((r * 255, g * 255, b * 255))
        return colors

    def _classifyAreas(self, areas):
        rounded = np.round(areas, 3)
        unq = np.unique(rounded)
        out = np.zeros(len(areas), dtype=int)
        for i, u in enumerate(unq):
            out[rounded == u] = i
        return out, unq

    def _tiling_hash(self):
        return (tuple(self.vector_data.flatten()),
                self.sizeValue.value(),
                self.shiftSelect.currentIndex())

    # ------------------------------------------------------------------
    # main actions
    # ------------------------------------------------------------------

    def generateTiling(self):
        if self.shiftSelect.currentIndex() not in (2, 3):
            current_hash = self._tiling_hash()
            if hasattr(self, '_last_tiling_hash') and current_hash == self._last_tiling_hash:
                return

        if self.shiftSelect.currentIndex() in (2, 3):
            self.updateShift()
            self.advancedWindow.dataGrab()

        self._last_tiling_hash = self._tiling_hash()

        if hasattr(self, 'vertex_window') and self.vertex_window is not None \
                and self.vertex_window.isVisible():
            self.vertex_window.highlight_items.clear()
            self.vertex_window._show_loading()
            QtWidgets.QApplication.processEvents()

        est = _estimate_tile_count(len(self.vector_data), self.sizeValue.value())
        quality = _quality_for_count(est)
        _apply_quality(self.tilingPlot, quality)

        self.tilingPlot.clear()
        self.tileItem = None
        self.vertItem = None
        self.edgeItem = None
        self.gridItem = None

        self.tiling = TileMaker(self.vector_data, self.sizeValue.value())
        self.vertices = (np.vstack(self.tiling.points) if len(self.tiling.points) > 0
                         else np.vstack(self.tiling.p_points))

        max_coord = np.max(np.abs(self.vertices)) * 1.1
        self.tilingPlot.enableAutoRange(False)
        self.tilingPlot.setLimits(
            xMin=-max_coord, xMax=max_coord,
            yMin=-max_coord, yMax=max_coord)
        self.tilingPlot.setRange(
            xRange=(-max_coord * 0.5, max_coord * 0.5),
            yRange=(-max_coord * 0.5, max_coord * 0.5))

        poly_idx, self.poly_unq = self._classifyAreas(self.tiling.poly_areas)
        ngon_idx, self.ngon_unq = (self._classifyAreas(self.tiling.ngon_areas)
                                   if self.tiling.ngon_areas else
                                   (np.array([], dtype=int), []))
        ngon_idx = ngon_idx + len(self.poly_unq)
        self.poly_areas = poly_idx
        self.ngon_areas = ngon_idx

        n_types = len(self.poly_unq) + len(self.ngon_unq)
        if hasattr(self, '_pending_colors') and len(self._pending_colors) == n_types:
            self.current_colors = self._pending_colors
            del self._pending_colors
        elif (hasattr(self, 'style_dialog') and self.style_dialog is not None
              and self.shiftSelect.currentIndex() in (2, 3)
              and len(self.current_colors) == n_types):
            pass  # keep self.current_colors as-is
        else:
            self.current_colors = self._makeColors(n_types)

        self._redraw_tiles()
        self.vertItem = pointPlot(self.vertices, color=self.point_color)
        self.tilingPlot.addItem(self.vertItem)

        self.plotted = True

        _qlabels = {
            'high': '',
            'medium': 'Quality: Medium (4× MSAA)',
            'low': 'Quality: Low (AA off)',
        }
        self.qualityLabel.setText(_qlabels[quality] if _PREFS['contextual_rendering'] else '')

        n_polys = len(self.poly_areas)
        for i, d in enumerate(self.tiling.intersection_data):
            if i < n_polys:
                d['type_idx'] = int(self.poly_areas[i])
            else:
                j = i - n_polys
                if j < len(self.ngon_areas):
                    d['type_idx'] = int(self.ngon_areas[j])

        self.gridItem = gridPlot(self.tiling.grid, self.grid_color, self.grid_width)
        self.tilingPlot.addItem(self.gridItem)
        self.gridItem.setZValue(self.tileItem.zValue() - 1)

        if self.gridView.isChecked():
            self.tileItem.hide()
            self.vertItem.hide()
        elif self.pointView.isChecked():
            self.tileItem.hide()
            self.vertItem.show()
            self.gridItem.hide()
        else:
            self.vertItem.hide()
            self.gridItem.hide()

        if hasattr(self, 'style_dialog') and self.style_dialog is not None and \
                self.style_dialog.isVisible():
            if hasattr(self.style_dialog, '_intersect_scatter'):
                self.style_dialog._intersect_scatter = None
            mode = self._current_view_mode()
            self.style_dialog.refresh(mode)

        if self.pointView.isChecked() and self.edge_was_checked:
            if hasattr(self, 'style_dialog') and self.style_dialog is not None and \
                    self.style_dialog.isVisible():
                self.style_dialog._edge_color = self.edge_color
                self.style_dialog._set_btn_color(self.edge_color)
                self.style_dialog.width_spin.setValue(self.edge_width)
                self.style_dialog.edge_check.setChecked(True)
            else:
                self.edgeItem = edgePlot(self.tiling, self.edge_color, self.edge_width)
                self.tilingPlot.addItem(self.edgeItem)
                self.edgeItem.setZValue(self.vertItem.zValue() - 1)

        if hasattr(self, 'vertex_window') and self.vertex_window is not None \
                and self.vertex_window.isVisible():
            self.vertex_window._find_and_display()

        if hasattr(self, 'network_window') and self.network_window is not None \
                and self.network_window.isVisible():
            self.network_window.refresh()

    def _redraw_tiles(self):
        poly_color = [self.current_colors[i] for i in self.poly_areas]
        ngon_color = [self.current_colors[i] for i in self.ngon_areas]

        hide_tiles = self.pointView.isChecked() or self.gridView.isChecked()

        if self.tileItem is not None:
            self.tilingPlot.removeItem(self.tileItem)

        self.tileItem = tilePlot(self.tiling, poly_color, ngon_color,
                                  self.edge_color, self.edge_width)
        self.tilingPlot.addItem(self.tileItem)

        if hide_tiles:
            self.tileItem.hide()

    def editTilingStyle(self):
        if not self.plotted:
            return
        if hasattr(self, 'style_dialog') and self.style_dialog is not None and \
                self.style_dialog.isVisible():
            self.style_dialog.raise_()
            self.style_dialog.activateWindow()
            return
        mode = self._current_view_mode()
        self.style_dialog = StyleDialog(self, mode)
        self.style_dialog.setMinimumWidth(380)
        self.style_dialog.setParent(self._main_window, QtCore.Qt.Window)
        top_right = self.tilingPlot.mapToGlobal(
            QtCore.QPoint(self.tilingPlot.width() + 10, 0))
        self.style_dialog.move(top_right)
        self.style_dialog.show()

    def pointViewButton(self, checked):
        if not self.plotted:
            self.pointView.setChecked(False)
            return
        if checked:
            self.gridView.blockSignals(True)
            self.gridView.setChecked(False)
            self.gridView.blockSignals(False)
            self.gridItem.hide()
            self.pointView.setText("Tile view")
            self.tileItem.hide()
            self.vertItem.show()
            if self.edgeItem is not None:
                self.edgeItem.show()
        else:
            self.pointView.setText("Point view")
            self.tileItem.show()
            self.vertItem.hide()
            if self.edgeItem is not None:
                self.edgeItem.hide()
        self._sync_highlight_visibility()
        if hasattr(self, 'style_dialog') and self.style_dialog is not None and \
                self.style_dialog.isVisible():
            mode = self._current_view_mode()
            self.style_dialog.refresh(mode)
            self.style_dialog.adjustSize()

    def openPreferences(self):
        dlg = PreferencesDialog(self._main_window)
        dlg.exec_()

    def saveAsTiling(self):
        if not self.plotted:
            return
        path, selected_filter = QtWidgets.QFileDialog.getSaveFileName(
            None, "Save Tiling", "", "PNG Image (*.png);;SVG Image (*.svg)")
        if not path:
            return
        if selected_filter.endswith('(*.svg)') or path.lower().endswith('.svg'):
            if not path.endswith('.svg'):
                path += '.svg'
            poly_color = [self.current_colors[i] for i in self.poly_areas]
            ngon_color = [self.current_colors[i] for i in self.ngon_areas]
            polys = list(self.tiling.p_points) + list(self.tiling.points)
            colors = list(ngon_color) + list(poly_color)
            # edge_width is a cosmetic (screen-pixel) pen width on screen, but
            # SVG stroke-width lives in the same data-unit space as the tile
            # geometry - convert via the view's current data-units-per-pixel
            # so the exported line matches what's on screen, not a raw pixel
            # count read straight into a differently-scaled coordinate space.
            px_w, _ = self.tilingPlot.getViewBox().viewPixelSize()
            write_svg(path, polys, colors, self.edge_color, self.edge_width * px_w)
            return
        if not path.endswith('.png'):
            path += '.png'
        exporter = ImageExporter(self.tilingPlot.plotItem)
        exporter.parameters()['width'] = 1000
        exporter.export(path)

    def computeFFT(self):
        if self._in_sub_mode:
            if not self._populate_from_substitution():
                return
        elif not self.plotted:
            return

        coords = self.vertices
        xmin, xmax = coords[:, 0].min(), coords[:, 0].max()
        ymin, ymax = coords[:, 1].min(), coords[:, 1].max()
        spread = max(xmax - xmin, ymax - ymin)

        grid_size = int(np.clip(spread * 20, 512, 4096))
        grid = np.zeros((grid_size, grid_size))
        xi = ((coords[:, 0] - xmin) / (xmax - xmin) * (grid_size - 1)).astype(int)
        yi = ((coords[:, 1] - ymin) / (ymax - ymin) * (grid_size - 1)).astype(int)
        np.add.at(grid, (yi, xi), 1.0)

        from scipy.ndimage import gaussian_filter
        sigma = max(1.0, grid_size / 512)
        grid = gaussian_filter(grid, sigma=sigma)

        fft = np.fft.fft2(grid)
        fft_shift = np.fft.fftshift(fft)
        magnitude = np.log1p(np.abs(fft_shift))

        self.fft_window = QtWidgets.QMainWindow(self._main_window)
        self.fft_window.setWindowTitle("FFT")

        plot = pg.PlotWidget(viewBox=LockedViewBox())
        plot.setBackground('k')
        plot.getPlotItem().hideAxis('bottom')
        plot.getPlotItem().hideAxis('left')
        plot.hideButtons()
        plot.setMouseEnabled(x=True, y=True)
        plot.getViewBox().setAspectLocked(True)
        plot.getViewBox().menu = None
        plot.scene().contextMenuEvent = lambda e: None

        img = pg.ImageItem()
        mag_norm = (magnitude - magnitude.min()) / (magnitude.max() - magnitude.min())
        img.setImage(mag_norm.T)
        cmap = pg.colormap.get('inferno')
        img.setColorMap(cmap)

        plot.addItem(img)
        self.fft_window.setCentralWidget(plot)
        self.fft_window.setFixedSize(600, 600)
        ref = self._active_plot_widget()
        center_on_screen(self.fft_window, ref)
        self.fft_window.show()

    # ------------------------------------------------------------------
    # parameter save / load
    # ------------------------------------------------------------------

    def saveParameters(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            None, "Save Parameters", "",
            "HyperTiler Parameters (*.htile);;JSON (*.json)")
        if not path:
            return
        if not (path.endswith('.htile') or path.endswith('.json')):
            path += '.htile'
        data = {
            "vector_data": self.vector_data.tolist(),
            "n_grids": self.sizeValue.value(),
            "shift_type": self.shiftSelect.currentIndex(),
        }
        if self.plotted and hasattr(self, 'current_colors'):
            data["colors"] = [list(c) for c in self.current_colors]
        with open(path, 'w') as f:
            json.dump(data, f, indent=2)

    def loadParameters(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            None, "Load Parameters", "",
            "HyperTiler Parameters (*.htile *.json);;All files (*)")
        if not path:
            return
        try:
            with open(path, 'r') as f:
                data = json.load(f)
            vd = np.array(data["vector_data"], dtype=float)
            if vd.ndim != 2 or vd.shape[1] != 4:
                raise ValueError("vector_data must be an Nx4 array")
            self.vector_data = vd
            self.symmetryValue.blockSignals(True)
            self.symmetryValue.setValue(len(vd))
            self.symmetryValue.blockSignals(False)
            if "n_grids" in data:
                self.sizeValue.setValue(int(data["n_grids"]))
            if "shift_type" in data:
                self.shiftSelect.setCurrentIndex(int(data["shift_type"]))
            if "colors" in data:
                self._pending_colors = [tuple(int(v) for v in c) for c in data["colors"]]
            self._refreshVectorPlot()
            self.advancedWindow.dataGrab()
            self.advancedWindow.gridVectorPlot.clear()
            self.advancedWindow.gridVectorPlot.addItem(
                vectorPlotting(self.vector_data, 'grid'))
            self.advancedWindow.gridVectorPlot.enableAutoRange()
        except Exception as e:
            QtWidgets.QMessageBox.warning(
                None, "Load failed", f"Could not load parameters:\n{e}")
