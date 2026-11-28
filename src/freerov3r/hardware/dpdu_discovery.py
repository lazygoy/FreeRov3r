"""Passive discovery of ISO 22900-2 D-PDU API / MVCI modules.

The standard Windows discovery path is HKLM\\SOFTWARE\\D-PDU API, value
"Root File". The root description file (RDF) lists the installed D-PDU API
libraries and their MDF/CDF metadata. Discovery never loads a DLL or opens a
VCI.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Callable, Iterable
from urllib.parse import unquote, urlparse
import xml.etree.ElementTree as ET


D_PDU_REGISTRY_KEY = r"SOFTWARE\D-PDU API"
D_PDU_REGISTRY_VALUE = "Root File"
LINUX_D_PDU_ROOT = Path("/etc/pdu_api_root.xml")
MAX_RDF_BYTES = 4 * 1024 * 1024
MAX_MODULES = 256


@dataclass(frozen=True)
class DPduModuleRegistration:
    """One installed MVCI D-PDU API implementation from the RDF."""

    short_name: str
    library_file: str
    module_description_file: str
    cable_description_file: str
    description: str = ""
    supplier_name: str = ""
    root_file: str = ""


def _windows_root_files() -> list[str]:
    if os.name != "nt":
        return []
    try:
        import winreg
    except ImportError:
        return []

    paths: list[str] = []
    seen: set[str] = set()
    views = [
        getattr(winreg, "KEY_WOW64_64KEY", 0),
        getattr(winreg, "KEY_WOW64_32KEY", 0),
    ]
    for view in views:
        try:
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                D_PDU_REGISTRY_KEY,
                0,
                winreg.KEY_READ | view,
            )
        except OSError:
            continue
        with key:
            try:
                root_file, value_type = winreg.QueryValueEx(
                    key, D_PDU_REGISTRY_VALUE
                )
            except OSError:
                continue
        if not isinstance(root_file, str) or not root_file.strip():
            continue
        root_file = root_file.strip()
        identity = root_file.casefold()
        if identity not in seen:
            seen.add(identity)
            paths.append(root_file)
    return paths


def _uri_to_local_path(value: str) -> str:
    """Convert RDF file: URIs or plain paths to a local path string."""
    value = (value or "").strip()
    if not value:
        return ""
    parsed = urlparse(value)
    if parsed.scheme.casefold() != "file":
        return value
    path = unquote(parsed.path or "")
    if parsed.netloc and parsed.netloc.casefold() not in ("", "localhost"):
        path = "//" + parsed.netloc + path
    # file:/C:/Program%20Files/... is common in Windows RDF files. Preserve
    # the drive-qualified path rather than treating C: as a URL authority.
    if len(path) >= 3 and path[0] == "/" and path[2] == ":":
        path = path[1:]
    return path


def _local_tag(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1].upper()


def _child_text(element: ET.Element, name: str) -> str:
    wanted = name.upper()
    for child in element:
        if _local_tag(child) == wanted:
            return (child.text or "").strip()
    return ""


def _child_uri(element: ET.Element, name: str) -> str:
    wanted = name.upper()
    for child in element:
        if _local_tag(child) == wanted:
            return _uri_to_local_path(
                child.attrib.get("URI", "") or (child.text or "")
            )
    return ""


def parse_d_pdu_root_file(root_file: str) -> list[DPduModuleRegistration]:
    """Parse a local D-PDU RDF without loading any listed library."""
    path = Path(root_file)
    try:
        if not path.is_file():
            return []
        if path.stat().st_size > MAX_RDF_BYTES:
            return []
        tree = ET.parse(path)
    except (OSError, ET.ParseError, ValueError):
        return []

    root = tree.getroot()
    modules: list[DPduModuleRegistration] = []
    for element in root.iter():
        if _local_tag(element) != "MVCI_PDU_API":
            continue
        short_name = _child_text(element, "SHORT_NAME")
        library_file = _child_uri(element, "LIBRARY_FILE")
        mdf_file = (
            _child_uri(element, "MODULE_DESCRIPTION_FILE")
            or _child_uri(element, "MODULE_DESCRIPTION_PATH")
        )
        cdf_file = (
            _child_uri(element, "CABLE_DESCRIPTION_FILE")
            or _child_uri(element, "CABLE_DESCRIPTION_PATH")
        )

        def resolve_description_path(value: str) -> str:
            if not value:
                return ""
            # Keep Windows drive paths and UNC paths intact when inspecting
            # RDF files from another operating system.
            if len(value) >= 3 and value[1] == ":" and value[2] in ("/", "\\\\"):
                return value
            if value.startswith("\\\\\\\\"):
                return value
            candidate_path = Path(value)
            if not candidate_path.is_absolute():
                candidate_path = path.parent / candidate_path
            return str(candidate_path)

        mdf_file = resolve_description_path(mdf_file)
        cdf_file = resolve_description_path(cdf_file)
        # The required identifying and library fields must be present.
        if not short_name or not library_file:
            continue
        modules.append(DPduModuleRegistration(
            short_name=short_name,
            library_file=library_file,
            module_description_file=mdf_file,
            cable_description_file=cdf_file,
            description=_child_text(element, "DESCRIPTION"),
            supplier_name=_child_text(element, "SUPPLIER_NAME"),
            root_file=str(path),
        ))
        if len(modules) >= MAX_MODULES:
            break
    return modules


def discover_d_pdu_modules(
    root_files: Iterable[str] | None = None,
    *,
    root_file_reader: Callable[[], Iterable[str]] | None = None,
) -> list[DPduModuleRegistration]:
    """Discover installed D-PDU API implementations from their RDF files.

    On Windows, the standard registry Root File value is read in both registry
    views. On Linux, /etc/pdu_api_root.xml is checked. Tests and other hosts
    may inject root_files or a root_file_reader. DLLs are never loaded.
    """
    if root_files is None:
        if root_file_reader is not None:
            candidates = list(root_file_reader())
        elif os.name == "nt":
            candidates = _windows_root_files()
        elif LINUX_D_PDU_ROOT.is_file():
            candidates = [str(LINUX_D_PDU_ROOT)]
        else:
            candidates = []
    else:
        candidates = list(root_files)

    modules: list[DPduModuleRegistration] = []
    seen_roots: set[str] = set()
    seen_modules: set[tuple[str, str]] = set()
    for candidate in candidates:
        root_file = str(candidate or "").strip()
        if not root_file:
            continue
        root_identity = root_file.casefold()
        if root_identity in seen_roots:
            continue
        seen_roots.add(root_identity)
        for module in parse_d_pdu_root_file(root_file):
            identity = (module.short_name.casefold(), module.library_file.casefold())
            if identity in seen_modules:
                continue
            seen_modules.add(identity)
            modules.append(module)
            if len(modules) >= MAX_MODULES:
                return modules
    return modules
