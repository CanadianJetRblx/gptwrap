"""Screen artwork for the A350-900 flight deck displays (drawn with Pillow).

Every function returns an RGB image that is later used as an emission texture.
The symbology follows Airbus conventions (green = engaged/active, cyan =
selected/armed, magenta = managed targets, amber = caution, white = titles).
"""
import math
import os
from PIL import Image, ImageDraw, ImageFont

GREEN = (40, 255, 60)
CYAN = (0, 235, 255)
MAGENTA = (255, 80, 255)
AMBER = (255, 170, 0)
RED = (255, 40, 40)
WHITE = (240, 240, 240)
GREY = (120, 124, 130)
DGREY = (52, 56, 62)
YELLOW = (255, 235, 0)
SKY = (38, 120, 205)
GROUND = (124, 78, 38)
BG = (4, 5, 8)

_FONT_DIRS = ["/usr/share/fonts/truetype/dejavu", "/usr/share/fonts/truetype/liberation"]
_cache = {}


def font(size, bold=True, mono=False):
    key = (size, bold, mono)
    if key not in _cache:
        names = (["DejaVuSansMono-Bold.ttf", "LiberationMono-Bold.ttf"] if mono else
                 (["DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf"] if bold else
                  ["DejaVuSans.ttf", "LiberationSans-Regular.ttf"]))
        f = None
        for d in _FONT_DIRS:
            for n in names:
                p = os.path.join(d, n)
                if os.path.exists(p):
                    f = ImageFont.truetype(p, size)
                    break
            if f:
                break
        _cache[key] = f or ImageFont.load_default()
    return _cache[key]


def text(d, xy, s, fill=WHITE, size=20, anchor="mm", mono=False, bold=True):
    d.text(xy, s, fill=fill, font=font(size, bold, mono), anchor=anchor)


def _rot(cx, cy, r, deg):
    a = math.radians(deg)
    return cx + r * math.sin(a), cy - r * math.cos(a)


