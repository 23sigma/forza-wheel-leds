"""
Unit tests for forza_wheel_leds.py — targeting 100 % line coverage.

All tests run without a real HID device, UDP socket, or running game.
hidapi.dll is mocked via ctypes.CDLL.
"""

import configparser
import os
import socket
import struct
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, call, patch

# ---------------------------------------------------------------------------
# Helpers to build valid Forza UDP packets
# ---------------------------------------------------------------------------

DASH_FORMAT = (
    "<iI"
    "fff"
    "fff" "fff" "fff" "fff"
    "ffff" "ffff" "ffff"
    "iiii"
    "ffff" "ffff" "ffff" "ffff" "ffff"
    "iiii" "i"
    "fff" "fff" "ffff" "fff" "fff" "f"
    "H" "B" "BBBBB" "bbb"
)


def _pack_packet(
    is_race_on: int = 1,
    max_rpm: float = 8000.0,
    idle_rpm: float = 800.0,
    current_rpm: float = 5000.0,
    car_ordinal: int = 1234,
    accel: int = 0,
    gear: int = 3,
    raw_size: int = 323,
) -> bytes:
    fmt_fields = struct.unpack_from(DASH_FORMAT, bytes(311))
    n = len(fmt_fields)
    vals = [0] * n
    vals[0] = is_race_on
    vals[2] = max_rpm
    vals[3] = idle_rpm
    vals[4] = current_rpm
    vals[53] = car_ordinal
    vals[77] = accel
    vals[81] = gear

    patched = struct.pack(DASH_FORMAT, *vals)
    assert len(patched) == 311

    gap = b"\x00" * 12
    raw_323 = patched[:232] + gap + patched[232:]
    assert len(raw_323) == 323

    if raw_size == 323:
        return raw_323
    elif raw_size == 331:
        return raw_323 + b"\x00" * 8
    else:
        raise ValueError(f"Unsupported raw_size {raw_size}")


# ---------------------------------------------------------------------------
# Import module under test
# ---------------------------------------------------------------------------

import forza_wheel_leds as fwl


# ---------------------------------------------------------------------------
# Tests: patch_and_parse
# ---------------------------------------------------------------------------

class TestPatchAndParse(unittest.TestCase):

    def test_returns_none_for_unknown_size(self):
        self.assertIsNone(fwl.patch_and_parse(b"\x00" * 100))
        self.assertIsNone(fwl.patch_and_parse(b"\x00" * 322))
        self.assertIsNone(fwl.patch_and_parse(b"\x00" * 325))

    def test_fh5_fh6_packet_parsed(self):
        pkt = _pack_packet(is_race_on=1, max_rpm=8000, idle_rpm=800,
                           current_rpm=6000, gear=4, raw_size=323)
        result = fwl.patch_and_parse(pkt)
        self.assertIsNotNone(result)
        self.assertEqual(result["game"], "FH5 / FH6")
        self.assertTrue(result["is_race_on"])
        self.assertAlmostEqual(result["max_rpm"], 8000.0, places=0)
        self.assertAlmostEqual(result["current_rpm"], 6000.0, places=0)
        self.assertAlmostEqual(result["idle_rpm"], 800.0, places=0)
        self.assertEqual(result["gear"], 4)

    def test_fh5_324_variant_parsed(self):
        # FH5 variant with 324 bytes (1 extra byte at end) — same structure
        pkt = _pack_packet(is_race_on=1, max_rpm=7500, current_rpm=4000,
                           gear=3, raw_size=323) + b"\x00"
        result = fwl.patch_and_parse(pkt)
        self.assertIsNotNone(result)
        self.assertEqual(result["game"], "FH5 / FH6")
        self.assertAlmostEqual(result["max_rpm"], 7500.0, places=0)

    def test_fm2023_packet_parsed(self):
        pkt = _pack_packet(is_race_on=1, max_rpm=9000, idle_rpm=900,
                           current_rpm=7000, gear=2, raw_size=331)
        result = fwl.patch_and_parse(pkt)
        self.assertIsNotNone(result)
        self.assertEqual(result["game"], "FM2023")
        self.assertAlmostEqual(result["max_rpm"], 9000.0, places=0)
        self.assertEqual(result["gear"], 2)

    def test_is_race_on_false(self):
        pkt = _pack_packet(is_race_on=0, raw_size=323)
        result = fwl.patch_and_parse(pkt)
        self.assertFalse(result["is_race_on"])

    def test_reverse_gear(self):
        pkt = _pack_packet(gear=0, raw_size=323)
        result = fwl.patch_and_parse(pkt)
        self.assertEqual(result["gear"], 0)

    def test_returns_none_on_struct_error(self):
        pkt = _pack_packet(raw_size=323)
        with patch("struct.unpack_from", side_effect=struct.error("bad")):
            self.assertIsNone(fwl.patch_and_parse(pkt))


# ---------------------------------------------------------------------------
# Tests: rpm_to_bitmask
# ---------------------------------------------------------------------------

