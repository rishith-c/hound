"""The verification sources of truth: wiring.py must pass, the drivetrain arithmetic must obey its own physics,
and station.py must find the radars the way the rover is wired (two CP2102s + the Pi's own UART)."""
import json
import math
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "sensing"))


def test_wiring_model_has_no_fail(tmp_path):
    r = subprocess.run([sys.executable, os.path.join(ROOT, "wiring.py")], cwd=tmp_path, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout[-2000:]
    s = json.load(open(tmp_path / "wiring.json"))["summary"]
    assert s["counts"]["FAIL"] == 0
    assert s["pi_usb_peak"] <= 1.2 and s["bank_peak"] <= 3.0


def test_drivetrain_identities():
    import drivetrain as d
    m = 5.0
    # level, no acceleration: pure rolling resistance through the √2 mecanum factor and η
    t, f = d.wheel_torque(m, 0.12, 0.0, 0.0)
    assert f == pytest.approx(m * d.G * 0.12)
    assert t == pytest.approx(f * d.WHEEL_R_M * math.sqrt(2) / (4 * d.ETA_MECH))
    # the inertia term is exactly J·a/r on top of the translational term
    t1, _ = d.wheel_torque(m, 0.12, 0.0, 1.0)
    assert t1 - t == pytest.approx(d.WHEEL_R_M * math.sqrt(2) * m / (4 * d.ETA_MECH) + (d.J_WHEEL + d.J_ROTOR) / d.WHEEL_R_M)
    # braking: rolling resistance helps, and a gentle stop needs no motor force at all
    assert d.brake_torque(m, 0.12, 0.0, 0.5)[1] == 0.0
    assert d.brake_torque(m, 0.12, 5.0, 1.8)[1] > d.brake_torque(m, 0.12, 0.0, 1.8)[1]
    # traction: no acceleration → no load; margin scales with μ; weight transfer only ever lowers it
    m03 = d.traction_margin(m, 1.8, 0.3)[0]; m06 = d.traction_margin(m, 1.8, 0.6)[0]
    assert m06 == pytest.approx(2 * m03)
    assert d.traction_margin(m, 1.8, 0.3)[1] < m * d.G / 4


def test_firmware_numbers_in_the_model_match_the_firmware():
    import drivetrain as d
    src = open(os.path.join(ROOT, "firmware", "r4_drive", "r4_drive.ino")).read()
    grab = lambda name: float(src.split(f"{name}")[1].split("=")[1].split(";")[0].strip().rstrip("f"))
    assert d.A_FW_ACCEL == pytest.approx(grab("ACCEL_MM_S2") / 1000)
    assert d.TICK_HZ_FW == grab("TICK_HZ")
    assert d.MAX_RATE_FW == grab("MAX_RATE ")
    assert "3 * aMm" in src                                              # stops ramp at 3× the start rate
    assert d.A_FW_DECEL == pytest.approx(3 * d.A_FW_ACCEL)
    assert d.WHEELBASE_M == pytest.approx(2 * grab("LX_MM") / 1000)


@pytest.fixture
def devs(tmp_path):
    by = tmp_path / "by-id"; by.mkdir()
    for n in ("usb-Silicon_Labs_CP2102_USB_to_UART_Bridge_Controller_0002-if00-port0",
              "usb-Silicon_Labs_CP2102_USB_to_UART_Bridge_Controller_0001-if00-port0",
              "usb-Arduino_UNO_WiFi_R4_CMSIS-DAP_B43A-if01"):
        (by / n).touch()
    (tmp_path / "ttyAMA0").touch(); (tmp_path / "ttyS0").touch()
    (tmp_path / "stock").symlink_to(tmp_path / "ttyS0")               # stock Pi 4: serial0 → mini UART, PL011 = Bluetooth
    (tmp_path / "uart").symlink_to(tmp_path / "ttyAMA0")              # after pi/enable_gpio_uart.sh
    return tmp_path


def _ports(devs, serial0, cfg=None):
    station = pytest.importorskip("station")
    return station.radar_ports(str(devs / "by-id"), str(devs / serial0), str(cfg or devs / "none.json"))


def test_radar_ports_stock_pi_never_takes_the_bluetooth_uart(devs):
    p = _ports(devs, "stock")
    assert set(p) == {"left", "right"}
    assert p["left"].endswith("0001-if00-port0") and p["right"].endswith("0002-if00-port0")
    assert not any("Arduino" in v for v in p.values())


def test_radar_ports_with_the_uart_enabled_finds_the_ld2450(devs):
    assert _ports(devs, "uart")["ld2450"].endswith("uart")


def test_radars_json_overrides_but_keeps_the_rest(devs):
    cfg = devs / "radars.json"; cfg.write_text('{"ld2450": "/dev/ttyAMA0", "left": "X"}')
    p = _ports(devs, "stock", cfg)
    assert p["ld2450"] == "/dev/ttyAMA0" and p["left"] == "X" and p["right"].endswith("0002-if00-port0")
