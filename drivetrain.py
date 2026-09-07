#!/usr/bin/env python3
"""Mecanum drivetrain sizing: can four JK42HS40-1704-13A steppers carry the rover?

Written out explicitly because no aeromech calculator covers a ground
drivetrain. Every input is labelled MEASURED (from a datasheet or listing),
ALLOCATED (a design budget to be replaced by a weighed part), or ASSUMED (an
engineering coefficient that must be tested). Acceptance: every margin ratio
>= MARGIN_REQUIRED with the load case that produced it.

    python3 drivetrain.py            # prints the report
    python3 drivetrain.py --json     # emits drivetrain.json for the BOM site
"""

import json
import math
import sys

# ── Motor: JKONGMOTOR drawing JK42HS40-1704-13A, spec rows 4–9 ──────── MEASURED
T_HOLD_NM = 4.2 * 0.0980665          # 4.2 kgf·cm holding torque → 0.4119 N·m
I_RATED_A = 1.7                      # peak per phase
R_OHM = 1.5                          # per phase at 20 °C
L_H = 2.3e-3                         # per phase
MOTOR_MASS_KG = 0.240
FULL_STEPS_PER_REV = 200

# ── Wheel and geometry ──────────────────────────────────────────────────────
WHEEL_D_M = 0.080                    # SmaringRobot 80 mm mecanum        MEASURED (listing)
WHEEL_R_M = WHEEL_D_M / 2
MECANUM_FACTOR = math.sqrt(2)        # roller axis at 45°: only F/√2 of each wheel's
                                     # tangential force acts along the travel direction
ETA_MECH = 0.85                      # roller bearings + coupling loss            ASSUMED
WHEELBASE_M = 0.30                   # contact centres, brackets under a 350 mm rail  ALLOCATED
TRACK_M = 0.43                       # wheels 5 mm off the bracket legs                 from assembly.py

# ── Environment ─────────────────────────────────────────────────────────────
G = 9.81
CRR_MECANUM_CARPET = 0.12            # plain wheel ~0.08; rollers add friction     ASSUMED
CRR_MECANUM_STRAFE = 0.15            # rollers rolling perpendicular               ASSUMED
RAMP_DEG = 5.0                       # ADA 1:12 = 4.76°, rounded up
A_CRUISE = 0.10                      # m/s²
A_RESPONSIVE = 0.30                  # m/s²
V_CRUISE = 0.10                      # m/s
V_MAX = 0.30                         # m/s
V_BUS_LOADED = 10.5                  # 3S at 3.5 V/cell under load                ASSUMED

# ── Stepper dynamic torque ─────────────────────────────────────────────────
# Pull-out torque at low speed is below holding torque: microstepping torque
# ripple, detent torque, resonance. Published NEMA 17 curves sit at 0.70–0.85
# of holding torque below ~100 rpm. 0.70 is the conservative end.   ASSUMED
K_DYN = 0.70

# ── Driver current capability (Pololu carrier guidance) ─────────────────────
DRIVERS = {
    "A4988, no cooling":            1.0,
    "A4988, heatsink + fan":        1.2,   # conservative; Pololu says ~1 A bare, more with cooling
    "DRV8825, no cooling":          1.5,
    "DRV8825, heatsink + fan":      1.7,   # carrier allows 2.2 A cooled; motor caps it at 1.7
}

# ── Acceptance ───────────────────────────────────────────────────────────────
MARGIN_REQUIRED = 1.25               # screening FoS on an unmeasured running torque

