# BeautiFi IoT - DUAN Compliance Roadmap

This roadmap outlines the path from the current MVP fan controller to a fully DUAN-compliant Proof-of-Air (PoA) device.

---

## Current State (Phase 0) ✅

- Flask web server for remote control
- PWM fan control (3 fans, GPIO 18/13/19)
- Staggered startup to avoid power surge
- WiFi configuration
- Basic web UI

---

## Phase 1: Sensor Integration 🔧

**Goal:** Add hardware sensors to measure the metrics required for PoA calculation.

### Hardware to Add

| Sensor | Purpose | Recommended Part | I2C Addr |
|--------|---------|------------------|----------|
| Differential Pressure | ΔP for CFM estimation | SDP810-500Pa or MPXV7002DP | 0x25 |
| VOC/Air Quality | Detect pollutant levels | SGP30 or BME680 | 0x58/0x77 |
| Power Monitor | Track energy consumption (Watts) | INA219 or INA226 | 0x40 |
| Temperature/Humidity | Environmental baseline | BME280 or SHT31 | 0x76/0x44 |
| Fan Tachometer | RPM measurement | Hall effect on fan tach wire | GPIO |

### Software Tasks

- [ ] Create `sensors/` module with drivers for each sensor
- [ ] Implement I2C bus multiplexing if needed (TCA9548A)
- [ ] Add `/api/sensors` endpoint for real-time readings
- [ ] Create calibration table for CFM estimation (RPM × ΔP → CFM)
- [ ] Store calibration constants in config file

### Deliverables

- `sensors/pressure.py` - Differential pressure driver
- `sensors/voc.py` - VOC sensor driver
- `sensors/power.py` - Power monitoring driver
- `sensors/tachometer.py` - RPM counter
- `calibration.json` - CFM lookup table

---

## Phase 2: Telemetry Collection 📊

**Goal:** Implement continuous data sampling and local storage.

### Requirements (from DUAN spec)

- Sample every **12 seconds**
- Collect: CFM, RPM, ΔP, VOC, power draw, temperature, humidity
- Sign data at the edge
- Buffer locally for network resilience

### Software Tasks

- [ ] Create `telemetry/collector.py` - Background sampling thread
- [ ] Implement local SQLite buffer for telemetry data
- [ ] Add timestamps (UTC) to all readings
- [ ] Calculate derived metrics:
  - `TAR` = CFM × eligible_minutes
  - `EI` = CFM / Watts (efficiency)
- [ ] Create `/api/telemetry` endpoint for recent data

### Data Schema

```python
{
    "timestamp": "2026-01-19T12:00:00Z",
    "device_id": "btfi-iot-001",
    "readings": {
        "cfm": 150.5,
        "rpm": 1200,
        "delta_p": 25.3,
        "voc_ppb": 450,
        "co2_ppm": 800,
        "power_watts": 45.2,
        "temp_c": 24.5,
        "humidity_pct": 55.0
    },
    "derived": {
        "tar_cfm_min": 150.5,
        "efficiency_cfm_w": 3.33
    }
}
```

---

## Phase 3: Device Identity & Edge Signing 🔐

**Goal:** Cryptographic identity for tamper-proof telemetry.

### Requirements (from DUAN spec)

- Unique device keypair (Ed25519 recommended)
- All telemetry signed at the edge
- Firmware version tracking
- Hardware manifest (sensor configuration)

### Software Tasks

- [ ] Generate device keypair on first boot (`crypto/identity.py`)
- [ ] Store private key securely (consider TPM if available)
- [ ] Implement signing for all telemetry payloads
- [ ] Create hardware manifest file
- [ ] Add `/api/identity` endpoint (returns public key + device info)

### Identity Schema

```python
{
    "device_id": "btfi-iot-001",
    "public_key": "ed25519:abc123...",
    "firmware_version": "1.2.0",
    "hardware_manifest": {
        "pressure_sensor": "SDP810",
        "voc_sensor": "SGP30",
        "power_monitor": "INA219",
        "fan_count": 3
    },
    "commissioned_at": "2026-01-15T00:00:00Z"
}
```

