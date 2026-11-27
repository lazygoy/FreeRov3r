/*
 * FreeRov3r ESP32-S3 TWAI passive CAN receiver.
 *
 * Target: ESP32-S3 DevKitC-1 N16R8 + external SN65HVD230 transceiver.
 * Classical CAN only. TWAI listen-only mode: no frame transmission and no ACK.
 *
 * Wiring:
 *   GPIO5 (TWAI TX) -> SN65HVD230 CTX
 *   GPIO4 (TWAI RX) -> SN65HVD230 CRX
 *   3V3             -> 3V3
 *   GND             -> GND
 *   CANH/CANL       -> vehicle CANH/CANL
 *
 * Never connect ESP32 GPIO directly to CANH/CANL.
 *
 * Set FREEROV3R_BINARY_PROTOCOL=1 in build flags to use protocol v1 over USB.
 * The default remains the legacy text stream for compatibility.
 */
#include <Arduino.h>
#include "driver/twai.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"

#ifndef FREEROV3R_WIFI_ENABLED
#define FREEROV3R_WIFI_ENABLED 0
#endif

#if FREEROV3R_BINARY_PROTOCOL && FREEROV3R_WIFI_ENABLED
#include <WiFi.h>
#ifndef FREEROV3R_WIFI_SSID
#error "Set FREEROV3R_WIFI_SSID at build time; no default network is configured."
#endif
#ifndef FREEROV3R_WIFI_PASSWORD
#error "Set FREEROV3R_WIFI_PASSWORD at build time; no default password is configured."
#endif
#ifndef FREEROV3R_WIFI_PORT
#define FREEROV3R_WIFI_PORT 3333
#endif
static WiFiServer wifiServer(FREEROV3R_WIFI_PORT);
static QueueHandle_t wifiOutputQueue = nullptr;
static volatile bool wifiClientConnected = false;
static volatile uint32_t wifiQueueDrops = 0;
#endif

static constexpr gpio_num_t CAN_TX_PIN = GPIO_NUM_5;
static constexpr gpio_num_t CAN_RX_PIN = GPIO_NUM_4;

#ifndef FREEROV3R_CAN_BITRATE
#define FREEROV3R_CAN_BITRATE 500000
#endif
#ifndef FREEROV3R_CAN_CHANNEL
#define FREEROV3R_CAN_CHANNEL 0
#endif
#ifndef FREEROV3R_BINARY_PROTOCOL
#define FREEROV3R_BINARY_PROTOCOL 0
#endif

#if FREEROV3R_CAN_BITRATE == 125000
static const twai_timing_config_t timing = TWAI_TIMING_CONFIG_125KBITS();
#elif FREEROV3R_CAN_BITRATE == 250000
static const twai_timing_config_t timing = TWAI_TIMING_CONFIG_250KBITS();
#elif FREEROV3R_CAN_BITRATE == 500000
static const twai_timing_config_t timing = TWAI_TIMING_CONFIG_500KBITS();
#elif FREEROV3R_CAN_BITRATE == 1000000
static const twai_timing_config_t timing = TWAI_TIMING_CONFIG_1MBITS();
#else
#error "Unsupported FREEROV3R_CAN_BITRATE. Use 125000, 250000, 500000, or 1000000."
#endif

#if FREEROV3R_BINARY_PROTOCOL
static constexpr uint8_t PROTOCOL_VERSION = 1;
static constexpr uint8_t MSG_HELLO = 0x01;
static constexpr uint8_t MSG_DEVICE_STATUS = 0x12;
static constexpr uint8_t MSG_FRAME_RX = 0x20;
static uint32_t messageSequence = 0;

static constexpr UBaseType_t OUTPUT_QUEUE_LENGTH = 256;
static constexpr uint8_t OUTPUT_ITEM_FRAME = 1;
static constexpr uint8_t OUTPUT_ITEM_STATUS = 2;
struct OutputItem {
  uint8_t kind;
  twai_message_t frame;
  uint64_t timestampUs;
  char status[64];
};
static QueueHandle_t outputQueue = nullptr;
static volatile uint32_t outputQueueDrops = 0;
static uint32_t reportedOutputQueueDrops = 0;
#if FREEROV3R_WIFI_ENABLED
static uint32_t wifiMessageSequence = 0;
#endif

