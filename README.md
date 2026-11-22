# FreeRov3r

Open-source, locally operated vehicle diagnostics and CAN research platform. Initial target: Land Rover Discovery 4 / LR4 (L319), model years 2010–2016.

**Status:** early development scaffold; not yet validated on a vehicle. No GAP IIDTool, JLR SDD, or Pathfinder proprietary software/data is included.

## First milestone
- Windows desktop shell (PySide6)
- Hardware-independent CAN adapter (python-can)
- Passive capture, session recording, CSV and candump export for SavvyCAN workflows
- Synthetic OBD-II vehicle simulator for dashboard development without hardware
- Generic SAE Mode 01 response decoder feeding the OBD-II table and sensor capture
- Virtual CAN mode for testing python-can transport without a physical CAN interface
- Categorized synthetic module network (Powertrain, Chassis, Body, Safety, Climate, Driver Assistance, Network, Infotainment) with per-module scans, DTC display, per-code/per-module clearing, and clear-all simulation controls
- Automatic VIN extraction from observed OBD-II Mode 09 PID 02 and UDS DID F190 ISO-TP responses, with VIN validation and VIN-keyed capture/history assignment
- Thinkcar-style Network overview tree with green scanned/no-fault modules, red modules with DTCs, and gray unscanned/no-response modules
- Local VIN-keyed vehicle history with timestamped module scan snapshots, DTC clearing events, capture start/stop records, and per-VIN raw CAN/sensor capture archives
- L319 vehicle profile placeholder with no guessed ECU addresses
- ESP32-WROOM-32 TWAI listen-only firmware starter and matching USB-serial PC adapter

## Install on Windows 11
```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"
freerov3r
```

For the ESP32 prototype, connect its USB serial port and select the matching COM port in `src/freerov3r/app.py` (currently COM3 default). For dashboard development without hardware, select **Simulated vehicle (synthetic OBD-II)**. It streams changing, generic SAE Mode 01 example values into the CAN log, OBD-II table, sensor recorder, and graph. These values are fabricated test data, not measurements from an L319 and not a validated L319 signal definition. **Virtual CAN** is a separate python-can transport option and does not generate a vehicle profile by itself.

## Hardware
ESP32-WROOM-32 has a Classical CAN (TWAI) controller but requires an external CAN transceiver. Never connect GPIO directly to CAN-H/CAN-L. First prototype should be receive-only, protected against automotive transients, and should not add termination unless the bus topology requires it. ESP32 TWAI is not CAN FD.

## Reference projects
- python-can: https://github.com/hardbyte/python-can
- python-can-isotp: https://github.com/pylessard/python-can-isotp
- udsoncan: https://github.com/pylessard/python-udsoncan
- SavvyCAN: https://github.com/Green-Sky/SavvyCAN
- can-utils: https://github.com/linux-can/can-utils

## Safety
Transmit, writes, adaptations, and programming are disabled by default. Vehicle history and capture archives are stored locally under `~/.freerov3r/`; diagnostic scans require a selected VIN, and capture data is filed under the VIN active when capture began. No VIN or capture data is transmitted to a remote service. The module/DTC interface currently operates only on an in-memory synthetic module network; its module names, example DTCs, and scan responses are fixtures, not verified L319 coverage or live ECU results. Automatic VIN identification passively recognizes valid VINs in observed OBD Mode 09 PID 02 or UDS DID F190 ISO-TP responses; it does not transmit a VIN request. The Network overview colors only modules that have been scanned: green means no DTCs in the current module data, red means DTCs are present, and gray means not scanned or no response. The current network tree is still backed by synthetic module fixtures, not a live L319 scan. Future write operations require explicit approval and operation-specific preconditions. ECU addresses, bitrates, gateway routing, and pinouts must come from verified L319 documentation and measured captures, not guesses.

## Sensor capture and LLM analysis

The sensor subsystem records ECU-reported and externally measured values as distinct sources. It supports CSV, JSONL, and a provider-neutral Markdown analysis packet suitable for ChatGPT or local/other LLMs. See [sensor capture documentation](docs/SENSOR_CAPTURE_AND_LLM.md). The current simulator and generic Mode 01 decoder exercise the live capture path. Real L319-specific signal definitions and external DAQ drivers remain future work.
