#!/usr/bin/env python3
# wifi_boot.py
"""
WiFi boot script for BeautiFi IoT devices.
Runs at startup to check WiFi and start AP mode if needed.
"""

import sys
import time

def main():
    print("=" * 50)
    print("BeautiFi WiFi Boot Check")
    print("=" * 50)

    try:
        from wifi_provisioning import WiFiProvisioning

        prov = WiFiProvisioning()

        # Run auto-provision
        in_ap_mode, message = prov.auto_provision()

        print(f"\nResult: {message}")

        if in_ap_mode:
            print("\n" + "=" * 50)
            print("SETUP MODE ACTIVE")
            print("=" * 50)
            print(f"1. Connect to WiFi: {prov.ap_ssid}")
            print(f"2. Password: {prov.ap_password}")
            print(f"3. Open browser: http://192.168.4.1:5000")
            print("=" * 50)
        else:
            status = prov.get_status()
            print(f"\nConnected to: {status.get('current_ssid')}")
            print(f"IP Address: {status.get('ip_address')}")

        return 0

    except ImportError as e:
        print(f"WiFi provisioning not available: {e}")
        print("Running in simulation mode or missing dependencies")
        return 0

    except Exception as e:
        print(f"WiFi boot error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
