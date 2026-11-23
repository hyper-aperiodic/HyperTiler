import os
import sys

os.environ.setdefault("PYQTGRAPH_QT_LIB", "PyQt5")

import pyqtgraph as pg
from PyQt5 import QtWidgets
from PyQt5.QtGui import QSurfaceFormat
from PyQt5.QtWidgets import QOpenGLWidget

from .config import _load_prefs
from .main_window import Ui_MainWindow


def main():
    pg.setConfigOptions(useOpenGL=True, antialias=True)
    ##default graphical settings
    fmt = QSurfaceFormat()
    fmt.setSamples(8)
    QSurfaceFormat.setDefaultFormat(fmt)

    app = QtWidgets.QApplication(sys.argv)
    _load_prefs()

    # Detect DPI for high-DPI displays
    screen = app.primaryScreen()
    dpi = screen.logicalDotsPerInch()
    scale = max(1.0, dpi / 96.0)

    main_win = QtWidgets.QMainWindow()
    ui = Ui_MainWindow()
    ui.setupUi(main_win, scale)

    def close_all_windows(event):
        for name, is_open in ui.windows_open.items():
            if is_open:
                getattr(ui, name).close()

    main_win.closeEvent = close_all_windows
    main_win.show()

    if getattr(sys, "frozen", False):
        try:
            import pyi_splash
            pyi_splash.close()
        except ImportError:
            pass

    main_win.raise_()
    main_win.activateWindow()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
