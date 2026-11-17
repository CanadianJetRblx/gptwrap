"""Airbus A350-900 flight deck, built procedurally in Blender.

Run:   python3 build_cockpit.py [--render] [--preview] [--views a,b,c]
   or: blender -b -P build_cockpit.py -- [--render]

Axes: +X = right (F/O side), +Y = forward, +Z = up.  Units are metres.
Origin: aircraft centreline, cockpit floor, at the pilots' design eye station
(the pilots' eyes are at X = -/+0.53, Y = 0, Z = 1.22).

Layout and proportions were taken from photographs of real A350-900/-1000
flight decks and scaled from known hardware sizes (see REFERENCES.md).
"""
import math
import os
import sys

import bpy  # must come first: the bpy module provides bmesh and mathutils
import bmesh
from mathutils import Matrix, Vector

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import displays  # noqa: E402
import panels  # noqa: E402
import seat  # noqa: E402

TEX = os.path.join(HERE, "textures")
ARGS = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]

# --------------------------------------------------------------------------
# Key dimensions (metres)
# --------------------------------------------------------------------------
SEAT_X = 0.53                       # pilot seat centreline offset
EYE_Z = 1.22                        # design eye height above the floor
DISP_W, DISP_H = 0.332, 0.207       # active area of the six 15.4 in displays
BEZ_W, BEZ_H = 0.356, 0.232         # display unit outline
COL_W = 0.075                       # narrow columns either side of the centre display
DZUS = 0.146                        # standard pedestal module width
MIP_TILT = 15.0                     # main instrument panel lean from vertical
MIP_O = Vector((0.0, 0.70, 0.675))  # bottom-centre of the main instrument panel
MIP_H = 0.290
MIP_HINGE = BEZ_W / 2 + COL_W + BEZ_W + 0.004   # half-width of the flat centre section
OIS_SIDE_W = 0.070                  # side panel outboard of each OIS display
MIP_WING = BEZ_W + OIS_SIDE_W + 0.014
MIP_WING_ANG = 25.0                 # the OIS displays are angled in toward the pilots
DISP_Y = 0.150                      # display centre height on the panel

PED_F = Vector((0.0, 0.685, 0.690))                     # top of the sloped front section
PED_SLOPE, PED_SLOPE_LEN = 30.0, 0.300
PED_A = PED_F + Vector((0, -math.cos(math.radians(PED_SLOPE)), -math.sin(math.radians(PED_SLOPE)))) * PED_SLOPE_LEN
PED_LEN = 1.118                                         # flat part, sloping 3 degrees down toward the aft end
PED_B = PED_A + Vector((0, -math.cos(math.radians(3)), -math.sin(math.radians(3)))) * PED_LEN
PED_W_FWD, PED_W_AFT = 0.600, 0.500

GS_Y = 0.575                        # pilot-facing edge of the glareshield
GS_Z0, GS_WING_H, GS_BLOCK_H = 0.975, 0.048, 0.090

OVH_FRONT = Vector((0.0, 0.60, 1.755))
OVH_AFT = Vector((0.0, -0.42, 2.03))
OVH_CANT = 12.0                     # side columns of the overhead are canted

# Window / shell stations, right-hand side, running from the rear wall forward
# around the nose to the centreline.  S = window sill, Tp = window top, Rp = roof.
S = [(1.40, -1.80, 1.06), (1.40, -0.55, 1.06), (1.34, 0.12, 1.045), (1.32, 0.20, 1.045),
     (1.05, 0.90, 1.03), (1.00, 0.97, 1.03), (0.045, 1.25, 1.03), (0.0, 1.25, 1.03)]
Tp = [(1.18, -1.80, 1.80), (1.16, -0.48, 1.64), (1.10, -0.06, 1.68), (1.08, 0.01, 1.685),
      (0.87, 0.40, 1.705), (0.83, 0.45, 1.71), (0.045, 0.66, 1.735), (0.0, 0.66, 1.735)]
Rp = [(0.42, -1.80, 2.03), (0.42, -0.42, 2.03), (0.42, -0.06, 1.933), (0.42, 0.01, 1.914),
      (0.42, 0.55, 1.768), (0.42, 0.60, 1.755), (0.045, 0.60, 1.755), (0.0, 0.60, 1.755)]
BULGE = [1.0, 1.0, 1.0, 1.0, 0.6, 0.5, 0.15, 0.15]
GLASS_BAYS = {1: "Window_Aft_Side", 3: "Window_Fwd_Side", 5: "Windshield"}


def V(p):
    return Vector(p)


def lerp(a, b, t):
    return V(a) * (1 - t) + V(b) * t


def frame(o, x, y):
    """4x4 matrix with origin o, local x along x, local y as close to y as possible."""
    x = V(x).normalized()
    y = V(y)
    y = (y - x * y.dot(x)).normalized()
    z = x.cross(y)
    M = Matrix.Identity(4)
    for i in range(3):
        M[i][0], M[i][1], M[i][2], M[i][3] = x[i], y[i], z[i], o[i]
    return M


def Tr(x=0.0, y=0.0, z=0.0):
    return Matrix.Translation((x, y, z))


def Rx(d):
    return Matrix.Rotation(math.radians(d), 4, "X")


def Ry(d):
    return Matrix.Rotation(math.radians(d), 4, "Y")


def Rz(d):
    return Matrix.Rotation(math.radians(d), 4, "Z")


def align_z(p0, p1):
    """Matrix placing local +Z along p0 -> p1, origin at p0."""
    p0, p1 = V(p0), V(p1)
    z = (p1 - p0).normalized()
    ref = Vector((0, 0, 1)) if abs(z.z) < 0.95 else Vector((1, 0, 0))
    x = ref.cross(z).normalized()
    y = z.cross(x)
    M = Matrix.Identity(4)
    for i in range(3):
        M[i][0], M[i][1], M[i][2], M[i][3] = x[i], y[i], z[i], p0[i]
    return M


def sill_x(y):
    """Half-width of the cockpit at sill height for a given station y."""
    pts = S[:5]
    for a, b in zip(pts, pts[1:]):
        if a[1] <= y <= b[1]:
            t = (y - a[1]) / (b[1] - a[1])
            return a[0] + (b[0] - a[0]) * t
    return pts[0][0] if y < pts[0][1] else pts[-1][0]


# --------------------------------------------------------------------------
# Scene / collections / materials
# --------------------------------------------------------------------------
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.unit_settings.system = "METRIC"
COLL = {}


def coll(name):
    if name not in COLL:
        c = bpy.data.collections.new(name)
        scene.collection.children.link(c)
        COLL[name] = c
    return COLL[name]


MAT = {}


def srgb(r, g, b):
    def f(c):
        c /= 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    return (f(r), f(g), f(b), 1.0)


