"""Clean 3D sensor-history waterfall surfaces using PyQtGraph OpenGL."""
from __future__ import annotations

import numpy as np
import pyqtgraph as pg
import pyqtgraph.opengl as gl
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QSizePolicy

PALETTE = ("#38BDF8", "#F59E0B", "#F472B6", "#4ADE80",
           "#A78BFA", "#FACC15", "#FB923C", "#60A5FA")
LANE_SPACING = 1.65


class WaterfallPlot(gl.GLViewWidget):
    """A clean ribbon per sensor above a shared ground grid."""
    cursorMoved = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.lanes = []
        self.duration = 1.0
        self.time_extent = 12.0
        self.opacity = 0.72
        self.height_scale = 1.4
        self._colors = {}
        self._scene_sensor_ids = ()
        self._surface_items = []
        self._ground_plane = None
        self._cursor_line = None
        self._cursor_fraction = 0.0
        self.setMinimumSize(0, 0)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setBackgroundColor("#0B1220")
        self.setMouseTracking(True)
        self.setCameraPosition(distance=20, elevation=26, azimuth=-48)

    def _camera_distance(self):
        lane_extent = max(1, len(self.lanes) - 1) * LANE_SPACING + 1.2
        return max(17.0, self.time_extent * 1.25, lane_extent * 1.45)

    def set_lanes(self, lanes, colors=None):
        self.lanes = list(lanes or [])[:8]
        self._colors = dict(colors or {})
        self.duration = max((float(point[0]) for lane in self.lanes
                             for point in lane.get("points", [])), default=1.0) or 1.0
        sensor_ids = tuple(lane["sensor_id"] for lane in self.lanes)
        if sensor_ids != self._scene_sensor_ids:
            self._build_scene()
        else:
            self._update_lane_items()

    def set_opacity(self, value):
        self.opacity = max(0.15, min(0.95, float(value) / 100.0))
        self._update_lane_items()

    def set_height_scale(self, value):
        self.height_scale = max(0.5, min(2.5, float(value) / 100.0))
        self._update_lane_items()

    def set_camera_preset(self, name):
        elevation, azimuth = {"Perspective": (26, -48), "Top": (88, -90),
                              "Front": (8, -90), "Side": (8, 0)}.get(name, (26, -48))
        self.setCameraPosition(distance=self._camera_distance(),
                               elevation=elevation, azimuth=azimuth)

    def _lane_geometry(self, index, lane):
        points = lane.get("points", [])
        x = np.asarray([float(point[0]) / self.duration * self.time_extent
                        for point in points], dtype=np.float32)
        raw_z = np.asarray([float(point[1]) for point in points], dtype=np.float32)
        z = np.clip(np.where(raw_z > 1.0, raw_z / 100.0, raw_z), 0.0, 1.0)
        z *= self.height_scale
        lane_y = index * LANE_SPACING
        y = np.asarray([lane_y - 0.40, lane_y + 0.40], dtype=np.float32)
        surface_z = np.column_stack((z, z)).astype(np.float32)
        color = pg.mkColor(self._colors.get(lane["sensor_id"], PALETTE[index % len(PALETTE)]))
        red, green, blue, _ = color.getRgbF()
        intensity = np.clip(z / max(self.height_scale, 1e-6), 0.0, 1.0)
        rgba = np.empty((len(x), 2, 4), dtype=np.float32)
        brightness = 0.66 + 0.34 * intensity
        rgba[:, :, 0] = red * brightness[:, None]
        rgba[:, :, 1] = green * brightness[:, None]
        rgba[:, :, 2] = blue * brightness[:, None]
        rgba[:, :, 3] = self.opacity * (0.68 + 0.25 * intensity[:, None])
        return x, y, surface_z, rgba.reshape(-1, 4)

    def _add_ground_plane(self):
        if not self.lanes:
            return
        lane_width = max(1, len(self.lanes) - 1) * LANE_SPACING + 1.6
        grid = gl.GLGridItem()
        grid.setSize(x=self.time_extent, y=lane_width, z=1)
        grid.setSpacing(x=1.0, y=LANE_SPACING)
        grid.setColor((0.24, 0.34, 0.47, 0.55))
        grid.translate(self.time_extent / 2.0,
                       (len(self.lanes) - 1) * LANE_SPACING / 2.0, 0.0)
        self.addItem(grid)
        self._ground_plane = grid

    def _build_scene(self):
        self.clear()
        self._surface_items = []
        self._ground_plane = None
        self._cursor_line = None
        if not self.lanes:
            self._scene_sensor_ids = ()
            self.update()
            return

        self._add_ground_plane()
        for index, lane in enumerate(self.lanes):
            x, y, surface_z, colors = self._lane_geometry(index, lane)
            surface = None
            if len(x) >= 2:
                surface = gl.GLSurfacePlotItem(
                    x=x, y=y, z=surface_z, colors=colors,
                    glOptions="translucent", smooth=False,
                    computeNormals=False, drawEdges=False,
                )
                self.addItem(surface)
            self._surface_items.append(surface)

        count = len(self.lanes)
        self._cursor_line = gl.GLLinePlotItem(
            pos=np.asarray([[self._cursor_fraction * self.time_extent, -0.8, 0.025],
                            [self._cursor_fraction * self.time_extent,
                             (count - 1) * LANE_SPACING + 0.8, 0.025]], dtype=np.float32),
            color=(0.92, 0.95, 1.0, 0.72), width=1.2, antialias=True,
            mode="line_strip", glOptions="translucent",
        )
        self.addItem(self._cursor_line)
        self._scene_sensor_ids = tuple(lane["sensor_id"] for lane in self.lanes)
        self.opts["center"] = pg.Vector(self.time_extent / 2.0,
                                        (count - 1) * LANE_SPACING / 2.0,
                                        self.height_scale * 0.30)
        self.setCameraPosition(distance=self._camera_distance(), elevation=26, azimuth=-48)
        self.update()

    def _update_lane_items(self):
        if not self.lanes:
            if self._scene_sensor_ids:
                self._build_scene()
            return
        if len(self._surface_items) != len(self.lanes):
            self._build_scene()
            return
        if any((self._surface_items[i] is None) != (len(lane.get("points", [])) < 2)
               for i, lane in enumerate(self.lanes)):
            self._build_scene()
            return
        for index, lane in enumerate(self.lanes):
            x, y, surface_z, colors = self._lane_geometry(index, lane)
            surface = self._surface_items[index]
            if surface is not None:
                surface.setData(x=x, y=y, z=surface_z, colors=colors)
        if self._cursor_line is not None:
            self._cursor_line.setData(pos=np.asarray([
                [self._cursor_fraction * self.time_extent, -0.8, 0.025],
                [self._cursor_fraction * self.time_extent,
                 (len(self.lanes) - 1) * LANE_SPACING + 0.8, 0.025],
            ], dtype=np.float32))
        self.update()

    def mouseMoveEvent(self, event):
        self._cursor_fraction = max(0.0, min(1.0, event.position().x() / max(1, self.width())))
        if self._cursor_line is not None:
            self._cursor_line.setData(pos=np.asarray([
                [self._cursor_fraction * self.time_extent, -0.8, 0.025],
                [self._cursor_fraction * self.time_extent,
                 (len(self.lanes) - 1) * LANE_SPACING + 0.8, 0.025],
            ], dtype=np.float32))
        self.cursorMoved.emit(self._cursor_fraction * self.duration)
        super().mouseMoveEvent(event)
