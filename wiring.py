#!/usr/bin/env python3
"""
wiring.py — the rover's electrical netlist and its checks. Source of truth for
every wire, rail, connector and signal; bom.json prose must agree with THIS.

Run:  python3 wiring.py        (exit 1 on any FAIL; writes wiring.json for build.py)

Every number below is either a datasheet figure (DS), a listing figure (LISTING),
an output of drivetrain.py (DT) or an allocation (ALLOC). Nothing is a guess.
"""
import json, sys

# ── Reference data ────────────────────────────────────────────────────────────
OHM_PER_M = {14: 0.00828, 16: 0.0132, 18: 0.0210, 20: 0.0333, 22: 0.0530, 24: 0.0842, 26: 0.134, 28: 0.213}  # copper, 20 °C
AMPACITY  = {14: 32, 16: 22, 18: 16, 20: 11, 22: 7, 24: 3.5, 26: 2.2, 28: 1.4}   # chassis wiring, short runs, free air
CONNECTOR_A = {"T-plug (Deans)": 50, "Wago 221-415": 32, "screw terminal 5.08": 10, "Dupont 2.54": 2.0,
               "JST-XH 2.54": 3.0, "JST 1.25": 1.0, "USB-A": 1.5, "USB-C": 3.0, "header 2.54": 2.0}
V_DROP_MAX = 0.03           # 3 % of rail per segment
BUCK_EFF = 0.85             # XL4015 / LM2596 at these ratios, DS typical

# ── Rails ─────────────────────────────────────────────────────────────────────
# v_min is the worst case the loads see (pack sagged / buck ripple); v_max the best case (pack fresh).
RAILS = {
    "PACK":     dict(desc="HOOVO 3S 2200 mAh 80C, T-plug",        v_nom=11.1, v_min=10.5, v_max=12.6, i_cont=44.0, i_peak=100.0, src=None,
                     note="2200 mAh × 20C = 44 A continuous, taken as the honest figure, not 80C. (LISTING/ALLOC)"),
    "V_SERVO":  dict(desc="XL4015 trimmed to 6.0 V",              v_nom=6.0,  v_min=5.8,  v_max=6.2,  i_cont=4.0,  i_peak=5.0,   src="PACK",
                     note="5 A module derated to 4 A continuous with the heatsink. (LISTING)"),
    "V5_LM":    dict(desc="LM2596 trimmed to 5.0 V",              v_nom=5.0,  v_min=4.9,  v_max=5.1,  i_cont=2.0,  i_peak=3.0,   src="PACK",
                     note="3 A module, 2 A continuous without a fan on it. (LISTING)"),
    "V5_BANK":  dict(desc="USB power bank → Pi USB-C",            v_nom=5.0,  v_min=4.75, v_max=5.25, i_cont=3.0,  i_peak=3.0,   src=None,
                     note="Must be a genuine 5 V / 3 A bank; 2.4 A banks fail this file. (ALLOC)"),
    "V5_PI_USB":dict(desc="Pi 4 downstream USB (4 ports, shared)", v_nom=5.0,  v_min=4.75, v_max=5.25, i_cont=1.2,  i_peak=1.2,   src="V5_BANK",
                     note="Pi 4 shares 1.2 A across all four ports (DS). Pi 5 defaults to 0.6 A unless usb_max_current_enable=1."),
    "V3_PI":    dict(desc="Pi 3.3 V header pin",                  v_nom=3.3,  v_min=3.2,  v_max=3.4,  i_cont=0.5,  i_peak=0.8,   src="V5_BANK",
                     note="Pi 4 3.3 V rail budget for HATs/peripherals ≈ 0.5 A. (DS)"),
}

