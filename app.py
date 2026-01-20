"""
BeautiFi IoT - Main Flask Application

Fan control server with telemetry collection for DUAN Proof-of-Air.
"""

from flask import Flask, request, jsonify, render_template
import subprocess
import threading
import time
import atexit

# Configuration
from config import (
    SIMULATION_MODE,
    DEVICE_ID,
    FIRMWARE_VERSION,
    FAN_PWM_PINS,
    PWM_FREQUENCY,
    SAMPLE_INTERVAL_SECONDS,
    VERIFIER_URL,
    VERIFIER_API_KEY,
    SYNC_INTERVAL_SECONDS,
    ENABLE_VERIFIER_SYNC,
)

# Telemetry
from telemetry import TelemetryCollector
from sensors import FanInterpolator

# Network / Verifier
from network import VerifierClient

# --- Flask Setup ---
app = Flask(__name__, template_folder='templates')

# --- Fan State ---
current_speeds = {name: 0 for name in FAN_PWM_PINS}
fan_interpolator = FanInterpolator()

# --- GPIO Setup (only on Raspberry Pi) ---
pwms = {}
GPIO = None

try:
    import RPi.GPIO as GPIO
    from wifi_config import apply_wifi_settings

    GPIO.setwarnings(False)
    GPIO.setmode(GPIO.BCM)

    for name, pin in FAN_PWM_PINS.items():
        GPIO.setup(pin, GPIO.OUT)
        pwm = GPIO.PWM(pin, PWM_FREQUENCY)
        pwm.start(0)
        pwms[name] = pwm
        print(f"[OK] {name} initialized on GPIO{pin}")

    RUNNING_ON_PI = True
except (ImportError, RuntimeError) as e:
    print(f"[WARN] GPIO not available (not on Pi or no permissions): {e}")
    print("       Running in simulation-only mode")
    RUNNING_ON_PI = False

    def apply_wifi_settings(ssid, password):
        print(f"[SIM] Would connect to WiFi: {ssid}")
        return True


def get_average_pwm() -> float:
    """Get average PWM across all fans for telemetry."""
    if not current_speeds:
        return 0
    return sum(current_speeds.values()) / len(current_speeds)


# --- Telemetry Collector ---
telemetry_collector = TelemetryCollector(
    db_path="telemetry.db",
    pwm_getter=get_average_pwm
)

# --- Verifier Client ---
verifier_client = None
if ENABLE_VERIFIER_SYNC:
    verifier_client = VerifierClient(
        verifier_url=VERIFIER_URL,
        device_id=DEVICE_ID,
        api_key=VERIFIER_API_KEY,
        buffer_db_path="sync_buffer.db",
        sync_interval_seconds=SYNC_INTERVAL_SECONDS,
    )

    # Wire up telemetry -> verifier streaming
    def on_sample_collected(sample: dict):
        """Send each sample to verifier as it's collected."""
        if verifier_client:
            verifier_client.send_sample(sample)

    def on_epoch_complete(epoch: dict):
        """Submit completed epochs to verifier."""
        if verifier_client:
            verifier_client.send_epoch(epoch)

    telemetry_collector.add_callback(on_sample_collected)
    telemetry_collector.set_epoch_callback(on_epoch_complete)

    print(f"[VERIFIER] Streaming enabled to {VERIFIER_URL}")


# ============================================
# ROUTES - Pages
# ============================================

@app.route('/')
def index():
    """Landing page."""
    return render_template('index.html')


@app.route('/dashboard')
def dashboard():
    """Fan control dashboard."""
    return render_template('fan.html')


# ============================================
# ROUTES - Device Info
# ============================================

@app.route('/api/info', methods=['GET'])
def device_info():
    """Get device information and status."""
    return jsonify({
        "device_id": DEVICE_ID,
        "firmware_version": FIRMWARE_VERSION,
        "simulation_mode": SIMULATION_MODE,
        "running_on_pi": RUNNING_ON_PI,
        "fan_count": len(FAN_PWM_PINS),
        "sample_interval_seconds": SAMPLE_INTERVAL_SECONDS,
        "telemetry_active": telemetry_collector._running,
    })


# ============================================
# ROUTES - Fan Control
# ============================================

