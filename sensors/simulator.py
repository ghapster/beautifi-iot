# sensors/simulator.py
"""
Simulated sensor readings for testing the BeautiFi IoT pipeline.
Generates realistic mock data for VOC, temperature, humidity, CO2, etc.
"""

import random
import math
import time
from datetime import datetime
from typing import Optional

from config import SIMULATION, FAN_SPECS
from .fan_interpolator import FanInterpolator


class SimulatedSensors:
    """
    Generates realistic simulated sensor data for testing.

    Simulates:
    - VOC levels with baseline, noise, and occasional spikes
    - Temperature with slow drift
    - Humidity
    - CO2 levels
    - Pressure differential (derived from CFM)

    The simulation includes realistic patterns:
    - VOC spikes when "work" is being done (nail polish, hair dye, etc.)
    - Temperature drift based on HVAC cycles
    - Correlated readings (higher fan speed -> lower VOC over time)
    """

    def __init__(self, fan_interpolator: Optional[FanInterpolator] = None):
        self.fan = fan_interpolator or FanInterpolator()
        self.config = SIMULATION

        # State tracking for realistic simulation
        self._start_time = time.time()
        self._voc_level = self.config["voc_baseline_ppb"]
        self._temp = self.config["temp_baseline_c"]
        self._humidity = self.config["humidity_baseline_pct"]
        self._co2 = self.config["co2_baseline_ppm"]
        self._in_spike = False
        self._spike_duration = 0

    def _add_noise(self, value: float, noise_range: float) -> float:
        """Add Gaussian noise to a value."""
        return value + random.gauss(0, noise_range / 2)

    def _simulate_voc(self, fan_cfm: float) -> float:
        """
        Simulate VOC readings.

        - Higher CFM = faster VOC reduction
        - Random spikes simulate work activities (nail polish, dye, etc.)
        - Gradual return to baseline
        """
        # Check for new spike
        if not self._in_spike and random.random() < self.config["voc_spike_probability"]:
            self._in_spike = True
            self._spike_duration = random.randint(3, 10)  # 3-10 samples
            self._voc_level += self.config["voc_spike_magnitude"] * random.uniform(0.5, 1.5)

        # Decay spike
        if self._in_spike:
            self._spike_duration -= 1
            if self._spike_duration <= 0:
                self._in_spike = False

        # VOC reduction based on ventilation (CFM)
        # Higher CFM = faster reduction toward baseline
        if fan_cfm > 0:
            reduction_rate = 0.02 * (fan_cfm / FAN_SPECS["max_cfm"])
            self._voc_level -= (self._voc_level - self.config["voc_baseline_ppb"]) * reduction_rate

        # Natural drift toward baseline (even without ventilation, but slower)
        self._voc_level -= (self._voc_level - self.config["voc_baseline_ppb"]) * 0.005

        # Add noise and ensure non-negative
        voc = self._add_noise(self._voc_level, self.config["voc_noise_ppb"])
        return max(0, round(voc, 1))

    def _simulate_temperature(self) -> float:
        """
        Simulate temperature with slow sinusoidal drift (HVAC cycles).
        """
        elapsed = time.time() - self._start_time
        # Slow sine wave for HVAC cycle (~15 min period)
        cycle = math.sin(elapsed / 900 * 2 * math.pi) * 1.5
        temp = self.config["temp_baseline_c"] + cycle
        temp = self._add_noise(temp, self.config["temp_noise_c"])
        return round(temp, 1)

    def _simulate_humidity(self) -> float:
        """Simulate humidity with noise."""
        humidity = self._add_noise(
            self.config["humidity_baseline_pct"],
            self.config["humidity_noise_pct"]
        )
        return round(max(0, min(100, humidity)), 1)

    def _simulate_co2(self, fan_cfm: float) -> float:
        """
        Simulate CO2 levels.
        Higher ventilation = lower CO2.
        """
        # CO2 increases slowly (occupancy), decreases with ventilation
        if fan_cfm > 0:
            target = self.config["co2_baseline_ppm"] - (fan_cfm / FAN_SPECS["max_cfm"]) * 50
        else:
            target = self.config["co2_baseline_ppm"] + 100  # Rises without ventilation

        self._co2 += (target - self._co2) * 0.05
        co2 = self._add_noise(self._co2, self.config["co2_noise_ppm"])
        return round(max(350, co2), 0)  # CO2 won't go below ~350 ppm outdoors

    def _simulate_pressure(self, fan_cfm: float) -> float:
        """
        Simulate differential pressure based on CFM.
        Simplified: ΔP roughly proportional to CFM squared for duct flow.
        """
        if fan_cfm <= 0:
            return 0.0

        # Simplified ΔP model (actual would depend on duct geometry)
        # At max CFM (402), assume ~50 Pa differential
        max_dp = 50
        dp = max_dp * (fan_cfm / FAN_SPECS["max_cfm"]) ** 2
        dp = self._add_noise(dp, 2)
        return round(max(0, dp), 1)

    def read_all(self, current_pwm: float) -> dict:
        """
        Get all simulated sensor readings.

        Args:
            current_pwm: Current fan PWM duty cycle (0-100)

        Returns:
            Dict with all sensor readings and derived metrics
        """
        # Get fan metrics from interpolator
        fan_metrics = self.fan.get_all_metrics(current_pwm)
        cfm = fan_metrics["cfm"]

        # Generate simulated environmental readings
        voc = self._simulate_voc(cfm)
        temp = self._simulate_temperature()
        humidity = self._simulate_humidity()
        co2 = self._simulate_co2(cfm)
        delta_p = self._simulate_pressure(cfm)

        # Calculate VOC reduction (compared to no-ventilation baseline)
        voc_reduction_pct = 0
        if cfm > 0 and self._voc_level < self.config["voc_baseline_ppb"] + self.config["voc_spike_magnitude"]:
            potential_max = self.config["voc_baseline_ppb"] + self.config["voc_spike_magnitude"]
            voc_reduction_pct = round((potential_max - voc) / potential_max * 100, 1)

        return {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "device_id": "btfi-iot-001",  # From config
            "simulation_mode": True,

            # Fan metrics (interpolated from known specs)
            "fan": {
                "pwm_percent": current_pwm,
                "cfm": cfm,
                "rpm": fan_metrics["rpm"],
                "watts": fan_metrics["watts"],
                "efficiency_cfm_w": fan_metrics["efficiency_cfm_w"],
            },

            # Environmental readings (simulated)
            "environment": {
                "voc_ppb": voc,
                "co2_ppm": co2,
                "temperature_c": temp,
                "humidity_pct": humidity,
                "delta_p_pa": delta_p,
            },

            # Derived metrics
            "derived": {
                "tar_cfm_min": cfm,  # TAR for this 1-minute sample
                "voc_reduction_pct": max(0, voc_reduction_pct),
                "energy_wh": round(fan_metrics["watts"] / 60, 3),  # Wh for 1 minute
            },

            # Simulation state (for debugging)
            "_sim_state": {
                "in_spike": self._in_spike,
                "internal_voc": round(self._voc_level, 1),
            }
        }


# Quick test
if __name__ == "__main__":
    sim = SimulatedSensors()

    print("Simulated Sensor Readings (10 samples at 50% PWM)")
    print("=" * 70)

    for i in range(10):
        reading = sim.read_all(current_pwm=50)
        print(f"Sample {i+1}:")
        print(f"  Fan: {reading['fan']['cfm']} CFM, {reading['fan']['watts']}W")
        print(f"  VOC: {reading['environment']['voc_ppb']} ppb, CO2: {reading['environment']['co2_ppm']} ppm")
        print(f"  Temp: {reading['environment']['temperature_c']}°C, Humidity: {reading['environment']['humidity_pct']}%")
        print(f"  ΔP: {reading['environment']['delta_p_pa']} Pa")
        print()
        time.sleep(0.5)