# ── Loads: what hangs on each rail ────────────────────────────────────────────
# (name, rail, vin_min, vin_max, i_avg, i_peak, connector, source-of-number)
LOADS = [
    ("4× DRV8825 + JK42HS40 motors (bus side)", "PACK",     8.2, 45.0, 1.96, 4.00, "screw terminal 5.08", "DT: 20.5 W at 10.5 V cruise; 4 A allocated for a ramp burst"),
    ("XL4015 input",                            "PACK",     4.0, 38.0, None, None, "screw terminal 5.08", "LISTING; current computed from its loads"),
    ("LM2596 input",                            "PACK",     4.5, 40.0, None, None, "screw terminal 5.08", "LISTING; current computed from its loads; needs Vin ≥ Vout + 1.5"),
    ("MG996R tilt servo via PCA9685 V+",        "V_SERVO",  4.8, 7.2,  0.30, 2.50, "header 2.54",         "DS: stall ≈ 2.5 A at 6 V; pan servo disconnected"),
    ("40 mm fan on the driver heatsinks",       "V5_LM",    4.5, 5.5,  0.15, 0.20, "Dupont 2.54",         "LISTING"),
    ("LD2410C radar",                           "V5_LM",    4.5, 5.5,  0.08, 0.10, "JST 1.25",            "DS: ≤ 80 mA"),
    ("LD2450 radar",                            "V5_LM",    4.5, 5.5,  0.10, 0.20, "JST 1.25",            "DS: ≤ 200 mA"),
    ("Raspberry Pi 4 itself",                   "V5_BANK",  4.75, 5.25, 0.70, 1.20, "USB-C",              "DS: idle 0.6 A, loaded 1.2 A without USB peripherals"),
    ("Webcam (C920-class, 1080p)",              "V5_PI_USB",4.75, 5.25, 0.25, 0.50, "USB-A",              "DS: 500 mA descriptor, ~250 typical"),
    ("UNO R4 WiFi + shield logic",              "V5_PI_USB",4.75, 5.25, 0.15, 0.20, "USB-A",              "DS: radio off"),
    ("ESP32-S3 #1 radar bridge (USB, WiFi off)","V5_PI_USB",4.75, 5.25, 0.15, 0.35, "USB-A",              "DS"),
    ("MLX90640 thermal array",                  "V3_PI",    3.0,  3.6,  0.023, 0.025, "header 2.54",      "DS: 23 mA"),
    ("VL53L1X ToF front",                       "V3_PI",    2.6,  3.6,  0.02, 0.04, "header 2.54",        "DS"),
    ("VL53L1X ToF rear",                        "V3_PI",    2.6,  3.6,  0.02, 0.04, "header 2.54",        "DS"),
    ("PCA9685 logic (VCC)",                     "V3_PI",    2.3,  5.5,  0.01, 0.01, "header 2.54",        "DS"),
    ("INMP441 microphone",                      "V3_PI",    1.8,  3.6,  0.0015, 0.002, "header 2.54",     "DS"),
    ("SCD41 CO2 (optional)",                    "V3_PI",    2.4,  5.5,  0.018, 0.205, "header 2.54",      "DS: 205 mA peak during a measurement"),
]

# ── Wire segments: (name, awg, length_m, connector at the far end) — current is derived from the loads
WIRES = [
    ("pack lead: HOOVO T-plug → OliRC extension → e-stop pair",     14, 0.30, "T-plug (Deans)",   "PACK_TOTAL"),
    ("Deans pigtail → 5-way Wagos (+ and −)",                       14, 0.15, "Wago 221-415",     "PACK_TOTAL"),
    ("Wago → CNC Shield VMOT/GND terminal",                         22, 0.15, "screw terminal 5.08", "PACK:4× DRV8825 + JK42HS40 motors (bus side)"),
    ("Wago → XL4015 IN",                                            22, 0.15, "screw terminal 5.08", "XL_IN"),
    ("Wago → LM2596 IN",                                            22, 0.15, "screw terminal 5.08", "LM_IN"),
    ("XL4015 OUT → PCA9685 V+ / GND terminal",                      22, 0.12, "screw terminal 5.08", "RAIL:V_SERVO"),
    ("LM2596 OUT → 5-way Wagos → fan, LD2410C, LD2450",             22, 0.30, "Wago 221-415",     "RAIL:V5_LM"),
    ("shield driver socket → 4-pin motor cable → motor (per phase)", 26, 0.40, "Dupont 2.54",      "PHASE"),
    ("bank → Pi USB-C cable",                                       24, 0.30, "USB-C",            "RAIL:V5_BANK"),
    ("Pi USB-A → webcam (captive cable, 1.5 m)",                    28, 1.50, "USB-A",            "PACK_LOAD:Webcam (C920-class, 1080p)"),
    ("Pi USB-A → UNO R4 USB-C",                                     28, 0.30, "USB-A",            "PACK_LOAD:UNO R4 WiFi + shield logic"),
    ("Pi USB-A → ESP32-S3 #1 USB-C",                                28, 0.30, "USB-A",            "PACK_LOAD:ESP32-S3 #1 radar bridge (USB, WiFi off)"),
]

