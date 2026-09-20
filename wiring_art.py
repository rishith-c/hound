#!/usr/bin/env python3
"""
wiring_art.py — Fritzing-style illustrated wiring for Hound, generated from the SAME net list as the WireViz sheets
(bom-site/wiring/*.yml) so every wire lands on a real pin. Part artwork = Fritzing breadboard SVGs pulled from the
open libraries (fritzing-parts, adafruit/Fritzing-Library, Protoneer, RafaGS) with pin positions read by fzpin.py;
parts no library has (Wagos, fan, hub, webcam, bank, LD2450, CP2102, dividers) are drawn here.

    venv/bin/python wiring_art.py     # → bom-site/wiring/art-*.svg/.png (one per diagram) + art-poster.svg/.png
"""
import base64
import json
import os
import subprocess

import yaml

ROOT = os.path.dirname(os.path.abspath(__file__))
WDIR = os.path.join(ROOT, "bom-site", "wiring")
PARTS = json.load(open(os.path.join(WDIR, "parts", "parts_pins.json")))
DIAGRAMS = ["1-power", "2-drive", "3a-turret-pi", "3b-turret-shield", "4-pi-sensors", "5-radars-usb", "6-csi"]
NET = {n: yaml.safe_load(open(os.path.join(WDIR, f"{n}.yml"))) for n in DIAGRAMS}

HEX = {"RD": "#e03131", "BK": "#1e1e1e", "YE": "#f5c400", "BU": "#1c7ed6", "GN": "#2f9e44", "WH": "#f1f3f5", "OG": "#f76707", "BN": "#8b5a2b", "VT": "#7048e8", "GY": "#868e96"}
ALIAS = {"coil A +": "A+", "coil A −": "A−", "coil B +": "B+", "coil B −": "B−", "USB-C: NEVER while 5V is fed": "USB-C (never with 5V)", "USB-C from any 5 V charger": "USB-C ← charger",
         "signal (orange)": "sig", "V+ (red)": "V+", "GND (brown)": "GND", "5V (red)": "5V", "GND (black)": "GND", "port 1: UNO R4": "R4", "port 2: CP2102 no.1": "CP1", "port 3: CP2102 no.2": "CP2", "port 4: CP2102 no.3": "CP3",
         "USB 1: webcam": "webcam", "USB 2: hub": "hub", "USB-A out": "out", "upstream": "in"}
WIDTH = {"14 AWG": 7, "22 AWG": 4.2, "24 AWG": 3.6, "26 AWG": 3.0, "28 AWG": 2.6}

# ── sprites ─────────────────────────────────────────────────────────────────────────────────────────────────
# id → dict(part=<fritzing key> | own=<kind>, x, y, s=scale, label, pins={my pin label: connector id | (x, y)}, hosts=[connector ids])
S = {}


def part(cid, key, x, y, s=1.25, label=None, pins=None, hosts=(), **kw):
    S[cid] = dict(part=key, x=x, y=y, s=s, label=label or cid, pins=pins or {}, hosts=list(hosts), **kw)


def own(cid, kind, x, y, label=None, pins=None, hosts=(), **kw):
    S[cid] = dict(own=kind, x=x, y=y, s=1.0, label=label or cid, pins=pins or {}, hosts=list(hosts), **kw)


pi_pins = {lab: f"connector{int(lab.split()[0]) - 1}" for d in ("4-pi-sensors", "3a-turret-pi") for lab in NET[d]["connectors"]["PI"]["pinlabels"]}

# top band: the four motors and the Pi-side sensors
for i, (m, ax) in enumerate((("M_FL", "Y"), ("M_FR", "A"), ("M_BL", "X"), ("M_BR", "Z"))):
    part(m, "stepper", 1000 + i * 180, 30, 0.8, label=f"{m[2:]} — NEMA 17 (axis {ax})",
         pins={"coil A +": "connector0", "coil A −": "connector1", "coil B +": "connector2", "coil B −": "connector3"})
