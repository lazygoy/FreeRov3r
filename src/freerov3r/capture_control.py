"""CAN capture start/stop orchestration."""

import time
from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QMessageBox

from .hardware.receiver import Receiver
from .hardware.dual_channel_simulator import DualChannelSimulator
from .hardware.capture_replay_adapter import CaptureReplayAdapter
from .hardware.simulated_vehicle import SimulatedVehicleAdapter
from .hardware.esp32_serial_adapter import Esp32SerialAdapter
from .hardware.esp32_dual_serial_adapter import Esp32DualSerialAdapter
from .hardware.elm327_serial_adapter import Elm327SerialAdapter
from .hardware.elm327_obd_adapter import Elm327ObdAdapter
from .hardware.python_can_adapter import PythonCanAdapter
from .core.capture.session_context import CaptureSessionContext


def toggle_capture(window):
    if window.receiver and window.receiver.isRunning():
        window.receiver.stop()
        window.obd_tab.set_dtc_scan_enabled(False)
        diagnostics = getattr(window.active_adapter, "diagnostics", None)
        if isinstance(diagnostics, dict):
            window._last_receiver_diagnostics = diagnostics
        context = window.capture_session_context
        elapsed = context.elapsed_seconds() if context else max(
            0.0, time.time() - (window.capture_started_at or time.time())
        )
        sample_start = context.sample_start_index if context else window.capture_start_sample_index
        frame_start = context.frame_start_index if context else window.capture_start_frame_index
        capture_samples = window.sensor_capture.samples_since(sample_start)
        capture_samples_dropped = max(
            0,
            window.sensor_capture.total_samples_added
            - window.capture_start_sample_index
            - len(capture_samples),
        )
        capture_frames = window.session.frames[frame_start:]
        archive_path = window.history_store.archive_capture(
            (context.vin if context else window.capture_vin),
            {
                "interface": context.interface if context else window.active_interface,
                "channel": context.channel if context else window.capture_channel,
                "bitrate": context.bitrate if context else window.capture_bitrate,
                "started_at": context.started_at if context else window.capture_started_at,
                "duration_seconds": round(elapsed, 2),
                "sensor_samples_dropped_from_bounded_buffer": capture_samples_dropped,
                "frames": [
                    {"timestamp": frame.timestamp, "arbitration_id": frame.arbitration_id,
                     "extended": frame.is_extended_id, "data": frame.data.hex(),
                     "channel": frame.channel}
                    for frame in capture_frames
                ],
                "sensor_samples": [
                    {"timestamp": sample.timestamp, "sensor_id": sample.sensor_id,
                     "name": sample.name, "value": sample.value, "unit": sample.unit,
                     "source": sample.source, "ecu": sample.ecu, "signal": sample.signal,
                     "quality": sample.quality, "metadata": sample.metadata}
                    for sample in capture_samples
                ],
            },
        )
        window.record_vehicle_event(
            "capture_completed", "CAN capture stopped",
            {
                **(context.event_metadata(
                    frame_count=len(capture_frames),
                    sample_count=len(capture_samples),
                    dropped_samples=capture_samples_dropped,
                ) if context else {
                    "interface": window.active_interface,
                    "channel": window.capture_channel or "Unknown",
                    "bitrate": window.capture_bitrate or "Unknown",
                    "frames": len(capture_frames),
                    "sensor_samples": len(capture_samples),
                    "sensor_samples_dropped_from_bounded_buffer": capture_samples_dropped,
                    "duration_seconds": round(elapsed, 2),
                }),
                "archive_file": str(archive_path),
            },
            vin=(context.vin if context else window.capture_vin) or "UNASSIGNED",
        )
        window.capture_session_context = None
        window.capture_started_at = None
        window.capture_channel = None
        window.capture_bitrate = None
        window.capture_vin = None
        window.receiver = None
        window.active_adapter = None
        window.research_tab.set_receiver_diagnostics(window._last_receiver_diagnostics)
        window.connect_btn.setText("Start listening")
        window.status.setText("Disconnected")
        window._refresh_workspace_header()
        window.show_toast("CAN capture stopped", "info")
        return

    data = window.backend.currentData()
    interface = data[0]
    channel = window.channel_edit.currentText().strip() or data[1]
    bitrate = int(window.bitrate.currentText())

    if interface == "elm327_obd" and not window.obd_tab.selected_pids():
        window.show_toast("Select at least one OBD-II PID to poll", "warning")
        return

    if interface == "dual_simulator":
        channel = "HS-CAN,MS-CAN"
        adapter = DualChannelSimulator()
    elif interface == "capture_replay":
        replay_path = channel
        if not replay_path or not Path(replay_path).is_file():
            replay_path, _ = QFileDialog.getOpenFileName(
                window, "Select FreeRov3r capture", str(Path.home()),
                "FreeRov3r captures (*.jsonl);;All files (*)",
            )
        if not replay_path:
            return
        channel = replay_path
        adapter = CaptureReplayAdapter(replay_path)
    elif interface == "simulator":
        adapter = SimulatedVehicleAdapter(channel=channel or "L319-DEMO")
    elif interface == "esp32":
        adapter = Esp32SerialAdapter(port=channel)
    elif interface == "esp32_dual":
        ports = [part.strip() for part in channel.split(",") if part.strip()]
        if len(ports) != 2 or ports[0].casefold() == ports[1].casefold():
            QMessageBox.warning(
                window, "Dual ESP32 connection",
                "Enter two different serial ports, for example COM4,COM5."
            )
            return
        adapter = Esp32DualSerialAdapter(ports, channel_names=("HS-CAN", "MS-CAN"))
    elif interface == "elm327":
        adapter = Elm327SerialAdapter(port=channel)
    elif interface == "elm327_obd":
        adapter = Elm327ObdAdapter(
            port=channel,
            pids=window.obd_tab.selected_pids(),
            request_interval=window.obd_tab.poll_interval_ms.value() / 1000.0,
        )
    else:
        adapter = PythonCanAdapter(interface=interface, channel=channel, bitrate=bitrate)

    window.active_interface = interface
    window.obd_scaling_context.clear()
    window.active_adapter = adapter
    window._last_receiver_diagnostics = {}
    window.research_tab.set_receiver_diagnostics({})
    window.capture_vin = window.settings.get("current_vin")
    window.research_tab.set_context(window.capture_vin, interface)
    window.capture_session_context = CaptureSessionContext.begin(
        interface=interface,
        channel=channel,
        bitrate=bitrate,
        vin=window.capture_vin,
        frame_start_index=len(window.session.frames),
        sample_start_index=window.sensor_capture.total_samples_added,
    )
    window.capture_started_at = window.capture_session_context.started_at
    window.capture_channel = channel
    window.capture_bitrate = bitrate
    window.capture_start_frames = 0
    window.capture_start_sample_index = window.capture_session_context.sample_start_index
    window.capture_start_frame_index = window.capture_session_context.frame_start_index
    window.record_vehicle_event(
        "capture_started", "CAN capture started",
        {"interface": interface, "channel": channel, "bitrate": bitrate},
        vin=window.capture_vin or "UNASSIGNED",
    )
    window.vin_decoder.reset()
    window.can_monitor.reset()
    window.log.clear()
    window.refresh_can_display()
    window.modules_tab.set_simulation_enabled(interface == "simulator")
    window.receiver = Receiver(adapter)
    window.receiver.frames_received.connect(window.on_frames)
    window.receiver.status.connect(window.status.setText)
    window.receiver.dtcs_completed.connect(window._on_dtc_scan_completed)
    window.receiver.dtcs_failed.connect(window._on_dtc_scan_failed)
    window.receiver.readiness_completed.connect(window._on_readiness_scan_completed)
    window.receiver.readiness_failed.connect(window._on_readiness_scan_failed)
    window.receiver.freeze_frame_completed.connect(window._on_freeze_frame_scan_completed)
    window.receiver.freeze_frame_failed.connect(window._on_freeze_frame_scan_failed)
    window.receiver.vehicle_info_completed.connect(window._on_vehicle_info_scan_completed)
    window.receiver.vehicle_info_failed.connect(window._on_vehicle_info_scan_failed)
    window.receiver.monitor_tests_completed.connect(window._on_monitor_tests_scan_completed)
    window.receiver.monitor_tests_failed.connect(window._on_monitor_tests_scan_failed)
    window.obd_tab.set_dtc_scan_enabled(interface == "elm327_obd")
    window.receiver.start()
    window.connect_btn.setText("Stop listening")
    window.frame_counter = 0
    window.last_rate_count = 0
    window.last_rate_time = time.monotonic()
    window.settings.update({"interface": interface, "channel": channel, "bitrate": bitrate})
    for i in range(window.settings_backend.count()):
        if window.settings_backend.itemData(i)[0] == interface:
            window.settings_backend.setCurrentIndex(i)
            break
    window.settings_channel.setText(channel)
    window.settings_bitrate.setCurrentText(str(bitrate))
    window._refresh_workspace_header()
    window.show_toast("CAN listener started", "success")
