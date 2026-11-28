"""CAN frame batch and OBD-II measurement processing."""

import time

from .core.capture.frame_analysis import analyze_frame
from .sensors.capture import SensorSample


def process_frames(window, frames):
    """Process a receiver batch while coalescing all visible sensor updates."""
    log_lines = []
    display_updates = {
        "sensor_lines": [],
        "obd_values": {},
        "refresh_sensor_list": False,
    }
    for frame in frames:
        line = process_frame(
            window, frame, update_display=False, display_updates=display_updates
        )
        if line:
            log_lines.append(line)

    window.frame_count_label.setText(f"Frames: {window.frame_counter}")
    if log_lines:
        window.log.appendPlainText("\n".join(log_lines))
    if display_updates["sensor_lines"]:
        window.sensor_log.appendPlainText("\n".join(display_updates["sensor_lines"]))
    for pid, value in display_updates["obd_values"].items():
        window.obd_tab.update_value(pid, value)
    if display_updates["refresh_sensor_list"]:
        window.graph_tab.refresh_sensor_list()


def process_frame(window, frame, update_display=True, display_updates=None):
    """Process one frame; optional accumulator defers widget work to batch end."""
    analysis = analyze_frame(
        frame,
        vin_decoder=window.vin_decoder,
        scaling_context=window.obd_scaling_context,
    )
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
        line = (
            f"{ts:.6f}  {frame.arbitration_id:08X}  {frame_type}  "
            f"DLC {len(frame.data)}  {frame.data.hex(' ').upper()}"
        )
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
            known = any(
                window.graph_tab._sensor_id(window.graph_tab.sensor_list.item(i)) == sensor_id
                for i in range(window.graph_tab.sensor_list.count())
            )
            if not known:
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
            # Keep only the newest value for each PID in this receiver batch.
            display_updates["obd_values"][measurements[0][0]] = obd_value

    return line
