# security/anomaly.py
"""
Anomaly detection for BeautiFi IoT telemetry.
Detects tampering, sensor failures, and suspicious patterns.
"""

import json
import math
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum
from collections import deque


class AnomalyType(Enum):
    """Types of anomalies that can be detected."""
    # Statistical anomalies
    OUT_OF_RANGE = "out_of_range"           # Value outside +-3 sigma
    IMPOSSIBLE_VALUE = "impossible_value"    # Physically impossible reading

    # Pattern anomalies
    FLATLINE = "flatline"                    # Same value repeated too many times
    SUDDEN_JUMP = "sudden_jump"              # Large change between samples

    # Integrity anomalies
    TIMESTAMP_VIOLATION = "timestamp_violation"  # Non-monotonic timestamps
    REPLAY_ATTACK = "replay_attack"              # Duplicate payload hash

    # Consistency anomalies
    CROSS_SENSOR_MISMATCH = "cross_sensor_mismatch"  # CFM/Power/RPM don't correlate

    # Calibration anomalies
    BASELINE_DRIFT = "baseline_drift"        # Gradual drift from baseline


class AnomalySeverity(Enum):
    """Severity levels for anomalies."""
    INFO = "info"           # Minor deviation, logged only
    WARNING = "warning"     # Notable deviation, flagged
    CRITICAL = "critical"   # Likely tampering or failure, blocks submission


@dataclass
class AnomalyReport:
    """Report of a detected anomaly."""
    anomaly_type: AnomalyType
    severity: AnomalySeverity
    field: str                          # Which field triggered it
    value: Any                          # The anomalous value
    expected_range: Optional[Tuple[float, float]] = None  # Expected min/max
    message: str = ""
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    sample_hash: Optional[str] = None   # Hash of the sample if available

    def to_dict(self) -> dict:
        return {
            "type": self.anomaly_type.value,
            "severity": self.severity.value,
            "field": self.field,
            "value": self.value,
            "expected_range": self.expected_range,
            "message": self.message,
            "timestamp": self.timestamp,
            "sample_hash": self.sample_hash,
        }


@dataclass
class BaselineStats:
    """Running statistics for baseline tracking."""
    count: int = 0
    mean: float = 0.0
    m2: float = 0.0  # For Welford's algorithm
    min_val: float = float('inf')
    max_val: float = float('-inf')

    @property
    def variance(self) -> float:
        if self.count < 2:
            return 0.0
        return self.m2 / (self.count - 1)

    @property
    def std_dev(self) -> float:
        return math.sqrt(self.variance)

    def update(self, value: float):
        """Update running statistics with new value (Welford's algorithm)."""
        self.count += 1
        delta = value - self.mean
        self.mean += delta / self.count
        delta2 = value - self.mean
        self.m2 += delta * delta2
        self.min_val = min(self.min_val, value)
        self.max_val = max(self.max_val, value)

    def to_dict(self) -> dict:
        return {
            "count": self.count,
            "mean": round(self.mean, 4),
            "std_dev": round(self.std_dev, 4),
            "min": round(self.min_val, 4) if self.min_val != float('inf') else None,
            "max": round(self.max_val, 4) if self.max_val != float('-inf') else None,
        }