part("MLX", "mlx90640", 1790, 70, 1.25, "MLX90640 thermal (i2c3)", {"VIN 3V3": "connector31", "GND": "connector33", "SCL": "connector34", "SDA": "connector35"})
part("TOF_F", "vl53l1x", 1990, 70, 1.25, "VL53L1X ToF FRONT (→0x30)", {"VIN 3V3": "connector29", "GND": "connector30", "SDA": "connector32", "SCL": "connector31", "XSHUT": "connector34"})
part("TOF_R", "vl53l1x", 2190, 70, 1.25, "VL53L1X ToF REAR (0x29)", {"VIN 3V3": "connector29", "GND": "connector30", "SDA": "connector32", "SCL": "connector31", "XSHUT": "connector34"})
part("MIC", "i2smic", 2390, 90, 1.25, "INMP441 mic (Adafruit art)", {"VDD 3V3": "connector17", "GND": "connector18", "SCK": "connector19", "WS": "connector21", "SD": "connector20", "L/R": "connector22"})
own("PULL", "perf3", 2600, 100, "2 × 4.7 kΩ i2c3 pull-ups", {"3V3": (12, 58), "SDA": (36, 58), "SCL": (60, 58)})
for _c in ("MLX", "TOF_F", "TOF_R", "MIC", "PULL", "M_FL", "M_FR", "M_BL", "M_BR"):
    S[_c]["label_pos"] = "top"

# middle band: pack side → shield → Pi
part("PACK", "lipo", 40, 380, 0.5, "HOOVO 3S 2200 mAh (T-plug)", {"V+": "connector1", "GND": "connector2"})
part("ESTOP", "estop", 170, 400, 0.7, "E-STOP (NC, in the + lead)", {"IN": "connector1", "OUT": "connector3"})
own("WAGO_P", "wago5", 330, 380, "PACK +", {}, tag_inside=True)
own("WAGO_N", "wago5", 330, 560, "PACK − (star ground)", {}, tag_inside=True)
own("DIV", "perf3", 480, 640, "47k / 10k divider", {"PACK+": (12, 58), "A3": (36, 58), "GND": (60, 58)})
part("XL4015", "lm2596", 480, 380, 1.1, "XL4015 buck → 6.0 V (drawn as the LM2596 module)", {"IN+": "connector0", "IN−": "connector1", "OUT+": "connector2", "OUT−": "connector3"})
part("R4", "uno", 1012, 394, 1.25, "", {}, hosts=["R4_USB"])
part("SHIELD", "cnc", 1000, 380, 1.25, "CNC Shield v3 + DRV8825 ×4, stacked on the UNO R4 WiFi (drawn as an Uno)", {}, hosts=["SHIELD_PWR", "SHIELD_CTRL", "SHIELD_A3", "SHIELD_I2C", "X_MOT", "Y_MOT", "Z_MOT", "A_MOT", "DRV"])
part("R_EN", "resistor", 880, 330, 1.6, "10 kΩ EN pull-up", {"EN side": "connector0", "5V side": "connector1"})
part("PI", "pi4", 1780, 380, 1.25, "Raspberry Pi 4", pi_pins, hosts=["PI_USB", "PI_PWR"])
own("CAM", "webcam", 2400, 400, "Webcam (turret)", {"USB-A": (0, 40)})
own("HUB", "hub", 2400, 560, "4-port USB hub", {"upstream": (0, 30), "port 1: UNO R4": (150, 12), "port 2: CP2102 no.1": (150, 26), "port 3: CP2102 no.2": (150, 40), "port 4: CP2102 no.3": (150, 54)})
for i, c in enumerate(("CP1", "CP2", "CP3")):
    own(c, "cp2102", 2620 + i * 110, 380, f"CP2102 no.{i + 1}", {"5V": (30, 0), "3V3": (10, 118), "GND": (20, 118), "TXD": (30, 118), "RXD": (40, 118), "DTR": (50, 118)})
