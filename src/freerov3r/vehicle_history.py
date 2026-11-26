"""Local, VIN-keyed diagnostic event history. No network access."""
import csv
import json
from datetime import datetime, timezone
from pathlib import Path


DTC_SCAN_EVENT_TYPES = {"dtc_scan_completed", "dtc_scan_failed"}


def filter_dtc_scan_events(events):
    """Return completed and failed OBD-II DTC scan events, preserving order."""
    return [event for event in events if event.get("type") in DTC_SCAN_EVENT_TYPES]


def search_history_events(events, query):
    """Search all recorded event fields, including nested details, case-insensitively."""
    term = str(query or "").strip().casefold()
    if not term:
        return list(events)
    matches = []
    for event in events:
        searchable = json.dumps(event, ensure_ascii=False, sort_keys=True, default=str)
        if term in searchable.casefold():
            matches.append(event)
    return matches


def format_readiness_scan_event(event):
    """Format a stored PID 01 readiness scan without inferring test status."""
    details = event.get("details") or {}
    lines = [
        f"Event: {event.get('type', '')}",
        f"Timestamp: {event.get('timestamp', '')}",
        f"VIN: {event.get('vin', 'UNASSIGNED')}",
        f"Summary: {event.get('summary', '')}",
        f"Interface: {details.get('interface', 'Unknown')}",
        f"Read-only: {'Yes' if details.get('read_only') else 'Not recorded'}",
    ]
    if event.get("type") == "readiness_scan_failed":
        lines.extend(["", f"Error: {details.get('error', 'No error detail recorded')}"])
        return "\n".join(lines)

    lines.extend(["", "READINESS RESULTS"])
    results = details.get("results") or []
    if not results:
        lines.append("No valid PID 01 response was returned.")
    for result in results:
        lines.extend([
            "",
            f"ECU: {int(result.get('arbitration_id', 0)):08X} "
            f"({'29-bit' if result.get('is_extended_id') else '11-bit'})",
            f"Channel: {result.get('channel', 'Unknown')}",
            f"Ignition: {result.get('ignition_type', 'Unknown')}",
            f"MIL: {'ON' if result.get('mil_on') else 'OFF'}",
            f"DTC count: {result.get('dtc_count', 'Unknown')}",
            "Monitors:",
        ])
        for monitor in result.get("monitors") or []:
            complete = monitor.get("complete")
            state = "N/A" if complete is None else ("Complete" if complete else "Incomplete")
            lines.append(
                f"  {monitor.get('name', 'unknown')} | "
                f"{'Supported' if monitor.get('supported') else 'Not supported'} | {state}"
            )
        lines.append(f"Raw: {result.get('raw', '')}")
    return "\n".join(lines)


def format_dtc_scan_event(event):
    """Format a stored DTC scan as readable text without inventing descriptions."""
    details = event.get("details") or {}
    lines = [
        f"Event: {event.get('type', '')}",
        f"Timestamp: {event.get('timestamp', '')}",
        f"VIN: {event.get('vin', 'UNASSIGNED')}",
        f"Summary: {event.get('summary', '')}",
        f"Interface: {details.get('interface', 'Unknown')}",
        f"Read-only: {'Yes' if details.get('read_only') else 'Not recorded'}",
    ]
    if event.get("type") == "dtc_scan_failed":
        lines.extend(["", f"Error: {details.get('error', 'No error detail recorded')}"])
        return "\n".join(lines)

    services = details.get("services") or []
    lines.extend([
        f"Services: {', '.join(str(service) for service in services) or 'Not recorded'}",
        f"Code records: {details.get('count', len(details.get('dtcs') or []))}",
        "",
        "TROUBLE CODES",
    ])
    codes = details.get("dtcs") or []
    if not codes:
        lines.append("No codes were returned.")
    for code in codes:
        lines.append(
            f"{code.get('code', 'Unknown')} | {code.get('status', 'Unknown')} | "
            f"ECU {int(code.get('arbitration_id', 0)):08X} "
            f"({'29-bit' if code.get('is_extended_id') else '11-bit'}) | "
            f"Channel {code.get('channel', 'Unknown')} | Raw {code.get('raw', '')}"
        )
    lines.extend(["", "OEM-specific descriptions are not inferred by this report."])
    return "\n".join(lines)


class VehicleHistoryStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.events = []
        self.load()

    def load(self):
        if not self.path.exists():
            self.events = []
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.events = data if isinstance(data, list) else []
        except (OSError, json.JSONDecodeError):
            self.events = []

    def record(self, vin, event_type, summary, details=None):
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "vin": vin or "UNASSIGNED",
            "type": str(event_type),
            "summary": str(summary),
            "details": details or {},
        }
        self.events.append(event)
        self.save()
        return event

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(self.events, indent=2, ensure_ascii=False), encoding="utf-8")
        temporary.replace(self.path)

    def archive_capture(self, vin, capture):
        vehicle_key = vin or "UNASSIGNED"
        safe_key = "".join(ch for ch in vehicle_key if ch.isalnum() or ch in "-_")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        folder = self.path.parent / "vehicles" / safe_key / "captures"
        folder.mkdir(parents=True, exist_ok=True)
        archive = folder / f"capture_{stamp}.json"
        archive.write_text(json.dumps(capture, indent=2, ensure_ascii=False), encoding="utf-8")
        return archive

    def for_vin(self, vin):
        return [event for event in self.events if event.get("vin") == (vin or "UNASSIGNED")]

    def vehicles(self):
        return sorted({event.get("vin", "UNASSIGNED") for event in self.events})


MODE06_SCAN_EVENT_TYPES = {"monitor_tests_scan_completed", "monitor_tests_scan_failed"}


def filter_mode06_scan_events(events):
    """Return completed and failed OBD-II Mode 06 scans, preserving order."""
    return [event for event in events if event.get("type") in MODE06_SCAN_EVENT_TYPES]


def format_mode06_scan_event(event):
    """Format a stored Mode 06 scan using raw values only; never infer units."""
    details = event.get("details") or {}
    lines = [
        f"Event: {event.get('type', '')}",
        f"Timestamp: {event.get('timestamp', '')}",
        f"VIN: {event.get('vin', 'UNASSIGNED')}",
        f"Summary: {event.get('summary', '')}",
        f"Interface: {details.get('interface', 'Unknown')}",
        f"Read-only: {'Yes' if details.get('read_only') else 'Not recorded'}",
    ]
    if event.get("type") == "monitor_tests_scan_failed":
        lines.extend(["", f"Error: {details.get('error', 'No error detail recorded')}"])
        return "\n".join(lines)

    supported = details.get("supported_monitor_ids") or []
    responses = details.get("results", {}).get("responses", [])
    lines.extend([
        f"Supported monitor IDs: {', '.join(f'{int(mid):02X}' for mid in supported) or 'None reported'}",
        f"ECU responses: {len(responses)}",
        "",
        "MODE 06 TEST RESULTS (RAW)",
    ])
    result_count = 0
    for response in responses:
        arbitration_id = response.get("arbitration_id")
        ecu = "Unknown" if arbitration_id is None else (
            f"{int(arbitration_id):08X} "
            f"({'29-bit' if response.get('is_extended_id') else '11-bit'})"
        )
        for result in response.get("results") or []:
            result_count += 1
            lines.extend([
                "",
                f"ECU: {ecu}",
                f"Channel: {response.get('channel', 'Unknown')}",
                f"MID: {int(response.get('monitor_id', result.get('monitor_id', 0))):02X}",
                f"TID: {int(result.get('test_id', 0)):02X}",
                f"UASID: {int(result.get('unit_scaling_id', 0)):02X}",
                f"Value (raw): {result.get('value_raw', 'Unknown')}",
                f"Minimum (raw): {result.get('minimum_raw', 'Unknown')}",
                f"Maximum (raw): {result.get('maximum_raw', 'Unknown')}",
                f"Limit comparison: {result.get('status', 'Unknown')}",
                f"Record bytes: {result.get('raw', 'Not recorded')}",
            ])
    if not result_count:
        lines.append("No valid Mode 06 result records were returned.")
    lines.extend(["", "Values are raw. No engineering units or scaling are inferred."])
    return "\n".join(lines)


