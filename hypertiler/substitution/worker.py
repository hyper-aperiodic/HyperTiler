import os
import traceback

from PyQt5 import QtCore, QtGui
import pyqtgraph as pg
import numpy as np
from scipy.spatial import KDTree
from scipy import ndimage
from .. import config

##TODO: check again with the dedups, must be a better way of removing tiny errors

def _canonical_sub(v_pos, incident_tiles, tol=0.2, gap_tol=0.3):
    """
    Cyclic-minimum (label, interior_angle) sequence at a substitution vertex.

    For each incident tile, the two edge-vectors from v_pos determine a sector.
    The cross product tells us which direction is interior, giving the start
    angle and angular span.  Sectors are sorted CCW, then the cyclic minimum
    rotation of (base_label, rounded_span) tuples is returned.

    A genuine interior vertex has its sectors sum to exactly 2*pi - growing
    from a single starting tile (rather than symmetrised over every
    rotation) can naturally leave a vertex with a tile missing from one
    side, deep inside the patch, not just near its outer edge (where
    _interior_mask's erosion already excludes incomplete vertices). Such a
    vertex isn't a real "type" - it's an artefact of where growth happened
    to stop - so returns None here too, same as finding no sectors at all.
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

    if abs(sum(s[1] for s in sectors) - 2 * np.pi) > gap_tol:
        return None             # a gap (or overlap): a tile is missing/doubled here

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


def _open(coords):
    c = np.asarray(coords)
    return c[:-1] if len(c) > 1 and np.allclose(c[0], c[-1], atol=1e-6) else c


def _typical_spacing(points, k=6):
    """Median distance from each point to its nearest genuinely-distinct
    neighbour (skipping near-zero distances, since `points` here is full
    of exact duplicates - the same physical vertex listed once per
    incident tile). A scale-appropriate stand-in for "one tile edge"."""
    if len(points) < 2:
        return 1.0
    tree = KDTree(points)
    d, _ = tree.query(points, k=min(k, len(points)))
    nn = [row[row > 1e-6][0] for row in np.atleast_2d(d) if np.any(row > 1e-6)]
    return float(np.median(nn)) if nn else 1.0


def _interior_mask(points, margin_edges=2.5, cell_frac=0.6):
    """Which points lie safely inside the point cloud's own footprint,
    after shrinking its boundary inward by about `margin_edges` tile
    edges - rasterise the footprint, erode it by that many grid cells,
    and keep whatever's still inside. Unlike a single fixed radius from
    the centroid, this follows the actual (possibly concave, possibly
    anisotropic - a long thin patch, an irregular seed growth) shape of
    the generated tiling, rather than assuming it's roughly circular."""
    n = len(points)
    if n < 4:
        return np.ones(n, dtype=bool)
    L = _typical_spacing(points)
    cell = max(L * cell_frac, 1e-9)
    margin_cells = max(int(round(margin_edges / cell_frac)), 1)

    lo = points.min(axis=0) - cell
    hi = points.max(axis=0) + cell
    nx = max(int(np.ceil((hi[0] - lo[0]) / cell)), 1)
    ny = max(int(np.ceil((hi[1] - lo[1]) / cell)), 1)
    # cap the grid so a huge/very fine patch can't blow up memory
    if nx * ny > 4_000_000:
        return np.ones(n, dtype=bool)
    ix = np.clip(((points[:, 0] - lo[0]) / cell).astype(int), 0, nx - 1)
    iy = np.clip(((points[:, 1] - lo[1]) / cell).astype(int), 0, ny - 1)

    occ = np.zeros((ny, nx), dtype=bool)
    occ[iy, ix] = True
    # close up small gaps between same-tiling cells before eroding, so the
    # margin is measured from the tiling's true outer edge, not from gaps
    # between individual vertices within it
    occ = ndimage.binary_closing(occ, iterations=2)
    eroded = ndimage.binary_erosion(occ, iterations=margin_cells)
    return eroded[iy, ix]


