#!/usr/bin/env python3
"""
wiring_page.py — builds bom-site/wiring.html and bom-site/wiring/gpt-prompt.txt from wiring_diagrams.json (the net list the
diagrams were rendered from) and wiring.json (wiring.py's checks). Run after wiring_diagrams.py.
"""
import html
import json
import os

ROOT = os.path.dirname(os.path.abspath(__file__))
D = json.load(open(os.path.join(ROOT, "wiring_diagrams.json")))
Wj = json.load(open(os.path.join(ROOT, "wiring.json")))
YML = {n: open(os.path.join(ROOT, "bom-site", "wiring", f"{n}.yml")).read() for n in D["diagrams"]}
import yaml
DOCS = {n: yaml.safe_load(YML[n]) for n in D["diagrams"]}

TITLES = {n: DOCS[n]["metadata"]["title"] for n in D["diagrams"]}
E = html.escape


def conn_rows(name):
    doc = DOCS[name]; rows = []
    for row in D["connections"][name]:
        (a, ap), (w, wi), (b, bp) = row[0], row[1], row[-1]
        cab = doc["cables"][w]; col = cab["colors"][int(wi) - 1]
        rows.append((a, ap, w, wi, col, cab["gauge"], b, bp))
    return rows


COL = {"RD": "red", "BK": "black", "YE": "yellow", "BU": "blue", "GN": "green", "WH": "white", "OG": "orange", "BN": "brown", "VT": "violet", "GY": "grey"}

# ── the GPT prompt, generated from the same data ─────────────────────────────────────────────────────────────
P = []
P.append("""You are an electronics documentation engineer. Produce the complete wiring diagram set for "Hound", an indoor search rover (Raspberry Pi 4 + Arduino UNO R4 WiFi + CNC Shield v3 + 4× DRV8825 + 4× NEMA 17 mecanum drive, 3S LiPo, two buck converters, PCA9685 tilt servo, MLX90640 thermal array, 2× VL53L1X ToF, INMP441 mic, 2–3 HLK radars on CP2102 USB-UART adapters, ESP32-S3 WiFi-CSI node, webcam).

HARD RULES — read before drawing anything
1. Use ONLY the connectors, pins and wires listed below. Every pin name is taken from a datasheet or the board silkscreen. Do not add, rename, merge or "helpfully" reroute anything. If something looks wrong, say so in a note; do not fix it silently.
2. Every wire is drawn with BOTH ends labelled "CONNECTOR:pin", its colour and its gauge, exactly as listed.
3. Colour the rails consistently: 11.1 V pack = red, 6.0 V servo rail = orange, 5.0 V rail = yellow, 3.3 V = violet, GND = black, signals = blue/green/white as listed.
4. Do NOT produce pin-level diagrams with an image generator: generated images get pin labels wrong. Produce them as code: a WireViz YAML file per diagram (https://github.com/wireviz/WireViz, `pip install wireviz`, needs Graphviz) rendered with Python, or hand-written SVG. An image generator may be used ONLY for a block-level overview picture with no pin text.
5. Seven diagrams, landscape, one per section below, named exactly as the section headings. Each diagram gets a notes box with the section's NOTES.
6. Before you hand anything over, run the SELF-CHECK at the end and print its results.
""")
for n in D["diagrams"]:
    doc = DOCS[n]
    P.append(f"\n=== DIAGRAM {n}: {TITLES[n]} ===\n")
    P.append("CONNECTORS (pin order is the physical order on the part):")
    for cname, c in doc["connectors"].items():
        P.append(f"  {cname} — {c['type']}")
        P.append("     pins: " + " | ".join(str(p) for p in c["pinlabels"]))
        if c.get("notes"): P.append("     NOTES: " + c["notes"])
    P.append("WIRES:")
    for wname, w in doc["cables"].items():
        P.append(f"  {wname}: {w['gauge']}, {w['length']} m, conductors {', '.join(COL[c] for c in w['colors'])}" + (f" — {w['notes']}" if w.get("notes") else ""))
    P.append("CONNECTIONS (from → wire#/colour → to):")
    for a, ap, w, wi, col, g, b, bp in conn_rows(n):
        P.append(f"  {a}:{ap}  →  {w} #{wi} {COL[col]}  →  {b}:{bp}")

P.append("\n=== PROCEDURES AND WARNINGS (print these on the sheet; they come from the electrical model wiring.py) ===")
for c in Wj["checks"]:
    if c["level"] in ("PROCEDURE", "VERIFY", "WARN"):
        P.append(f"  [{c['level']}] {c['text']}")

