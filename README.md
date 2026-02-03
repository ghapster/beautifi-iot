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

## Remote Fan Control

The device polls the backend every 10 seconds for commands:

| Command | Value | Action |
|---------|-------|--------|
| `fan` | `on` | Set all fans to 100% |
| `fan` | `off` | Set all fans to 0% |
| `set_speed` | `0-100` | Set specific percentage |

## Prototype Devices (Feb 2026)

| Device | Hostname | Device ID | Notes |
|--------|----------|-----------|-------|
| Prototype 1 | beautifi-4 | btfi-49311ccf334d9d45 | WiFi provisioning tested |
| Prototype 2 | beautifi-3 | btfi-5e93d18822a826b3 | Setup complete |
| Prototype 3 | beautifi-2 | btfi-9c5263e883ee1b97 | Setup complete |

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

*Last Updated: February 3, 2026*
