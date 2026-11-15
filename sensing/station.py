#!/usr/bin/env python3
"""
station.py — the stop-and-dwell sequencer. One call = one station = one honest sentence.

    venv/bin/python station.py --sim                    # run the protocol on the simulated sensors (no hardware)
    venv/bin/python station.py --name "hall S1"         # on the rover: real sensors, real R4 (motors held OFF)

Protocol (per station, ~65 s):
    0. STOP: motors off (R4 ENABLE released), turret parked.  A moving platform corrupts every RF sense
       (radar self-motion clutter, CSI channel change), so nothing RF is trusted while anything moves.
    1. SETTLE 5 s: radar static gates re-converge; CSI baseline window starts.
    2. DWELL 2 × 30 s: radar gate energies (all gates, 10 Hz, timestamped) + CSI packets (UDP) logged.
       Best gate = the one with the highest breathing-like confidence, as Walleye's VitalsTracker did.
    3. SWEEP: the rover rotates in 20° steps (commanded heading, ±20° true) taking thermal frames and camera
       frames at each; the optical track is associated by bearing.  Skipped in --sim (no motion model).
    4. FUSE and REPORT: two-track log-odds → label → sentence; everything logged to stations.jsonl.

Drivers are thin and swappable; each one raises at import if its hardware library is missing, and the
sequencer then marks that sense "absent" rather than pretending. Nothing here says "alive".
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from detectors import radar_features, csi_features, thermal_features, camera_features  # noqa: E402
from fusion import Calibration, fuse, sentence  # noqa: E402

LOG = os.path.expanduser("~/rover/stations.jsonl")


# ── real drivers (Pi) ────────────────────────────────────────────────────────
class RadarBridge:
    """ESP32 #1 forwards LD2410C engineering frames over USB serial; parse with Walleye's ld2410.py."""

    def __init__(self, port=None, baud=115200):
        import glob
        import serial
        from ld2410 import Parser  # Walleye bench/ld2410.py, copied next to this file on the Pi
        self.port = port or next(p for p in sorted(glob.glob("/dev/serial/by-id/*")) if "CP2102" in p or "Espressif" in p or "ESP32" in p)
        self.ser = serial.Serial(self.port, baud, timeout=0.05)
        self.parser = Parser()

    def collect(self, seconds: float):
        """Timestamped static-gate energies for every gate: returns (t, gates[n, 9])."""
        t, rows = [], []
        t0 = time.time()
        while time.time() - t0 < seconds:
            for frame in self.parser.feed(self.ser.read(512)):
                if "static_gates" in frame:
                    t.append(time.time()); rows.append(frame["static_gates"][:9])
        return np.array(t), np.array(rows, float)


class CsiSink:
    """RuView nodes stream CSI as UDP to SINK_IP:5005. Wire format per node is verified with listen.py --hexdump;
    until then this collects raw packet payloads and takes int8 pairs as (imag, real) like Walleye csi_rx."""

    def __init__(self, port=5005):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("0.0.0.0", port)); self.sock.settimeout(0.2)

    def collect(self, seconds: float):
        from csi import amplitudes  # Walleye bench/csi.py
        t, A = [], []
        t0 = time.time()
        while time.time() - t0 < seconds:
            try:
                data, addr = self.sock.recvfrom(4096)
            except socket.timeout:
                continue
            a = amplitudes(data[-104:])           # last 52 subcarriers × 2 bytes; adjust once the format is confirmed
            if len(a) >= 52:
                t.append(time.time()); A.append(a[:52])
        return np.array(t), np.array(A, float)


class Thermal:
    def __init__(self):
        import board, busio, adafruit_mlx90640
        i2c = busio.I2C(board.SCL, board.SDA, frequency=400000)  # i2c3 on BCM 4/5 is exposed as another bus id; set in config
        self.mlx = adafruit_mlx90640.MLX90640(i2c)
        self.mlx.refresh_rate = adafruit_mlx90640.RefreshRate.REFRESH_4_HZ

    def frame(self):
        buf = [0.0] * 768
        self.mlx.getFrame(buf)
        return np.array(buf).reshape(24, 32)


