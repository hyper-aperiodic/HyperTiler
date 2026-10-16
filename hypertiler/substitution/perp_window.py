import numpy as np
from PyQt5 import QtCore, QtGui, QtWidgets
import pyqtgraph as pg

from .. import config
from ..widgets import center_on_screen, LockedViewBox
from ..helpers import make_colors
from .worker import _PerpVertexTypesWorker


class PerpSpaceWindow(QtWidgets.QMainWindow):
    """Shows the perpendicular-space (cut-and-project) image of every tile
    vertex in the current substitution tiling - see inkTile.perp_coords().
    """

    def __init__(self, sub_win):
        parent = None
        if sub_win._ui is not None:
            parent = getattr(sub_win._ui, '_main_window', None)
        super().__init__(parent)
        self._sub_win = sub_win
        self._it = None
        self._by_default = None       # cached (pos, brush) scatter data
        self._vertex_scatters = []    # [(ScatterPlotItem, label), ...] per vertex type
        self._legend = None
        self._vertex_worker = None
        self._insets = []
        self.setWindowTitle("Perpendicular Space")

        tb = self.addToolBar("Perp space")
        tb.setMovable(False)

        self._colour_action = QtWidgets.QAction("Colour by vertex type", self)
        self._colour_action.setCheckable(True)
        self._colour_action.setEnabled(False)
        self._colour_action.toggled.connect(self._on_colour_toggled)
        tb.addAction(self._colour_action)

        self._vectors_action = QtWidgets.QAction("Basis vectors", self)
        self._vectors_action.setCheckable(True)
        self._vectors_action.setChecked(False)
        self._vectors_action.setEnabled(False)
        self._vectors_action.toggled.connect(self._on_vectors_toggled)
        tb.addAction(self._vectors_action)

        self._show_loading()
        self.resize(480, 480)
        center_on_screen(self, sub_win._plot)
        self.show()

    def _show_loading(self):
        if hasattr(self, '_loading_timer') and self._loading_timer is not None:
            self._loading_timer.stop()
        # setCentralWidget below deletes the old plot widget (and its child
        # inset widgets, if any) - drop our references so a resize event
        # arriving before build_display() rebuilds them can't touch them
        self._insets = []
        loading = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(loading)
        lay.addStretch()
        self._loading_lbl = QtWidgets.QLabel("Building perpendicular-space index")
        self._loading_lbl.setAlignment(QtCore.Qt.AlignCenter)
        lay.addWidget(self._loading_lbl)
        lay.addStretch()
        self.setCentralWidget(loading)
        self._loading_dots = 0
        self._loading_timer = QtCore.QTimer(self)
        self._loading_timer.timeout.connect(self._tick_loading)
        self._loading_timer.start(300)
        self._vertex_scatters = []
        self._legend = None

    def _tick_loading(self):
        self._loading_dots = (self._loading_dots + 1) % 4
        self._loading_lbl.setText("Building perpendicular-space index" + "." * self._loading_dots)

    # ------------------------------------------------------------------
    # main plot
    # ------------------------------------------------------------------

    def build_display(self, it, vert_canon=None, all_perp=None):
        if hasattr(self, '_loading_timer') and self._loading_timer is not None:
            self._loading_timer.stop()
            self._loading_timer = None
        self._it = it

        if it.d == 0:
            msg = QtWidgets.QLabel(
                "This tiling's vertex module has rank 2 (hyperspace = physical "
                "space): it's periodic, so there's no perpendicular space.")
            msg.setWordWrap(True)
            msg.setAlignment(QtCore.Qt.AlignCenter)
            msg.setContentsMargins(20, 20, 20, 20)
            self.setCentralWidget(msg)
            self.setWindowTitle("Perpendicular Space — none (periodic tiling)")
            return

        container = QtWidgets.QWidget()
        central_layout = QtWidgets.QVBoxLayout(container)
        central_layout.setContentsMargins(0, 0, 0, 0)
        self.setCentralWidget(container)

        self._plot_widget = pg.PlotWidget(viewBox=LockedViewBox())
        self._plot_widget.setBackground('w')
        central_layout.addWidget(self._plot_widget)
        plot = self._plot_widget.getPlotItem()
        plot.setAspectLocked(True)
        plot.hideButtons()
        plot.setMenuEnabled(False)
        label_style = {'font-size': '14pt'}
        plot.setLabel('bottom', 'E<sub>⊥,x</sub>', **label_style)
        plot.setLabel('left', 'E<sub>⊥,y</sub>', **label_style)
        self._scatter = pg.ScatterPlotItem(size=4, pen=None)
        plot.addItem(self._scatter)

        self._by_default = self._default_colors()
        self._set_scatter(self._by_default)

        self._insets = [
            _VectorInset(it.basis, "E∥", self._plot_widget, side='left'),
            _VectorInset(it.perp[:2] if it.perp.shape[0] >= 2
                        else np.vstack([it.perp, np.zeros((2 - it.perp.shape[0], it.r))]),
                        "E⊥", self._plot_widget, side='right'),
        ]
        for inset in self._insets:
            inset.set_visible(self._vectors_action.isChecked())
        QtCore.QTimer.singleShot(0, self._position_insets)

        self._colour_action.setEnabled(True)
        self._vectors_action.setEnabled(True)
        if vert_canon is not None and all_perp is not None:
            self._apply_vertex_types(vert_canon, all_perp)

        extra = f" (showing 2 of {it.d})" if it.d > 2 else ""
        self.setWindowTitle(
            f"Perpendicular Space — hyperspace rank {it.r}, "
            f"perp dim {it.d}{extra}, contraction {it.contraction:.4f}")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._position_insets()

    def _position_insets(self):
        for inset in self._insets:
            inset.reposition()

    def _on_vectors_toggled(self, checked):
        for inset in self._insets:
            inset.set_visible(checked)

    def _default_colors(self):
        """Plain, high-visibility points (black on the white background) -
        the tiling's own tile colours are often too bright/similar to read
        as a dense point cloud, so they're reserved for the explicit
        "colour by vertex type" view instead."""
        it = self._it
        pos = np.vstack([pts[:, :2] for pts in it.perp_coords()])
        brush = pg.mkBrush(30, 30, 30, 160)
        pos, _ = self._dedupe(pos, None)
        return pos, [brush] * len(pos)

    @staticmethod
    def _dedupe(pos, brushes):
        """keep one point per shared vertex, so density reflects distinct
        points rather than how many tiles touch each one"""
        if not len(pos):
            return pos, brushes
        _, idx = np.unique(np.round(pos, 6), axis=0, return_index=True)
        return pos[idx], ([brushes[i] for i in idx] if brushes is not None else None)

    def _set_scatter(self, data):
        pos, brushes = data
        if len(pos):
            self._scatter.setData(pos=pos, brush=brushes)
        else:
            self._scatter.clear()

    # ------------------------------------------------------------------
    # colour by vertex type
    # ------------------------------------------------------------------

    def _on_colour_toggled(self, checked):
        if not checked:
            self._show_default_view()
            return
        if self._vertex_scatters:
            self._show_vertex_type_view()
            return
        if self._vertex_worker is not None and self._vertex_worker.isRunning():
            return
        self._colour_action.setEnabled(False)
        self._colour_action.setText("Analysing vertex types…")
        self._vertex_worker = _PerpVertexTypesWorker(self._it)
        self._vertex_worker.finished.connect(self._on_vertex_types_done)
        self._vertex_worker.error.connect(self._on_vertex_types_error)
        self._vertex_worker.start()

    def _show_default_view(self):
        self._scatter.setVisible(True)
        for item, _ in self._vertex_scatters:
            item.setVisible(False)
        if self._legend is not None:
            self._legend.hide()

    def _show_vertex_type_view(self):
        self._scatter.setVisible(False)
        for item, _ in self._vertex_scatters:
            item.setVisible(True)
        if self._legend is not None:
            self._legend.show()

    def _apply_vertex_types(self, vert_canon, all_perp):
        from collections import defaultdict
        # canon is None for a vertex whose incident tiles don't close up
        # (a gap - growth from a single tile can leave one deep inside the
        # patch, not just near its edge) - not a genuine type, so excluded
        canons = sorted({c for c in vert_canon.values() if c is not None}, key=repr)
        palette = make_colors(max(len(canons), 1))
        by_canon = defaultdict(list)
        for i, canon in vert_canon.items():
            if canon is not None:
                by_canon[canon].append(all_perp[i, :2])

        plot = self._plot_widget.getPlotItem()
        for item, _ in self._vertex_scatters:
            plot.removeItem(item)
        if self._legend is not None:
            self._legend.scene().removeItem(self._legend)
        self._vertex_scatters = []

        for idx, canon in enumerate(canons):
            pts = np.array(by_canon[canon])
            brush = pg.mkBrush(*[int(v) for v in palette[idx]])
            item = pg.ScatterPlotItem(pos=pts, size=5, pen=None, brush=brush)
            item.setVisible(False)
            plot.addItem(item)
            self._vertex_scatters.append((item, f"Type {idx + 1}"))

        self._legend = pg.LegendItem(offset=(10, 10), labelTextColor='#2c3e50')
        self._legend.setParentItem(plot.graphicsItem())
        for item, label in self._vertex_scatters:
            self._legend.addItem(item, label)
        self._legend.hide()

        self._colour_action.setText(f"Colour by vertex type ({len(canons)} found)")
        if self._colour_action.isChecked():
            self._show_vertex_type_view()

    def _on_vertex_types_done(self, result):
        vert_canon, all_perp = result
        self._apply_vertex_types(vert_canon, all_perp)
        self._colour_action.setEnabled(True)
        # cache onto the substitution window so reopening this window
        # without changing rules/seed/gen/start doesn't recompute
        cache = getattr(self._sub_win, '_perp_cache', None)
        if cache is not None and cache[1] is self._it:
            self._sub_win._perp_cache = (cache[0], cache[1], vert_canon, all_perp)

    def _on_vertex_types_error(self, msg):
        self._colour_action.setEnabled(True)
        self._colour_action.setText("Colour by vertex type")
        self._colour_action.setChecked(False)
        QtWidgets.QMessageBox.warning(self, "Vertex-type analysis failed", msg)


