/*
 * FreeRov3r ESP32 TWAI passive receiver prototype.
 * ESP32-WROOM-32 + external CAN transceiver. Classical CAN only, not CAN FD.
 * No transmit command handler. Never connect GPIO directly to CAN-H/CAN-L.
 */
#include <Arduino.h>
#include "driver/twai.h"
static constexpr gpio_num_t CAN_TX_PIN = GPIO_NUM_5;
static constexpr gpio_num_t CAN_RX_PIN = GPIO_NUM_4;
static const twai_timing_config_t timing = TWAI_TIMING_CONFIG_500KBITS();

void setup() {
  Serial.begin(115200);
  delay(300);
  twai_general_config_t general = TWAI_GENERAL_CONFIG_DEFAULT(
      CAN_TX_PIN, CAN_RX_PIN, TWAI_MODE_LISTEN_ONLY);
  general.rx_queue_len = 64;
  general.tx_queue_len = 0;
  twai_filter_config_t filter = TWAI_FILTER_CONFIG_ACCEPT_ALL();
  esp_err_t result = twai_driver_install(&general, &timing, &filter);
  if (result != ESP_OK) {
    Serial.printf("TWAI install failed: %d\\n", result);
    return;
  }
  result = twai_start();
  Serial.printf("TWAI listen-only start: %d\\n", result);
  Serial.println("Format: ID,DLC,HEXDATA");
}
void loop() {
  twai_message_t msg;
  if (twai_receive(&msg, pdMS_TO_TICKS(100)) == ESP_OK) {
    Serial.printf("%08lX,%u,", (unsigned long)msg.identifier, msg.data_length_code);
    for (uint8_t i = 0; i < msg.data_length_code; ++i) Serial.printf("%02X", msg.data[i]);
    Serial.println();
  }
}
