from PyQt5 import QtCore
import numpy as np
import math


class _VertexWorker(QtCore.QThread):
    """Runs vertex-type computation off the main thread."""
    #TODO: robustly include the polygon addition here
    finished = QtCore.pyqtSignal(dict, dict, dict)  # type_map, idx_to_vert, vert_to_tiles

    def __init__(self, tiling, poly_areas, current_colors):
        super().__init__()
        self._tiling = tiling
        self._poly_areas = poly_areas
        self._current_colors = list(current_colors)

    def run(self):
        tiling = self._tiling
        poly_color = [self._current_colors[i] for i in self._poly_areas]

        idx_to_vert = {}
        vert_to_tiles = {}
        for raw_tile, proj_tile, color in zip(tiling.raw_indices[:len(tiling.points)], tiling.points, poly_color):
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
            for tile_raw, tile_proj, _ in tiles:
                n = len(tile_raw)
                for i in range(n):
                    for nb in [tile_raw[(i-1) % n], tile_raw[(i+1) % n]]:
                        nb_key = tuple(nb)
                        if nb_key != key:
                            neighbour_keys.add(nb_key)
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
            angles = [proj_angle(d) for d in diffs_sorted]
            gaps = []
            for i in range(len(angles)):
                gap = angles[(i+1) % len(angles)] - angles[i]
                if gap <= 0:
                    gap += 2*np.pi
                gaps.append(round(gap, 2))
            n = len(gaps)
            return min(tuple(gaps[i:] + gaps[:i]) for i in range(n))

        type_map = {}
        for k in set_a_keys:
            c = canonical(k)
            if c is None:
                continue
            if c not in type_map:
                type_map[c] = []
            type_map[c].append(k)

        self.finished.emit(type_map, idx_to_vert, vert_to_tiles)