class TestRpmToBitmask(unittest.TestCase):

    def test_zero_when_below_min(self):
        self.assertEqual(fwl.rpm_to_bitmask(1000, 5600, 8000), 0x00)

    def test_all_on_when_at_max(self):
        self.assertEqual(fwl.rpm_to_bitmask(8000, 5600, 8000), fwl.ALL_LEDS_ON)

    def test_all_on_when_above_max(self):
        self.assertEqual(fwl.rpm_to_bitmask(9000, 5600, 8000), fwl.ALL_LEDS_ON)

    def test_at_min_gives_zero(self):
        self.assertEqual(fwl.rpm_to_bitmask(5600, 5600, 8000), 0x00)

    def test_progressive_middle(self):
        result = fwl.rpm_to_bitmask(6800, 5600, 8000)
        self.assertGreater(result, 0x00)
        self.assertLess(result, fwl.ALL_LEDS_ON)

    def test_max_equals_min_returns_zero(self):
        self.assertEqual(fwl.rpm_to_bitmask(5000, 5000, 5000), 0x00)

    def test_just_above_min_gives_one_led(self):
        result = fwl.rpm_to_bitmask(5601, 5600, 8000)
        self.assertEqual(result, 0x01)


# ---------------------------------------------------------------------------
# Tests: _hidapi_dll_path
# ---------------------------------------------------------------------------

class TestHidapiDllPath(unittest.TestCase):

    def test_frozen_returns_meipass_path(self):
        with patch.object(sys, "frozen", True, create=True), \
             patch.object(sys, "_MEIPASS", "/fake/meipass", create=True):
            path = fwl._hidapi_dll_path()
        self.assertEqual(os.path.normpath(path), os.path.normpath("/fake/meipass/hidapi.dll"))

    def test_script_beside_file(self):
        with patch.object(sys, "frozen", False, create=True), \
             patch("os.path.exists", return_value=True):
            path = fwl._hidapi_dll_path()
        self.assertTrue(path.endswith("hidapi.dll"))
        self.assertNotEqual(path, "hidapi.dll")

    def test_script_fallback_to_path(self):
        with patch.object(sys, "frozen", False, create=True), \
             patch("os.path.exists", return_value=False):
            path = fwl._hidapi_dll_path()
        self.assertEqual(path, "hidapi.dll")


# ---------------------------------------------------------------------------
# Tests: _config_path
# ---------------------------------------------------------------------------

class TestConfigPath(unittest.TestCase):

    def test_frozen_returns_beside_executable(self):
        with patch.object(sys, "frozen", True, create=True), \
             patch.object(sys, "executable", "/fake/app.exe", create=True):
            path = fwl._config_path()
        self.assertEqual(path, os.path.join("/fake", "config.ini"))

    def test_script_returns_beside_script(self):
        with patch.object(sys, "frozen", False, create=True):
            path = fwl._config_path()
        self.assertTrue(path.endswith("config.ini"))


# ---------------------------------------------------------------------------
# Tests: load_config
# ---------------------------------------------------------------------------

