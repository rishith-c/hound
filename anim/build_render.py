"""
build_render.py — Blender 2.80 script: builds Hound from scene.json + the step.parts meshes and renders sketch frames.

    Blender -b -P anim/build_render.py -- START END        # frames [START, END), writes anim/frames/f_#####.png
    Blender -b -P anim/build_render.py -- --still 12.5     # one test frame at t = 12.5 s → anim/frames/still.png

Look: Eevee flat "toon + hatch" fills from an emission shader (no lights, deterministic), Freestyle ink with sketchy
chaining, Perlin wobble and tapered strokes, re-seeded on twos so the lines boil like hand-drawn animation. The film is
transparent; compose.py lays it on paper and adds the floor, effects and lettering.
"""
import bpy, bmesh, sys, os, math, time
import numpy as np
from mathutils import Matrix

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import timeline as TL

ARGV = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
MESH = os.path.join(HERE, "meshes")
TEX = os.path.join(HERE, "tex")
FRAMES = os.path.join(HERE, "frames")

PAPER = "#f3ede1"
INK = "#26221e"
GHOST_INK = "#b7ae9f"
LIGHT = (0.38, 0.52, 0.76)                               # key light direction (world), normalised in the shader


def lin(hexcol):
    h = hexcol.lstrip("#"); c = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    return tuple(v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in c)


# ── scene ───────────────────────────────────────────────────────────────────────────────────────────────────────
for o in list(bpy.data.objects): bpy.data.objects.remove(o, do_unlink=True)
for coll in (bpy.data.meshes, bpy.data.materials, bpy.data.curves, bpy.data.images, bpy.data.cameras, bpy.data.lights):
    for d in list(coll): coll.remove(d)
sc = bpy.context.scene
sc.render.engine = "BLENDER_EEVEE"
sc.render.resolution_x, sc.render.resolution_y, sc.render.resolution_percentage = TL.W, TL.H, 100
sc.render.film_transparent = True
sc.render.image_settings.file_format = "PNG"; sc.render.image_settings.color_mode = "RGBA"
sc.view_settings.view_transform = "Standard"; sc.view_settings.look = "None"
sc.view_settings.exposure = 0; sc.view_settings.gamma = 1
sc.eevee.taa_render_samples = 12
sc.eevee.use_gtao = False; sc.eevee.use_bloom = False; sc.eevee.use_ssr = False
sc.world = bpy.data.worlds.new("paper") if not sc.world else sc.world
sc.world.use_nodes = False; sc.world.color = (0, 0, 0)
cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam")); sc.collection.objects.link(cam); sc.camera = cam
cam.data.sensor_fit = "HORIZONTAL"; cam.data.sensor_width = TL.SENSOR
cam.data.clip_start, cam.data.clip_end = 10, 30000

COLL = {}
for g in TL.GROUPS + ["wires"]:
    c = bpy.data.collections.new(g); sc.collection.children.link(c); COLL[g] = c


# ── materials: flat toon + shadow hatching, fading to paper when ghosted ─────────────────────────────────────────
MATS = {g: [] for g in TL.GROUPS + ["wires"]}


