
import xml.etree.ElementTree as ET
import matplotlib.pyplot as plt
import numpy as np
import matplotlib.patches as patches
from matplotlib.collections import PatchCollection
from collections import defaultdict
from scipy.spatial import KDTree
import pandas as pd
from itertools import product
import pickle


class inkTile:
    def __init__(self, gen, start=None, tile=None,
                 seed=None):
        """
        Parameters
        ----------
        gen   : int
            Number of inflation generations.
        start : str, optional
            Tile type to begin from (e.g. 'T1'). Defaults to first type found.
        mpar, npar : int, optional
            SVG file is read from mn{mpar}{npar}.svg.
        tile  : str, optional
            Explicit SVG base name (without .svg).
        seed  : str, optional
            Seed SVG base name (without .svg). Tiles inside are inflated using
            the rules from the main SVG.
        sym   : int
            Rotational symmetry order. Creates sym additional rotated copies of
            the starting tile at angles k * 2π/sym for k = 1..sym.
        idx   : bool
            If True, build integer-lattice indices instead of float coords.
        """
        if tile is not None:
            svg_file = f"{tile}.svg"
        else:
            raise ValueError("Provide 'tile' (SVG base name)")

        tiling, types = self.parse_svg(svg_file)
        tiling = self.rename_tiles_by_type(tiling, types)

        global supertiles, subtiles, globalScale
        supertiles = {}
        subtiles = {}

        for key in tiling:
            if 'super' in key:
                k, v = list(tiling[key]['tiles'].items())[0]
                supertiles[k] = v
            else:
                subtiles[key[3:]] = tiling[key]['tiles']

        first_key = list(subtiles.keys())[0]
        s1 = np.linalg.norm(supertiles[first_key][1] - supertiles[first_key][0])
        for k in subtiles:
            for key in subtiles[k]:
                if key.startswith(first_key):
                    s2 = np.linalg.norm(subtiles[k][key][1] - subtiles[k][key][0])
                    break
        globalScale = np.round(s2 / s1,6)

        scale = self.find_min_edge_length(supertiles)
        supertiles = self.normalize_tiles(supertiles, scale)

        # Snap in raw SVG units (before dividing by `scale`) so the merge
        # tolerance stays fixed in drawing units regardless of how large or
        # small any individual supertile happens to be.
        subtiles = self._snap(subtiles)
        for k in subtiles:
            subtiles[k] = {t: np.round(coords / scale, 5) for t, coords in subtiles[k].items()}
        
        self.rules = self.extract_rules(supertiles, subtiles)

        if seed is not None:
            tile_list = self.parse_seed_svg(f"{seed}.svg", types, scale)
        else:
            if start is None:
                start = list(supertiles.keys())[0]
            template = supertiles[start]
            centered = template - template[0]   # anchor vertex 0 at origin
            tile_list = [(start, centered)]
            
        self.final_tiles = self.substitute(tile_list, self.rules, supertiles, gen)