own("BANK", "bank", 1780, 790, "USB power bank 5 V / 3 A", {"USB-A out": (170, 35)})

# bottom band: 5 V rail, turret, radars, CSI
part("LM2596", "lm2596", 480, 820, 1.1, "LM2596 buck → 5.0 V", {"IN+": "connector0", "IN−": "connector1", "OUT+": "connector2", "OUT−": "connector3"})
own("WAGO5_P", "wago5", 780, 820, "5 V +", {}, tag_inside=True)
own("WAGO5_N", "wago5", 900, 820, "5 V −", {}, tag_inside=True)
own("FAN", "fan", 780, 1010, "40 mm 5 V fan", {"5V (red)": (0, 30), "GND (black)": (0, 50)})
part("PCA", "pca9685", 1000, 820, 1.25, "PCA9685 16-ch servo driver", {}, hosts=["PCA_LOGIC", "PCA_PWR", "PCA_CH0"])
part("TILT", "servo", 1470, 830, 1.25, "MG996R TILT servo", {"signal (orange)": "connector2", "V+ (red)": "connector1", "GND (brown)": "connector0"})
part("PAN", "servo", 1470, 1010, 1.25, "MG996R PAN — NOT CONNECTED (locked)", {"signal": "connector2", "V+": "connector1", "GND": "connector0"}, ghost=True)
part("ESP3", "esp32c3", 2400, 800, 0.9, "ESP32-S3 no.3 csi_rx_udp (drawn as a C3 devkit)", {"5V (VIN)": "connector27", "GND": "connector26", "USB-C: NEVER while 5V is fed": (60, 207)})
part("ESP2", "esp32c3", 2560, 800, 0.9, "ESP32-S3 no.2 csi_tx — OFF the rover", {"USB-C from any 5 V charger": (60, 207)}, ghost=True)
part("LDL", "ld2410", 2400, 1070, 1.25, "LD2410C LEFT (+30°)", {"1 TX": "connector0", "2 RX": "connector1", "3 OUT": "connector2", "4 GND": "connector3", "5 VCC": "connector4"})
part("LDR", "ld2410", 2570, 1070, 1.25, "LD2410C RIGHT (−30°)", {"1 TX": "connector0", "2 RX": "connector1", "3 OUT": "connector2", "4 GND": "connector3", "5 VCC": "connector4"})
own("LD2450", "ld2450", 2740, 1070, "LD2450 (3rd adapter)", {"5V": (30, 0), "GND": (50, 0), "TX": (70, 0), "RX": (90, 0)})

# sub-connector pin maps on host parts (my label → host connector id)
HOSTPINS = {
    "SHIELD_PWR": ("SHIELD", {"VMOT": "connector30", "GND": "connector29"}),
    "SHIELD_CTRL": ("SHIELD", {"EN": "connector1", "5V": "connector11", "GND": "connector12", "A-axis jumper D12": "connector25", "A-axis jumper D13": "connector28"}),
    "SHIELD_A3": ("SHIELD", {"A3": "connector95", "GND": "connector96"}),
    "SHIELD_I2C": ("SHIELD", {"A4 SDA": "connector74", "A5 SCL": "connector72", "5V": "connector75", "GND": "connector76"}),
    "X_MOT": ("SHIELD", {"2B": "connector37", "2A": "connector38", "1A": "connector39", "1B": "connector40"}),
    "Y_MOT": ("SHIELD", {"2B": "connector57", "2A": "connector58", "1A": "connector59", "1B": "connector60"}),
    "Z_MOT": ("SHIELD", {"2B": "connector47", "2A": "connector48", "1A": "connector49", "1B": "connector50"}),
    "A_MOT": ("SHIELD", {"2B": "connector67", "2A": "connector68", "1A": "connector69", "1B": "connector70"}),
    "DRV": ("SHIELD", {}),
    "R4_USB": ("R4", {"USB-C": (14, 44)}),
    "PI_USB": ("PI", {"USB 1: webcam": (410, 118), "USB 2: hub": (410, 150), "USB 3: free": (410, 208), "USB 4: free": (410, 242)}),
    "PI_PWR": ("PI", {"USB-C": (55, 268)}),
    "PCA_LOGIC": ("PCA", {"GND": "connector42", "OE": "connector41", "SCL": "connector40", "SDA": "connector39", "VCC": "connector38", "V+": "connector37"}),
    "PCA_PWR": ("PCA", {"V+": "connector7", "GND": "connector8"}),
    "PCA_CH0": ("PCA", {"PWM": "connector34", "V+": "connector35", "GND": "connector36"}),
}
# Wago pins: slot i (from the net list's pinlabels) on the left face
for w in ("WAGO_P", "WAGO_N", "WAGO5_P", "WAGO5_N"):
    labels = next(d["connectors"][w]["pinlabels"] for d in NET.values() if w in d["connectors"])
    S[w]["pins"] = {lab: (0, 22 + i * 24) for i, lab in enumerate(labels)}


