# Changelog

## v1.1.0

### Added

- `hypertiler/ink2tile.py`: orientation-group rule correction - detects the
  drawing's rotation/reflection group, cleans templates to close exactly
  with shared edge lengths, rebuilds every child exactly, and fits the
  inflation factor by least squares.
- `hypertiler/ink2tile.py::generate(gen, start=None)`: separated from
  `__init__` so a built (corrected) instance can be re-generated cheaply
  without re-parsing/re-correcting the SVG.
- General cut-and-project vertex module, found via
  LLL lattice reduction on the drawing's own edge vectors - works for any
  detected symmetry order and any inflation factor.
- `hypertiler/substitution/perp_window.py` (new): `PerpSpaceWindow` -
  scatter plot of `perp_coords()`, with a toolbar for "Colour by vertex
  type" (per-type `ScatterPlotItem`s + a `pg.LegendItem`) and "Basis
  vectors" (two insets, `_VectorInset`/`_VectorArrowItem`, showing the
  module's E∥/E⊥ basis vectors as labelled black arrows).
- `hypertiler/substitution/window.py`: perp-space build/vertex-type cache
  (`_perp_cache`, `_refresh_perp_space`, `_perp_space_args`) - reopening
  the window with nothing changed is instant, and it auto-refreshes if
  open when a new tiling is generated.
- Exact decoration-conflict diagnosis and repair, replacing a float
  geometric-overlap heuristic: whether any two tile instances of the same
  type occupy the same vertex set under different labels - the actual
  definition of a self-contradictory rule.
- `hypertiler/substitution/clean_window.py`: `AnalyseSvgWindow`'s three-step
  workflow - **Analyse** (automatic, read-only, highlights conflicting
  children via `_RulePreviewItem`) → **Attempt to fix** (`fix_decorations`,
  re-clickable if conflicts remain) → **Save fixed SVG…** (`rewrite_svg`,
  writes a corrected copy via a file dialog, original untouched).
- `hypertiler/substitution/worker.py`: `compute_vertex_types` extracted as
  a standalone function (shared by the vertex-finder window and the
  perp-space window's vertex-type colouring).
- `hypertiler/substitution/window.py`: Generate button doubles as a kill
  switch - reads "Cancel" while running and forcibly terminates the worker
  thread if clicked (`_on_gen_btn_clicked`, `_cancel_generate`).
- `hypertiler/main_window.py`: "Analyse SVG…"/"Perpendicular space…" Tools-
  menu actions, visible only in substitution mode.
- `hypertiler/config.py::APP_STYLESHEET`: `QToolBar`/`QToolButton` rules.

### Changed

- `hypertiler/substitution/worker.py::compute_vertex_types`: the boundary
  filter (dropping vertices whose local neighbourhood is truncated by the
  patch edge) no longer uses a fixed radius from the centroid, which
  assumed a roughly circular patch and failed for anisotropic/concave
  ones. New `_typical_spacing`/`_interior_mask` rasterise the vertex cloud
  and erode it inward (via `scipy.ndimage`) by the patch's actual shape.
- `hypertiler/substitution/worker.py::_canonical_sub`: now requires a
  vertex's incident-tile sectors to sum to 360° (`gap_tol=0.3` rad),
  returning `None` otherwise - catches a vertex with a tile missing
  (e.g. growing from a single un-symmetrised starting tile) or with
  overlapping tiles (an unfixed decoration conflict), not just ones near
  the patch's outer edge. `PerpSpaceWindow._apply_vertex_types` updated to
  exclude `None`-canon vertices from colouring/the legend.
- `hypertiler/substitution/window.py::_SubstitutionWorker` accepts a
  pre-built `inkTile` (`built=`) and just calls `.generate()` on it,
  skipping correction entirely on a cache hit
- `hypertiler/main_window.py`: "Substitution Mode" promoted from a Tools-
  submenu entry to its own top-level menu-bar action.


### Fixed

- `hypertiler/substitution/utils.py::parse_rules` and
  `hypertiler/substitution/window.py::_load_rules_from_path` relied on
  module-level globals (`ink2tile.supertiles`, `ink2tile.globalScale`)
  removed by the correction-pipeline rewrite; updated to read from the
  built `inkTile` instance instead.

### Removed

- `_outline_symmetries`, `_overlaps`, the old `fix_overlaps` (float
  geometric-overlap heuristic) - superseded by the exact decoration-
  conflict check above; the old heuristic both false-positived (flagged
  `AB.svg` as broken when it wasn't) and was slow on some files.


---

## Documentation to update

Nothing in `docs/` has been touched; all outstanding.

- **`docs/user_guide/substitution.md`**: document the automatic correction
  pipeline (safe to run on every load) vs. the opt-in Analyse SVG workflow
  (Analyse → Attempt to fix → Save fixed SVG, and what the highlight
  colours mean); the Perpendicular Space window and its toolbar actions
  (noting it's unavailable for rank-2/periodic tilings); the Generate
  button's Cancel behaviour.
- **`docs/theory.md`**: currently only covers the dual-grid method's
  cut-and-project construction. Needs an equivalent section for the
  substitution method's hyperspace index (the vertex module, found via
  LLL rather than assumed from a known lattice, and the physical/
  perpendicular split), and a definition of "decoration conflict" as the
  formal correctness criterion.
- **`inkTile` class docstring** (`hypertiler/ink2tile.py`): the
  `Attributes` list predates this session's work and doesn't mention `r`,
  `d`, `basis`, `perp`, `hyper`, `stab`, `decorated`, `relabelled`,
  `relabel_overlaps`.
