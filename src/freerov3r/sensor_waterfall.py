"""Perspective 3D waterfall/ridgeline visualization for live sensor samples."""

import math

from PySide6.QtCore import Qt, QTimer, QPointF
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QComboBox, QDialog, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QVBoxLayout, QWidget,
)

from .sensors.scaling import sample_clock, sample_time
from .sensors.demo import generate_lr4_demo_samples


def _downsample_minmax(samples, clock, start, end, max_points):
    """Keep temporal shape and sharp transients while limiting render work."""
    ordered = sorted(samples, key=lambda sample: sample_time(sample, clock))
    visible = [s for s in ordered if start <= sample_time(s, clock) <= end]
    if len(visible) <= max_points:
        return visible
    bucket_count = max(1, max_points // 2)
    span = max(end - start, 1e-9)
    buckets = [[] for _ in range(bucket_count)]
    for sample in visible:
        index = min(bucket_count - 1, int((sample_time(sample, clock) - start) / span * bucket_count))
        buckets[index].append(sample)
    reduced = []
    for bucket in buckets:
        if not bucket:
            continue
        low = min(bucket, key=lambda s: float(s.value))
        high = max(bucket, key=lambda s: float(s.value))
        reduced.extend((low, high) if low is not high else (low,))
    return sorted(reduced, key=lambda sample: sample_time(sample, clock))


def prepare_waterfall_lanes(samples, selected_ids=None, window_seconds=60,
                            max_points=180, scale_mode="native", vin=None):
    """Prepare independent sensor lanes without modifying captured samples.

    Native mode maps each lane to its own local vertical range and reports that
    range in metadata. Normalized mode maps each lane to 0..100 percent.
    """
    selected = set(selected_ids) if selected_ids is not None else None
    grouped = {}
    for sample in samples or ():
        if selected is not None and sample.sensor_id not in selected:
            continue
        if vin and (sample.metadata or {}).get("vin", "UNASSIGNED") != vin:
            continue
        try:
            value = float(sample.value)
            timestamp = float(sample.timestamp)
        except (TypeError, ValueError):
            continue
        if sample.quality != "valid" or not math.isfinite(value) or not math.isfinite(timestamp):
            continue
        grouped.setdefault(sample.sensor_id, []).append(sample)

    all_samples = [sample for lane in grouped.values() for sample in lane]
    if not all_samples:
        return []
    clock = sample_clock(all_samples)
    latest = max(sample_time(sample, clock) for sample in all_samples)
    earliest = min(sample_time(sample, clock) for sample in all_samples)
    start = max(earliest, latest - window_seconds) if window_seconds else earliest
    lanes = []
    for sensor_id, lane_samples in grouped.items():
        visible = _downsample_minmax(lane_samples, clock, start, latest, max_points)
        if not visible:
            continue
        values = [float(sample.value) for sample in visible]
        low, high = min(values), max(values)
        span = high - low
        points = []
        for sample in visible:
            value = float(sample.value)
            if scale_mode == "normalized":
                z = 50.0 if span == 0 else (value - low) / span * 100.0
            else:
                z = 0.5 if span == 0 else (value - low) / span
            points.append((sample_time(sample, clock) - start, z))
        last = max(lane_samples, key=lambda sample: sample_time(sample, clock))
        lanes.append({
            "sensor_id": sensor_id,
            "name": last.name,
            "unit": last.unit or "unitless",
            "minimum": low,
            "maximum": high,
            "current": float(last.value),
            "points": points,
        })
    return sorted(lanes, key=lambda lane: lane["name"].casefold())


class WaterfallPlot(QWidget):
    """QPainter-based perspective ridgeline plot; no optional 3D runtime needed."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.lanes = []
        self.duration = 1.0
        self.lane_count = 1
        self.yaw = 0.0
        self.zoom = 1.0
        self.vertical_exaggeration = 1.0
        self._drag_pos = None
        self.setMinimumSize(820, 420)
        self.setMouseTracking(True)

    def set_lanes(self, lanes):
        self.lanes = lanes
        self.lane_count = max(1, len(lanes))
        self.setMinimumHeight(max(420, 92 + self.lane_count * 54))
        self.duration = max(
            (point[0] for lane in lanes for point in lane["points"]),
            default=1.0,
        ) or 1.0
        self.update()

    def _project(self, x, lane, z, rect):
        left = rect.left() + 220
        top = rect.top() + 54
        plot_width = max(100.0, rect.width() - 250)
        row_height = max(1.0, (rect.height() - 104) / self.lane_count)
        lane_height = min(
            row_height * 0.62,
            min(48.0, row_height * 0.58) * self.vertical_exaggeration,
        )
        # Normalized waterfall values are stored as 0..100; native lanes as 0..1.
        z_fraction = z / 100.0 if z > 1.0 else z
        perspective = lane * min(12.0, plot_width * 0.012) * self.zoom
        px = left + (x / self.duration) * plot_width * self.zoom + perspective
        py = top + lane * row_height + row_height * 0.78 - z_fraction * lane_height
        return px, py

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor("#0B1220"))
        painter.setPen(QColor("#E2E8F0"))
        painter.drawText(18, 25, "SENSOR HISTORY · ONE ROW PER SIGNAL")
        if not self.lanes:
            painter.setPen(QColor("#94A3B8"))
            painter.drawText(self.rect(), Qt.AlignCenter, "Waiting for valid sensor samples")
            painter.end()
            return

        top = 54
        bottom = self.height() - 50
        left = 220
        right = self.width() - 24
        plot_width = max(100, right - left)
        row_height = max(1.0, (bottom - top) / self.lane_count)
        palette = ("#38BDF8", "#F59E0B", "#F472B6", "#4ADE80",
                   "#A78BFA", "#FACC15", "#FB923C", "#60A5FA")

        painter.setPen(QPen(QColor("#334155"), 1, Qt.DashLine))
        for fraction in (0.0, 0.25, 0.5, 0.75, 1.0):
            x = left + plot_width * fraction
            painter.drawLine(int(x), top, int(x), bottom)
            painter.setPen(QColor("#94A3B8"))
            painter.drawText(int(x - 12), self.height() - 22, f"{fraction:.0%}")
            painter.setPen(QPen(QColor("#334155"), 1, Qt.DashLine))

        for index, lane in enumerate(self.lanes):
            row_top = top + index * row_height
            baseline_y = row_top + row_height * 0.78
            painter.setPen(QPen(QColor("#263449"), 1))
            painter.drawLine(left, int(baseline_y), right, int(baseline_y))
            painter.setPen(QColor("#E2E8F0"))
            painter.drawText(14, int(row_top + row_height * 0.43),
                             f'{lane["name"]} [{lane["unit"]}]')
            painter.setPen(QColor("#94A3B8"))
            detail = (f'min {lane["minimum"]:.4g}  max {lane["maximum"]:.4g}  '
                      f'now {lane["current"]:.4g}')
            painter.drawText(14, int(row_top + row_height * 0.72), detail)

            points = lane["points"]
            if not points:
                continue
            color = QColor(palette[index % len(palette)])
            polyline = QPolygonF()
            for x_value, z_value in points:
                px, py = self._project(x_value, index, z_value, self.rect())
                polyline.append(QPointF(px, py))
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(color, 2.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            if len(polyline) == 1:
                painter.drawEllipse(polyline.at(0), 3.5, 3.5)
            else:
                painter.drawPolyline(polyline)

        painter.setPen(QColor("#CBD5E1"))
        painter.drawText(left, self.height() - 22,
                         "Elapsed time across selected history window")
        painter.end()

    def wheelEvent(self, event):
        factor = 1.12 if event.angleDelta().y() > 0 else 1 / 1.12
        self.zoom = min(2.5, max(0.55, self.zoom * factor))
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.position().toPoint()

    def mouseMoveEvent(self, event):
        if self._drag_pos is not None:
            delta = event.position().toPoint() - self._drag_pos
            self.yaw = min(55, max(-35, self.yaw + delta.x() * 0.35))
            self.vertical_exaggeration = min(
                2.5, max(0.45, self.vertical_exaggeration - delta.y() * 0.008)
            )
            self._drag_pos = event.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, event):
        self._drag_pos = None


class SensorWaterfallDialog(QDialog):
    """Live 3D sensor view with independent lane scales and visibility controls."""

    def __init__(self, sensor_capture, vin_provider=None, parent=None):
        super().__init__(parent)
        self.sensor_capture = sensor_capture
        self.demo_samples = generate_lr4_demo_samples()
        self.vin_provider = vin_provider or (lambda: None)
        self.setWindowTitle("FreeRov3r | 3D Sensor Waterfall")
        self.resize(1100, 720)
        layout = QVBoxLayout(self)
        controls = QHBoxLayout()
        controls.addWidget(QLabel("History:"))
        self.window_combo = QComboBox()
        for label, seconds in (
            ("10 seconds", 10), ("30 seconds", 30), ("1 minute", 60),
            ("5 minutes", 300), ("15 minutes", 900), ("All samples", 0),
        ):
            self.window_combo.addItem(label, seconds)
        self.window_combo.setCurrentIndex(2)
        controls.addWidget(self.window_combo)
        controls.addWidget(QLabel("Vertical scale:"))
        self.scale_combo = QComboBox()
        self.scale_combo.addItem("Native units (independent per sensor)", "native")
        self.scale_combo.addItem("Normalized (0–100%)", "normalized")
        controls.addWidget(self.scale_combo)
        controls.addWidget(QLabel("Data source:"))
        self.source_combo = QComboBox()
        self.source_combo.addItem("Live sensor data", "live")
        self.source_combo.addItem("Synthetic LR4 demo", "demo")
        controls.addWidget(self.source_combo)
        controls.addStretch(1)
        layout.addLayout(controls)
        self.sensor_list = QListWidget()
        self.sensor_list.setMaximumHeight(104)
        self.sensor_list.itemChanged.connect(self.refresh_plot)
        layout.addWidget(self.sensor_list)
        self.plot = WaterfallPlot(self)
        layout.addWidget(self.plot, 1)
        self.window_combo.currentIndexChanged.connect(self.refresh_plot)
        self.source_combo.currentIndexChanged.connect(self.refresh_sensor_choices)
        self.scale_combo.currentIndexChanged.connect(self.refresh_plot)
        self.refresh_sensor_choices()
        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(750)
        self.refresh_timer.timeout.connect(self.refresh_sensor_choices)
        self.refresh_timer.start()
        self.refresh_plot()

    def refresh_sensor_choices(self):
        vin = self.vin_provider()
        available = {}
        source = self.source_combo.currentData()
        samples = (self.demo_samples if source == "demo"
                   else self.sensor_capture.samples)
        if source == "demo":
            vin = None
        for sample in samples:
            if vin and (sample.metadata or {}).get("vin", "UNASSIGNED") != vin:
                continue
            available.setdefault(sample.sensor_id, sample.name)
        selected = {
            self.sensor_list.item(i).data(Qt.UserRole)
            for i in range(self.sensor_list.count())
            if self.sensor_list.item(i).checkState() == Qt.Checked
        }
        expected = {sensor_id: f"{name} ({sensor_id})" for sensor_id, name in available.items()}
        current = {
            self.sensor_list.item(i).data(Qt.UserRole): self.sensor_list.item(i).text()
            for i in range(self.sensor_list.count())
        }
        if current != expected:
            self.sensor_list.blockSignals(True)
            self.sensor_list.clear()
            for sensor_id, name in sorted(available.items(), key=lambda item: item[1].casefold()):
                item = QListWidgetItem(f"{name} ({sensor_id})")
                item.setData(Qt.UserRole, sensor_id)
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Checked if not selected or sensor_id in selected else Qt.Unchecked)
                self.sensor_list.addItem(item)
            self.sensor_list.blockSignals(False)
        self.refresh_plot()

    def refresh_plot(self, *_):
        selected = {
            self.sensor_list.item(i).data(Qt.UserRole)
            for i in range(self.sensor_list.count())
            if self.sensor_list.item(i).checkState() == Qt.Checked
        }
        lanes = prepare_waterfall_lanes(
            (self.demo_samples if self.source_combo.currentData() == "demo"
             else self.sensor_capture.samples),
            selected_ids=selected,
            window_seconds=int(self.window_combo.currentData()),
            scale_mode=self.scale_combo.currentData(),
            vin=(None if self.source_combo.currentData() == "demo" else self.vin_provider()),
        )
        self.plot.set_lanes(lanes)