def compute_vertex_types(final_tiles):
    """Canonical vertex-type analysis shared by the vertex-finder window and
    the perp-space window's "colour by vertex type" action. Returns
    (all_verts, vert_type, vert_canon): all_verts is (N, 2), one row per
    vertex of every tile in `final_tiles` IN THE SAME ORDER (so index i
    here lines up with the i-th vertex when final_tiles is walked in
    order - e.g. against inkTile.perp_coords()); vert_type/vert_canon map
    a subset of those indices (one per distinct physical position, interior
    only) to its incident tiles and canonical signature."""
    from collections import defaultdict

    all_verts = np.vstack([_open(k[1]) for k in final_tiles])

    tree = KDTree(all_verts)

    # map each global vertex index → which tiles contain it
    vert_to_tiles = defaultdict(set)
    for oi, (_, verts) in enumerate(final_tiles):
        _, tile_global_idx = tree.query(_open(verts))
        for j in tile_global_idx:
            vert_to_tiles[j].add(oi)

    # batch all radius queries in one call
    all_idx = tree.query_ball_point(all_verts, 0.2)

    # drop vertices near the edge of the generated patch - their local
    # neighbourhood is truncated (tiles that would exist in an infinite
    # tiling are simply missing), so their "vertex type" would be wrong.
    # Follows the patch's actual footprint (shrunk inward by a couple of
    # tile edges) rather than assuming it's roughly circular, which fails
    # badly for an anisotropic (long/thin, irregular seed-grown) patch.
    interior = _interior_mask(all_verts)

    # compute each unique cluster once, assign result to all members
    cache = {}  # rep -> (tiles, canonical)
    vert_type = {}
    vert_canon = {}
    for i, idx in enumerate(all_idx):
        if not interior[i]:
            continue
        rep = min(idx)
        if rep not in cache:
            keep_oi = set().union(*(vert_to_tiles[j] for j in idx))
            tiles = [final_tiles[oi] for oi in keep_oi]
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

    return all_verts, clean_vt, clean_vc


class _SubstitutionVertexWorker(QtCore.QThread):
    finished = QtCore.pyqtSignal(object)   # emits (all_verts, vert_type, vert_canon)
    error    = QtCore.pyqtSignal(str)

    def __init__(self, final_tiles):
        super().__init__()
        self._final_tiles = final_tiles

    def run(self):
        self.finished.emit(compute_vertex_types(self._final_tiles))


class _SubstitutionWorker(QtCore.QThread):
    # emits (final_tiles, built_inkTile) - built_inkTile is the (possibly
    # freshly-built) inkTile instance, cheap to re-generate() from on a
    # later call since it already carries the corrected rules.
    finished = QtCore.pyqtSignal(list, object)
    error = QtCore.pyqtSignal(str)

    def __init__(self, rules_path, start_actual_key, seed_path, gen, built=None):
        super().__init__()
        self._rules_path = rules_path
        self._start = start_actual_key
        self._seed_path = seed_path
        self._gen = gen
        self._built = built

    def run(self):
        try:
            if self._built is not None:
                # rules/seed unchanged since the last build - skip straight
                # to generation, which is cheap; correction isn't repeated.
                self._built.generate(self._gen, self._start)
                self.finished.emit(self._built.final_tiles, self._built)
                return

            from ..ink2tile import inkTile

            stem = os.path.splitext(self._rules_path)[0]
            kwargs = {'gen': self._gen, 'tile': stem}
            if self._seed_path:
                kwargs['seed'] = os.path.splitext(self._seed_path)[0]
            else:
                kwargs['start'] = self._start

            it = inkTile(**kwargs)
            self.finished.emit(it.final_tiles, it)
        except Exception:
            self.error.emit(traceback.format_exc())


class _PerpSpaceWorker(QtCore.QThread):
    """Builds an inkTile with perp=True for the current rules/seed/start/gen
    and emits it, so the caller can read its final_tiles, indices and
    perp_coords()."""
    finished = QtCore.pyqtSignal(object)
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
            kwargs = {'gen': self._gen, 'tile': stem, 'perp': True}
            if self._seed_path:
                kwargs['seed'] = os.path.splitext(self._seed_path)[0]
            else:
                kwargs['start'] = self._start

            it = inkTile(**kwargs)
            self.finished.emit(it)
        except Exception:
            self.error.emit(traceback.format_exc())


class _PerpVertexTypesWorker(QtCore.QThread):
    """Vertex-type analysis for an already-built perp=True inkTile, plus the
    matching per-vertex perpendicular-space coordinate - the "colour by
    vertex type" action in the perp-space window. final_tiles and
    perp_coords() are built from the same (type, g, x) hyperspace arrays in
    the same order, so concatenating them the same way lines up index for
    index with compute_vertex_types()'s own all_verts."""
    finished = QtCore.pyqtSignal(object)   # emits (vert_canon, all_perp)
    error = QtCore.pyqtSignal(str)

    def __init__(self, built):
        super().__init__()
        self._built = built

    def run(self):
        try:
            it = self._built
            _, _, vert_canon = compute_vertex_types(it.final_tiles)
            all_perp = np.vstack([_open(p) for p in it.perp_coords()])
            self.finished.emit((vert_canon, all_perp))
        except Exception:
            self.error.emit(traceback.format_exc())
