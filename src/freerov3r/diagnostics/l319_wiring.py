"""2010 Discovery 4 / LR4 (LHD) electrical network reference, PV8 5.0L baseline.

Transcribed network details from section 418-00 of the 12/2009 Land Rover
Electrical Wiring Diagrams. Drawing vehicle: LHD, VIN 524545 > (1b).
This is factory-reference data, not a live-discovered vehicle topology.
"""
SOURCE_TITLE = "Land Rover Discovery 4 / LR4 Electrical Wiring Diagrams (12/2009)"
SOURCE_URL = "https://gershon.ucoz.com/LANDROVER/EWD2010.pdf"
SCRIBD_URL = "https://www.scribd.com/document/427340797/LR4-2009-2011-2010-Electrical-Wiring-Diagrams"
DEFAULT_ENGINE = "PV8 5.0L petrol V8"

# module tuple: short code, factory component ID, name, connector detail, notes
NETWORKS = {
"HS-CAN": {
"title":"HIGH-SPEED CAN", "pages":"Printed pages 122–123 | PDF pages 123–124",
"description":"Powertrain, chassis and safety network. Section 418-00, sheets 1–2.",
"pair":"HS CAN H: YN  |  HS CAN L: YB",
"dlc":"C0040 pin 6 = HS CAN H (YN); pin 14 = HS CAN L (YB)",
"modules":[
("ECM","D131","Engine Control Module — PV8 5.0L","PV8 engine-management branch, section 303-14","Selected engine baseline. Confirm exact VIN/market calibration."),
("TCM","D306","Transmission Control Module / Control Valve Body","Shown on HS-CAN sheet 1","Transmission circuit section 307-01 lists PV8 with 3.0L diesel variant."),
("ABS/DSC","D277","ABS / Dynamic Stability Control Module","Shown on HS-CAN sheet 1","Safety-critical module."),
("TCCM","D204","Transfer Box Control Module","Shown on HS-CAN sheet 1","Four-wheel-drive control."),
("AFS","D276","Adaptive Front Lighting Control Module","Shown on HS-CAN sheet 1","Equipment dependent."),
("AIR-SUS","D199","Air Suspension Control Module","C0867L-17 = H; C0867L-18 = L","H=YN; L=YB."),
("SAS","T274","Steering Angle Sensor","C0862L-6 = H; C0862L-7 = L","H=YN; L=YB."),
("SCL","D401","Steering Column Lock Module","C2055L-4 = H; C2055L-3 = L","H=YN; L=YB."),
("RCM","D171","Restraints Control Module","C0256-31 = H; C0256-32 = L","Gold-plated terminals noted; safety-critical."),
("REAR-DIFF","D283","Rear Differential Control Module","C2162S-5 = H; C2162S-2 = L","H=YN; L=YB."),
("EPB","D278","Parking Brake Module","C0376-31 / C0390-31 = H; C0376-32 / C0390-32 = L","Terminating resistor G171 shown in this branch."),
("IC-HS","D107","Instrument Cluster — HS-CAN connection","C0230-21 = H; C0230-5 = L","H=YN; L=YB."),
("OCC","T221","Occupancy Detector Sensor","C0962-18 = H; C0962-9 = L","Gold-plated terminals noted."),
("DLC-HS","V100","Diagnostic Socket","C0040-6 = H; C0040-14 = L","Diagnostic connector HS-CAN access."),
]},
"MS-CAN": {
"title":"MEDIUM-SPEED CAN", "pages":"Printed page 121 | PDF page 122",
"description":"Body, convenience and cabin network. Section 418-00, sheet 1.",
"pair":"MS CAN H: YW  |  MS CAN L: YU",
"dlc":"C0040 pin 3 = MS CAN H (YW); pin 11 = MS CAN L (YU)",
"modules":[
("BCM","D207 / P101","Body Control Module / Central Junction Box","C0581-5 = H; C0581-4 = L","Central junction box network and termination details shown."),
("DDM","D253","Driver Door Module","C2058-3 = H; C2058-15 = L","Door harness also references C0440-1 / C0440-2."),
("PDM","D254","Passenger Door Module","C2057-3 = H; C2057-15 = L","Door harness also references C0439-2 / C0439-3."),
("MEM","D119","Memory Control Module","C2382-14 = H; C2382-15 = L","Additional path via C0751 and C2378."),
("KVM","D374","Keyless Vehicle Module","C2428S-14 = H; C2428S-13 = L","Equipment dependent."),
("PAM","D184","Parking Aid Module","C0957-14 = H; C0957-7 = L","Header K236 branch via C1000."),
("CAM","D454","Camera Module","C3339-2 = H; C3339-3 = L","Header K236 branch via C1000."),
("MIRROR","B179","Electrochromic Mirror","C0698S-8 = H; C0698S-7 = L","As identified on page 121."),
("CONSOLE","S425","Center Instrument Panel Switch Pack","C1629SL-3 = H; C1629SL-4 = L","Cabin switch-pack connection."),
("AUDIO-HU","D282","Audio Head Unit","C1354-9 = H; C1354-10 = L","Also participates in MOST on applicable equipment."),
("ICP","D472","Lower Integrated Control Panel","C2153L-3 = H; C2153L-4 = L","Center stack control panel."),
("HVAC","D243","Climate Control Module","C3470-12 = H; C3470-13 = L","H=YW; L=YU."),
("DLC-MS","V100","Diagnostic Socket","C0040-3 = H; C0040-11 = L","Diagnostic connector MS-CAN access."),
("IC-MS","J100","Instrument Cluster — MS-CAN connection","C0230-23 = H; C0230-7 = L","Terminating resistor G171 shown at instrument cluster."),
]},
"MOST": {
"title":"MOST OPTICAL NETWORK", "pages":"Printed pages 124–129 | PDF pages 125–130",
"description":"Optical infotainment network. Section 418-00 shows several equipment-specific layouts.",
"pair":"Orange plastic optical fibre (POF); each participating device has MOST IN and MOST OUT.",
"dlc":"MOST is optical and is not exposed as a CAN wire pair at the diagnostic socket.",
"modules":[
("AUDIO-HU","D282","Audio Head Unit","MOST IN C2105-1; OUT C2105-2","Shown across the MOST equipment layouts."),
("DISPLAY","D326","Touch Screen Display","MOST IN C2825-1; OUT C2825-2","Configuration dependent."),
("AMP","F142","Power Amplifier","MOST IN C2102-1; OUT C2102-2","High-line audio equipment."),
("RSE","D313","Rear Seat Entertainment Module","MOST IN C2109-1; OUT C2109-2","Optional equipment."),
("PHONE","D261","Telephone Module","MOST IN C2778-1; OUT C2778-2","Optional equipment."),
("PORT-AUDIO","D436","Portable Audio Interface Module","MOST IN C3362-1; OUT C3362-2","Equipment dependent."),
("DAB","D350","DAB / SDARS Tuner Module","MOST IN C2155-1; OUT C2155-2","Market and equipment dependent."),
("TV","D328","Television Receiver Module","MOST IN C2106-1; OUT C2106-2","Optional equipment."),
("IBOC","D430","IBOC Radio Module","MOST IN C3284-1; OUT C3284-2","Market/equipment dependent."),
]}
}