# -------------------------------------------------------------------------
    # Snap helpers
    # -------------------------------------------------------------------------
    def _snap(self, subtiles):
        # KDTree
        data = subtiles
        # Absolute tolerance in raw SVG drawing units (independent of any
        # tiling normalization scale). True coincident vertices land at
        # ~0 distance (shared path endpoints); genuinely distinct vertices
        # in these drawings are tens of units apart, so this has wide margin.
        tol = 1.0

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

        for ok, inner in data.items():

            # 1. Flatten just this outer group
            all_verts, addresses = [], []
            for ik, poly in inner.items():
                for vi, v in enumerate(poly):
                    all_verts.append(v)
                    addresses.append((ik, vi))
            all_verts = np.array(all_verts)

            # 2. KDTree pairs within this group only
            pairs = KDTree(all_verts).query_pairs(r=tol)

            # 3. Union-Find (fresh state per outer key)
            parent = list(range(len(all_verts)))
            rank   = [0] * len(all_verts)

            for i, j in pairs:
                union(parent, rank, i, j)

            # 4. Mean per group
            groups = defaultdict(list)
            for idx in range(len(all_verts)):
                groups[find(parent, idx)].append(idx)

            # merged = {root: all_verts[members][np.argmin(np.linalg.norm(all_verts[members] - all_verts[members].mean(axis=0), axis=1))]
            #         for root, members in groups.items()}
            merged = {root: all_verts[members].mean(axis=0)
                    for root, members in groups.items()}
            
            # 5. Write back into this outer group only
            for idx, (ik, vi) in enumerate(addresses):
                data[ok][ik][vi] = merged[find(parent, idx)]
            
        return data
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
        tiling : dict  – raw group data
        types  : dict  – stroke-color -> tile-type
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

    def parse_seed_svg(self, filename, types, scale):
        """
        Parse a seed SVG containing pre-placed tiles.

        Tiles are identified by fill color (using the types mapping from the
        rules SVG). Coordinates are divided by the same scale factor so units
        match.  Group transforms are applied recursively.

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
                pts = pts #/ scale
                fill, _, _ = self.extract_style(path)
                if fill in types:
                    tile_list.append((types[fill], pts))

            for child in node.findall('svg:g', ns):
                collect_paths(child)

        collect_paths(root)
        return tile_list

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
    # Substitution
    # -------------------------------------------------------------------------

    def extract_rules(self, supertile, subtiles):
        """Build substitution rules: each entry is [sub_scale, sub_center, angle]."""
        rules = {}

        for k in supertile:
            tile = supertile[k]
            e1 = tile[1] - tile[0]
            a1 = np.degrees(np.arctan2(e1[1], e1[0]))
            a1 = round(a1*2)/2
            temp_rules = {}
            for tile_name in subtiles[k]:
                coords = subtiles[k][tile_name]
                e2 = coords[1] - coords[0]
                c2 = self.incenter(coords) if len(coords) == 3 else np.mean(coords, axis=0)
                a2 = np.degrees(np.arctan2(e2[1], e2[0]))
                a2 = round(a2*2)/2
                ang = a2 - a1
                temp_rules[tile_name] = [globalScale, np.round(c2,6), round(ang*2)/2]
            rules[k] = temp_rules
        return rules

    def apply_rule(self, tile_type, coords, rules, supertiles):
        """Inflate one tile into its subtiles. Returns list of (new_type, new_coords) tuples."""
        new_tiles = []
        rule_set = rules.get(tile_type, {})
        parent_template = supertiles[tile_type]

        if len(parent_template) == 3:
            parent_center = self.incenter(parent_template)
            current_center = self.incenter(coords)
        else:
            parent_center = np.mean(parent_template, axis=0)
            current_center = np.mean(coords, axis=0)

        e_t = parent_template[1] - parent_template[0]
        e_c = coords[1] - coords[0]
        scale = np.linalg.norm(e_c) / np.linalg.norm(e_t)
        theta = np.arctan2(e_c[1], e_c[0]) - np.arctan2(e_t[1], e_t[0])
        R_parent = np.array([[np.cos(theta), -np.sin(theta)],
                             [np.sin(theta),  np.cos(theta)]])

        def map_to_current(sub_coords):
            return (sub_coords - parent_center) * scale @ R_parent.T + current_center

        names = list(supertiles.keys())

        for key, (sub_scale, sub_center, sub_rotation_deg) in rule_set.items():
            new_type = next((name for name in names if key.startswith(name)), None)
            template = supertiles[new_type]
            temp_center = (self.incenter(template) if len(template) == 3
                           else np.mean(template, axis=0))
            theta_sub = np.radians(sub_rotation_deg)
            R_sub = np.array([[np.cos(theta_sub), -np.sin(theta_sub)],
                              [np.sin(theta_sub),  np.cos(theta_sub)]])
            subtile_local = sub_scale * (template - temp_center) @ R_sub.T + sub_center
            subtile_global = map_to_current(subtile_local)
            new_coords = subtile_global / sub_scale

            new_tiles.append((new_type, new_coords))

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