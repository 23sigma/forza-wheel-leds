"""
forza_wheel_leds.py
--------------------
Bridges Forza telemetry (UDP Data Out) to the Logitech G920/G29 RPM LEDs.

Supported games : Forza Horizon 5, Forza Horizon 6, Forza Motorsport (2023)
Supported wheels: Logitech G920, G29, G923 (any wheel with the Logitech Steering Wheel SDK)

Requirements:
  - Logitech G HUB installed and running
  - LogitechSteeringWheelEnginesWrapper.dll in the same folder as this script
  - Python 3.8+  (not needed if using the .exe release)

In-game setup (all supported Forza titles):
  Settings > HUD and Gameplay  (or Gameplay & HUD)
    Data Out             : ON
    Data Out IP Address  : 127.0.0.1
    Data Out IP Port     : 5607
"""

import ctypes
import socket
import struct
import sys
import time

# ---------------------------------------------------------------------------
# USER CONFIGURATION
# ---------------------------------------------------------------------------

UDP_PORT = 5607       # Must match the port set in-game
UDP_IP   = "0.0.0.0" # Listen on all interfaces (127.0.0.1 also works)

# Fraction of max RPM at which the FIRST LED lights up.
#   0.70 → first LED at 70 % of redline  (shift-indicator feel — recommended)
#   0.50 → first LED at 50 %             (wider spread, always visible)
LED_MIN_RPM_RATIO = 0.70

WHEEL_INDEX = 0       # 0 = first connected Logitech wheel

# ---------------------------------------------------------------------------
# LOGITECH STEERING WHEEL SDK  —  DLL BINDINGS
# ---------------------------------------------------------------------------

DLL_NAME = "LogitechSteeringWheelEnginesWrapper.dll"


def load_logitech_sdk() -> ctypes.CDLL:
    try:
        dll = ctypes.CDLL(DLL_NAME)
    except OSError:
        print(f"[ERROR] Could not load '{DLL_NAME}'.")
        print("        Place the DLL in the same folder as this script / .exe.")
        print("        Download the Logitech Steering Wheel SDK:")
        print("        https://www.logitechg.com/sdk/LogitechSteeringWheelSDK_8.75.30.zip")
        sys.exit(1)

    dll.LogiSteeringInitialize.restype  = ctypes.c_bool
    dll.LogiSteeringInitialize.argtypes = [ctypes.c_bool]

    dll.LogiSteeringShutdown.restype  = None
    dll.LogiSteeringShutdown.argtypes = []

    dll.LogiIsConnected.restype  = ctypes.c_bool
    dll.LogiIsConnected.argtypes = [ctypes.c_int]

    dll.LogiSetSteeringWheelRpmLeds.restype  = ctypes.c_bool
    dll.LogiSetSteeringWheelRpmLeds.argtypes = [
        ctypes.c_int,    # index
        ctypes.c_float,  # currentRPM
        ctypes.c_float,  # minRPM
        ctypes.c_float,  # maxRPM
    ]

    return dll


# ---------------------------------------------------------------------------
# FORZA PACKET PARSING
# ---------------------------------------------------------------------------

# FH5 / FH6 raw packet = 323 bytes.
# Bytes 232–243 are a 12-byte padding gap specific to FH4/FH5/FH6.
# After skipping that gap we get 311 bytes that map to DASH_FORMAT below.
#
# FM2023 raw packet = 331 bytes.
# It carries the same gap, plus 8 extra bytes at the tail
# (TireWear x4 floats + TrackOrdinal s32).  We ignore the tail for now
# and apply the same gap fix so the same parser works for both titles.

DASH_FORMAT = (
    "<iI"        # [0]  IsRaceOn (s32), TimestampMS (u32)
    "fff"        # [2]  EngineMaxRpm, EngineIdleRpm, CurrentEngineRpm
    "fff"        # [5]  AccelerationX/Y/Z
    "fff"        # [8]  VelocityX/Y/Z
    "fff"        # [11] AngularVelocityX/Y/Z
    "fff"        # [14] Yaw, Pitch, Roll
    "ffff"       # [17] NormalizedSuspensionTravel FL/FR/RL/RR
    "ffff"       # [21] TireSlipRatio FL/FR/RL/RR
    "ffff"       # [25] WheelRotationSpeed FL/FR/RL/RR
    "iiii"       # [29] WheelOnRumbleStrip FL/FR/RL/RR
    "ffff"       # [33] WheelInPuddleDepth FL/FR/RL/RR
    "ffff"       # [37] SurfaceRumble FL/FR/RL/RR
    "ffff"       # [41] TireSlipAngle FL/FR/RL/RR
    "ffff"       # [45] TireCombinedSlip FL/FR/RL/RR
    "ffff"       # [49] SuspensionTravelMeters FL/FR/RL/RR
    "iiii"       # [53] CarOrdinal, CarClass, CarPerformanceIndex, DrivetrainType
    "i"          # [57] NumCylinders
    "fff"        # [58] PositionX/Y/Z
    "fff"        # [61] Speed, Power, Torque
    "ffff"       # [64] TireTemp FL/FR/RL/RR
    "fff"        # [68] Boost, Fuel, DistanceTraveled
    "fff"        # [71] BestLap, LastLap, CurrentLap
    "f"          # [74] CurrentRaceTime
    "H"          # [75] LapNumber (u16)
    "B"          # [76] RacePosition (u8)
    "BBBBB"      # [77] Accel, Brake, Clutch, HandBrake, Gear (u8)
    "bbb"        # [82] Steer, NormalizedDrivingLine, NormalizedAIBrakeDifference (s8)
)

