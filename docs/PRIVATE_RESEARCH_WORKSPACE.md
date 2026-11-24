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
- ISO-TP Single Frame decoding and passive First Frame / Consecutive Frame reassembly.
- Sequence-number validation, transfer timeouts, incomplete-transfer reporting and extended-length First Frame support.
- UDS service-name hints for reassembled request, positive-response and negative-response payloads.
- Conservative request/response pairing using UDS service semantics, CAN-ID separation, channel, frame format and a configurable time window.
- Response latency measurements and a cautious hint for the common 11-bit request/response CAN-ID +0x8 pattern.
- A Research-tab transaction analysis view and paired-transaction export for REA.
- Candidate CAN responder-address aggregation by request/response ID pair, channel and frame format, including pair counts, observed services, positive/negative response counts and average latency.\n- Cross-capture validation that independently decodes and pairs two captures, then reports which candidate ID relationships recur in both, with per-capture counts and service evidence.
- A Research-tab action to inspect reassembled messages, plus ISO-TP results in the REA analysis packet.
- Frame bookmarks and annotations.
- Capture comparison by CAN identifier traffic counts.\n- Monotonic-time action markers and before/after payload-frequency comparison (2-second baseline, 5-second response window by default). Frames without a matching monotonic elapsed-time field are excluded rather than mixing unrelated clocks.
- Multi-capture operation-sequence alignment against the first loaded capture, reporting missing, inserted or substituted marker steps, alongside per-operation CAN traffic repeatability and timing.
- Per-operation UDS transaction correlation: reassembles each capture independently using monotonic elapsed time, pairs probable requests and responses, and compares raw request/response payloads, response kind, repeatability and latency across captures.
- Observed UDS identifier summary for ReadDataByIdentifier (0x22), WriteDataByIdentifier (0x2E), InputOutputControlByIdentifier (0x2F) and RoutineControl (0x31), aggregating DIDs, routine IDs, routine-control subfunctions, outcomes and cross-capture repeatability without guessing vehicle-specific meanings.
- DID response-data comparison: compares raw positive single-DID ReadDataByIdentifier payloads across marked operations and captures, reporting distinct values, data lengths and differing byte offsets. Multi-DID responses are deliberately skipped until record boundaries can be established from a trusted vehicle-specific definition.
- Source-backed DID response decoding: load a JSON definition registry, select its exact vehicle key, and decode only paired positive single-DID 0x22 transactions. The Research tab displays raw request/response bytes, decoded fields, confidence and source provenance. Multi-DID, negative, unmatched and unknown definitions remain uninterpreted.
- Registry validation CLI: run `python -m freerov3r.did_definitions path/to/registry.json` to validate the JSON structure and print definition counts, vehicle keys, confidence counts and source references. `examples/did_definitions.example.json` is an intentionally empty starter template; it contains no invented vehicle definitions.
- JSON session save and Markdown handoff packet for REA / ChatGPT.

## Safety and interpretation limits

- The Research tab itself never transmits CAN frames, sends diagnostic requests, or replays captured traffic.
- The selected adapter still determines whether the overall application is passive. The \`elm327_obd\` backend actively polls standard OBD-II Mode 01 PIDs; use the receive-only ESP32 interface or another known passive adapter when observing LAUNCH scanner traffic.
- A CAN ID alone does not establish ECU identity or request/response direction. The address map reports candidate responder IDs from observed pairs only; it does not assign module names.
- ISO-TP reassembly currently assumes normal addressing and separates transfers by CAN ID, CAN ID format and capture channel. Extended/mixed addressing modes and automatic request/response pairing are not implemented.
- Flow Control frames are recognized as transport metadata but are never answered or generated. A passive capture may therefore show an incomplete transfer if the observed sender waits for Flow Control that the capture interface does not provide.
- UDS service names and request/response associations are protocol hints only. Pairing requires matching service semantics, different CAN IDs, matching channel/format and close timing; it remains probable, not confirmed. The +0x8 relationship is reported only as a common pattern, not assumed as a rule.
- CAN IDs alone do not prove ECU identity or physical addressing, and a data identifier or routine's meaning remains unknown until independently established.
- No coding, programming, security access, actuator control, or ECU write support is implemented by this workspace.

## Not yet implemented

- Extended/mixed ISO-TP addressing and more advanced transaction grouping.
- Validation against independently verified vehicle-specific evidence, such as trusted wiring documentation or a known module-specific operation. Cross-capture repeatability alone still does not establish ECU identity.
- Multi-network capture and bus selection.
- Additional configurable timing windows and deeper payload-delta analysis.
- LAUNCH-specific protocol decoding.

Keep raw captures unchanged. Derived interpretations should remain separate and be marked as confirmed, probable, or unknown.


## Vehicle-specific DID definition framework

The research code includes an opt-in, in-memory DID definition registry. Definitions are keyed by exact vehicle label and 16-bit DID, and must include source title/reference plus an explicit confidence label (`confirmed`, `probable` or `unverified`). Field layouts support byte offsets, lengths, unsigned/signed integers, raw hexadecimal, ASCII, byte order, scale, bias and units. Decoding requires a matching positive `0x62` response and exact vehicle/DID match; unknown definitions remain raw. Truncated fields are reported rather than padded or guessed.

The registry does not ship with assumed LR4 DID meanings. DBC signal definitions are CAN-frame layouts and must not be reused as UDS DID layouts without independent evidence. A source citation and confidence label are metadata, not proof that a definition is correct.
