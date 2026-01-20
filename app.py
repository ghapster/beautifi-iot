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
    BACKEND_URL,
    CALIBRATION_DURATION_MINUTES,
)

# Telemetry
from telemetry import TelemetryCollector
from sensors import FanInterpolator

# Network / Verifier
from network import VerifierClient

# Registration
from registration import CommissioningManager, RegistrationClient, HardwareManifest

# OTA Updates
from ota import UpdateManager, ConfigManager

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

# --- Registration / Commissioning ---
commissioning_manager = CommissioningManager(db_path="commissioning.db")
registration_client = RegistrationClient(
    backend_url=BACKEND_URL,
    device_id=DEVICE_ID,
)
print(f"[REGISTER] Backend: {BACKEND_URL}")

# --- OTA / Configuration ---
update_manager = UpdateManager()
config_manager = ConfigManager()
print(f"[OTA] Update manager ready")


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

# WiFi provisioning instance (created on Pi only)
wifi_provisioner = None
if RUNNING_ON_PI:
    try:
        from wifi_provisioning import WiFiProvisioning
        wifi_provisioner = WiFiProvisioning()
        print("[WIFI] Provisioning module loaded")
    except Exception as e:
        print(f"[WIFI] Provisioning not available: {e}")


@app.route('/api/wifi/status', methods=['GET'])
def wifi_status():
    """Get current WiFi status."""
    if wifi_provisioner is None:
        return jsonify({
            "error": "WiFi provisioning not available (not on Pi)",
            "simulation": True
        })

    return jsonify(wifi_provisioner.get_status())


@app.route('/api/wifi/scan', methods=['GET'])
def wifi_scan():
    """Scan for available WiFi networks."""
    if wifi_provisioner is None:
        return jsonify({
            "networks": [
                {"ssid": "SimulatedNetwork", "signal": "80", "security": "WPA2"}
            ],
            "simulation": True
        })

    networks = wifi_provisioner.scan_networks()
    return jsonify({
        "count": len(networks),
        "networks": networks
    })


@app.route('/api/wifi/connect', methods=['POST'])
def wifi_connect():
    """Connect to a WiFi network."""
    data = request.get_json() or {}
    ssid = data.get('ssid') or request.form.get('ssid')
    password = data.get('password') or request.form.get('password')

    if not ssid or not password:
        return jsonify({'error': 'SSID and password required'}), 400

    if wifi_provisioner is None:
        return jsonify({
            'success': True,
            'message': 'Simulated connection (not on Pi)',
            'simulation': True
        })

    success, message = wifi_provisioner.connect_to_wifi(ssid, password)

    return jsonify({
        'success': success,
        'message': message,
        'status': wifi_provisioner.get_status()
    })


@app.route('/api/wifi/ap/start', methods=['POST'])
def wifi_ap_start():
    """Start Access Point (hotspot) mode."""
    if wifi_provisioner is None:
        return jsonify({'error': 'WiFi provisioning not available'}), 400

    success, message = wifi_provisioner.start_ap_mode()
    return jsonify({
        'success': success,
        'message': message,
        'ap_ssid': wifi_provisioner.ap_ssid,
        'ap_password': wifi_provisioner.ap_password
    })


@app.route('/api/wifi/ap/stop', methods=['POST'])
def wifi_ap_stop():
    """Stop Access Point mode."""
    if wifi_provisioner is None:
        return jsonify({'error': 'WiFi provisioning not available'}), 400

    success, message = wifi_provisioner.stop_ap_mode()
    return jsonify({
        'success': success,
        'message': message
    })


@app.route('/api/iot/connect-wifi', methods=['POST'])
def connect_wifi():
    """Configure WiFi connection (legacy endpoint)."""
    ssid = request.form.get('ssid') or (request.json or {}).get('ssid')
    password = request.form.get('password') or (request.json or {}).get('password')

    if not ssid or not password:
        return jsonify({'error': 'SSID and password required'}), 400

    if wifi_provisioner:
        success, message = wifi_provisioner.connect_to_wifi(ssid, password)
    else:
        from wifi_config import apply_wifi_settings
        success = apply_wifi_settings(ssid, password)
        message = "Connected" if success else "Failed"

    if success:
        return jsonify({'message': f'WiFi connected to {ssid}', 'success': True}), 200
    else:
        return jsonify({'error': message, 'success': False}), 500


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
# ROUTES - Registration / Commissioning
# ============================================

