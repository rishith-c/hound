"""
timeline.py — the single source of truth for the Hound breakdown film.

Pure Python (no numpy) so Blender's bundled Python 3.7 and the compositor both import it. Everything that moves is a
function of time t in seconds: part matrices, camera, highlight weights, wire draw-on, captions, labels and effects.

Frame: rover +X forward, +Y left, +Z up, millimetres (bom-site/rover3d/scene.json).
"""
import json, math, os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FPS, W, H = 24, 1920, 1080
SENSOR = 36.0                                            # mm, horizontal sensor fit (Blender AUTO for landscape)
DURATION = 82.0
NFRAMES = int(DURATION * FPS)

SCENE = json.load(open(os.path.join(ROOT, "bom-site", "rover3d", "scene.json")))
PARTS = SCENE["parts"]
WIRES = SCENE["wires"]

# ── timing ──────────────────────────────────────────────────────────────────────────────────────────────────────
T_ORBIT, T_EXPLODE, T_TOUR, STEP = 4.0, 9.0, 14.5, 4.6
GROUPS = ["frame", "drive", "control", "power", "brain", "turret", "mast", "sense"]
T_REASM = T_TOUR + STEP * len(GROUPS)                    # 51.3
T_WIRES = T_REASM + 5.0                                  # 56.3
T_DRIVE = T_WIRES + 5.2                                  # 61.5
T_END = 78.0

TITLES = {
    "frame": ("the frame", "2020 aluminium rails and a printed deck"),
    "drive": ("the drive", "four steppers on 80 mm mecanum wheels"),
    "control": ("motor control", "UNO R4 WiFi + CNC shield, four DRV8825s"),
    "power": ("power", "a 3S LiPo for the wheels, banks for the brains"),
    "brain": ("the brain", "a Raspberry Pi 4 runs the sensing"),
    "turret": ("the turret", "camera + thermal eye on the Ceres pan / tilt"),
    "mast": ("the mast", "mmWave radars and a microphone, up high"),
    "sense": ("range + Wi-Fi", "time-of-flight bumpers and a Wi-Fi CSI node"),
}


def clamp(x, a=0.0, b=1.0):
    return a if x < a else b if x > b else x


def smooth(x):
    x = clamp(x); return x * x * x * (x * (6 * x - 15) + 10)


def ramp(t, t0, dur):
    return smooth((t - t0) / dur)


# ── parts: group, label anchor, explode offset ──────────────────────────────────────────────────────────────────
def group_of(i):
    p = PARTS[i]; pid, lab = p["id"], p["label"]
    if pid in ("RAIL", "CNR", "BRK", "DECK"): return "frame"
    if pid.startswith("M_") or pid.startswith("W_"): return "drive"
    if pid in ("R4", "SHIELD", "FAN") or pid.startswith("DRV_"): return "control"
    if pid in ("PACK", "PLUG", "XL4015", "BANK", "BANK2"): return "power"
    if pid == "PETG": return "mast" if ("post" in lab or "radar bar" in lab) else "power"
    if pid in ("PI", "HUB", "CP1", "CP2", "CP3"): return "brain"
    if pid in ("PT", "PCA", "PAN", "TILT", "CAM", "MLX"): return "turret"
    if pid in ("LDL", "LDR", "LD2450", "MIC", "CO2"): return "mast"
    return "sense"                                        # TOF_F, TOF_R, ESP3, ESP2


def sgn(v):
    return 1.0 if v > 0 else -1.0 if v < 0 else 0.0


