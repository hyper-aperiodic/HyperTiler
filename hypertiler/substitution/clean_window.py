import os
import traceback

import numpy as np
from PyQt5 import QtCore, QtGui, QtWidgets
import pyqtgraph as pg

from ..widgets import center_on_screen
from .. import config


class _AnalyseWorker(QtCore.QThread):
    """Runs inkTile.decoration_conflicts() - a read-only diagnostic, no
    relabelling - off the UI thread."""
    finished = QtCore.pyqtSignal(object)   # emits (per_child, pairs)
    error = QtCore.pyqtSignal(str)

    def __init__(self, built):
        super().__init__()
        self._built = built

    def run(self):
        try:
            self.finished.emit(self._built.decoration_conflicts())
        except Exception:
            self.error.emit(traceback.format_exc())


class _FixDecorationsWorker(QtCore.QThread):
    """Runs inkTile.fix_decorations() - the actual relabelling search,
    triggered only by the "Attempt to fix" button - off the UI thread."""
    finished = QtCore.pyqtSignal(list)
    error = QtCore.pyqtSignal(str)

    def __init__(self, built):
        super().__init__()
        self._built = built

    def run(self):
        try:
            flagged = self._built.fix_decorations()
            self.finished.emit(flagged)
        except Exception:
            self.error.emit(traceback.format_exc())


class _RulePreviewItem(pg.GraphicsObject):
    """One supertile panel: the template outline plus its children, filled
    by the colour the main view uses for that tile type, with flagged
    children outlined on top."""

    def __init__(self, template, children):
        # children: list of (coords, fill_color, outline_color, outline_width)
        pg.GraphicsObject.__init__(self)
        self.picture = QtGui.QPicture()
        p = QtGui.QPainter(self.picture)
        if config._antialias:
            p.setRenderHint(QtGui.QPainter.Antialiasing)

        def _open(coords):
            c = np.asarray(coords, dtype=float)
            return c[:-1] if len(c) > 1 and np.allclose(c[0], c[-1], atol=1e-6) else c

        fill_paths = {}
        outline_groups = {}
        for coords, fill_color, outline_color, outline_width in children:
            verts = _open(coords)
            if len(verts) < 3:
                continue
            pts = [QtCore.QPointF(float(x), float(y)) for x, y in verts]
            qc = QtGui.QColor(fill_color)
            fkey = qc.rgb()
            if fkey not in fill_paths:
                cp = QtGui.QPainterPath()
                cp.setFillRule(QtCore.Qt.WindingFill)
                fill_paths[fkey] = (qc, cp)
            fill_paths[fkey][1].addPolygon(QtGui.QPolygonF(pts))

            ekey = (outline_color, outline_width)
            ep = outline_groups.setdefault(ekey, QtGui.QPainterPath())
            n = len(pts)
            for i in range(n):
                ep.moveTo(pts[i])
                ep.lineTo(pts[(i + 1) % n])

        p.setPen(QtCore.Qt.NoPen)
        for qc, path in fill_paths.values():
            p.setBrush(pg.mkBrush(qc))
            p.drawPath(path)

        for (color, width), path in outline_groups.items():
            pen = QtGui.QPen(QtGui.QColor(color), width)
            pen.setCosmetic(True)
            p.setPen(pen)
            p.setBrush(QtCore.Qt.NoBrush)
            p.drawPath(path)

        verts = _open(template)
        tpath = QtGui.QPainterPath()
        pts = [QtCore.QPointF(float(x), float(y)) for x, y in verts]
        tpath.moveTo(pts[0])
        for pt in pts[1:] + pts[:1]:
            tpath.lineTo(pt)
        pen = QtGui.QPen(QtGui.QColor('#1a1a1a'), 2)
        pen.setCosmetic(True)
        p.setPen(pen)
        p.setBrush(QtCore.Qt.NoBrush)
        p.drawPath(tpath)

        p.end()
        self._br = QtCore.QRectF(self.picture.boundingRect())

    def paint(self, p, *args):
        p.drawPicture(0, 0, self.picture)

    def boundingRect(self):
        return self._br