@app.route('/api/registration/status', methods=['GET'])
def registration_status():
    """Get commissioning/registration status."""
    return jsonify(commissioning_manager.get_status())


@app.route('/api/registration/manifest', methods=['GET'])
def get_manifest():
    """Get hardware manifest."""
    manifest_gen = HardwareManifest()
    manifest = manifest_gen.generate()
    return jsonify(manifest)


@app.route('/api/registration/calibrate', methods=['POST'])
def start_calibration():
    """Start baseline calibration."""
    data = request.get_json() or {}
    duration = data.get('duration_minutes', CALIBRATION_DURATION_MINUTES)

    # Create sensor reader that uses current telemetry setup
    def sensor_reader():
        from sensors import SimulatedSensors
        sensors = SimulatedSensors(fan_interpolator)
        return sensors.read_all(get_average_pwm())

    success = commissioning_manager.start_calibration(
        duration_minutes=duration,
        sensor_reader=sensor_reader,
    )

    if success:
        return jsonify({
            "status": "calibration_started",
            "duration_minutes": duration,
        })
    else:
        return jsonify({
            "error": "Could not start calibration",
            "current_state": commissioning_manager.state.value,
        }), 400


@app.route('/api/registration/calibrate/stop', methods=['POST'])
def stop_calibration():
    """Stop calibration early."""
    commissioning_manager.stop_calibration()
    return jsonify({
        "status": "calibration_stopped",
        "state": commissioning_manager.state.value,
    })


@app.route('/api/registration/register', methods=['POST'])
def register_device():
    """Submit device registration to backend."""
    data = request.get_json()

    if not data:
        return jsonify({"error": "Request body required"}), 400

    required_fields = ['wallet_address', 'salon_name', 'location', 'email']
    missing = [f for f in required_fields if f not in data]
    if missing:
        return jsonify({"error": f"Missing required fields: {missing}"}), 400

    success = commissioning_manager.register(
        wallet_address=data['wallet_address'],
        salon_name=data['salon_name'],
        location=data['location'],
        email=data['email'],
        backend_client=registration_client,
        reseller=data.get('reseller', ''),
        installer=data.get('installer', ''),
        manicure_stations=data.get('manicure_stations', 0),
        pedicure_stations=data.get('pedicure_stations', 0),
        comments=data.get('comments', ''),
    )

    if success:
        return jsonify({
            "status": "registration_submitted",
            "registration_id": commissioning_manager._registration_id,
            "message": "Registration submitted. Awaiting admin approval.",
        })
    else:
        return jsonify({
            "error": "Registration failed",
            "state": commissioning_manager.state.value,
        }), 500


@app.route('/api/registration/check-approval', methods=['GET'])
def check_approval():
    """Check if registration has been approved."""
    is_approved = commissioning_manager.check_approval(registration_client)

    return jsonify({
        "approved": is_approved,
        "state": commissioning_manager.state.value,
        "nft_binding": commissioning_manager.nft_binding,
    })


@app.route('/api/registration/reset', methods=['POST'])
def reset_registration():
    """Reset commissioning state (for re-registration)."""
    commissioning_manager.reset()
    return jsonify({
        "status": "reset",
        "state": commissioning_manager.state.value,
    })