# ── Signals: (driver, pin(s), V_out_high, receiver, pin(s), V_in_max, V_ih_min, bus)
SIGNALS = [
    ("UNO R4 (5 V logic)", "D2/D5 D3/D6 D4/D7 D12/D13 STEP/DIR, D8 EN", 5.0, "DRV8825 ×4", "STEP DIR nENABLE", 5.25, 2.2, "R4"),
    ("LD2410C TX (3.3 V)", "TX", 3.3, "ESP32-S3 #1", "GPIO 18 (UART1 RX)", 3.6, 2.4, "ESP1"),
    ("ESP32-S3 #1 GPIO 17 (UART1 TX)", "GPIO 17", 3.3, "LD2410C", "RX", 3.6, 2.0, "ESP1"),
    ("LD2450 TX (3.3 V)", "TX", 3.3, "ESP32-S3 #1", "GPIO 16 (UART2 RX)", 3.6, 2.4, "ESP1"),
    ("ESP32-S3 #1 GPIO 15 (UART2 TX)", "GPIO 15", 3.3, "LD2450", "RX", 3.6, 2.0, "ESP1"),
    ("Pi I2C-1 (BCM 2/3, pull-ups 3.3 V)", "SDA/SCL", 3.3, "PCA9685 0x40, VL53L1X 0x29→0x30, SCD41 0x62", "SDA/SCL", 3.6, 2.3, "I2C1"),
    ("Pi i2c3 (BCM 4/5, pull-ups 3.3 V)", "SDA/SCL", 3.3, "MLX90640 0x33", "SDA/SCL", 3.6, 2.3, "I2C3"),
    ("Pi BCM 22 / 27", "XSHUT out", 3.3, "VL53L1X front / rear", "XSHUT (pull-up to VIN = 3.3)", 3.6, 1.2, "GPIO"),
    ("Pi I2S (BCM 18/19/20)", "BCLK/LRCLK/DIN", 3.3, "INMP441", "SCK/WS/SD", 3.6, 2.3, "I2S"),
    ("Pi ↔ UNO R4", "USB CDC", 5.0, "UNO R4", "USB", 5.25, 0, "USB"),
    ("Pi ↔ ESP32-S3 #1", "USB CDC (UART0 bridge)", 5.0, "ESP32-S3 #1", "USB", 5.25, 0, "USB"),
    ("ESP32-S3 #2 and #3, OFF the rover (doorway / far wall), RuView receiver nodes", "WiFi UDP → SINK_IP:5005", 0, "Pi hotspot on the rover (the CSI transmitter)", "wlan0, 2.4 GHz", 0, 0, "WIFI"),
]

PI_BCM = {"I2C1 SDA": 2, "I2C1 SCL": 3, "i2c3 SDA": 4, "i2c3 SCL": 5, "I2S BCLK": 18, "I2S LRCLK": 19, "I2S DIN": 20, "XSHUT front": 22, "XSHUT rear": 27}
R4_PINS = {"X STEP": 2, "Y STEP": 3, "Z STEP": 4, "X DIR": 5, "Y DIR": 6, "Z DIR": 7, "ENABLE": 8, "A STEP (jumper SpnEn)": 12, "A DIR (jumper SpnDir)": 13}
R4_RESERVED_BY_SHIELD = {9: "X limit", 10: "Y limit", 11: "Z limit", 14: "A0 abort", 15: "A1 hold", 16: "A2 resume", 17: "A3 coolant"}
ESP1_GPIO = {"UART1 TX": 17, "UART1 RX": 18, "UART2 TX": 15, "UART2 RX": 16}
ESP32S3_AVOID = {0: "strap", 3: "strap", 45: "strap", 46: "strap", 19: "USB D-", 20: "USB D+", 43: "UART0 TX (console)", 44: "UART0 RX (console)"}
I2C_BUSES = {
    "I2C1": [("PCA9685", 0x40, 1000), ("VL53L1X front (re-addressed)", 0x30, 400), ("VL53L1X rear", 0x29, 400), ("SCD41 (optional)", 0x62, 100)],
    "I2C3": [("MLX90640", 0x33, 1000)],
}

