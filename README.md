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
| [sensing/report.html](https://rover-amazon-bom.vercel.app/sensing/report.html) | Sensing simulation results |
| `drivetrain.py` `assembly.py` `wiring.py` | The verification sources of truth: torque, placement, netlist |
| `sensing/` | Prior art, sensor models, vitals, fusion, station sequencer, Monte Carlo |
| `firmware/r4_drive` | The drive firmware (v1.0 tag `v1.0-best-drive`) |
| `pi/` | Pi-side code, deploy and flash scripts |
| `cad/` | Deck tiles for an Ender 3 and the full-plate DXF |
