# network/verifier_client.py
"""
Verifier client for BeautiFi IoT DUAN compliance.
Streams telemetry and submits epochs to the verifier service.
"""

import json
import time
import threading
import sqlite3
from datetime import datetime, timedelta
from typing import Optional, Callable, List, Dict, Any
from dataclasses import dataclass, field
from enum import Enum
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class ConnectionState(Enum):
    """Verifier connection states."""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    ERROR = "error"


@dataclass
class SyncStatus:
    """Current synchronization status."""
    connection_state: ConnectionState = ConnectionState.DISCONNECTED
    last_sample_sent: Optional[datetime] = None
    last_epoch_sent: Optional[datetime] = None
    last_error: Optional[str] = None
    last_error_time: Optional[datetime] = None
    samples_pending: int = 0
    epochs_pending: int = 0
    samples_sent_total: int = 0
    epochs_sent_total: int = 0
    retry_count: int = 0
    next_retry: Optional[datetime] = None

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dict."""
        return {
            "connection_state": self.connection_state.value,
            "last_sample_sent": self.last_sample_sent.isoformat() if self.last_sample_sent else None,
            "last_epoch_sent": self.last_epoch_sent.isoformat() if self.last_epoch_sent else None,
            "last_error": self.last_error,
            "last_error_time": self.last_error_time.isoformat() if self.last_error_time else None,
            "samples_pending": self.samples_pending,
            "epochs_pending": self.epochs_pending,
            "samples_sent_total": self.samples_sent_total,
            "epochs_sent_total": self.epochs_sent_total,
            "retry_count": self.retry_count,
            "next_retry": self.next_retry.isoformat() if self.next_retry else None,
            "is_online": self.connection_state == ConnectionState.CONNECTED,
        }


class VerifierClient:
    """
    Client for streaming telemetry and epochs to the DUAN verifier service.

    Features:
    - Real-time telemetry streaming via HTTP POST
    - Epoch submission with verification response
    - Exponential backoff retry logic
    - Offline buffering with SQLite
    - Automatic sync when connection restored
    """

    # Retry configuration
    MAX_RETRIES = 5
    INITIAL_BACKOFF_SECONDS = 1
    MAX_BACKOFF_SECONDS = 300  # 5 minutes
    BACKOFF_MULTIPLIER = 2

    # Buffer limits
    MAX_BUFFERED_SAMPLES = 10000
    MAX_BUFFERED_EPOCHS = 100

    def __init__(
        self,
        verifier_url: str,
        device_id: str,
        api_key: Optional[str] = None,
        buffer_db_path: str = "sync_buffer.db",
        auto_sync: bool = True,
        sync_interval_seconds: int = 30,
    ):
        """
        Initialize the verifier client.

        Args:
            verifier_url: Base URL of the verifier service (e.g., https://api.beautifi.io)
            device_id: This device's ID for authentication
            api_key: Optional API key for authentication
            buffer_db_path: Path to SQLite database for offline buffering
            auto_sync: Enable automatic background sync
            sync_interval_seconds: How often to attempt sync of buffered data
        """
        self.verifier_url = verifier_url.rstrip('/')
        self.device_id = device_id
        self.api_key = api_key
        self.buffer_db_path = buffer_db_path
        self.auto_sync = auto_sync
        self.sync_interval_seconds = sync_interval_seconds

        # Status tracking
        self.status = SyncStatus()
        self._status_lock = threading.Lock()

        # Background sync
        self._running = False
        self._sync_thread: Optional[threading.Thread] = None

        # HTTP session with retry
        self._session = self._create_session()

        # Callbacks
        self._on_verification: Optional[Callable[[dict], None]] = None

        # Initialize buffer database
        self._init_buffer_db()

        print(f"[VERIFIER] Client initialized for {self.verifier_url}")
        print(f"[VERIFIER] Device ID: {self.device_id}")

    def _create_session(self) -> requests.Session:
        """Create HTTP session with retry configuration."""
        session = requests.Session()

        # Configure retries for transient errors
        retry_strategy = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=[500, 502, 503, 504],
            allowed_methods=["POST", "GET"],
        )

        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)

        # Set default headers
        session.headers.update({
            "Content-Type": "application/json",
            "X-Device-ID": self.device_id,
            "User-Agent": f"BeautiFi-IoT/{self.device_id}",
        })

        if self.api_key:
            session.headers["Authorization"] = f"Bearer {self.api_key}"

        return session

    def _init_buffer_db(self):
        """Initialize SQLite buffer for offline data."""
        conn = sqlite3.connect(self.buffer_db_path)
        cursor = conn.cursor()

        # Pending samples table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS pending_samples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                attempts INTEGER DEFAULT 0,
                last_attempt TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Pending epochs table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS pending_epochs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                epoch_id TEXT UNIQUE NOT NULL,
                payload_json TEXT NOT NULL,
                attempts INTEGER DEFAULT 0,
                last_attempt TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Verification responses table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS verifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                epoch_id TEXT NOT NULL,
                status TEXT NOT NULL,
                response_json TEXT,
                received_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.commit()
        conn.close()

        # Update pending counts
        self._update_pending_counts()

    def _update_pending_counts(self):
        """Update status with current pending counts."""
        conn = sqlite3.connect(self.buffer_db_path)
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM pending_samples")
        samples_pending = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM pending_epochs")
        epochs_pending = cursor.fetchone()[0]

        conn.close()

        with self._status_lock:
            self.status.samples_pending = samples_pending
            self.status.epochs_pending = epochs_pending

    # ============================================
    # Public API - Sending Data
    # ============================================

    def send_sample(self, sample: dict) -> bool:
        """
        Send a telemetry sample to the verifier.

        If offline, buffers the sample for later sync.

        Args:
            sample: Signed telemetry sample

        Returns:
            True if sent successfully, False if buffered
        """
        # Try to send immediately
        success = self._post_sample(sample)

        if success:
            with self._status_lock:
                self.status.last_sample_sent = datetime.utcnow()
                self.status.samples_sent_total += 1
                self.status.connection_state = ConnectionState.CONNECTED
                self.status.retry_count = 0
            return True
        else:
            # Buffer for later
            self._buffer_sample(sample)
            return False

    def send_epoch(self, epoch: dict) -> Optional[dict]:
        """
        Submit a completed epoch to the verifier.

        Args:
            epoch: Signed epoch with Merkle root

        Returns:
            Verification response if successful, None if buffered
        """
        # Try to send immediately
        response = self._post_epoch(epoch)

        if response:
            with self._status_lock:
                self.status.last_epoch_sent = datetime.utcnow()
                self.status.epochs_sent_total += 1
                self.status.connection_state = ConnectionState.CONNECTED
                self.status.retry_count = 0

            # Store verification response
            self._store_verification(epoch.get('epoch_id'), response)

            # Notify callback
            if self._on_verification:
                try:
                    self._on_verification(response)
                except Exception as e:
                    print(f"[VERIFIER] Callback error: {e}")

            return response
        else:
            # Buffer for later
            self._buffer_epoch(epoch)
            return None

    def get_status(self) -> SyncStatus:
        """Get current sync status."""
        self._update_pending_counts()
        with self._status_lock:
            return self.status

    def get_verifications(self, limit: int = 10) -> List[dict]:
        """Get recent verification responses."""
        conn = sqlite3.connect(self.buffer_db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT epoch_id, status, response_json, received_at
            FROM verifications
            ORDER BY id DESC LIMIT ?
        """, (limit,))

        rows = cursor.fetchall()
        conn.close()

        return [
            {
                "epoch_id": row[0],
                "status": row[1],
                "response": json.loads(row[2]) if row[2] else None,
                "received_at": row[3],
            }
            for row in rows
        ]

    def set_verification_callback(self, callback: Callable[[dict], None]):
        """Set callback for verification responses."""
        self._on_verification = callback

    # ============================================
    # HTTP Operations
    # ============================================

    def _post_sample(self, sample: dict) -> bool:
        """POST a sample to the verifier."""
        url = f"{self.verifier_url}/api/telemetry/stream"

        try:
            response = self._session.post(
                url,
                json=sample,
                timeout=10,
            )

            if response.status_code == 200 or response.status_code == 201:
                return True
            else:
                self._record_error(f"HTTP {response.status_code}: {response.text[:100]}")
                return False

        except requests.exceptions.ConnectionError as e:
            self._record_error(f"Connection error: {e}")
            return False
        except requests.exceptions.Timeout:
            self._record_error("Request timeout")
            return False
        except Exception as e:
            self._record_error(f"Request error: {e}")
            return False

    def _post_epoch(self, epoch: dict) -> Optional[dict]:
        """POST an epoch to the verifier and return response."""
        url = f"{self.verifier_url}/api/epochs/submit"

        try:
            response = self._session.post(
                url,
                json=epoch,
                timeout=30,
            )

            if response.status_code == 200 or response.status_code == 201:
                return response.json()
            else:
                self._record_error(f"HTTP {response.status_code}: {response.text[:100]}")
                return None

        except requests.exceptions.ConnectionError as e:
            self._record_error(f"Connection error: {e}")
            return None
        except requests.exceptions.Timeout:
            self._record_error("Request timeout")
            return None
        except Exception as e:
            self._record_error(f"Request error: {e}")
            return None

    def check_connection(self) -> bool:
        """Check if verifier is reachable."""
        url = f"{self.verifier_url}/api/device/{self.device_id}/status"

        try:
            response = self._session.get(url, timeout=5)
            return response.status_code == 200
        except Exception:
            return False

    def _record_error(self, message: str):
        """Record an error in status."""
        with self._status_lock:
            self.status.last_error = message
            self.status.last_error_time = datetime.utcnow()
            self.status.connection_state = ConnectionState.ERROR
            self.status.retry_count += 1

            # Calculate next retry with exponential backoff
            backoff = min(
                self.INITIAL_BACKOFF_SECONDS * (self.BACKOFF_MULTIPLIER ** self.status.retry_count),
                self.MAX_BACKOFF_SECONDS
            )
            self.status.next_retry = datetime.utcnow() + timedelta(seconds=backoff)

        print(f"[VERIFIER] Error: {message}")

    # ============================================
    # Buffering Operations
    # ============================================

    def _buffer_sample(self, sample: dict):
        """Buffer a sample for later sync."""
        conn = sqlite3.connect(self.buffer_db_path)
        cursor = conn.cursor()

        # Check buffer limit
        cursor.execute("SELECT COUNT(*) FROM pending_samples")
        count = cursor.fetchone()[0]

        if count >= self.MAX_BUFFERED_SAMPLES:
            # Remove oldest samples
            cursor.execute(f"""
                DELETE FROM pending_samples WHERE id IN (
                    SELECT id FROM pending_samples ORDER BY id ASC LIMIT {count - self.MAX_BUFFERED_SAMPLES + 1}
                )
            """)

        cursor.execute("""
            INSERT INTO pending_samples (timestamp, payload_json)
            VALUES (?, ?)
        """, (
            sample.get('timestamp', datetime.utcnow().isoformat()),
            json.dumps(sample),
        ))

        conn.commit()
        conn.close()

        with self._status_lock:
            self.status.samples_pending += 1

    def _buffer_epoch(self, epoch: dict):
        """Buffer an epoch for later sync."""
        conn = sqlite3.connect(self.buffer_db_path)
        cursor = conn.cursor()

        try:
            cursor.execute("""
                INSERT OR REPLACE INTO pending_epochs (epoch_id, payload_json)
                VALUES (?, ?)
            """, (
                epoch.get('epoch_id'),
                json.dumps(epoch),
            ))

            conn.commit()
        except Exception as e:
            print(f"[VERIFIER] Buffer error: {e}")
        finally:
            conn.close()

        with self._status_lock:
            self.status.epochs_pending += 1

    def _store_verification(self, epoch_id: str, response: dict):
        """Store a verification response."""
        conn = sqlite3.connect(self.buffer_db_path)
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO verifications (epoch_id, status, response_json)
            VALUES (?, ?, ?)
        """, (
            epoch_id,
            response.get('status', 'unknown'),
            json.dumps(response),
        ))

        conn.commit()
        conn.close()

    # ============================================
    # Background Sync
    # ============================================

    def start(self):
        """Start background sync thread."""
        if self._running:
            return

        self._running = True
        self._sync_thread = threading.Thread(target=self._sync_loop, daemon=True)
        self._sync_thread.start()
        print(f"[VERIFIER] Background sync started (interval: {self.sync_interval_seconds}s)")

    def stop(self):
        """Stop background sync thread."""
        self._running = False
        if self._sync_thread:
            self._sync_thread.join(timeout=5)
            self._sync_thread = None
        print("[VERIFIER] Background sync stopped")

    def _sync_loop(self):
        """Background loop to sync buffered data."""
        while self._running:
            try:
                # Check if we should retry
                with self._status_lock:
                    if self.status.next_retry and datetime.utcnow() < self.status.next_retry:
                        time.sleep(1)
                        continue

                # Try to sync pending data
                self._sync_pending()

            except Exception as e:
                print(f"[VERIFIER] Sync loop error: {e}")

            time.sleep(self.sync_interval_seconds)

    def _sync_pending(self):
        """Attempt to sync all pending data."""
        # First check connection
        if not self.check_connection():
            with self._status_lock:
                if self.status.connection_state != ConnectionState.DISCONNECTED:
                    self.status.connection_state = ConnectionState.DISCONNECTED
                    print("[VERIFIER] Verifier unreachable, will retry...")
            return

        with self._status_lock:
            self.status.connection_state = ConnectionState.CONNECTED
            self.status.retry_count = 0

        # Sync pending samples
        self._sync_pending_samples()

        # Sync pending epochs
        self._sync_pending_epochs()

    def _sync_pending_samples(self):
        """Sync buffered samples."""
        conn = sqlite3.connect(self.buffer_db_path)
        cursor = conn.cursor()

        # Get oldest pending samples (batch of 50)
        cursor.execute("""
            SELECT id, payload_json FROM pending_samples
            ORDER BY id ASC LIMIT 50
        """)

        rows = cursor.fetchall()
        conn.close()

        if not rows:
            return

        synced_ids = []

        for row_id, payload_json in rows:
            sample = json.loads(payload_json)

            if self._post_sample(sample):
                synced_ids.append(row_id)
                with self._status_lock:
                    self.status.samples_sent_total += 1
            else:
                # Stop on first failure
                break

        # Remove synced samples
        if synced_ids:
            conn = sqlite3.connect(self.buffer_db_path)
            cursor = conn.cursor()
            cursor.execute(f"""
                DELETE FROM pending_samples WHERE id IN ({','.join('?' * len(synced_ids))})
            """, synced_ids)
            conn.commit()
            conn.close()

            print(f"[VERIFIER] Synced {len(synced_ids)} buffered samples")

        self._update_pending_counts()

    def _sync_pending_epochs(self):
        """Sync buffered epochs."""
        conn = sqlite3.connect(self.buffer_db_path)
        cursor = conn.cursor()

        # Get pending epochs
        cursor.execute("""
            SELECT id, epoch_id, payload_json FROM pending_epochs
            ORDER BY id ASC LIMIT 10
        """)

        rows = cursor.fetchall()
        conn.close()

        if not rows:
            return

        synced_ids = []

        for row_id, epoch_id, payload_json in rows:
            epoch = json.loads(payload_json)

            response = self._post_epoch(epoch)
            if response:
                synced_ids.append(row_id)
                self._store_verification(epoch_id, response)

                with self._status_lock:
                    self.status.epochs_sent_total += 1

                if self._on_verification:
                    try:
                        self._on_verification(response)
                    except Exception as e:
                        print(f"[VERIFIER] Callback error: {e}")
            else:
                # Stop on first failure
                break

        # Remove synced epochs
        if synced_ids:
            conn = sqlite3.connect(self.buffer_db_path)
            cursor = conn.cursor()
            cursor.execute(f"""
                DELETE FROM pending_epochs WHERE id IN ({','.join('?' * len(synced_ids))})
            """, synced_ids)
            conn.commit()
            conn.close()

            print(f"[VERIFIER] Synced {len(synced_ids)} buffered epochs")

        self._update_pending_counts()

    def force_sync(self) -> dict:
        """Force an immediate sync attempt."""
        with self._status_lock:
            self.status.next_retry = None
            self.status.retry_count = 0

        self._sync_pending()

        return self.get_status().to_dict()


# Quick test
if __name__ == "__main__":
    print("Testing VerifierClient...")
    print("=" * 60)

    # Create client (will fail to connect - that's expected)
    client = VerifierClient(
        verifier_url="http://localhost:8080",
        device_id="btfi-test-001",
        buffer_db_path="test_sync_buffer.db",
        auto_sync=False,
    )

    # Test sample buffering (offline)
    print("\n1. Testing offline buffering...")
    test_sample = {
        "timestamp": "2026-01-20T12:00:00Z",
        "device_id": "btfi-test-001",
        "fan": {"cfm": 250, "rpm": 1500},
    }

    result = client.send_sample(test_sample)
    print(f"   Sample sent: {result} (expected False - offline)")

    status = client.get_status()
    print(f"   Samples pending: {status.samples_pending}")
    print(f"   Connection state: {status.connection_state.value}")

    # Test epoch buffering
    print("\n2. Testing epoch buffering...")
    test_epoch = {
        "epoch_id": "ep-2026012012-btfi001",
        "device_id": "btfi-test-001",
        "summary": {"total_tar": 9000},
    }

    result = client.send_epoch(test_epoch)
    print(f"   Epoch response: {result} (expected None - offline)")

    status = client.get_status()
    print(f"   Epochs pending: {status.epochs_pending}")

    # Cleanup
    import os
    if os.path.exists("test_sync_buffer.db"):
        os.remove("test_sync_buffer.db")

    print("\nVerifierClient test complete!")