def toon(name, group, col=None, vcol=False, image=None, pastel=0.0):
    m = bpy.data.materials.new(name); m.use_nodes = True
    nt = m.node_tree; N, L = nt.nodes, nt.links
    for n in list(N): N.remove(n)
    out = N.new("ShaderNodeOutputMaterial"); em = N.new("ShaderNodeEmission")
    geo = N.new("ShaderNodeNewGeometry")
    ld = N.new("ShaderNodeCombineXYZ"); n = math.sqrt(sum(v * v for v in LIGHT))
    for k in range(3): ld.inputs[k].default_value = LIGHT[k] / n
    dot = N.new("ShaderNodeVectorMath"); dot.operation = "DOT_PRODUCT"
    L.new(geo.outputs["Normal"], dot.inputs[0]); L.new(ld.outputs[0], dot.inputs[1])
    ramp = N.new("ShaderNodeValToRGB"); ramp.color_ramp.interpolation = "CONSTANT"
    el = ramp.color_ramp.elements
    el[0].position, el[0].color = 0.0, (0.66, 0.66, 0.66, 1)
    el[1].position, el[1].color = 0.55, (1, 1, 1, 1)
    e = el.new(0.12); e.color = (0.83, 0.83, 0.83, 1)
    L.new(dot.outputs["Value"], ramp.inputs["Fac"])
    # hatching in the darkest band: diagonal screen-space lines
    tc = N.new("ShaderNodeTexCoord"); sep = N.new("ShaderNodeSeparateXYZ"); L.new(tc.outputs["Window"], sep.inputs[0])
    mx = N.new("ShaderNodeMath"); mx.operation = "MULTIPLY"; mx.inputs[1].default_value = TL.W / 6.5 * 2 * math.pi
    my = N.new("ShaderNodeMath"); my.operation = "MULTIPLY"; my.inputs[1].default_value = TL.H / 6.5 * 2 * math.pi
    L.new(sep.outputs[0], mx.inputs[0]); L.new(sep.outputs[1], my.inputs[0])
    ad = N.new("ShaderNodeMath"); ad.operation = "ADD"; L.new(mx.outputs[0], ad.inputs[0]); L.new(my.outputs[0], ad.inputs[1])
    sn = N.new("ShaderNodeMath"); sn.operation = "SINE"; L.new(ad.outputs[0], sn.inputs[0])
    gt = N.new("ShaderNodeMath"); gt.operation = "GREATER_THAN"; gt.inputs[1].default_value = 0.55; L.new(sn.outputs[0], gt.inputs[0])
    lt = N.new("ShaderNodeMath"); lt.operation = "LESS_THAN"; lt.inputs[1].default_value = 0.12; L.new(dot.outputs["Value"], lt.inputs[0])
    hm = N.new("ShaderNodeMath"); hm.operation = "MULTIPLY"; L.new(gt.outputs[0], hm.inputs[0]); L.new(lt.outputs[0], hm.inputs[1])
    hs = N.new("ShaderNodeMath"); hs.operation = "MULTIPLY"; hs.inputs[1].default_value = -0.28; L.new(hm.outputs[0], hs.inputs[0])
    one = N.new("ShaderNodeMath"); one.operation = "ADD"; one.inputs[1].default_value = 1.0; L.new(hs.outputs[0], one.inputs[0]); hs = one
    hc = N.new("ShaderNodeCombineRGB")
    for k in range(3): L.new(hs.outputs[0], hc.inputs[k])
    # base colour
    if image is not None:
        tx = N.new("ShaderNodeTexImage"); tx.image = image; tx.interpolation = "Cubic"; base = tx.outputs["Color"]
    elif vcol:
        at = N.new("ShaderNodeAttribute"); at.attribute_name = "Col"; base = at.outputs["Color"]
    else:
        rgb = N.new("ShaderNodeRGB"); rgb.outputs[0].default_value = lin(col) + (1,); base = rgb.outputs[0]
    paper = lin(PAPER) + (1,)
    if pastel > 0:
        pm = N.new("ShaderNodeMixRGB"); pm.blend_type = "MIX"; pm.inputs["Fac"].default_value = pastel
        L.new(base, pm.inputs["Color1"]); pm.inputs["Color2"].default_value = paper; base = pm.outputs[0]
    m1 = N.new("ShaderNodeMixRGB"); m1.blend_type = "MULTIPLY"; m1.inputs["Fac"].default_value = 1
    L.new(base, m1.inputs["Color1"]); L.new(ramp.outputs["Color"], m1.inputs["Color2"])
    m2 = N.new("ShaderNodeMixRGB"); m2.blend_type = "MULTIPLY"; m2.inputs["Fac"].default_value = 1
    L.new(m1.outputs[0], m2.inputs["Color1"]); L.new(hc.outputs[0], m2.inputs["Color2"])
    gv = N.new("ShaderNodeValue"); gv.name = "ghost"; gv.outputs[0].default_value = 0.0
    m3 = N.new("ShaderNodeMixRGB"); m3.blend_type = "MIX"
    L.new(gv.outputs[0], m3.inputs["Fac"]); L.new(m2.outputs[0], m3.inputs["Color1"]); m3.inputs["Color2"].default_value = paper
    L.new(m3.outputs[0], em.inputs["Color"]); em.inputs["Strength"].default_value = 1.0
    L.new(em.outputs[0], out.inputs["Surface"])
    MATS[group].append(m)
    return m


