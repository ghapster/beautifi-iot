# sensors/bme680_reader.py
"""
Real BME680 sensor reader for BeautiFi IoT.
Drop-in replacement for SimulatedSensors — same read_all() interface.

The BME680 provides: temperature, humidity, barometric pressure, gas resistance.
Gas resistance is converted to approximate VOC ppb.
CO2 and PM2.5 are estimated (BME680 does not measure these directly).
"""

import time
import math
from datetime import datetime
from typing import Optional

import bme680

from config import FAN_SPECS, DEVICE_ID
from .fan_interpolator import FanInterpolator


class BME680Sensors:
    """
    Reads real environmental data from a Waveshare BME680 sensor over I2C.

    Provides the same read_all(current_pwm) interface as SimulatedSensors
    so it can be used as a drop-in replacement in telemetry/collector.py.
    """

    # Gas resistance baseline for VOC ppb estimation.
    # ~50k ohms in clean air is typical for BME680 after burn-in.
    # This will be calibrated over time using a rolling average.
    GAS_BASELINE_OHMS = 50000
    GAS_BASELINE_SAMPLES = 300  # ~1 hour at 12s intervals

    def __init__(self, fan_interpolator: Optional[FanInterpolator] = None):
        self.fan = fan_interpolator or FanInterpolator()

        # Initialize BME680 at address 0x77
        self.sensor = bme680.BME680(bme680.I2C_ADDR_SECONDARY)

        # Configure oversampling and filter
        self.sensor.set_humidity_oversample(bme680.OS_2X)
        self.sensor.set_pressure_oversample(bme680.OS_4X)
        self.sensor.set_temperature_oversample(bme680.OS_8X)
        self.sensor.set_filter(bme680.FILTER_SIZE_3)

        # Configure gas heater: 320C for 150ms
        self.sensor.set_gas_status(bme680.ENABLE_GAS_MEAS)
        self.sensor.set_gas_heater_temperature(320)
        self.sensor.set_gas_heater_duration(150)
        self.sensor.select_gas_heater_profile(0)

        # Rolling baseline for gas resistance (for VOC estimation)
        self._gas_readings = []
        self._gas_baseline = self.GAS_BASELINE_OHMS

        # Track last known good readings for fallback
        self._last_temp = 22.0
        self._last_humidity = 50.0
        self._last_pressure = 1013.25
        self._last_gas_resistance = self.GAS_BASELINE_OHMS

        print("[BME680] Initialized at I2C address 0x77")

    def _update_gas_baseline(self, gas_resistance: float):
        """Update rolling gas resistance baseline for VOC estimation."""
        self._gas_readings.append(gas_resistance)
        if len(self._gas_readings) > self.GAS_BASELINE_SAMPLES:
            self._gas_readings.pop(0)

        # Use 75th percentile as baseline (clean air readings tend to be higher)
        if len(self._gas_readings) >= 10:
            sorted_readings = sorted(self._gas_readings)
            idx = int(len(sorted_readings) * 0.75)
            self._gas_baseline = sorted_readings[idx]

    def _gas_to_voc_ppb(self, gas_resistance: float) -> float:
        """
        Convert BME680 gas resistance (ohms) to approximate VOC ppb.

        Lower resistance = more VOCs present.
        This is an approximation — the BME680 gives a relative indicator,
        not a calibrated ppb reading. We use the rolling baseline for
        relative comparison.
        """
        if gas_resistance <= 0 or self._gas_baseline <= 0:
            return 150.0  # fallback

        # Ratio: 1.0 = at baseline (clean), <1.0 = worse air
        ratio = gas_resistance / self._gas_baseline

        # Map ratio to approximate ppb
        # ratio 1.0 = ~50 ppb (clean indoor air)
        # ratio 0.5 = ~300 ppb (moderate)
        # ratio 0.2 = ~800 ppb (high)
        if ratio >= 1.0:
            voc_ppb = max(10, 50 * (2.0 - ratio))
        else:
            voc_ppb = 50 + (1.0 - ratio) * 500

        return round(max(0, voc_ppb), 1)

    def _estimate_co2(self, voc_ppb: float) -> float:
        """Estimate CO2 from VOC (BME680 doesn't measure CO2 directly)."""
        # Indoor CO2 typically 400-1000 ppm
        # Rough correlation: higher VOC activity = higher CO2
        co2 = 400 + (voc_ppb / 500) * 200
        return round(max(350, min(2000, co2)), 0)

    def _estimate_pm25(self, voc_ppb: float) -> float:
        """Estimate PM2.5 from VOC (BME680 doesn't measure PM directly)."""
        # Indoor PM2.5 typically 5-25 ug/m3
        pm25 = 8 + (voc_ppb / 500) * 10
        return round(max(0, min(100, pm25)), 1)

    def _calculate_delta_p(self, fan_cfm: float) -> float:
        """Calculate differential pressure from CFM (same as simulator)."""
        if fan_cfm <= 0:
            return 0.0
        max_dp = 50
        dp = max_dp * (fan_cfm / FAN_SPECS["max_cfm"]) ** 2
        return round(max(0, dp), 1)

    def read_all(self, current_pwm: float) -> dict:
        """
        Read all sensor data from BME680 + fan interpolation.

        Args:
            current_pwm: Current fan PWM duty cycle (0-100)

        Returns:
            Dict matching SimulatedSensors.read_all() structure exactly.
        """
        # Get fan metrics from interpolator
        fan_metrics = self.fan.get_all_metrics(current_pwm)
        cfm = fan_metrics["cfm"]

        # Read BME680
        temp = self._last_temp
        humidity = self._last_humidity
        pressure_hpa = self._last_pressure
        gas_resistance = self._last_gas_resistance
        heat_stable = False

        try:
            if self.sensor.get_sensor_data():
                temp = round(self.sensor.data.temperature, 1)
                humidity = round(self.sensor.data.humidity, 1)
                pressure_hpa = round(self.sensor.data.pressure, 1)
                self._last_temp = temp
                self._last_humidity = humidity
                self._last_pressure = pressure_hpa

                if self.sensor.data.heat_stable:
                    gas_resistance = self.sensor.data.gas_resistance
                    self._last_gas_resistance = gas_resistance
                    self._update_gas_baseline(gas_resistance)
                    heat_stable = True
        except Exception as e:
            print(f"[BME680] Read error: {e}")

        # Derive VOC, CO2, PM2.5
        voc_ppb = self._gas_to_voc_ppb(gas_resistance)
        co2_ppm = self._estimate_co2(voc_ppb)
        pm25 = self._estimate_pm25(voc_ppb)
        delta_p = self._calculate_delta_p(cfm)

        # VOC reduction estimate
        voc_reduction_pct = 0
        if cfm > 0 and voc_ppb < 5000:
            voc_reduction_pct = round((5000 - voc_ppb) / 5000 * 100, 1)

        return {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "device_id": DEVICE_ID,
            "simulation_mode": False,

            # Fan metrics (interpolated from known specs)
            "fan": {
                "pwm_percent": current_pwm,
                "cfm": cfm,
                "rpm": fan_metrics["rpm"],
                "watts": fan_metrics["watts"],
                "power_w": fan_metrics["watts"],
                "efficiency_cfm_w": fan_metrics["efficiency_cfm_w"],
            },

            # Environmental readings (REAL from BME680)
            "environment": {
                "voc_ppb": voc_ppb,
                "tvoc_ppb": voc_ppb,
                "co2_ppm": co2_ppm,
                "eco2_ppm": co2_ppm,
                "pm25_ugm3": pm25,
                "temperature_c": temp,
                "temp_c": temp,
                "humidity_pct": humidity,
                "delta_p_pa": delta_p,
                "dp_pa": delta_p,
            },

            # Derived metrics
            "derived": {
                "tar_cfm_min": cfm,
                "voc_reduction_pct": max(0, voc_reduction_pct),
                "energy_wh": round(fan_metrics["watts"] / 60, 3),
            },

            # Sensor debug info
            "_sensor_state": {
                "gas_resistance_ohms": round(gas_resistance, 0),
                "gas_baseline_ohms": round(self._gas_baseline, 0),
                "heat_stable": heat_stable,
                "pressure_hpa": pressure_hpa,
                "baseline_samples": len(self._gas_readings),
            }
        }


# Quick test
if __name__ == "__main__":
    reader = BME680Sensors()

    print("BME680 Live Readings (5 samples at 0% PWM)")
    print("=" * 60)

    for i in range(5):
        reading = reader.read_all(current_pwm=0)
        env = reading["environment"]
        state = reading["_sensor_state"]
        print(f"Sample {i+1}:")
        print(f"  Temp: {env['temperature_c']}C, Humidity: {env['humidity_pct']}%")
        print(f"  VOC: {env['voc_ppb']} ppb (gas: {state['gas_resistance_ohms']} ohms)")
        print(f"  Pressure: {state['pressure_hpa']} hPa")
        print(f"  Heat stable: {state['heat_stable']}")
        print()
        time.sleep(3)
