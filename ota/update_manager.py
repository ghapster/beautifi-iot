# ota/update_manager.py
"""
Firmware update manager for BeautiFi IoT devices.
Handles secure OTA updates with signature verification and rollback support.
"""

import os
import json
import shutil
import hashlib
import requests
import threading
import subprocess
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Dict, Any, Tuple, Callable
from dataclasses import dataclass, field
from enum import Enum

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.backends import default_backend
from cryptography.exceptions import InvalidSignature

from config import FIRMWARE_VERSION, DEVICE_ID


class UpdateStatus(Enum):
    """States of the update process."""
    IDLE = "idle"
    CHECKING = "checking"
    AVAILABLE = "available"
    DOWNLOADING = "downloading"
    VERIFYING = "verifying"
    INSTALLING = "installing"
    COMPLETE = "complete"
    FAILED = "failed"
    ROLLBACK_REQUIRED = "rollback_required"


@dataclass
class FirmwareManifest:
    """
    Firmware update manifest describing a release.

    The manifest is signed by the BeautiFi release authority.
    """
    version: str
    release_date: str
    download_url: str
    file_hash: str  # SHA-256 of firmware file
    file_size: int
    changelog: str = ""
    min_version: str = "0.0.0"  # Minimum version required to upgrade
    signature: str = ""  # Ed25519 signature of manifest (excluding signature field)

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "release_date": self.release_date,
            "download_url": self.download_url,
            "file_hash": self.file_hash,
            "file_size": self.file_size,
            "changelog": self.changelog,
            "min_version": self.min_version,
            "signature": self.signature,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "FirmwareManifest":
        return cls(
            version=data.get("version", "0.0.0"),
            release_date=data.get("release_date", ""),
            download_url=data.get("download_url", ""),
            file_hash=data.get("file_hash", ""),
            file_size=data.get("file_size", 0),
            changelog=data.get("changelog", ""),
            min_version=data.get("min_version", "0.0.0"),
            signature=data.get("signature", ""),
        )

    def get_signable_content(self) -> bytes:
        """Get canonical JSON content for signature verification."""
        content = {
            "version": self.version,
            "release_date": self.release_date,
            "download_url": self.download_url,
            "file_hash": self.file_hash,
            "file_size": self.file_size,
            "changelog": self.changelog,
            "min_version": self.min_version,
        }
        return json.dumps(content, sort_keys=True, separators=(',', ':')).encode('utf-8')