_MC = {}


def mat(group, col=None, **kw):
    key = (group, col, kw.get("vcol"), kw.get("image").name if kw.get("image") else None, kw.get("pastel", 0))
    if key not in _MC: _MC[key] = toon("m_%s_%d" % (group, len(_MC)), group, col, **kw)
    return _MC[key]


# ── mesh builders (all return (verts Nx3, faces list/array, face colours or None, uv per loop or None, mat index per face)) ──
def make_obj(name, group, v, f, mats, fmat=None, fcol=None, uv=None, smooth=False):
    me = bpy.data.meshes.new(name)
    v = np.asarray(v, np.float32); f = np.asarray(f, np.int32)
    me.vertices.add(len(v)); me.vertices.foreach_set("co", v.ravel())
    me.loops.add(f.size); me.loops.foreach_set("vertex_index", f.ravel())
    me.polygons.add(len(f))
    me.polygons.foreach_set("loop_start", np.arange(0, f.size, f.shape[1], dtype=np.int32))
    me.polygons.foreach_set("loop_total", np.full(len(f), f.shape[1], np.int32))
    if fmat is not None: me.polygons.foreach_set("material_index", np.asarray(fmat, np.int32))
    me.polygons.foreach_set("use_smooth", np.full(len(f), smooth, bool))
    if fcol is not None:
        vc = me.vertex_colors.new(name="Col")
        c = np.repeat(np.c_[np.asarray(fcol, np.float32) / 255.0, np.ones(len(fcol), np.float32)], f.shape[1], axis=0)
        vc.data.foreach_set("color", c.ravel())
    if uv is not None:
        ul = me.uv_layers.new(name="UV"); ul.data.foreach_set("uv", np.asarray(uv, np.float32).ravel())
    me.update(); me.validate()
    for m in mats: me.materials.append(m)
    ob = bpy.data.objects.new(name, me); COLL[group].objects.link(ob)
    return ob


def box_geo(sx, sy, sz, c=(0, 0, 0)):
    x, y, z = sx / 2, sy / 2, sz / 2
    v = [(-x, -y, -z), (x, -y, -z), (x, y, -z), (-x, y, -z), (-x, -y, z), (x, -y, z), (x, y, z), (-x, y, z)]
    v = [(a + c[0], b + c[1], d + c[2]) for a, b, d in v]
    f = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
    return v, f


def cyl_geo(r, h, n=24, c=(0, 0, 0), axis="z"):
    v, f = [], []
    for k in range(n):
        a = 2 * math.pi * k / n
        for zz in (-h / 2, h / 2):
            p = [r * math.cos(a), r * math.sin(a), zz]
            if axis == "x": p = [p[2], p[0], p[1]]
            if axis == "y": p = [p[0], p[2], p[1]]
            v.append((p[0] + c[0], p[1] + c[1], p[2] + c[2]))
    for k in range(n):
        a, b = 2 * k, 2 * ((k + 1) % n)
        f.append((a, b, b + 1, a + 1))
    f.append(tuple(2 * k for k in range(n))[::-1]); f.append(tuple(2 * k + 1 for k in range(n)))
    return v, f


def merge(parts):
    """[(v, f)] → one (v, faces as a list of tuples, part index per face). Faces may be quads/ngons."""
    V, F, P = [], [], []
    for pi, (v, f) in enumerate(parts):
        o = len(V); V += list(v); F += [tuple(i + o for i in ff) for ff in f]; P += [pi] * len(f)
    return V, F, P


def ngon_obj(name, group, parts, mats, part_mat=None, bevel=0.0):
    """Mixed-polygon objects via bmesh (quads and n-gons keep clean Freestyle edges)."""
    V, F, P = merge(parts)
    me = bpy.data.meshes.new(name); bm = bmesh.new()
    vs = [bm.verts.new(p) for p in V]
    for ff, pi in zip(F, P):
        try:
            fa = bm.faces.new([vs[i] for i in ff]); fa.material_index = part_mat[pi] if part_mat else 0
        except ValueError:
            pass
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-4)
    bm.to_mesh(me); bm.free()
    for m in mats: me.materials.append(m)
    ob = bpy.data.objects.new(name, me); COLL[group].objects.link(ob)
    if bevel > 0:
        md = ob.modifiers.new("bevel", "BEVEL"); md.width = bevel; md.segments = 3; md.limit_method = "ANGLE"
    return ob


