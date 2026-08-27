import colorsys

import numpy as np


def regular_vectors(fold, shift="regular"):
    """Build a `vector_data` array for a regular `fold`-fold grid.

    Each row is (tile_length, grid_length, angle_degrees, shift) - the
    format TileMaker expects, with angles evenly spaced around the circle.
    `shift` matches the GUI's "Grid shifts" options:

    - 'regular': alternating +/-1/(fold/2) for even fold, or 1/fold for odd
      fold - the default, and what most named regular tilings use.
    - 'zero': no shift at all - the degenerate/singular case.
    - 'random': shifts drawn uniformly from (-1, 1), independent per vector.
    - 'regular_random': random shifts that sum to 1 across the whole set.
    """
    theta = 2 * np.pi / fold
    angles = [round(np.degrees(theta * i), 2) for i in range(fold)]
    shifts = _make_shifts(fold, shift)
    return np.array([(1.0, 1.0, a, s) for a, s in zip(angles, shifts)])


def _make_shifts(fold, shift):
    if shift == "regular":
        return ([1 / (fold / 2), -1 / (fold / 2)] * (fold // 2)
                if fold % 2 == 0 else [1 / fold] * fold)
    if shift == "zero":
        return [0.0] * fold
    if shift == "random":
        return list(np.round(np.random.uniform(-1, 1, fold), 3))
    if shift == "regular_random":
        r = np.random.rand(fold)
        r /= r.sum()
        return list(np.round(r, 3))
    raise ValueError(
        f"Unknown shift mode {shift!r}; expected 'regular', 'zero', "
        "'random', or 'regular_random'"
    )


def make_colors(n, scheme="default", base_color="#4a6fa5"):
    """Generate `n` visually distinct RGB colours for colouring tile types.

    This is the same colour generation the GUI uses to pick tile colours
    when you don't hand-pick your own - handy for a quick palette without
    designing one yourself.

    Parameters
    ----------
    n : int
        Number of colours to generate.
    scheme : {'default', 'tonal'}
        'default' steps hue around the full colour wheel (golden-ratio
        spacing from a random starting hue) - what the GUI uses unless you
        switch its colour scheme preference. 'tonal' instead generates `n`
        tones/shades of a single base colour.
    base_color : str
        Hex colour (e.g. '#4a6fa5'), only used when scheme='tonal'.

    Returns
    -------
    list of (r, g, b) tuples, each channel in 0-255.
    """
    if scheme == "tonal":
        return _make_tonal_colors(n, base_color)
    if scheme == "default":
        h = np.random.rand()
        colors = []
        for _ in range(n):
            h = (h + 0.618) % 1.0
            r, g, b = colorsys.hsv_to_rgb(h, 0.4, 0.8)
            colors.append((r * 255, g * 255, b * 255))
        return colors
    raise ValueError(f"Unknown scheme {scheme!r}; expected 'default' or 'tonal'")


def _make_tonal_colors(n, base_hex):
    """n distinct tones/shades around a single base colour, rather than
    the default scheme's full hue-circle spacing. Hue stays close to the
    base; saturation and value are what vary, stepped with the golden
    ratio so nearby indices still look distinct."""
    base_hex = base_hex.lstrip("#")
    r, g, b = (int(base_hex[i:i + 2], 16) / 255 for i in (0, 2, 4))
    base_h, _, _ = colorsys.rgb_to_hsv(r, g, b)
    colors = []
    gr = 0.0
    for i in range(n):
        gr = (gr + 0.618) % 1.0
        hue = (base_h + (gr - 0.5) * 0.12) % 1.0
        sat = 0.35 + 0.35 * ((i * 0.618) % 1.0)
        val = 0.55 + 0.35 * (((i * 0.382) + 0.5) % 1.0)
        rr, gg, bb = colorsys.hsv_to_rgb(hue, sat, val)
        colors.append((rr * 255, gg * 255, bb * 255))
    return colors


def classify_areas(areas):
    """Bucket raw tile areas into integer type indices.

    Tiles of the same underlying shape/type share (near-)identical area in
    these tilings, so rounding to 3 decimal places and taking the unique
    values gives a stable type label per tile - this is the same logic the
    GUI uses to decide how many colours a tiling needs.

    Returns (type_idx, unique_areas): `type_idx` is an int array parallel
    to `areas`, and `unique_areas` are the distinct rounded area values.
    """
    if len(areas) == 0:
        return np.array([], dtype=int), np.array([])
    rounded = np.round(areas, 3)
    unq = np.unique(rounded)
    out = np.zeros(len(areas), dtype=int)
    for i, u in enumerate(unq):
        out[rounded == u] = i
    return out, unq