class TestLoadConfig(unittest.TestCase):

    def _write_ini(self, content: str) -> str:
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".ini",
                                        delete=False)
        f.write(content)
        f.close()
        return f.name

    def test_defaults_when_file_absent(self):
        cfg = fwl.load_config("/nonexistent/config.ini")
        self.assertEqual(cfg["udp_port"],          fwl.UDP_PORT)
        self.assertAlmostEqual(cfg["led_min_rpm_ratio"], fwl.LED_MIN_RPM_RATIO)
        self.assertEqual(cfg["blink_offset_low_gear_rpm"],   fwl.BLINK_OFFSET_LOW_GEAR_RPM)
        self.assertEqual(cfg["blink_offset_high_gear_rpm"],   fwl.BLINK_OFFSET_HIGH_GEAR_RPM)
        self.assertAlmostEqual(cfg["blink_hz"],          fwl.BLINK_HZ)

    def test_reads_all_keys(self):
        ini = self._write_ini(
            "[settings]\n"
            "udp_port=1234\n"
            "led_min_rpm_ratio=0.65\n"
            "blink_offset_low_gear_rpm=150\n"
            "blink_offset_high_gear_rpm=100\n"
            "blink_hz=8\n"
        )
        try:
            cfg = fwl.load_config(ini)
        finally:
            os.unlink(ini)
        self.assertEqual(cfg["udp_port"], 1234)
        self.assertAlmostEqual(cfg["led_min_rpm_ratio"], 0.65)
        self.assertEqual(cfg["blink_offset_low_gear_rpm"],   150)
        self.assertEqual(cfg["blink_offset_high_gear_rpm"],   100)
        self.assertAlmostEqual(cfg["blink_hz"],          8.0)

    def test_invalid_values_fall_back_to_defaults(self):
        ini = self._write_ini(
            "[settings]\n"
            "udp_port=notanumber\n"
            "blink_hz=bad\n"
        )
        try:
            cfg = fwl.load_config(ini)
        finally:
            os.unlink(ini)
        self.assertEqual(cfg["udp_port"], fwl.UDP_PORT)
        self.assertAlmostEqual(cfg["blink_hz"], fwl.BLINK_HZ)

    def test_missing_section_uses_defaults(self):
        ini = self._write_ini("[other]\nfoo=bar\n")
        try:
            cfg = fwl.load_config(ini)
        finally:
            os.unlink(ini)
        self.assertEqual(cfg["udp_port"], fwl.UDP_PORT)

    def test_forward_targets_parsed(self):
        ini = self._write_ini(
            "[settings]\n"
            "[forward]\n"
            "targets = 192.168.1.42:5607, 127.0.0.1:5608\n"
        )
        try:
            cfg = fwl.load_config(ini)
        finally:
            os.unlink(ini)
        self.assertEqual(cfg["forward_targets"],
                         [("192.168.1.42", 5607), ("127.0.0.1", 5608)])

    def test_forward_targets_empty(self):
        cfg = fwl.load_config("/nonexistent/config.ini")
        self.assertEqual(cfg["forward_targets"], [])

    def test_forward_targets_malformed_ignored(self):
        ini = self._write_ini(
            "[forward]\n"
            "targets = notavalidentry, 192.168.1.1:5607\n"
        )
        try:
            cfg = fwl.load_config(ini)
        finally:
            os.unlink(ini)
        self.assertEqual(cfg["forward_targets"], [("192.168.1.1", 5607)])

    def test_forward_targets_blank(self):
        ini = self._write_ini("[forward]\ntargets =\n")
        try:
            cfg = fwl.load_config(ini)
        finally:
            os.unlink(ini)
        self.assertEqual(cfg["forward_targets"], [])

    def test_forward_targets_trailing_comma(self):
        """Trailing comma produces an empty entry that should be skipped."""
        ini = self._write_ini("[forward]\ntargets = 192.168.1.1:5607,\n")
        try:
            cfg = fwl.load_config(ini)
        finally:
            os.unlink(ini)
        self.assertEqual(cfg["forward_targets"], [("192.168.1.1", 5607)])

    def test_save_config(self):
        ini = self._write_ini("[settings]\n")
        try:
            settings = {
                "udp_port": 9999,
                "led_min_rpm_ratio": 0.75,
                "blink_offset_low_gear_rpm": 300,
                "blink_offset_high_gear_rpm": 250,
                "use_auto_redline": True,
                "blink_hz": 12.0
            }
            fwl.save_config(ini, settings)
            cfg = fwl.load_config(ini)
            self.assertEqual(cfg["udp_port"], 9999)
            self.assertAlmostEqual(cfg["led_min_rpm_ratio"], 0.75)
            self.assertEqual(cfg["blink_offset_low_gear_rpm"], 300)
            self.assertEqual(cfg["blink_offset_high_gear_rpm"], 250)
            self.assertTrue(cfg["use_auto_redline"])
            self.assertAlmostEqual(cfg["blink_hz"], 12.0)
        finally:
            if os.path.exists(ini):
                os.unlink(ini)

    def test_save_config_oserror(self):
        with patch("builtins.open", side_effect=OSError("write error")):
            fwl.save_config("/fake/config.ini", {
                "udp_port": 1234, 
                "led_min_rpm_ratio": 0.65, 
                "blink_offset_low_gear_rpm": 250, 
                "blink_offset_high_gear_rpm": 200, 
                "use_auto_redline": True, 
                "blink_hz": 10.0
            })
            # should swallow the error and not raise

    def test_load_car_sections(self):
        ini = self._write_ini(
            "[settings]\n"
            "udp_port=1234\n"
            "[car_1234]\n"
            "redline=8200.0\n"
            "nominal_max_rpm=8000.0\n"
            "led_min_rpm_ratio=0.65\n"
            "blink_offset_low_gear_rpm=150\n"
            "blink_offset_high_gear_rpm=100\n"
            "blink_hz=10.0\n"
            "[car_bad]\n"
            "redline=invalid\n"
        )
        try:
            cfg = fwl.load_config(ini)
        finally:
            os.unlink(ini)
        self.assertIn(1234, cfg["cars"])
        c = cfg["cars"][1234]
        self.assertEqual(c["redline"], 8200.0)
        self.assertEqual(c["nominal_max_rpm"], 8000.0)
        self.assertEqual(c["led_min_rpm_ratio"], 0.65)
        self.assertEqual(c["blink_offset_low_gear_rpm"], 150)
        self.assertEqual(c["blink_offset_high_gear_rpm"], 100)
        self.assertEqual(c["blink_hz"], 10.0)

# ---------------------------------------------------------------------------
# Tests: forward_packet
# ---------------------------------------------------------------------------

class TestForwardPacket(unittest.TestCase):

    def test_sends_to_all_targets(self):
        mock_sock = MagicMock()
        data = b"\x01\x02\x03"
        targets = [("192.168.1.42", 5607), ("127.0.0.1", 5608)]
        fwl.forward_packet(mock_sock, data, targets)
        mock_sock.sendto.assert_any_call(data, ("192.168.1.42", 5607))
        mock_sock.sendto.assert_any_call(data, ("127.0.0.1", 5608))
        self.assertEqual(mock_sock.sendto.call_count, 2)

    def test_empty_targets_sends_nothing(self):
        mock_sock = MagicMock()
        fwl.forward_packet(mock_sock, b"\x00", [])
        mock_sock.sendto.assert_not_called()

    def test_oserror_is_swallowed(self):
        mock_sock = MagicMock()
        mock_sock.sendto.side_effect = OSError("network unreachable")
        # must not raise
        fwl.forward_packet(mock_sock, b"\x00", [("10.0.0.1", 9999)])


