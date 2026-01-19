import subprocess

def apply_wifi_settings(ssid, password):
    try:
        cmd = ["nmcli", "device", "wifi", "connect", ssid, "password", password]
        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode == 0:
            print("✅ Wi-Fi connection added.")
            return True
        else:
            print(f"❌ Failed: {result.stderr}")
            return False
    except Exception as e:
        print(f"🔥 Exception: {e}")
        return False

