"""The Pi remote (pi/rover/web.py) against a stub R4: the motion recorder, playback timing, trim persistence and the
HTTP API's key check. No serial port, no hardware — web.py is imported with a fake `r4` module and HOME in a temp dir."""
import importlib
import json
import os
import sys
import threading
import time
import types
import urllib.error
import urllib.request

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class FakeR4:
    def __init__(self, *a, **k):
        self.port = "stub"
        self.status = {"tilton": 1, "tilt": 100, "rate": [0, 0, 0, 0], "pca": 1}
        self.sent = []                                   # (monotonic time, command)

    def _send(self, cmd): self.sent.append((time.monotonic(), cmd))
    def tilt(self, deg): self._send(f"t {int(deg)}")
    def nudge_pan(self, d, ms=300): self._send(f"n {1 if d > 0 else -1} {int(ms)}")
    def pan_stop(self): self._send("p 0")
    def velocity(self, *a): self._send("v")
    def stop(self): self._send("s")
    def jog(self, *a): self._send("j")
    def hold_enable(self, on): self._send(f"e {int(on)}")
    def close(self): pass


@pytest.fixture
def web(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "rover").mkdir()
    (tmp_path / "rover" / "pan_trim").write_text("-15")
    monkeypatch.setitem(sys.modules, "r4", types.SimpleNamespace(R4=FakeR4))
    monkeypatch.syspath_prepend(os.path.join(ROOT, "pi", "rover"))
    sys.modules.pop("web", None)
    mod = importlib.import_module("web")
    yield mod
    sys.modules.pop("web", None)


def test_saved_trim_is_sent_at_start(web):
    assert ("T -15" in [c for _, c in web.r4.sent])


def test_record_save_and_replay_keep_order_and_timing(web):
    web.rec_start()                                     # the stub holds tilt 100 → the start pose is logged at t=0
    web.turret_cmd("tilt", 110); time.sleep(0.25)
    web.turret_cmd("nudge", -1, 300); time.sleep(0.15)
    web.turret_cmd("tilt", 90)
    web.rec_stop("nod")
    ev = web.motions["nod"]
    assert [e[1:] for e in ev] == [["tilt", 100, 0], ["tilt", 110, 0], ["nudge", -1, 300], ["tilt", 90, 0]]
    assert json.load(open(web.MOTIONS_FILE))["nod"] == ev                     # saved to ~/rover/motions.json

    web.r4.sent.clear(); t0 = time.monotonic()
    web.play_start("nod"); time.sleep(0.8)
    got = [(round(t - t0, 2), c) for t, c in web.r4.sent]
    assert [c for _, c in got] == ["t 100", "t 110", "n -1 300", "t 90"]
    for (t, _), e in zip(got, ev):
        assert abs(t - e[0]) < 0.06                     # replayed within 60 ms of the recorded times
    assert web.status()["playing"] is None              # finished by itself


def test_stop_without_recording_saves_nothing(web):
    web.rec_start(); web.turret_cmd("tilt", 120); web.rec_stop("a")
    web.rec_stop("")
    assert list(web.motions) == ["a"]


def test_recording_with_only_the_start_pose_is_not_saved(web):
    web.rec_start(); web.rec_stop("empty")
    assert "empty" not in web.motions


def test_unnamed_recordings_take_the_first_free_label(web):
    for _ in range(2):
        web.rec_start(); web.turret_cmd("tilt", 95); web.rec_stop("")
    web.motions.pop("motion 1")
    web.rec_start(); web.turret_cmd("tilt", 96); web.rec_stop("")
    assert set(web.motions) == {"motion 1", "motion 2"}
    assert web.motions["motion 2"][-1][2] == 95         # the older one was not overwritten


def test_playback_can_be_stopped(web):
    web.motions["long"] = [[0.0, "tilt", 100, 0], [5.0, "tilt", 140, 0]]
    web.r4.sent.clear()
    web.play_start("long"); time.sleep(0.1); web.play_stop(); time.sleep(0.2)
    assert "t 140" not in [c for _, c in web.r4.sent]
    assert web.status()["playing"] is None


