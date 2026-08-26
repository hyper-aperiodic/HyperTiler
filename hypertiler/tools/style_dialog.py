from PyQt5 import QtCore, QtGui, QtWidgets
import pyqtgraph as pg
import numpy as np
from ..graphics import edgePlot, pointPlot, gridPlot
from ..widgets import TileSwatchButton

##the default colourings of tiles, points etc. is based off colour theory, 
##where harmonious but distinct colours can be picked using colours on a wheel
##separated by golden-mean related angles. This set of classes allows customisation
##across the board, because sometimes colour theory looks aesthetically...bad.

class StyleDialog(QtWidgets.QDialog):
    def __init__(self, parent_ui, mode):
        super().__init__()
        self.ui = parent_ui
        self.mode = mode
        self.setWindowTitle("Edit style")
        self.setModal(False)

        self.root_layout = QtWidgets.QVBoxLayout(self)

        self.close_btn = QtWidgets.QPushButton("Close")
        self.close_btn.clicked.connect(self.close)

        self._build(mode)

    def _build(self, mode):
        if hasattr(self, '_intersect_scatter') and self._intersect_scatter is not None:
            try:
                self.ui.tilingPlot.removeItem(self._intersect_scatter)
            except Exception:
                pass
            self._intersect_scatter = None

        while self.root_layout.count():
            item = self.root_layout.takeAt(0)
            if item.widget() and item.widget() is not self.close_btn:
                item.widget().deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())

        if mode == 'tile':
            self._setup_tile(self.root_layout)
        elif mode == 'grid':
            self._setup_grid(self.root_layout)
        else:
            self._setup_point(self.root_layout)

        self.root_layout.addWidget(self.close_btn)

    def closeEvent(self, event):
        if hasattr(self, '_intersect_scatter') and self._intersect_scatter is not None:
            try:
                self.ui.tilingPlot.removeItem(self._intersect_scatter)
            except Exception:
                pass
            self._intersect_scatter = None
        super().closeEvent(event)

    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())

    def refresh(self, mode):
        self.mode = mode
        self._build(mode)


    def _setup_tile(self, root):
        self._tile_edge_color = self.ui.edge_color

        edge_h = QtWidgets.QHBoxLayout()
        edge_h.addWidget(QtWidgets.QLabel("Tile edge colour:"))
        self.tile_edge_color_btn = QtWidgets.QPushButton()
        self.tile_edge_color_btn.setFixedSize(40, 24)
        self._set_tile_edge_btn_color(self._tile_edge_color)
        self.tile_edge_color_btn.clicked.connect(self._pick_tile_edge_color)
        edge_h.addWidget(self.tile_edge_color_btn)
        edge_h.addStretch()
        root.addLayout(edge_h)

        width_h = QtWidgets.QHBoxLayout()
        width_h.addWidget(QtWidgets.QLabel("Tile edge width:"))
        self.tile_width_spin = QtWidgets.QDoubleSpinBox()
        self.tile_width_spin.setRange(0.1, 5.0)
        self.tile_width_spin.setSingleStep(0.1)
        self.tile_width_spin.setValue(self.ui.edge_width)
        self.tile_width_spin.valueChanged.connect(self._update_tile_edges)
        width_h.addWidget(self.tile_width_spin)
        width_h.addStretch()
        root.addLayout(width_h)
        root.addStretch()

        top_h = QtWidgets.QHBoxLayout()
        top_h.addWidget(QtWidgets.QLabel("Click a tile type to change its colour."))
        top_h.addStretch()
        reset_btn = QtWidgets.QPushButton("Reset colours")
        reset_btn.clicked.connect(self._reset_colors)
        top_h.addWidget(reset_btn)
        root.addLayout(top_h)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFixedHeight(300)
        container = QtWidgets.QWidget()
        self.swatch_layout = QtWidgets.QGridLayout(container)
        self.swatch_layout.setSpacing(8)
        scroll.setWidget(container)
        root.addWidget(scroll)

        self._build_swatches()

    def _reset_colors(self):
        ui = self.ui
        ui.current_colors = ui._makeColors(len(ui.poly_unq) + len(ui.ngon_unq))
        ui._redraw_tiles()
        self._build_swatches()

    def _set_tile_edge_btn_color(self, color):
        r, g, b = color
        self.tile_edge_color_btn.setStyleSheet(
            f"background-color: rgb({r},{g},{b}); border: 1px solid #888;")

    def _pick_tile_edge_color(self):
        initial = QtGui.QColor(*self._tile_edge_color)
        dialog = self._open_color_dialog(initial, self)
        dialog.currentColorChanged.connect(self._on_tile_edge_color_changed)
        dialog.colorSelected.connect(self._on_tile_edge_color_changed)
        dialog.exec_()

    def _on_tile_edge_color_changed(self, color):
        if not color.isValid():
            return
        self._tile_edge_color = (color.red(), color.green(), color.blue())
        self._set_tile_edge_btn_color(self._tile_edge_color)
        self._update_tile_edges()

    def _update_tile_edges(self):
        ui = self.ui
        ui.edge_color = self._tile_edge_color
        ui.edge_width = self.tile_width_spin.value()
        ui._redraw_tiles()

    def _build_swatches(self):
        while self.swatch_layout.count():
            item = self.swatch_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        ui = self.ui
        n_types = len(ui.poly_unq) + len(ui.ngon_unq)
        cols = 4

        for idx in range(n_types):
            if idx < len(ui.poly_unq):
                tiles = [ui.tiling.points[i]
                         for i, a in enumerate(ui.poly_areas) if a == idx]
            else:
                ngon_idx = idx - len(ui.poly_unq) + len(ui.poly_unq)
                tiles = [ui.tiling.p_points[i]
                         for i, a in enumerate(ui.ngon_areas) if a == ngon_idx]

            color = ui.current_colors[idx]
            btn = TileSwatchButton(idx, tiles[0] if tiles else None, color)
            btn.clicked_with_idx.connect(self._on_swatch_clicked)
            row, col = divmod(idx, cols)
            self.swatch_layout.addWidget(btn, row, col)

    def _on_swatch_clicked(self, idx):
        current = self.ui.current_colors[idx]
        initial = QtGui.QColor(*[int(c) for c in current])
        dialog = self._open_color_dialog(initial, self)
        dialog.currentColorChanged.connect(
            lambda c, i=idx: self._apply_color(i, c))
        dialog.colorSelected.connect(
            lambda c, i=idx: self._apply_color(i, c))
        dialog.exec_()

    def _apply_color(self, idx, qcolor):
        if not qcolor.isValid():
            return
        self.ui.current_colors[idx] = (qcolor.red(), qcolor.green(), qcolor.blue())
        self.ui._redraw_tiles()
        self._build_swatches()

    @staticmethod
    def _open_color_dialog(initial, parent):
        dialog = QtWidgets.QColorDialog(initial, parent)
        dialog.setOption(QtWidgets.QColorDialog.DontUseNativeDialog, True)
        dialog.setOption(QtWidgets.QColorDialog.NoButtons, False)
        for w in dialog.findChildren(QtWidgets.QLabel):
            if 'ustom' in w.text():
                w.hide()
        for w in dialog.findChildren(QtWidgets.QPushButton):
            if 'ustom' in w.text():
                w.hide()
        wells = [w for w in dialog.findChildren(QtWidgets.QWidget)
                 if w.metaObject().className() == 'QWellArray']
        if len(wells) >= 2:
            wells[-1].hide()
        return dialog


    def _setup_edge_controls(self, root):
        """Tile-edge overlay controls (show/hide, colour, thickness) - shared
        between point view and grid view, since both hide the filled tiles
        and can use this as the only way to see tile boundaries."""
        self._edge_color = self.ui.edge_color
        self.edge_check = QtWidgets.QCheckBox("Show tile edges")
        self.edge_check.setChecked(False)
        self.edge_check.toggled.connect(self._toggle_edges)
        root.addWidget(self.edge_check)

        color_h = QtWidgets.QHBoxLayout()
        color_h.addWidget(QtWidgets.QLabel("Edge colour:"))
        self.color_btn = QtWidgets.QPushButton()
        self.color_btn.setFixedSize(40, 24)
        self._set_btn_color(self._edge_color)
        self.color_btn.clicked.connect(self._pick_edge_color)
        color_h.addWidget(self.color_btn)
        color_h.addStretch()
        root.addWidget(QtWidgets.QWidget())
        root.addLayout(color_h)

        width_h = QtWidgets.QHBoxLayout()
        width_h.addWidget(QtWidgets.QLabel("Edge width:"))
        self.width_spin = QtWidgets.QDoubleSpinBox()
        self.width_spin.setRange(0.1, 5.0)
        self.width_spin.setSingleStep(0.1)
        self.width_spin.setValue(1.0)
        self.width_spin.valueChanged.connect(self._update_edges)
        width_h.addWidget(self.width_spin)
        width_h.addStretch()
        root.addLayout(width_h)
        root.addStretch()

        self.width_spin.setValue(self.ui.edge_width)
        self.edge_check.setChecked(self.ui.edge_was_checked)

    def _setup_point(self, root):
        self._point_color = self.ui.point_color
        self._setup_edge_controls(root)

        point_h = QtWidgets.QHBoxLayout()
        point_h.addWidget(QtWidgets.QLabel("Point colour:"))
        self.point_color_btn = QtWidgets.QPushButton()
        self.point_color_btn.setFixedSize(40, 24)
        self._set_point_btn_color(self._point_color)
        self.point_color_btn.clicked.connect(self._pick_point_color)
        point_h.addWidget(self.point_color_btn)
        point_h.addStretch()
        root.addLayout(point_h)

        size_h = QtWidgets.QHBoxLayout()
        size_h.addWidget(QtWidgets.QLabel("Point size:"))
        self.point_size_spin = QtWidgets.QDoubleSpinBox()
        self.point_size_spin.setRange(0.01, 1.0)
        self.point_size_spin.setSingleStep(0.01)
        self.point_size_spin.setValue(0.2)
        self.point_size_spin.valueChanged.connect(self._update_points)
        size_h.addWidget(self.point_size_spin)
        size_h.addStretch()
        root.addLayout(size_h)
        root.addStretch()

    def _set_point_btn_color(self, color):
        r, g, b = color
        self.point_color_btn.setStyleSheet(
            f"background-color: rgb({r},{g},{b}); border: 1px solid #888;")

    def _pick_point_color(self):
        initial = QtGui.QColor(*self._point_color)
        dialog = self._open_color_dialog(initial, self)
        dialog.currentColorChanged.connect(self._on_point_color_changed)
        dialog.colorSelected.connect(self._on_point_color_changed)
        dialog.exec_()

    def _on_point_color_changed(self, color):
        if not color.isValid():
            return
        self._point_color = (color.red(), color.green(), color.blue())
        self.ui.point_color = self._point_color
        self._set_point_btn_color(self._point_color)
        self._update_points()

    def _update_points(self):
        ui = self.ui
        ui.point_radius = self.point_size_spin.value()
        ui.tilingPlot.removeItem(ui.vertItem)
        ui.vertItem = pointPlot(ui.vertices,
                                radius=ui.point_radius,
                                color=self._point_color)
        ui.tilingPlot.addItem(ui.vertItem)


    def _setup_grid(self, root):
        self._intersect_scatter = None
        self._grid_color = self.ui.grid_color

        color_h = QtWidgets.QHBoxLayout()
        color_h.addWidget(QtWidgets.QLabel("Grid line colour:"))
        self.grid_color_btn = QtWidgets.QPushButton()
        self.grid_color_btn.setFixedSize(40, 24)
        self._set_grid_btn_color(self._grid_color)
        self.grid_color_btn.clicked.connect(self._pick_grid_color)
        color_h.addWidget(self.grid_color_btn)
        color_h.addStretch()
        root.addLayout(color_h)

        width_h = QtWidgets.QHBoxLayout()
        width_h.addWidget(QtWidgets.QLabel("Grid line thickness:"))
        self.grid_width_spin = QtWidgets.QDoubleSpinBox()
        self.grid_width_spin.setRange(0.1, 5.0)
        self.grid_width_spin.setSingleStep(0.1)
        self.grid_width_spin.setValue(self.ui.grid_width)
        self.grid_width_spin.valueChanged.connect(self._update_grid)
        width_h.addWidget(self.grid_width_spin)
        width_h.addStretch()
        root.addLayout(width_h)
        root.addStretch()

        root.addWidget(QtWidgets.QLabel(
            "Toggle intersection points and click one for details."))
        self.intersect_check = QtWidgets.QCheckBox("Show intersection points")
        self.intersect_check.toggled.connect(self._toggle_intersections)
        root.addWidget(self.intersect_check)

        info_h = QtWidgets.QHBoxLayout()
        self.tile_preview = QtWidgets.QLabel()
        self.tile_preview.setFixedSize(120, 120)
        self.tile_preview.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self.tile_preview.setAlignment(QtCore.Qt.AlignCenter)
        self.tile_preview.setText("—")
        info_h.addWidget(self.tile_preview)

        self.intersect_info = QtWidgets.QLabel("Click an intersection point.")
        self.intersect_info.setWordWrap(True)
        self.intersect_info.setTextFormat(QtCore.Qt.RichText)
        self.intersect_info.setAlignment(QtCore.Qt.AlignTop | QtCore.Qt.AlignLeft)
        info_h.addWidget(self.intersect_info, 1)
        root.addLayout(info_h)
        root.addStretch()

    def _toggle_intersections(self, checked):
        ui = self.ui
        if checked:
            idata = ui.tiling.intersection_data
            if not idata:
                return
            spots = [{'pos': (d['x'], d['y']), 'data': i}
                     for i, d in enumerate(idata)]
            self._intersect_scatter = pg.ScatterPlotItem(
                spots=spots, size=8,
                pen=pg.mkPen((0, 100, 255), width=1),
                brush=pg.mkBrush(0, 100, 255, 140),
                hoverable=True,
                hoverPen=pg.mkPen((255, 140, 0), width=2),
                hoverBrush=pg.mkBrush(255, 140, 0, 220),
                pxMode=True)
            self._intersect_scatter.sigHovered.connect(self._on_intersect_hovered)
            ui.tilingPlot.addItem(self._intersect_scatter)
            self._intersect_scatter.setZValue(20)
        else:
            if self._intersect_scatter is not None:
                ui.tilingPlot.removeItem(self._intersect_scatter)
                self._intersect_scatter = None

    def _render_tile_preview(self, verts, color):
        SIZE = 120
        pixmap = QtGui.QPixmap(SIZE, SIZE)
        pixmap.fill(QtCore.Qt.white)
        verts = np.array(verts)
        pad = 14
        w, h = SIZE - 2 * pad, SIZE - 2 * pad
        vmin, vmax = verts.min(axis=0), verts.max(axis=0)
        span = vmax - vmin
        span[span == 0] = 1
        scale = min(w / span[0], h / span[1])
        cx, cy = SIZE / 2, SIZE / 2
        pts = [QtCore.QPointF(
            (x - (vmin[0] + vmax[0]) / 2) * scale + cx,
            (y - (vmin[1] + vmax[1]) / 2) * scale + cy)
            for x, y in verts]
        painter = QtGui.QPainter(pixmap)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        r, g, b = [int(c) for c in color]
        painter.setBrush(QtGui.QBrush(QtGui.QColor(r, g, b)))
        painter.setPen(QtGui.QPen(QtCore.Qt.black, 1.5))
        painter.drawPolygon(pts)
        painter.end()
        self.tile_preview.setPixmap(pixmap)
        self.tile_preview.setText("")

    def _on_intersect_hovered(self, *args):
        points = args[1]
        if points.size == 0:
            return
        idx = points[0].data()
        idata = self.ui.tiling.intersection_data
        if idx is None or idx >= len(idata):
            return
        d = idata[idx]
        ui = self.ui
        type_idx = d.get('type_idx', -1)
        n_polys = len(ui.tiling.points)
        is_ngon = idx >= n_polys

        color = (ui.current_colors[type_idx]
                 if 0 <= type_idx < len(ui.current_colors)
                 else (200, 200, 200))
        if is_ngon:
            ngon_idx = idx - n_polys
            if ngon_idx < len(ui.tiling.p_points):
                self._render_tile_preview(ui.tiling.p_points[ngon_idx], color)
        elif idx < len(ui.tiling.points):
            self._render_tile_preview(ui.tiling.points[idx], color)

        n_poly_types = len(ui.poly_unq)
        if 0 <= type_idx < n_poly_types:
            area = float(ui.poly_unq[type_idx])
        elif n_poly_types <= type_idx < n_poly_types + len(ui.ngon_unq):
            area = float(ui.ngon_unq[type_idx - n_poly_types])
        else:
            area = None

        if area is not None:
            r, g, b = [int(c) for c in ui.current_colors[type_idx]]
            swatch = (f"<span style='background-color:rgb({r},{g},{b});"
                      f"border:1px solid #555;'>&nbsp;&nbsp;&nbsp;&nbsp;</span>")
            type_str = f"Type {type_idx + 1} (area≈{area:.3f}) {swatch}"
        else:
            type_str = "Unknown"

        grids_str = "multiple grids" if is_ngon else f"{d['g1']+1} ∩ {d['g2']+1}"

        vertex_indices = d.get('vertex_indices', [])
        idx_lines = "<br>".join(
            f"v{i+1}: [{', '.join(str(x) for x in vi)}]"
            for i, vi in enumerate(vertex_indices))

        self.intersect_info.setText(
            f"<b>Type:</b> {type_str}<br>"
            f"<b>Grids:</b> {grids_str}<br><br>"
            f"<b>Vertex indices:</b><br>{idx_lines}"
        )

    def _set_btn_color(self, color):
        r, g, b = color
        self.color_btn.setStyleSheet(
            f"background-color: rgb({r},{g},{b}); border: 1px solid #888;")

    def _pick_edge_color(self):
        initial = QtGui.QColor(*self._edge_color)
        dialog = self._open_color_dialog(initial, self)
        dialog.currentColorChanged.connect(self._on_edge_color_changed)
        dialog.colorSelected.connect(self._on_edge_color_changed)
        dialog.exec_()

    def _on_edge_color_changed(self, color):
        if not color.isValid():
            return
        self._edge_color = (color.red(), color.green(), color.blue())
        self.ui.edge_color = self._edge_color
        self._set_btn_color(self._edge_color)
        if self.edge_check.isChecked():
            self._update_edges()

    def _toggle_edges(self, checked):
        self.ui.edge_was_checked = checked
        if checked:
            self._update_edges()
        else:
            if self.ui.edgeItem is not None:
                self.ui.tilingPlot.removeItem(self.ui.edgeItem)
                self.ui.edgeItem = None

    def _update_edges(self):
        if not self.edge_check.isChecked():
            return
        self.ui.edge_color = self._edge_color
        self.ui.edge_width = self.width_spin.value()
        ui = self.ui
        if ui.edgeItem is not None:
            ui.tilingPlot.removeItem(ui.edgeItem)
        ui.edgeItem = edgePlot(ui.tiling, self._edge_color, self.width_spin.value())
        ui.tilingPlot.addItem(ui.edgeItem)
        ui.edgeItem.setZValue(ui.vertItem.zValue() - 1)

    def _set_grid_btn_color(self, color):
        r, g, b = color
        self.grid_color_btn.setStyleSheet(
            f"background-color: rgb({r},{g},{b}); border: 1px solid #888;")

    def _pick_grid_color(self):
        initial = QtGui.QColor(*self._grid_color)
        dialog = self._open_color_dialog(initial, self)
        dialog.currentColorChanged.connect(self._on_grid_color_changed)
        dialog.colorSelected.connect(self._on_grid_color_changed)
        dialog.exec_()

    def _on_grid_color_changed(self, color):
        if not color.isValid():
            return
        self._grid_color = (color.red(), color.green(), color.blue())
        self._set_grid_btn_color(self._grid_color)
        self._update_grid()

    def _update_grid(self):
        ui = self.ui
        ui.grid_color = self._grid_color
        ui.grid_width = self.grid_width_spin.value()
        if ui.gridItem is None:
            return
        was_visible = ui.gridItem.isVisible()
        ui.tilingPlot.removeItem(ui.gridItem)
        ui.gridItem = gridPlot(ui.tiling.grid, ui.grid_color, ui.grid_width)
        ui.tilingPlot.addItem(ui.gridItem)
        ui.gridItem.setZValue(ui.tileItem.zValue() - 1)
        if not was_visible:
            ui.gridItem.hide()
