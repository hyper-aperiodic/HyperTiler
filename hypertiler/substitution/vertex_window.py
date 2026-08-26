import colorsys
import math
from collections import defaultdict

import numpy as np
from PyQt5 import QtCore, QtGui, QtWidgets
import pyqtgraph as pg
from ..widgets import center_on_screen
from ..workers import group_mirror_types

## similar vertex window to the main window. seperate because we use a different 'mode'
##but could potentially be folded into the main if I can be bothered.
class SubstitutionVertexWindow(QtWidgets.QMainWindow):

    def __init__(self, sub_win):
        parent = None
        if sub_win._ui is not None:
            parent = getattr(sub_win._ui, '_main_window', None)
        super().__init__(parent)
        self._sub_win = sub_win
        self._highlight_items = {}
        self._all_verts = None
        self._vert_type = None
        self._canon_to_indices = None
        self._raw_canon_to_indices = None
        self._group_mirrors = False
        self.setWindowTitle("Vertex Types — Substitution")
        self._show_loading()
        self.resize(400, 150)
        center_on_screen(self, sub_win._plot)
        self.show()


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

    # ------------------------------------------------------------------
    # build display from worker result
    # ------------------------------------------------------------------

    def build_display(self, result):
        if hasattr(self, '_loading_timer') and self._loading_timer is not None:
            self._loading_timer.stop()
            self._loading_timer = None

        all_verts, vert_type, vert_canon = result
        self._all_verts = all_verts
        self._vert_type = vert_type

        # group unique vertex positions by canonical form
        canon_to_indices = defaultdict(list)
        seen = set()
        for i, v in enumerate(all_verts):
            pos_key = (round(float(v[0]), 4), round(float(v[1]), 4))
            if pos_key in seen:
                continue
            seen.add(pos_key)
            canon = vert_canon.get(i)
            if canon is not None:
                canon_to_indices[canon].append(i)

        self._raw_canon_to_indices = canon_to_indices
        self._rebuild_ui()

    def _on_group_mirrors_toggled(self, checked):
        self._group_mirrors = checked
        plot = self._sub_win._plot
        for item in self._highlight_items.values():
            plot.removeItem(item)
        self._highlight_items.clear()
        self._rebuild_ui()
        ui = getattr(self._sub_win, '_ui', None)
        nw = getattr(ui, 'network_window', None) if ui is not None else None
        if nw is not None and nw.isVisible():
            type_map = {c: list(idxs) for c, idxs in self._canon_to_indices.items()}
            idx_to_vert = {i: self._all_verts[i]
                           for idxs in self._canon_to_indices.values() for i in idxs}
            nw.refresh_sub(type_map, idx_to_vert)

    def _rebuild_ui(self):
        canon_to_indices = (group_mirror_types(self._raw_canon_to_indices)
                             if self._group_mirrors else self._raw_canon_to_indices)
        self._canon_to_indices = canon_to_indices
        vert_type = self._vert_type
        all_verts = self._all_verts
        total = sum(len(v) for v in canon_to_indices.values())

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
        tile_colors = self._sub_win._current_colors()

        for idx, (canon, vert_indices) in enumerate(
                sorted(canon_to_indices.items(), key=lambda x: -len(x[1]))):
            pct = 100 * len(vert_indices) / total
            row, col = divmod(idx, cols)

            # find a representative vertex with valid geometry
            rep_i = None
            for i in vert_indices:
                tiles = vert_type.get(i, [])
                if tiles:
                    all_pts = np.vstack([coords for _, coords in tiles])
                    if (np.max(all_pts, axis=0) - np.min(all_pts, axis=0)).max() > 1e-4:
                        rep_i = i
                        break
            if rep_i is None:
                continue

            pixmap = self._make_preview(rep_i, vert_type, all_verts, tile_colors, PREVIEW_SIZE)

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
                f"Type {idx+1}  —  {pct:.1f}%  ({len(vert_indices)} vertices)")
            label.setAlignment(QtCore.Qt.AlignCenter)
            cell_layout.addWidget(label)

            cb = QtWidgets.QCheckBox("Highlight on plot")
            cb.toggled.connect(
                lambda checked, c=canon, vi=vert_indices, ti=idx:
                self._toggle_highlight(checked, c, vi, ti))
            cell_layout.addWidget(cb)
            grid.addWidget(cell, row, col)

        n_rows = math.ceil(len(canon_to_indices) / cols)
        self.resize(cols * 190 + 20, min(n_rows * 260 + 20, 600))
        self.show()

    def _make_preview(self, rep_i, vert_type, all_verts, tile_colors, size):
        rep_v = all_verts[rep_i]
        color_paths = {}
        edge_path = QtGui.QPainterPath()

        for tile_type, coords in vert_type[rep_i]:
            base = tile_type.rsplit('_', 1)[0] if '_' in tile_type else tile_type
            color_str = tile_colors.get(tile_type, tile_colors.get(base, '#aaaaaa'))
            qc = QtGui.QColor(color_str)
            ck = qc.rgb()
            if ck not in color_paths:
                color_paths[ck] = (qc, QtGui.QPainterPath())
            cp = color_paths[ck][1]
            pts = [QtCore.QPointF(float(v[0] - rep_v[0]), float(v[1] - rep_v[1]))
                   for v in coords]
            cp.addPolygon(QtGui.QPolygonF(pts))
            n = len(pts)
            for j in range(n):
                edge_path.moveTo(pts[j])
                edge_path.lineTo(pts[(j + 1) % n])

        pixmap = QtGui.QPixmap(size, size)
        pixmap.fill(QtCore.Qt.white)
        br = edge_path.boundingRect()
        if br.isValid() and not br.isEmpty() and br.width() > 0 and br.height() > 0:
            pad = 0.15
            bw = br.width()  * (1 + 2 * pad)
            bh = br.height() * (1 + 2 * pad)
            scale = size / max(bw, bh)
            ox = (size - bw * scale) / 2 - (br.x() - br.width()  * pad) * scale
            oy = (size - bh * scale) / 2 - (br.y() - br.height() * pad) * scale
            painter = QtGui.QPainter(pixmap)
            painter.setRenderHint(QtGui.QPainter.Antialiasing)
            painter.translate(ox, oy)
            painter.scale(scale, scale)
            painter.setPen(QtCore.Qt.NoPen)
            for _, (qcolor, path) in color_paths.items():
                painter.setBrush(pg.mkBrush(qcolor))
                painter.drawPath(path)
            edge_pen = QtGui.QPen(QtCore.Qt.black, 2)
            edge_pen.setCosmetic(True)
            painter.setPen(edge_pen)
            painter.setBrush(QtCore.Qt.NoBrush)
            painter.drawPath(edge_path)
            painter.end()
        return pixmap


    def _toggle_highlight(self, checked, canon, vert_indices, type_idx):
        plot = self._sub_win._plot
        if checked:
            positions = np.array([self._all_verts[i] for i in vert_indices])
            h = (type_idx * 0.618) % 1.0
            r, g, b = colorsys.hsv_to_rgb(h, 0.9, 1.0)
            scatter = pg.ScatterPlotItem(
                x=positions[:, 0], y=positions[:, 1],
                size=8, pen=pg.mkPen(None),
                brush=pg.mkBrush(int(r*255), int(g*255), int(b*255), 255))
            scatter.setZValue(10)
            plot.addItem(scatter)
            self._highlight_items[canon] = scatter
        else:
            if canon in self._highlight_items:
                plot.removeItem(self._highlight_items.pop(canon))

    def closeEvent(self, event):
        plot = self._sub_win._plot
        for item in self._highlight_items.values():
            plot.removeItem(item)
        self._highlight_items.clear()
        super().closeEvent(event)
