# Generating a grid tiling, step by step

1. Set **No. of vectors** to your desired symmetry order (5 for a classic
   Penrose-style tiling).
2. Leave **Grid shifts** on `Regular` unless you specifically want the more
   symmetric `Zero` variant, or a randomised one.
3. Set **No. of grids** - start small (e.g. 10) and increase once you're
   happy with the shape, since larger values render more slowly.
4. Optionally fine-tune individual vectors via **Advanced...**.
5. Click **Tile!**. HyperTiler estimates the tile count, picks a rendering
   quality tier automatically, builds the tiling, colours tiles by
   area-based "type", and draws it.
6. Pan and zoom to inspect it. Toggle **Grid view** to see the underlying
   multigrid lines, or **Point view** to see vertices only.
7. Use **Edit style...** to recolour tile types, or adjust point/edge
   styling.
8. Export with **Save as...** (PNG or SVG image) and/or
   **File → Save parameters...** (the recipe, to reopen and rebuild
   later).
