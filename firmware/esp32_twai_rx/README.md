# FreeRov3r ESP32-S3 CAN receiver

## Hardware

Target: ESP32-S3 DevKitC-1 N16R8 and SN65HVD230 CAN transceiver.

| ESP32-S3 | SN65HVD230 |
|---|---|
| 3V3 | 3V3 |
| GND | GND |
| GPIO5 | CTX |
| GPIO4 | CRX |
| CANH | CANH on the target network |
| CANL | CANL on the target network |

The SN65HVD230 is the physical-layer transceiver. The ESP32-S3 TWAI
controller handles CAN framing. Never connect GPIO directly to CANH/CANL.

Power the ESP32 from USB. Do not connect OBD-II pin 16 (vehicle battery) to
the ESP32 or transceiver 3.3 V supply. Use an appropriate OBD ground reference.
Do not add a 120-ohm terminator when connected to an already-terminated
vehicle network.

## Build settings

Open `esp32_twai_rx.ino` in Arduino IDE with an ESP32 Arduino core providing
`driver/twai.h`. Select the ESP32-S3 DevKitC-1 board.

The source supports these build-time settings:

| Define | Default | Purpose |
|---|---:|---|
| `FREEROV3R_CAN_BITRATE` | `500000` | CAN bitrate: 125000, 250000, 500000, or 1000000 |
| `FREEROV3R_CAN_CHANNEL` | `0` | Logical channel number sent in binary CAN frame records |
| `FREEROV3R_BINARY_PROTOCOL` | `0` | Set to `1` for version 1 binary USB protocol; `0` retains legacy text output |

For simultaneous LR4 HS-CAN and MS-CAN capture, build and upload the firmware
to two boards:

1. HS-CAN board, OBD-II pins 6/14: bitrate `500000`, channel `0`.
2. MS-CAN board, OBD-II pins 3/11: bitrate `125000`, channel `1`.

For the new binary protocol, set `FREEROV3R_BINARY_PROTOCOL=1` in the Arduino
build flags. Example compiler flags:

```text
-DFREEROV3R_BINARY_PROTOCOL=1
-DFREEROV3R_CAN_BITRATE=500000
-DFREEROV3R_CAN_CHANNEL=0
```

For the MS-CAN board, use `125000` and channel `1`. In Arduino IDE, build
flags can be supplied through the selected board's build configuration or
with a build system such as PlatformIO. Do not paste these defines into the
middle of the sketch after they have already been used.

Serial speed is 921600 baud. Use FreeRov3r's **ESP32 framed USB serial**
adapter for binary protocol firmware. The existing **ESP32 serial** adapter
continues to support the legacy text firmware. The two formats are not
interchangeable.

## Binary protocol v1

The binary stream uses the same versioned envelope as
`freerov3r.hardware.device_protocol`:

```text
magic[2] = "FR"
version:u8
message_type:u8
flags:u8
sequence:u32 (big endian)
payload_length:u16 (big endian)
payload[payload_length]
crc16:u16 (CRC-16/CCITT-FALSE, big endian)
```

Implemented device-to-host message types:

- `HELLO (0x01)`: firmware identity, protocol version and listen-only mode.
- `DEVICE_STATUS (0x12)`: startup, error and TWAI alert text.
- `FRAME_RX (0x20)`: channel, frame flags, DLC, CAN ID, device timestamp and
  Classical-CAN data bytes.

The CAN frame payload is big-endian for multi-byte fields:
`channel:u8 | flags:u8 | DLC:u8 | CAN_ID:u32 | device_time_us:u64 | data`.
Flag bit 0 indicates an extended identifier. Flag bit 1 is reserved for
remote frames; the current firmware omits remote frames.

Sequence numbers increase for every emitted protocol message. The timestamp
is microseconds since this ESP32 boot and is not synchronized with the PC or
another ESP32. FreeRov3r records a separate host monotonic receive timestamp.

This first firmware protocol implementation is deliberately transmit-free:
it does not parse host commands, configure CAN dynamically, acknowledge
requests, or send CAN frames. USB serial carries device-to-host data only.

## Legacy text protocol

With `FREEROV3R_BINARY_PROTOCOL=0`, the firmware emits text lines such as:

```text
S,00000123,2,0102,123456789
E,18DAF110,8,032201F190000000,123456790
```

Startup metadata and alerts begin with `#`. The existing legacy serial
adapter remains compatible with this mode.

## Receive-only behavior

TWAI is always installed in `TWAI_MODE_LISTEN_ONLY`, with its transmit queue
disabled. No CAN transmit function is called. In listen-only mode the
controller does not transmit frames or acknowledge received frames.

The current binary protocol implementation does not enable vehicle
diagnostic polling, UDS requests, or general CAN transmission. Those are
separate future capabilities requiring independent implementation and
authorization.

## Validation sequence

1. Compile and upload with the CAN transceiver disconnected from the vehicle.
2. Confirm the firmware emits either legacy startup metadata or valid binary
   HELLO and READY messages.
3. On a properly terminated bench CAN bus, verify standard and extended frame
   IDs, DLC, payload and device timestamps.
4. Confirm sequence numbers increase and FreeRov3r reports no decoder CRC
   errors or sequence gaps under controlled traffic.
5. Confirm the adapter reports receive-only operation and no frames are sent.
6. Only after bench validation, connect to the vehicle network without adding
   termination.

The software listen-only setting does not replace checking wiring, power and
the actual hardware. This firmware supports Classical CAN only, not CAN FD.

## Wi-Fi TCP transport

Wi-Fi streaming is optional and is compiled only when binary protocol is
enabled, `FREEROV3R_WIFI_ENABLED=1`, and the build supplies an SSID and
password. There is no default SSID, password, or open access point.

Example build defines for a user-configured WPA2 network:

```text
-DFREEROV3R_BINARY_PROTOCOL=1
-DFREEROV3R_WIFI_ENABLED=1
-DFREEROV3R_WIFI_SSID=\\\"YOUR_WIFI_NAME\\\"
-DFREEROV3R_WIFI_PASSWORD=\\\"YOUR_WIFI_PASSWORD\\\"
-DFREEROV3R_WIFI_PORT=3333
-DFREEROV3R_CAN_BITRATE=500000
-DFREEROV3R_CAN_CHANNEL=0
```

Keep real credentials out of source control and shared build logs. The device
joins the configured Wi-Fi network in station mode and listens for one TCP
client on port 3333. TCP uses the same binary v1 envelope as USB. USB and TCP
have independent bounded output queues and sequence counters. A slow or
disconnected TCP client cannot block the CAN receive loop or USB writer.
TCP queue overflow is reported as `STATS,WIFI_QUEUE_DROPS,<count>`. Old
queued frames are discarded when a new TCP client connects, preventing a
reconnect from silently replaying stale traffic.

The TCP stream is unencrypted and has no client authentication in this
firmware revision. Use only on a trusted, access-controlled local network.
Do not expose port 3333 to the public internet. The device accepts one client
at a time. The TCP listener does not parse commands and cannot transmit CAN.

FreeRov3r's PC-side Wi-Fi adapter connects to the ESP32 IP address and port
3333. Find the assigned address in the router's DHCP client list. This
firmware does not yet provide automatic device discovery.
