// Optional six-axis head tracker: real MPU6050 samples -> existing Playground HTTP API.
// Not hardware-validated. No automatic motion-mode activation or robot calibration.
#include <WiFi.h>
#include <HTTPClient.h>
#include <Wire.h>
#include <math.h>
#include "config.h"

// MPU6050 register/sensitivity constants: +/-2g and +/-250 degrees/second.
constexpr uint8_t IMU_ADDRESS = 0x68;
constexpr float ACCEL_COUNTS_PER_G = 16384.0f;
constexpr float GYRO_COUNTS_PER_DPS = 131.0f;
constexpr uint32_t SAMPLE_INTERVAL_US = 10000;  // About 100Hz, network may reduce this.
constexpr uint32_t SEND_INTERVAL_MS = 100;  // Maximum 10 HTTP requests/second.
constexpr float FILTER_TAU_SECONDS = 0.5f;  // Gravity correction time constant.
constexpr int CALIBRATION_SAMPLES = 400;  // Four seconds of stationary startup data.

struct Sample {
  float ax, ay, az, gx, gy, gz;
};

// Keep custom-type declarations explicit for Arduino's generated function prototypes.
bool readSample(Sample &sample);
float gravityPitch(const Sample &sample);

float biasX = 0, biasY = 0, biasZ = 0;
float yawDegrees = 0, pitchDegrees = 0;
uint32_t previousSampleUs = 0, previousSendMs = 0;
bool sensorReady = false;

// All I2C reads must complete; partial packets are never used as measurements.
bool readRegisters(uint8_t address, uint8_t *buffer, uint8_t count) {
  Wire.beginTransmission(IMU_ADDRESS);
  Wire.write(address);
  if (Wire.endTransmission(false) != 0) return false;
  if (Wire.requestFrom(IMU_ADDRESS, count, uint8_t(true)) != count) {
    while (Wire.available()) Wire.read();
    return false;
  }
  for (uint8_t i = 0; i < count; ++i) buffer[i] = Wire.read();
  return true;
}

bool writeRegister(uint8_t address, uint8_t value) {
  Wire.beginTransmission(IMU_ADDRESS);
  Wire.write(address);
  Wire.write(value);
  return Wire.endTransmission() == 0;
}

int16_t signedWord(const uint8_t *bytes) {
  return int16_t((uint16_t(bytes[0]) << 8) | bytes[1]);
}

bool readSample(Sample &sample) {
  uint8_t data[14];  // ACCEL_X/Y/Z, temperature (ignored), GYRO_X/Y/Z.
  if (!readRegisters(0x3B, data, sizeof(data))) return false;
  sample = {signedWord(data) / ACCEL_COUNTS_PER_G,
            signedWord(data + 2) / ACCEL_COUNTS_PER_G,
            signedWord(data + 4) / ACCEL_COUNTS_PER_G,
            signedWord(data + 8) / GYRO_COUNTS_PER_DPS,
            signedWord(data + 10) / GYRO_COUNTS_PER_DPS,
            signedWord(data + 12) / GYRO_COUNTS_PER_DPS};
  return true;
}

float gravityPitch(const Sample &sample) {
  return atan2f(-sample.ax, sqrtf(sample.ay * sample.ay + sample.az * sample.az)) * 180.0f / PI;
}

