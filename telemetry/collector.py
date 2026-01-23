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
    R2_ENDPOINT_URL,
    R2_ACCESS_KEY_ID,
    R2_SECRET_ACCESS_KEY,
    R2_BUCKET_NAME,
    ENABLE_EVIDENCE_PACKS,
    EVIDENCE_AUTO_UPLOAD,
    EVIDENCE_KEEP_LOCAL,
    EVIDENCE_OUTPUT_DIR,
    VERIFIER_URL,
    ENABLE_VERIFIER_SYNC,
)
from sensors import SimulatedSensors, FanInterpolator

# Evidence pack imports (with graceful fallback)
try:
    from evidence import EvidencePackBuilder
    EVIDENCE_AVAILABLE = True
except ImportError as e:
    print(f"[WARN] Evidence module not available: {e}")
    EVIDENCE_AVAILABLE = False
    EvidencePackBuilder = None

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

# Tokenomics imports (with graceful fallback)
try:
    from tokenomics import IssuanceCalculator, TokenomicsConfig
    TOKENOMICS_AVAILABLE = True
except ImportError as e:
    print(f"[WARN] Tokenomics module not available: {e}")
    TOKENOMICS_AVAILABLE = False
    IssuanceCalculator = None
    TokenomicsConfig = None

# Verifier client imports (with graceful fallback)
try:
    from network import VerifierClient
    VERIFIER_AVAILABLE = True
