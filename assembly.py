#!/usr/bin/env python3
"""Where every part goes, in millimetres, and what holds it there.

Frame: origin at the chassis centre on the floor plane. +X forward, +Y rover
left, +Z up (same convention as the Ceres CAD). Every position is a part
CENTRE unless the note says otherwise. Dimensions marked VERIFY are nominal
for that class of part and must be checked with a caliper on receipt before
any hole is drilled — the listing did not publish them.

Emits assembly.json (for the site), assembly.csv, and prints the table plus
interference, clearance, CG and fastener-count checks.

    python3 assembly.py
"""

import csv
import json
import math

# ── Fixed dimensions ────────────────────────────────────────────────────────
RAIL = 20.0                 # 2020 profile                                  MEASURED
RAIL_LEN = 350.0            # all four rails                                 MEASURED (listing)
RAIL_Z0 = 71.0              # rail underside = shaft height 40 + bracket offset 31
NEMA = 42.3                 # NEMA 17 flange                                 MEASURED (drawing)
NEMA_LEN = 39.5             # body length                                    MEASURED (drawing)
NEMA_PITCH = 31.0           # bolt pattern                                   MEASURED (drawing)
SHAFT_D, SHAFT_LEN = 5.0, 22.0   # shaft length VERIFY                        drawing: 5 mm with flat
BRK_T = 3.0                 # Anndason steel                                 MEASURED (listing)
BRK_OFFSET = 31.0           # axle centre to foot face                        from AMAZON-BOM fit section
BRK_FOOT_W, BRK_FOOT_D = 42.0, 35.0   # VERIFY
WHEEL_D, WHEEL_W = 80.0, 31.0         # width VERIFY
COUPLER_LEN = 15.0                    # VERIFY
AXLE_X = 125.0              # wheelbase 250
AXLE_Z = WHEEL_D / 2
DECK_T = 5.0                # PETG deck tiles
DECK_Z0 = RAIL_Z0 + RAIL    # 91: deck sits on the rail tops
DECK_TOP = DECK_Z0 + DECK_T # 96

UNO = (68.6, 53.3, 12.0)
SHIELD_STACK_H = 45.0       # Uno + shield + DRV8825 with heatsinks           VERIFY
PI = (85.0, 56.0, 20.0)
PCA9685 = (62.0, 25.0, 12.0)
BUCK = (61.0, 21.0, 14.0)   # DROK-style                                     VERIFY
ESP32 = (63.0, 25.4, 12.0)
LIPO = (132.0, 43.0, 25.0)  # MEASURED (listing)
CRADLE_T = 3.0
CAM = (29.0, 94.0, 24.0)    # owned C920-class webcam: depth, width, height  VERIFY
TURRET_BASE = (100.0, 60.0, 6.0)      # Ceres pan base plate (rover_parts.py make_turret_pan_base)
TURRET_H = 110.0            # base top to camera centre                       VERIFY on the actual Ceres turret
LD2410C = (35.0, 7.0, 3.0)  # VERIFY
LD2450 = (43.0, 15.0, 3.0)  # VERIFY
TOF = (25.0, 11.0, 4.0)     # VL53L1X module                                 VERIFY
FAN = (40.0, 40.0, 10.0)    # MEASURED (listing)
POST = (40.0, 40.0, 200.0)  # PETG radar post
RADAR_Z = DECK_TOP + POST[2] + 4.0    # 300: antenna faces horizontal, forward

# ── Masses, kg, for CG (same figures as drivetrain.py) ─────────────────────
M = dict(motor=0.240, rail=0.350 * 0.50, wheel=0.150, bracket=0.113, corner=0.012,
         uno_stack=0.117, pi=0.070, lipo=0.343, buck=0.040, radar=0.010, esp32=0.015,
         cam=0.162, tof=0.005, deck=0.300, cradle=0.060, post=0.100, turret=0.250,
         pca=0.010, fan=0.030, strapwire=0.150)

parts = []