---

## Phase 4: Epoch Formation 📦

**Goal:** Bundle telemetry into 1-hour epochs for verification.

### Requirements (from DUAN spec)

- Epochs typically 1 hour or fixed CFM-hour target
- Include all signed telemetry samples
- Compute epoch summary metrics
- Generate Merkle root over epoch data

### Software Tasks

- [ ] Create `epochs/builder.py` - Epoch formation logic
- [ ] Implement plausibility checks:
  - No negative airflow
  - VOC readings within physical bounds
  - Power draw matches expected range
  - No suspicious flatlines
- [ ] Calculate epoch summary:
  - Total TAR (CFM-minutes)
  - Average efficiency (CFM/W)
  - VOC reduction percentage
  - Total energy consumed (Wh)
- [ ] Generate Merkle root for epoch integrity
- [ ] Store completed epochs locally

### Epoch Schema

```python
{
    "epoch_id": "ep-2026011912-btfi001",
    "device_id": "btfi-iot-001",
    "site_nft_id": "0x123...",
    "start_time": "2026-01-19T12:00:00Z",
    "end_time": "2026-01-19T13:00:00Z",
    "summary": {
        "total_tar_cfm_min": 9030,
        "avg_cfm": 150.5,
        "avg_efficiency": 3.33,
        "total_energy_wh": 45.2,
        "voc_reduction_pct": 65.0,
        "eligible_minutes": 60,
        "sample_count": 300
    },
    "merkle_root": "0xabc...",
    "signature": "ed25519:xyz..."
}
```

---

## Phase 5: Verifier Integration 🌐

**Goal:** Stream telemetry and epochs to the DUAN verifier service.

### Requirements (from DUAN spec)

- Real-time telemetry streaming (every 12 seconds)
- Epoch submission for validation
- Handle network failures gracefully
- Receive verification confirmations

### Software Tasks

- [ ] Create `network/verifier_client.py` - API client for verifier
- [ ] Implement WebSocket or HTTP streaming for telemetry
- [ ] Add retry logic with exponential backoff
- [ ] Handle offline mode (buffer and sync when online)
- [ ] Process verification responses
- [ ] Create `/api/sync-status` endpoint

### API Integration

```
Verifier Endpoints (backend):
POST /api/telemetry/stream     - Real-time data
POST /api/epochs/submit        - Submit completed epoch
GET  /api/device/{id}/status   - Verification status
```

---

## Phase 6: Device Registration & Site NFT ✅

**Goal:** On-chain device commissioning and Site NFT binding.

### Requirements (from DUAN spec)

- Device registered on-chain
- Bound to Site NFT (BEP-721)
- Baseline readings recorded during commissioning
- Configuration manifest stored

### Software Tasks

- [x] Create `registration/` module
- [x] Implement commissioning flow:
  1. Generate device identity
  2. Run baseline calibration (30-min)
  3. Submit registration to backend
  4. Receive Site NFT binding confirmation
- [x] Store Site NFT ID locally
- [x] Add `/api/registration` endpoint
- [ ] Create commissioning UI page

### Implementation

- `registration/manifest.py` - Hardware manifest generation
- `registration/backend_client.py` - SalonSafe backend API client
- `registration/commissioning.py` - Commissioning state machine
- 8 API endpoints: `/api/registration/*`
- SQLite persistence for commissioning state

---

## Phase 7: Anti-Tamper & Anomaly Detection ✅

**Goal:** Local detection of suspicious behavior.

### Requirements (from DUAN spec)

- Detect drift from baseline
- Flag impossible readings
- Detect replay attacks
- Monitor for flatline patterns

### Software Tasks

- [x] Create `security/anomaly.py` - Local anomaly detection
- [x] Implement checks:
  - Reading within ±3σ of baseline
  - No sudden mode switches
  - Timestamp monotonicity
  - Cross-sensor consistency (CFM vs power vs RPM)
- [x] Flag suspicious epochs before submission
- [x] Log all anomalies locally

### Implementation