# ── own sprite art (drawn at scale 1, origin top-left) ─────────────────────────────────────────────────────
def own_svg(kind, label):
    if kind == "wago5":
        g = ['<rect width="96" height="140" rx="8" fill="#f28c28" stroke="#8a4b00" stroke-width="2"/>',
             '<rect x="60" y="8" width="30" height="124" rx="4" fill="#d9d9d9" stroke="#666"/>']
        for i in range(5):
            y = 22 + i * 24
            g.append(f'<rect x="0" y="{y - 7}" width="26" height="14" rx="3" fill="#3a2a1a"/><circle cx="8" cy="{y}" r="4" fill="#111"/>'
                     f'<rect x="64" y="{y - 8}" width="22" height="16" rx="3" fill="#ff8c1a" stroke="#8a4b00"/>')
        g.append('<text x="44" y="136" font-size="9" text-anchor="middle" fill="#fff" font-family="Helvetica,Arial" font-weight="bold">221-415</text>')
        return "".join(g), 96, 140
    if kind == "perf3":
        return ('<rect width="72" height="60" rx="4" fill="#c8a27a" stroke="#6b4a2b" stroke-width="2"/>'
                + "".join(f'<circle cx="{8 + i * 8}" cy="{10 + j * 10}" r="1.6" fill="#7a5a3a"/>' for i in range(8) for j in range(4))
                + '<rect x="8" y="22" width="22" height="8" rx="2" fill="#e6d2a8" stroke="#333"/><rect x="40" y="22" width="22" height="8" rx="2" fill="#e6d2a8" stroke="#333"/>'
                + "".join(f'<rect x="{x - 2}" y="50" width="4" height="10" fill="#999"/>' for x in (12, 36, 60)), 72, 60)
    if kind == "fan":
        return ('<rect width="80" height="80" rx="8" fill="#222" stroke="#000" stroke-width="2"/><circle cx="40" cy="40" r="34" fill="#333"/>'
                '<circle cx="40" cy="40" r="10" fill="#555"/>' + "".join(f'<path d="M40 40 L{40 + 30 * __import__("math").cos(a)} {40 + 30 * __import__("math").sin(a)} A30 30 0 0 1 {40 + 30 * __import__("math").cos(a + 0.8)} {40 + 30 * __import__("math").sin(a + 0.8)} Z" fill="#777"/>' for a in (0, 1.57, 3.14, 4.71))
                + '<rect x="-14" y="26" width="14" height="8" fill="#e03131"/><rect x="-14" y="46" width="14" height="8" fill="#1e1e1e"/>', 80, 80)
    if kind == "hub":
        return ('<rect width="150" height="66" rx="8" fill="#2b2b2b" stroke="#000" stroke-width="2"/><rect x="-10" y="22" width="14" height="16" fill="#888"/>'
                + "".join(f'<rect x="138" y="{6 + i * 14}" width="14" height="10" fill="#ccc" stroke="#555"/>' for i in range(4))
                + '<text x="70" y="38" font-size="11" text-anchor="middle" fill="#ddd" font-family="Helvetica,Arial">USB hub</text>', 150, 66)
    if kind == "webcam":
        return ('<rect x="0" y="20" width="120" height="40" rx="14" fill="#1f1f1f" stroke="#000" stroke-width="2"/><circle cx="60" cy="40" r="15" fill="#0b2a44" stroke="#4a90d9" stroke-width="2"/>'
                '<circle cx="60" cy="40" r="6" fill="#1a6fc4"/><rect x="50" y="60" width="20" height="14" fill="#333"/><rect x="-8" y="34" width="10" height="12" fill="#888"/>', 120, 80)
    if kind == "bank":
        return ('<rect width="170" height="70" rx="12" fill="#5c636a" stroke="#222" stroke-width="2"/><rect x="160" y="26" width="16" height="18" fill="#ccc" stroke="#555"/>'
                '<path d="M60 14 L44 40 H58 L52 58 L78 30 H62 Z" fill="#ffd43b"/><text x="110" y="42" font-size="12" fill="#fff" font-family="Helvetica,Arial">5 V · 3 A</text>', 170, 70)
    if kind == "ld2450":
        return ('<rect width="120" height="70" rx="4" fill="#1d4f91" stroke="#0b2a4a" stroke-width="2"/>'
                '<rect x="10" y="12" width="22" height="16" fill="#d4a017"/><rect x="49" y="12" width="22" height="16" fill="#d4a017"/><rect x="88" y="12" width="22" height="16" fill="#d4a017"/>'
                '<rect x="46" y="40" width="28" height="20" fill="#111"/><text x="60" y="68" font-size="9" text-anchor="middle" fill="#fff" font-family="Helvetica,Arial">HLK-LD2450</text>'
                + "".join(f'<rect x="{x - 3}" y="-8" width="6" height="10" fill="#ccc" stroke="#555"/>' for x in (30, 50, 70, 90)), 120, 70)
    if kind == "cp2102":
        return ('<rect x="18" y="-10" width="24" height="26" rx="3" fill="#bbb" stroke="#555" stroke-width="2"/><rect width="60" height="110" rx="5" fill="#c0392b" stroke="#6b1a12" stroke-width="2"/>'
                '<rect x="18" y="40" width="24" height="24" fill="#222"/><text x="30" y="34" font-size="8" text-anchor="middle" fill="#fff" font-family="Helvetica,Arial">CP2102</text>'
                + "".join(f'<rect x="{x - 3}" y="108" width="6" height="10" fill="#ccc" stroke="#555"/>' for x in (10, 20, 30, 40, 50)), 60, 118)
    raise KeyError(kind)