def principled(name, color, rough=0.5, metal=0.0, emit=None, emit_strength=0.0, coat=0.0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = color
    b.inputs["Roughness"].default_value = rough
    b.inputs["Metallic"].default_value = metal
    if coat:
        b.inputs["Coat Weight"].default_value = coat
    if emit:
        b.inputs["Emission Color"].default_value = emit
        b.inputs["Emission Strength"].default_value = emit_strength
    m.diffuse_color = color
    MAT[name] = m
    return m


def image_material(name, base_path, emit_path=None, emit_strength=1.0, rough=0.5, screen=False):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    b = nt.nodes["Principled BSDF"]
    b.inputs["Roughness"].default_value = rough
    t = nt.nodes.new("ShaderNodeTexImage")
    t.image = bpy.data.images.load(base_path, check_existing=True)
    t.location = (-420, 300)
    if screen:
        b.inputs["Base Color"].default_value = (0.004, 0.004, 0.005, 1)
        nt.links.new(t.outputs["Color"], b.inputs["Emission Color"])
        b.inputs["Emission Strength"].default_value = emit_strength
        b.inputs["Coat Weight"].default_value = 0.6
        b.inputs["Coat Roughness"].default_value = 0.08
    else:
        nt.links.new(t.outputs["Color"], b.inputs["Base Color"])
        if emit_path:
            e = nt.nodes.new("ShaderNodeTexImage")
            e.image = bpy.data.images.load(emit_path, check_existing=True)
            e.location = (-420, 0)
            nt.links.new(e.outputs["Color"], b.inputs["Emission Color"])
            b.inputs["Emission Strength"].default_value = emit_strength
    MAT[name] = m
    return m


def make_materials():
    principled("liner", srgb(150, 166, 186), 0.72)            # light blue-grey lining
    principled("liner_low", srgb(118, 132, 152), 0.75)
    principled("liner_dark", srgb(52, 58, 68), 0.8)
    principled("panel", srgb(*panels.PLATE), 0.55)            # Airbus blue-grey panels
    principled("panel_dark", srgb(74, 86, 104), 0.55)
    principled("glareshield", srgb(40, 44, 52), 0.9)
    principled("black_plastic", srgb(22, 22, 24), 0.42)
    principled("black_gloss", srgb(10, 10, 12), 0.18, coat=0.5)
    principled("rubber", srgb(16, 16, 17), 0.85)
    principled("metal", srgb(190, 192, 196), 0.32, metal=1.0)
    principled("metal_dark", srgb(70, 72, 76), 0.4, metal=1.0)
    principled("knob_white", srgb(*panels.KNOB_W), 0.5)
    principled("red", srgb(196, 34, 30), 0.4)
    principled("white", srgb(225, 225, 222), 0.45)
    principled("carpet", srgb(34, 36, 42), 1.0)
    principled("door", srgb(150, 166, 186), 0.6)
    principled("bezel", srgb(96, 110, 130), 0.5)
    principled("sunshade", (0.9, 0.45, 0.02, 1), 0.3)
    g = bpy.data.materials.new("window_glass")
    g.use_nodes = True
    nt = g.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    mix = nt.nodes.new("ShaderNodeMixShader")
    tr = nt.nodes.new("ShaderNodeBsdfTransparent")
    gl = nt.nodes.new("ShaderNodeBsdfGlossy")
    fr = nt.nodes.new("ShaderNodeFresnel")
    fr.inputs["IOR"].default_value = 1.25
    gl.inputs["Roughness"].default_value = 0.02
    tr.inputs["Color"].default_value = (0.96, 0.98, 0.97, 1)
    nt.links.new(fr.outputs[0], mix.inputs[0])
    nt.links.new(tr.outputs[0], mix.inputs[1])
    nt.links.new(gl.outputs[0], mix.inputs[2])
    nt.links.new(mix.outputs[0], out.inputs[0])
    g.diffuse_color = (0.6, 0.75, 0.8, 0.25)
    MAT["window_glass"] = g


# --------------------------------------------------------------------------
# Mesh builder
# --------------------------------------------------------------------------
class MB:
    def __init__(self, name):
        self.name = name
        self.bm = bmesh.new()
        self.uv = self.bm.loops.layers.uv.new("UVMap")
        self.mats = []

    def mi(self, mat):
        if mat not in self.mats:
            self.mats.append(mat)
        return self.mats.index(mat)

    def _merge(self, tb, M, mat):
        idx = self.mi(mat)
        vmap = {}
        for v in tb.verts:
            vmap[v.index] = self.bm.verts.new(M @ v.co if M is not None else v.co)
        out = []
        for f in tb.faces:
            try:
                nf = self.bm.faces.new([vmap[v.index] for v in f.verts])
            except ValueError:
                continue
            nf.material_index = idx
            out.append(nf)
        tb.free()
        return out

    def box(self, sx, sy, sz, M=None, mat="panel", bevel=0.0, segs=2):
        tb = bmesh.new()
        bmesh.ops.create_cube(tb, size=1.0)
        for v in tb.verts:
            v.co.x *= sx
            v.co.y *= sy
            v.co.z *= sz
        if bevel > 0:
            bmesh.ops.bevel(tb, geom=tb.edges[:], offset=min(bevel, 0.45 * min(sx, sy, sz)), segments=segs,
                            profile=0.5, affect="EDGES")
        tb.verts.index_update()
        return self._merge(tb, M, mat)

    def cyl(self, r, h, M=None, mat="black_plastic", segs=20, r2=None):
        """Cylinder / cone along local +Z, base at z = 0."""
        tb = bmesh.new()
        bmesh.ops.create_cone(tb, cap_ends=True, cap_tris=False, segments=segs, radius1=r,
                              radius2=r if r2 is None else r2, depth=h)
        for v in tb.verts:
            v.co.z += h / 2
        tb.verts.index_update()
        return self._merge(tb, M, mat)

    def sphere(self, r, M=None, mat="black_plastic", u=16, v=10, scale=(1, 1, 1)):
        tb = bmesh.new()
        bmesh.ops.create_uvsphere(tb, u_segments=u, v_segments=v, radius=r)
        for vv in tb.verts:
            vv.co.x *= scale[0]
            vv.co.y *= scale[1]
            vv.co.z *= scale[2]
        tb.verts.index_update()
        return self._merge(tb, M, mat)

    def rod(self, p0, p1, r, mat="metal_dark", segs=10, r2=None):
        return self.cyl(r, (V(p1) - V(p0)).length, align_z(p0, p1), mat, segs, r2)

    def strut(self, p0, p1, w, t, mat="frame", normal=None, bevel=0.004):
        """Rectangular beam from p0 to p1; w across, t along `normal`."""
        p0, p1 = V(p0), V(p1)
        d = p1 - p0
        n = V(normal) if normal is not None else Vector((0, 0, 1))
        M = frame((p0 + p1) / 2, d.cross(n), d)
        return self.box(w, d.length, t, M, mat, bevel)

    def poly(self, pts, mat, M=None):
        idx = self.mi(mat)
        vs = [self.bm.verts.new(M @ V(p) if M is not None else V(p)) for p in pts]
        f = self.bm.faces.new(vs)
        f.material_index = idx
        return f

    def prism(self, outline, z0, z1, mat, M=None):
        """Extrude a 2D outline (list of (x, y)) from z0 to z1."""
        n = len(outline)
        self.poly([(x, y, z1) for x, y in outline], mat, M)
        self.poly([(x, y, z0) for x, y in reversed(outline)], mat, M)
        for i in range(n):
            a, b = outline[i], outline[(i + 1) % n]
            self.poly([(a[0], a[1], z0), (b[0], b[1], z0), (b[0], b[1], z1), (a[0], a[1], z1)], mat, M)

    def finish(self, collection, sharp_deg=35.0, solidify=0.0, smooth=True):
        bm = self.bm
        bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=1e-6)
        bm.normal_update()
        lim = math.radians(sharp_deg)
        for e in bm.edges:
            if len(e.link_faces) == 2:
                try:
                    e.smooth = e.calc_face_angle() < lim
                except ValueError:
                    e.smooth = False
            else:
                e.smooth = False
        for f in bm.faces:
            f.smooth = smooth
        me = bpy.data.meshes.new(self.name)
        bm.to_mesh(me)
        bm.free()
        for m in self.mats:
            me.materials.append(MAT[m])
        ob = bpy.data.objects.new(self.name, me)
        coll(collection).objects.link(ob)
        if solidify:
            sm = ob.modifiers.new("Solidify", "SOLIDIFY")
            sm.thickness = solidify
            sm.offset = -1.0
        if smooth:
            wn = ob.modifiers.new("WeightedNormal", "WEIGHTED_NORMAL")
            wn.keep_sharp = True
        return ob


# --------------------------------------------------------------------------
# Panels and displays
# --------------------------------------------------------------------------
def write_textures():
    os.makedirs(TEX, exist_ok=True)
    disp = displays.save_all(TEX)
    for k, p in disp.items():
        image_material("screen_" + k, p, emit_strength=1.3, rough=0.25, screen=True)
    built = {}
    for k, fn in panels.ALL.items():
        P = fn()
        bp = os.path.join(TEX, "panel_%s.png" % k)
        ep = os.path.join(TEX, "panel_%s_emit.png" % k)
        P.img.save(bp)
        P.emit.save(ep)
        image_material("panel_" + k, bp, ep, emit_strength=2.5, rough=0.55)
        built[k] = P
    return built


