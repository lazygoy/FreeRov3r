# Commercial scan-tool workflow reference

Research snapshot: 2026-11-28

This document records public product and manual material reviewed while designing
the experimental FreeRov3r diagnostic workspace. It is a workflow reference, not
a claim that FreeRov3r has equivalent vehicle coverage or functionality.

## Product identity and source notes

### Snap-on ZEUS / ZEUS+

The current Snap-on US product catalog lists ZEUS+ as the current ZEUS platform.
The older ZEUS (EEMS342) remains documented separately. ZEUS+ (EEMS348) product
specifications include an 11.6-inch 1920x1080 touchscreen, 4-channel lab scope,
up to 6 MS/s scope sample rate, 3 MHz scope bandwidth, up to 16 live-data graphs,
all 10 global OBD-II modes, wireless scan module, and 100+ OEM-specific vehicle
systems across listed domestic, Asian, and European coverage.

The ZEUS scanner workflow includes vehicle identification, system selection,
codes, clear codes, data display, generic functions, functional tests, actuator
tests, memory resets, system tests, data recording and playback, and vehicle
system reports. Actual functions vary by vehicle and software coverage.

Useful UI patterns:
- Vehicle identity and scan-module / DLC-voltage status in a persistent header.
- A system-oriented menu rather than one flat list of every function.
- Code menu and data display as separate tasks.
- Selectable data lists, graphing, recording, pause and playback.
- Clear confirmation and warning messages before consequential actions.

Excluded Snap-on-specific services:
Fast-Track Intelligent Diagnostics, SureTrack, Smart Data, repair information
subscriptions, cloud upload/printing, training, and other proprietary online
resources. We may implement local, evidence-based diagnostic workflows, but must
not copy proprietary text, graphics, databases, or claim those services.

Sources:
- https://www.snapon.com/EN/US/Diagnostics/Products/ZEUS
- https://www.snapon.com/EN/US/Diagnostics/Products/ZEUS-Plus
- https://www.snapon.com/DiagnosticsManuals/ZEUSPLUS%20NA/Content/ZEUS/Scanner_1.htm
- https://www.snapon.com/DiagnosticsManuals/ZEUS%20NA/Content/ZEUS/Scanner_1.htm
- https://www.snapon.com/DiagnosticsManuals/ZEUSPLUS%20NA/Content/ZEUS/Basic%20Features%20Controls%20%20Navigation.htm

### Snap-on TITAN naming check

No Snap-on diagnostic platform named TITAN appears in the current Snap-on US
catalog or its current product-help listing. Snap-on lists ZEUS+, TRITON,
TRITON-D10, APOLLO, SOLUS+, and other platforms. The likely similarly named
Snap-on product is TRITON, but this document does not silently treat them as the
same product.

There are unrelated products called TITAN:
- Titan Tools 51002/51003 wireless OBD-II readers, with basic code, readiness,
  freeze-frame, live-data and vehicle-information functions.
- Autocom TITAN, a separate commercial-vehicle diagnostic interface.

If a different TITAN model was intended, its exact manufacturer/model should be
confirmed before using it as a UI reference.

Sources:
- https://www.snapon.com/EN/US/Diagnostics/Diagnostics-Tools/Current-Products
- https://www.snapon.com/EN/US/Diagnostics/Resource-Center
- https://www.eautotools.com/TITAN-TIT51003-p/tit51003.htm
- https://device.report/m/0d512d1661bd2d929e4eeacfeb005b4d3607c172546fcb2f67082cfb7b26feb7.pdf
- https://diagtools.eu/img/cms/Manuals-brochures/TITAN_Product_broschure_A5_ENG.pdf

### THINKCAR THINKTOOL 399 / Platinum 399

Public regional material describes a 14-inch diagnostic tablet using the TCOS
interface and THINKLINK PRO VCI. The US store lists full-system diagnostics,
DTC read/clear, live data streaming and recording, active tests, coding,
bidirectional functions, CAN FD and DoIP, dual-vehicle diagnosis with a second
VCI, and 48 maintenance functions. Regional product pages vary in their listed
maintenance-function count, update terms, vehicle packages and accessories.

