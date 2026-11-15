#!/usr/bin/env python3
"""Emit CHATGPT-CHECK.md: a copy-paste prompt asking another model to re-check the build."""
import json
bom = json.load(open("bom-site/bom.json")); asm = json.load(open("assembly.json")); dt = json.load(open("drivetrain.json"))
items = bom["items"]; p = bom["prose"]
own = [i for i in items if i["status"] == "owned"]; buy = [i for i in items if i["status"] == "buy"]; opt = [i for i in items if i["status"] == "optional"]
L = []
L.append("I am building an indoor search rover for a hackathon. Please do an adversarial second check of this design: find anything that will NOT physically fit, NOT electrically connect, or NOT work as claimed. Be specific and cite which two parts conflict. Do not pad; if it all checks out, say so briefly.\n")
L.append("## Goal\nA 350 x 390 mm four-wheel mecanum rover on four owned NEMA 17 steppers, a pan/tilt turret carrying a webcam and a thermal array, two 24 GHz radars on a rear post, two ToF obstacle sensors, all run by a Raspberry Pi with an Arduino UNO R4 WiFi doing the step generation. Purpose: drive into a room and find people (thermal + camera in line of sight, radar behind doors/walls).\n")
L.append("## What I already own (not buying)")
for i in own: L.append(f"- {i['qty']}x {i['item']} — {i.get('note','')}")
L.append("\n## What I am buying (exact Amazon listings)")
for i in buy: L.append(f"- {i['qty']}x {i['item']} — ${i['qty']*i['price']:.2f} — https://www.amazon.com/dp/{i['asin']} — {i.get('note','')}")
L.append(f"\nBuy total: ${sum(i['qty']*i['price'] for i in buy):.2f}")
L.append("\n## Optional, not in the first order")
for i in opt: L.append(f"- {i['item']} — " + (f"https://www.amazon.com/dp/{i['asin']} — " if i.get('asin') else "") + f"{i.get('note','')}")
L.append("\n## The design, in numbers")
L.append("Frame: +X forward, +Y left, +Z up, origin at chassis centre on the floor, all mm. " + " ".join(p["fit"]))
fr = asm["frame"]
L.append(f"\nEnvelope {fr['envelope'][0]} x {fr['envelope'][1]} x {fr['envelope'][2]} mm, track {fr['track']:.0f}, wheelbase {fr['wheelbase']:.0f}, CG z = {fr['cg'][2]:.0f} mm, ground clearance {fr['ground_clearance']:.1f} mm, tip angles {fr['tip_pitch_deg']}/{fr['tip_roll_deg']} deg, {len(fr['collisions'])} bounding-box collisions in the placement check.")
L.append("\nKey placements (part centre x, y, z mm; fastener):")
for pp in asm["parts"]:
    if pp["id"] in ("MOT","WHL","BRK","LIPO","BANK","UNO","PI","PT","CAM","THERM","LD2410C","LD2450","TOF","XL4015","PCA") and "spare" not in pp["instance"]:
        L.append(f"- {pp['id']} {pp['instance']}: ({pp['x']:+.0f}, {pp['y']:+.0f}, {pp['z']:.0f}) — {pp['fasteners']}")
L.append(f"\nDrivetrain sizing at {dt['design_mass_kg']:.2f} kg design mass, 80 mm mecanum wheels, direct drive, JK42HS40-1704-13A (0.41 N-m holding, 1.7 A, 1.5 ohm, 2.3 mH): required torque per wheel — " + "; ".join(f"{k}: {v['torque_design_Nm']:.3f} N-m" for k, v in dt["cases"].items()) + ". Available = holding x (I/1.7) x 0.70 (assumed low-speed factor). Margins at 1.5 A on DRV8825: " + ", ".join(f"{v['margins_design'][2]:.2f} ramp" for k, v in dt["drivers"].items() if "DRV8825, no" in k) + " (acceptance 1.25). Step rate at 1/16: ~3,800 steps/s per wheel at 0.3 m/s.")
L.append("\n## Multimodal detection plan")
for x in p["fusion"]: L.append(f"- {x}")
L.append("\n## Electrical and interfaces as designed")
for m in p["mesh"]: L.append(f"- {m}")
L.append("\n## Power and connections")
for m in p["power"]: L.append(f"- {m}")
L.append("\n## Pin map")
for m in p["pins"]: L.append(f"- {m}")
L.append("\n## What I want from you")
L.append("1. Walk every mechanical interface above and say whether the two parts actually mate (bore vs shaft, bolt pattern vs holes, screw length vs stack, slot vs T-nut size). Flag anything nominal that could be wrong on the real part.\n2. Walk every electrical connection: voltage windows, current budgets (especially the Pi's USB ports and the servo rail), logic levels, I2C address clashes, grounds.\n3. Check the torque logic: is a 0.70 low-speed factor on holding torque a reasonable screening assumption for a 1.8-degree NEMA 17 at 24-72 rpm on 10.5 V with DRV8825 at 1/16 microstepping? What would you measure first?\n4. Tell me what is missing from the buy list that I will discover I need on build day.\n5. Rank the three most likely reasons this rover does not move on the first try.")
open("CHATGPT-CHECK.md", "w").write("\n".join(L)); print(f"CHATGPT-CHECK.md: {len(L)} lines, {sum(len(x) for x in L)} chars")
