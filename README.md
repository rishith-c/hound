# Hound

An indoor search rover that finds people it cannot see. Four senses, two tracks, one honest sentence per station.

- **Hidden track (RF):** HLK-LD2410C 24 GHz radar for range and breathing-band periodicity through drywall; ESP32-S3 WiFi CSI receivers off the rover for bistatic presence.
- **Visible track (optical):** webcam with MobileNet-SSD and an MLX90640 thermal array on a tilt turret, associated by bearing.
- **Fusion:** two-track Bayesian log-odds with calibrated likelihood tables. Labels run from NOTHING to PERSON VISIBLE. The word "alive" appears nowhere: a radar scores repetition, not life.
- **Drivetrain:** four JK42HS40 NEMA 17s on 80 mm mecanum wheels, DRV8825s at 1/32, 30 kHz step interrupt on an UNO R4, 530 mm/s, body-vector ramps. Raspberry Pi 4 on top, remote control through a Cloudflare tunnel.

Named for the rescue dog: it stops, goes quiet, and listens.

| Where | What |
|---|---|
| [rover-amazon-bom.vercel.app](https://rover-amazon-bom.vercel.app) | BOM, placements, wiring checks, build order, cost |
| [manual.html](https://rover-amazon-bom.vercel.app/manual.html) | Assembly manual |
| [wiring.html](https://rover-amazon-bom.vercel.app/wiring.html) | Wiring diagrams (WireViz, cross-checked against wiring.py) + GPT prompt |
| [rover3d/](https://rover-amazon-bom.vercel.app/rover3d/) | Interactive 3D rover: every placement, every wire, real part artwork; click to unplug |
| [sensing/report.html](https://rover-amazon-bom.vercel.app/sensing/report.html) | Sensing simulation results |
| `drivetrain.py` `assembly.py` `wiring.py` | The verification sources of truth: torque, placement, netlist |
| `dc_drive.py` | What a DC-gearmotor Hound would need and cost: TT motors fail, a JGA25-370 12 V 1:45 passes; priced against the stepper build |
| `sensing/thermal_arrays.py` | Whether a cheaper thermal array still finds a person: the MLX90641 (−$12.55) does, the AMG8833 (−$41.42) loses a lying person past 2.8 m |
| `sensing/` | Prior art, sensor models, vitals, fusion, station sequencer, Monte Carlo |
| `firmware/r4_drive` | The drive firmware (v1.0 tag `v1.0-best-drive`) |
| `pi/` | Pi-side code, deploy and flash scripts |
| `cad/` | Deck tiles for an Ender 3 and the full-plate DXF |
| `tests/` | `python3 -m pytest tests` — the R4 firmware itself compiled on the host (turret, show, drive ramps, watchdog), remote recorder and API (stub R4), cross-file consistency, wiring gate, drivetrain identities, radar ports |

## The remote

`pi/rover/web.py` runs on the Pi as the `rover-web` service; `rover-tunnel` gives it a public Cloudflare link (`sh ~/rover/tunnel_url.sh` on the Pi prints it, key included; it changes on every reboot). Deploy with `pi/deploy.sh`, flash the R4 with `pi/flash_r4.sh` — both over the LAN.

- **Drive:** hold-to-drive pad, W A S D / Q E keys, speed slider, crab circle, per-motor test panel. The R4 stops by itself 400 ms after the Pi goes quiet.
- **Turret:** nothing is driven at boot — the turret starts wherever it was set by hand, and every move is relative to that. Tilt is a positional MG996R on PCA9685 channel 3 (78–150°); pan is a continuous-rotation MG996R on channel 2, turned only by timed nudges. **Pan trim:** press *hold still 3 s*; if the pan creeps, tap − or + until it doesn't (saved on the Pi). The Ceres show sweeps outward and back about the start pose and returns there when stopped.
- **Record motions:** record the tilt slider and pan buttons with their timing, label the take, replay it on the Pi. Recordings live in `~/rover/motions.json` (kept across deploys).
- **Check senses:** runs `sensing/bringup.py` on the Pi (radars, Wi-Fi CSI, thermal, both ToFs, camera, I2C, about 20 s) and shows a PASS / WARN / FAIL line for each, with the likely fault. It runs as its own process and never touches the motors.
- Working on the page without the rover: `python3 tests/remote_stub.py` → http://localhost:8099/?k=dev.

## Radars

The two LD2410Cs go through their own CP2102 adapters (+5V, GND, TXD → radar RX, RXD → radar TX; the 3V3 pin stays empty). The LD2450 needs no adapter: it sits on the Pi's own UART — 5V pin 4, GND pin 34, its TX → pin 10, its RX → pin 8 — after `sh ~/rover/enable_gpio_uart.sh` once on the Pi (moves Bluetooth off that UART, reboot afterwards). `sensing/station.py` finds all three; `~/rover/radars.json` overrides left/right if the adapters come up swapped. For every sense at once — I2C, both ToFs, thermal, camera, Wi-Fi CSI and the radars — run `cd ~/rover && venv/bin/python sensing/bringup.py` (one PASS / WARN / FAIL line each, with the likely fault). For the radars alone, `venv/bin/python sensing/radar_check.py` reads each radar for 5 s and says PASS / WARN / FAIL with frames per second, what it sees, and the likely fault when one is silent (power, TX/RX, the adapter's logic level, or the Pi console still on the UART).

## A search stop

`cd ~/rover && venv/bin/python sensing/station.py --name "hall S1"` runs one stop, about 75 s: motors released, 5 s settle, both LD2410Cs and Wi-Fi CSI read together for 60 s, then the pan sweeps the camera and the thermal array across five bearings and back. It prints one sentence and appends everything to `~/rover/stations.jsonl`. The remote holds the R4's port the whole time and only one program may have it, so stop the remote first (`sudo systemctl stop rover-web`, then `start` again afterwards); otherwise the station says the R4 is absent and skips the sweep. `--sim` runs the same protocol on simulated sensors, anywhere.

Wi-Fi CSI needs ESP32 #3 flashed with `firmware/csi_rx_udp` and ESP32 #2 running Walleye's `csi_tx`, both on channel 6. The receiver keeps only the transmitter's frames: it learns its MAC from the first probe and prints it in its 5 s serial report (`csi_tx NOT HEARD` until then).

## Regenerating the docs

`wiring.py` is the netlist and its checks; everything else is drawn from it, in this order: `python3 wiring.py`, `venv/bin/python wiring_diagrams.py` (WireViz + Graphviz; cross-checks against wiring.py), `wiring_art.py`, `wiring_page.py`, then `python3 assembly.py`, `rover3d.py`, `python3 drivetrain.py --json > bom-site/drivetrain.txt`, `cd bom-site && python3 build.py`, and `python3 make_prompt.py && cp CHATGPT-CHECK.md bom-site/` for the verification prompt. Every generator is deterministic: rerunning one on unchanged inputs leaves git clean.