The user manual describes:
- Intelligent VIN / vehicle identification and manual vehicle selection.
- High-speed scan where supported, Smart Scan, system scan and selected-system scan.
- A topology view and a system-list view.
- ECU-specific version information, DTCs, live data and special functions.
- Live-data recording and split-screen comparisons.
- Vehicle / ECU selection, VCI connection management and diagnostic settings.

Excluded from the FreeRov3r diagnostic workspace:
AI assistant, remote video support, cloud repair databases, online programming,
remote expert access, paid software packages, ADAS / TPMS / key-programming
accessories, and other add-on or online ecosystem features. Local active tests
or service routines may appear only when a real, verified implementation exists.

Sources:
- https://thinkcar.in/product/thinktool-expert-399/
- https://thinkcarus.com/products/platinum-399
- https://manuals.plus/m/1bff01ccf6c70640b35961885d2bf4628b6712bcd9941da3c27ff4bf366b3d4d
- https://automechanika.messefrankfurt.com/frankfurt/en/exhibitor-search.detail.html/thinkcar-europe-gmbh/mf_1_0052588770_5194439_10000007202601.html

## Common professional diagnostic workflow

The following functions are common to the reviewed commercial scanner workflows:

1. Vehicle identification and communication status.
2. Whole-vehicle / selected-system scan and system list.
3. ECU/module selection.
4. Read, clear and classify diagnostic trouble codes.
5. Freeze-frame data.
6. Live parameter data in list, digital and graph views.
7. Selectable parameter lists, recording, pause and playback.
8. Global OBD-II functions: current, pending and permanent codes where supported;
   readiness / I/M status; Mode 06 monitor results; oxygen-sensor tests; Mode 09
   vehicle and calibration identification; and Mode 02 freeze frame.
9. Supported active tests, actuator tests, adaptations and service resets.
10. Vehicle scan report and saved diagnostic session.

A commercial tool may expose additional functions for a particular vehicle. The
availability must be determined from verified vehicle support, not from a
generic menu template.

## FreeRov3r interface boundaries

### Diagnostics workspace

The operator-facing workspace should contain only conventional scan-tool tasks:
vehicle identity, OBD-II, module/system overview, DTCs, freeze frame, live data,
graphing, supported service functions, vehicle history and reports.

It should not contain raw CAN frame tables, protocol decoders, D-PDU configuration,
DBC editors, firmware tools, REA workflows, experimental tuning or wiring reverse
engineering. Those belong in Development & Research.

### Development & Research workspace

Keep raw CAN capture, D-PDU discovery, research analysis, tuning experiments,
wiring references, and engineering-oriented sensor / graph tools here.

### Current implementation truth

- ELM327 support is intended for standard OBD-II request / response functions;
  it is not a general raw-CAN capture interface.
- Dual ESP32 adapters are the intended raw HS-CAN / MS-CAN capture path.
- OBD-II controls exist for DTC, readiness, freeze-frame, vehicle-information
  and monitor-test requests, subject to adapter and vehicle support.
- Sensor graphing is available for recorded sensor samples; it is not a claim of
  universal OEM PID coverage.
- The module inventory and topology fixtures are synthetic. They are visibly
  labelled as simulated and must not be presented as a live scan.
- Special Functions currently provides a catalog and read-only preflight only.
  It does not execute ECU commands.
- No live all-module L319 scan, active-test executor, ECU coding, or online
  programming capability is claimed.

## Design principles

- One clear task per screen; avoid marketing tiles and oversized icon grids.
- Persistent vehicle identity, interface state and voltage / connection status
  where the data is actually available.
- System list and topology as alternate ways to browse modules.
- DTC details lead to related freeze-frame and live-data evidence.
- Live data offers compact list, digital and graph presentations.
- Keep recording and playback separate from the live stream display.
- Every function must communicate whether it is supported, unavailable,
  simulated, or not yet implemented.
- No placeholder action should look like an executable ECU command.