- `security/anomaly.py` - AnomalyDetector with statistical outlier detection
- Physical limits validation, flatline detection, replay attack detection
- Cross-sensor consistency checks (CFM/RPM/power correlation)
- 3 API endpoints: `/api/security/*`

---

## Phase 8: OTA Updates & Remote Management 📡

**Goal:** Secure firmware updates and remote configuration.

### Software Tasks

- [ ] Implement signed firmware updates
- [ ] Create update verification (check signature before applying)
- [ ] Add remote configuration endpoint
- [ ] Implement rollback capability
- [ ] Add `/api/system/update` endpoint

---

## Implementation Timeline

| Phase | Description | Status | Dependencies |
|-------|-------------|--------|--------------|
| 0 | Fan Control MVP | ✅ Complete | None |
| 1 | Sensor Integration | ✅ Complete (Simulation) | Hardware procurement |
| 2 | Telemetry Collection | ✅ Complete | Phase 1 |
| 3 | Device Identity | ✅ Complete | None |
| 4 | Epoch Formation | ✅ Complete | Phases 2, 3 |
| 5 | Verifier Integration | ✅ Complete | Phase 4, Backend ready |
| 6 | Registration & Site NFT | ✅ Complete | Phase 3, Smart contracts |
| 7 | Anti-Tamper | ✅ Complete | Phase 2 |
| 8 | OTA Updates | 🟡 Pending | Phase 3 |

---

## Hardware BOM (Estimated)

| Component | Qty | Est. Cost |
|-----------|-----|-----------|
| Raspberry Pi 4 (2GB+) | 1 | $45 |
| SDP810-500Pa (pressure) | 1 | $25 |
| SGP30 (VOC) | 1 | $15 |
| INA219 (power) | 1 | $8 |
| BME280 (temp/humidity) | 1 | $10 |
| Hall effect sensor (tach) | 3 | $6 |
| Enclosure + wiring | 1 | $20 |
| **Total** | | **~$130** |

---

## File Structure (Target)

```
beautifi-iot/
├── app.py                 # Main Flask server
├── config.py              # Configuration management
├── calibration.json       # CFM lookup table
├── sensors/
│   ├── __init__.py
│   ├── pressure.py        # Differential pressure
│   ├── voc.py             # VOC/air quality
│   ├── power.py           # Power monitoring
│   └── tachometer.py      # RPM measurement
├── telemetry/
│   ├── __init__.py
│   ├── collector.py       # Background sampling
│   └── buffer.py          # SQLite storage
├── crypto/
│   ├── __init__.py
│   ├── identity.py        # Device keypair
│   └── signing.py         # Payload signing
├── epochs/
│   ├── __init__.py
│   ├── builder.py         # Epoch formation
│   └── merkle.py          # Merkle tree
├── network/
│   ├── __init__.py
│   └── verifier_client.py # Verifier API
├── security/
│   ├── __init__.py
│   └── anomaly.py         # Tamper detection
├── registration/
│   ├── __init__.py
│   └── commissioning.py   # Device registration
├── templates/
│   ├── index.html
│   ├── fan.html
│   ├── dashboard.html     # Full telemetry dashboard
│   └── setup.html         # Commissioning UI
└── tests/
    └── ...
```

---

## Success Criteria

The IoT device is DUAN-compliant when it can:

1. ✅ Measure CFM, VOC, power, and environmental data
2. ✅ Sample telemetry every 12 seconds
3. ✅ Sign all data with device keypair
4. ✅ Form hourly epochs with Merkle roots
5. ✅ Stream to verifier and receive confirmations
6. ✅ Be registered and bound to a Site NFT
7. ✅ Detect and flag anomalous behavior
8. ✅ Accept secure OTA updates

---

## Next Steps

1. **Hardware:** Order sensors (Phase 1 BOM)
2. **Backend:** Ensure verifier endpoints are ready
3. **Smart Contracts:** Site NFT and device registry deployed
4. **Start coding:** Begin with Phase 1 sensor drivers

---

*This roadmap aligns with BeautiFi™ Tokenomics Technical White Paper v1*