@app.route('/api/registration/backend-ping', methods=['GET'])
def ping_backend():
    """Check if backend is reachable."""
    is_online = registration_client.ping()
    return jsonify({
        "backend_url": BACKEND_URL,
        "online": is_online,
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
# ROUTES - OTA Updates
# ============================================

@app.route('/api/system/status', methods=['GET'])
def system_status():
    """Get overall system status including update info."""
    return jsonify({
        "device_id": DEVICE_ID,
        "firmware_version": FIRMWARE_VERSION,
        "simulation_mode": SIMULATION_MODE,
        "update_status": update_manager.get_status(),
        "config_status": config_manager.get_status(),
    })


@app.route('/api/system/update/check', methods=['GET'])
def check_updates():
    """Check for available firmware updates."""
    available, manifest, message = update_manager.check_for_updates()
    result = {
        "update_available": available,
        "message": message,
        "current_version": FIRMWARE_VERSION,
    }
    if manifest:
        result["available_version"] = manifest.version
        result["changelog"] = manifest.changelog
        result["release_date"] = manifest.release_date
    return jsonify(result)


@app.route('/api/system/update/download', methods=['POST'])
def download_update():
    """Download available firmware update."""
    if update_manager.status.value not in ["available", "idle"]:
        return jsonify({
            "error": f"Cannot download in state: {update_manager.status.value}"
        }), 400

    # Check first
    available, manifest, msg = update_manager.check_for_updates()
    if not available:
        return jsonify({"error": msg}), 400

    success, message = update_manager.download_update(manifest)
    return jsonify({
        "success": success,
        "message": message,
        "status": update_manager.status.value,
    })


@app.route('/api/system/update/install', methods=['POST'])
def install_update():
    """Install downloaded firmware update."""
    data = request.get_json() or {}
    auto_backup = data.get("auto_backup", True)
    auto_restart = data.get("auto_restart", False)

    success, message = update_manager.install_update(
        auto_backup=auto_backup,
        auto_restart=auto_restart,
    )

    return jsonify({
        "success": success,
        "message": message,
        "status": update_manager.status.value,
    })


@app.route('/api/system/update/perform', methods=['POST'])
def perform_update():
    """Perform full update: check, download, install."""
    data = request.get_json() or {}
    auto_backup = data.get("auto_backup", True)
    auto_restart = data.get("auto_restart", False)

    success, message = update_manager.perform_update(
        auto_backup=auto_backup,
        auto_restart=auto_restart,
    )

    return jsonify({
        "success": success,
        "message": message,
        "status": update_manager.status.value,
    })


@app.route('/api/system/backups', methods=['GET'])
def list_backups():
    """List available firmware backups."""
    backups = update_manager.list_backups()
    return jsonify({
        "count": len(backups),
        "backups": backups,
    })


@app.route('/api/system/rollback', methods=['POST'])
def rollback_firmware():
    """Rollback to a previous firmware version."""
    data = request.get_json() or {}
    backup_path = data.get("backup_path")

    success, message = update_manager.rollback(backup_path)
    return jsonify({
        "success": success,
        "message": message,
    })


# ============================================
# ROUTES - Remote Configuration
# ============================================

@app.route('/api/system/config', methods=['GET'])
def get_config():
    """Get current device configuration."""
    return jsonify({
        "config": config_manager.get_all(),
        "status": config_manager.get_status(),
    })


@app.route('/api/system/config', methods=['POST'])
def update_config():
    """Update device configuration."""
    data = request.get_json()
    if not data:
        return jsonify({"error": "No configuration data provided"}), 400

    # Check for signature (for remote updates)
    signature = data.pop("_signature", None)

    if signature:
        success, results = config_manager.apply_remote_config(data, signature)
    else:
        success, results = config_manager.set_multiple(data, source="api")

    return jsonify({
        "success": success,
        "results": results,
    })


@app.route('/api/system/config/<key>', methods=['GET'])
def get_config_value(key):
    """Get a specific configuration value."""
    value = config_manager.get(key)
    if value is None and key not in config_manager.ALLOWED_FIELDS:
        return jsonify({"error": f"Unknown configuration key: {key}"}), 404

    return jsonify({
        "key": key,
        "value": value,
    })


@app.route('/api/system/config/<key>', methods=['PUT'])
def set_config_value(key):
    """Set a specific configuration value."""
    data = request.get_json()
    if data is None or "value" not in data:
        return jsonify({"error": "Value required"}), 400

    success, message = config_manager.set(key, data["value"], source="api")
    return jsonify({
        "success": success,
        "message": message,
        "key": key,
        "value": config_manager.get(key),
    })


@app.route('/api/system/config/reset', methods=['POST'])
def reset_config():
    """Reset configuration to defaults."""
    old_config = config_manager.reset_to_defaults()
    return jsonify({
        "status": "reset",
        "previous_config": old_config,
        "current_config": config_manager.get_all(),
    })


@app.route('/api/system/config/history', methods=['GET'])
def config_history():
    """Get configuration change history."""
    limit = request.args.get('limit', 50, type=int)
    history = config_manager.get_history(limit)
    return jsonify({
        "count": len(history),
        "history": history,
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
