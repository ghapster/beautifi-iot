# evidence/pack_builder.py
"""
Evidence pack builder for BeautiFi IoT DUAN compliance.
Creates ZIP archives of epoch data with cryptographic hashes for verifiable storage.
"""

import os
import json
import hashlib
import zipfile
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field

# boto3 for S3-compatible storage (Cloudflare R2)
try:
    import boto3
    from botocore.config import Config
    BOTO3_AVAILABLE = True
except ImportError:
    BOTO3_AVAILABLE = False
    print("[WARN] boto3 not installed. Run: pip install boto3")


@dataclass
class EvidencePack:
    """Represents a built evidence pack."""
    epoch_id: str
    device_id: str
    zip_path: str
    zip_sha256: str
    size_bytes: int
    sample_count: int
    created_at: str
    uploaded: bool = False
    storage_url: Optional[str] = None
    storage_key: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "epoch_id": self.epoch_id,
            "device_id": self.device_id,
            "zip_sha256": self.zip_sha256,
            "size_bytes": self.size_bytes,
            "sample_count": self.sample_count,
            "created_at": self.created_at,
            "uploaded": self.uploaded,
            "storage_url": self.storage_url,
            "storage_key": self.storage_key,
        }


class EvidencePackBuilder:
    """
    Builds and uploads evidence packs for epoch verification.

    Evidence pack contains:
    - epoch.json: Epoch summary with merkle_root and signature
    - samples.json: All telemetry samples in the epoch
    - device_identity.json: Device public key and ID
    - metadata.json: Pack metadata and creation timestamp

    The ZIP is hashed (SHA256) and optionally uploaded to R2/S3 storage.
    """

    def __init__(
        self,
        output_dir: str = "evidence_packs",
        r2_endpoint_url: Optional[str] = None,
        r2_access_key_id: Optional[str] = None,
        r2_secret_access_key: Optional[str] = None,
        r2_bucket_name: Optional[str] = None,
        auto_upload: bool = True,
        keep_local: bool = True,
    ):
        """
        Initialize the evidence pack builder.

        Args:
            output_dir: Local directory for evidence packs
            r2_endpoint_url: Cloudflare R2 S3 endpoint
            r2_access_key_id: R2 access key
            r2_secret_access_key: R2 secret key
            r2_bucket_name: R2 bucket name
            auto_upload: Automatically upload packs after building
            keep_local: Keep local copy after upload
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.auto_upload = auto_upload
        self.keep_local = keep_local

        # R2/S3 configuration
        self.r2_endpoint_url = r2_endpoint_url
        self.r2_bucket_name = r2_bucket_name
        self._s3_client = None

        if r2_endpoint_url and r2_access_key_id and r2_secret_access_key and BOTO3_AVAILABLE:
            try:
                self._s3_client = boto3.client(
                    's3',
                    endpoint_url=r2_endpoint_url,
                    aws_access_key_id=r2_access_key_id,
                    aws_secret_access_key=r2_secret_access_key,
                    config=Config(
                        signature_version='s3v4',
                        retries={'max_attempts': 3}
                    ),
                )
                print(f"[EVIDENCE] R2 client initialized: {r2_bucket_name}")
            except Exception as e:
                print(f"[EVIDENCE] Failed to initialize R2 client: {e}")
                self._s3_client = None
        elif not BOTO3_AVAILABLE:
            print("[EVIDENCE] boto3 not available, upload disabled")

    def build_pack(
        self,
        epoch: dict,
        samples: List[dict],
        device_identity: Optional[dict] = None,
    ) -> EvidencePack:
        """
        Build an evidence pack for an epoch.

        Args:
            epoch: Signed epoch data with merkle_root
            samples: List of telemetry samples in the epoch
            device_identity: Device identity info (public key, device_id)

        Returns:
            EvidencePack with hash and optional storage URL
        """
        epoch_id = epoch.get("epoch_id", "unknown")
        device_id = epoch.get("device_id", "unknown")
        timestamp = datetime.utcnow().isoformat() + "Z"

        print(f"[EVIDENCE] Building pack for epoch: {epoch_id}")

        # Create pack metadata
        metadata = {
            "pack_version": "1.0",
            "epoch_id": epoch_id,
            "device_id": device_id,
            "sample_count": len(samples),
            "created_at": timestamp,
            "merkle_root": epoch.get("merkle_root"),
            "epoch_signature": epoch.get("_signing", {}).get("signature"),
        }

        # Build ZIP file
        zip_filename = f"evidence_{epoch_id}_{timestamp[:10]}.zip"
        zip_path = self.output_dir / zip_filename

        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            # Add epoch summary
            zf.writestr(
                "epoch.json",
                json.dumps(epoch, indent=2, sort_keys=True)
            )

            # Add all samples
            zf.writestr(
                "samples.json",
                json.dumps(samples, indent=2, sort_keys=True)
            )

            # Add device identity if provided
            if device_identity:
                zf.writestr(
                    "device_identity.json",
                    json.dumps(device_identity, indent=2, sort_keys=True)
                )

            # Add metadata
            zf.writestr(
                "metadata.json",
                json.dumps(metadata, indent=2, sort_keys=True)
            )

            # Add leaf hashes if present (for merkle proof verification)
            if "leaf_hashes" in epoch:
                zf.writestr(
                    "leaf_hashes.json",
                    json.dumps(epoch["leaf_hashes"], indent=2)
                )

        # Calculate SHA256 of the ZIP
        zip_sha256 = self._hash_file(zip_path)
        size_bytes = zip_path.stat().st_size

        print(f"[EVIDENCE] Pack built: {zip_filename}")
        print(f"[EVIDENCE] SHA256: {zip_sha256}")
        print(f"[EVIDENCE] Size: {size_bytes} bytes, Samples: {len(samples)}")

        # Create evidence pack object
        pack = EvidencePack(
            epoch_id=epoch_id,
            device_id=device_id,
            zip_path=str(zip_path),
            zip_sha256=zip_sha256,
            size_bytes=size_bytes,
            sample_count=len(samples),
            created_at=timestamp,
        )

        # Upload if configured
        if self.auto_upload and self._s3_client:
            self._upload_pack(pack)

            # Remove local file if not keeping
            if not self.keep_local and pack.uploaded:
                zip_path.unlink()
                pack.zip_path = ""

        return pack

    def _hash_file(self, path: Path) -> str:
        """Calculate SHA256 hash of a file."""
        sha256 = hashlib.sha256()
        with open(path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                sha256.update(chunk)
        return sha256.hexdigest()

    def _upload_pack(self, pack: EvidencePack) -> bool:
        """Upload evidence pack to R2/S3."""
        if not self._s3_client or not self.r2_bucket_name:
            print("[EVIDENCE] Upload skipped: R2 not configured")
            return False

        # Storage key: device_id/year/month/epoch_id.zip
        created = datetime.fromisoformat(pack.created_at.replace("Z", "+00:00"))
        storage_key = f"{pack.device_id}/{created.year}/{created.month:02d}/{pack.epoch_id}.zip"

        try:
            # Upload with metadata
            with open(pack.zip_path, 'rb') as f:
                self._s3_client.put_object(
                    Bucket=self.r2_bucket_name,
                    Key=storage_key,
                    Body=f,
                    ContentType='application/zip',
                    Metadata={
                        'epoch_id': pack.epoch_id,
                        'device_id': pack.device_id,
                        'sha256': pack.zip_sha256,
                        'sample_count': str(pack.sample_count),
                    }
                )

            # Build storage URL
            pack.storage_key = storage_key
            pack.storage_url = f"{self.r2_endpoint_url}/{self.r2_bucket_name}/{storage_key}"
            pack.uploaded = True

            print(f"[EVIDENCE] Uploaded to R2: {storage_key}")
            return True

        except Exception as e:
            print(f"[EVIDENCE] Upload failed: {e}")
            return False

    def get_pack_url(self, epoch_id: str, device_id: str, year: int, month: int) -> str:
        """Generate the storage URL for a pack."""
        storage_key = f"{device_id}/{year}/{month:02d}/{epoch_id}.zip"
        return f"{self.r2_endpoint_url}/{self.r2_bucket_name}/{storage_key}"

    def download_pack(self, storage_key: str, output_path: str) -> Optional[str]:
        """Download an evidence pack from R2."""
        if not self._s3_client or not self.r2_bucket_name:
            print("[EVIDENCE] Download failed: R2 not configured")
            return None

        try:
            response = self._s3_client.get_object(
                Bucket=self.r2_bucket_name,
                Key=storage_key,
            )

            with open(output_path, 'wb') as f:
                f.write(response['Body'].read())

            print(f"[EVIDENCE] Downloaded: {storage_key}")
            return output_path

        except Exception as e:
            print(f"[EVIDENCE] Download failed: {e}")
            return None

    def verify_pack(self, zip_path: str, expected_sha256: str) -> bool:
        """Verify an evidence pack's integrity."""
        actual_sha256 = self._hash_file(Path(zip_path))
        is_valid = actual_sha256 == expected_sha256

        if is_valid:
            print(f"[EVIDENCE] Verification PASSED: {expected_sha256[:16]}...")
        else:
            print(f"[EVIDENCE] Verification FAILED!")
            print(f"  Expected: {expected_sha256}")
            print(f"  Actual:   {actual_sha256}")

        return is_valid

    def list_packs(self, device_id: Optional[str] = None, limit: int = 100) -> List[dict]:
        """List evidence packs in R2 storage."""
        if not self._s3_client or not self.r2_bucket_name:
            return []

        try:
            prefix = f"{device_id}/" if device_id else ""
            response = self._s3_client.list_objects_v2(
                Bucket=self.r2_bucket_name,
                Prefix=prefix,
                MaxKeys=limit,
            )

            packs = []
            for obj in response.get('Contents', []):
                packs.append({
                    'key': obj['Key'],
                    'size': obj['Size'],
                    'last_modified': obj['LastModified'].isoformat(),
                })

            return packs

        except Exception as e:
            print(f"[EVIDENCE] List failed: {e}")
            return []