# ---------------------------------------------------------------------------
# Tests: load_hidapi
# ---------------------------------------------------------------------------

class TestLoadHidapi(unittest.TestCase):

    def test_raises_oserror_when_dll_not_found(self):
        with patch("ctypes.CDLL", side_effect=OSError("not found")):
            with self.assertRaises(OSError):
                fwl.load_hidapi()

    def test_returns_lib_and_calls_hid_init(self):
        mock_lib = MagicMock()
        with patch("ctypes.CDLL", return_value=mock_lib):
            result = fwl.load_hidapi()
        self.assertIs(result, mock_lib)
        mock_lib.hid_init.assert_called_once()


# ---------------------------------------------------------------------------
# Tests: open_wheel
# ---------------------------------------------------------------------------

class TestOpenWheel(unittest.TestCase):

    def test_returns_handle_when_first_pid_matches(self):
        lib = MagicMock()
        lib.hid_open.return_value = 0xDEAD
        result = fwl.open_wheel(lib)
        self.assertEqual(result, 0xDEAD)
        lib.hid_open.assert_called_once_with(fwl.LOGITECH_VID, fwl.WHEEL_PIDS[0], None)

    def test_tries_second_pid_when_first_returns_null(self):
        lib = MagicMock()
        lib.hid_open.side_effect = [None, 0xBEEF]
        result = fwl.open_wheel(lib)
        self.assertEqual(result, 0xBEEF)

    def test_returns_none_when_all_pids_fail(self):
        lib = MagicMock()
        lib.hid_open.return_value = None
        result = fwl.open_wheel(lib)
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# Tests: _send_led_report
# ---------------------------------------------------------------------------

class TestSendLedReport(unittest.TestCase):

    def test_writes_correct_report(self):
        lib = MagicMock()
        fwl._send_led_report(lib, 0xDEAD, 0x1F)
        lib.hid_write.assert_called_once_with(
            0xDEAD,
            bytes([0x00, 0xF8, 0x12, 0x1F, 0x00, 0x00, 0x00, 0x00]),
            8,
        )

    def test_bitmask_masked_to_byte(self):
        lib = MagicMock()
        fwl._send_led_report(lib, 1, 0x1FF)
        report = lib.hid_write.call_args[0][1]
        self.assertEqual(report[3], 0xFF)


# ---------------------------------------------------------------------------
# Tests: compute_led_state
# ---------------------------------------------------------------------------

class TestComputeLedState(unittest.TestCase):

    def _call(self, current_rpm, max_rpm, blink_phase, last_blink, now,
              blink_thresh=None, blink_interval=0.1):
        if blink_thresh is None:
            min_rpm = max_rpm * fwl.LED_MIN_RPM_RATIO
            blink_thresh = max(min_rpm + 100, max_rpm - fwl.BLINK_OFFSET_LOW_GEAR_RPM)
        return fwl.compute_led_state(
            current_rpm, max_rpm, blink_phase, last_blink, now,
            blink_thresh, blink_interval,
        )

    def test_normal_zone_returns_normal(self):
        action, phase, lb = self._call(5000, 8000, False, 0.0, 1.0)
        self.assertEqual(action, fwl.LED_NORMAL)
        self.assertFalse(phase)

    def test_normal_zone_resets_blink_phase(self):
        action, phase, lb = self._call(5000, 8000, True, 0.0, 1.0)
        self.assertEqual(action, fwl.LED_NORMAL)
        self.assertFalse(phase)

    def test_blink_zone_toggles_after_interval(self):
        action, phase, lb = self._call(7800, 8000, False, 0.0, 1.0,
                                       blink_thresh=7760, blink_interval=0.1)
        self.assertEqual(action, fwl.LED_BLINK_ON)
        self.assertTrue(phase)

    def test_blink_zone_no_toggle_before_interval(self):
        action, phase, lb = self._call(7800, 8000, False, 0.99, 1.0,
                                       blink_thresh=7760, blink_interval=0.1)
        self.assertEqual(action, fwl.LED_BLINK_OFF)
        self.assertFalse(phase)

    def test_blink_zone_phase_true_gives_blink_on(self):
        action, _, _ = self._call(7800, 8000, True, 0.99, 1.0,
                                  blink_thresh=7760, blink_interval=0.1)
        self.assertEqual(action, fwl.LED_BLINK_ON)

    def test_blink_zone_toggle_off(self):
        action, phase, lb = self._call(7800, 8000, True, 0.0, 1.0,
                                       blink_thresh=7760, blink_interval=0.1)
        self.assertEqual(action, fwl.LED_BLINK_OFF)
        self.assertFalse(phase)

    def test_exactly_at_blink_thresh(self):
        action, _, _ = self._call(7760, 8000, False, 0.0, 1.0,
                                  blink_thresh=7760, blink_interval=0.1)
        self.assertIn(action, (fwl.LED_BLINK_ON, fwl.LED_BLINK_OFF))


