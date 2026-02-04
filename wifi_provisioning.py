# wifi_provisioning.py
"""
WiFi provisioning for BeautiFi IoT devices.
Handles AP (hotspot) mode for initial setup and switching to client mode.
"""

import subprocess
import time
import os
from pathlib import Path
from typing import Optional, Tuple, List, Dict


class WiFiProvisioning:
    """
    Manages WiFi provisioning flow:
    1. Check if WiFi is configured
    2. If not, start AP/hotspot mode
    3. User connects and provides credentials
    4. Switch to client mode and connect
    """

    # Default AP settings
    DEFAULT_AP_SSID = "BeautiFi-Setup"
    DEFAULT_AP_PASSWORD = "beautifi123"  # Min 8 chars for WPA
    DEFAULT_AP_IP = "192.168.4.1"

    # Connection file for NetworkManager
    NM_CONNECTIONS_DIR = Path("/etc/NetworkManager/system-connections")

    def __init__(
        self,
        ap_ssid: Optional[str] = None,
        ap_password: Optional[str] = None,
    ):
        """
        Initialize WiFi provisioning.

        Args:
            ap_ssid: SSID for the access point (default: BeautiFi-Setup)
            ap_password: Password for AP (default: beautifi123)
        """
        self.ap_ssid = ap_ssid or self.DEFAULT_AP_SSID
        self.ap_password = ap_password or self.DEFAULT_AP_PASSWORD
        self._ap_active = False
        self._interface = self._get_wifi_interface()

        print(f"[WIFI] Provisioning initialized")
        print(f"[WIFI] Interface: {self._interface}")

    def _run_command(self, cmd: List[str], timeout: int = 30) -> Tuple[bool, str]:
        """Run a shell command and return success status and output."""
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            output = result.stdout + result.stderr
            return result.returncode == 0, output.strip()
        except subprocess.TimeoutExpired:
            return False, "Command timed out"
        except Exception as e:
            return False, str(e)

    def _get_wifi_interface(self) -> str:
        """Get the WiFi interface name (usually wlan0)."""
        success, output = self._run_command(["nmcli", "-t", "-f", "DEVICE,TYPE", "device"])
        if success:
            for line in output.split('\n'):
                if ':wifi' in line:
                    device = line.split(':')[0]
                    # Skip p2p (peer-to-peer) devices - we want the real WiFi interface
                    if not device.startswith('p2p'):
                        return device
        return "wlan0"  # Default fallback

    # ============================================
    # Status Checks
    # ============================================

    def is_connected(self) -> bool:
        """Check if currently connected to a WiFi network."""
        success, output = self._run_command([
            "nmcli", "-t", "-f", "DEVICE,STATE", "device"
        ])
        if success:
            for line in output.split('\n'):
                if self._interface in line and 'connected' in line.lower():
                    # Make sure it's not just "disconnected"
                    if ':connected' in line:
                        return True
        return False

    def get_current_ssid(self) -> Optional[str]:
        """Get the SSID of the currently connected network."""
        success, output = self._run_command([
            "nmcli", "-t", "-f", "ACTIVE,SSID", "dev", "wifi"
        ])
        if success:
            for line in output.split('\n'):
                if line.startswith('yes:'):
                    return line.split(':', 1)[1]
        return None

    def get_ip_address(self) -> Optional[str]:
        """Get the current IP address."""
        success, output = self._run_command([
            "hostname", "-I"
        ])
        if success and output:
            return output.split()[0]
        return None

    def has_saved_networks(self) -> bool:
        """Check if there are any saved WiFi networks."""
        success, output = self._run_command([
            "nmcli", "-t", "-f", "NAME,TYPE", "connection", "show"
        ])
        if success:
            for line in output.split('\n'):
                if ':802-11-wireless' in line:
                    # Exclude our AP connection
                    if self.ap_ssid not in line:
                        return True
        return False

    def scan_networks(self) -> List[Dict[str, str]]:
        """Scan for available WiFi networks."""
        # Trigger a rescan
        self._run_command(["nmcli", "dev", "wifi", "rescan"])
        time.sleep(2)

        success, output = self._run_command([
            "nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY", "dev", "wifi", "list"
        ])

        networks = []
        seen = set()

        if success:
            for line in output.split('\n'):
                parts = line.split(':')
                if len(parts) >= 3:
                    ssid = parts[0]
                    if ssid and ssid not in seen:
                        seen.add(ssid)
                        networks.append({
                            "ssid": ssid,
                            "signal": parts[1],
                            "security": parts[2] if len(parts) > 2 else "Open"
                        })

        # Sort by signal strength
        networks.sort(key=lambda x: int(x.get("signal", 0)), reverse=True)
        return networks

    # ============================================
    # AP (Hotspot) Mode - using hostapd
    # ============================================

    def _run_shell(self, cmd: str, timeout: int = 30) -> Tuple[bool, str]:
        """Run a shell command string."""
        try:
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
            return result.returncode == 0, (result.stdout + result.stderr).strip()
        except Exception as e:
            return False, str(e)

    def start_ap_mode(self) -> Tuple[bool, str]:
        """
        Start the device in Access Point (hotspot) mode using hostapd.

        Returns:
            Tuple of (success, message)
        """
        print(f"[WIFI] Starting AP mode: {self.ap_ssid}")

        # Stop any existing hotspot
        self.stop_ap_mode()

        # Tell NetworkManager to stop managing wlan0
        self._run_shell("sudo nmcli dev set wlan0 managed no")
        time.sleep(1)

        # Set up the interface with static IP
        self._run_shell("sudo ip addr flush dev wlan0")
        self._run_shell(f"sudo ip addr add {self.DEFAULT_AP_IP}/24 dev wlan0")
        self._run_shell("sudo ip link set wlan0 up")
        time.sleep(1)

        # Start hostapd and dnsmasq
        success1, out1 = self._run_shell("sudo systemctl start hostapd")
        success2, out2 = self._run_shell("sudo systemctl start dnsmasq")

        if success1 and success2:
            self._ap_active = True
            print(f"[WIFI] AP mode started: {self.ap_ssid}")
            print(f"[WIFI] Connect to this network and go to http://{self.DEFAULT_AP_IP}:5000")
            return True, f"AP started: {self.ap_ssid}"
        else:
            print(f"[WIFI] Failed to start AP: {out1} {out2}")
            return False, f"Failed to start AP: {out1} {out2}"

    def stop_ap_mode(self) -> Tuple[bool, str]:
        """Stop AP mode (hostapd) and return wlan0 to NetworkManager."""
        print("[WIFI] Stopping AP mode...")

        # Stop hostapd and dnsmasq
        self._run_shell("sudo systemctl stop hostapd")
        self._run_shell("sudo systemctl stop dnsmasq")

        # Clear interface and return to NetworkManager
        self._run_shell("sudo ip addr flush dev wlan0")
        self._run_shell("sudo nmcli dev set wlan0 managed yes")
        time.sleep(2)

        self._ap_active = False
        return True, "AP stopped"

    def is_ap_active(self) -> bool:
        """Check if AP mode (hostapd) is currently active."""
        success, output = self._run_shell("sudo systemctl is-active hostapd")
        return success and "active" in output

    # ============================================
    # Client Mode (Connect to WiFi)
    # ============================================

    def connect_to_wifi(self, ssid: str, password: str) -> Tuple[bool, str]:
        """
        Connect to a WiFi network.

        Args:
            ssid: Network SSID
            password: Network password

        Returns:
            Tuple of (success, message)
        """
        print(f"[WIFI] Connecting to: {ssid}")

        # Stop AP mode if active (hostapd)
        if self._ap_active or self.is_ap_active():
            print("[WIFI] Stopping AP mode...")
            self.stop_ap_mode()
            time.sleep(3)

        # Make sure NetworkManager is managing wlan0
        self._run_shell("sudo nmcli dev set wlan0 managed yes")
        time.sleep(2)

        # Try to connect
        success, output = self._run_shell(
            f'sudo nmcli dev wifi connect "{ssid}" password "{password}" ifname {self._interface}',
            timeout=60
        )

        if success:
            # Wait for connection to establish
            time.sleep(3)
            ip = self.get_ip_address()
            print(f"[WIFI] Connected to {ssid}, IP: {ip}")
            return True, f"Connected to {ssid}. IP: {ip}"
        else:
            print(f"[WIFI] Failed to connect: {output}")
            return False, f"Failed to connect: {output}"

    def disconnect(self) -> Tuple[bool, str]:
        """Disconnect from current WiFi network."""
        success, output = self._run_command([
            "nmcli", "dev", "disconnect", self._interface
        ])
        return success, output

    def forget_network(self, ssid: str) -> Tuple[bool, str]:
        """Remove a saved network."""
        success, output = self._run_command([
            "nmcli", "connection", "delete", ssid
        ])
        return success, output

    # ============================================
    # Provisioning Flow
    # ============================================

    def auto_provision(self) -> Tuple[bool, str]:
        """
        Automatic provisioning flow:
        1. Check if connected to WiFi
        2. If not, try saved networks
        3. If still not connected, start AP mode

        Returns:
            Tuple of (is_in_ap_mode, message)
        """
        print("[WIFI] Starting auto-provision...")

        # Check if already connected
        if self.is_connected():
            ssid = self.get_current_ssid()
            ip = self.get_ip_address()
            print(f"[WIFI] Already connected to {ssid} ({ip})")
            return False, f"Connected to {ssid}"

        # Try to connect to any saved network
        if self.has_saved_networks():
            print("[WIFI] Trying saved networks...")
            # NetworkManager should auto-connect, wait a bit
            time.sleep(10)

            if self.is_connected():
                ssid = self.get_current_ssid()
                ip = self.get_ip_address()
                print(f"[WIFI] Connected to saved network {ssid} ({ip})")
                return False, f"Connected to {ssid}"

        # No connection - start AP mode
        print("[WIFI] No WiFi connection, starting AP mode...")
        success, msg = self.start_ap_mode()

        if success:
            return True, f"AP mode active: {self.ap_ssid} (password: {self.ap_password})"
        else:
            return True, f"Failed to start AP: {msg}"

    def get_status(self) -> Dict:
        """Get current WiFi status."""
        import socket
        return {
            "connected": self.is_connected(),
            "current_ssid": self.get_current_ssid(),
            "ip_address": self.get_ip_address(),
            "ap_active": self.is_ap_active(),
            "ap_ssid": self.ap_ssid,
            "interface": self._interface,
            "hostname": socket.gethostname(),
        }


# Convenience functions for backward compatibility
def apply_wifi_settings(ssid: str, password: str) -> bool:
    """Connect to WiFi (legacy function)."""
    provisioner = WiFiProvisioning()
    success, _ = provisioner.connect_to_wifi(ssid, password)
    return success


# Quick test
if __name__ == "__main__":
    print("Testing WiFi Provisioning...")
    print("=" * 60)

    prov = WiFiProvisioning()

    print("\n1. Current Status:")
    status = prov.get_status()
    for k, v in status.items():
        print(f"   {k}: {v}")

    print("\n2. Scanning for networks...")
    networks = prov.scan_networks()
    print(f"   Found {len(networks)} networks:")
    for net in networks[:5]:  # Show top 5
        print(f"   - {net['ssid']} ({net['signal']}%) [{net['security']}]")

    print("\n3. Auto-provision check...")
    in_ap, msg = prov.auto_provision()
    print(f"   AP Mode: {in_ap}")
    print(f"   Message: {msg}")
