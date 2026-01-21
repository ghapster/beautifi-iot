# BeautiFi IoT - Project Context for Claude

> This file helps Claude understand the project quickly in new sessions.

## What This Is

BeautiFi IoT is a Raspberry Pi-based device for **DUAN (Decentralized Utility Accountability Network) Proof-of-Air compliance**. It controls ventilation fans in nail salons and generates cryptographically signed telemetry proving air quality compliance for blockchain-based rewards (SLN tokens).

## Project Status: ALL 8 PHASES COMPLETE

| Phase | Feature | Status |
|-------|---------|--------|
| 0 | Fan Control MVP | Done |
| 1 | Sensor Integration (Simulation) | Done |
| 2 | Telemetry Collection | Done |
| 3 | Device Identity & Ed25519 Signing | Done |
| 4 | Epoch Formation with Merkle Trees | Done |
| 5 | Verifier Integration | Done |
| 6 | Device Registration & Site NFT | Done |
| 7 | Anti-Tamper & Anomaly Detection | Done |
| 8 | OTA Updates & Remote Config | Done |

## Key Architecture

```
Pi boots → wifi_boot.py checks WiFi → starts AP mode if needed
                                   → starts app.py Flask server

app.py → Controls fans via GPIO PWM
       → Collects telemetry every 12 seconds
       → Signs data with Ed25519 device key
       → Forms hourly epochs with Merkle roots
       → Streams to verifier backend
       → Detects anomalies
```

## Directory Structure

```
beautifi-iot/
├── app.py                 # Main Flask server (48 API endpoints)
├── config.py              # All configuration constants
├── wifi_provisioning.py   # AP mode & WiFi management
├── wifi_boot.py           # Boot-time WiFi check
├── crypto/
│   ├── identity.py        # Ed25519 keypair management
│   └── signing.py         # Payload & epoch signing, Merkle trees
├── sensors/
│   ├── fan_interpolator.py # CFM/RPM/Watt curves for AC Infinity S6
│   └── simulator.py       # Simulated sensor readings
├── telemetry/
│   └── collector.py       # 12-second sampling, epoch formation
├── network/
│   └── verifier_client.py # Backend streaming with retry buffer
├── security/
│   └── anomaly.py         # Statistical outlier & tamper detection
├── registration/
│   ├── commissioning.py   # 30-min calibration flow
│   ├── manifest.py        # Hardware manifest generation
│   └── backend_client.py  # SalonSafe API client
├── ota/
│   ├── update_manager.py  # Signed firmware updates, rollback
│   └── config_manager.py  # Remote configuration
├── templates/
│   ├── index.html         # WiFi setup page
│   └── fan.html           # Fan control dashboard
├── beautifi-iot.service   # Systemd service (main app)
├── beautifi-wifi.service  # Systemd service (WiFi boot)
└── setup-wifi-provisioning.sh  # Installation script
```

## Hardware Configuration

### Power Architecture
- **12V DC Adapter** → Powers fans + feeds DROK converter
- **DROK Buck Converter** → Steps 12V → 5V → Powers Pi via USB
- **Common ground** shared across all components

### Signal Flow
```
Pi GPIO (3.3V PWM) → SN74 Logic Buffer → PWM-to-0-10V Converter → Fan VSP (yellow wire)
```

### Components
| Component | Purpose |
|-----------|---------|
| Raspberry Pi 3B | PWM generation, control logic |
| AC Infinity Cloudline S6 | Ventilation (402 CFM, 70W max) |
| SN74 Logic Buffer | PWM signal conditioning & isolation |
| PWM-to-0-10V Converter | Converts PWM → analog voltage for fan |
| USB-C Breakout Boards | Access fan VSP (yellow wire) |
| DROK 12V→5V Converter | Pi power from 12V rail |
| Breadboard Rails | Power & ground distribution |

### GPIO Pins
- Fan 1: GPIO 18 (Pin 12)
- Fan 2: GPIO 13 (Pin 33)
- Fan 3: GPIO 19 (Pin 35)
- PWM Frequency: 100 Hz

### Fan Control Notes
- AC Infinity fans use **0-10V analog** for speed control (not direct PWM)
- Yellow wire = VSP (Variable Speed Potentiometer) input
- PWM-to-0-10V modules convert Pi's PWM signal to analog

### Detailed Wiring (3-Fan Setup)