# ── Checks ────────────────────────────────────────────────────────────────────
R = []                      # (level, id, text)
def out(level, cid, text): R.append((level, cid, text))
PASS, WARN, FAIL, VERIFY, PROC = "PASS", "WARN", "FAIL", "VERIFY", "PROCEDURE"

loads_on = lambda rail: [l for l in LOADS if l[1] == rail and l[4] is not None]
def rail_sum(rail, k):      # k = 4 avg, 5 peak
    return sum(l[k] for l in loads_on(rail))

# 1. buck input currents, computed from their output loads
def buck_in(rail_out, k, v_in):
    return RAILS[rail_out]["v_nom"] * rail_sum(rail_out, k) / (BUCK_EFF * v_in)
XL_IN_AVG,  XL_IN_PK  = buck_in("V_SERVO", 4, RAILS["PACK"]["v_nom"]), buck_in("V_SERVO", 5, RAILS["PACK"]["v_min"])
LM_IN_AVG,  LM_IN_PK  = buck_in("V5_LM", 4, RAILS["PACK"]["v_nom"]),   buck_in("V5_LM", 5, RAILS["PACK"]["v_min"])
MOT = next(l for l in LOADS if l[0].startswith("4× DRV8825"))
PACK_AVG = MOT[4] + XL_IN_AVG + LM_IN_AVG
PACK_PK  = MOT[5] + XL_IN_PK + LM_IN_PK
PI3_AVG_AT5 = rail_sum("V3_PI", 4) * 3.3 / (0.9 * 5.0);  PI3_PK_AT5 = rail_sum("V3_PI", 5) * 3.3 / (0.9 * 5.0)
BANK_AVG = rail_sum("V5_BANK", 4) + rail_sum("V5_PI_USB", 4) + PI3_AVG_AT5
BANK_PK  = rail_sum("V5_BANK", 5) + rail_sum("V5_PI_USB", 5) + PI3_PK_AT5

CURRENT = {"PACK_TOTAL": (PACK_AVG, PACK_PK), "XL_IN": (XL_IN_AVG, XL_IN_PK), "LM_IN": (LM_IN_AVG, LM_IN_PK),
           "RAIL:V_SERVO": (rail_sum("V_SERVO", 4), rail_sum("V_SERVO", 5)), "RAIL:V5_LM": (rail_sum("V5_LM", 4), rail_sum("V5_LM", 5)),
           "RAIL:V5_BANK": (BANK_AVG, BANK_PK), "PHASE": (1.5 * 0.71, 1.5),
           "PACK:4× DRV8825 + JK42HS40 motors (bus side)": (MOT[4], MOT[5])}
for l in LOADS: CURRENT[f"PACK_LOAD:{l[0]}"] = (l[4] or 0, l[5] or 0)

# 2. every load inside its rail's voltage window (worst case both ends)
for name, rail, vmin, vmax, ia, ip, conn, src in LOADS:
    r = RAILS[rail]
    if r["v_min"] < vmin or r["v_max"] > vmax:
        out(FAIL, "V-window", f"{name}: rail {rail} spans {r['v_min']}–{r['v_max']} V but the part accepts {vmin}–{vmax} V ({src})")
    else:
        out(PASS, "V-window", f"{name}: {r['v_min']}–{r['v_max']} V inside {vmin}–{vmax} V")

# 3. rail current budgets
budget = {"PACK": (PACK_AVG, PACK_PK), "V_SERVO": (rail_sum("V_SERVO", 4), rail_sum("V_SERVO", 5)),
          "V5_LM": (rail_sum("V5_LM", 4), rail_sum("V5_LM", 5)), "V5_BANK": (BANK_AVG, BANK_PK),
          "V5_PI_USB": (rail_sum("V5_PI_USB", 4), rail_sum("V5_PI_USB", 5)), "V3_PI": (rail_sum("V3_PI", 4), rail_sum("V3_PI", 5))}
