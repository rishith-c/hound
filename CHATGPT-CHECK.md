I am building an indoor search rover for a hackathon. Please do an adversarial second check of this design: find anything that will NOT physically fit, NOT electrically connect, or NOT work as claimed. Be specific and cite which two parts conflict. Do not pad; if it all checks out, say so briefly.

## Goal
A 350 x 390 mm four-wheel mecanum rover on four owned NEMA 17 steppers, a pan/tilt turret carrying a webcam and a thermal array, two 24 GHz radars on a rear post, two ToF obstacle sensors, all run by a Raspberry Pi with an Arduino UNO R4 WiFi doing the step generation. Purpose: drive into a room and find people (thermal + camera in line of sight, radar behind doors/walls).

## What I already own (not buying)
- 5x JK42HS40-1704-13A NEMA 17 stepper — Four drive wheels, fifth spare. 0.41 N·m holding, 1.7 A, 240 g each, 5 mm flatted shaft.
- 1x Arduino UNO R4 WiFi (from Walleye) — The CNC Shield V3 stacks on the R4's headers; 5 V logic, same pinout. Custom timer-ISR firmware, not GRBL. Frees up when the Walleye rail retires.
- 1x TB6600 stepper driver — Spare. No fifth axis in this design.
- 1x 11.1 V gel-blaster LiPo + its charger — Backup pack. The Gens ace is primary. If you ever run this one: read its label, confirm the connector, and never charge it on a two-wire wall brick.
- 1x USB power bank for the Pi — compact, ≤ 130 g, 5 V ≥ 3 A output — WEIGH IT. A 5,000 mAh bank (~130 g) fits the mass budget only with the drivers at 1.7 A and the fan running; a 10,000–20,000 mAh brick (300–400 g) fails the ramp case at every current. Needs a real 3 A output or the Pi throws undervoltage with the camera and thermal array on. Keeps the Pi isolated from motor-bus noise and from a mis-set buck.
- 3x HiLetgo XL4015 5 A adjustable buck converters, 3 pcs (4–38 V in, 1.25–36 V out) — One set to 6.0 V feeds the PCA9685 V+ for the servos: two MG996R at stall can ask for ~5 A together, which is why this takes the servo rail and the LM2596 does not. TRIM WITH A MULTIMETER BEFORE CONNECTING — ships at a random output. Two spare.
- 5x DROK LM2596 adjustable buck converters, pack of 5 (3.2–35 V in, 1.25–34 V out) — Spare. Outranked by the XL4015 for the servo rail (2–3 A vs 5 A). One trimmed to 5.10 V is the fallback Pi supply if the power bank ever drops out.
- 1x Multimeter (owned) — Sets the XL4015 to 6.0 V before anything is connected, and checks the pack: 12.6 V full, stop driving at 11.1 V (3.7 V/cell), never below 9.9 V. Check before and after every run — there is no alarm on the balance lead.
- 1x Three-pin switch — Not wired in until its DC rating is read and is ≥ 10 A. Until then the T-plug is the switch.
- 1x Balance charger (owned) — Yours. Charge the Gens ace at 2.6 A = 0.5 C on the LiPo program with the balance lead plugged in. If its output is banana plugs, you need an XT60 charge lead — that is the optional extension below.
- 1x Raspberry Pi — Camera, radar processing, servo control, interface. Model still unknown — affects the 5 V budget.
- 1x Your USB webcam (C920-class, ~162 g) on the Ceres tilt bracket — The turret was built for it. Person detection with MobileNet-SSD on the Pi at ~25 fps. If it turns out heavier than 170 g, the ELP board camera (B00KA80N9U, 50 g, $22.49) is the fallback.
- 2x HLK-LD2410C 24 GHz radar — Primary presence sensor; sees a motionless person. One on the post, one spare.
- 1x HLK-LD2450 24 GHz radar — x/y of moving targets only. On the post 100 mm from the LD2410C.
- 3x ESP32-S3 DevKitC (N16R8) — One bridges both radar UARTs to the Pi over USB. Two free for WiFi CSI experiments.
- 1x CP2102 USB-UART — Bench setup only. Check it is 3.3 V logic before touching a radar.
- 1x Ceres pan/tilt turret: 2× MG996R-class servos + bracket + 100 × 60 base — From the farm rover. Bolts to the front deck tile at X +110. Camera on the tilt bracket.
- 1x PCA9685 16-channel servo driver (Ceres) — I2C 0x40 from the Pi. Tilt ch 0, pan ch 2, as in turret_duet.ino.
- stockx Dupont leads, 22 AWG wire — Everything, including the power branches: the wire calc puts 22 AWG at a 7 A limit against a 4 A burst — 18 AWG was comfort, not need. I2C, UART, XSHUT, motor lead extensions.