class _VectorArrowItem(pg.GraphicsObject):
    """Black arrows from the origin, same drawing technique as the main
    app's grid-vector plot (graphics.vectorPlotting): a line plus a filled
    triangular arrowhead at the tip."""

    def __init__(self, vectors, color='k', width=2, head=5.0):
        pg.GraphicsObject.__init__(self)
        self.picture = QtGui.QPicture()
        p = QtGui.QPainter(self.picture)
        if config._antialias:
            p.setRenderHint(QtGui.QPainter.Antialiasing)
        pen = pg.mkPen(color, width=width)
        pen.setCosmetic(True)
        p.setPen(pen)
        p.setBrush(pg.mkBrush(color))
        for vx, vy in vectors:
            p.drawLine(QtCore.QLineF(0, 0, vx, vy))
            bearing = np.arctan2(vy, vx)
            pts = [
                QtCore.QPointF(vx, vy),
                QtCore.QPointF(vx + head * np.cos(bearing + np.radians(150)),
                               vy + head * np.sin(bearing + np.radians(150))),
                QtCore.QPointF(vx + head * np.cos(bearing - np.radians(150)),
                               vy + head * np.sin(bearing - np.radians(150))),
            ]
            p.drawPolygon(*pts)
        p.end()
        self._br = QtCore.QRectF(self.picture.boundingRect())

    def paint(self, p, *args):
        p.drawPicture(0, 0, self.picture)

    def boundingRect(self):
        return self._br


