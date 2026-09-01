# Network Builder

Opened from **Tools → Network builder**. Turns the tiling's vertices into
graph/lattice data - useful for feeding physics simulations such as
tight-binding or lattice models.

1. Tick which vertex type(s) to include (from the Vertex Types
   classification), using `All` / `None` as shortcuts.
2. Set `Min radius` / `Max radius` to bound which neighbour distances count
   as connected - or click `Auto` to derive sensible values from the median
   nearest-neighbour distance.
3. Set `Max shells` - how many distinct neighbour-distance bands
   ("coordination shells") to include.
4. Click `Build network`. Pairwise distances between the selected vertices
   are grouped into shells (within 2% tolerance of each other), and the
   network is drawn: points coloured by type, grey lines for connections.
   Hovering a vertex highlights it and shades its neighbours by shell.
5. Export with `Vertices only` (positions and types, as JSON or CSV) or
   `Neighbour dictionary` (JSON only - each vertex's full neighbour list
   with distances and shell numbers, plus a summary of mean distance per
   shell).

If the window is open and you change the vertex-type grouping (see
{doc}`vertex_types`), it refreshes in place rather than resetting its view.
