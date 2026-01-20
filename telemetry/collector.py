# telemetry/collector.py
"""
Telemetry collection service for BeautiFi IoT.
Samples sensor data at configured intervals and buffers locally.
Includes cryptographic signing for DUAN Proof-of-Air compliance.
"""

import threading
import time
import json
import sqlite3
from datetime import datetime, timedelta
from typing import Callable, Optional, List
from pathlib import Path

from config import (
    SAMPLE_INTERVAL_SECONDS,
    EPOCH_DURATION_MINUTES,
    TELEMETRY_BUFFER_SIZE,
    SIMULATION_MODE,
    DEVICE_ID,
)
from sensors import SimulatedSensors, FanInterpolator

# Crypto imports (with graceful fallback)
try:
    from crypto import sign_payload, sign_epoch, DeviceIdentity, get_device_identity
    CRYPTO_AVAILABLE = True
except ImportError as e:
    print(f"[WARN] Crypto module not available: {e}")
    CRYPTO_AVAILABLE = False

# Security imports (with graceful fallback)
try:
    from security import AnomalyDetector
    SECURITY_AVAILABLE = True
except ImportError as e:
    print(f"[WARN] Security module not available: {e}")
    SECURITY_AVAILABLE = False
    AnomalyDetector = None


class TelemetryCollector:
    """
    Background service that collects telemetry at regular intervals.

    Features:
    - Configurable sampling interval (default 12 seconds)
    - SQLite buffer for local storage
    - Epoch formation (bundles samples into 1-hour epochs)
    - Cryptographic signing of samples and epochs
    - Callback support for real-time streaming
    """

    def __init__(
        self,
        db_path: str = "telemetry.db",
        pwm_getter: Optional[Callable[[], float]] = None,
        enable_signing: bool = True,
        enable_anomaly_detection: bool = True,
    ):
        """
        Initialize the telemetry collector.

        Args:
            db_path: Path to SQLite database for buffering
            pwm_getter: Callback function that returns current PWM (0-100)
            enable_signing: Enable cryptographic signing of samples/epochs
            enable_anomaly_detection: Enable anomaly detection on samples
        """
        self.db_path = db_path
        self.pwm_getter = pwm_getter or (lambda: 0)
        self.enable_signing = enable_signing and CRYPTO_AVAILABLE
        self.enable_anomaly_detection = enable_anomaly_detection and SECURITY_AVAILABLE

        # Initialize device identity if signing is enabled
        self._identity: Optional[DeviceIdentity] = None
        if self.enable_signing:
            try:
                self._identity = get_device_identity()
                print(f"[CRYPTO] Device identity loaded: {self._identity.device_id}")
            except Exception as e:
                print(f"[WARN] Failed to load device identity: {e}")
                self.enable_signing = False

        # Initialize anomaly detector if enabled
        self._anomaly_detector = None
        if self.enable_anomaly_detection:
            try:
                self._anomaly_detector = AnomalyDetector(
                    db_path="anomaly.db",
                    sigma_threshold=3.0,
                )
                # Try to load existing baselines
                self._anomaly_detector.load_baselines()
            except Exception as e:
                print(f"[WARN] Failed to initialize anomaly detector: {e}")
                self.enable_anomaly_detection = False

        # Initialize sensors (simulation or real based on config)
        self.fan_interpolator = FanInterpolator()
        if SIMULATION_MODE:
            self.sensors = SimulatedSensors(self.fan_interpolator)
        else:
            # TODO: Initialize real sensors when available
            self.sensors = SimulatedSensors(self.fan_interpolator)

        # Threading
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

        # Callbacks for real-time data
        self._callbacks: List[Callable[[dict], None]] = []
        self._epoch_callback: Optional[Callable[[dict], None]] = None

        # Current epoch tracking
        self._current_epoch_start: Optional[datetime] = None
        self._current_epoch_samples: List[dict] = []

        # Initialize database
        self._init_db()

    def _init_db(self):
        """Initialize SQLite database for telemetry buffering."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Telemetry samples table (with signing columns)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS samples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                device_id TEXT NOT NULL,
                pwm_percent REAL,
                cfm REAL,
                rpm INTEGER,
                watts REAL,
                voc_ppb REAL,
                co2_ppm REAL,
                temperature_c REAL,
                humidity_pct REAL,
                delta_p_pa REAL,
                tar_cfm_min REAL,
                payload_hash TEXT,
                signature TEXT,
                raw_json TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Epochs table (with signing columns)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS epochs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                epoch_id TEXT UNIQUE NOT NULL,
                device_id TEXT NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                sample_count INTEGER,
                total_tar REAL,
                avg_cfm REAL,
                avg_watts REAL,
                avg_voc REAL,
                total_energy_wh REAL,
                merkle_root TEXT,
                epoch_hash TEXT,
                signature TEXT,
                summary_json TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Add columns if they don't exist (for db migration)
        try:
            cursor.execute("ALTER TABLE samples ADD COLUMN payload_hash TEXT")
        except sqlite3.OperationalError:
            pass
        try:
            cursor.execute("ALTER TABLE samples ADD COLUMN signature TEXT")
        except sqlite3.OperationalError:
            pass
        try:
            cursor.execute("ALTER TABLE epochs ADD COLUMN merkle_root TEXT")
        except sqlite3.OperationalError:
            pass
        try:
            cursor.execute("ALTER TABLE epochs ADD COLUMN epoch_hash TEXT")
        except sqlite3.OperationalError:
            pass
        try:
            cursor.execute("ALTER TABLE epochs ADD COLUMN signature TEXT")
        except sqlite3.OperationalError:
            pass

        conn.commit()
        conn.close()

    def _sign_sample(self, sample: dict) -> dict:
        """Sign a telemetry sample if signing is enabled."""
        if not self.enable_signing or self._identity is None:
            return sample

        try:
            signed = sign_payload(sample, self._identity)
            return signed
        except Exception as e:
            print(f"[WARN] Failed to sign sample: {e}")
            return sample

    def _store_sample(self, sample: dict):
        """Store a telemetry sample in the database."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Extract signing info if present
        payload_hash = None
        signature = None
        if '_signing' in sample:
            payload_hash = sample['_signing'].get('payload_hash')
            signature = sample['_signing'].get('signature')

        cursor.execute("""
            INSERT INTO samples (
                timestamp, device_id, pwm_percent, cfm, rpm, watts,
                voc_ppb, co2_ppm, temperature_c, humidity_pct, delta_p_pa,
                tar_cfm_min, payload_hash, signature, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            sample["timestamp"],
            sample["device_id"],
            sample["fan"]["pwm_percent"],
            sample["fan"]["cfm"],
            sample["fan"]["rpm"],
            sample["fan"]["watts"],
            sample["environment"]["voc_ppb"],
            sample["environment"]["co2_ppm"],
            sample["environment"]["temperature_c"],
            sample["environment"]["humidity_pct"],
            sample["environment"]["delta_p_pa"],
            sample["derived"]["tar_cfm_min"],
            payload_hash,
            signature,
            json.dumps(sample),
        ))

        conn.commit()

        # Cleanup old samples if buffer is full
        cursor.execute("SELECT COUNT(*) FROM samples")
        count = cursor.fetchone()[0]
        if count > TELEMETRY_BUFFER_SIZE:
            cursor.execute(f"""
                DELETE FROM samples WHERE id IN (
                    SELECT id FROM samples ORDER BY id ASC LIMIT {count - TELEMETRY_BUFFER_SIZE}
                )
            """)
            conn.commit()

        conn.close()

    def _store_epoch(self, epoch: dict):
        """Store a completed epoch in the database."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Extract signing info if present
        merkle_root = epoch.get('merkle_root')
        epoch_hash = None
        signature = None
        if '_signing' in epoch:
            epoch_hash = epoch['_signing'].get('epoch_hash')
            signature = epoch['_signing'].get('signature')

        cursor.execute("""
            INSERT OR REPLACE INTO epochs (
                epoch_id, device_id, start_time, end_time, sample_count,
                total_tar, avg_cfm, avg_watts, avg_voc, total_energy_wh,
                merkle_root, epoch_hash, signature, summary_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            epoch["epoch_id"],
            epoch["device_id"],
            epoch["start_time"],
            epoch["end_time"],
            epoch["sample_count"],
            epoch["summary"]["total_tar_cfm_min"],
            epoch["summary"]["avg_cfm"],
            epoch["summary"]["avg_watts"],
            epoch["summary"]["avg_voc_ppb"],
            epoch["summary"]["total_energy_wh"],
            merkle_root,
            epoch_hash,
            signature,
            json.dumps(epoch),
        ))

        conn.commit()
        conn.close()

    def _check_epoch(self, sample: dict):
        """Check if current epoch is complete and form new one if needed."""
        sample_time = datetime.fromisoformat(sample["timestamp"].replace("Z", "+00:00"))

        # Start new epoch if none exists
        if self._current_epoch_start is None:
            self._current_epoch_start = sample_time
            self._current_epoch_samples = []

        self._current_epoch_samples.append(sample)

        # Check if epoch is complete
        elapsed = sample_time - self._current_epoch_start
        if elapsed >= timedelta(minutes=EPOCH_DURATION_MINUTES):
            self._finalize_epoch()

    def _finalize_epoch(self):
        """Finalize the current epoch, sign it, and store it."""
        if not self._current_epoch_samples:
            return

        samples = self._current_epoch_samples
        start_time = self._current_epoch_start
        end_time = datetime.fromisoformat(
            samples[-1]["timestamp"].replace("Z", "+00:00")
        )

        # Calculate epoch summary
        total_tar = sum(s["derived"]["tar_cfm_min"] for s in samples)
        total_energy = sum(s["derived"]["energy_wh"] for s in samples)
        avg_cfm = sum(s["fan"]["cfm"] for s in samples) / len(samples)
        avg_watts = sum(s["fan"]["watts"] for s in samples) / len(samples)
        avg_voc = sum(s["environment"]["voc_ppb"] for s in samples) / len(samples)
        avg_efficiency = avg_cfm / avg_watts if avg_watts > 0 else 0

        # Determine eligible minutes (when fan was running)
        eligible_samples = [s for s in samples if s["fan"]["cfm"] > 0]
        eligible_minutes = len(eligible_samples) * (SAMPLE_INTERVAL_SECONDS / 60)

        # Build epoch data
        epoch_data = {
            "epoch_id": f"ep-{start_time.strftime('%Y%m%d%H')}-{DEVICE_ID}",
            "device_id": DEVICE_ID,
            "start_time": start_time.isoformat() + "Z",
            "end_time": end_time.isoformat() + "Z",
            "summary": {
                "total_tar_cfm_min": round(total_tar, 1),
                "eligible_minutes": round(eligible_minutes, 1),
                "avg_cfm": round(avg_cfm, 1),
                "avg_watts": round(avg_watts, 1),
                "avg_voc_ppb": round(avg_voc, 1),
                "avg_efficiency_cfm_w": round(avg_efficiency, 2),
                "total_energy_wh": round(total_energy, 2),
            },
        }

        # Sign the epoch if enabled
        if self.enable_signing and self._identity is not None:
            try:
                epoch = sign_epoch(epoch_data, samples, self._identity)
                print(f"[EPOCH] Signed epoch: {epoch['epoch_id']}")
                print(f"        Merkle root: {epoch['merkle_root'][:32]}...")
                print(f"        Samples: {epoch['sample_count']}, TAR: {epoch['summary']['total_tar_cfm_min']}")
            except Exception as e:
                print(f"[WARN] Failed to sign epoch: {e}")
                epoch = {**epoch_data, "sample_count": len(samples)}
        else:
            epoch = {**epoch_data, "sample_count": len(samples)}

        self._store_epoch(epoch)

        # Notify epoch callback
        if self._epoch_callback:
            try:
                self._epoch_callback(epoch)
            except Exception as e:
                print(f"[WARN] Epoch callback error: {e}")

        # Reset for next epoch
        self._current_epoch_start = None
        self._current_epoch_samples = []

    def _collection_loop(self):
        """Main collection loop running in background thread."""
        signing_status = "enabled" if self.enable_signing else "disabled"
        anomaly_status = "enabled" if self.enable_anomaly_detection else "disabled"
        print(f">> Telemetry collector started (interval: {SAMPLE_INTERVAL_SECONDS}s, signing: {signing_status}, anomaly: {anomaly_status})")

        while self._running:
            try:
                # Get current PWM from the fan controller
                current_pwm = self.pwm_getter()

                # Read sensors
                sample = self.sensors.read_all(current_pwm)

                # Check for anomalies before signing
                anomaly_flags = []
                if self.enable_anomaly_detection and self._anomaly_detector:
                    anomalies = self._anomaly_detector.check_sample(sample)
                    if anomalies:
                        # Add anomaly flags to sample
                        anomaly_flags = [a.to_dict() for a in anomalies]
                        sample["_anomalies"] = {
                            "count": len(anomalies),
                            "has_critical": self._anomaly_detector.has_critical_anomalies(anomalies),
                            "types": list(set(a.anomaly_type.value for a in anomalies)),
                        }

                # Sign the sample (includes anomaly flags in signature)
                sample = self._sign_sample(sample)

                # Store locally
                self._store_sample(sample)

                # Check/update epoch
                self._check_epoch(sample)

                # Notify callbacks
                for callback in self._callbacks:
                    try:
                        callback(sample)
                    except Exception as e:
                        print(f"[WARN] Callback error: {e}")

                # Log periodically (include signature and anomaly status)
                sig_indicator = "[S]" if '_signing' in sample else ""
                anomaly_indicator = "[!]" if anomaly_flags else ""
                print(f"[DATA]{sig_indicator}{anomaly_indicator} Sample: CFM={sample['fan']['cfm']}, "
                      f"VOC={sample['environment']['voc_ppb']}ppb, PWM={current_pwm}%")

            except Exception as e:
                print(f"[ERR] Collection error: {e}")

            # Wait for next sample
            time.sleep(SAMPLE_INTERVAL_SECONDS)

    def start(self):
        """Start the background collection thread."""
        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(target=self._collection_loop, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop the background collection thread."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None

        # Finalize any partial epoch
        if self._current_epoch_samples:
            self._finalize_epoch()

        # Save anomaly baselines
        if self._anomaly_detector:
            self._anomaly_detector.save_baselines()

        print("[STOP] Telemetry collector stopped")

    def add_callback(self, callback: Callable[[dict], None]):
        """Add a callback function to receive real-time samples."""
        self._callbacks.append(callback)

    def remove_callback(self, callback: Callable[[dict], None]):
        """Remove a callback function."""
        if callback in self._callbacks:
            self._callbacks.remove(callback)

    def set_epoch_callback(self, callback: Callable[[dict], None]):
        """Set callback function for completed epochs."""
        self._epoch_callback = callback

    def get_recent_samples(self, limit: int = 100) -> List[dict]:
        """Get recent samples from the database."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT raw_json FROM samples
            ORDER BY id DESC LIMIT ?
        """, (limit,))

        rows = cursor.fetchall()
        conn.close()

        return [json.loads(row[0]) for row in reversed(rows)]

    def get_recent_epochs(self, limit: int = 24) -> List[dict]:
        """Get recent epochs from the database."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT summary_json FROM epochs
            ORDER BY id DESC LIMIT ?
        """, (limit,))

        rows = cursor.fetchall()
        conn.close()

        return [json.loads(row[0]) for row in reversed(rows)]

    def get_device_identity_info(self) -> Optional[dict]:
        """Get device identity information."""
        if self._identity:
            return self._identity.get_identity_info()
        return None

    def get_anomaly_status(self) -> Optional[dict]:
        """Get anomaly detector status."""
        if self._anomaly_detector:
            return self._anomaly_detector.get_status()
        return None

    def get_anomaly_baselines(self) -> Optional[dict]:
        """Get anomaly detector baseline statistics."""
        if self._anomaly_detector:
            return self._anomaly_detector.get_baseline_stats()
        return None

    def get_recent_anomalies(self, limit: int = 50) -> List[dict]:
        """Get recent anomalies from the detector."""
        if self._anomaly_detector:
            return self._anomaly_detector.get_recent_anomalies(limit)
        return []


# Quick test
if __name__ == "__main__":
    print("Testing TelemetryCollector with signing")
    print("=" * 60)

    collector = TelemetryCollector(
        db_path="test_telemetry.db",
        pwm_getter=lambda: 50,  # Fixed 50% for testing
        enable_signing=True,
    )

    print(f"\nDevice Identity: {collector.get_device_identity_info()}")

    collector.start()
    time.sleep(15)  # Collect a few samples
    collector.stop()

    print("\nRecent signed samples:")
    for sample in collector.get_recent_samples(3):
        print(f"  {sample['timestamp']}: CFM={sample['fan']['cfm']}")
        if '_signing' in sample:
            print(f"    Hash: {sample['_signing']['payload_hash'][:32]}...")
            print(f"    Sig:  {sample['_signing']['signature'][:40]}...")