def npz(name):
    d = np.load(os.path.join(MESH, name + ".npz")); return d["v"].astype(np.float64), d["f"], d["c"]


def npz_obj(obname, group, name, xf, material, keep_colours=False, pastel=0.0):
    """xf(v) → transformed verts in the part's local frame (centred on its rest position)."""
    v, f, c = npz(name)
    v = xf(v)
    m = mat(group, vcol=True, pastel=pastel) if keep_colours else material
    return make_obj(obname, group, v, f, [m], fcol=c if keep_colours else None)


def centre_bbox(v, centre=None):
    c = (v.min(0) + v.max(0)) / 2 if centre is None else np.asarray(centre)
    return v - c


def rot_z(v, deg):
    a = math.radians(deg); c, s = math.cos(a), math.sin(a)
    return np.c_[c * v[:, 0] - s * v[:, 1], s * v[:, 0] + c * v[:, 1], v[:, 2]]


def rot_x(v, deg):
    a = math.radians(deg); c, s = math.cos(a), math.sin(a)
    return np.c_[v[:, 0], c * v[:, 1] - s * v[:, 2], s * v[:, 1] + c * v[:, 2]]


def mecanum_geo(size, hand):
    """Hub, two side plates and nine 45° barrel rollers. Wheel axle = local Y. At the ground contact a left-hand wheel's
    roller axis runs along (1, 1) in plan, a right-hand one along (1, −1) — the X pattern that makes it strafe."""
    R, Wd = size[0] / 2, size[1]
    parts, pm = [], []
    hub_v, hub_f = cyl_geo(R * 0.52, Wd * 0.62, 28, axis="y"); parts.append((hub_v, hub_f)); pm.append(0)
    for side in (-1, 1):
        pv, pf = cyl_geo(R * 0.80, 2.2, 36, c=(0, side * Wd * 0.44, 0), axis="y"); parts.append((pv, pf)); pm.append(1)
    bv, bf = cyl_geo(4.0, Wd * 1.05, 16, axis="y"); parts.append((bv, bf)); pm.append(1)
    nr, rr = 9, 7.0
    rl = Wd * 0.9
    s = 1 if hand == "L" else -1
    for k in range(nr):
        a = 2 * math.pi * k / nr
        pos = np.array([R * 0.83 * math.sin(a), 0, -R * 0.83 * math.cos(a)])
        tan = np.array([math.cos(a), 0, math.sin(a)])
        ax = (s * tan + np.array([0, 1, 0])) / math.sqrt(2)
        rad = pos / np.linalg.norm(pos)
        b2 = np.cross(ax, rad)
        rv, rf = [], []
        nu, nv = 10, 12
        for i in range(nu + 1):
            u = -1 + 2 * i / nu
            rad_u = rr * (1 - 0.55 * u * u)                      # barrel profile
            for j in range(nv):
                th = 2 * math.pi * j / nv
                p = pos * (1.0 + 0.0) + ax * (u * rl / 2) + (rad * math.cos(th) + b2 * math.sin(th)) * rad_u
                p = p + rad * (R - R * 0.83 - rr)                # push out so the barrel crowns reach R
                rv.append(tuple(p))
        for i in range(nu):
            for j in range(nv):
                a0 = i * nv + j; a1 = i * nv + (j + 1) % nv
                rf.append((a0, a1, a1 + nv, a0 + nv))
        rf.append(tuple(range(nv))[::-1]); rf.append(tuple(nu * nv + j for j in range(nv)))
        parts.append((rv, rf)); pm.append(2)
    return parts, pm


# ── build every part ─────────────────────────────────────────────────────────────────────────────────────────────
OBJ = {}
PALETTE = {"rail": "#cdd6de", "CNR": "#b3bcc5", "BRK": "#9ea7b0", "deck": "#eadbbc", "petg": "#e6d6b3", "motor": "#b9c0c6",
           "hub": "#9aa1a8", "plate": "#d4d8dc", "roller": "#7b8288", "pack": "#f0c93f", "plug": "#df7a6a", "bank": "#98a0a8",
           "hub_usb": "#6e757c", "cp": "#e08b7c", "servo": "#6f767d", "cam": "#636a71", "lens": "#9fb9d2", "ld2450": "#6f93c9",
           "pcb": "#6f9f78", "heatsink": "#c9ced3", "cap": "#5a6c8a", "coil": "#b8876a", "fan": "#595f65", "esp2": "#8a9096"}