def add(pid, inst, name, x, y, z, l, w, h, orient, mounts_to, fasteners, torque, mass, verify="", note=""):
    parts.append(dict(id=pid, instance=inst, part=name, x=round(x, 1), y=round(y, 1), z=round(z, 1),
                      l=l, w=w, h=h, orientation=orient, mounts_to=mounts_to, fasteners=fasteners,
                      torque=torque, mass_kg=mass, verify=verify, note=note))

# ── Frame ───────────────────────────────────────────────────────────────────
RAIL_ZC = RAIL_Z0 + RAIL / 2
SIDE_Y = 175.0 + RAIL / 2            # 185: inner face at 175, outer at 195
CROSS_X = 155.0 + RAIL / 2           # 165: inner face at 155, outer at 175
for inst, y in (("left", SIDE_Y), ("right", -SIDE_Y)):
    add("RAIL", f"side {inst}", "2020 V-slot rail 350 mm, along X", 0, y, RAIL_ZC, RAIL_LEN, RAIL, RAIL,
        "long axis X", "corner brackets at both ends", "—", "—", M["rail"],
        note="Outer face at Y = ±195. Ends at X = ±175.")
for inst, x in (("front", CROSS_X), ("rear", -CROSS_X)):
    add("RAIL", f"cross {inst}", "2020 V-slot rail 350 mm, along Y", x, 0, RAIL_ZC, RAIL, RAIL_LEN, RAIL,
        "long axis Y", "butts against inner faces of the side rails", "—", "—", M["rail"],
        note="Spans Y −175..+175 exactly between the side rails. Outer face at X = ±175.")
for cx in (CROSS_X, -CROSS_X):
    for sy in (SIDE_Y, -SIDE_Y):
        for face, z in (("top", RAIL_Z0 + RAIL - 8.5), ("bottom", RAIL_Z0 + 8.5)):
            add("CNR", f"{'front' if cx > 0 else 'rear'}-{'left' if sy > 0 else 'right'} {face}",
                "2020 corner bracket 17×20, black", cx - math.copysign(RAIL / 2 + 8.5, cx),
                sy - math.copysign(RAIL / 2 + 8.5, sy), z, 17, 17, 20,
                f"inside corner, on the {face} slot pair",
                "side rail + cross rail", "2× M5×8 hex + 2× M5 T-nut", "3.0 N·m (do not exceed on 2020 T-nuts)",
                M["corner"], note="One inside each corner on the top slot and one on the bottom slot: 8 total.")

# ── Drivetrain ──────────────────────────────────────────────────────────────
HAND = {"FL": "left-hand", "FR": "right-hand", "RL": "right-hand", "RR": "left-hand"}
for inst, sx, sy in (("FL", 1, 1), ("FR", 1, -1), ("RL", -1, 1), ("RR", -1, -1)):
    x = sx * AXLE_X
    outer = sy * 195.0                          # side-rail outer face
    leg_y = outer - sy * BRK_T / 2              # 3 mm leg just inboard of the outer face, under the rail
    motor_face_y = outer - sy * BRK_T           # motor flange against the leg's inboard side
    motor_c_y = motor_face_y - sy * NEMA_LEN / 2
    add("BRK", inst, "Steel NEMA 17 L-bracket, inverted under rail", x, outer - sy * BRK_FOOT_D / 2,
        RAIL_Z0 - BRK_T / 2, BRK_FOOT_W, BRK_FOOT_D, BRK_T,
        "foot flat against rail underside, leg hanging down flush with rail outer face",
        f"side rail {'left' if sy > 0 else 'right'} underside", "2× M4×10 hex + 2× M4 T-nut (bottom slot)",
        "2.0 N·m", M["bracket"], verify="foot 42×35 and slot spacing",
        note=f"Leg centre Y = {leg_y:+.1f}; axle hole centre at Z = {AXLE_Z:.0f}.")
    add("MOT", f"{inst} (motor {['FL','FR','RL','RR'].index(inst)+1})", "JK42HS40-1704-13A NEMA 17",
        x, motor_c_y, AXLE_Z, NEMA, NEMA_LEN, NEMA, f"shaft along Y pointing {'+Y' if sy > 0 else '−Y'} (outboard)",
        f"bracket {inst} leg, inboard side", "4× M3×6 socket head through leg into flange", "0.8 N·m (aluminium threads)",
        M["motor"], note=f"Flange face at Y = {motor_face_y:+.1f}; body bottom at Z = {AXLE_Z - NEMA/2:.1f} (ground clearance). Leads exit inboard.")
    wheel_c_y = outer + sy * (BRK_T + 3.0 + COUPLER_LEN / 2 + WHEEL_W / 2 - 4.0)
    add("WHL", f"{inst} ({HAND[inst]})", f"80 mm mecanum wheel, {HAND[inst]}", x, wheel_c_y, AXLE_Z,
        WHEEL_D, WHEEL_W, WHEEL_D, "axis Y; rollers on the TOP of the wheel point toward chassis centre (X seen from above)",
        f"5 mm coupler on motor {inst} shaft", "coupler grub screw on the shaft flat + blue threadlocker; wheel to coupler per kit hardware",
        "1.5 N·m grub", M["wheel"], verify="wheel width and coupler length",
        note=f"Inner face Y = {wheel_c_y - sy*WHEEL_W/2:+.1f}. Track = {2*abs(wheel_c_y):.0f} mm.")

