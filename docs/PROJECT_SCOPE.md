# FreeRov3r Project Scope and Architecture

## Product objective

FreeRov3r is a Land Rover-focused professional vehicle diagnostics and service platform. The initial implementation target is the Land Rover Discovery 4 / LR4 (L319), with the 5.0L naturally aspirated petrol V8 as the default development vehicle.

The long-term objective is broad, deeply integrated, dealer-level diagnostic and service capability for supported Land Rover vehicles. "Dealer-level" is the product target, not a claim that current functionality has achieved OEM tool parity. Each capability must be implemented, evidenced, and validated for its stated vehicle applicability.

## Land Rover-first, multi-platform-capable

The finished product should present as a Land Rover diagnostic application. The underlying architecture must preserve the ability to carry reusable engineering, protocol, hardware, and diagnostic capabilities into other manufacturers' platforms in the future.

Keep manufacturer-independent mechanisms separate from manufacturer-specific knowledge:

- **Shared core:** adapters, transport, CAN capture, frame models, ISO-TP, UDS, OBD-II, diagnostic orchestration, data storage, safety policy, evidence handling, reporting, and reusable UI components.
- **Land Rover platform package:** vehicle and model-year applicability, network topology, module definitions, addressing and routing, signal definitions, diagnostic services, security requirements, configuration definitions, service functions, wiring references, and validated procedures.
- **Future platform packages:** separate manufacturer-specific knowledge and implementations that reuse the shared core where technically appropriate. Never assume that another manufacturer's modules, addressing, security, or service behavior match Land Rover.

The first fully developed and tested platform remains the L319. Other vehicle support must not be represented as complete merely because a generic protocol or adapter is available.

## Permanent research and discovery capability

Research and discovery are permanent FreeRov3r subsystems, not temporary development scaffolding. Retain useful research code, analysis algorithms, capture tools, evidence records, tests, and exports after discoveries are incorporated into production diagnostics.

The same application supports two complementary environments:

1. **Vehicle Diagnostics:** the primary user-facing product. It presents practical vehicle-level results and supported operations: vehicle identification, module inventory, DTCs, live data, graphs, service functions, configuration, programming where supported, wiring/service references, history, and reports.
2. **Research and Discovery:** an engineering workspace used to investigate network behavior, capture traffic, compare channels and captures, analyze timing, identify candidate modules/signals/services, document evidence, and improve vehicle support. It may expose technical controls needed by development; it does not need to teach every internal algorithm to the end user.

Research findings should feed the shared knowledge base and become available to Diagnostics when they meet the relevant validation requirements. Production use must not delete or disable the research implementation that produced the finding.

## Research-to-production evidence model

Preserve provenance and distinguish levels of certainty. In particular:

- **Observed:** directly present in a capture, response, or measurement.
- **Candidate / probable:** a plausible interpretation supported by analysis but not independently established.
- **Documented:** supported by a traceable technical reference with stated vehicle applicability.
- **Verified:** independently checked against the applicable vehicle or a sufficiently authoritative test/reference process, with evidence and notes retained.
- **Supported:** implemented and tested in FreeRov3r for the stated vehicle, model year, engine, module, adapter, and operating conditions.

These are not interchangeable. An observed CAN identifier is not an ECU identity. A probable UDS responder is not proof of a physical module. A correlated payload is not automatically a decoded sensor. A discovered diagnostic service is not necessarily safe or available to execute. A discovered coding routine is not automatically a supported coding feature.

Keep source captures, vehicle context, tool/software versions where available, assumptions, test conditions, review history, and validation results with discoveries. Do not automatically promote analysis results to verified or supported status.

## Capability and safety boundaries

Keep these capabilities distinct:

- Passive network receive and capture.
- Passive decoding of diagnostic traffic already present on the network.
- Controlled diagnostic requests (OBD-II / UDS).
- General-purpose CAN transmission for explicitly authorized research or bench work.
- Vehicle writes, adaptations, coding, flashing, and programming.

Hardware capability, implemented firmware/software support, and user authorization are separate gates. Receive-only firmware must remain receive-only until a separately reviewed implementation and explicit authorization are in place. Enabling diagnostic requests must not enable unrestricted CAN transmission.

Any vehicle-changing operation must have operation-specific prerequisites, explicit user authorization, original-value/configuration backup where applicable, risk disclosure, execution logging, and post-operation verification. Unsupported operations must be unavailable or clearly identified as unsupported, not simulated as successful.

## Adapter and transport direction

The adapter architecture should accommodate USB serial and Wi-Fi TCP for ESP32 capture devices, with BLE reserved primarily for discovery, setup, and status where appropriate. Transport framing should remain independent of the underlying link. Preserve device timestamps and host timestamps as distinct clock domains, record reconnect/disconnect events, and quantify dropped frames and timing uncertainty.

Do not claim two independent device clocks are synchronized solely because both report timestamps. Calibration quality, path asymmetry, host scheduling, and uncertainty must be represented in the evidence.

ELM-style active OBD adapters, ELM raw-monitor modes, ESP32 raw CAN capture, and future bidirectional CAN adapters have different capabilities. Do not present them as interchangeable.

## User experience principle

The user-facing diagnostic experience should make complex research useful without requiring the user to understand CAN identifiers, ISO-TP details, correlation thresholds, or signal-discovery algorithms. Present verified module identities, useful diagnostic results, live data, supported functions, prerequisites, and clear outcomes.

The research environment may remain technical and developer-oriented. Do not spend product effort disguising the discovery machinery as a novice tutorial when the important usability requirement is that its results become clear, reliable diagnostic features.

## Development priorities

1. Establish reliable shared capture, adapter, vehicle identity, and evidence infrastructure.
2. Discover and validate the L319 network, modules, diagnostic access, signals, and service capabilities using documentation and measured vehicle evidence.
3. Build production-quality Land Rover diagnostic workflows on top of validated knowledge.
4. Retain and improve all reusable discovery tools and research records.
5. Separate L319-specific knowledge from reusable core mechanisms as the platform matures.
6. Introduce additional Land Rover models/engines and, later, other manufacturers through distinct platform packages and validation work.

## Current implementation caveat

This document defines the intended scope and architecture. It does not assert that dealer-level coverage, live module scanning, coding, programming, wireless adapter operation, or physical vehicle validation is already complete. Current capabilities and limitations must continue to be described accurately in the application and release notes.