## What I am buying (exact Amazon listings)
- 1x SmaringRobot 4× 80 mm mecanum wheels with 5 mm couplings — $29.99 — https://www.amazon.com/dp/B0DWSWQV4T — Two left-hand, two right-hand. Coupler fits the motor's 5 mm flatted shaft; do not print a hub.
- 1x Anndason 6× steel NEMA 17 L-brackets with screws — $16.99 — https://www.amazon.com/dp/B073QW9RPZ — Four used, two spare. 3 mm steel, 113 g each. Base slots are 4.3 mm: M4 T-nuts, not M5.
- 1x VICHSAMWY 4× 350 mm 2020 V-slot aluminium extrusion — $16.59 — https://www.amazon.com/dp/B099M9DMSL — All four used at full length. Nothing to cut.
- 1x TOCLUX 20× 2020 corner brackets with M5 screws and T-nuts — $14.99 — https://www.amazon.com/dp/B0F1B85397 — Eight for the frame corners; the rest and the 40 M5 T-nuts cover deck and post attachment.
- 1x Bemaka 2020 T-nut kit, M3/M4/M5, with M4×10 and M4×12 screws — $13.99 — https://www.amazon.com/dp/B0FQ55VFDK — The M4 T-nuts and M4×10 screws hold the motor brackets to the rails.
- 1x CNC Shield V3 kit with 4× DRV8825 drivers and heatsinks — $15.99 — https://www.amazon.com/dp/B0B24YS695 — Required, not optional: A4988 fails the ramp case. SIX JUMPERS: D12 and D13 on the A-axis header (gives the fourth wheel its own STEP/DIR — bridging X/Y/Z there clones another wheel instead); MS3 only under each of the four drivers for 1/16 microstepping on DRV8825 (an A4988 needs all three — most tutorials show that, and it is wrong for these). Leave EN/GND OFF so D8 controls enable. Insert each driver with its EN pin on the shield's EN mark — backwards destroys it; the trimpot sits on the opposite side from an A4988. Vref = 5 × Rsense × I. Check the kit includes jumper caps.
- 1x SIXQJZML 2× 40 × 40 × 10 mm 5 V fans — $5.99 — https://www.amazon.com/dp/B0DY6GQMJX — One over the drivers on a printed bridge, one spare. Powered from the 5 V buck.
- 1x Gens ace G-Tech Bashing 2200 mAh 11.1 V 3S 35C LiPo, XT60 — $25.99 — https://www.amazon.com/dp/B0C2CTZPMZ — The good pack: honest capacity, low internal resistance, XT60, and a G-Tech health tag. 35C is 77 A against a 4 A need. ~190 g (verify). At ~2.8 A total draw it runs the rover about 35–40 minutes; a second one doubles a demo day. Strapped low under the deck.
- 1x Padarsey 2 pairs XT60 14 AWG pigtails — $6.99 — https://www.amazon.com/dp/B07BF8154S — The rover-side pigtail splits into the 22 AWG branches. The plug is the disconnect.
- 1x MLX90640-D55 thermal camera, 32×24, 55° FoV — $66.30 — https://www.amazon.com/dp/B0FQHVSX91 — The biggest gap in the design. A body is ~10 °C above a room and unmistakable in 768 pixels, in darkness or smoke. Rides beside the camera on the tilt bracket so the turret sweeps thermal and visible together. Cannot see through walls — that stays the radar's job.
- 1x DWEII 2× VL53L1X time-of-flight distance modules — $14.99 — https://www.amazon.com/dp/B09V4DS888 — Two sensors: front and rear, each in a printed clip on the rail's outer slot. Side sensors were cut for cost — strafe only after the camera has seen that side clear.
- 1x Fgruh 750-piece M3 screw, nut and washer assortment — $9.99 — https://www.amazon.com/dp/B0FGV5FCBN — 16× M3×6 motor screws, turret base bolts, buck and fan-bridge screws.
- 1x 645-piece M2 stainless screw, nut and washer set, button head — $6.99 — https://www.amazon.com/dp/B0DFWWFY4Q — Radar, ToF and camera boards have ~2 mm holes that no other kit covers. 16 screws used.
- 1x ALLWIN 100 cable mounts + 100 cable ties — $6.99 — https://www.amazon.com/dp/B0F9T5G2J5 — Board retention through printed slots (no standoffs), motor leads under the deck, power branches on top, and two ties hold the battery in its printed cradle bar.