def add_screen(name, M, w, h, key, collection):
    """Emissive display surface, lower-left corner at the origin of M."""
    mb = MB(name)
    f = mb.poly([(0, 0, 0), (w, 0, 0), (w, h, 0), (0, h, 0)], "screen_" + key, M)
    for lp, uv in zip(f.loops, ((0, 0), (1, 0), (1, 1), (0, 1))):
        lp[mb.uv].uv = uv
    return mb.finish(collection, smooth=False)


def build_panel(P, key, M, collection, thickness=0.008):
    """Face plate + controls from a panels.Panel, placed with matrix M (lower-left corner)."""
    mb = MB(P.name)
    mat = "panel_" + key
    mb.box(P.w, P.h, thickness, Tr(P.w / 2, P.h / 2, -thickness / 2), mat)
    for g in P.geo:
        kind = g[0]
        if kind == "box":
            _, x, y, w, h, z0, z1 = g
            mb.box(w, h, z1 - z0 + 0.001, Tr(x, y, (z0 + z1) / 2 - 0.0005), mat)
        elif kind == "cyl":
            _, x, y, r, z0, z1, segs = g
            mb.cyl(r, z1 - z0, Tr(x, y, z0), mat, segs)
        elif kind == "knob":
            _, x, y, r, h, ptr, white = g
            body = "knob_white" if white else "black_plastic"
            mb.cyl(r, h, Tr(x, y, 0.002), body, 20, r2=r * 0.80)
            mb.box(0.0016, r * 0.9, 0.0016, Tr(x, y, h + 0.002) @ Rz(-ptr) @ Tr(0, r * 0.38, 0),
                   "black_plastic" if white else "white")
        elif kind == "guard":
            _, x, y, w, h, hz = g
            mb.box(w, h, 0.003, Tr(x, y + h / 2 - 0.002, 0.004) @ Rx(-14) @ Tr(0, -h / 2 + 0.002, hz * 0.5), mat, 0.001)
            mb.box(w, 0.003, hz * 0.6, Tr(x, y + h / 2 - 0.0015, hz * 0.3), mat)
        elif kind == "toggle":
            _, x, y, tilt, paddle = g
            mb.cyl(0.0048, 0.004, Tr(x, y, 0), "metal", 6)
            Mt = Tr(x, y, 0.003) @ Rx(-tilt)
            mb.cyl(0.0020, 0.018, Mt, "metal", 10, r2=0.0026)
            if paddle:
                mb.box(0.016, 0.004, 0.009, Mt @ Tr(0, 0, 0.020), "metal", 0.001)
            else:
                mb.box(0.0058, 0.0034, 0.008, Mt @ Tr(0, 0, 0.020), "metal", 0.001)
        elif kind == "guardtoggle":
            _, x, y = g
            mb.cyl(0.0048, 0.004, Tr(x, y, 0), "metal", 6)
            mb.cyl(0.0020, 0.020, Tr(x, y, 0.003), "metal", 10, r2=0.0026)
            mb.box(0.030, 0.036, 0.004, Tr(x, y + 0.018, 0.004) @ Rx(-25) @ Tr(0, -0.018, 0.012), "red", 0.001)
        elif kind == "dome":
            _, x, y, rx, ry, rz, inboard_right = g
            mb.sphere(1.0, Tr(x, y, 0.0), "panel", 24, 14, scale=(rx, ry, rz))
            sgn = 1 if inboard_right else -1
            mb.sphere(0.0115, Tr(x + sgn * rx * 0.86, y - ry * 0.10, rz * 0.34), "black_gloss")
            mb.cyl(0.0075, 0.006, Tr(x - sgn * rx * 0.90, y - ry * 0.05, rz * 0.30) @ Ry(-sgn * 70), "black_plastic", 14)
            mb.box(0.030, 0.012, 0.004, Tr(x, y + ry * 0.90, rz * 0.34) @ Rx(48), "black_plastic", 0.001)
        elif kind == "master":
            _, x, y, n = g
            Ml = Tr(x, y - 0.004, 0.0) @ Rx(22)
            mb.box(0.0055, 0.0055, 0.026, Ml @ Tr(0, 0, 0.013), "metal", 0.001)
            mb.box(0.017, 0.017, 0.013, Ml @ Tr(0, 0, 0.031), "black_plastic", 0.002)
            mb.box(0.012, 0.012, 0.001, Ml @ Tr(0, 0, 0.038), "white")
        elif kind == "parkbrk":
            _, x, y = g
            mb.box(0.014, 0.014, 0.020, Tr(x, y, 0.010), "black_plastic", 0.002)
            mb.box(0.024, 0.066, 0.030, Tr(x, y, 0.034) @ Rx(-8), "black_plastic", 0.007, 3)
        elif kind == "rudtrim":
            _, x, y = g
            mb.cyl(0.0185, 0.014, Tr(x, y, 0.002), "knob_white", 28, r2=0.016)
            mb.box(0.010, 0.036, 0.022, Tr(x, y, 0.026), "knob_white", 0.003)
        elif kind == "flapguide":
            _, x, y = g
            for sx in (-0.016, 0.016):
                mb.cyl(0.085, 0.018, Tr(x + sx - 0.009, y, -0.058) @ Ry(90), "panel", 40)
    idx = mb.mi(mat)
    for f in mb.bm.faces:
        if f.material_index == idx:
            for lp in f.loops:
                co = lp.vert.co
                lp[mb.uv].uv = (min(max(co.x / P.w, 0.002), 0.998), min(max(co.y / P.h, 0.002), 0.998))
    mb.bm.transform(M)
    ob = mb.finish(collection)
    for i, (x0, y0, x1, y1, skey) in enumerate(P.screens):
        add_screen("%s_screen%d" % (P.name, i), M @ Tr(x0, y0, 0.0078), x1 - x0, y1 - y0, skey, collection)
    return ob


def build_display(name, M, key, collection, depth=0.035):
    """One of the six large display units.  M: centre of the screen, z toward the viewer."""
    mb = MB(name + "_bezel")
    mb.box(BEZ_W, BEZ_H, depth, M @ Tr(0, 0, -depth / 2 + 0.006), "bezel", 0.003)
    rw, rh = (BEZ_W - DISP_W) / 2, (BEZ_H - DISP_H) / 2
    for sx, sy, w, h in ((0, 1, BEZ_W, rh), (0, -1, BEZ_W, rh), (1, 0, rw, DISP_H), (-1, 0, rw, DISP_H)):
        mb.box(w, h, 0.004, M @ Tr(sx * (DISP_W + rw) / 2, sy * (DISP_H + rh) / 2, 0.007), "bezel", 0.001)
    for sx in (-0.11, -0.04, 0.04, 0.11):                       # latch tabs on the top edge
        mb.box(0.018, 0.006, 0.003, M @ Tr(sx, BEZ_H / 2 - 0.004, 0.0095), "black_plastic", 0.001)
    mb.finish(collection)
    add_screen(name, M @ Tr(-DISP_W / 2, -DISP_H / 2, 0.0062), DISP_W, DISP_H, key, collection)


# --------------------------------------------------------------------------
# Cockpit shell, windows, floor
# --------------------------------------------------------------------------
def station_rings():
    F = [(s[0] - 0.05, s[1], 0.0) for s in S]
    F[-1] = (0.0, S[-1][1], 0.0)
    U = []
    for k in range(len(S)):
        mid = lerp(Tp[k], Rp[k], 0.5)
        U.append(tuple(mid + Vector((0.09, 0.0, 0.07)) * BULGE[k]))
    return F, U


