"""Conservative protocol hints for passively observed CAN payloads."""

UDS_SERVICES = {
    0x10: "DiagnosticSessionControl",
    0x11: "ECUReset",
    0x14: "ClearDiagnosticInformation",
    0x19: "ReadDTCInformation",
    0x22: "ReadDataByIdentifier",
    0x23: "ReadMemoryByAddress",
    0x27: "SecurityAccess",
    0x28: "CommunicationControl",
    0x2E: "WriteDataByIdentifier",
    0x2F: "InputOutputControlByIdentifier",
    0x31: "RoutineControl",
    0x34: "RequestDownload",
    0x35: "RequestUpload",
    0x36: "TransferData",
    0x37: "RequestTransferExit",
    0x3E: "TesterPresent",
    0x85: "ControlDTCSetting",
}


def classify_can_payload(payload):
    """Return conservative ISO-TP/UDS hints; never claims to identify intent."""
    data = bytes(payload or b"")
    if not data:
        return "—", "—"

    pci_type = data[0] >> 4
    if pci_type == 0 and len(data) > 1:
        if data[0] & 0x0F:
            service_index = 1
        elif len(data) > 2:
            service_index = 2
        else:
            return "ISO-TP SF", "Extended-length single frame"
        service = data[service_index]
        name = UDS_SERVICES.get(service)
        if service == 0x7F and len(data) >= 3:
            original = UDS_SERVICES.get(data[2], f"0x{data[2]:02X}")
            return "ISO-TP SF", f"Negative response to {original} (NRC 0x{data[3]:02X})" if len(data) > 3 else f"Negative response to {original}"
        if name:
            return "ISO-TP SF", name
        if 0x40 <= service <= 0x7E:
            request_name = UDS_SERVICES.get(service - 0x40)
            if request_name:
                return "ISO-TP SF", f"Positive response to {request_name} (0x{service:02X})"
            return "ISO-TP SF", f"Possible positive response 0x{service:02X}"
        return "ISO-TP SF", "Unclassified service"

    if pci_type == 1:
        return "ISO-TP FF", "First frame"
    if pci_type == 2:
        return "ISO-TP CF", f"Consecutive frame (sequence {data[0] & 0x0F})"
    if pci_type == 3:
        flow = {0: "Continue", 1: "Wait", 2: "Overflow"}.get(data[0] & 0x0F, "Unknown")
        return "ISO-TP FC", f"Flow control: {flow}"

    # Reassembled ISO-TP payloads no longer contain a PCI byte.
    service = data[0]
    if service == 0x7F and len(data) >= 3:
        original = UDS_SERVICES.get(data[1], f"0x{data[1]:02X}")
        return "UDS payload", f"Negative response to {original} (NRC 0x{data[2]:02X})"
    if 0x40 <= service <= 0x7E:
        request_name = UDS_SERVICES.get(service - 0x40)
        if request_name:
            return "UDS payload", f"Positive response to {request_name} (0x{service:02X})"
    if service in UDS_SERVICES:
        return "UDS payload", f"Possible raw UDS: {UDS_SERVICES[service]}"
    return "Unclassified", "No reliable UDS classification"



def classify_uds_payload(payload):
    """Name a UDS service in a reassembled application payload."""
    data = bytes(payload or b"")
    if not data:
        return "Empty payload"
    service = data[0]
    if service == 0x7F:
        if len(data) < 3:
            return "Malformed negative response"
        original = UDS_SERVICES.get(data[1], f"0x{data[1]:02X}")
        return f"Negative response to {original} (NRC 0x{data[2]:02X})"
    if service in UDS_SERVICES:
        return UDS_SERVICES[service]
    if 0x40 <= service <= 0x7E:
        original = UDS_SERVICES.get(service - 0x40)
        if original:
            return f"Positive response to {original}"
    return f"Unclassified service 0x{service:02X}"
