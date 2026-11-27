# J2534 and D-PDU Integration Architecture

## Scope

FreeRov3r will support a hardware-independent diagnostic interface spanning:

- SAE J2534 Pass-Thru devices, beginning with API 04.04 and adding 05.00 only where a driver exposes it.
- ISO 22900-2 D-PDU API / MVCI modules.
- Existing native CAN, SocketCAN, ESP32, ELM327, and simulator adapters.
- Vehicle-independent CAN, ISO-TP, OBD-II, and UDS services.
- Vehicle profiles and plugins that describe verified ECU addressing, services, identifiers, and capabilities.

J2534 and D-PDU are interface standards, not universal ECU unlocks. They standardize access to communication hardware; vehicle-specific diagnostic sequences, credentials, programming data, and authorization remain separate concerns.

## Existing foundation

The repository already has:

- `hardware.base.CanAdapter` as a small receive-oriented adapter abstraction.
- `hardware.capabilities.AdapterCapabilities` and independent `TransmitPolicy` gates.
- `isotp_transport.IsoTpTransport` for bounded classic-CAN ISO-TP transport.
- `diagnostics.uds` for a read-only UDS payload codec.
- `diagnostics.uds_client.UdsDiagnosticClient` for guarded read-only UDS transactions.
- Separate safety authorization in `safety.SafetyPolicy`.

The J2534/D-PDU work must extend these layers. It must not create a second ISO-TP or UDS engine.

## Planned layers

### 1. Driver inventory

The first implementation is read-only Windows registry discovery. It reports the registered device name, vendor, FunctionLibrary DLL path, optional configuration application, API version, and registry location.

Discovery must not load vendor DLLs, open hardware, probe a vehicle, or transmit. Missing or malformed registrations are reported as unavailable rather than guessed.

### 2. J2534 runtime adapter

A later Windows-specific adapter will load the registered vendor DLL only after an explicit user-selected open action. It will isolate vendor calls behind a narrow runtime interface and map J2534 statuses, errors, messages, filters, and channel lifecycle into FreeRov3r's internal types.

Requirements:

- Explicit DLL path and API-version selection.
- Correct Windows calling convention and fixed-width/native ABI declarations.
- Serialized access to vendor functions unless a vendor documents thread safety.
- Bounded waits and cancellation where the API permits.
- Deterministic close/cleanup on errors.
- No silent fallback to another device or API version.
- Device capabilities must be based on declared and tested support, not on the existence of a DLL.

### 3. D-PDU / MVCI adapter

D-PDU support will be a separate provider because its module discovery, resource model, protocol configuration, and lifecycle differ from J2534. The application will discover installed MVCI protocol modules and their module-description metadata, then expose supported resources through the same internal adapter contract.

J2534 and D-PDU may share normalized CAN/diagnostic operations, but their vendor APIs must remain isolated behind separate provider implementations.

### 4. Protocol services

CAN framing, ISO-TP, UDS payload encoding/decoding, OBD-II, DTC handling, and transaction policy remain vehicle-independent. An adapter provides frames or diagnostic PDUs; it does not decide which ECU service is appropriate.

The transport layer must preserve:
- Addressing mode and transmit/receive identifiers.
- CAN classic/CAN FD support as explicitly declared.
- Padding and timing parameters.
- Flow-control behavior.
- Message timestamps and source-interface metadata.
- Per-frame authorization for active transmission.

### 5. Vehicle profiles and plugins

The first complete reference profile remains Land Rover L319 / Discovery 3 and Discovery 4, with the naturally aspirated 5.0L petrol V8 as the initial validation target.

Profiles must state exact supported model years, engine/ECU variants, network buses, addressing, service coverage, and evidence confidence. Unknown or unverified values remain unknown. Other manufacturers can contribute profiles without changing the shared transport engine.

## Safety and authorization model

The following are independent permissions and must never be inferred from device discovery:

1. Passive receive/capture.
2. Standard OBD-II diagnostic requests.
3. UDS diagnostic requests.
4. General raw CAN transmission.
5. UDS session control, security access, routines, reset, write services, and programming.

The initial J2534 discovery feature grants none of these permissions.

Read-only UDS support remains the default diagnostic scope. Security-access research may document observed seed/key exchanges and implement authorized access for a verified, supported ECU when the method and authorization are established. It must not turn into a generic immobilizer or anti-theft defeat feature.

Programming remains disabled unless exact ECU identity, file compatibility, verified original backups, stable power, a validated recovery route, and explicit operator approval are all present. The existing dual-location recovery archive requirements remain mandatory.

## Development sequence and exit criteria

