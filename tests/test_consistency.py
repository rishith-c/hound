"""Cross-file facts that drifted apart before (tilt channel, motor order, adapter count, tilt limits): each one is
read from every file that states it, and they must agree. The firmware is the authority for what the rover does."""
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
read = lambda *p: open(os.path.join(ROOT, *p), encoding="utf-8").read()
FW = read("firmware", "r4_drive", "r4_drive.ino")
NET = json.load(open(os.path.join(ROOT, "wiring_diagrams.json")))
WEB = read("pi", "rover", "web.py")


def fw_int(name):
    return int(re.search(rf"\b{name}\s*=\s*(\d+)", FW).group(1))


def linked(conn_to):
    """Net-list rows ending at a connector, as (from_connector, from_pin)."""
    return [tuple(r[0]) for rows in NET["connections"].values() for r in rows if r[-1][0] == conn_to]


def test_servo_channels_agree():
    tilt, pan = fw_int("TILT_CH"), fw_int("PAN_CH")
    assert {c for c, _ in linked("TILT")} == {f"PCA_CH{tilt}"}, "net list tilt channel ≠ firmware TILT_CH"
    assert {c for c, _ in linked("PAN")} == {f"PCA_CH{pan}"}, "net list pan channel ≠ firmware PAN_CH"
    wiring = read("wiring.py")
    assert f"tilt servo on PCA9685 channel {tilt}" in wiring and f"channels {tilt} / {pan}" in wiring
    parts = {p["id"]: p for p in json.load(open(os.path.join(ROOT, "assembly.json")))["parts"]}
    assert f"Tilt ch {tilt}, pan ch {pan}" in parts["PCA"]["note"], "assembly.py's PCA9685 note names other channels"
    assert f"Tilt on channel {tilt}, pan on {pan}" in read("bom-site", "manual.html"), "manual's PCA9685 channels ≠ firmware"


def test_tilt_limits_agree():
    lo, hi = fw_int("TILT_MIN"), fw_int("TILT_MAX")
    m = re.search(r"id=tilt type=range min=(\d+) max=(\d+)", WEB)
    assert (int(m.group(1)), int(m.group(2))) == (lo, hi), "remote tilt slider range ≠ firmware limits"
    turret = read("pi", "rover", "turret.py")
    assert f"TILT_MIN_DEG = {lo}" in turret and f"TILT_MAX_DEG = {hi}" in turret


def test_wheel_to_axis_map_agrees():
    axis = re.search(r'AXIS\[4\]\s*=\s*\{\s*"(\w)",\s*"(\w)",\s*"(\w)",\s*"(\w)"', FW).groups()     # FL FR BL BR
    fw_map = dict(zip(("FL", "FR", "BL", "BR"), axis))
    net_map = {r[-1][0][2:]: r[0][0][0] for r in NET["connections"]["2-drive"] if r[0][1] == "2B"}   # M_BL ← X_MOT
    assert net_map == fw_map, f"wiring sheet motor order {net_map} ≠ firmware {fw_map}"
    assert re.search(r"const DRV=\[(.*?)\]", WEB).group(1).replace("'", "").split(",") == list(axis)
    assert "X = BL, Y = FL, Z = BR, A = FR" in json.dumps(json.load(open(os.path.join(ROOT, "bom-site", "bom.json"))), ensure_ascii=False)
    rear = {"BL": "RL", "BR": "RR"}                                       # the manual says rear-left/right
    wheel_of = {ax: w for w, ax in fw_map.items()}
    order = ", ".join(f"{ax} = {rear.get(wheel_of[ax], wheel_of[ax])}" for ax in "XYZA")          # X = RL, Y = FL, Z = RR, A = FR
    found = re.findall(r"X = \w\w, Y = \w\w, Z = \w\w, A = \w\w", read("bom-site", "manual.html"))
    assert found and all(f == order for f in found), f"every motor order in the manual must be {order}: {found}"


def test_radar_adapters_agree():
    cps = sorted(c for c in NET["connectors"] if re.fullmatch(r"CP\d", c))
    bom = {i["id"]: i for i in json.load(open(os.path.join(ROOT, "bom-site", "bom.json")))["items"]}
    assert bom["CP2102"]["qty"] == len(cps), "BOM CP2102 quantity ≠ adapters in the net list"
    assert {c for c, _ in linked("LD2450")} == {"PI"}, "the LD2450 is on the Pi's own UART"
    for ld in ("LDL", "LDR"):
        assert {c for c, _ in linked(ld)} <= set(cps) | {ld}


def test_watchdog_and_keepalive_agree():
    wd_ms = 1000 * 4 / 10                                        # WATCHDOG_TICKS = TICK_HZ * 4 / 10 ticks
    assert "WATCHDOG_TICKS = TICK_HZ * 4 / 10" in FW
    keep = float(re.search(r"KEEPALIVE_S\s*=\s*([\d.]+)", read("pi", "rover", "r4.py")).group(1))
    assert keep * 1000 <= wd_ms / 3, "the Pi's keepalive must beat the R4 watchdog with room for two misses"
