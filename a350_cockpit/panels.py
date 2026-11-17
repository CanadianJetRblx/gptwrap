"""Control-panel layouts for the A350-900 flight deck.

A Panel is a flat face plate measured in metres.  Each control added to it does
two things at once: it paints its legend on the face-plate artwork (base colour
+ emission maps, via Pillow) and records a small piece of 3D geometry (push
button cap, rotary knob, toggle lever, guard, key).  build_cockpit.py turns the
geometry records into a mesh and projects the artwork onto it, so labels and
relief always line up.

Layouts were taken from photographs of in-service A350-900/-1000 flight decks
(see REFERENCES.md).  Local frame of every panel: x to the right, y "up" as
the legends read, z out of the face plate.
"""
import math
from PIL import Image, ImageDraw
from displays import font, GREEN, CYAN, AMBER, RED, WHITE

PLATE = (116, 132, 154)     # Airbus blue-grey face plate
PLATE_DK = (92, 106, 126)
CAP = (26, 27, 30)          # push-button / key cap
CAP_EDGE = (70, 74, 82)
KNOB_W = (226, 226, 220)    # white rotary knobs (overhead, pedestal, glareshield)
KNOB_B = (26, 27, 29)       # black knobs (RMP)
LEGEND = (240, 242, 244)
DIM = (96, 100, 106)        # unlit legend
BLUE = (70, 170, 255)
GUARD_RED = (196, 34, 30)
GUARD_BLK = (22, 22, 24)
FLOW = (70, 220, 70)        # green synoptic flow lines on the overhead


class Panel:
    def __init__(self, name, w, h, ppm=4000, plate=PLATE):
        self.name, self.w, self.h, self.ppm = name, w, h, ppm
        self.W, self.H = int(round(w * ppm)), int(round(h * ppm))
        self.plate = plate
        self.img = Image.new("RGB", (self.W, self.H), plate)
        self.emit = Image.new("RGB", (self.W, self.H), (0, 0, 0))
        self.d = ImageDraw.Draw(self.img)
        self.e = ImageDraw.Draw(self.emit)
        self.geo = []          # geometry records
        self.screens = []      # (x0, y0, x1, y1, texture_key)
        self.d.rectangle([0, 0, self.W - 1, self.H - 1], outline=PLATE_DK, width=max(2, int(0.0008 * ppm)))

    # -- helpers ---------------------------------------------------------
    def p(self, x, y):
        return (x * self.ppm, self.H - y * self.ppm)

    def s(self, m):
        return m * self.ppm

    def _text(self, x, y, s, col=LEGEND, mm=2.2, anchor="mm", lit=0.0, bold=True, mono=False):
        f = font(max(7, int(self.s(mm / 1000.0) * 1.35)), bold, mono)
        lines = s.split("\n")
        lh = self.s(mm / 1000.0) * 1.45
        px, py = self.p(x, y)
        py -= lh * (len(lines) - 1) / 2
        for i, ln in enumerate(lines):
            self.d.text((px, py + i * lh), ln, fill=col, font=f, anchor=anchor)
            if lit > 0:
                self.e.text((px, py + i * lh), ln, fill=tuple(int(c * lit) for c in col), font=f, anchor=anchor)

    def label(self, x, y, s, mm=2.0, col=LEGEND, anchor="mm", lit=0.08):
        self._text(x, y, s, col, mm, anchor, lit)

    def line(self, x0, y0, x1, y1, col=LEGEND, mm=0.4):
        self.d.line([self.p(x0, y0), self.p(x1, y1)], fill=col, width=max(1, int(self.s(mm / 1000.0))))

    def frame(self, x0, y0, x1, y1, title=None, mm=2.6, side=None):
        self.d.rounded_rectangle([self.p(x0, y1), self.p(x1, y0)], radius=int(self.s(0.004)), outline=LEGEND,
                                 width=max(2, int(self.s(0.0004))))
        if title:
            f = font(max(7, int(self.s(mm / 1000.0) * 1.35)))
            tw = self.d.textlength(title, font=f) + self.s(0.004)
            px, py = self.p((x0 + x1) / 2, y1)
            self.d.rectangle([px - tw / 2, py - self.s(0.002), px + tw / 2, py + self.s(0.002)], fill=self.plate)
            self._text((x0 + x1) / 2, y1, title, LEGEND, mm, lit=0.08)

    def screw(self, x, y, r=0.0028):
        self.d.ellipse([self.p(x - r, y + r), self.p(x + r, y - r)], fill=(150, 160, 172), outline=(70, 78, 90))
        self.line(x - r * 0.6, y, x + r * 0.6, y, (60, 66, 76), 0.4)
        self.geo.append(("cyl", x, y, r, 0.0, 0.0008, 10))

    def screws(self, inset=0.006):
        for x in (inset, self.w - inset):
            for y in (inset, self.h - inset):
                self.screw(x, y)

    # -- controls --------------------------------------------------------
    def pb(self, x, y, top="", bot="", size=0.019, top_col=AMBER, bot_col=LEGEND, lit=(False, False),
           label=None, cover=None, height=0.004, mm=1.7, label_mm=1.9, w=None):
        """Korry-style push-button switch with two legend fields; cover = guard colour."""
        w2 = (w or size) / 2
        h2 = size / 2
        self.d.rounded_rectangle([self.p(x - w2 - 0.0012, y + h2 + 0.0012), self.p(x + w2 + 0.0012, y - h2 - 0.0012)],
                                 radius=int(self.s(0.0015)), fill=(60, 68, 80))
        self.d.rounded_rectangle([self.p(x - w2, y + h2), self.p(x + w2, y - h2)], radius=int(self.s(0.0012)),
                                 fill=CAP, outline=CAP_EDGE, width=max(1, int(self.s(0.0004))))
        for txt, col, on, dy in ((top, top_col, lit[0], size * 0.22), (bot, bot_col, lit[1], -size * 0.22)):
            if txt:
                c = col if on else tuple(int(DIM[i] * 0.45 + col[i] * 0.10) for i in range(3))
                self._text(x, y + dy if (top and bot) else y, txt, c, mm, lit=1.0 if on else 0.0)
        self.geo.append(("box", x, y, w2 * 2, size, 0.0, height))
        if cover:
            cw, ch = w2 * 2 + 0.004, size + 0.007
            self.d.rounded_rectangle([self.p(x - cw / 2, y + ch / 2 - 0.002), self.p(x + cw / 2, y - ch / 2 - 0.002)],
                                     radius=int(self.s(0.002)), fill=cover)
            self.geo.append(("guard", x, y - 0.002, cw, ch, 0.014))
        if label:
            n = label.count("\n")
            self._text(x, y + h2 + 0.0040 + n * 0.0015 + (0.002 if cover else 0), label, LEGEND, label_mm, lit=0.08)

    def rpb(self, x, y, r=0.0045, label=None, label_dy=None, col=CAP, height=0.004, label_mm=1.7):
        """Small round push-button."""
        self.d.ellipse([self.p(x - r - 0.0015, y + r + 0.0015), self.p(x + r + 0.0015, y - r - 0.0015)],
                       fill=(58, 66, 78))
        self.d.ellipse([self.p(x - r, y + r), self.p(x + r, y - r)], fill=col, outline=CAP_EDGE)
        self.geo.append(("cyl", x, y, r, 0.0, height, 14))
        if label:
            self._text(x, y + (label_dy if label_dy is not None else r + 0.0045), label, LEGEND, label_mm, lit=0.08)

    def key(self, x, y, w, h, txt="", col=LEGEND, fill=CAP, mm=1.7, height=0.0025, lit=0.10, rnd=False):
        box = [self.p(x - w / 2, y + h / 2), self.p(x + w / 2, y - h / 2)]
        if rnd:
            self.d.ellipse(box, fill=fill, outline=CAP_EDGE)
            self.geo.append(("cyl", x, y, w / 2, 0.0, height, 12))
        else:
            self.d.rounded_rectangle(box, radius=int(self.s(0.0010)), fill=fill, outline=CAP_EDGE,
                                     width=max(1, int(self.s(0.0003))))
            self.geo.append(("box", x, y, w, h, 0.0, height))
        if txt:
            self._text(x, y, txt, col, mm, lit=lit)

    def knob(self, x, y, r=0.010, label=None, marks=(), pointer=0.0, height=0.018, mm=1.7, label_dy=None,
             white=True, skirt=True, star=False, label_mm=1.9):
        """Rotary selector.  marks = [(angle_deg_clockwise_from_up, text), ...]"""
        for ang, txt in marks:
            a = math.radians(ang)
            rr = r + 0.0034
            self.line(x + rr * math.sin(a), y + rr * math.cos(a), x + (rr + 0.0018) * math.sin(a),
                      y + (rr + 0.0018) * math.cos(a), LEGEND, 0.4)
            if txt:
                ln = max(len(t) for t in txt.split("\n"))
                tr = rr + 0.0034 + 0.0010 * ln
                self._text(x + tr * math.sin(a), y + tr * math.cos(a) * 0.9, txt, LEGEND, mm, lit=0.08)
        body = KNOB_W if white else KNOB_B
        if star:
            pts = []
            for i in range(24):
                a = math.radians(i * 15)
                rr = r + (0.0045 if i % 2 == 0 else 0.0020)
                pts.append(self.p(x + rr * math.sin(a), y + rr * math.cos(a)))
            self.d.polygon(pts, fill=(170, 176, 184), outline=(70, 76, 86))
            self.geo.append(("cyl", x, y, r + 0.0035, 0.0, 0.004, 12))
        if skirt:
            rs = r + 0.0020
            self.d.ellipse([self.p(x - rs, y + rs), self.p(x + rs, y - rs)],
                           fill=(168, 172, 176) if white else (14, 14, 16), outline=(60, 66, 76))
            self.geo.append(("cyl", x, y, rs, 0.0, 0.004, 24))
        self.d.ellipse([self.p(x - r, y + r), self.p(x + r, y - r)], fill=body, outline=(110, 114, 120))
        a = math.radians(pointer)
        self.line(x + r * 0.05 * math.sin(a), y + r * 0.05 * math.cos(a), x + r * 0.98 * math.sin(a),
                  y + r * 0.98 * math.cos(a), (30, 32, 36) if white else (235, 235, 235), 0.9)
        self.geo.append(("knob", x, y, r, height, pointer, 1 if white else 0))
        if label:
            dy = label_dy if label_dy is not None else -(r + 0.0070)
            self._text(x, y + dy, label, LEGEND, label_mm, lit=0.08)

    def toggle(self, x, y, label=None, pos=None, tilt=18.0, mm=1.5, label_dy=0.0125, paddle=False, label_mm=1.8):
        """Toggle switch; pos = [(dy_factor, text)] legends to the right."""
        r = 0.0042
        self.d.ellipse([self.p(x - r, y + r), self.p(x + r, y - r)], fill=(150, 152, 156), outline=(60, 60, 62))
        self.geo.append(("toggle", x, y, tilt, 1 if paddle else 0))
        if label:
            self._text(x, y + label_dy, label, LEGEND, label_mm, lit=0.08)
        for dy, txt in (pos or ()):
            self._text(x + 0.0075, y + dy * 0.0055, txt, LEGEND, mm, anchor="lm", lit=0.08)

    def lcd(self, x0, y0, x1, y1, txt="", col=WHITE, mm=5.0, anchor="mm", mono=True):
        self.d.rectangle([self.p(x0, y1), self.p(x1, y0)], fill=(5, 6, 8), outline=(30, 32, 36),
                         width=max(2, int(self.s(0.0006))))
        self.e.rectangle([self.p(x0, y1), self.p(x1, y0)], fill=(3, 4, 5))
        if txt:
            cx = (x0 + x1) / 2 if anchor == "mm" else x0 + 0.002
            self._text(cx, (y0 + y1) / 2, txt, col, mm, anchor=anchor, lit=1.0, mono=mono)

    def lcd_text(self, x, y, txt, col=WHITE, mm=2.4, anchor="mm", mono=False):
        self._text(x, y, txt, col, mm, anchor=anchor, lit=1.0, mono=mono)

    def annun(self, x, y, w, h, txt, col=GREEN, lit=False, mm=1.6):
        self.d.rectangle([self.p(x - w / 2, y + h / 2), self.p(x + w / 2, y - h / 2)], fill=(14, 15, 17),
                         outline=CAP_EDGE, width=max(1, int(self.s(0.0004))))
        c = col if lit else tuple(int(DIM[i] * 0.45 + col[i] * 0.12) for i in range(3))
        self._text(x, y, txt, c, mm, lit=1.0 if lit else 0.0)

    def slot(self, x0, y0, x1, y1):
        self.d.rounded_rectangle([self.p(x0, y1), self.p(x1, y0)], radius=int(self.s(0.003)), fill=(8, 8, 9),
                                 outline=(70, 78, 90), width=max(2, int(self.s(0.0005))))

    def raised(self, x0, y0, x1, y1, height, fill=None):
        self.d.rounded_rectangle([self.p(x0, y1), self.p(x1, y0)], radius=int(self.s(0.002)),
                                 fill=fill or self.plate, outline=PLATE_DK, width=max(1, int(self.s(0.0005))))
        self.geo.append(("box", (x0 + x1) / 2, (y0 + y1) / 2, x1 - x0, y1 - y0, 0.0, height))

    def rocker(self, x, y, w, h, height=0.010):
        self.d.rectangle([self.p(x - w / 2, y + h / 2), self.p(x + w / 2, y - h / 2)], fill=(20, 20, 22))
        n = 7
        for i in range(n):
            yy = y - h / 2 + h * (i + 0.5) / n
            self.line(x - w / 2, yy, x + w / 2, yy, (60, 60, 64), 0.5)
        self.geo.append(("box", x, y, w, h, 0.0, height))

    def hazard(self, x0, y0, x1, y1, t=0.008):
        """Yellow / black striped frame."""
        px0, py1 = self.p(x0, y0)
        px1, py0 = self.p(x1, y1)
        tile = Image.new("RGB", (int(px1 - px0), int(py1 - py0)), (240, 200, 20))
        td = ImageDraw.Draw(tile)
        st = int(self.s(0.006))
        for i in range(-tile.height, tile.width + tile.height, 2 * st):
            td.polygon([(i, tile.height), (i + st, tile.height), (i + st + tile.height, 0), (i + tile.height, 0)],
                       fill=(20, 20, 20))
        self.img.paste(tile, (int(px0), int(py0)))
        self.d.rectangle([self.p(x0 + t, y1 - t), self.p(x1 - t, y0 + t)], fill=(150, 30, 28))

    def screen(self, x0, y0, x1, y1, key):
        self.d.rectangle([self.p(x0, y1), self.p(x1, y0)], fill=(4, 4, 5))
        self.screens.append((x0, y0, x1, y1, key))

    def row(self, y, x0, x1, items, fn):
        n = len(items)
        for i, it in enumerate(items):
            if it is None:
                continue
            fn(x0 + (x1 - x0) * (i + 0.5) / n, y, it)

    def flow(self, pts):
        self.d.line([self.p(*q) for q in pts], fill=FLOW, width=max(2, int(self.s(0.0009))))


