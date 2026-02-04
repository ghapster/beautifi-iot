# BeautiFi IoT - Raspberry Pi Air Quality Monitor

IoT component for the BeautiFi/DUAN ecosystem. Controls ventilation fans, collects air quality telemetry, and generates cryptographically signed evidence packs for blockchain-based rewards (SLN tokens).

## Status: All 8 Phases Complete

| Phase | Feature | Status |
|-------|---------|--------|
| 0 | Fan Control MVP | Done |
| 1 | Sensor Integration | Done (Simulation) |
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

### 3. WiFi Provisioning (AP Mode)

If no WiFi is pre-configured, the device automatically enters AP mode on boot:

1. Connect to WiFi network: **BeautiFi-Setup**
2. Password: **beautifi123**
3. Open browser: **http://192.168.4.1:5000**
4. Enter your WiFi credentials manually (scanning not available in AP mode)
5. Device connects and hotspot disappears

> **Note:** The WiFi provisioning UI is functional but needs polish. Network scanning is not available while in AP mode. This is a known limitation - manual SSID entry works correctly.

### 4. Access Your Device (mDNS)

After WiFi setup, access your device using its hostname - no IP lookup needed:

```
http://beautifi-1.local:5000/dashboard
http://beautifi-2.local:5000/dashboard
http://beautifi-3.local:5000/dashboard
http://beautifi-4.local:5000/dashboard
```

The `.local` address works on most home networks via mDNS/Bonjour.

## Features

- **Fan Control**: PWM control for up to 3 fans via GPIO
- **Telemetry**: 12-second sampling of VOC, CO2, PM2.5, temperature, humidity
- **Cryptographic Signing**: Ed25519 device identity with Merkle tree verification
- **Evidence Packs**: Hourly epoch bundles uploaded to Cloudflare R2
- **Backend Integration**: Auto-submission to verifier API with token rewards
- **Remote Control**: Dashboard can toggle fans and set speed (50%/100%)
- **WiFi Provisioning**: AP mode fallback for initial setup
- **Anomaly Detection**: Statistical outlier and tamper detection

## Hardware

- Raspberry Pi 3B/4
- AC Infinity Cloudline S6 fans (402 CFM, 70W max)
- SN74 Logic Buffer (PWM signal conditioning)
- PWM-to-0-10V Converter modules
- DROK 12V-5V Buck Converter

### GPIO Pins

| Fan | GPIO Pin |
|-----|----------|
| Fan 1 | 18 |
| Fan 2 | 13 |
| Fan 3 | 19 |

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

## Remote Fan Control

The device polls the backend every 10 seconds for commands:

| Command | Value | Action |
|---------|-------|--------|
| `fan` | `on` | Set all fans to 100% |
| `fan` | `off` | Set all fans to 0% |
| `set_speed` | `0-100` | Set specific percentage |

## Prototype Devices (Feb 2026)

| Device | Hostname | Device ID | Status |
|--------|----------|-----------|--------|
| IoT #1 | beautifi-1 | btfi-e8a6eb4a363fe54e | ✅ Fully operational |
| IoT #2 | beautifi-2 | btfi-9c5263e883ee1b97 | ✅ Fully operational |
| IoT #3 | beautifi-3 | btfi-5e93d18822a826b3 | ✅ Fully operational |
| IoT #4 | beautifi-4 | btfi-49311ccf334d9d45 | ✅ Fully operational |

All prototype devices have:
- Latest code from GitHub
- WiFi AP mode provisioning configured and tested (hostapd/dnsmasq)
- Fan control working via PWM
- Service files configured to run as root (required for AP mode)

### Hardware Troubleshooting Notes

**SN74AHCT125 Orientation**: The SN74 logic buffer chip must be oriented correctly with pin 1 (marked by dot/notch) in the correct position. A 180° rotation will cause the chip to overheat and become damaged. If the SN74 gets hot, check orientation immediately and replace with a fresh chip.

**USB-C Breakout Boards**: Use identical breakout boards across all units. Different manufacturers may have different pin labeling. Reference IoT #1 wiring: Pin 1 (GND/B1) and Pin 6 (A8/B6).

**Service File Fix**: If WiFi hotspot doesn't appear on boot, check `/etc/systemd/system/beautifi-wifi.service` - it must NOT have `User=pi` line (needs to run as root to start hostapd). Fix with: `sudo sed -i '/User=pi/d' /etc/systemd/system/beautifi-wifi.service && sudo systemctl daemon-reload`

## Known Issues / TODO

- [ ] **WiFi Provisioning UI** (Low Priority): The setup interface at `192.168.4.1:5000` is functional but not polished. Network scanning doesn't work in AP mode (hardware limitation). Manual SSID entry works. Needs UI/UX improvements after IoT testing is complete.

## Related Projects

| Project | Purpose |
|---------|---------|
| [salon-safe-backend](https://github.com/ghapster/salon-safe-backend) | Node.js API backend |
| [salonsafe-vite](https://github.com/ghapster/salonsafe-vite) | Miner dashboard (Vite) |
| [salonsafe-admin-dashboard](https://github.com/ghapster/salonsafe-admin-dashboard) | Admin dashboard |

## Documentation

See `CLAUDE.md` for detailed architecture, wiring diagrams, and implementation notes.

*Last Updated: February 4, 2026*
