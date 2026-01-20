# config.py - BeautiFi IoT Configuration

# ============================================
# OPERATION MODE
# ============================================
# Set to True for testing with simulated sensors
# Set to False when real hardware is connected
SIMULATION_MODE = True

# ============================================
# DEVICE IDENTITY
# ============================================
DEVICE_ID = "btfi-iot-001"
SITE_ID = "site-test-001"
FIRMWARE_VERSION = "0.2.0"

# ============================================
# FAN SPECIFICATIONS (AC Infinity Cloudline S6)
# ============================================
FAN_SPECS = {
    "model": "AC Infinity Cloudline S6",
    "duct_size_inches": 6,
    "max_cfm": 402,
    "max_watts": 70,
    "avg_watts": 38,
    "max_rpm": 2500,  # Estimated for EC motor
    "noise_dba": 32,
    "static_pressure_pa": 503,
    "speed_levels": 10,
    "bearing_type": "Dual Ball",
    "voltage": "100-240V AC",
}

# CFM curve (estimated for 10-speed EC motor)
# Speed level -> percentage of max CFM
# EC motors have good low-speed efficiency
FAN_CFM_CURVE = {
    0: 0.0,
    10: 0.15,   # Speed 1 = 15% = ~60 CFM
    20: 0.28,   # Speed 2 = 28% = ~112 CFM
    30: 0.40,   # Speed 3 = 40% = ~161 CFM
    40: 0.52,   # Speed 4 = 52% = ~209 CFM
    50: 0.62,   # Speed 5 = 62% = ~249 CFM
    60: 0.72,   # Speed 6 = 72% = ~289 CFM
    70: 0.81,   # Speed 7 = 81% = ~325 CFM
    80: 0.89,   # Speed 8 = 89% = ~358 CFM
    90: 0.95,   # Speed 9 = 95% = ~382 CFM
    100: 1.0,   # Speed 10 = 100% = 402 CFM
}

# Power curve (watts scale roughly with cube of airflow for fans)
# But EC motors are more efficient at partial load
FAN_POWER_CURVE = {
    0: 0.0,
    10: 0.08,   # ~5.6W
    20: 0.15,   # ~10.5W
    30: 0.22,   # ~15.4W
    40: 0.30,   # ~21W
    50: 0.40,   # ~28W
    60: 0.52,   # ~36W
    70: 0.65,   # ~45W
    80: 0.78,   # ~55W
    90: 0.90,   # ~63W
    100: 1.0,   # 70W
}

# RPM curve (roughly linear with PWM for EC motors)
FAN_RPM_CURVE = {
    0: 0.0,
    10: 0.20,
    20: 0.30,
    30: 0.40,
    40: 0.50,
    50: 0.60,
    60: 0.70,
    70: 0.80,
    80: 0.88,
    90: 0.94,
    100: 1.0,
}

# ============================================
# TELEMETRY SETTINGS
# ============================================
SAMPLE_INTERVAL_SECONDS = 12
EPOCH_DURATION_MINUTES = 60
TELEMETRY_BUFFER_SIZE = 1000  # Max samples to buffer locally

# ============================================
# SIMULATION SETTINGS
# ============================================
SIMULATION = {
    # Baseline VOC (ppb) - typical indoor air
    "voc_baseline_ppb": 150,
    "voc_noise_ppb": 30,
    "voc_spike_probability": 0.05,  # 5% chance of spike per sample
    "voc_spike_magnitude": 500,     # ppb added during spike

    # Temperature
    "temp_baseline_c": 24.0,
    "temp_noise_c": 0.5,
    "temp_drift_rate": 0.01,  # degrees per sample

    # Humidity
    "humidity_baseline_pct": 50.0,
    "humidity_noise_pct": 2.0,

    # CO2 (ppm)
    "co2_baseline_ppm": 450,
    "co2_noise_ppm": 25,

    # Pressure differential (derived from CFM)
    "pressure_coefficient": 0.5,  # Pa per CFM (simplified)
}

# ============================================
# NETWORK SETTINGS
# ============================================
VERIFIER_URL = "http://localhost:8000"  # Backend verifier endpoint
API_TIMEOUT_SECONDS = 10

# ============================================
# GPIO PIN MAPPING
# ============================================
FAN_PWM_PINS = {
    "Fan 1": 18,
    "Fan 2": 13,
    "Fan 3": 19,
}
PWM_FREQUENCY = 100  # Hz
