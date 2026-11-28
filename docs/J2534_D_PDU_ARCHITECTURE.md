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
status and be explicitly connected before module-specific operations that
require READY state. Opening the API and enumerating modules do not call
`PDUModuleConnect`. Separate methods support `PDUGetResourceIds`,
`PDUGetResourceStatus`, and `PDUGetConflictingResources`; the first and
third remain available without module connection, and resource status is an
API-level query that does not require module connection. Explicit
`PDUModuleConnect` is required before creating a ComLogicalLink. The runtime
now supports offline CLL creation and destruction, but still does not call
`PDUConnect`, create a ComPrimitive, or communicate on the vehicle bus.

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
The separate CLL lifecycle is documented below.

The parser is bounded by file-size and object-count limits, resolves XML
IDREF relationships, supports namespaced XML, and rejects unresolved resource
references rather than guessing. Tests cover MDF resource resolution, module
type membership, CDF pin mapping, namespaced documents, invalid references,
relative description paths, and mocked PDUGetResourceIds memory handling.

The ISO description model defines resources as a bus type, protocol, and
physical pins; the MDF supplies supported IDs and the CDF maps module pins to
the vehicle connector. PDUGetResourceIds accepts those identifiers and
returns API-allocated resource-ID items that the application must destroy.


## D-PDU resource status, conflicts, and offline logical links

The runtime supports:
- `DPduApiRuntime.enumerate_conflicts(resource_id)`, which calls
  `PDUGetConflictingResources` using the current or explicitly supplied
  module inventory, copies the conflicting module/resource pairs, and frees
  the API-owned result with `PDUDestroyItem`.
- `DPduApiRuntime.get_resource_status(module_handle, resource_ids)`, which
  calls `PDUGetResourceStatus` with an application-owned
  `PDU_RSC_STATUS_ITEM`. The returned status is preserved as a raw integer;
  FreeRov3r does not invent a universal bit decoding.

Both resource inventory calls are API-level queries. In particular,
`PDUGetResourceStatus` does not require `PDUModuleConnect`. The standard's
function prototype and behavior describe an application-allocated status item
filled by the API, without a module-connect precondition.

`PDUModuleConnect` initializes the selected MVCI module and its system-level
driver, transitioning the module to READY. It does not create a ComLogicalLink,
connect a CLL to the vehicle bus, or send vehicle messages. This remains an
explicit operation.

The runtime now supports
`create_logical_link(module_handle, resource_id)` and
`destroy_logical_link(module_handle, logical_link_handle)`. Creation uses
the ISO specific-resource-ID scheme: `pRscData=NULL`, the selected resource
ID, and a caller-provided CLL handle output. The new ComLogicalLink is
recorded as OFFLINE. Creation reserves the selected resource in the D-PDU
resource table, but does not call `PDUConnect`; it therefore does not
physically connect the logical link to the vehicle interface or begin ECU
communication. The module must be explicitly initialized first. A module
cannot be disconnected while one of its CLLs remains registered. Runtime
cleanup destroys CLLs before disconnecting modules and then calls
`PDUDestruct`.

The next separate stage is physical `PDUConnect` / `PDUDisconnect`
lifecycle. That will be treated as vehicle-interface activation and will not
be triggered by CLL creation. No ComPrimitive, receive operation, or transmit
operation is exposed by this slice.

Tests cover resource status without module connection, explicit module
initialization, offline CLL creation and destruction, cleanup ordering,
conflict-list decoding, module inventory structure construction, and
API-owned conflict-item destruction. All runtime tests use mocked D-PDU
libraries; real VCI compatibility is not established by CI.


## D-PDU typed ComParam working-buffer updates

The runtime now exposes `set_com_param_uint32(module_handle, cll_handle,
param_id, value)` for the standard `PDU_PT_UNUM32` ComParam type.

The method uses the ISO-defined sequence:
1. `PDUGetComParam` retrieves the API-owned parameter item for the MDF
   ComParam ID.
2. FreeRov3r verifies the returned ID and data type, then changes only the
   32-bit value in the returned data buffer. The API-provided class and
   structure are retained.
3. `PDUSetComParam` copies the new value into the CLL working buffer.
4. `PDUDestroyItem` releases the API-owned parameter item.

This method only accepts an existing tracked OFFLINE ComLogicalLink and a
module that has been explicitly initialized. The numeric ComParam ID must
come from the selected module's MDF. The caller is responsible for selecting
a parameter appropriate to the CLL's protocol and checking MDF-defined
minimum/maximum constraints; this first setter validates the unsigned
32-bit representation but does not yet parse every MDF ComParam constraint.
Unsupported types (UNUM8/16, signed, bytefield, structfield, longfield) are
rejected rather than guessed.

Per ISO 22900-2, PDUSetComParam changes the working buffer. Those changes
become active on a later PDUConnect or an explicit UPDATEPARAM ComPrimitive.
This stage deliberately does not call PDUConnect or start a ComPrimitive, so
setting parameters does not initiate vehicle communication.


## Explicit physical connection lifecycle

