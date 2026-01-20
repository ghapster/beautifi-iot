# registration/backend_client.py
"""
Backend API client for BeautiFi IoT device registration.
Handles communication with the SalonSafe backend service.
"""

import json
import requests
from datetime import datetime, timezone
from typing import Optional, Dict, Any, Tuple
from dataclasses import dataclass


@dataclass
class RegistrationResult:
    """Result of a registration attempt."""
    success: bool
    registration_id: Optional[str] = None
    message: str = ""
    nft_token_id: Optional[int] = None
    nft_metadata_uri: Optional[str] = None
    tx_hash: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "registration_id": self.registration_id,
            "message": self.message,
            "nft_token_id": self.nft_token_id,
            "nft_metadata_uri": self.nft_metadata_uri,
            "tx_hash": self.tx_hash,
            "error": self.error,
        }


class RegistrationClient:
    """
    Client for registering IoT devices with the SalonSafe backend.

    Handles:
    - Device registration submission
    - Registration status polling
    - NFT binding retrieval
    """

    def __init__(
        self,
        backend_url: str,
        device_id: str,
        timeout: int = 30,
    ):
        """
        Initialize the registration client.

        Args:
            backend_url: Base URL of the backend API
            device_id: This device's ID
            timeout: Request timeout in seconds
        """
        self.backend_url = backend_url.rstrip('/')
        self.device_id = device_id
        self.timeout = timeout

        # HTTP session
        self._session = requests.Session()
        self._session.headers.update({
            "Content-Type": "application/json",
            "X-Device-ID": device_id,
            "User-Agent": f"BeautiFi-IoT/{device_id}",
        })

        print(f"[REGISTER] Client initialized for {self.backend_url}")

    def register_device(
        self,
        wallet_address: str,
        salon_name: str,
        location: str,
        email: str,
        manifest: Dict[str, Any],
        activation_date: Optional[str] = None,
        **kwargs
    ) -> RegistrationResult:
        """
        Register a device with the backend.

        Args:
            wallet_address: Owner's wallet address (for NFT)
            salon_name: Name of the salon/site
            location: Location address
            email: Contact email
            manifest: Hardware manifest dict
            activation_date: Optional activation date (defaults to today)
            **kwargs: Additional fields (reseller, installer, etc.)

        Returns:
            RegistrationResult with status and IDs
        """
        url = f"{self.backend_url}/api/register"

        # Build registration payload
        payload = {
            "wallet": wallet_address.lower(),
            "walletAddress": wallet_address.lower(),
            "salonName": salon_name,
            "location": location,
            "email": email,
            "unitModel": manifest.get("unit_model", "BeautiFi IoT"),
            "unitCount": manifest.get("unit_count", 1),
            "activationDate": activation_date or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "status": "pending",  # Requires admin approval

            # Device-specific fields
            "deviceId": self.device_id,
            "publicKey": manifest.get("public_key"),
            "firmwareVersion": manifest.get("firmware_version"),
            "manifestHash": manifest.get("manifest_hash"),

            # Optional fields from kwargs
            "reseller": kwargs.get("reseller", ""),
            "manicureStations": kwargs.get("manicure_stations", 0),
            "pedicureStations": kwargs.get("pedicure_stations", 0),
            "designerEngineer": kwargs.get("designer_engineer", ""),
            "installer": kwargs.get("installer", "BeautiFi Self-Install"),
            "comments": kwargs.get("comments", f"IoT Device: {self.device_id}"),
        }

        try:
            response = self._session.post(url, json=payload, timeout=self.timeout)

            if response.status_code == 200:
                data = response.json()
                return RegistrationResult(
                    success=True,
                    registration_id=data.get("id"),
                    message=data.get("message", "Registration submitted"),
                )
            else:
                return RegistrationResult(
                    success=False,
                    error=f"HTTP {response.status_code}: {response.text[:200]}",
                )

        except requests.exceptions.ConnectionError as e:
            return RegistrationResult(
                success=False,
                error=f"Connection error: {e}",
            )
        except requests.exceptions.Timeout:
            return RegistrationResult(
                success=False,
                error="Request timeout",
            )
        except Exception as e:
            return RegistrationResult(
                success=False,
                error=f"Request error: {e}",
            )

    def check_registration_status(self, wallet_address: str) -> Optional[Dict[str, Any]]:
        """
        Check registration status for a wallet.

        Args:
            wallet_address: Owner's wallet address

        Returns:
            Registration data if found, None otherwise
        """
        url = f"{self.backend_url}/api/miner/{wallet_address.lower()}"

        try:
            response = self._session.get(url, timeout=self.timeout)

            if response.status_code == 200:
                data = response.json()
                salons = data.get("salons", [])

                # Find our device
                for salon in salons:
                    # Match by device ID if available, otherwise return first
                    if salon.get("device_id") == self.device_id:
                        return salon

                # Return first salon if no exact match
                if salons:
                    return salons[0]

                return None
            else:
                print(f"[REGISTER] Status check failed: HTTP {response.status_code}")
                return None

        except Exception as e:
            print(f"[REGISTER] Status check error: {e}")
            return None

    def get_nft_binding(self, wallet_address: str) -> Optional[Dict[str, Any]]:
        """
        Get NFT binding information for a registered device.

        Args:
            wallet_address: Owner's wallet address

        Returns:
            NFT binding data if found
        """
        status = self.check_registration_status(wallet_address)

        if status is None:
            return None

        if status.get("status") != "approved":
            return {
                "status": status.get("status", "unknown"),
                "message": "Registration not yet approved",
            }

        return {
            "status": "approved",
            "nft_token_id": status.get("nft_token_id"),
            "nft_metadata_uri": status.get("nft_metadata_uri"),
            "tx_hash": status.get("tx_hash"),
            "mining_rate": status.get("mining_rate"),
            "vesting_days": status.get("vesting_days"),
            "activation_date": status.get("activation_date"),
        }

    def ping(self) -> bool:
        """Check if backend is reachable."""
        url = f"{self.backend_url}/api/admin/ping"

        try:
            response = self._session.get(url, timeout=5)
            return response.status_code == 200 and response.text == "pong"
        except Exception:
            return False


# Quick test
if __name__ == "__main__":
    print("Testing RegistrationClient...")
    print("=" * 60)

    client = RegistrationClient(
        backend_url="https://salon-safe-backend.onrender.com",
        device_id="btfi-test-001",
    )

    # Test ping
    print("\n1. Testing backend connectivity...")
    is_online = client.ping()
    print(f"   Backend online: {is_online}")

    # Test status check (won't find anything for test wallet)
    print("\n2. Testing registration status check...")
    status = client.check_registration_status("0x0000000000000000000000000000000000000000")
    print(f"   Status: {status}")

    print("\nRegistrationClient test complete!")