READINESS_SCAN_EVENT_TYPES = {"readiness_scan_completed", "readiness_scan_failed"}
FREEZE_FRAME_SCAN_EVENT_TYPES = {"freeze_frame_scan_completed", "freeze_frame_scan_failed"}
VEHICLE_INFO_SCAN_EVENT_TYPES = {"vehicle_info_scan_completed", "vehicle_info_scan_failed"}


def filter_readiness_scan_events(events):
    """Return completed and failed OBD-II readiness scans, preserving order."""
    return [event for event in events if event.get("type") in READINESS_SCAN_EVENT_TYPES]


def filter_freeze_frame_scan_events(events):
    """Return completed and failed OBD-II freeze-frame scans, preserving order."""
    return [event for event in events if event.get("type") in FREEZE_FRAME_SCAN_EVENT_TYPES]


def filter_vehicle_info_scan_events(events):
    """Return completed and failed OBD-II vehicle-information scans, preserving order."""
    return [event for event in events if event.get("type") in VEHICLE_INFO_SCAN_EVENT_TYPES]


def filter_obd_scan_events(events):
    """Return all supported OBD-II scan event types, preserving event order."""
    scan_types = (
        DTC_SCAN_EVENT_TYPES | READINESS_SCAN_EVENT_TYPES |
        FREEZE_FRAME_SCAN_EVENT_TYPES | VEHICLE_INFO_SCAN_EVENT_TYPES |
        MODE06_SCAN_EVENT_TYPES
    )
    return [event for event in events if event.get("type") in scan_types]


def format_freeze_frame_scan_event(event):
    """Format stored Mode 02 measurements with their decoded PID labels and units."""
    details = event.get("details") or {}
    lines = [
        f"Event: {event.get('type', '')}",
        f"Timestamp: {event.get('timestamp', '')}",
        f"VIN: {event.get('vin', 'UNASSIGNED')}",
        f"Summary: {event.get('summary', '')}",
        f"Interface: {details.get('interface', 'Unknown')}",
        f"Read-only: {'Yes' if details.get('read_only') else 'Not recorded'}",
    ]
    if event.get("type") == "freeze_frame_scan_failed":
        lines.extend(["", f"Error: {details.get('error', 'No error detail recorded')}"])
        return "\n".join(lines)

    frame_number = details.get("frame_number", "Unknown")
    results = details.get("results") or []
    lines.extend([
        f"Freeze-frame number: {frame_number}",
        f"PID responses: {len(results)}",
        "",
        "FREEZE-FRAME MEASUREMENTS",
    ])
    measurement_count = 0
    for result in results:
        arbitration_id = result.get("arbitration_id")
        ecu = "Unknown" if arbitration_id is None else (
            f"{int(arbitration_id):08X} "
            f"({'29-bit' if result.get('is_extended_id') else '11-bit'})"
        )
        lines.extend([
            "",
            f"PID: {result.get('pid', 'Unknown')}",
            f"ECU: {ecu}",
            f"Channel: {result.get('channel', 'Unknown')}",
            f"Response frame: {result.get('frame_number', frame_number)}",
        ])
        measurements = result.get("measurements") or []
        if not measurements:
            lines.append("No decoded measurements were stored.")
        for measurement in measurements:
            measurement_count += 1
            value = measurement.get("value", "Unknown")
            unit = measurement.get("unit", "")
            lines.append(
                f"  {measurement.get('name', measurement.get('key', 'Unknown'))}: "
                f"{value}{(' ' + str(unit)) if unit else ''}"
            )
        lines.append(f"Raw response: {result.get('raw', 'Not recorded')}")
    if not results:
        lines.append("No valid freeze-frame PID responses were returned.")
    lines.extend(["", f"Decoded measurements: {measurement_count}"])
    return "\n".join(lines)


