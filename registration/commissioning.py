# registration/commissioning.py
"""
Device commissioning flow for BeautiFi IoT DUAN compliance.
Handles baseline calibration and registration.
"""

import json
import time
import threading
import sqlite3
from datetime import datetime, timezone
from typing import Optional, Dict, Any, Callable, List
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from config import (
    DEVICE_ID,
    SIMULATION_MODE,
    SAMPLE_INTERVAL_SECONDS,
)


class CommissioningState(Enum):
    """States of the commissioning process."""
    NOT_STARTED = "not_started"
    CALIBRATING = "calibrating"
    CALIBRATION_COMPLETE = "calibration_complete"
    REGISTERING = "registering"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    FAILED = "failed"


@dataclass
class CalibrationResult:
    """Results of baseline calibration."""
    duration_minutes: float
    sample_count: int
    baselines: Dict[str, Dict[str, float]]
    started_at: str
    completed_at: str
    passed: bool
    issues: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "duration_minutes": self.duration_minutes,
            "sample_count": self.sample_count,
            "baselines": self.baselines,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "passed": self.passed,
            "issues": self.issues,
        }


class CommissioningManager:
    """
    Manages the device commissioning process.

    Flow:
    1. Run baseline calibration (30 minutes)
    2. Generate hardware manifest
    3. Submit registration to backend
    4. Store Site NFT binding when approved
    """

    # Calibration settings
    DEFAULT_CALIBRATION_MINUTES = 30
    MIN_CALIBRATION_SAMPLES = 50

    # Baseline validation thresholds
    BASELINE_THRESHOLDS = {
        "cfm": {"min": 0, "max": 1000, "min_std": 0},
        "rpm": {"min": 0, "max": 5000, "min_std": 0},
        "watts": {"min": 0, "max": 200, "min_std": 0},
        "voc_ppb": {"min": 0, "max": 5000, "min_std": 0},
        "co2_ppm": {"min": 200, "max": 5000, "min_std": 0},
        "temperature_c": {"min": 10, "max": 40, "min_std": 0},
        "humidity_pct": {"min": 10, "max": 90, "min_std": 0},
    }

    def __init__(
        self,
        db_path: str = "commissioning.db",
        key_dir: Optional[Path] = None,
    ):
        """
        Initialize commissioning manager.

        Args:
            db_path: Path to SQLite database for commissioning data
            key_dir: Directory for keys and manifest
        """
        self.db_path = db_path
        self.key_dir = key_dir or Path.home() / ".beautifi" / "keys"

        # State
        self._state = CommissioningState.NOT_STARTED
        self._calibration_result: Optional[CalibrationResult] = None
        self._registration_id: Optional[str] = None
        self._nft_binding: Optional[Dict[str, Any]] = None

        # Calibration
        self._calibrating = False
        self._calibration_thread: Optional[threading.Thread] = None
        self._calibration_samples: List[Dict] = []
        self._calibration_start: Optional[datetime] = None

        # Callbacks
        self._on_state_change: Optional[Callable[[CommissioningState], None]] = None
        self._on_calibration_progress: Optional[Callable[[int, int], None]] = None

        # Initialize database
        self._init_db()

        # Load existing state
        self._load_state()

        print(f"[COMMISSION] Manager initialized (state: {self._state.value})")

    def _init_db(self):
        """Initialize SQLite database for commissioning data."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS commissioning_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                state TEXT NOT NULL,
                registration_id TEXT,
                wallet_address TEXT,
                calibration_json TEXT,
                nft_binding_json TEXT,
                updated_at TEXT
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS calibration_samples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                sample_json TEXT NOT NULL
            )
        """)

        conn.commit()
        conn.close()

    def _load_state(self):
        """Load commissioning state from database."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM commissioning_state WHERE id = 1")
        row = cursor.fetchone()
        conn.close()

        if row:
            self._state = CommissioningState(row[1])
            self._registration_id = row[2]

            if row[4]:  # calibration_json
                cal_data = json.loads(row[4])
                self._calibration_result = CalibrationResult(**cal_data)

            if row[5]:  # nft_binding_json
                self._nft_binding = json.loads(row[5])

    def _save_state(self):
        """Save commissioning state to database."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cal_json = json.dumps(self._calibration_result.to_dict()) if self._calibration_result else None
        nft_json = json.dumps(self._nft_binding) if self._nft_binding else None

        cursor.execute("""
            INSERT OR REPLACE INTO commissioning_state (
                id, state, registration_id, wallet_address, calibration_json, nft_binding_json, updated_at
            ) VALUES (1, ?, ?, ?, ?, ?, ?)
        """, (
            self._state.value,
            self._registration_id,
            self._nft_binding.get("wallet_address") if self._nft_binding else None,
            cal_json,
            nft_json,
            datetime.now(timezone.utc).isoformat(),
        ))

        conn.commit()
        conn.close()

    def _notify_state_change(self):
        """Notify callback of state change."""
        if self._on_state_change:
            try:
                self._on_state_change(self._state)
            except Exception as e:
                print(f"[COMMISSION] State callback error: {e}")

    @property
    def state(self) -> CommissioningState:
        """Get current commissioning state."""
        return self._state

    @property
    def calibration_result(self) -> Optional[CalibrationResult]:
        """Get calibration result if completed."""
        return self._calibration_result

    @property
    def nft_binding(self) -> Optional[Dict[str, Any]]:
        """Get NFT binding if registered."""
        return self._nft_binding

    def set_state_callback(self, callback: Callable[[CommissioningState], None]):
        """Set callback for state changes."""
        self._on_state_change = callback

    def set_progress_callback(self, callback: Callable[[int, int], None]):
        """Set callback for calibration progress (current, total)."""
        self._on_calibration_progress = callback

    # ============================================
    # Calibration
    # ============================================

    def start_calibration(
        self,
        duration_minutes: int = DEFAULT_CALIBRATION_MINUTES,
        sensor_reader: Optional[Callable[[], Dict]] = None,
    ) -> bool:
        """
        Start baseline calibration.

        Args:
            duration_minutes: Duration of calibration in minutes
            sensor_reader: Function that returns sensor readings dict

        Returns:
            True if calibration started
        """
        if self._calibrating:
            print("[COMMISSION] Calibration already in progress")
            return False

        if self._state == CommissioningState.APPROVED:
            print("[COMMISSION] Device already approved, cannot recalibrate")
            return False

        self._calibrating = True
        self._calibration_samples = []
        self._calibration_start = datetime.now(timezone.utc)
        self._state = CommissioningState.CALIBRATING
        self._save_state()
        self._notify_state_change()

        # Start calibration thread
        self._calibration_thread = threading.Thread(
            target=self._calibration_loop,
            args=(duration_minutes, sensor_reader),
            daemon=True,
        )
        self._calibration_thread.start()

        print(f"[COMMISSION] Calibration started ({duration_minutes} minutes)")
        return True

    def _calibration_loop(
        self,
        duration_minutes: int,
        sensor_reader: Optional[Callable[[], Dict]],
    ):
        """Calibration background loop."""
        from sensors import SimulatedSensors, FanInterpolator

        # Use provided reader or create default
        if sensor_reader is None:
            interpolator = FanInterpolator()
            sensors = SimulatedSensors(interpolator)
            sensor_reader = lambda: sensors.read_all(50)  # Fixed 50% PWM for baseline

        total_samples = int((duration_minutes * 60) / SAMPLE_INTERVAL_SECONDS)
        session_id = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            sample_count = 0
            while self._calibrating and sample_count < total_samples:
                # Read sensors
                sample = sensor_reader()
                sample["calibration_sample"] = True
                sample["sample_index"] = sample_count

                self._calibration_samples.append(sample)

                # Store to database
                cursor.execute("""
                    INSERT INTO calibration_samples (session_id, timestamp, sample_json)
                    VALUES (?, ?, ?)
                """, (
                    session_id,
                    sample.get("timestamp", datetime.now(timezone.utc).isoformat()),
                    json.dumps(sample),
                ))
                conn.commit()

                sample_count += 1

                # Notify progress
                if self._on_calibration_progress:
                    try:
                        self._on_calibration_progress(sample_count, total_samples)
                    except Exception:
                        pass

                # Log progress periodically
                if sample_count % 10 == 0:
                    pct = int((sample_count / total_samples) * 100)
                    print(f"[CALIBRATION] Progress: {sample_count}/{total_samples} ({pct}%)")

                time.sleep(SAMPLE_INTERVAL_SECONDS)

            # Finalize calibration
            self._finalize_calibration()

        except Exception as e:
            print(f"[COMMISSION] Calibration error: {e}")
            self._state = CommissioningState.FAILED
            self._save_state()
            self._notify_state_change()

        finally:
            conn.close()
            self._calibrating = False

    def _finalize_calibration(self):
        """Finalize calibration and compute baselines."""
        if not self._calibration_samples:
            self._state = CommissioningState.FAILED
            self._save_state()
            return

        samples = self._calibration_samples
        start_time = self._calibration_start
        end_time = datetime.now(timezone.utc)
        duration = (end_time - start_time).total_seconds() / 60

        # Compute baselines for each metric
        baselines = {}
        issues = []

        metric_paths = {
            "cfm": ("fan", "cfm"),
            "rpm": ("fan", "rpm"),
            "watts": ("fan", "watts"),
            "voc_ppb": ("environment", "voc_ppb"),
            "co2_ppm": ("environment", "co2_ppm"),
            "temperature_c": ("environment", "temperature_c"),
            "humidity_pct": ("environment", "humidity_pct"),
        }

        for metric, path in metric_paths.items():
            values = []
            for sample in samples:
                try:
                    val = sample
                    for key in path:
                        val = val[key]
                    values.append(float(val))
                except (KeyError, TypeError):
                    continue

            if not values:
                issues.append(f"No data for {metric}")
                continue

            # Calculate statistics
            mean = sum(values) / len(values)
            variance = sum((x - mean) ** 2 for x in values) / len(values) if len(values) > 1 else 0
            std_dev = variance ** 0.5
            min_val = min(values)
            max_val = max(values)

            baselines[metric] = {
                "mean": round(mean, 4),
                "std_dev": round(std_dev, 4),
                "min": round(min_val, 4),
                "max": round(max_val, 4),
                "sample_count": len(values),
            }

            # Validate against thresholds
            if metric in self.BASELINE_THRESHOLDS:
                thresh = self.BASELINE_THRESHOLDS[metric]
                if mean < thresh["min"] or mean > thresh["max"]:
                    issues.append(f"{metric} baseline ({mean:.2f}) outside expected range")

        # Check minimum sample count
        passed = len(samples) >= self.MIN_CALIBRATION_SAMPLES and len(issues) == 0

        self._calibration_result = CalibrationResult(
            duration_minutes=round(duration, 2),
            sample_count=len(samples),
            baselines=baselines,
            started_at=start_time.isoformat(),
            completed_at=end_time.isoformat(),
            passed=passed,
            issues=issues,
        )

        self._state = CommissioningState.CALIBRATION_COMPLETE
        self._save_state()
        self._notify_state_change()

        print(f"[COMMISSION] Calibration complete: {len(samples)} samples, passed={passed}")
        if issues:
            print(f"[COMMISSION] Issues: {issues}")

    def stop_calibration(self):
        """Stop calibration early."""
        self._calibrating = False
        if self._calibration_thread:
            self._calibration_thread.join(timeout=5)

    # ============================================
    # Registration
    # ============================================

    def register(
        self,
        wallet_address: str,
        salon_name: str,
        location: str,
        email: str,
        backend_client,  # RegistrationClient
        **kwargs
    ) -> bool:
        """
        Submit device registration to backend.

        Args:
            wallet_address: Owner's wallet address
            salon_name: Name of the salon/site
            location: Location address
            email: Contact email
            backend_client: RegistrationClient instance
            **kwargs: Additional registration fields

        Returns:
            True if registration submitted successfully
        """
        if self._state not in [CommissioningState.CALIBRATION_COMPLETE, CommissioningState.FAILED]:
            print(f"[COMMISSION] Cannot register in state: {self._state.value}")
            return False

        self._state = CommissioningState.REGISTERING
        self._save_state()
        self._notify_state_change()

        # Generate manifest with calibration data
        from .manifest import HardwareManifest

        manifest_gen = HardwareManifest(key_dir=self.key_dir)
        calibration_data = self._calibration_result.to_dict() if self._calibration_result else None
        manifest = manifest_gen.generate(calibration_data=calibration_data)
        manifest_gen.save()

        # Submit registration
        payload = manifest_gen.get_registration_payload()
        result = backend_client.register_device(
            wallet_address=wallet_address,
            salon_name=salon_name,
            location=location,
            email=email,
            manifest=payload,
            **kwargs
        )

        if result.success:
            self._registration_id = result.registration_id
            self._nft_binding = {
                "wallet_address": wallet_address,
                "registration_id": result.registration_id,
                "status": "pending",
            }
            self._state = CommissioningState.PENDING_APPROVAL
            self._save_state()
            self._notify_state_change()

            print(f"[COMMISSION] Registration submitted: {result.registration_id}")
            return True
        else:
            print(f"[COMMISSION] Registration failed: {result.error}")
            self._state = CommissioningState.FAILED
            self._save_state()
            self._notify_state_change()
            return False

    def check_approval(self, backend_client) -> bool:
        """
        Check if registration has been approved.

        Args:
            backend_client: RegistrationClient instance

        Returns:
            True if approved
        """
        if not self._nft_binding or not self._nft_binding.get("wallet_address"):
            return False

        nft_info = backend_client.get_nft_binding(self._nft_binding["wallet_address"])

        if nft_info and nft_info.get("status") == "approved":
            self._nft_binding.update(nft_info)
            self._state = CommissioningState.APPROVED
            self._save_state()
            self._notify_state_change()

            print(f"[COMMISSION] Device approved! NFT Token ID: {nft_info.get('nft_token_id')}")
            return True

        return False

    # ============================================
    # Status
    # ============================================

    def get_status(self) -> Dict[str, Any]:
        """Get commissioning status summary."""
        status = {
            "state": self._state.value,
            "device_id": DEVICE_ID,
            "registration_id": self._registration_id,
        }

        if self._calibrating:
            status["calibration_progress"] = {
                "samples_collected": len(self._calibration_samples),
                "started_at": self._calibration_start.isoformat() if self._calibration_start else None,
            }

        if self._calibration_result:
            status["calibration"] = {
                "passed": self._calibration_result.passed,
                "sample_count": self._calibration_result.sample_count,
                "duration_minutes": self._calibration_result.duration_minutes,
                "issues": self._calibration_result.issues,
            }

        if self._nft_binding:
            status["nft_binding"] = self._nft_binding

        return status

    def reset(self):
        """Reset commissioning state (for re-registration)."""
        if self._calibrating:
            self.stop_calibration()

        self._state = CommissioningState.NOT_STARTED
        self._calibration_result = None
        self._registration_id = None
        self._nft_binding = None
        self._calibration_samples = []

        # Clear database
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM commissioning_state")
        cursor.execute("DELETE FROM calibration_samples")
        conn.commit()
        conn.close()

        self._notify_state_change()
        print("[COMMISSION] State reset")


# Quick test
if __name__ == "__main__":
    print("Testing CommissioningManager...")
    print("=" * 60)

    manager = CommissioningManager(db_path="test_commissioning.db")

    print(f"\nInitial state: {manager.state.value}")

    # Start short calibration (1 minute for testing)
    print("\n1. Starting calibration (1 minute test)...")
    manager.start_calibration(duration_minutes=1)

    # Wait for calibration
    while manager.state == CommissioningState.CALIBRATING:
        time.sleep(5)
        status = manager.get_status()
        print(f"   Progress: {status.get('calibration_progress', {}).get('samples_collected', 0)} samples")

    print(f"\n2. Calibration complete!")
    print(f"   State: {manager.state.value}")
    if manager.calibration_result:
        print(f"   Samples: {manager.calibration_result.sample_count}")
        print(f"   Passed: {manager.calibration_result.passed}")
        print(f"   Baselines: {list(manager.calibration_result.baselines.keys())}")

    # Cleanup
    import os
    if os.path.exists("test_commissioning.db"):
        os.remove("test_commissioning.db")

    print("\nCommissioningManager test complete!")
