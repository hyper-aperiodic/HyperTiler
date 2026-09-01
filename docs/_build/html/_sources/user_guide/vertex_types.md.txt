# Vertex Types

Opened from **Tools → Vertex types** once a tiling exists. This groups
every vertex in the tiling by its local environment - the sequence of
tile-edge angles surrounding it - so that vertices with an identical local
arrangement end up in the same "type", regardless of where they sit in the
tiling.

Results appear as a grid of cards, one per distinct type, each showing:

- A preview of the tiles meeting at a representative vertex of that type
- A label such as "Type 2 - 18% (134 vertices)"
- A **Highlight on plot** checkbox, which overlays that type's vertex
  positions directly on the main tiling plot

A **Group mirror-symmetric types** checkbox merges types that are mirror
images of each other (identical up to reflection) into a single card,
useful when you don't care about handedness and just want distinct local
environments. Toggling it clears any active highlights and, if a Network
Builder window is open, refreshes it to match the new grouping.

```{note}
Vertices near the edge of the tiling are excluded from classification
(their surrounding tiles are cut off, which would distort the result), so
counts reflect only the interior of the tiling.

**Because the underlying logic of this cut off is lazy, it will give some bad results on substitution tiles if the initial seed isn't sufficiently isotropic**
```