Buy total: $252.77

## Optional, not in the first order
- LINSYRC 2× XT60 M-F 30 cm 14 AWG extensions — https://www.amazon.com/dp/B09CT5VGPW — Charger lead: only if your balance charger has banana-plug outputs and no XT60 lead. Cut one end, fit the bananas.
- OVERTURE black PETG 1 kg 1.75 mm — https://www.amazon.com/dp/B07PGYHYV8 — PLA you already have is fine for the deck, cradle, post and clips; PETG only if you have nothing loaded.
- Kingston Canvas Select Plus 64 GB microSD, A1 — https://www.amazon.com/dp/B07YGZQ4H8 — Only if your Pi has no card.
- Ginsco 580-piece heat-shrink assortment — https://www.amazon.com/dp/B01MFA3OFA — Electrical tape works for a hackathon; this is nicer.
- SCD41 CO2 + temperature + humidity module, I2C — https://www.amazon.com/dp/B0F6MRMNLH — The SAR literature's area-narrowing sensor: a person in a closed room raises CO2 hundreds of ppm above 400 baseline. Slow (minutes) and only meaningful in enclosed spaces. On the rear of the radar post in free air.
- 3× INMP441 I2S microphone modules with Dupont cables — https://www.amazon.com/dp/B0GSZJFJVM — Voice and knocking, the way rescue listening devices work. One mic gives energy only, no bearing; the other two in the pack could later give a left/right bearing. Stop-and-listen protocol: motors off, three-second capture.
- MEIYA hanging scale — https://www.amazon.com/dp/B0GGHDNZWJ — The torque measurement: lever on the shaft, scale on the lever, T = F × arm.
- Jiavarry 150 mm digital caliper — https://www.amazon.com/dp/B08Y8M54M9 — Needed for every VERIFY dimension before drilling the deck. Skip only if you own one.
- Q-MING soldering iron kit — https://www.amazon.com/dp/B087767KNW — 
- AMTOVL metric hex key set — https://www.amazon.com/dp/B0CJBRYQF3 — 2.5 / 3 / 4 mm for M3 / M4 / M5.
- DOWELL wire strippers — https://www.amazon.com/dp/B08Y6GDS61 — 

