"""A350 flight-crew seat, built procedurally for Blender.

The seat is a small rig rather than a single mesh:

    <Seat>                 empty on the floor at the seat centreline
      <Seat>_Base          floor tracks, carriage and lift column
      <Seat>_Pan           seat pan; origin at its rear pivot, rotate X to rake
        <Seat>_Back        backrest; origin at the recline hinge, rotate X to recline
          <Seat>_Headrest
          <Seat>_Armrest_L / _R   origin at the hinge, rotate X to stow / deploy

so recline, rake and armrests can be posed in Blender by rotating one object.

Shapes are rounded boxes generated directly (no modifiers): the edges are
true ellipse arcs with their own radius per axis, and cushions are then
sculpted by displacement functions (lumbar bulge, thoracic bolsters, seam
creases, dished seat pan).  The proportions, trim and detail follow
photographs of in-service A350 flight decks (see REFERENCES in README.md).

Units: metres.  Seat frame: +X right, +Y forward, +Z up, origin on the floor.
Run standalone to build and render a seat on its own:

    python3 seat.py [--render] [--out DIR]
"""
import math
import os
import random

import bpy  # noqa: F401  (bmesh and mathutils come from the bpy module)
import bmesh
from mathutils import Matrix, Vector
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
TEX = os.path.join(HERE, "textures")

# --------------------------------------------------------------------------
# Key dimensions (seat frame)
# --------------------------------------------------------------------------
PAN_PIVOT = Vector((0.0, -0.06, 0.36))     # rear of the seat-pan frame
PAN_RAKE = 4.0                              # seat pan front raised, degrees
BACK_PIVOT = Vector((0.0, -0.085, 0.03))    # recline hinge, in the pan frame
BACK_RECLINE = 10.0                         # relative to the pan (total ~14 deg from vertical)
ARM_HINGE_X = 0.250                         # armrest hinge offset, backrest frame
ARM_HINGE = (-0.040, 0.165)                 # (y, z) of the armrest hinge, backrest frame

PAN_LO, PAN_HI = (-0.250, -0.080, 0.000), (0.250, 0.400, 0.088)
BACK_LO, BACK_HI = (-0.221, -0.030, -0.050), (0.221, 0.075, 0.660)
HEAD_LO, HEAD_HI = (-0.190, -0.072, 0.665), (0.190, 0.082, 0.905)
SHELL_LO, SHELL_HI = (-0.231, -0.125, -0.075), (0.231, 0.110, 0.860)
SHELL_CUT_Y = 0.028


def sstep(a, b, x):
    t = min(max((x - a) / (b - a), 0.0), 1.0)
    return t * t * (3 - 2 * t)


def gauss(x, mu, s):
    return math.exp(-((x - mu) / s) ** 2)


def Tr(x=0.0, y=0.0, z=0.0):
    return Matrix.Translation((x, y, z))


def Rx(d):
    return Matrix.Rotation(math.radians(d), 4, "X")


def Ry(d):
    return Matrix.Rotation(math.radians(d), 4, "Y")


def Rz(d):
    return Matrix.Rotation(math.radians(d), 4, "Z")


# --------------------------------------------------------------------------
# Surface functions shared by the cushion meshes and the harness paths
# --------------------------------------------------------------------------
def back_front_offset(x, z):
    """How far the backrest cushion front stands proud of its base plane."""
    ax = abs(x)
    lumbar = 0.019 * gauss(z, 0.19, 0.09) * (1 - 0.45 * (x / 0.221) ** 2)
    bolster = 0.036 * sstep(0.122, 0.195, ax) * sstep(0.20, 0.40, z) * (1 - 0.5 * sstep(0.56, 0.66, z))
    seam = -0.0045 * gauss(ax, 0.122, 0.0045) * sstep(-0.03, 0.02, z) * (1 - sstep(0.60, 0.64, z))
    top_roll = -0.006 * sstep(0.56, 0.66, z)
    return lumbar + bolster + seam + top_roll


def pan_top_offset(x, y):
    """Height change of the seat-pan cushion top (dish, thigh bolsters, waterfall front)."""
    ax = abs(x)
    dish = -0.009 * (1 - min(1.0, (x / 0.25) ** 2)) * sstep(-0.08, 0.06, y) * (1 - sstep(0.22, 0.36, y))
    bolster = 0.008 * sstep(0.15, 0.235, ax) * sstep(0.0, 0.20, y)
    waterfall = -0.010 * sstep(0.30, 0.40, y)
    rear = -0.004 * (1 - sstep(-0.08, 0.0, y))
    return dish + bolster + waterfall + rear


def back_front_point(x, z, lift=0.0):
    return Vector((x, BACK_HI[1] + back_front_offset(x, z) + lift, z))


def pan_top_point(x, y, lift=0.0):
    return Vector((x, y, PAN_HI[2] + pan_top_offset(x, y) + lift))


