# BeautiFi IoT - Raspberry Pi Fan Controller

IoT component for the BeautiFi/DUAN ecosystem. Controls ventilation fans via PWM on Raspberry Pi.

## Current Features

- Flask web server (port 5000)
- PWM control for 3 fans (GPIO 18, 13, 19)
- Staggered fan startup to avoid power surge
- WiFi configuration endpoint
- Web UI for manual control

## Hardware

- Raspberry Pi (tested on Pi 4)
- PWM-controllable fans (AC Infinity or similar)
- Optional: PCA9685 I2C PWM controller

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Index page |
| `/dashboard` | GET | Fan control UI |
| `/api/fan` | POST | Set fan speed `{"speed": 0-100}` |
| `/api/iot/connect-wifi` | POST | Configure WiFi |

## Setup

```bash
# Install dependencies
pip install flask RPi.GPIO

# Run the server
python app.py
```

## GPIO Pin Mapping

| Fan | GPIO Pin |
|-----|----------|
| Fan 1 | 18 |
| Fan 2 | 13 |
| Fan 3 | 19 |

## Roadmap (DUAN Compliance)

- [ ] Add CFM airflow sensor
- [ ] Add VOC sensor (SGP30/BME680)
- [ ] Add power monitoring (INA219)
- [ ] Implement 12-second telemetry sampling
- [ ] Add edge-signing with device keypair
- [ ] Implement epoch bundling (1-hour)
- [ ] Stream telemetry to verifier service

## License

MIT