static bool enqueueFrame(const twai_message_t &frame, uint64_t timestampUs) {
  if (!outputQueue) {
    ++outputQueueDrops;
    return false;
  }
  OutputItem item = {};
  item.kind = OUTPUT_ITEM_FRAME;
  item.frame = frame;
  item.timestampUs = timestampUs;
  if (xQueueSend(outputQueue, &item, 0) != pdTRUE) {
    ++outputQueueDrops;
    return false;
  }
#if FREEROV3R_WIFI_ENABLED
  if (wifiClientConnected && wifiOutputQueue &&
      xQueueSend(wifiOutputQueue, &item, 0) != pdTRUE) {
    ++wifiQueueDrops;
  }
#endif
  return true;
}
static bool enqueueStatus(const char *status) {
  if (!outputQueue) return false;
  OutputItem item = {};
  item.kind = OUTPUT_ITEM_STATUS;
  strncpy(item.status, status, sizeof(item.status) - 1);
  const bool queued = xQueueSend(outputQueue, &item, 0) == pdTRUE;
#if FREEROV3R_WIFI_ENABLED
  if (queued && wifiClientConnected && wifiOutputQueue &&
      xQueueSend(wifiOutputQueue, &item, 0) != pdTRUE) ++wifiQueueDrops;
#endif
  return queued;
}

static void writeU16(uint8_t *out, uint16_t value) {
  out[0] = (uint8_t)(value >> 8);
  out[1] = (uint8_t)value;
}
static void writeU32(uint8_t *out, uint32_t value) {
  out[0] = (uint8_t)(value >> 24);
  out[1] = (uint8_t)(value >> 16);
  out[2] = (uint8_t)(value >> 8);
  out[3] = (uint8_t)value;
}
static void writeU64(uint8_t *out, uint64_t value) {
  for (uint8_t i = 0; i < 8; ++i) {
    out[i] = (uint8_t)(value >> (56 - (i * 8)));
  }
}
static uint16_t crc16Ccitt(const uint8_t *data, size_t length) {
  uint16_t crc = 0xFFFF;
  for (size_t i = 0; i < length; ++i) {
    crc ^= (uint16_t)data[i] << 8;
    for (uint8_t bit = 0; bit < 8; ++bit) {
      crc = (crc & 0x8000) ? (uint16_t)((crc << 1) ^ 0x1021)
                           : (uint16_t)(crc << 1);
    }
  }
  return crc;
}
static void sendMessage(uint8_t type, const uint8_t *payload, uint16_t length) {
  // Protocol envelope: FR | version | type | flags | sequence | length | payload | CRC.
  if (length > 4096) return;
  uint8_t header[11] = {
    'F', 'R', PROTOCOL_VERSION, type, 0, 0, 0, 0, 0, 0, 0
  };
  writeU32(&header[5], messageSequence++);
  writeU16(&header[9], length);
  uint16_t crc = crc16Ccitt(header, sizeof(header));
  for (uint16_t i = 0; i < length; ++i) {
    uint8_t byte = payload[i];
    crc ^= (uint16_t)byte << 8;
    for (uint8_t bit = 0; bit < 8; ++bit) {
      crc = (crc & 0x8000) ? (uint16_t)((crc << 1) ^ 0x1021)
                           : (uint16_t)(crc << 1);
    }
  }
  Serial.write(header, sizeof(header));
  if (length) Serial.write(payload, length);
  uint8_t crcBytes[2];
  writeU16(crcBytes, crc);
  Serial.write(crcBytes, sizeof(crcBytes));
}
static void sendStatus(const char *status) {
  sendMessage(MSG_DEVICE_STATUS, (const uint8_t *)status, strlen(status));
}
static void sendHello() {
  static const char hello[] =
      "FreeRov3r ESP32-S3;protocol=1;mode=listen-only;can=classical";
  sendMessage(MSG_HELLO, (const uint8_t *)hello, sizeof(hello) - 1);
}
#if FREEROV3R_WIFI_ENABLED
static bool wifiWriteMessage(WiFiClient &client, uint8_t type,
                             const uint8_t *payload, uint16_t length) {
  uint8_t packet[11 + 64 + 2];
  if (length > 64) return false;
  packet[0] = 'F'; packet[1] = 'R';
  packet[2] = PROTOCOL_VERSION; packet[3] = type; packet[4] = 0;
  writeU32(&packet[5], wifiMessageSequence++);
  writeU16(&packet[9], length);
  if (length) memcpy(&packet[11], payload, length);
  uint16_t crc = crc16Ccitt(packet, 11 + length);
  writeU16(&packet[11 + length], crc);
  return client.write(packet, 13 + length) == (size_t)(13 + length);
}

static bool wifiSendItem(WiFiClient &client, const OutputItem &item) {
  if (item.kind == OUTPUT_ITEM_STATUS) {
    return wifiWriteMessage(client, MSG_DEVICE_STATUS,
        (const uint8_t *)item.status, strlen(item.status));
  }
  uint8_t payload[23] = {0};
  payload[0] = FREEROV3R_CAN_CHANNEL;
  payload[1] = item.frame.extd ? 0x01 : 0x00;
  payload[2] = item.frame.data_length_code;
  writeU32(&payload[3], item.frame.identifier);
  writeU64(&payload[7], item.timestampUs);
  for (uint8_t i = 0; i < item.frame.data_length_code; ++i)
    payload[15 + i] = item.frame.data[i];
  return wifiWriteMessage(client, MSG_FRAME_RX, payload,
                          15 + item.frame.data_length_code);
}

