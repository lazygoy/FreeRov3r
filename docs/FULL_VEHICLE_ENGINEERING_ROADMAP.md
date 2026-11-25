# FreeRov3r: Full Vehicle Engineering and Calibration Roadmap

## Mission

FreeRov3r is intended to grow into a general-purpose vehicle engineering platform: diagnostics, network research, service functions, configuration, adaptation, calibration analysis, and eventually supported module unlocking and programming.

The project will begin with the Land Rover L319 / Discovery 4 platform, prioritizing the naturally aspirated 5.0L petrol V8 vehicle available for development and validation. The architecture must remain modular so other vehicles, ECUs, interfaces, and protocols can be added without pretending they are already supported.

The goal is not merely to read fault codes. The goal is to understand and work with the vehicle's electronic systems as completely as the available hardware, documentation, and validated engineering methods permit.

## Capability scope

### 1. Diagnostics and service operations
- OBD-II live data, readiness, DTCs, freeze-frame data, and supported Mode 06/Mode 08 functions.
- Manufacturer-specific diagnostics, module scans, DIDs, routines, adaptations, resets, and service procedures.
- Module inventory, VIN association, software/hardware identity, network topology, and vehicle history.
- Before/after reports and durable records of every operation.

### 2. Network and signal engineering
- Passive HS-CAN, MS-CAN, and other supported vehicle-network capture.
- CAN/CAN-FD interface support when suitable hardware is available; current ESP32/SN65HVD230 hardware is Classical CAN only.
- DBC import, validation, decoding, signal graphing, timing analysis, and evidence-based signal discovery.
- ISO-TP and UDS analysis, request/response correlation, DID research, and protocol documentation.
- Controlled active diagnostics and message experiments as a separate capability from passive capture.
- Message generation, replay, and signal substitution research only in explicitly selected test contexts, with clear separation from ordinary road use.

### 3. Vehicle configuration and module control
- Read and compare module configuration, variant coding, adaptations, learned values, and supported service routines.
- Preserve original values and configuration snapshots before changes.
- Provide explicit, reviewable change sets and read-back verification.
- Support module-specific workflows rather than assuming every module implements the same UDS services or security model.

### 4. Engine calibration and performance development
- Identify the exact ECU hardware, software, calibration, strategy, and associated engine/vehicle configuration.
- Acquire and verify original calibration backups using a documented, ECU-compatible method.
- Build offline calibration-file inventory, hashing, binary comparison, metadata extraction, and version tracking.
- Research map structures, axes, units, scaling, limiters, torque models, fueling, ignition, airflow, throttle, knock control, temperature protection, and related strategies only where evidence supports the interpretation.
- Visualize maps and compare original versus modified calibration data.
- Track every proposed change with rationale, expected effect, dependencies, confidence, and rollback information.
- Validate changes through logs, controlled testing, and suitable instrumentation such as wideband lambda, knock monitoring, fuel-pressure measurement, and dyno testing where applicable.
- Treat CAN signal spoofing as a distinct experimental technique. It may help investigate control strategies or test module responses, but it is not a substitute for editing the ECU's actual calibration and must not be presented as a reliable performance tune by itself.

### 5. ECU security access, unlocking, and programming
- Research documented diagnostic security access, seed/key methods, boot modes, bootloaders, programming sessions, and supported bench/vehicle interfaces.
- Identify which operations are supported for the exact ECU hardware and software revision before enabling them.
- Support read, backup, checksum/signature validation, write, verify, and recovery workflows when technically established.
- Keep bench programming and in-vehicle programming as distinct operating modes.
- Provide power-supply monitoring and explicit preflight checks for programming operations.
- Preserve the original read and verify its integrity before any write is permitted.
- Require a documented recovery path, compatible recovery hardware, and a verified file/ECU match before programming.
- Never invent memory addresses, map definitions, security algorithms, checksum rules, or compatibility claims.

### 6. Broader vehicle electronics
- Extend the same evidence-driven approach to transmission, ABS/DSC, air suspension, body, gateway, restraint, instrument, HVAC, and other modules.
- Add support through vehicle profiles and plugins so one platform's assumptions do not leak into another.
- Support additional physical interfaces and protocols as the project grows, including CAN-FD and other networks where hardware and protocol research justify them.

