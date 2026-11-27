"""Insight-style 3D sensor history surfaces using PyQtGraph OpenGL."""
from __future__ import annotations

import numpy as np
import pyqtgraph as pg
import pyqtgraph.opengl as gl
from PySide6.QtCore import Signal
from PySide6.QtGui import QVector3D


PALETTE = ("#38BDF8", "#F59E0B", "#F472B6", "#4ADE80",
           "#A78BFA", "#FACC15", "#FB923C", "#60A5FA")


class WaterfallPlot(gl.GLViewWidget):
    """Separate translucent 3D surface ribbon for each selected vehicle sensor.

    X is elapsed time, Y is sensor identity, and Z is independently normalized
    signal magnitude. Raw engineering units are retained in lane metadata.
    """
    cursorMoved = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.lanes = []
        self.duration = 1.0
        self.opacity = 0.55
        self.height_scale = 1.4
        self._colors = {}
        self._camera_initialized = False
        self.setMinimumSize(820, 420)
        self.setBackgroundColor("#0B1220")
        self.setMouseTracking(True)
        self.setCameraPosition(distance=14, elevation=28, azimuth=-48)

    def set_lanes(self, lanes, colors=None):
        self.lanes = list(lanes or [])[:8]
        self._colors = dict(colors or {})
        self.duration = max(
            (float(p[0]) for lane in self.lanes for p in lane.get("points", [])),
            default=1.0,
        ) or 1.0
        self._build_scene()

    def set_opacity(self, value):
        self.opacity = max(0.15, min(0.90, float(value) / 100.0))
        self._build_scene()

    def set_height_scale(self, value):
        self.height_scale = max(0.5, min(2.5, float(value) / 100.0))
        self._build_scene()

    def set_camera_preset(self, name):
        elevation, azimuth = {
            "Perspective": (28, -48), "Top": (88, -90),
            "Front": (8, -90), "Side": (8, 0),
        }.get(name, (28, -48))
        self.setCameraPosition(
            distance=max(10.0, self.duration * 1.35, len(self.lanes) * 2.2),
            elevation=elevation, azimuth=azimuth,
        )

    def _build_scene(self):
        camera_elevation = self.opts.get("elevation", 28)
        camera_azimuth = self.opts.get("azimuth", -48)
        camera_distance = self.opts.get("distance", 14)
        first_scene = not self._camera_initialized
        self.clear()
        if not self.lanes:
            self.update()
            return
        spacing = 1.65
        count = len(self.lanes)
        grid = gl.GLGridItem()
        grid.setSize(x=max(self.duration, 1.0), y=max(1.0, count * spacing), z=0)
        grid.setSpacing(x=max(self.duration / 10.0, 0.1), y=spacing)
        grid.setColor((0.25, 0.34, 0.45, 0.38))
        grid.translate(self.duration / 2.0, (count - 1) * spacing / 2.0, 0)
        self.addItem(grid)
        self.addItem(gl.GLAxisItem(size=QVector3D(
            max(self.duration, 1.0), max(1.0, count * spacing), self.height_scale
        )))

        for index, lane in enumerate(self.lanes):
            points = lane.get("points", [])
            if len(points) < 2:
                continue
            x = np.asarray([float(p[0]) for p in points], dtype=np.float32)
            raw_z = np.asarray([float(p[1]) for p in points], dtype=np.float32)
            z = np.clip(np.where(raw_z > 1.0, raw_z / 100.0, raw_z), 0.0, 1.0)
            z *= self.height_scale
            y = np.asarray([index * spacing - 0.42, index * spacing + 0.42], dtype=np.float32)
            z_grid = np.column_stack((z, z)).astype(np.float32)
            color = pg.mkColor(self._colors.get(lane["sensor_id"], PALETTE[index % 8]))
            red, green, blue, _ = color.getRgbF()
            intensity = np.clip(z / max(self.height_scale, 1e-6), 0.0, 1.0)
            rgba = np.empty((len(x), 2, 4), dtype=np.float32)
            brightness = 0.62 + 0.38 * intensity[:, None]
            rgba[:, :, 0] = red * brightness
            rgba[:, :, 1] = green * brightness
            rgba[:, :, 2] = blue * brightness
            rgba[:, :, 3] = (self.opacity * (0.28 + 0.58 * intensity))[:, None]

            surface = gl.GLSurfacePlotItem(
                x=x, y=y, z=z_grid, colors=rgba, glOptions="translucent",
                smooth=False, computeNormals=False, drawEdges=False,
            )
            self.addItem(surface)
            self.addItem(gl.GLTextItem(
                pos=(0.0, index * spacing - 0.48, 0.04),
                text=(f'{lane["name"]} [{lane["unit"]}]  '
                      f'min {lane["minimum"]:.4g}  max {lane["maximum"]:.4g}  '
                      f'now {lane["current"]:.4g}'),
                color=(0.88, 0.92, 0.98, 1.0),
            ))
            crest = np.column_stack((
                x, np.full_like(x, index * spacing), z + 0.012,
            )).astype(np.float32)
            self.addItem(gl.GLLinePlotItem(
                pos=crest, color=(red, green, blue, min(1.0, self.opacity + 0.32)),
                width=2.0, antialias=True, mode="line_strip", glOptions="translucent",
            ))

        self._cursor_line = gl.GLLinePlotItem(
            pos=np.asarray([[0, -0.55, 0.025],
                            [0, (count - 1) * spacing + 0.55, 0.025]], dtype=np.float32),
            color=(0.92, 0.95, 1.0, 0.72), width=1.2,
            antialias=True, mode="line_strip", glOptions="translucent",
        )
        self.addItem(self._cursor_line)
        self.opts["center"] = pg.Vector(
            self.duration / 2.0, (count - 1) * spacing / 2.0,
            self.height_scale * 0.32,
        )
        if first_scene:
            self.setCameraPosition(
                distance=max(10.0, self.duration * 1.35, count * 2.2),
                elevation=28, azimuth=-48,
            )
            self._camera_initialized = True
        else:
            self.setCameraPosition(
                distance=camera_distance,
                elevation=camera_elevation,
                azimuth=camera_azimuth,
            )
        self.update()

    def mouseMoveEvent(self, event):
        elapsed = max(0.0, min(1.0, event.position().x() / max(1, self.width()))) * self.duration
        if self.lanes and getattr(self, "_cursor_line", None) is not None:
            self._cursor_line.setData(pos=np.asarray([
                [elapsed, -0.55, 0.025],
                [elapsed, (len(self.lanes) - 1) * 1.65 + 0.55, 0.025],
            ], dtype=np.float32))
        self.cursorMoved.emit(elapsed)
        super().mouseMoveEvent(event)