def test_http_api_needs_the_key_and_serves_the_recorder(web):
    srv = web.ThreadingHTTPServer(("127.0.0.1", 0), web.H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(f"{base}/api/status?k=wrong")
        assert e.value.code == 403
        get = lambda p: json.load(urllib.request.urlopen(f"{base}/api/{p}&k={web.KEY}"))
        assert get("rec?on=1")["rec"] is True
        get("set?tilt=120")
        s = get("rec?on=0&name=wave")
        assert s["rec"] is False and "wave" in s["motions"]
        assert "id=rec" in urllib.request.urlopen(f"{base}/?k={web.KEY}").read().decode()
        get("set?ptrim=20")
        assert open(web.TRIM_FILE).read() == "20" and ("T 20" in [c for _, c in web.r4.sent])
    finally:
        srv.shutdown()


def test_r4_status_is_assembled_across_reads(monkeypatch):
    """pi/rover/r4.py: a status line split over two serial reads is joined, the newest complete JSON wins, noise is ignored."""
    monkeypatch.setitem(sys.modules, "serial", types.SimpleNamespace(Serial=object, SerialException=Exception))
    monkeypatch.syspath_prepend(os.path.join(ROOT, "pi", "rover"))
    sys.modules.pop("r4", None)
    r4 = importlib.import_module("r4")

    class Port:
        def __init__(self, chunks): self.chunks, self.written = list(chunks), []
        def write(self, b): self.written.append(b)
        def read(self, n): return self.chunks.pop(0) if self.chunks else b""

    r = object.__new__(r4.R4)
    r._io = threading.Lock(); r.status = {}
    r.ser = Port([b'noise\n{"tilt": 9', b'2, "pca": 1}\n{"tilt": 1', b'00}\n'])
    r._send("?"); assert r.status == {}                                  # only half a line so far
    r._send("?"); assert r.status == {"tilt": 92, "pca": 1}              # joined across the two reads
    r._send("?"); assert r.status == {"tilt": 100}
    assert r.ser.written == [b"?\n"] * 3
    sys.modules.pop("r4", None)


def test_r4_takes_the_port_exclusively(monkeypatch):
    """web.py holds the R4 all the time; a second opener (station.py, demo.py) must fail loudly, not fight it for the motors."""
    opened = {}
    class Serial:
        def __init__(self, port, baud, **kw): opened.update(kw); self.dtr = False
        def reset_input_buffer(self): pass
        def write(self, b): pass
        def read(self, n): return b""
        def close(self): pass
    monkeypatch.setitem(sys.modules, "serial", types.SimpleNamespace(Serial=Serial, SerialException=Exception))
    monkeypatch.syspath_prepend(os.path.join(ROOT, "pi", "rover"))
    sys.modules.pop("r4", None)
    r4 = importlib.import_module("r4")
    monkeypatch.setattr(r4.time, "sleep", lambda s: None)
    r = r4.R4(port="/dev/fake")
    r._alive = False; r.close()
    assert opened.get("exclusive") is True
    sys.modules.pop("r4", None)


def test_station_finds_r4_in_the_pi_layout(tmp_path):
    """On the Pi, deploy.sh puts r4.py in ~/rover and station.py in ~/rover/sensing: station must still import it."""
    import shutil, subprocess
    (tmp_path / "rover" / "sensing").mkdir(parents=True)
    for f in os.listdir(os.path.join(ROOT, "sensing")):
        if f.endswith(".py") or f.endswith(".json"):
            shutil.copy(os.path.join(ROOT, "sensing", f), tmp_path / "rover" / "sensing")
    (tmp_path / "rover" / "r4.py").write_text("R4 = 'found'\n")
    # a runner OUTSIDE ~/rover, so nothing but station.py's own sys.path can put ~/rover on it (python -c would add the cwd)
    (tmp_path / "run.py").write_text("import importlib.util as u, sys\n"
                                     "s = u.spec_from_file_location('station', sys.argv[1]); m = u.module_from_spec(s)\n"
                                     "s.loader.exec_module(m)\nfrom r4 import R4\nprint(R4)\n")
    r = subprocess.run([sys.executable, str(tmp_path / "run.py"), str(tmp_path / "rover" / "sensing" / "station.py")],
                       cwd=tmp_path, capture_output=True, text=True)
    assert r.stdout.strip() == "found", r.stderr[-800:]


def _wait_senses(web, limit=10.0):
    t0 = time.monotonic()
    while web.senses["running"] and time.monotonic() - t0 < limit:
        time.sleep(0.02)
    return list(web.senses["lines"])


def test_senses_check_streams_bringup_lines_and_can_run_again(web, tmp_path):
    """The remote's 'check senses' runs sensing/bringup.py as its own process and shows its lines; a second press works."""
    d = tmp_path / "sensing"; d.mkdir()
    (d / "bringup.py").write_text("import sys\nprint('PASS  radars  left 10.0 frames/s')\nprint('FAIL  thermal x\\n      → re-seat it')\n"
                                  "print('args', sys.argv[1:])\n")
    web.SENSING = str(d)
    web.senses_start(); web.senses_start()                         # a double tap starts one run
    lines = _wait_senses(web)
    assert lines == ["PASS  radars  left 10.0 frames/s", "FAIL  thermal x", "      → re-seat it", "args ['--seconds', '3']"]
    web.senses_start(); assert _wait_senses(web) == lines            # again, fresh lines
    assert web.status()["mode"] == "idle" and not any(c.startswith("v") for _, c in web.r4.sent)   # motors untouched


def test_senses_check_that_hangs_is_stopped(web, tmp_path):
    d = tmp_path / "sensing"; d.mkdir()
    (d / "bringup.py").write_text("import time\nprint('PASS  i2c  ok', flush=True)\ntime.sleep(60)\n")
    web.SENSING, web.SENSES_TIMEOUT = str(d), 0.5
    web.senses_start()
    lines = _wait_senses(web)
    assert lines[0] == "PASS  i2c  ok" and "stopped after" in lines[-1] and not web.senses["running"]


def test_senses_api_needs_the_key_and_returns_lines(web, tmp_path):
    import http.server
    d = tmp_path / "sensing"; d.mkdir(); (d / "bringup.py").write_text("print('WARN  csi  12 CSI packets/s')\n")
    web.SENSING = str(d)
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), web.H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}/api/senses"
    try:
        with pytest.raises(urllib.error.HTTPError):
            urllib.request.urlopen(base + "?go=1&k=wrong")
        assert not web.senses["running"] and web.senses["lines"] == []    # the wrong key started nothing
        j = json.loads(urllib.request.urlopen(base + f"?go=1&k={web.KEY}").read())
        assert j["senses"]["running"] is True and "mode" in j
        _wait_senses(web)
        j = json.loads(urllib.request.urlopen(base + f"?k={web.KEY}").read())
        assert j["senses"] == {"running": False, "lines": ["WARN  csi  12 CSI packets/s"]}
    finally:
        srv.shutdown()


