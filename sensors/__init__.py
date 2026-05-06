# sensors/__init__.py
from .simulator import SimulatedSensors
from .fan_interpolator import FanInterpolator

# BME680 import is lazy: only fails on devices without the bme680 library
# installed (e.g. dev workstations). Exposed lazily via _try_bme680_sensors
# rather than top-level so this module always imports cleanly.

def _try_bme680_sensors():
    """Return BME680Sensors class if available, else None."""
    try:
        from .bme680_reader import BME680Sensors
        return BME680Sensors
    except ImportError:
        return None

__all__ = ['SimulatedSensors', 'FanInterpolator', '_try_bme680_sensors']