# ==========================================================================
# Glareshield
# ==========================================================================
def afs_cp():
    """AFS control panel: SPD - HDG/TRK - FD/AP/A-THR - ALT - V/S/FPA."""
    P = Panel("AFS_CP", 0.240, 0.090)
    for x, a, b in ((0.030, "MACH", "SPD"), (0.086, "TRUE", "MAG"), (0.160, "", "METER")):
        P.rpb(x, 0.081, 0.0042, height=0.003)
        if a:
            P.label(x - 0.006, 0.081, a, 1.4, anchor="rm")
        P.label(x + 0.006, 0.081, b, 1.4, anchor="lm")
    P.rpb(0.120, 0.078, 0.0048, height=0.003)
    P.label(0.120, 0.086, "HDG  V/S", 1.3)
    P.label(0.120, 0.069, "TRK  FPA", 1.3)
    P.lcd(0.010, 0.046, 0.104, 0.072)
    P.lcd_text(0.022, 0.067, "SPD", WHITE, 1.6)
    P.lcd_text(0.034, 0.056, "280", WHITE, 4.6, mono=True)
    P.lcd_text(0.049, 0.054, "KT", WHITE, 1.6)
    P.lcd_text(0.066, 0.067, "HDG", WHITE, 1.6)
    P.lcd_text(0.080, 0.056, "045°", WHITE, 4.6, mono=True)
    P.pb(0.121, 0.055, "FD", "", 0.013, top_col=GREEN, mm=1.7, lit=(True, False))
    P.pb(0.1135, 0.035, "AP1", "", 0.0135, top_col=GREEN, mm=1.5, lit=(True, False))
    P.pb(0.1285, 0.035, "AP2", "", 0.0135, top_col=GREEN, mm=1.5)
    P.pb(0.121, 0.014, "A/THR", "", 0.0135, top_col=GREEN, mm=1.3, lit=(True, False))
    P.lcd(0.138, 0.046, 0.232, 0.072)
    P.lcd_text(0.152, 0.067, "ALT", WHITE, 1.6)
    P.lcd_text(0.164, 0.056, "36000", WHITE, 4.6, mono=True)
    P.lcd_text(0.212, 0.067, "V/S", WHITE, 1.6)
    P.lcd_text(0.210, 0.056, "-----", WHITE, 4.0, mono=True)
    P.knob(0.036, 0.027, 0.0105, height=0.020)
    P.knob(0.080, 0.027, 0.0095, height=0.020, star=True, skirt=False)
    P.pb(0.080, 0.007, "LOC", "", 0.011, top_col=GREEN, mm=1.4, w=0.014)
    P.knob(0.162, 0.029, 0.0105, height=0.020, marks=((-45, "100"), (45, "1000")))
    P.pb(0.162, 0.007, "ALT", "", 0.011, top_col=GREEN, mm=1.4, w=0.014)
    P.knob(0.208, 0.029, 0.0105, height=0.020, marks=((-50, "DN"), (50, "UP")))
    P.pb(0.208, 0.007, "APPR", "", 0.011, top_col=GREEN, mm=1.3, w=0.014)
    P.screws(0.005)
    return P