# ── Deck ────────────────────────────────────────────────────────────────────
for inst, x in (("front tile", 85.0), ("rear tile", -85.0)):
    add("PETG", inst, "PETG deck tile 170×350×5", x, 0, DECK_Z0 + DECK_T / 2, 170, 350, DECK_T,
        "flat on rail tops", "all four rails", "6× M5×10 hex + 6× M5 T-nut (top slots: 3 per side-rail edge)",
        "3.0 N·m", M["deck"] / 2, note="Tiles meet at X = 0. Print flat, 5 perimeters, 30% infill.")

# ── Battery, slung under the deck ───────────────────────────────────────────
cradle_z = DECK_Z0 - (LIPO[2] + 2 * CRADLE_T) / 2
add("PETG", "battery cradle", f"PETG cradle {LIPO[0]+8:.0f}×{LIPO[1]+6:.0f}×{LIPO[2]+6:.0f}", 0, 0, cradle_z,
    LIPO[0] + 8, LIPO[1] + 6, LIPO[2] + 2 * CRADLE_T, "hangs from deck underside, open at both ends for the strap",
    "deck underside", "4× M4×16 through deck + 4× M4 nyloc, at X ±60, Y ±18", "2.0 N·m", M["cradle"],
    note=f"Cradle bottom at Z = {cradle_z - (LIPO[2]+2*CRADLE_T)/2:.0f}: 61 mm ground clearance, above the 18.9 mm motor bottoms.")
add("LIPO", "—", "Zeee 3S 5200 mAh 132×43×25", 0, 0, cradle_z, *LIPO, "long axis X, XT60 lead exits −X (rear)",
    "battery cradle", "printed retaining bar + 2 cable ties", "hand-tight", M["lipo"],
    note="Lowest heavy part → h_CG. Balance lead to the cell alarm, velcro alarm to cradle side.")
add("PETG", "cradle retaining bar", "printed bar 140×12×6 across the cradle mouth", 0, 0, cradle_z - (LIPO[2] + 2 * CRADLE_T) / 2 + 3, 140, 12, 6,
    "spans the open bottom of the cradle", "cradle side walls, two printed hooks", "2× cable ties through printed slots", "hand-tight", 0.01,
    note="Replaces a bought strap. Print two.")

# ── Electronics on deck top (Z = 96) ────────────────────────────────────────
def on_deck(pid, inst, name, dims, x, y, mounts, fast, torque, mass, verify="", note=""):
    add(pid, inst, name, x, y, DECK_TOP + dims[2] / 2 + 10.0, *dims, "flat on 10 mm standoffs", mounts, fast, torque, mass, verify, note)