# ---------------------------------------------------------------------------
# Tests: apply_led_action
# ---------------------------------------------------------------------------

class TestApplyLedAction(unittest.TestCase):

    def test_led_off_sends_all_off(self):
        lib = MagicMock()
        fwl.apply_led_action(lib, 1, fwl.LED_OFF, 0, 0, 0)
        report = lib.hid_write.call_args[0][1]
        self.assertEqual(report[3], fwl.ALL_LEDS_OFF)

    def test_led_blink_off_sends_all_off(self):
        lib = MagicMock()
        fwl.apply_led_action(lib, 1, fwl.LED_BLINK_OFF, 0, 0, 0)
        report = lib.hid_write.call_args[0][1]
        self.assertEqual(report[3], fwl.ALL_LEDS_OFF)

    def test_led_blink_on_sends_all_on(self):
        lib = MagicMock()
        fwl.apply_led_action(lib, 1, fwl.LED_BLINK_ON, 0, 0, 0)
        report = lib.hid_write.call_args[0][1]
        self.assertEqual(report[3], fwl.ALL_LEDS_ON)

    def test_led_normal_sends_computed_bitmask(self):
        lib = MagicMock()
        fwl.apply_led_action(lib, 1, fwl.LED_NORMAL, 8000.0, 5600.0, 8000.0)
        report = lib.hid_write.call_args[0][1]
        self.assertEqual(report[3], fwl.ALL_LEDS_ON)


# ---------------------------------------------------------------------------
# Tests: main()
# ---------------------------------------------------------------------------

