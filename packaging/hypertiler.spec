# -*- mode: python ; coding: utf-8 -*-

import os
import sys

# This spec lives in packaging/, one level below the repo root where the
# actual `hypertiler` package sits - PyInstaller injects SPECPATH as this
# file's own directory, and every path below is built from it explicitly
# rather than relying on whatever directory `pyinstaller` happens to be
# invoked from.
#
# The entry script is named launcher.py, NOT hypertiler.py, on purpose:
# PyInstaller adds the entry script's own directory (packaging/) to the
# front of its module search path, ahead of _REPO_ROOT below. A script
# named hypertiler.py sitting there would itself resolve as the module
# `hypertiler` before the real package one level up ever gets a look in,
# so `from hypertiler.__main__ import main` would silently bind to the
# entry script itself and fail to find `.__main__` on it.
_REPO_ROOT = os.path.abspath(os.path.join(SPECPATH, '..'))


def _asset(name):
    return os.path.join(SPECPATH, name)


# scipy submodules confirmed (empirically, by blocking each one and actually
# exercising KDTree/query_ball_point/query_pairs/_distance_wrap/gaussian_filter)
# to be unused by the app's own code and NOT a transitive dependency of
# scipy.spatial/scipy.ndimage. scipy.sparse, scipy.linalg, and scipy.special
# are NOT in this list on purpose - they looked unused too until blocking them
# broke spatial/ndimage internally, so they have to stay.
_UNUSED_SCIPY_MODULES = [
    'scipy.optimize', 'scipy.integrate', 'scipy.stats', 'scipy.io',
    'scipy.interpolate', 'scipy.signal', 'scipy.fft', 'scipy.fftpack',
    'scipy.cluster', 'scipy.odr', 'scipy.datasets', 'scipy.misc',
]

# Linux has no equivalent to embedding an icon in the executable itself (that's
# handled by a .desktop file's Icon= key at install time) - ship the PNG
# alongside the binary so a .desktop file has something to point at.
_linux_datas = [(_asset('hypertiler.png'), '.')] if sys.platform.startswith('linux') else []

a = Analysis(
    [_asset('launcher.py')],
    pathex=[_REPO_ROOT],
    binaries=[],
    datas=_linux_datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # PySide6 excluded so pyqtgraph's Qt-binding autodetection can't pull in
    # a second, unused Qt binding alongside PyQt5.
    excludes=['PySide6'] + _UNUSED_SCIPY_MODULES,
    noarchive=False,
    optimize=0,
)

# HyperTiler only touches QtCore/QtGui/QtWidgets directly, plus QtOpenGL(Widgets)
# and QtSvg pulled in transitively by pyqtgraph - every plugin category below
# belongs to a Qt feature area (SQL, multimedia, geolocation, sensors,
# text-to-speech, web view, Qt3D asset/scene loading, printing) this app never
# imports. Stripping them cuts the plugins folder roughly in half; keep
# platforms (required to launch at all), imageformats/iconengines (image and
# SVG icon rendering), and styles.
_UNUSED_QT_PLUGIN_DIRS = (
    'assetimporters', 'audio', 'bearer', 'generic', 'geometryloaders',
    'geoservices', 'mediaservice', 'platformthemes', 'playlistformats',
    'position', 'printsupport', 'renderers', 'sceneparsers',
    'sensorgestures', 'sensors', 'sqldrivers', 'texttospeech', 'webview',
)
def _is_unused_qt_plugin(dest_path):
    parts = [p.lower() for p in os.path.normpath(dest_path).split(os.sep)]
    for i, p in enumerate(parts):
        if p == 'plugins' and i + 1 < len(parts) and parts[i + 1] in _UNUSED_QT_PLUGIN_DIRS:
            return True
    return False

a.binaries = [b for b in a.binaries if not _is_unused_qt_plugin(b[0])]

pyz = PYZ(a.pure)

# PyInstaller's splash screen is unsupported on macOS (it needs UI calls from
# a non-main thread, which macOS disallows outright - Splash() raises
# SystemExit there) and requires tkinter to be present on the build machine
# on Linux. Skip it on Darwin so the build doesn't hard-fail; Windows/Linux
# keep the splash as before.
if sys.platform != 'darwin':
    splash = Splash(
        _asset('splash.png'),
        binaries=a.binaries,
        datas=a.datas,
        text_pos=None,
        text_size=12,
        minify_script=True,
        always_on_top=True,
    )
    splash_args = (splash,)
    splash_binaries = [splash.binaries]
else:
    splash_args = ()
    splash_binaries = []

# .ico is Windows-only and .icns is macOS-only; EXE(icon=...) on Linux is
# ignored outright (there's no equivalent - see _linux_datas above).
if sys.platform == 'win32':
    icon_file = _asset('HT.ico')
elif sys.platform == 'darwin':
    icon_file = _asset('HT.icns')
else:
    icon_file = None

exe = EXE(
    pyz,
    a.scripts,
    *splash_args,
    [],
    exclude_binaries=True,
    name='hypertiler',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_file,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    *splash_binaries,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='hypertiler',
)

# Without this, macOS gets the same bare onedir folder as Linux - a Unix
# executable + _internal, not something Finder treats as a real application
# (no dock icon, no double-click launch). BUNDLE() wraps COLLECT's output
# into a proper HyperTiler.app carrying the .icns set above.
if sys.platform == 'darwin':
    app = BUNDLE(
        coll,
        name='HyperTiler.app',
        icon=_asset('HT.icns'),
        bundle_identifier='io.github.hyper-aperiodic.hypertiler',
    )