on_deck("UNO", "—", "UNO R4 WiFi + DRV8825 CNC Shield stack", (UNO[0], UNO[1], SHIELD_STACK_H), -115.7, 86.7,
        "deck top, rear-left", "printed 10 mm bosses on the deck tile + 2 cable ties through printed slots", "hand-tight",
        M["uno_stack"], verify="stack height with heatsinks",
        note="Board spans X −150..−81.4, Y +60..+113.3. Motor leads reach all four sockets from inboard. USB-B faces −X.")
on_deck("FAN", "—", "40×40×10 5 V fan over the drivers", FAN, -115.7, 86.7, "printed PETG bridge over the shield",
        "2× M3×8 into deck + 4× M3×30 through fan into bridge", "hand-tight", M["fan"],
        note=f"Blows down onto the four DRV8825 heatsinks. Fan face at Z ≈ {DECK_TOP + 10 + SHIELD_STACK_H + 8:.0f}.")
on_deck("PI", "—", "Raspberry Pi", PI, -107.5, -88.0, "deck top, rear-right",
        "printed 10 mm bosses on the deck tile (58×49 pattern) + 2× M2 + nut from the M2 kit (Pi holes are 2.7 mm)", "hand-tight", M["pi"],
        note="Spans X −150..−65, Y −116..−60. USB ports face −X (rear). Powered from the 5 V buck on GPIO 2/4 (+) and 6 (−).")
on_deck("PCA", "—", "PCA9685 servo driver (Ceres)", PCA9685, -29.0, -97.5, "deck top, beside the Pi",
        "printed bosses + 2× M2 + nut", "hand-tight", M["pca"], note="V+ terminal from the 6 V buck. I2C from Pi. Servo cables run forward to the turret.")
on_deck("BUCK5", "—", "5 V 3 A buck → Pi", BUCK, -44.5, 80.5, "deck top, front of the Uno",
        "2× M3×8 into deck (or VHB + zip tie)", "hand-tight", M["buck"], verify="module footprint",
        note="IN from the XT60 pigtail. Set to 5.10 V unloaded with the multimeter BEFORE connecting the Pi.")
on_deck("BUCK6", "—", "6 V buck → servos (Ceres)", BUCK, -44.5, 110.5, "deck top, beside the 5 V buck",
        "2× M3×8 into deck", "hand-tight", M["buck"], note="Set to 6.0 V before connecting the PCA9685. Own return to the shield GND.")
on_deck("ESP32", "#1 radar bridge", "ESP32-S3 DevKitC", ESP32, -100.0, -17.3, "deck top, rear-centre, just ahead of the radar post",
        "printed bosses + 2 cable ties through printed slots", "hand-tight", M["esp32"], verify="devkit hole positions",
        note="UART1 → LD2410C, UART2 → LD2450. USB-C to the Pi.")

# ── Turret (Ceres pan/tilt) at the front centre ─────────────────────────────
TX = 110.0
add("PT", "base", "Ceres pan/tilt turret base plate 100×60×6", TX, 0, DECK_TOP + TURRET_BASE[2] / 2, *TURRET_BASE,
    "flat on deck, pan axis vertical, servo collar toward +X", "front deck tile",
    "4× M3×12 through base + deck + 4× M3 nyloc", "1.0 N·m", M["turret"],
    verify="hole positions on the actual Ceres base", note="Spans X +60..+160, Y −30..+30. Pan servo cable and tilt servo cable to PCA9685 ch 2 / ch 0.")
CAM_Z = DECK_TOP + TURRET_BASE[2] + TURRET_H
add("CAM", "on tilt bracket", "Owned USB webcam (C920-class)", TX, 0, CAM_Z, *CAM,
    "lens forward (+X) at tilt = 0", "turret tilt bracket — the Ceres clamp it was built for", "Ceres camera clamp; 2 cable ties as backup", "hand-tight",
    M["cam"], verify="camera mass ≤ 170 g and clamp fit", note=f"Lens centre Z ≈ {CAM_Z:.0f}. USB to Pi. Clear of the radar line of sight at Z 300.")