def pencil_image(fn):
    p = os.path.join(TEX, os.path.basename(fn))
    im = bpy.data.images.load(p); im.name = os.path.basename(fn); return im


def board_obj(name, group, p):
    L_, W_, T_ = p["size"]; face = p.get("face", "up"); yaw = p.get("yaw", 0) or 0
    img = pencil_image(p["tex"])
    m_edge, m_face = mat(group, PALETTE["pcb"], pastel=0.1), mat(group, image=img)
    bm = bmesh.new(); uvl = bm.loops.layers.uv.new("UV")
    if face == "up":
        v, f = box_geo(L_, W_, T_)
    else:
        v, f = box_geo(L_, W_, T_)                            # size = rover-frame extents: thin along X
    vs = [bm.verts.new(x) for x in v]
    for k, ff in enumerate(f):
        fa = bm.faces.new([vs[i] for i in ff]); fa.material_index = 0
        top = (face == "up" and k == 1) or (face == "+x" and k == 3) or (face == "-x" and k == 5)
        if top:
            fa.material_index = 1
            for lp in fa.loops:
                x, y, z = lp.vert.co
                if face == "up": uv = (x / L_ + 0.5, y / W_ + 0.5)
                elif face == "+x": uv = (y / W_ + 0.5, z / T_ + 0.5)
                else: uv = (-y / W_ + 0.5, z / T_ + 0.5)
                lp[uvl].uv = uv
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    me.materials.append(m_edge); me.materials.append(m_face)
    ob = bpy.data.objects.new(name, me); COLL[group].objects.link(ob)
    if yaw:
        me.transform(Matrix.Rotation(math.radians(yaw), 4, "Z"))
    return ob


def extras(name, group, parts, colour, bevel=0.0):
    return ngon_obj(name, group, parts, [mat(group, colour)], bevel=bevel)


prof_v, prof_f, _ = npz("profile_2020_b_slot6_a_l100")
nema_v, nema_f, _ = npz("stepper_motor_nema17_l0040_single_shaft")
servo = npz("futaba_s3003"); fan = npz("axial_fan_40x40x10_simple")

