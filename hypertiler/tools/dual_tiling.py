import numpy as np
from collections import Counter
from types import SimpleNamespace
from PyQt5 import QtCore, QtWidgets

import pyqtgraph as pg

from ..widgets import LockedViewBox
from ..graphics import coloredPointPlot, linkPlot, tilePlot


#TODO: 

def _compute_dual(tiling, poly_areas, ngon_areas, current_colors):
    """Compute the dual graph of a tiling: one point per tile (its
    centroid), linked to the centroids of every tile it shares an edge
    with, coloured by the same classified type index as the tile.

    Returns (centroids, colors, type_idx, edges):
      centroids - (N, 2) ndarray, one row per tile
      colors    - list of (r, g, b) tuples, one per tile
      type_idx  - list of int, the classified type index per tile
      edges     - list of (i, j) centroid-index pairs, one per shared edge
    """
    n_polys = len(tiling.points)
    poly_color = [current_colors[t] for t in poly_areas]
    tiles = list(zip(tiling.raw_indices[:n_polys], tiling.points,
                      poly_color, poly_areas))

    if len(ngon_areas) > 0 and len(tiling.raw_indices) > n_polys:
        ngon_color = [current_colors[t] for t in ngon_areas]
        tiles += list(zip(tiling.raw_indices[n_polys], tiling.p_points,
                           ngon_color, ngon_areas))

    centroids = np.array([proj.mean(axis=0) for _, proj, _, _ in tiles])
    colors = [c for _, _, c, _ in tiles]
    type_idx = [int(t) for _, _, _, t in tiles]

    # two tiles are edge-adjacent iff they share exactly two corners - use
    # the same raw-index corner keys _VertexWorker already uses
    # (hypertiler/workers.py:68) to detect shared corners between tiles
    corner_to_tiles = {}
    for i, (raw_tile, _, _, _) in enumerate(tiles):
        for raw_vert in raw_tile:
            key = tuple(raw_vert)
            corner_to_tiles.setdefault(key, []).append(i)

    pair_counts = Counter()
    for tile_ids in corner_to_tiles.values():
        unique_ids = sorted(set(tile_ids))
        for a_pos in range(len(unique_ids)):
            for b_pos in range(a_pos + 1, len(unique_ids)):
                pair_counts[(unique_ids[a_pos], unique_ids[b_pos])] += 1

    edges = [pair for pair, count in pair_counts.items() if count >= 2]

    return centroids, colors, type_idx, edges


def _compute_dual_faces(tiling, centroids):
    """Build the proper dual-tiling faces: for each original vertex shared
    by >=3 tiles, a new polygon connecting the centroids of every tile
    touching that vertex (i.e. vert_to_tiles), in angular order around it.

    Mirrors _VertexWorker's own idx_to_vert/vert_to_tiles construction
    (hypertiler/workers.py:64-73), just tracking tile index instead of
    full tile tuples since we already have `centroids` per tile.

    Returns (faces, face_tile_ids, vertex_keys):
      faces         - list of (K, 2) ndarrays, K >= 3, one polygon per
                      original vertex with >=3 surrounding tiles
      face_tile_ids - list of int-lists, the tile indices forming each
                      face, in the same cyclic order as `faces`
      vertex_keys   - list of raw index-space vertex keys, parallel to
                      `faces` - unused for now, kept for a future
                      "colour by vertex type" option
    """
    n_polys = len(tiling.points)
    all_raw = list(tiling.raw_indices[:n_polys])
    if len(tiling.raw_indices) > n_polys:
        all_raw += list(tiling.raw_indices[n_polys])
    all_proj = list(tiling.points) + list(tiling.p_points)

    idx_to_vert = {}
    vert_to_tiles = {}
    for tile_i, (raw_tile, proj_tile) in enumerate(zip(all_raw, all_proj)):
        for raw_vert, proj_vert in zip(raw_tile, proj_tile):
            key = tuple(raw_vert)
            if key not in idx_to_vert:
                idx_to_vert[key] = proj_vert
            vert_to_tiles.setdefault(key, []).append(tile_i)

    faces, face_tile_ids, vertex_keys = [], [], []
    for key, tile_ids in vert_to_tiles.items():
        unique_ids = sorted(set(tile_ids))
        if len(unique_ids) < 3:
            continue  # need >=3 tiles round a vertex to make a polygon
        v = idx_to_vert[key]
        unique_ids.sort(key=lambda t: np.arctan2(
            centroids[t][1] - v[1], centroids[t][0] - v[0]))
        faces.append(centroids[unique_ids])
        face_tile_ids.append(unique_ids)
        vertex_keys.append(key)

    return faces, face_tile_ids, vertex_keys


# TODO(option 2): colour dual faces by which vertex TYPE (canonical
# vertex-configuration key from _VertexWorker's type_map) the vertex they
# surround belongs to, instead of by raw polygon area - more robust than
# area (distinguishes faces that happen to have the same area but come
# from topologically different vertices). Blocked on _VertexWorker's
# coverage: it only classifies vertices within 80% of the bounding radius
# (workers.py:79 `radius = norms.max() * 0.8`, applied by the
# `set_a_keys` filter at workers.py:81-85), so ~20% of vertices near the
# tiling boundary never get a canonical type - update that filter/logic
# before wiring this in, or faces near the edge will have no colour to
# fall back on.
def _color_faces_by_vertex_type(faces, vertex_keys, type_map):
    raise NotImplementedError


