"""CAN frame batch and OBD-II measurement processing."""

import time
from collections import deque

from PySide6.QtCore import QTimer

from .core.capture.frame_analysis import analyze_frame
from .sensors.capture import SensorSample

DISPLAY_REFRESH_MS = 100
MAX_PENDING_DISPLAY_LINES = 1000


def _new_display_queue():
    return {
        "frame_lines": deque(maxlen=MAX_PENDING_DISPLAY_LINES),
        "sensor_lines": deque(maxlen=MAX_PENDING_DISPLAY_LINES),
        "obd_values": {},
        "refresh_sensor_list": False,
        "dropped_frame_lines": 0,
        "dropped_sensor_lines": 0,
    }


def _queue_lines(pending, key, values, dropped_key):
    target = pending[key]
    for value in values:
        if len(target) == target.maxlen:
            pending[dropped_key] += 1
        target.append(value)


def flush_display_updates(window):
    """Paint accumulated display state without touching retained capture data."""
    pending = getattr(window, "_pending_display_updates", None)
    if not pending:
        window._display_flush_pending = False
        return
    window._display_flush_pending = False
    frame_lines = list(pending["frame_lines"])
    sensor_lines = list(pending["sensor_lines"])
    obd_values = dict(pending["obd_values"])
    refresh_sensor_list = pending["refresh_sensor_list"]
    dropped_frames = pending["dropped_frame_lines"]
    dropped_sensors = pending["dropped_sensor_lines"]
    window._pending_display_updates = _new_display_queue()

    if hasattr(window, "frame_count_label"):
        window.frame_count_label.setText(f"Frames: {window.frame_counter}")
    if frame_lines:
        if dropped_frames:
            frame_lines.insert(0, f"[Display skipped {dropped_frames} older frame log lines; capture retained]")
        window.log.appendPlainText("\n".join(frame_lines))
    if sensor_lines:
        if dropped_sensors:
            sensor_lines.insert(0, f"[Display skipped {dropped_sensors} older sensor log lines; samples retained]")
        window.sensor_log.appendPlainText("\n".join(sensor_lines))
    for pid, value in obd_values.items():
        window.obd_tab.update_value(pid, value)
    if refresh_sensor_list:
        window.graph_tab.refresh_sensor_list()


def _schedule_display_flush(window):
    if getattr(window, "_display_flush_pending", False):
        return
    window._display_flush_pending = True
    QTimer.singleShot(DISPLAY_REFRESH_MS, lambda: flush_display_updates(window))


def process_frames(window, frames):
    """Process every received frame, then schedule one coalesced UI refresh."""
    log_lines = []
    display_updates = {
        "sensor_lines": [],
        "obd_values": {},
        "refresh_sensor_list": False,
    }
    for frame in frames:
        line = process_frame(window, frame, update_display=False, display_updates=display_updates)
        if line:
            log_lines.append(line)

    pending = getattr(window, "_pending_display_updates", None)
    if pending is None:
        pending = _new_display_queue()
        window._pending_display_updates = pending
    _queue_lines(pending, "frame_lines", log_lines, "dropped_frame_lines")
    _queue_lines(pending, "sensor_lines", display_updates["sensor_lines"], "dropped_sensor_lines")
    pending["obd_values"].update(display_updates["obd_values"])
    pending["refresh_sensor_list"] |= display_updates["refresh_sensor_list"]
    if frames:
        _schedule_display_flush(window)


def process_frame(window, frame, update_display=True, display_updates=None):
    """Process one frame; optional accumulator defers widget work to batch end."""
    analysis = analyze_frame(frame, vin_decoder=window.vin_decoder,
                             scaling_context=window.obd_scaling_context)
    if analysis.detected_vin:
        window._apply_detected_vin(analysis.detected_vin)
    window.session.add(frame)
    window.can_monitor.add(frame)
    window.research_tab.observe_frame(frame)
    window.frame_counter += 1
    if update_display:
        window.frame_count_label.setText(f"Frames: {window.frame_counter}")
    ts = frame.timestamp or 0
    line = None
    if window.can_monitor.matches(frame, window.can_id_filter.text(), window.can_format_filter.currentText()):
        frame_type = "EXT" if frame.is_extended_id else "STD"
        line = (f"{ts:.6f}  {frame.arbitration_id:08X}  {frame_type}  "
                f"DLC {len(frame.data)}  {frame.data.hex(' ').upper()}")
        if update_display:
            window.log.appendPlainText(line)
    measurements = analysis.measurements
    if measurements:
        simulated = window.active_interface == "simulator"
        display_values = []
        for pid, key, name, value, unit in measurements:
            sensor_id = f"obd_{pid:02X}" if key == "value" else f"obd_{pid:02X}_{key}"
            window.sensor_capture.add(SensorSample(
                timestamp=ts or time.time(), sensor_id=sensor_id, name=name,
                value=value, unit=unit, source="simulated" if simulated else "ecu",
                ecu="SIMULATED ECU" if simulated else None,
                signal=f"Mode 01 PID {pid:02X}" + (f" {key}" if key != "value" else ""),
                metadata={"can_id": frame.arbitration_id, "raw": frame.data.hex(),
                          "vin": window.capture_vin or "UNASSIGNED"},
                monotonic_timestamp=time.monotonic(),
            ))
            window.graph_tab.mark_sample(sensor_id)
            if sensor_id not in window.graph_tab.known_sensor_ids:
                if display_updates is None:
                    window.graph_tab.refresh_sensor_list()
                else:
                    display_updates["refresh_sensor_list"] = True
            display_values.append(f"{value:.2f} {unit}")
            sensor_line = f"{name}: {value:.2f} {unit} [{sensor_id}]"
            if display_updates is None:
                window.sensor_log.appendPlainText(sensor_line)
            else:
                display_updates["sensor_lines"].append(sensor_line)
        obd_value = " | ".join(display_values)
        if display_updates is None:
            window.obd_tab.update_value(measurements[0][0], obd_value)
        else:
            display_updates["obd_values"][measurements[0][0]] = obd_value
    return line