def test_r4_busy_port_says_what_holds_it(monkeypatch):
    class Busy(Exception): pass
    def Serial(*a, **k): raise Busy("Could not exclusively lock port /dev/ttyACM0: [Errno 11] Resource temporarily unavailable")
    monkeypatch.setitem(sys.modules, "serial", types.SimpleNamespace(Serial=Serial, SerialException=Busy))
    monkeypatch.syspath_prepend(os.path.join(ROOT, "pi", "rover"))
    sys.modules.pop("r4", None)
    r4 = importlib.import_module("r4")
    with pytest.raises(Busy, match="systemctl stop rover-web"):
        r4.R4(port="/dev/ttyACM0")
    sys.modules.pop("r4", None)


def _ld2450_frame(x, y, speed=20):
    import struct
    enc = lambda v: (0x8000 | v) if v >= 0 else (-v & 0x7FFF)            # bit 15 set = positive
    return b"\xaa\xff\x03\x00" + struct.pack("<HHHH", enc(x), enc(y), enc(speed), 360) + bytes(16) + b"\x55\xcc"


def test_radar_view_shows_ld2450_targets_and_lets_the_port_go(web):
    """The remote's radar view reads the LD2450 only while it is on, reports its moving targets, and closes the port."""
    class Port:
        def __init__(self): self.closed = False
        def read(self, n): time.sleep(0.01); return _ld2450_frame(-400, 1800)
        def close(self): self.closed = True
    port = Port()
    web.radar_start(opener=lambda p: port)
    t0 = time.monotonic()
    while not web.status().get("radar", {}).get("targets") and time.monotonic() - t0 < 3:
        time.sleep(0.02)
    r = web.status()["radar"]
    assert r["on"] and r["targets"] == [{"x_mm": -400, "y_mm": 1800, "speed_cms": 20}]
    web.radar_stop(wait=True)
    assert port.closed and "radar" not in web.status()                     # off: port closed, nothing in the status


def test_radar_view_without_the_uart_says_why(web):
    def missing(p): raise OSError(2, "No such file or directory")
    web.radar_start(opener=missing)
    t0 = time.monotonic()
    while web.radar["on"] and time.monotonic() - t0 < 3:
        time.sleep(0.02)
    r = web.status()["radar"]
    assert not r["on"] and "enable_gpio_uart.sh" in r["err"]


def test_check_senses_turns_the_radar_view_off_first(web, tmp_path):
    class Port:
        closed = False
        def read(self, n): time.sleep(0.01); return b""
        def close(self): Port.closed = True
    web.radar_start(opener=lambda p: Port())
    time.sleep(0.1)
    d = tmp_path / "sensing"; d.mkdir(); (d / "bringup.py").write_text("print('PASS  i2c  ok')\n"); web.SENSING = str(d)
    web.senses_start()
    assert Port.closed and not web.radar["on"]                             # bringup gets the port to itself
    _wait_senses(web)


def test_radar_view_waits_while_check_senses_has_the_port(web):
    opened = []
    with web.lock:
        web.senses["running"] = True
    web.radar_start(opener=lambda p: opened.append(p) or (_ for _ in ()).throw(OSError("busy")))
    time.sleep(0.1)
    assert opened == [] and not web.radar["on"]                            # never touched the port
    with web.lock:
        web.senses["running"] = False