for rail, (ia, ip) in budget.items():
    r = RAILS[rail]; ua, up = ia / r["i_cont"], ip / r["i_peak"]
    lvl = FAIL if up > 1.0 or ua > 1.0 else (WARN if up > 0.85 else PASS)
    out(lvl, "I-budget", f"{rail} ({r['desc']}): avg {ia:.2f} A of {r['i_cont']} A ({ua:.0%}), peak {ip:.2f} A of {r['i_peak']} A ({up:.0%})")
out(PASS if RAILS["PACK"]["v_min"] >= RAILS["V5_LM"]["v_nom"] + 1.5 else FAIL, "dropout", f"LM2596 needs Vin ≥ {RAILS['V5_LM']['v_nom'] + 1.5} V; pack minimum {RAILS['PACK']['v_min']} V")
out(PASS if RAILS["PACK"]["v_min"] >= RAILS["V_SERVO"]["v_nom"] + 1.0 else FAIL, "dropout", f"XL4015 needs Vin ≥ {RAILS['V_SERVO']['v_nom'] + 1.0} V; pack minimum {RAILS['PACK']['v_min']} V")
hours = 2.2 * 0.8 / PACK_AVG
out(PASS if hours * 60 >= 30 else WARN, "endurance", f"pack draw avg {PACK_AVG:.2f} A, peak {PACK_PK:.2f} A → {hours*60:.0f} min per 2200 mAh pack (80 % usable)")

# 4. wire ampacity, voltage drop, connector rating
for name, awg, length, conn, key in WIRES:
    ia, ip = CURRENT[key]
    v_ref = RAILS["PACK"]["v_nom"] if key.startswith(("PACK", "XL_IN", "LM_IN")) else (6.0 if "SERVO" in key else 5.0)
    if key == "PHASE": v_ref = RAILS["PACK"]["v_nom"]
    drop = ip * OHM_PER_M[awg] * length * 2            # out and back
    amp = AMPACITY[awg]; cr = CONNECTOR_A[conn]
    lvl = PASS
    if ip > amp or ip > cr: lvl = FAIL
    elif ip > 0.8 * amp or ip > 0.8 * cr or drop > V_DROP_MAX * v_ref: lvl = WARN
    out(lvl, "wire", f"{name}: {awg} AWG × {length} m, peak {ip:.2f} A (ampacity {amp} A, {conn} {cr} A), round-trip drop {drop*1000:.0f} mV = {drop/v_ref:.1%}")

# 5. logic levels
for drv, dp, vo, rcv, rp, vmax, vih, bus in SIGNALS:
    if bus == "WIFI": out(PASS, "level", f"{drv} → {rcv}: radio link, no wire"); continue
    if vo > vmax: out(FAIL, "level", f"{drv} {dp} drives {vo} V into {rcv} {rp} rated {vmax} V max")
    elif vo < vih: out(FAIL, "level", f"{drv} {dp} high {vo} V below {rcv} V_IH {vih} V")
    else: out(PASS, "level", f"{drv} {dp} → {rcv} {rp}: {vo} V out, {vih}–{vmax} V accepted")

# 6. pin uniqueness
def unique(name, table, avoid=None):
    seen = {}
    for k, v in table.items():
        if v in seen: out(FAIL, "pins", f"{name}: pin {v} used by both '{seen[v]}' and '{k}'")
        seen[v] = k
        if avoid and v in avoid: out(FAIL, "pins", f"{name}: pin {v} ('{k}') is {avoid[v]}")
    out(PASS, "pins", f"{name}: {len(table)} pins, all distinct" + (f", none on {sorted(avoid)}" if avoid else ""))
unique("Pi BCM", PI_BCM); unique("UNO R4 / shield", R4_PINS, R4_RESERVED_BY_SHIELD); unique("ESP32-S3 #1", ESP1_GPIO, ESP32S3_AVOID)

