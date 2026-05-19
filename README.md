# forza-wheel-leds

Lights up the RPM LEDs on your **Logitech G920 / G29 / G923** steering wheel using live telemetry from **Forza Horizon 5**, **Forza Horizon 6**, and **Forza Motorsport (2023)**.

Forza does not natively drive the wheel LEDs — this tool bridges the gap.

![CI](https://github.com/guivdh/forza-wheel-leds/actions/workflows/build.yml/badge.svg)
![Coverage](https://img.shields.io/badge/coverage-100%25-brightgreen)
![Windows](https://img.shields.io/badge/Windows-10%2F11-blue)
![Python](https://img.shields.io/badge/Python-3.8%2B-blue)
![License](https://img.shields.io/badge/License-MIT-green)

---

## How it works

```
Forza (UDP Data Out)  →  forza-wheel-leds  →  Logitech SDK  →  G920 RPM LEDs
```

Forza broadcasts real-time telemetry over UDP (~60 packets/s).  
This tool reads `CurrentEngineRpm` and `EngineMaxRpm` from each packet and calls the official Logitech Steering Wheel SDK to light the 5 LEDs accordingly.

---

## Requirements

| Requirement | Notes |
|---|---|
| Windows 10 / 11 | Linux/macOS not supported (Logitech SDK is Windows-only) |
| Logitech G HUB | Must be installed **and running** in the background |
| `LogitechSteeringWheelEnginesWrapper.dll` | From the [Logitech Steering Wheel SDK](#logitech-sdk) — place it next to the script / .exe |
| Python 3.8+ | Only needed if running the `.py` script — not needed for the `.exe` release |

---

## Quick Start

### Option A — Pre-built .exe (no Python needed)

1. Download the latest `forza_wheel_leds.exe` from [Releases](../../releases/latest).
2. Place `LogitechSteeringWheelEnginesWrapper.dll` **in the same folder** as the `.exe` (see [Logitech SDK](#logitech-sdk) below).
3. Configure Forza (see [In-game setup](#in-game-setup)).
4. Double-click `forza_wheel_leds.exe`, then launch a race.

### Option B — Python script

```bash
# No dependencies to install — uses Python stdlib only
python forza_wheel_leds.py
```

Place `LogitechSteeringWheelEnginesWrapper.dll` in the same folder as the script.

---

## In-game Setup

> This must be done **once** per Forza title.

| Game | Settings path |
|---|---|
| Forza Horizon 5 | Settings → **HUD and Gameplay** → scroll to bottom |
| Forza Horizon 6 | Settings → **HUD and Gameplay** → scroll to bottom |
| Forza Motorsport 2023 | Settings → **Gameplay & HUD** → scroll to bottom |

Set the following values:

```
Data Out             : ON
Data Out IP Address  : 127.0.0.1
Data Out IP Port     : 5607
```

---

## Logitech SDK

The Logitech Steering Wheel SDK is **not bundled** in this repo (Logitech licence).  
Download it directly from Logitech:

**[LogitechSteeringWheelSDK_8.75.30.zip](https://www.logitechg.com/sdk/LogitechSteeringWheelSDK_8.75.30.zip)**

Inside the archive, copy the correct DLL for your Python/system architecture:

| Architecture | DLL file |
|---|---|
| 64-bit (most users) | `LogitechSteeringWheelEnginesWrapper.dll` |
| 32-bit | `LogitechSteeringWheelEnginesWrapper_x86.dll` → rename to `LogitechSteeringWheelEnginesWrapper.dll` |

---

## Configuration

Open `forza_wheel_leds.py` and edit the constants at the top:

```python
UDP_PORT          = 5607   # Must match the port set in Forza
LED_MIN_RPM_RATIO = 0.70   # First LED lights at 70 % of redline
WHEEL_INDEX       = 0      # 0 = first connected Logitech wheel
```

| Setting | Description |
|---|---|
| `UDP_PORT` | UDP port — must match the value set in Forza's Data Out settings |
| `LED_MIN_RPM_RATIO` | `0.70` = shift-indicator feel (LEDs start late). `0.50` = wider spread |
| `WHEEL_INDEX` | Index of your wheel (0 for single wheel setups) |

---

## Supported games & wheels

**Games**
- Forza Horizon 5
- Forza Horizon 6
- Forza Motorsport (2023)

**Wheels** (any Logitech wheel supported by the Steering Wheel SDK)

| Wheel | LEDs | Layout |
|---|---|---|
| Logitech G29 | 11 | Arc: 🟢🟢🟡🟡🔴🔴🔴🟡🟡🟢🟢 |
| Logitech G920 | 5 | Row: 🟢🟢🟡🔴🔴 |
| Logitech G923 | 5 | Row: 🟢🟢🟡🔴🔴 |
| Logitech G27 | 5 | Row: 🟢🟢🟡🔴🔴 |

The Logitech SDK automatically maps the `[min_rpm … max_rpm]` range to however many LEDs the connected wheel has — no configuration needed.

---

## Troubleshooting

**LEDs don't light up**
- Is Logitech G HUB installed and running in the system tray?
- Is `LogitechSteeringWheelEnginesWrapper.dll` next to the script / .exe?
- Did you set Data Out to ON in Forza and use port `5607`?

**`[ERROR] Could not load DLL`**
- The DLL is missing or in the wrong folder. See [Logitech SDK](#logitech-sdk).

**`[WARN] No Logitech wheel detected`**
- Plug in the wheel before launching the tool, or launch the tool after G HUB has detected the wheel.

**Wrong port**
- Make sure the port in Forza's settings matches `UDP_PORT` in the script (default: `5607`).

---

## License

MIT — see [LICENSE](LICENSE).

---

## Under the hood

### 1. The UDP telemetry stream

When **Data Out** is enabled, Forza broadcasts one binary UDP datagram per physics tick (~60 Hz) to the configured IP:port. The packet is a flat C struct serialized in **little-endian** byte order.

FH5 and FH6 send **323 bytes** per packet. FM2023 sends **331 bytes** (8 extra bytes at the end for tire wear and track ID).

### 2. The 12-byte gap (FH4/FH5/FH6 quirk)

The packet is not a single contiguous struct. **Bytes 232–243 are padding** inserted by Playground Games — they contain no useful data. Before parsing, the script removes them:

```
Raw packet (323 bytes):
[  0 ────────────── 231 ][ 232 ─ 243 ][ 244 ──────────── 322 ]
        sled fields        12-byte gap      dash-only fields

After patch (311 bytes):
[  0 ────────────── 231 ][ 232 ──────────────────────────── 310 ]
        sled fields              dash-only fields (shifted)
```

```python
patched = data[:232] + data[244:323]   # skip bytes 232–243
```

### 3. Packet layout (key fields)

The 311-byte patched buffer maps to 85 little-endian fields. Here are the ones used by this script:

```
Offset  Size  Type   Field
──────  ────  ─────  ────────────────────────
0       4     s32    IsRaceOn       — 1 = driving, 0 = menus
                                     Note: 0 also in free roam (FH series)
                                     → script only checks max_rpm > 0
4       4     u32    TimestampMS    — millisecond counter (unused)
8       4     f32    EngineMaxRpm   — redline RPM of the current car
12      4     f32    EngineIdleRpm  — idle RPM (unused)
16      4     f32    CurrentEngineRpm — live RPM
...     ...   ...    (53 other fields: suspension, tyres, speed, position…)
244     4     f32    Speed          — m/s
252     4     f32    Power          — watts
256     4     f32    Torque         — N·m
...     ...   ...
296     1     u8     Gear           — 0 = reverse, 1–10 = forward gears
...
```

> Full struct definition: [`forza_wheel_leds.py` → `DASH_FORMAT`](forza_wheel_leds.py)

### 4. LED logic

From the three RPM values the script computes which of the **5 LEDs** to light up via a single SDK call:

```python
min_rpm = max_rpm * LED_MIN_RPM_RATIO   # e.g. 70 % of redline
LogiSetSteeringWheelRpmLeds(index, currentRPM, min_rpm, max_rpm)
```

The SDK maps `[min_rpm … max_rpm]` linearly across however many LEDs the wheel has:

```
G920 / G27 (5 LEDs)
min_rpm ──────────────────────────── max_rpm
  ○ ○ ○ ○ ○  →  ● ○ ○ ○ ○  →  ● ● ● ● ●

G29 (11 LEDs, green → yellow → red)
min_rpm ──────────────────────────── max_rpm
  ○ ○ ○ ○ ○ ○ ○ ○ ○ ○ ○  →  ● ● ● ● ● ● ● ● ● ● ●
  (all off)                   (all on: 🟢🟢🟡🟡🔴🔴🔴🟡🟡🟢🟢)
```

When `currentRPM ≥ 97 % of max_rpm` (rev-limiter zone), the script **ignores the SDK's progressive mode** and flashes all LEDs on/off at 10 Hz instead:

```python
action, blink_phase, last_blink = compute_led_state(
    current_rpm, max_rpm, blink_phase, last_blink, now,
    blink_thresh, blink_interval
)
# → LED_NORMAL | LED_BLINK_ON | LED_BLINK_OFF | LED_OFF
```

### 5. Logitech SDK call chain

```
forza_wheel_leds.py
  │
  ├── ctypes.CDLL("LogitechSteeringWheelEnginesWrapper.dll")
  │       │
  │       ├── LogiSteeringInitialize()   — connects to G HUB service
  │       ├── LogiIsConnected(0)         — checks wheel presence
  │       └── LogiSetSteeringWheelRpmLeds(index, current, min, max)
  │               └── G HUB driver → USB HID command → G920 LEDs
  │
  └── socket.recvfrom(2048)             — UDP listener (blocking, 1 s timeout)
```

The DLL communicates with the **Logitech G HUB** background service over a local pipe. G HUB then sends the LED state to the wheel over USB HID. This is why G HUB must be running — the DLL itself has no direct USB access.
