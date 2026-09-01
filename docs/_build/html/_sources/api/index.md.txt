# Python API reference

Everything below is importable directly from the top-level package:

```python
from hypertiler import TileMaker, inkTile, write_svg, write_png, regular_vectors, classify_areas, make_colors
```

See {doc}`../quickstart` for worked examples using each of these together.

## Building tilings

```{eval-rst}
.. autofunction:: hypertiler.regular_vectors

.. autoclass:: hypertiler.TileMaker
   :members:
   :undoc-members:
```

## Substitution (inflation) tilings

```{eval-rst}
.. autoclass:: hypertiler.inkTile
   :members:
   :undoc-members:
```

## Helpers

```{eval-rst}
.. autofunction:: hypertiler.classify_areas

.. autofunction:: hypertiler.make_colors

.. autofunction:: hypertiler.write_svg

.. autofunction:: hypertiler.write_png
```
