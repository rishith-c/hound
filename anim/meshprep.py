#!/usr/bin/env python3
"""
meshprep.py — turn the step.parts GLBs (and the deck STLs) into compact welded meshes for the Blender renderer.

    python3 anim/meshprep.py            # needs numpy; reads anim/assets/*.glb, writes anim/meshes/*.npz

Each .npz holds: v (N,3 float32, mm, Z-up rover-style), f (M,3 int32), c (M,3 uint8 sRGB per face).
Welding matters: STEP tessellations duplicate vertices along every B-rep face seam, and Freestyle would then draw
every seam as a "border" line. Welded, it only draws real creases and silhouettes.
"""
import json, struct, os, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS, OUT = os.path.join(HERE, "assets"), os.path.join(HERE, "meshes")
CT = {5120: np.int8, 5121: np.uint8, 5122: np.int16, 5123: np.uint16, 5125: np.uint32, 5126: np.float32}
NC = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


def quat_mat(q):
    x, y, z, w = q
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def node_mat(n):
    if "matrix" in n: return np.array(n["matrix"], float).reshape(4, 4).T
    M = np.eye(4)
    if "scale" in n: M = np.diag(list(n["scale"]) + [1]) @ M
    if "rotation" in n: R = np.eye(4); R[:3, :3] = quat_mat(n["rotation"]); M = R @ M
    if "translation" in n: T = np.eye(4); T[:3, 3] = n["translation"]; M = T @ M
    return M


def box_mesh(mn, mx):
    x0, y0, z0 = mn; x1, y1, z1 = mx
    v = np.array([(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0), (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)], float)
    f = np.array([(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4), (1, 2, 6), (1, 6, 5), (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7)])
    return v, f


def read_glb(path, min_diag=0.0, yup=False, boxify=()):
    b = open(path, "rb").read()
    jl = struct.unpack("<I", b[12:16])[0]; j = json.loads(b[20:20 + jl])
    bin0 = 20 + jl + 8
    def acc(i):
        a = j["accessors"][i]; bv = j["bufferViews"][a["bufferView"]]
        off = bin0 + bv.get("byteOffset", 0) + a.get("byteOffset", 0)
        n = NC[a["type"]]; dt = np.dtype(CT[a["componentType"]])
        stride = bv.get("byteStride", 0)
        if stride and stride != n * dt.itemsize:
            raw = np.frombuffer(b, np.uint8, count=stride * a["count"], offset=off).reshape(a["count"], stride)
            return raw[:, :n * dt.itemsize].copy().view(dt).reshape(a["count"], n)
        return np.frombuffer(b, dt, count=a["count"] * n, offset=off).reshape(a["count"], n)
    V, F, C, nv = [], [], [], 0
    def walk(ni, parent):
        n = j["nodes"][ni]; M = parent @ node_mat(n)
        nonlocal nv
        if "mesh" in n:
            for pr in j["meshes"][n["mesh"]]["primitives"]:
                p = acc(pr["attributes"]["POSITION"]).astype(float)
                p = (np.c_[p, np.ones(len(p))] @ M.T)[:, :3]
                idx = acc(pr["indices"]).reshape(-1, 3).astype(np.int64) if "indices" in pr else np.arange(len(p)).reshape(-1, 3)
                if any(n.get("name", "").startswith(b) for b in boxify):
                    p, idx = box_mesh(p.min(0), p.max(0))             # e.g. the R4's 96 matrix LEDs: 2464 triangles each → a box
                elif min_diag and np.linalg.norm(p.max(0) - p.min(0)) < min_diag: continue
                col = j["materials"][pr["material"]].get("pbrMetallicRoughness", {}).get("baseColorFactor", [1, 1, 1, 1]) if "material" in pr else [1, 1, 1, 1]
                srgb = np.clip(np.where(np.array(col[:3]) <= 0.0031308, np.array(col[:3]) * 12.92, 1.055 * np.power(np.array(col[:3]), 1 / 2.4) - 0.055), 0, 1)
                V.append(p); F.append(idx + nv); C.append(np.tile((srgb * 255).astype(np.uint8), (len(idx), 1))); nv += len(p)
        for c in n.get("children", []): walk(c, M)
    for r in j["scenes"][j.get("scene", 0)]["nodes"]: walk(r, np.eye(4))
    v = np.concatenate(V); f = np.concatenate(F); c = np.concatenate(C)
    if yup: v = v[:, [0, 2, 1]] * np.array([1, -1, 1])   # this model is Y-up: (x, y, z) → (x, −z, y). The others are Z-up.
    return v, f, c


def read_stl(path):
    b = open(path, "rb").read(); n = struct.unpack("<I", b[80:84])[0]
    d = np.frombuffer(b, np.dtype([("n", "<3f4"), ("v", "<9f4"), ("a", "<u2")]), count=n, offset=84)
    v = d["v"].reshape(-1, 3).astype(float); f = np.arange(len(v)).reshape(-1, 3)
    return v, f, np.tile(np.array([255, 255, 255], np.uint8), (n, 1))


