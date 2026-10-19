
import itertools
import os
import re
import xml.etree.ElementTree as ET
import numpy as np
from collections import defaultdict, deque
from itertools import product
from scipy.spatial import KDTree
from PIL import Image, ImageDraw


# -----------------------------------------------------------------------------
# Lattice basis reduction - the general tool perpendicular-space indexing
# runs on the drawing's own edge vectors (see inkTile._build_module): it
# doesn't assume any particular algebraic structure (e.g. a root of unity)
# ahead of time, so it generalizes to any rule, including ones whose edge
# lengths/inflation factor are irrational in a way that isn't a cyclotomic
# integer.
# -----------------------------------------------------------------------------

def _lll_reduce(basis, delta=0.99):
    """Lenstra-Lenstra-Lovasz lattice basis reduction. `basis`: (n, m) array,
    rows are basis vectors of a (possibly non-integer) lattice. Returns a
    reduced basis of the same shape."""
    B = np.array(basis, dtype=float)
    n = len(B)

    def gram_schmidt(B):
        Bs = np.zeros_like(B)
        mu = np.zeros((n, n))
        for i in range(n):
            Bs[i] = B[i].copy()
            for j in range(i):
                mu[i, j] = (B[i] @ Bs[j]) / (Bs[j] @ Bs[j])
                Bs[i] -= mu[i, j] * Bs[j]
        return Bs, mu

    Bs, mu = gram_schmidt(B)
    k = 1
    while k < n:
        for j in range(k - 1, -1, -1):
            if abs(mu[k, j]) > 0.5:
                B[k] -= round(mu[k, j]) * B[j]
                Bs, mu = gram_schmidt(B)
        if Bs[k] @ Bs[k] >= (delta - mu[k, k - 1] ** 2) * (Bs[k - 1] @ Bs[k - 1]):
            k += 1
        else:
            B[[k, k - 1]] = B[[k - 1, k]]
            Bs, mu = gram_schmidt(B)
            k = max(k - 1, 1)
    return B


