import numpy as np
import itertools
import math
from scipy.spatial.distance import _distance_wrap


class Grids:
    def __init__(self, vectors, line_len, grid_len, shifts, val):
        self.grid_vectors = vectors
        self.line_len = line_len
        self.grid_len = grid_len * 2
        self.shifts = shifts
        self.val = val
        self.angles = [math.atan2(v[1], v[0]) for v in vectors]
        self.grids, self.index, self.midpoints = self._generate(
            vectors, line_len, grid_len, shifts)
        self.idx_min = np.min(self.index)
        self.idx_max = np.max(self.index)

    @staticmethod
    def _perp(v):
        return (v[1], -v[0])

    def _generate(self, vectors, line_len, grid_len, shifts):
        """Create the endpoints of the 'infinite' grid lines, and 
        apply the relevant shifts to each family.
        
        Label each grid line with the correct index, and calculate its midpoint."""


        store, indices, midpoints = [], [], []
        idx = list(range(-grid_len, grid_len))
        n = grid_len * 2
        for a, vec in enumerate(vectors):
            pvec = self._perp(vec)
            cx = (n / 2) * vec[0]
            cy = (n / 2) * vec[1]
            s = shifts[a]
            p1 = [((x + s) * vec[0] - cx + pvec[0] * line_len,
                   (x + s) * vec[1] - cy + pvec[1] * line_len) for x in range(n)]
            p2 = [((x + s) * vec[0] - cx - pvec[0] * line_len,
                   (x + s) * vec[1] - cy - pvec[1] * line_len) for x in range(n)]
            mid = np.array([(p1[x][0] + vec[0] / 2, p1[x][1] + vec[1] / 2) for x in range(n)])
            store.append([p1, p2])
            indices.append([idx[x] for x in range(n)])
            midpoints.append(mid)
        return store, indices, midpoints