## The design, in numbers
Frame: +X forward, +Y left, +Z up, origin at chassis centre on the floor, all mm. Frame: two side rails along X with outer faces at Y = ±195; two cross rails along Y butted between them with outer faces at X = ±175. Rails sit at Z 71–91. Eight corner brackets, one top and one bottom at each joint, M5 T-nuts, 3.0 N·m maximum or the slot deforms. Drive: each steel L-bracket goes inverted under a side rail near its end, foot against the rail underside on two M4 T-nuts, leg hanging down flush with the rail's outer face. The motor bolts to the inboard side of the leg with four M3×6 at 0.8 N·m (aluminium threads — the full 1.1 N·m an M3 can take will strip the flange). Shaft through the leg, coupler on the flat with blue threadlocker, wheel on the coupler. Axle at X = ±125, Z = 40. Motor body bottom at Z = 18.9 mm: that is your ground clearance. Mecanum handedness: front-left and rear-right take the left-hand wheels, front-right and rear-left the right-hand. Check from above — the rollers on top of each wheel should point toward the chassis centre, forming an X. Deck: two printed tiles 170 × 350 × 5 on the rail tops, held by the corner kit's M5×8 screws into M5 T-nuts — the screw holes are counterbored so only 3 mm of tile sits under each head and the 8 mm screw still gets 5 mm of T-nut. Every board sits on 10 mm bosses printed into the tile and is held by cable ties through printed slots (the Pi and PCA9685 take M2 screws, their holes being 2.7 mm). Battery cradle hangs under the deck centre on four M3×12 with nuts from the M3 kit — 179 g is nothing for four M3s — with a printed retaining bar and two cable ties instead of a strap; battery bottom at Z 65. R4/shield stack rear-left, Pi rear-right, XL4015 ahead of the R4, PCA9685 beside the Pi, ESP32 rear-centre, power bank centred over the cradle. Turret base at X = +110 on four M3×16. Radar post on two M4×12 into M4 T-nuts in the rear rail, flange and tile counterbored so the 12 mm screw reaches. Thermal array in a printed saddle on the camera clamp. Every screw on the rover comes from the two kits already on the list.

Envelope 350 x 390 x 304 mm, track 440, wheelbase 250, CG z = 80 mm, ground clearance 18.9 mm, tip angles 57/70 deg, 0 bounding-box collisions in the placement check.

Key placements (part centre x, y, z mm; fastener):
- BRK FL: (+125, +178, 70) — 2× M4×10 hex + 2× M4 T-nut (bottom slot)
- MOT FL (motor 1): (+125, +172, 40) — 4× M3×6 socket head through leg into flange
- WHL FL (left-hand): (+125, +220, 40) — coupler grub screw on the shaft flat + blue threadlocker; wheel to coupler per kit hardware
- BRK FR: (+125, -178, 70) — 2× M4×10 hex + 2× M4 T-nut (bottom slot)
- MOT FR (motor 2): (+125, -172, 40) — 4× M3×6 socket head through leg into flange
- WHL FR (right-hand): (+125, -220, 40) — coupler grub screw on the shaft flat + blue threadlocker; wheel to coupler per kit hardware
- BRK RL: (-125, +178, 70) — 2× M4×10 hex + 2× M4 T-nut (bottom slot)
- MOT RL (motor 3): (-125, +172, 40) — 4× M3×6 socket head through leg into flange
- WHL RL (right-hand): (-125, +220, 40) — coupler grub screw on the shaft flat + blue threadlocker; wheel to coupler per kit hardware
- BRK RR: (-125, -178, 70) — 2× M4×10 hex + 2× M4 T-nut (bottom slot)
- MOT RR (motor 4): (-125, -172, 40) — 4× M3×6 socket head through leg into flange
- WHL RR (left-hand): (-125, -220, 40) — coupler grub screw on the shaft flat + blue threadlocker; wheel to coupler per kit hardware
- LIPO —: (+0, +0, 76) — printed retaining bar + 2 cable ties
- UNO —: (-116, +87, 128) — printed 10 mm bosses on the deck tile + 2 cable ties through printed slots
- PI —: (-108, -88, 116) — printed 10 mm bosses on the deck tile (58×49 pattern) + 2× M2 + nut from the M2 kit (Pi holes are 2.7 mm)
- PCA —: (-29, -98, 112) — printed bosses + 2× M2 + nut
- BANK → Pi: (+0, +0, 114) — printed lip on the deck tile + 2 cable ties through printed slots
- XL4015 → servos 6.0 V: (-44, +110, 115) — printed bosses + 2 cable ties
- PT base: (+110, +0, 99) — 4× M3×16 through base (6 mm) + deck (5 mm) + 4× M3 nut (M3 kit)
- CAM on tilt bracket: (+110, +0, 212) — Ceres camera clamp; 2 cable ties as backup
- THERM above the camera: (+114, +0, 230) — 2× M2 + nut through the saddle
- LD2410C #1 (primary): (-159, +50, 300) — 2× M2 or a printed clip; nothing metal within 10 mm of the antenna face
- LD2450 —: (-159, -50, 300) — 2× M2 or printed clip
- TOF front: (+179, +0, 81) — 1× M5×8 + M5 T-nut (clip) + 2× M2 (module)
- TOF rear: (-179, +0, 81) — 1× M5×8 + M5 T-nut (clip) + 2× M2 (module)

