"""Insight-style 3D sensor history surfaces using PyQtGraph OpenGL."""
from __future__ import annotations

import numpy as np
import pyqtgraph as pg
import pyqtgraph.opengl as gl
from PySide6.QtCore import Signal
from PySide6.QtGui import QVector3D


PALETTE = ("#38BDF8", "#F59E0B", "#F472B6", "#4ADE80",
           "#A78BFA", "#FACC15", "#FB923C", "#60A5FA")
LANE_SPACING = 1.65


class WaterfallPlot(gl.GLViewWidget):
    """One translucent 3D surface ribbon per selected vehicle sensor.

    X is elapsed time, Y is sensor identity, and Z is independently normalized
    magnitude. Engineering values and units remain separate from display height.
    """
    cursorMoved = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.lanes = []
        self.duration = 1.0
        self.time_extent = 12.0
        self.opacity = 0.55
        self.height_scale = 1.4
        self._colors = {}
        self._camera_initialized = False
        self._scene_sensor_ids = ()
        self._surface_items = []
        self._contour_items = []
        self._text_items = []
        self._cursor_line = None
        self._axis_item = None
        self._cursor_fraction = 0.0
        self.setMinimumSize(820, 420)
        self.setBackgroundColor("#0B1220")
        self.setMouseTracking(True)
        self.setCameraPosition(distance=14, elevation=28, azimuth=-48)

    def set_lanes(self, lanes, colors=None):
        self.lanes = list(lanes or [])[:8]
        self._colors = dict(colors or {})
        self.duration = max(
            (float(point[0]) for lane in self.lanes for point in lane.get("points", [])),
            default=1.0,
        ) or 1.0
        sensor_ids = tuple(lane["sensor_id"] for lane in self.lanes)
        if sensor_ids != self._scene_sensor_ids:
            self._build_scene()
        else:
            self._update_lane_items()

    def set_opacity(self, value):
        self.opacity = max(0.15, min(0.90, float(value) / 100.0))
        self._update_lane_items()

    def set_height_scale(self, value):
        self.height_scale = max(0.5, min(2.5, float(value) / 100.0))
        self._update_lane_items()

    def set_camera_preset(self, name):
        elevation, azimuth = {
            "Perspective": (28, -48),
            "Top": (88, -90),
            "Front": (8, -90),
            "Side": (8, 0),
        }.get(name, (28, -48))
        self.setCameraPosition(
            distance=max(14.0, len(self.lanes) * 2.2),
            elevation=elevation,
            azimuth=azimuth,
        )

    def _lane_geometry(self, index, lane):
        points = lane.get("points", [])
        x = np.asarray(
            [float(point[0]) / self.duration * self.time_extent for point in points],
            dtype=np.float32,
        )
        raw_z = np.asarray([float(point[1]) for point in points], dtype=np.float32)
        z = np.clip(np.where(raw_z > 1.0, raw_z / 100.0, raw_z), 0.0, 1.0)
        z *= self.height_scale
        lane_y = index * LANE_SPACING
        y = np.asarray([lane_y - 0.42, lane_y + 0.42], dtype=np.float32)
        z_grid = np.column_stack((z, z)).astype(np.float32)

        color = pg.mkColor(self._colors.get(
            lane["sensor_id"], PALETTE[index % len(PALETTE)]
        ))
        red, green, blue, _ = color.getRgbF()
        intensity = np.clip(z / max(self.height_scale, 1e-6), 0.0, 1.0)
        rgba = np.empty((len(x), 2, 4), dtype=np.float32)
        brightness = 0.62 + 0.38 * intensity[:, None]
        rgba[:, :, 0] = red * brightness
        rgba[:, :, 1] = green * brightness
        rgba[:, :, 2] = blue * brightness
        rgba[:, :, 3] = (self.opacity * (0.28 + 0.58 * intensity))[:, None]

        crest = np.column_stack((
            x, np.full_like(x, lane_y), z + 0.012,
        )).astype(np.float32)
        label = (
            f'{lane["name"]} [{lane["unit"]}]  '
            f'min {lane["minimum"]:.4g}  max {lane["maximum"]:.4g}  '
            f'now {lane["current"]:.4g}'
        )
        return x, y, z_grid, rgba, crest, (red, green, blue), label, lane_y

    def _build_scene(self):
        camera_elevation = self.opts.get("elevation", 28)
        camera_azimuth = self.opts.get("azimuth", -48)
        camera_distance = self.opts.get("distance", 14)
        first_scene = not self._camera_initialized
        self.clear()
        self._surface_items = []
        self._contour_items = []
        self._text_items = []
        self._cursor_line = None
        self._axis_item = None

        if not self.lanes:
            self._scene_sensor_ids = ()
            self.update()
            return

        count = len(self.lanes)
        grid = gl.GLGridItem()
        grid.setSize(
            x=self.time_extent,
            y=max(1.0, count * LANE_SPACING),
            z=0,
        )
        grid.setSpacing(x=self.time_extent / 10.0, y=LANE_SPACING)
        grid.setColor((0.25, 0.34, 0.45, 0.38))
        grid.translate(
            self.time_extent / 2.0,
            (count - 1) * LANE_SPACING / 2.0,
            0,
        )
        self.addItem(grid)

        self._axis_item = gl.GLAxisItem(size=QVector3D(
            self.time_extent,
            max(1.0, count * LANE_SPACING),
            self.height_scale,
        ))
        self.addItem(self._axis_item)

        for index, lane in enumerate(self.lanes):
            x, y, z_grid, rgba, crest, rgb, label, lane_y = self._lane_geometry(index, lane)
            if len(x) >= 2:
                surface = gl.GLSurfacePlotItem(
                    x=x,
                    y=y,
                    z=z_grid,
                    colors=rgba,
                    glOptions="translucent",
                    smooth=False,
                    computeNormals=False,
                    drawEdges=False,
                )
                self.addItem(surface)
                red, green, blue = rgb
                contour = gl.GLLinePlotItem(
                    pos=crest,
                    color=(red, green, blue, min(1.0, self.opacity + 0.32)),
                    width=2.0,
                    antialias=True,
                    mode="line_strip",
                    glOptions="translucent",
                )
                self.addItem(contour)
            else:
                surface = None
                contour = None
            self._surface_items.append(surface)
            self._contour_items.append(contour)

            text = gl.GLTextItem(
                pos=(0.0, lane_y - 0.48, 0.04),
                text=label,
                color=(0.88, 0.92, 0.98, 1.0),
            )
            self.addItem(text)
            self._text_items.append(text)

        self._cursor_line = gl.GLLinePlotItem(
            pos=np.asarray([
                [self._cursor_fraction * self.time_extent, -0.55, 0.025],
                [self._cursor_fraction * self.time_extent,
                 (count - 1) * LANE_SPACING + 0.55, 0.025],
            ], dtype=np.float32),
            color=(0.92, 0.95, 1.0, 0.72),
            width=1.2,
            antialias=True,
            mode="line_strip",
            glOptions="translucent",
        )
        self.addItem(self._cursor_line)
        self._scene_sensor_ids = tuple(lane["sensor_id"] for lane in self.lanes)
        self.opts["center"] = pg.Vector(
            self.time_extent / 2.0,
            (count - 1) * LANE_SPACING / 2.0,
            self.height_scale * 0.32,
        )
        if first_scene:
            self.setCameraPosition(
                distance=max(14.0, count * 2.2),
                elevation=28,
                azimuth=-48,
            )
            self._camera_initialized = True
        else:
            self.setCameraPosition(
                distance=camera_distance,
                elevation=camera_elevation,
                azimuth=camera_azimuth,
            )
        self.update()

    def _update_lane_items(self):
        if not self.lanes:
            if self._scene_sensor_ids:
                self._build_scene()
            return
        if len(self._surface_items) != len(self.lanes):
            self._build_scene()
            return
        if any(
            (self._surface_items[index] is None) != (len(lane.get("points", [])) < 2)
            for index, lane in enumerate(self.lanes)
        ):
            self._build_scene()
            return

        for index, lane in enumerate(self.lanes):
            x, y, z_grid, rgba, crest, rgb, label, lane_y = self._lane_geometry(index, lane)
            surface = self._surface_items[index]
            red, green, blue = rgb
            if surface is not None:
                surface.setData(x=x, y=y, z=z_grid, colors=rgba)
                self._contour_items[index].setData(
                    pos=crest,
                    color=(red, green, blue, min(1.0, self.opacity + 0.32)),
                )
            self._text_items[index].setData(
                pos=(0.0, lane_y - 0.48, 0.04),
                text=label,
                color=(0.88, 0.92, 0.98, 1.0),
            )

        if self._axis_item is not None:
            self._axis_item.setSize(
                x=self.time_extent,
                y=max(1.0, len(self.lanes) * LANE_SPACING),
                z=self.height_scale,
            )
        self._update_cursor_line()
        self.update()

    def _update_cursor_line(self):
        if self._cursor_line is None or not self.lanes:
            return
        scene_x = self._cursor_fraction * self.time_extent
        self._cursor_line.setData(pos=np.asarray([
            [scene_x, -0.55, 0.025],
            [scene_x, (len(self.lanes) - 1) * LANE_SPACING + 0.55, 0.025],
        ], dtype=np.float32))

    def mouseMoveEvent(self, event):
        self._cursor_fraction = max(
            0.0,
            min(1.0, event.position().x() / max(1, self.width())),
        )
        self._update_cursor_line()
        self.cursorMoved.emit(self._cursor_fraction * self.duration)
        super().mouseMoveEvent(event)
