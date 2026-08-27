import os


def parse_rules(rules_path):
    """Use inkTile(gen=0) to extract supertile keys, colors, and template coords.

    Returns (actual_keys, type_colors, supertile_coords) where:
      actual_keys     : {display_name: actual_inkTile_key}  e.g. {'T1': 'T1_1'}
      type_colors     : {display_name: css_color_string}
      supertile_coords: {display_name: np.ndarray of polygon vertices}
    """
    from .. import ink2tile as _m
    from ..ink2tile import inkTile

    stem = os.path.splitext(rules_path)[0]
    it = inkTile(gen=0, tile=stem)

    actual_keys = {}
    supertile_coords = {}
    for key in _m.supertiles:
        base = key.rsplit('_', 1)[0]
        actual_keys[base] = key
        supertile_coords[base] = _m.supertiles[key].copy()

    _, types_raw = it.parse_svg(rules_path)
    type_colors = {base: stroke for stroke, base in types_raw.items()}

    return actual_keys, type_colors, supertile_coords