Drivetrain sizing at 5.13 kg design mass, 80 mm mecanum wheels, direct drive, JK42HS40-1704-13A (0.41 N-m holding, 1.7 A, 1.5 ohm, 2.3 mH): required torque per wheel — A  level cruise, a=0.1: 0.109 N-m; B  level responsive, a=0.3: 0.126 N-m; C  5° ramp, a=0.3: 0.199 N-m; D  strafe on carpet, a=0.3: 0.151 N-m. Available = holding x (I/1.7) x 0.70 (assumed low-speed factor). Margins at 1.5 A on DRV8825: 1.28 ramp (acceptance 1.25). Step rate at 1/16: ~3,800 steps/s per wheel at 0.3 m/s.

## Electrical and interfaces as designed
- Motor shaft 5 mm with flat → wheel-kit 5 mm coupler (grub screw on the flat) → 80 mm mecanum hub. Same nominal bore on both sides; verify the coupler's set screw lands on the flat.
- Motor 31 mm × 31 mm M3 pattern, 22 mm pilot → Anndason bracket (31 mm pattern, 3 mm steel, M3 screws in the box). Bracket 4.3 mm foot slots → M4×10 + M4 T-nut (T-nut kit) → 2020 rail 6 mm slot. M5 does not fit the bracket; M4 does.
- 2020 rail ↔ 2020 rail → TOCLUX 17×20 corner brackets, M5×8 + M5 T-nut (corner kit). Rail ↔ printed deck → M5×8 + M5 T-nut into the top slot, counterbored tiles. Rail ↔ printed radar post → M4×12 + M4 T-nut, counterbored flange.
- Deck → boards: printed 10 mm bosses; Uno R4 and ESP32 held by cable ties through slots; Pi (2.7 mm holes) and PCA9685 by M2 + nut. Deck → battery cradle: M3×12 + nut. Deck → Ceres turret base: M3×16 + nut through the base's existing M3 clearance holes.
- Gens ace XT60 → Padarsey XT60 pigtail → two 22 AWG branches → CNC Shield VMOT screw terminal (8–45 V, DRV8825 range) and XL4015 IN (4–38 V). 12.6 V charged pack sits inside both windows.
- XL4015 OUT 6.0 V → PCA9685 V+ terminal → MG996R servos (4.8–7.2 V). PCA9685 VCC ← Pi 3.3 V; I2C 0x40 ← Pi GPIO 2/3 at 3.3 V. Nothing on this rail sees pack voltage.
- Power bank 5 V/3 A → Pi USB-C. Pi USB-A → UNO R4 USB-C (5 V logic, CNC Shield V3 is a 5 V shield: pinout matches). Pi USB-A → ESP32-S3 USB-C. Pi USB-A → webcam. Four Pi USB ports, four loads, ~950 mA of a 1.2 A budget.
- CNC Shield 5 V header → 40 mm 5 V fan (150 mA). ESP32-S3 5 V pin → LD2410C and LD2450 VCC (5 V, ~200 mA peak); their UART is 3.3 V, matching the ESP32-S3 GPIO. Radar TX → ESP32 RX and vice versa, 256000 baud.
- Pi I2C-1 (3.3 V): PCA9685 0x40, VL53L1X ×2 at 0x29 re-addressed via XSHUT on GPIO 5/6, SCD41 0x62 — no address clashes. Pi I2C-3 (i2c-gpio overlay): MLX90640 0x33 alone at 1 MHz. VL53L1X and MLX90640 modules run on 3.3 V from the Pi header.
- Pi I2S GPIO 18/19/20 → INMP441 (3.3 V). Pi ↔ R4 serial over the same USB cable that powers it.
- Firmware boundary: R4 runs the four-axis step generator (timer ISR, D2–D7 + D12/D13, enable D8) and takes velocity commands over serial; the Pi runs everything else. Nothing on the shield is driven by GRBL.