def weld(v, f, c, tol=1e-3):
    q = np.round(v / tol).astype(np.int64)
    _, first, inv = np.unique(q, axis=0, return_index=True, return_inverse=True)
    f2 = inv.reshape(-1)[f]
    ok = (f2[:, 0] != f2[:, 1]) & (f2[:, 1] != f2[:, 2]) & (f2[:, 0] != f2[:, 2])
    return v[first].astype(np.float32), f2[ok].astype(np.int32), c[ok]


def pi_colours(v, f, c):
    """The Pi 4 model carries no colours: paint the board (big, thin, flat faces at the PCB plane) green, parts silver."""
    tri = v[f]; zc = tri[:, :, 2].mean(1); zspan = np.ptp(tri[:, :, 2], 1)
    pcb = (zspan < 0.05) & ((np.abs(zc - v[:, 2].min()) < 0.05) | (np.abs(zc - 0.0) < 0.05) | (np.abs(zc + 1.6) < 0.05))
    out = np.tile(np.array([200, 204, 208], np.uint8), (len(f), 1))
    board = np.all((tri[:, :, 2] <= 0.02) & (tri[:, :, 2] >= -1.72), axis=1)
    out[board] = (58, 122, 72)
    return out


JOBS = {  # name: (Y-up source?, min part diagonal to keep mm, weld grid mm, components to replace by their box)
    # sub-2.5 mm SMD parts only add noise at this scale; the weld grid collapses over-tessellated little curves (Freestyle
    # time scales with edges) while boxy connectors, headers and chips keep their exact shape
    "raspberry_pi_4_model_b": (True, 2.5, 0.35, ()), "arduino_uno_r4_wifi": (False, 2.5, 0.3, ("HSMx",)), "futaba_s3003": (False, 0, 1e-3, ()),
    "axial_fan_40x40x10_simple": (False, 0, 1e-3, ()), "profile_2020_b_slot6_a_l100": (False, 0, 1e-3, ()), "stepper_motor_nema17_l0040_single_shaft": (False, 0, 1e-3, ()),
}

def pencil_textures():
    """Board artwork → pencil + wash: colours softened toward paper, edges inked. Keeps the real layouts readable."""
    from PIL import Image, ImageFilter, ImageOps
    src, dst = os.path.join(HERE, "..", "bom-site", "rover3d", "tex"), os.path.join(HERE, "tex")
    os.makedirs(dst, exist_ok=True)
    paper = np.array([243, 237, 225], float)
    for fn in sorted(os.listdir(src)):
        if not fn.endswith(".png"): continue
        im = Image.open(os.path.join(src, fn)).convert("RGB")
        im.thumbnail((1024, 1024))
        a = np.asarray(im, float)
        g = a.mean(2, keepdims=True)
        wash = g + (a - g) * 0.62                                   # desaturate a little
        wash = wash * 0.62 + paper * 0.38                            # and lift toward the paper
        e = np.asarray(ImageOps.grayscale(im).filter(ImageFilter.FIND_EDGES), float)[..., None] / 255.0
        ink = np.clip((e - 0.10) * 2.2, 0, 0.75)
        out = wash * (1 - ink) + np.array([40, 36, 32], float) * ink
        Image.fromarray(np.clip(out, 0, 255).astype(np.uint8)).save(os.path.join(dst, fn))
        print("tex", fn, im.size)


if __name__ == "__main__":
    pencil_textures()
    os.makedirs(OUT, exist_ok=True)
    for name, (yup, md, tol, bx) in JOBS.items():
        v, f, c = read_glb(os.path.join(ASSETS, name + ".glb"), md, yup, bx)
        n0 = len(f)
        v, f, c = weld(v, f, c, tol)
        key = np.sort(f, 1); _, u = np.unique(key, axis=0, return_index=True); u.sort(); f, c = f[u], c[u]   # drop duplicate faces
        if name.startswith("raspberry"): c = pi_colours(v, f, c)
        np.savez_compressed(os.path.join(OUT, name + ".npz"), v=v, f=f, c=c)
        print(f"{name:42s} tris {n0:7d} → {len(f):7d}  verts {len(v):7d}  bbox {np.round(v.min(0), 1)} … {np.round(v.max(0), 1)}")
    deck = os.path.join(HERE, "..", "bom-site", "cad")
    for t in ("FL", "FR", "RL", "RR"):
        v, f, c = weld(*read_stl(os.path.join(deck, f"deck_{t}.stl")))
        np.savez_compressed(os.path.join(OUT, f"deck_{t}.npz"), v=v, f=f, c=c)
        print(f"deck_{t:38s} tris {len(f):7d}  verts {len(v):7d}  bbox {np.round(v.min(0), 1)} … {np.round(v.max(0), 1)}")
