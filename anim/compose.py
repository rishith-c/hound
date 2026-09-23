#!/usr/bin/env python3
"""
compose.py — lays the transparent Freestyle frames on paper and draws everything that is hand-lettered or schematic:
floor grid, pencil shadow, wheel force arrows, radar pings, the thermal cone, ToF beams, part labels and captions.

    python3 anim/compose.py                       # all frames → anim/hound_breakdown.mp4 (needs numpy, pillow, ffmpeg)
    python3 anim/compose.py --still 44.0 out.png  # one composed frame (uses anim/frames/f_#####.png if present)

Geometry comes from timeline.py, the same functions Blender used, so every overlay sits exactly on the rendered parts.
"""
import math, os, subprocess, sys, zlib
from multiprocessing import Pool
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import timeline as TL

W, H, SS = TL.W, TL.H, 2                                   # overlays are drawn at 2× and downsampled for antialiasing
FRAMES = os.path.join(HERE, "frames")
NOTE = "/System/Library/Fonts/Noteworthy.ttc"
F_LABEL = ImageFont.truetype(NOTE, 31 * SS, index=1)
F_CAP_T = ImageFont.truetype(NOTE, 56 * SS, index=1)
F_CAP_S = ImageFont.truetype(NOTE, 33 * SS, index=0)
F_TITLE = ImageFont.truetype(NOTE, 190 * SS, index=1)
F_SUB = ImageFont.truetype(NOTE, 40 * SS, index=0)
F_SMALL = ImageFont.truetype(NOTE, 26 * SS, index=0)
INK = (38, 34, 30)
PENCIL = (120, 110, 98)
RED, TEAL, ORANGE, GREEN, BLUE, PURPLE = (200, 70, 50), (30, 130, 140), (225, 110, 40), (60, 140, 70), (50, 100, 180), (130, 80, 160)