# ── Mass budget, kg ─────────────────────────────────────────────────────────
MASS_ITEMS = [
    # (name, kg, tag)
    ("4x JK42HS40 motors",                     4 * MOTOR_MASS_KG, "MEASURED"),
    ("4x 350 mm 2020 V-slot @ 0.50 kg/m",      4 * 0.350 * 0.50,  "ALLOCATED"),
    ("4x 80 mm mecanum wheel + 5 mm coupling", 4 * 0.150,         "ALLOCATED"),
    ("4x steel NEMA 17 bracket",               4 * 0.113,         "MEASURED"),   # listing: 1.5 lb per 6 = 113 g each
    ("Pan/tilt turret: 2x MG996R-class servo + bracket + PCA9685", 0.250, "ALLOCATED"),  # field-triage-rover hardware
    ("XL4015 5 A buck (owned): 6.0 V servo rail", 0.030,           "ALLOCATED"),
    ("USB power bank for Pi, compact 5000 mAh — WEIGH IT", 0.130, "ALLOCATED"),
    ("8x 2020 corner bracket + T-nuts",        8 * 0.012,         "ALLOCATED"),
    ("Uno + CNC Shield + 4 drivers + fan",     0.117,             "ALLOCATED"),
    ("Raspberry Pi + case",                    0.070,             "ALLOCATED"),
    ("HOOVO 3S 2200 mAh 80C shorty LiPo",       0.140,             "ALLOCATED"),  # listing says 138 g; VERIFY on receipt
    ("LD2410C + LD2450 + ESP32-S3 #1 (allocation kept)", 0.060,   "ALLOCATED"),
    ("Owned USB webcam (C920-class)",          0.162,             "ALLOCATED"),  # Ceres DESIGN.md envelope
    ("2x VL53L1X",                             0.010,             "ALLOCATED"),
    ("MLX90640 thermal + SCD41 CO2 + INMP441 mic", 0.025,         "ALLOCATED"),
    ("Printed parts: 4 tiles, cradle, post, bridge, clips, lock", 0.550, "ALLOCATED"),  # 4×80 g tiles at 20% infill
    ("Cable ties, tape",                       0.030,             "ALLOCATED"),
    ("22 AWG wiring + connectors",             0.080,             "ALLOCATED"),
]
FASTENER_ALLOWANCE = 0.15
MASS_CEILING_KG = 6.0                # sensitivity case from the earlier study


def design_mass():
    sub = sum(m for _, m, _ in MASS_ITEMS)
    return sub, sub * (1 + FASTENER_ALLOWANCE)


def wheel_torque(mass, crr, ramp_deg, accel):
    """Required tangential torque per wheel, N·m, for four mecanum wheels."""
    th = math.radians(ramp_deg)
    f_total = mass * G * (crr * math.cos(th) + math.sin(th)) + mass * accel
    return f_total * WHEEL_R_M * MECANUM_FACTOR / (4 * ETA_MECH), f_total


def available_torque(i_set):
    return T_HOLD_NM * (i_set / I_RATED_A) * K_DYN


def corner_rpm(i_set):
    """Full-torque step rate limit: current must swing -I→+I in half a step, dI/dt = V/L."""
    f_full = V_BUS_LOADED / (4 * L_H * i_set)          # full steps/s
    return f_full / FULL_STEPS_PER_REV * 60


def rpm_at(v):
    return v / (math.pi * WHEEL_D_M) * 60


def step_rate(v, microsteps):
    return FULL_STEPS_PER_REV * microsteps * rpm_at(v) / 60


def power(i_set, t_wheel, v, driver_r_on=0.64):
    """Bus power, W: copper + mechanical + driver conduction. Driver R = A4988 src+sink."""
    copper = 4 * R_OHM * i_set ** 2
    omega = v / WHEEL_R_M
    mech = 4 * t_wheel * omega
    driver = 4 * driver_r_on * i_set ** 2
    return copper + mech + driver, copper, mech, driver


