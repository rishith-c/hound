# Hound — the breakdown film

A sketch-style exploded-view film of the rover, built from the same placement data as the 3D viewer
(`bom-site/rover3d/scene.json`), with real part models from [step.parts](https://www.step.parts).

It runs about 82 seconds: title, the assembled rover, an explode, then a part-by-part tour of eight
groups with hand-lettered labels. After that it reassembles, draws the 76 wires in, and drives.
The drive covers forward, sideways, diagonal and a spin, with mecanum wheel speeds from the inverse
kinematics. The turret runs the Ceres show while radar pings, the thermal cone and the ToF beams play.

| file | does |
|---|---|
| `timeline.py` | Single source of truth: every transform, camera move, highlight, caption and effect as a function of time. Pure Python, shared by Blender and the compositor. |
| `fetch_assets.py` | Downloads the step.parts GLBs (Pi 4, UNO R4 WiFi, servo, NEMA 17, fan, 2020 profile). |
| `meshprep.py` | Welds and lightens those meshes into `meshes/*.npz`, and makes pencil versions of the board artwork in `tex/`. |
| `build_render.py` | Blender 2.80: builds the rover and renders transparent frames with Eevee toon fills and Freestyle ink. |
| `compose.py` | Paper, floor grid, shadow, force arrows, radar, thermal, ToF, Wi-Fi, labels and captions, then encoding. |
| `render_all.py` | Renders in 8-second chunks, composes each, deletes its PNGs, and stitches the chunks. |

```bash
python3 anim/fetch_assets.py && python3 anim/meshprep.py
python3 anim/render_all.py --procs 6
```

One test frame, rendered and composed:

```bash
/Applications/Blender.app/Contents/MacOS/Blender -b -P anim/build_render.py -- --still 44.5 /tmp/f.png
python3 anim/compose.py --still 44.5 /tmp/out.png /tmp/f.png
```

A frame takes about 12 s in Blender on an M1 Pro. Six processes render the film in roughly 1.5 hours.
The compositor needs numpy and pillow, and ffmpeg must be on the path.
