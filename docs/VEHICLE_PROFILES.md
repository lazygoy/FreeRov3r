# FreeRov3r vehicle capability packages

FreeRov3r separates its generic diagnostic core from manufacturer-specific
vehicle support.

## Generic core

The generic profile is intended to provide reusable features such as:

- CAN capture and raw frame logging
- Standard OBD-II data and supported PID monitoring
- Sensor recording, graphing and exports
- VIN and vehicle history association

Actual capabilities depend on the connected interface. The generic OBD-II
decoder handles supported Mode 01 responses on 11-bit CAN (0x7E8–0x7EF).
A dedicated ELM327 serial/Bluetooth OBD-II polling mode can actively request
selected Mode 01 PIDs in round-robin order, with a configurable delay between
requests. The passive ELM327 CAN monitor, ESP32 receive-only firmware, and
other receive-only CAN adapters only decode traffic they observe. The ELM327
VIN query is a separate read-only Mode 09 PID 02 request. Unsupported PIDs may
return no data; available values depend on the vehicle and ECU.

## Built-in package

The first manufacturer family is **Land Rover L319**. A shared L319 workspace
is the default while vehicle identity is unknown; a VIN decode identifying a
different make/model switches to generic OBD-II/CAN support. The LR3 and LR4
variant packages remain available when the VIN or user selection identifies
the specific generation.

The family workspace exposes the common L319 workspaces without claiming that
variant-specific wiring, module fitment or service procedures are interchangeable.
The variant packages are:

- **LR3 / Discovery 3:** North American model years 2005–2009. Generic OBD-II/CAN
  features are available; LR3-specific wiring and module definitions are not
  yet implemented.
- **LR4 / Discovery 4:** North American model years 2010–2016. This is the
  current manufacturer-specific development target. The factory wiring
  reference presently describes a 2010 LHD PV8 5.0L baseline only.

VIN classification uses the Land Rover WMI, Discovery model-range character and
model-year code. The result is a probable match and must be reviewed; VIN
decoding alone does not prove installed equipment, engine, market or
configuration. LR3 users can open the shared workspaces, but the current wiring
reference remains explicitly labeled as a 2010 LR4 baseline and is not evidence
of LR3 fitment. Workspace visibility does not certify module presence or
procedure compatibility.

## Third-party package registration

A Python package can advertise a FreeRov3r vehicle profile using this entry
point group in its own `pyproject.toml`:

```toml
[project.entry-points."freerov3r.vehicle_profiles"]
my_vehicle = "my_package.freerov3r:VehicleProfileFactory"
```

The entry point must resolve to a zero-argument factory returning a
`freerov3r.vehicle_profiles.registry.VehicleProfile` instance. The registry
loads the shared L319 workspace plus the separate LR3 and LR4 variant packages.

The profile currently supplies metadata and declared capabilities. Registering
a profile does not automatically implement its ECU addresses, diagnostic
services, PIDs, network topology or service routines. Those functions must be
provided and tested by the plugin before they are advertised as supported.

## Safety and data quality

- Never infer ECU presence from a generic VIN decode or a wiring diagram.
- Distinguish passive observation from active diagnostic requests.
- Mark simulated data as simulated.
- Keep manufacturer-specific requests read-only until the relevant protocol,
  addressing and vehicle configuration are verified.
- Plugins must not send ECU writes, coding or actuator commands by default.


## Research-to-diagnostics knowledge bridge

The shared vehicle knowledge catalog lives in
\`freerov3r.core.vehicle.knowledge.VehicleKnowledgeStore\`. It is separate from
the specialized Research evidence ledgers and is intended to be consumed by
both Research and the Diagnostic services.

Each knowledge record has an artifact type/key, structured data, explicit
vehicle applicability, provenance, review history, and one evidence status:

- \`observed\` and \`candidate\`: retained for engineering investigation only.
- \`documented\`: source-backed and applicable to a stated vehicle, but not
  independently verified.
- \`verified\`: independently checked with grade-A evidence and verification
  notes. It is available as verified knowledge, not automatically as an
  executable feature.
- \`supported\`: verified knowledge that also names the implementation and test
  references proving that FreeRov3r implements and tests the capability.

The Diagnostic catalog returns verified knowledge and supported capabilities
as separate collections. It does not expose observed/candidate findings as
production facts. A signal research record can be imported only after it has
been reviewed as documented or verified. Importing does not delete or modify
the original Research record and never marks the imported item supported.

Applicability can be limited by profile IDs, model-year range, and engine IDs.
Truly manufacturer-independent knowledge must be explicitly marked
\`platform_independent\`; a generic protocol definition must not accidentally
inherit Land Rover ECU addressing or behavior.

This catalog is a data and service foundation. It does not itself create a
live ECU scanner, decode an unverified signal, register an executable service
routine, or enable vehicle writes.


Passive module-discovery reports can also be imported into the shared catalog
with \`VehicleKnowledgeStore.import_module_discovery_report()\`. These are stored
as \`observed_can_node\` records with capture provenance and explicit
\`identity_confirmed: false\`. A probable UDS response association remains a
probable traffic role, not a named ECU. The import requires a report that
explicitly states no transmission occurred and a traceable capture/session ID.
It never creates a verified module identity or a supported diagnostic feature.


The diagnostic-side module inventory API is
\`VehicleKnowledgeStore.module_inventory(profile_id, model_year, engine_id)\`.
It returns observed CAN nodes separately from candidate/documented module
identity records, verified module identities, and supported module identities.
A CAN node with a probable UDS responder role is never rendered as a named ECU
unless a separate \`module_identity\` record has passed explicit verification.
This keeps passive discovery useful to diagnostics without overstating what a
capture proves.


The Diagnostic **Modules** workspace now presents retained vehicle network
evidence in a separate read-only section above the synthetic module simulator.
Observed CAN nodes and verified module identities are displayed in separate
tables. Opening the Modules workspace refreshes the evidence from the active
vehicle profile. The simulator remains explicitly labelled synthetic and its
scan/clear controls do not operate on physical ECUs.