# 7. I2C addresses and bus speed
for bus, devs in I2C_BUSES.items():
    addrs = [a for _, a, _ in devs]
    dup = {a for a in addrs if addrs.count(a) > 1}
    if dup: out(FAIL, "i2c", f"{bus}: address clash at {[hex(a) for a in dup]}")
    speed = min(s for _, _, s in devs)
    out(PASS, "i2c", f"{bus}: {', '.join(f'{n} {hex(a)}' for n, a, _ in devs)} — no clashes; bus speed limited to {speed} kHz by the slowest part")
out(VERIFY, "i2c", "Before connecting SDA/SCL: power each I2C module alone and meter SDA to GND — it must read ≤ 3.3 V. A module whose pull-ups go to 5 V goes on 3.3 V power or not on the Pi.")

# 8. USB port count and Pi 5 caveat
usb_loads = loads_on("V5_PI_USB")
out(PASS if len(usb_loads) <= 4 else FAIL, "usb", f"Pi USB: {len(usb_loads)} devices on 4 ports ({', '.join(l[0].split(' (')[0] for l in usb_loads)})")
out(WARN, "usb", "Pi 5 only: default 600 mA USB cap → set usb_max_current_enable=1, or use the Pi 4 this file assumes.")

# 9. grounds: attachment points between the bank island (Pi, R4 logic, ESP32 #1, PCA9685 logic) and the pack ground
branches = {"shield GND terminal (via R4 USB GND)": MOT[5] * OHM_PER_M[22] * 0.15,
            "PCA9685 GND (via XL4015 OUT− / IN−)": XL_IN_PK * OHM_PER_M[22] * 0.15,
            "radar GND (via LM2596 OUT− / IN−)": LM_IN_PK * OHM_PER_M[22] * 0.15}
dv = max(branches.values()) - min(branches.values()); i_circ = dv / 0.4
out(PASS if dv < 0.1 else FAIL, "ground", f"star = Wago negative. Peak drop per branch: " + ", ".join(f"{k} {v*1000:.0f} mV" for k, v in branches.items()) +
    f" → ≤ {dv*1000:.0f} mV between attachment points, ~{i_circ*1000:.0f} mA circulating through USB grounds (limit 100 mV)")
out(PROC, "ground", "Servo return: PCA9685 V+ GND terminal → XL4015 OUT− (its own wire). Motor return: shield GND terminal → Wago. Neither ever through a board GND pin or a USB cable.")

# 10. things a checker cannot check but a build must do
out(PROC, "sequence", "Power-up: bank → Pi → R4 (USB) FIRST, then the pack at the T-plug. DRV8825 nENABLE floats LOW = enabled; with VMOT alone four motors sit at full holding current with nothing commanding them.")
out(PROC, "vref", "Read the sense resistor on one driver: R100 → Vref = 0.75 V for 1.5 A; R200 → 1.50 V. Set all four with the multimeter, motors unplugged, before any motor is connected.")
out(PROC, "microstep", "DRV8825 1/16 = M2 only → ONE cap on MS3 under each driver, MS1/MS2 open. Four caps, plus the D12 and D13 jumpers on the A header = six jumpers total. Caps go on before the drivers.")
out(PROC, "phases", "Motor coil pairs by multimeter: the two leads that show ~2 Ω are one coil. A coil split across the 2B/2A–1A/1B header halves makes a motor buzz and not turn.")
out(WARN, "protection", "No fuse on the pack and no cell alarm (declined). A 2200 mAh 80C pack delivers >70 A into a short; the T-plug is a disconnect, not protection. Listed under Safety as reviewer-recommended.")
out(WARN, "connector", f"Motor phases run 1.5 A through Dupont 2.54 contacts rated {CONNECTOR_A['Dupont 2.54']} A — inside rating but the crimp quality is the margin. A contact that heats in the wheels-up test gets re-crimped or soldered.")
out(VERIFY, "bank", "Load-test the bank at 2.5 A for 60 s with the meter on the Pi's 5 V pin: below 4.8 V the bank is not a 3 A bank.")
out(PROC, "csi-nodes", "ESP32 #2 and #3 are NOT on the rover. Walleye's csi_rx firmware writes CSI to Serial (a wire to the Pi), and the RuView firmware's nodes are receivers of the AP's frames — so the transmitter is the Pi's own 2.4 GHz hotspot on the rover, and the two nodes sit at the doorway and the far wall on any USB power, streaming CSI back over that same WiFi as UDP. Two bistatic links through two walls, zero rover wiring, nothing on the Pi's USB budget.")
out(PASS, "bulk-cap", "1000 µF 25 V across VMOT at the shield terminal (consumables) — protects the drivers from the pack lead's inductance on connect.")