def explode_vec(i):
    p = PARTS[i]; pid, lab = p["id"], p["label"]; x, y, z = p["pos"]
    if pid == "RAIL": return (sgn(x) * 30 if "cross" in lab else 0, sgn(y) * 30 if "side" in lab else 0, 0)
    if pid == "CNR": return (sgn(x) * 45, sgn(y) * 45, 0)
    if pid == "BRK": return (0, sgn(y) * 70, -10)
    if pid == "DECK": return (sgn(x) * 30, sgn(y) * 30, 95)
    if pid.startswith("M_"): return (0, sgn(y) * 120, 0)
    if pid.startswith("W_"): return (0, sgn(y) * 230, 0)
    if pid == "PACK": return (0, 0, -150)
    if pid == "PETG" and "cradle 83" in lab: return (0, 0, -95)
    if pid == "PETG" and "bar 140" in lab: return (0, 0, -190)
    if pid == "PETG" and "post" in lab: return (-110, 0, 150)
    if pid == "PETG" and "radar bar" in lab: return (-110, 0, 250)
    if pid in ("LDL", "LDR", "LD2450"): return (-110, sgn(y) * 40, 300)
    if pid == "MIC": return (-160, 0, 230)
    if pid == "R4": return (0, 0, 170)
    if pid == "SHIELD": return (0, 0, 225)
    if pid.startswith("DRV_"): return (sgn(x + 115.3) * 14, sgn(y - 87.1) * 14, 275)
    if pid == "FAN": return (0, 0, 340)
    if pid == "PLUG": return (-60, -40, 170)
    if pid == "XL4015": return (0, 40, 190)
    if pid == "BANK": return (0, 0, 200)
    if pid == "BANK2": return (0, 70, 170)
    if pid == "PI": return (0, -20, 180)
    if pid == "HUB": return (-20, -60, 170)
    if pid.startswith("CP"): return (0, -70, 200)
    if pid == "PT": return (60, 0, 170)
    if pid == "PCA": return (20, -40, 190)
    if pid == "PAN": return (60, 0, 215)
    if pid == "TILT": return (60, 0, 265)
    if pid == "CAM": return (60, 0, 320)
    if pid == "MLX": return (100, 0, 350)
    if pid == "TOF_F": return (130, 0, 0)
    if pid == "TOF_R": return (-130, 0, -30)
    if pid == "ESP3": return (40, 50, 170)
    return (0, 0, 0)


# the fan sits on a printed bridge over the drivers ("fan face at Z ≈ 159", assembly note) — scene.json's z = 111 is the standoff base
POS_FIX = {"FAN": (-115.7, 86.7, 164.0)}


def part_pos(i):
    return POS_FIX.get(PARTS[i]["id"], tuple(PARTS[i]["pos"]))


def visible(i, t):
    pid = PARTS[i]["id"]
    if pid == "CO2": return False                         # optional, not fitted
    if pid == "ESP2": return abs(t - (T_TOUR + STEP * 7.5)) < STEP / 2 or t > T_DRIVE
    return True


def explode_amount(g, t):
    k = GROUPS.index(g)
    up = ramp(t, T_EXPLODE + 0.32 * k, 2.6)
    down = ramp(t, T_REASM + 0.30 * (len(GROUPS) - 1 - k), 2.4)
    return up * (1.0 - down)


def highlight(g, t):
    """1 = drawn normally, 0 = ghosted. Only the tour ghosts groups; the step's own group stays in ink."""
    tour = ramp(t, T_TOUR - 0.6, 0.6) * (1 - ramp(t, T_REASM - 0.4, 0.7))
    k = GROUPS.index(g); a, b = T_TOUR + STEP * k, T_TOUR + STEP * (k + 1)
    w = ramp(t, a - 0.45, 0.6) * (1 - ramp(t, b - 0.15, 0.6))
    return 1.0 - tour * (1.0 - w)


