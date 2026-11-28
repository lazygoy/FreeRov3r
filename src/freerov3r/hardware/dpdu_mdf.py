"""Passive ISO 22900-2 MDF/CDF capability parsing.

MDF data describes what a module type supports. CDF data describes how
module-side pins map to diagnostic-link-connector (DLC) pins for each cable.
Neither file proves that a cable is currently attached or a resource is free.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import xml.etree.ElementTree as ET


MAX_DESCRIPTION_FILE_BYTES = 8 * 1024 * 1024
MAX_DESCRIPTION_OBJECTS = 8192


class DPduDescriptionError(ValueError):
    """A D-PDU description file is unreadable or structurally unsafe."""


@dataclass(frozen=True)
class DPduPinType:
    object_id: int
    short_name: str
    description: str = ""
    eid: str = ""


@dataclass(frozen=True)
class DPduBusType:
    object_id: int
    short_name: str
    description: str = ""
    eid: str = ""


@dataclass(frozen=True)
class DPduProtocol:
    object_id: int
    short_name: str
    description: str = ""
    eid: str = ""


@dataclass(frozen=True)
class DPduModuleType:
    object_id: int
    short_name: str
    description: str = ""
    resource_eids: tuple[str, ...] = ()


@dataclass(frozen=True)
class DPduResourcePin:
    module_pin_number: int
    pin_type_id: int
    pin_type_name: str
    pin_type_eid: str


@dataclass(frozen=True)
class DPduResource:
    object_id: int
    short_name: str
    description: str
    eid: str
    bus_type_id: int
    bus_type_name: str
    protocol_id: int
    protocol_name: str
    pins: tuple[DPduResourcePin, ...]


@dataclass(frozen=True)
class DPduModuleDescription:
    path: str
    description: str
    supplier_name: str
    file_version: str
    standard_version: str
    pin_types: tuple[DPduPinType, ...]
    bus_types: tuple[DPduBusType, ...]
    protocols: tuple[DPduProtocol, ...]
    resources: tuple[DPduResource, ...]
    module_types: tuple[DPduModuleType, ...]

    def resources_for_module_type(self, module_type_id: int) -> tuple[DPduResource, ...]:
        module_type = next(
            (item for item in self.module_types if item.object_id == module_type_id),
            None,
        )
        if module_type is None:
            return ()
        wanted = set(module_type.resource_eids)
        return tuple(resource for resource in self.resources if resource.eid in wanted)


@dataclass(frozen=True)
class DPduCablePinMapping:
    dlc_pin_number: int
    module_pin_number: int


@dataclass(frozen=True)
class DPduCable:
    object_id: int
    short_name: str
    description: str
    dlc_type_eid: str
    mappings: tuple[DPduCablePinMapping, ...]


@dataclass(frozen=True)
class DPduCableDescription:
    path: str
    description: str
    supplier_name: str
    file_version: str
    standard_version: str
    cables: tuple[DPduCable, ...]


@dataclass(frozen=True)
class DPduDlcPin:
    dlc_pin_number: int
    pin_type_id: int
    pin_type_name: str
    module_pin_number: int


def _tag(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1].upper()


def _children(element: ET.Element, name: str) -> list[ET.Element]:
    target = name.upper()
    return [child for child in element if _tag(child) == target]


def _child(element: ET.Element, name: str) -> ET.Element | None:
    matches = _children(element, name)
    return matches[0] if matches else None


def _text(element: ET.Element, name: str, default: str = "") -> str:
    child = _child(element, name)
    return (child.text or "").strip() if child is not None else default


def _integer(value: str, *, field: str) -> int:
    try:
        token = value.strip()
        number = int(token, 16) if token.lower().startswith("0x") else int(token, 10)
    except (AttributeError, ValueError) as exc:
        raise DPduDescriptionError(f"Invalid {field} value: {value!r}") from exc
    if not 0 <= number <= 0xFFFFFFFF:
        raise DPduDescriptionError(f"{field} outside unsigned 32-bit range: {number}")
    return number


def _read_root(path: str | Path, expected_root: str) -> tuple[ET.Element, Path]:
    source = Path(path)
    try:
        if not source.is_file():
            raise DPduDescriptionError(f"Description file not found: {source}")
        if source.stat().st_size > MAX_DESCRIPTION_FILE_BYTES:
            raise DPduDescriptionError(f"Description file exceeds size limit: {source}")
        root = ET.parse(source).getroot()
    except DPduDescriptionError:
        raise
    except (OSError, ET.ParseError, ValueError) as exc:
        raise DPduDescriptionError(f"Cannot parse description file {source}: {exc}") from exc
    if _tag(root) != expected_root:
        raise DPduDescriptionError(
            f"Expected {expected_root}, found {_tag(root)} in {source}"
        )
    return root, source


def _object(element: ET.Element, kind: str):
    object_id = _integer(_text(element, "ID"), field=f"{kind}.ID")
    short_name = _text(element, "SHORT_NAME")
    if not short_name:
        raise DPduDescriptionError(f"{kind} {object_id} has no SHORT_NAME")
    return object_id, short_name, _text(element, "DESCRIPTION"), element.attrib.get("EID", "")


def parse_d_pdu_mdf(path: str | Path) -> DPduModuleDescription:
    """Parse module types, buses, protocols, resources, and module-side pins."""
    root, source = _read_root(path, "MVCI_MODULE_DESCRIPTION")
    pin_by_eid: dict[str, DPduPinType] = {}
    bus_by_eid: dict[str, DPduBusType] = {}
    protocol_by_eid: dict[str, DPduProtocol] = {}
    resource_eids: set[str] = set()
    module_types: list[DPduModuleType] = []
    resources_raw: list[ET.Element] = []

    for element in root:
        kind = _tag(element)
        if kind == "PINTYPE":
            object_id, name, desc, eid = _object(element, kind)
            if not eid or eid in pin_by_eid:
                raise DPduDescriptionError(f"Missing or duplicate PINTYPE EID: {eid!r}")
            pin_by_eid[eid] = DPduPinType(object_id, name, desc, eid)
        elif kind == "BUSTYPE":
            object_id, name, desc, eid = _object(element, kind)
            if not eid or eid in bus_by_eid:
                raise DPduDescriptionError(f"Missing or duplicate BUSTYPE EID: {eid!r}")
            bus_by_eid[eid] = DPduBusType(object_id, name, desc, eid)
        elif kind == "PROTOCOL":
            object_id, name, desc, eid = _object(element, kind)
            if not eid or eid in protocol_by_eid:
                raise DPduDescriptionError(f"Missing or duplicate PROTOCOL EID: {eid!r}")
            protocol_by_eid[eid] = DPduProtocol(object_id, name, desc, eid)
        elif kind == "RESOURCE":
            resources_raw.append(element)
        elif kind == "MODULETYPE":
            object_id, name, desc, _eid = _object(element, kind)
            refs = tuple(
                child.attrib.get("IDREF", "")
                for child in _children(element, "RESOURCE")
                if child.attrib.get("IDREF")
            )
            module_types.append(DPduModuleType(object_id, name, desc, refs))

    if sum(map(len, (pin_by_eid, bus_by_eid, protocol_by_eid, resources_raw, module_types))) > MAX_DESCRIPTION_OBJECTS:
        raise DPduDescriptionError("MDF contains too many description objects")

    parsed_resources: list[DPduResource] = []
    for element in resources_raw:
        object_id, name, desc, eid = _object(element, "RESOURCE")
        if not eid or eid in resource_eids:
            raise DPduDescriptionError(f"Missing or duplicate RESOURCE EID: {eid!r}")
        resource_eids.add(eid)
        bus_element = _child(element, "BUSTYPE")
        protocol_element = _child(element, "PROTOCOL")
        bus_ref = bus_element.attrib.get("IDREF", "") if bus_element is not None else ""
        protocol_ref = protocol_element.attrib.get("IDREF", "") if protocol_element is not None else ""
        if bus_ref not in bus_by_eid:
            raise DPduDescriptionError(f"RESOURCE {name} references unknown BUSTYPE {bus_ref!r}")
        if protocol_ref not in protocol_by_eid:
            raise DPduDescriptionError(f"RESOURCE {name} references unknown PROTOCOL {protocol_ref!r}")
        pins: list[DPduResourcePin] = []
        for pin in _children(element, "PIN_ON_MODULE"):
            pin_number = _integer(_text(pin, "PIN_ON_MODULE"), field=f"{name}.PIN_ON_MODULE")
            pin_type_element = _child(pin, "PINTYPE")
            pin_ref = (
                pin_type_element.attrib.get("IDREF", "")
                if pin_type_element is not None else ""
            )
            pin_type = pin_by_eid.get(pin_ref)
            if pin_type is None:
                raise DPduDescriptionError(f"RESOURCE {name} references unknown PINTYPE {pin_ref!r}")
            pins.append(DPduResourcePin(
                module_pin_number=pin_number,
                pin_type_id=pin_type.object_id,
                pin_type_name=pin_type.short_name,
                pin_type_eid=pin_ref,
            ))
        if not pins:
            raise DPduDescriptionError(f"RESOURCE {name} has no PIN_ON_MODULE entries")
        bus = bus_by_eid[bus_ref]
        protocol = protocol_by_eid[protocol_ref]
        parsed_resources.append(DPduResource(
            object_id, name, desc, eid, bus.object_id, bus.short_name,
            protocol.object_id, protocol.short_name, tuple(pins),
        ))

    unknown_refs = {
        ref for module in module_types for ref in module.resource_eids
        if ref not in resource_eids
    }
    if unknown_refs:
        raise DPduDescriptionError(
            "MODULETYPE references unknown RESOURCE EID(s): " + ", ".join(sorted(unknown_refs))
        )

    return DPduModuleDescription(
        path=str(source),
        description=_text(root, "DESCRIPTION"),
        supplier_name=_text(root, "SUPPLIER_NAME"),
        file_version=root.attrib.get("FILE_VERSION", ""),
        standard_version=root.attrib.get("MVCI_PART2_STANDARD_VERSION", ""),
        pin_types=tuple(pin_by_eid.values()),
        bus_types=tuple(bus_by_eid.values()),
        protocols=tuple(protocol_by_eid.values()),
        resources=tuple(parsed_resources),
        module_types=tuple(module_types),
    )


def parse_d_pdu_cdf(path: str | Path) -> DPduCableDescription:
    """Parse cable definitions and their module-pin to DLC-pin mappings."""
    root, source = _read_root(path, "MVCI_CABLE_DESCRIPTION")
    cables: list[DPduCable] = []
    for element in _children(root, "CABLE"):
        object_id, name, desc, _eid = _object(element, "CABLE")
        dlc_type = _child(element, "DLCTYPE")
        dlc_type_eid = dlc_type.attrib.get("IDREF", "") if dlc_type is not None else ""
        mappings: list[DPduCablePinMapping] = []
        for mapping in _children(element, "MAPPING"):
            mappings.append(DPduCablePinMapping(
                dlc_pin_number=_integer(_text(mapping, "PIN_ON_DLC"), field=f"{name}.PIN_ON_DLC"),
                module_pin_number=_integer(_text(mapping, "PIN_ON_MODULE"), field=f"{name}.PIN_ON_MODULE"),
            ))
        cables.append(DPduCable(object_id, name, desc, dlc_type_eid, tuple(mappings)))
        if len(cables) > MAX_DESCRIPTION_OBJECTS:
            raise DPduDescriptionError("CDF contains too many cable definitions")
    return DPduCableDescription(
        path=str(source),
        description=_text(root, "DESCRIPTION"),
        supplier_name=_text(root, "SUPPLIER_NAME"),
        file_version=root.attrib.get("FILE_VERSION", ""),
        standard_version=root.attrib.get("MVCI_PART2_STANDARD_VERSION", ""),
        cables=tuple(cables),
    )


def map_resource_to_dlc_pins(
    resource: DPduResource,
    cable: DPduCable,
) -> tuple[DPduDlcPin, ...]:
    """Map the resource's module pins through one explicitly selected cable."""
    module_to_dlc: dict[int, int] = {}
    for mapping in cable.mappings:
        if mapping.module_pin_number in module_to_dlc:
            raise DPduDescriptionError(
                f"Cable {cable.short_name} maps module pin "
                f"{mapping.module_pin_number} more than once"
            )
        module_to_dlc[mapping.module_pin_number] = mapping.dlc_pin_number

    mapped: list[DPduDlcPin] = []
    for pin in resource.pins:
        dlc_pin = module_to_dlc.get(pin.module_pin_number)
        if dlc_pin is None:
            raise DPduDescriptionError(
                f"Cable {cable.short_name} does not map module pin {pin.module_pin_number}"
            )
        mapped.append(DPduDlcPin(
            dlc_pin_number=dlc_pin,
            pin_type_id=pin.pin_type_id,
            pin_type_name=pin.pin_type_name,
            module_pin_number=pin.module_pin_number,
        ))
    return tuple(mapped)
