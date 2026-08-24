import sys
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

    main_win = QtWidgets.QMainWindow()
    ui = Ui_MainWindow()
    ui.setupUi(main_win)

    def close_all_windows(event):
        for name, is_open in ui.windows_open.items():
            if is_open:
                getattr(ui, name).close()

    main_win.closeEvent = close_all_windows
    main_win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
