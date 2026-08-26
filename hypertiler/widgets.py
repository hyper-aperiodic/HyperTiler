from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtCore import Qt
import pyqtgraph as pg
import numpy as np


def center_on_screen(window, ref_widget=None):
    """Center `window` on the screen that `ref_widget` (or `window` itself)
    currently occupies, instead of an absolute pixel offset that can land
    off-screen. Caller must set the window's size (resize/setFixedSize)
    before calling this, since it doesn't touch sizing itself."""
    target = ref_widget if ref_widget is not None else window
    screen = target.screen() if hasattr(target, 'screen') else None
    if screen is None:
        screen = QtWidgets.QApplication.primaryScreen()
    geo = screen.availableGeometry()
    x = geo.x() + (geo.width() - window.width()) // 2
    y = geo.y() + (geo.height() - window.height()) // 2
    window.move(x, y)


class LockedViewBox(pg.ViewBox):
    def mousePressEvent(self, event):
        if event.button() in (QtCore.Qt.RightButton, QtCore.Qt.MiddleButton):
            event.ignore()
            return
        super().mousePressEvent(event)

    def mouseDragEvent(self, event, axis=None):
        if event.button() in (QtCore.Qt.RightButton, QtCore.Qt.MiddleButton):
            event.ignore()
            return
        super().mouseDragEvent(event, axis)

    def wheelEvent(self, event, axis=None):
        super().wheelEvent(event, axis)


class DecimalDelegate(QtWidgets.QStyledItemDelegate):
    """Formats a cell's numeric display, and edits it with a QDoubleSpinBox
    (steppers, scroll-wheel, clamped range) instead of the default bare
    line-edit editor."""

    def __init__(self, decimals=2, minimum=-1e10, maximum=1e10, step=0.1, parent=None):
        super().__init__(parent)
        self.decimals = decimals
        self.minimum = minimum
        self.maximum = maximum
        self.step = step

    def displayText(self, value, locale):
        try:
            return f"{float(value):.{self.decimals}f}"
        except (ValueError, TypeError):
            return str(value)

    def createEditor(self, parent, option, index):
        editor = QtWidgets.QDoubleSpinBox(parent)
        editor.setDecimals(self.decimals)
        editor.setRange(self.minimum, self.maximum)
        editor.setSingleStep(self.step)
        return editor

    def setEditorData(self, editor, index):
        try:
            editor.setValue(float(index.model().data(index, Qt.EditRole)))
        except (TypeError, ValueError):
            editor.setValue(0.0)

    def setModelData(self, editor, model, index):
        editor.interpretText()
        model.setData(index, editor.value(), Qt.EditRole)


class TableModel(QtCore.QAbstractTableModel):
    def __init__(self, data, headers):
        super().__init__()
        self._data = data
        self._headers = headers

    def data(self, index, role=Qt.DisplayRole):
        if role == Qt.DisplayRole:
            return str(self._data[index.row(), index.column()])
        if role == Qt.EditRole:
            return float(self._data[index.row(), index.column()])

    def rowCount(self, index=QtCore.QModelIndex()):
        return self._data.shape[0]

    def columnCount(self, index=QtCore.QModelIndex()):
        return self._data.shape[1]

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return
        if orientation == Qt.Horizontal:
            return self._headers[section]
        return f'v{section + 1}'

    def insertRow(self, row, parent=QtCore.QModelIndex()):
        self.beginInsertRows(parent, row, row)
        self._data = np.insert(self._data, row, np.zeros(self.columnCount()), axis=0)
        self.endInsertRows()

    def removeRow(self, row, parent=QtCore.QModelIndex()):
        self.beginRemoveRows(parent, row, row)
        self._data = np.delete(self._data, row, axis=0)
        self.endRemoveRows()

    def set_row_data(self, row, new_data, parent=QtCore.QModelIndex()):
        for col in range(self.columnCount()):
            self.setData(self.index(row, col), new_data[col], Qt.EditRole)

    def setData(self, index, value, role=Qt.EditRole):
        if role == Qt.EditRole:
            self._data[index.row(), index.column()] = value
            self.dataChanged.emit(index, index, (Qt.DisplayRole,))
            return True
        return False

    def flags(self, index):
        return Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsEditable


class TileSwatchButton(QtWidgets.QPushButton):

    clicked_with_idx = QtCore.pyqtSignal(int)

    def __init__(self, idx, tile_verts, color):
        super().__init__()
        self.idx = idx
        self.tile_verts = tile_verts
        self.color = color
        self.setFixedSize(80, 80)
        self.clicked.connect(lambda: self.clicked_with_idx.emit(self.idx))

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)

        p.fillRect(self.rect(), QtGui.QColor(245, 245, 245))

        pen_color = QtGui.QColor(80, 80, 80)
        p.setPen(QtGui.QPen(pen_color, 1))
        p.drawRect(self.rect().adjusted(0, 0, -1, -1))

        if self.tile_verts is not None and len(self.tile_verts):
            verts = np.array(self.tile_verts)
            pad = 10
            w, h = self.width() - 2 * pad, self.height() - 2 * pad
            vmin, vmax = verts.min(axis=0), verts.max(axis=0)
            span = vmax - vmin
            span[span == 0] = 1
            scale = min(w / span[0], h / span[1])
            cx, cy = self.width() / 2, self.height() / 2
            pts = []
            for x, y in verts:
                sx = (x - (vmin[0] + vmax[0]) / 2) * scale + cx
                sy = (y - (vmin[1] + vmax[1]) / 2) * scale + cy
                pts.append(QtCore.QPointF(sx, sy))

            r, g, b = [int(c) for c in self.color]
            p.setBrush(QtGui.QBrush(QtGui.QColor(r, g, b)))
            p.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0), 1))
            p.drawPolygon(pts)

        p.end()
