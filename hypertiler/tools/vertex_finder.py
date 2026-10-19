from PyQt5 import QtCore, QtGui, QtWidgets
import pyqtgraph as pg
import numpy as np
import math
import colorsys
from ..workers import _VertexWorker, group_mirror_types
from ..widgets import center_on_screen
from ..config import make_app_icon


class VertexFinderWindow(QtWidgets.QMainWindow):
    def __init__(self, parent_ui):
        super().__init__(None)
        self.ui = parent_ui
        self.setWindowTitle("Vertex Types")
        self.setWindowIcon(make_app_icon())
        self.highlight_items = {}
        self._group_mirrors = False
        self._raw_type_map = {}
        self._show_loading()
        self.resize(400, 150)
        ref = self.ui._active_plot_widget()
        center_on_screen(self, ref)
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
        self._raw_type_map = type_map
        self.idx_to_vert = idx_to_vert
        self.vert_to_tiles = vert_to_tiles
        self._rebuild_ui()

    def _on_group_mirrors_toggled(self, checked):
        self._group_mirrors = checked
        for items in self.highlight_items.values():
            for plot, scatter in items:
                plot.removeItem(scatter)
        self.highlight_items.clear()
        self._rebuild_ui()
        nw = getattr(self.ui, 'network_window', None)
        if nw is not None and nw.isVisible():
            nw.refresh_sub(self.type_map, self.idx_to_vert)

    def _rebuild_ui(self):
        type_map = (group_mirror_types(self._raw_type_map) if self._group_mirrors
                    else self._raw_type_map)
        self.type_map = type_map
        idx_to_vert = self.idx_to_vert
        vert_to_tiles = self.vert_to_tiles
        total = sum(len(v) for v in type_map.values())

        central = QtWidgets.QWidget()
        outer = QtWidgets.QVBoxLayout(central)
        outer.setContentsMargins(6, 6, 6, 6)
        outer.setSpacing(4)

        mirror_cb = QtWidgets.QCheckBox("Group mirror-symmetric types")
        mirror_cb.setChecked(self._group_mirrors)
        mirror_cb.toggled.connect(self._on_group_mirrors_toggled)
        outer.addWidget(mirror_cb)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        container = QtWidgets.QWidget()
        grid = QtWidgets.QGridLayout(container)
        grid.setSpacing(10)
        scroll.setWidget(container)
        outer.addWidget(scroll)
        self.setCentralWidget(central)

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
        self.show()

    def _target_plots(self):
        """Every plot a highlight should be drawn on - normally just
        whichever is active (main tiling, or substitution's), but also
        the dual tiling window's own plot when that's open: its vertex
        types are built from a _DualAdapter whose vertices are the
        original tiling's tile centroids, so the same positions are
        meaningful on both plots at once, and both should show the
        highlight together rather than only whichever plot this window
        happened to be opened against."""
        ui = self.ui
        plots = [ui._active_plot_widget()]
        dual_win = getattr(ui, 'dual_window', None)
        if dual_win is not None and dual_win.isVisible() and dual_win._plot not in plots:
            plots.append(dual_win._plot)
        return plots

    def _toggle_highlight(self, checked, key, vert_keys, type_idx):
        ui = self.ui
        if checked:
            verts = np.array([self.idx_to_vert[k] for k in vert_keys])
            h = (type_idx * 0.618) % 1.0
            r, g, b = colorsys.hsv_to_rgb(h, 0.9, 1)
            brush = pg.mkBrush(int(r*255), int(g*255), int(b*255), 255)
            items = []
            for plot in self._target_plots():
                scatter = pg.ScatterPlotItem(
                    x=verts[:, 0], y=verts[:, 1],
                    size=ui.point_radius * 2, pen=pg.mkPen(None),
                    brush=brush, pxMode=False)
                scatter.setZValue(10)
                plot.addItem(scatter)
                plot.viewport().update()
                items.append((plot, scatter))
            self.highlight_items[key] = items
        else:
            for plot, scatter in self.highlight_items.pop(key, []):
                plot.removeItem(scatter)

    def closeEvent(self, event):
        for items in self.highlight_items.values():
            for plot, scatter in items:
                try:
                    plot.removeItem(scatter)
                except Exception:
                    pass
        self.highlight_items.clear()
        super().closeEvent(event)
