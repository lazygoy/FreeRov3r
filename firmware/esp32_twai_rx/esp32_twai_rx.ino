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
 */
#include <Arduino.h>
#include "driver/twai.h"

static constexpr gpio_num_t CAN_TX_PIN = GPIO_NUM_5;
static constexpr gpio_num_t CAN_RX_PIN = GPIO_NUM_4;

#ifndef FREEROV3R_CAN_BITRATE
#define FREEROV3R_CAN_BITRATE 500000
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

static void printFrame(const twai_message_t &msg) {
  // Explicit S/E flag preserves extended-frame information even when the
  // numeric arbitration ID happens to fit inside the 11-bit range.
  Serial.printf("%c,%08lX,%u,", msg.extd ? 'E' : 'S',
                (unsigned long)msg.identifier, msg.data_length_code);
  for (uint8_t i = 0; i < msg.data_length_code; ++i) {
    Serial.printf("%02X", msg.data[i]);
  }
  Serial.write('\n');
}

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
    Serial.printf("#ERROR,TWAI_INSTALL,%d\n", (int)result);
    while (true) delay(1000);
  }

  result = twai_start();
  if (result != ESP_OK) {
    Serial.printf("#ERROR,TWAI_START,%d\n", (int)result);
    while (true) delay(1000);
  }

  Serial.println("#FREEROV3R_CAN_RX,1");
  Serial.println("#MODE,LISTEN_ONLY");
  Serial.printf("#BITRATE,%u\n", (unsigned)FREEROV3R_CAN_BITRATE);
  Serial.println("#FORMAT,S-or-E,ID,DLC,HEXDATA");
}

void loop() {
  twai_message_t msg;
  if (twai_receive(&msg, pdMS_TO_TICKS(20)) == ESP_OK) {
    // Remote frames have no application payload and are not part of the
    // current Classical-CAN data-frame capture format.
    if (!msg.rtr && !msg.rtr) {
      printFrame(msg);
    }
  }

  uint32_t alerts = 0;
  if (twai_read_alerts(&alerts, 0) == ESP_OK) {
    if (alerts & TWAI_ALERT_RX_QUEUE_FULL) {
      Serial.println("#ALERT,RX_QUEUE_FULL");
    }
    if (alerts & TWAI_ALERT_BUS_OFF) {
      Serial.println("#ALERT,BUS_OFF");
    }
    if (alerts & TWAI_ALERT_BUS_ERROR) {
      Serial.println("#ALERT,BUS_ERROR");
    }
  }
}