# 11. voltage chain: bank → cable → Pi → USB port → the farthest device (webcam on its captive 1.5 m cable)
V_BANK_LOADED = 4.90                                      # requirement on the bank at 2.5 A (VERIFY 'bank')
drop_bank_cable = BANK_PK * OHM_PER_M[24] * 0.30 * 2
v_pi = V_BANK_LOADED - drop_bank_cable
v_port = v_pi - 0.05                                      # Pi 4 USB power switch
cam = next(l for l in LOADS if l[0].startswith("Webcam"))
v_cam = v_port - cam[5] * OHM_PER_M[28] * 1.5 * 2
v_cam_typ = v_port - cam[4] * OHM_PER_M[28] * 1.5 * 2
out(PASS if v_pi > 4.63 + 0.10 else FAIL, "V-chain", f"Pi input {v_pi:.2f} V from a bank holding {V_BANK_LOADED} V under load through a 24 AWG × 0.3 m cable; the Pi's under-voltage warning is 4.63 V")
out(WARN if v_cam < 4.75 else PASS, "V-chain", f"webcam sees {v_cam:.2f} V at its 500 mA descriptor ({v_cam_typ:.2f} V at a typical 250 mA) through its own captive 1.5 m cable; USB floor 4.75 V, most cameras run to ~4.4 V. If it drops out at 1080p, run 720p — its cable cannot be shortened")
bad = BANK_PK * OHM_PER_M[28] * 1.0 * 2
out(WARN, "V-chain", f"A 1 m 28 AWG phone cable to the Pi would drop {bad:.2f} V → {V_BANK_LOADED - bad:.2f} V at the Pi = brownout. The bank cable is a spec: ≤ 0.3 m with ≥ 24 AWG power conductors (any '3 A fast-charge' cable)")

# 12. things that turn a PASS into a FAIL if someone forgets them
usb_wifi = rail_sum("V5_PI_USB", 5) - 0.35 + 0.50
out(PROC, "usb", f"ESP32-S3 #1 firmware must call WiFi.mode(WIFI_OFF): with its radio on, Pi USB peak is {usb_wifi:.2f} A of 1.2 A — the port limiter trips and takes the R4's power and serial link with it")
out(WARN, "enable", "DRV8825 nENABLE has an internal pull-down: during the R4's ~1 s reset window (boot, watchdog, sketch upload) D8 floats and all four drivers are ENABLED at full holding current. Add a 10 kΩ pull-up from the shield's EN pin to its 5 V header (consumables). The R4-unpowered case is still the power-up order")
out(VERIFY, "i2c3", "BCM 4/5 have NO on-board I2C pull-ups (BCM 2/3 have 1.8 kΩ). The MLX90640 module must carry its own, or add 4.7 kΩ from SDA and SCL to 3.3 V (consumables). And w1-gpio (1-Wire) defaults to BCM 4 — leave that overlay off")
out(VERIFY, "servo-pwm", "PCA9685 VCC is 3.3 V, so the tilt servo gets 3.3 V PWM. MG996R clones normally accept it; if the servo jitters or ignores commands, that is the level. Do NOT raise VCC to 5 V — the board's I2C pull-ups follow VCC and would put 5 V on the Pi's SDA/SCL. A 74HCT125 buffer fixes it")
out(WARN, "connector", f"Tilt servo stall {rail_sum('V_SERVO', 5):.1f} A through the PCA9685's 2.54 mm channel header (rated {CONNECTOR_A['header 2.54']} A). Momentary, and how every servo board works; keep stalls short with tilt limits in software")
out(PASS, "wago", "Wago 221-415 accepts 0.14–4 mm² (24–12 AWG), solid or fine-stranded: the 14 AWG pigtail and the 22 AWG branches both land in it without ferrules")

