# Substitution tiling

**28/08/26: Currently updating, will be finished by next week!**

## Rules SVG, seed, and generations

Substitution tiling is driven entirely by an SVG file you prepare in
Inkscape beforehand.

### The Rules SVG

Defines every supertile type and how it subdivides. In other words: draw
the shape once as a supertile, then draw the same shape again subdivided
into smaller labelled pieces - that subdivision is the inflation rule
HyperTiler will apply repeatedly.

#### Supertile groups

Draw the supertile's outline as a single closed path, then select it and
group it (`Ctrl+G`, or `Cmd+G` on Mac - grouping a single object still
works and is required, since HyperTiler reads the *group's* label, not the
path's).

That group needs to be **labelled** `super<Type>` (e.g. `superT1`) - not
just named internally, but given that label so HyperTiler can find it.
Inkscape shows two different names for every object (`id`, an internal
identifier you rarely touch, and `label`, the human-readable one) - the
label is what to set. Open the **Objects panel** (`Object → Objects...`)
or the **XML editor** (`Ctrl+Shift+X`), find your new group, double-click
its name, and type `superT1` (or whichever type name you're using).

Set that path's fill and stroke to the **same colour** - open
**Fill and Stroke** (`Ctrl+Shift+F`), or just left-click a palette swatch
to set fill and `Shift`-left-click the same swatch to set stroke. That
shared colour becomes `<Type>`'s identifying colour for the rest of the
file. This isn't a cosmetic convention: HyperTiler reads the *stroke*
colour off the supertile path to learn "this colour means type T1", then
looks for that same colour on every other path's *fill* to decide what
type it is. If a path's fill doesn't match any supertile's colour,
HyperTiler won't know what to do with it.

#### Subtile groups

Draw the smaller tiles the supertile subdivides into, positioned and
scaled to fit exactly inside the supertile's own outline. Select all of
them and group them (`Ctrl+G`), then label that group `sub<Type>` (e.g.
`subT1`) the same way, via the Objects panel or XML editor.

Each subtile path's own **fill colour** identifies its type - a subtile
filled with `superT2`'s colour will be treated as a `T2` tile once
inflated, regardless of which supertile's `sub` group it was drawn inside.
Set fill the same way (left-click a palette swatch with the path
selected). A subtile's stroke colour doesn't matter for parsing and can be
anything - useful for just seeing the tile outlines clearly while you
draw.

#### Path requirements

Every tile - supertile or subtile - needs to be a single path made of
**straight line segments only**. Draw with the Bezier/straight-line tool
(`B`) rather than the pencil/freehand tool, and don't drag while clicking
(dragging creates curved nodes). Close the shape as you draw by clicking
back on the starting node - Inkscape will snap to it and close the path
automatically, which is simpler than closing it after the fact.

Shapes drawn with the rectangle, ellipse, or star tools won't parse, even
though they look like closed straight-edged shapes - they're a different
kind of SVG element internally. Convert any of those to a plain path first
via `Path → Object to Path` (`Shift+Ctrl+C`).

#### Transforms are real

Any transform applied to a path or its containing group - move, rotate,
scale, mirror - is baked directly into the coordinates HyperTiler reads,
not just a display-time effect. So the natural Inkscape workflow of
drawing one subtile, then duplicating it (`Ctrl+D`) and using
`Object → Flip Horizontal/Vertical` (`H`/`V`) or the rotate handles to
place the rest, works exactly as you'd want - whatever mirroring or
rotation you apply is exactly what ends up in the substitution rule, and
will be reproduced faithfully on every generation.

### Seed

What generation starts from:

- **Single tile** - one instance of a chosen supertile type, centred at the
  origin. Pick the type from the dropdown.
- **From SVG** - a separate hand-arranged SVG containing a specific
  starting patch of one or more tiles, if you want to inflate outward from
  a particular arrangement rather than a lone tile.

### Generations

How many times the subdivision rule is applied. Each generation replaces
every current tile with its rule-defined subtiles, then removes
near-duplicate tiles introduced along shared edges. Tile count grows
quickly with generation count, so HyperTiler estimates the result size in
advance and lowers rendering quality automatically for large generations.

## Using the Substitution window

1. Open it via **Tools → Substitution tiling...** - the main window
   switches into a dedicated substitution workspace (switch back any time
   via the same menu item, now labelled "Grid tiling...").
2. `Browse...` next to `Rules SVG` and select your rules file. Discovered
   tile types are listed and previewed as coloured swatches.
3. Choose a seed: either `Single tile` plus a type from the dropdown, or
   `From SVG` plus a seed file via its own `Browse...`.
4. Set `Generations` (1-10).
5. Click `Generate`. Progress and tile counts are reported as it runs.
6. Once generated, a style panel appears: click any tile-type swatch to
   recolour it, and adjust `Edge width` (set to 0 to hide tile edges
   entirely).
7. `Save as...` exports the current view as a PNG or SVG image, the same
   as in grid tiling mode.

Vertex Types, Network Builder, and Compute FFT all work on substitution
results exactly as they do for grid tilings - use the same Tools menu
items. The vertex classification here reasons directly about the angles
between tiles at each vertex, since substitution tiles don't carry the
integer-lattice structure grid tilings do, but the results are presented
identically, including the mirror-symmetric grouping option (see
{doc}`vertex_types`).

## Doing the same thing from Python

If you want to script substitution generation rather than clicking through
the window, see {doc}`../quickstart` - `hypertiler.inkTile` is the same
substitution engine the window uses underneath.
