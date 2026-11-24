# FreeRov3r

Open-source, locally operated vehicle diagnostics and CAN research platform. Initial target: Land Rover Discovery 4 / LR4 (L319), model years 2010–2016.

**Status:** early development scaffold; not yet validated on a vehicle. No GAP IIDTool, JLR SDD, or Pathfinder proprietary software/data is included.

## Branding

The desktop shell uses original, scalable SVG artwork in `src/freerov3r/assets/`: an application badge, a wide workspace banner, and a startup/home graphic. The visual system uses deep green, brushed-silver accents, topographic contours, and generic off-road imagery. It is inspired by classic 4x4 vehicle badging but does not use Land Rover trademarks or proprietary artwork.

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
- VIN- and module-specific ChatGPT Solutions workspace that builds prompts from module DTCs, recent VIN history and recent sensor samples, with expandable module groups and locally saved AI responses
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
Transmit, writes, adaptations, and programming are disabled by default. Vehicle history and capture archives are stored locally under `~/.freerov3r/`; diagnostic scans require a selected VIN, and capture data is filed under the VIN active when capture began. No VIN or capture data is transmitted to a remote service. The module/DTC interface currently operates only on an in-memory synthetic module network; its module names, example DTCs, and scan responses are fixtures, not verified L319 coverage or live ECU results. Future write operations require explicit approval and operation-specific preconditions. ECU addresses, bitrates, gateway routing, and pinouts must come from verified L319 documentation and measured captures, not guesses.

## Sensor capture and LLM analysis

Transmit, writes, adaptations, and programming are disabled by default. Vehicle history and capture archives are stored locally under `~/.freerov3r/`; diagnostic scans require a selected VIN, and capture data is filed under the VIN active when capture began. No VIN or capture data is transmitted to a remote service. The module/DTC interface currently operates only on an in-memory synthetic module network; its module names, example DTCs, and scan responses are fixtures, not verified L319 coverage or live ECU results. Automatic VIN identification passively recognizes valid VINs in observed OBD Mode 09 PID 02 or UDS DID F190 ISO-TP responses; it does not transmit a VIN request. The Network overview colors only modules that have been scanned: green means no DTCs in the current module data, red means DTCs are present, and gray means not scanned or no response. The current network tree is still backed by synthetic module fixtures, not a live L319 scan. Future write operations require explicit approval and operation-specific preconditions. ECU addresses, bitrates, gateway routing, and pinouts must come from verified L319 documentation and measured captures, not guesses.

## Sensor capture and LLM analysis

The **Solutions** tab provides an expandable module list. Selecting a module builds a focused troubleshooting prompt containing its current DTCs, the selected VIN's recent history, and recent sensor samples. Copy the prompt into ChatGPT (or another LLM), then paste the response back into the module's solution editor and save it. Saved responses are stored locally in `~/.freerov3r/solutions.json`, keyed by VIN and module. This workflow does not require an API key and does not send vehicle data automatically. The prompt explicitly labels the current module inventory and DTCs as synthetic simulator fixtures. Direct in-app ChatGPT/API integration can be added later without changing the local storage format.



The sensor subsystem records ECU-reported and externally measured values as distinct sources. It supports CSV, JSONL, and a provider-neutral Markdown analysis packet suitable for ChatGPT or local/other LLMs. See [sensor capture documentation](docs/SENSOR_CAPTURE_AND_LLM.md). The current simulator and generic Mode 01 decoder exercise the live capture path. Real L319-specific signal definitions and external DAQ drivers remain future work.


### Simulator state persistence

Synthetic module/DTC state is stored separately for each selected VIN under
`~/.freerov3r/vehicles/<VIN>/simulated_modules.json`. Scan timestamps and
simulated DTC clear operations are saved locally and restored on the next
application launch. These records remain demonstration data and are not
evidence of a physical ECU response. The file is written atomically; an
unreadable or unsupported state file leaves the seeded simulator defaults
intact.

### Automated checks

GitHub Actions runs Python compilation and the test suite on Python 3.10 and
3.12 for pushes to `main` and feature branches, and for pull requests targeting
`main`.


### VIN backup export

The Vehicle History workspace can export a selected VIN as a ZIP backup. The
bundle contains that vehicle's event history, available capture JSON archives,
and saved simulated module state. It excludes other VINs and includes a
manifest identifying the export schema and synthetic-data limitation. Choose
a specific VIN; the combined "All vehicles" view cannot be exported as a
vehicle backup.


### Offline capture replay and session comparison

The Vehicle History workspace lists capture archives for the selected VIN. Load
a capture to inspect its recorded CAN frames, then use Play/Pause, Stop and the
speed selector to step through the archived traffic in timestamp order. This is
a local display replay: it does not connect to an adapter, transmit CAN frames,
or alter the original archive.

Choose two different archives to compare frame counts by arbitration ID,
payload-byte frequencies, and matching sensor IDs/units. Sensor comparison
reports sample counts, minimum, maximum, mean, first and last values, plus the
difference between session means where both sessions contain the same signal
and unit. Comparison tables can be exported to CSV. Different capture clocks
are not assumed to be synchronized, so the comparison does not claim
point-by-point temporal alignment.