| Step | Work | Exit criteria |
|---|---|---|
| 1 | J2534 registry discovery | Deterministic inventory; malformed entries ignored; no DLL loading or vehicle I/O |
| 2 | J2534 ABI/runtime wrapper | Mocked API tests; vendor DLL lifecycle and error mapping verified |
| 3 | J2534 CAN receive path | Timestamped frames; filters and timeouts verified on supported hardware |
| 4 | J2534 controlled transmit path | Independent capability/policy gates and per-frame authorization tested |
| 5 | D-PDU/MVCI discovery | Installed module metadata and supported resources inventoried |
| 6 | D-PDU runtime adapter | Provider lifecycle and protocol mapping verified with a supported VCI |
| 7 | Shared ISO-TP/UDS integration | Reuse existing transport/client; no duplicate protocol implementation |
| 8 | LR3/LR4 profile validation | ECU identities, addressing, services, and results recorded with evidence |
| 9 | Security and programming research | Module-specific authorization, backup, recovery, and verification gates proven |

A feature is not considered hardware-verified because it passes mocked tests. Hardware verification must identify the exact VCI model, driver version, firmware, API version, vehicle, ECU identity, and test result.

## First implementation

`hardware.j2534_discovery` performs registry-only inventory for the J2534 04.04 and 05.00 registration roots. It is intentionally not a J2534 communication adapter. No vendor DLL is loaded and no vehicle communication is attempted.


## J2534 runtime slice: receive-only classic CAN

The current branch now includes `hardware.j2534_adapter.J2534CanAdapter`.
It binds the required J2534 exports using the Windows stdcall loader and
fixed-width 32-bit DWORD fields, opens the selected registered driver, opens
one classic-CAN channel, installs a receive pass filter, and reads one frame
at a time.

The runtime currently supports:

- Classic CAN only, with a configurable protocol baud rate (default 500 kbit/s).
- 11-bit and 29-bit CAN identifiers.
- J2534 millisecond device timestamps preserved as microseconds in the
  device-clock domain.
- Bounded read timeouts and explicit driver status errors.
- Filter, channel, and device cleanup on normal close and connection failure.
- An injected DLL loader so the ABI and lifecycle can be tested without
  hardware.

It intentionally does not bind or call `PassThruWriteMsgs`. It does not yet
support ISO15765 protocol channels, CAN FD, K-Line, multiple simultaneous
channels, flow-control filters, or vendor-specific IOCTLs. These are separate
follow-on capabilities and must be added only with tests and verified device
support.

The mocked driver tests validate the structure size, open/connect/filter/read/
disconnect/close lifecycle, 11-bit and 29-bit frame decoding, timestamps,
empty receive buffers, malformed identifiers, and driver errors. CI results
are authoritative for software tests; physical hardware compatibility remains
unverified until exercised with an identified VCI and driver version.


## Capture workspace integration

J2534 registrations are now included in the unified passive interface inventory
used by the Capture workspace, serial-port selector, vehicle setup wizard, and
settings backend selector. A discovered J2534 entry displays its registered
FunctionLibrary path as the selectable device value.

Selecting J2534 routes capture startup through `J2534CanAdapter` using the
selected bitrate. The existing Receiver owns the adapter lifecycle on its
worker thread. The initial J2534 selection is receive-only; it does not enable
OBD polling, UDS requests, or CAN transmission.


## D-PDU API discovery slice

The branch now includes `hardware.dpdu_discovery`. On Windows it reads the
standard `HKLM\\SOFTWARE\\D-PDU API` registry key and its `Root File`
string value in both 64-bit and 32-bit registry views. It parses the referenced
D-PDU API root description file (RDF), extracting each MVCI_PDU_API entry's
symbolic name, library path, module description file (MDF), cable description
file (CDF), description, and supplier.

The parser accepts the standard URI attributes and plain path text, handles
namespaced XML tags, bounds RDF file size and module count, and ignores
incomplete or malformed entries. On Linux it can inspect
`/etc/pdu_api_root.xml`; tests may inject root-file paths.

Discovery is passive: it does not load any D-PDU DLL, call PDU functions,
enumerate live VCI resources, or connect to a vehicle. The RDF identifies
installed D-PDU API implementations, not necessarily currently connected
physical VCIs. Runtime integration must next load a selected API DLL and use
its standard module/resource enumeration functions to determine live devices.

The D-PDU discovery implementation follows the ISO 22900-2 root-file discovery
model and RDF entry structure. The standard defines the root file as the
application entry point for installed MVCI protocol modules, with library,
MDF, and CDF references. The 2022 edition is the current published edition.


## D-PDU runtime slice: passive live-module inventory

The branch now includes `hardware.dpdu_runtime.DPduApiRuntime`. It loads only
the user-selected API library and binds the ISO 22900-2 exports
`PDUConstruct`, `PDUGetModuleIds`, `PDUDestroyItem`, and `PDUDestruct`
using the Windows `__stdcall` ABI (or the platform C ABI on Linux).

The runtime performs the standard construction and module-list query. It
returns module type IDs, API-assigned module handles, module status, and
vendor-provided identity/connection strings. The API-owned module-list item
is released with `PDUDestroyItem`, and the API session is closed with
`PDUDestruct`, including error paths.