# ── helpers ────────────────────────────────────────────────────────────────────────────────────────────────
def sprite_box(cid):
    s = S[cid]
    if "part" in s:
        p = PARTS[s["part"]]; w, h = p["w"] * s["s"], p["h"] * s["s"]
    else:
        _, w, h = own_svg(s["own"], s["label"])
    return s["x"], s["y"], w, h


def pin_xy(cid, lab):
    """Absolute canvas coordinates of a connector's pin, plus the outward direction (dx, dy)."""
    host, pins = (cid, S[cid]["pins"]) if cid in S else HOSTPINS[cid]
    s = S[host]; ref = pins[lab]
    if isinstance(ref, tuple):
        lx, ly = ref[0] * (s["s"] if "part" in s else 1), ref[1] * (s["s"] if "part" in s else 1)
    else:
        p = PARTS[s["part"]]["pins"][ref]; lx, ly = p["x"] * s["s"], p["y"] * s["s"]
    x, y = s["x"] + lx, s["y"] + ly
    bx, by, bw, bh = sprite_box(host)
    d = min((lx, (-1, 0)), (bw - lx, (1, 0)), (ly, (0, -1)), (bh - ly, (0, 1)), key=lambda t: t[0])[1]
    return x, y, d


def wire_path(a, b):
    (x1, y1, d1), (x2, y2, d2) = a, b
    k = max(60, 0.3 * ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5)
    return f"M{x1:.1f} {y1:.1f} C{x1 + d1[0] * k:.1f} {y1 + d1[1] * k:.1f} {x2 + d2[0] * k:.1f} {y2 + d2[1] * k:.1f} {x2:.1f} {y2:.1f}"