// Refuse startup calibration if the sensor is missing, moving, or not near 1g.
bool initializeAndCalibrate() {
  uint8_t identity;
  if (!readRegisters(0x75, &identity, 1) || identity != 0x68) return false;
  if (!writeRegister(0x6B, 0x01) ||  // Wake, use X-gyro PLL clock.
      !writeRegister(0x1A, 0x03) ||  // DLPF around 44Hz gyro / 42Hz accel.
      !writeRegister(0x19, 0x09) ||  // 1kHz filtered source / (9+1) = 100Hz.
      !writeRegister(0x1B, 0x00) ||  // Gyro +/-250dps.
      !writeRegister(0x1C, 0x00)) return false;  // Accel +/-2g.
  delay(200);
  Serial.println("Keep MPU6050 stationary for four seconds; no robot action is sent.");
  float sumX = 0, sumY = 0, sumZ = 0, sumPitch = 0;
  for (int i = 0; i < CALIBRATION_SAMPLES; ++i) {
    Sample sample;
    if (!readSample(sample)) return false;
    float gravity = sqrtf(sample.ax * sample.ax + sample.ay * sample.ay + sample.az * sample.az);
    if (gravity < .85f || gravity > 1.15f ||
        fabsf(sample.gx) > 5 || fabsf(sample.gy) > 5 || fabsf(sample.gz) > 5) return false;
    sumX += sample.gx;
    sumY += sample.gy;
    sumZ += sample.gz;
    sumPitch += gravityPitch(sample);
    delay(10);
  }
  biasX = sumX / CALIBRATION_SAMPLES;
  biasY = sumY / CALIBRATION_SAMPLES;
  biasZ = sumZ / CALIBRATION_SAMPLES;
  pitchDegrees = sumPitch / CALIBRATION_SAMPLES;
  yawDegrees = 0;  // Relative heading only: six-axis hardware has no absolute yaw reference.
  previousSampleUs = micros();
  return true;
}

// Send only measured/filter-derived values. This never selects mode or calibrates the robot.
void publishPose() {
  if (WiFi.status() != WL_CONNECTED) return;
  char payload[128];
  snprintf(payload, sizeof(payload),
           "{\"action\":\"imu\",\"yaw\":%.2f,\"pitch\":%.2f,\"simulated\":false}",
           yawDegrees * YAW_SIGN, pitchDegrees * PITCH_SIGN);
  WiFiClient client;
  HTTPClient http;
  http.setConnectTimeout(150);
  http.setTimeout(150);
  if (!http.begin(client, String(ROARM_SERVER) + "/api/action")) {
    Serial.println("HTTP begin failed; no packet sent.");
    return;
  }
  http.addHeader("Content-Type", "application/json");
  int code = http.POST(String(payload));
  if (code < 200 || code >= 300) Serial.printf("Pose POST failed: %d\n", code);
  http.end();
}

void setup() {
  Serial.begin(115200);
  Wire.begin(IMU_SDA_PIN, IMU_SCL_PIN);
  Wire.setClock(100000);
  Wire.setTimeOut(50);
  sensorReady = initializeAndCalibrate();
  if (!sensorReady) {
    Serial.println("Sensor/calibration failed. No pose packets. Check wiring, hold still and restart.");
    return;
  }
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.println("Sensor ready. Start IMU mode and set neutral pose in the webpage when ready.");
}

void loop() {
  if (!sensorReady) { delay(100); return; }
  uint32_t nowUs = micros();
  if (uint32_t(nowUs - previousSampleUs) < SAMPLE_INTERVAL_US) { delay(1); return; }
  float dt = uint32_t(nowUs - previousSampleUs) / 1000000.0f;
  previousSampleUs = nowUs;
  Sample sample;
  if (!readSample(sample) || dt > .25f) {
    // A long unobserved interval cannot be repaired with invented gyro readings.
    sensorReady = false;
    Serial.println("I2C failure or >250ms sample gap. Publishing stopped; check network/sensor and restart.");
    return;
  }
  yawDegrees += (sample.gz - biasZ) * dt;
  float alpha = FILTER_TAU_SECONDS / (FILTER_TAU_SECONDS + dt);
  pitchDegrees = alpha * (pitchDegrees + (sample.gy - biasY) * dt)
                 + (1 - alpha) * gravityPitch(sample);
  if (!isfinite(yawDegrees) || !isfinite(pitchDegrees)) {
    sensorReady = false;
    Serial.println("Invalid filter state; publishing stopped.");
    return;
  }
  uint32_t nowMs = millis();
  if (uint32_t(nowMs - previousSendMs) >= SEND_INTERVAL_MS) {
    previousSendMs = nowMs;
    publishPose();
  }
}