def efis_cp(side="L"):
    """EFIS control panel: QNH, LS/VV, soft-key LCD strip, ND mode + range."""
    w = 0.185
    P = Panel("EFIS_CP_" + side, w, 0.090)
    mx = (lambda x: x) if side == "L" else (lambda x: w - x)
    a, b = sorted((mx(0.008), mx(0.044)))
    P.lcd(a, 0.049, b, 0.069)
    P.lcd_text((a + b) / 2, 0.065, "QNH", WHITE, 1.4)
    P.lcd_text((a + b) / 2, 0.056, "1013", WHITE, 3.6, mono=True)
    P.key(mx(0.016), 0.080, 0.013, 0.008, "TAXI", mm=1.1)
    P.key(mx(0.033), 0.080, 0.013, 0.008, "", mm=1.1)
    P.knob(mx(0.026), 0.029, 0.0100, height=0.018, marks=((-45, "inHg"), (45, "hPa")))
    P.key(mx(0.016), 0.007, 0.013, 0.009, "LS" if side == "L" else "VV", mm=1.5)
    P.key(mx(0.034), 0.007, 0.013, 0.009, "VV" if side == "L" else "LS", mm=1.5)
    a, b = sorted((mx(0.052), mx(0.178)))
    P.lcd(a, 0.051, b, 0.071)
    opts = (("CSTR", "WPT", "VORD", "NDB", "ARPT"), ("─▷─", "WX", "TERR", "TRAF", "─◁═"))
    for i in range(5):
        cx = a + (b - a) * (i + 0.5) / 5
        P.lcd_text(cx, 0.066, opts[0][i], GREEN if opts[0][i] == "WPT" else WHITE, 1.7)
        P.lcd_text(cx, 0.056, opts[1][i], GREEN if opts[1][i] == "TERR" else WHITE, 1.7)
        P.key(cx, 0.080, 0.017, 0.008, "˅", mm=1.8, height=0.003)
        P.key(cx, 0.042, 0.017, 0.008, "˄", mm=1.8, height=0.003)
    P.knob(mx(0.088), 0.019, 0.0090, height=0.017, pointer=30,
           marks=((-90, "LS"), (-50, "VOR"), (-10, "NAV"), (30, "ARC"), (75, "PLAN")), mm=1.4)
    P.knob(mx(0.146), 0.019, 0.0090, height=0.017, pointer=0, mm=1.3,
           marks=((-110, "ZOOM"), (-75, "10"), (-45, "20"), (-15, "40"), (15, "80"), (45, "160"), (75, "320"),
                  (105, "640")))
    P.screws(0.005)
    return P


def warn_block(side="L"):
    """MASTER WARN over MASTER CAUT at the end of the raised glareshield block."""
    P = Panel("MASTER_WARN_CAUT_" + side, 0.036, 0.090)
    P.pb(0.018, 0.060, "MASTER", "WARN", 0.022, top_col=RED, bot_col=RED, mm=1.6)
    P.pb(0.018, 0.030, "MASTER", "CAUT", 0.022, top_col=AMBER, bot_col=AMBER, mm=1.6)
    return P


def wing_inner(side="L"):
    """Side-stick priority light and CHRONO push-button on the glareshield wing."""
    w = 0.200
    P = Panel("GLARESHIELD_WING_INNER_" + side, w, 0.048)
    mx = (lambda x: x) if side == "R" else (lambda x: w - x)
    P.pb(mx(0.020), 0.020, "◄" if side == "R" else "►", "CAPT" if side == "L" else "F/O", 0.018, top_col=RED,
         bot_col=GREEN, mm=1.5)
    P.label(mx(0.020), 0.040, "SIDESTICK\nPRIORITY", 1.2)
    P.rpb(mx(0.052), 0.020, 0.0075, height=0.004)
    P.label(mx(0.052), 0.040, "CHRONO", 1.3)
    # audio / microphone sub-panel further outboard: selector, volume knob, push-button
    P.line(mx(0.078), 0.004, mx(0.078), 0.044, PLATE_DK, 0.8)
    P.rpb(mx(0.104), 0.021, 0.0050, height=0.004)
    P.knob(mx(0.138), 0.021, 0.0070, height=0.012)
    P.key(mx(0.172), 0.021, 0.016, 0.010, "", height=0.003)
    return P


def wing_outer(side="L"):
    """Outer glareshield wing: two push-buttons and the loudspeaker volume knob."""
    w = 0.170
    P = Panel("GLARESHIELD_WING_OUTER_" + side, w, 0.048)
    mx = (lambda x: x) if side == "R" else (lambda x: w - x)
    P.pb(mx(0.030), 0.021, "", "", 0.016, mm=1.2)
    P.label(mx(0.030), 0.040, "ATC MSG", 1.2)
    P.pb(mx(0.090), 0.021, "", "", 0.016, mm=1.2)
    P.label(mx(0.090), 0.040, "AUTOLAND", 1.2)
    P.knob(mx(0.140), 0.021, 0.0075, height=0.012)
    P.label(mx(0.140), 0.040, "LOUDSPEAKER", 1.2)
    return P


# ==========================================================================
# Main instrument panel
# ==========================================================================
def col_left():
    """Between the captain's PFD/ND and the centre display: placard + switching."""
    P = Panel("MIP_COLUMN_LEFT", 0.075, 0.290)
    P.d.rectangle([P.p(0.008, 0.280), P.p(0.067, 0.196)], fill=(120, 150, 190), outline=(200, 215, 235))
    P.label(0.0375, 0.270, "LIMIT SPD\n(IAS KT)", 1.5)
    for i, (a, b) in enumerate((("VLO/VLE", "250"), ("VFE 1", "255"), ("1+F", "233"), ("2", "212"), ("3", "195"),
                                 ("FULL", "186"))):
        P.label(0.012, 0.253 - i * 0.0095, a, 1.3, anchor="lm")
        P.label(0.063, 0.253 - i * 0.0095, b, 1.3, anchor="rm")
    P.screw(0.012, 0.188)
    P.screw(0.063, 0.188)
    P.label(0.0375, 0.158, "AIR DATA", 2.0)
    P.knob(0.0375, 0.126, 0.010, height=0.020, marks=((-52, "CAPT ON\nBKUP"), (0, "AUTO"), (52, "F/O ON\nBKUP")),
           mm=1.2)
    P.line(0.012, 0.094, 0.063, 0.094)
    P.label(0.0375, 0.084, "FMS", 2.0)
    P.knob(0.0375, 0.050, 0.010, height=0.020, marks=((-52, "BOTH\nON 2"), (0, "NORM"), (52, "BOTH\nON 1")), mm=1.2)
    P.screw(0.010, 0.010)
    P.screw(0.065, 0.010)
    return P


def col_right():
    """Between the centre display and the F/O's PFD/ND: anti-skid, auto-brake, gear lever."""
    P = Panel("MIP_COLUMN_RIGHT", 0.075, 0.290)
    P.label(0.050, 0.278, "ANTI SKID", 1.4)
    P.toggle(0.050, 0.262, pos=((1.2, "ON"), (-1.2, "OFF")), mm=1.3)
    P.label(0.0375, 0.236, "RWY     BRAKING\nCOND    ACTION", 1.2)
    P.knob(0.0375, 0.212, 0.0095, height=0.018)
    P.pb(0.0375, 0.182, "A/BRK", "", 0.014, top_col=LEGEND, mm=1.3)
    P.screw(0.010, 0.170)
    P.screw(0.065, 0.170)
    P.raised(0.006, 0.008, 0.069, 0.150, 0.004)
    P.slot(0.016, 0.022, 0.030, 0.134)
    P.label(0.048, 0.132, "UP", 1.8)
    P.label(0.048, 0.024, "DOWN", 1.8)
    for y0, y1 in ((0.090, 0.122), (0.034, 0.068)):
        P.d.rectangle([P.p(0.046, y1), P.p(0.050, y0)], outline=LEGEND)
    P.d.polygon([P.p(0.043, 0.118), P.p(0.048, 0.127), P.p(0.053, 0.118)], outline=LEGEND)
    P.d.polygon([P.p(0.043, 0.038), P.p(0.048, 0.029), P.p(0.053, 0.038)], outline=LEGEND)
    return P


def isis_unit(side="L"):
    """Integrated standby instrument unit beside the lower centre display, + 2 push-buttons."""
    w = 0.105
    P = Panel("ISIS_" + side, w, 0.200)
    P.raised(0.008, 0.072, 0.097, 0.192, 0.007, fill=(96, 110, 130))
    P.screen(0.022, 0.092, 0.083, 0.166, "isis" if side == "L" else "isis_nav")
    P.key(0.036, 0.180, 0.016, 0.007, "MODE", mm=1.1, height=0.009)
    P.key(0.064, 0.180, 0.016, 0.007, "LS/▷", mm=1.1, height=0.009)
    P.key(0.036, 0.080, 0.016, 0.007, "MENU", mm=1.1, height=0.009)
    P.label(0.066, 0.080, "SET/SEL", 1.1)
    P.knob(0.088, 0.090, 0.0055, height=0.022, skirt=False)
    P.key(0.014, 0.146, 0.006, 0.014, "", height=0.009)
    P.key(0.014, 0.116, 0.006, 0.014, "", height=0.009)
    names = ("DISPLAY\nCYCLE", "CAPT OIS\nON CENTER") if side == "L" else ("F/O OIS\nON CENTER", "DISPLAY\nCYCLE")
    for x, nm in zip((0.032, 0.072), names):
        P.pb(x, 0.030, "", "", 0.017, label=nm, label_mm=1.3)
    for x, y in ((0.006, 0.196), (0.099, 0.196), (0.006, 0.006), (0.099, 0.006)):
        P.screw(x, y)
    return P


