from flask import Flask, request, jsonify, render_template
import subprocess, threading, time
import RPi.GPIO as GPIO
from wifi_config import apply_wifi_settings

# --- Flask Setup ---
app = Flask(__name__, template_folder='templates')

# --- Fan GPIO Setup ---
FAN_PWM_PINS = {
    "Fan 1": 18,
    "Fan 2": 13,
    "Fan 3": 19
}
FREQ = 100
DELAY_BETWEEN = 5  # seconds between staggered starts

GPIO.setwarnings(False)
GPIO.setmode(GPIO.BCM)

pwms = {}
for name, pin in FAN_PWM_PINS.items():
    GPIO.setup(pin, GPIO.OUT)
    pwm = GPIO.PWM(pin, FREQ)
    pwm.start(0)
    pwms[name] = pwm
    print(f"{name} initialized on GPIO{pin}")

# --- Routes ---
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/dashboard')
def dashboard():
    return render_template('fan.html')

@app.route('/api/iot/connect-wifi', methods=['POST'])
def connect_wifi():
    ssid = request.form.get('ssid')
    password = request.form.get('password')

    if not ssid or not password:
        return jsonify({'error': 'SSID and password required'}), 400

    success = apply_wifi_settings(ssid, password)
    if success:
        subprocess.run(["sudo", "reboot"])
        return jsonify({'message': 'WiFi connected. Rebooting...'}), 200
    else:
        return jsonify({'error': 'Failed to connect via nmcli'}), 500

@app.route('/api/fan', methods=['POST'])
def set_fan_speed():
    try:
        data = request.get_json()
        speed = int(data.get('speed'))

        if speed < 0 or speed > 100:
            return jsonify({"error": "Speed must be between 0 and 100"}), 400

        def ramp():
            print(f"🚀 Setting all fans to {speed}%")
            for i, (name, pwm) in enumerate(pwms.items()):
                time.sleep(i * DELAY_BETWEEN)
                print(f"{name} → {speed}%")
                pwm.ChangeDutyCycle(speed)

        threading.Thread(target=ramp).start()

        return jsonify({"status": f"All fans ramping to {speed}% staggered by {DELAY_BETWEEN}s"})

    except Exception as e:
        print("❌ Fan control error:", e)
        return jsonify({"error": str(e)}), 500

# --- Cleanup on Exit ---
@app.before_first_request
def setup_fan_cleanup():
    import atexit
    def cleanup():
        for pwm in pwms.values():
            pwm.ChangeDutyCycle(0)
            pwm.stop()
        GPIO.cleanup()
        print("🧼 Cleaned up GPIO on exit.")
    atexit.register(cleanup)

# --- Launch ---
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)