class inkTile:
    def __init__(self, gen=0, start=None, tile=None,
                 seed=None, mirror_types=(), verbose=False, perp=False):
        """Parse and correct an Inkscape rules SVG, then run substitution.

        Parsing and correcting the drawing (orientation-group detection,
        template cleaning, overlap-avoiding orientation choice - see below)
        is the expensive part and depends only on `tile`/`seed`/
        `mirror_types`; it runs once, here. Actually generating a tiling is
        cheap by comparison and can be re-run - with a different `gen` or
        `start` - on the same built instance via generate(), without
        repeating that work.

        Parameters
        ----------
        gen   : int
            Number of inflation generations to apply.
        start : str, optional
            Supertile type to begin from (e.g. 'T1'), used only when `seed`
            is not given. Defaults to the first type found in the rules SVG.
        tile  : str
            Rules SVG base name, without the `.svg` extension - the file is
            read from `{tile}.svg`. Required.
        seed  : str, optional
            Seed SVG base name (without `.svg`). If given, generation starts
            from the tiles pre-placed in this file instead of a single
            `start` tile.
        mirror_types : iterable of str
            Chiral tile types whose reversed-winding copies in the drawing
            are genuine mirror images (an achiral outline drawn reversed is
            read as a rotated copy, as normal).
        verbose : bool
            Print what the rule correction changed (see correction_report).
        perp : bool
            Also build the perpendicular-space (cut-and-project) index for
            every generated vertex - see perp_coords(). Adds the one-off
            cost of the LLL/cyclotomic setup, done here alongside the rest
            of the correction.

        The drawn rules are corrected before use: orientations snapped to
        the drawing's rotation group, templates made to close exactly with
        shared edge lengths, every child rebuilt exactly from the corrected
        templates, and the inflation factor fitted so the parent's corners
        land on child vertices. See correction_report() for how far each
        moved.

        Attributes
        ----------
        final_tiles : list of (str, ndarray)
            The generated tiling as a flat list of (tile_type, coords)
            tuples, one per tile, where `coords` is an (M, 2) polygon.
        rules : dict
            The substitution rule extracted from the rules SVG: for each
            supertile type, the exact placement of every subtile found
            inside it.
        """
        if tile is not None:
            svg_file = f"{tile}.svg"
        else:
            raise ValueError("Provide 'tile' (SVG base name)")
        self.svg_path = os.path.abspath(svg_file)

        tiling, types = self.parse_svg(svg_file)
        tiling = self.rename_tiles_by_type(tiling, types)

        templates, drawn = {}, {}
        for key in tiling:
            if 'super' in key:
                k, v = list(tiling[key]['tiles'].items())[0]
                templates[k] = self._clean_poly(v)
            else:
                drawn[key[3:]] = tiling[key]['tiles']

        if not templates:
            raise ValueError(f"{svg_file} has no 'super<type>' groups to use as tile templates")
        missing = [k for k in templates if not drawn.get(k)]
        if missing:
            raise ValueError(f"{svg_file} has no 'sub<type>' children for {missing}")

        # units: the shortest template edge is 1
        scale = self.find_min_edge_length(templates)
        self.drawing_scale = scale          # SVG units per unit edge
        self.templates = self.normalize_tiles(templates, scale)

        # snap near-coincident vertices in raw SVG units (absolute tolerance,
        # independent of the tiling's normalization scale) before anything
        # else runs - true coincident vertices land at ~0 distance apart.
        drawn = self._snap(drawn)
        drawn = {k: {n: c / scale for n, c in d.items()
                     if isinstance(c, np.ndarray) and c.ndim == 2 and np.ptp(c) > 0}
                 for k, d in drawn.items()}

        self.type_names = list(self.templates)
        self.mirror_types = set(mirror_types)
        self.lam = self._drawn_scale(drawn)            # child size / parent size, as drawn

        raw_rules = self.extract_rules(self.templates, drawn)

        seed_raw = None
        if seed is not None:
            seed_tiles = self.parse_seed_svg(f"{seed}.svg", types, self.templates)
            seed_raw = [(t, self._fit_orientation(t, c, 1.0)) for t, c in seed_tiles]

        self._build_group(raw_rules, seed_raw)
        self._clean_templates()
        self._place_children(raw_rules)
        self._choose_orientations(raw_rules)
        self.rules = raw_rules
        self._seed_raw = seed_raw
        self._perp_mode = perp

        # The hyperspace module/index/inflation/symmetry always build (it's
        # cheap - the per-generation substitution below runs on it either
        # way); only the perpendicular-space PROJECTION itself is gated
        # behind perp=True, since that's the one genuinely extra cost.
        # Fixing a genuinely ambiguous drawing (fix_decorations) is NOT run
        # here - an already-consistent rules SVG should load and generate
        # correctly without it; call it explicitly when it isn't.
        self._build_module()
        self.index_rules(self.rules)
        self._build_inflation()
        self._build_symmetry()
        # the as-drawn (m, g) of every child, captured once before any
        # fix_decorations() call - rewrite_svg()'s notion of "changed" is
        # always relative to this, not to whichever fix_decorations() call
        # happens to run last, so repeated "attempt to fix" rounds (e.g.
        # one that improves things further after an earlier one) still add
        # up to the right total diff against the original drawing.
        self._as_drawn_child_state = [(k, j, c['m'].copy(), c['g'])
                                      for k in self.type_names
                                      for j, c in enumerate(self.rules[k])]
        if perp:
            self._build_projection()

        if verbose:
            print(self.correction_report())

        self.generate(gen, start)

    def generate(self, gen, start=None):
        """(Re-)run substitution from the already-built, corrected rules.

        Unlike __init__, this doesn't re-parse or re-correct the drawing -
        it's cheap, and can be called repeatedly on the same instance with
        a different `gen` or `start` (ignored if the instance was built
        with `seed`). Updates and returns self.final_tiles.
        """
        if self._seed_raw is not None:
            tiles0 = self._index_seed(self._seed_raw)
        else:
            if start is None:
                start = self.type_names[0]
            tiles0 = self._single_tile(start)

        self.hyper = self.substitute_hyper(tiles0, gen)
        self.final_tiles = self.to_physical(self.hyper)
        self.final_tiles = self._snap_flat(self.final_tiles, tol=1e-2)
        return self.final_tiles

    # -------------------------------------------------------------------------
    # Snap helpers
    # -------------------------------------------------------------------------
    @staticmethod
    def _cluster_merge(verts, tol):
        """Union-find clustering of near-coincident points; each point is
        replaced by the mean of its cluster."""
        def find(parent, x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(parent, rank, a, b):
            ra, rb = find(parent, a), find(parent, b)
            if ra == rb: return
            if rank[ra] < rank[rb]: ra, rb = rb, ra
            parent[rb] = ra
            if rank[ra] == rank[rb]: rank[ra] += 1

        pairs = KDTree(verts).query_pairs(r=tol)
        parent = list(range(len(verts)))
        rank = [0] * len(verts)
        for i, j in pairs:
            union(parent, rank, i, j)

        groups = defaultdict(list)
        for idx in range(len(verts)):
            groups[find(parent, idx)].append(idx)
        merged = {root: verts[members].mean(axis=0) for root, members in groups.items()}
        return np.array([merged[find(parent, idx)] for idx in range(len(verts))])

    def _snap(self, subtiles):
        # Absolute tolerance in raw SVG drawing units (independent of any
        # tiling normalization scale). True coincident vertices land at
        # ~0 distance (shared path endpoints); genuinely distinct vertices
        # in these drawings are tens of units apart, so this has wide margin.
        tol = 1.0
        for ok, inner in subtiles.items():
            all_verts, addresses = [], []
            for ik, poly in inner.items():
                for vi, v in enumerate(poly):
                    all_verts.append(v)
                    addresses.append((ik, vi))
            all_verts = np.array(all_verts)
            snapped = self._cluster_merge(all_verts, tol)
            for idx, (ik, vi) in enumerate(addresses):
                subtiles[ok][ik][vi] = snapped[idx]
        return subtiles

    def _snap_flat(self, tile_list, tol):
        """Snap near-coincident vertices across a flat [(type, coords), ...]
        list, regardless of which tile they belong to."""
        if not tile_list:
            return tile_list
        all_verts, addresses = [], []
        for ti, (_, coords) in enumerate(tile_list):
            for vi, v in enumerate(coords):
                all_verts.append(v)
                addresses.append((ti, vi))
        all_verts = np.array(all_verts)
        snapped = self._cluster_merge(all_verts, tol)
        new_tiles = [(t, np.array(coords, dtype=float)) for t, coords in tile_list]
        for idx, (ti, vi) in enumerate(addresses):
            new_tiles[ti][1][vi] = snapped[idx]
        return new_tiles

    # -------------------------------------------------------------------------
    # Geometry helpers
    # -------------------------------------------------------------------------

    def rot(self, v, ang):
        x, y = v[0], v[1]
        c, s = np.cos(ang), np.sin(ang)
        return np.array([x * c - y * s, y * c + x * s])

    def incenter(self, coords):
        """Incenter of a triangle (exact centre for equilateral, weighted for others)."""
        A, B, C = coords
        a = np.linalg.norm(B - C)
        b = np.linalg.norm(A - C)
        c = np.linalg.norm(A - B)
        return (a * A + b * B + c * C) / (a + b + c)

    # -------------------------------------------------------------------------
    # SVG parsing
    # -------------------------------------------------------------------------

    def parse_path_d(self, d):
        tokens = d.replace(',', ' ').split()
        points = []
        i = 0
        cmd = None
        x = y = 0.0
        while i < len(tokens):
            token = tokens[i]
            if token[0].isalpha():
                cmd = token          # preserve case
                i += 1
            else:
                is_rel = cmd.islower()
                c = cmd.upper()
                if c in ('M', 'L'):
                    dx = float(tokens[i])
                    dy = float(tokens[i + 1])
                    if is_rel:
                        x += dx
                        y += dy
                    else:
                        x = dx
                        y = dy
                    points.append((x, y))
                    i += 2
                elif c == 'H':
                    dx = float(tokens[i])
                    x = x + dx if is_rel else dx
                    points.append((x, y))
                    i += 1
                elif c == 'V':

                    dy = float(tokens[i])
                    y = y + dy if is_rel else dy
                    points.append((x, y))
                    i += 1
                elif c == 'Z':
                    if points:
                        points.append(points[0])
                    i += 1
                else:
                    raise ValueError(f"Unknown SVG command '{cmd}'")
        return points

    def extract_style(self, element):
        """Extract (fill, stroke, stroke_width) from any SVG element."""
        fill = element.attrib.get('fill', 'none')
        stroke = element.attrib.get('stroke', 'none')
        stroke_width = element.attrib.get('stroke-width', None)

        for part in element.attrib.get('style', '').split(';'):
            if ':' not in part:
                continue
            key, val = part.strip().split(':', 1)
            key, val = key.strip(), val.strip()
            if key == 'fill':
                fill = val
            elif key == 'stroke':
                stroke = val
            elif key == 'stroke-width':
                stroke_width = float(val)

        return fill, stroke, stroke_width

    def parse_tuple_string(self, s):
        s = s.strip().replace('(', '').replace(')', '')
        return [float(v) for v in s.replace(',', ' ').split() if v.strip()]

    def parse_transform_string(self, transform_str):
        transform_str = transform_str.strip()
        if transform_str.startswith('translate'):
            nums = self.parse_tuple_string(transform_str[len('translate('):-1])
            return ('translate', nums)
        elif transform_str.startswith('rotate'):
            nums = self.parse_tuple_string(transform_str[len('rotate('):-1])
            return ('rotate', nums)
        elif transform_str.startswith('matrix'):
            nums = self.parse_tuple_string(transform_str[len('matrix('):-1])
            return ('matrix', nums)
        return (None, [])

    def apply_matrix(self, points, matrix_vals):
        a, b, c, d, e, f = matrix_vals
        pts = np.array(points, dtype=float)
        return pts @ np.array([[a, c], [b, d]]).T + np.array([e, f])

    def apply_rotation(self, points, angle, cx=0.0, cy=0.0):
        rad = np.radians(angle)
        R = np.array([[np.cos(rad), -np.sin(rad)],
                      [np.sin(rad),  np.cos(rad)]])
        shifted = np.array(points) - np.array([cx, cy])
        return shifted @ R.T + np.array([cx, cy])

    def apply_transform_to_points(self, points, transform_type, nums):
        points = np.array(points, dtype=float)
        if transform_type == 'translate':
            dx = nums[0]
            dy = nums[1] if len(nums) > 1 else 0.0
            points += np.array([dx, dy])
        elif transform_type == 'rotate':
            angle = nums[0]
            cx, cy = (nums[1], nums[2]) if len(nums) == 3 else (0.0, 0.0)
            points = self.apply_rotation(points, angle, cx, cy)
        elif transform_type == 'matrix':
            points = self.apply_matrix(points, nums)
        return points

    def parse_svg(self, filename):
        """
        Parse an inflation-rules SVG file.

        Layers labelled 'super<type>' define supertile templates; layers labelled
        'sub<type>' define subtile placements.

        Returns
        -------
        tiling : dict  - raw group data
        types  : dict  - stroke-color -> tile-type
        """
        ns = {'svg': 'http://www.w3.org/2000/svg'}
        tree = ET.parse(filename)
        root = tree.getroot()
        supertile = {}
        layer_id = 'layer1'
        layer = root.find(f".//svg:g[@id='{layer_id}']", ns)
        if layer is None:
            raise ValueError(f"Layer '{layer_id}' not found in {filename}")

        top_groups = layer.findall('svg:g', ns)
        types = {}

        for g in top_groups:
            label = g.attrib.get('{http://www.inkscape.org/namespaces/inkscape}label', None)
            top_label = label if label else g.attrib.get('id', '(no id)')
            transform_attr = g.attrib.get('transform', '')
            transform_type, nums = self.parse_transform_string(transform_attr)

            tiles = {}
            props = {}

            # Paths directly in top-level group
            for path in g.findall('svg:path', ns):
                path_id = path.attrib.get('id', '(no id)')
                d = path.attrib.get('d', '')
                points = self.parse_path_d(d)
                if len(points) < 3:
                    continue
                if transform_type:
                    points = self.apply_transform_to_points(points, transform_type, nums)
                points = np.array(points)
                points[:, 1] = -points[:, 1]
                style = self.extract_style(path)

                if top_label.startswith('super'):
                    tile_type = top_label[5:]
                    tiles[tile_type] = points
                    props[tile_type] = style
                    types[style[1]] = tile_type   # stroke color -> tile type
                else:
                    tiles[path_id] = points
                    props[path_id] = style

            # Paths inside sub-groups (subtile orientation markers)
            for group in g.findall('svg:g', ns):
                groupmode = group.attrib.get(
                    '{http://www.inkscape.org/namespaces/inkscape}groupmode')
                if groupmode == 'layer':
                    continue
                t_attr = group.attrib.get('transform', '')
                t_type_g, nums_g = self.parse_transform_string(t_attr)

                for path in group.findall('svg:path', ns):
                    path_id = path.attrib.get('id', '(no id)')
                    d = path.attrib.get('d', '')
                    points = self.parse_path_d(d)
                    if len(points) < 3:
                        continue
                    if t_type_g:
                        points = self.apply_transform_to_points(points, t_type_g, nums_g)
                    points = np.array(points)
                    points[:, 1] = -points[:, 1]
                    tiles[path_id] = points - points   # zero: orientation marker
                    props[path_id] = self.extract_style(path)

            supertile[top_label] = {'tiles': tiles, 'props': props}

        return supertile, types

    def parse_seed_svg(self, filename, types, supertiles):
        """
        Parse a seed SVG containing pre-placed tiles.

        Tiles are identified by fill color (using the types mapping from the
        rules SVG). The seed may be drawn at any consistent scale (supertile
        size, subtile size, or otherwise) -- the actual scale factor is
        inferred by comparing the first seed tile's own edge length to its
        type's already-normalized (unity-edge) template in `supertiles`, the
        same trick `self.lam` itself is derived with. Group transforms are
        applied recursively.

        Returns a list of (tile_type, coords) tuples.
        """
        ns = {'svg': 'http://www.w3.org/2000/svg'}
        tree = ET.parse(filename)
        root = tree.getroot()
        tile_list = []

        def collect_paths(node):
            t_attr = node.attrib.get('transform', '')
            t_type, t_nums = self.parse_transform_string(t_attr)

            for path in node.findall('svg:path', ns):
                d = path.attrib.get('d', '')
                points = self.parse_path_d(d)
                if len(points) < 3:
                    continue
                pts = np.array(points, dtype=float)
                if t_type:
                    pts = self.apply_transform_to_points(pts, t_type, t_nums)
                pts[:, 1] = -pts[:, 1]
                fill, _, _ = self.extract_style(path)
                if fill in types:
                    tile_list.append((types[fill], pts))

            for child in node.findall('svg:g', ns):
                collect_paths(child)

        collect_paths(root)
        # snap in raw SVG units first (matches _snap()'s reasoning for the
        # rules SVG), then normalize into the same unit space as supertiles
        tile_list = self._snap_flat(tile_list, tol=1.0)
        if not tile_list:
            return tile_list

        t0, coords0 = tile_list[0]
        template = supertiles[t0]
        e_seed = np.linalg.norm(coords0[1] - coords0[0])
        e_template = np.linalg.norm(template[1] - template[0])
        seed_scale = e_seed / e_template

        return [(t, coords / seed_scale) for t, coords in tile_list]

    # -------------------------------------------------------------------------
    # Tile helpers
    # -------------------------------------------------------------------------

    def rename_tiles_by_type(self, tiling, names):
        """Rename tile keys to standardised type_N form using fill-color mapping."""
        renamed_tiling = {}
        for group, data in tiling.items():
            tiles = data['tiles']
            props = data['props']
            new_tiles = {}
            new_props = {}
            counters = defaultdict(int)
            for old_key, coords in tiles.items():
                fill_color = props[old_key][0]
                if fill_color == 'none':
                    new_tiles[old_key] = coords
                    new_props[old_key] = props[old_key]
                    continue
                tile_type = names[fill_color]
                counters[tile_type] += 1
                new_key = f"{tile_type}_{counters[tile_type]}"
                new_tiles[new_key] = coords
                new_props[new_key] = props[old_key]
            renamed_tiling[group] = {'tiles': new_tiles, 'props': new_props}
        return renamed_tiling

    def find_min_edge_length(self, tiles):
        min_edge = float('inf')
        for coords in tiles.values():
            edges = [np.linalg.norm(coords[i] - coords[(i + 1) % len(coords)])
                     for i in range(len(coords))]
            min_edge = min(min_edge, min(edges))
        return min_edge

    def normalize_tiles(self, tiles, scale):
        return {k: v / scale for k, v in tiles.items()}

    # -------------------------------------------------------------------------
    # Substitution rules
    # -------------------------------------------------------------------------
    # A tile is an isometric copy of its template: coords = x + Q (T - T[0]),
    # Q in O(2). Inflating it places child j (type t, orientation R_j and
    # vertex-0 offset p_j relative to the parent's vertex 0, both measured in
    # the parent template's own frame) at
    #     Q' = Q R_j,      x' = (x + Q p_j) / lam.
    # R_j is measured against the CHILD's template, never the parent's, so it
    # doesn't matter how each supertile happens to be rotated in the drawing.

    @staticmethod
    def _clean_poly(P):
        """drop the closing duplicate vertex that a trailing 'Z' adds"""
        P = np.asarray(P, dtype=float)
        if len(P) > 3 and np.linalg.norm(P[0] - P[-1]) < 1e-3 * np.ptp(P, axis=0).max():
            P = P[:-1]
        return P

    @staticmethod
    def _area(P):
        """signed area (shoelace): the sign is the winding"""
        x, y = P[:, 0], P[:, 1]
        return 0.5 * np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y)

    @staticmethod
    def _rot_matrix(deg, reflect=False):
        a = np.radians(deg)
        R = np.array([[np.cos(a), -np.sin(a)], [np.sin(a), np.cos(a)]])
        return R @ np.diag([1.0, -1.0]) if reflect else R

    def _drawn_scale(self, drawn):
        """child size / parent size as drawn: the median, over every child,
        of its median edge over its template's median edge."""
        ratios = []
        for d in drawn.values():
            for name, P in d.items():
                t = name.rsplit('_', 1)[0]
                if t not in self.templates:
                    continue
                P = self._clean_poly(P)
                T = self.templates[t]
                if len(P) != len(T):
                    continue
                e = np.linalg.norm(np.roll(P, -1, axis=0) - P, axis=1)
                et = np.linalg.norm(np.roll(T, -1, axis=0) - T, axis=1)
                ratios.append(np.median(e) / np.median(et))
        if not ratios:
            raise ValueError("no child tile matches a template")
        return float(np.median(ratios))

    def _fit_orientation(self, t, P, scale):
        """isometry taking template t (at `scale`) onto polygon P, vertex 0 to
        vertex 0 -- returns P cleaned, its rotation angle and reflection flag"""
        P = self._clean_poly(P)
        T = self.templates[t] - self.templates[t][0]
        if len(P) != len(T):
            raise ValueError(f"a {t} tile has {len(P)} vertices, its template "
                             f"has {len(T)}")
        e_t, e_c = T[1], P[1] - P[0]
        size = scale * np.linalg.norm(e_t)

        def rotation_fit(Tf):
            ang = np.degrees(np.arctan2(e_c[1], e_c[0]) - np.arctan2(Tf[1][1], Tf[1][0]))
            res = np.abs(scale * Tf @ self._rot_matrix(ang).T + P[0] - P).max() / size
            return ang % 360, res

        # 1. a proper rotation, vertex 0 onto vertex 0
        ang, res = rotation_fit(T)
        if res < 0.05:
            return {'poly': P, 'angle': ang, 'reflect': False}

        # 2. drawn with the opposite winding (e.g. a rule made by mirroring
        #    another in Inkscape). If the OUTLINE is achiral, it is still a
        #    rotated copy: turn the template by the edge-0 angle about its
        #    centre -- the original ink2tile convention -- and relabel the
        #    drawn vertices to follow the template's. Skipped for
        #    mirror_types, whose reversed copies are reflections (step 3).
        #    Reversed winding runs every edge the other way, so the template's
        #    edge 0 is tried against each drawn edge in both directions (edge
        #    0 forwards - the original convention - first): an equilateral
        #    triangle, unlike a square, is not symmetric under the 180 degrees
        #    that a reversed edge 0 alone would give.
        if t not in self.mirror_types:
            n, base = len(P), np.arctan2(e_t[1], e_t[0])
            dirs = [(P[i], P[(i + 1) % n]) for i in range(n)]
            dirs = [dirs[0], dirs[0][::-1]] + [d for d_ in dirs[1:] for d in (d_, d_[::-1])]
            for a_, b_ in dirs:
                ang = np.degrees(np.arctan2(*(b_ - a_)[::-1]) - base) % 360
                img = scale * (T - T.mean(axis=0)) @ self._rot_matrix(ang).T + P.mean(axis=0)
                D = np.linalg.norm(img[:, None] - P[None], axis=2)
                order = D.argmin(axis=1)
                if D.min(axis=1).max() / size < 0.05 and len(set(order)) == len(P):
                    return {'poly': P[order], 'angle': ang, 'reflect': False}

        # 3. a genuinely mirrored chiral outline
        ang, res = rotation_fit(T * [1.0, -1.0])
        if res < 0.05:
            return {'poly': P, 'angle': ang, 'reflect': True}
        raise ValueError(f"a {t} tile doesn't match its template by any "
                         f"isometry (relative residual {res:.3f})")

    def extract_rules(self, templates, subtiles):
        """parent -> list of children as drawn: key, type, polygon and
        measured orientation relative to the child's own template"""
        rules = {}
        for k in templates:
            kids = []
            for key, P in subtiles.get(k, {}).items():
                t = key.rsplit('_', 1)[0]
                if t not in templates or len(P) < 3 or np.ptp(P) == 0:
                    continue          # orientation marker / non-tile entry
                fit = self._fit_orientation(t, P, self.lam)
                drawn = self._clean_poly(P)
                kids.append({'key': key, 'type': t, **fit,
                             # as drawn, for diagnostics: vertex order and winding
                             'drawn': drawn,
                             'reversed': bool(np.sign(self._area(drawn)) !=
                                              np.sign(self._area(templates[t])))})
            rules[k] = kids
        return rules

    # -------------------------------------------------------------------------
    # Orientation group
    # -------------------------------------------------------------------------
    # Orientations are snapped to multiples of 360/N (N detected from the
    # drawing) and stored as elements (k, s) = Rot(360 k/N) F^s of the
    # dihedral group D_N, F the reflection in the x-axis. G is the subgroup
    # generated by every orientation that actually occurs.

    def _gmul(self, a, b):
        (k1, s1), (k2, s2) = a, b
        return ((k1 + (-k2 if s1 else k2)) % self.N, s1 ^ s2)

    def _ginv(self, a):
        k, s = a
        return a if s else ((-k) % self.N, 0)

    def _build_group(self, raw_rules, seed_raw):
        fits = [c for kids in raw_rules.values() for c in kids]
        if seed_raw:
            fits += [f for _, f in seed_raw]
        angles = np.array([f['angle'] for f in fits])
        for N in range(1, 361):
            q = 360.0 / N
            if np.all(np.abs((angles / q) - np.round(angles / q)) * q < 0.5):
                break
        self.N = N
        for f in fits:
            f['g'] = (int(round(f['angle'] / (360.0 / N))) % N, int(f['reflect']))
        self._align_frames(raw_rules, seed_raw)

        G = [(0, 0)]
        frontier = list({f['g'] for f in fits})
        while frontier:
            new = []
            for a in frontier:
                for b in list(G):
                    for c in (self._gmul(a, b), self._gmul(b, a)):
                        if c not in G:
                            G.append(c); new.append(c)
            frontier = new
        self.G = G
        self.gidx = {g: i for i, g in enumerate(G)}
        self.Q = np.array([self._rot_matrix(360.0 * k / N, s) for k, s in G])
        self.gmul_table = np.array([[self.gidx[self._gmul(a, b)] for b in G] for a in G])
        self.ginv = np.array([self.gidx[self._ginv(a)] for a in G])
        for f in fits:
            f['g'] = self.gidx[f['g']]

    def _align_frames(self, raw_rules, seed_raw):
        """Remove orientation offsets that are artefacts of the drawing.

        Two things inflate the orientation group beyond the tiling's real
        symmetry: a template drawn rotated w.r.t. the orientations its type
        actually takes (offset beta_t), and an inflation that rotates the
        tiling by phi each generation. Both show up as every child's
        relative orientation satisfying  g_j = phi + beta_t - beta_k  (mod d)
        for some coarse subgroup d Z_N. Find the coarsest d for which that
        holds, rotate each template by beta_t, and absorb phi into the
        substitution (so generation n is drawn rotated by -n phi). Rotation
        -only rules; with reflections present the drawing is left as is."""
        N = self.N
        kids = [(k, c['type'], c['g'][0]) for k, cs in raw_rules.items() for c in cs]
        self.inflation_rotation = 0.0
        self.frame_offsets = {t: 0.0 for t in self.type_names}
        if any(c['g'][1] for cs in raw_rules.values() for c in cs):
            return
        types = self.type_names
        best = None
        for d in sorted((d for d in range(1, N + 1) if N % d == 0), reverse=True):
            # phi = 0 only: absorbing an inflation rotation means turning each
            # rule's children about that parent's own vertex 0, which breaks
            # how neighbouring parents' children fit together (stamp: 287
            # overlapping tiles by generation 2). A rotation of the whole
            # tiling would need a common centre; it is kept in the group instead.
            for phi in (0,):
                beta = {types[0]: 0}
                changed, ok = True, True
                while changed and ok:
                    changed = False
                    for k, t, g in kids:
                        if k in beta and t not in beta:
                            beta[t] = (beta[k] + g - phi) % d; changed = True
                        elif t in beta and k not in beta:
                            beta[k] = (beta[t] - g + phi) % d; changed = True
                        elif k in beta and (beta[k] + g - phi - beta[t]) % d:
                            ok = False; break
                if ok and len(beta) == len(types):
                    best = (d, phi, beta); break
            if best:
                break
        if best is None or best[0] == 1:
            return
        d, phi, beta = best
        q = 360.0 / N
        for t in types:                           # re-draw each type's template
            if beta[t]:
                T = self.templates[t]
                self.templates[t] = (T - T[0]) @ self._rot_matrix(beta[t] * q).T + T[0]
        for k, cs in raw_rules.items():           # rotate each rule's children
            turn = (beta[k] - phi) % N
            piv = self.templates[k][0]
            for c in cs:
                if turn:
                    c['poly'] = (c['poly'] - piv) @ self._rot_matrix(turn * q).T + piv
                c['g'] = ((c['g'][0] + turn - beta[c['type']]) % N, 0)
                c['angle'] = c['g'][0] * q
        if seed_raw:
            off = {(f['g'][0] - beta[t]) % d for t, f in seed_raw}
            c0 = off.pop() if len(off) == 1 else 0
            piv = seed_raw[0][1]['poly'][0]
            for t, f in seed_raw:
                if c0:
                    f['poly'] = (f['poly'] - piv) @ self._rot_matrix(-c0 * q).T + piv
                f['g'] = ((f['g'][0] - beta[t] - c0) % N, 0)
                f['angle'] = f['g'][0] * q
        self.inflation_rotation = -phi * q
        self.frame_offsets = {t: beta[t] * q for t in types}

    # -------------------------------------------------------------------------
    # Drawing noise
    # -------------------------------------------------------------------------
    # Hand-drawn templates are off by ~1e-3 (a side of 1.3045 where 1.3066 is
    # meant), which is enough to hide the integer relations between edges.
    # Directions are snapped to the angle quantum, lengths that agree to
    # within `rel_tol` are treated as one length, and those lengths are then
    # solved for by least squares subject to every template closing exactly.

    def _clean_templates(self, rel_tol=0.01, ang_tol=0.3):
        edges = {t: np.roll(T, -1, axis=0) - T for t, T in self.templates.items()}
        allE = np.vstack(list(edges.values()))
        ang = np.degrees(np.arctan2(allE[:, 1], allE[:, 0]))
        q = None
        for div in (1, 2, 4, 8):
            qq = 360.0 / (self.N * div)
            if np.all(np.abs(ang / qq - np.round(ang / qq)) * qq < ang_tol):
                q = qq; break
        if q is None:
            print("  warning: template edge directions don't sit on any "
                  "multiple of the rotation quantum -- directions left as drawn")
            U = allE / np.linalg.norm(allE, axis=1, keepdims=True)
        else:
            a = np.radians(np.round(ang / q) * q)
            U = np.column_stack([np.cos(a), np.sin(a)])

        # cluster lengths
        ln = np.linalg.norm(allE, axis=1)
        order = np.argsort(ln)
        cl = np.zeros(len(ln), dtype=int)
        for a_, b_ in zip(order[:-1], order[1:]):
            cl[b_] = cl[a_] + (ln[b_] > ln[a_] * (1 + rel_tol))
        nc = cl.max() + 1
        mean = np.array([ln[cl == c].mean() for c in range(nc)])
        w = np.array([np.sum(cl == c) for c in range(nc)], dtype=float)

        # closure: sum_i L_{c(i)} u_i = 0 for each template
        rows, o = [], 0
        for t, E in edges.items():
            Ct = np.zeros((2, nc))
            for i in range(len(E)):
                Ct[:, cl[o + i]] += U[o + i]
            rows.append(Ct); o += len(E)
        Ccl = np.vstack(rows)
        # KKT for  min sum_c w_c (L_c - mean_c)^2  s.t.  Ccl L = 0
        m = len(Ccl)
        K = np.block([[np.diag(2 * w), Ccl.T], [Ccl, np.zeros((m, m))]])
        sol = np.linalg.lstsq(K, np.concatenate([2 * w * mean, np.zeros(m)]), rcond=None)[0]
        L = sol[:nc]
        closes = np.abs(Ccl @ L).max() < 1e-9
        moved = np.abs(L / mean - 1).max()
        if not closes or moved > 2 * rel_tol:
            print(f"  warning: templates can't be made to close with shared "
                  f"lengths (moved {moved:.1%}) -- lengths left as drawn")
            L = None
        newE = U * (L[cl] if L is not None else ln)[:, None]
        self.template_correction, o = 0.0, 0
        for t, E in edges.items():
            T = self.templates[t]
            Tn = T[0] + np.vstack([np.zeros(2), np.cumsum(newE[o:o + len(E)], axis=0)[:-1]])
            self.template_correction = max(self.template_correction, np.abs(Tn - T).max())
            self.templates[t] = Tn; o += len(E)
        self.edge_lengths = np.sort(L if L is not None else mean)
        self.angle_quantum = q

    # -------------------------------------------------------------------------
    # Exact children
    # -------------------------------------------------------------------------
    # Cleaning the templates leaves each child where it was drawn, and a
    # child misplaced by d (in child units) puts its level-n descendants
    # d / lam^(n-1) out - the drift that splits vertices by ABvar n = 3.
    # So every rule's children are rebuilt from the clean templates and the
    # exact orientations: one child is anchored at the parent's corner 0 (or,
    # if no child vertex sits there, at its own drawn vertex), and the rest
    # are placed by the vertices they share in the drawing. Every child
    # vertex is then corner0 + lam * w with w exact, so lam is fitted by least
    # squares to put the parent's corners on child vertices.

    def _place_children(self, rules, tol_frac=0.2):
        tol = tol_frac * self.lam
        unit = {t: T - T[0] for t, T in self.templates.items()}
        placed = {}                                   # (k, j) -> (anchor point, offset o, shape)
        for k, cs in rules.items():
            T = self.templates[k]
            shape = [unit[c['type']] @ self.Q[c['g']].T for c in cs]   # vertices at lam = 1
            todo = set(range(len(cs)))
            # start at the parent's corner 0 if a child vertex sits there
            start = next(((j, vi) for j, c in enumerate(cs) for vi in range(len(c['poly']))
                          if np.linalg.norm(c['poly'][vi] - T[0]) < tol), None)
            while todo:
                if start is not None:
                    j0, vi0 = start
                    anchor, o0 = T[0].copy(), -shape[j0][vi0]
                    start = None
                else:
                    j0 = min(todo)
                    anchor, o0 = cs[j0]['poly'][0].copy(), -shape[j0][0]
                placed[(k, j0)] = (anchor, o0, shape[j0])
                todo.discard(j0)
                queue = [j0]
                while queue:
                    j = queue.pop()
                    a_j, o_j, s_j = placed[(k, j)]
                    for j2 in sorted(todo):
                        hit = next(((vi, vi2) for vi in range(len(cs[j]['poly']))
                                    for vi2 in range(len(cs[j2]['poly']))
                                    if np.linalg.norm(cs[j]['poly'][vi] - cs[j2]['poly'][vi2]) < tol), None)
                        if hit:
                            vi, vi2 = hit
                            placed[(k, j2)] = (a_j, o_j + s_j[vi] - shape[j2][vi2], shape[j2])
                            todo.discard(j2)
                            queue.append(j2)
        # lam from the parent corners (children anchored at a corner only)
        num = den = 0.0
        corner_fits = []
        for k, cs in rules.items():
            T = self.templates[k]
            for i in range(1, len(T)):
                for j, c in enumerate(cs):
                    a, o, s = placed[(k, j)]
                    if not np.allclose(a, T[0]):
                        continue
                    d = np.linalg.norm(c['poly'] - T[i], axis=1)
                    if d.min() < tol:
                        w = o + s[int(d.argmin())]
                        num += (T[i] - T[0]) @ w
                        den += w @ w
                        corner_fits.append((T[i] - T[0], w))
                        break
        self.lam_drawn = self.lam
        if den > 0:
            self.lam = float(num / den)
        self.corner_residual = max((np.linalg.norm(c - self.lam * w) / self.lam for c, w in corner_fits),
                                   default=float('nan'))
        self.child_correction = 0.0
        for k, cs in rules.items():
            for j, c in enumerate(cs):
                a, o, s = placed[(k, j)]
                c['exact'] = a + self.lam * (o + s)
                c['p'] = c['exact'][0] - self.templates[k][0]
                self.child_correction = max(self.child_correction,
                                            np.abs(c['exact'] - c['poly']).max() / self.lam)

    # -------------------------------------------------------------------------
    # Which way round each child is decorated
    # -------------------------------------------------------------------------
    # A child whose outline is symmetric (a square, a rhombus) can be turned
    # by an outline symmetry without moving: only its decoration - which way
    # its own substitution faces - changes, and the drawing doesn't always
    # say which is meant. The drawn label is used as is here (cheap, and a
    # consistent drawing needs nothing more); see fix_decorations() (below
    # the hyperspace module, once it's built) for the search that resolves
    # a genuinely ambiguous drawing - an explicit, opt-in diagnostic/repair
    # step, not run on every load.

    def _relabel(self, c, s):
        """child c turned by outline symmetry s (an index into self.Q):
        (orientation, polygon, vertex permutation) - the same outline, its
        vertices relabelled."""
        T = self.templates[c['type']]
        g2 = int(self.gmul_table[c['g0'], s])
        shape = self.lam * (T - T[0]) @ self.Q[g2].T
        E = c['exact0']
        for i0 in range(len(E)):
            Enew = E[i0] + shape
            d = np.linalg.norm(Enew[:, None] - E[None], axis=2)
            if d.min(axis=1).max() < 1e-6 * self.lam:
                return g2, Enew, d.argmin(axis=1)
        raise ValueError(f"symmetry {self.G[s]} does not map a {c['type']} outline onto itself")

    def _set_orientations(self, rules, choice):
        for k, cs in rules.items():
            for c in cs:
                g2, E, _ = self._relabel(c, choice.get((k, c['type']), 0))
                c['g'], c['exact'] = g2, E
                c['p'] = E[0] - self.templates[k][0]

    def _choose_orientations(self, rules):
        """Pick the as-drawn orientation/placement for every child (vertex 0
        onto vertex 0, kept as is - no search). Also stamps g0/exact0, the
        reference _relabel() turns are measured against."""
        for cs in rules.values():
            for c in cs:
                c['g0'], c['exact0'] = c['g'], c['exact']
        self._set_orientations(rules, {})

    def _exact_tile(self, t, fit):
        """the template of type t placed exactly at a fitted orientation."""
        T = self.templates[t]
        return fit['poly'][0] + (T - T[0]) @ self.Q[fit['g']].T

    def _tile_frame(self, tile_type, coords):
        """(group element, vertex-0 position) of a tile: the element of G whose
        orientation of the template fits the tile best."""
        T = self.templates[tile_type]
        C = np.asarray(coords, dtype=float)
        D = T - T[0]
        res = np.abs((C - C[0])[None] - np.einsum('ij,gkj->gik', D, self.Q)).max(axis=(1, 2))
        gi = int(res.argmin())
        if res[gi] > 0.1 * np.linalg.norm(D[1]):
            raise ValueError(f"a {tile_type} tile matches no orientation of its template "
                             f"(residual {res[gi]:.3f})")
        return gi, C[0]

    def correction_report(self):
        """what the rule correction changed, in words."""
        kind = 'D' if any(s for _, s in self.G) else 'C'
        lines = [f"orientation group: {kind}{self.N if kind == 'C' else self.N} "
                 f"({len(self.G)} elements; angle quantum {self.angle_quantum} deg)",
                 f"inflation factor 1/lam = {1 / self.lam:.6f} "
                 f"(as drawn {1 / self.lam_drawn:.6f})",
                 f"edge lengths {np.round(self.edge_lengths, 6).tolist()}",
                 f"largest template vertex moved {self.template_correction:.2e} (tile edges)",
                 f"largest child vertex moved {self.child_correction:.2e} (child edges)",
                 f"parent corners off child vertices after the fit: {self.corner_residual:.2e} (child edges)",
                 f"vertex module rank {self.r} (perpendicular dimension "
                 f"{self.r - 2}); basis from {'edge vectors' if self.basis_edges is not None else 'LLL combinations'}, "
                 f"fit residual {self.module_residual:.1e}"]
        if self.decorated:
            lines.append(f"decorated tiles (rule less symmetric than outline): {self.decorated} "
                         f"- run fix_decorations() to check/repair (not done automatically)")
        if getattr(self, 'relabelled', None):
            lines.append("children turned by an outline symmetry so the tiling has no decoration "
                         "conflicts ((parent, child): (rotation step, reflected)): " + str(self.relabelled))
        if getattr(self, 'relabel_overlaps', 0):
            lines.append(f"DECORATION CONFLICTS REMAIN: {self.relabel_overlaps}")
        if self.inflation_rotation:
            lines.append(f"each generation turned by {self.inflation_rotation:g} deg (drawing artefact absorbed)")
        if any(self.frame_offsets.values()):
            lines.append(f"templates re-drawn turned by {self.frame_offsets} deg")
        return '\n'.join(lines)

    def apply_rule(self, tile_type, coords, rules, supertiles):
        """
        Inflate one tile into its subtiles: Q' = Q R_j, x' = (x + Q p_j) / lam.

        Returns list of (new_type, new_coords) tuples.
        """
        gi, x = self._tile_frame(tile_type, coords)
        Q = self.Q[gi]
        new_tiles = []
        for c in rules.get(tile_type, []):
            g2 = self.gmul_table[gi, c['g']]
            T = self.templates[c['type']]
            new_coords = (x + Q @ c['p']) / self.lam + (T - T[0]) @ self.Q[g2].T
            new_tiles.append((c['type'], new_coords))
        return new_tiles

    def remove_duplicates(self, tiles, tol=1e-2):
        """Remove duplicate tiles based on centre position."""
        seen = set()
        unique_tiles = []
        for t, coords in tiles:
            center = (tuple(np.round(self.incenter(coords) / tol) * tol)
                      if len(coords) == 3
                      else tuple(np.round(np.mean(coords, axis=0) / tol) * tol))
            key = (t, center)
            if key not in seen:
                seen.add(key)
                unique_tiles.append((t, coords))
        return unique_tiles

    def substitute(self, initial_tiles, rules, supertiles, generations=1):
        """Apply recursive substitution; returns [(tile_type, coords), ...]."""
        tiles = initial_tiles
        for _ in range(generations):
            new_tiles = []
            for tile_type, coords in tiles:
                new_tiles.extend(
                    self.apply_rule(tile_type, coords, rules, supertiles))
            tiles = self.remove_duplicates(new_tiles)

        return [(t, c) for t, c in tiles]

    # -------------------------------------------------------------------------
    # Vertex module: minimal Z-basis
    # -------------------------------------------------------------------------
    # Every vertex of the tiling is a sum of edge vectors g.e (g in G, e an
    # edge of some template). Integer relations among those vectors are
    # found by LLL (reusing _lll_reduce above, on the drawing's own edge
    # vectors - not assuming any particular algebraic structure such as a
    # root of unity ahead of time, so this generalizes to any rule, even one
    # whose edge lengths or inflation factor are irrational in a way that
    # isn't a cyclotomic integer, e.g. a + b sqrt2); the vectors are then
    # expressed in a Z-basis of the module they span - chosen from the edges
    # themselves whenever some r of them are unimodular. The basis size r is
    # the hyperspace dimension.

    def _build_module(self, dedup=1e-2, weight=100.0, max_combos=200000):
        # every edge g.e, deduplicated up to sign into a list of distinct vectors
        uniq, edge_ref = [], {}
        for gi, Q in enumerate(self.Q):
            for t, T in self.templates.items():
                E = np.roll(T, -1, axis=0) - T
                for i, e in enumerate(E @ Q.T):
                    for ui, u in enumerate(uniq):
                        if np.linalg.norm(e - u) < dedup:
                            edge_ref[gi, t, i] = (ui, 1); break
                        if np.linalg.norm(e + u) < dedup:
                            edge_ref[gi, t, i] = (ui, -1); break
                    else:
                        if np.arctan2(e[1], e[0]) % (2 * np.pi) >= np.pi - 1e-9:
                            e, sgn = -e, -1
                        else:
                            sgn = 1
                        edge_ref[gi, t, i] = (len(uniq), sgn)
                        uniq.append(e)
        order = sorted(range(len(uniq)), key=lambda i: (round(np.linalg.norm(uniq[i]), 3),
                                                        round(np.arctan2(uniq[i][1], uniq[i][0]), 6)))
        remap = {old: new for new, old in enumerate(order)}
        V = np.array([uniq[i] for i in order])
        edge_ref = {key: (remap[u], s) for key, (u, s) in edge_ref.items()}
        n = len(V)

        # integer relations: LLL on [I | weight * V]
        red = _lll_reduce(np.hstack([np.eye(n), weight * V]))
        U = np.round(red[:, :n]).astype(np.int64)
        res = np.linalg.norm(U @ V, axis=1)
        srt = np.sort(res)
        gaps = srt[1:] / np.maximum(srt[:-1], 1e-12)
        # relations are the rows with (near-)zero residual; split at the
        # biggest jump in residual, and only if it really is a jump
        cut = int(np.argmax(gaps)) + 1 if len(gaps) and gaps.max() > 5 and srt[0] < dedup else 0
        thresh = srt[cut - 1] if cut else -1.0
        is_rel = res <= thresh
        r = n - int(is_rel.sum())
        if r < 2:
            raise ValueError("edge vectors span less than the plane")
        if round(abs(np.linalg.det(U))) != 1:
            raise ValueError("LLL transform is not unimodular")
        Uinv = np.round(np.linalg.inv(U)).astype(np.int64)
        coords = Uinv[:, ~is_rel]                      # coords of V in the LLL basis

        # prefer a basis made of actual edge vectors
        chosen = None
        for c, combo in enumerate(itertools.combinations(range(n), r)):
            if c >= max_combos:
                break
            if round(abs(np.linalg.det(coords[list(combo)]))) == 1:
                chosen = list(combo); break
        if chosen is not None:
            Cb = coords[chosen]
            coords = np.round(coords @ np.linalg.inv(Cb)).astype(np.int64)
        self.basis_edges = chosen

        # physical images of the basis, least squares over every edge
        Bt, *_ = np.linalg.lstsq(coords.astype(float), V, rcond=None)
        self.basis = Bt.T                               # (2, r)
        self.module_residual = np.abs(coords @ Bt - V).max()
        if self.module_residual > 5 * dedup:
            raise ValueError(f"module fit failed (residual {self.module_residual:.3g}); "
                             f"relations misidentified -- check the drawing's precision")
        self.r = r
        self.relation_gap = (srt[cut] / max(thresh, 1e-12)) if cut else np.inf

        # exact integer coords of every edge / vertex of every oriented template
        self.edge_coords = [{t: np.array([s * coords[u] for i in range(len(T))
                                           for (u, s) in [edge_ref[gi, t, i]]])
                             for t, T in self.templates.items()}
                            for gi in range(len(self.G))]
        self.vtx_coords = [{t: np.vstack([np.zeros(r, dtype=np.int64),
                                          np.cumsum(E, axis=0)[:-1]])
                            for t, E in ec.items()}
                           for ec in self.edge_coords]
        for ec in self.edge_coords:
            for t, E in ec.items():
                if np.any(E.sum(axis=0)):
                    raise ValueError(f"template {t} doesn't close in the module")

        # G acts on the module by integer matrices (the identity-orientation
        # edges alone needn't span the module over Q, so solve on the edges
        # of every orientation at once)
        Cs = np.hstack([np.hstack([self.edge_coords[h][t].T for t in self.templates])
                        for h in range(len(self.G))])
        Cs_pinv = np.linalg.pinv(Cs.astype(float))
        self.Rm = np.zeros((len(self.G), r, r), dtype=np.int64)
        for gi in range(len(self.G)):
            Ds = np.hstack([np.hstack([self.edge_coords[self.gmul_table[gi, h]][t].T
                                       for t in self.templates])
                            for h in range(len(self.G))])
            Rg = np.round(Ds @ Cs_pinv).astype(np.int64)
            if np.any(Rg @ Cs != Ds):
                raise ValueError("orientation group does not act on the module "
                                 "by integer matrices")
            self.Rm[gi] = Rg

    # -------------------------------------------------------------------------
    # Indexing: exact integer coordinates by walking shared edges
    # -------------------------------------------------------------------------

    @staticmethod
    def _cluster_labels(verts, tol):
        """union-find clusters of near-coincident points -> compact labels"""
        parent = list(range(len(verts)))

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        for i, j in KDTree(verts).query_pairs(r=tol):
            ri, rj = find(i), find(j)
            if ri != rj:
                parent[rj] = ri
        roots = np.array([find(i) for i in range(len(verts))])
        _, lab = np.unique(roots, return_inverse=True)
        return lab

    def _walk(self, polys, origin, scale, name):
        """Integer coordinates of every vertex of a patch of polygons.

        polys  : list of (type, g, P) -- P oriented as template `type`
                 under group element g
        origin : the point that gets coordinates 0 (must be a vertex)
        scale  : edge-length multiplier of the polygons (lam for a rule,
                 1 for a seed patch)

        Each polygon edge is a known module element (edge i of template t
        under g), so every hop adds an exact integer vector -- nothing is
        fitted. Returns (per-polygon vertex coords, cluster centres, cluster
        coords, fit error)."""
        verts = np.vstack([P for _, _, P in polys])
        tol = 0.1 * scale
        lab = self._cluster_labels(verts, tol)
        m = lab.max() + 1
        centres = np.array([verts[lab == c].mean(axis=0) for c in range(m)])
        spans, adj, o = [], [[] for _ in range(m)], 0
        for t, g, P in polys:
            L = lab[o:o + len(P)]; spans.append(L); o += len(P)
            E = self.edge_coords[g][t]
            for i in range(len(P)):
                a, b = L[i], L[(i + 1) % len(P)]
                adj[a].append((b, E[i])); adj[b].append((a, -E[i]))

        d = np.linalg.norm(centres - origin, axis=1)
        root = int(np.argmin(d))
        cc = [None] * m
        cc[root] = np.zeros(self.r, dtype=np.int64)
        queue, conflicts = deque([root]), 0
        while queue:
            a = queue.popleft()
            for b, e in adj[a]:
                if cc[b] is None:
                    cc[b] = cc[a] + e; queue.append(b)
                elif np.any(cc[b] != cc[a] + e):
                    conflicts += 1
        missing = sum(c is None for c in cc)
        if missing:
            raise ValueError(f"{name}: {missing} of {m} vertices unreachable "
                             f"along shared edges -- patch is not edge-to-edge")
        if conflicts:
            raise ValueError(f"{name}: {conflicts // 2} edges give inconsistent "
                             f"integer coordinates -- merged vertices or "
                             f"orientations are wrong")
        cc = np.array(cc)
        if d[root] > tol:
            # the origin is not a vertex of the patch: bridge from the
            # nearest vertex using a short lattice vector
            cc = cc - self._fit_short((origin - centres[root]) / scale, f"{name} origin")
        err = np.abs(cc @ self.basis.T * scale - (centres - origin)).max() / scale
        return [cc[L] for L in spans], centres, cc, err

    def _fit_short(self, v, what, tol=0.02, margin=5.0):
        """Integer label n with basis @ n = v, for a SHORT vector v (a couple
        of edges long, in edge units): exhaustive search over small
        coefficients. Few enough candidates exist that exactly one lands
        within drawing noise of v; anything ambiguous is refused, not
        guessed. Used only to reach points that aren't patch vertices."""
        r = self.r
        K = {2: 12, 3: 8, 4: 6, 5: 4, 6: 3}.get(r)
        if K is None:
            raise ValueError(f"{what}: can't bridge to a non-vertex point in rank {r}")
        if getattr(self, '_short_table', (None,))[0] != (r, K):
            grid = np.stack(np.meshgrid(*[np.arange(-K, K + 1)] * r, indexing='ij'),
                            -1).reshape(-1, r).astype(np.int64)
            self._short_table = ((r, K), grid, grid @ self.basis.T)
        _, grid, img = self._short_table
        dist = np.linalg.norm(img - v, axis=1)
        order = np.argsort(dist)[:2]
        best, second = dist[order[0]], dist[order[1]]
        if best > tol or second < margin * max(best, 1e-3):
            raise ValueError(f"{what}: no unambiguous short lattice vector for "
                             f"offset {np.round(v, 4)} (best {best:.3g}, next "
                             f"{second:.3g}) -- the point may not be in the module")
        return grid[order[0]]

    def index_rules(self, rules):
        """Exact integer index of every child vertex relative to its parent's
        vertex 0, in child-edge units. Adds 'm' (vertex 0) and 'verts' (all
        vertices) to each child; also records each parent corner's index.
        Walks the CORRECTED geometry (c['exact']), not the raw drawing."""
        self.corner_idx, self.walk_err = {}, {}
        for k, kids in rules.items():
            T = self.templates[k]
            vc, centres, cc, err = self._walk(
                [(c['type'], c['g'], c['exact']) for c in kids],
                T[0], self.lam, f"rule {k}")
            for c, v in zip(kids, vc):
                c['m'], c['verts'] = v[0], v
            corners = []
            for ci, P in enumerate(T):
                d = np.linalg.norm(centres - P, axis=1)
                i = int(np.argmin(d))
                if d[i] > 0.1 * self.lam:
                    # overhanging rule: the corner lies inside a child tile
                    corners.append(cc[i] + self._fit_short((P - centres[i]) / self.lam,
                                                           f"rule {k} corner {ci}"))
                else:
                    corners.append(cc[i])
            self.corner_idx[k] = np.array(corners)
            self.walk_err[k] = err
        return rules

    def _build_inflation(self):
        """integer A with A c(v) = c(v / lam): parent template edges (unit
        scale) against the same edges measured in child units"""
        Cs, Ds = [], []
        for gi in range(len(self.G)):
            for k in self.templates:
                Cs.append(self.Rm[gi] @ self.vtx_coords[0][k].T)
                Ds.append(self.Rm[gi] @ self.corner_idx[k].T)
        Cs, Ds = np.hstack(Cs), np.hstack(Ds)
        A = np.round(Ds @ np.linalg.pinv(Cs.astype(float))).astype(np.int64)
        if np.any(A @ Cs != Ds):
            raise ValueError("parent corners are not an integer linear image "
                             "of the parent edges -- no consistent inflation")
        for Rg in self.Rm:
            if np.any(A @ Rg != Rg @ A):
                raise ValueError("inflation does not commute with the rotations")
        self.A = A
        # physical action of A: delta times a rotation (the inflation's own)
        self.M_phys = self.basis @ A @ np.linalg.pinv(self.basis)
        self.delta = float(np.sqrt(abs(np.linalg.det(self.M_phys))))
        self.eigs = np.linalg.eigvals(A.astype(float))

    # -------------------------------------------------------------------------
    # Projections
    # -------------------------------------------------------------------------
    # B : R^r -> R^2 (the basis) is the physical projection; its kernel is
    # perpendicular space. The physical subspace inside R^r is the unique
    # 2-plane J with B J = I that A stretches by delta and G rotates exactly
    # as in the plane -- then perp coordinates are n - J B n, written in a
    # basis of ker B in which G acts orthogonally.

    def _build_projection(self):
        r, B = self.r, self.basis
        I2 = np.eye(2)
        rows, rhs = [np.kron(B, I2)], [I2.ravel()]
        Mp = self.delta * self._rot_matrix(self.inflation_rotation)
        rows.append(np.kron(self.A, I2) - np.kron(np.eye(r), Mp.T)); rhs.append(np.zeros(2 * r))
        for gi in range(len(self.G)):
            rows.append(np.kron(self.Rm[gi], I2) - np.kron(np.eye(r), self.Q[gi].T))
            rhs.append(np.zeros(2 * r))
        M, b = np.vstack(rows), np.concatenate(rhs)
        j, *_ = np.linalg.lstsq(M, b, rcond=None)
        sv = np.linalg.svd(M, compute_uv=False)
        self.phys_ambiguity = int(np.sum(sv < 1e-8 * sv[0]))
        self.phys_residual = np.abs(M @ j - b).max()
        J = j.reshape(r, 2)
        Pperp = np.eye(r) - J @ B

        self.d = r - 2
        if self.d == 0:                                 # periodic: no perp space
            self.perp = np.zeros((0, r))
            self.R_perp = np.zeros((len(self.G), 0, 0))
            self.A_perp = np.zeros((0, 0))
            self.contraction = 0.0
            return

        K = np.linalg.svd(B)[2][2:].T                   # (r, d) basis of ker B
        Kp = np.linalg.pinv(K)
        Rp = np.array([Kp @ Rg @ K for Rg in self.Rm])
        S = sum(Rg.T @ Rg for Rg in Rp) / len(Rp)        # G-invariant metric
        L = np.linalg.cholesky(S)
        M2 = L.T
        if r == 4:          # fix the free rotation: perp(b0) along +x
            v = M2 @ Kp @ Pperp[:, 0]
            M2 = self._rot_matrix(-np.degrees(np.arctan2(v[1], v[0]))) @ M2
        self.perp = M2 @ Kp @ Pperp                      # (d, r)
        Mi = np.linalg.inv(M2)
        self.R_perp = np.array([M2 @ Rg @ Mi for Rg in Rp])
        self.A_perp = M2 @ Kp @ self.A @ K @ Mi
        self.contraction = float(np.max(np.abs(np.linalg.eigvals(self.A_perp))))

    # -------------------------------------------------------------------------
    # Symmetry and canonical labelling
    # -------------------------------------------------------------------------
    # Stab(t): elements h of G mapping template t onto itself, with the
    # vertex c_h that vertex 0 lands on -- the same tile then also reads as
    # (g h, x + R_g c_h). Overlapping rules can produce such relabelled
    # copies of one tile, so labels are canonicalised over Stab(t) before
    # de-duplicating in hyperspace. That is only sound for the symmetries
    # the RULE shares (a hexagon whose rule is a 3-fold pinwheel is a
    # decorated tile, and turning it by 60 deg gives a different tile), so
    # Stab(t) is cut down to the shape symmetries under which t's rule is
    # unchanged - iterated to a self-consistent fixed point.

    def _build_symmetry(self):
        self.stab = {}
        for t, T in self.templates.items():
            Tp = T - T[0]
            S = []
            for gi, Q in enumerate(self.Q):
                P = Tp @ Q.T
                for i in range(len(Tp)):
                    D = np.linalg.norm((P + Tp[i])[:, None] - Tp[None], axis=2)
                    if D.min(axis=1).max() < 1e-2:
                        S.append((gi, self.vtx_coords[0][t][i])); break
            self.stab[t] = S               # S[0] is the identity

        def children(k, h, c):
            one = {'type': np.array([self.type_names.index(k)]), 'g': np.array([h]),
                   'x': c[None, :].copy(), 'piece': np.array([-1])}
            kids = self.substitute_hyper(one, 1, canonical=True)
            return {tuple(row) for row in np.column_stack([kids['type'], kids['g'], kids['x']])}

        self.shape_stab = {t: list(S) for t, S in self.stab.items()}
        changed = True
        while changed:
            changed = False
            for k in self.type_names:
                ref = children(k, *self.stab[k][0])
                keep = [(h, c) for h, c in self.stab[k] if children(k, h, c) == ref]
                if len(keep) < len(self.stab[k]):
                    self.stab[k] = keep
                    changed = True
        # tiles whose rule carries less symmetry than their outline: turning
        # one by an outline symmetry not in stab gives a genuinely different
        # tile (a decorated square, the 3-fold hex) - these are the only
        # ones fix_decorations() can do anything about.
        self.decorated = {t: (len(self.shape_stab[t]), len(self.stab[t]))
                          for t in self.type_names
                          if len(self.stab[t]) < len(self.shape_stab[t])}

    def _label_conflicts(self, generations=3):
        """Tiles produced twice with DIFFERENT decorations, per type, over a
        few generations from each prototile - exact (integer hyperspace
        vertex sets), not a geometric-overlap heuristic. Overhanging rules
        make neighbouring supertiles generate the same tile, and they must
        agree on its label (which corner is vertex 0, i.e. which way its
        own substitution faces); if they don't, this is nonzero - usually a
        child drawn starting at the wrong corner, or a rule made by
        mirroring another. Returns {type: worst count over every seed}."""
        found = defaultdict(int)
        for k in self.type_names:
            T = self.substitute_hyper(self._single_tile(k), generations)
            for ti, t in enumerate(self.type_names):
                sel = np.where(T['type'] == ti)[0]
                if len(sel) < 2:
                    continue
                V = T['x'][sel][:, None, :] + np.stack(
                    [self.vtx_coords[g][t] for g in T['g'][sel]])
                V = np.sort(V.reshape(len(sel), -1, self.r).view(
                    [('', V.dtype)] * self.r).squeeze(-1), axis=1)   # same vertex set
                _, counts = np.unique(V, axis=0, return_counts=True)
                found[t] = max(found[t], int((counts > 1).sum()))
        return {t: n for t, n in found.items() if n}

    def decoration_conflicts(self, generations=3):
        """Which rule children disagree. Grows a few generations from each
        prototile; wherever one tile is produced twice with different
        labels, the two rule children that made the copies are recorded.
        Returns (per-child counts {(rule, index): n}, pair counts
        {((rule, index), (rule, index)): n})."""
        where = [(k, j) for k in self.type_names for j in range(len(self.rules[k]))]
        per_child, pairs = defaultdict(int), defaultdict(int)
        for k in self.type_names:
            T = self.substitute_hyper(self._single_tile(k), generations)
            if not len(T['type']) or T['piece'][0] < 0:
                continue
            for ti, t in enumerate(self.type_names):
                sel = np.where(T['type'] == ti)[0]
                if len(sel) < 2:
                    continue
                V = T['x'][sel][:, None, :] + np.stack(
                    [self.vtx_coords[g][t] for g in T['g'][sel]])
                V = np.sort(V.reshape(len(sel), -1, self.r).view(
                    [('', V.dtype)] * self.r).squeeze(-1), axis=1)
                _, inv, counts = np.unique(V, axis=0, return_inverse=True, return_counts=True)
                inv = inv.ravel()
                for grp in np.where(counts > 1)[0]:
                    who = sorted({where[p] for p in T['piece'][sel[inv == grp]]})
                    for w in who:
                        per_child[w] += 1
                    for a, b in itertools.combinations(who, 2):
                        pairs[a, b] += 1
        return dict(per_child), dict(pairs)

    def _refresh_exact(self, k, c):
        """keep c['exact']/'p'/'verts' (the float geometry) in sync with its
        (m, g) hyperspace label, for anything that still reads it after a
        relabelling - e.g. the "clean rules SVG" preview."""
        T0 = self.templates[k][0]
        verts = c['m'] + self.vtx_coords[c['g']][c['type']]
        c['verts'] = verts
        c['exact'] = T0 + self.lam * (verts @ self.basis.T)
        c['p'] = c['exact'][0] - T0

    def _relabel_hyper(self, k, j, h, ch):
        """Turn child j of rule k by stabilizer element (h, ch) - same
        geometry, different (g, m) label (see fix_decorations)."""
        c = self.rules[k][j]
        c['m'] = c['m'] + self.Rm[c['g']] @ ch
        c['g'] = int(self.gmul_table[c['g'], h])
        self._refresh_exact(k, c)
        self._piece_off = None

    def _set_turns(self, choice):
        """Reset every decorated child to the as-drawn baseline, then apply
        `choice` = {(parent_type, child_type): rep_index} - every child of
        that pair turned by self._deco_reps[child_type][rep_index]."""
        for k, j, m0, g0 in self._deco_baseline:
            c = self.rules[k][j]
            c['m'], c['g'] = m0.copy(), g0
            self._refresh_exact(k, c)
        for (k, ty), i in choice.items():
            if not i:
                continue
            h, ch = self._deco_reps[ty][i]
            for c in self.rules[k]:
                if c['type'] == ty:
                    c['m'] = c['m'] + self.Rm[c['g']] @ ch
                    c['g'] = int(self.gmul_table[c['g'], h])
                    self._refresh_exact(k, c)
        self._piece_off = None

    def fix_decorations(self, generations=3, max_full=4096):
        """Search decorated children's labelling for one with no decoration
        conflicts (see _label_conflicts) - the exact criterion for whether
        this rule tiles without contradiction, replacing a geometric-
        overlap heuristic with the thing that's actually wrong. Not run
        automatically (even though it's usually fast): call it explicitly
        - e.g. from a "clean rules SVG" action - to diagnose and repair a
        rules SVG, since loading one should "just work" without it when the
        drawing is already consistent.

        Mutates self.rules in place (turns some children by an outline
        symmetry of their own type - same geometry, different label; see
        _relabel_hyper). Returns the (parent_type, child_type) pairs worth
        a second look in the drawing: every pair actually turned away from
        how it was drawn, or - if no combination removes every conflict -
        every decorated pair, since which one is at fault can't be told
        apart at that point.
        """
        self.label_conflicts = self._label_conflicts(generations)
        base = sum(self.label_conflicts.values())
        self.relabelled, self.relabel_overlaps = {}, base
        self.ambiguous_pairs = sorted(
            {(k, c['type']) for k in self.type_names for c in self.rules[k]
             if c['type'] in self.decorated})
        if base == 0 or not self.decorated:
            return []

        N = self.N
        reps = {}
        for ty in self.decorated:
            dec = {self.G[h][0] for h, _ in self.stab[ty] if not self.G[h][1]}
            chosen, covered = [], set()
            for h, c in sorted(self.shape_stab[ty],
                               key=lambda hc: (self.G[hc[0]][1], self.G[hc[0]][0])):
                if self.G[h][1]:
                    continue                        # turns only
                kk = self.G[h][0]
                if kk in covered:
                    continue
                chosen.append((h, c))
                covered |= {(kk + d) % N for d in dec}
            reps[ty] = chosen
        self._deco_reps = reps
        self._deco_baseline = [(k, j, c['m'].copy(), c['g'])
                               for k in self.type_names for j, c in enumerate(self.rules[k])]

        pairs = self.ambiguous_pairs
        options = [range(len(reps[t])) for _, t in pairs]
        best = (base, {})

        def score(choice):
            self._set_turns(choice)
            return sum(self._label_conflicts(generations).values())

        if np.prod([len(o) for o in options], dtype=float) <= max_full:
            for combo in product(*options):
                choice = dict(zip(pairs, combo))
                n = score(choice)
                if n < best[0]:
                    best = (n, choice)
                    if n == 0:
                        break
        else:                                         # coordinate descent from the drawn labels
            improved = True
            while improved and best[0]:
                improved = False
                for pair, opts in zip(pairs, options):
                    for s in opts:
                        choice = {**best[1], pair: s}
                        n = score(choice)
                        if n < best[0]:
                            best, improved = (n, choice), True
        self._set_turns(best[1])
        self.relabelled = {pair: self.G[reps[pair[1]][s][0]]
                          for pair, s in best[1].items() if s}
        self.label_conflicts = self._label_conflicts(generations)
        self.relabel_overlaps = sum(self.label_conflicts.values())
        if self.relabel_overlaps:
            print(f"  warning: no relabelling of the children removes every decoration "
                  f"conflict ({self.relabel_overlaps} remain) - check the drawing")
            return pairs
        return list(self.relabelled)

    def child_path_ids(self, rules=None):
        """{(rule, child index): SVG path id}, so a flagged child can be
        found in Inkscape (Edit > Find, or the XML editor), and so
        rewrite_svg() knows which path to rewrite."""
        tiling, _ = self.parse_svg(self.svg_path)
        ids = {}
        for k, kids in (self.rules if rules is None else rules).items():
            layer = tiling.get(f"sub{k}", {'tiles': {}})['tiles']
            cand = {pid: self._clean_poly(P) / self.drawing_scale
                    for pid, P in layer.items() if len(P) >= 3 and np.ptp(P) > 0}
            used = set()
            for j, c in enumerate(kids):
                D = c['drawn']
                best = sorted((np.linalg.norm(P[:, None] - D[None], axis=2).min(1).max(), pid)
                              for pid, P in cand.items() if len(P) == len(D))
                best = [(d, pid) for d, pid in best if d < 0.1 * self.lam]
                pick = next((pid for d, pid in best if pid not in used), None) or \
                    (best[0][1] if best else None)
                if pick is not None:
                    ids[k, j] = pick
                    used.add(pick)
        return ids

    def decoration_changes(self):
        """(parent_type, child_index) pairs whose (m, g) label differs from
        how they were originally drawn - i.e. what fix_decorations() has
        actually changed so far, across every call (there may have been
        more than one "attempt to fix" round). Empty before fix_decorations
        is ever called, or if it never found an improvement to make."""
        baseline = getattr(self, '_as_drawn_child_state', None)
        if not baseline:
            return []
        return [(k, j) for k, j, m0, g0 in baseline
               if not (np.array_equal(self.rules[k][j]['m'], m0)
                       and self.rules[k][j]['g'] == g0)]

    def rewrite_svg(self, out_path=None):
        """Write a corrected copy of the rules SVG reflecting whatever
        relabelling fix_decorations() applied - same corners and winding,
        just a different start vertex per affected child, the minimum
        change that makes the drawing agree with itself. The original
        file is left untouched.

        Returns the path written, or None if fix_decorations() hasn't
        found (or needed) any change to apply - across every call so far,
        if it's been called more than once (e.g. "attempt to fix" clicked
        again after one round still left some conflicts).
        """
        changed = self.decoration_changes()
        if not changed:
            return None

        ids = self.child_path_ids()
        svg = open(self.svg_path, encoding='utf-8').read()
        written = 0
        for k, j in changed:
            pid = ids.get((k, j))
            if pid is None:
                continue
            c = self.rules[k][j]
            m = re.search(r'<path\b[^>]*?\bid="' + re.escape(pid) + r'"[^>]*?/>', svg, re.S)
            if m is None:
                continue
            el = m.group(0)
            dm = re.search(r'\bd="([^"]+)"', el)
            if dm is None:
                continue
            d_attr = dm.group(1)
            local = self._clean_poly(np.array(self.parse_path_d(d_attr)))
            if len(local) != len(c['drawn']):
                continue
            # same physical polygon, drawn vs now-corrected: for each
            # corrected vertex, which drawn (= local, same index order)
            # vertex is it - the new start corner/winding, nothing else
            order = [int(np.argmin(np.linalg.norm(c['drawn'] - v, axis=1)))
                    for v in c['exact']]
            new_d = 'M ' + ' '.join(f'{x:.6f},{y:.6f}' for x, y in local[order]) + ' Z'
            svg = svg.replace(el, el.replace(f'd="{d_attr}"', f'd="{new_d}"'), 1)
            written += 1
        if not written:
            return None

        if out_path is None:
            root, ext = os.path.splitext(self.svg_path)
            out_path = f"{root}_fixed{ext}"
        with open(out_path, 'w', encoding='utf-8') as f:
            f.write(svg)
        return out_path

    # -------------------------------------------------------------------------
    # Substitution in hyperspace
    # -------------------------------------------------------------------------

    def pieces(self):
        """flat list of (parent type index, child) over all rules"""
        return [(self.type_names.index(k), c) for k in self.type_names
                for c in self.rules[k]]

    def _n_kids(self):
        return np.bincount([k for k, _ in self.pieces()], minlength=len(self.type_names))

    def _single_tile(self, start):
        return {'type': np.array([self.type_names.index(start)]),
                'g': np.array([0]), 'x': np.zeros((1, self.r), dtype=np.int64),
                'piece': np.array([-1])}

    def _index_seed(self, seed_raw):
        polys = [(t, f['g'], self._exact_tile(t, f)) for t, f in seed_raw]
        vc, *_ = self._walk(polys, polys[0][2][0], 1.0, "seed")
        return {'type': np.array([self.type_names.index(t) for t, _ in seed_raw]),
                'g': np.array([f['g'] for _, f in seed_raw]),
                'x': np.array([v[0] for v in vc]),
                'piece': -np.ones(len(seed_raw), dtype=int)}

    def _canonical(self, tiles):
        """relabel each tile to the lexicographically smallest equivalent
        (g, x) over its template's symmetry group"""
        tiles = dict(tiles)
        for ti, t in enumerate(self.type_names):
            S = self.stab[t]
            sel = np.where(tiles['type'] == ti)[0]
            if len(S) < 2 or not len(sel):
                continue
            g, x = tiles['g'][sel], tiles['x'][sel]
            cand = np.stack([np.column_stack([self.gmul_table[g, h],
                                              x + np.einsum('nab,b->na', self.Rm[g], c)])
                             for h, c in S], axis=1)        # (n, |S|, 1 + r)
            valid = np.ones(cand.shape[:2], dtype=bool)
            for col in range(cand.shape[2]):
                v = np.where(valid, cand[:, :, col], np.iinfo(np.int64).max)
                valid &= v == v.min(axis=1, keepdims=True)
            best = cand[np.arange(len(sel)), np.argmax(valid, axis=1)]
            tiles['g'] = tiles['g'].copy(); tiles['x'] = tiles['x'].copy()
            tiles['g'][sel], tiles['x'][sel] = best[:, 0], best[:, 1:]
        return tiles

    def _step(self, tiles, canonical=True):
        """one substitution step in hyperspace, without removing duplicates"""
        pieces = self.pieces()
        if getattr(self, '_piece_off', None) is None:
            self._piece_off = np.einsum('gab,pb->pga', self.Rm,
                                        np.array([c['m'] for _, c in pieces]))
        off = self._piece_off
        new = defaultdict(list)
        for p, (k, c) in enumerate(pieces):
            sel = tiles['type'] == k
            if not sel.any():
                continue
            g = tiles['g'][sel]
            new['type'].append(np.full(len(g), self.type_names.index(c['type'])))
            new['g'].append(self.gmul_table[g, c['g']])
            new['x'].append(tiles['x'][sel] @ self.A.T + off[p, g])
            new['piece'].append(np.full(len(g), p))
        tiles = {key: np.concatenate(v) for key, v in new.items()}
        return self._canonical(tiles) if canonical else tiles

    def substitute_hyper(self, tiles, generations=1, canonical=True):
        """x' = A x + R_g m_j,  g' = g * g_j  -- exact, vectorised hyperspace
        substitution (the perp=True analogue of substitute())."""
        for _ in range(generations):
            tiles = self._step(tiles, canonical)
            key = np.column_stack([tiles['type'], tiles['g'], tiles['x']])
            _, keep = np.unique(key, axis=0, return_index=True)
            tiles = {key_: v[np.sort(keep)] for key_, v in tiles.items()}
        return tiles

    def to_physical(self, tiles):
        """[(type, polygon)] with every vertex rebuilt exactly from its
        integer hyperspace coordinates"""
        out = []
        for t, g, x in zip(tiles['type'], tiles['g'], tiles['x']):
            name = self.type_names[t]
            out.append((name, (x + self.vtx_coords[g][name]) @ self.basis.T))
        return out

    def perp_coords(self):
        """Perpendicular-space coordinates of every vertex of every tile in
        self.final_tiles (same list structure: one (n, d) array per tile,
        d = self.d). Requires perp=True."""
        if not self._perp_mode:
            raise RuntimeError("perp_coords() needs inkTile(..., perp=True)")
        if self.d == 0:
            return [np.zeros((len(c), 0)) for _, c in self.final_tiles]
        out = []
        for t, g, x in zip(self.hyper['type'], self.hyper['g'], self.hyper['x']):
            name = self.type_names[t]
            verts = x + self.vtx_coords[g][name]
            out.append(verts @ self.perp.T)
        return out


