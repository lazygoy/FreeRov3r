# Private Protocol Research Workspace

This workspace is experimental and lives on the \`ui-experiments\` branch. It is not part of the Alpha 1 baseline and must not be merged into a stable or release branch by default.

## Purpose

Provide a local workbench for studying traffic observed while the LAUNCH Creader Elite V2.0 performs a diagnostic operation on the user's Land Rover LR4 / Discovery 4 (L319).

## Intended workflow

1. Connect a passive FreeRov3r listener alongside the commercial scanner.
2. Start the ordinary FreeRov3r CAN listener.
3. In **Research**, select the operation being performed on the LAUNCH tool.
4. Start research recording immediately before the operation.
5. Perform one operation at a time on the LAUNCH scanner.
6. Stop recording, annotate important frames, and save the capture.
7. Compare captures and export a REA analysis packet.

## Current capabilities

- Live frame preview from the main FreeRov3r listener.
- Explicit research recording separate from live preview.
- Session metadata: operation, notes, VIN and selected interface.
- Import of FreeRov3r JSON, JSONL, CSV and common candump text files.
- CAN ID, payload and protocol-hint filters.
- Basic ISO-TP PCI and UDS service hints.
- Frame bookmarks and annotations.
- Capture comparison by CAN identifier traffic counts.
- JSON session save and Markdown handoff packet for REA / ChatGPT.

## Safety and interpretation limits

- The Research tab itself never transmits CAN frames, sends diagnostic requests, or replays captured traffic.
- The selected adapter still determines whether the overall application is passive. The \`elm327_obd\` backend actively polls standard OBD-II Mode 01 PIDs; use the receive-only ESP32 interface or another known passive adapter when observing LAUNCH scanner traffic.
- A CAN ID alone does not establish ECU identity or request/response direction.
- UDS labels are heuristics based on ISO-TP single-frame payloads. Multi-frame UDS messages are not yet reassembled or interpreted.
- No coding, programming, security access, actuator control, or ECU write support is implemented by this workspace.

## Not yet implemented

- Multi-frame ISO-TP reassembly and transaction grouping.
- Automatic request/response pairing and ECU address mapping.
- Multi-network capture and bus selection.
- Timing-aligned operation markers and capture comparison by sequence.
- LAUNCH-specific protocol decoding.

Keep raw captures unchanged. Derived interpretations should remain separate and be marked as confirmed, probable, or unknown.
