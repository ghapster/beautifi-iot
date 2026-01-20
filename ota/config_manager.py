# ota/config_manager.py
"""
Remote configuration manager for BeautiFi IoT devices.
Handles dynamic configuration updates without full firmware updates.
"""

import json
import hashlib
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Dict, Any, Tuple, List
from dataclasses import dataclass, field

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.exceptions import InvalidSignature


@dataclass
class ConfigChange:
    """Record of a configuration change."""
    key: str
    old_value: Any
    new_value: Any
    changed_at: str
    source: str  # "local", "remote", "api"

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "changed_at": self.changed_at,
            "source": self.source,
        }


class ConfigManager:
    """
    Manages device configuration with support for remote updates.

    Features:
    - Load/save configuration from JSON file
    - Apply remote configuration updates
    - Validate configuration values
    - Track configuration change history
    - Support for signed configuration updates
    """

    CONFIG_FILE = "device_config.json"
    HISTORY_FILE = "config_history.json"

    # Configurable fields and their validation rules
    ALLOWED_FIELDS = {
        # Telemetry settings
        "sample_interval_seconds": {"type": int, "min": 5, "max": 300, "default": 12},
        "epoch_duration_minutes": {"type": int, "min": 15, "max": 1440, "default": 60},

        # Network settings
        "verifier_url": {"type": str, "default": "http://localhost:8000"},
        "sync_interval_seconds": {"type": int, "min": 10, "max": 600, "default": 30},
        "enable_verifier_sync": {"type": bool, "default": True},

        # Fan settings
        "default_fan_speed": {"type": int, "min": 0, "max": 100, "default": 0},
        "max_fan_speed": {"type": int, "min": 0, "max": 100, "default": 100},

        # Simulation
        "simulation_mode": {"type": bool, "default": True},

        # VOC thresholds
        "voc_alert_threshold_ppb": {"type": int, "min": 100, "max": 10000, "default": 500},
        "voc_critical_threshold_ppb": {"type": int, "min": 500, "max": 50000, "default": 2000},

        # Security
        "anomaly_sigma_threshold": {"type": float, "min": 2.0, "max": 5.0, "default": 3.0},
        "enable_anomaly_detection": {"type": bool, "default": True},

        # Logging
        "log_level": {"type": str, "allowed": ["DEBUG", "INFO", "WARNING", "ERROR"], "default": "INFO"},
    }

    def __init__(
        self,
        config_dir: Optional[Path] = None,
        trusted_public_key: Optional[str] = None,
    ):
        """
        Initialize configuration manager.

        Args:
            config_dir: Directory for config files
            trusted_public_key: Ed25519 public key (hex) for verifying remote configs
        """
        self.config_dir = Path(config_dir) if config_dir else Path.home() / ".beautifi"
        self._trusted_public_key_hex = trusted_public_key
        self._config: Dict[str, Any] = {}
        self._history: List[ConfigChange] = []

        # Ensure directory exists
        self.config_dir.mkdir(parents=True, exist_ok=True)

        # Load configuration
        self._load_config()
        self._load_history()

        print(f"[CONFIG] Manager initialized with {len(self._config)} settings")

    def _load_config(self):
        """Load configuration from file."""
        config_path = self.config_dir / self.CONFIG_FILE

        # Start with defaults
        self._config = {k: v["default"] for k, v in self.ALLOWED_FIELDS.items()}

        if config_path.exists():
            try:
                with open(config_path, 'r') as f:
                    saved_config = json.load(f)

                # Merge saved values (only allowed fields)
                for key, value in saved_config.items():
                    if key in self.ALLOWED_FIELDS:
                        self._config[key] = value

            except Exception as e:
                print(f"[CONFIG] Failed to load config: {e}")

    def _save_config(self):
        """Save configuration to file."""
        config_path = self.config_dir / self.CONFIG_FILE
        with open(config_path, 'w') as f:
            json.dump(self._config, f, indent=2)

    def _load_history(self):
        """Load configuration change history."""
        history_path = self.config_dir / self.HISTORY_FILE
        if history_path.exists():
            try:
                with open(history_path, 'r') as f:
                    history_data = json.load(f)
                    self._history = [
                        ConfigChange(**item) for item in history_data[-100:]  # Keep last 100
                    ]
            except Exception:
                pass

    def _save_history(self):
        """Save configuration change history."""
        history_path = self.config_dir / self.HISTORY_FILE
        # Keep only last 100 changes
        history_data = [c.to_dict() for c in self._history[-100:]]
        with open(history_path, 'w') as f:
            json.dump(history_data, f, indent=2)

    def _record_change(self, key: str, old_value: Any, new_value: Any, source: str):
        """Record a configuration change."""
        change = ConfigChange(
            key=key,
            old_value=old_value,
            new_value=new_value,
            changed_at=datetime.now(timezone.utc).isoformat(),
            source=source,
        )
        self._history.append(change)
        self._save_history()

    # ============================================
    # Validation
    # ============================================

    def validate_value(self, key: str, value: Any) -> Tuple[bool, str]:
        """
        Validate a configuration value.

        Returns:
            Tuple of (is_valid, error_message)
        """
        if key not in self.ALLOWED_FIELDS:
            return False, f"Unknown configuration key: {key}"

        rules = self.ALLOWED_FIELDS[key]
        expected_type = rules["type"]

        # Type check
        if not isinstance(value, expected_type):
            # Allow int for float
            if expected_type == float and isinstance(value, int):
                value = float(value)
            else:
                return False, f"Invalid type for {key}: expected {expected_type.__name__}"

        # Range check for numbers
        if expected_type in (int, float):
            if "min" in rules and value < rules["min"]:
                return False, f"{key} must be >= {rules['min']}"
            if "max" in rules and value > rules["max"]:
                return False, f"{key} must be <= {rules['max']}"

        # Allowed values check
        if "allowed" in rules and value not in rules["allowed"]:
            return False, f"{key} must be one of: {rules['allowed']}"

        return True, ""

    # ============================================
    # Get/Set Configuration
    # ============================================

    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value."""
        return self._config.get(key, default)

    def get_all(self) -> Dict[str, Any]:
        """Get all configuration values."""
        return self._config.copy()

    def set(self, key: str, value: Any, source: str = "local") -> Tuple[bool, str]:
        """
        Set a configuration value.

        Args:
            key: Configuration key
            value: New value
            source: Source of change ("local", "remote", "api")

        Returns:
            Tuple of (success, message)
        """
        valid, error = self.validate_value(key, value)
        if not valid:
            return False, error

        old_value = self._config.get(key)
        if old_value == value:
            return True, "Value unchanged"

        self._config[key] = value
        self._save_config()
        self._record_change(key, old_value, value, source)

        print(f"[CONFIG] {key}: {old_value} -> {value} (source: {source})")
        return True, f"Updated {key}"

    def set_multiple(self, updates: Dict[str, Any], source: str = "local") -> Tuple[bool, Dict[str, str]]:
        """
        Set multiple configuration values.

        Args:
            updates: Dict of key-value pairs
            source: Source of changes

        Returns:
            Tuple of (all_success, results_dict)
        """
        results = {}
        all_success = True

        for key, value in updates.items():
            success, msg = self.set(key, value, source)
            results[key] = msg
            if not success:
                all_success = False

        return all_success, results

    def reset_to_defaults(self) -> Dict[str, Any]:
        """Reset all configuration to defaults."""
        old_config = self._config.copy()

        for key, rules in self.ALLOWED_FIELDS.items():
            old_value = self._config.get(key)
            new_value = rules["default"]
            if old_value != new_value:
                self._config[key] = new_value
                self._record_change(key, old_value, new_value, "reset")

        self._save_config()
        return old_config

    # ============================================
    # Remote Configuration
    # ============================================

    def apply_remote_config(
        self,
        config_data: Dict[str, Any],
        signature: Optional[str] = None,
    ) -> Tuple[bool, Dict[str, str]]:
        """
        Apply configuration from remote source.

        Args:
            config_data: Configuration updates
            signature: Optional Ed25519 signature

        Returns:
            Tuple of (success, results_dict)
        """
        # Verify signature if trusted key is configured
        if self._trusted_public_key_hex and signature:
            valid, msg = self._verify_config_signature(config_data, signature)
            if not valid:
                return False, {"_error": msg}

        # Extract configuration values (ignore metadata fields)
        updates = {
            k: v for k, v in config_data.items()
            if not k.startswith("_") and k in self.ALLOWED_FIELDS
        }

        if not updates:
            return False, {"_error": "No valid configuration fields in update"}

        return self.set_multiple(updates, source="remote")

    def _verify_config_signature(
        self,
        config_data: Dict[str, Any],
        signature: str,
    ) -> Tuple[bool, str]:
        """Verify remote configuration signature."""
        try:
            # Load trusted public key
            public_key_bytes = bytes.fromhex(self._trusted_public_key_hex)
            public_key = Ed25519PublicKey.from_public_bytes(public_key_bytes)

            # Canonicalize config (exclude signature field)
            signable = {k: v for k, v in config_data.items() if k != "_signature"}
            content = json.dumps(signable, sort_keys=True, separators=(',', ':')).encode()

            # Parse signature
            sig_str = signature
            if sig_str.startswith("ed25519:"):
                sig_str = sig_str[8:]
            sig_bytes = bytes.fromhex(sig_str)

            # Verify
            public_key.verify(sig_bytes, content)
            return True, "Signature valid"

        except InvalidSignature:
            return False, "Invalid configuration signature"
        except Exception as e:
            return False, f"Signature verification error: {e}"

    # ============================================
    # History
    # ============================================

    def get_history(self, limit: int = 50) -> List[Dict]:
        """Get recent configuration changes."""
        return [c.to_dict() for c in self._history[-limit:]]

    # ============================================
    # Status
    # ============================================

    def get_status(self) -> Dict[str, Any]:
        """Get configuration status summary."""
        return {
            "config_count": len(self._config),
            "history_count": len(self._history),
            "fields": list(self._config.keys()),
            "last_change": self._history[-1].to_dict() if self._history else None,
        }


# Quick test
if __name__ == "__main__":
    import tempfile

    print("Testing ConfigManager...")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmpdir:
        manager = ConfigManager(config_dir=Path(tmpdir))

        # Test get defaults
        print("\n1. Default values:")
        print(f"   sample_interval_seconds: {manager.get('sample_interval_seconds')}")
        print(f"   simulation_mode: {manager.get('simulation_mode')}")

        # Test set
        print("\n2. Setting values:")
        success, msg = manager.set("sample_interval_seconds", 30)
        print(f"   Set sample_interval_seconds=30: {success} - {msg}")

        # Test validation
        print("\n3. Validation tests:")
        success, msg = manager.set("sample_interval_seconds", 1)  # Too low
        print(f"   Set sample_interval_seconds=1: {success} - {msg}")

        success, msg = manager.set("log_level", "INVALID")  # Invalid value
        print(f"   Set log_level=INVALID: {success} - {msg}")

        # Test multiple
        print("\n4. Setting multiple:")
        success, results = manager.set_multiple({
            "default_fan_speed": 50,
            "voc_alert_threshold_ppb": 600,
        })
        print(f"   Success: {success}")
        for k, v in results.items():
            print(f"   {k}: {v}")

        # Test history
        print("\n5. History:")
        for change in manager.get_history():
            print(f"   {change['key']}: {change['old_value']} -> {change['new_value']}")

        # Test status
        print("\n6. Status:")
        for k, v in manager.get_status().items():
            print(f"   {k}: {v}")