The runtime now exposes `connect_logical_link(module_handle, cll_handle)`
and `disconnect_logical_link(module_handle, cll_handle)`, bound to
`PDUConnect` and `PDUDisconnect`.

This is the first operation in the D-PDU runtime that can physically activate
the vehicle-interface connection. It is deliberately separate from API open,
module enumeration, module initialization, logical-link creation, and
ComParam setup. None of those operations calls `PDUConnect`. The application
must explicitly invoke `connect_logical_link()` on a tracked OFFLINE CLL.

A successful `PDUConnect` transitions the CLL from OFFLINE to ONLINE.
`PDUDisconnect` returns it to OFFLINE. Destroying an ONLINE CLL is rejected;
it must first be disconnected. Runtime cleanup attempts to disconnect ONLINE
links, destroys links that are confirmed OFFLINE, disconnects modules only
after their links are gone, and finally calls `PDUDestruct`. If a disconnect
fails, the still-online link is left for the API's `PDUDestruct` cleanup
rather than incorrectly issuing `PDUDestroyComLogicalLink`.

Important: `PDUConnect` is not a passive CAN listen operation. It physically
connects the CLL to the vehicle interface and is required before ECU
communication. The selected protocol and physical ComParams must be valid
before invoking it. ISO 22900-2 warns that improper physical ComParams can
cause significant bus errors. No `PDUStartComPrimitive`, diagnostic request,
receive operation, or transmit operation has been added in this stage.


## D-PDU receive-only ComPrimitive and event queue

The new `hardware.dpdu_receive.DPduReceiveRuntime` extends the D-PDU runtime
with explicit receive-only protocol primitives and event retrieval.

`start_receive_only(module, cll, response_mask, response_pattern, ...)`
starts `PDU_COPT_SENDRECV` with:
- no PDU data buffer and a data length of zero;
- `NumSendCycles = 0`;
- `NumReceiveCycles = -1` (continuous receive);
- one caller-supplied expected-response mask/pattern;
- optional unique response identifiers and an application acceptance ID.

This is protocol-level response reception, not unrestricted raw CAN capture.
The expected-response structure is required because D-PDU ComPrimitives operate
on protocol data and matching rules. It does not provide a generic passive
monitor of every CAN arbitration ID on a bus. Raw CAN capture remains a
separate adapter capability (currently provided by the J2534 classic-CAN
receive path where the driver supports it).

The runtime binds `PDUStartComPrimitive`, `PDUCancelComPrimitive`, and
`PDUGetEventItem`. Event items are copied into immutable Python records
before their API-owned memory is released with `PDUDestroyItem`. Result
events include copied payload bytes, the ComPrimitive handle, acceptance and
unique-response identifiers, and timestamps. Error and information event
codes are retained as raw numeric values; no undocumented decoding is
invented. Empty event queues return `None`.

Only receive ComPrimitives started through this wrapper are tracked. Shutdown
cancels those primitives before disconnecting or destroying their logical
links. If cancellation fails, shutdown stops and reports the failure rather
than tearing down a link underneath a still-running receive operation.

All D-PDU event tests use mocked libraries. They validate the ABI-shaped
structures, zero-send/infinite-receive control values, result payload copying,
API-owned event destruction, empty-queue handling, and cancellation-before-
disconnect cleanup. This does not establish compatibility with a physical VCI.

The D-PDU ctypes declarations use the one-byte structure packing required by
ISO 22900-2:2022 clause 10.1.4.1. This matters on 64-bit Windows: pointer fields
in structures such as `PDU_EXP_RESP_DATA`, `PDU_COP_CTRL_DATA`, and
`PDU_RESULT_DATA` are not naturally aligned by the standard ABI. Tests assert
the field offsets and structure sizes rather than relying on Python mocks that
would otherwise hide an ABI mismatch.

Result timestamps are exposed only when the corresponding ISO timestamp-valid
bits are set in `TimestampFlags`. Status and information event codes are kept
in their own fields rather than being mislabeled as errors.



## Normalized diagnostic event capture model

Protocol-level D-PDU events now have a separate `DiagnosticEvent` model.
The conversion helper preserves the D-PDU item type, API timestamp and clock
domain, module/CLL/ComPrimitive handles, response identifiers, status/error/
information codes, timestamp-validity results, and payload bytes.

Diagnostic events are deliberately not converted into `CanFrame` objects.
A D-PDU result payload may be a decoded diagnostic PDU rather than a raw CAN
frame; non-raw protocol modes may omit CAN identifiers and transport headers.
The shared `CaptureSession` stores these events in a separate bounded buffer,
tracks absolute sequence indices and dropped-event counts, and exports them
as JSONL with exact payload bytes represented as hexadecimal.

Capture archives now keep `frames`, `sensor_samples`, and
`diagnostic_events` as separate collections. This is the storage boundary
for a future D-PDU event worker. The current J2534 receiver still supplies raw
CAN frames, and the D-PDU runtime does not yet start a UI-managed worker or
automatically feed the shared capture session. That connection remains a
separate step requiring an explicit D-PDU device/protocol configuration and
hardware validation.
