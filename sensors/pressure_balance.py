# sensors/pressure_balance.py
"""
Building pressure balance detection using BME680 barometric pressure.

Compares indoor barometric pressure during fan-on vs fan-off periods.
If exhaust fans create negative pressure (insufficient makeup air),
the BME680 will read lower during fan-on periods. The delta between
fan-on and fan-off averages indicates whether the building ventilation
is balanced.

No external data (weather API) needed — the sensor compares against
itself across natural fan on/off cycles (business hours vs after hours).
"""

import time
from collections import deque
from datetime import datetime


class PressureBalanceTracker:
    """
    Tracks barometric pressure across fan state transitions to detect
    building ventilation imbalance.

    Uses transition-based detection: when the fan switches on or off,
    compares average pressure before and after the transition. Weather
    changes are slow (hours) while fan effects are fast (seconds), so
    an immediate pressure shift at a fan transition is the fan's doing.
    """

    # Minimum readings needed before/after a transition to compute a delta
    MIN_WINDOW_SAMPLES = 30  # ~6 minutes at 12s intervals

    # How many readings to keep in each rolling window
    WINDOW_SIZE = 150  # ~30 minutes at 12s intervals

    # How many transition deltas to accumulate for a verdict
    MIN_TRANSITIONS = 3

    # Max transitions to keep (rolling)
    MAX_TRANSITIONS = 50

    # Pressure delta threshold (Pa) — below this = imbalanced
    IMBALANCE_THRESHOLD_PA = -2.0

    def __init__(self):
        # Rolling pressure windows for current fan state
        self._fan_on_pressures = deque(maxlen=self.WINDOW_SIZE)
        self._fan_off_pressures = deque(maxlen=self.WINDOW_SIZE)

        # Current fan state tracking
        self._current_fan_on = None  # None = unknown
        self._state_start_time = None

        # Transition deltas: (timestamp, avg_before, avg_after, delta_pa)
        self._transition_deltas = deque(maxlen=self.MAX_TRANSITIONS)

        # Persistence: rolling averages for current session
        self._total_fan_on_readings = 0
        self._total_fan_off_readings = 0

    def update(self, pressure_hpa, fan_is_on, timestamp=None):
        """
        Feed a new pressure reading with current fan state.

        Args:
            pressure_hpa: Barometric pressure in hPa from BME680
            fan_is_on: True if fan PWM > 0, False if fan is off
            timestamp: Optional ISO timestamp string (defaults to now)
        """
        if pressure_hpa is None or pressure_hpa < 800 or pressure_hpa > 1100:
            return  # Skip invalid readings

        ts = timestamp or datetime.utcnow().isoformat() + "Z"
        pressure_pa = pressure_hpa * 100  # Convert hPa to Pa for finer resolution

        # Detect state transitions
        if self._current_fan_on is not None and fan_is_on != self._current_fan_on:
            self._handle_transition(fan_is_on, ts)

        # Update current state
        self._current_fan_on = fan_is_on
        if self._state_start_time is None:
            self._state_start_time = ts

        # Add to appropriate window
        if fan_is_on:
            self._fan_on_pressures.append(pressure_pa)
            self._total_fan_on_readings += 1
        else:
            self._fan_off_pressures.append(pressure_pa)
            self._total_fan_off_readings += 1

    def _handle_transition(self, new_fan_on, timestamp):
        """
        Handle a fan state transition. Compare pressure before and after.

        When fan goes OFF→ON: the "before" window is fan_off_pressures
        When fan goes ON→OFF: the "before" window is fan_on_pressures
        """
        if new_fan_on:
            # Fan just turned ON — "before" is the off window
            before_window = self._fan_off_pressures
            label = "off_to_on"
        else:
            # Fan just turned OFF — "before" is the on window
            before_window = self._fan_on_pressures
            label = "on_to_off"

        # Need enough readings in the "before" window
        if len(before_window) < self.MIN_WINDOW_SAMPLES:
            return

        avg_before = sum(before_window) / len(before_window)

        # Store transition for later comparison
        # We'll compute the "after" average when we have enough samples
        self._transition_deltas.append({
            "timestamp": timestamp,
            "type": label,
            "avg_before_pa": avg_before,
            "avg_after_pa": None,  # Filled in later
            "delta_pa": None,
            "before_samples": len(before_window),
            "after_samples": 0,
        })

    def _update_pending_transitions(self):
        """
        Check if any pending transitions now have enough 'after' data.
        """
        for t in self._transition_deltas:
            if t["delta_pa"] is not None:
                continue  # Already computed

            # Determine which window is the "after" window
            if t["type"] == "off_to_on":
                after_window = self._fan_on_pressures
            else:
                after_window = self._fan_off_pressures

            if len(after_window) >= self.MIN_WINDOW_SAMPLES:
                avg_after = sum(after_window) / len(after_window)
                t["avg_after_pa"] = avg_after
                t["after_samples"] = len(after_window)

                if t["type"] == "off_to_on":
                    # Fan turned on: delta = on_pressure - off_pressure
                    # Negative = fan creates negative pressure = imbalanced
                    t["delta_pa"] = avg_after - t["avg_before_pa"]
                else:
                    # Fan turned off: delta = off_pressure - on_pressure
                    # Positive = pressure recovers when fan stops = imbalanced
                    t["delta_pa"] = avg_after - t["avg_before_pa"]

    def get_status(self):
        """
        Get the current pressure balance verdict.

        Returns:
            dict with status, delta, confidence, and debug info
        """
        self._update_pending_transitions()

        # Collect completed transition deltas
        completed = [t for t in self._transition_deltas if t["delta_pa"] is not None]

        # Also compute simple rolling average comparison
        simple_delta_pa = None
        if (len(self._fan_on_pressures) >= self.MIN_WINDOW_SAMPLES and
                len(self._fan_off_pressures) >= self.MIN_WINDOW_SAMPLES):
            avg_on = sum(self._fan_on_pressures) / len(self._fan_on_pressures)
            avg_off = sum(self._fan_off_pressures) / len(self._fan_off_pressures)
            simple_delta_pa = round(avg_on - avg_off, 1)

        # Determine verdict
        if len(completed) >= self.MIN_TRANSITIONS:
            # Use transition-based analysis
            # For off_to_on transitions: negative delta = fan creates negative pressure
            on_transitions = [t["delta_pa"] for t in completed if t["type"] == "off_to_on"]
            # For on_to_off transitions: positive delta = pressure recovers
            off_transitions = [t["delta_pa"] for t in completed if t["type"] == "on_to_off"]

            all_deltas = []
            # off_to_on: negative = imbalanced
            all_deltas.extend(on_transitions)
            # on_to_off: positive recovery means negative during on, so negate
            all_deltas.extend([-d for d in off_transitions])

            if all_deltas:
                avg_delta = sum(all_deltas) / len(all_deltas)
                confidence = min(1.0, len(completed) / 10.0)

                if avg_delta < self.IMBALANCE_THRESHOLD_PA:
                    status = "imbalanced"
                else:
                    status = "balanced"
            else:
                status = "insufficient_data"
                avg_delta = 0
                confidence = 0
        elif simple_delta_pa is not None:
            # Fallback: use simple rolling averages (less confident)
            avg_delta = simple_delta_pa
            confidence = 0.3  # Low confidence without transition data
            if simple_delta_pa < self.IMBALANCE_THRESHOLD_PA:
                status = "imbalanced"
            else:
                status = "balanced"
        else:
            status = "insufficient_data"
            avg_delta = 0
            confidence = 0

        return {
            "status": status,
            "delta_pa": round(avg_delta, 1),
            "confidence": round(confidence, 2),
            "fan_on_samples": self._total_fan_on_readings,
            "fan_off_samples": self._total_fan_off_readings,
            "transitions_completed": len(completed),
            "simple_delta_pa": simple_delta_pa,
        }


# Quick test
if __name__ == "__main__":
    import random

    tracker = PressureBalanceTracker()
    base_pressure = 1006.0  # hPa

    print("Simulating pressure balance detection")
    print("=" * 60)

    # Simulate 10 min fan off (baseline)
    print("\n--- Fan OFF (10 min) ---")
    for i in range(50):
        p = base_pressure + random.gauss(0, 0.02)
        tracker.update(p, fan_is_on=False)

    # Simulate fan turning on (with 0.03 hPa = 3 Pa drop for imbalanced building)
    print("--- Fan ON (10 min, -3 Pa shift) ---")
    for i in range(50):
        p = base_pressure - 0.03 + random.gauss(0, 0.02)
        tracker.update(p, fan_is_on=True)

    # Check status
    status = tracker.get_status()
    print(f"\nResult: {status}")