# --------------------------------------------------------------------------
# Mesh builder
# --------------------------------------------------------------------------
class MB:
    def __init__(self, name):
        self.name = name
        self.bm = bmesh.new()
        self.uv = self.bm.loops.layers.uv.new("UVMap")
        self.mats = []
        self.sharp = set()

    def mi(self, mat):
        if mat not in self.mats:
            self.mats.append(mat)
        return self.mats.index(mat)

    # ---- rounded box with per-axis elliptical edge radii -------------------
    def rbox(self, lo, hi, R, n=(8, 8, 8), m=4, extra=((), (), ()), deform=None, mat="seat_black",
             cut=None, M=None):
        axes = []
        for a in range(3):
            h = (hi[a] - lo[a]) / 2
            c = (hi[a] + lo[a]) / 2
            r = min(R[a], h * 0.999)
            band = [h - r + r * math.tan(math.radians(45.0 * k / m)) for k in range(m + 1)]
            inner = [-(h - r) + 2 * (h - r) * i / max(1, n[a]) for i in range(n[a] + 1)]
            ex = [e - c for e in extra[a] if abs(e - c) < h - r]
            vals = sorted(set(round(v, 7) for v in [-b for b in band] + inner + band + ex))
            axes.append((vals, c, h, r))
        (xs, cx, hx, rx), (ys, cy, hy, ry), (zs, cz, hz, rz) = axes
        hh, rr, cc = (hx, hy, hz), (rx, ry, rz), (cx, cy, cz)
        verts = {}
        idx = self.mi(mat)

        def V(i, j, k):
            key = (i, j, k)
            v = verts.get(key)
            if v is not None:
                return v
            p = (xs[i], ys[j], zs[k])
            inner = [max(-(hh[a] - rr[a]), min(hh[a] - rr[a], p[a])) for a in range(3)]
            d = [(p[a] - inner[a]) / rr[a] for a in range(3)]
            L = math.sqrt(d[0] ** 2 + d[1] ** 2 + d[2] ** 2)
            q = [inner[a] + (d[a] / L * rr[a] if L > 1e-9 else 0.0) + cc[a] for a in range(3)]
            q = Vector(q)
            if deform:
                q = deform(q)
            if M is not None:
                q = M @ q
            v = self.bm.verts.new(q)
            verts[key] = v
            return v

        nx, ny, nz = len(xs), len(ys), len(zs)
        quads = []
        for i in (0, nx - 1):
            for j in range(ny - 1):
                for k in range(nz - 1):
                    quads.append(((i, j, k), (i, j + 1, k), (i, j + 1, k + 1), (i, j, k + 1)))
        for j in (0, ny - 1):
            for i in range(nx - 1):
                for k in range(nz - 1):
                    quads.append(((i, j, k), (i + 1, j, k), (i + 1, j, k + 1), (i, j, k + 1)))
        for k in (0, nz - 1):
            for i in range(nx - 1):
                for j in range(ny - 1):
                    quads.append(((i, j, k), (i + 1, j, k), (i + 1, j + 1, k), (i, j + 1, k)))
        faces = []
        for q in quads:
            if cut is not None:
                c = [sum((xs, ys, zs)[a][q[t][a]] for t in range(4)) / 4 + cc[a] for a in range(3)]
                if cut(*c):
                    continue
            try:
                f = self.bm.faces.new([V(*t) for t in q])
            except ValueError:
                continue
            f.material_index = idx
            faces.append(f)
        bmesh.ops.recalc_face_normals(self.bm, faces=faces)
        return faces

    def box(self, lo, hi, r=0.003, mat="seat_black", M=None, n=(1, 1, 1), m=2):
        return self.rbox(lo, hi, (r, r, r), n=n, m=m, mat=mat, M=M)

    def cyl(self, r, h, M, mat="seat_black", segs=24, r2=None, caps=True):
        tb = bmesh.new()
        bmesh.ops.create_cone(tb, cap_ends=caps, cap_tris=False, segments=segs, radius1=r,
                              radius2=r if r2 is None else r2, depth=h)
        for v in tb.verts:
            v.co.z += h / 2
        return self._merge(tb, M, mat, sharp_caps=True)

    def sphere(self, r, M, mat="seat_black", u=20, v=12, scale=(1, 1, 1)):
        tb = bmesh.new()
        bmesh.ops.create_uvsphere(tb, u_segments=u, v_segments=v, radius=r)
        for vv in tb.verts:
            vv.co.x *= scale[0]
            vv.co.y *= scale[1]
            vv.co.z *= scale[2]
        return self._merge(tb, M, mat)

    def torus(self, R, r, M, mat="seat_black", segs=28, rsegs=10):
        idx = self.mi(mat)
        rings = []
        for i in range(segs):
            a = 2 * math.pi * i / segs
            ring = []
            for j in range(rsegs):
                b = 2 * math.pi * j / rsegs
                p = Vector(((R + r * math.cos(b)) * math.cos(a), (R + r * math.cos(b)) * math.sin(a), r * math.sin(b)))
                ring.append(self.bm.verts.new(M @ p))
            rings.append(ring)
        for i in range(segs):
            for j in range(rsegs):
                a, b = rings[i], rings[(i + 1) % segs]
                f = self.bm.faces.new([a[j], b[j], b[(j + 1) % rsegs], a[(j + 1) % rsegs]])
                f.material_index = idx

    def _merge(self, tb, M, mat, sharp_caps=False):
        idx = self.mi(mat)
        tb.verts.ensure_lookup_table()
        vmap = {v.index: self.bm.verts.new(M @ v.co if M is not None else v.co) for v in tb.verts}
        out = []
        for f in tb.faces:
            try:
                nf = self.bm.faces.new([vmap[v.index] for v in f.verts])
            except ValueError:
                continue
            nf.material_index = idx
            if sharp_caps and len(f.verts) > 4:
                nf.smooth = False
                self.sharp.add(nf)
            out.append(nf)
        tb.free()
        return out

    def prism(self, outline, z0, z1, M, mat="seat_black", uv_box=None):
        """Extrude a 2D outline (counter-clockwise list of (x, y)) from z0 to z1."""
        idx = self.mi(mat)
        n = len(outline)
        top = [self.bm.verts.new(M @ Vector((x, y, z1))) for x, y in outline]
        bot = [self.bm.verts.new(M @ Vector((x, y, z0))) for x, y in outline]
        ft = self.bm.faces.new(top)
        fb = self.bm.faces.new(bot[::-1])
        for f in (ft, fb):
            f.material_index = idx
            f.smooth = False
            self.sharp.add(f)
        if uv_box:
            x0, y0, x1, y1 = uv_box
            for lp, (x, y) in zip(ft.loops, outline):
                lp[self.uv].uv = ((x - x0) / (x1 - x0), (y - y0) / (y1 - y0))
        for i in range(n):
            j = (i + 1) % n
            f = self.bm.faces.new([bot[i], bot[j], top[j], top[i]])
            f.material_index = idx
        return ft

    def decal(self, outline, M, mat, uv_box):
        """Flat image decal; outline counter-clockwise in the decal plane."""
        idx = self.mi(mat)
        vs = [self.bm.verts.new(M @ Vector((x, y, 0.0))) for x, y in outline]
        f = self.bm.faces.new(vs)
        f.material_index = idx
        f.smooth = False
        self.sharp.add(f)
        x0, y0, x1, y1 = uv_box
        for lp, (x, y) in zip(f.loops, outline):
            lp[self.uv].uv = ((x - x0) / (x1 - x0), (y - y0) / (y1 - y0))
        return f

    def tube(self, pts, r, mat, closed=False, segs=8):
        pts = [Vector(p) for p in pts]
        idx = self.mi(mat)
        n = len(pts)
        rings = []
        prev_side = None
        for i in range(n):
            if closed:
                t = (pts[(i + 1) % n] - pts[i - 1]).normalized()
            else:
                t = (pts[min(i + 1, n - 1)] - pts[max(i - 1, 0)]).normalized()
            ref = prev_side if prev_side is not None else (Vector((0, 0, 1)) if abs(t.z) < 0.9 else Vector((1, 0, 0)))
            side = (ref - t * ref.dot(t)).normalized()
            prev_side = side
            up = t.cross(side)
            rings.append([self.bm.verts.new(pts[i] + (side * math.cos(2 * math.pi * k / segs) +
                                                      up * math.sin(2 * math.pi * k / segs)) * r)
                          for k in range(segs)])
        for i in range(n if closed else n - 1):
            a, b = rings[i], rings[(i + 1) % n]
            for k in range(segs):
                f = self.bm.faces.new([a[k], b[k], b[(k + 1) % segs], a[(k + 1) % segs]])
                f.material_index = idx
        if not closed:
            for ring in (rings[0], rings[-1][::-1]):
                f = self.bm.faces.new(ring[::-1])
                f.material_index = idx

    def ribbon(self, pts, normals, width, thick, mat, steps=6):
        """Flat strap (webbing) along a smoothed path; normals = surface normal at each control point."""
        P, N = catmull(pts, normals, steps)
        idx = self.mi(mat)
        rings = []
        for i in range(len(P)):
            t = (P[min(i + 1, len(P) - 1)] - P[max(i - 1, 0)]).normalized()
            n = (N[i] - t * N[i].dot(t)).normalized()
            s = t.cross(n).normalized()
            c = P[i] + n * (thick / 2)
            rings.append([self.bm.verts.new(c + s * sx * width / 2 + n * sz * thick / 2)
                          for sx, sz in ((-1, -1), (1, -1), (1, 1), (-1, 1))])
        for i in range(len(rings) - 1):
            a, b = rings[i], rings[i + 1]
            for k in range(4):
                f = self.bm.faces.new([a[k], a[(k + 1) % 4], b[(k + 1) % 4], b[k]])
                f.material_index = idx
                f.smooth = False
        for ring in (rings[0], rings[-1][::-1]):
            f = self.bm.faces.new(ring)
            f.material_index = idx
        return P, N

    def finish(self, collection, parent=None, location=(0, 0, 0), rotation=(0, 0, 0), name=None):
        bm = self.bm
        bm.normal_update()
        for f in bm.faces:
            if f not in self.sharp:
                f.smooth = True
        me = bpy.data.meshes.new(name or self.name)
        bm.to_mesh(me)
        bm.free()
        for m in self.mats:
            me.materials.append(bpy.data.materials[m])
        ob = bpy.data.objects.new(name or self.name, me)
        collection.objects.link(ob)
        ob.parent = parent
        ob.location = location
        ob.rotation_euler = [math.radians(a) for a in rotation]
        return ob