# 13. pass 3 — the paths a schematic hides
radar_ret = sum(l[4] for l in LOADS if "radar" in l[0])
out(PROC, "radar-gnd", f"Each radar's GND pin gets TWO wires: one to the LM2596 OUT− (its power return) and the cable's GND to ESP32 #1 (signal reference). With only the cable GND, the radars' {radar_ret*1000:.0f} mA returns through ESP32 #1 → Pi → R4 USB → shield → Wago: {radar_ret*0.4*1000:.0f} mV of ground shift on every serial link. That is the exact Ceres fault")
out(PROC, "lm-dist", "LM2596 OUT feeds three loads (fan, LD2410C, LD2450): four conductors per polarity, so two MORE 5-way Wagos (four of the pack of ten used) or a soldered splice. Never daisy-chain through a load's connector")
out(PROC, "driver-orient", "DRV8825 into the shield socket with its EN pin over the socket's EN label (the trimpot ends up toward the shield's power terminal on genuine Pololu layouts; clones vary — go by the label). Backwards = dead driver on power-up, no warning")
out(PROC, "cap-polarity", "1000 µF electrolytic across VMOT: stripe = negative, to the GND terminal. Reversed, it vents on the first power-up")
out(VERIFY, "bank-cable", "If the bank's output is USB-C and the Pi 4 is an early board (pre-2020, rev 1.1), an e-marked C-to-C cable will not power it — use an A-to-C cable or a plain C-to-C. Later Pi 4s and all Pi 5s are fine")
out(PROC, "fan-rail", "The 40 mm fan must be a 5 V fan for the LM2596 rail. A 12 V fan goes on the pack side (Wago +/−, 11.1 V nominal) instead — check the label before it is wired")

# ── Report ────────────────────────────────────────────────────────────────────
order = {FAIL: 0, WARN: 1, VERIFY: 2, PROC: 3, PASS: 4}
counts = {k: sum(1 for l, _, _ in R if l == k) for k in order}
print(f"WIRING CHECK — {len(LOADS)} loads, {len(WIRES)} wire segments, {len(SIGNALS)} signal links\n{'='*100}")
for lvl, cid, text in sorted(R, key=lambda r: (order[r[0]], r[1])):
    print(f"  {lvl:9s} {cid:10s} {text}")
print(f"\n  {counts[FAIL]} FAIL · {counts[WARN]} WARN · {counts[VERIFY]} VERIFY · {counts[PROC]} PROCEDURE · {counts[PASS]} PASS")
print(f"  pack: {PACK_AVG:.2f} A avg / {PACK_PK:.2f} A peak · bank: {BANK_AVG:.2f} A avg / {BANK_PK:.2f} A peak · Pi USB: {budget['V5_PI_USB'][1]:.2f} A peak of 1.2")

json.dump(dict(
    rails=[dict(id=k, **v) for k, v in RAILS.items()],
    loads=[dict(name=n, rail=r, vin=[a, b], i_avg=ia, i_peak=ip, connector=c, source=s) for n, r, a, b, ia, ip, c, s in LOADS],
    wires=[dict(name=n, awg=a, length_m=l, connector=c, i_avg=round(CURRENT[k][0], 2), i_peak=round(CURRENT[k][1], 2)) for n, a, l, c, k in WIRES],
    signals=[dict(driver=d, pins=dp, v_out=vo, receiver=r, rpins=rp, v_in_max=vm, v_ih=vih, bus=b) for d, dp, vo, r, rp, vm, vih, b in SIGNALS],
    checks=[dict(level=l, id=c, text=t) for l, c, t in sorted(R, key=lambda r: (order[r[0]], r[1]))],
    summary=dict(pack_avg=round(PACK_AVG, 2), pack_peak=round(PACK_PK, 2), bank_avg=round(BANK_AVG, 2), bank_peak=round(BANK_PK, 2),
                 pi_usb_peak=round(budget["V5_PI_USB"][1], 2), minutes=round(hours * 60), v_pi=round(v_pi, 2), v_cam=round(v_cam, 2),
                 n_loads=len(LOADS), n_wires=len(WIRES), n_signals=len(SIGNALS), counts=counts),
), open("wiring.json", "w"), indent=1, ensure_ascii=False)
sys.exit(1 if counts[FAIL] else 0)
