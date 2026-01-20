# sensors/fan_interpolator.py
"""
Fan performance interpolation based on AC Infinity Cloudline S6 specs.
Converts PWM duty cycle (0-100%) to CFM, RPM, and Watts.
"""

from config import FAN_SPECS, FAN_CFM_CURVE, FAN_POWER_CURVE, FAN_RPM_CURVE


class FanInterpolator:
    """Interpolates fan performance metrics from PWM duty cycle."""

    def __init__(self, fan_specs=None):
        self.specs = fan_specs or FAN_SPECS
        self.cfm_curve = FAN_CFM_CURVE
        self.power_curve = FAN_POWER_CURVE
        self.rpm_curve = FAN_RPM_CURVE

    def _interpolate(self, curve: dict, pwm_percent: float) -> float:
        """
        Linear interpolation between curve points.

        Args:
            curve: Dict mapping PWM % -> multiplier (0.0 to 1.0)
            pwm_percent: Current PWM duty cycle (0-100)

        Returns:
            Interpolated multiplier
        """
        pwm = max(0, min(100, pwm_percent))

        # Find surrounding points
        points = sorted(curve.keys())

        if pwm in curve:
            return curve[pwm]

        # Find lower and upper bounds
        lower = max([p for p in points if p <= pwm], default=0)
        upper = min([p for p in points if p >= pwm], default=100)

        if lower == upper:
            return curve[lower]

        # Linear interpolation
        lower_val = curve[lower]
        upper_val = curve[upper]
        ratio = (pwm - lower) / (upper - lower)

        return lower_val + (upper_val - lower_val) * ratio

    def get_cfm(self, pwm_percent: float) -> float:
        """
        Get estimated CFM for given PWM duty cycle.

        Args:
            pwm_percent: PWM duty cycle (0-100)

        Returns:
            Estimated CFM
        """
        multiplier = self._interpolate(self.cfm_curve, pwm_percent)
        return round(self.specs["max_cfm"] * multiplier, 1)

    def get_rpm(self, pwm_percent: float) -> int:
        """
        Get estimated RPM for given PWM duty cycle.

        Args:
            pwm_percent: PWM duty cycle (0-100)

        Returns:
            Estimated RPM
        """
        multiplier = self._interpolate(self.rpm_curve, pwm_percent)
        return int(self.specs["max_rpm"] * multiplier)

    def get_watts(self, pwm_percent: float) -> float:
        """
        Get estimated power consumption for given PWM duty cycle.

        Args:
            pwm_percent: PWM duty cycle (0-100)

        Returns:
            Estimated watts
        """
        multiplier = self._interpolate(self.power_curve, pwm_percent)
        return round(self.specs["max_watts"] * multiplier, 1)

    def get_all_metrics(self, pwm_percent: float) -> dict:
        """
        Get all interpolated fan metrics.

        Args:
            pwm_percent: PWM duty cycle (0-100)

        Returns:
            Dict with cfm, rpm, watts, and efficiency
        """
        cfm = self.get_cfm(pwm_percent)
        watts = self.get_watts(pwm_percent)
        rpm = self.get_rpm(pwm_percent)

        # Calculate efficiency (CFM per Watt)
        efficiency = round(cfm / watts, 2) if watts > 0 else 0

        return {
            "pwm_percent": pwm_percent,
            "cfm": cfm,
            "rpm": rpm,
            "watts": watts,
            "efficiency_cfm_w": efficiency,
        }

    def get_speed_table(self) -> list:
        """
        Generate a full speed table for reference.

        Returns:
            List of dicts with metrics at each 10% increment
        """
        return [self.get_all_metrics(pwm) for pwm in range(0, 101, 10)]


# Quick test
if __name__ == "__main__":
    fan = FanInterpolator()

    print("AC Infinity Cloudline S6 - Performance Table")
    print("=" * 60)
    print(f"{'PWM %':<8} {'CFM':<8} {'RPM':<8} {'Watts':<8} {'CFM/W':<8}")
    print("-" * 60)

    for row in fan.get_speed_table():
        print(f"{row['pwm_percent']:<8} {row['cfm']:<8} {row['rpm']:<8} {row['watts']:<8} {row['efficiency_cfm_w']:<8}")
