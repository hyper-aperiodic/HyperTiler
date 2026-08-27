import os
import traceback

from PyQt5 import QtCore, QtGui
import pyqtgraph as pg
import numpy as np
from scipy.spatial import KDTree
from .. import config

##TODO: check again with the dedups, must be a better way of removing tiny errors

def _canonical_sub(v_pos, incident_tiles, tol=0.2):
    """
    Cyclic-minimum (label, interior_angle) sequence at a substitution vertex.

    For each incident tile, the two edge-vectors from v_pos determine a sector.
    The cross product tells us which direction is interior, giving the start
    angle and angular span.  Sectors are sorted CCW, then the cyclic minimum
    rotation of (base_label, rounded_span) tuples is returned.
    """
    sectors = []
    for tile_type, coords in incident_tiles:
        coords = np.asarray(coords)
        if len(coords) > 1 and np.allclose(coords[0], coords[-1], atol=1e-6):
            coords = coords[:-1]
        dists = np.linalg.norm(coords - v_pos, axis=1)
        v_idx = int(np.argmin(dists))
        if dists[v_idx] > tol:
            continue
        n = len(coords)
        dp = coords[(v_idx - 1) % n] - v_pos   # toward prev vertex
        dn = coords[(v_idx + 1) % n] - v_pos   # toward next vertex
        cross = float(dp[0]*dn[1] - dp[1]*dn[0])
        a1 = np.arctan2(float(dp[1]), float(dp[0]))
        a2 = np.arctan2(float(dn[1]), float(dn[0]))
        # sector runs CCW from start; interior is on the left of the boundary
        if cross > 0:
            start, span = a1, a2 - a1
        else:
            start, span = a2, a1 - a2
        while span <= 0:
            span += 2 * np.pi
        base = tile_type.rsplit('_', 1)[0] if '_' in tile_type else tile_type
        sectors.append((start, round(span, 1), base))

    if not sectors:
        return None

    sectors.sort(key=lambda s: (round(s[0], 1), s[2]))
    seq = [(base, span) for _, span, base in sectors]
    n = len(seq)
    return min(tuple(seq[i:] + seq[:i]) for i in range(n))


class _SubstitutionItem(pg.GraphicsObject):
    """Renders a list of (tile_type, coords) polygons coloured by type."""

    def __init__(self, final_tiles, type_colors, edge_width=0.5):
        pg.GraphicsObject.__init__(self)
        self.picture = QtGui.QPicture()
        p = QtGui.QPainter(self.picture)
        if config._antialias:
            p.setRenderHint(QtGui.QPainter.Antialiasing)

        color_paths = {}
        edge_path = QtGui.QPainterPath()

        for tile_type, coords in final_tiles:
            base = tile_type.rsplit('_', 1)[0] if '_' in tile_type else tile_type
            color_str = type_colors.get(tile_type, type_colors.get(base, '#aaaaaa'))
            qc = QtGui.QColor(color_str)
            key = qc.rgb()
            if key not in color_paths:
                cp = QtGui.QPainterPath()
                cp.setFillRule(QtCore.Qt.WindingFill)
                color_paths[key] = (qc, cp)
            cp = color_paths[key][1]
            verts = (coords[:-1]
                     if len(coords) > 1 and np.allclose(coords[0], coords[-1])
                     else coords)
            if len(verts) < 3:
                continue
            pts = [QtCore.QPointF(float(v[0]), float(v[1])) for v in verts]
            cp.addPolygon(QtGui.QPolygonF(pts))
            n = len(pts)
            for i in range(n):
                edge_path.moveTo(pts[i])
                edge_path.lineTo(pts[(i + 1) % n])

        p.setPen(QtCore.Qt.NoPen)
        for qcolor, path in color_paths.values():
            p.setBrush(pg.mkBrush(qcolor))
            p.drawPath(path)
        if edge_width > 0:
            edge_pen = QtGui.QPen(QtCore.Qt.black, edge_width)
            edge_pen.setCosmetic(True)
            p.setPen(edge_pen)
            p.setBrush(QtCore.Qt.NoBrush)
            p.drawPath(edge_path)
        p.end()
        self._br = QtCore.QRectF(self.picture.boundingRect())

    def paint(self, p, *args):
        p.drawPicture(0, 0, self.picture)

    def boundingRect(self):
        return self._br


