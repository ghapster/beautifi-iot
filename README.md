# BeautiFi IoT - Raspberry Pi Air Quality Monitor

IoT component for the BeautiFi/DUAN ecosystem. Controls ventilation fans, collects air quality telemetry, and generates cryptographically signed evidence packs for blockchain-based rewards (SLN tokens).

## Status: All 8 Phases Complete

| Phase | Feature | Status |
|-------|---------|--------|
| 0 | Fan Control MVP | ✅ Done |
| 1 | Sensor Integration | ✅ Done (Simulation) |
| 2 | Telemetry Collection | ✅ Done |
| 3 | Device Identity & Ed25519 Signing | ✅ Done |
| 4 | Epoch Formation with Merkle Trees | ✅ Done |
| 5 | Verifier Integration | ✅ Done |
| 6 | Device Registration & Site NFT | ✅ Done |
| 7 | Anti-Tamper & Anomaly Detection | ✅ Done |
| 8 | OTA Updates & Remote Config | ✅ Done |

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
- DROK 12V→5V Buck Converter

### GPIO Pins

| Fan | GPIO Pin |
|-----|----------|
| Fan 1 | 18 |
| Fan 2 | 13 |
| Fan 3 | 19 |

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

## Setup

```bash
# Install dependencies
pip install flask RPi.GPIO requests boto3 pynacl

# Run the server
python app.py

# Or via systemd
sudo systemctl start beautifi-iot
```

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

## Related Projects

| Project | Purpose |
|---------|---------|
| [salon-safe-backend](https://github.com/ghapster/salon-safe-backend) | Node.js API backend |
| [salonsafe-dashboard](https://github.com/ghapster/salonsafe-dashboard) | Miner dashboard |
| [salonsafe-admin-dashboard](https://github.com/ghapster/salonsafe-admin-dashboard) | Admin dashboard |

## Documentation

See `CLAUDE.md` for detailed architecture, wiring diagrams, and implementation notes.

*Last Updated: January 27, 2026*