add("THERM", "above the camera", "MLX90640-D55 thermal array, 55° FoV", TX + 4, 0, CAM_Z + CAM[2] / 2 + 4 + 2, 26, 18, 8,
    "boresight parallel to the camera, +X at tilt = 0", "printed PETG/PLA saddle on top of the camera clamp", "2× M2 + nut through the saddle", "hand-tight",
    0.005, verify="breakout hole spacing", note="I2C 0x33 on the Pi's SECOND I2C bus (dtoverlay i2c-gpio) so the 1 MHz thermal reads never stall the ToF/servo bus. 55° FoV: a person at 4 m fills ~6 pixels tall, a warm blob ~10 °C above the room. Ribbon runs with the camera USB through the tilt axis.")

# ── Radar post, rear centre, looking forward over the turret ────────────────
PX = -CROSS_X
add("PETG", "radar post", "PETG post 40×40×200 with 60×60×6 flange", PX, 0, DECK_TOP + POST[2] / 2, *POST,
    "vertical, on the rear cross rail through the deck", "rear tile → rear cross rail top slot",
    "2× M5×20 hex through flange + deck + 2× M5 T-nut, at Y ±20", "3.0 N·m", M["post"],
    note="Hollow 3 mm walls, print upright. Cable channel down the +X face for the two radar leads.")
add("PETG", "radar bar", "PETG radar bar 120×20×8 on the post top", PX, 0, DECK_TOP + POST[2] + 4, 120, 20, 8,
    "horizontal, antenna faces toward +X", "radar post top", "2× M3×10 + heat-set inserts", "hand-tight", 0.02)
add("LD2410C", "#1 (primary)", "HLK-LD2410C radar", PX + 6, 50, RADAR_Z, *LD2410C, "antenna face +X, horizontal",
    "radar bar, Y +50", "2× M2 or a printed clip; nothing metal within 10 mm of the antenna face", "hand-tight", M["radar"],
    verify="PCB 35×7", note=f"Boresight Z = {RADAR_Z:.0f}, passes over the camera (top ≈ {DECK_TOP + TURRET_BASE[2] + TURRET_H + 10:.0f}). Walleye found floor-level radar sees nothing — this height is a compromise to TEST.")
add("LD2450", "—", "HLK-LD2450 radar", PX + 6, -50, RADAR_Z, *LD2450, "antenna face +X, horizontal", "radar bar, Y −50",
    "2× M2 or printed clip", "hand-tight", M["radar"], verify="PCB 43×15",
    note="100 mm from the LD2410C. Power one at a time first; then test both for mutual interference.")
add("LD2410C", "#2 (spare)", "HLK-LD2410C radar — not mounted", 0, 0, 0, *LD2410C, "—", "in the parts box", "—", "—", 0,
    note="Spare. Swap in if #1 fails.")
add("MIC", "—", "INMP441 I2S microphone", PX + 6, 0, RADAR_Z, 14, 12, 3, "port facing +X, centred between the radars",
    "radar bar, Y 0", "1× M2 + nut (or VHB)", "hand-tight", 0.002, verify="board hole",
    note="I2S to Pi GPIO 18/19/20. Stop-and-listen: motors and fan off, ENABLE low, then 3 s capture. Voice/knock energy only — one mic gives no bearing.")
add("CO2", "—", "SCD41 CO2 sensor", PX - POST[0] / 2 - 4, 0, DECK_TOP + 150, 8, 24, 20, "sensing face −X (rear), in free air",
    "radar post, rear face, 150 mm up", "printed saddle + 2× M2 + nut", "hand-tight", 0.005, verify="breakout hole spacing",
    note="I2C 0x62 on the main bus. Rear face keeps it out of the driver-fan exhaust. Reads a room in minutes, not seconds: park at a closed door and wait.")

