# DBC research sources and evidence notes

This register tracks candidate sources for FreeRov3r's L319 signal research. A source listing is not proof that its definitions match a particular vehicle, model year, engine, market, or CAN bus.

## Format and tooling references

- [Open Vehicles DBC primer](https://docs.openvehicles.com/en/latest/components/vehicle_dbc/docs/dbc-primer.html) — useful explanation of DBC message and signal structure. Treat it as a format reference, not an LR3/LR4 signal database.
- [cantools](https://github.com/cantools/cantools) — parser/decoder used by the optional FreeRov3r DBC feature.

## Candidate data repositories

### CAN-DBC-Collection

- Repository: https://github.com/billyjack2/CAN-DBC-Collection
- Its README describes a broad collection of 155 makes, 599 models, and 789 DBC files.
- A recursive repository-tree check on 2026-11-24 found 2,441 entries and no paths matching Land Rover, Jaguar, Discovery, or Freelander.
- The README notes that some definitions require `strict=False` because of intentionally overlapping signals. FreeRov3r therefore tries strict parsing first and can fall back to permissive parsing, while retaining the validation mode in local metadata.
- Current assessment: useful as a broad comparison source and a source of examples, but no direct L319 DBC was found in the checked tree.

### Awesome Automotive CAN IDs

- Repository: https://github.com/iDoka/awesome-automotive-can-id
- Its Land Rover section links to CAN-code notes for Freelander 2 (2007 and 2013), Discovery 3 4.4 (2006), and a Land Rover/Jaguar gear-knob project.
- It does not list a Discovery 4 / LR4 L319 5.0 DBC.
- Current assessment: the Discovery 3 material may offer platform-adjacent clues, but the engine, year, generation, bus, and market differ. Do not import those findings as confirmed LR4 definitions.

## Vehicle-specific cross-check references

- [Nanocom CAN-BUS coverage manual](https://www.nanocom-diagnostics.com/downloads/preview/nanocom-evolution-can-bus-functions-coverage-manual) lists L319 Discovery 3 (2005–2009) and Discovery 4 (2010–2014) coverage. This is useful evidence that the L319 platform has vehicle-specific CAN diagnostic coverage, but it is not a public DBC file and does not provide signal bit layouts.
- Wiring diagrams and connector/pin references can help identify which physical network a capture came from. They do not, by themselves, prove a DBC signal's scaling, endianness, or update behavior.

## Evidence grading used by FreeRov3r

| Grade | Meaning | Allowed use |
|---|---|---|
| A | Captured on the target vehicle and independently checked against a known physical value or controlled state change | Candidate for verified vehicle profile after review |
| B | Exact model/year/engine/bus source with traceable documentation and consistent capture behavior | Candidate definition; still marked provisional |
| C | Related Land Rover/Jaguar platform, different year/engine/market, or undocumented source | Comparison and reverse-engineering hints only |
| D | Generic DBC, format example, or unknown provenance | Parser tests and syntax examples only |

## Validation checklist

Before a signal is promoted into a verified L319 profile, record:

1. Source URL/file and SHA-256.
2. Vehicle generation, model year, engine, market, and relevant ECU/module.
3. Physical bus/network and nominal bitrate.
4. CAN arbitration ID and standard/extended format.
5. Payload length, start bit, bit length, byte order, signedness, scale, offset, and unit.
6. At least one known-state or known-value cross-check.
7. Capture conditions and any competing definitions for the same CAN ID.

A CAN ID match by itself is weak evidence. The same arbitration ID can be reused on different networks or vehicle generations.
