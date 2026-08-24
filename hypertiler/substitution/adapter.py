import numpy as np


class _SubstitutionAdapter:
    """Wraps substitution final_tiles so vertex/network workers can consume them.

    Provides the same interface as TileMaker: .points, .p_points,
    .raw_indices, .poly_areas, .ngon_areas.

    Vertex deduplication uses rounded-float proximity keys (6 d.p.), assigning
    each unique position a sequential integer index stored as np.array([idx]).
    """

    def __init__(self, final_tiles):
        seen = {}   # (round_x, round_y) -> int global index
        n = 0
        raw_indices = []

        self.points = []
        self.poly_areas = []
        self.p_points = []
        self.ngon_areas = []

        for _tile_type, coords in final_tiles:
            if len(coords) > 1 and np.allclose(coords[0], coords[-1]):
                coords = coords[:-1]
            self.points.append(coords)
            tile_raw = []
            for v in coords:
                k = (round(float(v[0]), 6), round(float(v[1]), 6))
                if k not in seen:
                    seen[k] = n
                    n += 1
                tile_raw.append(np.array([seen[k]]))
            raw_indices.append(tile_raw)

        self.raw_indices = raw_indices