except ImportError as e:
    print(f"[WARN] Verifier client not available: {e}")
    VERIFIER_AVAILABLE = False
    VerifierClient = None


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
        enable_evidence_packs: bool = True,
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

        # Initialize evidence pack builder if enabled
        self.enable_evidence_packs = enable_evidence_packs and EVIDENCE_AVAILABLE and ENABLE_EVIDENCE_PACKS
        self._evidence_builder = None
        if self.enable_evidence_packs:
            try:
                self._evidence_builder = EvidencePackBuilder(
                    output_dir=EVIDENCE_OUTPUT_DIR,
                    r2_endpoint_url=R2_ENDPOINT_URL,
                    r2_access_key_id=R2_ACCESS_KEY_ID,
                    r2_secret_access_key=R2_SECRET_ACCESS_KEY,
                    r2_bucket_name=R2_BUCKET_NAME,
                    auto_upload=EVIDENCE_AUTO_UPLOAD,
                    keep_local=EVIDENCE_KEEP_LOCAL,
                )
                print(f"[EVIDENCE] Pack builder initialized, upload={'enabled' if EVIDENCE_AUTO_UPLOAD else 'disabled'}")
            except Exception as e:
                print(f"[WARN] Failed to initialize evidence pack builder: {e}")
                self.enable_evidence_packs = False

        # Initialize tokenomics issuance calculator
        self._issuance_calculator = None
        if TOKENOMICS_AVAILABLE:
            try:
                self._issuance_calculator = IssuanceCalculator()
                print(f"[TOKENOMICS] Issuance calculator initialized (base rate: {self._issuance_calculator.config.base_issuance_rate})")
            except Exception as e:
                print(f"[WARN] Failed to initialize issuance calculator: {e}")

        # Initialize verifier client for backend submission
        self._verifier_client = None
        if VERIFIER_AVAILABLE and ENABLE_VERIFIER_SYNC:
            try:
                self._verifier_client = VerifierClient(
                    verifier_url=VERIFIER_URL,
                    device_id=DEVICE_ID,
                    auto_sync=True,
                )
                self._verifier_client.start()
                print(f"[VERIFIER] Client initialized: {VERIFIER_URL}")
            except Exception as e:
                print(f"[WARN] Failed to initialize verifier client: {e}")

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

        # Handle both v1 spec format and legacy format
        summary = epoch.get("summary", {})
        if "mitigation" in summary:
            # v1 spec format
            total_tar = summary["mitigation"]["total_tar_cfm_min"]
            total_energy = summary["mitigation"]["total_energy_wh"]
            avg_cfm = summary["fan_performance"]["avg_cfm"]
            avg_watts = summary["fan_performance"]["avg_power_w"]
            avg_voc = summary["air_quality"]["avg_tvoc_ppb"]
        else:
            # Legacy format
            total_tar = summary.get("total_tar_cfm_min", 0)
            total_energy = summary.get("total_energy_wh", 0)
            avg_cfm = summary.get("avg_cfm", 0)
            avg_watts = summary.get("avg_watts", 0)
            avg_voc = summary.get("avg_voc_ppb", 0)

        # Handle v1 time format vs legacy
        start_time = epoch.get("start_time") or epoch.get("time", {}).get("start", "")
        end_time = epoch.get("end_time") or epoch.get("time", {}).get("end", "")

        cursor.execute("""
            INSERT OR REPLACE INTO epochs (
                epoch_id, device_id, start_time, end_time, sample_count,
                total_tar, avg_cfm, avg_watts, avg_voc, total_energy_wh,
                merkle_root, epoch_hash, signature, summary_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            epoch["epoch_id"],
            epoch["device_id"],
            start_time,
            end_time,
            epoch.get("sample_count", 0),
            total_tar,
            avg_cfm,
            avg_watts,
            avg_voc,
            total_energy,
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

        # Calculate duration in minutes
        duration_minutes = (end_time - start_time).total_seconds() / 60

        # Air quality aggregations
        voc_values = [s["environment"].get("voc_ppb", s["environment"].get("tvoc_ppb", 0)) for s in samples]
        co2_values = [s["environment"].get("co2_ppm", s["environment"].get("eco2_ppm", 0)) for s in samples]
        pm25_values = [s["environment"].get("pm25_ugm3", 0) for s in samples]
        temp_values = [s["environment"].get("temperature_c", s["environment"].get("temp_c", 0)) for s in samples]
        humidity_values = [s["environment"].get("humidity_pct", 0) for s in samples]
        pressure_values = [s["environment"].get("delta_p_pa", s["environment"].get("dp_pa", 0)) for s in samples]

        avg_tvoc = sum(voc_values) / len(voc_values) if voc_values else 0
        max_tvoc = max(voc_values) if voc_values else 0
        avg_eco2 = sum(co2_values) / len(co2_values) if co2_values else 0
        avg_pm25 = sum(pm25_values) / len(pm25_values) if pm25_values else 0
        avg_temp = sum(temp_values) / len(temp_values) if temp_values else 0
        avg_humidity = sum(humidity_values) / len(humidity_values) if humidity_values else 0
        avg_pressure = sum(pressure_values) / len(pressure_values) if pressure_values else 0

        # Fan performance aggregations
        cfm_values = [s["fan"]["cfm"] for s in samples]
        rpm_values = [s["fan"].get("rpm", 0) for s in samples]
        watts_values = [s["fan"].get("watts", s["fan"].get("power_w", 0)) for s in samples]
        efficiency_values = [s["fan"].get("efficiency_cfm_w", 0) for s in samples]

        avg_cfm = sum(cfm_values) / len(cfm_values) if cfm_values else 0
        avg_rpm = sum(rpm_values) / len(rpm_values) if rpm_values else 0
        avg_watts = sum(watts_values) / len(watts_values) if watts_values else 0
        avg_efficiency = sum(efficiency_values) / len(efficiency_values) if efficiency_values else 0

        # Mitigation metrics
        total_tar = sum(s["derived"]["tar_cfm_min"] for s in samples)
        total_energy = sum(s["derived"]["energy_wh"] for s in samples)
        voc_reduction_values = [s["derived"].get("voc_reduction_pct", 0) for s in samples]
        avg_voc_reduction = sum(voc_reduction_values) / len(voc_reduction_values) if voc_reduction_values else 0

        # Build epoch data in v1 spec format
        epoch_id = f"ep-{start_time.strftime('%Y%m%d%H')}-{DEVICE_ID}"
        epoch_data = {
            "schema_version": "1.0",
            "epoch_id": epoch_id,
            "device_id": DEVICE_ID,
            "time": {
                "start": start_time.isoformat() + "Z",
                "end": end_time.isoformat() + "Z",
                "duration_minutes": round(duration_minutes, 1),
            },
            "sample_count": len(samples),
            "summary": {
                "air_quality": {
                    "avg_tvoc_ppb": round(avg_tvoc, 1),
                    "max_tvoc_ppb": round(max_tvoc, 1),
                    "avg_eco2_ppm": round(avg_eco2, 1),
                    "avg_pm25_ugm3": round(avg_pm25, 2),
                    "avg_temp_c": round(avg_temp, 1),
                    "avg_humidity_pct": round(avg_humidity, 1),
                    "avg_pressure_pa": round(avg_pressure, 1),
                },
                "fan_performance": {
                    "avg_cfm": round(avg_cfm, 1),
                    "avg_rpm": round(avg_rpm),
                    "avg_power_w": round(avg_watts, 1),
                    "avg_dp_pa": round(avg_pressure, 1),
                    "avg_efficiency_cfm_w": round(avg_efficiency, 2),
                },
                "mitigation": {
                    "total_tar_cfm_min": round(total_tar, 1),
                    "total_energy_wh": round(total_energy, 2),
                    "voc_reduction_pct": round(avg_voc_reduction, 1),
                },
                "tokenomics": {
                    "efficiency_index": 1.0,
                    "quality_factor": 1.0,
                    "valid_events_count": 0,
                    "events_per_epoch": 5,
                    "epoch_valid": True,
                    "issued_tokens": 0.0,
                },
            },
            # Backward compatibility fields
            "start_time": start_time.isoformat() + "Z",
            "end_time": end_time.isoformat() + "Z",
        }

        # Calculate token issuance if tokenomics available
        issuance_result = None
        if self._issuance_calculator:
            try:
                issuance_result = self._issuance_calculator.calculate_epoch_issuance(
                    epoch_id=epoch_id,
                    device_id=DEVICE_ID,
                    samples=samples,
                )
                # Update tokenomics section with actual values
                epoch_data["summary"]["tokenomics"] = {
                    "efficiency_index": round(issuance_result.ei_clamped, 3),
                    "quality_factor": round(issuance_result.quality_factor, 3),
                    "valid_events_count": issuance_result.valid_events,
                    "events_per_epoch": issuance_result.total_events,
                    "epoch_valid": issuance_result.valid_events > 0,
                    "issued_tokens": round(issuance_result.tokens_issued, 4),
                }
                # Keep backward-compatible issuance section
                epoch_data["issuance"] = issuance_result.to_dict()["issuance"]
                epoch_data["issuance"]["split"] = issuance_result.split.to_dict()
                epoch_data["issuance"]["validation"] = {
                    "total_events": issuance_result.total_events,
                    "valid_events": issuance_result.valid_events,
                    "quality_factor": round(issuance_result.quality_factor, 3),
                }
                print(f"[TOKENOMICS] Epoch {epoch_id}: {issuance_result.tokens_issued:.4f} BTFI "
                      f"(EI={issuance_result.ei_clamped:.2f}, QF={issuance_result.quality_factor:.2f})")
            except Exception as e:
                print(f"[WARN] Issuance calculation failed: {e}")

        # Sign the epoch if enabled
        if self.enable_signing and self._identity is not None:
            try:
                epoch = sign_epoch(epoch_data, samples, self._identity)
                print(f"[EPOCH] Signed epoch: {epoch['epoch_id']}")
                print(f"        Merkle root: {epoch['merkle_root'][:32]}...")
                # v1 spec: TAR is in summary.mitigation.total_tar_cfm_min
                tar_value = epoch['summary'].get('mitigation', {}).get('total_tar_cfm_min', total_tar)
                print(f"        Samples: {epoch['sample_count']}, TAR: {tar_value}")
            except Exception as e:
                print(f"[WARN] Failed to sign epoch: {e}")
                import traceback
                traceback.print_exc()
                epoch = {**epoch_data, "sample_count": len(samples)}
        else:
            epoch = {**epoch_data, "sample_count": len(samples)}

        self._store_epoch(epoch)

        # Build evidence pack if enabled
        if self.enable_evidence_packs and self._evidence_builder:
            try:
                device_identity = self.get_device_identity_info()
                evidence_pack = self._evidence_builder.build_pack(
                    epoch=epoch,
                    samples=samples,
                    device_identity=device_identity,
                )
                print(f"[EVIDENCE] Pack SHA256: {evidence_pack.zip_sha256}")
                if evidence_pack.uploaded:
                    print(f"[EVIDENCE] Uploaded to: {evidence_pack.storage_key}")
            except Exception as e:
                print(f"[WARN] Evidence pack error: {e}")

        # Submit epoch to backend verifier
        if self._verifier_client:
            try:
                response = self._verifier_client.send_epoch(epoch)
                if response:
                    print(f"[VERIFIER] Epoch submitted: {epoch['epoch_id']}")
                    print(f"[VERIFIER] Response: {response.get('status', 'unknown')}")
                else:
                    print(f"[VERIFIER] Epoch buffered for later sync: {epoch['epoch_id']}")
            except Exception as e:
                print(f"[WARN] Verifier submission error: {e}")

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

        # Stop verifier client
        if self._verifier_client:
            self._verifier_client.stop()

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
