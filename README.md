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
- Logitech G920
- Logitech G29
- Logitech G923
- Logitech G27

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