def main(emit_json=False):
    sub, m_design = design_mass()
    cases = {
        "A  level cruise, a=0.1":        (CRR_MECANUM_CARPET, 0.0,      A_CRUISE),
        "B  level responsive, a=0.3":    (CRR_MECANUM_CARPET, 0.0,      A_RESPONSIVE),
        "C  5° ramp, a=0.3":             (CRR_MECANUM_CARPET, RAMP_DEG, A_RESPONSIVE),
        "D  strafe on carpet, a=0.3":    (CRR_MECANUM_STRAFE, 0.0,      A_RESPONSIVE),
    }
    out = {"design_mass_kg": round(m_design, 3), "subtotal_kg": round(sub, 3),
           "margin_required": MARGIN_REQUIRED, "cases": {}, "drivers": {}}

    print(f"\nMECANUM DRIVETRAIN — four JK42HS40-1704-13A, direct drive, 80 mm wheels")
    print(f"{'='*78}")
    print(f"\nMASS BUDGET")
    for name, m, tag in MASS_ITEMS:
        print(f"  {name:44s} {m:6.3f} kg  {tag}")
    print(f"  {'fasteners + wiring allowance 15%':44s} {sub*FASTENER_ALLOWANCE:6.3f} kg  ALLOCATED")
    print(f"  {'DESIGN MASS':44s} {m_design:6.3f} kg")
    print(f"  {'ceiling for sensitivity':44s} {MASS_CEILING_KG:6.3f} kg")

    print(f"\nREQUIRED TORQUE PER WHEEL   (T = F · r · √2 / (4 · η),  η = {ETA_MECH})")
    print(f"  {'load case':32s} {'F total N':>10s} {'T @ design':>11s} {'T @ 6 kg':>10s}")
    req = {}
    for name, (crr, ramp, a) in cases.items():
        t, f = wheel_torque(m_design, crr, ramp, a)
        t6, _ = wheel_torque(MASS_CEILING_KG, crr, ramp, a)
        req[name] = (t, t6)
        out["cases"][name.strip()] = {"force_N": round(f, 2), "torque_design_Nm": round(t, 4),
                                      "torque_6kg_Nm": round(t6, 4)}
        print(f"  {name:32s} {f:10.2f} {t:11.4f} {t6:10.4f}")

    print(f"\nAVAILABLE TORQUE   (T_hold {T_HOLD_NM:.4f} N·m × I/{I_RATED_A} × k_dyn {K_DYN})")
    print(f"  {'driver / current setting':32s} {'I A':>5s} {'T avail':>8s}  margins A / B / C / D at design mass   verdict")
    governing = None
    for drv, i_set in DRIVERS.items():
        t_av = available_torque(i_set)
        margins = [t_av / req[c][0] for c in cases]
        margins6 = [t_av / req[c][1] for c in cases]
        worst = min(margins)
        ok = worst >= MARGIN_REQUIRED
        out["drivers"][drv] = {"i_set_A": i_set, "t_avail_Nm": round(t_av, 4),
                               "margins_design": [round(x, 2) for x in margins],
                               "margins_6kg": [round(x, 2) for x in margins6],
                               "pass": ok}
        ms = " / ".join(f"{x:4.2f}" for x in margins)
        print(f"  {drv:32s} {i_set:5.2f} {t_av:8.4f}  {ms}   {'PASS' if ok else 'FAIL'}"
              f"   (6 kg worst {min(margins6):.2f})")
        if ok and governing is None:
            governing = drv

    print(f"\nSPEED–TORQUE VALIDITY   (k_dyn assumes operation well below the corner speed)")
    for i_set in (1.0, 1.5, 1.7):
        print(f"  I = {i_set:.1f} A: full-current corner {corner_rpm(i_set):6.0f} rpm"
              f"   vs operating {rpm_at(V_CRUISE):.0f}–{rpm_at(V_MAX):.0f} rpm"
              f"   ratio ≥ {corner_rpm(i_set)/rpm_at(V_MAX):.1f}")
    ke = T_HOLD_NM / I_RATED_A
    print(f"  back-EMF at {V_MAX} m/s: {ke * V_MAX / WHEEL_R_M:.2f} V of {V_BUS_LOADED} V bus — negligible")

    print(f"\nSTEP RATE   (1/16 microstep — one MS3 cap per DRV8825 — four wheels)")
    for v in (V_CRUISE, V_MAX):
        s = step_rate(v, 16)
        print(f"  {v:.1f} m/s = {rpm_at(v):5.1f} rpm → {s:6.0f} steps/s per wheel, {4*s:6.0f} total"
              f"   {'OK' if s < 5000 else 'EXCEEDS'} vs 5 000/axis ISR budget")

    print(f"\nPOWER AND ENDURANCE   (HOOVO 3S 2200 mAh shorty, 80% usable, bus {V_BUS_LOADED} V)")
    for i_set in (1.0, 1.5):
        t_b = req["B  level responsive, a=0.3"][0]
        p, cu, me, dr = power(i_set, t_b, V_CRUISE)
        i_bus = p / V_BUS_LOADED
        hours = 2.2 * 0.8 / i_bus
        print(f"  I = {i_set:.1f} A: copper {cu:5.1f} W + mech {me:4.1f} W + driver {dr:4.1f} W"
              f" = {p:5.1f} W → {i_bus:4.2f} A → {hours:4.1f} h motors only")
    print(f"  Holding at rest draws the copper + driver terms with zero motion. Cut ENABLE (D8)")
    print(f"  when parked; mecanum wheels on a level floor do not roll away.")

    print(f"\nSHAFT RADIAL LOAD   (NEMA 17 typical rating 28 N at 20 mm from the flange — ASSUMED, unverified for this motor)")
    n_static = m_design * G / 4
    overhang = 23.5                       # wheel centre to flange face, mm (bracket leg 3 + 5 clearance + half wheel)
    lever = overhang / 20.0               # rating is quoted at 20 mm; load scales with the lever
    for dyn, case in ((1.5, "indoor floors, small bumps"), (2.0, "kerbs, thresholds")):
        n = dyn * n_static * lever
        print(f"  static {n_static:.1f} N/wheel at {overhang:.1f} mm overhang; ×{dyn} {case:26s} = {n:.1f} N-equivalent"
              f"   margin {28/n:.2f}  {'PASS' if 28/n >= 1.0 else 'FAIL'}")
    print(f"  ← thinnest margin in the design. Indoor floors pass; a 20 mm threshold does not. Keep the wheel tight to the leg.")
    print(f"  Mount the wheel as close to the motor face as the coupling allows.")

    print(f"\nSTATIC STABILITY   (h_CG ≈ 0.10 m with battery on the deck — ALLOCATED)")
    h = 0.10
    print(f"  pitch tip {math.degrees(math.atan((WHEELBASE_M/2)/h)):.0f}°,"
          f"  roll tip {math.degrees(math.atan((TRACK_M/2)/h)):.0f}°   PASS")

    print(f"\n{'='*78}")
    print(f"VERDICT")
    if governing:
        print(f"  Four motors carry the rover at design mass {m_design:.2f} kg with the lowest passing")
        print(f"  setting: {governing}. Governing case is C (5° ramp): the smallest margin")
        print(f"  in every row. At the 6 kg ceiling, case C fails at every current — keep mass")
        print(f"  under ~5.2 kg or accept level floors only.")
    else:
        print(f"  NO setting passes. Redesign required.")
    print(f"\n  What fails first: a 5° ramp on carpet at 0.3 m/s². The motors stall silently —")
    print(f"  steppers do not slow down, they stop and lose position with no error.")
    print(f"  Next: measure pull-out torque at 24 rpm, 1.5 A, on the actual battery with a")
    print(f"  lever arm and the hanging scale. That one number retires K_DYN.")

    print(f"\nNOT ANALYSED: fatigue, buckling, impact, vibration, roller wear, uneven floors,")
    print(f"  wheel unloading, combined-slip mecanum behaviour, thermal equilibrium of motors")
    print(f"  or drivers, battery sag under stall, firmware timing. None of this is a")
    print(f"  substitute for the torque measurement above.\n")

    out["governing_setting"] = governing
    out["governing_case"] = "C  5° ramp, a=0.3"
    if emit_json:
        with open("drivetrain.json", "w") as f:
            json.dump(out, f, indent=1)
        print("wrote drivetrain.json")


if __name__ == "__main__":
    main(emit_json="--json" in sys.argv)