# -----------------------------------------------------------------------------
# SVG writing - the reverse of parse_svg/parse_seed_svg above: instead of
# reading fill-coloured <path> polygons out of an SVG, write a flat list of
# polygons back out as one <path> per tile. The y-axis is negated on the way
# out, mirroring the negation parse_svg/parse_seed_svg apply on the way in, so
# a tiling exported here reads back in with the same orientation it was drawn.
# -----------------------------------------------------------------------------

def write_svg(filepath, polys, colors, edge_color=(0, 0, 0), edge_width=1.0):
    """Write polygons as fill-coloured SVG paths.

    Parameters
    ----------
    polys  : list of (N, 2) coordinate arrays, one polygon per tile.
    colors : list of (r, g, b) 0-255 tuples, one per polygon in `polys`.
    edge_color, edge_width : stroke applied to every tile; edge_width <= 0
        omits the stroke entirely.
    """
    polys = [np.asarray(p, dtype=float) for p in polys if len(p)]
    if polys:
        all_pts = np.vstack(polys)
        xmin, ymin = all_pts.min(axis=0)
        xmax, ymax = all_pts.max(axis=0)
    else:
        xmin = ymin = 0.0
        xmax = ymax = 1.0
    margin = 0.02 * max(xmax - xmin, ymax - ymin, 1.0)
    width = (xmax - xmin) + 2 * margin
    height = (ymax - ymin) + 2 * margin

    def path_d(coords):
        pts = [(x - xmin + margin, (ymax - y) + margin) for x, y in coords]
        head = f"M {pts[0][0]:.6f} {pts[0][1]:.6f}"
        tail = " ".join(f"L {x:.6f} {y:.6f}" for x, y in pts[1:])
        return f"{head} {tail} Z".strip()

    stroke = (f'stroke="rgb({edge_color[0]},{edge_color[1]},{edge_color[2]})" '
              f'stroke-width="{edge_width}" stroke-linejoin="round"'
              if edge_width and edge_width > 0
              else 'stroke="none"')

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{width:.6f}" height="{height:.6f}" '
        f'viewBox="0 0 {width:.6f} {height:.6f}">',
    ]
    for coords, color in zip(polys, colors):
        if len(coords) < 3:
            continue
        fill = f"rgb({int(color[0])},{int(color[1])},{int(color[2])})"
        lines.append(f'<path d="{path_d(coords)}" fill="{fill}" {stroke}/>')
    lines.append('</svg>')

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))