# ── paper ───────────────────────────────────────────────────────────────────────────────────────────────────────
def make_paper(seed=3):
    rng = np.random.default_rng(seed)
    base = np.array([243, 237, 225], np.float32) / 255
    def blur_noise(scale, amp):
        n = rng.standard_normal((H // scale + 2, W // scale + 2)).astype(np.float32)
        im = Image.fromarray(((n - n.min()) / (np.ptp(n) + 1e-6) * 255).astype(np.uint8)).resize((W, H), Image.BICUBIC)
        return (np.asarray(im, np.float32) / 255 - 0.5) * amp
    tex = blur_noise(180, 0.035) + blur_noise(24, 0.02) + blur_noise(3, 0.022) + blur_noise(1, 0.018)
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    vig = 1 - 0.10 * (((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2)
    paper = np.clip(base[None, None, :] * (1 + tex[..., None]) * vig[..., None], 0, 1)
    grain = np.clip(1 + tex[..., None] * 0.8, 0.9, 1.1)
    return paper.astype(np.float32), grain.astype(np.float32)


PAPER, GRAIN = make_paper()


def make_wash():
    im = Image.new("L", (W, H), 0)
    ImageDraw.Draw(im).rounded_rectangle([W * 0.17, 90, W * 0.83, 430], radius=80, fill=225)
    return np.asarray(im.filter(ImageFilter.GaussianBlur(45)), np.float32)[..., None] / 255


WASH = make_wash()


# ── hand-drawn primitives ───────────────────────────────────────────────────────────────────────────────────────
class Pen:
    def __init__(self, frame):
        self.boil = frame // 2
        self.under = Image.new("RGBA", (W * SS, H * SS), (0, 0, 0, 0))
        self.over = Image.new("RGBA", (W * SS, H * SS), (0, 0, 0, 0))
        self.du, self.do = ImageDraw.Draw(self.under), ImageDraw.Draw(self.over)

    def jit(self, key, amp=1.2):
        r = np.random.default_rng((zlib.crc32(repr(key).encode()) + self.boil * 7919) & 0xFFFFFFFF)   # stable across worker processes
        return r.normal(0, amp, 2)

    def line(self, pts, col, width=2.4, alpha=1.0, layer="over", key=0, wobble=1.1, dash=None):
        pts = [p for p in pts if p is not None]
        if len(pts) < 2 or alpha <= 0.01: return
        d = self.do if layer == "over" else self.du
        jit = [np.asarray(p[:2], float) * SS + self.jit((key, k), wobble * SS) for k, p in enumerate(pts)]
        c = col + (int(255 * min(1, alpha)),)
        if dash:
            seg = [];
            for a, b in zip(jit[:-1], jit[1:]):
                L = np.linalg.norm(b - a); n = max(1, int(L / (dash * SS)))
                for k in range(0, n, 2):
                    d.line([tuple(a + (b - a) * k / n), tuple(a + (b - a) * min(n, k + 1) / n)], fill=c, width=int(width * SS))
            return
        d.line([tuple(p) for p in jit], fill=c, width=int(width * SS), joint="curve")

    def arrow(self, a, b, col, width=3.0, alpha=1.0, layer="over", key=0, head=16):
        if a is None or b is None or alpha <= 0.01: return
        a, b = np.asarray(a[:2], float), np.asarray(b[:2], float)
        v = b - a; L = np.linalg.norm(v)
        if L < 6: return
        u = v / L; n = np.array([-u[1], u[0]]); h = min(head, L * 0.45)
        self.line([a, b], col, width, alpha, layer, key)
        self.line([b - u * h + n * h * 0.55, b, b - u * h - n * h * 0.55], col, width, alpha, layer, (key, 1))

    def poly(self, pts, fill, alpha, layer="under"):
        pts = [p for p in pts if p is not None]
        if len(pts) < 3 or alpha <= 0.01: return
        d = self.do if layer == "over" else self.du
        d.polygon([(p[0] * SS, p[1] * SS) for p in pts], fill=fill + (int(255 * alpha),))

    def text(self, xy, s, font, col, alpha=1.0, reveal=1.0, layer="over", anchor="ls", halo=True):
        if alpha <= 0.01 or reveal <= 0: return None
        img = self.over if layer == "over" else self.under
        l, t, r, b = font.getbbox(s, anchor=anchor)
        l, t, r, b = l - 12, t - 12, r + 12, b + 12
        tw, th = r - l + 8, b - t + 8
        tile = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
        ImageDraw.Draw(tile).text((-l + 4, -t + 4), s, font=font, fill=col + (255,), anchor=anchor)
        if reveal < 1:                                       # the pen writes it left to right, soft nib edge
            ramp = np.clip((reveal * (tw + 60) - np.arange(tw)) / 60.0, 0, 1)
            a = np.asarray(tile.split()[3], np.float32) * ramp[None, :]
            tile.putalpha(Image.fromarray(a.astype(np.uint8)))
        if alpha < 1:
            tile.putalpha(Image.fromarray((np.asarray(tile.split()[3], np.float32) * alpha).astype(np.uint8)))
        x, y = int(xy[0] * SS + l - 4), int(xy[1] * SS + t - 4)
        if halo:                                             # a soft paper halo keeps words readable over the drawing
            ha = tile.split()[3].filter(ImageFilter.MaxFilter(9)).filter(ImageFilter.GaussianBlur(4))
            hal = Image.new("RGBA", tile.size, (243, 237, 225, 0)); hal.putalpha(ha.point(lambda v: int(v * 0.85)))
            img.alpha_composite(hal, (max(0, x), max(0, y)))
        img.alpha_composite(tile, (max(0, x), max(0, y)))
        return (x / SS, y / SS, (x + tw) / SS, (y + th) / SS)

    def flat(self, layer):
        im = (self.under if layer == "under" else self.over).resize((W, H), Image.LANCZOS)
        a = np.asarray(im, np.float32) / 255
        return a[..., :3], a[..., 3:4]


# ── 3-D helpers ─────────────────────────────────────────────────────────────────────────────────────────────────
def P(p, cam):
    q = TL.project(p, cam)
    return None if q is None else (q[0], q[1])


def world(i, t, local=(0, 0, 0)):
    return TL.apply(TL.part_matrix(i, t), local)


def rot_only(M, v):
    return tuple(M[r][0] * v[0] + M[r][1] * v[1] + M[r][2] * v[2] for r in range(3))


I_CAM, I_MLX, I_LD2450 = TL.find("CAM"), TL.find("MLX"), TL.find("LD2450")
I_TOF_F, I_TOF_R, I_ESP2, I_ESP3 = TL.find("TOF_F"), TL.find("TOF_R"), TL.find("ESP2"), TL.find("ESP3")


def floor_and_shadow(pen, t, cam):
    fw = TL.fx("arrows", t); fl = TL.fx("floor", t)
    rx, ry, _ = TL.pose(t)
    if fl > 0.01:                                           # a pencil grid on the floor, fading away from the rover
        for k, rng_ in ((0, range(-1000, 1601, 100)), (1, range(-1000, 1401, 100))):
            for c in rng_:
                seg = []
                span = range(-1000, 1401, 50) if k == 0 else range(-1000, 1601, 50)
                for s in span:
                    p = (c, s, 0) if k == 0 else (s, c, 0)
                    dist = math.hypot(p[0] - rx, p[1] - ry)
                    seg.append((P(p, cam), max(0.0, 1 - dist / 1300.0)))
                for (a, wa), (b, wb) in zip(seg[:-1], seg[1:]):
                    al = 0.34 * fl * min(wa, wb)
                    if a and b and al > 0.02: pen.line([a, b], PENCIL, 1.3, al, "under", key=("g", k, c, round(a[0])), wobble=0.3)
    sh = TL.shadow(t)
    if sh > 0.01:                                           # a hatched pencil shadow under the chassis
        R = TL.root(t)
        corners = [TL.apply(R, (x, y, 0)) for x, y in ((205, 245), (205, -245), (-205, -245), (-205, 245))]
        poly = [P(c, cam) for c in corners]
        pen.poly(poly, (150, 138, 122), 0.16 * sh)
        if all(poly):
            xs = [p[0] for p in poly]; ys = [p[1] for p in poly]
            for k in range(int(min(xs)) - 400, int(max(xs)), 13):
                a, b = (k, max(ys)), (k + (max(ys) - min(ys)), min(ys))
                clip = clip_seg_poly(a, b, poly)
                if clip: pen.line(clip, (130, 118, 104), 1.2, 0.30 * sh, "under", key=("h", k), wobble=0.5)
    if fw > 0.01:                                           # wheel force arrows: roller direction × wheel speed
        R = TL.root(t); sp = TL.wheel_speeds(t)
        vx, vy, w = TL.body_twist(t)
        for pid, (wx, wy, d) in TL.WHEELS.items():
            s = sp[pid] / 530.0
            if abs(s) < 0.03: continue
            L = 150 * max(-1.3, min(1.3, s))
            o = (wx, wy + (70 if wy > 0 else -70), 0)
            e = (o[0] + d[0] * L / math.sqrt(2), o[1] + d[1] * L / math.sqrt(2), 0)
            pen.arrow(P(TL.apply(R, o), cam), P(TL.apply(R, e), cam), RED, 3.2, fw * min(1, abs(s) * 3), "under", key=("fa", pid))
        spd = math.hypot(vx, vy)
        if spd > 30:                                        # the body's own velocity, in blue, ahead of the rover
            ux, uy = vx / spd, vy / spd
            o = (ux * 280, uy * 330, 0); e = (ux * (280 + 260 * min(1.2, spd / 400)), uy * (330 + 260 * min(1.2, spd / 400)), 0)
            pen.arrow(P(TL.apply(R, o), cam), P(TL.apply(R, e), cam), BLUE, 4.2, fw, "under", key="body", head=22)
        if abs(w) > 0.15:                                   # spinning: a curved arrow round the rover
            sg = 1 if w > 0 else -1
            arc = [P(TL.apply(R, (330 * math.cos(a), 330 * math.sin(a), 0)), cam) for a in np.linspace(-0.6 * sg, 1.4 * sg, 18)]
            pen.line(arc, BLUE, 4.2, fw, "under", key="spin")
            pen.arrow(arc[-3], arc[-1], BLUE, 4.2, fw, "under", key="spinh", head=22)


def clip_seg_poly(a, b, poly):
    """Clip segment ab to a convex polygon (Cyrus-Beck)."""
    a, b = np.asarray(a, float), np.asarray(b, float); d = b - a
    t0, t1 = 0.0, 1.0
    n = len(poly); cx = np.mean([p[0] for p in poly]); cy = np.mean([p[1] for p in poly])
    for k in range(n):
        p, q = np.asarray(poly[k], float), np.asarray(poly[(k + 1) % n], float)
        e = q - p; nrm = np.array([e[1], -e[0]])
        if np.dot(nrm, np.array([cx, cy]) - p) < 0: nrm = -nrm
        den = np.dot(nrm, d); num = np.dot(nrm, a - p)
        if abs(den) < 1e-9:
            if num < 0: return None
            continue
        tt = -num / den
        if den > 0: t0 = max(t0, tt)
        else: t1 = min(t1, tt)
        if t0 > t1: return None
    return [tuple(a + d * t0), tuple(a + d * t1)]


def effects(pen, t, cam):
    wr = TL.fx("radar", t)
    if wr > 0.01:                                           # 24 GHz pings from the mast, ±60° about the heading
        M = TL.part_matrix(I_LD2450, t); o = TL.apply(M, (0, 0, 0))
        for k in range(3):
            ph = ((t * 0.55) + k / 3.0) % 1.0
            r = 60 + ph * 950; al = wr * (1 - ph) ** 1.3 * 0.9
            pts = []
            for a in np.linspace(-math.radians(60), math.radians(60), 28):
                d = rot_only(M, (math.cos(a), math.sin(a), 0))
                pts.append(P((o[0] + d[0] * r, o[1] + d[1] * r, o[2] + d[2] * r), cam))
            pen.line(pts, TEAL, 3.0, al, key=("rad", k))
        for a in (-60, 60):
            d = rot_only(M, (math.cos(math.radians(a)), math.sin(math.radians(a)), 0))
            pen.line([P(o, cam), P((o[0] + d[0] * 1000, o[1] + d[1] * 1000, o[2] + d[2] * 1000), cam)], TEAL, 1.6, wr * 0.45, key=("radl", a), dash=9)
    wt = TL.fx("thermal", t)
    if wt > 0.01:                                           # MLX90640: 55° × 35° field, drawn to 0.6 m, with a 8×6 hint of its grid
        M = TL.part_matrix(I_CAM, t)
        o = TL.apply(M, (18, 0, 0)); D = 380 if t > TL.T_DRIVE else 300
        th, tv = math.tan(math.radians(27.5)), math.tan(math.radians(17.5))
        cs = [TL.apply(M, (18 + D, sy * D * th, sz * D * tv)) for sy, sz in ((1, 1), (-1, 1), (-1, -1), (1, -1))]
        pc = [P(c, cam) for c in cs]; po = P(o, cam)
        for k, c in enumerate(pc): pen.line([po, c], ORANGE, 2.0, wt * 0.6, key=("th", k))
        pen.line(pc + [pc[0]], ORANGE, 2.4, wt * 0.85, key="thr")
        for k in range(1, 8):
            f = k / 8
            pen.line([P(TL.apply(M, (18 + D, D * th * (1 - 2 * f), D * tv)), cam), P(TL.apply(M, (18 + D, D * th * (1 - 2 * f), -D * tv)), cam)], ORANGE, 1.1, wt * 0.35, key=("tg", k), wobble=0.4)
        for k in range(1, 6):
            f = k / 6
            pen.line([P(TL.apply(M, (18 + D, D * th, D * tv * (1 - 2 * f))), cam), P(TL.apply(M, (18 + D, -D * th, D * tv * (1 - 2 * f))), cam)], ORANGE, 1.1, wt * 0.35, key=("tgh", k), wobble=0.4)
    wf = TL.fx("tof", t)
    if wf > 0.01:                                           # VL53L1X: 27° cones, pulses running out and back
        for i, sgn in ((I_TOF_F, 1), (I_TOF_R, -1)):
            M = TL.part_matrix(i, t); o = TL.apply(M, (0, 0, 0)); L = 520; tn = math.tan(math.radians(13.5))
            ends = [TL.apply(M, (sgn * L, s * L * tn, 0)) for s in (-1, 1)]
            for k, e in enumerate(ends): pen.line([P(o, cam), P(e, cam)], GREEN, 2.0, wf * 0.8, key=("tof", i, k), dash=8)
            for k in range(3):
                ph = (t * 1.3 + k / 3) % 1.0; x = sgn * (40 + ph * (L - 40)); hw = abs(x) * tn
                pen.line([P(TL.apply(M, (x, -hw, 0)), cam), P(TL.apply(M, (x, hw, 0)), cam)], GREEN, 2.6, wf * (1 - ph), key=("tp", i, k))
    ww = TL.fx("wifi", t)
    if ww > 0.01:                                           # Wi-Fi CSI: the off-rover ESP32 transmits, ESP32 no.3 listens
        a, b = world(I_ESP2, t), world(I_ESP3, t)
        n = 22; pts = [P(tuple(a[j] + (b[j] - a[j]) * k / n + (math.sin(k / n * math.pi) * 220 if j == 2 else 0) for j in range(3)), cam) for k in range(n + 1)]
        pen.line(pts, PURPLE, 2.4, ww, key="wifi", dash=10)
        for k in range(3):
            ph = (t * 0.8 + k / 3) % 1.0; r = 30 + ph * 170
            ring = [P((a[0] + r * math.cos(u), a[1] + r * math.sin(u), a[2] + 20), cam) for u in np.linspace(0, 2 * math.pi, 30)]
            pen.line(ring, PURPLE, 2.0, ww * (1 - ph), key=("wr", k))


def part_anchor(i, t, off=(0, 0, 0)):
    sz = TL.PARTS[i]["size"]
    return world(i, t, (off[0], off[1], sz[2] / 2 + off[2]))


def labels(pen, t, cam, frame):
    items = []
    for i, txt, rv, al, off in TL.labels(t):
        q = TL.project(part_anchor(i, t, off), cam)
        if q is None: continue
        items.append([q[0], q[1], txt, rv, al, i])
    if not items: return
    cx = np.mean([it[0] for it in items])
    placed = {"L": [], "R": []}
    for it in sorted(items, key=lambda it: it[1]):
        tw = F_LABEL.getlength(it[2]) / SS
        side = "L" if it[0] < cx else "R"
        if side == "L" and it[0] - 170 - tw < 40: side = "R"
        if side == "R" and it[0] + 170 + tw > W - 40: side = "L"
        x = it[0] - 170 - tw if side == "L" else it[0] + 170
        x = min(max(x, 40), W - 40 - tw)
        y = it[1] - 70
        for py in sorted(placed[side]):
            if abs(y - py) < 60: y = py + 60
        y = min(max(y, 90), H - 200)
        placed[side].append(y)
        ax, ay = it[0], it[1]
        ex = x + tw + 10 if side == "L" else x - 10
        rv, al = it[3], it[4]
        # dot on the part, a curved leader, then the words with an underline
        pen.do.ellipse([(ax - 5) * SS, (ay - 5) * SS, (ax + 5) * SS, (ay + 5) * SS], outline=INK + (int(255 * al),), width=3 * SS)
        mid = ((ax + ex) / 2, min(ay, y) - 22)
        curve = [tuple((1 - u) ** 2 * np.array([ax, ay]) + 2 * (1 - u) * u * np.array(mid) + u * u * np.array([ex, y - 10])) for u in np.linspace(0, min(1, rv * 1.6), 12)]
        pen.line(curve, INK, 2.2, al, key=("ld", it[5]))
        pen.text((x, y), it[2], F_LABEL, INK, al, max(0, rv * 1.4 - 0.3))
        if rv > 0.5:
            uu = min(1, (rv - 0.5) * 2)
            pen.line([(x - 4, y + 9), (x - 4 + (tw + 8) * uu, y + 7)], RED, 2.2, al * 0.85, key=("ul", it[5]))


def captions(pen, t):
    for k, (a, b, rv, al) in enumerate(TL.captions(t)):
        x, y = 90, H - 118
        pen.text((x, y), a, F_CAP_T, INK, al, rv * 1.3)
        tw = F_CAP_T.getlength(a) / SS
        if rv > 0.4: pen.line([(x - 6, y + 14), (x - 6 + (tw + 16) * min(1, (rv - 0.4) * 2), y + 11)], RED, 3.4, al, key=("cap", a))
        pen.text((x, y + 56), b, F_CAP_S, (70, 64, 58), al, max(0, rv * 1.3 - 0.25))
    k = TL.tour_step(t)
    if k is not None:
        s = "%d / %d" % (k + 1, len(TL.GROUPS))
        pen.text((W - 90 - F_SMALL.getlength(s) / SS, H - 70), s, F_SMALL, (90, 82, 74), 0.9)


def title_card(pen, t):
    al, _ = TL.title(t)
    if al > 0.01:
        rv = TL.clamp((t - 0.2) / 1.3)
        s = "Hound"; tw = F_TITLE.getlength(s) / SS
        pen.text(((W - tw) / 2, 250), s, F_TITLE, INK, al, rv)
        if rv > 0.6: pen.line([((W - tw) / 2 - 20, 280), ((W - tw) / 2 - 20 + (tw + 40) * min(1, (rv - 0.6) * 2.5), 272)], RED, 5, al, key="tu")
        sub = "an indoor search rover that finds people it cannot see"
        sw = F_SUB.getlength(sub) / SS
        pen.text(((W - sw) / 2, 345), sub, F_SUB, (70, 64, 58), al, TL.clamp((t - 1.0) / 1.4))
    e = TL.end_card(t)
    if e > 0.01:
        s = "Hound"; tw = F_TITLE.getlength(s) / SS
        pen.text(((W - tw) / 2, 230), s, F_TITLE, INK, e, TL.clamp((t - TL.T_END) / 1.2))
        pen.line([((W - tw) / 2 - 20, 260), ((W - tw) / 2 + tw + 20, 252)], RED, 5, e * TL.clamp((t - TL.T_END - 0.8) / 0.6), key="eu")
        lines = ["60 parts  ·  76 wires  ·  4 steppers  ·  3 radars  ·  1 thermal eye", "rover-amazon-bom.vercel.app"]
        for k, sline in enumerate(lines):
            sw = (F_SUB if k == 0 else F_SMALL).getlength(sline) / SS
            pen.text(((W - sw) / 2, 320 + 52 * k), sline, F_SUB if k == 0 else F_SMALL, (70, 64, 58) if k == 0 else (110, 100, 90), e, TL.clamp((t - TL.T_END - 0.6 - 0.4 * k) / 1.2))


def reveal_mask(t):
    """Opening: the drawing appears as if sketched, a ragged diagonal wipe."""
    _, rv = TL.title(t)
    if rv >= 1: return None
    yy, xx = np.mgrid[0:H:4, 0:W:4].astype(np.float32)
    rng = np.random.default_rng(11)
    n = np.asarray(Image.fromarray((rng.random((H // 64 + 2, W // 64 + 2)) * 255).astype(np.uint8)).resize((W // 4, H // 4), Image.BICUBIC), np.float32) / 255
    d = (xx / W * 0.75 + (1 - yy / H) * 0.25) + n * 0.25
    m = np.clip((rv * 1.35 - d) / 0.08, 0, 1)
    return np.asarray(Image.fromarray((m * 255).astype(np.uint8)).resize((W, H), Image.BILINEAR), np.float32)[..., None] / 255


def compose(frame, src=None):
    t = frame / TL.FPS
    cam = TL.camera(t)
    pen = Pen(frame)
    floor_and_shadow(pen, t, cam)
    effects(pen, t, cam)
    labels(pen, t, cam, frame)
    captions(pen, t)
    title_card(pen, t)
    out = PAPER.copy()
    m = reveal_mask(t)
    uc, ua = pen.flat("under")
    if m is not None: ua = ua * m
    out = out * (1 - ua) + uc * ua * GRAIN
    path = src or os.path.join(FRAMES, "f_%05d.png" % frame)
    if os.path.exists(path):
        r = np.asarray(Image.open(path).convert("RGBA"), np.float32) / 255
        rc, ra = r[..., :3], r[..., 3:4]
        if m is not None: ra = ra * m
        out = out * (1 - ra) + rc * GRAIN * ra
    e = max(TL.end_card(t), TL.title(t)[0])
    if e > 0.01: out = out * (1 - WASH * e) + PAPER * WASH * e      # paper wash behind the opening and closing lettering
    oc, oa = pen.flat("over"); out = out * (1 - oa) + oc * oa
    return (np.clip(out, 0, 1) * 255).astype(np.uint8)


def _job(frame):
    return compose(frame - frame % 2).tobytes()             # on twos, overlays included, so labels never drift off their parts


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--still":
        t = float(sys.argv[2]); out = sys.argv[3]; src = sys.argv[4] if len(sys.argv) > 4 else None
        Image.fromarray(compose(int(round(t * TL.FPS)), src)).save(out); print("wrote", out)
        sys.exit()
    out = os.path.join(HERE, "hound_breakdown.mp4")
    ff = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "%dx%d" % (W, H), "-r", str(TL.FPS), "-i", "-",
                           "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-pix_fmt", "yuv420p", "-movflags", "+faststart", out], stdin=subprocess.PIPE)
    with Pool(max(1, os.cpu_count() - 1)) as pool:
        for k, buf in enumerate(pool.imap(_job, range(TL.NFRAMES), chunksize=4)):
            ff.stdin.write(buf)
            if k % 96 == 0: print("composed", k, "/", TL.NFRAMES, flush=True)
    ff.stdin.close(); ff.wait(); print("wrote", out)