class _DualAdapter:
    """Tiling-like adapter for the dual tiling's FACES: each dual face
    (from _compute_dual_faces - one real polygon per original vertex with
    >=3 surrounding tiles) becomes a proper n-gon tile, so it can be
    swapped in as self.tiling and driven by the existing FFT / Network
    builder / Vertex types / Edit style tools exactly like a real
    TileMaker tiling - no degenerate tiles needed. Each face's raw corner
    key is (tile_id,), matching _VertexWorker's `tuple(raw_vert)`
    convention (workers.py:68): two faces share a corner exactly when
    they share a tile_id, i.e. when both dual faces surround a vertex
    that the same original tile touches."""

    def __init__(self, faces, face_tile_ids):
        self.points = []
        self.p_points = faces
        self.poly_areas = []
        self.ngon_areas = []  # set by caller, see Ui_MainWindow._activate_dual_tiling
        self.raw_indices = [[[np.array([t]) for t in ids] for ids in face_tile_ids]]


class DualTilingWindow(QtWidgets.QMainWindow):
    """Shows the dual of the current tiling - one point per tile at its
    centroid, linked to neighbouring tiles' centroids, plus the proper
    dual-tiling faces built from vertices shared by >=3 tiles - and makes
    the faces the active tiling instance for FFT / Network builder /
    Vertex types / Edit style."""

    def __init__(self, parent_ui):
        # no Qt parent - a parented top-level window is an "owned window"
        # on Windows, which Qt/the OS then forces to always stay above its
        # owner in z-order regardless of click focus. Independent here so
        # normal click-to-front focus works; main_window.py tracks it via
        # windows_open/destroyed for cleanup instead of parent ownership.
        super().__init__(None)
        self.ui = parent_ui
        self.setWindowTitle("Dual tiling")
        self._centroids = None
        self._faces = None
        self._face_tile_ids = None
        self._setup_ui()
        self._compute_and_show()

    def _setup_ui(self):
        central = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(central)

        self._plot = pg.PlotWidget(viewBox=LockedViewBox())
        self._plot.setBackground('w')
        self._plot.getPlotItem().hideAxis('bottom')
        self._plot.getPlotItem().hideAxis('left')
        self._plot.hideButtons()
        self._plot.setMouseEnabled(x=True, y=True)
        self._plot.getViewBox().setAspectLocked(True)
        self._plot.getViewBox().menu = None
        self._plot.scene().contextMenuEvent = lambda e: None
        v.addWidget(self._plot)

        btn_h = QtWidgets.QHBoxLayout()
        self._fft_btn = QtWidgets.QPushButton("Compute FFT")
        self._fft_btn.clicked.connect(self._run_fft)
        self._vertex_btn = QtWidgets.QPushButton("Vertex types")
        self._vertex_btn.clicked.connect(self._run_vertex_types)
        self._network_btn = QtWidgets.QPushButton("Network builder")
        self._network_btn.clicked.connect(self._run_network_builder)
        for btn in (self._fft_btn, self._vertex_btn, self._network_btn):
            btn_h.addWidget(btn)
        v.addLayout(btn_h)

        self._status_lbl = QtWidgets.QLabel("")
        self._status_lbl.setStyleSheet("color:#888; font-size:8pt;")
        v.addWidget(self._status_lbl)

        self.setCentralWidget(central)
        self.setFixedSize(700, 650)

        # offset next to the active tiling plot rather than centering on
        # screen, which would otherwise land this window directly on top
        # of the main window (same trick editTilingStyle uses for
        # StyleDialog, main_window.py)
        ref = self.ui._active_plot_widget()
        top_right = ref.mapToGlobal(QtCore.QPoint(ref.width() + 10, 0))
        self.move(top_right)

    def _compute_and_show(self):
        ui = self.ui
        centroids, colors, type_idx, edges = _compute_dual(
            ui.tiling, ui.poly_areas, ui.ngon_areas, ui.current_colors)

        faces, face_tile_ids, vertex_keys = _compute_dual_faces(ui.tiling, centroids)
        self._centroids, self._faces, self._face_tile_ids = centroids, faces, face_tile_ids

        ui._activate_dual_tiling(centroids, faces, face_tile_ids)

        self._plot.clear()
        if faces:
            face_colors = [ui.current_colors[t] for t in ui.ngon_areas]
            fake_tiling = SimpleNamespace(points=[], p_points=faces)
            self._plot.addItem(tilePlot(fake_tiling, [], face_colors,
                                         edge_color=(60, 60, 60), edge_width=1))
        self._plot.addItem(linkPlot(centroids, edges, color=(120, 120, 120, 160), width=1))
        # self._plot.addItem(coloredPointPlot(centroids, colors, radius=0.15))
        self._plot.enableAutoRange()

        self._status_lbl.setText(
            f"{len(centroids)} tiles, {len(edges)} links, {len(faces)} dual faces - "
            f"now the active tiling instance for FFT / Network builder / Vertex types")

    def _activate(self):
        """Re-assert this window's dual tiling as self.tiling before
        running a tool on it - covers the case where something else (e.g.
        clicking "Tile!" on the main window) swapped it away since this
        window was computed."""
        if self._centroids is not None:
            self.ui._activate_dual_tiling(self._centroids, self._faces, self._face_tile_ids)

    def _run_fft(self):
        # call the _show_*_window() cores directly, not the public
        # compute*() menu actions - those branch on _in_sub_mode first
        # and would re-populate from substitution (if this dual tiling
        # was computed while in substitution mode), undoing the
        # _activate() call above and running on the wrong tiling
        self._activate()
        self.ui._show_fft_window()

    def _run_vertex_types(self):
        self._activate()
        self.ui._show_vertex_types_window()

    def _run_network_builder(self):
        self._activate()
        self.ui._show_network_builder_window()