class Camera:
    """MobileNet-SSD person score per frame via OpenCV DNN (files: MobileNetSSD_deploy.prototxt/.caffemodel in ~/rover)."""

    def __init__(self):
        import cv2
        self.cv2 = cv2
        self.net = cv2.dnn.readNetFromCaffe(os.path.expanduser("~/rover/MobileNetSSD_deploy.prototxt"),
                                            os.path.expanduser("~/rover/MobileNetSSD_deploy.caffemodel"))
        self.cap = cv2.VideoCapture(0)

    def score(self):
        ok, img = self.cap.read()
        if not ok:
            return 0.0
        blob = self.cv2.dnn.blobFromImage(self.cv2.resize(img, (300, 300)), 0.007843, (300, 300), 127.5)
        self.net.setInput(blob); det = self.net.forward()
        best = 0.0
        for i in range(det.shape[2]):
            if int(det[0, 0, i, 1]) == 15:        # class 15 = person
                best = max(best, float(det[0, 0, i, 2]))
        return best


def open_drivers(sim: bool):
    if sim:
        return {}
    d = {}
    for name, cls in (("radar", RadarBridge), ("csi", CsiSink), ("thermal", Thermal), ("camera", Camera)):
        try:
            d[name] = cls()
        except Exception as e:                 # absent hardware is reported, never faked
            print(f"  {name}: absent ({e.__class__.__name__}: {e})")
    return d


# ── the station ─────────────────────────────────────────────────────────────
def run_station(name: str, drivers: dict, sim: bool, rng=None, scenario=None, r4=None, baseline_var=None):
    t_start = time.time()
    if r4:
        r4.stop(); r4.hold_enable(False)        # motors off: nothing RF is trusted while anything moves
    feats = {"radar": None, "csi": None, "thermal": None, "camera": None}

    if sim:
        from sim import station as sim_station
        feats = sim_station(rng, scenario)
    else:
        time.sleep(5.0)                          # settle
        if "radar" in drivers:
            t1, g1 = drivers["radar"].collect(30.0); t2, g2 = drivers["radar"].collect(30.0)
            best = None
            for gate in range(2, min(9, g1.shape[1])):          # gates 0–1 masked: the turret sits in them
                f = radar_features(t1, g1[:, gate], t2, g2[:, gate]); f["gate"] = gate
                if best is None or f["conf"] > best["conf"]:
                    best = f
            feats["radar"] = best
        if "csi" in drivers:
            tc, A = drivers["csi"].collect(30.0)
            feats["csi"] = csi_features(tc, A, baseline_var=baseline_var) if len(tc) > 200 else None
        if "thermal" in drivers:
            frames = [drivers["thermal"].frame() for _ in range(3)]
            feats["thermal"] = max((thermal_features(f) for f in frames), key=lambda d: d["score"])
        if "camera" in drivers:
            feats["camera"] = camera_features([drivers["camera"].score() for _ in range(6)])

    cal = Calibration()
    res = fuse(feats["radar"], feats["csi"], feats["thermal"], feats["camera"], cal)
    line = sentence(res, feats["radar"], name)
    rec = {"station": name, "t": t_start, "seconds": round(time.time() - t_start, 1), "features": feats, "result": res, "sentence": line}
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a") as f:
        f.write(json.dumps(rec, default=float) + "\n")
    return rec


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--sim", action="store_true"); ap.add_argument("--name", default="S1")
    ap.add_argument("--scenario", default="behind drywall 2 m standing")
    a = ap.parse_args()
    if a.sim:
        from sim import SCENARIOS
        rec = run_station(a.name, {}, True, rng=np.random.default_rng(int(time.time())), scenario=SCENARIOS[a.scenario])
    else:
        try:
            from r4 import R4
            r4 = R4()
        except Exception:
            r4 = None
        rec = run_station(a.name, open_drivers(False), False, r4=r4)
    print(json.dumps(rec["result"], indent=1)); print(rec["sentence"])
