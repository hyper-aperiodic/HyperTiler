from PyQt5 import QtCore, QtGui, QtWidgets
import pyqtgraph as pg
import numpy as np
import math
import colorsys
from ..workers import _VertexWorker


class VertexFinderWindow(QtWidgets.QMainWindow):
    def __init__(self, parent_ui):
        super().__init__(parent_ui._main_window)
        self.ui = parent_ui
        self.setWindowTitle("Vertex Types")
        self.highlight_items = {}
        self._show_loading()
        self.resize(400, 150)
        ref = self.ui._active_plot_widget()
        self.move(ref.mapToGlobal(QtCore.QPoint(ref.width() + 10, 0)))
        self.show()
        self._find_and_display()

    def _show_loading(self):
        if hasattr(self, '_loading_timer') and self._loading_timer is not None:
            self._loading_timer.stop()
        loading = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(loading)
        lay.addStretch()
        self._loading_lbl = QtWidgets.QLabel("Computing vertex types")
        self._loading_lbl.setAlignment(QtCore.Qt.AlignCenter)
        lay.addWidget(self._loading_lbl)
        lay.addStretch()
        self.setCentralWidget(loading)
        self._loading_dots = 0
        self._loading_timer = QtCore.QTimer(self)
        self._loading_timer.timeout.connect(self._tick_loading)
        self._loading_timer.start(300)

    def _tick_loading(self):
        self._loading_dots = (self._loading_dots + 1) % 4
        self._loading_lbl.setText("Computing vertex types" + "." * self._loading_dots)

    def refresh(self):
        self.highlight_items.clear()
        self._show_loading()
        self._find_and_display()

    def _find_and_display(self):
        ui = self.ui
        self._worker = _VertexWorker(ui.tiling, ui.poly_areas, ui.current_colors, ui.ngon_areas)
        self._worker.finished.connect(self._build_display)
        self._worker.start()

    def _build_display(self, type_map, idx_to_vert, vert_to_tiles):

        ##grab all the vertex types and plot them nicely. 
        ##TODO: does this still throw errors or flash?
        if hasattr(self, '_loading_timer') and self._loading_timer is not None:
            self._loading_timer.stop()
            self._loading_timer = None
        total = sum(len(v) for v in type_map.values())
        self.type_map = type_map
        self.idx_to_vert = idx_to_vert
        self.vert_to_tiles = vert_to_tiles

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        container = QtWidgets.QWidget()
        grid = QtWidgets.QGridLayout(container)
        grid.setSpacing(10)
        scroll.setWidget(container)
        self.setCentralWidget(scroll)

        cols = 3
        PREVIEW_SIZE = 150

        for idx, (key, vert_keys) in enumerate(
                sorted(type_map.items(), key=lambda x: -len(x[1]))):
            pct = 100 * len(vert_keys) / total
            row, col = divmod(idx, cols)

            rep_key = None
            for k in vert_keys:
                if k in vert_to_tiles and len(vert_to_tiles[k]) > 0:
                    tiles = vert_to_tiles[k]
                    rep_v = idx_to_vert[k]
                    all_pts = np.vstack([t[1] for t in tiles])
                    spread = np.max(all_pts, axis=0) - np.min(all_pts, axis=0)
                    if spread.max() > 1e-4:
                        rep_key = k
                        break

            if rep_key is None:
                continue

            rep_v = idx_to_vert[rep_key]
            tiles = vert_to_tiles[rep_key]

            color_paths = {}
            edge_path = QtGui.QPainterPath()
            for raw_tile, proj_tile, color in tiles:
                ck = tuple(color)
                if ck not in color_paths:
                    cp = QtGui.QPainterPath()
                    cp.setFillRule(QtCore.Qt.WindingFill)
                    color_paths[ck] = cp
                pts = [QtCore.QPointF(v[0] - rep_v[0], v[1] - rep_v[1]) for v in proj_tile]
                color_paths[ck].addPolygon(QtGui.QPolygonF(pts))
                n = len(pts)
                for i in range(n):
                    edge_path.moveTo(pts[i])
                    edge_path.lineTo(pts[(i + 1) % n])

            pixmap = QtGui.QPixmap(PREVIEW_SIZE, PREVIEW_SIZE)
            pixmap.fill(QtCore.Qt.white)
            br = edge_path.boundingRect()
            if br.isValid() and not br.isEmpty() and br.width() > 0 and br.height() > 0:
                pad = 0.15
                bw = br.width() * (1 + 2 * pad)
                bh = br.height() * (1 + 2 * pad)
                scale = PREVIEW_SIZE / max(bw, bh)
                ox = (PREVIEW_SIZE - bw * scale) / 2 - (br.x() - br.width() * pad) * scale
                oy = (PREVIEW_SIZE - bh * scale) / 2 - (br.y() - br.height() * pad) * scale
                painter = QtGui.QPainter(pixmap)
                painter.setRenderHint(QtGui.QPainter.Antialiasing)
                painter.translate(ox, oy)
                painter.scale(scale, scale)
                painter.setPen(QtCore.Qt.NoPen)
                for ck, path in color_paths.items():
                    painter.setBrush(pg.mkBrush(*ck))
                    painter.drawPath(path)
                edge_pen = QtGui.QPen(QtCore.Qt.black, 2)
                edge_pen.setCosmetic(True)
                painter.setPen(edge_pen)
                painter.setBrush(QtCore.Qt.NoBrush)
                painter.drawPath(edge_path)
                painter.end()

            cell = QtWidgets.QWidget()
            cell.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
            cell_layout = QtWidgets.QVBoxLayout(cell)
            cell_layout.setSpacing(2)
            cell_layout.setContentsMargins(4, 4, 4, 4)
            for c in range(cols):
                grid.setColumnStretch(c, 0)
            grid.setRowStretch(grid.rowCount(), 1)

            preview = QtWidgets.QLabel()
            preview.setFixedSize(PREVIEW_SIZE, PREVIEW_SIZE)
            preview.setPixmap(pixmap)
            cell_layout.addWidget(preview)

            label = QtWidgets.QLabel(
                f"Type {idx+1}  —  {pct:.1f}%  ({len(vert_keys)} vertices)")
            label.setAlignment(QtCore.Qt.AlignCenter)
            cell_layout.addWidget(label)

            cb = QtWidgets.QCheckBox("Highlight on plot")
            cb.toggled.connect(
                lambda checked, k=key, vk=vert_keys, i=idx:
                self._toggle_highlight(checked, k, vk, i))
            cell_layout.addWidget(cb)
            grid.addWidget(cell, row, col)

        n_rows = math.ceil(len(type_map) / cols)
        self.resize(cols * 190 + 20, min(n_rows * 260 + 20, 600))
        ref = self.ui._active_plot_widget()
        self.move(ref.mapToGlobal(QtCore.QPoint(ref.width() + 10, 0)))
        self.show()

    def _toggle_highlight(self, checked, key, vert_keys, type_idx):
        ui = self.ui
        if checked:
            verts = np.array([self.idx_to_vert[k] for k in vert_keys])
            h = (type_idx * 0.618) % 1.0
            r, g, b = colorsys.hsv_to_rgb(h, 0.9, 1)
            scatter = pg.ScatterPlotItem(
                x=verts[:, 0], y=verts[:, 1],
                size=ui.point_radius * 2, pen=pg.mkPen(None),
                brush=pg.mkBrush(int(r*255), int(g*255), int(b*255), 255),
                pxMode=False)
            scatter.setZValue(10)
            plot = ui._active_plot_widget()
            plot.addItem(scatter)
            plot.viewport().update()
            self.highlight_items[key] = scatter
        else:
            if key in self.highlight_items:
                ui._active_plot_widget().removeItem(self.highlight_items.pop(key))

    def closeEvent(self, event):
        plot = self.ui._active_plot_widget()
        for item in self.highlight_items.values():
            plot.removeItem(item)
        self.highlight_items.clear()
        super().closeEvent(event)