# ==========================================================================
# Pedestal
# ==========================================================================
def kccu(side="L"):
    """Keyboard and cursor control unit (keyboard forward, palm-rest dome aft)."""
    w = 0.190
    P = Panel("KCCU_" + side, w, 0.270)
    mx = (lambda x: x) if side == "L" else (lambda x: w - x)
    P.key(mx(0.016), 0.256, 0.016, 0.010, "ESC", mm=1.2)
    for dx, dy, t in ((0, 0.006, "▲"), (0, -0.006, "▼"), (-0.007, 0, "◄"), (0.007, 0, "►")):
        P.key(mx(0.044) + dx, 0.251 + dy, 0.0062, 0.0062, t, mm=1.0, rnd=True)
    for i, t in enumerate(("DIR", "PERF", "INIT", "NAV\nAID", "C/L\nMENU")):
        P.key(mx(0.076 + i * 0.0235), 0.257, 0.020, 0.0105, t, mm=1.1)
    P.key(mx(0.016), 0.242, 0.016, 0.010, "CLR\nINFO", mm=1.0)
    for i, t in enumerate(("F-PLN", "DEST", "SEC\nINDEX", "SURV", "ATC\nCOM")):
        P.key(mx(0.076 + i * 0.0235), 0.243, 0.020, 0.0105, t, mm=1.1)
    for r, row in enumerate(("QWERTYUIOP", "ASDFGHJKL", "ZXCVBNM")):
        for c, t in enumerate(row):
            P.key(mx(0.020 + (c + r * 0.4) * 0.0152), 0.224 - r * 0.0148, 0.0120, 0.0120, t, mm=1.6, rnd=True)
    P.key(mx(0.175), 0.2092, 0.018, 0.011, "NOTE\nPAD", mm=1.0)
    P.key(mx(0.150), 0.1944, 0.022, 0.011, "SPACE", mm=1.0)
    P.key(mx(0.176), 0.1944, 0.018, 0.011, "ENT", mm=1.1)
    # numeric keypad, inboard side
    for i, t in enumerate(("1", "2", "3", "4", "5", "6", "7", "8", "9", ".", "0", "+/-")):
        P.key(mx(0.132 + (i % 3) * 0.0160), 0.172 - (i // 3) * 0.0152, 0.0120, 0.0120, t, mm=1.5, rnd=True)
    P.key(mx(0.148), 0.108, 0.024, 0.010, "SPACE", mm=1.0)
    P.label(mx(0.176), 0.094, "KBD %s\nCCD %s" % (("1", "1") if side == "L" else ("2", "2")), 1.1)
    P.key(mx(0.136), 0.078, 0.018, 0.010, "KBD", mm=1.1)
    P.key(mx(0.160), 0.078, 0.018, 0.010, "ESC", mm=1.1)
    # cursor control device: moulded palm rest with trackball and click keys
    cx, cy = mx(0.066), 0.098
    P.d.rounded_rectangle([P.p(cx - 0.060, cy + 0.076), P.p(cx + 0.060, cy - 0.086)], radius=int(P.s(0.020)),
                          fill=(104, 119, 140), outline=PLATE_DK)
    P.geo.append(("dome", cx, cy - 0.010, 0.054, 0.066, 0.050, mx(0.002) - cx > 0))
    P.screws(0.006)
    return P


def rmp(n=1):
    """Radio management panel."""
    P = Panel("RMP_%d" % n, 0.146, 0.220)
    for i, t in enumerate(("VHF", "HF", "TEL", "SQWK", "", "MENU", "NAV")):
        P.key(0.0155 + i * 0.0192, 0.208, 0.0170, 0.0095, t, mm=1.3, lit=0.5 if t == "VHF" else 0.1,
              col=GREEN if t == "VHF" else LEGEND)
    P.raised(0.022, 0.130, 0.124, 0.198, 0.003, fill=(84, 96, 114))
    P.lcd(0.027, 0.135, 0.119, 0.193)
    data = (("118.700", "VHF1", "121.500"), ("124.350", "VHF2", "132.975"), ("DATA", "VHF3", "136.900"))
    for i, (act, nm, sby) in enumerate(data):
        yy = 0.183 - i * 0.0185
        P.lcd_text(0.031, yy, act, GREEN if i + 1 == n else WHITE, 2.6, "lm", mono=True)
        P.lcd_text(0.073, yy, nm, WHITE, 1.6)
        P.lcd_text(0.116, yy, sby, CYAN, 2.4, "rm", mono=True)
        P.key(0.012, yy, 0.0095, 0.0095, "", rnd=True, height=0.003)
        P.key(0.134, yy, 0.011, 0.0085, "", height=0.003)
    P.key(0.012, 0.126, 0.012, 0.010, "MSG\nCLR", mm=0.9)
    # audio: three rows of reception knobs with transmission keys, numeric keypad on the right
    names = (("VHF1", "VHF2", "VHF3"), ("HF1", "HF2", "TEL1"), ("INT", "CAB", "PA"))
    for r, rown in enumerate(names):
        for c, t in enumerate(rown):
            x, y = 0.020 + c * 0.0225, 0.104 - r * 0.031
            P.label(x, y + 0.0125, t, 1.1)
            P.knob(x, y, 0.0068, height=0.015, white=False, skirt=False)
    for i, t in enumerate(("1", "2", "3", "4", "5", "6", "7", "8", "9", ".", "0", "CLR")):
        P.key(0.090 + (i % 3) * 0.0138, 0.112 - (i // 3) * 0.0136, 0.0105, 0.0105, t, mm=1.3, rnd=True)
    P.key(0.135, 0.098, 0.013, 0.010, "LOAD", mm=1.0)
    P.key(0.135, 0.062, 0.013, 0.010, "VOICE", mm=0.9)
    P.knob(0.096, 0.046, 0.0068, height=0.015, white=False, skirt=False)
    P.knob(0.118, 0.046, 0.0068, height=0.015, white=False, skirt=False)
    P.toggle(0.024, 0.014, pos=((0, "RAD"),), mm=1.1, tilt=0)
    P.raised(0.058, 0.007, 0.086, 0.021, 0.008, fill=(170, 174, 180))
    P.label(0.100, 0.014, "STBY\nRAD NAV", 1.0, anchor="lm")
    P.knob(0.130, 0.018, 0.0068, height=0.015, white=False, skirt=False)
    P.screws(0.005)
    return P


def thrust_plate():
    P = Panel("THRUST_LEVER_BASE", 0.150, 0.270)
    P.screws(0.007)
    return P


def eng_ecp():
    """Engine master / start panel above the ECAM control panel (pedestal centre column)."""
    P = Panel("ENG_MASTER_ECAM_CP", 0.185, 0.220)
    for x, n in ((0.042, "1"), (0.143, "2")):
        P.d.rectangle([P.p(x - 0.008, 0.200), P.p(x + 0.008, 0.170)], fill=(14, 14, 15))
        P.geo.append(("master", x, 0.183, n))
        P.label(x - 0.016, 0.196, "ON", 1.4)
        P.label(x - 0.016, 0.172, "OFF", 1.4)
    P.label(0.0925, 0.206, "ENG START", 1.6)
    P.knob(0.0925, 0.180, 0.0095, height=0.018, marks=((-55, "CRANK"), (0, "NORM"), (55, "IGN\nSTART")), mm=1.2)
    P.pb(0.118, 0.156, "", "", 0.010, w=0.016, cover=GUARD_RED, height=0.003)
    P.line(0.010, 0.148, 0.175, 0.148)
    P.key(0.022, 0.134, 0.014, 0.014, "✓", mm=2.2, rnd=True, height=0.004)
    P.key(0.163, 0.134, 0.014, 0.014, "✓", mm=2.2, rnd=True, height=0.004)
    P.key(0.060, 0.136, 0.019, 0.010, "T.O\nCONFIG", mm=1.0)
    P.key(0.060, 0.120, 0.019, 0.010, "RCL\nLAST", mm=1.0)
    P.key(0.088, 0.128, 0.019, 0.010, "DEFRD", mm=1.0)
    P.key(0.110, 0.128, 0.019, 0.010, "ABN", mm=1.1)
    P.key(0.134, 0.122, 0.019, 0.010, "RCL\nALL", mm=1.0)
    P.rocker(0.022, 0.102, 0.012, 0.028)
    P.rocker(0.163, 0.102, 0.012, 0.028)
    for i, t in enumerate(("DISPCH", "STS", "MORE")):
        P.key(0.075 + i * 0.0225, 0.102, 0.019, 0.010, t, mm=1.0)
    for i, t in enumerate(("ENG", "DOOR", "WHEEL", "FUEL")):
        P.key(0.064 + i * 0.0225, 0.083, 0.019, 0.010, t, mm=1.1)
    for i, t in enumerate(("EL/AC", "EL/DC", "HYD", "F/CTL")):
        P.key(0.064 + i * 0.0225, 0.064, 0.019, 0.010, t, mm=1.1)
    for i, t in enumerate(("ALL", "APU", "BLEED", "COND", "PRESS")):
        P.key(0.044 + i * 0.0225, 0.045, 0.019, 0.010, t, mm=1.1)
    P.knob(0.030, 0.068, 0.0085, height=0.014)
    P.knob(0.158, 0.076, 0.0080, height=0.026)
    P.key(0.160, 0.048, 0.019, 0.010, "CLEAR", mm=1.0)
    P.label(0.0925, 0.014, "ECAM", 1.8)
    P.screws(0.006)
    return P


def spd_brk():
    P = Panel("SPEED_BRAKE", 0.146, 0.160)
    P.slot(0.090, 0.022, 0.106, 0.128)
    P.d.rectangle([P.p(0.074, 0.146), P.p(0.122, 0.136)], outline=LEGEND)
    P.label(0.098, 0.141, "GND SPLRS ARMED", 1.1)
    for yy, t in ((0.120, "RET"), (0.076, "1/2"), (0.030, "FULL")):
        P.label(0.078, yy, t, 1.6, anchor="rm")
        P.line(0.080, yy, 0.088, yy)
        P.label(0.118, yy, t, 1.6, anchor="lm")
        P.line(0.108, yy, 0.116, yy)
    P.line(0.086, 0.030, 0.086, 0.120)
    P.line(0.110, 0.030, 0.110, 0.120)
    P.label(0.038, 0.078, "SPEED\nBRAKE", 2.2)
    P.screws(0.007)
    return P


def surv():
    """TCAS / transponder / weather radar control panel."""
    P = Panel("SURV_TCAS", 0.185, 0.160)
    P.label(0.0925, 0.150, "TCAS", 1.9)
    for x, tag in ((0.028, "CAPT"), (0.157, "F/O")):
        for i in range(3):
            P.knob(x, 0.128 - i * 0.040, 0.0078, height=0.020, skirt=True)
        P.label(x + (0.016 if tag == "CAPT" else -0.016), 0.088, "\n".join(tag), 1.2)
    P.key(0.074, 0.130, 0.016, 0.009, "ABV", mm=1.1)
    P.key(0.074, 0.116, 0.016, 0.009, "BLW", mm=1.1, col=GREEN, lit=0.6)
    P.key(0.116, 0.130, 0.018, 0.009, "", mm=1.1)
    P.raised(0.080, 0.086, 0.106, 0.104, 0.004, fill=(90, 100, 116))
    P.label(0.093, 0.076, "WXR", 1.5)
    P.key(0.072, 0.060, 0.018, 0.009, "", mm=1.1)
    P.key(0.116, 0.064, 0.018, 0.009, "", mm=1.1, col=GREEN, lit=0.6)
    P.label(0.093, 0.046, "XPDR\nTCAS", 1.3)
    P.key(0.072, 0.034, 0.018, 0.009, "", mm=1.1)
    P.key(0.116, 0.036, 0.018, 0.009, "", mm=1.1, col=GREEN, lit=0.6)
    P.screws(0.006)
    return P


def flaps():
    P = Panel("FLAPS", 0.146, 0.160)
    for yy, t in ((0.124, "0"), (0.102, "1"), (0.080, "2"), (0.058, "3"), (0.034, "FULL")):
        P.label(0.036, yy, t, 1.8, anchor="rm")
        P.label(0.096, yy, t, 1.8, anchor="lm")
    P.label(0.122, 0.090, "FLAPS", 2.0)
    P.geo.append(("flapguide", 0.066, 0.080))
    P.d.rectangle([P.p(0.040, 0.140), P.p(0.092, 0.020)], fill=(104, 119, 140))
    P.slot(0.060, 0.026, 0.072, 0.134)
    P.screws(0.007)
    return P


def park():
    P = Panel("PARK_BRK", 0.146, 0.125)
    P.label(0.060, 0.085, "PARK BRK", 2.0)
    P.label(0.070, 0.030, "ON", 1.5)
    P.geo.append(("parkbrk", 0.030, 0.060))
    P.d.rounded_rectangle([P.p(0.016, 0.100), P.p(0.052, 0.022)], radius=int(P.s(0.006)), fill=(16, 16, 18))
    P.rpb(0.110, 0.070, 0.0045, "ACCU\nREINFLATE", label_mm=1.2, label_dy=0.012)
    P.screws(0.007)
    return P


def trim():
    """Brake accumulator pressure gauge, pitch trim switch, rudder trim knob."""
    P = Panel("TRIM", 0.185, 0.125)
    cx, cy, r = 0.040, 0.072, 0.027
    P.d.ellipse([P.p(cx - r, cy + r), P.p(cx + r, cy - r)], fill=(10, 10, 11), outline=(60, 66, 76),
                width=max(2, int(P.s(0.001))))
    P.label(cx, cy + 0.015, "YELLOW", 1.4, col=(240, 220, 60), lit=0.3)
    P.label(cx, cy - 0.016, "GREEN", 1.4, col=(110, 230, 120), lit=0.3)
    P.label(cx - 0.014, cy, "ACCU", 1.2)
    P.label(cx + 0.014, cy, "PRESS", 1.2)
    P.geo.append(("cyl", cx, cy, r, 0.0, 0.003, 32))
    P.label(0.118, 0.116, "PITCH TRIM", 1.8)
    P.rocker(0.108, 0.094, 0.030, 0.024, height=0.012)
    P.label(0.150, 0.102, "NOSE DN", 1.3)
    P.label(0.150, 0.086, "NOSE UP", 1.3)
    P.line(0.076, 0.074, 0.178, 0.074)
    P.label(0.118, 0.066, "RUDDER TRIM", 1.8)
    P.geo.append(("rudtrim", 0.118, 0.034))
    P.d.ellipse([P.p(0.118 - 0.019, 0.034 + 0.019), P.p(0.118 + 0.019, 0.034 - 0.019)], fill=KNOB_W,
                outline=(110, 114, 120))
    P.label(0.084, 0.040, "NOSE\nL", 1.2)
    P.label(0.150, 0.048, "NOSE\nR", 1.2)
    P.rpb(0.164, 0.026, 0.0045, "RESET", label_mm=1.3)
    P.screws(0.006)
    return P


def lg_gravity():
    P = Panel("LG_GRVTY_EXTN", 0.146, 0.140)
    P.label(0.060, 0.128, "L/G GRVTY EXTN", 1.9)
    P.hazard(0.020, 0.026, 0.112, 0.116)
    P.geo.append(("box", 0.066, 0.071, 0.092, 0.090, 0.0, 0.004))
    P.d.rounded_rectangle([P.p(0.036, 0.104), P.p(0.096, 0.050)], radius=int(P.s(0.004)), fill=(176, 180, 186),
                          outline=(90, 94, 100))
    P.geo.append(("box", 0.066, 0.077, 0.060, 0.054, 0.0, 0.022))
    for i, t in enumerate(("RESET", "OFF", "DOWN")):
        P.label(0.116, 0.100 - i * 0.028, t, 1.3, anchor="lm")
    P.screws(0.007)
    return P


def ckpt_lt():
    """Cockpit lighting knobs and the cockpit door switch."""
    P = Panel("CKPT_LT_DOOR", 0.185, 0.140)
    P.label(0.062, 0.132, "CKPT LT", 1.9)
    P.knob(0.028, 0.104, 0.0085, "FLOOD", height=0.020, marks=((-60, "OFF"), (60, "BRT")), mm=1.1, label_mm=1.2)
    P.knob(0.090, 0.108, 0.0085, "INTEG", height=0.020, marks=((-60, "OFF"), (60, "BRT")), mm=1.1, label_mm=1.2)
    P.knob(0.050, 0.046, 0.0085, "STORM", height=0.020, marks=((-60, "OFF"), (60, "BRT")), mm=1.1, label_mm=1.2)
    P.knob(0.104, 0.060, 0.0085, "DU", height=0.026, marks=((-60, "OFF"), (60, "MAX")), mm=1.1, label_mm=1.2)
    P.line(0.128, 0.010, 0.128, 0.118)
    P.label(0.156, 0.112, "CKPT DOOR", 1.6)
    P.toggle(0.160, 0.074, pos=((1.5, "UNLOCK"), (0, "NORM"), (-1.5, "LOCK")), mm=1.0, tilt=0)
    P.annun(0.150, 0.034, 0.022, 0.012, "OPEN", RED, True, 1.3)
    P.screws(0.006)
    return P


def printer():
    P = Panel("PRINTER", 0.331, 0.150)
    for i, t in enumerate(("ABORT", "SLEW", "TEST", "STATUS")):
        P.key(0.120 + i * 0.030, 0.134, 0.020, 0.011, t, mm=1.1, height=0.004)
    P.raised(0.020, 0.012, 0.311, 0.118, 0.003)
    P.slot(0.040, 0.100, 0.290, 0.107)
    P.screws(0.007)
    return P


def blank(name, w, h):
    P = Panel(name, w, h)
    P.screws(0.007)
    return P


# ==========================================================================
# Overhead panel: three columns, forward edge at y = 0
# ==========================================================================
OVH_LEN = 1.040


def _sec(P, title, x0, y0, x1, y1):
    P.frame(x0, y0, x1, y1 - 0.004, title)
    return x0 + 0.004, x1 - 0.004


def overhead_centre():
    P = Panel("OVERHEAD_CENTRE", 0.340, OVH_LEN, ppm=3600)
    X0, X1 = 0.006, 0.334

    def pbf(top="FAULT", bot="OFF", **kw):
        return lambda x, y, lab: P.pb(x, y, top, bot, label=lab, **kw)

    # R1: exterior lights | APU | interior lights | signs
    a, b = _sec(P, "EXT LT", X0, 0.006, 0.150, 0.118)
    for i, (lab, pos) in enumerate((("STROBE", ("ON", "AUTO", "OFF")), ("BEACON", ("ON", "", "OFF")),
                                    ("NAV", ("1", "2", "OFF")), ("LOGO", ("ON", "AUTO", "OFF")))):
        P.toggle(a + (b - a) * (i + 0.5) / 4 - 0.004, 0.084, lab, pos=((1.4, pos[0]), (0, pos[1]), (-1.4, pos[2])),
                 mm=1.1, label_mm=1.3)
    for i, (lab, pos, pad) in enumerate((("WING", ("ON", "", "OFF"), False), ("RWY\nTURN OFF", ("ON", "", "OFF"), False),
                                         ("LAND", ("ON", "", "OFF"), True), ("NOSE", ("T.O", "TAXI", "OFF"), False))):
        P.toggle(a + (b - a) * (i + 0.5) / 4 - 0.004, 0.034, lab, pos=((1.4, pos[0]), (0, pos[1]), (-1.4, pos[2])),
                 mm=1.1, label_mm=1.3, paddle=pad, label_dy=0.014)
    a, b = _sec(P, "APU", 0.156, 0.006, 0.196, 0.118)
    P.pb((a + b) / 2, 0.082, "FAULT", "ON", 0.017, bot_col=BLUE, label="MASTER SW", label_mm=1.2, mm=1.4)
    P.pb((a + b) / 2, 0.036, "AVAIL", "ON", 0.017, top_col=GREEN, bot_col=BLUE, label="START", label_mm=1.2, mm=1.4)
    a, b = _sec(P, "INT LT", 0.202, 0.064, X1, 0.118)
    for i, (lab, pos) in enumerate((("STBY\nCOMPASS", ("ON", "", "OFF")), ("ICE IND", ("ON", "", "OFF")),
                                    ("ANN LT", ("TEST", "BRT", "DIM")), ("DOME", ("BRT", "DIM", "OFF")))):
        P.toggle(a + (b - a) * (i + 0.5) / 4 - 0.004, 0.084, lab, pos=((1.4, pos[0]), (0, pos[1]), (-1.4, pos[2])),
                 mm=1.0, label_mm=1.1, label_dy=0.013)
    a, b = _sec(P, "SIGNS", 0.202, 0.006, X1, 0.060)
    for i, (lab, pos) in enumerate((("SEAT BELTS", ("ON", "AUTO", "OFF")), ("NO PED", ("ON", "AUTO", "OFF")),
                                    ("EMER\nEXIT LT", ("ON", "ARM", "OFF")))):
        P.toggle(a + (b - a) * (i + 0.5) / 3 - 0.004, 0.028, lab, pos=((1.4, pos[0]), (0, pos[1]), (-1.4, pos[2])),
                 mm=1.0, label_mm=1.1, label_dy=0.013)

    # R2: anti ice | cabin press
    a, b = _sec(P, "ANTI ICE", X0, 0.124, 0.176, 0.204)
    P.row(0.156, a, b, ["WING", "ENG 1", "ENG 2", None, "PROBE &\nWINDOW HEAT"], lambda x, y, lab: P.pb(
        x, y, "FAULT", "ON", bot_col=BLUE, lit=(False, lab.startswith("ENG")), label=lab, label_mm=1.4, w=0.024,
        size=0.015))
    a, b = _sec(P, "CABIN PRESS", 0.182, 0.124, X1, 0.204)
    P.knob(a + 0.016, 0.158, 0.0085, height=0.022, marks=((-60, "DEC"), (60, "INC")), mm=1.1)
    P.pb(a + 0.046, 0.156, "FAULT", "MAN", 0.015, label="MODE", label_mm=1.3, w=0.020)
    P.label(a + 0.030, 0.186, "CABIN ALT", 1.3)
    P.pb(a + 0.078, 0.156, "FAULT", "MAN", 0.015, label="MODE", label_mm=1.3, w=0.020)
    P.knob(a + 0.106, 0.158, 0.0085, height=0.022, marks=((-60, "DN"), (60, "UP")), mm=1.1)
    P.label(a + 0.092, 0.186, "CABIN V/S", 1.3)
    P.pb(b - 0.014, 0.150, "", "ON", 0.015, bot_col=BLUE, label="DITCHING", label_mm=1.2, cover=GUARD_BLK, w=0.020)

    # R3: air
    a, b = _sec(P, "AIR", X0, 0.210, X1, 0.376)
    P.flow([(0.062, 0.262), (0.062, 0.300), (0.280, 0.300), (0.280, 0.262)])
    P.flow([(0.150, 0.262), (0.150, 0.300)])
    P.pb(0.030, 0.316, "FAULT", "ON", 0.016, bot_col=BLUE, label="CKPT\nHI VENT", label_mm=1.2, w=0.024)
    P.pb(0.078, 0.344, "FAULT", "OFF", 0.016, label="PACK 1", label_mm=1.4, w=0.024)
    P.knob(0.120, 0.330, 0.0105, height=0.026, marks=((-90, "MAN"), (-50, "LO"), (0, "NORM"), (50, "HI")), mm=1.1)
    P.label(0.120, 0.362, "AIR FLOW", 1.3)
    P.knob(0.172, 0.334, 0.0095, height=0.024, marks=((-60, "COLD"), (60, "HOT")), mm=1.1)
    P.label(0.172, 0.362, "COCKPIT", 1.3)
    P.knob(0.224, 0.334, 0.0095, height=0.024, marks=((-60, "COLD"), (60, "HOT")), mm=1.1)
    P.label(0.224, 0.362, "CABIN", 1.3)
    P.pb(0.268, 0.344, "FAULT", "OFF", 0.016, label="PACK 2", label_mm=1.4, w=0.024)
    P.pb(0.310, 0.316, "FAULT", "ON", 0.016, bot_col=BLUE, label="WINDSHIELD\nDEFOG", label_mm=1.1, w=0.024)
    P.pb(0.062, 0.244, "FAULT", "OFF", 0.016, label="ENG 1 BLEED", label_mm=1.2, w=0.024)
    P.pb(0.106, 0.268, "FAULT", "OFF", 0.014, label="HOT AIR 1", label_mm=1.1, w=0.022)
    P.pb(0.150, 0.244, "FAULT", "ON", 0.016, bot_col=BLUE, label="APU BLEED", label_mm=1.2, w=0.024)
    P.knob(0.196, 0.262, 0.0095, height=0.024, marks=((-60, "CLOSE"), (0, "AUTO"), (60, "OPEN")), mm=1.1)
    P.label(0.196, 0.290, "XBLEED", 1.3)
    P.pb(0.240, 0.268, "FAULT", "OFF", 0.014, label="HOT AIR 2", label_mm=1.1, w=0.022)
    P.pb(0.280, 0.244, "FAULT", "OFF", 0.016, label="ENG 2 BLEED", label_mm=1.2, w=0.024)
    P.pb(0.318, 0.250, "", "ON", 0.015, bot_col=BLUE, label="RAM AIR", label_mm=1.2, cover=GUARD_BLK, w=0.020)

    # R4: elec
    a, b = _sec(P, "ELEC", X0, 0.382, X1, 0.552)
    names = ["BAT 1", "BAT\nEMER 1", "BAT\nEMER 2", "BAT 2", "SIDE 1&2\nISOL", "ELM", "PAX SYS", "GALLEY",
             "COMMER-\nCIAL 1", "COMMER-\nCIAL 2"]
    P.row(0.518, a, b, names, lambda x, y, lab: P.pb(x, y, "FAULT", "OFF", 0.016, label=lab, label_mm=1.1, w=0.024,
                                                     mm=1.4))
    for x, t in ((0.060, "AC 1A BUS"), (0.128, "AC 1B BUS"), (0.224, "AC 2B BUS"), (0.292, "AC 2A BUS")):
        P.d.rectangle([P.p(x - 0.022, 0.492), P.p(x + 0.022, 0.484)], outline=LEGEND)
        P.label(x, 0.488, t, 1.2)
        P.flow([(x, 0.484), (x, 0.470)])
    P.flow([(0.036, 0.470), (0.144, 0.470)])
    P.flow([(0.208, 0.470), (0.316, 0.470)])
    P.pb(0.176, 0.474, "", "OFF", 0.015, label="BUS TIE", label_mm=1.2, w=0.022)
    gens = ((0.036, "1A", True), (0.108, "1B", True), (0.244, "2B", False), (0.316, "2A", False))
    for x, n, left in gens:
        dx = 0.0 if left else 0.0
        P.pb(x + dx - 0.010, 0.426, "", "", 0.015, w=0.018, cover=GUARD_RED, label="DRIVE", label_mm=1.1)
        P.pb(x + dx + 0.014, 0.426, "FAULT", "OFF", 0.015, label="GEN " + n, label_mm=1.1, w=0.020, lit=(True, False),
             mm=1.3)
        P.flow([(x, 0.470), (x, 0.446)])
    for x, t in ((0.074, "EXT 1"), (0.280, "EXT 2")):
        P.pb(x, 0.408, "AVAIL", "AUTO", 0.015, top_col=GREEN, bot_col=BLUE, label=t, label_mm=1.2, w=0.022,
             lit=(False, True), mm=1.3)
        P.flow([(x, 0.470), (x, 0.428)])
    P.pb(0.176, 0.414, "FAULT", "OFF", 0.015, label="APU GEN", label_mm=1.2, w=0.022, mm=1.3)
    P.flow([(0.144, 0.470), (0.160, 0.474)])
    P.flow([(0.192, 0.474), (0.208, 0.470)])

    # R5: fuel
    a, b = _sec(P, "FUEL", X0, 0.558, X1, 0.716)
    P.flow([(0.046, 0.604), (0.046, 0.650), (0.294, 0.650), (0.294, 0.604)])
    P.flow([(0.170, 0.650), (0.170, 0.620)])
    P.row(0.682, a, b, ["L TK\nPUMP 1", "L TK\nPUMP 2", "CTR TK\nPUMP L", "X FEED", "CTR TK\nPUMP R", "R TK\nPUMP 1",
                        "R TK\nPUMP 2"],
          lambda x, y, lab: P.pb(x, y, "OPEN" if lab == "X FEED" else "FAULT", "ON" if lab == "X FEED" else "OFF",
                                 0.016, top_col=GREEN if lab == "X FEED" else AMBER,
                                 bot_col=BLUE if lab == "X FEED" else LEGEND, label=lab, label_mm=1.1, w=0.024, mm=1.4))
    P.row(0.596, a, b, ["L STBY\nPUMP", "L INR TK\nXFR", None, "JETTISON\nARM", "JETTISON\nACTIVE", None,
                        "R INR TK\nXFR", "R STBY\nPUMP"],
          lambda x, y, lab: P.pb(x, y, "" if "JETT" in lab else "FAULT", "ON" if "JETT" in lab else "OFF", 0.016,
                                 bot_col=BLUE if "JETT" in lab else LEGEND, label=lab, label_mm=1.1, w=0.022,
                                 cover=GUARD_RED if "JETT" in lab else None, mm=1.4))

    # R6: hyd -- four guarded engine-driven pumps, GREEN and YELLOW on each engine
    a, b = _sec(P, "HYD", X0, 0.722, X1, 0.812)
    for x, lab, col in ((0.060, "GREEN", (120, 235, 130)), (0.124, "YELLOW", (240, 222, 90)),
                        (0.216, "GREEN", (120, 235, 130)), (0.280, "YELLOW", (240, 222, 90))):
        P.d.rectangle([P.p(x - 0.020, 0.800), P.p(x + 0.020, 0.790)], outline=col, width=3)
        P.label(x, 0.795, lab, 1.2, col=col)
        P.pb(x, 0.754, "FAULT", "OFF", 0.015, label="PUMP", label_mm=1.1, w=0.024, mm=1.3, cover=GUARD_RED)
    P.label(0.092, 0.806, "ENG 1", 1.2)
    P.label(0.248, 0.806, "ENG 2", 1.2)
    P.pb(0.170, 0.760, "FAULT", "ON", 0.015, bot_col=BLUE, label="ELEC PUMPS", label_mm=1.1, w=0.022, mm=1.3)

    # R7: fire
    a, b = _sec(P, "FIRE", X0, 0.818, X1, 0.930)
    for x, lab in ((0.062, "ENG 1"), (0.170, "APU"), (0.278, "ENG 2")):
        P.label(x, 0.918, lab, 1.9)
        P.pb(x, 0.892, "FIRE", "PUSH", 0.022, top_col=RED, bot_col=RED, cover=GUARD_RED, mm=1.7, height=0.006, w=0.050)
        if lab == "APU":
            P.pb(x + 0.022, 0.846, "SQUIB", "DISCH", 0.014, top_col=LEGEND, bot_col=AMBER, label="AGENT", mm=1.0,
                 label_mm=1.1, w=0.020)
        else:
            for dx, n in ((-0.016, "1"), (0.016, "2")):
                P.pb(x + dx, 0.846, "SQUIB", "DISCH", 0.014, top_col=LEGEND, bot_col=AMBER, label="AGENT " + n,
                     mm=1.0, label_mm=1.1, w=0.020)
    P.rpb(0.118, 0.850, 0.0040, "FIRE\nTEST", label_mm=1.0, label_dy=0.010)
    # blank plate with the stowage hook, then the aft maintenance row
    P.raised(0.150, 0.940, 0.190, 0.962, 0.016, fill=(16, 16, 18))
    a, b = _sec(P, "", X0, 0.968, X1, 1.034)
    P.label(0.050, 1.022, "ENG", 1.4)
    for x, n in ((0.034, "FADEC GND\nPWR 1"), (0.070, "FADEC GND\nPWR 2")):
        P.pb(x, 0.992, "", "ON", 0.013, bot_col=BLUE, label=n, label_mm=0.9, cover=GUARD_BLK, w=0.018)
    P.pb(0.116, 0.992, "", "ON", 0.013, bot_col=BLUE, label="REFUEL ON\nBATTERIES", label_mm=0.9, cover=GUARD_BLK,
         w=0.018)
    P.pb(0.158, 0.992, "FAULT", "OFF", 0.013, label="CKPT DOOR\nLKG SYS", label_mm=0.9, cover=GUARD_BLK, w=0.018)
    P.pb(0.200, 0.992, "", "", 0.013, label="APU\nAUTO EXTING", label_mm=0.9, w=0.018)
    P.knob(0.250, 0.996, 0.0075, height=0.018, mm=1.0)
    P.lcd(0.272, 0.986, 0.304, 1.006)
    P.pb(0.320, 0.996, "", "", 0.012, w=0.014)
    P.screws(0.006)
    return P


def _cb_panels(P, x0, x1, y0, title):
    """Row of equipment power-supply breakers, then the grid of reset breakers behind it."""
    P.frame(x0, y0, x1, y0 + 0.040, title, mm=1.3)
    for i in range(6):
        P.rpb(x0 + (x1 - x0) * (i + 0.5) / 6, y0 + 0.016, 0.0046, "ABCDEF"[i], height=0.007, label_mm=1.0,
              label_dy=-0.010)
    y1 = y0 + 0.046
    P.frame(x0, y1, x1, 1.034 - 0.004, "RESET", mm=1.3)
    rows = int((1.030 - y1 - 0.012) / 0.021)
    for j in range(rows):
        for i in range(6):
            P.rpb(x0 + (x1 - x0) * (i + 0.5 + (0.25 if j % 2 else -0.25) * 0.5) / 6, y1 + 0.016 + j * 0.021, 0.0052,
                  height=0.008)


def overhead_left():
    P = Panel("OVERHEAD_LEFT", 0.220, OVH_LEN, ppm=3600)
    X0, X1 = 0.006, 0.214
    a, b = _sec(P, "WIPER", X0, 0.006, X1, 0.090)
    P.knob(0.110, 0.044, 0.0105, height=0.026, pointer=-10, mm=1.1,
           marks=((-100, "INTMT\nMEDIUM"), (-55, "INTMT\nFAST"), (-10, "OFF"), (40, "SLOW"), (85, "FAST")))
    P.rpb(0.184, 0.046, 0.0042, "RAIN\nRPLNT", label_mm=1.1, label_dy=0.011)

    a, b = _sec(P, "CALLS", X0, 0.096, X1, 0.200)
    P.rpb(0.036, 0.164, 0.0050, "MECH CALL", label_mm=1.2)
    P.row(0.150, 0.060, b, ["PURS", "FLT REST", "ALL", "CAB REST"], lambda x, y, lab: P.rpb(x, y, 0.0045, lab,
                                                                                         label_mm=1.1))
    P.pb(b - 0.014, 0.176, "", "ON", 0.013, label="EMER", label_mm=1.2, cover=GUARD_BLK, w=0.018)
    P.row(0.118, 0.060, b, ["FWD", "MID", "EXIT", "AFT"], lambda x, y, lab: P.rpb(x, y, 0.0045, lab, label_mm=1.1))

    a, b = _sec(P, "EVAC", X0, 0.206, X1, 0.280)
    P.pb(0.050, 0.236, "EVAC", "ON", 0.015, top_col=RED, cover=GUARD_RED, label="COMMAND", label_mm=1.2, w=0.022)
    P.rpb(0.116, 0.240, 0.0045, "HORN OFF", label_mm=1.2)
    P.toggle(0.170, 0.238, pos=((1.3, "CAPT &\nPURS"), (-1.3, "CAPT")), mm=1.0, tilt=14)

    a, b = _sec(P, "OXYGEN", X0, 0.286, X1, 0.366)
    P.pb(0.050, 0.320, "", "AUTO", 0.015, cover=GUARD_RED, label="MASK MAN ON", label_mm=1.2, w=0.022)
    P.pb(0.112, 0.320, "", "OFF", 0.015, label="PAX", label_mm=1.3, w=0.024)
    P.pb(0.172, 0.320, "", "OFF", 0.015, label="CREW\nSUPPLY", label_mm=1.2, w=0.024)

    a, b = _sec(P, "RCDR", X0, 0.372, X1, 0.446)
    P.rpb(0.040, 0.400, 0.0048, "ACMS\nTRIGGER", label_mm=1.2, label_dy=0.012)
    P.rpb(0.096, 0.400, 0.0048, "DFDR\nEVENT", label_mm=1.2, label_dy=0.012)
    P.pb(0.166, 0.402, "", "ON", 0.015, bot_col=BLUE, label="GND CTL", label_mm=1.2, w=0.024)

    a, b = _sec(P, "ELT", X0, 0.452, 0.086, 0.556)
    P.geo.append(("guardtoggle", 0.046, 0.496))
    P.d.rounded_rectangle([P.p(0.030, 0.520), P.p(0.062, 0.478)], radius=int(P.s(0.003)), fill=GUARD_RED)
    P.label(0.046, 0.532, "ON", 1.2)
    P.label(0.072, 0.504, "ARMED", 1.0)
    P.label(0.072, 0.482, "RESET", 1.0)
    a, b = _sec(P, "EMER ELEC PWR", 0.092, 0.452, X1, 0.556)
    P.pb(0.124, 0.492, "FAULT", "OFF", 0.016, label="EMER GEN", label_mm=1.2, w=0.026)
    P.pb(0.176, 0.492, "", "AUTO", 0.016, cover=GUARD_RED, label="RAT MAN ON", label_mm=1.2, w=0.022)

    a, b = _sec(P, "F/CTL", X0, 0.562, X1, 0.640)
    P.row(0.594, a, b, ["PRIM 1", "SEC 1", None, "PRIM 3", "SEC 3"], lambda x, y, lab: P.pb(
        x, y, "FAULT", "OFF", 0.014, label=lab, label_mm=1.2, w=0.020, cover=GUARD_BLK, mm=1.2))
    a, b = _sec(P, "ADIRS", X0, 0.646, X1, 0.776)
    for i, n in enumerate(("1", "3", "2")):
        cx = a + (b - a) * (i + 0.5) / 3
        P.pb(cx, 0.744, "FAULT", "OFF", 0.014, label="IR " + n, label_mm=1.2, w=0.022, mm=1.2)
        P.knob(cx, 0.690, 0.0095, height=0.024, pointer=0, marks=((-55, "OFF"), (0, "NAV"), (55, "ATT")), mm=1.0)
    a, b = _sec(P, "CABIN", X0, 0.782, X1, 0.872)
    for i, n in enumerate(("PAX PERS\nELEC SPLY", "LAVATORY &\nGALLEY", "WIRELESS\nCOM", "CAB LIGHTS")):
        P.pb(a + (b - a) * (0.32 + 0.36 * (i % 2)), 0.846 - 0.040 * (i // 2), "", "OFF", 0.013, label=n,
             label_mm=0.9, w=0.020, mm=1.1)
    _cb_panels(P, X0, X1, 0.878, "CAPT EQPT POWER SUPPLY")
    P.screws(0.006)
    return P


def overhead_right():
    P = Panel("OVERHEAD_RIGHT", 0.220, OVH_LEN, ppm=3600)
    X0, X1 = 0.006, 0.214
    a, b = _sec(P, "WIPER", X0, 0.006, X1, 0.090)
    P.rpb(0.036, 0.046, 0.0042, "RAIN\nRPLNT", label_mm=1.1, label_dy=0.011)
    P.knob(0.110, 0.044, 0.0105, height=0.026, pointer=-10, mm=1.1,
           marks=((-100, "INTMT\nMEDIUM"), (-55, "INTMT\nFAST"), (-10, "OFF"), (40, "SLOW"), (85, "FAST")))

    a, b = _sec(P, "ENG", X0, 0.096, 0.110, 0.180)
    P.label(0.058, 0.158, "MAN START", 1.2)
    for x, n in ((0.040, "1"), (0.076, "2")):
        P.pb(x, 0.128, "", "ON", 0.014, bot_col=BLUE, label=n, label_mm=1.2, cover=GUARD_BLK, w=0.020)
    a, b = _sec(P, "CAB SYS SMOKE", 0.116, 0.096, X1, 0.180)
    P.pb(0.165, 0.130, "SMOKE", "OFF", 0.015, top_col=RED, label="IFEC", label_mm=1.2, w=0.024)

    a, b = _sec(P, "VENT", X0, 0.186, X1, 0.262)
    P.row(0.216, a, b, ["AVNC\nSMOKE", "AVNCS\nEXTRACT", "COOLG", "CAB FANS"], lambda x, y, lab: P.pb(
        x, y, "SMOKE" if "SMOKE" in lab else "FAULT", "" if "SMOKE" in lab else ("OVRD" if "EXT" in lab else "OFF"),
        0.015, top_col=RED if "SMOKE" in lab else AMBER, label=lab, label_mm=1.1, w=0.024, mm=1.3))

    a, b = _sec(P, "CARGO SMOKE", X0, 0.268, 0.160, 0.352)
    P.pb(0.034, 0.300, "SMOKE", "DISCH", 0.015, top_col=RED, bot_col=AMBER, cover=GUARD_RED, label="AGENT TO FWD",
         label_mm=1.1, w=0.022)
    P.annun(0.082, 0.302, 0.020, 0.012, "═", AMBER, False, 2.0)
    P.pb(0.128, 0.300, "SMOKE", "DISCH", 0.015, top_col=RED, bot_col=AMBER, cover=GUARD_RED, label="AGENT TO AFT",
         label_mm=1.1, w=0.022)
    a, b = _sec(P, "MLG BAY", 0.166, 0.268, X1, 0.352)
    P.pb(0.190, 0.300, "FIRE", "", 0.015, top_col=RED, label="", w=0.024)

    for x0, x1, nm in ((X0, 0.107, "FWD"), (0.113, X1, "BULK")):
        a, b = _sec(P, "CARGO " + nm, x0, 0.358, x1, 0.556)
        cx = (a + b) / 2
        P.pb(cx, 0.510, "FAULT", "OFF", 0.016, label="ISOL VALVES", label_mm=1.2, w=0.026)
        P.label(cx, 0.476, "TEMP REGUL", 1.2)
        P.knob(cx, 0.440, 0.0115, height=0.028, marks=((-110, "OFF"), (-60, "5"), (0, "15"), (60, "25")), mm=1.1)
        P.pb(cx, 0.390, "FAULT", "OFF", 0.016, label="HEATER", label_mm=1.2, w=0.026)

    a, b = _sec(P, "F/CTL", X0, 0.562, 0.104, 0.640)
    P.row(0.594, a, b, ["PRIM 2", "SEC 2"], lambda x, y, lab: P.pb(
        x, y, "FAULT", "OFF", 0.014, label=lab, label_mm=1.2, w=0.020, cover=GUARD_BLK, mm=1.2))
    a, b = _sec(P, "GND HYD", 0.110, 0.562, X1, 0.640)
    P.row(0.594, a, b, ["GREEN", "YELLOW"], lambda x, y, lab: P.pb(
        x, y, "", "ON", 0.014, bot_col=BLUE, label=lab, label_mm=1.2, w=0.022, cover=GUARD_BLK, mm=1.2))
    a, b = _sec(P, "LTG", X0, 0.646, X1, 0.712)
    P.row(0.672, a, b, ["AVNCS\nCOMPT", "WHEEL\nWELL", "SVCE INT\nOVRD"], lambda x, y, lab: P.pb(
        x, y, "", "ON", 0.013, bot_col=BLUE, label=lab, label_mm=1.0, w=0.022, mm=1.1))
    a, b = _sec(P, "SURV", X0, 0.718, X1, 0.790)
    P.row(0.746, a, b, ["TERR SYS", "GPWS\nG/S MODE"], lambda x, y, lab: P.pb(
        x, y, "FAULT", "OFF", 0.014, label=lab, label_mm=1.1, w=0.024, mm=1.2))
    a, b = _sec(P, "CVR", X0, 0.796, X1, 0.872)
    P.rpb(0.040, 0.830, 0.0040, "TEST", label_mm=1.1)
    P.d.rectangle([P.p(0.094, 0.848), P.p(0.126, 0.814)], fill=(176, 180, 186), outline=(80, 84, 90))
    P.geo.append(("box", 0.110, 0.831, 0.032, 0.034, 0.0, 0.004))
    P.rpb(0.110, 0.831, 0.0085, height=0.010, col=(40, 40, 44))
    P.rpb(0.180, 0.830, 0.0040, "ERASE", label_mm=1.1)
    _cb_panels(P, X0, X1, 0.878, "F/O EQPT POWER SUPPLY")
    P.screws(0.006)
    return P


# ==========================================================================
# Side walls
# ==========================================================================
def ois_side(side="L"):
    """Narrow panel outboard of each OIS display."""
    P = Panel("OIS_SIDE_PANEL_" + side, 0.070, 0.232)
    P.label(0.035, 0.218, "OIS", 1.6)
    P.knob(0.022, 0.190, 0.0075, height=0.016, mm=1.0)
    P.toggle(0.050, 0.190, mm=1.0)
    P.label(0.035, 0.160, "CONSOLE LT", 1.1)
    P.knob(0.022, 0.136, 0.0075, height=0.016, mm=1.0)
    P.pb(0.050, 0.136, "", "", 0.013, mm=1.0)
    P.label(0.035, 0.104, "PEDALS LT", 1.1)
    P.knob(0.035, 0.080, 0.0075, height=0.016, mm=1.0)
    P.toggle(0.035, 0.034, "OXY / MIC", mm=1.0, label_mm=1.1)
    P.screws(0.006)
    return P


def side_wall_panel():
    """Small two-knob panel on the console face beside the loudspeaker grille."""
    P = Panel("CONSOLE_AUDIO_PANEL", 0.060, 0.070)
    P.knob(0.030, 0.050, 0.0070, height=0.012)
    P.knob(0.030, 0.022, 0.0070, height=0.012)
    return P


def grille(name, w, h, pitch=0.0055, r=0.0013):
    """Perforated loudspeaker grille."""
    P = Panel(name, w, h, ppm=3000)
    j = 0
    y = pitch
    while y < h - pitch * 0.5:
        x = pitch + (pitch / 2 if j % 2 else 0)
        while x < w - pitch * 0.5:
            P.d.ellipse([P.p(x - r, y + r), P.p(x + r, y - r)], fill=(34, 40, 50))
            x += pitch
        y += pitch * 0.87
        j += 1
    return P


ALL = dict(afs=afs_cp, efis_l=lambda: efis_cp("L"), efis_r=lambda: efis_cp("R"), warn_l=lambda: warn_block("L"),
           warn_r=lambda: warn_block("R"), wingin_l=lambda: wing_inner("L"), wingin_r=lambda: wing_inner("R"),
           wingout_l=lambda: wing_outer("L"), wingout_r=lambda: wing_outer("R"),
           col_l=col_left, col_r=col_right, isis_l=lambda: isis_unit("L"), isis_r=lambda: isis_unit("R"),
           kccu_l=lambda: kccu("L"), kccu_r=lambda: kccu("R"), rmp1=lambda: rmp(1), rmp2=lambda: rmp(2),
           rmp3=lambda: rmp(3), thrust=thrust_plate, eng_ecp=eng_ecp, spdbrk=spd_brk, surv=surv, flaps=flaps,
           park=park, trim=trim, lg=lg_gravity, ckptlt=ckpt_lt, printer=printer,
           blank_r1=lambda: blank("BLANK_R1", 0.146, 0.065), sidewall=side_wall_panel, blank_r2=lambda: blank("BLANK_R2", 0.146, 0.150),
           ovhd_c=overhead_centre, ovhd_l=overhead_left, ovhd_r=overhead_right,
           oisside_l=lambda: ois_side("L"), oisside_r=lambda: ois_side("R"),
           grille=lambda: grille("SPEAKER_GRILLE", 0.16, 0.09))


if __name__ == "__main__":
    import os
    import sys
    out = sys.argv[1] if len(sys.argv) > 1 else "textures"
    os.makedirs(out, exist_ok=True)
    for k, fn in ALL.items():
        P = fn()
        P.img.save(os.path.join(out, "panel_%s.png" % k))
        P.emit.save(os.path.join(out, "panel_%s_emit.png" % k))
        print(k, P.W, P.H, len(P.geo))