## Development stages

| Stage | Deliverable | Exit criteria |
|---|---|---|
| A. Observe | Passive capture, OBD-II, module inventory, DTC and live-data history | Reliable capture, timestamps, VIN association, reproducible exports |
| B. Understand | DBC/UDS/DID research, signal analysis, network maps | Evidence and confidence recorded; unknowns remain explicitly unknown |
| C. Read and preserve | Read-only configuration, identity, adaptation and calibration acquisition | Exact module identity; repeatable reads; integrity-checked backups |
| D. Analyze | Offline binary/map analysis and calibration comparison | Map definitions supported by evidence; units and dependencies documented |
| E. Controlled diagnostics | Selected routines, configuration changes, and isolated message experiments | Explicit operation approval, preconditions, read-back, logs, rollback |
| F. Bench development | ECU bench communication, recovery, and programming research | Verified interface, stable power, repeatable recovery procedure |
| G. Validated programming | Supported ECU unlock/read/write/verify workflows | Exact compatibility established; original backup and recovery proven |
| H. Expand | Additional ECUs, vehicle platforms, and network types | Plugin/profile isolation and platform-specific validation |

Stages are capability gates, not promises that every ECU will be supported. Some manufacturers and hardware revisions may remain inaccessible without specialized equipment or proprietary information.

## Evidence and confidence model

Every discovered identifier, signal, DID, routine, map, checksum, and programming method must carry a source and confidence state:

- **Observed:** directly captured or measured, but meaning or applicability is not established.
- **Probable:** supported by repeatable patterns or multiple indirect clues.
- **Documented:** supported by a traceable technical source applicable to the identified platform.
- **Verified:** independently reproduced on the exact hardware/software combination, with results recorded.

A label, internet listing, similar model year, or matching connector is not enough to mark a protocol or calibration as verified.

## Operational principles

1. Vehicle ownership is the starting point for the project's user-controlled engineering goal. The software should expose capabilities honestly rather than impose arbitrary vendor-tool limitations.
2. Technical capability must be demonstrated for the exact module and revision. Ownership does not make an unknown protocol safe or a mismatched binary compatible.
3. Passive observation and active transmission must remain visibly distinct.
4. No active operation should run silently. Show the target module, operation, expected effect, prerequisites, and risk before execution.
5. Preserve original data before changing it. Record who/what initiated the operation, timestamps, inputs, results, and read-back verification.
6. Never make unsupported claims of successful writes, unlocks, recovery, or validation.
7. Avoid road testing experimental spoofing or calibration changes in situations where loss of propulsion, braking, steering assistance, or other control functions could endanger people. Use an appropriate bench, closed test area, or dyno.
8. Keep emissions-related and safety-critical functions visible in analysis. Do not silently disable diagnostics, protections, or safety systems.
9. Prefer reversible, narrowly scoped changes. Provide rollback instructions and recovery tooling before enabling high-risk operations.
10. Support plugins and vehicle profiles, but require each plugin to declare its capabilities, supported hardware, protocol assumptions, and validation status.

## Initial L319 5.0L work

The first vehicle profile is the L319 / Discovery 4 5.0L naturally aspirated petrol V8. The engine and ECU labels currently shown in the application are project defaults, not verified vehicle identity.

The immediate research priorities are:
1. Capture the VIN and exact ECM identification data from the vehicle.
2. Record ECM part number, hardware number, software/strategy identifiers, calibration identifier, and diagnostic protocol evidence.
3. Determine the exact ECM family and supported read/programming methods from matching evidence.
4. Build a baseline of DTCs, supported live data, adaptations, and network behavior.
5. Establish a repeatable original calibration acquisition and recovery strategy before investigating edits or writes.

Do not infer ECU type, programming support, or calibration compatibility from engine displacement or model year alone.

## Current implementation boundary

The initial Tuning workspace is a read-only research log and workflow tracker. It does not currently transmit CAN messages, spoof signals, request ECU security access, write configurations, unlock ECUs, or flash modules. Those capabilities are future stages and must be implemented separately with module-specific validation and explicit user control.
