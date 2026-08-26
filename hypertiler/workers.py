from PyQt5 import QtCore
import numpy as np
import math


def mirror_canonical(key):
    """Canonical key of the mirror-reflected version of this vertex type.

    A canonical key is the cyclic-minimum rotation of a sequence recorded
    while walking around the vertex in one direction. Reflecting the vertex
    reverses that walk direction, so the mirror's canonical key is just the
    cyclic-minimum of the reversed sequence - true for both the dual-grid
    (gap, owner) keys and the substitution (tile_type, span) keys, since
    it only depends on cyclic order, not on what each element holds."""
    m = len(key)
    if m == 0:
        return key
    rev = tuple(reversed(key))
    return min(rev[i:] + rev[:i] for i in range(m))


def group_mirror_types(type_map):
    """Merge each vertex type with its mirror-symmetric partner (if one
    exists as a separate type in type_map), combining their vertex lists
    under a single (deterministically-chosen) key. A type that's its own
    mirror image (achiral) is left as its own single entry."""
    grouped = {}
    handled = set()
    for key in type_map:
        if key in handled:
            continue
        handled.add(key)
        mkey = mirror_canonical(key)
        if mkey in type_map and mkey != key:
            handled.add(mkey)
            group_key = min(key, mkey)
            grouped[group_key] = list(type_map[key]) + list(type_map[mkey])
        else:
            grouped[key] = list(type_map[key])
    return grouped


class _VertexWorker(QtCore.QThread):
    """Runs vertex-type computation off the main thread."""
    finished = QtCore.pyqtSignal(dict, dict, dict)  # type_map, idx_to_vert, vert_to_tiles

    def __init__(self, tiling, poly_areas, current_colors, ngon_areas=None):
        super().__init__()
        self._tiling = tiling
        self._poly_areas = poly_areas
        self._ngon_areas = ngon_areas if ngon_areas is not None else []
        self._current_colors = list(current_colors)

    def run(self):
        tiling = self._tiling
        poly_color = [self._current_colors[i] for i in self._poly_areas]
        n_polys = len(tiling.points)

        tiles = list(zip(tiling.raw_indices[:n_polys], tiling.points, poly_color))
        if len(self._ngon_areas) > 0 and len(tiling.raw_indices) > n_polys:
            ngon_color = [self._current_colors[i] for i in self._ngon_areas]
            tiles += list(zip(tiling.raw_indices[n_polys], tiling.p_points, ngon_color))

        idx_to_vert = {}
        vert_to_tiles = {}
        for raw_tile, proj_tile, color in tiles:
            for raw_vert, proj_vert in zip(raw_tile, proj_tile):
                key = tuple(raw_vert)
                if key not in idx_to_vert:
                    idx_to_vert[key] = proj_vert
                if key not in vert_to_tiles:
                    vert_to_tiles[key] = []
                vert_to_tiles[key].append((raw_tile, proj_tile, color))

        pos_arr = np.array(list(idx_to_vert.values()))
        center = np.mean(pos_arr, axis=0)
        all_pos = pos_arr - center
        norms = np.sqrt(all_pos[:, 0]**2 + all_pos[:, 1]**2)
        radius = norms.max() * 0.8

        set_a_keys = [
            k for k, v in idx_to_vert.items()
            if np.sqrt((v[0] - center[0])**2 + (v[1] - center[1])**2) <= radius
            and len(vert_to_tiles.get(k, [])) > 0
        ]

        def canonical(key):
            k = np.array(key)
            tiles = vert_to_tiles[key]
            neighbour_keys = set()
            wedge_owner = {}
            for tile_raw, tile_proj, _ in tiles:
                n = len(tile_raw)
                for i in range(n):
                    if tuple(tile_raw[i]) != key:
                        continue
                    prev_key = tuple(tile_raw[(i-1) % n])
                    next_key = tuple(tile_raw[(i+1) % n])
                    for nb in (prev_key, next_key):
                        if nb != key:
                            neighbour_keys.add(nb)
                    if prev_key != key and next_key != key:
                        wedge_owner[frozenset((prev_key, next_key))] = n
            if not neighbour_keys:
                return None
            diffs = [tuple(np.array(nk) - k) for nk in neighbour_keys]
            v = idx_to_vert[key]
            def proj_angle(diff):
                nb_key = tuple(k + np.array(diff))
                nb_pos = idx_to_vert.get(nb_key)
                if nb_pos is None:
                    return 0
                return np.arctan2(nb_pos[1]-v[1], nb_pos[0]-v[0])
            diffs_sorted = sorted(diffs, key=proj_angle)
            nbs_sorted = [tuple(k + np.array(d)) for d in diffs_sorted]
            angles = [proj_angle(d) for d in diffs_sorted]
            m = len(angles)
            seq = []
            for i in range(m):
                gap = angles[(i+1) % m] - angles[i]
                if gap <= 0:
                    gap += 2*np.pi
                # -1 sentinel (not None): a missing owner must still be
                # orderable against real tile sizes, or min() below raises
                # and silently kills this QThread mid-computation - the
                # window is left stuck on "Computing vertex types..." forever.
                owner = wedge_owner.get(frozenset((nbs_sorted[i], nbs_sorted[(i+1) % m])), -1)
                seq.append((round(gap, 2), owner))
            return min(tuple(seq[i:] + seq[:i]) for i in range(m))

        type_map = {}
        for k in set_a_keys:
            c = canonical(k)
            if c is None:
                continue
            if c not in type_map:
                type_map[c] = []
            type_map[c].append(k)

        self.finished.emit(type_map, idx_to_vert, vert_to_tiles)