def tour_step(t):
    k = int((t - T_TOUR) // STEP)
    return k if 0 <= k < len(GROUPS) and t < T_REASM else None


# ── 4×4 matrices as nested lists ────────────────────────────────────────────────────────────────────────────────
def mat_mul(A, B):
    return [[sum(A[r][k] * B[k][c] for k in range(4)) for c in range(4)] for r in range(4)]


def T(x, y, z):
    return [[1, 0, 0, x], [0, 1, 0, y], [0, 0, 1, z], [0, 0, 0, 1]]


def Rz(a):
    c, s = math.cos(a), math.sin(a); return [[c, -s, 0, 0], [s, c, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]


def Ry(a):
    c, s = math.cos(a), math.sin(a); return [[c, 0, s, 0], [0, 1, 0, 0], [-s, 0, c, 0], [0, 0, 0, 1]]


def apply(M, p):
    return tuple(M[r][0] * p[0] + M[r][1] * p[1] + M[r][2] * p[2] + M[r][3] for r in range(3))


# ── drive: pose, wheel spin (mecanum inverse kinematics), turret (the Ceres show) ─────────────────────────────────
LX, LY, R_WHEEL = 125.0, 215.5, 40.0
MOVES = [  # (t0, t1, (dx, dy, dyaw_deg), caption)
    (T_DRIVE + 1.0, T_DRIVE + 4.0, (520, 0, 0), "forward"),
    (T_DRIVE + 4.4, T_DRIVE + 7.6, (0, 460, 0), "sideways: no steering, the rollers do it"),
    (T_DRIVE + 8.0, T_DRIVE + 11.0, (-380, -380, 0), "diagonal"),
    (T_DRIVE + 11.4, T_DRIVE + 14.8, (0, 0, 180), "spin in place"),
]


def pose(t):
    x = y = yaw = 0.0
    for t0, t1, (dx, dy, dyaw), _ in MOVES:
        f = ramp(t, t0, t1 - t0)
        x += dx * f; y += dy * f; yaw += math.radians(dyaw) * f
    return x, y, yaw


WHEELS = {"W_FL": (LX, LY, (1, -1)), "W_FR": (LX, -LY, (1, 1)), "W_BL": (-LX, LY, (1, 1)), "W_BR": (-LX, -LY, (1, -1))}


def body_twist(t, dt=1e-3):
    x0, y0, a0 = pose(t - dt); x1, y1, a1 = pose(t + dt)
    vx, vy, w = (x1 - x0) / (2 * dt), (y1 - y0) / (2 * dt), (a1 - a0) / (2 * dt)
    a = (a0 + a1) / 2
    return math.cos(a) * vx + math.sin(a) * vy, -math.sin(a) * vx + math.cos(a) * vy, w


def wheel_speeds(t):
    vx, vy, w = body_twist(t); k = LX + LY
    return {"W_FL": vx - vy - k * w, "W_FR": vx + vy + k * w, "W_BL": vx + vy - k * w, "W_BR": vx - vy + k * w}


_WA = None


def wheel_angles(t):
    """Integrated wheel angle (rad) — the tread moves exactly as far as the ground under it."""
    global _WA
    if _WA is None:
        dt, acc, tab = 1.0 / 480, {k: 0.0 for k in WHEELS}, []
        tt = T_DRIVE
        while tt <= DURATION + dt:
            tab.append(dict(acc)); s = wheel_speeds(tt)
            for kk in acc: acc[kk] += s[kk] * dt / R_WHEEL
            tt += dt
        _WA = (dt, tab)
    dt, tab = _WA
    if t <= T_DRIVE: return {k: 0.0 for k in WHEELS}
    i = min(int((t - T_DRIVE) / dt), len(tab) - 1)
    return tab[i]


def turret(t):
    """(pan_rad, pitch_rad). Only moves in the drive segment, replaying r4_drive's 'K 1' show: tilt 80–116° sine,
    eased 500 ms pan nudges as the tilt passes centre, two one way then two back."""
    if t < T_DRIVE: return 0.0, 0.0
    ts = t - T_DRIVE
    sn = math.sin(2 * math.pi * ts / 5.0)
    tilt = 96.0 + (20.0 if sn > 0 else 16.0) * sn
    fade = ramp(t, T_DRIVE, 0.8) * (1.0 - ramp(t, T_END + 1.0, 1.5))
    pitch = math.radians((tilt - 92.0) * fade)
    pan, last, right, count = 0.0, -10.0, True, 0
    step, ta = 1.0 / 48, 0.0
    nudges = []
    while ta <= ts:
        s = math.sin(2 * math.pi * ta / 5.0); tl = 96.0 + (20.0 if s > 0 else 16.0) * s
        if abs(tl - 96.0) < 8.0 and ta - last > 1.5 and ta + T_DRIVE < T_END:
            nudges.append((ta, 1 if right else -1)); last = ta; count += 1
            if count >= 2: count = 0; right = not right
        ta += step
    for t0, d in nudges:
        f = clamp((ts - t0) / 0.5)
        pan += d * math.radians(25.0) * (0.5 - 0.5 * math.cos(math.pi * f))
    return pan, pitch


PAN_PIVOT = (110.0, 0.0)
TILT_PIVOT = (110.0, 0.0, 178.0)
PANNING = {"TILT", "CAM", "MLX"}
TILTING = {"CAM", "MLX"}


def root(t):
    x, y, yaw = pose(t)
    return mat_mul(T(x, y, 0), Rz(yaw))


def part_matrix(i, t):
    """World matrix of part i (its mesh is built centred on its rest position, rest orientation baked in)."""
    p = PARTS[i]; pid = p["id"]; g = group_of(i)
    px, py, pz = part_pos(i)
    e = explode_amount(g, t); ex, ey, ez = explode_vec(i)
    M = T(px, py, pz)
    if pid.startswith("W_"):
        M = mat_mul(M, Ry(wheel_angles(t)[pid]))
    if pid in PANNING:
        pan, pitch = turret(t)
        if pid in TILTING:
            M = mat_mul(mat_mul(T(*TILT_PIVOT), Ry(-pitch)), mat_mul(T(-TILT_PIVOT[0], -TILT_PIVOT[1], -TILT_PIVOT[2]), M))
        M = mat_mul(mat_mul(T(PAN_PIVOT[0], PAN_PIVOT[1], 0), Rz(pan)), mat_mul(T(-PAN_PIVOT[0], -PAN_PIVOT[1], 0), M))
    M = mat_mul(T(ex * e, ey * e, ez * e), M)
    if pid == "ESP2": return M                            # off the rover: stays put on the floor
    return mat_mul(root(t), M)


def wire_progress(k, t):
    n = len(WIRES)
    return clamp((t - T_WIRES - 0.2 - 3.6 * k / n) / 0.9)


WIRE_ORDER = sorted(range(len(WIRES)), key=lambda k: (WIRES[k]["sheet"], k))


# ── camera ──────────────────────────────────────────────────────────────────────────────────────────────────────
def group_centre(g, e=1.0):
    pts = [tuple(part_pos(i)[j] + explode_vec(i)[j] * e for j in range(3)) for i in range(len(PARTS)) if group_of(i) == g and PARTS[i]["id"] not in ("CO2", "ESP2")]
    c = [sum(p[j] for p in pts) / len(pts) for j in range(3)]
    r = max(math.sqrt(sum((p[j] - c[j]) ** 2 for j in range(3))) for p in pts)
    return c, r


def _cam_keys():
    K = [  # t, azimuth°, elevation°, distance, target xyz, lens
        (0.0, 50, 31, 1180, (-10, 0, 150), 40),
        (T_ORBIT, 40, 30, 1120, (-10, 0, 150), 40),
        (T_EXPLODE, -26, 27, 1120, (-10, 0, 150), 40),
        (T_EXPLODE + 3.2, -34, 27, 2150, (0, 0, 220), 40),
        (T_TOUR - 0.3, -38, 27, 2250, (0, 0, 240), 40),
    ]
    tour_view = {"frame": (-40, 38, 1.0), "drive": (-58, 22, 1.0), "control": (-110, 34, 1.0), "power": (-28, 20, 1.0),
                 "brain": (-70, 30, 1.0), "turret": (30, 20, 1.0), "mast": (-150, 18, 1.0), "sense": (-35, 22, 1.0)}
    for k, g in enumerate(GROUPS):
        c, r = group_centre(g)
        az, el, _ = tour_view[g]
        d = max(1150.0, min(2700.0, 3.3 * r + 520))
        if g == "sense": c = [c[0] * 0.5, c[1] * 0.5, c[2]]; d = 2500
        t0 = T_TOUR + STEP * k
        K.append((t0 + 0.9, az, el, d, tuple(c), 42))
        K.append((t0 + STEP - 0.25, az - 8, el + 1, d * 0.96, tuple(c), 42))
    K += [
        (T_REASM + 1.4, 24, 26, 1950, (0, 0, 190), 42),
        (T_WIRES - 0.2, 28, 30, 1450, (0, 0, 160), 42),
        (T_WIRES + 1.6, 12, 46, 1320, (-30, 0, 150), 40),
        (T_DRIVE - 0.8, -12, 44, 1380, (-30, 0, 150), 40),
        (T_DRIVE + 1.0, 36, 27, 2250, (150, 60, 120), 38),
        (T_DRIVE + 7.6, 58, 29, 2300, (260, 300, 120), 38),
        (T_DRIVE + 11.0, 44, 30, 2250, (180, 150, 120), 38),
        (T_END + 0.6, 30, 30, 2050, (150, 90, 330), 40),
        (DURATION, 24, 31, 2250, (150, 90, 380), 40),
    ]
    return K


CAM_KEYS = _cam_keys()


def _catmull(p0, p1, p2, p3, u):
    return 0.5 * ((2 * p1) + (-p0 + p2) * u + (2 * p0 - 5 * p1 + 4 * p2 - p3) * u * u + (-p0 + 3 * p1 - 3 * p2 + p3) * u ** 3)


def camera(t):
    """Returns (eye, target, lens). Channels interpolate with Catmull-Rom through eased key times."""
    K = CAM_KEYS
    t = clamp(t, K[0][0], K[-1][0])
    i = max(j for j in range(len(K)) if K[j][0] <= t) if t < K[-1][0] else len(K) - 2
    i = min(i, len(K) - 2)
    a, b = K[i], K[i + 1]
    u = (t - a[0]) / (b[0] - a[0]) if b[0] > a[0] else 0.0
    u = u * u * (3 - 2 * u)
    P = lambda j: K[max(0, min(len(K) - 1, j))]
    def ch(f):
        return _catmull(f(P(i - 1)), f(P(i)), f(P(i + 1)), f(P(i + 2)), u)
    az, el, d = ch(lambda k: k[1]), ch(lambda k: k[2]), ch(lambda k: k[3])
    tx, ty, tz, lens = ch(lambda k: k[4][0]), ch(lambda k: k[4][1]), ch(lambda k: k[4][2]), ch(lambda k: k[5])
    az += 2.5 * math.sin(t * 0.37); el += 1.2 * math.sin(t * 0.23 + 1)           # a breathing hand-held drift
    if t > T_DRIVE:
        rx, ry, _ = pose(t); w = ramp(t, T_DRIVE, 1.5)
        tx += (rx - tx) * 0.55 * w; ty += (ry - ty) * 0.55 * w
    A, E = math.radians(az), math.radians(el)
    eye = (tx + d * math.cos(E) * math.cos(A), ty + d * math.cos(E) * math.sin(A), tz + d * math.sin(E))
    return eye, (tx, ty, tz), lens


def cam_basis(eye, target):
    f = [target[j] - eye[j] for j in range(3)]; n = math.sqrt(sum(v * v for v in f)); f = [v / n for v in f]
    r = [f[1] * 1 - 0, 0 - f[0] * 1, 0]                   # f × (0,0,1)
    n = math.sqrt(sum(v * v for v in r)); r = [v / n for v in r]
    u = [r[1] * f[2] - r[2] * f[1], r[2] * f[0] - r[0] * f[2], r[0] * f[1] - r[1] * f[0]]
    return r, u, f


def project(p, cam):
    """World point → (px, py, depth) in the 1920×1080 frame, matching Blender's camera (horizontal sensor fit)."""
    eye, target, lens = cam
    r, u, f = cam_basis(eye, target)
    d = [p[j] - eye[j] for j in range(3)]
    x, y, z = sum(d[j] * r[j] for j in range(3)), sum(d[j] * u[j] for j in range(3)), sum(d[j] * f[j] for j in range(3))
    if z < 1: return None
    s = lens / SENSOR * W
    return W / 2 + s * x / z, H / 2 - s * y / z, z


# ── words on screen ─────────────────────────────────────────────────────────────────────────────────────────────
def find(pid, label=None):
    for i, p in enumerate(PARTS):
        if p["id"] == pid and (label is None or label in p["label"]): return i
    raise KeyError(pid)


LABELS = {  # group → [(part index, text, local anchor offset on that part)]
    "frame": [(find("RAIL", "side right"), "2020 aluminium rail ×4", (140, 0, 10)), (find("DECK", "front-right"), "printed PETG deck, 4 tiles", (0, 0, 0)),
              (find("CNR"), "corner bracket ×4", (0, 0, 0)), (find("BRK"), "motor plate ×4", (0, 0, 0))],
    "drive": [(find("M_FR"), "NEMA 17 stepper ×4", (0, 0, 0)), (find("W_FR"), "80 mm mecanum wheel, 45° rollers", (0, 0, 0)),
              (find("W_BR"), "the rollers make an X: it can go any way", (0, 0, 0))],
    "control": [(find("R4"), "Arduino UNO R4 WiFi", (0, 0, 0)), (find("SHIELD"), "CNC Shield v3", (0, 0, 0)), (find("DRV_Y"), "DRV8825 driver ×4, 1/32 step", (0, 0, 0)),
                (find("FAN"), "40 mm fan on the heatsinks", (0, 0, 0))],
    "power": [(find("PACK"), "3S 2200 mAh LiPo", (0, 0, 0)), (find("PLUG"), "Deans plug = E-stop", (0, 0, 0)), (find("XL4015"), "XL4015 buck: 5 V for the servos", (0, 0, 0)),
              (find("BANK"), "power bank for the Pi", (0, 0, 0)), (find("BANK2"), "2nd bank for the ESP32", (0, 0, 0))],
    "brain": [(find("PI"), "Raspberry Pi 4", (0, 0, 0)), (find("HUB"), "USB hub", (0, 0, 0)), (find("CP2"), "CP2102 ×3 for the radars", (0, 0, 0))],
    "turret": [(find("CAM"), "webcam", (0, 0, 0)), (find("MLX"), "MLX90640 thermal, 32×24", (0, 0, 0)), (find("PAN"), "pan + tilt servos (Ceres)", (0, 0, 0)),
               (find("PCA"), "PCA9685 servo driver", (0, 0, 0))],
    "mast": [(find("LDL"), "LD2410C 24 GHz radar ×2", (0, 0, 0)), (find("LD2450"), "LD2450: x/y of movers", (0, 0, 0)), (find("MIC"), "INMP441 microphone", (0, 0, 0)),
             (find("PETG", "post"), "printed mast", (0, 0, -40))],
    "sense": [(find("TOF_F"), "VL53L1X time-of-flight, front + rear", (0, 0, 0)), (find("ESP3"), "ESP32-S3 Wi-Fi CSI receiver", (0, 0, 0)),
              (find("ESP2"), "ESP32 transmitter, off the rover", (0, 0, 0))],
}


def labels(t):
    """[(part index, text, reveal 0..1, alpha, local anchor offset)]"""
    k = tour_step(t)
    out = []
    if k is not None:
        g = GROUPS[k]; t0 = T_TOUR + STEP * k
        for j, (i, txt, off) in enumerate(LABELS[g]):
            a = ramp(t, t0 + 0.55 + 0.32 * j, 0.25) * (1 - ramp(t, t0 + STEP - 0.45, 0.3))
            rv = clamp((t - (t0 + 0.55 + 0.32 * j)) / 0.7)
            if a > 0.01: out.append((i, txt, rv, a, off))
    return out


def captions(t):
    """[(title, subtitle, reveal, alpha)] — bottom-left hand-lettered captions."""
    out = []
    def add(t0, t1, a, b):
        al = ramp(t, t0, 0.35) * (1 - ramp(t, t1 - 0.35, 0.35))
        if al > 0.01: out.append((a, b, clamp((t - t0) / 0.9), al))
    add(T_ORBIT + 0.4, T_EXPLODE + 0.2, "assembled", "462 mm across the wheels, radar mast 304 mm up")
    add(T_EXPLODE + 0.6, T_TOUR - 0.5, "taken apart", "60 parts, where assembly.py puts them")
    for k, g in enumerate(GROUPS):
        t0 = T_TOUR + STEP * k
        add(t0 + 0.2, t0 + STEP - 0.1, *TITLES[g])
    add(T_REASM + 0.5, T_WIRES - 0.1, "back together", "every bolt where it was")
    add(T_WIRES + 0.2, T_DRIVE - 0.2, "76 wires", "six harness sheets, drawn in")
    for t0, t1, _, cap in MOVES:
        add(t0 - 0.2, t1 + 0.3, "mecanum drive", cap)
    add(T_DRIVE + 0.0, T_DRIVE + 0.95, "working", "radar pings, thermal + camera turret scanning")
    return out


def fx(kind, t):
    """Strength 0..1 of each effect: all of them while it drives, and each one during its own tour step."""
    w = ramp(t, T_DRIVE - 0.6, 1.0) * (1 - ramp(t, T_END - 0.4, 1.0))
    if kind == "floor": return ramp(t, T_DRIVE - 0.6, 1.0)
    step = {"radar": "mast", "thermal": "turret", "tof": "sense", "wifi": "sense", "arrows": None}[kind]
    if step:
        k = GROUPS.index(step); a = T_TOUR + STEP * k
        w = max(w, ramp(t, a + 0.9, 0.5) * (1 - ramp(t, a + STEP - 0.5, 0.4)))
    if kind == "wifi": w = min(w, 1 - ramp(t, T_DRIVE - 0.6, 1.0)) if t < T_DRIVE + 1 else 0.0
    return w


def shadow(t):
    """The rover's pencil shadow on the ground: only while it is assembled."""
    e = max(explode_amount(g, t) for g in GROUPS)
    return 1.0 - smooth(e * 3.0)


def title(t):
    """(title alpha, reveal of the drawing 0..1) for the opening card."""
    return 1 - ramp(t, T_ORBIT - 0.6, 0.8), ramp(t, 0.5, 2.6)


def end_card(t):
    return ramp(t, T_END, 1.2)


def effects_on(t):
    """Strength 0..1 of the working-mode effects (radar waves, sensor cones, force arrows, floor)."""
    return ramp(t, T_DRIVE - 0.6, 1.0) * (1 - ramp(t, DURATION - 1.2, 1.0))