This is deliberately a module-interface inventory, not a claim that every
reported module is ready for diagnostics. A module must report an appropriate
status and be explicitly connected in a later, separate step before resources
or diagnostic links can be used. This slice does not call
`PDUModuleConnect`, `PDUGetResourceIds`, `PDUCreateComLogicalLink`, or
any communication primitive. No vehicle-bus communication or transmit path
is exposed.

The module enumeration ABI follows ISO 22900-2:2022 clauses 8.4.2, 8.4.3,
8.4.20, 8.4.24, 8.7.2.2, and 10.1.4.2 / 10.1.4.6. The standard explicitly
specifies that Windows D-PDU exports use `__stdcall`, and that
`PDUConstruct` initializes the API and detects modules while remaining
offline with no allocation of communication resources and no vehicle
communication. Resource enumeration is a subsequent stage because it requires
MDF-derived bus, protocol, and DLC-pin identifiers.

Mocked tests cover export validation, ABI-shaped structures, successful and
empty inventories, bounded module counts, API error handling, item destruction,
and session cleanup. Real vendor DLL compatibility remains unverified until
tested against an identified API implementation and VCI.


## D-PDU capability and resource-ID slice

The branch now includes `hardware.dpdu_mdf`, which parses the standard
`MVCI_MODULE_DESCRIPTION` MDF and `MVCI_CABLE_DESCRIPTION` CDF files.

MDF parsing extracts:
- PINTYPE IDs and names.
- BUSTYPE IDs and names.
- PROTOCOL IDs and names.
- RESOURCE IDs, bus/protocol references, and module-side pin assignments.
- MODULETYPE IDs and the resources associated with each module type.

CDF parsing extracts cable definitions and the mappings between MVCI module
pins and DLC pins. The mapping helper requires one explicitly selected cable.
It does not assume that a cable is physically attached, and it fails if a
resource pin is not mapped by that cable.

The D-PDU runtime now also exposes
`DPduApiRuntime.enumerate_resource_ids()`. It builds the standard
`PDU_RSC_DATA` structure from bus type ID, protocol ID, and DLC pin/type
pairs, calls `PDUGetResourceIds`, copies the returned module/resource ID
lists, and releases the API-owned result with `PDUDestroyItem`.

This operation queries the D-PDU API's constructed resource table. It does
not call `PDUModuleConnect`, create a ComLogicalLink, or transmit vehicle
traffic. Resource availability and conflicts are separate checks and are not
inferred from an ID match. The selected module handle and pin mapping must
come from the matching module inventory, MDF, and selected CDF cable.

The parser is bounded by file-size and object-count limits, resolves XML
IDREF relationships, supports namespaced XML, and rejects unresolved resource
references rather than guessing. Tests cover MDF resource resolution, module
type membership, CDF pin mapping, namespaced documents, invalid references,
relative description paths, and mocked PDUGetResourceIds memory handling.

The ISO description model defines resources as a bus type, protocol, and
physical pins; the MDF supplies supported IDs and the CDF maps module pins to
the vehicle connector. PDUGetResourceIds accepts those identifiers and
returns API-allocated resource-ID items that the application must destroy.


## D-PDU resource status and conflict inventory

The runtime now supports two additional resource queries:

- `DPduApiRuntime.enumerate_conflicts(resource_id)` calls
  `PDUGetConflictingResources` using the current or explicitly supplied
  module inventory. It returns conflicting module handles and resource IDs,
  and releases the API-allocated conflict item with `PDUDestroyItem`.
- `DPduApiRuntime.get_resource_status(module_handle, resource_ids)` calls
  `PDUGetResourceStatus` with an application-owned
  `PDU_RSC_STATUS_ITEM`, returning the raw status bitfield plus decoded
  in-use and available flags.

The ISO 22900-2:2022 rules matter here: `PDUGetConflictingResources` is
permitted before `PDUModuleConnect`, but `PDUGetResourceStatus` requires the
module to be connected. The runtime therefore exposes an explicit
`connect_module()` / `disconnect_module()` pair. It does not connect modules
automatically when opening the API or listing resources.

`PDUModuleConnect` initializes the selected MVCI module and its system-level
driver, and obtains its resource table while the D-PDU communication state
remains offline. It does not create a ComLogicalLink, allocate a diagnostic
resource, connect to the vehicle bus, or send vehicle messages. This is a
separate hardware-initialization step and must be requested explicitly.
Connected modules are disconnected during normal runtime cleanup before
`PDUDestruct`.

Resource status is a bitfield, not a single enum: bit 0 reports in-use and
bit 1 reports not-available. FreeRov3r preserves the raw value and exposes
those two flags separately so unknown or vendor-defined bits are not lost.

Tests cover the explicit module-connect prerequisite, status bit decoding,
module-disconnect cleanup, conflict-list decoding, module inventory structure
construction, and API-owned conflict-item destruction. All runtime tests use
mocked D-PDU libraries; real VCI compatibility is not established by CI.