static void wifiWriterTask(void *parameter) {
  (void)parameter;
  WiFi.mode(WIFI_STA);
  WiFi.begin(FREEROV3R_WIFI_SSID, FREEROV3R_WIFI_PASSWORD);
  while (WiFi.status() != WL_CONNECTED) vTaskDelay(pdMS_TO_TICKS(500));
  wifiServer.begin();
  wifiServer.setNoDelay(true);
  const String ipText = WiFi.localIP().toString();
  char networkStatus[64];
  snprintf(networkStatus, sizeof(networkStatus), "WIFI_READY,%s,%u",
           ipText.c_str(), (unsigned)FREEROV3R_WIFI_PORT);
  enqueueStatus(networkStatus);

  WiFiClient client;
  OutputItem item;
  uint32_t reportedDrops = 0;
  for (;;) {
    if (!client || !client.connected()) {
      if (client) client.stop();
      wifiClientConnected = false;
      WiFiClient incoming = wifiServer.available();
      if (incoming) {
        client = incoming;
        client.setNoDelay(true);
        // Do not replay stale frames from a previous TCP session.
        while (xQueueReceive(wifiOutputQueue, &item, 0) == pdTRUE) {}
        wifiClientConnected = true;
        enqueueStatus("WIFI_CLIENT_CONNECTED");
        static const char hello[] =
            "FreeRov3r ESP32-S3;protocol=1;mode=listen-only;tcp=1";
        wifiWriteMessage(client, MSG_HELLO, (const uint8_t *)hello,
                         sizeof(hello) - 1);
        static const char ready[] = "READY,LISTEN_ONLY,TCP";
        wifiWriteMessage(client, MSG_DEVICE_STATUS,
                         (const uint8_t *)ready, sizeof(ready) - 1);
      }
    }

    if (client && client.connected() &&
        xQueueReceive(wifiOutputQueue, &item, pdMS_TO_TICKS(20)) == pdTRUE) {
      if (!wifiSendItem(client, item)) {
        client.stop();
        wifiClientConnected = false;
      }
    }

    const uint32_t dropped = wifiQueueDrops;
    if (client && client.connected() && dropped != reportedDrops) {
      char status[64];
      snprintf(status, sizeof(status), "STATS,WIFI_QUEUE_DROPS,%lu",
               (unsigned long)dropped);
      wifiWriteMessage(client, MSG_DEVICE_STATUS,
                       (const uint8_t *)status, strlen(status));
      reportedDrops = dropped;
    }
    vTaskDelay(pdMS_TO_TICKS(1));
  }
}
#endif

static void sendCanFrame(const twai_message_t &msg, uint64_t timestampUs);

static void serialWriterTask(void *parameter) {
  (void)parameter;
  OutputItem item;
  for (;;) {
    if (xQueueReceive(outputQueue, &item, pdMS_TO_TICKS(100)) == pdTRUE) {
      if (item.kind == OUTPUT_ITEM_FRAME) {
        sendCanFrame(item.frame, item.timestampUs);
      } else if (item.kind == OUTPUT_ITEM_STATUS) {
        sendStatus(item.status);
      }
    }

    const uint32_t dropped = outputQueueDrops;
    if (dropped != reportedOutputQueueDrops) {
      char status[64];
      snprintf(status, sizeof(status), "STATS,OUTPUT_QUEUE_DROPS,%lu",
               (unsigned long)dropped);
      sendStatus(status);
      reportedOutputQueueDrops = dropped;
    }
  }
}

static void sendCanFrame(const twai_message_t &msg, uint64_t timestampUs) {
  // FRAME_RX payload: channel:u8, flags:u8, DLC:u8, CAN ID:u32, timestamp:u64, data.
  uint8_t payload[23] = {0};
  payload[0] = FREEROV3R_CAN_CHANNEL;
  payload[1] = msg.extd ? 0x01 : 0x00;
  payload[2] = msg.data_length_code;
  writeU32(&payload[3], msg.identifier);
  writeU64(&payload[7], timestampUs);
  for (uint8_t i = 0; i < msg.data_length_code; ++i) {
    payload[15 + i] = msg.data[i];
  }
  sendMessage(MSG_FRAME_RX, payload, 15 + msg.data_length_code);
}
#else
static void printFrame(const twai_message_t &msg, int64_t deviceTimestampUs) {
  Serial.printf("%c,%08lX,%u,", msg.extd ? 'E' : 'S',
                (unsigned long)msg.identifier, msg.data_length_code);
  for (uint8_t i = 0; i < msg.data_length_code; ++i) {
    Serial.printf("%02X", msg.data[i]);
  }
  Serial.printf(",%llu\n", (unsigned long long)deviceTimestampUs);
}
#endif

