# Styling and inspecting a tiling

The Style Dialog (**Edit style...**) adapts to whichever view mode is
active:

## Tile mode

A grid of colour swatches, one per distinct tile type (grouped by area),
each showing a mini preview of that tile's shape. Click a swatch to
recolour that type via a colour picker. `Reset colours` re-randomises all
type colours. A **tile edge colour** picker and **edge width** control let
you adjust the outline drawn around every tile.

## Point mode

A "Show tile edges" checkbox to overlay tile outlines on the points, an
edge colour picker and width control, and separate point colour and size
controls.

## Grid mode

A "Show intersection points" checkbox overlays every grid-line crossing
(including higher-order n-gon crossings, not just simple quad
intersections) as a hoverable point. Hovering one shows a preview of the
resulting tile plus its details: which two grid line families crossed, the
tile's type/area/colour, and its raw index coordinates in the underlying
lattice. A grid line colour picker and width control are also available
here.