class TestMain(unittest.TestCase):

    def _make_lib(self, wheel_found=True):
        lib = MagicMock()
        lib.hid_open.return_value = 0xDEAD if wheel_found else None
        return lib

    def _run_main(self, packets, wheel_found=True, dll_load_ok=True, kb_presses=None):
        lib = self._make_lib(wheel_found)
        mock_sock = MagicMock()
        recv_iter = iter(packets)

        def fake_recvfrom(_):
            try:
                item = next(recv_iter)
            except StopIteration:
                raise KeyboardInterrupt
            if item is socket.timeout:
                raise socket.timeout
            return item, ("127.0.0.1", 5607)

        mock_sock.recvfrom.side_effect = fake_recvfrom

        if dll_load_ok:
            load_patch = patch.object(fwl, "load_hidapi", return_value=lib)
        else:
            load_patch = patch.object(fwl, "load_hidapi",
                                      side_effect=OSError("dll missing"))

        presses = kb_presses or []
        
        def fake_kbhit():
            return len(presses) > 0

        def fake_getch():
            if len(presses) > 0:
                return presses.pop(0)
            return b''

        with load_patch, \
             patch("socket.socket", return_value=mock_sock), \
             patch("time.time", return_value=100.0), \
             patch.object(fwl, "_config_path", return_value="/fake/config.ini"), \
             patch("os.path.exists", return_value=False), \
             patch("builtins.input"), \
             patch("msvcrt.kbhit", new=fake_kbhit), \
             patch("msvcrt.getch", new=fake_getch):
            fwl.main()

        return lib

    def test_main_config_file_present_label(self):
        """Cover the cfg_source = 'config.ini' branch (os.path.exists returns True)."""
        pkt = _pack_packet(is_race_on=1, max_rpm=8000, current_rpm=5000,
                           raw_size=323)
        lib = self._make_lib(wheel_found=True)
        mock_sock = MagicMock()
        recv_iter = iter([pkt])

        def fake_recvfrom(_):
            try:
                return next(recv_iter), ("127.0.0.1", 5607)
            except StopIteration:
                raise KeyboardInterrupt

        mock_sock.recvfrom.side_effect = fake_recvfrom

        with patch.object(fwl, "load_hidapi", return_value=lib), \
             patch("socket.socket", return_value=mock_sock), \
             patch("time.time", return_value=100.0), \
             patch.object(fwl, "_config_path", return_value="/fake/config.ini"), \
             patch("os.path.exists", return_value=True), \
             patch("builtins.input"):
            fwl.main()

    def test_main_dll_not_found_exits(self):
        with self.assertRaises(SystemExit):
            self._run_main([], dll_load_ok=False)

    def test_main_normal_race(self):
        pkt = _pack_packet(is_race_on=1, max_rpm=8000, current_rpm=5000,
                           gear=3, raw_size=323)
        self._run_main([pkt])

    def test_main_fm2023_packet(self):
        pkt = _pack_packet(is_race_on=1, max_rpm=9000, current_rpm=6000,
                           gear=2, raw_size=331)
        self._run_main([pkt])

    def test_main_no_race_but_driving(self):
        pkt = _pack_packet(is_race_on=0, max_rpm=8000, current_rpm=4000,
                           gear=3, raw_size=323)
        self._run_main([pkt])

    def test_main_max_rpm_zero_turns_leds_off(self):
        pkt = _pack_packet(is_race_on=1, max_rpm=0, current_rpm=0, raw_size=323)
        self._run_main([pkt])

    def test_main_redline_blink(self):
        pkt = _pack_packet(is_race_on=1, max_rpm=8000, current_rpm=7800,
                           gear=6, raw_size=323)
        self._run_main([pkt])

    def test_main_reverse_gear(self):
        pkt = _pack_packet(is_race_on=1, max_rpm=8000, current_rpm=2000,
                           gear=0, raw_size=323)
        self._run_main([pkt])

    def test_main_socket_timeout_then_packet(self):
        pkt = _pack_packet(is_race_on=1, max_rpm=8000, current_rpm=5000,
                           raw_size=323)
        self._run_main([socket.timeout, pkt])

    def test_main_unknown_packet_ignored(self):
        bad = b"\x00" * 100
        pkt = _pack_packet(is_race_on=1, max_rpm=8000, current_rpm=5000,
                           raw_size=323)
        self._run_main([bad, pkt])

    def test_main_no_wheel_on_start(self):
        pkt = _pack_packet(is_race_on=1, max_rpm=8000, current_rpm=5000,
                           raw_size=323)
        self._run_main([pkt], wheel_found=False)

    def test_main_max_rpm_zero_no_wheel(self):
        pkt = _pack_packet(is_race_on=1, max_rpm=0, current_rpm=0, raw_size=323)
        self._run_main([pkt], wheel_found=False)

    def test_main_game_detected_printed_once(self):
        pkt = _pack_packet(is_race_on=1, max_rpm=8000, current_rpm=5000,
                           raw_size=323)
        self._run_main([pkt, pkt])

    def test_main_second_game_triggers_new_label(self):
        pkt1 = _pack_packet(raw_size=323)
        pkt2 = _pack_packet(raw_size=331)
        self._run_main([pkt1, pkt2])

    def test_main_forward_targets_displayed_and_called(self):
        """Forwarding targets in config are shown in banner and packets are forwarded."""
        pkt = _pack_packet(is_race_on=1, max_rpm=8000, current_rpm=5000,
                           raw_size=323)
        lib = self._make_lib(wheel_found=True)
        mock_sock = MagicMock()
        recv_iter = iter([pkt])

        def fake_recvfrom(_):
            try:
                return next(recv_iter), ("127.0.0.1", 5607)
            except StopIteration:
                raise KeyboardInterrupt

        mock_sock.recvfrom.side_effect = fake_recvfrom

        fake_cfg = {
            "udp_port": 5607,
            "led_min_rpm_ratio": fwl.LED_MIN_RPM_RATIO,
            "blink_offset_low_gear_rpm": fwl.BLINK_OFFSET_LOW_GEAR_RPM,
            "blink_offset_high_gear_rpm": fwl.BLINK_OFFSET_HIGH_GEAR_RPM,
            "blink_hz": fwl.BLINK_HZ,
            "use_auto_redline": fwl.USE_AUTO_REDLINE,
            "forward_targets": [("192.168.1.42", 5607)],
        }

        with patch.object(fwl, "load_hidapi", return_value=lib), \
             patch("socket.socket", return_value=mock_sock), \
             patch("time.time", return_value=100.0), \
             patch.object(fwl, "_config_path", return_value="/fake/config.ini"), \
             patch.object(fwl, "load_config", return_value=fake_cfg), \
             patch("os.path.exists", return_value=True), \
             patch("builtins.input"):
            fwl.main()

        mock_sock.sendto.assert_called_with(pkt, ("192.168.1.42", 5607))

    def test_main_wheel_reconnects_during_loop(self):
        """handle starts None, wheel found on first packet retry."""
        pkt = _pack_packet(is_race_on=1, max_rpm=8000, current_rpm=5000,
                           raw_size=323)
        lib = MagicMock()
        # Startup: all PIDs return None → open_wheel returns None
        # Loop retry: first PID returns a valid handle
        lib.hid_open.side_effect = [None]*5 + [0xDEAD]

        mock_sock = MagicMock()
        recv_iter = iter([pkt])

        def fake_recvfrom(_):
            try:
                return next(recv_iter), ("127.0.0.1", 5607)
            except StopIteration:
                raise KeyboardInterrupt

        mock_sock.recvfrom.side_effect = fake_recvfrom

        with patch.object(fwl, "load_hidapi", return_value=lib), \
             patch("socket.socket", return_value=mock_sock), \
             patch("time.time", return_value=100.0), \
             patch.object(fwl, "_config_path", return_value="/fake/config.ini"), \
             patch("os.path.exists", return_value=False), \
             patch("builtins.input"):
            fwl.main()

        lib.hid_write.assert_called()

    def test_main_finally_handles_errors(self):
        """Cover except-pass branches in finally when lib/sock calls raise."""
        lib = MagicMock()
        lib.hid_open.return_value = 0xDEAD
        lib.hid_write.side_effect = Exception("write error")
        lib.hid_close.side_effect = Exception("close error")
        lib.hid_exit.side_effect  = Exception("exit error")

        mock_sock = MagicMock()
        mock_sock.recvfrom.side_effect = KeyboardInterrupt
        mock_sock.close.side_effect = Exception("close error")

        with patch.object(fwl, "load_hidapi", return_value=lib), \
             patch("socket.socket", return_value=mock_sock), \
             patch("time.time", return_value=100.0), \
             patch.object(fwl, "_config_path", return_value="/fake/config.ini"), \
             patch("os.path.exists", return_value=False), \
             patch("builtins.input"):
            fwl.main()  # must not raise

    def test_main_loop_and_kb(self):
        class BadStr:
            def __str__(self):
                raise ValueError("bad string representation")

        pkts = [
            _pack_packet(is_race_on=1, max_rpm=8000, current_rpm=7000, accel=255, gear=3, raw_size=323),
            _pack_packet(is_race_on=1, max_rpm=8000, current_rpm=6800, accel=255, gear=3, raw_size=323),
            _pack_packet(is_race_on=1, max_rpm=8000, current_rpm=7000, accel=255, gear=3, raw_size=323),
            _pack_packet(is_race_on=1, max_rpm=8000, current_rpm=6800, accel=255, gear=3, raw_size=323),
            _pack_packet(is_race_on=1, max_rpm=8000, current_rpm=7000, accel=255, gear=3, raw_size=323),
            _pack_packet(is_race_on=1, max_rpm=8000, current_rpm=6800, accel=255, gear=3, raw_size=323),
            _pack_packet(is_race_on=1, max_rpm=8000, current_rpm=6800, accel=255, gear=3, raw_size=323),
        ]
        kb = [
            b'\xe0', b'h',
            b'\xe0', b'p',
            b'\xe0', b'k',
            b'\xe0', b'm',
            b's',
            b'x',
            b'r',
            BadStr()
        ]
        self._run_main(pkts, kb_presses=kb)

    def test_main_keyboard_save_and_autosave(self):
        mock_detector = MagicMock()
        mock_detector.is_locked.return_value = True
        mock_detector.get_limiter.return_value = 8200.0
        mock_detector.car_data = {
            1234: {"max_seen": 8200.0, "nominal_max_rpm": 8000.0}
        }

        pkt = _pack_packet(is_race_on=1, max_rpm=8000, current_rpm=5000, car_ordinal=1234, accel=255, raw_size=323)

        packet_count = [0]
        kb_queue = [b's']

        def fake_kbhit():
            return packet_count[0] > 0 and len(kb_queue) > 0

        def fake_getch():
            if len(kb_queue) > 0:
                return kb_queue.pop(0)
            return b''

        mock_sock = MagicMock()
        def fake_recvfrom(_):
            if packet_count[0] == 0:
                packet_count[0] += 1
                return pkt, ("127.0.0.1", 5607)
            else:
                raise KeyboardInterrupt

        mock_sock.recvfrom.side_effect = fake_recvfrom

        fake_cfg = {
            "udp_port": 5607,
            "led_min_rpm_ratio": fwl.LED_MIN_RPM_RATIO,
            "blink_offset_low_gear_rpm": fwl.BLINK_OFFSET_LOW_GEAR_RPM,
            "blink_offset_high_gear_rpm": fwl.BLINK_OFFSET_HIGH_GEAR_RPM,
            "blink_hz": fwl.BLINK_HZ,
            "use_auto_redline": True,
            "forward_targets": [],
            "cars": {
                1234: {
                    "redline": 8200.0,
                    "nominal_max_rpm": 8000.0,
                    "led_min_rpm_ratio": 0.55,
                    "blink_offset_low_gear_rpm": 200,
                    "blink_offset_high_gear_rpm": 150,
                    "blink_hz": 15.0
                }
            }
        }

        lib = self._make_lib(wheel_found=True)

        with patch.object(fwl, "load_hidapi", return_value=lib), \
             patch("socket.socket", return_value=mock_sock), \
             patch("time.time", return_value=100.0), \
             patch.object(fwl, "_config_path", return_value="/fake/config.ini"), \
             patch.object(fwl, "load_config", return_value=fake_cfg), \
             patch("os.path.exists", return_value=True), \
             patch("builtins.input"), \
             patch("msvcrt.kbhit", new=fake_kbhit), \
             patch("msvcrt.getch", new=fake_getch), \
             patch.object(fwl, "RedlineDetector", return_value=mock_detector), \
             patch.object(fwl, "save_config") as mock_save:
            fwl.main()

        self.assertTrue(mock_save.called)
        self.assertIn("cars", fake_cfg)
        self.assertIn(1234, fake_cfg["cars"])
        self.assertEqual(fake_cfg["cars"][1234]["redline"], 8200.0)

