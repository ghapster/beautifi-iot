# BeautiFi Pi HAT v1 — Single Fan Design

## Overview
Custom Raspberry Pi HAT that consolidates all breadboard components into a single PCB.
Replaces: breadboard, jumper wires, DROK converter, SN74 DIP, PWM-to-0-10V module.

**Board size:** 65 x 56 mm (standard Pi HAT)
**Input:** 12V DC (barrel jack)
**Output:** 0-10V analog to fan VSP, tach feedback from fan
**Sensors:** BME680 (on-board, I2C)

---

## Circuit Schematic (ASCII)

```
                         12V DC INPUT
                             │
                    ┌────────┴────────┐
                    │   J1 Barrel     │
                    │   Jack 5.5x2.1  │
                    └────────┬────────┘
                             │
                    ┌────────┴────────┐
              ┌─────┤ VIN         VOUT├─────┐
              │     │  MP1584 Module  │     │
              │     │  12V → 5V/3A   │     │
              │     ├─────┬──────────┤     │
              │     │     │ GND      │     │
              │     └─────┼──────────┘     │
              │           │                │
   12V Rail ──┤           │          5V ───┼──► Pi Pin 2 & Pin 4 (5V)
              │       GND Rail ────────────┼──► Pi Pin 6, 9, 14, etc.
              │           │                │
              │           │                │
              │           │         3.3V ◄─┼─── Pi Pin 1 (3.3V out)
              │           │                │
              │           │                │
    ══════════╪═══════════╪════════════════╪══════════════════════════
    PWM-TO-0-10V SECTION  │                │
    ══════════╪═══════════╪════════════════╪══════════════════════════
              │           │                │
              │     Pi Pin 12 (GPIO18)     │
              │           │                │
              │     ┌─────┴─────┐          │
              │     │ U1: SN74  │          │
              │     │ AHCT125   │          │
              │     │           │          │
              │     │ 1A ── 1Y  │──── PWM out (5V, 100Hz)
              │     │           │     │
              │  5V─┤ VCC   GND ├─GND │
              │     │           │     │
              │     │ 1OE──GND  │     │  (OE tied low = always enabled)
              │     └───────────┘     │
              │                       │
              │                 ┌─────┴─────┐
              │                 │  R1 10kΩ   │  RC Low-Pass Filter
              │                 └─────┬─────┘  (smooths PWM → DC)
              │                       │
              │                       ├──────── C1 2.2µF to GND
              │                       │         (f_c ≈ 7.2 Hz)
              │                       │
              │                 ┌─────┴─────┐
              │            ┌────┤ +  U2a     │
              │            │    │  LM358     ├──────┐
              │            │ ┌──┤ -          │      │
              │            │ │  └────────────┘      │
              │            │ │                      │
              │            │ ├──── R3 10kΩ ─────────┤  Non-inverting amp
              │            │ │                      │  Gain = 1 + R2/R3
              │            │ └──── R2 10kΩ ── GND   │  Gain = 2
              │            │                        │  0-5V in → 0-10V out
              │            │                        │
         12V──┼────────────┼─ U2 V+ (pin 8)        │
              │            │                        │
              │         GND┼─ U2 V- (pin 4)        │
              │            │                        │
              │            │              VSP OUT ◄─┘ (0-10V analog)
              │            │                │
              │            │          ┌─────┴─────┐
              │            │          │ J2 Fan    │
              │            │          │ Screw     │
              │            │          │ Terminal  │
              │            │          │           │
              │            │          │ 1: VSP ◄──┘  (Yellow wire)
              │            │      GND─┤ 2: GND       (Black wire)
              │            │          │ 3: TACH ──┐   (White wire)
              │            │          │ 4: NC     │   (Red wire — NOT CONNECTED)
              │            │          └───────────┘
              │            │                │
    ══════════╪════════════╪════════════════╪══════════════════════════
    TACH INPUT SECTION     │                │
    ══════════╪════════════╪════════════════╪══════════════════════════
              │            │                │
              │            │          ┌─────┘
              │            │          │
              │            │    R4 10kΩ (pull-up to 3.3V)
              │            │          │
              │         3.3V──────────┤
              │            │          │
              │            │          └───────► Pi Pin 7 (GPIO4) — Tach In
              │            │
    ══════════╪════════════╪══════════════════════════════════════════
    BME680 SENSOR SECTION  │
    ══════════╪════════════╪══════════════════════════════════════════
              │            │
              │         3.3V──────────┬──────── U3 BME680 VCC
              │            │          │
              │         GND───────────┼──────── U3 BME680 GND
              │            │          │
              │   Pi Pin 3 (SDA) ─────┼──R5──── U3 BME680 SDA
              │            │          │  4.7kΩ
              │   Pi Pin 5 (SCL) ─────┼──R6──── U3 BME680 SCL
              │            │          │  4.7kΩ
              │            │       3.3V┘ (pull-ups for I2C)
              │            │
    ══════════╪════════════╪══════════════════════════════════════════
    STATUS LEDs             │
    ══════════╪════════════╪══════════════════════════════════════════
              │            │
           12V─── R7 1kΩ ──┤── LED1 (Green, Power) ── GND
              │            │
           5V ─── R8 330Ω ─┤── LED2 (Blue, Pi Power) ── GND
              │            │
              │            │
```