P.append("""
=== DECISION ALREADY MADE: which bus drives the PCA9685 ===
AS BUILT = diagram 3A: the Raspberry Pi drives the PCA9685 over I2C-1 (BCM 2/3), 3.3 V logic, VCC = Pi 3V3. The software (turret.py, station.py) is written for this. Diagram 3B (PCA9685 on the CNC Shield's A4/A5, 5 V logic, VCC = shield 5V, driven by the UNO R4) is the ALTERNATIVE, only if the servo misbehaves on 3.3 V PWM; it requires new R4 firmware. Draw both, mark 3A "AS BUILT" and 3B "ALTERNATIVE — NOT WIRED". Never wire both at once: the PCA9685 must never see 5 V pull-ups while its SDA/SCL touch the Pi.

=== SELF-CHECK (run it, print PASS/FAIL per line) ===
1. Every CONNECTOR:pin used in CONNECTIONS exists in that connector's pin list.
2. Each LD2410C and the LD2450 has exactly TWO GND wires: one to WAGO5_N, one to its CP2102 GND. Their VCC/5V comes from WAGO5_P, never from the CP2102's 5V pin.
3. Nothing on the Pi 40-pin header carries 5 V: all I2C/I2S devices are on 3V3 pins; PCA9685 VCC = 3V3 in 3A.
4. The MLX90640 is on BCM 4/5 (i2c3), alone. The two VL53L1X and the PCA9685 are on BCM 2/3 (I2C-1). Addresses on I2C-1: 0x40, 0x29, 0x30 — no clash.
5. Motor bus: WAGO_P → SHIELD_PWR VMOT and WAGO_N → SHIELD_PWR GND, 22 AWG, with the 1000 µF cap noted, stripe to GND.
6. XL4015 OUT− goes to the PCA9685 GND TERMINAL by its own wire (servo return); it is not shared with any signal ground.
7. The E-STOP sits in the pack + lead between the T-plug and WAGO_P; the Pi is on the USB bank, not on the pack.
8. The divider is 47 kΩ WAGO_P → A3, 10 kΩ A3 → WAGO_N; A3 is the shield's CoolEn pin.
9. ESP32-S3 no.3 is fed at its 5V pin from WAGO5_P and its USB port is marked "never while 5V is fed".
10. The shield's four motor headers map X=BL, Y=FL, Z=BR, A=FR; each motor's coil pairs are found with a meter, colours are indicative only.
11. Power-up order is printed: bank → Pi → R4 (USB) → then the pack.
""")
PROMPT = "\n".join(P)
open(os.path.join(ROOT, "bom-site", "wiring", "gpt-prompt.txt"), "w").write(PROMPT)

# ── the page ─────────────────────────────────────────────────────────────────────────────────────────────────
CSS = """
body{margin:0;font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif;color:#1b2430;background:#f6f7f9}
main{max-width:1180px;margin:0 auto;padding:24px 16px 60px}
h1{font-size:28px;margin:0 0 6px}h2{font-size:20px;margin:36px 0 8px;border-bottom:2px solid #d8dde3;padding-bottom:4px}h3{font-size:16px;margin:18px 0 6px}
p,li{max-width:900px}.lead{font-size:17px;color:#3a4652}
.box{background:#fff;border:1px solid #d8dde3;border-radius:8px;padding:14px 16px;margin:12px 0}
.ok{border-left:5px solid #2f9e44}.warn{border-left:5px solid #e67700}.bad{border-left:5px solid #c92a2a}.alt{border-left:5px solid #7048e8}
figure{margin:12px 0;background:#fff;border:1px solid #d8dde3;border-radius:8px;padding:8px;overflow:auto}
figure img{display:block;min-width:900px;width:100%;height:auto}figcaption{font-size:13px;color:#5a6672;padding:6px 4px 0}
table{border-collapse:collapse;width:100%;font-size:13px;background:#fff}th,td{border:1px solid #d8dde3;padding:4px 6px;text-align:left;vertical-align:top}th{background:#eef1f4}
td.c{font-family:ui-monospace,Menlo,monospace;white-space:nowrap}.sw{display:inline-block;width:12px;height:12px;border:1px solid #888;vertical-align:middle;margin-right:4px}
pre{background:#101820;color:#e6ebf0;padding:14px;border-radius:8px;overflow:auto;font-size:12px;max-height:520px}
code{font-family:ui-monospace,Menlo,monospace;background:#e9edf1;padding:0 4px;border-radius:3px}
button{font:inherit;padding:8px 14px;border:1px solid #2a3641;border-radius:6px;background:#172029;color:#fff;cursor:pointer}
details summary{cursor:pointer;font-weight:600;margin:8px 0}
.two{display:grid;grid-template-columns:1fr 1fr;gap:12px}@media(max-width:800px){.two{grid-template-columns:1fr}}
"""
SWATCH = {"RD": "#e03131", "BK": "#111", "YE": "#ffd43b", "BU": "#1c7ed6", "GN": "#2f9e44", "WH": "#fff", "OG": "#f76707", "BN": "#8b5a2b", "VT": "#7048e8", "GY": "#868e96"}