@app.route('/api/fan', methods=['POST'])
def set_fan_speed():
    """
    Set fan speed for all fans.

    Body: {"speed": 0-100}
    """
    try:
        data = request.get_json()
        speed = int(data.get('speed', 0))

        if speed < 0 or speed > 100:
            return jsonify({"error": "Speed must be between 0 and 100"}), 400

        def ramp():
            delay_between = 5  # seconds between staggered starts
            print(f">> Setting all fans to {speed}%")

            for i, (name, _) in enumerate(FAN_PWM_PINS.items()):
                time.sleep(i * delay_between)
                print(f"  {name} -> {speed}%")
                current_speeds[name] = speed

                if RUNNING_ON_PI and name in pwms:
                    pwms[name].ChangeDutyCycle(speed)

        threading.Thread(target=ramp).start()

        # Get interpolated metrics for response
        metrics = fan_interpolator.get_all_metrics(speed)

        return jsonify({
            "status": f"All fans ramping to {speed}%",
            "target_speed": speed,
            "estimated_cfm": metrics["cfm"],
            "estimated_watts": metrics["watts"],
            "estimated_rpm": metrics["rpm"],
        })

    except Exception as e:
        print(f"[ERR] Fan control error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/fan/status', methods=['GET'])
def fan_status():
    """Get current fan status with interpolated metrics."""
    avg_pwm = get_average_pwm()
    metrics = fan_interpolator.get_all_metrics(avg_pwm)

    return jsonify({
        "fans": current_speeds,
        "average_pwm": avg_pwm,
        "estimated": metrics,
    })


# ============================================
# ROUTES - Telemetry
# ============================================

@app.route('/api/telemetry/start', methods=['POST'])
def start_telemetry():
    """Start telemetry collection."""
    if telemetry_collector._running:
        return jsonify({"status": "already running"})

    telemetry_collector.start()
    return jsonify({"status": "started"})


@app.route('/api/telemetry/stop', methods=['POST'])
def stop_telemetry():
    """Stop telemetry collection."""
    if not telemetry_collector._running:
        return jsonify({"status": "not running"})

    telemetry_collector.stop()
    return jsonify({"status": "stopped"})


@app.route('/api/telemetry/status', methods=['GET'])
def telemetry_status():
    """Get telemetry collection status."""
    return jsonify({
        "running": telemetry_collector._running,
        "simulation_mode": SIMULATION_MODE,
        "sample_interval": SAMPLE_INTERVAL_SECONDS,
        "current_epoch_samples": len(telemetry_collector._current_epoch_samples),
    })


@app.route('/api/telemetry/samples', methods=['GET'])
def get_samples():
    """Get recent telemetry samples."""
    limit = request.args.get('limit', 100, type=int)
    samples = telemetry_collector.get_recent_samples(limit)
    return jsonify({
        "count": len(samples),
        "samples": samples,
    })


@app.route('/api/telemetry/epochs', methods=['GET'])
def get_epochs():
    """Get recent epochs."""
    limit = request.args.get('limit', 24, type=int)
    epochs = telemetry_collector.get_recent_epochs(limit)
    return jsonify({
        "count": len(epochs),
        "epochs": epochs,
    })


@app.route('/api/telemetry/current', methods=['GET'])
def get_current_reading():
    """Get a single current reading (does not store)."""
    from sensors import SimulatedSensors
    sensors = SimulatedSensors(fan_interpolator)
    reading = sensors.read_all(get_average_pwm())
    return jsonify(reading)


# ============================================
# ROUTES - WiFi Configuration
# ============================================

@app.route('/api/iot/connect-wifi', methods=['POST'])
def connect_wifi():
    """Configure WiFi connection."""
    ssid = request.form.get('ssid') or request.json.get('ssid')
    password = request.form.get('password') or request.json.get('password')

    if not ssid or not password:
        return jsonify({'error': 'SSID and password required'}), 400

    success = apply_wifi_settings(ssid, password)

    if success:
        if RUNNING_ON_PI:
            subprocess.run(["sudo", "reboot"])
        return jsonify({'message': 'WiFi connected. Rebooting...'}), 200
    else:
        return jsonify({'error': 'Failed to connect via nmcli'}), 500


# ============================================
# ROUTES - Device Identity (Crypto)
# ============================================

@app.route('/api/identity', methods=['GET'])
def get_identity():
    """Get device cryptographic identity."""
    identity_info = telemetry_collector.get_device_identity_info()
    if identity_info:
        return jsonify({
            "status": "ok",
            "signing_enabled": True,
            **identity_info,
        })
    else:
        return jsonify({
            "status": "unavailable",
            "signing_enabled": False,
            "message": "Cryptographic identity not available",
        })


@app.route('/api/telemetry/verify', methods=['POST'])
def verify_sample():
    """Verify a signed telemetry sample."""
    try:
        from crypto import verify_signature
        sample = request.get_json()

        if '_signing' not in sample:
            return jsonify({"valid": False, "message": "No signature present"}), 400

        is_valid, message = verify_signature(sample)
        return jsonify({
            "valid": is_valid,
            "message": message,
            "payload_hash": sample['_signing'].get('payload_hash'),
        })
    except ImportError:
        return jsonify({"error": "Crypto module not available"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ============================================
# ROUTES - Verifier Sync Status
# ============================================

@app.route('/api/sync/status', methods=['GET'])
def sync_status():
    """Get verifier sync status."""
    if verifier_client is None:
        return jsonify({
            "enabled": False,
            "message": "Verifier sync is disabled",
        })

    status = verifier_client.get_status()
    return jsonify({
        "enabled": True,
        "verifier_url": VERIFIER_URL,
        **status.to_dict(),
    })


@app.route('/api/sync/force', methods=['POST'])
def force_sync():
    """Force an immediate sync attempt."""
    if verifier_client is None:
        return jsonify({"error": "Verifier sync is disabled"}), 400

    result = verifier_client.force_sync()
    return jsonify({
        "status": "sync attempted",
        **result,
    })


@app.route('/api/sync/verifications', methods=['GET'])
def get_verifications():
    """Get recent verification responses from verifier."""
    if verifier_client is None:
        return jsonify({"error": "Verifier sync is disabled"}), 400

    limit = request.args.get('limit', 10, type=int)
    verifications = verifier_client.get_verifications(limit)
    return jsonify({
        "count": len(verifications),
        "verifications": verifications,
    })


# ============================================
# ROUTES - Security / Anomaly Detection
# ============================================

@app.route('/api/security/status', methods=['GET'])
def security_status():
    """Get anomaly detection status."""
    status = telemetry_collector.get_anomaly_status()
    if status is None:
        return jsonify({
            "enabled": False,
            "message": "Anomaly detection is disabled",
        })

    return jsonify({
        "enabled": True,
        **status,
    })


@app.route('/api/security/baselines', methods=['GET'])
def security_baselines():
    """Get current baseline statistics for all sensors."""
    baselines = telemetry_collector.get_anomaly_baselines()
    if baselines is None:
        return jsonify({"error": "Anomaly detection is disabled"}), 400

    return jsonify({
        "fields": baselines,
    })


@app.route('/api/security/anomalies', methods=['GET'])
def get_anomalies():
    """Get recent anomalies detected."""
    limit = request.args.get('limit', 50, type=int)
    anomalies = telemetry_collector.get_recent_anomalies(limit)
    return jsonify({
        "count": len(anomalies),
        "anomalies": anomalies,
    })


# ============================================
# ROUTES - Sensors (Direct Access)
# ============================================

@app.route('/api/sensors/fan-table', methods=['GET'])
def get_fan_table():
    """Get full fan performance interpolation table."""
    table = fan_interpolator.get_speed_table()
    return jsonify({
        "fan_model": "AC Infinity Cloudline S6",
        "table": table,
    })


# ============================================
# Cleanup & Startup
# ============================================

def cleanup():
    """Clean up GPIO, stop telemetry, and stop verifier on exit."""
    print("\n[CLEAN] Cleaning up...")

    # Stop verifier sync
    if verifier_client:
        verifier_client.stop()

    # Stop telemetry
    telemetry_collector.stop()

    # Clean up GPIO
    if RUNNING_ON_PI and GPIO:
        for pwm in pwms.values():
            pwm.ChangeDutyCycle(0)
            pwm.stop()
        GPIO.cleanup()
        print("[OK] GPIO cleaned up")

    print("[BYE] Goodbye!")


atexit.register(cleanup)


# ============================================
# Main Entry Point
# ============================================

if __name__ == '__main__':
    print("=" * 60)
    print("  BeautiFi IoT - DUAN Proof-of-Air Device")
    print(f"  Device ID: {DEVICE_ID}")
    print(f"  Firmware: {FIRMWARE_VERSION}")
    print(f"  Mode: {'SIMULATION' if SIMULATION_MODE else 'PRODUCTION'}")
    print(f"  Running on Pi: {RUNNING_ON_PI}")
    print(f"  Verifier: {VERIFIER_URL if ENABLE_VERIFIER_SYNC else 'DISABLED'}")
    print("=" * 60)

    # Start verifier background sync
    if verifier_client:
        verifier_client.start()

    # Auto-start telemetry collection
    telemetry_collector.start()

    # Run Flask server
    app.run(host='0.0.0.0', port=5000, debug=False)