def write_png(filepath, polys, colors, edge_color=(0, 0, 0), edge_width=1,
               size=(1000, 1000), background=(255, 255, 255)):
    """Rasterize polygons to a PNG image.

    Unlike `write_svg`, `edge_width` here is in output pixels directly -
    there's no data-unit-vs-pixel ambiguity for a raster image the way
    there is for an SVG's own coordinate space.

    Parameters
    ----------
    polys, colors : as in `write_svg`.
    edge_color, edge_width : stroke applied to every tile, in pixels;
        edge_width <= 0 omits the stroke entirely.
    size : (width, height) of the output image in pixels. The tiling is
        scaled to fit within this box (preserving aspect ratio, with a 5%
        margin) and centred.
    background : RGB fill for the area outside the tiling.
    """
    polys = [np.asarray(p, dtype=float) for p in polys if len(p)]
    background = tuple(int(c) for c in background)
    img = Image.new('RGB', size, background)
    if not polys:
        img.save(filepath)
        return

    all_pts = np.vstack(polys)
    xmin, ymin = all_pts.min(axis=0)
    xmax, ymax = all_pts.max(axis=0)
    span_x = max(xmax - xmin, 1e-9)
    span_y = max(ymax - ymin, 1e-9)
    scale = min(size[0] / span_x, size[1] / span_y) * 0.95
    ox = (size[0] - span_x * scale) / 2
    oy = (size[1] - span_y * scale) / 2

    draw = ImageDraw.Draw(img)
    outline = tuple(int(c) for c in edge_color) if edge_width and edge_width > 0 else None
    width = max(int(round(edge_width)), 1) if outline else 1
    for coords, color in zip(polys, colors):
        if len(coords) < 3:
            continue
        pts = [((x - xmin) * scale + ox, size[1] - ((y - ymin) * scale + oy))
               for x, y in coords]
        fill = tuple(int(c) for c in color)
        draw.polygon(pts, fill=fill, outline=outline, width=width)
    img.save(filepath)