def catmull(pts, normals, steps):
    pts = [Vector(p) for p in pts]
    normals = [Vector(n).normalized() for n in normals]
    P, N = [], []
    for i in range(len(pts) - 1):
        p0, p1, p2, p3 = pts[max(i - 1, 0)], pts[i], pts[i + 1], pts[min(i + 2, len(pts) - 1)]
        for s in range(steps):
            t = s / steps
            t2, t3 = t * t, t * t * t
            P.append(0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2 +
                            (-p0 + 3 * p1 - 3 * p2 + p3) * t3))
            N.append((normals[i] * (1 - t) + normals[i + 1] * t).normalized())
    P.append(pts[-1])
    N.append(normals[-1])
    return P, N


def rounded_rect(w, h, r, n=6, notch=None):
    """Counter-clockwise rounded rectangle centred on the origin; notch=(width, depth) cut into the top edge."""
    pts = []
    for cx, cy, a0 in ((w / 2 - r, -h / 2 + r, -90), (w / 2 - r, h / 2 - r, 0), (-w / 2 + r, h / 2 - r, 90),
                       (-w / 2 + r, -h / 2 + r, 180)):
        if a0 == 90 and notch:
            nw, nd = notch
            k = 14
            for i in range(k + 1):
                a = math.pi * i / k
                pts.append((nw / 2 * math.cos(a), h / 2 - nd * math.sin(a) ** 0.8))
        for i in range(n + 1):
            a = math.radians(a0 + 90 * i / n)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def ellipse(w, h, n=40):
    return [(w / 2 * math.cos(2 * math.pi * i / n), h / 2 * math.sin(2 * math.pi * i / n)) for i in range(n)]


def knurl(r, lobes=12, depth=0.12, n=96):
    return [((r * (1 - depth * 0.5 + depth * 0.5 * math.cos(lobes * 2 * math.pi * i / n))) * math.cos(2 * math.pi * i / n),
             (r * (1 - depth * 0.5 + depth * 0.5 * math.cos(lobes * 2 * math.pi * i / n))) * math.sin(2 * math.pi * i / n))
            for i in range(n)]


def frame_from(o, x, y):
    x = Vector(x).normalized()
    y = Vector(y)
    y = (y - x * y.dot(x)).normalized()
    z = x.cross(y)
    M = Matrix.Identity(4)
    for i in range(3):
        M[i][0], M[i][1], M[i][2], M[i][3] = x[i], y[i], z[i], o[i]
    return M


