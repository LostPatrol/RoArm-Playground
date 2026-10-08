// Optional ESP32/MPU6050 reference: copy to local config.h; never commit credentials.
#pragma once

constexpr char WIFI_SSID[] = "<YOUR_WIFI_SSID>";
constexpr char WIFI_PASSWORD[] = "<YOUR_WIFI_PASSWORD>";
constexpr char ROARM_SERVER[] = "http://<RK_HOST>:<PORT>";  // No trailing slash.
constexpr int IMU_SDA_PIN = 21;  // Classic ESP32 example; match the actual board.
constexpr int IMU_SCL_PIN = 22;
constexpr float YAW_SIGN = 1.0f;  // Adjust signs after confirming the mounting axes.
constexpr float PITCH_SIGN = 1.0f;
