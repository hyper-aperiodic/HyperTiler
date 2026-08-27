# HyperTiler

HyperTiler is a desktop tool for generating and analysing quasiperiodic 2D
tilings, via the de Bruijn multigrid method and substitution rules. It also
ships as a plain Python package, so you can generate tilings from a script
without touching the GUI at all.

This documentation covers both sides:

- The **user guide** walks through the desktop app.
- The **Python API** reference is for using HyperTiler's tiling engine
  directly from your own code (`from hypertiler import TileMaker`, etc.).

```{toctree}
:maxdepth: 2
:caption: Getting started

installation
theory
quickstart
```

```{toctree}
:maxdepth: 2
:caption: User guide

user_guide/main_window
user_guide/grid_tiling
user_guide/styling
user_guide/vertex_types
user_guide/network_builder
user_guide/substitution
user_guide/preferences
user_guide/shortcuts
```

```{toctree}
:maxdepth: 2
:caption: Python API

api/index
```