# Quick test
if __name__ == "__main__":
    import os
    from dotenv import load_dotenv

    # Load .env file
    load_dotenv()

    print("Testing EvidencePackBuilder...")
    print("=" * 60)

    # Create builder with R2 config
    builder = EvidencePackBuilder(
        output_dir="test_evidence",
        r2_endpoint_url=os.getenv("R2_ENDPOINT_URL"),
        r2_access_key_id=os.getenv("R2_ACCESS_KEY_ID"),
        r2_secret_access_key=os.getenv("R2_SECRET_ACCESS_KEY"),
        r2_bucket_name=os.getenv("R2_BUCKET_NAME"),
        auto_upload=True,
        keep_local=True,
    )

    # Test epoch data
    test_epoch = {
        "epoch_id": "ep-2026012216-btfi-test-001",
        "device_id": "btfi-test-001",
        "start_time": "2026-01-22T16:00:00Z",
        "end_time": "2026-01-22T17:00:00Z",
        "sample_count": 3,
        "merkle_root": "abc123def456789...",
        "summary": {
            "total_tar_cfm_min": 12500,
            "avg_cfm": 250,
        },
        "_signing": {
            "signature": "ed25519:abcdef...",
            "epoch_hash": "hash123...",
        },
        "leaf_hashes": ["leaf1", "leaf2", "leaf3"],
    }

    test_samples = [
        {"timestamp": "2026-01-22T16:00:00Z", "fan": {"cfm": 250}},
        {"timestamp": "2026-01-22T16:00:12Z", "fan": {"cfm": 260}},
        {"timestamp": "2026-01-22T16:00:24Z", "fan": {"cfm": 240}},
    ]

    test_identity = {
        "device_id": "btfi-test-001",
        "public_key": "ed25519:abc123...",
    }

    # Build pack
    pack = builder.build_pack(test_epoch, test_samples, test_identity)
    print(f"\nPack result: {json.dumps(pack.to_dict(), indent=2)}")

    # Verify pack
    if pack.zip_path:
        is_valid = builder.verify_pack(pack.zip_path, pack.zip_sha256)
        print(f"\nVerification: {'PASSED' if is_valid else 'FAILED'}")

    # List packs in R2
    print("\nListing packs in R2...")
    packs = builder.list_packs()
    for p in packs:
        print(f"  {p['key']} ({p['size']} bytes)")

    print("\nEvidencePackBuilder test complete!")