for i, p in enumerate(TL.PARTS):
    pid, kind, g = p["id"], p["kind"], TL.group_of(i)
    name = "p%02d_%s" % (i, pid)
    sx, sy, sz = p["size"]
    ob = None
    if kind == "rail":
        Lr = sx if p["along"] == "x" else sy
        v = prof_v.copy(); v[:, 1] = (v[:, 1] + 50.0) * Lr / 100.0
        if p["along"] == "x": v = rot_z(v, -90)
        ob = make_obj(name, g, v, prof_f, [mat(g, PALETTE["rail"])])
    elif pid == "DECK":
        tag = p["label"].split("deck tile ")[1].split(" ")[0]
        t = {"front-left": "FL", "front-right": "FR", "rear-left": "RL", "rear-right": "RR"}[tag]
        off = {"FL": (0, 0), "FR": (0, -195), "RL": (-175, 0), "RR": (-175, -195)}[t]
        v, f, _ = npz("deck_" + t)
        v = v + np.array([off[0], off[1], 91.0]) - np.array(p["pos"])
        ob = make_obj(name, g, v, f, [mat(g, PALETTE["deck"])])
    elif pid.startswith("M_"):
        v = nema_v.copy()
        shaft_top = np.abs(v[v[:, 2] > v[:, 2].max() - 3][:, :2]).max() < 6
        if not shaft_top: v[:, 2] = -v[:, 2]
        v = rot_x(v, -90 if p["shaft"][1] > 0 else 90)
        v = centre_bbox(v)
        ob = make_obj(name, g, v, nema_f, [mat(g, PALETTE["motor"])])
    elif pid.startswith("W_"):
        parts, pm = mecanum_geo(p["size"], p["hand"])
        ob = ngon_obj(name, g, parts, [mat(g, PALETTE["hub"]), mat(g, PALETTE["plate"]), mat(g, PALETTE["roller"])], part_mat=pm)
    elif pid == "R4":
        ob = npz_obj(name, g, "arduino_uno_r4_wifi", lambda v: v - np.array([34.29, 26.67, -0.8]), None, keep_colours=True, pastel=0.45)
    elif pid == "PI":
        ob = npz_obj(name, g, "raspberry_pi_4_model_b", lambda v: rot_z(v - np.array([42.5, 28.0, -0.8]), p.get("yaw", 0)), None, keep_colours=True, pastel=0.3)
    elif pid in ("PAN", "TILT"):
        v, f, c = servo; v = centre_bbox(v.copy())
        ob = make_obj(name, g, v, f, [mat(g, PALETTE["servo"])])
    elif pid == "FAN":
        v, f, c = fan; v = centre_bbox(v.copy())
        ob = make_obj(name, g, v, f, [mat(g, PALETTE["fan"])])
    elif kind == "board":
        ob = board_obj(name, g, p)
        if pid.startswith("DRV_"):
            fins = [box_geo(9, 9, 1.4, (0, 0, 1.3))] + [box_geo(1.1, 9, 5.5, (-3.6 + 2.4 * k, 0, 4.6)) for k in range(4)]
            hs = extras(name + "_hs", g, fins, PALETTE["heatsink"]); hs.parent = ob
        if pid == "XL4015":
            bits = [cyl_geo(4.2, 9, 18, (-14, 5, 5.3)), cyl_geo(4.2, 9, 18, (14, 5, 5.3)), cyl_geo(6.5, 6, 20, (0, -2, 3.8))]
            ex = extras(name + "_parts", g, bits, PALETTE["cap"]); ex.parent = ob
        if pid == "MLX":
            can = extras(name + "_can", g, [cyl_geo(4.6, 4.5, 20, (3.0, 0, 0), axis="x")], PALETTE["heatsink"]); can.parent = ob
    elif pid == "CAM":
        body = extras(name, g, [box_geo(sx, sy, sz)], PALETTE["cam"], bevel=6.0)
        lens = extras(name + "_lens", g, [cyl_geo(8.5, 4, 24, (sx / 2 + 1.5, 0, 0), axis="x"), cyl_geo(5.0, 2, 20, (sx / 2 + 4, 0, 0), axis="x")], PALETTE["lens"])
        lens.parent = body; ob = body
        zb, zp = -sz / 2, TL.TILT_PIVOT[2] - p["pos"][2]                 # camera underside, tilt axis (local)
        yoke = [box_geo(30, 40, 3, (0, 0, zb - 1.5))]
        for sgn_ in (-1, 1):
            yoke += [box_geo(12, 3, zb - zp + 6, (0, sgn_ * 11.5, (zb + zp) / 2 - 1.5)), cyl_geo(6.5, 3.2, 20, (0, sgn_ * 13.6, zp), axis="y")]
        yk = extras(name + "_yoke", g, yoke, PALETTE["petg"]); yk.parent = body
    elif pid == "PACK":
        ob = extras(name, g, [box_geo(sx, sy, sz)], PALETTE["pack"], bevel=2.5)
        band = extras(name + "_label", g, [box_geo(sx * 0.62, sy + 0.6, sz + 0.6)], "#f7e7a1"); band.parent = ob
    elif pid in ("BANK", "BANK2"):
        ob = extras(name, g, [box_geo(sx, sy, sz)], PALETTE["bank"], bevel=5.0)
    elif pid == "PETG" and "post" in p["label"]:
        wall = 3.0
        u = [box_geo(sx, wall, sz, (0, sy / 2 - wall / 2, 0)), box_geo(sx, wall, sz, (0, -sy / 2 + wall / 2, 0)), box_geo(wall, sy, sz, (-sx / 2 + wall / 2, 0, 0)),
             box_geo(60, 60, 6, (0, 0, -sz / 2 - 3))]
        ob = extras(name, g, u, PALETTE["petg"])
    else:
        col = {"CNR": PALETTE["CNR"], "BRK": PALETTE["BRK"], "PETG": PALETTE["petg"], "PT": PALETTE["petg"], "PLUG": PALETTE["plug"],
               "HUB": PALETTE["hub_usb"], "CP1": PALETTE["cp"], "CP2": PALETTE["cp"], "CP3": PALETTE["cp"], "LD2450": PALETTE["ld2450"],
               "ESP2": PALETTE["esp2"], "CO2": "#999999"}.get(pid, p.get("color", "#999999"))
        ob = extras(name, g, [box_geo(sx, sy, sz)], col, bevel=1.2 if pid in ("HUB", "PLUG") else 0.0)
    OBJ[i] = ob

