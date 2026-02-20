# BeautiFi IoT - Raspberry Pi Air Quality Monitor

IoT component for the BeautiFi/DUAN ecosystem. Controls ventilation fans, collects air quality telemetry, and generates cryptographically signed evidence packs for blockchain-based rewards (SLN tokens).

## Status: All 8 Phases Complete

| Phase | Feature | Status |
|-------|---------|--------|
| 0 | Fan Control MVP | Done |
| 1 | Sensor Integration | Done (BME680 real on IoT #1, simulated on others) |
| 2 | Telemetry Collection | Done |
| 3 | Device Identity & Ed25519 Signing | Done |
| 4 | Epoch Formation with Merkle Trees | Done |
| 5 | Verifier Integration | Done |
| 6 | Device Registration & Site NFT | Done |
| 7 | Anti-Tamper & Anomaly Detection | Done |
| 8 | OTA Updates & Remote Config | Done |

## Quick Start - New Device Setup

### 1. Flash Pi OS 32-bit Lite

Use Raspberry Pi Imager:
- Set hostname (e.g., `beautifi-2`, `beautifi-3`, etc.)
- Enable SSH with password authentication
- Set username: `pi` with your password
- Optionally configure WiFi (or use AP mode provisioning)

### 2. Run One-Command Setup

SSH into the Pi and run:

```bash
curl -sSL https://raw.githubusercontent.com/ghapster/beautifi-iot/main/setup-new-device.sh | bash
```

This installs everything:
- System dependencies (git, Python, hostapd, dnsmasq)
- Clones repo to `/home/pi/beautifi-iot`
- Creates Python virtualenv and installs packages
- Configures WiFi AP mode for provisioning
- Sets up systemd services
- Auto-generates unique Ed25519 device identity

### 3. WiFi Provisioning (AP+STA Concurrent Mode, v0.6.0+)

If no WiFi is pre-configured, the device automatically enters AP mode on boot:

1. Connect to WiFi network: **BeautiFi-Setup**
2. Password: **beautifi123**
3. Open browser: **http://192.168.4.1:5000**
4. Enter your WiFi credentials manually (scanning not available in AP mode)
5. **Live status feedback** — the setup page shows connection progress in real-time
6. On success: shows your device's IP address with a clickable dashboard link
7. On failure: shows a clear error message (wrong password, network not found, etc.)
8. Hotspot stays active for 60 seconds after successful connection, then shuts down

> **How it works:** The Pi uses AP+STA concurrent mode — a virtual `uap0` interface runs the hotspot while `wlan0` connects to your WiFi. Both run simultaneously on the BCM43438's single radio (same channel). This means the setup page stays accessible throughout the entire connection process, giving real-time feedback instead of going dead.

### 4. Access Your Device (mDNS)

After WiFi setup, access your device using its hostname - no IP lookup needed:

```
http://beautifi-1.local:5000/dashboard
http://beautifi-2.local:5000/dashboard
http://beautifi-3.local:5000/dashboard
http://beautifi-4.local:5000/dashboard
```

The `.local` address works on most home networks via mDNS/Bonjour.

> **mDNS Note:** The device auto-fixes avahi IPv6 on every startup (v0.4.1+): disables IPv6 (`use-ipv6=no`), stops AAAA record publishing over IPv4 (`publish-aaaa-on-ipv4=no`), and always restarts avahi-daemon. This prevents `.local` from resolving to unusable `fe80::` link-local addresses. Applied automatically via OTA.

### 5. Local Access via Miner Dashboard (v0.5.0+)

For phones and devices where mDNS is unreliable, the **Miner Dashboard** shows a clickable "Local Access" link for each online device. The link opens the device's fan control dashboard directly by IP — no `.local` resolution needed.

Each device self-reports its local IP in telemetry every 12 seconds, so the dashboard link stays current even if DHCP reassigns the address. Just open the miner dashboard on any device connected to the same network as the IoT device.

## Features

- **Fan Control**: PWM control for up to 3 fans via GPIO
- **Telemetry**: 12-second sampling of VOC, CO2, PM2.5, temperature, humidity
- **Cryptographic Signing**: Ed25519 device identity with Merkle tree verification
- **Evidence Packs**: Hourly epoch bundles uploaded to Cloudflare R2
- **Backend Integration**: Auto-submission to verifier API with token rewards
- **Remote Control**: Dashboard can toggle fans and set speed (50%/100%)
- **WiFi Provisioning**: AP+STA concurrent mode with live connection status feedback
- **Anomaly Detection**: Statistical outlier and tamper detection
- **Local IP Reporting**: Self-reports LAN IP in telemetry for miner dashboard access link

## Hardware

- Raspberry Pi 3B/4
- AC Infinity Cloudline S6 fans (402 CFM, 70W max)
- SN74 Logic Buffer (PWM signal conditioning)
- PWM-to-0-10V Converter modules
- DROK 12V-5V Buck Converter
- Waveshare IU-BME680 Environmental Sensor (IoT #1 only, I2C address **0x77**)

### GPIO Pins — Fan PWM

| Fan | GPIO Pin | Physical Pin |
|-----|----------|-------------|
| Fan 1 | GPIO 18 | Pin 12 |
| Fan 2 | GPIO 13 | Pin 33 |
| Fan 3 | GPIO 19 | Pin 35 |

### GPIO Pins — BME680 Sensor (IoT #1 only)

| Pi Pin | Function | Wire Color | BME680 Pin |
|--------|----------|------------|------------|
| Pin 1  | 3.3V     | Red        | VCC        |
| Pin 3  | SDA (GPIO 2) | Blue   | SDA/MOSI   |
| Pin 5  | SCL (GPIO 3) | White  | SCL/SCK    |
| Pin 25 | GND      | Black      | GND        |

Default I2C address: **0x77** (configurable to 0x76 by shorting ADDR pad on the board).
Disconnected wires: Green (CS), Orange (ADDR/MISO) — not needed for I2C mode.
Software: `sensors/bme680_reader.py` — activated when `SIMULATION_MODE = False` in `config.py`.

## Useful Commands

```bash
# Check service status
sudo systemctl status beautifi-iot

# View live logs
sudo journalctl -u beautifi-iot -f

# Restart service
sudo systemctl restart beautifi-iot

# Test fan control
curl -X POST http://<IP>:5000/api/fan -H "Content-Type: application/json" -d '{"speed": 50}'
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | WiFi setup page |
| `/dashboard` | GET | Fan control UI |
| `/api/fan` | POST | Set fan speed `{"speed": 0-100}` |
| `/api/wifi/status` | GET | WiFi connection status |
| `/api/wifi/connect` | POST | Connect to network |
| `/api/wifi/connect-status` | GET | Connection progress polling |
| `/api/telemetry/samples` | GET | Recent sensor readings |
| `/api/registration/status` | GET | Commissioning state |
| `/api/system/status` | GET | Full system status |

## Configuration

Edit `config.py`:
- `SIMULATION_MODE = True` - Use simulated sensors (False for real hardware)
- `DEVICE_ID` - Unique device identifier
- `SAMPLE_INTERVAL_SECONDS = 12` - Telemetry sampling rate
- `EPOCH_DURATION_MINUTES = 60` - Epoch length

## User Registration & Token Rewards

When deploying a device to a new location, users must register to earn SLN token rewards.

### Registration Flow

```
1. SETUP DEVICE
   └─ Power on IoT device
   └─ Connect to "BeautiFi-Setup" hotspot
   └─ Configure WiFi at http://192.168.4.1:5000
   └─ Note the Device ID (e.g., btfi-9c5263e883ee1b97)

2. REGISTER ONLINE
   └─ Go to registration portal
   └─ Connect crypto wallet (MetaMask, etc.)
   └─ Fill in salon details
   └─ Enter Device ID from step 1  ← Links device to wallet
   └─ Submit registration

3. ADMIN APPROVAL
   └─ Admin reviews registration
   └─ Approves and mints Site NFT
   └─ Device automatically linked to wallet

4. START EARNING
   └─ Device submits telemetry to backend
   └─ Epochs verified every hour
   └─ SLN tokens credited to registered wallet
```

### Finding Your Device ID

The Device ID is displayed:
- On the device dashboard at `http://<device-ip>:5000/dashboard`
- In the API response: `GET /api/system/status`
- In device logs: `sudo journalctl -u beautifi-iot | grep CRYPTO`

Format: `btfi-` followed by 16 hex characters (e.g., `btfi-9c5263e883ee1b97`)

## OTA Updates (Over-The-Air)

Devices automatically check for and install firmware updates, even when deployed at remote locations.

### Automatic Updates
- Devices check for updates **every 30 minutes**
- Updates are installed when **fans have been OFF for 5+ minutes** (salon likely closed)
- If device was powered off, updates install **on next boot** before fans start
- This prevents ventilation interruption during business hours
- Service restarts after successful update (~5-10 seconds downtime)

### Backend-Triggered Updates
The backend can send update commands to specific devices:

| Command | Value | Action |
|---------|-------|--------|
| `check_update` | - | Check for available updates |
| `perform_update` | - | Download and install update |

### Publishing a New Release

1. Create `releases/latest.json` manifest:
```json
{
  "version": "1.2.0",
  "release_date": "2026-02-04",
  "download_url": "https://github.com/ghapster/beautifi-iot/releases/download/v1.2.0/firmware.zip",
  "file_hash": "<sha256>",
  "file_size": 12345,
  "changelog": "Bug fixes",
  "min_version": "1.0.0"
}
```

2. Create firmware ZIP and upload to GitHub Releases
3. Devices will auto-update within 6 hours (or trigger via backend command)

### Update Safety
- **Backup created** before each update
- **Rollback available** if update fails
- **Signature verification** (optional, for production)
- **System config fixes** applied on startup (e.g., avahi IPv6 + AAAA fix in v0.4.1)

## Remote Fan Control

The device polls the backend every 10 seconds for commands:

| Command | Value | Action |
|---------|-------|--------|
| `fan` | `on` | Set all fans to 100% |
| `fan` | `off` | Set all fans to 0% |
| `set_speed` | `0-100` | Set specific percentage |

## Multi-Device Discovery & Control

The fan dashboard (`/dashboard`) can discover and control multiple BeautiFi devices on the network.

### Discovery Methods

| Method | How It Works | Limitation |
|--------|--------------|------------|
| **Local (self)** | Always shows the device you're connected to | None |
| **mDNS** | Uses Avahi to find `_beautifi._tcp` services | Blocked by WiFi client isolation |
| **Backend** | Queries `/api/devices/online/all` for devices reporting telemetry | Requires internet, no local IP |

### Dashboard Features

- **THIS DEVICE** tag: Identifies the device you're directly connected to
- Fan speed controls: Off / 50% / 100% for all locally reachable devices
- Only devices on the same local network are shown (v0.3.0+)
- Auto-refresh: Click "Refresh" to rescan the network

### API Endpoint

```
GET /api/network/discover
```

Returns all discoverable devices:
```json
{
  "devices": [
    {
      "hostname": "beautifi-1",
      "device_id": "btfi-e8a6eb4a363fe54e",
      "ip": "192.168.0.151",
      "port": "5000",
      "is_self": true,
      "source": "local"
    },
    {
      "hostname": "beautifi-2",
      "device_id": "btfi-9c5263e883ee1b97",
      "ip": null,
      "port": "5000",
      "is_self": false,
      "source": "backend"
    }
  ]
}
```

## Prototype Devices (Feb 2026)

| Device | Hostname | Device ID | Firmware | Status |
|--------|----------|-----------|----------|--------|
| IoT #1 | beautifi-1 | btfi-e8a6eb4a363fe54e | v0.6.0 | ✅ Operational (BME680 real sensor) |
| IoT #2 | beautifi-2 | btfi-9c5263e883ee1b97 | v0.6.0 | ✅ Operational |
| IoT #3 | beautifi-3 | btfi-5e93d18822a826b3 | v0.6.0 | ✅ Operational (offsite) |
| IoT #4 | beautifi-4 | btfi-49311ccf334d9d45 | Unknown | ⏳ Offline |

All prototype devices have:
- WiFi AP mode provisioning configured and tested (hostapd/dnsmasq)
- Fan control working via PWM
- Service files configured to run as root (required for AP mode)
- OTA auto-update enabled (will self-update when powered on)

### Hardware Troubleshooting Notes

**SN74AHCT125 Orientation**: The SN74 logic buffer chip must be oriented correctly with pin 1 (marked by dot/notch) in the correct position. A 180° rotation will cause the chip to overheat and become damaged. If the SN74 gets hot, check orientation immediately and replace with a fresh chip.

**USB-C Breakout Boards**: Use identical breakout boards across all units. Different manufacturers may have different pin labeling. Reference IoT #1 wiring: Pin 1 (GND/B1) and Pin 6 (A8/B6).

**AC Infinity Fan Wiring - RED WIRE WARNING**: AC Infinity fans have a USB-C control cable with 4 wires:
| Wire | Purpose | Connect to Breadboard? |
|------|---------|------------------------|
| Yellow | VSP (0-10V speed control input) | **YES** - to PWM-to-0-10V output |
| Black | Ground | **YES** - to GND rail |
| White | Tach (RPM feedback) | NO - leave unconnected |
| Red | Power reference (~10V output) | **NO - NEVER CONNECT** |

The red wire is a **power OUTPUT** from the fan's internal controller (meant for AC Infinity's proprietary controller). Connecting it to the Pi or any Pi-connected circuit will backfeed voltage and **damage the Pi** (learned the hard way - destroyed a Pi during early development).

**Safe configuration**: Only connect GND and A8 (yellow/VSP) pins from the USB-C breakout to your breadboard. The red and white wires can remain connected inside the fan - they simply float unconnected at the breakout board, which is electrically safe. No need to physically disconnect them inside the fan.

**Service File Fix**: If WiFi hotspot doesn't appear on boot, check `/etc/systemd/system/beautifi-wifi.service` - it must NOT have `User=pi` line (needs to run as root to start hostapd). Fix with: `sudo sed -i '/User=pi/d' /etc/systemd/system/beautifi-wifi.service && sudo systemctl daemon-reload`

## Known Issues / TODO

- [ ] **WiFi Network Scanning** (Low Priority): Network scanning is not available during AP mode (hardware limitation — wlan0 is used by the virtual AP interface). Manual SSID entry works correctly. Users must type their WiFi network name.
- [ ] **Roll out BME680 to other devices**: IoT #1 has a real BME680 sensor wired in and reporting real data. Once validated, wire BME680 sensors into IoT #2, #3, #4 and set `SIMULATION_MODE = False` on each.
- [ ] **Beta Tester Recruitment — Salon Owner Outreach**: Compose a recruitment email and Google Form to identify existing SalonSafe salons for the first BeautiFi IoT beta deployment. The ideal partner is an operating salon that already purchased/installed a SalonSafe ventilation system — we'd swap their fan for the AC Infinity S6 and install the IoT device + BME680 sensor. The form should collect: salon info (name, location, size, station count), current ventilation setup (fan model, duct size, vent destination, control method), technical readiness (WiFi reliability, outlet proximity, building type), availability for a 30–60 min install, and motivation/air quality concerns. Draft email and full form spec are in the conversation history from Feb 19, 2026. Target: 8–12 week beta, salon keeps hardware afterward.
- [ ] **Sponsor Outreach — Buy-and-Burn / Proof-of-Care**: Finalize and send sponsor recruitment email for the PoC buy-and-burn program (whitepaper Section 4.4). Sponsors fund salon air quality and receive verified, permanent, audit-ready impact reports. Tiers: Bronze (month), Silver (quarter), Gold (year), Platinum (lifetime). Two audiences: (1) corporate ESG departments needing audit-proof reporting, (2) mission-driven sponsors who simply want to help. Draft email at `docs/sponsor-outreach-email-draft.md`.

## Related Projects

| Project | Purpose |
|---------|---------|
| [salon-safe-backend](https://github.com/ghapster/salon-safe-backend) | Node.js API backend |
| [salonsafe-vite](https://github.com/ghapster/salonsafe-vite) | Miner dashboard (Vite) |
| [salonsafe-admin-dashboard](https://github.com/ghapster/salonsafe-admin-dashboard) | Admin dashboard |

## Documentation

See `CLAUDE.md` for detailed architecture, wiring diagrams, and implementation notes.

### Firmware Release History

| Version | Date | Changes |
|---------|------|---------|
| v0.6.0 | Feb 8, 2026 | AP+STA concurrent WiFi provisioning with live status feedback; firmware version telemetry reporting |
| v0.5.0 | Feb 7, 2026 | Report local IP in telemetry for miner dashboard Local Access link |
| v0.4.1 | Feb 7, 2026 | Fix AAAA record publishing, always restart avahi on boot |
| v0.4.0 | Feb 7, 2026 | Auto-fix avahi IPv6 on startup |
| v0.3.0 | Feb 6, 2026 | Hide off-network devices from fan dashboard, fix OTA manifest URL |

### Session Notes (Feb 18, 2026)

#### BME680 Real Sensor Integration (IoT #1)
Wired a Waveshare IU-BME680 environmental sensor to IoT #1 (beautifi-1) via I2C. This is the first real sensor on any BeautiFi IoT device — all previous telemetry was simulated.

**What the BME680 measures (real):** Temperature, humidity, barometric pressure, gas resistance (VOC indicator)
**What is estimated from gas resistance:** VOC ppb (via rolling baseline), CO2 ppm, PM2.5 (BME680 does not measure these directly)

**Changes made directly on IoT #1 (not via OTA):**
1. Installed `bme680` Python library
2. Created `sensors/bme680_reader.py` — same `read_all()` interface as `SimulatedSensors`
3. Patched `telemetry/collector.py` — uses `BME680Sensors` when `SIMULATION_MODE = False`, falls back to simulator if sensor init fails
4. Set `SIMULATION_MODE = False` in `config.py`

**Wiring notes:**
- Pin 25 used for GND instead of Pin 9 (Pin 9 taken by SN74 buffer OE1)
- White wire = SCL (not yellow as initially assumed from harness colors)
- I2C must be enabled on Pi: `sudo raspi-config nonint do_i2c 0`
- Verify sensor detection: `sudo i2cdetect -y 1` (should show `77`)

#### Real Sensor Validation Tests (IoT #1)
Ran live tests with the BME680 sensor to validate real-world readings:

**Nail polish remover VOC test:**
- Baseline (fan on 50%, clean air): ~40 ppb
- Peak with open bottle near sensor: ~216 ppb
- Recovery after bottle removed: returned to baseline within minutes

**Fan vs no-fan VOC comparison:**
- Fan OFF: VOC climbed from 63.4 → 73.4 ppb, with occasional spikes to 95 ppb
- Fan ON at 100%: VOC ~74.7-83.6 ppb (no improvement because fan is not connected to ductwork/filter — just recirculating room air)
- Fan ON at 50%, normal operation: ~63-73 ppb

**Key insight:** Fan speed only affects VOC when ducted through a carbon filter. Without ductwork, the fan just recirculates ambient air and VOC readings stay flat regardless of speed.

#### Dashboard Expanded Health Cards (salonsafe-vite)
Added 5 new metric cards to the Health tab, expanding from 5 to 10 cards:
- **Existing:** Air Cleaning (CFM), VOC Level, Power Draw, Temperature, Humidity
- **Added:** VOC Reduction %, CO₂ Level, PM2.5, Barometric Pressure, Gas Resistance

Updated `useDeviceTelemetry.js` to extract pressure_hpa, voc_reduction_pct, gas_resistance, and simulation_mode from telemetry payload. Updated VOC reduction threshold from 500 ppb to 5000 ppb (500 was calibrated for simulated data; real nail salons can spike to 4000+ ppb).

#### Device ID Clarification
Confirmed device ID mapping after initial confusion:
- IoT #1 (`btfi-e8a6eb4a363fe54e`) at 192.168.0.151 — LOCAL, has BME680, registered to salon
- IoT #2 (`btfi-9c5263e883ee1b97`) at 192.168.0.134 — LOCAL, simulated sensors, NOT registered
- IoT #3 (`btfi-5e93d18822a826b3`) at 192.168.1.165 — OFFSITE
- IoT #4 (`btfi-49311ccf334d9d45`) — OFFLINE

#### Building Pressure Balance Detection — Research
Investigated whether the IoT system can detect if a building's ventilation is balanced (positive/negative pressure) as a simple YES/NO indicator.

**Tach wire (white wire) on AC Infinity S6 USB-C cable:**
- The white wire is the **tach (RPM feedback)** signal — already documented but currently left floating/unconnected
- It's physically present inside the USB-C cable alongside the yellow (VSP) and black (GND) wires
- EC fan tach outputs are typically open-collector — can connect directly to a Pi GPIO pin with internal pull-up enabled (no external resistors needed)
- To connect: pick up the white wire's USB-C breakout pin on the Pi side → jumper to a free GPIO pin → enable `GPIO.PUD_UP` in software
- **Safety step:** Before connecting, use a multimeter to verify the tach wire isn't pushing voltage (measure white-to-black with fan running; should be near 0V or low fluctuating if open-collector)

**Tach is useful for:**
- Fan health monitoring (bearing wear, motor degradation)
- Clogged filter detection (RPM drops as filter loads up over weeks)
- Ductwork blockage detection (sudden RPM drop)
- Confirming the fan is actually spinning (currently assumed from PWM)

**Tach is NOT useful for building pressure balance:**
- At any commanded speed, the EC motor controller compensates for back-pressure by drawing more current to maintain RPM
- Building pressure differentials (2-5 Pa) are tiny compared to duct static pressure (hundreds of Pa)
- RPM changes from pressure imbalance would be lost in noise

**Recommended approach for pressure balance detection — Fan-On vs Fan-Off Delta (no external data needed):**

We control the fan and know when it's ON vs OFF. The BME680 measures barometric pressure in both states. The delta between the two tells us if the building has adequate makeup air:

| Scenario | Fan ON pressure | Fan OFF pressure | Delta | Verdict |
|----------|----------------|-----------------|-------|---------|
| Balanced (adequate makeup air) | 1006.0 hPa | 1006.0 hPa | ~0 Pa | BALANCED |
| Negative pressure (no makeup air) | 1005.7 hPa | 1006.0 hPa | -3 Pa | IMBALANCED |

**Why this works without outdoor weather data:**
- We're comparing the sensor **against itself** in two known states — absolute accuracy doesn't matter
- BME680 resolution is 0.18 Pa per reading; sampling every 12 seconds, a 10-minute rolling average easily resolves 2-5 Pa offsets
- If the exhaust fan creates negative pressure (air leaving faster than entering), BME680 sees a pressure drop during fan-on periods
- If the building has balanced supply/exhaust, pressure stays the same regardless of fan state
- Self-calibrating: no API keys, no internet dependency, no external reference

**Algorithm — Transition-based detection using natural business cycles:**

Salons have natural fan cycles: on during business hours, off at night. The device collects 24/7 and detects fan state transitions (off→on, on→off). The transition moments provide the cleanest signal because weather pressure changes are slow (hours) while fan pressure effects are fast (seconds to minutes). An immediate pressure drop when the fan kicks on can only be the fan's doing.

1. Detect fan state transitions (off→on and on→off)
2. Compare average pressure 10 min before vs 10 min after each transition
3. Accumulate transition deltas over multiple days
4. Consistent negative delta on fan-start → **IMBALANCED** (exhaust exceeds makeup air)
5. No consistent delta → **BALANCED**

The system gets more confident over time — day 1 may report "insufficient data," but after a week of daily on/off cycles it has a solid verdict. If someone installs makeup air or fixes HVAC, the system self-corrects within a few days.

**Why tach/power curves won't work for this:**
- EC motor controller compensates for back-pressure by drawing more current to maintain RPM
- Building pressure differentials (2-5 Pa) are negligible vs duct static pressure (hundreds of Pa)
- We don't measure actual power draw or actual CFM — both are interpolated from PWM duty cycle

**Tach wire is still valuable for other purposes** (see above): fan health, filter clogging, ductwork blockage, spin confirmation.

---

### ⏸️ STOPPING POINT — February 19, 2026

**Where things stand:**
- IoT #1 has a real BME680 sensor producing live environmental data (temp, humidity, pressure, VOC)
- Fan control working on IoT #1 (tested at 0%, 50%, 100%)
- Miner dashboard shows 11 health metric cards including Building Balance (was 10)
- Admin dashboard has Balance column in device table + detail card in telemetry view
- **Pressure balance detection IMPLEMENTED and TESTED** — transition-based algorithm using fan-on vs fan-off BME680 barometric pressure delta
  - `sensors/pressure_balance.py` — PressureBalanceTracker class
  - Integrated into `telemetry/collector.py` — feeds pressure + fan state each sample, includes `_pressure_balance` in telemetry
  - Backend passes `pressure_balance` through WebSocket to admin dashboard
  - Live test: 3 transitions completed, status = **BALANCED**, delta = +22.8 Pa, confidence = 30%
  - Confidence grows with more transitions (30% at 3, 100% at 10+); salon gets ~2 transitions/day from natural business cycles
- Pi HAT v1 schematic and BOM in `hardware/beautifi-hat-v1.md` — consolidates breadboard into single PCB (~$15/board)
- Salon registration correctly linked to IoT #1 (`btfi-e8a6eb4a363fe54e`)
- IoT #2 is online and reporting simulated data but NOT registered to any salon

**Next steps when we return:**
1. **Wire BME680 sensors into IoT #2, #3, #4** — same wiring as IoT #1 (Pin 1=3.3V, Pin 3=SDA, Pin 5=SCL, Pin 25=GND, I2C addr 0x77)
2. **Connect tach wire (white)** on IoT #1 as proof-of-concept — find USB-C breakout pin, jumper to GPIO 4 (Pin 7), test with multimeter first
3. **Register IoT #2** to the salon once it has a real sensor
4. **Continue with verify-first signup + registration merge** (plan exists at `C:\Users\CO-OP\.claude\plans\generic-booping-cray.md`)

**Fan is currently OFF on IoT #1.**

*Last Updated: February 19, 2026*