def esc(t):
    return str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def draw_sprite(cid, defs, embed):
    s = S[cid]; x, y, w, h = sprite_box(cid); out = []
    if s.get("ghost"):
        out.append(f'<rect x="{x - 8}" y="{y - 8}" width="{w + 16}" height="{h + 16}" rx="10" fill="none" stroke="#999" stroke-dasharray="8 6" stroke-width="2"/>')
    if "part" in s:
        key = s["part"]
        if key not in defs:
            p = PARTS[key]
            href = ("data:image/svg+xml;base64," + base64.b64encode(open(os.path.join(WDIR, "parts", key + ".svg"), "rb").read()).decode()) if embed else f"parts/{key}.svg"
            defs[key] = f'<image id="img-{key}" href="{href}" width="{p["w"]}" height="{p["h"]}"/>'
        op = ' opacity="0.45"' if s.get("ghost") else ""
        out.append(f'<use href="#img-{key}" transform="translate({x} {y}) scale({s["s"]})"{op}/>')
    else:
        art, _, _ = own_svg(s["own"], s["label"])
        out.append(f'<g transform="translate({x} {y})">{art}</g>')
    if s["label"]:
        ly = y - 10 if s.get("label_pos") == "top" else y + h + 22
        out.append(f'<text x="{x + w / 2:.0f}" y="{ly:.0f}" font-size="14" font-weight="bold" text-anchor="middle" fill="#222" font-family="Helvetica,Arial" paint-order="stroke" stroke="#fff" stroke-width="4">{esc(s["label"])}</text>')
    return "".join(out)


def pin_tag(x, y, d, text, inside=False):
    text = ALIAS.get(text, text)
    st = 'font-size="10" font-family="Menlo,monospace" fill="#111" paint-order="stroke" stroke="#fff" stroke-width="3"'
    if inside:
        return f'<text x="{x + 30:.0f}" y="{y + 3.5:.0f}" font-size="8.5" font-family="Menlo,monospace" fill="#fff" paint-order="stroke" stroke="#7a3b00" stroke-width="2.5">{esc(text)}</text>'
    if d[1] < 0:   # exits upward: run the text upward from the pin
        return f'<text transform="rotate(-90 {x:.0f} {y - 14:.0f})" x="{x:.0f}" y="{y - 14 + 3.5:.0f}" text-anchor="start" {st}>{esc(text)}</text>'
    if d[1] > 0:   # exits downward
        return f'<text transform="rotate(90 {x:.0f} {y + 14:.0f})" x="{x:.0f}" y="{y + 14 + 3.5:.0f}" text-anchor="start" {st}>{esc(text)}</text>'
    ox = x + d[0] * 16; anchor = "end" if d[0] < 0 else "start"
    return f'<text x="{ox:.0f}" y="{y + 4:.0f}" text-anchor="{anchor}" {st}>{esc(text)}</text>'


