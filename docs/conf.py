# Configuration file for the Sphinx documentation builder.
#
# This docs source currently lives OUTSIDE the hypertiler git repo
# (sibling to the "1.0" project folder) so it can be reviewed before
# deciding how/whether to fold it into version control. To build it, the
# `hypertiler` package needs to be importable - either `pip install -e`
# the project first, or point PYTHONPATH at the repo root.

import os
import sys

# Try the eventual in-repo layout first (docs/ living directly inside the
# project root, next to the hypertiler/ package), then fall back to the
# current staging layout (docs/ inside a sibling hypertiler-docs/ folder,
# next to the 1.0/ project folder) - so this keeps working unmodified
# once this whole docs/ directory is moved into the real repo.
_here = os.path.abspath(os.path.dirname(__file__))
for _candidate in (
    os.path.join(_here, ".."),
    os.path.join(_here, "..", "..", "1.0"),
):
    if os.path.isdir(os.path.join(_candidate, "hypertiler")):
        sys.path.insert(0, _candidate)
        break

project = "HyperTiler"
copyright = "2026, Sam Coates"
author = "Sam Coates"
release = "1.0.0"

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "sphinx.ext.intersphinx",
    "myst_parser",
]

myst_enable_extensions = [
    "colon_fence",
    "deflist",
]

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

source_suffix = {
    ".rst": "restructuredtext",
    ".md": "markdown",
}

autodoc_member_order = "bysource"
autodoc_typehints = "description"

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "numpy": ("https://numpy.org/doc/stable/", None),
}

html_theme = "sphinx_rtd_theme"
html_static_path = ["_static"]
html_title = "HyperTiler"