class _SubstitutionVertexWorker(QtCore.QThread):
    finished = QtCore.pyqtSignal(object)   # emits (all_verts, vert_type, vert_canon)
    error    = QtCore.pyqtSignal(str)

    def __init__(self, final_tiles):
        super().__init__()
        self._final_tiles = final_tiles

    def run(self):
        from collections import defaultdict
        def _open(coords):
            c = np.asarray(coords)
            return c[:-1] if len(c) > 1 and np.allclose(c[0], c[-1], atol=1e-6) else c

        all_verts = np.vstack([_open(k[1]) for k in self._final_tiles])
        
        tree = KDTree(all_verts)

        # map each global vertex index → which tiles contain it
        vert_to_tiles = defaultdict(set)
        for oi, (_, verts) in enumerate(self._final_tiles):
            _, tile_global_idx = tree.query(_open(verts))
            for j in tile_global_idx:
                vert_to_tiles[j].add(oi)

        # batch all radius queries in one call
        all_idx = tree.query_ball_point(all_verts, 0.2)

        # 60 % radius filter — drop boundary vertices like the grid worker does
        center = all_verts.mean(axis=0)
        dists = np.linalg.norm(all_verts - center, axis=1)
        r_threshold = dists.max() * 0.5

        # compute each unique cluster once, assign result to all members
        cache = {}  # rep -> (tiles, canonical)
        vert_type = {}
        vert_canon = {}
        for i, idx in enumerate(all_idx):
            if dists[i] > r_threshold:
                continue
            rep = min(idx)
            if rep not in cache:
                keep_oi = set().union(*(vert_to_tiles[j] for j in idx))
                tiles = [self._final_tiles[oi] for oi in keep_oi]
                # remove near-duplicate tiles (same type, centers within 0.05)
                # that slipped through ink2tile's remove_duplicates due to
                # floating-point boundary straddling
                dedup, seen_tc = [], []
                for t, c in tiles:
                    ctr = np.mean(_open(c), axis=0)
                    if not any(tt == t and np.linalg.norm(ctr - cc) < 0.05
                               for tt, cc in seen_tc):
                        dedup.append((t, c))
                        seen_tc.append((t, ctr))
                tiles = dedup
                canon = _canonical_sub(all_verts[i], tiles)
                cache[rep] = (tiles, canon)
            vert_type[i], vert_canon[i] = cache[rep]

        # deduplicate: keep one representative per spatial cluster so the
        # network builder sees one vertex per physical position, not ~N per tile
        seen_reps = set()
        clean_vt, clean_vc = {}, {}
        for i in sorted(vert_type.keys()):
            rep = min(all_idx[i])
            if rep in seen_reps:
                continue
            seen_reps.add(rep)
            clean_vt[i] = vert_type[i]
            clean_vc[i] = vert_canon[i]

        self.finished.emit((all_verts, clean_vt, clean_vc))


class _SubstitutionWorker(QtCore.QThread):
    finished = QtCore.pyqtSignal(list)
    error = QtCore.pyqtSignal(str)

    def __init__(self, rules_path, start_actual_key, seed_path, gen):
        super().__init__()
        self._rules_path = rules_path
        self._start = start_actual_key
        self._seed_path = seed_path
        self._gen = gen

    def run(self):
        try:
            from ..ink2tile import inkTile

            stem = os.path.splitext(self._rules_path)[0]
            kwargs = {'gen': self._gen, 'tile': stem}
            if self._seed_path:
                kwargs['seed'] = os.path.splitext(self._seed_path)[0]
            else:
                kwargs['start'] = self._start

            it = inkTile(**kwargs)
            self.finished.emit(it.final_tiles)
        except Exception:
            self.error.emit(traceback.format_exc())