# ── render ─────────────────────────────────────────────────────────────────────────────────────────────────
def render(name, diagrams, embed=False, title=None):
    sprites, wires, tags = set(), [], []
    for dn in diagrams:
        doc = NET[dn]
        for cid in doc["connectors"]:
            sprites.add(HOSTPINS[cid][0] if cid in HOSTPINS else cid)
        for row in doc["connections"]:
            (a, pa), (w, wi), (b, pb) = [(list(h)[0], list(h.values())[0][0]) for h in (row[0], row[1], row[-1])]
            cab = doc["cables"][w]; col = HEX[cab["colors"][int(wi) - 1]]; width = WIDTH.get(cab["gauge"], 3)
            A, B = pin_xy(a, pa), pin_xy(b, pb)
            wires.append((wire_path(A, B), col, width))
            tags.append((A, pa, a)); tags.append((B, pb, b))
    if "SHIELD" in sprites: sprites.add("R4")
    boxes = [sprite_box(c) for c in sprites]
    x0 = min(b[0] for b in boxes) - 90; y0 = min(b[1] for b in boxes) - 110
    x1 = max(b[0] + b[2] for b in boxes) + 70; y1 = max(b[1] + b[3] for b in boxes) + 60
    defs = {}
    body = [draw_sprite(c, defs, embed) for c in sorted(sprites, key=lambda c: (S[c]["part"] != "uno") if "part" in S[c] else True)]
    wire_svg = "".join(f'<path d="{d}" fill="none" stroke="#222" stroke-width="{w + 2.2}" stroke-linecap="round" opacity="0.9"/><path d="{d}" fill="none" stroke="{c}" stroke-width="{w}" stroke-linecap="round"/>' for d, c, w in wires)
    dots = "".join(f'<circle cx="{p[0]:.1f}" cy="{p[1]:.1f}" r="4" fill="#ddd" stroke="#222" stroke-width="1.5"/>' for p, _, _ in tags)
    seen = set(); tag_svg = ""
    for (x, y, d), lab, cid in tags:
        if (round(x), round(y)) in seen: continue
        host = HOSTPINS[cid][0] if cid in HOSTPINS else cid
        seen.add((round(x), round(y))); tag_svg += pin_tag(x, y, d, lab, inside=S[host].get("tag_inside", False))
    W, H = x1 - x0, y1 - y0
    ttl = title or NET[diagrams[0]]["metadata"]["title"]
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="{x0:.0f} {y0:.0f} {W:.0f} {H:.0f}" width="{W:.0f}" height="{H:.0f}">'
           f'<defs>{"".join(defs.values())}</defs><rect x="{x0}" y="{y0}" width="{W}" height="{H}" fill="#ffffff"/>'
           f'<text x="{x0 + 24}" y="{y0 + 34}" font-size="22" font-weight="bold" font-family="Helvetica,Arial" fill="#222">{esc(ttl)}</text>'
           f'<text x="{x0 + 24}" y="{y0 + 54}" font-size="12" font-family="Helvetica,Arial" fill="#555">Part artwork: Fritzing open libraries (fritzing-parts, Adafruit, Protoneer, RafaGS). Wires and pin tags: generated from the net list, cross-checked against wiring.py.</text>'
           + "".join(body) + wire_svg + dots + tag_svg + "</svg>")
    path = os.path.join(WDIR, f"{name}.svg")
    open(path, "w").write(svg)
    return path, len(wires), len(sprites)


if __name__ == "__main__":
    made = []
    for dn in DIAGRAMS:
        p, nw, ns = render(f"art-{dn}", [dn]); made.append(p); print(f"  art-{dn}: {ns} parts, {nw} wires")
    p, nw, ns = render("art-poster", [d for d in DIAGRAMS if d != "3b-turret-shield"], title="Hound — everything wired (as built; 3B alternative on its own sheet)"); made.append(p)
    print(f"  art-poster: {ns} parts, {nw} wires")
    render("art-poster-standalone", [d for d in DIAGRAMS if d != "3b-turret-shield"], embed=True, title="Hound — everything wired (as built)")
    for p in made:  # rasterise (rsvg-convert follows the relative parts/ links from the file's own directory)
        png = p[:-4] + ".png"
        r = subprocess.run(["rsvg-convert", "-o", png, p], capture_output=True, text=True, cwd=WDIR)
        print(f"  {os.path.basename(png)}: {'ok' if r.returncode == 0 else r.stderr[:200]}")