class _VectorInset:
    """Small floating diagram, pinned to a corner of a plot widget, showing
    one set of the vertex module's basis-vector images (physical or
    perpendicular) as black arrows."""

    SIZE = 120

    def __init__(self, vecs, label, host_widget, side='left'):
        self.host = host_widget
        self.side = side
        self.widget = pg.PlotWidget(host_widget)
        self.widget.setFixedSize(self.SIZE, self.SIZE)
        self.widget.setBackground(pg.mkColor(255, 255, 255, 235))
        plot = self.widget.getPlotItem()
        plot.setAspectLocked(True)
        plot.hideAxis('bottom')
        plot.hideAxis('left')
        plot.setMouseEnabled(x=False, y=False)
        plot.setMenuEnabled(False)
        plot.hideButtons()
        plot.showGrid(x=False, y=False)
        plot.setTitle(label, size='9pt', color='#2c3e50')

        span = max(np.abs(vecs).max(), 1e-9)
        pairs = [(vecs[0, i] / span, vecs[1, i] / span) for i in range(vecs.shape[1])]
        # vectors are normalised to length <= 1 here, so the arrowhead (and
        # pen width) must be sized in that same small scale, not the pixel-
        # ish sizes that suit graphics.vectorPlotting's much longer vectors
        plot.addItem(_VectorArrowItem(pairs, width=1.5, head=0.07))
        for i, (vx, vy) in enumerate(pairs):
            bearing = np.arctan2(vy, vx) if (vx or vy) else 0.0
            txt = pg.TextItem(html=f"<span style='color:#2c3e50'>e<sub>{i}</sub></span>",
                              anchor=(0.5, 0.5))
            txt.setPos(vx + 0.16 * np.cos(bearing), vy + 0.16 * np.sin(bearing))
            plot.addItem(txt)
        plot.setXRange(-1.35, 1.35, padding=0)
        plot.setYRange(-1.35, 1.35, padding=0)

        self.widget.show()

    def set_visible(self, visible):
        self.widget.setVisible(visible)

    def reposition(self):
        margin = 8
        y = margin
        if self.side == 'left':
            x = margin
        else:
            x = self.host.width() - self.SIZE - margin
        self.widget.move(max(x, 0), y)
        self.widget.raise_()