void setup() {
  Serial.begin(921600);
  delay(300);

  twai_general_config_t general = TWAI_GENERAL_CONFIG_DEFAULT(
      CAN_TX_PIN, CAN_RX_PIN, TWAI_MODE_LISTEN_ONLY);
  general.rx_queue_len = 256;
  general.tx_queue_len = 0;
  general.alerts_enabled =
      TWAI_ALERT_RX_QUEUE_FULL | TWAI_ALERT_BUS_OFF | TWAI_ALERT_BUS_ERROR;

  const twai_filter_config_t filter = TWAI_FILTER_CONFIG_ACCEPT_ALL();
  esp_err_t result = twai_driver_install(&general, &timing, &filter);
  if (result != ESP_OK) {
#if FREEROV3R_BINARY_PROTOCOL
    sendStatus("ERROR,TWAI_INSTALL");
#else
    Serial.printf("#ERROR,TWAI_INSTALL,%d\n", (int)result);
#endif
    while (true) delay(1000);
  }

  result = twai_start();
  if (result != ESP_OK) {
#if FREEROV3R_BINARY_PROTOCOL
    sendStatus("ERROR,TWAI_START");
#else
    Serial.printf("#ERROR,TWAI_START,%d\n", (int)result);
#endif
    while (true) delay(1000);
  }

#if FREEROV3R_BINARY_PROTOCOL
  outputQueue = xQueueCreate(OUTPUT_QUEUE_LENGTH, sizeof(OutputItem));
  if (!outputQueue) {
    sendStatus("ERROR,OUTPUT_QUEUE_CREATE");
    while (true) delay(1000);
  }
  BaseType_t taskResult = xTaskCreatePinnedToCore(
      serialWriterTask, "fr_usb_writer", 4096, nullptr, 2, nullptr, 0);
  if (taskResult != pdPASS) {
    sendStatus("ERROR,OUTPUT_TASK_CREATE");
    while (true) delay(1000);
  }
#if FREEROV3R_WIFI_ENABLED
  wifiOutputQueue = xQueueCreate(128, sizeof(OutputItem));
  if (!wifiOutputQueue) {
    sendStatus("ERROR,WIFI_QUEUE_CREATE");
    while (true) delay(1000);
  }
  BaseType_t wifiTaskResult = xTaskCreatePinnedToCore(
      wifiWriterTask, "fr_wifi_writer", 6144, nullptr, 1, nullptr, 0);
  if (wifiTaskResult != pdPASS) {
    sendStatus("ERROR,WIFI_TASK_CREATE");
    while (true) delay(1000);
  }
#endif
  sendHello();
  sendStatus("READY,LISTEN_ONLY");
#else
  Serial.println("#FREEROV3R_CAN_RX,2");
  Serial.println("#PROTOCOL,2");
  Serial.println("#MODE,LISTEN_ONLY");
  Serial.printf("#BITRATE,%u\n", (unsigned)FREEROV3R_CAN_BITRATE);
  Serial.println("#FORMAT,S-or-E,ID,DLC,HEXDATA,DEVICE_TIME_US");
#endif
}

void loop() {
  twai_message_t msg;
  if (twai_receive(&msg, pdMS_TO_TICKS(20)) == ESP_OK) {
    // Device clock is local to this board and is not synchronized to the PC
    // or to another ESP32. The host adds its own monotonic receive timestamp.
    const uint64_t deviceTimestampUs = (uint64_t)esp_timer_get_time();
    if (!msg.rtr) {
#if FREEROV3R_BINARY_PROTOCOL
      enqueueFrame(msg, deviceTimestampUs);
#else
      printFrame(msg, (int64_t)deviceTimestampUs);
#endif
    }
  }

  uint32_t alerts = 0;
  if (twai_read_alerts(&alerts, 0) == ESP_OK) {
    if (alerts & TWAI_ALERT_RX_QUEUE_FULL) {
#if FREEROV3R_BINARY_PROTOCOL
      enqueueStatus("ALERT,RX_QUEUE_FULL");
#else
      Serial.println("#ALERT,RX_QUEUE_FULL");
#endif
    }
    if (alerts & TWAI_ALERT_BUS_OFF) {
#if FREEROV3R_BINARY_PROTOCOL
      enqueueStatus("ALERT,BUS_OFF");
#else
      Serial.println("#ALERT,BUS_OFF");
#endif
    }
    if (alerts & TWAI_ALERT_BUS_ERROR) {
#if FREEROV3R_BINARY_PROTOCOL
      enqueueStatus("ALERT,BUS_ERROR");
#else
      Serial.println("#ALERT,BUS_ERROR");
#endif
    }
  }
}
