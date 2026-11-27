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


## Firmware preservation and recovery prerequisite

Firmware preservation is a first-class project requirement, not an optional convenience. FreeRov3r must prioritize protecting the original state of every module before firmware editing or programming is enabled.

### Dual-location recovery archive

Before a user can begin an ECU firmware modification workflow, the application should require two independently stored copies of the recovery archive:

1. A user-designated removable USB drive.
2. A designated internal-drive location on the computer.

The application should treat both as required recovery destinations, not as alternatives. It should display each destination's device/location, capacity or available space, and verification status. If either destination is unavailable, lacks space, is not writable, or fails verification, the application must not mark the backup as protected and must block programming.

For each destination, the application should:
- Let the user explicitly select the target and show its identity, capacity, available space, and filesystem where applicable.
- Never silently format, repartition, erase, or repurpose a drive. Any destructive storage operation requires a separate, explicit confirmation and a clear explanation.
- Check that the destination is writable and has adequate free space for the expected firmware, metadata, logs, and recovery assets.
- Perform a write/read verification test in a dedicated test folder where practical, then remove only that test file.
- Write the archive, close the files, reopen and read them from that destination, and recompute their SHA-256 hashes.
- Compare the verified hashes and file sizes across the internal and removable copies. Both copies must match the manifest and one another.
- Recheck both copies before any programming operation, and report missing, unreadable, altered, or mismatched files clearly.
- Keep originals immutable. Never overwrite an archived original with a modified file.

The application should create a predictable archive structure organized by VIN, module identity, hardware/software revision, and acquisition date. Store original firmware reads, calibration files, module configuration/coding, identification records, DTC/baseline reports, operation logs, tool versions, protocol notes, and recovery instructions. Record hashes, file sizes, acquisition method, source module identity, timestamps, and verification results in an exportable manifest.

A file is not considered backed up merely because a copy operation completed. It is protected only after both destinations have been independently reopened and read successfully, their hashes have been recomputed, and the results match. The application should provide a clear backup report showing the status of each file on each destination.

The removable and internal copies reduce the risk of a single storage-device failure, but they are not a substitute for a genuinely independent second backup where the consequences justify it. The application should warn users that both copies can still be lost through theft, fire, malware, accidental deletion, or correlated hardware failure. Require an additional independent copy of critical originals and recovery assets before high-risk programming where practical.

The USB archive is a designated recovery repository, not proof that recovery is possible. Some modules cannot be fully read through the normal diagnostic interface, and some recovery methods require boot-mode access, bench tools, security credentials, or manufacturer-specific procedures. FreeRov3r must state exactly what was and was not acquired.

### Mandatory operation gates

**Before editing a firmware/calibration working copy offline:**
1. Identify the exact target module and software/hardware revision.
2. Preserve an untouched original source file or module read, when obtainable.
3. Store the original in both designated destinations and verify that each copy can be reopened and read, with matching SHA-256 hashes.
4. Create a separate working copy. Never edit the only original.
5. Record the source-to-working-copy relationship and all subsequent changes.

Offline analysis and editing of a separate working copy may proceed once the original is safely preserved in both locations. This is distinct from authorizing a write to the vehicle.

**Before writing modified firmware to a vehicle module:**
1. Confirm that both the internal and removable original backups are present, readable, and hash-verified against the manifest and each other.
2. Confirm that the additional independent copy required for this risk level exists.
3. Confirm the exact module/file compatibility and required checksum/signature handling.
4. Confirm a module-specific recovery method, compatible recovery hardware, required credentials/tools, and recovery instructions.
5. Confirm that the recovery method is documented and has been validated for the target hardware/software revision. If recovery is unknown or unverified, block the write and explain why.
6. Confirm stable power, communications, and environmental preconditions.
7. Re-read and verify both original backup copies immediately before programming.
8. Require a final explicit user confirmation showing the target module, source and modified file hashes, backup status for both destinations, expected changes, risks, and recovery method.

A user may still perform read-only diagnostics, capture traffic, inspect files, and conduct offline research without recovery media. The hard gate applies to firmware modification workflows and especially to writing/programming a module. No bypass should silently waive missing, unreadable, mismatched, or unverified backups or an unknown recovery path.

## Current implementation boundary

The initial Tuning workspace is a read-only research log and workflow tracker. It does not currently transmit CAN messages, spoof signals, request ECU security access, write configurations, unlock ECUs, or flash modules. Those capabilities are future stages and must be implemented separately with module-specific validation and explicit user control.


### Independent diagnostic request permissions

Standard SAE J1979 OBD-II requests and UDS diagnostic requests have separate
capability, implementation, and authorization gates. Enabling active OBD-II
requests does not authorize UDS. UDS requires an adapter to declare both
\`uds_active_requests\` and \`uds_diagnostic_requests_implemented\`, plus the
separate \`uds_requests_enabled\` policy flag. General CAN transmission remains
a third, separately controlled capability and still requires bench mode.
Current ESP32 firmware remains receive-only, and current ELM327 support remains
standard OBD-II only.


### Read-only UDS application codec

\`freerov3r.diagnostics.uds\` provides a vehicle-independent payload codec for
UDS ReadDataByIdentifier (0x22) and a bounded subset of ReadDTCInformation
(0x19 subfunctions 0x01, 0x02, and 0x0A). It validates positive-response
service echoes, requested DIDs, DTC subfunctions, negative response codes,
and DTC/status record lengths. Multi-DID response record boundaries remain
unknown unless a DID length catalogue is available.

This layer only builds/decodes application payload bytes. It does not choose
CAN IDs, perform ISO-TP transmission, open an adapter, authorize requests, or
identify an ECU. Session-control, security-access, routine-control, reset,
write-data, and programming services are intentionally excluded. Physical
requests still require an adapter that implements UDS, the independent UDS
permission gate, and the safety policy.