class AnalyseSvgWindow(QtWidgets.QMainWindow):
    """Diagnoses a rules SVG: highlights which drawn children disagree with
    each other (decoration_conflicts - exact, read-only, nothing is
    changed just by opening this). "Attempt to fix" then searches for a
    relabelling that resolves it (fix_decorations), shows what it changed,
    and - if that's something you want to keep - "Save fixed SVG…" writes
    it back into an actual SVG file you can inspect or keep drawing from.
    """

    def __init__(self, sub_win, built):
        parent = None
        if sub_win._ui is not None:
            parent = getattr(sub_win._ui, '_main_window', None)
        super().__init__(parent)
        self._sub_win = sub_win
        self._built = built
        self._per_child = {}
        self._fixed = False
        self.setWindowTitle("Analyse SVG")
        self.resize(560, 460)
        center_on_screen(self, sub_win._plot)
        self._show_loading("Checking for decoration conflicts…")
        self.show()

        self._worker = _AnalyseWorker(built)
        self._worker.finished.connect(self._on_analysed)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _show_loading(self, text):
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        lay.addStretch()
        lbl = QtWidgets.QLabel(text)
        lbl.setAlignment(QtCore.Qt.AlignCenter)
        lay.addWidget(lbl)
        lay.addStretch()
        self.setCentralWidget(w)

    def _on_error(self, msg):
        QtWidgets.QMessageBox.warning(self, "Analysis failed", msg)
        self.close()

    # ------------------------------------------------------------------
    # step 1: analyse (read-only)
    # ------------------------------------------------------------------

    def _on_analysed(self, result):
        self._per_child, _pairs = result
        self._fixed = False
        self._build_ui()

    def _build_ui(self):
        it = self._built
        # before any fix attempt, go by the fresh per-child analysis;
        # afterwards, by fix_decorations()'s own (possibly still nonzero)
        # count, so a second "attempt to fix" stays available if the first
        # round didn't resolve everything
        n_conflicts = it.relabel_overlaps if self._fixed else sum(self._per_child.values())

        central = QtWidgets.QWidget()
        outer = QtWidgets.QVBoxLayout(central)
        outer.setContentsMargins(6, 6, 6, 6)
        outer.setSpacing(4)

        if self._fixed:
            header_text = (
                f"{it.relabel_overlaps} decoration conflict(s) remain after fixing"
                if it.relabel_overlaps else
                "Fixed: no decoration conflicts remain.")
        elif n_conflicts:
            header_text = (f"{n_conflicts} decoration conflict(s) found - "
                           f"highlighted children disagree with another copy of themselves")
        else:
            header_text = "No decoration conflicts: this rules SVG is already consistent."
        self._header = QtWidgets.QLabel(header_text)
        self._header.setWordWrap(True)
        outer.addWidget(self._header)

        legend = QtWidgets.QLabel(
            "<span style='color:#d9534f'>red</span> turned away from the drawing &nbsp; "
            "<span style='color:#f0ad4e'>orange</span> still worth checking")
        legend.setStyleSheet("font-size:8pt; color:#888;")
        outer.addWidget(legend)

        self._changes_lbl = QtWidgets.QLabel()
        self._changes_lbl.setWordWrap(True)
        self._changes_lbl.setStyleSheet("font-size:8pt; color:#2c3e50;")
        self._changes_lbl.setVisible(False)
        outer.addWidget(self._changes_lbl)

        btn_row = QtWidgets.QHBoxLayout()
        self._fix_btn = QtWidgets.QPushButton("Attempt to fix" if not self._fixed else "Attempt to fix again")
        self._fix_btn.setEnabled(bool(n_conflicts))
        self._fix_btn.clicked.connect(self._on_fix_clicked)
        btn_row.addWidget(self._fix_btn)

        self._save_btn = QtWidgets.QPushButton("Save fixed SVG…")
        self._save_btn.setEnabled(bool(it.decoration_changes()))
        self._save_btn.clicked.connect(self._on_save_clicked)
        btn_row.addWidget(self._save_btn)
        btn_row.addStretch()
        outer.addLayout(btn_row)

        grid = pg.GraphicsLayoutWidget()
        grid.setBackground('w')
        outer.addWidget(grid, 1)
        self.setCentralWidget(central)

        type_colors = self._sub_win._current_colors()

        def color_for(tile_type):
            base = tile_type.rsplit('_', 1)[0] if '_' in tile_type else tile_type
            return type_colors.get(tile_type, type_colors.get(base, '#aaaaaa'))

        relabelled = set(getattr(it, 'relabelled', {}))
        flagged_pairs = set(getattr(it, 'ambiguous_pairs', [])) if self._fixed else set()

        cols = max(1, int(np.ceil(np.sqrt(len(it.type_names)))))
        for i, t in enumerate(it.type_names):
            plot = grid.addPlot(row=i // cols, col=i % cols, title=t)
            plot.setAspectLocked(True)
            plot.hideAxis('bottom')
            plot.hideAxis('left')

            children = []
            for j, c in enumerate(it.rules.get(t, [])):
                if self._fixed:
                    pair = (t, c['type'])
                    if pair in relabelled:
                        outline = ('#d9534f', 3)
                    elif it.relabel_overlaps and pair in flagged_pairs:
                        outline = ('#f0ad4e', 3)
                    else:
                        outline = ('#333333', 0.75)
                else:
                    outline = ('#f0ad4e', 3) if self._per_child.get((t, j), 0) else ('#333333', 0.75)
                children.append((c['exact'], color_for(c['type']), *outline))
            plot.addItem(_RulePreviewItem(it.templates[t], children))

    # ------------------------------------------------------------------
    # step 2: attempt to fix (opt-in - mutates self._built.rules)
    # ------------------------------------------------------------------

    def _on_fix_clicked(self):
        self._fix_btn.setEnabled(False)
        self._fix_btn.setText("Fixing…")
        self._fix_worker = _FixDecorationsWorker(self._built)
        self._fix_worker.finished.connect(self._on_fixed)
        self._fix_worker.error.connect(self._on_error)
        self._fix_worker.start()

    def _on_fixed(self, flagged):
        it = self._built
        self._fixed = True
        self._build_ui()
        if it.relabelled:
            lines = [f"{child} inside {parent} turned {angle:g}° "
                    f"({'reflected' if reflect else 'rotated'})"
                    for (parent, child), (angle_steps, reflect) in it.relabelled.items()
                    for angle in [angle_steps * 360.0 / it.N]]
            self._changes_lbl.setText("Changed: " + "; ".join(lines))
            self._changes_lbl.setVisible(True)

    # ------------------------------------------------------------------
    # step 3: save the fix back into an SVG
    # ------------------------------------------------------------------

    def _on_save_clicked(self):
        stem, ext = os.path.splitext(self._built.svg_path)
        default = f"{stem}_fixed{ext}"
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save fixed SVG", default, "SVG files (*.svg);;All files (*)")
        if not path:
            return
        try:
            written = self._built.rewrite_svg(out_path=path)
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Save failed", str(e))
            return
        if written is None:
            QtWidgets.QMessageBox.information(
                self, "Nothing to save", "No change was actually made, so there's nothing to write.")
        else:
            QtWidgets.QMessageBox.information(
                self, "Saved", f"Wrote the fixed rules to:\n{written}")
