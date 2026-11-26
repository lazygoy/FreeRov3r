"""Local, VIN-keyed diagnostic event history. No network access."""
import json
from datetime import datetime, timezone
from pathlib import Path


DTC_SCAN_EVENT_TYPES = {"dtc_scan_completed", "dtc_scan_failed"}


def filter_dtc_scan_events(events):
    """Return completed and failed OBD-II DTC scan events, preserving order."""
    return [event for event in events if event.get("type") in DTC_SCAN_EVENT_TYPES]


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
        return "\\n".join(lines)

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
    return "\\n".join(lines)


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
        return "\\n".join(lines)

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
    return "\\n".join(lines)


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
        return "\\n".join(lines)

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
    return "\\n".join(lines)