def rounded_window(p00, p10, p11, p01, margin=0.05, radius=0.085, n=7):
    """Rounded-corner aperture inside a four-sided bay.  Returns (inner loop, outer loop) as 3D points."""
    p00, p10, p11, p01 = V(p00), V(p10), V(p11), V(p01)
    lu = ((p10 - p00).length + (p11 - p01).length) / 2
    lv = ((p01 - p00).length + (p11 - p10).length) / 2
    mu, mv, ru, rv = margin / lu, margin / lv, radius / lu, radius / lv

    def B(u, v):
        return p00 * (1 - u) * (1 - v) + p10 * u * (1 - v) + p11 * u * v + p01 * (1 - u) * v

    inner, outer = [], []
    corners = (((1 - mu - ru, mv + rv), -90, lambda t, c: (c[0] + (1 - c[0]) * 2 * t, 0.0) if t < 0.5 else (1.0, c[1] * (2 * t - 1))),
               ((1 - mu - ru, 1 - mv - rv), 0, lambda t, c: (1.0, c[1] + (1 - c[1]) * 2 * t) if t < 0.5 else (1 - (1 - c[0]) * (2 * t - 1), 1.0)),
               ((mu + ru, 1 - mv - rv), 90, lambda t, c: (c[0] * (1 - 2 * t), 1.0) if t < 0.5 else (0.0, 1 - (1 - c[1]) * (2 * t - 1))),
               ((mu + ru, mv + rv), 180, lambda t, c: (0.0, c[1] * (1 - 2 * t)) if t < 0.5 else (c[0] * (2 * t - 1), 0.0)))
    for c, a0, fo in corners:
        for i in range(n):
            t = i / (n - 1)
            a = math.radians(a0 + 90 * t)
            inner.append(B(c[0] + ru * math.cos(a), c[1] + rv * math.sin(a)))
            outer.append(B(*fo(t, c)))
    return inner, outer


