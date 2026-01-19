import subprocess
import time

time.sleep(15)

try:
    wifi = subprocess.check_output(["iwgetid"])
    if wifi:
        print("✅ Wi-Fi is connected.")
    else:
        raise Exception("No Wi-Fi")
except:
    print("❗ No Wi-Fi. Starting fallback hotspot...")
    subprocess.run(["systemctl", "start", "hostapd"])
    subprocess.run(["systemctl", "start", "dnsmasq"])

