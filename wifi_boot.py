#!/usr/bin/env python3
# wifi_boot.py
"""
WiFi boot script for BeautiFi IoT devices.
Runs at startup to check WiFi and start hostapd AP mode if needed.
"""

import subprocess
import sys
import time


def run_cmd(cmd, timeout=30):
    """Run a shell command and return (success, output)."""
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return result.returncode == 0, result.stdout + result.stderr
    except Exception as e:
        return False, str(e)


def is_wifi_connected():
    """Check if connected to a WiFi network."""
    success, output = run_cmd("nmcli -t -f DEVICE,STATE device")
    if success:
        for line in output.strip().split('\n'):
            if 'wlan0:connected' in line:
                return True
    return False


def get_wifi_info():
    """Get current WiFi SSID and IP."""
    ssid = None
    ip = None

    success, output = run_cmd("nmcli -t -f ACTIVE,SSID dev wifi")
    if success:
        for line in output.strip().split('\n'):
            if line.startswith('yes:'):
                ssid = line.split(':', 1)[1]
                break

    success, output = run_cmd("hostname -I")
    if success and output.strip():
        ip = output.strip().split()[0]

    return ssid, ip


def start_hostapd_mode():
    """Start hostapd AP mode on uap0 virtual interface (concurrent AP+STA)."""
    print("[WIFI] Starting AP+STA concurrent mode...")

    # Remove stale uap0 if it exists (idempotent)
    run_cmd("iw dev uap0 del")
    time.sleep(0.5)

    # Create virtual AP interface from wlan0
    success, output = run_cmd("iw dev wlan0 interface add uap0 type __ap")
    if not success:
        print(f"[WIFI] Failed to create uap0: {output}")
        return False
    time.sleep(1)

    # Configure uap0 with static IP for AP
    run_cmd("ip addr flush dev uap0")
    run_cmd("ip addr add 192.168.4.1/24 dev uap0")
    run_cmd("ip link set uap0 up")
    time.sleep(1)

    # Start hostapd and dnsmasq (both configured for uap0)
    success1, out1 = run_cmd("systemctl start hostapd")
    success2, out2 = run_cmd("systemctl start dnsmasq")

    if success1 and success2:
        print("[WIFI] AP mode started on uap0: BeautiFi-Setup")
        print("[WIFI] Password: beautifi123")
        print("[WIFI] Connect and go to http://192.168.4.1:5000")
        print("[WIFI] wlan0 remains available for station mode")
        return True
    else:
        print(f"[WIFI] Failed to start AP: {out1} {out2}")
        return False


def stop_hostapd_mode():
    """Stop hostapd and remove uap0 virtual interface."""
    print("[WIFI] Stopping hostapd AP mode...")
    run_cmd("systemctl stop hostapd")
    run_cmd("systemctl stop dnsmasq")
    run_cmd("ip link set uap0 down")
    run_cmd("iw dev uap0 del")
    time.sleep(1)


def main():
    print("=" * 50)
    print("BeautiFi WiFi Boot Check")
    print("=" * 50)

    # Ensure NetworkManager manages wlan0 for station mode
    run_cmd("nmcli dev set wlan0 managed yes")

    # Wait for NetworkManager to be ready
    print("[WIFI] Waiting for NetworkManager...")
    time.sleep(5)

    # Check if already connected
    if is_wifi_connected():
        ssid, ip = get_wifi_info()
        print(f"[WIFI] Already connected to {ssid} ({ip})")
        return 0

    # Wait a bit longer for auto-connect
    print("[WIFI] Not connected, waiting for auto-connect...")
    time.sleep(10)

    if is_wifi_connected():
        ssid, ip = get_wifi_info()
        print(f"[WIFI] Connected to {ssid} ({ip})")
        return 0

    # No WiFi - start AP mode
    print("[WIFI] No WiFi connection available")
    if start_hostapd_mode():
        print("\n" + "=" * 50)
        print("SETUP MODE ACTIVE")
        print("=" * 50)
        print("1. Connect to WiFi: BeautiFi-Setup")
        print("2. Password: beautifi123")
        print("3. Open browser: http://192.168.4.1:5000")
        print("=" * 50)
        return 0
    else:
        print("[WIFI] Failed to start AP mode")
        return 1


if __name__ == "__main__":
    sys.exit(main())