class UpdateManager:
    """
    Manages OTA firmware updates.

    Features:
    - Check for updates from manifest URL
    - Verify manifest signature with trusted public key
    - Download and verify firmware integrity
    - Create backup before update
    - Rollback on failure
    """

    # Default paths
    UPDATE_DIR = Path.home() / ".beautifi" / "updates"
    BACKUP_DIR = Path.home() / ".beautifi" / "backups"
    STATE_FILE = "update_state.json"

    # Update manifest URL (configurable)
    DEFAULT_MANIFEST_URL = "https://raw.githubusercontent.com/ghapster/beautifi-iot/main/releases/latest.json"

    def __init__(
        self,
        app_dir: Optional[Path] = None,
        manifest_url: Optional[str] = None,
        trusted_public_key: Optional[str] = None,
    ):
        """
        Initialize update manager.

        Args:
            app_dir: Application directory to update (default: current directory)
            manifest_url: URL to fetch update manifest
            trusted_public_key: Ed25519 public key (hex) for verifying manifests
        """
        self.app_dir = Path(app_dir) if app_dir else Path.cwd()
        self.manifest_url = manifest_url or self.DEFAULT_MANIFEST_URL
        self._trusted_public_key_hex = trusted_public_key

        # State
        self._status = UpdateStatus.IDLE
        self._current_manifest: Optional[FirmwareManifest] = None
        self._download_progress: float = 0.0
        self._error_message: Optional[str] = None

        # Callbacks
        self._on_status_change: Optional[Callable[[UpdateStatus], None]] = None
        self._on_progress: Optional[Callable[[float], None]] = None

        # Ensure directories exist
        self.UPDATE_DIR.mkdir(parents=True, exist_ok=True)
        self.BACKUP_DIR.mkdir(parents=True, exist_ok=True)

        # Load persisted state
        self._load_state()

        print(f"[OTA] Update manager initialized")
        print(f"[OTA] Current version: {FIRMWARE_VERSION}")

    def _load_state(self):
        """Load update state from disk."""
        state_path = self.UPDATE_DIR / self.STATE_FILE
        if state_path.exists():
            try:
                with open(state_path, 'r') as f:
                    state = json.load(f)
                    if state.get("status") == "rollback_required":
                        self._status = UpdateStatus.ROLLBACK_REQUIRED
                        self._error_message = state.get("error")
            except Exception as e:
                print(f"[OTA] Failed to load state: {e}")

    def _save_state(self):
        """Save update state to disk."""
        state_path = self.UPDATE_DIR / self.STATE_FILE
        state = {
            "status": self._status.value,
            "version": FIRMWARE_VERSION,
            "error": self._error_message,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if self._current_manifest:
            state["pending_version"] = self._current_manifest.version

        with open(state_path, 'w') as f:
            json.dump(state, f, indent=2)

    def _set_status(self, status: UpdateStatus, error: Optional[str] = None):
        """Update status and notify callback."""
        self._status = status
        self._error_message = error
        self._save_state()

        if self._on_status_change:
            try:
                self._on_status_change(status)
            except Exception:
                pass

    @property
    def status(self) -> UpdateStatus:
        """Get current update status."""
        return self._status

    @property
    def current_version(self) -> str:
        """Get current firmware version."""
        return FIRMWARE_VERSION

    def set_status_callback(self, callback: Callable[[UpdateStatus], None]):
        """Set callback for status changes."""
        self._on_status_change = callback

    def set_progress_callback(self, callback: Callable[[float], None]):
        """Set callback for download progress (0.0 - 1.0)."""
        self._on_progress = callback

    # ============================================
    # Version Comparison
    # ============================================

    @staticmethod
    def compare_versions(v1: str, v2: str) -> int:
        """
        Compare two version strings.

        Returns:
            -1 if v1 < v2
            0 if v1 == v2
            1 if v1 > v2
        """
        def parse_version(v: str) -> Tuple[int, ...]:
            parts = v.split('.')
            return tuple(int(p) for p in parts if p.isdigit())

        p1 = parse_version(v1)
        p2 = parse_version(v2)

        # Pad shorter version with zeros
        max_len = max(len(p1), len(p2))
        p1 = p1 + (0,) * (max_len - len(p1))
        p2 = p2 + (0,) * (max_len - len(p2))

        if p1 < p2:
            return -1
        elif p1 > p2:
            return 1
        return 0

    # ============================================
    # Signature Verification
    # ============================================

    def verify_manifest_signature(self, manifest: FirmwareManifest) -> Tuple[bool, str]:
        """
        Verify manifest signature with trusted public key.

        Args:
            manifest: Firmware manifest to verify

        Returns:
            Tuple of (is_valid, message)
        """
        if not self._trusted_public_key_hex:
            # No trusted key configured - skip verification (development mode)
            print("[OTA] WARNING: No trusted public key configured, skipping signature verification")
            return True, "Signature verification skipped (no trusted key)"

        if not manifest.signature:
            return False, "Manifest has no signature"

        try:
            # Load trusted public key
            public_key_bytes = bytes.fromhex(self._trusted_public_key_hex)
            public_key = Ed25519PublicKey.from_public_bytes(public_key_bytes)

            # Get signable content
            content = manifest.get_signable_content()

            # Parse signature
            sig_str = manifest.signature
            if sig_str.startswith("ed25519:"):
                sig_str = sig_str[8:]
            signature = bytes.fromhex(sig_str)

            # Verify
            public_key.verify(signature, content)
            return True, "Manifest signature valid"

        except InvalidSignature:
            return False, "Invalid manifest signature"
        except Exception as e:
            return False, f"Signature verification error: {e}"

    # ============================================
    # Check for Updates
    # ============================================

    def check_for_updates(self) -> Tuple[bool, Optional[FirmwareManifest], str]:
        """
        Check for available firmware updates.

        Returns:
            Tuple of (update_available, manifest, message)
        """
        self._set_status(UpdateStatus.CHECKING)

        try:
            # Fetch manifest
            response = requests.get(self.manifest_url, timeout=30)
            response.raise_for_status()
            manifest_data = response.json()

            manifest = FirmwareManifest.from_dict(manifest_data)

            # Verify signature
            valid, msg = self.verify_manifest_signature(manifest)
            if not valid:
                self._set_status(UpdateStatus.FAILED, msg)
                return False, None, msg

            # Check if update is available
            if self.compare_versions(manifest.version, FIRMWARE_VERSION) <= 0:
                self._set_status(UpdateStatus.IDLE)
                return False, manifest, f"Already on latest version ({FIRMWARE_VERSION})"

            # Check minimum version requirement
            if self.compare_versions(FIRMWARE_VERSION, manifest.min_version) < 0:
                self._set_status(UpdateStatus.FAILED, "Current version too old")
                return False, manifest, f"Current version {FIRMWARE_VERSION} is below minimum {manifest.min_version}"

            self._current_manifest = manifest
            self._set_status(UpdateStatus.AVAILABLE)
            return True, manifest, f"Update available: {manifest.version}"

        except requests.exceptions.RequestException as e:
            self._set_status(UpdateStatus.FAILED, str(e))
            return False, None, f"Failed to fetch manifest: {e}"
        except json.JSONDecodeError as e:
            self._set_status(UpdateStatus.FAILED, str(e))
            return False, None, f"Invalid manifest format: {e}"
        except Exception as e:
            self._set_status(UpdateStatus.FAILED, str(e))
            return False, None, f"Update check failed: {e}"

    # ============================================
    # Download Update
    # ============================================

    def download_update(self, manifest: Optional[FirmwareManifest] = None) -> Tuple[bool, str]:
        """
        Download firmware update.

        Args:
            manifest: Firmware manifest (uses cached if not provided)

        Returns:
            Tuple of (success, message)
        """
        manifest = manifest or self._current_manifest
        if not manifest:
            return False, "No update manifest available"

        self._set_status(UpdateStatus.DOWNLOADING)
        self._download_progress = 0.0

        try:
            # Download file
            download_path = self.UPDATE_DIR / f"firmware-{manifest.version}.zip"

            response = requests.get(manifest.download_url, stream=True, timeout=300)
            response.raise_for_status()

            total_size = manifest.file_size or int(response.headers.get('content-length', 0))
            downloaded = 0

            with open(download_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)

                        if total_size > 0:
                            self._download_progress = downloaded / total_size
                            if self._on_progress:
                                try:
                                    self._on_progress(self._download_progress)
                                except Exception:
                                    pass

            # Verify hash
            self._set_status(UpdateStatus.VERIFYING)
            file_hash = self._compute_file_hash(download_path)

            if file_hash != manifest.file_hash:
                download_path.unlink()
                self._set_status(UpdateStatus.FAILED, "Hash mismatch")
                return False, f"File hash mismatch. Expected: {manifest.file_hash[:16]}..., Got: {file_hash[:16]}..."

            print(f"[OTA] Download complete: {download_path}")
            return True, f"Downloaded {manifest.version}"

        except Exception as e:
            self._set_status(UpdateStatus.FAILED, str(e))
            return False, f"Download failed: {e}"

    def _compute_file_hash(self, file_path: Path) -> str:
        """Compute SHA-256 hash of a file."""
        sha256 = hashlib.sha256()
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                sha256.update(chunk)
        return sha256.hexdigest()

    # ============================================
    # Backup and Rollback
    # ============================================

    def create_backup(self) -> Tuple[bool, str]:
        """
        Create backup of current firmware.

        Returns:
            Tuple of (success, backup_path or error)
        """
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        backup_name = f"backup-{FIRMWARE_VERSION}-{timestamp}"
        backup_path = self.BACKUP_DIR / backup_name

        try:
            # Copy application directory
            shutil.copytree(
                self.app_dir,
                backup_path,
                ignore=shutil.ignore_patterns(
                    '__pycache__', '*.pyc', '.git', 'venv', '*.db',
                    'updates', 'backups', '.beautifi'
                )
            )

            # Save backup metadata
            metadata = {
                "version": FIRMWARE_VERSION,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "device_id": DEVICE_ID,
            }
            with open(backup_path / "backup_metadata.json", 'w') as f:
                json.dump(metadata, f, indent=2)

            print(f"[OTA] Backup created: {backup_path}")
            return True, str(backup_path)

        except Exception as e:
            return False, f"Backup failed: {e}"

    def list_backups(self) -> list:
        """List available backups."""
        backups = []
        for backup_dir in self.BACKUP_DIR.iterdir():
            if backup_dir.is_dir():
                metadata_file = backup_dir / "backup_metadata.json"
                if metadata_file.exists():
                    with open(metadata_file, 'r') as f:
                        metadata = json.load(f)
                        backups.append({
                            "path": str(backup_dir),
                            "name": backup_dir.name,
                            **metadata
                        })
        return sorted(backups, key=lambda x: x.get("created_at", ""), reverse=True)

    def rollback(self, backup_path: Optional[str] = None) -> Tuple[bool, str]:
        """
        Rollback to a previous backup.

        Args:
            backup_path: Path to backup (uses most recent if not provided)

        Returns:
            Tuple of (success, message)
        """
        if not backup_path:
            backups = self.list_backups()
            if not backups:
                return False, "No backups available"
            backup_path = backups[0]["path"]

        backup_dir = Path(backup_path)
        if not backup_dir.exists():
            return False, f"Backup not found: {backup_path}"

        try:
            # Get list of files to restore (excluding certain patterns)
            exclude = {'__pycache__', 'venv', '.git', '*.db', 'updates', 'backups', '.beautifi'}

            for item in backup_dir.iterdir():
                if item.name in exclude or item.name == "backup_metadata.json":
                    continue

                dest = self.app_dir / item.name
                if item.is_dir():
                    if dest.exists():
                        shutil.rmtree(dest)
                    shutil.copytree(item, dest)
                else:
                    shutil.copy2(item, dest)

            self._set_status(UpdateStatus.IDLE)
            return True, f"Rolled back to {backup_dir.name}"

        except Exception as e:
            self._set_status(UpdateStatus.FAILED, str(e))
            return False, f"Rollback failed: {e}"

    # ============================================
    # Install Update
    # ============================================

    def install_update(
        self,
        manifest: Optional[FirmwareManifest] = None,
        auto_backup: bool = True,
        auto_restart: bool = False,
    ) -> Tuple[bool, str]:
        """
        Install a downloaded firmware update.

        Args:
            manifest: Firmware manifest
            auto_backup: Create backup before installing
            auto_restart: Restart application after install

        Returns:
            Tuple of (success, message)
        """
        manifest = manifest or self._current_manifest
        if not manifest:
            return False, "No update manifest available"

        download_path = self.UPDATE_DIR / f"firmware-{manifest.version}.zip"
        if not download_path.exists():
            return False, "Update not downloaded"

        # Create backup first
        if auto_backup:
            success, backup_result = self.create_backup()
            if not success:
                return False, f"Backup failed: {backup_result}"

        self._set_status(UpdateStatus.INSTALLING)

        try:
            import zipfile

            # Extract update
            extract_dir = self.UPDATE_DIR / f"extract-{manifest.version}"
            if extract_dir.exists():
                shutil.rmtree(extract_dir)

            with zipfile.ZipFile(download_path, 'r') as zf:
                zf.extractall(extract_dir)

            # Find the actual content directory (handle nested directories)
            content_dirs = list(extract_dir.iterdir())
            if len(content_dirs) == 1 and content_dirs[0].is_dir():
                source_dir = content_dirs[0]
            else:
                source_dir = extract_dir

            # Copy files to application directory
            exclude = {'__pycache__', 'venv', '.git', '*.db'}
            for item in source_dir.iterdir():
                if item.name in exclude:
                    continue

                dest = self.app_dir / item.name
                if item.is_dir():
                    if dest.exists():
                        shutil.rmtree(dest)
                    shutil.copytree(item, dest, ignore=shutil.ignore_patterns(*exclude))
                else:
                    shutil.copy2(item, dest)

            # Cleanup
            shutil.rmtree(extract_dir)
            download_path.unlink()

            self._set_status(UpdateStatus.COMPLETE)
            print(f"[OTA] Update installed: {manifest.version}")

            # Restart if requested
            if auto_restart:
                self._restart_application()

            return True, f"Updated to {manifest.version}"

        except Exception as e:
            self._set_status(UpdateStatus.ROLLBACK_REQUIRED, str(e))
            return False, f"Installation failed: {e}"

    def _restart_application(self):
        """Restart the application (Unix/systemd)."""
        try:
            # Try systemd first
            subprocess.run(
                ["sudo", "systemctl", "restart", "beautifi-iot"],
                timeout=10,
                check=False
            )
        except Exception:
            print("[OTA] Could not restart via systemd")

    # ============================================
    # Full Update Flow
    # ============================================

    def perform_update(
        self,
        auto_backup: bool = True,
        auto_restart: bool = False,
    ) -> Tuple[bool, str]:
        """
        Perform full update flow: check, download, install.

        Args:
            auto_backup: Create backup before installing
            auto_restart: Restart after install

        Returns:
            Tuple of (success, message)
        """
        # Check for updates
        available, manifest, msg = self.check_for_updates()
        if not available:
            return False, msg

        # Download
        success, msg = self.download_update(manifest)
        if not success:
            return False, msg

        # Install
        success, msg = self.install_update(manifest, auto_backup, auto_restart)
        return success, msg

    # ============================================
    # Status
    # ============================================

    def get_status(self) -> Dict[str, Any]:
        """Get update status summary."""
        status = {
            "status": self._status.value,
            "current_version": FIRMWARE_VERSION,
            "error": self._error_message,
        }

        if self._current_manifest:
            status["available_version"] = self._current_manifest.version
            status["changelog"] = self._current_manifest.changelog

        if self._status == UpdateStatus.DOWNLOADING:
            status["download_progress"] = round(self._download_progress * 100, 1)

        backups = self.list_backups()
        status["backup_count"] = len(backups)
        if backups:
            status["latest_backup"] = backups[0]["version"]

        return status


# Quick test
if __name__ == "__main__":
    print("Testing UpdateManager...")
    print("=" * 60)

    manager = UpdateManager()
    print(f"Current version: {manager.current_version}")
    print(f"Status: {manager.status.value}")

    # Version comparison test
    print("\nVersion comparison tests:")
    tests = [
        ("0.1.0", "0.2.0", -1),
        ("0.2.0", "0.1.0", 1),
        ("1.0.0", "1.0.0", 0),
        ("1.0", "1.0.0", 0),
        ("2.0.0", "1.9.9", 1),
    ]
    for v1, v2, expected in tests:
        result = UpdateManager.compare_versions(v1, v2)
        status = "PASS" if result == expected else "FAIL"
        print(f"  {v1} vs {v2}: {result} [{status}]")

    print("\nStatus:")
    for k, v in manager.get_status().items():
        print(f"  {k}: {v}")