# --------------------------------------------------------------------------
# Textures and materials
# --------------------------------------------------------------------------
def _font(size, bold=True):
    for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else
              "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
              "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"):
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def make_textures():
    os.makedirs(TEX, exist_ok=True)
    out = {}
    # star-pattern seat fabric (tileable)
    S = 1024
    rnd = random.Random(350)
    img = Image.new("RGB", (S, S), (38, 42, 57))
    px = img.load()
    for y in range(S):
        for x in range(S):
            tw = ((x + y) // 3) % 2
            n = rnd.randint(-5, 5) + (3 if tw else -2)
            r, g, b = px[x, y]
            px[x, y] = (r + n, g + n, b + n)
    d = ImageDraw.Draw(img)
    star = (128, 133, 146)
    for _ in range(95):
        cx, cy = rnd.uniform(0, S), rnd.uniform(0, S)
        R = rnd.choice((5, 6, 7, 8, 9, 10, 12, 14, 18, 24, 34, 46))
        rot = rnd.uniform(0, math.pi / 4)
        for ox in (-S, 0, S):
            for oy in (-S, 0, S):
                x, y = cx + ox, cy + oy
                if not (-80 < x < S + 80 and -80 < y < S + 80):
                    continue
                for k in range(8):
                    a = rot + k * math.pi / 4
                    L = R if k % 2 == 0 else R * 0.45
                    w = max(0.8, R * 0.055)
                    tip = (x + L * math.cos(a), y + L * math.sin(a))
                    s1 = (x + w * math.cos(a + math.pi / 2), y + w * math.sin(a + math.pi / 2))
                    s2 = (x - w * math.cos(a + math.pi / 2), y - w * math.sin(a + math.pi / 2))
                    d.polygon([s1, tip, s2], fill=star)
                d.ellipse([x - R * 0.08, y - R * 0.08, x + R * 0.08, y + R * 0.08], fill=star)
    out["fabric"] = os.path.join(TEX, "seat_fabric_stars.png")
    img.save(out["fabric"])

    def badge(name, size, bg, draw):
        im = Image.new("RGB", size, bg)
        draw(ImageDraw.Draw(im), size)
        p = os.path.join(TEX, name)
        im.save(p)
        out[name.split(".")[0]] = p

    def a350(d, s):
        W, H = s
        d.ellipse([4, 4, W - 5, H - 5], fill=(236, 238, 240), outline=(150, 152, 156), width=6)
        d.text((W / 2, H / 2 + 2), "A350", fill=(22, 44, 120), font=_font(int(H * 0.56)), anchor="mm")
    badge("seat_badge_a350.png", (512, 200), (150, 172, 190), a350)

    def roundb(d, s):
        W, H = s
        d.ellipse([4, 4, W - 5, H - 5], fill=(236, 238, 240), outline=(150, 152, 156), width=6)
        d.ellipse([W * 0.2, H * 0.2, W * 0.8, H * 0.8], outline=(22, 44, 120), width=int(W * 0.06))
        d.ellipse([W * 0.38, H * 0.38, W * 0.62, H * 0.62], fill=(22, 44, 120))
    badge("seat_badge_round.png", (256, 256), (150, 172, 190), roundb)

    def vests(d, s):
        W, H = s
        d.rectangle([0, 0, W, H], fill=(200, 30, 28))
        d.rectangle([5, 5, W - 6, H - 6], outline=(250, 250, 250), width=3)
        d.text((W / 2, H / 2), "2 LIFE VESTS", fill=(250, 250, 250), font=_font(int(H * 0.52)), anchor="mm")
    badge("seat_placard_vests.png", (512, 100), (200, 30, 28), vests)

    def caution(d, s):
        W, H = s
        d.rectangle([0, 0, W, H], fill=(200, 30, 28))
        d.text((W / 2, H / 2), "CAUTION", fill=(250, 250, 250), font=_font(int(H * 0.55)), anchor="mm")
    badge("seat_placard_caution.png", (256, 80), (200, 30, 28), caution)

    def lumbar(d, s):
        W, H = s
        ink = (30, 32, 36)
        f, fs = _font(int(H * 0.075)), _font(int(H * 0.058))
        # knob centres (fractions of the plate) must match build_pan
        d.text((W * 0.20, H * 0.13), "UP", fill=ink, font=f, anchor="mm")
        d.text((W * 0.20, H * 0.58), "DOWN", fill=ink, font=fs, anchor="mm")
        d.text((W * 0.05, H * 0.36), "LUMBAR", fill=ink, font=fs, anchor="lm")
        d.text((W * 0.62, H * 0.20), "UNLOCK", fill=ink, font=fs, anchor="mm")
        d.text((W * 0.86, H * 0.20), "LOCK", fill=ink, font=fs, anchor="mm")
        d.text((W * 0.72, H * 0.52), "FWD", fill=ink, font=f, anchor="mm")
        d.text((W * 0.72, H * 0.90), "LUMBAR", fill=ink, font=fs, anchor="mm")
    badge("seat_label_lumbar.png", (450, 410), (150, 172, 190), lumbar)
    return out


def _mat(name, color, rough=0.5, metal=0.0, coat=0.0, sheen=0.0):
    if name in bpy.data.materials:
        return bpy.data.materials[name]
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = color
    b.inputs["Roughness"].default_value = rough
    b.inputs["Metallic"].default_value = metal
    if coat:
        b.inputs["Coat Weight"].default_value = coat
    if sheen:
        b.inputs["Sheen Weight"].default_value = sheen
    m.diffuse_color = color
    return m


def _bump(m, scale, strength, kind="noise", detail=2.0):
    nt = m.node_tree
    b = nt.nodes["Principled BSDF"]
    if kind == "voronoi":
        t = nt.nodes.new("ShaderNodeTexVoronoi")
        t.inputs["Scale"].default_value = scale
        out = t.outputs["Distance"]
    else:
        t = nt.nodes.new("ShaderNodeTexNoise")
        t.inputs["Scale"].default_value = scale
        t.inputs["Detail"].default_value = detail
        out = t.outputs["Fac"]
    bp = nt.nodes.new("ShaderNodeBump")
    bp.inputs["Strength"].default_value = strength
    bp.inputs["Distance"].default_value = 0.0005
    nt.links.new(out, bp.inputs["Height"])
    nt.links.new(bp.outputs["Normal"], b.inputs["Normal"])


def srgb(r, g, b):
    def f(c):
        c /= 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    return (f(r), f(g), f(b), 1.0)


def make_materials():
    tex = make_textures()
    shell = _mat("seat_shell", srgb(150, 172, 190), 0.42, coat=0.15)
    if len(shell.node_tree.nodes) <= 2:
        _bump(shell, 2500.0, 0.04)
    _mat("seat_shell_dark", srgb(104, 120, 136), 0.5)
    _mat("seat_black", srgb(30, 31, 34), 0.45)
    _mat("seat_black_matte", srgb(24, 25, 27), 0.75)
    vinyl = _mat("seat_vinyl", srgb(26, 27, 30), 0.38)
    if len(vinyl.node_tree.nodes) <= 2:
        _bump(vinyl, 900.0, 0.12, "voronoi")
    _mat("seat_groove", srgb(40, 46, 54), 0.6)
    _mat("seat_metal", srgb(196, 198, 202), 0.22, metal=1.0)
    _mat("seat_metal_dark", srgb(80, 82, 86), 0.35, metal=1.0)
    web = _mat("seat_webbing", srgb(80, 84, 92), 0.7, sheen=0.15)
    if len(web.node_tree.nodes) <= 2:
        _bump(web, 4000.0, 0.10)
    _mat("seat_track", srgb(70, 72, 78), 0.4, metal=1.0)

    if "seat_fabric" not in bpy.data.materials:
        m = bpy.data.materials.new("seat_fabric")
        m.use_nodes = True
        nt = m.node_tree
        b = nt.nodes["Principled BSDF"]
        b.inputs["Roughness"].default_value = 0.9
        b.inputs["Sheen Weight"].default_value = 0.25
        b.inputs["Sheen Roughness"].default_value = 0.5
        tc = nt.nodes.new("ShaderNodeTexCoord")
        mp = nt.nodes.new("ShaderNodeMapping")
        mp.inputs["Scale"].default_value = (1 / 0.36, 1 / 0.36, 1 / 0.36)
        img = nt.nodes.new("ShaderNodeTexImage")
        img.image = bpy.data.images.load(tex["fabric"], check_existing=True)
        img.projection = "BOX"
        img.projection_blend = 0.25
        nt.links.new(tc.outputs["Object"], mp.inputs["Vector"])
        nt.links.new(mp.outputs["Vector"], img.inputs["Vector"])
        nt.links.new(img.outputs["Color"], b.inputs["Base Color"])
        m.diffuse_color = srgb(38, 42, 57)
        _bump(m, 3000.0, 0.12)
    _mat("seat_piping", srgb(36, 40, 54), 0.85, sheen=0.2)

    for key in ("seat_badge_a350", "seat_badge_round", "seat_placard_vests", "seat_placard_caution",
                "seat_label_lumbar"):
        if key in bpy.data.materials:
            continue
        m = bpy.data.materials.new(key)
        m.use_nodes = True
        nt = m.node_tree
        b = nt.nodes["Principled BSDF"]
        b.inputs["Roughness"].default_value = 0.3
        t = nt.nodes.new("ShaderNodeTexImage")
        t.image = bpy.data.images.load(tex[key], check_existing=True)
        nt.links.new(t.outputs["Color"], b.inputs["Base Color"])


# --------------------------------------------------------------------------
# Parts
# --------------------------------------------------------------------------
def shell_taper(z):
    zn = min(max((z - SHELL_LO[2]) / (SHELL_HI[2] - SHELL_LO[2]), 0.0), 1.0)
    return 0.955 + 0.045 * zn                       # narrower toward the bottom


def shell_depth(z):
    """Side walls are deepest at the shoulders and shallower at the top and bottom."""
    return 1.0 - 0.32 * sstep(0.60, 0.86, z) - 0.10 * (1 - sstep(-0.075, 0.12, z))


def shell_deform(p):
    p.x *= shell_taper(p.z)
    p.y = SHELL_LO[1] + (p.y - SHELL_LO[1]) * shell_depth(p.z)
    return p


def shell_back_y():
    return SHELL_LO[1]


def build_back(col, parent, inboard, observer=False):
    """Moulded back shell, backrest cushion, harness shoulder straps, lumbar hardware."""
    base = parent.name.replace("_Pan", "")
    mb = MB(base + "_Back")
    sh = MB(base + "_Back_Shell")
    # ---- shell (open-fronted tub) ------------------------------------------
    sh.rbox(SHELL_LO, SHELL_HI, (0.068, 0.040, 0.068), n=(8, 4, 14), m=5,
                          extra=((), (SHELL_CUT_Y,), ()), deform=shell_deform, mat="seat_shell",
                          cut=lambda x, y, z: y > SHELL_CUT_Y)
    by = shell_back_y() - 0.0002
    # ---- details on the back face (all slightly proud of the flat back) -----
    Mback = frame_from(Vector((0, by, 0)), (1, 0, 0), (0, 0, 1))   # decal plane, normal -Y (outward)
    # life-vest stowage lid with its finger notch, and the parting lines
    lid = rounded_rect(0.290, 0.330, 0.028, notch=(0.074, 0.042))
    Mlid = Mback @ Tr(0, 0.205, 0)
    mb.prism(rounded_rect(0.297, 0.337, 0.031), 0.0, 0.0010, Mlid, "seat_groove")       # parting gap
    mb.prism(lid, 0.0, 0.0034, Mlid, "seat_shell")                                       # lid
    mb.prism([(x, y + 0.165 - 0.021) for x, y in ellipse(0.066, 0.036, 28)], 0.0, 0.0012, Mlid,
             "seat_shell_dark")                                                           # finger recess
    mb.box((-0.208, by - 0.0010, 0.384), (0.208, by + 0.0001, 0.3865), 0.0003, "seat_groove")
    mb.box((0.150, by - 0.0010, 0.392), (0.1515, by + 0.0001, 0.80), 0.0003, "seat_groove")
    # badges and placard
    mb.decal(ellipse(0.088, 0.034), Mback @ Tr(0, 0.790, 0.0012), "seat_badge_a350", (-0.044, -0.017, 0.044, 0.017))
    mb.decal(ellipse(0.054, 0.054, 36), Mback @ Tr(0, 0.690, 0.0012), "seat_badge_round",
             (-0.027, -0.027, 0.027, 0.027))
    mb.decal(rounded_rect(0.112, 0.022, 0.003), Mback @ Tr(0, 0.418, 0.0012), "seat_placard_vests",
             (-0.056, -0.011, 0.056, 0.011))
    # ---- backrest cushion ---------------------------------------------------
    def cushion_deform(p):
        w = sstep(BACK_LO[1] + 0.03, BACK_HI[1], p.y)
        p.y += back_front_offset(p.x, p.z) * w
        p.x *= shell_taper(p.z)
        return p
    seam_x = [s * v for s in (-1, 1) for v in (0.112, 0.117, 0.122, 0.127, 0.132)]
    mb.rbox(BACK_LO, BACK_HI, (0.034, 0.030, 0.040), n=(14, 3, 22), m=4, extra=(seam_x, (), ()),
            deform=cushion_deform, mat="seat_fabric")
    # topstitching beside each seam and piping round the cushion face
    for sx in (-1, 1):
        for off in (-0.007, 0.007):
            x = sx * (0.122 + off)
            mb.tube([back_front_point(x, z, 0.0006) for z in [0.0 + 0.0275 * i for i in range(22)]], 0.0006,
                    "seat_piping", segs=4)
    # ---- armrest hinge brackets (both sides) ---------------------------------
    hy, hz = ARM_HINGE
    for sx in (-1, 1):
        x = sx * (ARM_HINGE_X - 0.020)
        mb.box((x - 0.006, hy - 0.035, hz - 0.045), (x + 0.006, hy + 0.030, hz + 0.040), 0.004, "seat_black")
        mb.cyl(0.016, 0.010, Tr(sx * (ARM_HINGE_X - 0.014), hy, hz) @ Ry(sx * 90), "seat_black", 24)
    # ---- shoulder-harness inertia-reel exits + straps (lying down the cushion) --
    if True:
        for sx in (-1, 1):
            x0 = sx * 0.072
            mb.box((x0 - 0.030, BACK_LO[1] - 0.004, 0.640), (x0 + 0.030, BACK_LO[1] + 0.030, 0.676), 0.006,
                   "seat_black")
            path = [Vector((x0, 0.0, 0.672)), Vector((x0, 0.040, 0.668)), back_front_point(x0, 0.630, 0.003)]
            for z in (0.56, 0.46, 0.36, 0.27, 0.19, 0.12):
                path.append(back_front_point(sx * (0.070 - (0.56 - z) * 0.05), z, 0.003))
            nrm = [Vector((0, 0, 1)), Vector((0, 0.3, 1))] + [Vector((0, 1, 0))] * (len(path) - 2)
            P, N = mb.ribbon(path, nrm, 0.044, 0.0022, "seat_webbing")
            # length adjuster and tongue at the strap end
            e, ne = P[-1], N[-1]
            t = (P[-1] - P[-4]).normalized()
            Mt = frame_from(e + ne * 0.004, t.cross(ne), t)
            mb.box((-0.026, -0.010, -0.002), (0.026, 0.010, 0.004), 0.002, "seat_metal", Mt)
            mb.box((-0.016, 0.010, -0.0015), (0.016, 0.038, 0.0015), 0.001, "seat_metal", Mt)
    ob = mb.finish(col, parent, BACK_PIVOT, (BACK_RECLINE, 0, 0))
    so = sh.finish(col, ob, (0, 0, 0))
    sm = so.modifiers.new("Shell wall", "SOLIDIFY")
    sm.thickness = 0.004
    sm.offset = -1.0
    sm.use_even_offset = True
    return ob


def build_headrest(col, back, observer=False):
    mb = MB(back.name.replace("_Back", "") + "_Headrest")

    def deform(p):
        w = sstep(HEAD_LO[1] + 0.05, HEAD_HI[1], p.y)
        p.y += (-0.013 * (1 - (p.x / 0.19) ** 2) + 0.016 * sstep(0.11, 0.19, abs(p.x))) * w
        p.y -= 0.010 * sstep(0.84, 0.905, p.z) * (1 - w)
        return p
    mb.rbox(HEAD_LO, HEAD_HI, (0.050, 0.045, 0.058), n=(12, 4, 8), m=4, deform=deform, mat="seat_fabric")
    # piping round the front face
    loop = []
    hx, hz = (HEAD_HI[0] - HEAD_LO[0]) / 2, (HEAD_HI[2] - HEAD_LO[2]) / 2
    cz = (HEAD_HI[2] + HEAD_LO[2]) / 2
    rx, rz = 0.050, 0.058
    for cxs, czs, a0 in ((1, 1, 0), (-1, 1, 90), (-1, -1, 180), (1, -1, 270)):
        for i in range(7):
            a = math.radians(a0 + 90 * i / 6)
            x = cxs * (hx - rx) + rx * 0.82 * math.cos(a)
            z = cz + czs * (hz - rz) + rz * 0.82 * math.sin(a)
            p = Vector((x, HEAD_HI[1] - 0.012, z))
            loop.append(deform(p))
    mb.tube(loop, 0.0028, "seat_piping", closed=True, segs=6)
    # adjustment posts into the shell top
    for sx in (-0.08, 0.08):
        mb.cyl(0.0055, 0.10, Tr(sx, -0.02, 0.60), "seat_metal", 14)
    return mb.finish(col, back, (0, 0, 0))


def build_armrest(col, back, side, stowed=True):
    """side = -1 left, +1 right.  Built deployed (pointing forward) about its hinge, then rotated."""
    mb = MB("%s_Armrest_%s" % (back.name.replace("_Back", ""), "L" if side < 0 else "R"))
    mb.rbox((-0.030, -0.060, -0.040), (0.030, 0.315, 0.046), (0.022, 0.034, 0.026), n=(3, 12, 3), m=4,
            deform=lambda p: p + Vector((0, 0, 0.004 * (1 - (p.x / 0.030) ** 2) * sstep(0.0, 0.046, p.z))),
            mat="seat_vinyl")
    # cast hinge arm and release lever
    mb.box((-0.020, -0.060, -0.040), (0.020, 0.040, -0.012), 0.004, "seat_black")
    mb.box((side * 0.018, -0.030, -0.034), (side * 0.032, 0.030, -0.018), 0.003, "seat_black")
    mb.box((side * 0.024, 0.020, -0.050), (side * 0.034, 0.075, -0.030), 0.003, "seat_black")
    hy, hz = ARM_HINGE
    rot = 90.0 if stowed else 0.0
    return mb.finish(col, back, (side * ARM_HINGE_X, hy, hz), (rot, 0, 0))


def build_pan(col, root, inboard, observer=False):
    mb = MB(root.name + "_Pan")

    def deform(p):
        w = sstep((PAN_LO[2] + PAN_HI[2]) / 2, PAN_HI[2], p.z)
        p.z += pan_top_offset(p.x, p.y) * w
        return p
    mb.rbox(PAN_LO, PAN_HI, (0.035, 0.045, 0.034), n=(16, 16, 3), m=4, deform=deform, mat="seat_fabric")
    # piping round the top
    loop = []
    hx, hy = (PAN_HI[0] - PAN_LO[0]) / 2, (PAN_HI[1] - PAN_LO[1]) / 2
    cy = (PAN_HI[1] + PAN_LO[1]) / 2
    rx, ry = 0.035, 0.045
    for cxs, cys, a0 in ((1, 1, 0), (-1, 1, 90), (-1, -1, 180), (1, -1, 270)):
        for i in range(7):
            a = math.radians(a0 + 90 * i / 6)
            x = cxs * (hx - rx) + rx * 0.70 * math.cos(a)
            y = cy + cys * (hy - ry) + ry * 0.70 * math.sin(a)
            loop.append(deform(Vector((x, y, PAN_HI[2] - 0.009))))
    mb.tube(loop, 0.0028, "seat_piping", closed=True, segs=6)
    # pan structure: black tray and blue-grey side skirts
    mb.box((-0.232, -0.105, -0.040), (0.232, 0.370, 0.004), 0.008, "seat_black")
    for sx in (-1, 1):
        mb.rbox((sx * 0.236 - 0.012, -0.110, -0.075), (sx * 0.236 + 0.012, 0.360, 0.012), (0.010, 0.030, 0.010),
                n=(1, 8, 2), m=3, mat="seat_shell")
    # crotch-strap slot
    sl = pan_top_point(0.0, 0.270, 0.0)
    mb.prism(ellipse(0.070, 0.024, 28), -0.004, 0.0008, Tr(*sl), "seat_piping")       # stitched slot edge
    mb.prism(ellipse(0.058, 0.012, 24), -0.004, 0.0012, Tr(*sl), "seat_black_matte")  # opening
    build_lap_harness(mb)
    # seat-adjustment handle in the inboard front corner, recline lever, lumbar knobs
    x = inboard * 0.249
    Mh = frame_from(Vector((x, 0.300, -0.030)), (0, 1, 0), (0, 0, 1))
    if inboard < 0:
        Mh = frame_from(Vector((x, 0.300, -0.030)), (0, -1, 0), (0, 0, 1))
    mb.box((-0.035, -0.014, -0.002), (0.035, 0.014, 0.010), 0.004, "seat_black", Mh)
    mb.box((-0.026, -0.008, 0.006), (0.026, 0.008, 0.014), 0.002, "seat_black_matte", Mh)
    Ml = Tr(inboard * 0.250, -0.075, 0.000) @ Ry(inboard * 90)
    mb.cyl(0.0045, 0.030, Ml, "seat_black", 10)
    mb.sphere(0.014, Ml @ Tr(0, 0, 0.034), "seat_black")
    Mlab = frame_from(Vector((inboard * 0.2481, -0.030, -0.034)), (0, inboard, 0), (0, 0, 1))
    mb.decal(rounded_rect(0.090, 0.082, 0.006), Mlab, "seat_label_lumbar", (-0.045, -0.041, 0.045, 0.041))
    for (ky, kz, r) in ((-0.052, -0.022, 0.024), (-0.008, -0.050, 0.021)):
        Mk = Tr(inboard * 0.248, ky, kz) @ Ry(inboard * 90)
        mb.prism(knurl(r, 14, 0.10), 0.0, 0.024, Mk, "seat_black")
        mb.cyl(r * 0.55, 0.003, Mk @ Tr(0, 0, 0.024), "seat_black_matte", 20)
    return mb.finish(col, root, PAN_PIVOT, (PAN_RAKE, 0, 0))


def build_lap_harness(mb):
    """Lap belts, crotch strap and rotary buckle lying on the seat pan (stowed)."""
    up = Vector((0, 0, 1))
    buckle = pan_top_point(0.0, 0.140, 0.006)
    for sx in (-1, 1):
        anchor = Vector((sx * 0.244, -0.050, 0.040))
        path = [anchor, Vector((sx * 0.250, -0.030, 0.080)), pan_top_point(sx * 0.215, -0.005, 0.002),
                pan_top_point(sx * 0.150, 0.040, 0.002), pan_top_point(sx * 0.085, 0.095, 0.002),
                pan_top_point(sx * 0.038, 0.128, 0.003)]
        nrm = [Vector((sx, 0, 0)), Vector((sx, 0, 1))] + [up] * 4
        P, N = mb.ribbon(path, nrm, 0.046, 0.0024, "seat_webbing")
        # anchor fitting and adjuster
        mb.box((sx * 0.236 - 0.006, -0.070, 0.020), (sx * 0.236 + 0.008, -0.030, 0.062), 0.003, "seat_metal_dark")
        a = pan_top_point(sx * 0.120, 0.068, 0.006)
        t = (P[-6] - P[-9]).normalized()
        Ma = frame_from(a, t.cross(up), t)
        mb.box((-0.028, -0.012, -0.003), (0.028, 0.012, 0.004), 0.002, "seat_metal", Ma)
    crotch = [pan_top_point(0.0, 0.266, -0.003), pan_top_point(0.0, 0.250, 0.0005), pan_top_point(0.0, 0.205, 0.001),
              pan_top_point(0.0, 0.165, 0.002)]
    mb.ribbon(crotch, [up] * 4, 0.044, 0.0022, "seat_webbing")
    # rotary buckle: body, knurled turning ring, centre plate and tongue slots
    Mb = Tr(*buckle)
    mb.cyl(0.040, 0.010, Mb, "seat_black", 40)
    mb.prism(knurl(0.043, 24, 0.05), 0.010, 0.016, Mb, "seat_black")
    mb.cyl(0.019, 0.004, Mb @ Tr(0, 0, 0.016), "seat_metal", 28)
    for a in range(4):
        mb.box((-0.006, 0.020, 0.010), (0.006, 0.036, 0.0165), 0.001, "seat_black_matte", Mb @ Rz(a * 90 + 45))


def build_base(col, root, observer=False):
    mb = MB(root.name + "_Base")
    if True:
        for sx in (-1, 1):
            # floor track with a slotted top
            mb.box((sx * 0.165 - 0.018, -0.62, 0.0), (sx * 0.165 + 0.018, 0.42, 0.016), 0.002, "seat_track")
            for i in range(26):
                y = -0.60 + i * 0.04
                mb.box((sx * 0.165 - 0.005, y, 0.016), (sx * 0.165 + 0.005, y + 0.025, 0.0168), 0.0004,
                       "seat_black_matte")
            mb.box((sx * 0.165 - 0.030, -0.26, 0.016), (sx * 0.165 + 0.030, 0.20, 0.050), 0.008, "seat_black")
            for y in (-0.22, 0.15):
                mb.box((sx * 0.165 - 0.026, y - 0.030, 0.012), (sx * 0.165 + 0.026, y + 0.030, 0.058), 0.010,
                       "seat_black")
    # lift column and moulded shroud
    mb.rbox((-0.190, -0.240, 0.050), (0.190, 0.210, 0.300), (0.040, 0.050, 0.020), n=(4, 4, 4), m=4,
            deform=lambda p: Vector((p.x * (0.92 + 0.08 * sstep(0.05, 0.30, p.z)), p.y, p.z)),
            mat="seat_black")
    for i in range(6):
        z = 0.090 + i * 0.030
        mb.box((-0.140, -0.2425, z), (0.140, -0.236, z + 0.012), 0.002, "seat_black_matte")
    mb.decal(rounded_rect(0.070, 0.022, 0.002), frame_from(Vector((0.09, -0.2432, 0.068)), (1, 0, 0), (0, 0, 1)),
             "seat_placard_caution", (-0.035, -0.011, 0.035, 0.011))
    # track-lock / fore-aft release bar at the front
    mb.tube([(-0.12, 0.215, 0.090), (-0.12, 0.250, 0.085), (0.12, 0.250, 0.085), (0.12, 0.215, 0.090)], 0.007,
            "seat_black", segs=10)
    # cable boot to the floor at the rear
    mb.tube([(0.10, -0.24, 0.12), (0.10, -0.29, 0.08), (0.10, -0.31, 0.02)], 0.011, "seat_black_matte", segs=10)
    return mb.finish(col, root, (0, 0, 0))


def build_crew_seat(name, location, inboard, col, observer=False, rotation_z=0.0):
    """Build one seat.  inboard = +1 when the aircraft centreline is on the seat's +X side."""
    make_materials()
    root = bpy.data.objects.new(name, None)
    root.empty_display_type = "ARROWS"
    root.empty_display_size = 0.2
    col.objects.link(root)
    root.location = location
    root.rotation_euler = (0, 0, math.radians(rotation_z))
    build_base(col, root, observer)
    pan = build_pan(col, root, inboard, observer)
    back = build_back(col, pan, inboard, observer)
    build_headrest(col, back, observer)
    if not observer:
        build_armrest(col, back, -1, stowed=True)
        build_armrest(col, back, 1, stowed=True)
    return root


# --------------------------------------------------------------------------
# Stand-alone preview
# --------------------------------------------------------------------------
def _preview(out_dir, render=True):
    import sys
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    col = scene.collection
    build_crew_seat("Seat_CAPT", (0, 0, 0), 1, col)
    me = bpy.data.meshes.new("floor")
    me.from_pydata([(-3, -3, 0), (3, -3, 0), (3, 3, 0), (-3, 3, 0)], [], [(0, 1, 2, 3)])
    fl = bpy.data.objects.new("floor", me)
    fm = _mat("floor", srgb(70, 74, 82), 0.9)
    me.materials.append(fm)
    col.objects.link(fl)
    w = bpy.data.worlds.new("w")
    scene.world = w
    w.use_nodes = True
    w.node_tree.nodes["Background"].inputs[0].default_value = (0.55, 0.58, 0.62, 1)
    w.node_tree.nodes["Background"].inputs[1].default_value = 0.8
    for nm, loc, e, s in (("key", (1.4, 1.6, 2.4), 260, 1.2), ("fill", (-1.8, 0.6, 1.4), 90, 1.5),
                          ("rim", (0.2, -2.2, 2.0), 140, 1.0)):
        ld = bpy.data.lights.new(nm, "AREA")
        ld.energy = e
        ld.size = s
        ob = bpy.data.objects.new(nm, ld)
        ob.location = loc
        d = Vector((0, 0, 0.7)) - Vector(loc)
        ob.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
        col.objects.link(ob)
    views = {"front34": ((1.25, 1.45, 1.25), (0.0, 0.0, 0.62)), "rear34": ((-1.15, -1.55, 1.35), (0.0, -0.1, 0.70)),
             "side": ((1.9, 0.12, 0.85), (0.0, 0.05, 0.62)), "detail": ((0.62, 0.62, 0.88), (0.12, 0.05, 0.40))}
    scene.render.engine = "CYCLES"
    final = "--final" in sys.argv
    scene.cycles.samples = 128 if final else 48
    scene.cycles.use_denoising = True
    scene.render.resolution_x = 1400 if final else 900
    scene.render.resolution_y = 1400 if final else 900
    scene.view_settings.view_transform = "AgX"
    os.makedirs(out_dir, exist_ok=True)
    for nm, (loc, tgt) in views.items():
        cd = bpy.data.cameras.new(nm)
        cd.lens = 50 if nm != "detail" else 40
        ob = bpy.data.objects.new("Cam_" + nm, cd)
        ob.location = loc
        ob.rotation_euler = (Vector(tgt) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
        col.objects.link(ob)
        if render and (len(sys.argv) < 2 or "--views" not in sys.argv or nm in sys.argv[sys.argv.index("--views") + 1]):
            scene.camera = ob
            scene.render.filepath = os.path.join(out_dir, "seat_%s.png" % nm)
            bpy.ops.render.render(write_still=True)
            print("rendered", scene.render.filepath)
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(out_dir, "seat_preview.blend"))


if __name__ == "__main__":
    import sys
    out = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else os.path.join(HERE, "renders_preview")
    _preview(out, render="--render" in sys.argv)