## Power and connections
- Gens ace pack -> XT60 pigtail -> two 22 AWG branches: shield VMOT (four DRV8825 -> four motors) and XL4015 IN for the servo rail. 22 AWG is rated 7 A against a 4 A burst here. No fuse, by your call — the XT60 is the disconnect, so keep the pack leads short and sleeved.
- Power bank -> Pi USB-C. The bank must hold 5 V at 3 A: a 2.4 A bank browns out the moment the camera, thermal array and ESP32 are all drawing. Pi USB-A -> UNO R4 USB-C for logic power and serial. Fallback if the bank misbehaves: an XL4015 or LM2596 trimmed to 5.10 V on GPIO 2/4 and 6.
- XL4015 OUT -> PCA9685 V+ terminal. Set to 6.0 V with a multimeter before connecting. Its 5 A rating covers both servos stalling at once (~2.5 A each); an LM2596 would sag there. Servo current returns through the PCA9685 terminal, never through a USB ground.
- Fan -> the shield's 5 V / GND header pins (the R4 passes the Pi's USB 5 V through), 150 mA. Radars -> the ESP32-S3's 5 V pin, also USB pass-through from the Pi. The Pi 4's USB ports share a 1.2 A budget: webcam ~250 mA + ESP32 with both radars ~400 mA + R4 with fan ~300 mA ≈ 950 mA. Inside it, but nothing else goes on the Pi's USB. If the Pi shows the lightning bolt, move the radars to a third LM2596 trimmed to 5.0 V.
- Pi -> camera by USB. Pi -> ESP32-S3 by USB-C; the ESP32 bridges both radar UARTs. Radars take 5 V power and 3.3 V UART signalling.
- Four VL53L1X share I2C only after XSHUT (GPIO 5, 6, 13, 19) assigns unique addresses at boot. PCA9685 is on the same I2C bus at 0x40.
- Single common ground at the shield GND terminal. Never put LiPo voltage on a logic rail.

## Pin map
- R4 / CNC Shield — X (FL): STEP D2, DIR D5 · Y (FR): STEP D3, DIR D6 · Z (RL): STEP D4, DIR D7 · A (RR): STEP D12, DIR D13 · ENABLE all four: D8 (LOW = on) · fan: shield 5 V / GND header.
- Pi I2C-1 (GPIO 2/3): PCA9685 0x40, VL53L1X front and rear (0x29 until re-addressed; XSHUT on GPIO 5 and 6), SCD41 0x62. Pi I2C-3 via dtoverlay i2c-gpio: MLX90640 0x33 alone, so its 1 MHz reads never stall the servo bus.
- Pi I2S (GPIO 18 BCLK, 19 LRCLK, 20 DIN): INMP441. Pi USB: R4 (serial + power), ESP32-S3 (serial + power), webcam. Pi power: bank on USB-C.
- ESP32-S3: UART1 (GPIO 17/18) ↔ LD2410C TX/RX crossed at 256000 baud; UART2 (GPIO 15/16) ↔ LD2450 crossed at 256000. Both radars 5 V from the devkit's 5 V pin, 3.3 V signalling, nothing metal within 10 mm of the antenna faces.
- PCA9685: tilt on ch 0, pan on ch 2, as in the Ceres turret_duet firmware. V+ from the XL4015 at 6.0 V, VCC from the Pi 3.3 V, GND to both.

## What I want from you
1. Walk every mechanical interface above and say whether the two parts actually mate (bore vs shaft, bolt pattern vs holes, screw length vs stack, slot vs T-nut size). Flag anything nominal that could be wrong on the real part.
2. Walk every electrical connection: voltage windows, current budgets (especially the Pi's USB ports and the servo rail), logic levels, I2C address clashes, grounds.
3. Check the torque logic: is a 0.70 low-speed factor on holding torque a reasonable screening assumption for a 1.8-degree NEMA 17 at 24-72 rpm on 10.5 V with DRV8825 at 1/16 microstepping? What would you measure first?
4. Tell me what is missing from the buy list that I will discover I need on build day.
5. Rank the three most likely reasons this rover does not move on the first try.