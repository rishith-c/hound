#!/usr/bin/env python3
"""
fetch_assets.py — downloads the real part models the film uses from step.parts (https://www.step.parts), as GLB meshes.

    python3 anim/fetch_assets.py && python3 anim/meshprep.py

Provenance (step.parts part ids; pages at https://www.step.parts/parts/<id>):
    raspberry_pi_4_model_b                   Raspberry Pi 4 Model B
    arduino_uno_r4_wifi                      Arduino UNO R4 WiFi (ABX00087)
    futaba_s3003                             standard servo (stands in for the MG996R: same case)
    stepper_motor_nema17_l0040_single_shaft  NEMA 17, 40 mm body (the JK42HS40)
    axial_fan_40x40x10_simple                40 × 40 × 10 fan
    profile_2020_b_slot6_a_l100              2020 B-type slot-6 extrusion, 100 mm sample (stretched per rail)
step.parts' "mecanum_wheel_d80" is a plain cylinder, so the wheels are modelled in build_render.py instead
(hub, side plates, nine 45° barrel rollers).
"""
import json, os, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
IDS = ["raspberry_pi_4_model_b", "arduino_uno_r4_wifi", "futaba_s3003", "stepper_motor_nema17_l0040_single_shaft",
       "axial_fan_40x40x10_simple", "profile_2020_b_slot6_a_l100"]

if __name__ == "__main__":
    out = os.path.join(HERE, "assets"); os.makedirs(out, exist_ok=True)
    for i in IDS:
        rec = json.load(urllib.request.urlopen("https://api.step.parts/v1/parts/" + i, timeout=30))
        rec = rec.get("item", rec)
        dst = os.path.join(out, i + ".glb")
        urllib.request.urlretrieve(rec["glbUrl"], dst)
        print("%-42s %6.2f MB  %s" % (i, os.path.getsize(dst) / 1e6, rec["pageUrl"]))
