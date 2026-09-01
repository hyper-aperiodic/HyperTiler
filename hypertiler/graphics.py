from PyQt5 import QtCore, QtGui
import pyqtgraph as pg
import numpy as np
from . import config

##all the settings for how to draw things 

class tilePlot(pg.GraphicsObject):
    def __init__(self, tiling, poly_color, ngon_color, edge_color=(0, 0, 0), edge_width=2):
        pg.GraphicsObject.__init__(self)
        self._build(tiling, poly_color, ngon_color, edge_color, edge_width)
        self._bounding_rect = QtCore.QRectF(self.picture.boundingRect())

    def _build(self, tiling, poly_color, ngon_color, edge_color, edge_width):
        self.picture = QtGui.QPicture()
        p = QtGui.QPainter(self.picture)
        if config._antialias:
            p.setRenderHint(QtGui.QPainter.Antialiasing)

        color_paths = {}
        edge_path = QtGui.QPainterPath()

        def add_poly(verts, color):
            key = tuple(color)
            if key not in color_paths:
                color_paths[key] = QtGui.QPainterPath()
                color_paths[key].setFillRule(QtCore.Qt.WindingFill)
            path = color_paths[key]
            pts = [QtCore.QPointF(x, y) for x, y in verts]
            poly = QtGui.QPolygonF(pts)
            path.addPolygon(poly)
            n = len(verts)
            for i in range(n):
                edge_path.moveTo(pts[i])
                edge_path.lineTo(pts[(i + 1) % n])

        for ngon, color in zip(tiling.p_points, ngon_color):
            if len(ngon):
                add_poly(ngon, color)

        for tile, color in zip(tiling.points, poly_color):
            add_poly(tile, color)

        p.setPen(pg.mkPen(None))
        for color_key, path in color_paths.items():
            p.setBrush(pg.mkBrush(*color_key))
            p.drawPath(path)

        p.setPen(pg.mkPen(edge_color, width=edge_width))
        p.setBrush(pg.mkBrush(None))
        p.drawPath(edge_path)

        p.end()

    def paint(self, p, *args):
        p.drawPicture(0, 0, self.picture)

    def boundingRect(self):
        return self._bounding_rect


class linkPlot(pg.GraphicsObject):
    """Draws straight connections between vertex pairs (Network Builder's
    edges). Built the same plain moveTo/lineTo way as edgePlot/gridPlot,
    rather than via pyqtgraph's PlotDataItem(connect='finite') - that path
    builds its QPainterPath through a QDataStream/QByteArray binary trick
    that's sensitive to the exact Qt build in use, and has been seen to
    silently produce an empty path (no error, just nothing drawn) under a
    PyInstaller-frozen build while working fine from source."""
    def __init__(self, verts, edges, color=(120, 120, 120, 160), width=1):
        pg.GraphicsObject.__init__(self)
        self._build(verts, edges, color, width)
        self._bounding_rect = QtCore.QRectF(self.picture.boundingRect())

    def _build(self, verts, edges, color, width):
        self.picture = QtGui.QPicture()
        p = QtGui.QPainter(self.picture)
        if config._antialias:
            p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.setPen(pg.mkPen(color, width=width))
        path = QtGui.QPainterPath()
        for i, j in edges:
            path.moveTo(QtCore.QPointF(*verts[i]))
            path.lineTo(QtCore.QPointF(*verts[j]))
        p.drawPath(path)
        p.end()

    def paint(self, p, *args):
        p.drawPicture(0, 0, self.picture)

    def boundingRect(self):
        return self._bounding_rect


class pointPlot(pg.GraphicsObject):
    def __init__(self, verts, radius=0.2, color=(0, 0, 0)):
        pg.GraphicsObject.__init__(self)
        self._build(verts, radius, color)
        self._bounding_rect = QtCore.QRectF(self.picture.boundingRect())

    def _build(self, verts, radius, color):
        self.picture = QtGui.QPicture()
        p = QtGui.QPainter(self.picture)
        if config._antialias:
            p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.setPen(pg.mkPen(None))
        p.setBrush(pg.mkBrush(*color))
        for v in verts:
            p.drawEllipse(QtCore.QPointF(v[0], v[1]), radius, radius)
        p.end()

    def paint(self, p, *args):
        p.drawPicture(0, 0, self.picture)

    def boundingRect(self):
        return self._bounding_rect


