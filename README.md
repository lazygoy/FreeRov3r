# FreeRov3r

Open-source, locally operated vehicle diagnostics and CAN research platform. Initial target: Land Rover Discovery 4 / LR4 (L319), model years 2010–2016.

**Status:** early development scaffold; not yet validated on a vehicle. No GAP IIDTool, JLR SDD, or Pathfinder proprietary software/data is included.

## First milestone
- Windows desktop shell (PySide6)
- Hardware-independent CAN adapter (python-can)
- Passive capture, session recording, CSV and candump export for SavvyCAN workflows
- Virtual CAN mode for development without hardware
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

For the ESP32 prototype, connect its USB serial port and select the matching COM port in `src/freerov3r/app.py` (currently COM3 default). For development, select Virtual CAN. It produces synthetic frames, not real vehicle traffic.

## Hardware
ESP32-WROOM-32 has a Classical CAN (TWAI) controller but requires an external CAN transceiver. Never connect GPIO directly to CAN-H/CAN-L. First prototype should be receive-only, protected against automotive transients, and should not add termination unless the bus topology requires it. ESP32 TWAI is not CAN FD.

## Reference projects
- python-can: https://github.com/hardbyte/python-can
- python-can-isotp: https://github.com/pylessard/python-can-isotp
- udsoncan: https://github.com/pylessard/python-udsoncan
- SavvyCAN: https://github.com/Green-Sky/SavvyCAN
- can-utils: https://github.com/linux-can/can-utils

## Safety
Transmit, writes, adaptations, and programming are disabled by default. Future write operations require explicit approval and operation-specific preconditions. ECU addresses, bitrates, gateway routing, and pinouts must come from verified L319 documentation and measured captures, not guesses.

## Sensor capture and LLM analysis

The sensor subsystem records ECU-reported and externally measured values as distinct sources. It supports CSV, JSONL, and a provider-neutral Markdown analysis packet suitable for ChatGPT or local/other LLMs. See [sensor capture documentation](docs/SENSOR_CAPTURE_AND_LLM.md). This initial subsystem is a data model/export framework; live ECU PID decoding and external DAQ drivers are future work.
