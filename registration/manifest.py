# registration/manifest.py
"""
Hardware manifest generation for BeautiFi IoT device registration.
Captures device configuration for on-chain commissioning.
"""

import json
import hashlib
import platform
import subprocess
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from pathlib import Path

from config import (
    DEVICE_ID,
    FIRMWARE_VERSION,
    FAN_SPECS,
    FAN_PWM_PINS,
    SIMULATION_MODE,
)


class HardwareManifest:
    """
    Generates and manages the device hardware manifest.

    The manifest captures:
    - Device identity (ID, public key)
    - Hardware configuration (fans, sensors)
    - Firmware version
    - Calibration data
    """

    MANIFEST_FILE = "hardware_manifest.json"

    def __init__(self, key_dir: Optional[Path] = None):
        """Initialize hardware manifest generator."""
        self.key_dir = key_dir or Path.home() / ".beautifi" / "keys"
        self._manifest: Optional[Dict[str, Any]] = None

    def _get_system_info(self) -> Dict[str, Any]:
        """Get basic system information."""
        info = {
            "platform": platform.system(),
            "platform_release": platform.release(),
            "platform_version": platform.version(),
            "architecture": platform.machine(),
            "processor": platform.processor(),
            "python_version": platform.python_version(),
        }

        # Try to get Raspberry Pi specific info
        try:
            with open("/proc/cpuinfo", "r") as f:
                cpuinfo = f.read()
                for line in cpuinfo.split("\n"):
                    if "Model" in line:
                        info["pi_model"] = line.split(":")[-1].strip()
                    if "Serial" in line:
                        info["pi_serial"] = line.split(":")[-1].strip()
        except (FileNotFoundError, PermissionError):
            pass

        # Try to get hostname
        try:
            info["hostname"] = platform.node()
        except Exception:
            pass

        return info

    def _get_device_identity(self) -> Dict[str, Any]:
        """Get device cryptographic identity."""
        identity_file = self.key_dir / "identity.json"

        if identity_file.exists():
            with open(identity_file, "r") as f:
                return json.load(f)

        return {
            "device_id": DEVICE_ID,
            "public_key": None,
            "key_algorithm": None,
            "created_at": None,
        }

    def _get_sensor_config(self) -> Dict[str, Any]:
        """Get sensor configuration."""
        if SIMULATION_MODE:
            return {
                "mode": "simulation",
                "sensors": {
                    "pressure": {"type": "simulated", "model": "SDP810-500Pa"},
                    "voc": {"type": "simulated", "model": "SGP30"},
                    "power": {"type": "simulated", "model": "INA219"},
                    "temperature": {"type": "simulated", "model": "BME280"},
                    "humidity": {"type": "simulated", "model": "BME280"},
                    "tachometer": {"type": "simulated", "model": "Hall Effect"},
                },
            }
        else:
            # TODO: Detect real sensors via I2C scan
            return {
                "mode": "production",
                "sensors": {
                    "pressure": {"type": "unknown", "i2c_addr": "0x25"},
                    "voc": {"type": "unknown", "i2c_addr": "0x58"},
                    "power": {"type": "unknown", "i2c_addr": "0x40"},
                    "temperature": {"type": "unknown", "i2c_addr": "0x76"},
                    "humidity": {"type": "unknown", "i2c_addr": "0x76"},
                    "tachometer": {"type": "unknown", "gpio": "tach_pin"},
                },
            }

    def _get_fan_config(self) -> Dict[str, Any]:
        """Get fan configuration."""
        return {
            "model": FAN_SPECS.get("model", "Unknown"),
            "count": len(FAN_PWM_PINS),
            "max_cfm": FAN_SPECS.get("max_cfm", 0),
            "max_watts": FAN_SPECS.get("max_watts", 0),
            "max_rpm": FAN_SPECS.get("max_rpm", 0),
            "pwm_pins": FAN_PWM_PINS,
            "duct_size_inches": FAN_SPECS.get("duct_size_inches", 6),
        }

    def generate(self, calibration_data: Optional[Dict] = None) -> Dict[str, Any]:
        """
        Generate the complete hardware manifest.

        Args:
            calibration_data: Optional baseline calibration results

        Returns:
            Complete hardware manifest dict
        """
        identity = self._get_device_identity()

        manifest = {
            "manifest_version": "1.0",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "device": {
                "id": identity.get("device_id", DEVICE_ID),
                "firmware_version": FIRMWARE_VERSION,
                "simulation_mode": SIMULATION_MODE,
            },
            "identity": {
                "public_key": identity.get("public_key"),
                "key_algorithm": identity.get("key_algorithm"),
                "created_at": identity.get("created_at"),
            },
            "hardware": {
                "system": self._get_system_info(),
                "fans": self._get_fan_config(),
                "sensors": self._get_sensor_config(),
            },
        }

        # Add calibration data if provided
        if calibration_data:
            manifest["calibration"] = calibration_data

        # Generate manifest hash
        manifest_json = json.dumps(manifest, sort_keys=True, separators=(',', ':'))
        manifest["manifest_hash"] = hashlib.sha256(manifest_json.encode()).hexdigest()

        self._manifest = manifest
        return manifest

    def save(self, path: Optional[Path] = None) -> Path:
        """Save manifest to file."""
        if self._manifest is None:
            self.generate()

        save_path = path or (self.key_dir / self.MANIFEST_FILE)
        save_path.parent.mkdir(parents=True, exist_ok=True)

        with open(save_path, "w") as f:
            json.dump(self._manifest, f, indent=2)

        print(f"[MANIFEST] Saved to {save_path}")
        return save_path

    def load(self, path: Optional[Path] = None) -> Optional[Dict[str, Any]]:
        """Load manifest from file."""
        load_path = path or (self.key_dir / self.MANIFEST_FILE)

        if not load_path.exists():
            return None

        with open(load_path, "r") as f:
            self._manifest = json.load(f)

        return self._manifest

    def get_registration_payload(self) -> Dict[str, Any]:
        """
        Get payload suitable for backend registration.

        Returns:
            Dict with fields matching backend /api/register expectations
        """
        if self._manifest is None:
            self.generate()

        manifest = self._manifest

        return {
            "device_id": manifest["device"]["id"],
            "public_key": manifest["identity"]["public_key"],
            "firmware_version": manifest["device"]["firmware_version"],
            "unit_model": manifest["hardware"]["fans"]["model"],
            "unit_count": manifest["hardware"]["fans"]["count"],
            "max_cfm": manifest["hardware"]["fans"]["max_cfm"],
            "simulation_mode": manifest["device"]["simulation_mode"],
            "manifest_hash": manifest.get("manifest_hash"),
            "sensors": list(manifest["hardware"]["sensors"]["sensors"].keys()),
        }


# Quick test
if __name__ == "__main__":
    print("Testing HardwareManifest...")
    print("=" * 60)

    manifest_gen = HardwareManifest()
    manifest = manifest_gen.generate()

    print(f"\nDevice ID: {manifest['device']['id']}")
    print(f"Firmware: {manifest['device']['firmware_version']}")
    print(f"Fan Model: {manifest['hardware']['fans']['model']}")
    print(f"Fan Count: {manifest['hardware']['fans']['count']}")
    print(f"Sensors: {list(manifest['hardware']['sensors']['sensors'].keys())}")
    print(f"Manifest Hash: {manifest['manifest_hash'][:32]}...")

    print("\nRegistration Payload:")
    payload = manifest_gen.get_registration_payload()
    for k, v in payload.items():
        print(f"  {k}: {v}")