class AnomalyDetector:
    """
    Detects anomalies in telemetry data for DUAN compliance.

    Features:
    - Baseline tracking with running statistics
    - Statistical outlier detection (+-3 sigma)
    - Flatline pattern detection
    - Replay attack detection (duplicate hashes)
    - Cross-sensor consistency checks
    - Timestamp monotonicity validation
    """

    # Physical limits for sensors
    PHYSICAL_LIMITS = {
        "cfm": (0, 1000),           # CFM can't be negative or absurdly high
        "rpm": (0, 5000),           # RPM limits
        "watts": (0, 200),          # Power limits
        "voc_ppb": (0, 10000),      # VOC limits
        "co2_ppm": (200, 10000),    # CO2 limits (outdoor ~420ppm)
        "temperature_c": (-20, 60), # Temperature limits
        "humidity_pct": (0, 100),   # Humidity is 0-100%
        "delta_p_pa": (-500, 500),  # Pressure differential
    }

    # Fields to track for baseline
    TRACKED_FIELDS = [
        "cfm", "rpm", "watts", "voc_ppb", "co2_ppm",
        "temperature_c", "humidity_pct", "delta_p_pa"
    ]

    # Flatline detection: how many identical readings before flagging
    FLATLINE_THRESHOLD = 10

    # Sudden jump: max allowed change as multiple of std_dev
    SUDDEN_JUMP_SIGMA = 5

    # Minimum samples before enabling statistical checks
    MIN_BASELINE_SAMPLES = 50

    def __init__(
        self,
        db_path: str = "anomaly.db",
        sigma_threshold: float = 3.0,
        enable_logging: bool = True,
    ):
        """
        Initialize the anomaly detector.

        Args:
            db_path: Path to SQLite database for anomaly logging
            sigma_threshold: Number of standard deviations for outlier detection
            enable_logging: Whether to log anomalies to database
        """
        self.db_path = db_path
        self.sigma_threshold = sigma_threshold
        self.enable_logging = enable_logging

        # Baseline statistics per field
        self._baselines: Dict[str, BaselineStats] = {
            field: BaselineStats() for field in self.TRACKED_FIELDS
        }

        # Recent values for pattern detection (rolling window)
        self._recent_values: Dict[str, deque] = {
            field: deque(maxlen=20) for field in self.TRACKED_FIELDS
        }

        # Replay detection: recent payload hashes
        self._recent_hashes: deque = deque(maxlen=1000)

        # Last timestamp for monotonicity check
        self._last_timestamp: Optional[datetime] = None

        # Thread safety
        self._lock = threading.Lock()

        # Anomaly counts
        self._anomaly_counts: Dict[str, int] = {t.value: 0 for t in AnomalyType}

        # Initialize database
        if self.enable_logging:
            self._init_db()

        print(f"[SECURITY] Anomaly detector initialized (sigma={sigma_threshold})")

    def _init_db(self):
        """Initialize SQLite database for anomaly logging."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS anomalies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                anomaly_type TEXT NOT NULL,
                severity TEXT NOT NULL,
                field TEXT,
                value TEXT,
                expected_range TEXT,
                message TEXT,
                sample_hash TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS baselines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                field TEXT UNIQUE NOT NULL,
                count INTEGER,
                mean REAL,
                std_dev REAL,
                min_val REAL,
                max_val REAL,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.commit()
        conn.close()

    def _log_anomaly(self, report: AnomalyReport):
        """Log an anomaly to the database."""
        if not self.enable_logging:
            return

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO anomalies (
                timestamp, anomaly_type, severity, field, value,
                expected_range, message, sample_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            report.timestamp,
            report.anomaly_type.value,
            report.severity.value,
            report.field,
            json.dumps(report.value),
            json.dumps(report.expected_range) if report.expected_range else None,
            report.message,
            report.sample_hash,
        ))

        conn.commit()
        conn.close()

    def _extract_values(self, sample: dict) -> Dict[str, float]:
        """Extract tracked values from a telemetry sample."""
        values = {}

        # Fan metrics
        if "fan" in sample:
            fan = sample["fan"]
            if "cfm" in fan:
                values["cfm"] = float(fan["cfm"])
            if "rpm" in fan:
                values["rpm"] = float(fan["rpm"])
            if "watts" in fan:
                values["watts"] = float(fan["watts"])

        # Environment metrics
        if "environment" in sample:
            env = sample["environment"]
            if "voc_ppb" in env:
                values["voc_ppb"] = float(env["voc_ppb"])
            if "co2_ppm" in env:
                values["co2_ppm"] = float(env["co2_ppm"])
            if "temperature_c" in env:
                values["temperature_c"] = float(env["temperature_c"])
            if "humidity_pct" in env:
                values["humidity_pct"] = float(env["humidity_pct"])
            if "delta_p_pa" in env:
                values["delta_p_pa"] = float(env["delta_p_pa"])

        return values

    def check_sample(self, sample: dict) -> List[AnomalyReport]:
        """
        Check a telemetry sample for anomalies.

        Args:
            sample: Telemetry sample dict

        Returns:
            List of AnomalyReport objects (empty if no anomalies)
        """
        anomalies = []

        with self._lock:
            # Extract values
            values = self._extract_values(sample)

            # Get sample hash if signed
            sample_hash = None
            if "_signing" in sample:
                sample_hash = sample["_signing"].get("payload_hash")

            # 1. Check timestamp monotonicity
            ts_anomaly = self._check_timestamp(sample)
            if ts_anomaly:
                anomalies.append(ts_anomaly)

            # 2. Check for replay attack
            if sample_hash:
                replay_anomaly = self._check_replay(sample_hash)
                if replay_anomaly:
                    anomalies.append(replay_anomaly)

            # 3. Check each value
            for field, value in values.items():
                # Physical limits check
                limit_anomaly = self._check_physical_limits(field, value, sample_hash)
                if limit_anomaly:
                    anomalies.append(limit_anomaly)

                # Statistical check (only if we have enough baseline)
                if self._baselines[field].count >= self.MIN_BASELINE_SAMPLES:
                    stat_anomaly = self._check_statistical(field, value, sample_hash)
                    if stat_anomaly:
                        anomalies.append(stat_anomaly)

                    # Sudden jump check
                    jump_anomaly = self._check_sudden_jump(field, value, sample_hash)
                    if jump_anomaly:
                        anomalies.append(jump_anomaly)

                # Flatline check
                flatline_anomaly = self._check_flatline(field, value, sample_hash)
                if flatline_anomaly:
                    anomalies.append(flatline_anomaly)

                # Update baseline and recent values
                self._baselines[field].update(value)
                self._recent_values[field].append(value)

            # 4. Cross-sensor consistency check
            if all(f in values for f in ["cfm", "watts", "rpm"]):
                consistency_anomalies = self._check_cross_sensor(values, sample_hash)
                anomalies.extend(consistency_anomalies)

            # Log anomalies
            for anomaly in anomalies:
                self._anomaly_counts[anomaly.anomaly_type.value] += 1
                self._log_anomaly(anomaly)

                # Print warnings/criticals
                if anomaly.severity in [AnomalySeverity.WARNING, AnomalySeverity.CRITICAL]:
                    print(f"[ANOMALY] {anomaly.severity.value.upper()}: {anomaly.message}")

        return anomalies

    def _check_timestamp(self, sample: dict) -> Optional[AnomalyReport]:
        """Check for timestamp monotonicity violations."""
        if "timestamp" not in sample:
            return None

        try:
            ts_str = sample["timestamp"].replace("Z", "+00:00")
            current_ts = datetime.fromisoformat(ts_str)

            if self._last_timestamp is not None:
                if current_ts <= self._last_timestamp:
                    report = AnomalyReport(
                        anomaly_type=AnomalyType.TIMESTAMP_VIOLATION,
                        severity=AnomalySeverity.CRITICAL,
                        field="timestamp",
                        value=sample["timestamp"],
                        message=f"Non-monotonic timestamp: {current_ts} <= {self._last_timestamp}",
                    )
                    return report

            self._last_timestamp = current_ts

        except Exception as e:
            return AnomalyReport(
                anomaly_type=AnomalyType.TIMESTAMP_VIOLATION,
                severity=AnomalySeverity.WARNING,
                field="timestamp",
                value=sample.get("timestamp"),
                message=f"Invalid timestamp format: {e}",
            )

        return None

    def _check_replay(self, payload_hash: str) -> Optional[AnomalyReport]:
        """Check for replay attacks (duplicate hashes)."""
        if payload_hash in self._recent_hashes:
            return AnomalyReport(
                anomaly_type=AnomalyType.REPLAY_ATTACK,
                severity=AnomalySeverity.CRITICAL,
                field="payload_hash",
                value=payload_hash,
                message=f"Duplicate payload hash detected - possible replay attack",
                sample_hash=payload_hash,
            )

        self._recent_hashes.append(payload_hash)
        return None

    def _check_physical_limits(
        self, field: str, value: float, sample_hash: Optional[str]
    ) -> Optional[AnomalyReport]:
        """Check if value is within physical limits."""
        if field not in self.PHYSICAL_LIMITS:
            return None

        min_val, max_val = self.PHYSICAL_LIMITS[field]

        if value < min_val or value > max_val:
            return AnomalyReport(
                anomaly_type=AnomalyType.IMPOSSIBLE_VALUE,
                severity=AnomalySeverity.CRITICAL,
                field=field,
                value=value,
                expected_range=(min_val, max_val),
                message=f"{field}={value} is outside physical limits [{min_val}, {max_val}]",
                sample_hash=sample_hash,
            )

        return None

    def _check_statistical(
        self, field: str, value: float, sample_hash: Optional[str]
    ) -> Optional[AnomalyReport]:
        """Check if value is within statistical norms (+-N sigma)."""
        stats = self._baselines[field]

        if stats.std_dev == 0:
            return None

        z_score = abs(value - stats.mean) / stats.std_dev

        if z_score > self.sigma_threshold:
            expected_min = stats.mean - self.sigma_threshold * stats.std_dev
            expected_max = stats.mean + self.sigma_threshold * stats.std_dev

            severity = AnomalySeverity.WARNING
            if z_score > self.sigma_threshold * 2:
                severity = AnomalySeverity.CRITICAL

            return AnomalyReport(
                anomaly_type=AnomalyType.OUT_OF_RANGE,
                severity=severity,
                field=field,
                value=value,
                expected_range=(round(expected_min, 2), round(expected_max, 2)),
                message=f"{field}={value} is {z_score:.1f} sigma from mean ({stats.mean:.2f})",
                sample_hash=sample_hash,
            )

        return None

    def _check_sudden_jump(
        self, field: str, value: float, sample_hash: Optional[str]
    ) -> Optional[AnomalyReport]:
        """Check for sudden large changes between consecutive samples."""
        recent = self._recent_values[field]
        if len(recent) == 0:
            return None

        last_value = recent[-1]
        stats = self._baselines[field]

        if stats.std_dev == 0:
            return None

        change = abs(value - last_value)
        change_sigma = change / stats.std_dev

        if change_sigma > self.SUDDEN_JUMP_SIGMA:
            return AnomalyReport(
                anomaly_type=AnomalyType.SUDDEN_JUMP,
                severity=AnomalySeverity.WARNING,
                field=field,
                value=value,
                expected_range=(last_value - stats.std_dev * 2, last_value + stats.std_dev * 2),
                message=f"{field} jumped from {last_value:.2f} to {value:.2f} ({change_sigma:.1f} sigma)",
                sample_hash=sample_hash,
            )

        return None

    def _check_flatline(
        self, field: str, value: float, sample_hash: Optional[str]
    ) -> Optional[AnomalyReport]:
        """Check for flatline patterns (same value repeated)."""
        recent = self._recent_values[field]

        # Count consecutive identical values
        identical_count = 0
        for past_value in reversed(recent):
            if abs(past_value - value) < 0.001:  # Tolerance for floating point
                identical_count += 1
            else:
                break

        if identical_count >= self.FLATLINE_THRESHOLD:
            return AnomalyReport(
                anomaly_type=AnomalyType.FLATLINE,
                severity=AnomalySeverity.WARNING,
                field=field,
                value=value,
                message=f"{field}={value} has been identical for {identical_count + 1} consecutive readings",
                sample_hash=sample_hash,
            )

        return None

    def _check_cross_sensor(
        self, values: Dict[str, float], sample_hash: Optional[str]
    ) -> List[AnomalyReport]:
        """Check cross-sensor consistency (CFM vs Power vs RPM)."""
        anomalies = []

        cfm = values.get("cfm", 0)
        watts = values.get("watts", 0)
        rpm = values.get("rpm", 0)

        # Check: If CFM > 0, power should be > 0
        if cfm > 10 and watts < 1:
            anomalies.append(AnomalyReport(
                anomaly_type=AnomalyType.CROSS_SENSOR_MISMATCH,
                severity=AnomalySeverity.WARNING,
                field="cfm_vs_watts",
                value={"cfm": cfm, "watts": watts},
                message=f"CFM={cfm} but watts={watts} - fan running with no power?",
                sample_hash=sample_hash,
            ))

        # Check: If CFM > 0, RPM should be > 0
        if cfm > 10 and rpm < 100:
            anomalies.append(AnomalyReport(
                anomaly_type=AnomalyType.CROSS_SENSOR_MISMATCH,
                severity=AnomalySeverity.WARNING,
                field="cfm_vs_rpm",
                value={"cfm": cfm, "rpm": rpm},
                message=f"CFM={cfm} but RPM={rpm} - airflow with no rotation?",
                sample_hash=sample_hash,
            ))

        # Check: If watts > 5, RPM should be > 0
        if watts > 5 and rpm < 100:
            anomalies.append(AnomalyReport(
                anomaly_type=AnomalyType.CROSS_SENSOR_MISMATCH,
                severity=AnomalySeverity.WARNING,
                field="watts_vs_rpm",
                value={"watts": watts, "rpm": rpm},
                message=f"Watts={watts} but RPM={rpm} - power draw with no rotation?",
                sample_hash=sample_hash,
            ))

        # Check efficiency bounds (CFM/Watt should be reasonable)
        if watts > 5:
            efficiency = cfm / watts
            if efficiency > 20:  # Unrealistically efficient
                anomalies.append(AnomalyReport(
                    anomaly_type=AnomalyType.CROSS_SENSOR_MISMATCH,
                    severity=AnomalySeverity.WARNING,
                    field="efficiency",
                    value={"cfm": cfm, "watts": watts, "efficiency": efficiency},
                    message=f"Efficiency {efficiency:.1f} CFM/W is unrealistically high",
                    sample_hash=sample_hash,
                ))

        return anomalies

    def get_baseline_stats(self) -> Dict[str, dict]:
        """Get current baseline statistics for all fields."""
        with self._lock:
            return {
                field: stats.to_dict()
                for field, stats in self._baselines.items()
            }

    def get_anomaly_counts(self) -> Dict[str, int]:
        """Get counts of each anomaly type detected."""
        with self._lock:
            return dict(self._anomaly_counts)

    def get_recent_anomalies(self, limit: int = 50) -> List[dict]:
        """Get recent anomalies from the database."""
        if not self.enable_logging:
            return []

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT timestamp, anomaly_type, severity, field, value, message
            FROM anomalies
            ORDER BY id DESC LIMIT ?
        """, (limit,))

        rows = cursor.fetchall()
        conn.close()

        return [
            {
                "timestamp": row[0],
                "type": row[1],
                "severity": row[2],
                "field": row[3],
                "value": json.loads(row[4]) if row[4] else None,
                "message": row[5],
            }
            for row in rows
        ]

    def save_baselines(self):
        """Save current baselines to database."""
        if not self.enable_logging:
            return

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        with self._lock:
            for field, stats in self._baselines.items():
                cursor.execute("""
                    INSERT OR REPLACE INTO baselines (
                        field, count, mean, std_dev, min_val, max_val, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    field,
                    stats.count,
                    stats.mean,
                    stats.std_dev,
                    stats.min_val if stats.min_val != float('inf') else None,
                    stats.max_val if stats.max_val != float('-inf') else None,
                    datetime.utcnow().isoformat() + "Z",
                ))

        conn.commit()
        conn.close()

    def load_baselines(self):
        """Load baselines from database."""
        if not self.enable_logging:
            return

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("SELECT field, count, mean, std_dev, min_val, max_val FROM baselines")
        rows = cursor.fetchall()
        conn.close()

        with self._lock:
            for row in rows:
                field, count, mean, std_dev, min_val, max_val = row
                if field in self._baselines:
                    stats = self._baselines[field]
                    stats.count = count or 0
                    stats.mean = mean or 0.0
                    # Reconstruct m2 from std_dev (approximate)
                    if count and count > 1:
                        stats.m2 = (std_dev ** 2) * (count - 1) if std_dev else 0.0
                    stats.min_val = min_val if min_val is not None else float('inf')
                    stats.max_val = max_val if max_val is not None else float('-inf')

        print(f"[SECURITY] Loaded baselines for {len(rows)} fields")

    def has_critical_anomalies(self, anomalies: List[AnomalyReport]) -> bool:
        """Check if any anomalies are critical (should block submission)."""
        return any(a.severity == AnomalySeverity.CRITICAL for a in anomalies)

    def get_status(self) -> dict:
        """Get detector status summary."""
        with self._lock:
            return {
                "baseline_samples": self._baselines["cfm"].count,
                "baseline_ready": self._baselines["cfm"].count >= self.MIN_BASELINE_SAMPLES,
                "sigma_threshold": self.sigma_threshold,
                "anomaly_counts": dict(self._anomaly_counts),
                "total_anomalies": sum(self._anomaly_counts.values()),
            }


# Quick test
if __name__ == "__main__":
    print("Testing AnomalyDetector...")
    print("=" * 60)

    detector = AnomalyDetector(
        db_path="test_anomaly.db",
        sigma_threshold=3.0,
    )

    # Generate some normal samples to build baseline
    print("\n1. Building baseline with normal samples...")
    import random
    for i in range(60):
        sample = {
            "timestamp": f"2026-01-20T12:{i:02d}:00Z",
            "device_id": "btfi-test-001",
            "fan": {
                "cfm": 250 + random.gauss(0, 5),
                "rpm": 1500 + random.gauss(0, 20),
                "watts": 28 + random.gauss(0, 1),
            },
            "environment": {
                "voc_ppb": 150 + random.gauss(0, 10),
                "co2_ppm": 450 + random.gauss(0, 15),
                "temperature_c": 24 + random.gauss(0, 0.3),
                "humidity_pct": 50 + random.gauss(0, 2),
                "delta_p_pa": 125 + random.gauss(0, 3),
            },
        }
        anomalies = detector.check_sample(sample)

    print(f"   Baseline ready: {detector.get_status()['baseline_ready']}")
    print(f"   Baseline stats (CFM): {detector.get_baseline_stats()['cfm']}")

    # Test anomaly detection
    print("\n2. Testing anomaly detection...")

    # Test impossible value
    print("\n   a) Impossible value (negative CFM)...")
    bad_sample = {
        "timestamp": "2026-01-20T13:00:00Z",
        "fan": {"cfm": -50, "rpm": 1500, "watts": 28},
        "environment": {"voc_ppb": 150, "co2_ppm": 450, "temperature_c": 24, "humidity_pct": 50, "delta_p_pa": 125},
    }
    anomalies = detector.check_sample(bad_sample)
    print(f"      Found {len(anomalies)} anomalies")
    for a in anomalies:
        print(f"      - {a.anomaly_type.value}: {a.message}")

    # Test statistical outlier
    print("\n   b) Statistical outlier (CFM way too high)...")
    bad_sample = {
        "timestamp": "2026-01-20T13:01:00Z",
        "fan": {"cfm": 500, "rpm": 1500, "watts": 28},
        "environment": {"voc_ppb": 150, "co2_ppm": 450, "temperature_c": 24, "humidity_pct": 50, "delta_p_pa": 125},
    }
    anomalies = detector.check_sample(bad_sample)
    print(f"      Found {len(anomalies)} anomalies")
    for a in anomalies:
        print(f"      - {a.anomaly_type.value}: {a.message}")

    # Test cross-sensor mismatch
    print("\n   c) Cross-sensor mismatch (CFM with no power)...")
    bad_sample = {
        "timestamp": "2026-01-20T13:02:00Z",
        "fan": {"cfm": 250, "rpm": 0, "watts": 0},
        "environment": {"voc_ppb": 150, "co2_ppm": 450, "temperature_c": 24, "humidity_pct": 50, "delta_p_pa": 125},
    }
    anomalies = detector.check_sample(bad_sample)
    print(f"      Found {len(anomalies)} anomalies")
    for a in anomalies:
        print(f"      - {a.anomaly_type.value}: {a.message}")

    # Test timestamp violation
    print("\n   d) Timestamp violation (going backwards)...")
    bad_sample = {
        "timestamp": "2026-01-20T12:30:00Z",  # Earlier than last
        "fan": {"cfm": 250, "rpm": 1500, "watts": 28},
        "environment": {"voc_ppb": 150, "co2_ppm": 450, "temperature_c": 24, "humidity_pct": 50, "delta_p_pa": 125},
    }
    anomalies = detector.check_sample(bad_sample)
    print(f"      Found {len(anomalies)} anomalies")
    for a in anomalies:
        print(f"      - {a.anomaly_type.value}: {a.message}")

    # Summary
    print("\n3. Final status...")
    status = detector.get_status()
    print(f"   Total anomalies: {status['total_anomalies']}")
    print(f"   Anomaly counts: {status['anomaly_counts']}")

    # Cleanup
    import os
    if os.path.exists("test_anomaly.db"):
        os.remove("test_anomaly.db")

    print("\nAnomalyDetector test complete!")
