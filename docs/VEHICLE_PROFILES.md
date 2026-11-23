# FreeRov3r vehicle capability packages

FreeRov3r separates its generic diagnostic core from manufacturer-specific
vehicle support.

## Generic core

The generic profile is intended to provide reusable features such as:

- CAN capture and raw frame logging
- Standard OBD-II data and supported PID monitoring
- Sensor recording, graphing and exports
- VIN and vehicle history association

Actual capabilities depend on the connected interface. A receive-only CAN
adapter can capture traffic but cannot actively request OBD-II PIDs.

## Built-in package

The first manufacturer package is **Land Rover L319 (LR3 / LR4)**. It is the
only manufacturer-specific package currently selected for full development
and testing. Its factory wiring references and vehicle-specific diagnostic
workspaces must remain separate from generic OBD-II features.

VIN classification is conservative. North American LR3 model years 2005–2009
and LR4 model years 2010–2016 are suggested from the Land Rover WMI, Discovery
model-range character and model-year code. The result is a probable match and
must be reviewed; VIN decoding alone does not prove installed equipment or
market-specific configuration.

## Third-party package registration

A Python package can advertise a FreeRov3r vehicle profile using this entry
point group in its own `pyproject.toml`:

```toml
[project.entry-points."freerov3r.vehicle_profiles"]
my_vehicle = "my_package.freerov3r:VehicleProfileFactory"
```

The entry point must resolve to a zero-argument factory returning a
`freerov3r.vehicle_profiles.registry.VehicleProfile` instance.

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