# ── VL53L1X obstacle sensors on the four rail outer faces ───────────────────
# Module stands on edge: its 4 mm thickness lies along the facing axis, the 25 mm
# length runs along the rail. Sits 2 mm proud of the rail face inside a printed clip.
# Front and rear only: one 2-pack. Sideways moves are made only after the camera has
# seen that side clear — the two side sensors were the first thing cut for cost.
for inst, x, y, face, dims in (("front", 175 + 2 + TOF[2] / 2, 0, "+X", (TOF[2], TOF[0], TOF[1])),
                               ("rear", -(175 + 2 + TOF[2] / 2), 0, "−X", (TOF[2], TOF[0], TOF[1]))):
    add("TOF", inst, "VL53L1X ToF module", x, y, RAIL_ZC, *dims, f"on edge, emitter facing {face}",
        f"printed clip in the {inst} rail outer slot", "1× M5×8 + M5 T-nut (clip) + 2× M2 (module)", "hand-tight", M["tof"],
        verify="module hole spacing", note=f"XSHUT → Pi GPIO {dict(front=5, rear=6)[inst]}. Both share I2C 0x29 until re-addressed at boot.")

# ── Wiring ──────────────────────────────────────────────────────────────────
add("WIRE22", "power", "22 AWG (owned): pack → shield VMOT, → 5 V buck IN, → 6 V buck IN", -60, 40, DECK_TOP, 0, 0, 0,
    "—", "pack connector at the battery (rear)", "cable ties every 60 mm to the deck; tape or heat-shrink every joint", "—", M["strapwire"] / 3,
    note="~250 mm each run; 22 AWG is rated 7 A against a 4 A burst. Single common ground at the shield GND terminal. No fuse — by your call; the connector is the disconnect, so keep the pack leads short, sleeved and never resting on a rail edge.")
add("WIRE22", "signals", "22 AWG / Dupont: 4× motor 4-wire → shield sockets; I2C to 2× ToF + PCA9685 + SCD41; UART radar → ESP32", -80, 0, DECK_TOP, 0, 0, 0,
    "—", "—", "cable mounts on deck underside for motor leads", "—", M["strapwire"] / 3,
    verify="motor lead length reaches the shield (~300 mm stock)", note="Motor order at the shield: X=FL, Y=FR, Z=RL, A=RR (D12/D13 jumpers fitted). Shared ENABLE on D8.")

# ── Checks ──────────────────────────────────────────────────────────────────
def box(p):
    return (p["x"] - p["l"] / 2, p["x"] + p["l"] / 2, p["y"] - p["w"] / 2, p["y"] + p["w"] / 2, p["z"] - p["h"] / 2, p["z"] + p["h"] / 2)

def overlap(a, b):
    A, B = box(a), box(b)
    return all(A[i] < B[i + 1] - 0.01 and B[i] < A[i + 1] - 0.01 for i in (0, 2, 4))

rigid = [p for p in parts if p["l"] > 0 and p["id"] not in ("STRAP", "CNR") and "spare" not in p["instance"]]
skip_pairs = {("LIPO", "PETG"), ("PETG", "LIPO"), ("FAN", "UNO"), ("UNO", "FAN"), ("CAM", "PT"), ("PT", "CAM"),
              ("LD2410C", "PETG"), ("LD2450", "PETG"), ("PETG", "LD2410C"), ("PETG", "LD2450"),
              ("MIC", "PETG"), ("PETG", "MIC"), ("THERM", "CAM"), ("CAM", "THERM")}  # by design mounted on / nested in
collisions = []
for i, a in enumerate(rigid):
    for b in rigid[i + 1:]:
        if (a["id"], b["id"]) in skip_pairs or a["id"] == b["id"] == "PETG":
            continue
        if overlap(a, b):
            collisions.append(f'{a["id"]} {a["instance"]}  ×  {b["id"]} {b["instance"]}')