def build_shell():
    F, U = station_rings()
    mb = MB("Shell_Lining")
    inside = Vector((0, -0.2, 1.2))

    def add(target, pts, mat):
        for sgn in (1, -1):
            q = [(sgn * p[0], p[1], p[2]) for p in pts]
            f = target.poly(q, mat)
            f.normal_update()
            if f.normal.dot(f.calc_center_median() - inside) > 0:
                f.normal_flip()

    n = len(S)
    for k in range(n - 1):
        add(mb, [F[k], F[k + 1], S[k + 1], S[k]], "liner_low")
        if k in GLASS_BAYS:
            wide = k == 5
            inner, outer = rounded_window(S[k], S[k + 1], Tp[k + 1], Tp[k], margin=0.045 if wide else 0.06,
                                          radius=0.10 if wide else 0.12)
            m = len(inner)
            for i in range(m):
                j = (i + 1) % m
                if (V(outer[i]) - V(outer[j])).length < 1e-6:
                    add(mb, [inner[i], inner[j], outer[i]], "liner")
                else:
                    add(mb, [inner[i], inner[j], outer[j], outer[i]], "liner")
            for sgn in (1, -1):
                g = MB("%s_%s" % (GLASS_BAYS[k], "R" if sgn > 0 else "L"))
                loop = [V((sgn * p[0], p[1], p[2])) for p in inner]
                nrm = (loop[1] - loop[0]).cross(loop[len(loop) // 2] - loop[0]).normalized()
                c = sum(loop, Vector()) / len(loop)
                if nrm.dot(c - inside) < 0:
                    nrm = -nrm
                g.poly([p + nrm * 0.035 for p in loop], "window_glass")
                g.finish("Structure", smooth=False)
        else:
            add(mb, [S[k], S[k + 1], Tp[k + 1], Tp[k]], "liner")
        add(mb, [Tp[k], Tp[k + 1], U[k + 1], U[k]], "liner")
        add(mb, [U[k], U[k + 1], Rp[k + 1], Rp[k]], "liner")
    for k in range(5):                      # ceiling strip that carries the overhead panel
        mb.poly([Rp[k], Rp[k + 1], (-Rp[k + 1][0], Rp[k + 1][1], Rp[k + 1][2]), (-Rp[k][0], Rp[k][1], Rp[k][2])],
                "liner")
    ring = [F[0], S[0], Tp[0], U[0], Rp[0]]
    mb.poly(ring + [(-p[0], p[1], p[2]) for p in reversed(ring)], "liner")
    mb.poly(F[:-1] + [(-p[0], p[1], p[2]) for p in reversed(F[:-1])], "carpet")
    mb.finish("Structure", solidify=0.05)

    d = MB("Structure_Details")
    # windshield centre post with standby compass, placard and two spot lights
    d.strut(V(S[7]) + Vector((0, -0.03, 0.0)), V(Tp[7]) + Vector((0, -0.03, 0.0)), 0.11, 0.06, "liner",
            (0, -0.72, -0.69), 0.02)
    d.box(0.10, 0.07, 0.06, Tr(0, 0.70, 1.665) @ Rx(-45), "liner_low", 0.012)
    d.cyl(0.026, 0.008, Tr(0, 0.672, 1.640) @ Rx(135), "black_gloss", 24)
    d.box(0.05, 0.004, 0.06, Tr(0, 0.80, 1.545) @ Rx(-45), "white", 0.001)
    for sx in (-0.022, 0.022):
        d.cyl(0.007, 0.004, Tr(sx, 0.715, 1.688) @ Rx(135), "red", 12)
    # sill rails and slotted air vents under the side windows
    for sgn in (1, -1):
        for k in (1, 2, 3):
            a = V((sgn * (S[k][0] - 0.03), S[k][1], S[k][2] - 0.035))
            b = V((sgn * (S[k + 1][0] - 0.03), S[k + 1][1], S[k + 1][2] - 0.035))
            d.strut(a, b, 0.08, 0.04, "liner_low", (0, 0, 1), 0.012)
        a, b = V((sgn * (S[3][0] - 0.055), S[3][1] + 0.06, 0.975)), V((sgn * (S[4][0] - 0.055), S[4][1] - 0.12, 0.965))
        d.strut(a, b, 0.030, 0.012, "liner_dark", (sgn, 0.4, 0), 0.002)
        for i in range(14):
            p = lerp(a, b, (i + 0.5) / 14)
            d.box(0.004, 0.034, 0.014, frame(p, (sgn, 0.4, 0.0), (0, 0, 1)), "liner", 0.0)
        # roller sun shades stowed above the side windows
        d.rod((sgn * (Tp[3][0] - 0.02), Tp[3][1] + 0.03, Tp[3][2] - 0.02),
              (sgn * (Tp[4][0] - 0.02), Tp[4][1] - 0.03, Tp[4][2] - 0.02), 0.022, "liner_dark", 14)
    # ceiling: pods flanking the overhead panel and two dark recesses aft of it
    for sgn in (1, -1):
        d.box(0.26, 0.86, 0.10, Tr(sgn * 0.60, -0.02, 1.90) @ Rx(-15) @ Ry(sgn * 18), "liner", 0.04, 4)
        for i in range(7):
            d.box(0.012, 0.075, 0.004, Tr(sgn * 0.52, 0.02, 1.868) @ Rx(-15) @ Ry(sgn * 18) @ Tr(0, 0, -0.012)
                  @ Tr(0, -0.12 + i * 0.0, 0) @ Tr(sgn * (i - 3) * 0.018, 0, 0), "liner_dark")
        d.prism([(sgn * 0.52, -0.62), (sgn * 0.98, -0.80), (sgn * 0.62, -1.22)] if sgn > 0 else
                [(sgn * 0.62, -1.22), (sgn * 0.98, -0.80), (sgn * 0.52, -0.62)], 1.985, 2.02, "liner_dark")
    d.finish("Structure")

    door = MB("Cockpit_Door")
    door.box(0.66, 0.035, 1.92, Tr(0, -1.785, 0.96), "liner_low", 0.006)
    door.box(0.58, 0.04, 1.84, Tr(0, -1.77, 0.94), "door", 0.006)
    door.box(0.10, 0.03, 0.16, Tr(0.0, -1.747, 1.50), "panel_dark", 0.004)
    door.rod((0.22, -1.74, 0.98), (0.22, -1.74, 1.10), 0.011, "metal")
    door.rod((0.22, -1.75, 0.98), (0.22, -1.71, 0.98), 0.008, "metal")
    door.finish("Structure")


# --------------------------------------------------------------------------
# Main instrument panel
# --------------------------------------------------------------------------
def mip_frames():
    t = math.radians(MIP_TILT)
    up = Vector((0, math.sin(t), math.cos(t)))
    x = Vector((1, 0, 0))
    n = x.cross(up)                         # points aft and slightly up
    centre = frame(MIP_O, x, up)
    a = math.radians(MIP_WING_ANG)
    xr = x * math.cos(a) + n * math.sin(a)  # right wing runs outboard and aft
    right = frame(MIP_O + x * MIP_HINGE, xr, up)
    xl = x * math.cos(a) - n * math.sin(a)
    left = frame(MIP_O - x * MIP_HINGE - xl * MIP_WING, xl, up)
    return centre, left, right


def build_main_panel(P):
    centre, left, right = mip_frames()
    c = "MainPanel"
    mb = MB("MIP_Structure")
    th = 0.06
    mb.box(2 * MIP_HINGE, MIP_H, th, centre @ Tr(0, MIP_H / 2, -th / 2 - 0.002), "panel")
    for Mw in (left, right):
        mb.box(MIP_WING, MIP_H, th, Mw @ Tr(MIP_WING / 2, MIP_H / 2, -th / 2 - 0.002), "panel")
        mb.box(MIP_WING, 0.05, 0.10, Mw @ Tr(MIP_WING / 2, -0.025, -0.05), "liner_low", 0.01)   # pod underside
    mb.finish(c)

    xc = BEZ_W / 2 + COL_W + BEZ_W / 2
    build_display("Display_Upper_Centre_ED_SD_WD", centre @ Tr(0, DISP_Y, 0), "ecam", c)
    build_display("Display_CAPT_PFD_ND", centre @ Tr(-xc, DISP_Y, 0), "pfd_nd_capt", c)
    build_display("Display_FO_PFD_ND", centre @ Tr(xc, DISP_Y, 0), "pfd_nd_fo", c)
    build_display("Display_CAPT_OIS", left @ Tr(MIP_WING - 0.006 - BEZ_W / 2, DISP_Y, 0), "ois_capt", c)
    build_display("Display_FO_OIS", right @ Tr(0.006 + BEZ_W / 2, DISP_Y, 0), "ois_fo", c)
    build_panel(P["col_l"], "col_l", centre @ Tr(-BEZ_W / 2 - COL_W, 0.0, 0.0), c)
    build_panel(P["col_r"], "col_r", centre @ Tr(BEZ_W / 2, 0.0, 0.0), c)
    y0 = DISP_Y - BEZ_H / 2
    build_panel(P["oisside_l"], "oisside_l", left @ Tr(0.004, y0, 0.0), c)
    build_panel(P["oisside_r"], "oisside_r", right @ Tr(MIP_WING - 0.004 - OIS_SIDE_W, y0, 0.0), c)

    # landing gear lever (shown UP) in the right-hand column
    g = MB("Landing_Gear_Lever")
    M = centre @ Tr(BEZ_W / 2 + 0.023, 0.118, 0.004)
    g.box(0.008, 0.012, 0.050, M @ Rx(-10) @ Tr(0, 0, 0.025), "black_plastic", 0.002)
    g.cyl(0.017, 0.014, M @ Rx(-10) @ Tr(-0.007, 0, 0.056) @ Ry(90), "black_plastic", 28)
    g.finish(c)
    return centre


# --------------------------------------------------------------------------
# Glareshield with AFS / EFIS control panels
# --------------------------------------------------------------------------
def build_glareshield(P):
    c = "Glareshield"
    zt = GS_Z0 + GS_WING_H
    lean = 0.006
    rear = [(0.0, GS_Y), (0.80, GS_Y), (1.02, 0.505), (1.215, 0.47)]
    front = [(0.0, 1.25), (1.00, 0.97), (1.05, 0.90), (1.215, 0.47)]
    mipt = [(0.0, 0.776), (MIP_HINGE, 0.776), (1.02, 0.60), (1.215, 0.52)]
    mb = MB("Glareshield")
    for sgn in (1, -1):
        def P3(p, z):
            return (sgn * p[0], p[1], z)

        def add(pts, mat="glareshield"):
            mb.poly(pts if sgn > 0 else pts[::-1], mat)
        add([P3(rear[0], zt), P3(rear[1], zt), P3(front[1], 1.032), P3(front[0], 1.032)])
        add([P3(rear[1], zt), P3(rear[2], zt), P3(front[2], 1.032), P3(front[1], 1.032)])
        add([P3(rear[2], zt), P3(rear[3], zt), P3(front[2], 1.032)])
        for i in range(3):
            a, b = rear[i], rear[i + 1]
            add([(sgn * a[0], a[1] - lean, GS_Z0), (sgn * b[0], b[1] - lean, GS_Z0), P3(b, zt), P3(a, zt)], "panel")
            add([P3(mipt[i], 0.958), P3(mipt[i + 1], 0.958), (sgn * b[0], b[1] - lean, GS_Z0),
                 (sgn * a[0], a[1] - lean, GS_Z0)], "panel_dark")
    mb.finish(c, sharp_deg=50)

    # raised centre block that carries the EFIS control panels and the AFS control panel
    hw = 0.120 + 0.185 + 0.036 + 0.004
    sh = 0.075
    zb = GS_Z0 + GS_BLOCK_H + 0.006
    blk = MB("Glareshield_Centre_Block")

    def section(y, top, half, shoulder, yl):
        return [(-half - shoulder, y, zt + 0.001), (-half, y + yl, top), (half, y + yl, top), (half + shoulder, y, zt + 0.001),
                (half + shoulder, y, GS_Z0), (-half - shoulder, y, GS_Z0)]
    s0 = section(GS_Y - 0.008, zb, hw, sh, 0.012)
    s1 = section(GS_Y + 0.14, zb - 0.004, hw - 0.02, sh, 0.0)
    s2 = section(GS_Y + 0.42, zt + 0.004, hw - 0.14, sh + 0.05, 0.0)
    blk.poly(s0[::-1], "panel")
    for a, b in ((s0, s1), (s1, s2)):
        for i in range(6):
            j = (i + 1) % 6
            blk.poly([a[i], a[j], b[j], b[i]], "glareshield" if i < 3 else "panel_dark")
    blk.finish(c, sharp_deg=40)

    up = Vector((0, 0.012, GS_BLOCK_H)).normalized()
    x = Vector((1, 0, 0))
    nrm = x.cross(up)
    base = Vector((0.0, GS_Y - 0.008, GS_Z0 + 0.003)) + nrm * 0.002

    def place(key, x0):
        build_panel(P[key], key, frame(base + x * x0, x, up), c, thickness=0.010)

    place("afs", -0.120)
    place("efis_l", -0.120 - 0.185)
    place("efis_r", 0.120)
    place("warn_l", -0.120 - 0.185 - 0.036)
    place("warn_r", 0.120 + 0.185)
    upw = Vector((0, lean, GS_WING_H)).normalized()
    nw = x.cross(upw)
    bw = Vector((0.0, GS_Y - lean, GS_Z0)) + nw * 0.002
    for key, x0 in (("wingin_l", -hw - sh - 0.200), ("wingin_r", hw + sh), ("wingout_l", -0.795), ("wingout_r", 0.625)):
        build_panel(P[key], key, frame(bw + x * x0, x, upw), c, thickness=0.006)


# --------------------------------------------------------------------------
# Pedestal
# --------------------------------------------------------------------------
def build_pedestal(P):
    c = "Pedestal"
    x = Vector((1, 0, 0))
    u = (PED_A - PED_B).normalized()           # forward along the flat pedestal top
    nrm = x.cross(u)
    y_step = PED_A.y - 0.27 * u.y              # where the pedestal narrows, aft of the KCCUs
    z_step = PED_A.z - 0.27 * u.z

    mb = MB("Pedestal_Body")
    Mx = frame((0, 0, 0), (0, 1, 0), (0, 0, 1))      # prism local x->Y, y->Z, z->X
    fwd = [(0.74, 0.0), (0.74, PED_F.z - 0.03), (PED_F.y, PED_F.z - 0.004), (PED_A.y, PED_A.z - 0.004),
           (y_step, z_step - 0.004), (y_step, 0.0)]
    aft = [(y_step, 0.0), (y_step, z_step - 0.004), (PED_B.y, PED_B.z - 0.004), (PED_B.y, 0.0)]
    mb.prism(fwd, -PED_W_FWD / 2, PED_W_FWD / 2, "panel", Mx)
    mb.prism(aft, -PED_W_AFT / 2, PED_W_AFT / 2, "panel", Mx)
    # rounded aft fairing down to the floor
    arc = [(PED_W_AFT / 2 * math.cos(math.radians(a)), PED_B.y - 0.10 * math.sin(math.radians(a)))
           for a in range(0, 181, 15)]
    mb.prism(arc[::-1], 0.0, PED_B.z - 0.03, "liner")
    # raised side rails
    for sgn in (-1, 1):
        mb.strut(V((sgn * (PED_W_FWD / 2 - 0.012), PED_A.y, PED_A.z + 0.004)),
                 V((sgn * (PED_W_FWD / 2 - 0.012), y_step, z_step + 0.004)), 0.024, 0.016, "panel", nrm, 0.006)
        mb.strut(V((sgn * (PED_W_FWD / 2 - 0.004), PED_F.y, PED_F.z + 0.004)),
                 V((sgn * (PED_W_FWD / 2 - 0.004), PED_A.y, PED_A.z + 0.004)), 0.008, 0.016, "panel", (0, 0.5, 0.87), 0.003)
    # black grab pocket on the left side, abeam the park brake
    mb.box(0.03, 0.20, 0.10, Tr(-PED_W_AFT / 2 - 0.004, PED_A.y - 0.70, 0.42), "black_plastic", 0.012)
    mb.finish(c)

    # sloped front section: ISIS units either side of the lower centre display
    up_s = (PED_F - PED_A).normalized()
    ns = x.cross(up_s)
    mid = (PED_A + PED_F) / 2 + ns * 0.004
    build_display("Display_Lower_Centre_MFD", frame(mid + up_s * 0.012, x, up_s), "mfd", c)
    top = mid + up_s * (0.012 + BEZ_H / 2)
    for key, x0 in (("isis_l", -BEZ_W / 2 - 0.006 - 0.105), ("isis_r", BEZ_W / 2 + 0.006)):
        build_panel(P[key], key, frame(top + x * x0 - up_s * 0.200, x, up_s), c)

    placed = {}

    def place(key, x0, s_fwd):
        """Panel whose forward edge is s_fwd metres aft of the start of the flat section."""
        pan = P[key]
        Mp = frame(PED_A - u * (s_fwd + pan.h) + x * x0 + nrm * 0.004, x, u)
        build_panel(pan, key, Mp, c)
        placed[key] = Mp

    place("kccu_l", -0.265, 0.0)
    place("thrust", -0.075, 0.0)
    place("kccu_r", 0.075, 0.0)
    L, C, R = -0.0925 - DZUS, -0.0925, 0.0925
    for key, x0, s0 in (("rmp1", L, 0.27), ("eng_ecp", C, 0.27), ("rmp2", R, 0.27),
                        ("spdbrk", L, 0.49), ("surv", C, 0.49), ("flaps", R, 0.49),
                        ("park", L, 0.65), ("trim", C, 0.65), ("blank_r1", R, 0.65),
                        ("lg", L, 0.775), ("ckptlt", C, 0.775), ("rmp3", R, 0.715),
                        ("printer", L, 0.915), ("blank_r2", R, 0.935)):
        place(key, x0, s0)

    # ---- thrust levers (idle) on their quadrant -----------------------------
    Mt = placed["thrust"]
    t = MB("Thrust_Levers")
    t.cyl(0.092, 0.092, Mt @ Tr(0.029, 0.150, -0.030) @ Ry(90), "panel", 48)             # quadrant drum
    t.box(0.120, 0.230, 0.012, Mt @ Tr(0.075, 0.150, 0.006), "panel", 0.004)
    for lx, out in ((0.060, -1), (0.090, 1)):
        piv = Mt @ Tr(lx, 0.150, -0.030) @ Rx(12)
        t.box(0.020, 0.036, 0.210, piv @ Tr(0, 0, 0.105), "black_plastic", 0.004)
        t.cyl(0.016, 0.066, piv @ Tr(out * 0.005 - (0.033 if out > 0 else 0.033), 0, 0.212) @ Ry(90), "black_plastic", 20)
        t.cyl(0.0085, 0.008, piv @ Tr(out * 0.038, 0, 0.212) @ Ry(out * 90), "red", 14)   # A/THR instinctive disconnect
        t.box(0.018, 0.010, 0.060, piv @ Tr(0, 0.024, 0.150) @ Rx(-16), "black_plastic", 0.002)   # reverse lever
    t.finish(c)

    # ---- speed brake lever (retracted) --------------------------------------
    s = MB("Speed_Brake_Lever")
    piv = placed["spdbrk"] @ Tr(0.098, 0.118, -0.02) @ Rx(-6)
    s.box(0.008, 0.014, 0.080, piv @ Tr(0, 0, 0.040), "black_plastic", 0.002)
    s.box(0.040, 0.030, 0.034, piv @ Tr(0, 0, 0.094), "black_plastic", 0.010, 3)
    s.finish(c)

    # ---- flap lever (0) ------------------------------------------------------
    f = MB("Flap_Lever")
    piv = placed["flaps"] @ Tr(0.066, 0.122, -0.02) @ Rx(-6)
    f.box(0.008, 0.014, 0.100, piv @ Tr(0, 0, 0.050), "black_plastic", 0.002)
    f.box(0.062, 0.030, 0.014, piv @ Tr(0, 0, 0.104) @ Rx(8), "black_plastic", 0.006, 3)
    f.box(0.062, 0.006, 0.016, piv @ Tr(0, -0.016, 0.092), "black_plastic", 0.002)
    f.finish(c)

    # ---- handset at the aft end ----------------------------------------------
    hs = MB("Handset")
    Mh = frame(PED_B + u * 0.035 + nrm * 0.004, x, u)
    hs.box(0.30, 0.060, 0.016, Mh @ Tr(0.0, 0.0, 0.008), "black_plastic", 0.006)
    hs.box(0.24, 0.045, 0.030, Mh @ Tr(0.02, 0.0, 0.028), "black_plastic", 0.012, 3)
    hs.finish(c)


# --------------------------------------------------------------------------
# Overhead panel
# --------------------------------------------------------------------------
def build_overhead(P):
    c = "Overhead"
    yv = (OVH_AFT - OVH_FRONT).normalized()
    x = Vector((1, 0, 0))
    nrm = x.cross(yv)                    # points down
    drop = 0.055
    wc, ws = P["ovhd_c"].w, P["ovhd_l"].w
    o = OVH_FRONT + nrm * drop + yv * 0.008
    a = math.radians(OVH_CANT)
    xl = x * math.cos(a) - nrm * math.sin(a)     # left column: outer (left) edge hangs lower
    xr = x * math.cos(a) + nrm * math.sin(a)
    frames = {"ovhd_c": frame(o - x * (wc / 2), x, yv),
              "ovhd_l": frame(o - x * (wc / 2 + 0.004) - xl * ws, xl, yv),
              "ovhd_r": frame(o + x * (wc / 2 + 0.004), xr, yv)}
    mb = MB("Overhead_Housing")
    for key, Mo in frames.items():
        pan = P[key]
        build_panel(pan, key, Mo, c, thickness=0.010)
        mb.box(pan.w + 0.012, pan.h + 0.03, 0.07, Mo @ Tr(pan.w / 2, pan.h / 2, -0.010 - 0.035), "panel", 0.006)
    mb.box(wc + 0.02, 0.05, 0.05, frames["ovhd_c"] @ Tr(wc / 2, -0.02, -0.02), "panel", 0.012)   # front lip
    mb.finish(c)
    h = MB("Escape_Hatch")
    h.box(0.56, 0.62, 0.02, Tr(0, -1.10, 2.022), "liner_low", 0.02)
    h.box(0.12, 0.05, 0.03, Tr(0.0, -0.86, 2.005), "red", 0.008)
    h.finish(c)


# --------------------------------------------------------------------------
# Seats (see seat.py: rigged, with pivots for rake, recline, headrest and armrests)
# --------------------------------------------------------------------------
SEAT_TRACK_X = 0.54     # seat centreline; leaves ~1 cm to the pedestal and the side console


def build_seats():
    c = coll("Seats")
    seat.build_crew_seat("Seat_CAPT", (-SEAT_TRACK_X, 0.0, 0.0), +1, c)
    seat.build_crew_seat("Seat_FO", (SEAT_TRACK_X, 0.0, 0.0), -1, c)
    seat.build_crew_seat("Seat_Third_Occupant", (0.0, -1.30, 0.0), +1, c, observer=True)


# --------------------------------------------------------------------------
# Side consoles, side-sticks, tillers, rudder pedals, tables
# --------------------------------------------------------------------------
def build_side(sgn, P):
    """sgn = -1 captain (left), +1 first officer (right)."""
    c = "SideConsoles"
    tag = "CAPT" if sgn < 0 else "FO"
    top = 0.60
    inner = 0.83
    ys = [-1.05, -0.55, 0.12, 0.20, 0.50]
    outline = [(inner, ys[0])] + [(sill_x(y) - 0.035, y) for y in ys] + [(inner, ys[-1])]
    mb = MB("Side_Console_" + tag)
    pts = [(sgn * px, py) for px, py in outline]
    if sgn > 0:
        pts = pts[::-1]
    mb.prism(pts, 0.0, top, "liner_low")
    # raised desk carrying the side-stick; sloped front face with the loudspeaker grille
    mb.box(0.30, 0.34, 0.03, Tr(sgn * 1.00, 0.20, top + 0.015), "liner", 0.012)
    # moulded stowage bins aft, with a lid
    mb.box(0.30, 0.44, 0.012, Tr(sgn * 1.10, -0.62, top + 0.006), "liner_dark", 0.004)
    mb.box(0.16, 0.20, 0.02, Tr(sgn * 1.02, -0.36, top + 0.012), "liner", 0.008)
    mb.cyl(0.042, 0.014, Tr(sgn * 1.20, 0.02, top + 0.030), "white", 24)                    # cup holder ring
    mb.cyl(0.036, 0.015, Tr(sgn * 1.20, 0.02, top + 0.030), "rubber", 24)
    mb.rod((sgn * (inner - 0.012), -0.08, 0.50), (sgn * (inner - 0.012), -0.08, 0.66), 0.018, "black_plastic", 16)  # torch
    mb.box(0.16, 0.26, 0.11, Tr(sgn * 1.20, -0.90, top + 0.055), "liner_low", 0.012)        # oxygen mask stowage
    for dy in (-0.05, 0.05):
        mb.box(0.012, 0.05, 0.045, Tr(sgn * 1.115, -0.90 + dy, top + 0.06), "red", 0.004)
    mb.finish(c)
    Mg = frame((sgn * 0.93 - 0.08, 0.375, top - 0.045), (1, 0, 0), (0, 0.55, 0.83))
    build_panel(P["grille"], "grille", Mg @ Tr(0, 0, 0.004), c, thickness=0.02)
    build_panel(P["sidewall"], "sidewall", Mg @ Tr(0.175 if sgn > 0 else -0.075, 0.01, 0.004), c, thickness=0.02)
    w = MB("Side_Wall_Fittings_" + tag)                     # air outlet and grab handle outboard of the OIS display
    wx = sill_x(0.52) - 0.07
    w.cyl(0.028, 0.03, Tr(sgn * wx, 0.52, 0.86) @ Ry(-sgn * 75), "black_plastic", 24)
    w.cyl(0.020, 0.032, Tr(sgn * wx, 0.52, 0.86) @ Ry(-sgn * 75), "black_gloss", 24)
    w.box(0.012, 0.06, 0.035, Tr(sgn * (sill_x(0.42) - 0.065), 0.42, 0.93), "liner_low", 0.004)
    w.finish(c)

    # side-stick on its stepped rubber boot
    s = MB("Sidestick_" + tag)
    base = Tr(sgn * 0.93, 0.20, top + 0.030)
    for i, w in enumerate((0.150, 0.128, 0.106, 0.084)):
        s.box(w, w, 0.013, base @ Tr(0, 0, 0.0065 + i * 0.012), "rubber", 0.006)
    G = base @ Tr(0, 0, 0.050) @ Rx(-12) @ Ry(-sgn * 8)
    s.cyl(0.017, 0.085, G, "black_plastic", 20, r2=0.020)
    s.box(0.046, 0.058, 0.075, G @ Tr(0, 0.006, 0.118), "black_plastic", 0.016, 3)
    s.cyl(0.0085, 0.007, G @ Tr(-sgn * 0.022, -0.004, 0.140) @ Ry(-sgn * 90), "red", 14)    # takeover push-button
    s.box(0.012, 0.010, 0.026, G @ Tr(0, 0.036, 0.118), "black_gloss", 0.003)               # radio trigger
    s.finish(c)

    # nose-wheel steering tiller, outboard and aft of the side-stick
    t = MB("Tiller_" + tag)
    tb = Tr(sgn * 1.085, 0.11, top + 0.030)
    t.cyl(0.050, 0.014, tb, "panel_dark", 28)
    t.cyl(0.040, 0.016, tb @ Tr(0, 0, 0.012), "black_plastic", 28, r2=0.030)
    t.cyl(0.012, 0.045, tb @ Tr(0, 0, 0.026), "black_plastic", 14)
    t.box(0.024, 0.110, 0.020, tb @ Tr(0, 0.02, 0.078) @ Rz(sgn * 20), "black_plastic", 0.008, 3)
    t.cyl(0.011, 0.030, tb @ Rz(sgn * 20) @ Tr(0, 0.070, 0.080), "black_plastic", 14)
    t.finish(c)

    # rudder pedals, pedal adjustment handle and the stowed sliding table
    p = MB("Rudder_Pedals_" + tag)
    for dx in (-0.115, 0.115):
        px = sgn * SEAT_X + dx
        Mp = Tr(px, 0.98, 0.20) @ Rx(58)
        p.box(0.105, 0.16, 0.014, Mp, "metal_dark", 0.005)
        for i in range(4):
            p.box(0.095, 0.010, 0.004, Mp @ Tr(0, -0.055 + i * 0.036, 0.009), "rubber", 0.001)
        p.rod((px, 1.02, 0.24), (px, 1.08, 0.62), 0.013, "metal_dark")
        p.box(0.11, 0.07, 0.02, Tr(px, 0.80, 0.135) @ Rx(20), "black_plastic", 0.006)
    p.box(0.14, 0.26, 0.42, Tr(sgn * SEAT_X, 0.86, 0.36), "black_plastic", 0.02)             # central column
    p.box(0.07, 0.03, 0.05, Tr(sgn * SEAT_X, 0.725, 0.50), "black_plastic", 0.008)           # PULL TO ADJUST PEDALS
    p.finish(c)
    k = MB("Sliding_Table_" + tag)
    k.box(0.52, 0.30, 0.030, Tr(sgn * SEAT_X, 0.78, 0.640), "black_plastic", 0.006)
    k.box(0.16, 0.03, 0.035, Tr(sgn * SEAT_X, 0.635, 0.632), "black_plastic", 0.008)
    k.finish(c)


# --------------------------------------------------------------------------
# World, lights, cameras
# --------------------------------------------------------------------------
def build_world():
    w = bpy.data.worlds.new("Sky")
    scene.world = w
    w.use_nodes = True
    nt = w.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputWorld")
    bg = nt.nodes.new("ShaderNodeBackground")
    sky = nt.nodes.new("ShaderNodeTexSky")
    for attr, val in (("sun_elevation", math.radians(38)), ("sun_rotation", math.radians(-125)),
                      ("altitude", 11000.0), ("sun_intensity", 0.35)):
        try:
            setattr(sky, attr, val)
        except Exception as ex:
            print("sky:", attr, ex)
    tc = nt.nodes.new("ShaderNodeTexCoord")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(tc.outputs["Generated"], sep.inputs[0])

    def math_node(op, a=None, b=None):
        n = nt.nodes.new("ShaderNodeMath")
        n.operation = op
        for i, v in enumerate((a, b)):
            if v is None:
                continue
            if isinstance(v, (int, float)):
                n.inputs[i].default_value = v
            else:
                nt.links.new(v, n.inputs[i])
        return n.outputs[0]

    negz = math_node("MULTIPLY", sep.outputs["Z"], -1.0)
    safe = math_node("MAXIMUM", negz, 0.02)
    comb = nt.nodes.new("ShaderNodeCombineXYZ")
    nt.links.new(math_node("DIVIDE", sep.outputs["X"], safe), comb.inputs[0])
    nt.links.new(math_node("DIVIDE", sep.outputs["Y"], safe), comb.inputs[1])
    noise = nt.nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 0.9
    noise.inputs["Detail"].default_value = 8.0
    noise.inputs["Roughness"].default_value = 0.62
    nt.links.new(comb.outputs[0], noise.inputs["Vector"])
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].position = 0.40
    ramp.color_ramp.elements[0].color = (0.10, 0.20, 0.36, 1)
    ramp.color_ramp.elements[1].position = 0.62
    ramp.color_ramp.elements[1].color = (0.95, 0.96, 0.98, 1)
    nt.links.new(noise.outputs[0], ramp.inputs[0])
    haze = nt.nodes.new("ShaderNodeMixRGB")
    haze.inputs[2].default_value = (0.72, 0.82, 0.93, 1)
    hz = nt.nodes.new("ShaderNodeMapRange")
    for i, v in ((1, 0.0), (2, 0.14), (3, 1.0), (4, 0.0)):
        hz.inputs[i].default_value = v
    nt.links.new(negz, hz.inputs[0])
    nt.links.new(hz.outputs[0], haze.inputs[0])
    nt.links.new(ramp.outputs[0], haze.inputs[1])
    mix = nt.nodes.new("ShaderNodeMixRGB")
    nt.links.new(math_node("GREATER_THAN", negz, 0.0), mix.inputs[0])
    nt.links.new(sky.outputs[0], mix.inputs[1])
    nt.links.new(haze.outputs[0], mix.inputs[2])
    hsv = nt.nodes.new("ShaderNodeHueSaturation")       # keep the daylight close to neutral inside the cockpit
    hsv.inputs["Saturation"].default_value = 0.45
    nt.links.new(mix.outputs[0], hsv.inputs["Color"])
    nt.links.new(hsv.outputs[0], bg.inputs[0])
    bg.inputs[1].default_value = 1.0
    nt.links.new(bg.outputs[0], out.inputs[0])


def look_at(ob, target):
    d = V(target) - ob.location
    ob.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()


def build_cameras():
    cams = {}
    specs = {
        "overview": ((0.0, -0.92, 1.70), (0.0, 0.62, 0.86), 14.0),
        "captain": ((-SEAT_X, -0.04, EYE_Z + 0.02), (-0.18, 0.80, 0.86), 16.0),
        "panel": ((0.0, -0.30, 1.42), (0.0, 0.66, 0.80), 22.0),
        "pedestal": ((0.0, -0.75, 1.62), (0.0, 0.02, 0.52), 24.0),
        "overhead": ((0.0, -0.62, 1.02), (0.0, 0.10, 1.90), 16.0),
        "glareshield": ((0.0, -0.02, 1.12), (0.0, 0.60, 0.98), 30.0),
        "fo_side": ((0.05, -0.55, 1.50), (0.85, 0.42, 0.72), 18.0),
        "rear": ((0.0, -1.62, 1.50), (0.0, 0.50, 1.05), 13.0),
        "captain_seat": ((0.10, 0.42, 1.10), (-0.54, -0.12, 0.74), 20.0),
    }
    for name, (loc, tgt, lens) in specs.items():
        cd = bpy.data.cameras.new("Cam_" + name)
        cd.lens = lens
        cd.sensor_width = 36.0
        cd.clip_start = 0.02
        cd.clip_end = 500.0
        ob = bpy.data.objects.new("Cam_" + name, cd)
        ob.location = loc
        look_at(ob, tgt)
        coll("Cameras").objects.link(ob)
        cams[name] = ob
    scene.camera = cams["overview"]
    return cams


def build_lights():
    ld = bpy.data.lights.new("Dome_Light", "AREA")
    ld.energy = 70.0
    ld.size = 0.5
    ld.color = (1.0, 0.96, 0.9)
    ob = bpy.data.objects.new("Dome_Light", ld)
    ob.location = (0.0, -0.95, 1.98)
    coll("Lights").objects.link(ob)
    for sx in (-0.45, 0.0, 0.45):
        lf = bpy.data.lights.new("Panel_Flood", "AREA")
        lf.shape = "RECTANGLE"
        lf.size = 0.40
        lf.size_y = 0.03
        lf.energy = 3.0
        o2 = bpy.data.objects.new("Panel_Flood", lf)
        o2.location = (sx, 0.69, 0.952)
        o2.rotation_euler = (math.radians(15), 0, 0)
        coll("Lights").objects.link(o2)


def setup_render(preview=False):
    scene.render.engine = "CYCLES"
    cy = scene.cycles
    cy.device = "CPU"
    cy.samples = 40 if preview else 96
    cy.use_adaptive_sampling = True
    cy.adaptive_threshold = 0.05 if preview else 0.03
    cy.use_denoising = True
    cy.max_bounces = 6 if preview else 8
    cy.sample_clamp_indirect = 8.0
    cy.caustics_reflective = False
    cy.caustics_refractive = False
    scene.render.resolution_x = 960 if preview else 1600
    scene.render.resolution_y = 540 if preview else 900
    scene.render.image_settings.file_format = "PNG"
    try:
        scene.view_settings.view_transform = "AgX"
        scene.view_settings.look = "AgX - Medium High Contrast"
    except Exception as ex:
        print("view:", ex)
    scene.view_settings.exposure = 0.25


# --------------------------------------------------------------------------
def main():
    preview = "--preview" in ARGS
    make_materials()
    P = write_textures()
    build_shell()
    build_main_panel(P)
    build_glareshield(P)
    build_pedestal(P)
    build_overhead(P)
    build_seats()
    build_side(-1, P)
    build_side(1, P)
    build_world()
    build_lights()
    cams = build_cameras()
    setup_render(preview)

    for img in bpy.data.images:
        if img.filepath and not img.packed_file:
            img.pack()
    if "--no-save" not in ARGS:
        bpy.ops.wm.save_as_mainfile(filepath=os.path.join(HERE, "a350_900_cockpit.blend"), compress=True)
    n_obj = len([o for o in bpy.data.objects if o.type == "MESH"])
    n_tri = sum(sum(len(p.vertices) - 2 for p in o.data.polygons) for o in bpy.data.objects if o.type == "MESH")
    print("objects:", n_obj, "triangles:", n_tri)

    if "--render" in ARGS:
        views = list(cams)
        if "--views" in ARGS:
            views = ARGS[ARGS.index("--views") + 1].split(",")
        out = os.path.join(HERE, "renders_preview" if preview else "renders")
        os.makedirs(out, exist_ok=True)
        for v in views:
            scene.camera = cams[v]
            scene.render.filepath = os.path.join(out, "a350_cockpit_%s.png" % v)
            bpy.ops.render.render(write_still=True)
            print("rendered", scene.render.filepath)


main()
