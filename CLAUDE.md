# BeautiFi IoT - Project Context for Claude

> This file helps Claude understand the project quickly in new sessions.

## Essential Documentation (READ FIRST)

Before starting a new session, reference these key documentation files for full system context:

| Document | Location | Purpose |
|----------|----------|---------|
| **System Summary** | `C:\Users\CO-OP\salon-safe-backend\docs\BEAUTIFI_SYSTEM_SUMMARY.md` | Complete system overview, all components, blockchain integration, database schema, API endpoints, recent commits |
| **Evidence Pack v1 Spec** | `C:\Users\CO-OP\salon-safe-backend\docs\EVIDENCE_PACK_V1_SPEC.md` | Cryptographic evidence pack format specification |
| **Tokenomics Whitepaper** | `C:\Users\CO-OP\Downloads\salonsafe-iot\BeautiFi™ Tokenomics Technical White Paper (v1).pdf` | Token economics and DUAN protocol details (GOVERNING DOCUMENT) |
| **Tokenomics Simulator** | `C:\Users\CO-OP\Downloads\salonsafe-iot\BTFI v1 Tokenomics Simulator.xlsx` | Excel model showing how metrics are tabulated and calculated |
| **Executive Summary** | `C:\Users\CO-OP\Documents\Beauti Fi™ Executive Summary & Key Sections (neat Format).docx` | Business overview |

## ⚠️ CRITICAL: Whitepaper vs Implementation

**The Tokenomics Whitepaper is the governing document for this project, with ONE MAJOR EXCEPTION:**

| Whitepaper Mentions | Actual Implementation | Notes |
|---------------------|----------------------|-------|
| **BNB Greenfield** (evidence storage) | **Cloudflare R2** (S3-compatible) | Greenfield is NOT implemented |
| opBNB (smart contracts) | BSC Testnet | Migration to opBNB not done |

**DO NOT attempt to implement BNB Greenfield.** The project uses Cloudflare R2 for all evidence storage. This is intentional and will not change. Evidence packs are uploaded to R2 with the storage key format: `epochs/{device_id}/{year}/{month}/{day}/{epoch_id}.zip`

When reading the whitepaper, follow all specifications EXCEPT storage infrastructure references.

## Raspberry Pi Access

**IMPORTANT:** SSH access to the Pi uses `pi@` username, NOT `btfi@`:
```bash
ssh pi@192.168.0.151
```

The Pi runs at IP `192.168.0.151` on the local network. The IoT code is located at `/home/pi/salonsafe-iot` on the Pi.

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
├── tokenomics/
│   └── issuance.py        # $BTFI token issuance calculator (whitepaper formula)
├── evidence/
│   └── pack_builder.py    # Evidence pack builder + Cloudflare R2 upload
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

## Architecture Clarification (Important!)

**⚠️ REMINDER: BNB Greenfield is NOT implemented. See "CRITICAL: Whitepaper vs Implementation" section above.**

The whitepaper is the governing document, but evidence storage uses Cloudflare R2 instead of BNB Greenfield:

| Whitepaper Mentions | Actual Implementation |
|---------------------|----------------------|
| BNB Greenfield (evidence storage) | **Cloudflare R2** (S3-compatible) - PERMANENT |
| opBNB (smart contracts) | BSC Testnet (migration to opBNB not done) |
| On-chain epoch submission | Backend-managed via SalonSafe API |

### Evidence Storage (Cloudflare R2)
- Evidence packs are ZIP archives uploaded to R2
- Storage key format: `epochs/{device_id}/{year}/{month}/{day}/{epoch_id}.zip`
- Each pack contains: `epoch.json`, `samples.json`, `device_identity.json`, `leaf_hashes.json`, `metadata.json`
- SHA256 hash computed for integrity verification
- Config in `.env`: `R2_ENDPOINT_URL`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET_NAME`

### Tokenomics Module (`tokenomics/issuance.py`)
Implements the whitepaper formula:
```
Tokens = (Base_rate × TAR × EI × Quality_Factor) / BCAI
```
- TAR = Toxic Air Removed (CFM-minutes)
- EI = Energy Input factor (efficiency, clamped 0.8-1.2)
- Quality_Factor = valid_events / total_events
- BCAI = BeautiFi Clean Air Index (price adjustment)

Issuance splits: 75% facilities, 5% verifiers, 10% treasury, 10% team (capped at 75M)

### Evidence Pack Builder (`evidence/pack_builder.py`)
- Builds ZIP archives per epoch with all telemetry and signing data
- Uploads to Cloudflare R2 with metadata
- Supports download and verification

### What's NOT Implemented Yet
1. **Real sensors** - Device runs in `SIMULATION_MODE = True`
2. **PoC retirement system** - Burn $BTFI → mint soulbound NFT flow
3. **BCAI dynamic calculation** - Currently uses static `bcai_scalar = 1.0`
4. **Sponsor dashboard** - vESG reporting interface

### Token Minting - FULLY IMPLEMENTED

**IoT Device** (`tokenomics/issuance.py`):
- Calculates tokens per epoch using whitepaper formula
- Integrated with `telemetry/collector.py`
- No web3 dependency - calculates and reports

**Backend** (`salon-safe-backend/utils/blockchain.js`):
- `rewardTokens()` - Tries mint first, falls back to transfer
- `mintTokens()` - Creates new tokens (if rewards wallet is contract owner)
- `transferTokens()` - Sends from rewards wallet (fallback)
- Uses ethers.js to interact with deployed SLN token contract

**Auto-Minting Flow** (`routes/telemetry.js`):
```
IoT Device                              Backend
───────────────────────────────────────────────────────────────────
POST /api/epochs/submit        →  Store epoch in database
                               →  autoVerifyEpoch() called async
                               →  Calculate: slnAmount = tarAmount × slnPerTar
                               →  blockchain.rewardTokens(wallet, sln, epochId)
                               →  Record tx in tar_rewards_ledger
                               →  WebSocket emit epoch:verified