---

## GPIO Pin Assignments

| Pi Pin | GPIO | Function | Direction | Notes |
|--------|------|----------|-----------|-------|
| Pin 1  | 3.3V | BME680 VCC, I2C pull-ups, tach pull-up | Power | — |
| Pin 2  | 5V   | Pi power from DC-DC | Power In | HAT feeds Pi |
| Pin 3  | GPIO2 (SDA) | BME680 I2C data | Bidirectional | 4.7kΩ pull-up |
| Pin 4  | 5V   | Pi power from DC-DC | Power In | Parallel with Pin 2 |
| Pin 5  | GPIO3 (SCL) | BME680 I2C clock | Output | 4.7kΩ pull-up |
| Pin 6  | GND  | Common ground | — | — |
| Pin 7  | GPIO4 | **Tach input** | Input | 10kΩ pull-up to 3.3V |
| Pin 9  | GND  | SN74 OE (tied low) | — | Enables buffer |
| Pin 12 | GPIO18 | **Fan PWM output** | Output | To SN74 channel 1 |
| Pin 14 | GND  | Common ground | — | — |

All other GPIO pins pass through unused (available for future expansion).

---

## Bill of Materials (BOM)

| Ref | Component | Value/Part | Package | Qty | ~Cost | Notes |
|-----|-----------|-----------|---------|-----|-------|-------|
| J1 | DC barrel jack | 5.5x2.1mm | Through-hole | 1 | $0.50 | 12V input |
| J2 | Screw terminal | 4-pos, 3.5mm pitch | Through-hole | 1 | $0.60 | Fan connection (VSP/GND/TACH/NC) |
| J3 | 2x20 GPIO header | Female stacking | Through-hole | 1 | $1.50 | Pi connection (passes through) |
| U1 | SN74AHCT125 | Quad buffer | SOIC-14 (SMD) | 1 | $0.40 | 1 of 4 channels used |
| U2 | LM358 | Dual op-amp | SOIC-8 (SMD) | 1 | $0.30 | 1 of 2 channels used |
| U3 | BME680 | Env sensor | Breakout module | 1 | $8.00 | 4-pin header mount |
| U4 | MP1584EN module | 12V→5V 3A DC-DC | Module (17x22mm) | 1 | $1.50 | Pre-built, solder to pads |
| R1 | Resistor | 10kΩ | 0805 (SMD) | 1 | $0.01 | RC filter |
| R2 | Resistor | 10kΩ | 0805 (SMD) | 1 | $0.01 | Op-amp feedback (gain) |
| R3 | Resistor | 10kΩ | 0805 (SMD) | 1 | $0.01 | Op-amp feedback (gain) |
| R4 | Resistor | 10kΩ | 0805 (SMD) | 1 | $0.01 | Tach pull-up |
| R5 | Resistor | 4.7kΩ | 0805 (SMD) | 1 | $0.01 | I2C SDA pull-up |
| R6 | Resistor | 4.7kΩ | 0805 (SMD) | 1 | $0.01 | I2C SCL pull-up |
| R7 | Resistor | 1kΩ | 0805 (SMD) | 1 | $0.01 | Power LED current limit |
| R8 | Resistor | 330Ω | 0805 (SMD) | 1 | $0.01 | Pi power LED current limit |
| C1 | Capacitor | 2.2µF | 0805 (SMD) | 1 | $0.05 | RC filter (ceramic) |
| C2 | Capacitor | 100nF | 0805 (SMD) | 1 | $0.02 | SN74 decoupling |
| C3 | Capacitor | 100nF | 0805 (SMD) | 1 | $0.02 | LM358 decoupling |
| C4 | Capacitor | 10µF | 0805 (SMD) | 1 | $0.05 | 12V rail bulk cap |
| LED1 | LED | Green 3mm | Through-hole | 1 | $0.05 | 12V power indicator |
| LED2 | LED | Blue 3mm | Through-hole | 1 | $0.05 | 5V/Pi power indicator |
| — | PCB | 65x56mm 2-layer | — | 1 | $1.00 | JLCPCB min order 5 |
| — | Standoffs | M2.5 x 11mm | — | 4 | $0.50 | HAT mounting |

