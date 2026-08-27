import os

from PyQt5 import QtCore, QtWidgets, QtGui
from PyQt5.QtCore import Qt
import pyqtgraph as pg
import numpy as np
from pyqtgraph.exporters import ImageExporter

from ..widgets import LockedViewBox
from ..config import _quality_for_count, _apply_quality
from ..ink2tile import write_svg
from .utils import parse_rules
from .worker import _SubstitutionItem, _SubstitutionWorker, _SubstitutionVertexWorker
from .vertex_window import SubstitutionVertexWindow

## a window dedicated to showing off our substitution tiles, and resultant tiling.
class SubstitutionWindow(QtWidgets.QWidget):
    """Substitution-tiling panel embedded in the main window's QStackedWidget."""

    def __init__(self, parent_ui):
        super().__init__()
        self._ui = parent_ui
        self._rules_path = None
        self._seed_path = None
        self._type_colors = {}
        self._user_colors = {}
        self._actual_start_keys = {}
        self._supertile_coords = {}
        self._final_tiles = None
        self._needs_autorange = True
        self._edge_width = 0.5
        self._worker = None
        self._vertex_worker = None
        self._vertex_window = None
        self._last_vertex_result = None
        self._expansion_factor = 1.0
        self._seed_tile_count = None
        self._setup_ui()

    def _setup_ui(self):
        h = QtWidgets.QHBoxLayout(self)
        h.setContentsMargins(8, 8, 8, 8)
        h.setSpacing(8)

        left = QtWidgets.QWidget()
        left.setFixedWidth(250)
        lv = QtWidgets.QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(4)

        lv.addWidget(QtWidgets.QLabel("Rules SVG:"))
        rules_h = QtWidgets.QHBoxLayout()
        self._rules_lbl = QtWidgets.QLabel("(none)")
        self._rules_lbl.setStyleSheet("color:#888; font-size:8pt;")
        self._rules_lbl.setWordWrap(True)
        btn_rules = QtWidgets.QPushButton("Browse…")
        btn_rules.setFixedWidth(80)
        btn_rules.clicked.connect(self._browse_rules)
        rules_h.addWidget(self._rules_lbl, 1)
        rules_h.addWidget(btn_rules)
        lv.addLayout(rules_h)

        self._preview_area = QtWidgets.QScrollArea()
        self._preview_area.setWidgetResizable(True)
        self._preview_area.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self._preview_area.setFixedHeight(330)
        pw = QtWidgets.QWidget()
        self._preview_grid = QtWidgets.QGridLayout(pw)
        self._preview_grid.setSpacing(8)
        self._preview_grid.setContentsMargins(4, 4, 4, 4)
        self._preview_area.setWidget(pw)
        lv.addWidget(self._preview_area)

        lv.addSpacing(4)

        seed_box = QtWidgets.QGroupBox("Seed")
        sv = QtWidgets.QVBoxLayout(seed_box)
        sv.setSpacing(4)

        self._rb_type = QtWidgets.QRadioButton("Single tile:")
        self._rb_type.setChecked(True)
        type_h = QtWidgets.QHBoxLayout()
        type_h.addWidget(self._rb_type)
        self._seed_combo = QtWidgets.QComboBox()
        type_h.addWidget(self._seed_combo, 1)
        sv.addLayout(type_h)

        self._rb_seed = QtWidgets.QRadioButton("From SVG:")
        seed_svg_h = QtWidgets.QHBoxLayout()
        seed_svg_h.addWidget(self._rb_seed)
        self._seed_svg_lbl = QtWidgets.QLabel("(none)")
        self._seed_svg_lbl.setStyleSheet("color:#888; font-size:8pt;")
        btn_seed = QtWidgets.QPushButton("Browse…")
        btn_seed.setFixedWidth(80)
        btn_seed.clicked.connect(self._browse_seed)
        seed_svg_h.addWidget(self._seed_svg_lbl, 1)
        seed_svg_h.addWidget(btn_seed)
        sv.addLayout(seed_svg_h)

        self._rb_type.toggled.connect(self._sync_seed_controls)
        lv.addWidget(seed_box)

        lv.addSpacing(4)
        gen_h = QtWidgets.QHBoxLayout()
        gen_h.addWidget(QtWidgets.QLabel("Generations:"))
        self._gen_spin = QtWidgets.QSpinBox()
        self._gen_spin.setRange(1, 10)
        self._gen_spin.setValue(3)
        gen_h.addWidget(self._gen_spin)
        gen_h.addStretch()
        lv.addLayout(gen_h)

        lv.addSpacing(4)
        self._gen_btn = QtWidgets.QPushButton("Generate")
        self._gen_btn.clicked.connect(self._generate)
        lv.addWidget(self._gen_btn)

        self._style_widget = QtWidgets.QWidget()
        sv2 = QtWidgets.QVBoxLayout(self._style_widget)
        sv2.setContentsMargins(0, 6, 0, 0)
        sv2.setSpacing(4)

        sep = QtWidgets.QFrame()
        sep.setFrameShape(QtWidgets.QFrame.HLine)
        sep.setFrameShadow(QtWidgets.QFrame.Sunken)
        sv2.addWidget(sep)

        sv2.addWidget(QtWidgets.QLabel("Colours (click to change):"))
        self._colour_area = QtWidgets.QScrollArea()
        self._colour_area.setWidgetResizable(True)
        self._colour_area.setFrameShape(QtWidgets.QFrame.NoFrame)
        self._colour_area.setFixedHeight(80)
        cw = QtWidgets.QWidget()
        self._colour_h = QtWidgets.QHBoxLayout(cw)
        self._colour_h.setSpacing(6)
        self._colour_h.addStretch()
        self._colour_area.setWidget(cw)
        sv2.addWidget(self._colour_area)

        ew_h = QtWidgets.QHBoxLayout()
        ew_h.addWidget(QtWidgets.QLabel("Edge width:"))
        self._ew_spin = QtWidgets.QDoubleSpinBox()
        self._ew_spin.setRange(0.0, 10.0)
        self._ew_spin.setSingleStep(0.25)
        self._ew_spin.setDecimals(2)
        self._ew_spin.valueChanged.connect(self._on_edge_width_changed)
        self._ew_spin.setValue(0.5)
        ew_h.addWidget(self._ew_spin)
        ew_h.addStretch()
        sv2.addLayout(ew_h)

        self._save_as_btn = QtWidgets.QPushButton("Save as...")
        self._save_as_btn.clicked.connect(self._save_as_image)
        sv2.addWidget(self._save_as_btn)

        lv.addWidget(self._style_widget)
        self._style_widget.setVisible(False)

        lv.addStretch()

        self._progress = QtWidgets.QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setTextVisible(False)
        self._progress.setFixedHeight(6)
        self._progress.setVisible(False)
        lv.addWidget(self._progress)

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
        h.addWidget(self._plot, 1)

        self._sync_seed_controls()

    # ------------------------------------------------------------------
    # file pickers
    # ------------------------------------------------------------------

    def _browse_rules(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Open rules SVG", "", "SVG files (*.svg);;All files (*)")
        if path:
            self._load_rules_from_path(path)

    def _load_rules_from_path(self, path):
        try:
            QtWidgets.QApplication.setOverrideCursor(Qt.WaitCursor)
            actual_keys, type_colors, supertile_coords = parse_rules(path)
        except Exception as e:
            QtWidgets.QApplication.restoreOverrideCursor()
            self._status_lbl.setText(f"Load error: {e}")
            return
        QtWidgets.QApplication.restoreOverrideCursor()

        actual_keys = {key: value for key, value in sorted(actual_keys.items())}

        self._rules_path = path
        self._actual_start_keys = actual_keys
        self._type_colors = type_colors
        self._supertile_coords = supertile_coords
        self._user_colors = {}
        self._rules_lbl.setText(os.path.basename(path))
        self._rules_lbl.setStyleSheet("font-size:8pt;")
        self._rebuild_preview_swatches()
        self._seed_combo.clear()
        
        for display_name in actual_keys:
            self._seed_combo.addItem(display_name)

        try:
            from .. import ink2tile as _m
            self._expansion_factor = 1.0 / (_m.globalScale ** 2)
        except Exception:
            self._expansion_factor = 1.0

        self._status_lbl.setText(
            f"{len(actual_keys)} tile type(s): {', '.join(actual_keys)}")

    def _browse_seed(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Open seed SVG", "", "SVG files (*.svg);;All files (*)")
        if not path:
            return
        self._seed_path = path
        self._seed_svg_lbl.setText(os.path.basename(path))
        self._seed_svg_lbl.setStyleSheet("font-size:8pt;")
        self._rb_seed.setChecked(True)
        try:
            from ..ink2tile import inkTile
            stem = os.path.splitext(self._rules_path)[0]
            seed_stem = os.path.splitext(path)[0]
            it = inkTile(gen=0, tile=stem, seed=seed_stem)
            self._seed_tile_count = len(it.final_tiles)
        except Exception:
            self._seed_tile_count = None

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _sync_seed_controls(self):
        tile_mode = self._rb_type.isChecked()
        self._seed_combo.setEnabled(tile_mode)
        self._seed_svg_lbl.setEnabled(not tile_mode)

    def _current_colors(self):
        merged = dict(self._type_colors)
        merged.update(self._user_colors)
        return merged

    def _rebuild_preview_swatches(self, chnge = False):
        while self._preview_grid.count():
            item = self._preview_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        SZ = 100
        for idx, (t, coords) in enumerate(sorted(self._supertile_coords.items())):

            if chnge:
                color_str = self._current_colors().get(t, '#aaaaaa')
                            
            else:
                color_str = self._type_colors.get(t, '#aaaaaa')
                
            qc = QtGui.QColor(color_str)

            pixmap = QtGui.QPixmap(SZ, SZ)
            pixmap.fill(QtCore.Qt.white)

            xs, ys = coords[:, 0], coords[:, 1]
            w_data = xs.max() - xs.min()
            h_data = ys.max() - ys.min()
            span = max(w_data, h_data)
            if span < 1e-9:
                continue
            pad = 0.12
            scale = SZ / (span * (1 + 2 * pad))
            cx = SZ / 2 - (xs.mean()) * scale
            cy = SZ / 2 - (ys.mean()) * scale
            pts = [QtCore.QPointF(x * scale + cx, y * scale + cy) for x, y in coords]

            painter = QtGui.QPainter(pixmap)
            painter.setRenderHint(QtGui.QPainter.Antialiasing)
            painter.setBrush(pg.mkBrush(qc))
            painter.setPen(QtGui.QPen(QtCore.Qt.black, 1.2))
            painter.drawPolygon(QtGui.QPolygonF(pts))
            painter.end()

            cell = QtWidgets.QWidget()
            cl = QtWidgets.QVBoxLayout(cell)
            cl.setContentsMargins(2, 2, 2, 2)
            cl.setSpacing(2)
            img_lbl = QtWidgets.QLabel()
            img_lbl.setFixedSize(SZ, SZ)
            img_lbl.setPixmap(pixmap)
            txt_lbl = QtWidgets.QLabel(t)
            txt_lbl.setAlignment(Qt.AlignCenter)
            txt_lbl.setStyleSheet("font-size:14pt;")
            txt_lbl.setSizePolicy(QtWidgets.QSizePolicy.Preferred,
                                   QtWidgets.QSizePolicy.Fixed)
            cl.addWidget(img_lbl)
            cl.addWidget(txt_lbl)
            row, col = divmod(idx, 2)
            self._preview_grid.addWidget(cell, row, col)

    def _rebuild_colour_swatches(self):
        while self._colour_h.count() > 1:
            item = self._colour_h.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        colors = self._current_colors()
        colors = {key: value for key, value in sorted(colors.items())}

        
        for t, color_str in colors.items():
            w = QtWidgets.QWidget()
            wl = QtWidgets.QVBoxLayout(w)
            wl.setContentsMargins(2, 2, 2, 2)
            wl.setSpacing(1)
            btn = QtWidgets.QPushButton()
            btn.setFixedSize(26, 26)
            qc = QtGui.QColor(color_str)
            btn.setStyleSheet(
                f"background:{qc.name()}; border:1px solid #555; border-radius:3px;")
            btn.clicked.connect(lambda _checked, name=t: self._on_swatch_click(name))
            lbl = QtWidgets.QLabel(t)
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setStyleSheet("font-size:14pt;")
            wl.addWidget(btn, alignment=Qt.AlignCenter)
            wl.addWidget(lbl)
            self._colour_h.insertWidget(self._colour_h.count() - 1, w)
        

    def _on_swatch_click(self, type_name):
        colors = self._current_colors()
        original = colors.get(type_name, '#aaaaaa')
        initial = QtGui.QColor(original)
        dlg = QtWidgets.QColorDialog(initial, self)
        dlg.setOption(QtWidgets.QColorDialog.DontUseNativeDialog, True)
        for w in dlg.findChildren(QtWidgets.QLabel):
            if 'ustom' in w.text():
                w.hide()
        for w in dlg.findChildren(QtWidgets.QPushButton):
            if 'ustom' in w.text():
                w.hide()
        wells = [w for w in dlg.findChildren(QtWidgets.QWidget)
                 if w.metaObject().className() == 'QWellArray']
        if len(wells) >= 2:
            wells[-1].hide()
        dlg.currentColorChanged.connect(
            lambda c, n=type_name: self._apply_live_color(n, c.name()))
        if dlg.exec_() == QtWidgets.QDialog.Accepted:
            self._user_colors[type_name] = dlg.selectedColor().name()
        else:
            self._user_colors[type_name] = original
        self._rebuild_colour_swatches()
        self._rebuild_plot_item()

    def _apply_live_color(self, type_name, color_str):
        self._user_colors[type_name] = color_str
        self._rebuild_colour_swatches()
        self._rebuild_plot_item()
        self._rebuild_preview_swatches(chnge = True)

    def _on_edge_width_changed(self, val):
        self._edge_width = val
        self._rebuild_plot_item()

    def _save_as_image(self):
        if self._final_tiles is None:
            return
        path, selected_filter = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save Tiling", "", "PNG Image (*.png);;SVG Image (*.svg)")
        if not path:
            return
        if selected_filter.endswith('(*.svg)') or path.lower().endswith('.svg'):
            if not path.endswith('.svg'):
                path += '.svg'
            type_colors = self._current_colors()
            polys, colors = [], []
            for tile_type, coords in self._final_tiles:
                base = tile_type.rsplit('_', 1)[0] if '_' in tile_type else tile_type
                color_str = type_colors.get(tile_type, type_colors.get(base, '#aaaaaa'))
                qc = QtGui.QColor(color_str)
                verts = (coords[:-1]
                         if len(coords) > 1 and np.allclose(coords[0], coords[-1])
                         else coords)
                polys.append(verts)
                colors.append((qc.red(), qc.green(), qc.blue()))
            # _edge_width is a cosmetic (screen-pixel) pen width; convert to
            # data-unit space via the view's current data-units-per-pixel so
            # the exported stroke matches what's shown on screen.
            px_w, _ = self._plot.getViewBox().viewPixelSize()
            write_svg(path, polys, colors, (0, 0, 0), self._edge_width * px_w)
            return
        if not path.endswith('.png'):
            path += '.png'
        exporter = ImageExporter(self._plot.plotItem)
        exporter.parameters()['width'] = 1000
        exporter.export(path)

    def _rebuild_plot_item(self):
        if self._final_tiles is None:
            return
        vb = self._plot.getViewBox()
        ax, ay = vb.autoRangeEnabled()
        saved = None if (self._needs_autorange or (ax and ay)) else vb.viewRange()
        self._needs_autorange = False
        self._plot.clear()
        self._plot.addItem(
            _SubstitutionItem(self._final_tiles, self._current_colors(),
                              self._edge_width))
        if saved:
            vb.setRange(xRange=saved[0], yRange=saved[1], padding=0)
        else:
            self._plot.enableAutoRange()

    # ------------------------------------------------------------------
    # vertex finder
    # ------------------------------------------------------------------

    def _show_vertices(self, silent=False):
        if self._final_tiles is None:
            return
        if self._vertex_worker is not None and self._vertex_worker.isRunning():
            return
        if not silent:
            if self._vertex_window is not None:
                self._vertex_window.close()
            self._vertex_window = SubstitutionVertexWindow(self)
        self._vertex_worker = _SubstitutionVertexWorker(self._final_tiles)
        self._vertex_worker.finished.connect(self._on_vertices_done)
        self._vertex_worker.error.connect(
            lambda msg: self._status_lbl.setText(f"Vertex error: {msg}"))
        self._status_lbl.setText("Computing vertex types…")
        self._vertex_worker.start()

    def _on_vertices_done(self, result):
        self._last_vertex_result = result
        if self._vertex_window is not None:
            self._vertex_window.build_display(result)
        _, _, vert_canon = result
        n_types = len({v for v in vert_canon.values() if v is not None})
        self._status_lbl.setText(f"{n_types} vertex type(s) found")
        if self._ui is not None:
            self._refresh_network_builder()

    def _refresh_network_builder(self):
        if self._last_vertex_result is None:
            return
        nw = getattr(self._ui, 'network_window', None)
        if nw is None or not nw.isVisible():
            return
        all_verts, _, vert_canon = self._last_vertex_result
        from collections import defaultdict
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
        self._ui._populate_from_substitution()
        type_map = {c: list(idxs) for c, idxs in canon_to_indices.items()}
        idx_to_vert = {i: all_verts[i] for idxs in canon_to_indices.values() for i in idxs}
        nw.refresh_sub(type_map, idx_to_vert)

    # ------------------------------------------------------------------
    # generation
    # ------------------------------------------------------------------

    def _generate(self):
        if not self._rules_path:
            self._status_lbl.setText("Load a rules SVG first.")
            return
        if self._rb_type.isChecked() and not self._seed_combo.currentText():
            self._status_lbl.setText("No tile types found.")
            return
        if self._rb_seed.isChecked() and not self._seed_path:
            self._status_lbl.setText("Choose a seed SVG.")
            return
        if self._worker is not None and self._worker.isRunning():
            return

        gen = self._gen_spin.value()

        # estimate output tile count and adjust rendering quality
        n_initial = (self._seed_tile_count or 1) if self._rb_seed.isChecked() else 1
        est = int(n_initial * (self._expansion_factor ** gen))
        quality = _quality_for_count(est)
        _apply_quality(self._plot, quality)

        self._gen_btn.setEnabled(False)
        self._progress.setVisible(True)

        if est > 10000:
            self._status_lbl.setText(
                f"Generating… (~{est:,} tiles expected, quality: {quality})")
        else:
            self._status_lbl.setText(f"Generating gen {gen}…" if gen >= 4 else "Generating…")

        display = self._seed_combo.currentText() if self._rb_type.isChecked() else None
        start_actual = self._actual_start_keys.get(display) if display else None
        seed_path = self._seed_path if self._rb_seed.isChecked() else None

        self._worker = _SubstitutionWorker(
            self._rules_path, start_actual, seed_path, gen)
        self._worker.finished.connect(self._on_done)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_done(self, final_tiles):
        self._gen_btn.setEnabled(True)
        self._progress.setVisible(False)
        self._final_tiles = final_tiles
        self._needs_autorange = True

        self._style_widget.setVisible(True)
        self._rebuild_colour_swatches()
        self._rebuild_plot_item()

        self._status_lbl.setText(
            f"{len(final_tiles)} tiles, {self._gen_spin.value()} gen(s)")

        vw_open = self._vertex_window is not None and self._vertex_window.isVisible()
        nw_open = (self._ui is not None
                   and getattr(self._ui, 'network_window', None) is not None
                   and self._ui.network_window.isVisible())
        if vw_open or nw_open:
            self._show_vertices(silent=not vw_open)

    def _on_error(self, msg):
        self._gen_btn.setEnabled(True)
        self._progress.setVisible(False)
        self._status_lbl.setText("Generation failed.")
        QtWidgets.QMessageBox.warning(self, "Substitution failed", msg)