class vectorPlotting(pg.GraphicsObject):
    def __init__(self, vector_data, kind='real'):
        pg.GraphicsObject.__init__(self)
        col = 0 if kind == 'real' else 1
        vectors = [
            (30 * row[col] * np.cos(np.radians(row[2])),
             30 * row[col] * np.sin(np.radians(row[2])))
            for row in vector_data
        ]
        self._build(vectors)

    def _build(self, vectors):
        self.picture = QtGui.QPicture()
        p = QtGui.QPainter(self.picture)
        if config._antialias:
            p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.setPen(pg.mkPen('k', width=2))
        p.setBrush(pg.mkBrush('k'))
        for vx, vy in vectors:
            p.drawLine(QtCore.QLineF(0, 0, vx, vy))
            bearing = np.arctan2(vy, vx)
            pts = [
                QtCore.QPointF(vx, vy),
                QtCore.QPointF(vx + 5 * np.cos(bearing + np.radians(150)),
                               vy + 5 * np.sin(bearing + np.radians(150))),
                QtCore.QPointF(vx + 5 * np.cos(bearing - np.radians(150)),
                               vy + 5 * np.sin(bearing - np.radians(150))),
            ]
            p.drawPolygon(pts)
        p.end()

    def paint(self, p, *args):
        p.drawPicture(0, 0, self.picture)

    def boundingRect(self):
        return QtCore.QRectF(self.picture.boundingRect())


class edgePlot(pg.GraphicsObject):
    def __init__(self, tiling, color=(0, 0, 0), width=1):
        pg.GraphicsObject.__init__(self)
        self._build(tiling, color, width)
        self._bounding_rect = QtCore.QRectF(self.picture.boundingRect())

    def _build(self, tiling, color, width):
        self.picture = QtGui.QPicture()
        p = QtGui.QPainter(self.picture)
        if config._antialias:
            p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.setPen(pg.mkPen(color, width=width))
        path = QtGui.QPainterPath()
        for tile in tiling.points:
            n = len(tile)
            for i in range(n):
                path.moveTo(QtCore.QPointF(*tile[i]))
                path.lineTo(QtCore.QPointF(*tile[(i + 1) % n]))
        for ngon in tiling.p_points:
            if not len(ngon):
                continue
            n = len(ngon)
            for i in range(n):
                path.moveTo(QtCore.QPointF(*ngon[i]))
                path.lineTo(QtCore.QPointF(*ngon[(i + 1) % n]))
        p.drawPath(path)
        p.end()

    def paint(self, p, *args):
        p.drawPicture(0, 0, self.picture)

    def boundingRect(self):
        return self._bounding_rect


class gridPlot(pg.GraphicsObject):
    def __init__(self, grid, color=(100, 149, 237), width=2):
        pg.GraphicsObject.__init__(self)
        self._build(grid, color, width)
        self._bounding_rect = QtCore.QRectF(self.picture.boundingRect())

    def _build(self, grid, color, width):
        self.picture = QtGui.QPicture()
        p = QtGui.QPainter(self.picture)
        if config._antialias:
            p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.setPen(pg.mkPen(color, width=width))
        path = QtGui.QPainterPath()
        for p1_list, p2_list in grid.grids:
            for p1, p2 in zip(p1_list, p2_list):
                path.moveTo(QtCore.QPointF(p1[0], p1[1]))
                path.lineTo(QtCore.QPointF(p2[0], p2[1]))
        p.drawPath(path)
        p.end()

    def paint(self, p, *args):
        p.drawPicture(0, 0, self.picture)

    def boundingRect(self):
        return self._bounding_rect
