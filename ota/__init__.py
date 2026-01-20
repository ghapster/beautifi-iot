# ota/__init__.py
"""
OTA (Over-The-Air) Update module for BeautiFi IoT.
Handles secure firmware updates and remote configuration.
"""

from .update_manager import UpdateManager, UpdateStatus, FirmwareManifest
from .config_manager import ConfigManager

__all__ = [
    "UpdateManager",
    "UpdateStatus",
    "FirmwareManifest",
    "ConfigManager",
]
