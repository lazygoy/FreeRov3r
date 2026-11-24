# FreeRov3r ESP32-S3 CAN receiver

## Hardware

Target: ESP32-S3 DevKitC-1 N16R8 and the user's SN65HVD230 transceiver module.

| ESP32-S3 | SN65HVD230 |
|---|---|
| 3V3 | 3V3 |
| GND | GND |
| GPIO5 | CTX |
| GPIO4 | CRX |
| CANH | OBD-II pin 6 |
| CANL | OBD-II pin 14 |

The SN65HVD230 module is the physical-layer transceiver. The ESP32-S3's
built-in TWAI controller handles CAN framing. Never connect GPIO directly
to CANH or CANL.

Power the ESP32 from USB. Do not connect OBD-II pin 16 (vehicle battery)
to the ESP32 or transceiver's 3.3 V supply. Share signal ground using the
appropriate OBD ground reference. Do not add a 120-ohm terminator when
connecting to an already-terminated vehicle network.

## Firmware

Open `esp32_twai_rx.ino` in Arduino IDE with an ESP32 Arduino core that
provides `driver/twai.h`. Select the ESP32-S3 DevKitC-1 board.

Default CAN speed is 500 kbit/s. To change it, edit the
`FREEROV3R_CAN_BITRATE` definition to one of:

- `125000`
- `250000`
- `500000`
- `1000000`

The serial output is 921600 baud. FreeRov3r's ESP32 adapter uses the same
default.

## Receive-only behavior

The TWAI driver is installed in `TWAI_MODE_LISTEN_ONLY`, with its transmit
queue disabled. There is no serial command handler and no CAN transmit call.
In listen-only mode the controller does not transmit frames or acknowledge
received frames. This is the intended mode for observing another scanner's
traffic without participating in vehicle communication.

The firmware reports startup metadata and bus/queue alerts as comment lines
beginning with `#`. CAN data frames use:

```text
S,00000123,2,0102
E,18DAF110,8,032201F190000000
```

The explicit S/E flag preserves standard-versus-extended frame format even
when an extended identifier has a numeric value below 0x800.

## Validation sequence

1. Compile and upload with the CAN transceiver disconnected from the vehicle.
2. Open the serial monitor at 921600 baud and confirm the listen-only startup
   metadata appears.
3. Use a known CAN test source on a properly terminated bench bus to confirm
   frame reception and standard/extended ID parsing.
4. Confirm the adapter reports no transmit capability and no frames are sent.
5. Only then connect to the vehicle network, without adding termination.

The software's listen-only setting is not a substitute for checking wiring,
power, and the actual hardware before vehicle connection. The firmware is
Classical CAN only; it does not support CAN FD.
