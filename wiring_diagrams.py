#!/usr/bin/env python3
"""
wiring_diagrams.py — Hound harness diagrams, generated (not drawn) from one net list, rendered with WireViz + Graphviz,
and cross-checked against wiring.py so a diagram can never disagree with the electrical model.

    venv/bin/python wiring_diagrams.py            # writes bom-site/wiring/*.yml, *.svg, *.png, wiring_diagrams.json, and bom-site/wiring.html

Every connector pin below comes from a datasheet or the board silkscreen (source in the connector's notes). Every wire
comes from wiring.py's WIRES / LOADS / SIGNALS tables. The cross-check at the bottom fails the build if a load, a
signal link, or a pin in wiring.py has no wire here — or if this file invents one that wiring.py does not know.
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from contextlib import redirect_stdout

import yaml

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "bom-site", "wiring")
os.makedirs(OUT, exist_ok=True)

# ── the truth: wiring.py's tables (it prints and exits; capture both) ────────────────────────────────────────
os.chdir(ROOT)
src = open(os.path.join(ROOT, "wiring.py")).read().replace("sys.exit(1 if counts[FAIL] else 0)", "")
W = {"__file__": os.path.join(ROOT, "wiring.py"), "__name__": "wiring_model"}
with redirect_stdout(io.StringIO()):
    exec(compile(src, "wiring.py", "exec"), W)
if W["counts"][W["FAIL"]]:
    sys.exit("wiring.py reports a FAIL — fix the model before drawing it")
LOADS, WIRES, SIGNALS, PI_BCM, R4_PINS = W["LOADS"], W["WIRES"], W["SIGNALS"], W["PI_BCM"], W["R4_PINS"]
CHECKS = json.load(open(os.path.join(ROOT, "wiring.json")))["checks"]


def C(type_, pins, notes=None, **kw):
    d = dict(type=type_, pinlabels=list(pins))
    if notes: d["notes"] = notes
    d.update(kw); return d


def B(gauge, length, colors, notes=None):
    d = dict(gauge=f"{gauge} AWG", length=length, colors=list(colors), category="bundle")
    if notes: d["notes"] = notes
    return d


def link(*hops):
    """link(('CONN', 'pin'), ('CABLE', 1), ('CONN2', 'pin2'), ...) → one WireViz connection row."""
    return [{name: [pin]} for name, pin in hops]


# ── shared connector definitions (pin order = silkscreen / datasheet order) ──────────────────────────────────
WAGO_P = C("Wago 221-415 5-way — PACK + (11.1 V)", ["pigtail +", "shield VMOT", "XL4015 IN+", "LM2596 IN+", "47k divider"],
           "Lever nut, 24–12 AWG. Slot 1 takes the 14 AWG pigtail, the rest 22 AWG. This and its twin are the ONLY pack-side splices.")
WAGO_N = C("Wago 221-415 5-way — PACK − = STAR GROUND", ["pigtail −", "shield GND", "XL4015 IN−", "LM2596 IN−", "10k divider"],
           "Every return comes back here on its own wire. Never through a board GND pin, never through a USB cable.")
WAGO5_P = C("Wago 221-415 5-way — 5 V rail +", ["LM2596 OUT+", "LD2410C LEFT VCC", "LD2410C RIGHT VCC", "LD2450 5V", "ESP32-S3 no.3 5V"],
            "Feeds the four sensor loads; the fan takes its own wire straight off the LM2596 OUT terminal.")
WAGO5_N = C("Wago 221-415 5-way — 5 V rail −", ["LM2596 OUT−", "LD2410C LEFT GND", "LD2410C RIGHT GND", "LD2450 GND", "ESP32-S3 no.3 GND"],
            "Power returns for the sensors. Each radar ALSO grounds to its CP2102 (signal reference): two GND wires per radar.")
XL4015 = C("XL4015 5 A buck — trim OUT to 6.0 V", ["IN+", "IN−", "OUT+", "OUT−"],
           "Screw terminals. Set 6.00 V on the meter with nothing on OUT, then wire the PCA9685. Heatsink on. 4 A continuous derated.")
LM2596 = C("LM2596 3 A buck — trim OUT to 5.0 V", ["IN+", "IN−", "OUT+", "OUT−"],
           "Screw terminals. Set 5.00 V on the meter with nothing on OUT. 2 A continuous without a fan. Vin must stay ≥ 6.5 V (pack floor 10.5 V: fine).")
PCA_PWR = C("PCA9685 servo-power screw terminal", ["V+", "GND"], "The big 2-pin terminal at the end of the board = servo rail, NOT logic VCC.")
PCA_LOGIC = C("PCA9685 logic header (6 pins, either end)", ["GND", "OE", "SCL", "SDA", "VCC", "V+"],
              "Adafruit-pattern silkscreen: GND OE SCL SDA VCC V+. OE left open (internal pull-down = outputs on). V+ pin unused; V+ enters at the terminal. Address 0x40 (no jumpers).")
PCA_CH0 = C("PCA9685 channel 0 (3-pin, at the board's channel 0 end)", ["PWM", "V+", "GND"], "Rows on the board: PWM (top, yellow), V+ (middle, red), GND (bottom, black). Channels 1–15 empty.")
TILT = C("MG996R TILT servo", ["signal (orange)", "V+ (red)", "GND (brown)"], "Plugs straight onto channel 0, brown toward the board edge (GND row). Limits 65–150° in turret.py.")
PAN = C("MG996R PAN servo — NOT CONNECTED", ["signal", "V+", "GND"], "Continuous-rotation unit: cannot hold an angle. Pinned with the printed lock; leave its lead unplugged.")

# CP2102 6-pin adapters: label order varies by vendor — go by the silkscreen, only these three pins are used
def CP(n, role):
    return C(f"CP2102 USB-UART no.{n} → {role}", ["3V3", "5V", "GND", "TXD", "RXD", "DTR"],
             "Only GND, TXD, RXD are used. 5V and 3V3 pins stay EMPTY (the radar is powered from the LM2596 rail, not the Pi's USB budget). Jumper on 3.3 V logic if the adapter has one. Label the adapter body: " + role + ".")


LD2410 = lambda side, toe: C(f"HLK-LD2410C {side} (toed {toe})", ["1 TX", "2 RX", "3 OUT", "4 GND", "5 VCC"],
                             "Pins per Hi-Link manual table 1: 1 UART_Tx, 2 UART_Rx, 3 OUT, 4 GND, 5 VCC (5–12 V, 5 V advised). IO 3.3 V, 256000 baud. OUT unused.")
LD2450 = C("HLK-LD2450 (centre, x/y tracker)", ["5V", "GND", "TX", "RX"], "Silkscreen 5V GND TX RX; 5 V supply, 3.3 V UART, 256000 baud. Needs the THIRD CP2102 — until it arrives, leave power and data unplugged.")

PI_HDR = C("Raspberry Pi 4 — 40-pin header (used pins only)",
           ["1 3V3", "3 SDA1 BCM2", "5 SCL1 BCM3", "6 GND", "7 BCM4 i2c3-SDA", "9 GND", "12 BCM18 I2S-BCLK", "13 BCM27 XSHUT-rear",
            "14 GND", "15 BCM22 XSHUT-front", "17 3V3", "20 GND", "29 BCM5 i2c3-SCL", "30 GND", "35 BCM19 I2S-LRCLK", "38 BCM20 I2S-DIN", "39 GND"],
           "Physical pin numbers (odd = inner row from the SD-card end). i2c3 on BCM 4/5 needs dtoverlay=i2c3 in config.txt and has NO on-board pull-ups. w1-gpio must stay off (it defaults to BCM 4).")

def shield_motor_header(axis, wheel, step, dir_):
    return C(f"CNC Shield v3 — {axis} driver motor header ({wheel})", ["2B", "2A", "1A", "1B"],
             f"4-pin male header beside the {axis} socket. Driver STEP = D{step}, DIR = D{dir_}, EN = D8 shared. Firmware map: {wheel} = {axis}.")


def motor(wheel, axis):
    return C(f"JK42HS40 NEMA 17 — {wheel} (axis {axis})", ["coil A +", "coil A −", "coil B +", "coil B −"],
             "Find the pairs with the meter: the two leads that read ~1.5–2 Ω are ONE coil. Lead colours vary between batches — the meter, not the colour, decides.")


# ── the seven diagrams ───────────────────────────────────────────────────────────────────────────────────────
D = {}

D["1-power"] = dict(
    metadata=dict(title="Hound 1 — power distribution (pack side and logic island)"),
    connectors=dict(
        PACK=C("HOOVO 3S 2200 mAh 80C LiPo — T-plug (Deans)", ["V+", "GND"], "11.1 V nominal, 12.6 V full, 10.5 V floor (cutoff V 10.5 in firmware). A pack that reads 6.8 V is dead: never charge it."),
        ESTOP=C("E-STOP — NC mushroom switch in the + lead", ["IN", "OUT"], "Latching, twist-release, mounted at deck X −140 (assembly.py). Breaks EVERYTHING on the pack side; the Pi keeps running on the bank."),
        WAGO_P=WAGO_P, WAGO_N=WAGO_N,
        SHIELD_PWR=C("CNC Shield v3 — power screw terminal", ["VMOT", "GND"], "1000 µF 25 V electrolytic across VMOT/GND at the terminal, stripe (−) to GND. Reversed = vents on first power-up."),
        XL4015=XL4015, LM2596=LM2596, PCA_PWR=PCA_PWR,
        FAN=C("40 mm 5 V fan on the driver heatsinks", ["5V (red)", "GND (black)"], "Must be a 5 V fan. A 12 V fan goes on the pack Wagos instead — read the label."),
        WAGO5_P=WAGO5_P, WAGO5_N=WAGO5_N,
        DIV=C("Pack-voltage divider on perfboard — 47 kΩ / 10 kΩ", ["PACK+", "A3", "GND"], "47 kΩ between PACK+ and A3; 10 kΩ between A3 and GND. 12.6 V → 2.21 V at A3 (R4 ADC ref 5 V, VBAT_RATIO 57/10). A3 = the shield's CoolEn pin."),
        SHIELD_A3=C("CNC Shield v3 — CoolEn header pin (= R4 A3)", ["A3", "GND"], "The 4-pin block Abort/Hold/Resume/CoolEn on the shield's edge; CoolEn is A3. Its GND is the neighbouring GND pin."),
        BANK=C("USB power bank 5 V / 3 A (logic island)", ["USB-A out"], "Genuine 3 A bank. Cable ≤ 0.3 m, ≥ 24 AWG power conductors. Powers ONLY the Pi; the Pi powers the R4, the hub, the adapters and the webcam."),
        PI_PWR=C("Raspberry Pi 4 — USB-C power in", ["USB-C"], "Under-voltage warning at 4.63 V. Early Pi 4 (rev 1.1) needs an A-to-C or non-e-marked cable."),
    ),
    cables=dict(
        W_PACK=B(14, 0.30, ["RD", "BK"], "HOOVO T-plug → OliRC extension → pigtail. Both conductors 14 AWG."),
        W_ESTOP=B(14, 0.10, ["RD"]),
        W_SHIELD=B(22, 0.15, ["RD", "BK"], "Motor bus: 4 A ramp burst, 20 mV drop"),
        W_XL_IN=B(22, 0.15, ["RD", "BK"]),
        W_LM_IN=B(22, 0.15, ["RD", "BK"]),
        W_SERVO=B(22, 0.12, ["RD", "BK"], "6.0 V servo rail. OUT− → PCA9685 GND terminal is the servo RETURN: its own wire, always."),
        W_LM_OUT=B(22, 0.10, ["RD", "BK"], "5.0 V rail into the sensor Wagos"),
        W_FAN=B(24, 0.15, ["RD", "BK"], "Fan straight off the LM2596 OUT terminals (second wire in the same screw)"),
        W_DIV=B(24, 0.10, ["RD", "YE", "BK"], "Divider: red to Wago +, yellow to A3, black to Wago −"),
        W_BANK=B(24, 0.30, ["RD"], "USB-A → USB-C, '3 A fast-charge' cable, ≤ 0.3 m"),
    ),
    connections=[
        link(("PACK", "V+"), ("W_PACK", 1), ("ESTOP", "IN")),
        link(("ESTOP", "OUT"), ("W_ESTOP", 1), ("WAGO_P", "pigtail +")),
        link(("PACK", "GND"), ("W_PACK", 2), ("WAGO_N", "pigtail −")),
        link(("WAGO_P", "shield VMOT"), ("W_SHIELD", 1), ("SHIELD_PWR", "VMOT")),
        link(("WAGO_N", "shield GND"), ("W_SHIELD", 2), ("SHIELD_PWR", "GND")),
        link(("WAGO_P", "XL4015 IN+"), ("W_XL_IN", 1), ("XL4015", "IN+")),
        link(("WAGO_N", "XL4015 IN−"), ("W_XL_IN", 2), ("XL4015", "IN−")),
        link(("WAGO_P", "LM2596 IN+"), ("W_LM_IN", 1), ("LM2596", "IN+")),
        link(("WAGO_N", "LM2596 IN−"), ("W_LM_IN", 2), ("LM2596", "IN−")),
        link(("XL4015", "OUT+"), ("W_SERVO", 1), ("PCA_PWR", "V+")),
        link(("XL4015", "OUT−"), ("W_SERVO", 2), ("PCA_PWR", "GND")),
        link(("LM2596", "OUT+"), ("W_LM_OUT", 1), ("WAGO5_P", "LM2596 OUT+")),
        link(("LM2596", "OUT−"), ("W_LM_OUT", 2), ("WAGO5_N", "LM2596 OUT−")),
        link(("LM2596", "OUT+"), ("W_FAN", 1), ("FAN", "5V (red)")),
        link(("LM2596", "OUT−"), ("W_FAN", 2), ("FAN", "GND (black)")),
        link(("WAGO_P", "47k divider"), ("W_DIV", 1), ("DIV", "PACK+")),
        link(("DIV", "A3"), ("W_DIV", 2), ("SHIELD_A3", "A3")),
        link(("WAGO_N", "10k divider"), ("W_DIV", 3), ("DIV", "GND")),
        link(("BANK", "USB-A out"), ("W_BANK", 1), ("PI_PWR", "USB-C")),
    ],
)

D["2-drive"] = dict(
    metadata=dict(title="Hound 2 — UNO R4 WiFi + CNC Shield v3 + DRV8825 ×4 + NEMA 17 ×4 (frozen v1.0 drive)"),
    connectors=dict(
        R4=C("Arduino UNO R4 WiFi — under the shield (stacked, no wires)", ["D2 X STEP", "D5 X DIR", "D3 Y STEP", "D6 Y DIR", "D4 Z STEP", "D7 Z DIR", "D12 A STEP", "D13 A DIR", "D8 EN (all four)", "A3 VBAT sense", "A4 SDA (option B)", "A5 SCL (option B)", "USB-C → Pi hub"],
             "Stack the shield on the R4; the pins listed are what the shield takes. Firmware r4_drive v1.0-best-drive: 30 kHz step ISR, 1/32, 415 mm/s. Logic 5 V. USB from the Pi hub; ENABLE_WIFI 0."),
        SHIELD_CTRL=C("CNC Shield v3 — jumpers and control pins", ["EN", "5V", "GND", "A-axis jumper D12", "A-axis jumper D13", "MS1 cap ×4", "MS2 (open) ×4", "MS3 cap ×4"],
                      "AS BUILT: caps on MS1 + MS3 under every driver = 1/32 (M0+M2), MS2 open. Two jumpers on the A header = D12/D13 drive the A axis. 10 kΩ from EN to 5V (pull-up) so the drivers stay OFF during R4 resets. Caps on before the drivers."),
        R_EN=C("10 kΩ resistor — EN pull-up", ["EN side", "5V side"], "Consumables. Without it, D8 floats LOW during the R4's ~1 s reset and all four drivers sit at full current uncommanded."),
        DRV=C("DRV8825 ×4 in sockets X Y Z A (plug-in, no wires)", ["EN pin over the socket's EN label", "Vref 0.75 V (R100) = 1.5 A", "heatsink on"],
              "Orientation: the driver's EN pin over the socket's EN label; trimpot toward the power terminal on Pololu layouts, clones vary — go by the label. Backwards = dead driver. Set Vref with motors UNPLUGGED, meter black on the shield GND pin, red on the trimpot screw."),
        X_MOT=shield_motor_header("X", "BL", 2, 5), Y_MOT=shield_motor_header("Y", "FL", 3, 6), Z_MOT=shield_motor_header("Z", "BR", 4, 7), A_MOT=shield_motor_header("A", "FR", 12, 13),
        M_BL=motor("BL back-left", "X"), M_FL=motor("FL front-left", "Y"), M_BR=motor("BR back-right", "Z"), M_FR=motor("FR front-right", "A"),
    ),
    cables={f"W_{w}": B(26, 0.40, ["RD", "BU", "GN", "BK"], "4-pin Dupont, 1.5 A per phase (2 A contacts): any pin that warms in the wheels-up test gets re-crimped") for w in ("BL", "FL", "BR", "FR")}
           | dict(W_PULL=B(24, 0.03, ["OG", "OG"], "resistor leads")),
    connections=[
        link(("SHIELD_CTRL", "EN"), ("W_PULL", 1), ("R_EN", "EN side")),
        link(("SHIELD_CTRL", "5V"), ("W_PULL", 2), ("R_EN", "5V side")),
    ] + [
        row for hdr, m, w in (("X_MOT", "M_BL", "W_BL"), ("Y_MOT", "M_FL", "W_FL"), ("Z_MOT", "M_BR", "W_BR"), ("A_MOT", "M_FR", "W_FR"))
        for row in (link((hdr, "2B"), (w, 1), (m, "coil B +")), link((hdr, "2A"), (w, 2), (m, "coil B −")),
                    link((hdr, "1A"), (w, 3), (m, "coil A +")), link((hdr, "1B"), (w, 4), (m, "coil A −")))
    ],
)

D["3a-turret-pi"] = dict(
    metadata=dict(title="Hound 3A — turret: PCA9685 driven by the Pi (AS BUILT — turret.py, station.py)"),
    connectors=dict(
        PI=C("Raspberry Pi 4 — 40-pin header", ["1 3V3", "3 SDA1 BCM2", "5 SCL1 BCM3", "6 GND"], "I2C-1 has 1.8 kΩ pull-ups to 3.3 V on the Pi. PCA9685 VCC = 3.3 V so its own pull-ups also sit at 3.3 V — never 5 V here."),
        PCA_LOGIC=PCA_LOGIC, PCA_PWR=PCA_PWR, PCA_CH0=PCA_CH0, TILT=TILT, PAN=PAN, XL4015=XL4015,
    ),
    cables=dict(
        W_I2C=B(24, 0.20, ["BK", "YE", "BU", "RD"], "GND, SCL (yellow), SDA (blue), 3V3 (red) — Dupont female-female"),
        W_SERVO=B(22, 0.12, ["RD", "BK"], "6.0 V from the XL4015; OUT− to the PCA9685 GND TERMINAL is the servo return"),
        W_TILT=B(22, 0.30, ["OG", "RD", "BN"], "the servo's own lead"),
    ),
    connections=[
        link(("PI", "6 GND"), ("W_I2C", 1), ("PCA_LOGIC", "GND")),
        link(("PI", "5 SCL1 BCM3"), ("W_I2C", 2), ("PCA_LOGIC", "SCL")),
        link(("PI", "3 SDA1 BCM2"), ("W_I2C", 3), ("PCA_LOGIC", "SDA")),
        link(("PI", "1 3V3"), ("W_I2C", 4), ("PCA_LOGIC", "VCC")),
        link(("XL4015", "OUT+"), ("W_SERVO", 1), ("PCA_PWR", "V+")),
        link(("XL4015", "OUT−"), ("W_SERVO", 2), ("PCA_PWR", "GND")),
        link(("PCA_CH0", "PWM"), ("W_TILT", 1), ("TILT", "signal (orange)")),
        link(("PCA_CH0", "V+"), ("W_TILT", 2), ("TILT", "V+ (red)")),
        link(("PCA_CH0", "GND"), ("W_TILT", 3), ("TILT", "GND (brown)")),
    ],
)

D["3b-turret-shield"] = dict(
    metadata=dict(title="Hound 3B — turret: PCA9685 on the CNC Shield's I2C pins (ALTERNATIVE — needs a firmware 't' command)"),
    connectors=dict(
        SHIELD_I2C=C("CNC Shield v3 — A4/A5 + 5V/GND pins (= R4 Wire bus, 5 V logic)", ["A4 SDA", "A5 SCL", "5V", "GND"],
                     "A4/A5 are the R4's primary I2C ('Wire'), 5 V logic, no on-board pull-ups: the PCA9685's 10 kΩ pull-ups to VCC=5 V do the job. NOT the R4's Qwiic socket (that is Wire1, 3.3 V)."),
        PCA_LOGIC=PCA_LOGIC, PCA_PWR=PCA_PWR, PCA_CH0=PCA_CH0, TILT=TILT, PAN=PAN, XL4015=XL4015,
    ),
    cables=dict(
        W_I2C=B(24, 0.15, ["BK", "YE", "BU", "RD"], "GND, SCL, SDA, 5V — Dupont"),
        W_SERVO=B(22, 0.12, ["RD", "BK"]),
        W_TILT=B(22, 0.30, ["OG", "RD", "BN"]),
    ),
    connections=[
        link(("SHIELD_I2C", "GND"), ("W_I2C", 1), ("PCA_LOGIC", "GND")),
        link(("SHIELD_I2C", "A5 SCL"), ("W_I2C", 2), ("PCA_LOGIC", "SCL")),
        link(("SHIELD_I2C", "A4 SDA"), ("W_I2C", 3), ("PCA_LOGIC", "SDA")),
        link(("SHIELD_I2C", "5V"), ("W_I2C", 4), ("PCA_LOGIC", "VCC")),
        link(("XL4015", "OUT+"), ("W_SERVO", 1), ("PCA_PWR", "V+")),
        link(("XL4015", "OUT−"), ("W_SERVO", 2), ("PCA_PWR", "GND")),
        link(("PCA_CH0", "PWM"), ("W_TILT", 1), ("TILT", "signal (orange)")),
        link(("PCA_CH0", "V+"), ("W_TILT", 2), ("TILT", "V+ (red)")),
        link(("PCA_CH0", "GND"), ("W_TILT", 3), ("TILT", "GND (brown)")),
    ],
)

D["4-pi-sensors"] = dict(
    metadata=dict(title="Hound 4 — Pi 40-pin header: thermal (i2c3), ToF ×2 (I2C-1), microphone (I2S)"),
    connectors=dict(
        PI=PI_HDR,
        MLX=C("MLX90640 thermal array breakout (0x33)", ["VIN 3V3", "GND", "SCL", "SDA"], "On i2c3 (BCM 4/5) ALONE so it can run at 1 MHz. BCM 4/5 have no pull-ups: if the module has none either, add 4.7 kΩ SDA→3V3 and SCL→3V3. Rides beside the webcam on the tilt bracket."),
        TOF_F=C("VL53L1X ToF FRONT (0x29 → re-addressed 0x30 by XSHUT)", ["VIN 3V3", "GND", "SDA", "SCL", "XSHUT"], "Both ToFs share I2C-1. At boot the Pi holds FRONT XSHUT low, gives REAR 0x29… then raises FRONT and moves it to 0x30."),
        TOF_R=C("VL53L1X ToF REAR (0x29)", ["VIN 3V3", "GND", "SDA", "SCL", "XSHUT"], "XSHUT on BCM 27 so the Pi can reset it independently."),
        MIC=C("INMP441 I2S microphone", ["VDD 3V3", "GND", "SCK", "WS", "SD", "L/R"], "L/R tied to GND = left channel. On the post front face, 120 mm up (assembly.py)."),
        PULL=C("2 × 4.7 kΩ i2c3 pull-ups (only if the MLX module has none)", ["3V3", "SDA", "SCL"], "Meter the module first: SDA to GND must read ≤ 3.3 V when powered alone."),
    ),
    cables=dict(
        W_MLX=B(26, 0.35, ["RD", "BK", "YE", "BU"], "to the turret: leave a service loop for tilt"),
        W_TOF_F=B(26, 0.25, ["RD", "BK", "BU", "YE", "WH"]),
        W_TOF_R=B(26, 0.35, ["RD", "BK", "BU", "YE", "WH"]),
        W_MIC=B(26, 0.25, ["RD", "BK", "GN", "OG", "VT", "BK"]),
        W_PULL=B(26, 0.05, ["RD", "BU", "YE"]),
    ),
    connections=[
        link(("PI", "1 3V3"), ("W_MLX", 1), ("MLX", "VIN 3V3")),
        link(("PI", "9 GND"), ("W_MLX", 2), ("MLX", "GND")),
        link(("PI", "29 BCM5 i2c3-SCL"), ("W_MLX", 3), ("MLX", "SCL")),
        link(("PI", "7 BCM4 i2c3-SDA"), ("W_MLX", 4), ("MLX", "SDA")),
        link(("PI", "17 3V3"), ("W_TOF_F", 1), ("TOF_F", "VIN 3V3")),
        link(("PI", "14 GND"), ("W_TOF_F", 2), ("TOF_F", "GND")),
        link(("PI", "3 SDA1 BCM2"), ("W_TOF_F", 3), ("TOF_F", "SDA")),
        link(("PI", "5 SCL1 BCM3"), ("W_TOF_F", 4), ("TOF_F", "SCL")),
        link(("PI", "15 BCM22 XSHUT-front"), ("W_TOF_F", 5), ("TOF_F", "XSHUT")),
        link(("PI", "17 3V3"), ("W_TOF_R", 1), ("TOF_R", "VIN 3V3")),
        link(("PI", "20 GND"), ("W_TOF_R", 2), ("TOF_R", "GND")),
        link(("PI", "3 SDA1 BCM2"), ("W_TOF_R", 3), ("TOF_R", "SDA")),
        link(("PI", "5 SCL1 BCM3"), ("W_TOF_R", 4), ("TOF_R", "SCL")),
        link(("PI", "13 BCM27 XSHUT-rear"), ("W_TOF_R", 5), ("TOF_R", "XSHUT")),
        link(("PI", "17 3V3"), ("W_MIC", 1), ("MIC", "VDD 3V3")),
        link(("PI", "39 GND"), ("W_MIC", 2), ("MIC", "GND")),
        link(("PI", "12 BCM18 I2S-BCLK"), ("W_MIC", 3), ("MIC", "SCK")),
        link(("PI", "35 BCM19 I2S-LRCLK"), ("W_MIC", 4), ("MIC", "WS")),
        link(("PI", "38 BCM20 I2S-DIN"), ("W_MIC", 5), ("MIC", "SD")),
        link(("PI", "30 GND"), ("W_MIC", 6), ("MIC", "L/R")),
        link(("PI", "1 3V3"), ("W_PULL", 1), ("PULL", "3V3")),
        link(("MLX", "SDA"), ("W_PULL", 2), ("PULL", "SDA")),
        link(("MLX", "SCL"), ("W_PULL", 3), ("PULL", "SCL")),
    ],
)

D["5-radars-usb"] = dict(
    metadata=dict(title="Hound 5 — radars on CP2102 adapters, the USB tree, and the double ground"),
    connectors=dict(
        PI_USB=C("Raspberry Pi 4 — USB-A ports", ["USB 1: webcam", "USB 2: hub", "USB 3: free", "USB 4: free"], "1.2 A shared across all four ports (peak here 0.80 A). Webcam on its own port, everything else through the hub."),
        HUB=C("4-port USB hub (unpowered)", ["upstream", "port 1: UNO R4", "port 2: CP2102 no.1", "port 3: CP2102 no.2", "port 4: CP2102 no.3"]),
        CAM=C("Webcam (C920-class) — captive 1.5 m cable", ["USB-A"], "On the turret beside the thermal array. If it drops out at 1080p, run 720p."),
        R4_USB=C("UNO R4 WiFi — USB-C", ["USB-C"], "USB CDC serial to the Pi: /dev/serial/by-id/*Arduino*"),
        CP1=CP(1, "LD2410C LEFT"), CP2=CP(2, "LD2410C RIGHT"), CP3=CP(3, "LD2450 (when the third adapter arrives)"),
        LDL=LD2410("LEFT", "+30° out, deck Y +50"), LDR=LD2410("RIGHT", "−30° out, deck Y −50"), LD2450=LD2450,
        WAGO5_P=WAGO5_P, WAGO5_N=WAGO5_N,
    ),
    cables=dict(
        W_CAM=B(28, 1.50, ["WH"], "captive"), W_HUB=B(28, 0.30, ["WH"]), W_R4=B(28, 0.30, ["WH"], "USB-A → USB-C"),
        W_CPA=B(28, 0.15, ["WH"]), W_CPB=B(28, 0.15, ["WH"]), W_CPC=B(28, 0.15, ["WH"]),
        W_LDL=B(26, 0.25, ["GN", "WH", "BK", "RD", "BK"], "TX, RX, signal-GND to the adapter; VCC and power-GND to the Wagos"),
        W_LDR=B(26, 0.25, ["GN", "WH", "BK", "RD", "BK"]),
        W_LD2450=B(26, 0.25, ["GN", "WH", "BK", "RD", "BK"]),
    ),
    connections=[
        link(("PI_USB", "USB 1: webcam"), ("W_CAM", 1), ("CAM", "USB-A")),
        link(("PI_USB", "USB 2: hub"), ("W_HUB", 1), ("HUB", "upstream")),
        link(("HUB", "port 1: UNO R4"), ("W_R4", 1), ("R4_USB", "USB-C")),
        link(("HUB", "port 2: CP2102 no.1"), ("W_CPA", 1), ("CP1", "5V")),
        link(("HUB", "port 3: CP2102 no.2"), ("W_CPB", 1), ("CP2", "5V")),
        link(("HUB", "port 4: CP2102 no.3"), ("W_CPC", 1), ("CP3", "5V")),
    ] + [
        row for cp, ld, w, vcc, gnd, tx, rx, wp, wn in (
            ("CP1", "LDL", "W_LDL", "5 VCC", "4 GND", "1 TX", "2 RX", "LD2410C LEFT VCC", "LD2410C LEFT GND"),
            ("CP2", "LDR", "W_LDR", "5 VCC", "4 GND", "1 TX", "2 RX", "LD2410C RIGHT VCC", "LD2410C RIGHT GND"),
            ("CP3", "LD2450", "W_LD2450", "5V", "GND", "TX", "RX", "LD2450 5V", "LD2450 GND"))
        for row in (link((ld, tx), (w, 1), (cp, "RXD")), link((ld, rx), (w, 2), (cp, "TXD")), link((ld, gnd), (w, 3), (cp, "GND")),
                    link(("WAGO5_P", wp), (w, 4), (ld, vcc)), link(("WAGO5_N", wn), (w, 5), (ld, gnd)))
    ],
)

D["6-csi"] = dict(
    metadata=dict(title="Hound 6 — WiFi CSI nodes (ESP32-S3 ×2; no.1 is the spare)"),
    connectors=dict(
        ESP3=C("ESP32-S3 DevKitC no.3 — csi_rx_udp, ON the rover at deck (60,120)", ["5V (VIN)", "GND", "USB-C: NEVER while 5V is fed"], "Joins the Pi hotspot (channel 6) and streams the CSI of every probe to the Pi, UDP 5005. secrets.h holds the hotspot name and password (git-ignored)."),
        ESP2=C("ESP32-S3 DevKitC no.2 — csi_tx, OFF the rover", ["USB-C from any 5 V charger"], "Dropped ~3 m along the wall. 100 Hz ESP-NOW probes on channel 6. Radio link only — no wire to the rover."),
        WAGO5_P=WAGO5_P, WAGO5_N=WAGO5_N,
    ),
    cables=dict(W_ESP=B(24, 0.20, ["RD", "BK"], "WiFi bursts to 0.5 A: 24 AWG or heavier")),
    connections=[
        link(("WAGO5_P", "ESP32-S3 no.3 5V"), ("W_ESP", 1), ("ESP3", "5V (VIN)")),
        link(("WAGO5_N", "ESP32-S3 no.3 GND"), ("W_ESP", 2), ("ESP3", "GND")),
    ],
)

# ── render ───────────────────────────────────────────────────────────────────────────────────────────────────
WV = os.path.join(os.path.dirname(sys.executable), "wireviz")
for name, doc in D.items():
    doc.setdefault("options", {})["bgcolor"] = "#ffffff"
    path = os.path.join(OUT, f"{name}.yml")
    with open(path, "w") as f:
        yaml.safe_dump(doc, f, allow_unicode=True, sort_keys=False, width=200)
    r = subprocess.run([WV, "-f", "sp", "-o", OUT, path], capture_output=True, text=True)
    if r.returncode:
        sys.exit(f"wireviz failed on {name}:\n{r.stdout}\n{r.stderr}")
    print(f"  rendered {name}")

# ── cross-check against wiring.py ────────────────────────────────────────────────────────────────────────────
edges = set(); conns = {}
for name, doc in D.items():
    conns.update({k: v for k, v in doc["connectors"].items()})
    for row in doc["connections"]:
        ends = [(list(h)[0], list(h.values())[0][0]) for h in row]
        a, b = ends[0], ends[-1]
        edges.add((a[0], b[0])); edges.add((b[0], a[0]))
        edges.add(((a[0], a[1]), (b[0], b[1]))); edges.add(((b[0], b[1]), (a[0], a[1])))

problems = []
def need(cond, msg):
    if not cond: problems.append(msg)

# 1. every load in wiring.py has a power feed from the right rail's connector
RAIL_SRC = {"PACK": {"WAGO_P", "SHIELD_PWR"}, "V_SERVO": {"XL4015", "PCA_PWR"}, "V5_LM": {"LM2596", "WAGO5_P"},
            "V5_BANK": {"BANK"}, "V5_PI_USB": {"PI_USB", "HUB"}, "V3_PI": {"PI"}}
LOAD_CONN = {"4× DRV8825": "SHIELD_PWR", "XL4015": "XL4015", "LM2596": "LM2596", "MG996R": "PCA_PWR", "40 mm fan": "FAN",
             "LD2410C radar #2": "LDR", "LD2410C radar": "LDL", "LD2450": "LD2450", "ESP32-S3 #3": "ESP3", "Raspberry Pi 4": "PI_PWR",
             "Webcam": "CAM", "UNO R4": "R4_USB", "3× CP2102": "HUB", "MLX90640": "MLX", "VL53L1X ToF front": "TOF_F",
             "VL53L1X ToF rear": "TOF_R", "PCA9685 logic": "PCA_LOGIC", "INMP441": "MIC", "SCD41": None}
for load in LOADS:
    name, rail = load[0], load[1]
    key = next((k for k in sorted(LOAD_CONN, key=len, reverse=True) if name.startswith(k)), None)
    need(key is not None, f"load not mapped to a connector: {name}")
    if key is None or LOAD_CONN[key] is None: continue
    conn = LOAD_CONN[key]
    need(any((src, conn) in edges for src in RAIL_SRC[rail]), f"{name}: no feed from rail {rail} ({sorted(RAIL_SRC[rail])}) in any diagram")

# 2. every wired signal link exists as an edge between the named parts
SIG_CONN = {"UNO R4 (5 V logic)": "X_MOT", "DRV8825 ×4": "M_BL", "LD2410C left TX": "LDL", "CP2102 #1": "CP1", "LD2410C left": "LDL",
            "LD2410C right TX": "LDR", "CP2102 #2": "CP2", "LD2410C right": "LDR", "LD2450 TX": "LD2450", "CP2102 #3": "CP3", "LD2450": "LD2450",
            "Pi I2C-1": "PI", "PCA9685 0x40": "PCA_LOGIC", "Pi i2c3": "PI", "MLX90640 0x33": "MLX", "Pi BCM 22 / 27": "PI", "VL53L1X front / rear": "TOF_F",
            "Pi I2S": "PI", "INMP441": "MIC", "Pi ↔ UNO R4": "HUB", "UNO R4": "R4_USB", "Pi ↔ 3× CP2102": "HUB", "radars at 256000 baud": "CP1"}
def sc(s):
    return next((v for k, v in sorted(SIG_CONN.items(), key=lambda kv: -len(kv[0])) if s.startswith(k)), None)
for drv, dp, vo, rcv, rp, vmax, vih, bus in SIGNALS:
    if bus == "WIFI": continue
    a, b = sc(drv), sc(rcv)
    need(a and b, f"signal not mapped: {drv} → {rcv}")
    if a and b:
        need((a, b) in edges or (a == "X_MOT" and b == "M_BL" and ("X_MOT", "M_BL") in edges), f"signal has no wire in the diagrams: {drv} [{a}] → {rcv} [{b}]")

# 3. Pi BCM pins: the set used in the diagrams equals wiring.py's PI_BCM
used_bcm = set()
for lab in PI_HDR["pinlabels"] + D["3a-turret-pi"]["connectors"]["PI"]["pinlabels"]:
    for tok in lab.split():
        if tok.startswith("BCM"): used_bcm.add(int(tok[3:]))
need(used_bcm == set(PI_BCM.values()), f"Pi BCM pins differ: diagrams {sorted(used_bcm)} vs wiring.py {sorted(PI_BCM.values())}")

# 4. R4 pins: the shield's pin list carries every R4_PINS entry (D-number) and A3
r4_lab = " ".join(D["2-drive"]["connectors"]["R4"]["pinlabels"])
for k, v in R4_PINS.items():
    tag = "A3" if v == 17 else f"D{v}"
    need(f"{tag} " in r4_lab, f"R4 pin {tag} ({k}) missing from the drive diagram")

# 5. every powered module has a GND wire; every radar has exactly two
gnd_of = {}
for name, doc in D.items():
    for row in doc["connections"]:
        for h in (row[0], row[-1]):
            c, p = list(h)[0], list(h.values())[0][0]
            if c in doc["connectors"] and isinstance(p, str) and ("GND" in p or p.endswith("−") or p == "L/R"):
                gnd_of.setdefault(c, []).append((name, p))
for c in ("LDL", "LDR", "LD2450"):
    n = len(gnd_of.get(c, []))
    need(n == 2, f"{c} needs exactly two GND wires (power return + signal reference), has {n}")
for c in ("PCA_LOGIC", "MLX", "TOF_F", "TOF_R", "MIC", "ESP3", "FAN", "XL4015", "LM2596", "SHIELD_PWR", "PCA_PWR"):
    need(c in gnd_of, f"{c} has no GND wire")

# 6. I2C addresses on each bus are distinct (from wiring.py) and each device sits on the bus wiring.py says
I2C = W["I2C_BUSES"]
for bus, devs in I2C.items():
    addrs = [a for _, a, _ in devs]
    need(len(addrs) == len(set(addrs)), f"{bus}: duplicate I2C address")
need(("PI", "MLX") in edges and (("PI", "7 BCM4 i2c3-SDA"), ("MLX", "SDA")) in edges, "MLX90640 must hang on BCM 4/5 (i2c3), as wiring.py says")
need((("PI", "3 SDA1 BCM2"), ("PCA_LOGIC", "SDA")) in edges, "PCA9685 (option A) must hang on I2C-1 BCM 2/3")

print("\nCROSS-CHECK vs wiring.py:", "OK — every load fed, every signal wired, pins match" if not problems else f"{len(problems)} problem(s)")
for p in problems: print("  ✗", p)

json.dump(dict(diagrams=list(D), connectors={k: v for d in D.values() for k, v in d["connectors"].items()},
               connections={n: [[(list(h)[0], list(h.values())[0][0]) for h in row] for row in d["connections"]] for n, d in D.items()},
               problems=problems), open(os.path.join(ROOT, "wiring_diagrams.json"), "w"), indent=1, ensure_ascii=False)
sys.exit(1 if problems else 0)
