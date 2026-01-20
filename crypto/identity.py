# crypto/identity.py
"""
Device identity management for BeautiFi IoT.
Handles Ed25519 keypair generation, storage, and retrieval.
"""

import os
import json
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Optional, Tuple

# Use cryptography library for Ed25519
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.backends import default_backend


class DeviceIdentity:
    """
    Manages device cryptographic identity.

    - Generates Ed25519 keypair on first run
    - Stores keys securely on disk
    - Provides signing and verification methods
    """

    DEFAULT_KEY_DIR = Path.home() / ".beautifi" / "keys"
    PRIVATE_KEY_FILE = "device_private.pem"
    PUBLIC_KEY_FILE = "device_public.pem"
    IDENTITY_FILE = "identity.json"

    def __init__(self, key_dir: Optional[Path] = None, device_id: Optional[str] = None):
        """
        Initialize device identity.

        Args:
            key_dir: Directory to store keys (default: ~/.beautifi/keys)
            device_id: Device identifier (generated if not provided)
        """
        self.key_dir = Path(key_dir) if key_dir else self.DEFAULT_KEY_DIR
        self._private_key: Optional[Ed25519PrivateKey] = None
        self._public_key: Optional[Ed25519PublicKey] = None
        self._device_id = device_id
        self._identity_info: dict = {}

        # Ensure key directory exists
        self.key_dir.mkdir(parents=True, exist_ok=True)

        # Load or generate keys
        self._load_or_generate()

    def _generate_device_id(self) -> str:
        """Generate a unique device ID from the public key."""
        public_bytes = self._public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw
        )
        # Use first 8 bytes of SHA256 hash as device ID
        hash_bytes = hashlib.sha256(public_bytes).digest()[:8]
        return f"btfi-{hash_bytes.hex()}"

    def _load_or_generate(self):
        """Load existing keys or generate new ones."""
        private_key_path = self.key_dir / self.PRIVATE_KEY_FILE
        public_key_path = self.key_dir / self.PUBLIC_KEY_FILE
        identity_path = self.key_dir / self.IDENTITY_FILE

        if private_key_path.exists() and public_key_path.exists():
            # Load existing keys
            self._load_keys(private_key_path, public_key_path)
            if identity_path.exists():
                with open(identity_path, 'r') as f:
                    self._identity_info = json.load(f)
                    self._device_id = self._identity_info.get('device_id')
            print(f"[CRYPTO] Loaded existing device identity: {self._device_id}")
        else:
            # Generate new keys
            self._generate_keys()
            self._save_keys(private_key_path, public_key_path)

            # Generate device ID from public key
            if not self._device_id:
                self._device_id = self._generate_device_id()

            # Save identity info
            self._identity_info = {
                'device_id': self._device_id,
                'created_at': datetime.utcnow().isoformat() + 'Z',
                'key_algorithm': 'Ed25519',
                'public_key_hex': self.public_key_hex,
            }
            with open(identity_path, 'w') as f:
                json.dump(self._identity_info, f, indent=2)

            print(f"[CRYPTO] Generated new device identity: {self._device_id}")

    def _generate_keys(self):
        """Generate a new Ed25519 keypair."""
        self._private_key = Ed25519PrivateKey.generate()
        self._public_key = self._private_key.public_key()

    def _load_keys(self, private_path: Path, public_path: Path):
        """Load keys from PEM files."""
        with open(private_path, 'rb') as f:
            self._private_key = serialization.load_pem_private_key(
                f.read(),
                password=None,
                backend=default_backend()
            )
        self._public_key = self._private_key.public_key()

    def _save_keys(self, private_path: Path, public_path: Path):
        """Save keys to PEM files."""
        # Save private key (no encryption for IoT device - consider TPM in production)
        private_pem = self._private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        )
        with open(private_path, 'wb') as f:
            f.write(private_pem)

        # Restrict permissions on private key (Unix only)
        try:
            os.chmod(private_path, 0o600)
        except (OSError, AttributeError):
            pass  # Windows doesn't support chmod

        # Save public key
        public_pem = self._public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        )
        with open(public_path, 'wb') as f:
            f.write(public_pem)

    @property
    def device_id(self) -> str:
        """Get the device ID."""
        return self._device_id

    @property
    def public_key_hex(self) -> str:
        """Get the public key as hex string."""
        public_bytes = self._public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw
        )
        return public_bytes.hex()

    @property
    def public_key_bytes(self) -> bytes:
        """Get the raw public key bytes."""
        return self._public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw
        )

    def sign(self, data: bytes) -> bytes:
        """
        Sign data with the device's private key.

        Args:
            data: Bytes to sign

        Returns:
            Ed25519 signature (64 bytes)
        """
        return self._private_key.sign(data)

    def sign_hex(self, data: bytes) -> str:
        """Sign data and return signature as hex string."""
        return self.sign(data).hex()

    def verify(self, data: bytes, signature: bytes) -> bool:
        """
        Verify a signature against data.

        Args:
            data: Original data
            signature: Signature to verify

        Returns:
            True if valid, False otherwise
        """
        try:
            self._public_key.verify(signature, data)
            return True
        except Exception:
            return False

    def get_identity_info(self) -> dict:
        """Get full device identity information."""
        return {
            'device_id': self._device_id,
            'public_key': f"ed25519:{self.public_key_hex}",
            'key_algorithm': 'Ed25519',
            'created_at': self._identity_info.get('created_at'),
        }


# Module-level singleton for convenience
_identity: Optional[DeviceIdentity] = None


def get_device_identity(key_dir: Optional[Path] = None) -> DeviceIdentity:
    """Get or create the device identity singleton."""
    global _identity
    if _identity is None:
        _identity = DeviceIdentity(key_dir=key_dir)
    return _identity


# Quick test
if __name__ == "__main__":
    print("Testing DeviceIdentity...")
    print("=" * 50)

    # Use temp directory for testing
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        identity = DeviceIdentity(key_dir=Path(tmpdir))

        print(f"Device ID: {identity.device_id}")
        print(f"Public Key: ed25519:{identity.public_key_hex[:32]}...")

        # Test signing
        test_data = b"Hello, BeautiFi!"
        signature = identity.sign(test_data)
        print(f"Signature: {signature.hex()[:32]}...")

        # Test verification
        is_valid = identity.verify(test_data, signature)
        print(f"Signature valid: {is_valid}")

        # Test tampering detection
        tampered_data = b"Hello, BeautiFi?"
        is_valid_tampered = identity.verify(tampered_data, signature)
        print(f"Tampered data valid: {is_valid_tampered}")

        print("\nIdentity Info:")
        for k, v in identity.get_identity_info().items():
            print(f"  {k}: {v}")
