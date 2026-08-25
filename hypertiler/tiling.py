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
    def __init__(self, vector_data, grid_len):
        """For the passed vector data, build our tiling engine."""
        tile_vectors, grid_vectors, shifts = [], [], []
        for row in vector_data:
            angle_rad = np.radians(row[2])
            tile_vectors.append((row[0] * np.cos(angle_rad), row[0] * np.sin(angle_rad)))
            grid_vectors.append((row[1] * np.cos(angle_rad), row[1] * np.sin(angle_rad)))
            shifts.append(row[3])

        ang = [math.atan2(v[1], v[0]) for v in grid_vectors]
        val = (np.round(ang, 2) >= 0).sum()
        ang = [(a + 2 * np.pi if np.round(a, 2) < 0 else a) for a in ang]
        order = np.argsort(ang)
        grid_vectors = np.array(grid_vectors)[order]
        tile_vectors = np.array(tile_vectors)[order]
        ##create the grids
        grid = Grids(grid_vectors, 100, grid_len, shifts, val)
        self.grid = grid
        ##send everything off to create out tiles!
        self.points, self.p_points, self.poly_areas, self.ngon_areas = \
            self._make_tile(grid, tile_vectors)

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

        store, p_store = [], []
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

        if p_store:
            seen = set()
            deduped = []
            for ngon in p_store:
                key = frozenset(tuple(v) for v in ngon)
                if key not in seen:
                    seen.add(key)
                    deduped.append(ngon)
            p_store = deduped

        poly_areas, ngon_areas = [], []

        if store:
            self.raw_indices = [list(tile) for tile in store]
            store = np.dot(store, tile_vectors)
            for s in store:
                poly_areas.append(self._polygon_area(s[:, 0], s[:, 1]))
        ##horrible way of trying to get multiple different n-gons into one neat list
        if p_store:
            self.raw_indices.append(p_store)
            if p_store:
                x = (2 + dimension) * 2
                nan_row = [[np.nan] * dimension]
                p_store = [
                    a + nan_row * (x - len(a))
                    for a in (p_store + [[]] * (x - len(p_store)))
                ]
                p_store = np.dot(p_store, tile_vectors)
                p_store = [s[~np.isnan(s).any(axis=1)] for s in p_store]
                for s in p_store:
                    if len(s):
                        ngon_areas.append(self._polygon_area(s[:, 0], s[:, 1]))

        return store, p_store, poly_areas, ngon_areas