# ── wires: tubes along the viewer's path, drawn on by bevel factor, no ink (they read as coloured pencil) ────────
def catmull_centripetal(pts, n=10):
    P = [np.array(pts[0]) * 2 - np.array(pts[1])] + [np.array(p) for p in pts] + [np.array(pts[-1]) * 2 - np.array(pts[-2])]
    out = []
    for k in range(1, len(P) - 2):
        p0, p1, p2, p3 = P[k - 1], P[k], P[k + 1], P[k + 2]
        t0 = 0.0; t1 = t0 + max(np.linalg.norm(p1 - p0) ** 0.5, 1e-3); t2 = t1 + max(np.linalg.norm(p2 - p1) ** 0.5, 1e-3); t3 = t2 + max(np.linalg.norm(p3 - p2) ** 0.5, 1e-3)
        for s in range(n):
            t = t1 + (t2 - t1) * s / n
            A1 = (t1 - t) / (t1 - t0) * p0 + (t - t0) / (t1 - t0) * p1
            A2 = (t2 - t) / (t2 - t1) * p1 + (t - t1) / (t2 - t1) * p2
            A3 = (t3 - t) / (t3 - t2) * p2 + (t - t2) / (t3 - t2) * p3
            B1 = (t2 - t) / (t2 - t0) * A1 + (t - t0) / (t2 - t0) * A2
            B2 = (t3 - t) / (t3 - t1) * A2 + (t - t1) / (t3 - t1) * A3
            out.append((t2 - t) / (t2 - t1) * B1 + (t - t1) / (t2 - t1) * B2)
    out.append(P[-2]); return out


WOBJ = []
for k, w in enumerate(TL.WIRES):
    A, B, na, nb = [np.array(w[q], float) for q in ("a", "b", "na", "nb")]
    d = np.linalg.norm(A - B); lift = min(40, 10 + d * 0.06)
    a1, b1 = A + na * 6, B + nb * 6
    top = max(a1[2], b1[2]) + lift
    a2, b2 = a1.copy(), b1.copy(); a2[2] = top; b2[2] = top
    pts = catmull_centripetal([A, a1, a2, (a2 + b2) / 2, b2, b1, B])
    cu = bpy.data.curves.new("w%02d" % k, "CURVE"); cu.dimensions = "3D"
    sp = cu.splines.new("POLY"); sp.points.add(len(pts) - 1)
    for j, q in enumerate(pts): sp.points[j].co = (q[0], q[1], q[2], 1)
    cu.bevel_depth = max(1.1, w["r"] * 0.8); cu.bevel_resolution = 2; cu.use_fill_caps = True
    cu.bevel_factor_mapping_end = "SPLINE"; cu.bevel_factor_end = 0.0
    cu.materials.append(mat("wires", w["color"]))
    ob = bpy.data.objects.new("w%02d" % k, cu); COLL["wires"].objects.link(ob); WOBJ.append(ob)


