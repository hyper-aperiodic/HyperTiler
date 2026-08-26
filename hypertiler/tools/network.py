from PyQt5 import QtCore, QtWidgets, QtGui
from PyQt5.QtCore import Qt
import pyqtgraph as pg
import numpy as np
import colorsys
import json
from ..workers import _VertexWorker
from ..widgets import LockedViewBox, center_on_screen

###a self-contained little thing which allows the creation, visualisation, and
##exportation of a network of connected sites
##TODO: must double triple check on the dedup-ing of sites!!

class NetworkBuilderWindow(QtWidgets.QMainWindow):
    """Spatial network from selected vertex types — build, visualise, export."""

    def __init__(self, parent_ui, skip_worker=False):
        super().__init__(parent_ui._main_window)
        self.ui = parent_ui
        self.setWindowTitle("Network builder")
        self._vertices = None
        self._type_idxs = None
        self._edges = None
        self._neighbour_dict = None
        self._type_checkboxes = {}
        self._scatter_items = {}
        self._type_map = None
        self._idx_to_vert = None
        self._plot = None
        self._hover_items = []
        self._hover_tree = None
        self._hover_thresh = 1.0
        self._rebuild_timer = QtCore.QTimer(self)
        self._rebuild_timer.setSingleShot(True)
        self._rebuild_timer.timeout.connect(self._build_network)
        self._positioned = False

        vw = getattr(parent_ui, 'vertex_window', None)
        if vw is not None and vw.isVisible() and hasattr(vw, 'type_map'):
            self._type_map = vw.type_map
            self._idx_to_vert = vw.idx_to_vert
            self._setup_ui()
        elif skip_worker:
            self._setup_loading_ui()
        else:
            self._setup_loading_ui()
            self._worker = _VertexWorker(
                parent_ui.tiling, parent_ui.poly_areas, parent_ui.current_colors,
                parent_ui.ngon_areas)
            self._worker.finished.connect(self._on_worker_done)
            self._worker.start()

        self._reposition()
        self._positioned = True
        self.show()

    def _on_worker_done(self, type_map, idx_to_vert, _vert_to_tiles):
        self._type_map = type_map
        self._idx_to_vert = idx_to_vert
        self._setup_ui()
        # only the very first build 
        # should reposition - a refresh of an already-open, user-moved
        # window must stay exactly where it currently sits.
        if not self._positioned:
            self._reposition()
            self._positioned = True

    def refresh(self):
        self._rebuild_timer.stop()
        if hasattr(self, '_worker') and self._worker is not None:
            try:
                self._worker.finished.disconnect(self._on_worker_done)
            except RuntimeError:
                pass
        self._vertices = None
        self._type_idxs = None
        self._edges = None
        self._neighbour_dict = None
        self._scatter_items = {}
        self._type_checkboxes = {}
        self._type_map = None
        self._idx_to_vert = None
        self._plot = None
        self._setup_loading_ui()
        self._worker = _VertexWorker(
            self.ui.tiling, self.ui.poly_areas, self.ui.current_colors,
            self.ui.ngon_areas)
        self._worker.finished.connect(self._on_worker_done)
        self._worker.start()

    def refresh_sub(self, type_map, idx_to_vert):
        """Refresh with pre-computed substitution vertex data (bypasses VertexWorker)."""
        self._rebuild_timer.stop()
        self._vertices = None
        self._type_idxs = None
        self._edges = None
        self._neighbour_dict = None
        self._scatter_items = {}
        self._type_checkboxes = {}
        self._plot = None
        self._type_map = type_map
        self._idx_to_vert = idx_to_vert
        self._setup_ui()
        if not self._positioned:
            self._reposition()
            self._positioned = True

    def _setup_loading_ui(self):
        lbl = QtWidgets.QLabel("Computing vertex types…")
        lbl.setAlignment(Qt.AlignCenter)
        self.setCentralWidget(lbl)
        self.setFixedSize(900, 80)

    def _setup_ui(self):
        central = QtWidgets.QWidget()
        h = QtWidgets.QHBoxLayout(central)
        h.setContentsMargins(8, 8, 8, 8)
        h.setSpacing(8)

        left = QtWidgets.QWidget()
        left.setFixedWidth(230)
        lv = QtWidgets.QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(4)

        lv.addWidget(QtWidgets.QLabel("Vertex types:"))

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        tc = QtWidgets.QWidget()
        tv = QtWidgets.QVBoxLayout(tc)
        tv.setSpacing(2)
        tv.setContentsMargins(0, 0, 0, 0)

        total_verts = max(1, sum(len(v) for v in self._type_map.values()))
        for idx, (key, vert_keys) in enumerate(
                sorted(self._type_map.items(), key=lambda x: -len(x[1]))):
            pct = 100.0 * len(vert_keys) / total_verts
            cb = QtWidgets.QCheckBox(
                f"Type {idx + 1}  ({len(vert_keys)},  {pct:.1f}%)")
            cb.toggled.connect(
                lambda checked, k=key, vk=vert_keys, ti=idx:
                self._on_type_toggled(checked, k, vk, ti))
            tv.addWidget(cb)
            self._type_checkboxes[key] = (cb, vert_keys, idx)

        tv.addStretch()
        scroll.setWidget(tc)
        lv.addWidget(scroll)

        sel_h = QtWidgets.QHBoxLayout()
        btn_all = QtWidgets.QPushButton("All")
        btn_none = QtWidgets.QPushButton("None")
        btn_all.clicked.connect(self._select_all)
        btn_none.clicked.connect(self._select_none)
        sel_h.addWidget(btn_all)
        sel_h.addWidget(btn_none)
        lv.addLayout(sel_h)

        lv.addSpacing(8)

        rad_grid = QtWidgets.QGridLayout()
        rad_grid.setSpacing(3)
        rad_grid.addWidget(QtWidgets.QLabel("Min radius:"), 0, 0)
        self._rmin_spin = QtWidgets.QDoubleSpinBox()
        self._rmin_spin.setRange(0.0, 100000.0)
        self._rmin_spin.setSingleStep(0.1)
        self._rmin_spin.setDecimals(4)
        self._rmin_spin.setValue(0.0)
        rad_grid.addWidget(self._rmin_spin, 0, 1)
        rad_grid.addWidget(QtWidgets.QLabel("Max radius:"), 1, 0)
        self._rmax_spin = QtWidgets.QDoubleSpinBox()
        self._rmax_spin.setRange(0.001, 100000.0)
        self._rmax_spin.setSingleStep(0.1)
        self._rmax_spin.setDecimals(4)
        self._rmax_spin.setValue(1.5)
        rad_grid.addWidget(self._rmax_spin, 1, 1)
        self._rmin_spin.valueChanged.connect(lambda v: self._rmax_spin.setMinimum(v))
        self._rmax_spin.valueChanged.connect(lambda v: self._rmin_spin.setMaximum(v))
        btn_auto = QtWidgets.QPushButton("Auto")
        btn_auto.setFixedWidth(48)
        btn_auto.clicked.connect(self._auto_radius)
        rad_grid.addWidget(btn_auto, 0, 2, 2, 1)
        lv.addLayout(rad_grid)

        lv.addSpacing(4)
        nn_h = QtWidgets.QHBoxLayout()
        nn_h.addWidget(QtWidgets.QLabel("Max shells:"))
        self._nn_spin = QtWidgets.QSpinBox()
        self._nn_spin.setRange(1, 999)
        self._nn_spin.setValue(6)
        nn_h.addWidget(self._nn_spin)
        nn_h.addStretch()
        lv.addLayout(nn_h)

        lv.addSpacing(4)
        btn_build = QtWidgets.QPushButton("Build network")
        btn_build.clicked.connect(self._build_network)
        lv.addWidget(btn_build)

        lv.addSpacing(10)
        lv.addWidget(QtWidgets.QLabel("Export:"))
        btn_exp_verts = QtWidgets.QPushButton("Vertices only")
        btn_exp_nbrs = QtWidgets.QPushButton("Neighbour dictionary")
        btn_exp_verts.clicked.connect(self._export_vertices_only)
        btn_exp_nbrs.clicked.connect(self._export_neighbours)
        lv.addWidget(btn_exp_verts)
        lv.addWidget(btn_exp_nbrs)

        lv.addStretch()
        self._status_lbl = QtWidgets.QLabel("")
        self._status_lbl.setWordWrap(True)
        self._status_lbl.setStyleSheet("color:#888; font-size:8pt;")
        lv.addWidget(self._status_lbl)

        h.addWidget(left)

        self._plot = pg.PlotWidget(viewBox=LockedViewBox())
        self._plot.setBackground('w')
        self._plot.getPlotItem().hideAxis('bottom')
        self._plot.getPlotItem().hideAxis('left')
        self._plot.hideButtons()
        self._plot.setMouseEnabled(x=True, y=True)
        self._plot.getViewBox().setAspectLocked(True)
        self._plot.getViewBox().menu = None
        self._plot.scene().contextMenuEvent = lambda e: None
        self._plot.scene().sigMouseMoved.connect(self._on_hover)
        h.addWidget(self._plot)

        self.setCentralWidget(central)
        self.setFixedSize(900, 650)

    def _reposition(self):
        ref = self.ui._active_plot_widget()
        center_on_screen(self, ref)


    def _select_all(self):
        for cb, _, __ in self._type_checkboxes.values():
            cb.setChecked(True)

    def _select_none(self):
        for cb, _, __ in self._type_checkboxes.values():
            cb.setChecked(False)

    def _on_type_toggled(self, checked, key, vert_keys, tidx):
        if self._plot is None:
            return
        if checked:
            if key not in self._scatter_items:
                verts = np.array([self._idx_to_vert[vk] for vk in vert_keys], dtype=float)
                hue = (tidx * 0.618) % 1.0
                r, g, b = colorsys.hsv_to_rgb(hue, 0.9, 1.0)
                sc = pg.ScatterPlotItem(
                    x=verts[:, 0], y=verts[:, 1],
                    size=7, pxMode=True,
                    pen=pg.mkPen(None),
                    brush=pg.mkBrush(int(r * 255), int(g * 255), int(b * 255), 220))
                self._plot.addItem(sc)
                self._scatter_items[key] = sc
                self._plot.enableAutoRange()
        else:
            if key in self._scatter_items:
                self._plot.removeItem(self._scatter_items.pop(key))
        if self._edges is not None:
            self._rebuild_timer.start(150)

    def _collect_selected(self):
        verts, tidxs = [], []
        for key, (cb, vert_keys, tidx) in self._type_checkboxes.items():
            if not cb.isChecked():
                continue
            for vk in vert_keys:
                verts.append(self._idx_to_vert[vk])
                tidxs.append(tidx)
        if not verts:
            return None, None
        return np.array(verts, dtype=float), np.array(tidxs, dtype=int)

    def _auto_radius(self):
        from scipy.spatial import KDTree
        verts, _ = self._collect_selected()
        if verts is None or len(verts) < 2:
            return
        tree = KDTree(verts)
        k = min(4, len(verts))
        dists, _ = tree.query(verts, k=k)
        nn1 = dists[:, 1] if dists.ndim > 1 and dists.shape[1] > 1 else dists.ravel()
        nn1 = nn1[nn1 > 1e-10]
        if len(nn1):
            med = float(np.median(nn1))
            self._rmin_spin.setValue(round(med * 0.5, 4))
            self._rmax_spin.setValue(round(med * 1.05, 4))

    def _build_network(self):
        from scipy.spatial import KDTree
        verts, tidxs = self._collect_selected()
        if verts is None:
            self._status_lbl.setText("No vertex types selected.")
            return

        rmin = self._rmin_spin.value()
        rmax = self._rmax_spin.value()
        max_shells = self._nn_spin.value()

        tree = KDTree(verts)
        n = len(verts)

        raw = []
        for i, j in tree.query_pairs(rmax):
            d = float(np.linalg.norm(verts[i] - verts[j]))
            if d >= rmin:
                raw.append((d, i, j))
        raw.sort()

        _TOL = 0.02
        global_shells = []
        for d, i, j in raw:
            if not global_shells or d > global_shells[-1][0] * (1.0 + _TOL):
                global_shells.append((d, []))
            global_shells[-1][1].append((d, i, j))

        nbr_dict = {i: [] for i in range(n)}
        kept = set()
        for shell_idx, (ref_d, shell_pairs) in enumerate(
                global_shells[:max_shells], start=1):
            for d, i, j in shell_pairs:
                nbr_dict[i].append((d, j, shell_idx))
                nbr_dict[j].append((d, i, shell_idx))
                kept.add((min(i, j), max(i, j)))

        for i in range(n):
            nbr_dict[i].sort()

        edges = (np.array(sorted(kept), dtype=int) if kept
                 else np.empty((0, 2), dtype=int))

        self._vertices = verts
        self._type_idxs = tidxs
        self._edges = edges
        self._neighbour_dict = nbr_dict

        self._hover_tree = KDTree(verts)
        self._hover_thresh = (global_shells[0][0] * 0.5 if global_shells else 1.0)

        self._draw_network()
        n_shown = min(len(global_shells), max_shells)
        self._status_lbl.setText(
            f"{n} vertices\n{len(edges)} connections\n"
            f"{n_shown} shells  r [{rmin:.3f}, {rmax:.3f}]")

    def _draw_network(self):
        if self._plot is None:
            return
        vb = self._plot.getViewBox()
        auto_x, auto_y = vb.autoRangeEnabled()
        saved_range = None if (auto_x and auto_y) else vb.viewRange()

        self._plot.clear()
        self._scatter_items.clear()
        self._hover_items.clear()
        verts = self._vertices
        if verts is None or len(verts) == 0:
            return

        if len(self._edges) > 0:
            xs, ys = [], []
            for i, j in self._edges:
                xs += [verts[i, 0], verts[j, 0], float('nan')]
                ys += [verts[i, 1], verts[j, 1], float('nan')]
            self._plot.addItem(pg.PlotDataItem(
                x=xs, y=ys,
                pen=pg.mkPen((120, 120, 120, 160), width=1)))

        for tidx in np.unique(self._type_idxs):
            mask = self._type_idxs == tidx
            hue = (tidx * 0.618) % 1.0
            r, g, b = colorsys.hsv_to_rgb(hue, 0.9, 1.0)
            sc = pg.ScatterPlotItem(
                x=verts[mask, 0], y=verts[mask, 1],
                size=7, pxMode=True,
                pen=pg.mkPen(None),
                brush=pg.mkBrush(int(r * 255), int(g * 255), int(b * 255), 220))
            self._plot.addItem(sc)
            key = next(
                (k for k, (_, __, ti) in self._type_checkboxes.items() if ti == tidx),
                None)
            if key is not None:
                self._scatter_items[key] = sc

        if saved_range is not None:
            vb.setRange(xRange=saved_range[0], yRange=saved_range[1], padding=0)
        else:
            self._plot.enableAutoRange()


    def _on_hover(self, pos):
        if self._plot is None:
            return
        for item in self._hover_items:
            self._plot.removeItem(item)
        self._hover_items.clear()

        if self._hover_tree is None or self._vertices is None:
            return

        vb = self._plot.getViewBox()
        if not vb.sceneBoundingRect().contains(pos):
            return

        mp = vb.mapSceneToView(pos)
        dist, idx = self._hover_tree.query([mp.x(), mp.y()], k=1)
        if dist > self._hover_thresh:
            return

        h = pg.ScatterPlotItem(
            x=[self._vertices[idx, 0]], y=[self._vertices[idx, 1]],
            size=12, pxMode=True,
            pen=pg.mkPen(None),
            brush=pg.mkBrush(0, 0, 0, 255))
        h.setZValue(30)
        self._plot.addItem(h)
        self._hover_items.append(h)

        for d, j, shell in self._neighbour_dict.get(idx, []):
            grey = min(210, 50 + (shell - 1) * 60)
            hn = pg.ScatterPlotItem(
                x=[self._vertices[j, 0]], y=[self._vertices[j, 1]],
                size=10, pxMode=True,
                pen=pg.mkPen(None),
                brush=pg.mkBrush(grey, grey, grey, 255))
            hn.setZValue(30)
            self._plot.addItem(hn)
            self._hover_items.append(hn)


    def _export_vertices_only(self):
        verts, tidxs = self._collect_selected()
        if verts is None:
            QtWidgets.QMessageBox.information(self, "Export", "Select at least one vertex type.")
            return
        saved = (self._vertices, self._type_idxs, self._edges, self._neighbour_dict)
        self._vertices = verts
        self._type_idxs = tidxs
        self._edges = np.empty((0, 2), dtype=int)
        self._neighbour_dict = None
        self._do_export(include_connections=False)
        self._vertices, self._type_idxs, self._edges, self._neighbour_dict = saved

    def _export_neighbours(self):
        if self._neighbour_dict is None:
            QtWidgets.QMessageBox.information(self, "Export", "Build the network first.")
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Export Neighbour Dictionary", "", "JSON (*.json);;All files (*)")
        if not path:
            return
        if not path.endswith('.json'):
            path += '.json'

        max_order = max(
            (s for nbrs in self._neighbour_dict.values() for _, _, s in nbrs), default=0)
        order_dists = {s: [] for s in range(1, max_order + 1)}
        for nbrs in self._neighbour_dict.values():
            for d, _, shell in nbrs:
                order_dists[shell].append(d)
        mean_by_order = {
            s: round(float(np.mean(ds)), 6)
            for s, ds in order_dists.items() if ds}

        data = {
            "max_nn_order": max_order,
            "mean_distance_by_nn_order": mean_by_order,
            "vertices": [
                {
                    "index": i,
                    "x": round(float(self._vertices[i, 0]), 6),
                    "y": round(float(self._vertices[i, 1]), 6),
                    "type": int(self._type_idxs[i]),
                    "neighbours": [
                        {"index": int(j),
                         "distance": round(float(d), 6),
                         "nn_order": shell}
                        for d, j, shell in self._neighbour_dict[i]
                    ]
                }
                for i in range(len(self._vertices))
            ]
        }
        with open(path, 'w') as f:
            json.dump(data, f, indent=2)
        self._status_lbl.setText(f"Saved {len(self._vertices)} vertices.")

    def _do_export(self, include_connections):
        path, filt = QtWidgets.QFileDialog.getSaveFileName(
            self, "Export Network", "",
            "JSON (*.json);;CSV (*.csv);;All files (*)")
        if not path:
            return
        is_csv = path.endswith('.csv') or 'CSV' in filt
        if not path.endswith('.json') and not path.endswith('.csv'):
            path += '.csv' if is_csv else '.json'
            is_csv = path.endswith('.csv')

        verts, tidxs = self._vertices, self._type_idxs
        if is_csv:
            import csv
            with open(path, 'w', newline='') as f:
                w = csv.writer(f)
                w.writerow(['index', 'x', 'y', 'type'])
                for i, (p, t) in enumerate(zip(verts, tidxs)):
                    w.writerow([i, round(float(p[0]), 6),
                                 round(float(p[1]), 6), int(t)])
            if include_connections and len(self._edges) > 0:
                cp = path.replace('.csv', '_connections.csv')
                with open(cp, 'w', newline='') as f:
                    w = csv.writer(f)
                    w.writerow(['i', 'j', 'distance', 'nn_order_from_i', 'nn_order_from_j'])
                    def _rk(src, tgt):
                        for _, nb, shell in self._neighbour_dict.get(src, []):
                            if nb == tgt:
                                return shell
                        return -1
                    for i, j in self._edges:
                        d = float(np.linalg.norm(verts[i] - verts[j]))
                        w.writerow([int(i), int(j), round(d, 6), _rk(i, j), _rk(j, i)])
        else:
            data = {
                "vertices": [
                    {"index": i,
                     "x": round(float(p[0]), 6),
                     "y": round(float(p[1]), 6),
                     "type": int(t)}
                    for i, (p, t) in enumerate(zip(verts, tidxs))
                ]
            }
            if include_connections:
                def _nn_rank(src, tgt):
                    for _, nb, shell in self._neighbour_dict.get(src, []):
                        if nb == tgt:
                            return shell
                    return -1
                data["connections"] = [
                    {"i": int(i), "j": int(j),
                     "distance": round(float(np.linalg.norm(verts[i] - verts[j])), 6),
                     "nn_order_from_i": _nn_rank(i, j),
                     "nn_order_from_j": _nn_rank(j, i)}
                    for i, j in self._edges
                ]
            with open(path, 'w') as f:
                json.dump(data, f, indent=2)

        self._status_lbl.setText(f"Saved {len(verts)} vertices.")