# --------------------------------------------------------------------------
# PFD
# --------------------------------------------------------------------------
def draw_pfd(img, box):
    d = ImageDraw.Draw(img)
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    # FMA
    fma_h = int(h * 0.105)
    cols = [0.0, 0.2, 0.4, 0.6, 0.78, 1.0]
    for c in cols[1:-1]:
        d.line([x0 + c * w, y0 + 4, x0 + c * w, y0 + fma_h - 4], fill=GREY, width=2)
    fs = int(h * 0.030)
    fma = [("MACH", GREEN, None), ("ALT CRZ", GREEN, None), ("NAV", GREEN, None),
           ("", WHITE, None), ("AP1", WHITE, "1FD2")]
    for i, (a, col, b) in enumerate(fma):
        cx = x0 + (cols[i] + cols[i + 1]) / 2 * w
        text(d, (cx, y0 + fma_h * 0.27), a, col, fs)
        if b:
            text(d, (cx, y0 + fma_h * 0.60), b, WHITE, fs)
    text(d, (x0 + 0.89 * w, y0 + fma_h * 0.90), "A/THR", WHITE, fs)

    # attitude
    acx, acy = x0 + 0.47 * w, y0 + 0.40 * h
    ar = 0.215 * w
    pitch_px = ar / 22.0
    pitch, roll = 2.5, 0.0
    att = Image.new("RGB", (int(ar * 2), int(ar * 2)), SKY)
    ad = ImageDraw.Draw(att)
    hz = ar + pitch * pitch_px
    ad.rectangle([0, hz, ar * 2, ar * 2], fill=GROUND)
    ad.line([0, hz, ar * 2, hz], fill=WHITE, width=3)
    for p in (-20, -10, 10, 20):
        yy = hz - p * pitch_px
        ad.line([ar - ar * 0.32, yy, ar + ar * 0.32, yy], fill=WHITE, width=2)
        ad.text((ar - ar * 0.40, yy), str(abs(p)), fill=WHITE, font=font(int(h * 0.026)), anchor="rm")
        ad.text((ar + ar * 0.40, yy), str(abs(p)), fill=WHITE, font=font(int(h * 0.026)), anchor="lm")
    for p in (-15, -5, 5, 15):
        yy = hz - p * pitch_px
        ad.line([ar - ar * 0.16, yy, ar + ar * 0.16, yy], fill=WHITE, width=2)
    for p in (-17.5, -12.5, -7.5, -2.5, 2.5, 7.5, 12.5, 17.5):
        yy = hz - p * pitch_px
        ad.line([ar - ar * 0.07, yy, ar + ar * 0.07, yy], fill=WHITE, width=2)
    mask = Image.new("L", att.size, 0)
    md = ImageDraw.Draw(mask)
    md.rounded_rectangle([ar * 0.08, 0, ar * 1.92, ar * 2], radius=int(ar * 0.55), fill=255)
    img.paste(att, (int(acx - ar), int(acy - ar)), mask)
    # roll scale
    for deg in (-45, -30, -20, -10, 10, 20, 30, 45):
        p1 = _rot(acx, acy, ar * 1.0, deg)
        p2 = _rot(acx, acy, ar * (1.09 if abs(deg) in (30, 45) else 1.05), deg)
        d.line([p1, p2], fill=WHITE, width=2)
    tip = _rot(acx, acy, ar * 1.0, 0)
    d.polygon([tip, (tip[0] - 9, tip[1] - 16), (tip[0] + 9, tip[1] - 16)], outline=YELLOW)
    # aircraft symbol
    yw = max(4, int(h * 0.011))
    for sgn in (-1, 1):
        d.line([acx + sgn * ar * 0.72, acy, acx + sgn * ar * 0.30, acy], fill=BG, width=yw + 4)
        d.line([acx + sgn * ar * 0.72, acy, acx + sgn * ar * 0.30, acy], fill=YELLOW, width=yw)
        d.line([acx + sgn * ar * 0.30, acy, acx + sgn * ar * 0.30, acy + ar * 0.13], fill=YELLOW, width=yw)
    d.rectangle([acx - yw, acy - yw, acx + yw, acy + yw], outline=YELLOW, width=3)
    # flight director bars
    d.line([acx - ar * 0.5, acy - 1, acx + ar * 0.5, acy - 1], fill=GREEN, width=3)
    d.line([acx + 1, acy - ar * 0.5, acx + 1, acy + ar * 0.5], fill=GREEN, width=3)

    # speed tape
    sx0, sx1 = x0 + 0.045 * w, x0 + 0.185 * w
    ty0, ty1 = acy - ar * 1.0, acy + ar * 1.0
    d.rectangle([sx0, ty0, sx1, ty1], fill=DGREY)
    spd = 278.0
    px_per_kt = (ty1 - ty0) / 84.0
    for v in range(230, 330, 10):
        yy = acy - (v - spd) * px_per_kt
        if ty0 + 8 < yy < ty1 - 8:
            d.line([sx1 - 12, yy, sx1, yy], fill=WHITE, width=2)
            if v % 20 == 0:
                text(d, (sx1 - 18, yy), str(v), WHITE, int(h * 0.034), "rm")
    d.line([sx1, ty0, sx1, ty1], fill=WHITE, width=2)
    d.line([sx0, ty0, sx1 + 14, ty0], fill=WHITE, width=2)
    d.line([sx0, ty1, sx1 + 14, ty1], fill=WHITE, width=2)
    d.line([sx0 - 6, acy, sx1 + 22, acy], fill=YELLOW, width=3)
    d.polygon([(sx1 + 4, acy), (sx1 + 22, acy - 9), (sx1 + 22, acy + 9)], fill=YELLOW)
    # managed speed target + trend
    yy = acy - (282 - spd) * px_per_kt
    d.polygon([(sx1 + 2, yy), (sx1 + 20, yy - 11), (sx1 + 20, yy + 11)], outline=MAGENTA, width=2)
    text(d, (sx0 + (sx1 - sx0) / 2, ty1 + h * 0.026), ".850", GREEN, int(h * 0.034))

    # altitude tape
    ax0, ax1 = x0 + 0.755 * w, x0 + 0.885 * w
    d.rectangle([ax0, ty0, ax1, ty1], fill=DGREY)
    alt = 36000.0
    px_per_ft = (ty1 - ty0) / 1100.0
    for a in range(35500, 36600, 100):
        yy = acy - (a - alt) * px_per_ft
        if ty0 + 8 < yy < ty1 - 8:
            d.line([ax1 - 10, yy, ax1, yy], fill=WHITE, width=2)
            if a % 500 == 0 and abs(a - alt) > 150:
                text(d, (ax1 - 14, yy), "%03d" % (a // 100), WHITE, int(h * 0.032), "rm")
    d.line([ax0, ty0, ax1 + 10, ty0], fill=WHITE, width=2)
    d.line([ax0, ty1, ax1 + 10, ty1], fill=WHITE, width=2)
    bh = h * 0.034
    d.rectangle([ax0 - 4, acy - bh, ax1 + w * 0.045, acy + bh], fill=BG, outline=YELLOW, width=3)
    text(d, (ax1 - 8, acy), "360", GREEN, int(h * 0.046), "rm")
    text(d, (ax1 + w * 0.040, acy), "00", GREEN, int(h * 0.034), "rm")
    text(d, ((ax0 + ax1) / 2 + 6, ty0 - h * 0.026), "FL360", CYAN, int(h * 0.034))
    text(d, ((ax0 + ax1) / 2 + 6, ty1 + h * 0.026), "STD", CYAN, int(h * 0.034))

    # V/S scale
    vx = x0 + 0.945 * w
    d.polygon([(vx - 14, ty0 + 6), (vx + 14, ty0 + ar * 0.35), (vx + 14, ty1 - ar * 0.35),
               (vx - 14, ty1 - 6)], fill=DGREY)
    for i, fr in enumerate((-0.8, -0.55, -0.3, 0.3, 0.55, 0.8)):
        yy = acy + fr * ar
        d.line([vx - 12, yy, vx - 2, yy], fill=WHITE, width=2)
    d.line([vx - 14, acy, vx + 4, acy], fill=YELLOW, width=3)
    d.line([vx - 12, acy, vx + 30, acy], fill=GREEN, width=3)

    # heading tape
    hy0, hy1 = ty1 + h * 0.055, ty1 + h * 0.115
    hx0, hx1 = acx - ar * 0.95, acx + ar * 0.95
    d.rectangle([hx0, hy0, hx1, hy1], fill=DGREY, outline=WHITE, width=2)
    hdg = 45.0
    px_per_deg = (hx1 - hx0) / 50.0
    for hd in range(20, 75, 5):
        xx = acx + (hd - hdg) * px_per_deg
        if hx0 + 6 < xx < hx1 - 6:
            d.line([xx, hy0, xx, hy0 + (12 if hd % 10 == 0 else 6)], fill=WHITE, width=2)
            if hd % 10 == 0:
                text(d, (xx, hy0 + (hy1 - hy0) * 0.66), "%02d" % (hd // 10), WHITE, int(h * 0.030))
    d.line([acx, hy0 - 16, acx, hy0 + 6], fill=YELLOW, width=4)
    xx = acx + (47 - hdg) * px_per_deg
    d.polygon([(xx, hy0), (xx - 8, hy0 - 14), (xx + 8, hy0 - 14)], outline=GREEN, width=2)

    # lower memo area: slats/flaps, trim, gear
    my0 = y0 + 0.80 * h
    d.line([x0 + 6, my0, x1 - 6, my0], fill=GREY, width=2)
    wx, wy = x0 + 0.26 * w, my0 + 0.085 * h
    d.polygon([(wx - 46, wy - 7), (wx + 46, wy - 12), (wx + 46, wy + 6), (wx - 46, wy + 9)], fill=GREY)
    d.line([wx - 50, wy + 2, wx - 96, wy + 9], fill=GREEN, width=4)
    d.line([wx + 50, wy - 2, wx + 110, wy + 6], fill=GREEN, width=4)
    text(d, (wx - 110, wy - 22), "S", WHITE, int(h * 0.030))
    text(d, (wx + 124, wy - 22), "F", WHITE, int(h * 0.030))
    text(d, (wx, wy + 34), "0", GREEN, int(h * 0.036))
    tx = x0 + 0.66 * w
    text(d, (tx, my0 + 0.035 * h), "PITCH TRIM", WHITE, int(h * 0.026))
    text(d, (tx - 8, my0 + 0.085 * h), "0.4", GREEN, int(h * 0.036), "rm")
    text(d, (tx - 2, my0 + 0.085 * h), "° UP", CYAN, int(h * 0.028), "lm")
    text(d, (tx, my0 + 0.135 * h), "GW 232.4 T", GREEN, int(h * 0.026))
    text(d, (tx + 0.22 * w, my0 + 0.035 * h), "RUD", WHITE, int(h * 0.026))
    text(d, (tx + 0.22 * w, my0 + 0.085 * h), "0.0", GREEN, int(h * 0.032))


# --------------------------------------------------------------------------
# ND with vertical display
# --------------------------------------------------------------------------
def draw_nd(img, box, side="L"):
    d = ImageDraw.Draw(img)
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    vd_h = 0.24 * h
    cx, cy = x0 + w / 2, y1 - vd_h - 0.10 * h
    R = min(w * 0.47, (cy - y0) * 0.86)
    hdg = 45
    fs = int(h * 0.030)
    # compass arc
    d.arc([cx - R, cy - R, cx + R, cy + R], 180 + 22, 360 - 22, fill=WHITE, width=3)
    for dd in range(-65, 70, 5):
        hd = (hdg + dd) % 360
        if abs(dd) > 66:
            continue
        ln = 16 if hd % 10 == 0 else 8
        d.line([_rot(cx, cy, R, dd), _rot(cx, cy, R + ln, dd)], fill=WHITE, width=2)
        if hd % 30 == 0 or (hd % 10 == 0 and abs(dd) < 60):
            lab = str(hd // 10)
            text(d, _rot(cx, cy, R + 34, dd), lab, WHITE, fs if hd % 30 else int(fs * 1.25))
    # range arcs (dashed)
    for fr, lab in ((0.25, None), (0.5, "80"), (0.75, None)):
        r = R * fr
        for a in range(-66, 66, 6):
            d.arc([cx - r, cy - r, cx + r, cy + r], 270 + a, 270 + a + 3, fill=WHITE, width=2)
        if lab:
            text(d, _rot(cx, cy, r + 2, -58), lab, CYAN, int(fs * 0.9))
            text(d, _rot(cx, cy, r + 2, 58), lab, CYAN, int(fs * 0.9))
    # track line + flight plan
    d.line([cx, cy - 10, cx, cy - R], fill=GREEN, width=2)
    wpts = [(0.0, -0.02, ""), (0.02, 0.27, "DEVAL"), (-0.13, 0.52, "KOSEB"), (-0.05, 0.80, "ROTAR"),
            (0.20, 1.06, "")]
    pts = [(cx + a * R, cy - b * R) for a, b, _ in wpts]
    d.line(pts, fill=GREEN, width=3)
    for (px, py), (_, _, nm) in zip(pts, wpts):
        if nm:
            s = 9
            d.polygon([(px, py - s), (px + s, py), (px, py + s), (px - s, py)],
                      outline=WHITE if nm == "DEVAL" else GREEN, width=2)
            text(d, (px + 16, py - 4), nm, WHITE if nm == "DEVAL" else GREEN, int(fs * 0.95), "lm")
    # other symbols: VOR, airport, TCAS traffic
    vx, vy = cx + 0.33 * R, cy - 0.46 * R
    d.line([vx - 9, vy, vx + 9, vy], fill=MAGENTA, width=2)
    d.line([vx, vy - 9, vx, vy + 9], fill=MAGENTA, width=2)
    text(d, (vx + 14, vy + 12), "TOU", MAGENTA, int(fs * 0.85), "lm")
    ax_, ay_ = cx - 0.42 * R, cy - 0.28 * R
    for a in range(0, 180, 45):
        p1 = _rot(ax_, ay_, 10, a)
        p2 = _rot(ax_, ay_, 10, a + 180)
        d.line([p1, p2], fill=MAGENTA, width=2)
    text(d, (ax_ + 14, ay_ + 12), "LFBO", MAGENTA, int(fs * 0.85), "lm")
    tx_, ty_ = cx + 0.18 * R, cy - 0.68 * R
    d.polygon([(tx_, ty_ - 8), (tx_ + 8, ty_), (tx_, ty_ + 8), (tx_ - 8, ty_)], outline=WHITE, width=2)
    text(d, (tx_, ty_ + 20), "+20", WHITE, int(fs * 0.8))
    # aircraft symbol
    d.line([cx, cy - 22, cx, cy + 24], fill=YELLOW, width=4)
    d.line([cx - 26, cy, cx + 26, cy], fill=YELLOW, width=4)
    d.line([cx - 10, cy + 18, cx + 10, cy + 18], fill=YELLOW, width=4)
    # corner data
    text(d, (x0 + 12, y0 + 0.035 * h), "GS", WHITE, int(fs * 0.9), "lm")
    text(d, (x0 + 12 + fs * 1.6, y0 + 0.035 * h), "487", GREEN, fs, "lm")
    text(d, (x0 + 12 + fs * 4.0, y0 + 0.035 * h), "TAS", WHITE, int(fs * 0.9), "lm")
    text(d, (x0 + 12 + fs * 6.1, y0 + 0.035 * h), "479", GREEN, fs, "lm")
    text(d, (x0 + 12, y0 + 0.080 * h), "230/18", GREEN, fs, "lm")
    text(d, (x1 - 12, y0 + 0.035 * h), "DEVAL", WHITE, fs, "rm")
    text(d, (x1 - 12, y0 + 0.080 * h), "046°", GREEN, fs, "rm")
    text(d, (x1 - 12, y0 + 0.125 * h), "42.6 NM", GREEN, fs, "rm")
    text(d, (x1 - 12, y0 + 0.170 * h), "10:47", GREEN, fs, "rm")
    text(d, (x0 + 12, cy + 0.045 * h), "VOR1", WHITE, int(fs * 0.85), "lm")
    text(d, (x0 + 12, cy + 0.085 * h), "TOU 114.3", WHITE, int(fs * 0.85), "lm")
    text(d, (x1 - 12, cy + 0.045 * h), "ARC  160", CYAN, int(fs * 0.85), "rm")
    # vertical display
    vy0 = y1 - vd_h
    d.rectangle([x0 + 4, vy0, x1 - 4, y1 - 4], outline=GREY, width=2)
    gx0, gx1 = x0 + 0.13 * w, x1 - 0.04 * w
    for i, lab in enumerate(("400", "300", "200", "100")):
        yy = vy0 + vd_h * (0.14 + 0.2 * i)
        d.line([gx0 - 8, yy, gx0, yy], fill=WHITE, width=2)
        text(d, (gx0 - 14, yy), lab, WHITE, int(fs * 0.8), "rm")
    d.line([gx0, vy0 + 6, gx0, y1 - 10], fill=WHITE, width=2)
    terr = [(gx0, y1 - 6)]
    n = 40
    for i in range(n + 1):
        t = i / n
        e = 0.05 + 0.05 * math.sin(t * 9) + 0.10 * math.exp(-((t - 0.62) / 0.12) ** 2) + 0.03 * math.sin(t * 31)
        terr.append((gx0 + t * (gx1 - gx0), y1 - 6 - e * vd_h))
    terr.append((gx1, y1 - 6))
    d.polygon(terr, fill=(110, 72, 30))
    fy = vy0 + vd_h * 0.22
    d.line([gx0 + 10, fy, gx1, fy], fill=GREEN, width=3)
    d.polygon([(gx0 + 2, fy), (gx0 + 22, fy - 7), (gx0 + 22, fy + 7)], fill=YELLOW)
    for t, nm in ((0.17, "DEVAL"), (0.47, "KOSEB"), (0.78, "ROTAR")):
        xx = gx0 + t * (gx1 - gx0)
        d.line([xx, fy - 7, xx, fy + 7], fill=GREEN, width=2)
        text(d, (xx, fy - 18), nm, GREEN, int(fs * 0.75))
    for t, lab in ((0.25, "40"), (0.5, "80"), (0.75, "120")):
        xx = gx0 + t * (gx1 - gx0)
        text(d, (xx, y1 - 16), lab, CYAN, int(fs * 0.7))


def pfd_nd(side="L", size=(1280, 800)):
    img = Image.new("RGB", size, BG)
    W, H = size
    split = int(W * 0.43)
    if side == "L":
        draw_pfd(img, (0, 0, split, H))
        draw_nd(img, (split, 0, W, H), side)
        ImageDraw.Draw(img).line([split, 6, split, H - 6], fill=DGREY, width=3)
    else:
        draw_nd(img, (0, 0, W - split, H), side)
        draw_pfd(img, (W - split, 0, W, H))
        ImageDraw.Draw(img).line([W - split, 6, W - split, H - 6], fill=DGREY, width=3)
    return img


# --------------------------------------------------------------------------
# Upper centre display: ED + SD (left), mailbox + WD (right)
# --------------------------------------------------------------------------
def _dial(d, cx, cy, r, frac, value, label=None, col=GREEN, size=24, limit=0.93):
    a0, a1 = 215, 215 + 250
    d.arc([cx - r, cy - r, cx + r, cy + r], a0 - 90, a1 - 90, fill=WHITE, width=3)
    d.arc([cx - r, cy - r, cx + r, cy + r], a0 + 250 * limit - 90, a1 - 90, fill=RED, width=6)
    for t in (0, 0.5, 1.0):
        d.line([_rot(cx, cy, r - 9, a0 + 250 * t), _rot(cx, cy, r, a0 + 250 * t)], fill=WHITE, width=3)
    ang = a0 + 250 * frac
    d.line([(cx, cy), _rot(cx, cy, r + 4, ang)], fill=col, width=4)
    bw, bh = r * 0.80, r * 0.36
    d.rectangle([cx - bw * 0.05, cy + r * 0.18, cx + bw * 1.15, cy + r * 0.18 + bh * 1.2], fill=BG,
                outline=GREY, width=2)
    text(d, (cx + bw * 1.08, cy + r * 0.18 + bh * 0.6), value, col, size, "rm")


def ecam(size=(1280, 800)):
    img = Image.new("RGB", size, BG)
    d = ImageDraw.Draw(img)
    W, H = size
    sx = int(W * 0.64)
    ey = int(H * 0.40)
    d.line([sx, 6, sx, H - 6], fill=DGREY, width=3)
    d.line([6, ey, sx - 6, ey], fill=DGREY, width=3)
    # --- engine display
    e1, e2 = sx * 0.27, sx * 0.73
    mid = sx * 0.5
    r = H * 0.085
    text(d, (mid, H * 0.035), "CLB 86.4%", CYAN, 24)
    for ex in (e1, e2):
        _dial(d, ex, H * 0.125, r, 0.78, "84.2", size=26)
        _dial(d, ex, H * 0.305, r * 0.74, 0.60, "612", size=22)
    text(d, (mid, H * 0.115), "THR", WHITE, 22)
    text(d, (mid, H * 0.150), "%", CYAN, 20)
    text(d, (mid, H * 0.295), "EGT", WHITE, 22)
    text(d, (mid, H * 0.330), "°C", CYAN, 20)
    text(d, (sx * 0.06, H * 0.225), "N1", WHITE, 20, "lm")
    text(d, (e1 - r * 1.25, H * 0.225), "89.6", GREEN, 22, "lm")
    text(d, (e2 + r * 1.25, H * 0.225), "89.6", GREEN, 22, "rm")
    # --- system display : CRUISE page
    y = ey + 10
    text(d, (20, y + 18), "CRUISE", WHITE, 24, "lm")
    d.line([20, y + 34, 128, y + 34], fill=WHITE, width=2)
    rows = [("FF", "KG/H", "2810", "2795"), ("OIL QT", "QT", "14.5", "14.2"),
            ("VIB N1", "", "0.3", "0.4"), ("NAC", "°C", "62", "64")]
    for i, (nm, unit, a, b) in enumerate(rows):
        yy = y + 70 + i * 42
        text(d, (mid, yy), nm, WHITE, 21)
        text(d, (mid, yy + 20), unit, CYAN, 15)
        text(d, (mid - 150, yy), a, GREEN, 23, "rm")
        text(d, (mid + 150, yy), b, GREEN, 23, "lm")
    # fuel synoptic
    fy = y + 262
    d.line([20, fy - 22, sx - 20, fy - 22], fill=DGREY, width=2)
    text(d, (mid, fy), "FOB  48 250 KG", GREEN, 24)
    bw = sx * 0.22
    for i, (lab, val) in enumerate((("L", "18 400"), ("CTR", "11 450"), ("R", "18 400"))):
        bx = sx * (0.20 + 0.30 * i)
        d.rectangle([bx - bw / 2, fy + 26, bx + bw / 2, fy + 76], outline=WHITE, width=2)
        text(d, (bx, fy + 51), val, GREEN, 22)
    # cabin / air
    cy = fy + 112
    d.line([20, cy - 24, sx - 20, cy - 24], fill=DGREY, width=2)
    for i, (lab, val, unit) in enumerate((("CAB ALT", "5 900", "FT"), ("CAB V/S", "0", "FT/MIN"),
                                           ("ΔP", "8.9", "PSI"))):
        bx = sx * (0.18 + 0.32 * i)
        text(d, (bx, cy), lab, WHITE, 19)
        text(d, (bx, cy + 27), val, GREEN, 22)
        text(d, (bx + 62, cy + 29), unit, CYAN, 14, "lm")
    # permanent data
    py = H - 34
    d.line([6, py - 22, sx - 6, py - 22], fill=GREY, width=2)
    text(d, (20, py), "TAT -24 °C", GREEN, 19, "lm")
    text(d, (250, py), "SAT -56 °C", GREEN, 19, "lm")
    text(d, (mid + 60, py), "10 H 04", GREEN, 22)
    text(d, (sx - 20, py), "GW 232.4 T", GREEN, 19, "rm")
    # --- mailbox
    mh = int(H * 0.25)
    d.rectangle([sx + 12, 12, W - 12, mh], outline=GREY, width=2)
    text(d, (sx + 26, 34), "ATC MAILBOX", WHITE, 19, "lm")
    text(d, (sx + 26, 76), "1004Z FROM LFBB CTL", GREEN, 18, "lm", bold=False)
    text(d, (sx + 26, 106), "CLIMB TO FL380", WHITE, 21, "lm")
    text(d, (sx + 26, 136), "REPORT LEVEL", WHITE, 21, "lm")
    for i, (lab, col) in enumerate((("WILCO", CYAN), ("UNABLE", CYAN), ("STBY", CYAN))):
        bx = sx + 26 + i * (W - sx - 52) / 3
        d.rectangle([bx, mh - 44, bx + (W - sx - 70) / 3, mh - 10], outline=GREY, width=2)
        text(d, (bx + (W - sx - 70) / 6, mh - 27), lab, col, 17)
    # --- warning display / memos
    wy = mh + 26
    memos = [("SEAT BELTS", GREEN), ("NO MOBILE", GREEN), ("ENG A-ICE", GREEN), ("ADS-C CONNECTED", GREEN),
             ("CPDLC CONNECTED", GREEN), ("TCAS TA/RA", GREEN), ("AUTO BRK OFF", GREEN)]
    text(d, (sx + 22, wy), "MEMO", WHITE, 19, "lm")
    for i, (m, col) in enumerate(memos):
        text(d, (sx + 22, wy + 38 + i * 34), m, col, 21, "lm")
    ly = H - 150
    d.line([sx + 12, ly, W - 12, ly], fill=DGREY, width=2)
    text(d, (sx + 22, ly + 28), "LIMITATIONS", WHITE, 18, "lm")
    text(d, (sx + 22, ly + 62), "NONE", GREEN, 20, "lm")
    text(d, (sx + 22, H - 34), "STS", WHITE, 20, "lm")
    return img


# --------------------------------------------------------------------------
# Lower centre display: two MFD (FMS) pages side by side
# --------------------------------------------------------------------------
def _fms_page(d, box, title="ACTIVE / F-PLN", shift=0):
    x0, y0, x1, y1 = box
    w = x1 - x0
    d.rectangle([x0 + 6, y0 + 6, x1 - 6, y0 + 44], fill=(60, 64, 72))
    for i, m in enumerate(("ACTIVE", "POSITION", "SEC INDEX", "DATA")):
        text(d, (x0 + 24 + i * w * 0.24, y0 + 25), m, WHITE, 17, "lm")
    d.rectangle([x0 + 6, y0 + 50, x1 - 6, y0 + 86], outline=GREY, width=2)
    text(d, (x0 + 20, y0 + 68), title, WHITE, 20, "lm")
    text(d, (x1 - 20, y0 + 68), "AIB350", GREEN, 20, "rm")
    hdr = ("FROM", "UTC", "SPD", "ALT", "TRK", "DIST")
    cols = (0.04, 0.30, 0.46, 0.62, 0.78, 0.96)
    anch = ("lm", "lm", "lm", "lm", "lm", "rm")
    for c, hname, an in zip(cols, hdr, anch):
        text(d, (x0 + c * w, y0 + 110), hname, WHITE, 15, an)
    rows = [("LFBO/14R", "0932", "---", "499", "", ""),
            ("FISTO5B", "", "", "", "", ""),
            ("FISTO", "0941", "250", "FL120", "352°", "38"),
            ("PERIG", "0949", ".85", "FL290", "004°", "61"),
            ("DEVAL", "1010", ".85", "FL360", "046°", "168"),
            ("KOSEB", "1024", ".85", "FL360", "039°", "112"),
            ("ROTAR", "1041", ".85", "FL360", "052°", "134"),
            ("(T/D)", "1118", ".85", "FL360", "", "290"),
            ("EDDM/26R", "1146", "", "1487", "", "214")]
    rows = rows[shift:] + rows[:shift]
    for i, r in enumerate(rows):
        yy = y0 + 150 + i * 48
        hl = (r[0] == "DEVAL")
        for c, v, an in zip(cols, r, anch):
            col = WHITE if hl else GREEN
            if c == cols[0] and r[0] == "FISTO5B":
                col = WHITE
            text(d, (x0 + c * w, yy), v, col, 20, an)
        d.line([x0 + 14, yy + 24, x1 - 14, yy + 24], fill=(30, 33, 38), width=1)
    by = y1 - 96
    d.line([x0 + 6, by, x1 - 6, by], fill=GREY, width=2)
    text(d, (x0 + 20, by + 26), "DEST EDDM26R", WHITE, 18, "lm")
    text(d, (x0 + w * 0.50, by + 26), "1146", GREEN, 20, "lm")
    text(d, (x0 + w * 0.70, by + 26), "8.4 T", GREEN, 20, "lm")
    text(d, (x1 - 20, by + 26), "1247 NM", GREEN, 20, "rm")
    for i, m in enumerate(("INIT", "F-PLN INFO", "DIR TO")):
        bx = x0 + 14 + i * w * 0.32
        d.rectangle([bx, by + 48, bx + w * 0.29, by + 86], fill=(60, 64, 72), outline=GREY, width=2)
        text(d, (bx + w * 0.145, by + 67), m, WHITE, 17)


def mfd(size=(1280, 800)):
    img = Image.new("RGB", size, BG)
    d = ImageDraw.Draw(img)
    W, H = size
    _fms_page(d, (0, 0, W // 2, H), "ACTIVE / F-PLN")
    _fms_page(d, (W // 2, 0, W, H), "ACTIVE / F-PLN", shift=2)
    d.line([W // 2, 6, W // 2, H - 6], fill=DGREY, width=3)
    return img


# --------------------------------------------------------------------------
# Outer displays: OIS (airport chart / application menu)
# --------------------------------------------------------------------------
def ois_chart(size=(1280, 800)):
    img = Image.new("RGB", size, (232, 232, 224))
    d = ImageDraw.Draw(img)
    W, H = size
    ink = (30, 34, 40)
    d.rectangle([0, 0, W, 46], fill=(48, 62, 84))
    text(d, (18, 23), "OIS   CHARTS   LFBO  TOULOUSE BLAGNAC   AIRPORT GROUND CHART", WHITE, 20, "lm")
    d.rectangle([0, 46, 170, H], fill=(206, 208, 204))
    for i, m in enumerate(("REF", "CO", "STAR", "APP", "TAXI", "SID", "DEP", "ENROUTE")):
        d.rectangle([12, 66 + i * 58, 158, 110 + i * 58], fill=(180, 186, 192) if m != "TAXI" else (90, 130, 190),
                    outline=ink, width=2)
        text(d, (85, 88 + i * 58), m, ink if m != "TAXI" else WHITE, 19)
    # runways
    def strip(p1, p2, wd, col):
        (ax, ay), (bx, by) = p1, p2
        L = math.hypot(bx - ax, by - ay)
        nx, ny = -(by - ay) / L * wd / 2, (bx - ax) / L * wd / 2
        d.polygon([(ax + nx, ay + ny), (bx + nx, by + ny), (bx - nx, by - ny), (ax - nx, ay - ny)], fill=col)
    r1 = ((330, 640), (1100, 200))
    r2 = ((400, 740), (1170, 300))
    for r in (r1, r2):
        strip(r[0], r[1], 22, ink)
    for t in (0.1, 0.3, 0.5, 0.7, 0.9):
        a = (r1[0][0] + (r1[1][0] - r1[0][0]) * t, r1[0][1] + (r1[1][1] - r1[0][1]) * t)
        b = (r2[0][0] + (r2[1][0] - r2[0][0]) * t, r2[0][1] + (r2[1][1] - r2[0][1]) * t)
        strip(a, b, 8, (120, 124, 130))
    strip((360, 692), (1130, 252), 8, (120, 124, 130))
    d.polygon([(560, 220), (800, 110), (850, 190), (620, 300)], fill=(170, 176, 184), outline=ink)
    text(d, (705, 205), "TERMINAL", ink, 18)
    for (x, y, s) in ((310, 668, "14R"), (1125, 178, "32L"), (385, 770, "14L"), (1195, 285, "32R")):
        text(d, (x, y), s, (160, 30, 30), 22)
    text(d, (1090, 700), "ELEV 499 FT", ink, 20)
    text(d, (1090, 730), "N43 37.7 E001 22.1", ink, 18)
    for i in range(6):
        d.line([200 + i * 200, 60, 200 + i * 200, H - 10], fill=(200, 200, 192), width=1)
    for i in range(5):
        d.line([180, 100 + i * 150, W - 10, 100 + i * 150], fill=(200, 200, 192), width=1)
    return img


def ois_menu(size=(1280, 800)):
    img = Image.new("RGB", size, (20, 26, 36))
    d = ImageDraw.Draw(img)
    W, H = size
    d.rectangle([0, 0, W, 46], fill=(48, 62, 84))
    text(d, (18, 23), "OIS   FLT OPS MENU", WHITE, 20, "lm")
    text(d, (W - 18, 23), "AIB350   LFBO - EDDM", WHITE, 18, "rm")
    tiles = ["OPS LIBRARY", "T.O PERF", "LDG PERF", "LOADSHEET", "CHARTS", "FLT FOLDER",
             "E-LOGBOOK", "IN-FLT PERF", "WEATHER", "COMPANY COM", "MAINTENANCE", "EXPORT"]
    tw, th = 270, 190
    for i, t in enumerate(tiles):
        cx = 60 + (i % 4) * (tw + 32)
        cy = 86 + (i // 4) * (th + 32)
        d.rounded_rectangle([cx, cy, cx + tw, cy + th], radius=10, fill=(54, 74, 104), outline=(120, 150, 190),
                            width=2)
        d.rounded_rectangle([cx + tw / 2 - 34, cy + 36, cx + tw / 2 + 34, cy + 104], radius=8,
                            outline=(190, 210, 235), width=3)
        text(d, (cx + tw / 2, cy + 148), t, WHITE, 21)
    return img


# --------------------------------------------------------------------------
# Small displays
# --------------------------------------------------------------------------
def isis(size=(512, 512)):
    img = Image.new("RGB", size, BG)
    d = ImageDraw.Draw(img)
    W, H = size
    hz = H * 0.52
    d.rectangle([0, 0, W, hz], fill=SKY)
    d.rectangle([0, hz, W, H], fill=GROUND)
    d.line([0, hz, W, hz], fill=WHITE, width=3)
    for p, ln in ((10, 60), (5, 30), (-5, 30), (-10, 60)):
        yy = hz - p * 9
        d.line([W / 2 - ln, yy, W / 2 + ln, yy], fill=WHITE, width=2)
    d.rectangle([0, 60, 92, H - 60], fill=DGREY)
    d.rectangle([W - 120, 60, W, H - 60], fill=DGREY)
    for i in range(7):
        yy = 90 + i * 55
        d.line([80, yy, 92, yy], fill=WHITE, width=2)
        d.line([W - 120, yy, W - 108, yy], fill=WHITE, width=2)
    d.rectangle([0, hz - 22, 96, hz + 22], fill=BG, outline=YELLOW, width=3)
    text(d, (48, hz), "278", GREEN, 30)
    d.rectangle([W - 132, hz - 22, W, hz + 22], fill=BG, outline=YELLOW, width=3)
    text(d, (W - 66, hz), "36000", GREEN, 28)
    d.line([W / 2 - 110, hz, W / 2 - 40, hz], fill=YELLOW, width=6)
    d.line([W / 2 + 40, hz, W / 2 + 110, hz], fill=YELLOW, width=6)
    d.rectangle([W / 2 - 6, hz - 6, W / 2 + 6, hz + 6], fill=YELLOW)
    text(d, (W / 2, 30), "STD", CYAN, 26)
    text(d, (W / 2, H - 28), "045°", GREEN, 26)
    return img


def isis_nav(size=(512, 512)):
    img = Image.new("RGB", size, BG)
    d = ImageDraw.Draw(img)
    W, H = size
    cx, cy, R = W / 2, H / 2 + 20, 170
    d.ellipse([cx - R, cy - R, cx + R, cy + R], outline=WHITE, width=3)
    for dd in range(0, 360, 10):
        ln = 18 if dd % 30 == 0 else 9
        d.line([_rot(cx, cy, R - ln, dd - 45), _rot(cx, cy, R, dd - 45)], fill=WHITE, width=2)
        if dd % 30 == 0:
            text(d, _rot(cx, cy, R - 38, dd - 45), str(dd // 10), WHITE, 22)
    d.line([cx, cy - R - 16, cx, cy - R + 20], fill=YELLOW, width=5)
    d.line([cx, cy - 26, cx, cy + 30], fill=YELLOW, width=5)
    d.line([cx - 30, cy, cx + 30, cy], fill=YELLOW, width=5)
    d.line([_rot(cx, cy, R * 0.8, 20), _rot(cx, cy, R * 0.8, 200)], fill=GREEN, width=3)
    text(d, (20, 28), "GS 487", GREEN, 24, "lm")
    text(d, (W - 20, 28), "045°", GREEN, 26, "rm")
    text(d, (20, H - 26), "VOR1 TOU", WHITE, 20, "lm")
    return img


def save_all(outdir):
    os.makedirs(outdir, exist_ok=True)
    out = {}
    for name, im in (("pfd_nd_capt", pfd_nd("L")), ("pfd_nd_fo", pfd_nd("R")), ("ecam", ecam()),
                     ("mfd", mfd()), ("ois_capt", ois_chart()), ("ois_fo", ois_menu()), ("isis", isis()), ("isis_nav", isis_nav())):
        p = os.path.join(outdir, name + ".png")
        im.save(p)
        out[name] = p
    return out


if __name__ == "__main__":
    import sys
    print(save_all(sys.argv[1] if len(sys.argv) > 1 else "textures"))
