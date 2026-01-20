# crypto/signing.py
"""
Cryptographic signing functions for BeautiFi IoT telemetry.
Includes payload signing, epoch signing, and Merkle tree generation.
"""

import json
import hashlib
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime

from .identity import DeviceIdentity, get_device_identity


def canonicalize_json(data: dict) -> bytes:
    """
    Convert dict to canonical JSON bytes for consistent hashing.
    Uses sorted keys and no whitespace.
    """
    return json.dumps(data, sort_keys=True, separators=(',', ':')).encode('utf-8')


def hash_data(data: bytes) -> bytes:
    """SHA-256 hash of data."""
    return hashlib.sha256(data).digest()


def hash_hex(data: bytes) -> str:
    """SHA-256 hash of data as hex string."""
    return hashlib.sha256(data).hexdigest()


# ============================================
# Payload Signing (Individual Samples)
# ============================================

def sign_payload(
    payload: dict,
    identity: Optional[DeviceIdentity] = None,
    include_timestamp: bool = True
) -> dict:
    """
    Sign a telemetry payload with the device's private key.

    Args:
        payload: The telemetry data to sign
        identity: Device identity (uses singleton if not provided)
        include_timestamp: Add signing timestamp if not present

    Returns:
        Payload with added signature fields:
        - _signing.device_id
        - _signing.public_key
        - _signing.timestamp
        - _signing.payload_hash
        - _signing.signature
    """
    if identity is None:
        identity = get_device_identity()

    # Create a copy without any existing signing info
    payload_copy = {k: v for k, v in payload.items() if not k.startswith('_signing')}

    # Add timestamp if needed
    if include_timestamp and 'timestamp' not in payload_copy:
        payload_copy['timestamp'] = datetime.utcnow().isoformat() + 'Z'

    # Canonicalize and hash the payload
    canonical = canonicalize_json(payload_copy)
    payload_hash = hash_hex(canonical)

    # Sign the hash
    signature = identity.sign_hex(hash_data(canonical))

    # Add signing metadata
    payload_copy['_signing'] = {
        'device_id': identity.device_id,
        'public_key': f"ed25519:{identity.public_key_hex}",
        'timestamp': datetime.utcnow().isoformat() + 'Z',
        'payload_hash': payload_hash,
        'signature': f"ed25519:{signature}",
    }

    return payload_copy


def verify_signature(
    payload: dict,
    identity: Optional[DeviceIdentity] = None
) -> Tuple[bool, str]:
    """
    Verify a signed payload's signature.

    Args:
        payload: Signed payload with _signing field
        identity: Device identity for verification (uses singleton if not provided)

    Returns:
        Tuple of (is_valid, message)
    """
    if '_signing' not in payload:
        return False, "No signature present"

    signing_info = payload['_signing']

    # Extract payload without signing info
    payload_copy = {k: v for k, v in payload.items() if not k.startswith('_signing')}

    # Canonicalize and hash
    canonical = canonicalize_json(payload_copy)
    computed_hash = hash_hex(canonical)

    # Check hash matches
    if computed_hash != signing_info.get('payload_hash'):
        return False, "Payload hash mismatch - data may have been tampered"

    # Verify signature
    if identity is None:
        identity = get_device_identity()

    signature_str = signing_info.get('signature', '')
    if signature_str.startswith('ed25519:'):
        signature_str = signature_str[8:]

    try:
        signature = bytes.fromhex(signature_str)
        is_valid = identity.verify(hash_data(canonical), signature)
        if is_valid:
            return True, "Signature valid"
        else:
            return False, "Signature invalid"
    except Exception as e:
        return False, f"Verification error: {e}"


# ============================================
# Merkle Tree for Epochs
# ============================================

def create_merkle_root(items: List[bytes]) -> Tuple[str, List[str]]:
    """
    Create a Merkle root from a list of items.

    Args:
        items: List of bytes to include in the tree

    Returns:
        Tuple of (merkle_root_hex, list_of_leaf_hashes)
    """
    if not items:
        return hash_hex(b""), []

    # Hash all items to create leaves
    leaves = [hash_data(item) for item in items]
    leaf_hashes = [leaf.hex() for leaf in leaves]

    # Build tree bottom-up
    current_level = leaves

    while len(current_level) > 1:
        next_level = []

        for i in range(0, len(current_level), 2):
            left = current_level[i]

            # If odd number of nodes, duplicate the last one
            if i + 1 < len(current_level):
                right = current_level[i + 1]
            else:
                right = left

            # Combine and hash
            combined = left + right
            parent = hash_data(combined)
            next_level.append(parent)

        current_level = next_level

    root = current_level[0].hex()
    return root, leaf_hashes


def create_merkle_root_from_samples(samples: List[dict]) -> Tuple[str, List[str]]:
    """
    Create a Merkle root from a list of telemetry samples.

    Args:
        samples: List of telemetry sample dicts

    Returns:
        Tuple of (merkle_root_hex, list_of_sample_hashes)
    """
    # Canonicalize each sample and convert to bytes
    items = []
    for sample in samples:
        # Remove signing info for consistent hashing
        clean_sample = {k: v for k, v in sample.items() if not k.startswith('_')}
        items.append(canonicalize_json(clean_sample))

    return create_merkle_root(items)


# ============================================
# Epoch Signing
# ============================================