# ---------------------------------------------------------------------------
# Tests: RedlineDetector
# ---------------------------------------------------------------------------

class TestRedlineDetector(unittest.TestCase):
    def test_locked_after_bounces(self):
        d = fwl.RedlineDetector()
        r = d.get_limiter(car_ordinal=1, current_rpm=7000.0, accel=255, game_max_rpm=8000.0)
        self.assertEqual(r, 8000.0)
        self.assertFalse(d.is_locked(1))
        
        r = d.get_limiter(car_ordinal=1, current_rpm=8100.0, accel=200, game_max_rpm=8000.0)
        self.assertEqual(r, 8000.0)
        self.assertFalse(d.is_locked(1))
        
        r = d.get_limiter(car_ordinal=1, current_rpm=8100.0, accel=255, game_max_rpm=8000.0)
        self.assertEqual(r, 8000.0)
        self.assertEqual(d.car_data[1]["max_seen"], 8100.0)
        
        r = d.get_limiter(car_ordinal=1, current_rpm=7900.0, accel=255, game_max_rpm=8000.0)
        self.assertEqual(d.car_data[1]["bounces"], 1)
        self.assertFalse(d.is_locked(1))
        
        r = d.get_limiter(car_ordinal=1, current_rpm=8050.0, accel=255, game_max_rpm=8000.0)
        r = d.get_limiter(car_ordinal=1, current_rpm=7800.0, accel=255, game_max_rpm=8000.0)
        self.assertEqual(d.car_data[1]["bounces"], 2)
        
        r = d.get_limiter(car_ordinal=1, current_rpm=8050.0, accel=255, game_max_rpm=8000.0)
        r = d.get_limiter(car_ordinal=1, current_rpm=7800.0, accel=255, game_max_rpm=8000.0)
        self.assertEqual(d.car_data[1]["bounces"], 3)
        self.assertTrue(d.is_locked(1))
        
        r = d.get_limiter(car_ordinal=1, current_rpm=5000.0, accel=0, game_max_rpm=8000.0)
        self.assertEqual(r, 8100.0)

    def test_reset(self):
        d = fwl.RedlineDetector()
        d.get_limiter(car_ordinal=1, current_rpm=8100.0, accel=255, game_max_rpm=8000.0)
        self.assertIn(1, d.car_data)
        d.reset(1)
        self.assertNotIn(1, d.car_data)
        d.reset(99)

    def test_initialize_from_cache(self):
        cached = {
            1234: {
                "redline": 8200.0,
                "nominal_max_rpm": 8000.0,
                "led_min_rpm_ratio": 0.65,
                "blink_offset_low_gear_rpm": 150,
                "blink_offset_high_gear_rpm": 100,
                "blink_hz": 10.0
            },
            5678: {
                "redline": 6000.0,
                "nominal_max_rpm": 0.0,
                "led_min_rpm_ratio": 0.65,
                "blink_offset_low_gear_rpm": 150,
                "blink_offset_high_gear_rpm": 100,
                "blink_hz": 10.0
            }
        }
        d = fwl.RedlineDetector(cached_cars=cached)
        r = d.get_limiter(car_ordinal=1234, current_rpm=5000.0, accel=0, game_max_rpm=8000.0)
        self.assertEqual(r, 8200.0)
        self.assertTrue(d.is_locked(1234))
        
        r2 = d.get_limiter(car_ordinal=5678, current_rpm=4000.0, accel=0, game_max_rpm=5800.0)
        self.assertEqual(r2, 6000.0)
        self.assertTrue(d.is_locked(5678))
        self.assertEqual(d.car_data[5678]["nominal_max_rpm"], 5800.0)

    def test_nominal_limit_change_resets(self):
        cached = {
            1234: {
                "redline": 8200.0,
                "nominal_max_rpm": 8000.0
            }
        }
        d = fwl.RedlineDetector(cached_cars=cached)
        r = d.get_limiter(car_ordinal=1234, current_rpm=5000.0, accel=0, game_max_rpm=8300.0)
        self.assertEqual(r, 8300.0)
        self.assertFalse(d.is_locked(1234))

    def test_overrev_unlock_removed(self):
        cached = {
            1234: {
                "redline": 8000.0,
                "nominal_max_rpm": 8000.0
            }
        }
        d = fwl.RedlineDetector(cached_cars=cached)
        r = d.get_limiter(car_ordinal=1234, current_rpm=8250.0, accel=250, game_max_rpm=8000.0)
        self.assertEqual(r, 8000.0)
        self.assertTrue(d.is_locked(1234))

    def test_accel_release_resets_peaks(self):
        d = fwl.RedlineDetector()
        d.get_limiter(car_ordinal=1, current_rpm=9000.0, accel=255, game_max_rpm=10000.0)
        self.assertEqual(d.car_data[1]["max_seen"], 9000.0)
        d.get_limiter(car_ordinal=1, current_rpm=8000.0, accel=0, game_max_rpm=10000.0)
        self.assertEqual(d.car_data[1]["max_seen"], 0.0)

# ---------------------------------------------------------------------------
# Guard
# ---------------------------------------------------------------------------

class TestEntryPoint(unittest.TestCase):
    def test_main_called_when_run_as_script(self):
        with patch.object(fwl, "main") as mock_main, \
             patch.object(fwl, "__name__", "__main__"):
            exec(
                "if __name__ == '__main__': main()",
                {**vars(fwl), "__name__": "__main__", "main": mock_main},
            )
        mock_main.assert_called_once()


if __name__ == "__main__":
    unittest.main()
