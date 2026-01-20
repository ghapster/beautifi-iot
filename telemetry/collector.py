# telemetry/collector.py
"""
Telemetry collection service for BeautiFi IoT.
Samples sensor data at configured intervals and buffers locally.
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


class TelemetryCollector:
    """
    Background service that collects telemetry at regular intervals.

    Features:
    - Configurable sampling interval (default 12 seconds)
    - SQLite buffer for local storage
    - Epoch formation (bundles samples into 1-hour epochs)
    - Callback support for real-time streaming
    """

    def __init__(
        self,
        db_path: str = "telemetry.db",
        pwm_getter: Optional[Callable[[], float]] = None,
    ):
        """
        Initialize the telemetry collector.

        Args:
            db_path: Path to SQLite database for buffering
            pwm_getter: Callback function that returns current PWM (0-100)
        """
        self.db_path = db_path
        self.pwm_getter = pwm_getter or (lambda: 0)

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

        # Current epoch tracking
        self._current_epoch_start: Optional[datetime] = None
        self._current_epoch_samples: List[dict] = []

        # Initialize database
        self._init_db()

    def _init_db(self):
        """Initialize SQLite database for telemetry buffering."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Telemetry samples table
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
                raw_json TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Epochs table
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
                summary_json TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.commit()
        conn.close()

    def _store_sample(self, sample: dict):
        """Store a telemetry sample in the database."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO samples (
                timestamp, device_id, pwm_percent, cfm, rpm, watts,
                voc_ppb, co2_ppm, temperature_c, humidity_pct, delta_p_pa,
                tar_cfm_min, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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

        cursor.execute("""
            INSERT OR REPLACE INTO epochs (
                epoch_id, device_id, start_time, end_time, sample_count,
                total_tar, avg_cfm, avg_watts, avg_voc, total_energy_wh, summary_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
        """Finalize the current epoch and store it."""
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

        epoch = {
            "epoch_id": f"ep-{start_time.strftime('%Y%m%d%H')}-{DEVICE_ID}",
            "device_id": DEVICE_ID,
            "start_time": start_time.isoformat() + "Z",
            "end_time": end_time.isoformat() + "Z",
            "sample_count": len(samples),
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

        self._store_epoch(epoch)
        print(f"📦 Epoch finalized: {epoch['epoch_id']} - {epoch['summary']['total_tar_cfm_min']} TAR")

        # Reset for next epoch
        self._current_epoch_start = None
        self._current_epoch_samples = []

    def _collection_loop(self):
        """Main collection loop running in background thread."""
        print(f"🚀 Telemetry collector started (interval: {SAMPLE_INTERVAL_SECONDS}s)")

        while self._running:
            try:
                # Get current PWM from the fan controller
                current_pwm = self.pwm_getter()

                # Read sensors
                sample = self.sensors.read_all(current_pwm)

                # Store locally
                self._store_sample(sample)

                # Check/update epoch
                self._check_epoch(sample)

                # Notify callbacks
                for callback in self._callbacks:
                    try:
                        callback(sample)
                    except Exception as e:
                        print(f"⚠️ Callback error: {e}")

                # Log periodically
                print(f"📊 Sample: CFM={sample['fan']['cfm']}, VOC={sample['environment']['voc_ppb']}ppb, "
                      f"PWM={current_pwm}%")

            except Exception as e:
                print(f"❌ Collection error: {e}")

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

        print("🛑 Telemetry collector stopped")

    def add_callback(self, callback: Callable[[dict], None]):
        """Add a callback function to receive real-time samples."""
        self._callbacks.append(callback)

    def remove_callback(self, callback: Callable[[dict], None]):
        """Remove a callback function."""
        if callback in self._callbacks:
            self._callbacks.remove(callback)

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


# Quick test
if __name__ == "__main__":
    print("Testing TelemetryCollector (5 samples at 50% PWM)")
    print("=" * 60)

    collector = TelemetryCollector(
        db_path="test_telemetry.db",
        pwm_getter=lambda: 50  # Fixed 50% for testing
    )

    # Add a print callback
    collector.add_callback(lambda s: print(f"  → Callback received: VOC={s['environment']['voc_ppb']}"))

    collector.start()
    time.sleep(15)  # Collect a few samples
    collector.stop()

    print("\nRecent samples:")
    for sample in collector.get_recent_samples(5):
        print(f"  {sample['timestamp']}: CFM={sample['fan']['cfm']}")