# Field indices in the unpacked tuple
IDX_IS_RACE_ON      = 0
IDX_ENGINE_MAX_RPM  = 2
IDX_ENGINE_IDLE_RPM = 3
IDX_CURRENT_RPM     = 4
IDX_GEAR            = 81  # 5th entry in the BBBBB block (0-indexed)

# Raw packet sizes used for game detection
SIZE_FH5_FH6 = 323
SIZE_FM2023  = 331

GAME_LABELS = {
    SIZE_FH5_FH6: "FH5 / FH6",
    SIZE_FM2023:  "FM2023",
}


def patch_and_parse(data: bytes):
    """
    Remove the 12-byte FH4/FH5/FH6 gap (bytes 232–243),
    unpack the struct, and return a named dict of the fields we care about.
    Returns None if the packet size is not recognised.
    """
    size = len(data)
    if size not in (SIZE_FH5_FH6, SIZE_FM2023):
        return None

    patched = data[:232] + data[244:323]  # always 311 bytes after patch

    try:
        vals = struct.unpack_from(DASH_FORMAT, patched)
    except struct.error:
        return None

    return {
        "game":        GAME_LABELS[size],
        "is_race_on":  bool(vals[IDX_IS_RACE_ON]),
        "current_rpm": float(vals[IDX_CURRENT_RPM]),
        "max_rpm":     float(vals[IDX_ENGINE_MAX_RPM]),
        "idle_rpm":    float(vals[IDX_ENGINE_IDLE_RPM]),
        "gear":        int(vals[IDX_GEAR]),
    }


# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------

def leds_off(dll: ctypes.CDLL) -> None:
    """Turn all RPM LEDs off."""
    dll.LogiSetSteeringWheelRpmLeds(
        WHEEL_INDEX,
        ctypes.c_float(0.0),
        ctypes.c_float(1.0),
        ctypes.c_float(1.0),
    )


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main() -> None:
    print("=" * 54)
    print("  forza-wheel-leds  |  Logitech G920/G29 RPM LEDs")
    print("=" * 54)

    # --- Logitech SDK ---
    dll = load_logitech_sdk()

    if not dll.LogiSteeringInitialize(False):
        print("[WARN] LogiSteeringInitialize returned False.")
        print("       Make sure Logitech G HUB is installed and running.")

    time.sleep(0.5)  # Give the SDK a moment to enumerate devices

    if not dll.LogiIsConnected(WHEEL_INDEX):
        print(f"[WARN] No Logitech wheel detected at index {WHEEL_INDEX}.")
        print("       LEDs will activate once a wheel is connected.")
    else:
        print("[INFO] Logitech wheel connected.")

    # --- UDP socket ---
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((UDP_IP, UDP_PORT))
    sock.settimeout(1.0)

    print(f"[INFO] Listening for Forza telemetry on UDP port {UDP_PORT} …")
    print("[INFO] In-game: Settings > HUD and Gameplay > Data Out : ON")
    print("[INFO] Press Ctrl+C to quit.\n")

    last_game = ""

    try:
        while True:
            try:
                data, _ = sock.recvfrom(2048)
            except socket.timeout:
                continue

            packet = patch_and_parse(data)
            if packet is None:
                continue

            # Announce game change
            if packet["game"] != last_game:
                print(f"\n[INFO] Game detected: {packet['game']}")
                last_game = packet["game"]

            if not packet["is_race_on"] or packet["max_rpm"] <= 0:
                leds_off(dll)
                print("  Waiting for race …               ", end="\r")
                continue

            min_rpm = packet["max_rpm"] * LED_MIN_RPM_RATIO

            dll.LogiSetSteeringWheelRpmLeds(
                WHEEL_INDEX,
                ctypes.c_float(packet["current_rpm"]),
                ctypes.c_float(min_rpm),
                ctypes.c_float(packet["max_rpm"]),
            )

            gear_str = "R" if packet["gear"] == 0 else str(packet["gear"])
            print(
                f"  RPM {packet['current_rpm']:6.0f} / {packet['max_rpm']:.0f}"
                f"  |  Gear {gear_str}"
                f"  |  {packet['game']}   ",
                end="\r",
            )

    except KeyboardInterrupt:
        print("\n[INFO] Shutting down …")
    finally:
        leds_off(dll)
        dll.LogiSteeringShutdown()
        sock.close()
        print("[INFO] Done.")


if __name__ == "__main__":
    main()