**Total BOM cost: ~$15 per board** (less at quantity)

---

## Net List

```
Net: 12V
  J1.+ → U4.VIN → R7.1 → C4.+ → U2.V+(pin8)

Net: 5V
  U4.VOUT → J3.Pin2 → J3.Pin4 → U1.VCC(pin14) → R8.1 → C2.1

Net: 3.3V (from Pi)
  J3.Pin1 → U3.VCC → R4.1 → R5.1 → R6.1

Net: GND
  J1.- → U4.GND → J3.Pin6 → J3.Pin9 → J3.Pin14 → U1.GND(pin7)
  → U1.1OE(pin1) → U2.V-(pin4) → J2.2 → U3.GND → C1.2 → C2.2
  → C3.2 → C4.2 → R2.2 → LED1.K → LED2.K

Net: PWM_GPIO
  J3.Pin12 (GPIO18) → U1.1A(pin2)

Net: PWM_BUFFERED
  U1.1Y(pin3) → R1.1

Net: PWM_FILTERED
  R1.2 → C1.1 → U2.IN+(pin3)

Net: FAN_VSP
  U2.OUT(pin1) → R3.1 → J2.1

Net: OP_FB
  U2.OUT(pin1) → R3.1 → R2.1 → U2.IN-(pin2)

Net: TACH
  J2.3 → R4.2 → J3.Pin7 (GPIO4)

Net: I2C_SDA
  J3.Pin3 (GPIO2) → R5.2 → U3.SDA

Net: I2C_SCL
  J3.Pin5 (GPIO3) → R6.2 → U3.SCL
```

---

## Design Notes

### PWM-to-0-10V Conversion
The AC Infinity S6 expects 0-10V analog on the VSP (yellow) wire.
- SN74 buffers GPIO18's 3.3V PWM to 5V PWM (100Hz)
- RC filter (R1=10kΩ, C1=2.2µF) smooths to 0-5V DC (cutoff ~7.2Hz, well below 100Hz PWM)
- LM358 non-inverting amp with gain=2 (R2=R3=10kΩ) scales to 0-10V
- LM358 powered from 12V rail, can swing output to ~10.5V (sufficient for 0-10V)

### Tach Input
- AC Infinity tach wire (white) is likely open-collector
- R4 pulls up to 3.3V when tach output releases
- Tach pulls to GND when active (creating pulses)
- GPIO4 reads pulses; count pulses per second × 30 = RPM (for 2-pole motor)
- **VERIFY WITH MULTIMETER BEFORE FIRST USE**: Measure white-to-black with fan running. Should see 0V or low fluctuating voltage. If >3.3V, the tach is active push-pull and needs a voltage divider instead of pull-up.

### BME680 Mounting
- Use a 4-pin female header so the BME680 breakout board can be plugged in/removed
- Position away from the DC-DC converter (heat source) for accurate temperature readings
- Edge of board recommended, with airflow exposure
- I2C address: 0x77 (BME680 default secondary address)

