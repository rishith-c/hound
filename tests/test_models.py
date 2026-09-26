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


def test_station_runs_a_simulated_stop_to_its_sentence(tmp_path):
    """sensing/station.py --sim: the whole stop (settle, dwell, fuse) on simulated sensors ends in one honest sentence."""
    pytest.importorskip("scipy")
    r = subprocess.run([sys.executable, os.path.join(ROOT, "sensing", "station.py"), "--sim"], cwd=tmp_path,
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr[-2000:]
    last = [l for l in r.stdout.splitlines() if l.strip()][-1]
    assert last.startswith("S1:") and "alive" not in r.stdout.lower(), last


def _ld2410_frame(engineering: bool, static_gates=(0, 0, 5, 60, 20, 10, 5, 3, 2)):
    import struct
    import ld2410
    p = bytes([0x01 if engineering else 0x02, 0xAA, 2]) + struct.pack("<HBHBH", 0, 0, 290, 60, 290)
    if engineering:
        p += bytes([8, 8]) + bytes(9) + bytes(static_gates) + bytes([0, 0])
    p += b"\x55\x00"
    return ld2410.DATA_HEAD + struct.pack("<H", len(p)) + p + ld2410.DATA_TAIL


class _FakePort:
    def __init__(self, chunks): self.chunks, self.written = list(chunks), []
    def write(self, b): self.written.append(bytes(b))
    def flush(self): pass
    def read(self, n): return self.chunks.pop(0) if self.chunks else b""


def test_station_radar_arms_engineering_mode_and_reads_gates(monkeypatch):
    """The LD2410C forgets engineering mode at power-up; without it there are no gate energies and a stop sees nothing."""
    station = pytest.importorskip("station")
    import ld2410
    monkeypatch.setattr(station.time, "sleep", lambda s: None)
    port = _FakePort([_ld2410_frame(True) * 3, _ld2410_frame(False) * 30, _ld2410_frame(True)])
    r = station.RadarUSB("fake", ser=port)
    arm = [ld2410.ENABLE_CONFIG, ld2410.ENG_ON, ld2410.END_CONFIG]
    assert port.written == arm                                              # armed at open
    t, rows = r.collect(0.2)
    assert rows.shape == (4, 9) and list(rows[0]) == [0, 0, 5, 60, 20, 10, 5, 3, 2]   # basic frames add no rows
    assert port.written == arm * 2                                          # 30 basic frames → re-armed once


def _ld2450_frame(x=300, y=1500):
    import struct
    import ld2450
    enc = lambda v: (0x8000 | v) if v >= 0 else (-v & 0x7FFF)            # bit 15 set = positive
    t = struct.pack("<HHHH", enc(x), enc(y), enc(10), 360) + bytes(16)
    return ld2450.HEAD + t + ld2450.TAIL


class _Repeat(_FakePort):
    def read(self, n): return self.chunks[0] if self.chunks else b""      # a radar that keeps talking


def test_radar_check_verdicts(monkeypatch):
    rc = pytest.importorskip("radar_check")
    monkeypatch.setattr(rc.time, "sleep", lambda s: None)
    healthy = rc.check_ld2410("left", 0.05, _Repeat([_ld2410_frame(True)]))
    assert healthy["verdict"] == "PASS" and healthy["strongest_m"] == "2.25–3.00 m"
    assert rc.check_ld2410("left", 0.05, _FakePort([]))["verdict"] == "FAIL"                      # silent: power / TX
    basic = rc.check_ld2410("right", 0.05, _Repeat([_ld2410_frame(False)]))
    assert basic["verdict"] == "WARN" and "RX" in basic["hint"]                                   # arm never arrived
    t = rc.check_ld2450("ld2450", 0.05, _Repeat([_ld2450_frame()]))
    assert t["verdict"] == "PASS" and t["nearest_xy_mm"] == (300, 1500)
    noisy = rc.check_ld2450("ld2450", 0.05, _Repeat([b"login: " * 8]))
    assert noisy["verdict"] == "FAIL" and "enable_gpio_uart.sh" in noisy["hint"]


class _ToFBus:
    """Two VL53L1X on one bus. Waking (XSHUT high) resets a sensor to 0x29; an address change moves every awake sensor
    that answers the old address — which is exactly what goes wrong when both are awake."""
    def __init__(self): self.dev = {22: {"on": False, "addr": 0x29}, 27: {"on": False, "addr": 0x29}}; self.collisions = 0
    def pin(self, bcm):
        bus = self
        class P:
            @property
            def value(self): return bus.dev[bcm]["on"]
            @value.setter
            def value(self, v):
                if v and not bus.dev[bcm]["on"]: bus.dev[bcm]["addr"] = 0x29
                bus.dev[bcm]["on"] = bool(v)
        return P()
    def sensor(self, i2c, address):
        bus = self
        awake = [d for d in bus.dev.values() if d["on"] and d["addr"] == address]
        assert awake, f"nothing answers 0x{address:02x}"
        if len(awake) > 1: bus.collisions += 1
        class S:
            def set_address(self, new):
                for d in awake: d["addr"] = new
        return S()


def test_tofs_come_up_at_two_addresses():
    tof = pytest.importorskip("tof")
    bus = _ToFBus()
    tof.init_tofs(i2c=object(), pin=bus.pin, sensor=bus.sensor, sleep=lambda s: None)
    assert bus.collisions == 0, "two sensors answered 0x29 while one was being addressed"
    assert bus.dev[tof.FRONT_XSHUT]["addr"] == 0x30 and bus.dev[tof.REAR_XSHUT]["addr"] == 0x29


def test_dc_drive_study():
    """dc_drive.py: the linear motor model, and the verdicts it reports (TT fails, the JGA25-370 1:45 passes)."""
    import dc_drive as dc
    rows = {r["name"]: r for r in (dc.evaluate(m) for m in dc.MOTORS)}
    assert not rows["TT 1:48 (6 V, via a buck)"]["ok"]
    assert rows["JGA25-370 12 V 1:45"]["ok"] and rows["JGA25-370 12 V 1:45, 97 mm"]["ok"]
    assert dc.dc_mass(0.1, 0.080) < 0.85 * __import__("drivetrain").design_mass()[1]      # the DC build is lighter
    assert dc.min_stall_for(170, 0.097) < dc.min_stall_for(170, 0.080)                    # bigger wheels need less speed
    assert dc.min_stall_for(100, 0.080) is None                                           # too slow at any torque


def test_thermal_array_ranges():
    """sensing/thermal_arrays.py: worst-case pixel coverage, and the ranking it gives (finer arrays see farther)."""
    import thermal_arrays as ta
    assert ta.cover(0.5) == 0.25 and ta.cover(1.5) == 0.75 and ta.cover(2.0) == 1.0
    r = [ta.max_range(a, 0.5, 0.5) for a in ta.ARRAYS]
    assert r[0] > r[1] > r[2]
    amg = ta.ARRAYS[2]
    assert abs(ta.worst_fill(amg, 0.5, 0.5, r[2]) - ta.F_MIN) < 1e-3              # the range is where the fill hits the threshold


I2CDETECT = """     0  1  2  3  4  5  6  7  8  9  a  b  c  d  e  f
00:                         -- -- -- -- -- -- -- --
10: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
20: -- -- -- -- -- -- -- -- -- 29 -- -- -- -- -- --
30: {30} -- -- 33 -- -- -- -- -- -- -- -- -- -- -- --
40: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
"""


def test_bringup_checks(monkeypatch):
    np = pytest.importorskip("numpy")
    bu = pytest.importorskip("bringup")
    v, txt, hint = bu.check_i2c(I2CDETECT.replace("{30}", "30"))
    assert v == "PASS" and "0x29 0x30 0x33" in txt
    v, txt, hint = bu.check_i2c(I2CDETECT.replace("{30}", "--"))
    assert v == "PASS" and "not yet moved" in txt
    v, _, hint = bu.check_i2c(I2CDETECT.replace("{30}", "--").replace(" 33 ", " -- "))
    assert v == "FAIL" and "0x33 thermal" in hint
    assert bu.check_tof(init=lambda: ("f", "r"), read=lambda s: 850)[0] == "PASS"
    assert bu.check_tof(init=lambda: ("f", "r"), read=lambda s: None if s == "r" else 850)[0] == "WARN"
    room = type("T", (), {"frame": lambda self: 22 + np.random.default_rng(1).normal(0, 0.3, (24, 32))})()
    flat = type("T", (), {"frame": lambda self: np.zeros((24, 32))})()
    assert bu.check_thermal(room)[0] == "PASS" and bu.check_thermal(flat)[0] == "FAIL"
    cam = type("C", (), {"cap": type("V", (), {"read": lambda self: (True, None)})(), "score": lambda self: 0.91})()
    assert bu.check_camera(cam) == ("PASS", "frame ok, person score 0.91", "")
    sink = lambda n: type("S", (), {"collect": lambda self, s: (list(range(n)), None)})()
    assert bu.check_csi(sink(500), 5)[0] == "PASS" and bu.check_csi(sink(100), 5)[0] == "WARN" and bu.check_csi(sink(0), 5)[0] == "FAIL"
    monkeypatch.setattr(bu, "check_thermal", lambda: (_ for _ in ()).throw(ModuleNotFoundError("No module named 'adafruit_mlx90640'")))
    res = bu.run(skip={"i2c", "tof", "camera", "csi", "radars"}, report=lambda s: None)
    assert res == [("thermal", "FAIL", "thermal", "ModuleNotFoundError: No module named 'adafruit_mlx90640'")]