def table(name):
    r = ["<table><tr><th>from</th><th>wire</th><th>colour</th><th>gauge</th><th>to</th></tr>"]
    for a, ap, w, wi, col, g, b, bp in conn_rows(name):
        r.append(f"<tr><td class=c>{E(a)}:{E(str(ap))}</td><td class=c>{E(w)} #{wi}</td><td><span class=sw style='background:{SWATCH[col]}'></span>{COL[col]}</td><td>{E(g)}</td><td class=c>{E(b)}:{E(str(bp))}</td></tr>")
    return "".join(r) + "</table>"

def pins(name):
    r = []
    for cname, c in DOCS[name]["connectors"].items():
        r.append(f"<tr><td class=c>{E(cname)}</td><td>{E(c['type'])}</td><td class=c>{E(' | '.join(str(p) for p in c['pinlabels']))}</td><td>{E(c.get('notes',''))}</td></tr>")
    return "<table><tr><th>id</th><th>part</th><th>pins (physical order)</th><th>notes</th></tr>" + "".join(r) + "</table>"

procs = "".join(f"<li><b>{E(c['id'])}</b> — {E(c['text'])}</li>" for c in Wj["checks"] if c["level"] == "PROCEDURE")
verifs = "".join(f"<li><b>{E(c['id'])}</b> — {E(c['text'])}</li>" for c in Wj["checks"] if c["level"] in ("VERIFY", "WARN"))
S = Wj["summary"]; cnt = S["counts"]

figs = []
for n in D["diagrams"]:
    cls = " class=alt" if n.startswith("3b") else ""
    figs.append(f"""
<h3 id="{n}">{E(TITLES[n])}</h3>
<figure{cls}><a href="wiring/{n}.svg" target="_blank"><img src="wiring/{n}.svg" alt="{E(TITLES[n])}"></a>
<figcaption>Click for the full-size SVG (searchable text). Source: <a href="wiring/{n}.yml">{n}.yml</a> · PNG: <a href="wiring/{n}.png">{n}.png</a></figcaption></figure>
<details><summary>Connections ({len(D['connections'][n])} wires)</summary>{table(n)}</details>
<details><summary>Connector pin lists and notes</summary>{pins(n)}</details>""")