### Power
- MP1584EN module handles 12V→5V conversion efficiently
- Powers Pi through GPIO 5V pins (Pin 2 & 4)
- **IMPORTANT**: When HAT provides 5V through GPIO, do NOT also power Pi via USB — backfeeding risk
- 12V rail also feeds the LM358 op-amp directly (needs >10V to output 10V)

### Unused SN74 Channels
- Channels 2, 3, 4 (pins 4-6, 8-10, 11-13) are unused
- Tie unused inputs (pins 5, 9, 12) to GND
- Tie unused OE pins (pins 4, 10, 11) to VCC (disabled, high-Z output)

### Red Wire Protection
- J2 pin 4 is labeled NC (No Connect) — no trace routed
- Physical barrier: the red wire from the fan USB-C can be inserted but has no electrical path
- Consider omitting pin 4 entirely (use 3-pos terminal) to prevent any accidental connection

### Future Expansion
- 3 unused SN74 channels available for additional PWM outputs
- Unused op-amp channel (U2b) available for a second fan or signal conditioning
- GPIO4 could be reassigned; plenty of free GPIO pins on the stacking header
- Second I2C device can share the bus (different address)
- Board edge could accommodate a second screw terminal for a second fan

---

## PCB Layout Guidelines

```
┌──────────────────────────────────────────────┐
│  ┌──────┐                          ┌──────┐  │
│  │Standoff                         │Standoff  │
│  └──────┘    ┌─────────────┐       └──────┘  │
│              │  MP1584EN   │                  │
│    [LED1]    │  DC-DC Mod  │   [LED2]        │
│              └─────────────┘                  │
│  ┌──────────────────────────┐                │
│  │     J1 Barrel Jack       │                │
│  └──────────────────────────┘                │
│                                              │
│   ┌────┐   R1  C1   ┌────┐                  │
│   │ U1 │─────────────│ U2 │── [J2 Fan Term] │
│   │SN74│  R2  R3     │LM58│                  │
│   └────┘             └────┘                  │
│                                              │
│   C2  C3  C4   R4  R5  R6                   │
│                                              │
│          ┌──────────────┐  ← BME680 header   │
│          │  U3 BME680   │    (board edge for  │
│          └──────────────┘     airflow)        │
│  ┌──────┐                          ┌──────┐  │
│  │Standoff                         │Standoff  │
│  └──────┘                          └──────┘  │
│  ╔══════════════════════════════════════════╗ │
│  ║  J3: 2x20 Female Stacking GPIO Header   ║ │
│  ╚══════════════════════════════════════════╝ │
└──────────────────────────────────────────────┘
        ▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼
        Raspberry Pi 3B below
```

- Keep DC-DC module away from BME680 (thermal isolation)
- Ground plane on bottom layer for noise reduction
- Keep analog section (op-amp, RC filter) away from PWM digital signals
- Fan screw terminal on board edge for easy cable access

---

## KiCad Project Setup

To create the KiCad project:
1. Create new project: `beautifi-hat-v1`
2. Import symbols: SN74AHCT125, LM358, BME680 (from KiCad standard library)
3. MP1584EN: Use a generic module footprint (17x22mm, 4 pads: VIN, VOUT, GND, EN)
4. Assign footprints: SOIC-14 (U1), SOIC-8 (U2), 0805 (all R/C), TH barrel jack, TH screw terminal
5. PCB outline: 65x56mm with 4x M2.5 mounting holes at Pi HAT standard positions
   - Hole positions (from board origin): (3.5, 3.5), (61.5, 3.5), (3.5, 52.5), (61.5, 52.5)

---

## Ordering

**PCB fabrication (JLCPCB):**
- 2-layer, 1.6mm, green solder mask
- Min order: 5 boards, ~$5 total + shipping
- Upload Gerber files from KiCad

**SMD assembly (optional, JLCPCB SMT):**
- SN74AHCT125, LM358, all 0805 R/C components
- ~$15-20 setup + $2/board for assembly
- You hand-solder: barrel jack, screw terminal, GPIO header, LEDs, MP1584 module, BME680