**FAN 1 (GPIO 18)**
```
Pi Pin 12 (GPIO18) → SN74 Pin 2 (input)
SN74 Pin 7 (OE)    → Pi Pin 6 (GND)
SN74 Pin 3 (out)   → PWM Module 1 → Fan 1 VSP (A8)
```

**FAN 2 (GPIO 13)**
```
Pi Pin 33 (GPIO13) → SN74 Pin 5 (input)
SN74 Pin 4         → Pi Pin 14 (GND)
SN74 Pin 6 (out)   → PWM Module 2 → Fan 2 VSP
```

**FAN 3 (GPIO 19)**
```
Pi Pin 35 (GPIO19) → SN74 Pin 9 (input)
SN74 Pin 10        → Pi Pin 20 (GND)
SN74 Pin 8 (out)   → PWM Module 3 → Fan 3 VSP
```

**Shared Power Rails**
```
12V Adapter VIN+ → Breadboard + Rail
12V Adapter VIN− → Breadboard − Rail (common GND)
DROK VCC         → + Rail
DROK GND         → − Rail
Pi powered via DROK 5V USB output
```

### Technical Learnings
- AC Infinity fans require **analog 0-10V**, not direct PWM
- PWM-to-0-10V modules solve this cleanly
- SN74 buffers stabilize PWM and protect the Pi GPIO
- PWM frequency should be ~1kHz (no benefit increasing beyond)
- White tach wire (RPM feedback) is optional, unused currently
- Current config.py has PWM_FREQUENCY=100Hz (may need adjustment to 1kHz)

### Sensors (Currently Simulated)
- Pressure: SDP810-500Pa
- VOC: SGP30
- Power: INA219
- Temp/Humidity: BME280

## Backend Integration

| Service | URL |
|---------|-----|
| SalonSafe Backend | https://salon-safe-backend.onrender.com |
| Admin Dashboard | https://salonsafe-admin-dashboard.vercel.app |
| NFT Contract (BSC Testnet) | 0x6708c25adeca86eeb36b7c5520f5c5d7faf91e69 |
| Token Contract | 0x039a5E5Aa286157ccB84378e26Ea702929DA540c |

## Key API Endpoints

- `GET /` - WiFi setup page
- `GET /dashboard` - Fan control UI
- `POST /api/fan` - Set fan speed `{"speed": 0-100}`
- `GET /api/wifi/status` - WiFi connection status
- `POST /api/wifi/connect` - Connect to network
- `GET /api/telemetry/samples` - Recent sensor readings
- `GET /api/registration/status` - Commissioning state
- `GET /api/system/status` - Full system status

## WiFi Provisioning Flow

1. Pi boots, `wifi_boot.py` runs
2. If no WiFi configured → starts AP mode
3. AP SSID: `BeautiFi-Setup`, Password: `beautifi123`
4. User connects, opens `http://192.168.4.1:5000`
5. User selects network, enters password
6. Pi connects to WiFi, AP stops

## Running the Device

```bash
# Start manually
cd ~/beautifi-iot && python3 app.py

# Or via systemd
sudo systemctl start beautifi-iot
sudo systemctl status beautifi-iot

# View logs
sudo journalctl -u beautifi-iot -f
```

## Configuration (config.py)

- `SIMULATION_MODE = True` - Use simulated sensors (set False for real hardware)
- `DEVICE_ID` - Unique device identifier
- `SAMPLE_INTERVAL_SECONDS = 12` - Telemetry sampling rate
- `EPOCH_DURATION_MINUTES = 60` - Epoch length

## Device Identity

Keys stored in `~/.beautifi/keys/`:
- `device_private.pem` - Ed25519 private key
- `device_public.pem` - Public key
- `identity.json` - Device ID derived from public key

## Common Tasks

**Test fan control:**
```bash
curl -X POST http://192.168.0.151:5000/api/fan -H "Content-Type: application/json" -d '{"speed": 50}'
```

**Check telemetry:**
```bash
curl http://192.168.0.151:5000/api/telemetry/samples?limit=5
```

**Start calibration:**
```bash
curl -X POST http://192.168.0.151:5000/api/registration/calibrate -H "Content-Type: application/json" -d '{"duration_minutes": 1}'
```

## Recent Session Notes (Jan 2026)

- Completed all 8 DUAN compliance phases
- Added WiFi provisioning with AP mode fallback
- Pi IP on local network: 192.168.0.151
- Repo: https://github.com/ghapster/beautifi-iot
- User: ghapster