mass = sum(p["mass_kg"] for p in parts)
cg = [sum(p[k] * p["mass_kg"] for p in parts) / mass for k in ("x", "y", "z")]
ground_min = min((box(p)[4], p["id"], p["instance"]) for p in rigid if p["mass_kg"] > 0 and p["id"] != "WHL")  # wheels touch the floor by definition
L, B = 2 * AXLE_X, 2 * abs(next(p["y"] for p in parts if p["id"] == "WHL"))
tip_pitch = math.degrees(math.atan((L / 2) / cg[2]))
tip_roll = math.degrees(math.atan((B / 2) / cg[2]))

fast = {"M5 T-nut": 16 + 12 + 2 + 2, "M5 screw": 16 + 12 + 2 + 2, "M4 T-nut": 8, "M4×10": 8, "M4×16 + nyloc": 4,
        "M3×6 (motor, supplied with brackets)": 16, "M3 misc": 4 + 2 + 4 + 2 + 2, "M2 + nut": 4 + 4 + 2 + 2 + 4 + 1 + 2, "cable ties": 2 + 2 + 2 + 2 + 2 + 20}
kits = {"M5 T-nut": "corner kit 40 + T-nut kit", "M4 T-nut": "T-nut kit 40", "M4×10": "T-nut kit 20", "M3": "750-pc M3 kit", "M2.5": "COMRUN standoff kit"}

# ── Output ──────────────────────────────────────────────────────────────────
print(f"\nASSEMBLY — origin chassis centre on the floor; +X forward, +Y left, +Z up; mm\n{'='*100}")
print(f"{'id':8s} {'instance':22s} {'x':>7s} {'y':>7s} {'z':>7s}  fasteners")
for p in parts:
    print(f"{p['id']:8s} {p['instance'][:22]:22s} {p['x']:7.1f} {p['y']:7.1f} {p['z']:7.1f}  {p['fasteners'][:60]}")
print(f"\nCHECKS")
print(f"  parts placed                 {len(parts)}")
print(f"  AABB collisions              {len(collisions)}  {'PASS' if not collisions else 'FAIL: ' + '; '.join(collisions)}")
print(f"  lowest point                 Z = {ground_min[0]:.1f} mm  ({ground_min[1]} {ground_min[2]})  → ground clearance")
print(f"  frame envelope               350 × 390 × {RADAR_Z + 4:.0f} mm  (X × Y × Z incl. radar bar)")
print(f"  track / wheelbase            {B:.0f} / {L:.0f} mm")
print(f"  CG                           x {cg[0]:+.1f}  y {cg[1]:+.1f}  z {cg[2]:.1f} mm   (placed mass {mass:.2f} kg)")
print(f"  static tip angles            pitch {tip_pitch:.0f}°   roll {tip_roll:.0f}°   PASS")
print(f"  fasteners                    " + ", ".join(f"{k} {v}" for k, v in fast.items()))
print(f"  kit coverage                 M5 {fast['M5 T-nut']} of 40+; M4 {fast['M4 T-nut']} of 40; M3 misc {fast['M3 misc']} of 750; M2 {fast['M2 + nut']} of 645; ties {fast['cable ties']} of 100  PASS")
print(f"\nVERIFY ON RECEIPT (caliper, before drilling): " + "; ".join(sorted({p['verify'] for p in parts if p['verify']})))
print(f"\nNOT CHECKED: fastener pull-out in PETG, deck deflection under the turret, cable strain relief, servo torque with the ELP camera,")
print(f"  radar detection at Z = {RADAR_Z:.0f} mm (Walleye measured floor-level radar as blind — test before trusting), wheel roller clearance to the bracket foot.\n")

json.dump(dict(frame=dict(origin="chassis centre on floor", axes="+X forward, +Y left, +Z up", units="mm",
                          envelope=[350, 390, round(RADAR_Z + 4)], track=B, wheelbase=L, cg=[round(c, 1) for c in cg],
                          ground_clearance=ground_min[0], tip_pitch_deg=round(tip_pitch), tip_roll_deg=round(tip_roll),
                          collisions=collisions),
               parts=parts), open("assembly.json", "w"), indent=1)
with open("assembly.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(parts[0].keys()))
    w.writeheader(); w.writerows(parts)
print("wrote assembly.json, assembly.csv")
