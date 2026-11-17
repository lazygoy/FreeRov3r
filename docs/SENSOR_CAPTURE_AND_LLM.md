# Sensor monitoring, capture and LLM analysis

## Two acquisition families

1. **ECU-reported signals:** decoded from vehicle diagnostic responses (for example UDS read-data identifiers or verified JLR-specific services). Each definition must record ECU identity, request/response details, scaling, unit, valid range if documented, and the source document/version.
2. **External measurements:** independent sensors and DAQ hardware such as thermocouples, pressure transducers, voltage/current monitors, accelerometers, and wheel-speed pickups. Each channel needs calibration, range, wiring/interface, sample rate, and isolation/protection notes.

Never merge these into one unlabeled value stream. The `source` field distinguishes `ecu`, `external`, `calculated`, and `simulated`.

## Capture record

Every sample stores timestamp, stable sensor ID, display name, numeric value, unit, source, optional ECU/signal identity, quality flag, and metadata. Later versions should add monotonic time, synchronization status, calibration ID, raw bytes, and capture configuration.

## Export options

- CSV: spreadsheet and analysis workflows.
- JSONL: lossless machine-readable records.
- Markdown analysis packet: provider-neutral prompt plus data and summary statistics. It can be pasted into ChatGPT or another LLM, or uploaded as a file. It makes no API call and contains no API keys.

Future integrations can add optional OpenAI-compatible or local-model endpoints. They must be opt-in, disclose exactly what data is sent, allow local-only mode, and never upload VIN, owner identity, location, or raw logs without explicit user approval.

## LLM analysis rules

The prompt asks the model to:
- separate observed facts from hypotheses;
- retain units and timestamps;
- avoid inventing OEM limits or normal ranges;
- cite exact samples for claims;
- identify missing measurements and propose discriminating tests;
- never issue vehicle commands or initiate writes/programming.

LLM output is advisory. It is not an authoritative diagnosis and must not automatically trigger vehicle actions.

## Planned UI

- Live sensor table with source, value, unit, timestamp, and quality.
- Multi-signal time plots with selectable channels and time window.
- Record / pause / mark-event controls.
- Session metadata (vehicle, model year, engine, ambient conditions, test procedure).
- Export CSV, JSONL, and LLM analysis packet.
- Compare two captures and overlay traces.