```

**Backend Minting Endpoints**:
| Endpoint | Purpose |
|----------|---------|
| `POST /api/epochs/submit` | Auto-verifies & mints on submission |
| `POST /api/epochs/verify-onchain/:epochId` | Manual single epoch verification |
| `POST /api/epochs/verify-all-onchain/:deviceId` | Batch verify all epochs |
| `GET /api/blockchain/status` | Check blockchain connection |

**Contract ABI** (`contract/abi.json`):
- `mint(address to, uint256 amount)` - Owner-only minting
- `burn(uint256 amount)` - Token burning
- Standard ERC20 functions

**Backend Location**: `C:\Users\CO-OP\salon-safe-backend\`

## Remote Fan Control (Jan 27, 2026)

The IoT device now supports remote fan control from the Miner Dashboard via a command polling system.

### CommandPoller Class (`app.py`)
- Polls backend every 10 seconds for pending commands
- Handles command types: `fan` (on/off), `set_speed` (0-100%)
- Acknowledges commands after execution
- Runs in background thread

### Command Flow
```
Dashboard                    Backend                         IoT Device
─────────────────────────────────────────────────────────────────────────
Toggle On/Off     →   POST /api/devices/:id/command   →   CommandPoller polls
                      (queued in device_commands)          every 10 seconds
                                                      →   GET /commands/pending
                                                      →   Execute: set fan speed
                                                      →   POST /commands/:id/ack
```

### Supported Commands
| Command | Value | Action |
|---------|-------|--------|
| `fan` | `on` | Set all fans to 100% |
| `fan` | `off` | Set all fans to 0% |
| `set_speed` | `0-100` | Set all fans to specific percentage |

### Dashboard Fan Controls
- **On/Off Toggle**: Visible in device row, turns fans to 100% when on
- **Speed Buttons**: 50% and 100% presets in expanded device panel
- **Real-time Telemetry**: Polls every 30s when device expanded

## Recent Session Notes (Jan 2026)

- Completed all 8 DUAN compliance phases
- Added WiFi provisioning with AP mode fallback
- Pi IP on local network: `192.168.0.151` (SSH: `pi@192.168.0.151`)
- Repo: https://github.com/ghapster/beautifi-iot
- User: ghapster
- **Admin Dashboard UI** upgraded with BeautiFi branding (slate #546A7B + cream #E8E4D9)
- Testing on **BSC Testnet with SLN token** (not BTFI yet, not mainnet)
- Evidence storage uses **Cloudflare R2** (not BNB Greenfield)
- **Remote Fan Control** - Dashboard can toggle fans on/off and set speed (50%/100%)
- **Miner Dashboard** - Real-time telemetry display, TAR-based rewards, community stats

### Miner Dashboard Cleanup (Jan 27, 2026)
- Removed dead code: `calculateOperatingMinutes` function, unused imports
- Removed commented-out Pledge/Vesting/Ad code blocks
- Removed PledgeModal, ClaimPledgeModal imports and pledge-related state
- Updated footer branding from "SalonSafe, LLC" to "BeautiFi"
- Deleted legacy `walletConfig-v1.js` file

### Related Repositories
| Repo | Local Path | Purpose |
|------|------------|---------|
| beautifi-iot | `C:\Users\CO-OP\Downloads\salonsafe-iot\salonsafe-iot` | Raspberry Pi IoT device code |
| salon-safe-backend | `C:\Users\CO-OP\salon-safe-backend` | Node.js backend API |
| salonsafe-admin-dashboard | `C:\Users\CO-OP\salonsafe-admin-dashboard` | React admin dashboard |
| salonsafe-vite | `C:\Users\CO-OP\salonsafe-vite` | React miner dashboard (Vite) |

For complete system documentation including database schema, API endpoints, blockchain integration, and recent commits, see the **System Summary** referenced above.