def sign_epoch(
    epoch_data: dict,
    samples: List[dict],
    identity: Optional[DeviceIdentity] = None
) -> dict:
    """
    Sign a complete epoch with Merkle root of all samples.

    Args:
        epoch_data: Epoch summary data (without samples)
        samples: List of telemetry samples in the epoch
        identity: Device identity (uses singleton if not provided)

    Returns:
        Signed epoch with:
        - merkle_root
        - sample_count
        - leaf_hashes (list of sample hashes)
        - _signing (signature block)
    """
    if identity is None:
        identity = get_device_identity()

    # Create Merkle root from samples
    merkle_root, leaf_hashes = create_merkle_root_from_samples(samples)

    # Build epoch document
    epoch_doc = {
        **epoch_data,
        'merkle_root': merkle_root,
        'sample_count': len(samples),
        'leaf_hashes': leaf_hashes,
    }

    # Sign the epoch
    canonical = canonicalize_json(epoch_doc)
    epoch_hash = hash_hex(canonical)
    signature = identity.sign_hex(hash_data(canonical))

    # Add signing metadata
    epoch_doc['_signing'] = {
        'device_id': identity.device_id,
        'public_key': f"ed25519:{identity.public_key_hex}",
        'signed_at': datetime.utcnow().isoformat() + 'Z',
        'epoch_hash': epoch_hash,
        'signature': f"ed25519:{signature}",
    }

    return epoch_doc


def verify_epoch(
    epoch_doc: dict,
    samples: Optional[List[dict]] = None,
    identity: Optional[DeviceIdentity] = None
) -> Tuple[bool, str]:
    """
    Verify an epoch's signature and optionally its Merkle root.

    Args:
        epoch_doc: Signed epoch document
        samples: Optional list of samples to verify Merkle root
        identity: Device identity for verification

    Returns:
        Tuple of (is_valid, message)
    """
    if '_signing' not in epoch_doc:
        return False, "No signature present"

    signing_info = epoch_doc['_signing']

    # Extract epoch without signing info
    epoch_copy = {k: v for k, v in epoch_doc.items() if not k.startswith('_signing')}

    # Canonicalize and hash
    canonical = canonicalize_json(epoch_copy)
    computed_hash = hash_hex(canonical)

    # Check hash matches
    if computed_hash != signing_info.get('epoch_hash'):
        return False, "Epoch hash mismatch - data may have been tampered"

    # Verify signature
    if identity is None:
        identity = get_device_identity()

    signature_str = signing_info.get('signature', '')
    if signature_str.startswith('ed25519:'):
        signature_str = signature_str[8:]

    try:
        signature = bytes.fromhex(signature_str)
        is_valid = identity.verify(hash_data(canonical), signature)
        if not is_valid:
            return False, "Signature invalid"
    except Exception as e:
        return False, f"Verification error: {e}"

    # Optionally verify Merkle root
    if samples is not None:
        computed_root, _ = create_merkle_root_from_samples(samples)
        if computed_root != epoch_doc.get('merkle_root'):
            return False, "Merkle root mismatch - samples don't match epoch"

    return True, "Epoch signature and integrity valid"


# Quick test
if __name__ == "__main__":
    import tempfile
    from pathlib import Path

    print("Testing signing functions...")
    print("=" * 60)

    # Use temp directory for testing
    with tempfile.TemporaryDirectory() as tmpdir:
        identity = DeviceIdentity(key_dir=Path(tmpdir))

        # Test payload signing
        print("\n1. Payload Signing")
        print("-" * 40)

        sample_payload = {
            "timestamp": "2026-01-20T12:00:00Z",
            "device_id": "btfi-test-001",
            "fan": {"cfm": 250, "rpm": 1500, "watts": 28},
            "environment": {"voc_ppb": 150, "temp_c": 24.0},
        }

        signed = sign_payload(sample_payload, identity)
        print(f"Payload hash: {signed['_signing']['payload_hash'][:32]}...")
        print(f"Signature: {signed['_signing']['signature'][:40]}...")

        # Verify
        valid, msg = verify_signature(signed, identity)
        print(f"Verification: {valid} - {msg}")

        # Test tampering detection
        signed['fan']['cfm'] = 999  # Tamper!
        valid, msg = verify_signature(signed, identity)
        print(f"After tampering: {valid} - {msg}")

        # Test Merkle tree
        print("\n2. Merkle Tree")
        print("-" * 40)

        samples = [
            {"ts": 1, "cfm": 100},
            {"ts": 2, "cfm": 150},
            {"ts": 3, "cfm": 200},
            {"ts": 4, "cfm": 250},
        ]

        root, leaves = create_merkle_root_from_samples(samples)
        print(f"Merkle root: {root[:32]}...")
        print(f"Leaf count: {len(leaves)}")
        for i, leaf in enumerate(leaves):
            print(f"  Leaf {i}: {leaf[:16]}...")

        # Test epoch signing
        print("\n3. Epoch Signing")
        print("-" * 40)

        epoch_data = {
            "epoch_id": "ep-2026012012-btfi001",
            "start_time": "2026-01-20T12:00:00Z",
            "end_time": "2026-01-20T13:00:00Z",
            "summary": {
                "total_tar": 9000,
                "avg_cfm": 150,
            }
        }

        signed_epoch = sign_epoch(epoch_data, samples, identity)
        print(f"Epoch hash: {signed_epoch['_signing']['epoch_hash'][:32]}...")
        print(f"Merkle root: {signed_epoch['merkle_root'][:32]}...")
        print(f"Sample count: {signed_epoch['sample_count']}")

        # Verify epoch
        valid, msg = verify_epoch(signed_epoch, samples, identity)
        print(f"Epoch verification: {valid} - {msg}")

        # Test with wrong samples
        wrong_samples = samples + [{"ts": 5, "cfm": 300}]
        valid, msg = verify_epoch(signed_epoch, wrong_samples, identity)
        print(f"With wrong samples: {valid} - {msg}")