def format_vehicle_info_scan_event(event):
    """Format standardized Mode 09 identification records without guessing."""
    details = event.get("details") or {}
    lines = [
        f"Event: {event.get('type', '')}",
        f"Timestamp: {event.get('timestamp', '')}",
        f"VIN: {event.get('vin', 'UNASSIGNED')}",
        f"Summary: {event.get('summary', '')}",
        f"Interface: {details.get('interface', 'Unknown')}",
        f"Read-only: {'Yes' if details.get('read_only') else 'Not recorded'}",
    ]
    if event.get("type") == "vehicle_info_scan_failed":
        lines.extend(["", f"Error: {details.get('error', 'No error detail recorded')}"])
        return "\n".join(lines)

    results = details.get("results") or []
    record_count = sum(len(result.get("items") or []) for result in results)
    lines.extend([
        f"ECU responses: {len(results)}",
        f"Identification records: {record_count}",
        "",
        "VEHICLE IDENTIFICATION",
    ])
    for result in results:
        arbitration_id = result.get("arbitration_id")
        ecu = "Unknown" if arbitration_id is None else (
            f"{int(arbitration_id):08X} "
            f"({'29-bit' if result.get('is_extended_id') else '11-bit'})"
        )
        lines.extend([
            "",
            f"PID: {int(result.get('pid', 0)):02X} | {result.get('name', 'Unknown')}",
            f"ECU: {ecu}",
            f"Channel: {result.get('channel', 'Unknown')}",
            f"Record count: {result.get('count', len(result.get('items') or []))}",
        ])
        items = result.get("items") or []
        if not items:
            lines.append("  No identification records returned.")
        for item in items:
            lines.append(
                f"  {item.get('type', 'record')}: {item.get('value', 'Unknown')}"
            )
        lines.append(f"Raw response: {result.get('raw', 'Not recorded')}")
    if not results:
        lines.append("No valid Mode 09 ECU responses were returned.")
    return "\n".join(lines)


def format_capture_event(event):
    """Format CAN capture lifecycle and VIN-detection events from recorded metadata."""
    details = event.get("details") or {}
    lines = [
        f"Event: {event.get('type', '')}",
        f"Timestamp: {event.get('timestamp', '')}",
        f"VIN: {event.get('vin', 'UNASSIGNED')}",
        f"Summary: {event.get('summary', '')}",
    ]
    event_type = event.get("type")
    if event_type == "vin_detected":
        lines.extend([
            "",
            "VIN IDENTIFICATION",
            f"Detected VIN: {details.get('vin', 'Not recorded')}",
            f"Source: {details.get('source', 'Not recorded')}",
        ])
    else:
        lines.extend([
            "",
            "CAN CAPTURE",
            f"Interface: {details.get('interface', 'Unknown')}",
        ])
        if event_type == "capture_started":
            lines.extend([
                f"Channel: {details.get('channel', 'Unknown')}",
                f"Bitrate: {details.get('bitrate', 'Unknown')}",
                "Status: Started",
            ])
        elif event_type == "capture_completed":
            lines.extend([
                f"Frames recorded: {details.get('frames', 'Unknown')}",
                f"Sensor samples: {details.get('sensor_samples', 'Unknown')}",
                f"Sensor samples dropped from bounded buffer: {details.get('sensor_samples_dropped_from_bounded_buffer', 'Not recorded')}",
                f"Duration: {details.get('duration_seconds', 'Unknown')} seconds",
                f"Archive file: {details.get('archive_file', 'Not recorded')}",
                "Status: Completed",
            ])
        else:
            lines.append("Status: Unknown capture event")
    return "\n".join(lines)


def export_history_json(path, events):
    """Export selected history events as a UTF-8 JSON array."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(list(events), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return destination


def export_history_csv(path, events):
    """Export selected history events with structured details kept as JSON."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=("timestamp", "vin", "type", "summary", "details"),
        )
        writer.writeheader()
        for event in events:
            writer.writerow({
                "timestamp": event.get("timestamp", ""),
                "vin": event.get("vin", "UNASSIGNED"),
                "type": event.get("type", ""),
                "summary": event.get("summary", ""),
                "details": json.dumps(
                    event.get("details") or {}, ensure_ascii=False, sort_keys=True
                ),
            })
    return destination
