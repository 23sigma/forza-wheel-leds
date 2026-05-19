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
| Python 3.8+ | Only needed if running the `.py` script — not needed for the `.exe` release |

> The Logitech DLL is included in this repo (`dll/x64/` and `dll/x86/`) and bundled automatically in every release zip.

---

## Quick Start

### Option A — Pre-built .exe (no Python needed)

1. Download the latest `forza_wheel_leds_vX.X.X.zip` from [Releases](../../releases/latest) and extract it.
2. Configure Forza (see [In-game setup](#in-game-setup)).
3. Double-click `forza_wheel_leds.exe`.

> The Logitech DLL (`LogitechSteeringWheelEnginesWrapper.dll`) is included in the zip — nothing else to download.

### Option B — Python script

```bash
# No dependencies to install — uses Python stdlib only
python forza_wheel_leds.py
```

Place `dll/x64/LogitechSteeringWheelEnginesWrapper.dll` (or `dll/x86/` for 32-bit Python) in the same folder as the script.

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

## Troubleshooting

**LEDs don't light up**
- Is Logitech G HUB installed and running in the system tray?
- Did you set Data Out to ON in Forza and use port `5607`?

**`[ERROR] Could not load DLL`**
- The DLL is missing from the folder. For the `.exe`: re-download the release zip (DLL is included). For the script: copy `dll/x64/LogitechSteeringWheelEnginesWrapper.dll` next to `forza_wheel_leds.py`.

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