page = f"""<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Hound wiring</title><style>{CSS}</style></head><body><main>
<h1>Hound — wiring</h1>
<p class=lead>Seven harness diagrams generated from one net list, rendered with <a href="https://github.com/wireviz/WireViz">WireViz</a> (open source, Python + Graphviz), and cross-checked by script against the electrical model <code>wiring.py</code>: every load is fed from the rail the model says, every signal link has a wire, the Pi and R4 pins match. The model itself: <b>{cnt['FAIL']} FAIL · {cnt['WARN']} WARN · {cnt['VERIFY']} VERIFY · {cnt['PROCEDURE']} PROCEDURE · {cnt['PASS']} PASS</b>; pack {S['pack_avg']} A avg / {S['pack_peak']} A peak, bank {S['bank_avg']} A avg / {S['bank_peak']} A peak, Pi USB {S['pi_usb_peak']} A of 1.2.</p>

<div class="box ok"><b>Can the PCA9685 be wired straight to the CNC Shield's pins?</b> Yes. The shield breaks out the R4's A4 (SDA) and A5 (SCL) — the R4's primary <code>Wire</code> bus, 5 V logic — plus 5V and GND pins. That is diagram 3B. <b>But the rover is built the other way (3A):</b> the Raspberry Pi drives the PCA9685 over its I2C-1 (BCM 2/3) at 3.3 V, and turret.py / station.py already work that way. Keep 3A. Switch to 3B only if the MG996R jitters or ignores 3.3 V PWM — then the shield's 5 V logic fixes it, and the R4 firmware needs a tilt command (not written yet). Never wire both: a PCA9685 with 5 V pull-ups must not touch the Pi's SDA/SCL.</div>

<div class=box><b>The sensors.</b> The two LD2410C radars each go through their own CP2102 adapter into the Pi's USB hub: only TX, RX and GND on the adapter; power from the 5 V Wagos. The LD2450 (the long one) is the third radar: it tracks up to three moving targets with x/y position and is what turns "someone is 2.1 m away" into "someone is 2.1 m away, 0.4 m to the left". It needs a third CP2102 (on order or skipped) and until then stays unplugged. Thermal array (MLX90640) rides on the tilt bracket beside the webcam and hangs on the Pi's second I2C bus alone, so it can run fast. ToF ×2, mic, PCA9685 on the Pi's first I2C/I2S. Pack side: e-stop → two Wagos → shield, XL4015 (6.0 V servo), LM2596 (5.0 V fan + radars + ESP32 no.3). Pi on its own USB bank.</div>

<h2>Diagrams</h2>
<p>Left-to-right: source → wire (colour, gauge, length) → destination. Every pin name is the part's own silkscreen or datasheet name.</p>
{''.join(figs)}

<h2>Build procedures (from wiring.py)</h2><ul>{procs}</ul>
<h2>Verify before power (VERIFY / WARN)</h2><ul>{verifs}</ul>

<h2>Double-check results</h2>
<div class="box ok">Script cross-check of the diagrams against wiring.py: <b>{'OK — ' + str(sum(len(v) for v in D['connections'].values())) + ' wires, every load fed, every signal wired, Pi BCM and R4 pins identical to the model' if not D['problems'] else 'PROBLEMS: ' + '; '.join(D['problems'])}</b>.</div>
<div class="box warn"><b>Found and fixed while building this page:</b> (1) the pack-voltage divider on A3 was not in wiring.py — added (A3 = the shield's CoolEn pin). (2) wiring.py's microstep note still said 1/16; the frozen v1.0 drive is 1/32 with caps on MS1 + MS3 — corrected. (3) station.py opened the thermal array on I2C-1 while the wiring puts it on i2c3 (BCM 4/5) — station.py now opens bus 3 and falls back to I2C-1. (4) LD2410C pin order confirmed from the Hi-Link manual: 1 TX, 2 RX, 3 OUT, 4 GND, 5 VCC — the silkscreen reads TX RX OUT GND VCC left to right.</div>
<div class="box warn"><b>Still to verify on the bench (cannot be checked from a desk):</b> each I2C module powered alone must show ≤ 3.3 V on SDA; the MG996R must accept 3.3 V PWM (else 3B); the USB bank must hold ≥ 4.8 V at 2.5 A; the CP2102 adapters' silkscreen order (varies by vendor — wire by label, not position).</div>

<h2>Open-source tools for this kind of diagram</h2>
<ul>
<li><a href="https://github.com/wireviz/WireViz">WireViz</a> — what this page uses: YAML in, harness diagram + BOM out; exact by construction. Needs Graphviz.</li>
<li><a href="https://fritzing.org/">Fritzing</a> — breadboard-style pictures of Arduino/Pi builds; good for a photo-like view, weak for pin-accurate harnesses.</li>
<li><a href="https://www.kicad.org/">KiCad</a> — full schematic capture; overkill for wiring, right if this ever becomes a PCB.</li>
<li><a href="https://schemdraw.readthedocs.io/">schemdraw</a> — Python schematic drawing, pure code, no Graphviz.</li>
</ul>

<h2>Or: the prompt for GPT</h2>
<p>Everything above, as one self-contained brief generated from the same net list (so it cannot drift from the diagrams). It tells GPT to produce WireViz YAML or SVG by code, not an image-generator picture, because generated images get pin text wrong. <a href="wiring/gpt-prompt.txt" download>Download gpt-prompt.txt</a> · <button onclick="navigator.clipboard.writeText(document.getElementById('pr').textContent).then(()=>this.textContent='copied')">copy prompt</button></p>
<pre id=pr>{E(PROMPT)}</pre>
</main></body></html>"""
open(os.path.join(ROOT, "bom-site", "wiring.html"), "w").write(page)
print(f"wiring.html ({len(page)//1024} kB) and gpt-prompt.txt ({len(PROMPT)//1024} kB) written")