class TileMaker:
    def __init__(self, vector_data, grid_len, dedupe=True):
        """Build a de Bruijn dual-grid tiling from a set of grid vectors.

        Parameters
        ----------
        vector_data : array_like, shape (N, 4)
            One row per grid vector: (tile_length, grid_length,
            angle_degrees, shift). :func:`hypertiler.regular_vectors` builds
            this array for the common regular-star case; see its docstring
            for the shift convention.
        grid_len : int
            Number of lines each grid family contains - controls the
            physical size/density of the resulting tiling.
        dedupe : bool, default True
            Collapse grid vectors that describe the same infinite line
            family twice (see `_dedupe_vectors`). This only compares grid
            geometry (angle + shift), not `tile_length` - so if two
            "duplicate" vectors were deliberately given different
            `tile_length`s, dedup keeps whichever has the lower index and
            silently discards the other's tile_length along with it. Pass
            False while a vector set is being hand-edited (e.g. the
            Advanced panel is open) so every row the user typed stays a
            genuinely independent vector, at the cost of the degenerate
            zero-area tiles dedup normally exists to avoid for exact
            duplicates.

        Attributes
        ----------
        points : list of (M, 2) ndarray
            Quadrilateral tile polygons.
        p_points : list of (M, 2) ndarray
            Higher-order (n-gon) tile polygons, from singular multi-line
            crossings.
        poly_areas : ndarray
            Raw area of each polygon in `points`, in the same order. Tiles
            that share a "type" share (near-)identical area - see
            :func:`hypertiler.classify_areas`.
        ngon_areas : ndarray
            Raw area of each polygon in `p_points`, in the same order.
        grid : Grids
            The underlying grid-line construction (line endpoints, indices,
            midpoints) this tiling was built from.
        """
        grid, tile_vectors = self.build_grid(vector_data, grid_len, dedupe=dedupe)
        self.grid = grid
        ##send everything off to create out tiles!
        self.points, self.p_points, self.poly_areas, self.ngon_areas = \
            self._make_tile(grid, tile_vectors)

        # cut-and-project perpendicular-space embedding, for PerpSpaceWindow -
        # mirrors inkTile's self.basis/self.perp/self.r/self.d, but simpler:
        # no symmetry-group alignment or contraction eigenvalue (dual-grid
        # tilings have no inflation to align to). Built lazily (see the
        # properties below) - every ordinary "Tile!"/live-edit regenerate
        # goes through this constructor, including transient, half-edited
        # vector sets while the user is still typing, and this computation
        # can legitimately fail on a degenerate set; it must never be able
        # to break normal tiling generation just because nothing asked for
        # perp space yet.
        self.tile_vectors = tile_vectors
        self._perp_built = False
        self.contraction = None

    def _ensure_perp(self):
        if self._perp_built:
            return
        self._r = self.tile_vectors.shape[0]
        self._basis = self.tile_vectors.T                # (2, r)
        self._d = self._r - 2
        self._perp = self._build_perp(self._basis)        # (d, r)
        self._perp_built = True

    @property
    def r(self):
        self._ensure_perp()
        return self._r

    @property
    def d(self):
        self._ensure_perp()
        return self._d

    @property
    def basis(self):
        self._ensure_perp()
        return self._basis

    @property
    def perp(self):
        self._ensure_perp()
        return self._perp

    @staticmethod
    def _build_perp(basis):
        """Perpendicular-space embedding, cut-and-project literature
        convention: physical space uses frequency m=1 (each grid vector at
        its own angle); perp space uses the *other* rotation harmonics
        m=2,3,... of those same vectors (same magnitude, just rotated to m
        times the angle). A harmonic m only gives a genuine, non-degenerate
        rotated copy of the full star when gcd(m, r) == 1 (a true
        automorphism of the index cycle - e.g. for the octagonal case
        r=8, m=3 retraces all 8 points; m=2 does not: cos/sin(2*theta_k)
        repeats every 4 steps, so it only ever traces a square, the same
        4 points twice over) - those are tried first, so the first two
        rows (what the "basis vectors" inset plots) are always a clean,
        representative rotated star. Only once genuine conjugates run out
        does the sweep fall back to the remaining (necessarily degenerate
        for a cyclic index of composite order) harmonics, and finally the
        1-D leftovers (m=0's constant direction, and m=r/2's alternating
        +/- direction when r is even) needed to fill out the full rank
        d = r - 2. Gram-Schmidt against basis and previously accepted rows
        only drops dependent candidates (e.g. m and r-m give the same real
        row space, and the m=0 sine row is identically zero) and fixes up
        rounding, never blends frequencies together."""
        r = basis.shape[1]
        d = r - 2
        if d <= 0:
            return np.zeros((0, r))
        mags = np.linalg.norm(basis, axis=0)
        angles = np.arctan2(basis[1], basis[0])

        refs = [row / np.linalg.norm(row) for row in basis]
        perp_rows = []

        def _try_accept(cand):
            if len(perp_rows) >= d:
                return
            for ref in refs:
                cand = cand - (cand @ ref) * ref
            n = np.linalg.norm(cand)
            if n > 1e-9:
                cand = cand / n
                perp_rows.append(cand)
                refs.append(cand)

        from math import gcd
        harmonics = sorted(range(2, r), key=lambda m: (gcd(m, r) != 1, m))
        for m in harmonics:
            if len(perp_rows) >= d:
                break
            _try_accept(mags * np.cos(m * angles))
            _try_accept(mags * np.sin(m * angles))

        for m in (0, r / 2 if r % 2 == 0 else None):
            if m is None or len(perp_rows) >= d:
                continue
            _try_accept(mags * np.cos(m * angles))
            _try_accept(mags * np.sin(m * angles))
        if len(perp_rows) < d:
            raise ValueError(
                "could not build a perpendicular-space basis for this "
                "vector set (degenerate grid vectors?)")
        return np.array(perp_rows)

    def perp_coords(self):
        """Perpendicular-space coordinates of every tile vertex, one (n, d)
        array per tile - same layout/order as self.points + self.p_points,
        mirroring inkTile.perp_coords()."""
        n_polys = len(self.points)
        tiles = list(self.raw_indices[:n_polys])
        if len(self.raw_indices) > n_polys:
            tiles += list(self.raw_indices[n_polys])
        return [np.asarray(t) @ self.perp.T for t in tiles]

    @classmethod
    def build_grid(cls, vector_data, grid_len, dedupe=True):
        """Just the grid-line construction (dedupe + sort + Grids), with no
        tile/intersection computation at all. """
        tile_vectors, grid_vectors, shifts = [], [], []
        for row in vector_data:
            angle_rad = np.radians(row[2])
            tile_vectors.append((row[0] * np.cos(angle_rad), row[0] * np.sin(angle_rad)))
            grid_vectors.append((row[1] * np.cos(angle_rad), row[1] * np.sin(angle_rad)))
            shifts.append(row[3])

        if dedupe:
            grid_vectors, tile_vectors, shifts = cls._dedupe_vectors(
                grid_vectors, tile_vectors, shifts)

        ang = [math.atan2(v[1], v[0]) for v in grid_vectors]
        val = (np.round(ang, 2) >= 0).sum()
        ang = [(a + 2 * np.pi if np.round(a, 2) < 0 else a) for a in ang]
        order = np.argsort(ang)
        grid_vectors = np.array(grid_vectors)[order]
        tile_vectors = np.array(tile_vectors)[order]
        return Grids(grid_vectors, 1000, grid_len, shifts, val), tile_vectors

    @staticmethod
    def _dedupe_vectors(grid_vectors, tile_vectors, shifts, tol=1e-6):
        """Some vector sets describe the same infinite line family more than
        once - e.g. an 8-vector set at zero shift is really just 4 true
        directions, each listed twice . A family's line
        at label L sits at scalar offset (L + shift) along its own vector,
        so two families are exact duplicates when they're parallel with
        matching shift (mod 1), or antiparallel with shifts summing to an
        integer.

        Keeping a redundant duplicate forces the intersection code to treat
        every ordinary crossing as if an extra grid meets there too,
        producing degenerate zero-area tiles and fake high-vertex-count
        n-gons for what are really plain rhombi. Collapse each duplicate
        group down to a single representative before any of that runs -
        a 6-vector zero-shift set becomes the 3-vector, 120-degree family
        it actually is; 8 vectors at zero shift becomes 4 vectors at
        45 degrees."""
        n = len(grid_vectors)
        angles = [math.atan2(v[1], v[0]) for v in grid_vectors]
        dropped = set()
        for i, j in itertools.combinations(range(n), 2):
            if i in dropped or j in dropped:
                continue
            da = (angles[j] - angles[i]) % (2 * np.pi)
            parallel = da < tol or (2 * np.pi - da) < tol
            antiparallel = abs(da - np.pi) < tol
            if not (parallel or antiparallel):
                continue
            combined = shifts[i] + shifts[j] if antiparallel else shifts[i] - shifts[j]
            offset = (combined + 0.5) % 1 - 0.5
            if abs(offset) < tol:
                dropped.add(j)
        if not dropped:
            return grid_vectors, tile_vectors, shifts
        keep = [i for i in range(n) if i not in dropped]
        return ([grid_vectors[i] for i in keep],
                [tile_vectors[i] for i in keep],
                [shifts[i] for i in keep])

    @staticmethod
    def _intersect(A, B, C, D):
        ##where do our grid lines intersect
        dAB = (B[0] - A[0], B[1] - A[1])
        dCD = (D[0] - C[0], D[1] - C[1])
        denom = dAB[0] * (-dCD[1]) - dAB[1] * (-dCD[0])
        if denom == 0:
            return None
        dx = C[0] - A[0]
        dy = C[1] - A[1]
        t = (dx * (-dCD[1]) - dy * (-dCD[0])) / denom
        u = (dx * (-dAB[1]) - dy * (-dAB[0])) / denom
        if 0 <= t <= 1 and 0 <= u <= 1:
            return np.array([[A[0] + t * dAB[0], A[1] + t * dAB[1]]])
        return None

    @staticmethod
    def _cdist(XA, XB, dm):
        ##I can't remember why I did this, but it sped something up somewhere...
        _distance_wrap.cdist_euclidean_double_wrap(XA, XB, dm)
        return dm

    @staticmethod
    def _collinear_filter(combs, vectors):
        ##no point including grid vector combinations that won't intersect
        vecs = np.array(vectors)
        keep = []
        for a, b in combs:
            if vecs[a, 0] * vecs[b, 1] - vecs[a, 1] * vecs[b, 0] != 0:
                keep.append((a, b))
        return keep

    @staticmethod
    def _polygon_area(x, y):
        x, y = np.asarray(x), np.asarray(y)
        correction = x[-1] * y[0] - y[-1] * x[0]
        return 0.5 * abs(np.dot(x[:-1], y[1:]) - np.dot(y[:-1], x[1:]) + correction)

    @staticmethod
    def _cyclic(size):
        ##stepping around for polygon solving
        j, j_step, i, i_step = 0, 0, 1, 1
        store = []
        for a in range(size):
            store.append(list(range(j, i)))
            if a + 1 == size / 2:
                i_step, j_step = 0, 1
            i += i_step
            j += j_step
        return store

    def _n_gon(self, index_set, g1, g2, j, k, grid, list2, val):
        """Creates an n-gon based on the intersection of multiple 
        grids meeting at the same intersection point.
        
        The idea is to gather the grids that are involved, start at an origin, 
        and cyclically build the n-gon according to the dual-grid spaces that we cross.
        Each crossing only ever changes one of the vector indices, so it's easy
        enough to build in a loop."""
        indices = grid.index[0]
        angles = [grid.angles[g1], grid.angles[g2]]
        vectors = [grid.grid_vectors[g1], grid.grid_vectors[g2]]
        factor = []
        all_grids = [g1, g2]

        def _process(gi, idx_pos, idx_neg):
            nonlocal factor
            if gi >= val:
                index_set[gi] = indices[idx_pos]
                angles.append(grid.angles[gi] + math.pi)
                vectors.append((-grid.grid_vectors[gi][0], -grid.grid_vectors[gi][1]))
                factor.append(-1)
            else:
                index_set[gi] = indices[idx_neg]
                angles.append(grid.angles[gi])
                vectors.append(grid.grid_vectors[gi])
                factor.append(1)

        if g1 >= val:
            index_set[g1] = indices[j];  angles[0] += math.pi
            vectors[0] = (-vectors[0][0], -vectors[0][1]);  factor.append(-1)
        else:
            index_set[g1] = indices[j - 1];  factor.append(1)

        if g2 >= val:
            index_set[g2] = indices[k];  angles[1] += math.pi
            vectors[1] = (-vectors[1][0], -vectors[1][1]);  factor.append(-1)
        else:
            index_set[g2] = indices[k - 1];  factor.append(1)

        for gc, i1, i2 in list2:
            all_grids.append(gc)
            _process(gc, max(i1, i2), min(i1, i2))

        construct = self._cyclic((2 + len(list2)) * 2)
        ang_sort = np.argsort(angles)
        all_grids = np.array(all_grids)[ang_sort]
        factor = np.array(factor)[ang_sort]

        origin = index_set.copy()
        store = [origin]
        for step in construct[:-1]:
            ext = origin.copy()
            for s in step:
                ext[all_grids[s]] += factor[s]
            store.append(ext)
        return store

    def _make_tile(self, grid, tile_vectors):
        """Does what is says! Takes our combinations of grid families and finds
        where they intersect. These crossings are gated behind the collinear filter
        and the radius stopper.

        If it's a singular crossing, we build the tile and create its properties:
        - intersection coordinates
        - tile vertices
        - indices
        - type
        
        The multiple intersection logic is crude, but if there exists a point within a tiny
        tolerance that multiple grids pass through, we throw it to the n-gon generator."""


        dimension = len(grid.grid_vectors)
        ind_mult = [(1, 0), (1, 1), (0, 1)]
        vec_no = list(range(dimension))
        radius_sq = np.ceil(grid.grid_len / 3) ** 2
        val = grid.val
        dm = np.empty((1, grid.grid_len), dtype=np.double)

        combs = self._collinear_filter(
            list(itertools.combinations(vec_no, 2)), grid.grid_vectors)

        store, p_store, p_store_interx = [], [], []
        indices = [0] * dimension
        self.intersection_data = []

        for g1, g2 in combs:
            vec_query = [v for v in vec_no if v not in (g1, g2)]
            for j in range(1, grid.grid_len):
                for k in range(1, grid.grid_len):
                    interx = self._intersect(
                        grid.grids[g1][0][j], grid.grids[g1][1][j],
                        grid.grids[g2][0][k], grid.grids[g2][1][k])
                    if interx is None:
                        continue
                    if interx[0][0] ** 2 + interx[0][1] ** 2 > radius_sq:
                        continue

                    index_set = indices.copy()
                    index_set[g1] = grid.index[g1][j]
                    index_set[g2] = grid.index[g2][k]

                    count = 0
                    list2 = []
                    for gc in vec_query:
                        dist = self._cdist(interx, grid.midpoints[gc], dm)[0]
                        dist_idx = dist.argsort()
                        if dist[dist_idx[1]] - dist[dist_idx[0]] < 1e-8:
                            count += 1
                            list2.append((gc, dist_idx[0], dist_idx[1]))
                        else:
                            index_set[gc] = grid.index[gc][dist_idx[0]]

                    if count == 0:
                        tile = [index_set]
                        for dm0, dm1 in ind_mult:
                            tv = index_set.copy()
                            tv[g1] -= dm0
                            tv[g2] -= dm1
                            tile.append(tv)
                        self.intersection_data.append({
                            'x': float(interx[0][0]),
                            'y': float(interx[0][1]),
                            'index_set': tuple(index_set),
                            'vertex_indices': [tuple(v) for v in tile],
                            'g1': g1, 'g2': g2,
                            'type_idx': -1
                        })
                        store.append(tile)
                    else:
                        p_store.append(
                            self._n_gon(index_set, g1, g2, j, k, grid, list2, val))
                     
                        p_store_interx.append((float(interx[0][0]), float(interx[0][1])))

        if p_store:
            seen = set()
            deduped = []
            deduped_interx = []
            for ngon, ix in zip(p_store, p_store_interx):
                key = frozenset(tuple(v) for v in ngon)
                if key not in seen:
                    seen.add(key)
                    deduped.append(ngon)
                    deduped_interx.append(ix)
            p_store = deduped
            p_store_interx = deduped_interx

        poly_areas, ngon_areas = [], []
        self.raw_indices = []
        # coincident grid families (e.g. antipodal directions in even-fold
        # sets) can produce degenerate, zero-area "tiles" that are really
        # just collapsed lines - drop them here so nothing downstream
        # (plotting, vertex-type wedge lookup) ever sees them.
        AREA_EPS = 1e-9

        if store:
            store_xy = np.dot(store, tile_vectors)
            keep_idx = [i for i, s in enumerate(store_xy)
                        if self._polygon_area(s[:, 0], s[:, 1]) > AREA_EPS]
            if keep_idx:
                self.raw_indices = [list(store[i]) for i in keep_idx]
                store = store_xy[keep_idx]
                poly_areas = [self._polygon_area(s[:, 0], s[:, 1]) for s in store]
            else:
                store = []
        ##horrible way of trying to get multiple different n-gons into one neat list
        if p_store:
            x = (2 + dimension) * 2
            nan_row = [[np.nan] * dimension]
            padded = [
                a + nan_row * (x - len(a))
                for a in (p_store + [[]] * (x - len(p_store)))
            ]
            p_store_xy = np.dot(padded, tile_vectors)
            p_store_xy = [s[~np.isnan(s).any(axis=1)] for s in p_store_xy]

            keep = [(orig, xy, ix) for orig, xy, ix in zip(p_store, p_store_xy, p_store_interx)
                    if len(xy) >= 3 and self._polygon_area(xy[:, 0], xy[:, 1]) > AREA_EPS]
            if keep:
                self.raw_indices.append([orig for orig, _, _ in keep])
                p_store = [xy for _, xy, _ in keep]
                ngon_areas = [self._polygon_area(xy[:, 0], xy[:, 1]) for xy in p_store]
                # n-gons involve more than 2 grid families crossing at once,
                # so unlike the quad branch above there's no single (g1, g2)
                # to report - g1/g2 are left as -1 to mark that. The crossing
                # point is `ix`, carried from the intersect() call that found
                # it - none of _n_gon's own vertices are the crossing point
                # itself (they're corners offset from it by construction).
                for orig, xy, ix in keep:
                    self.intersection_data.append({
                        'x': ix[0],
                        'y': ix[1],
                        'index_set': tuple(orig[0]),
                        'vertex_indices': [tuple(v) for v in orig],
                        'g1': -1, 'g2': -1,
                        'type_idx': -1,
                    })
            else:
                p_store = []

        return store, p_store, poly_areas, ngon_areas