# ── Freestyle: one line set per group so the tour can ghost them independently ────────────────────────────────────
sc.render.use_freestyle = True
sc.render.line_thickness_mode = "ABSOLUTE"; sc.render.line_thickness = 1.0
fs = sc.view_layers[0].freestyle_settings
fs.mode = "EDITOR"; fs.crease_angle = math.radians(142); fs.use_culling = False; fs.use_smoothness = True
for ls in list(fs.linesets): fs.linesets.remove(ls)
STYLE = {}
for gi, g in enumerate(TL.GROUPS):
    ls = fs.linesets.new(g)
    ls.select_by_visibility = True; ls.visibility = "VISIBLE"
    ls.select_by_edge_types = True; ls.select_silhouette = True; ls.select_border = True; ls.select_crease = True
    ls.select_by_collection = True; ls.collection = COLL[g]
    st = bpy.data.linestyles.new("ink_" + g); ls.linestyle = st
    st.color = lin(INK)
    st.thickness = 2.3; st.thickness_position = "CENTER"
    st.chaining = "SKETCHY"; st.rounds = 2; st.use_same_object = True
    sm = st.geometry_modifiers.new("sampling", "SAMPLING"); sm.sampling = 3.0
    pn = st.geometry_modifiers.new("wobble", "PERLIN_NOISE_1D"); pn.frequency = 9.0; pn.amplitude = 1.3; pn.octaves = 2; pn.seed = gi
    bb = st.geometry_modifiers.new("overshoot", "BACKBONE_STRETCHER"); bb.backbone_length = 4.0
    tm = st.thickness_modifiers.new("taper", "ALONG_STROKE"); tm.mapping = "CURVE"; tm.value_min = 0.25; tm.value_max = 1.0; tm.blend = "MULTIPLY"
    cm = tm.curve; cv = cm.curves[0]
    cv.points[0].location = (0.0, 0.0); cv.points[1].location = (1.0, 0.0)
    cv.points.new(0.15, 1.0); cv.points.new(0.85, 1.0); cm.update()
    STYLE[g] = (st, pn)


def mix(a, b, f):
    return tuple(a[k] + (b[k] - a[k]) * f for k in range(len(a)))


INK_RGB, GHOST_RGB = lin(INK), lin(GHOST_INK)


def set_time(t, frame):
    for i, ob in OBJ.items():
        ob.matrix_world = Matrix(TL.part_matrix(i, t))
        ob.hide_render = not TL.visible(i, t)
        for ch in ob.children: ch.hide_render = ob.hide_render
    R = Matrix(TL.root(t))
    for k, ob in enumerate(WOBJ):
        prog = TL.wire_progress(TL.WIRE_ORDER.index(k), t)
        ob.data.bevel_factor_end = max(prog, 0.0)
        ob.hide_render = prog <= 0.001 or t < TL.T_WIRES - 0.5
        ob.matrix_world = R
    for g in TL.GROUPS:
        h = TL.highlight(g, t)
        st, pn = STYLE[g]
        st.color = mix(GHOST_RGB, INK_RGB, h); st.alpha = 0.45 + 0.55 * h; st.thickness = 1.3 + 1.0 * h
        pn.seed = (frame // 2) * 7 + TL.GROUPS.index(g)
        for m in MATS[g]:
            m.node_tree.nodes["ghost"].outputs[0].default_value = (1 - h) * 0.86
    eye, target, lens = TL.camera(t)
    r, u, f = TL.cam_basis(eye, target)
    cam.matrix_world = Matrix(((r[0], u[0], -f[0], eye[0]), (r[1], u[1], -f[1], eye[1]), (r[2], u[2], -f[2], eye[2]), (0, 0, 0, 1)))
    cam.data.lens = lens


os.makedirs(FRAMES, exist_ok=True)
if ARGV and ARGV[0] == "--stills":
    for tt in ARGV[1].split(","):
        t = float(tt); out = os.path.join(FRAMES, "still_%05.1f.png" % t)
        set_time(t, int(t * TL.FPS)); sc.render.filepath = out
        t0 = time.time(); bpy.ops.render.render(write_still=True)
        print("STILL t=%.2f %.1fs -> %s" % (t, time.time() - t0, out), flush=True)
elif ARGV and ARGV[0] == "--still":
    t = float(ARGV[1]); out = ARGV[2] if len(ARGV) > 2 else os.path.join(FRAMES, "still.png")
    set_time(t, int(t * TL.FPS)); sc.render.filepath = out
    t0 = time.time(); bpy.ops.render.render(write_still=True)
    print("STILL t=%.2f %.1fs -> %s" % (t, time.time() - t0, out))
else:
    a, b = int(ARGV[0]), int(ARGV[1])
    for fr in range(a, min(b, TL.NFRAMES)):
        path = os.path.join(FRAMES, "f_%05d.png" % fr)
        if os.path.exists(path) and os.path.getsize(path) > 0: continue
        t = fr / TL.FPS; set_time(t, fr); sc.render.filepath = path
        t0 = time.time(); bpy.ops.render.render(write_still=True)
        print("FRAME %d t=%.2f %.1fs" % (fr, t, time.time() - t0), flush=True)
