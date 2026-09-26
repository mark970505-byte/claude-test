#!/usr/bin/env python3
"""Render "UNBROKEN", a 2-minute English-language video about Chinese civilization.

The style follows a fast "blueprint montage": about 60 two-second shots of line-art
illustrations on aged parchment, a dark gold-glow palette for the night and space
chapters, headlines that land one word at a time, and a HUD with the chapter, the year,
a timeline and a Kardashev meter. The whole story is told in the first person ("WE ..."),
and a single motif opens and closes it: the glowing character 文 ("writing"), half of
文明, the Chinese word for civilization.

Everything is procedural. Shots are drawn with skia, the soundtrack is synthesized
with numpy, and ffmpeg (from imageio-ffmpeg) encodes the result.

    pip install skia-python numpy pillow imageio-ffmpeg
    python3 make_video_en.py             # full render -> output/chinese_civilization_en.mp4
    python3 make_video_en.py --stills    # contact sheets of every shot in output/
"""
import math
import os
import subprocess
import sys
import urllib.request
import wave
from multiprocessing import Pool

import imageio_ffmpeg
import numpy as np
import skia
from PIL import Image, ImageFilter

ROOT = os.path.dirname(os.path.abspath(__file__))
FONT_DIR = os.path.join(ROOT, "fonts")
OUT_DIR = os.path.join(ROOT, "output")
OUT_NAME = "chinese_civilization_en"
GF = "https://fonts.gstatic.com/s/"
FONTS = {
    # All SIL Open Font License, served by Google Fonts.
    "display": ("Cinzel-Black.ttf", GF + "cinzel/v26/8vIU7ww63mVu7gtR-kwKxNvkNOjw-n_gTYo.ttf"),
    "italic": ("EBGaramond-Italic.ttf", GF + "ebgaramond/v33/SlGFmQSNjdsmc35JDF1K5GRwUjcdlttVFm-rI7eOQI96.ttf"),
    "mono": ("IBMPlexMono-Medium.ttf", GF + "ibmplexmono/v20/-F6qfjptAgt5VM-kVkqdyU8n3twJ8lc.ttf"),
    "cjk": ("NotoSerifSC-Bold.ttf", GF + "notoserifsc/v35/H4cyBXePl9DZ0Xe7gG9cyOj7uK2-n-D2rd4FY7RlrCWv.ttf"),
    "brush": ("MaShanZheng.ttf", GF + "mashanzheng/v18/NaPecZTRCLxvwo41b4gvzkXaRMQ.ttf"),
}

W, H = 1280, 720
FPS = 30

PAL = {
    "paper": dict(ink=(40, 33, 27), fill=(227, 216, 193), hatch=(40, 33, 27), acc=(182, 36, 28),
                  text=(30, 25, 21), sub=(92, 80, 66), gold=(176, 128, 40), blue=(40, 70, 140), white=(246, 240, 226), dark=False),
    "dark": dict(ink=(228, 192, 114), fill=(15, 17, 25), hatch=(228, 192, 114), acc=(246, 122, 52),
                 text=(238, 230, 214), sub=(160, 148, 124), gold=(250, 212, 124), blue=(70, 140, 235), white=(246, 240, 226), dark=True),
}
BG_MODE = {"paper": "paper", "dark": "dark", "ember": "dark", "space": "dark"}


# ---------------------------------------------------------------------------
# Small math helpers
# ---------------------------------------------------------------------------
def clamp(x, a=0.0, b=1.0):
    return a if x < a else b if x > b else x


def lerp(a, b, t):
    return a + (b - a) * t


def ease(x):
    x = clamp(x)
    return x * x * (3 - 2 * x)


def eo(x):
    """Ease out cubic."""
    x = clamp(x)
    return 1 - (1 - x) ** 3


def seg(t, a, b):
    return clamp((t - a) / (b - a)) if b > a else float(t >= a)


def rnd(i, salt=0):
    """Deterministic hash noise in [0, 1)."""
    x = math.sin(i * 12.9898 + salt * 78.233) * 43758.5453
    return x - math.floor(x)


def mix(c1, c2, t):
    return tuple(int(lerp(a, b, t)) for a, b in zip(c1, c2))


# ---------------------------------------------------------------------------
# Fonts
# ---------------------------------------------------------------------------
def ensure_fonts():
    os.makedirs(FONT_DIR, exist_ok=True)
    for name, url in FONTS.values():
        path = os.path.join(FONT_DIR, name)
        if not os.path.exists(path) or os.path.getsize(path) < 20_000:
            print(f"downloading {name} ...")
            urllib.request.urlretrieve(url, path)


_TF = {}
_FONT = {}


def font(kind, size):
    key = (kind, round(size * 4))
    if key not in _FONT:
        if kind not in _TF:
            _TF[kind] = skia.Typeface.MakeFromFile(os.path.join(FONT_DIR, FONTS[kind][0]))
        f = skia.Font(_TF[kind], size)
        f.setEdging(skia.Font.Edging.kAntiAlias)
        f.setSubpixel(True)
        _FONT[key] = f
    return _FONT[key]


def is_cjk(ch):
    return ord(ch) >= 0x2E80


def has_glyph(kind, ch):
    font(kind, 12)
    return _TF[kind].unicharToGlyph(ord(ch)) != 0


# ---------------------------------------------------------------------------
# 3-D projection
# ---------------------------------------------------------------------------
class Cam:
    """A simple perspective camera: y is up, the camera orbits the target."""

    def __init__(self, yaw=30, pitch=20, dist=900, f=900, cx=640, cy=400, target=(0, 0, 0)):
        self.cyw, self.syw = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
        self.cp, self.sp = math.cos(math.radians(pitch)), math.sin(math.radians(pitch))
        self.dist, self.f, self.cx, self.cy, self.t = dist, f, cx, cy, target

    def p(self, x, y, z):
        x, y, z = x - self.t[0], y - self.t[1], z - self.t[2]
        x1 = x * self.cyw - z * self.syw
        z1 = x * self.syw + z * self.cyw
        y2 = y * self.cp + z1 * self.sp
        z2 = -y * self.sp + z1 * self.cp + self.dist
        s = self.f / max(z2, 1e-3)
        return (self.cx + x1 * s, self.cy - y2 * s, z2)

    def pp(self, pts):
        return [self.p(*v)[:2] for v in pts]


def face(pts, **kw):
    kw["pts"] = pts
    return kw


def box(x0, y0, z0, x1, y1, z1, **kw):
    v = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
         (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
    idx = [(0, 1, 2, 3), (5, 4, 7, 6), (4, 0, 3, 7), (1, 5, 6, 2), (3, 2, 6, 7), (4, 5, 1, 0)]
    shades = [0.0, 0.0, 0.12, 0.12, -0.04, 0.2]
    out = []
    for f, sh in zip(idx, shades):
        d = dict(kw)
        d["shade"] = d.get("shade", 0) + sh
        out.append(face([v[i] for i in f], **d))
    return out


def cyl(cx, cz, r, y0, y1, n=16, top=True, **kw):
    out = []
    for i in range(n):
        a0, a1 = 2 * math.pi * i / n, 2 * math.pi * (i + 1) / n
        p0 = (cx + r * math.cos(a0), cz + r * math.sin(a0))
        p1 = (cx + r * math.cos(a1), cz + r * math.sin(a1))
        d = dict(kw)
        d["shade"] = d.get("shade", 0) + 0.18 * (0.5 + 0.5 * math.cos(a0 + 0.6))
        out.append(face([(p0[0], y0, p0[1]), (p1[0], y0, p1[1]), (p1[0], y1, p1[1]), (p0[0], y1, p0[1])], **d))
    if top:
        out.append(face([(cx + r * math.cos(2 * math.pi * i / n), y1, cz + r * math.sin(2 * math.pi * i / n))
                         for i in range(n)], **kw))
    return out


# ---------------------------------------------------------------------------
# Drawing context
# ---------------------------------------------------------------------------
class Ctx:
    def __init__(self, canvas, mode, lt, dur, shot=None):
        self.c = canvas
        self.mode = mode
        self.pal = PAL[mode]
        self.dark = self.pal["dark"]
        self.lt, self.dur, self.shot = lt, dur, shot

    # -- colour & paint ------------------------------------------------------
    def rgb(self, col):
        return self.pal[col] if isinstance(col, str) else col

    def paint(self, col="ink", a=1.0, w=1.3, fill=False, blur=0.0, add=False, cap=True):
        r, g, b = self.rgb(col)
        p = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(int(255 * clamp(a)), r, g, b))
        if fill:
            p.setStyle(skia.Paint.kFill_Style)
        else:
            p.setStyle(skia.Paint.kStroke_Style)
            p.setStrokeWidth(w)
            if cap:
                p.setStrokeCap(skia.Paint.kRound_Cap)
                p.setStrokeJoin(skia.Paint.kRound_Join)
        if blur > 0:
            p.setMaskFilter(skia.MaskFilter.MakeBlur(skia.kNormal_BlurStyle, blur))
        if add:
            p.setBlendMode(skia.BlendMode.kPlus if self.dark else skia.BlendMode.kMultiply)
        return p

    @staticmethod
    def path(pts, closed=False):
        p = skia.Path()
        if not pts:
            return p
        p.moveTo(*pts[0])
        for q in pts[1:]:
            p.lineTo(*q)
        if closed:
            p.close()
        return p

    # -- primitives ------------------------------------------------------------
    def line(self, pts, col="ink", a=1.0, w=1.3, prog=1.0, closed=False, blur=0.0, add=False, dash=None):
        if a <= 0.003 or prog <= 0 or len(pts) < 2:
            return
        pts = list(pts)
        if closed:
            pts = pts + [pts[0]]
        if prog < 1:
            pts = trim(pts, prog)
        p = self.paint(col, a, w, blur=blur, add=add)
        if dash:
            p.setPathEffect(skia.DashPathEffect.Make(dash, 0))
        self.c.drawPath(self.path(pts), p)

    def poly(self, pts, fill="fill", fa=1.0, stroke="ink", sa=1.0, w=1.3, hatch=None, shade=0.0):
        if len(pts) < 3:
            return
        path = self.path(pts, True)
        if fill is not None and fa > 0:
            col = self.rgb(fill)
            if shade:
                col = mix(col, self.pal["ink"] if not self.dark else (0, 0, 0), clamp(shade * (1.0 if not self.dark else 1.6), 0, 1)) \
                    if shade > 0 else mix(col, (255, 255, 255), -shade)
            self.c.drawPath(path, self.paint(col, fa, fill=True))
        if hatch:
            self.hatch_path(path, **hatch)
        if stroke is not None and sa > 0:
            self.c.drawPath(path, self.paint(stroke, sa, w))

    def hatch_path(self, path, gap=5.0, ang=45, col="hatch", a=0.45, w=0.7):
        b = path.getBounds()
        self.c.save()
        self.c.clipPath(path, doAntiAlias=True)
        cx, cy = b.centerX(), b.centerY()
        R = math.hypot(b.width(), b.height()) / 2 + 2
        ca, sa = math.cos(math.radians(ang)), math.sin(math.radians(ang))
        p = self.paint(col, a, w, cap=False)
        n = int(2 * R / gap) + 1
        pth = skia.Path()
        for i in range(n):
            o = -R + i * gap
            x0, y0 = cx + o * -sa - R * ca, cy + o * ca - R * sa
            x1, y1 = cx + o * -sa + R * ca, cy + o * ca + R * sa
            pth.moveTo(x0, y0)
            pth.lineTo(x1, y1)
        self.c.drawPath(pth, p)
        self.c.restore()

    def circle(self, x, y, r, fill=None, fa=1.0, stroke="ink", a=1.0, w=1.3, hatch=None, blur=0.0, add=False):
        if fill is not None and fa > 0:
            self.c.drawCircle(x, y, r, self.paint(fill, fa, fill=True, blur=blur, add=add))
        if hatch:
            pth = skia.Path()
            pth.addCircle(x, y, r)
            self.hatch_path(pth, **hatch)
        if stroke is not None and a > 0:
            self.c.drawCircle(x, y, r, self.paint(stroke, a, w, blur=blur, add=add))

    def ellipse(self, x, y, rx, ry, fill=None, fa=1.0, stroke="ink", a=1.0, w=1.3, hatch=None, blur=0.0, add=False):
        rect = skia.Rect.MakeLTRB(x - rx, y - ry, x + rx, y + ry)
        if fill is not None and fa > 0:
            self.c.drawOval(rect, self.paint(fill, fa, fill=True, blur=blur, add=add))
        if hatch:
            pth = skia.Path()
            pth.addOval(rect)
            self.hatch_path(pth, **hatch)
        if stroke is not None and a > 0:
            self.c.drawOval(rect, self.paint(stroke, a, w, blur=blur, add=add))

    def arc(self, x, y, r, a0, sweep, col="ink", a=1.0, w=1.3, ry=None):
        ry = r if ry is None else ry
        p = skia.Path()
        p.addArc(skia.Rect.MakeLTRB(x - r, y - ry, x + r, y + ry), a0, sweep)
        self.c.drawPath(p, self.paint(col, a, w))

    def glow(self, x, y, r, col="gold", a=0.5, ry=None):
        """Soft radial light, additive on dark palettes."""
        if a <= 0:
            return
        c = self.rgb(col)
        shader = skia.GradientShader.MakeRadial(
            skia.Point(x, y), r,
            [skia.ColorSetARGB(int(255 * clamp(a)), *c), skia.ColorSetARGB(int(90 * clamp(a)), *c),
             skia.ColorSetARGB(0, *c)], [0.0, 0.35, 1.0])
        p = skia.Paint(AntiAlias=True, Shader=shader)
        p.setBlendMode(skia.BlendMode.kPlus if self.dark else skia.BlendMode.kSrcOver)
        self.c.save()
        if ry:
            self.c.translate(x, y)
            self.c.scale(1, ry / r)
            self.c.translate(-x, -y)
        self.c.drawCircle(x, y, r, p)
        self.c.restore()

    def rays(self, cx, cy, n=60, r0=80, r1=900, a=0.25, col="ink", w=0.8, a0=0, a1=360, spin=0.0):
        pth = skia.Path()
        for i in range(n):
            ang = math.radians(a0 + (a1 - a0) * (i + 0.5) / n + spin)
            j = 0.6 + 0.4 * rnd(i, 3)
            pth.moveTo(cx + r0 * math.cos(ang), cy + r0 * math.sin(ang))
            pth.lineTo(cx + r1 * j * math.cos(ang), cy + r1 * j * math.sin(ang))
        self.c.drawPath(pth, self.paint(col, a, w))

    def text(self, s, x, y, kind="mono", size=11, col="sub", a=1.0, track=0.0, align="left",
             blur=0.0, add=False, cjk="cjk"):
        """Draw text with letter-spacing; CJK characters switch to a CJK font automatically."""
        if a <= 0.003 or not s:
            return 0
        runs = []
        for ch in s:
            k = cjk if (is_cjk(ch) and kind not in ("cjk", "brush")) else kind
            if k == "brush" and not has_glyph("brush", ch):
                k = "cjk"
            f = font(k, size * (1.0 if k == kind else 1.08))
            runs.append((ch, f, f.measureText(ch)))
        total = sum(r[2] for r in runs) + track * (len(runs) - 1)
        x0 = x - total if align == "right" else x - total / 2 if align == "center" else x
        p = self.paint(col, a, fill=True, blur=blur, add=add)
        cx = x0
        for ch, f, wch in runs:
            self.c.drawString(ch, cx, y, f, p)
            cx += wch + track
        return total

    def width(self, s, kind="display", size=40, track=0.0):
        return sum(font(kind, size).measureText(ch) for ch in s) + track * (len(s) - 1)

    def bilinear(self, quad, u, v):
        (x0, y0), (x1, y1), (x2, y2), (x3, y3) = quad
        ax, ay = lerp(x0, x1, u), lerp(y0, y1, u)
        bx, by = lerp(x3, x2, u), lerp(y3, y2, u)
        return lerp(ax, bx, v), lerp(ay, by, v)

    # -- meshes ------------------------------------------------------------------
    def mesh(self, cam, faces, a=1.0, w=1.2, cull=False):
        items = []
        for f in faces:
            pr = [cam.p(*v) for v in f["pts"]]
            z = sum(q[2] for q in pr) / len(pr)
            pts = [(q[0], q[1]) for q in pr]
            if cull or f.get("cull"):
                s = sum(pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1]
                        for i in range(len(pts)))
                if s > 0:
                    continue
            items.append((z, pts, f))
        items.sort(key=lambda it: -it[0])
        for z, pts, f in items:
            fa = f.get("fa", 1.0) * a
            self.poly(pts, fill=f.get("fill", "fill"), fa=fa, stroke=f.get("stroke", "ink"),
                      sa=f.get("sa", 1.0) * a, w=f.get("w", w), hatch=f.get("hatch"), shade=f.get("shade", 0))
            if f.get("deco"):
                f["deco"](self, pts)
        return items


def trim(pts, prog):
    """The first `prog` fraction (by length) of a polyline."""
    d = [math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
    total = sum(d)
    if total == 0:
        return pts
    goal = total * clamp(prog)
    out = [pts[0]]
    acc = 0.0
    for i, di in enumerate(d):
        if acc + di >= goal:
            t = (goal - acc) / di if di else 0
            out.append((lerp(pts[i][0], pts[i + 1][0], t), lerp(pts[i][1], pts[i + 1][1], t)))
            return out
        acc += di
        out.append(pts[i + 1])
    return out


def point_at(pts, prog):
    tp = trim(pts, prog)
    return tp[-1]


def bez(p0, p1, p2, p3=None, n=24):
    """Quadratic (3 points) or cubic (4 points) Bezier as a polyline."""
    out = []
    for i in range(n + 1):
        t = i / n
        if p3 is None:
            x = (1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t * t * p2[0]
            y = (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t * t * p2[1]
        else:
            x = (1 - t) ** 3 * p0[0] + 3 * (1 - t) ** 2 * t * p1[0] + 3 * (1 - t) * t * t * p2[0] + t ** 3 * p3[0]
            y = (1 - t) ** 3 * p0[1] + 3 * (1 - t) ** 2 * t * p1[1] + 3 * (1 - t) * t * t * p2[1] + t ** 3 * p3[1]
        out.append((x, y))
    return out


def circle_pts(cx, cy, rx, ry=None, n=48, a0=0, a1=360):
    ry = rx if ry is None else ry
    return [(cx + rx * math.cos(math.radians(a0 + (a1 - a0) * i / n)),
             cy + ry * math.sin(math.radians(a0 + (a1 - a0) * i / n))) for i in range(n + 1)]



def catmull(pts, n=8):
    """A smooth curve through the given points."""
    out = []
    P = [pts[0]] + list(pts) + [pts[-1]]
    for i in range(1, len(P) - 2):
        p0, p1, p2, p3 = P[i - 1], P[i], P[i + 1], P[i + 2]
        for j in range(n):
            t = j / n
            t2, t3 = t * t, t * t * t
            out.append(tuple(0.5 * (2 * p1[k] + (-p0[k] + p2[k]) * t + (2 * p0[k] - 5 * p1[k] + 4 * p2[k] - p3[k]) * t2 +
                                    (-p0[k] + 3 * p1[k] - 3 * p2[k] + p3[k]) * t3) for k in range(2)))
    out.append(pts[-1])
    return out


def mountain(ctx, x, base, w, h, a=1.0, seed=0, fill="fill"):
    """A tall, rounded ink-painting peak with a shaded (hatched) flank."""
    j = lambda k: (rnd(seed, k) - 0.5)
    ridge = catmull([(x - w, base), (x - w * (0.55 + 0.1 * j(1)), base - h * (0.45 + 0.1 * j(2))),
                     (x - w * 0.22, base - h * 0.92), (x + w * 0.02 * j(3), base - h), (x + w * 0.2, base - h * 0.9),
                     (x + w * (0.5 + 0.1 * j(4)), base - h * 0.42), (x + w, base)], 10)
    ctx.poly(ridge, fill=fill, fa=a, stroke=None)
    shade = [q for q in ridge if q[0] >= x + w * 0.02 * j(3)] + [(x + w * 0.1, base)]
    ctx.hatch_path(ctx.path(shade, True), gap=3.2, ang=65, a=0.42 * a)
    ctx.line(ridge, "ink", a, 1.4)
    ctx.line(catmull([(x + w * 0.02 * j(3), base - h), (x + w * 0.1, base - h * 0.6), (x - w * 0.05, base - h * 0.25),
                      (x + w * 0.05, base)], 8), "ink", 0.5 * a, 0.9)
    for k in range(3):
        yy = base - h * (0.2 + 0.2 * k)
        ctx.line([(x - w * (0.55 - 0.12 * k), yy), (x - w * (0.4 - 0.1 * k), yy - 6)], "ink", 0.45 * a, 0.9)

# ---------------------------------------------------------------------------
# Headlines: words land one at a time; a leading "*" marks an accent word
# ---------------------------------------------------------------------------
STYLE = {"ink": "text", "red": "acc", "gold": "gold", "white": (246, 240, 226), "fire": "acc"}


def headline(ctx, lines, x=92, y=150, t0=0.12, stagger=0.13, cap=None, align="left", cap_gap=34):
    lt = ctx.lt
    k = 0
    yy = y
    for text, style, size in lines:
        words = text.split(" ")
        track = size * 0.05
        space = ctx.width(" ", "display", size) + track * 1.5
        clean = [w.lstrip("*") for w in words]
        widths = [ctx.width(w, "display", size, track) for w in clean]
        total = sum(widths) + space * (len(words) - 1)
        xx = x - total / 2 if align == "center" else x - total if align == "right" else x
        yy += size * 0.78
        for raw, word, ww in zip(words, clean, widths):
            tk = t0 + k * stagger
            k += 1
            a = eo(seg(lt, tk, tk + 0.2))
            if a <= 0:
                xx += ww + space
                continue
            st = ("fire" if ctx.dark else "red") if raw.startswith("*") else style
            col = ctx.rgb(STYLE[st]) if isinstance(STYLE[st], str) else STYLE[st]
            big = size >= 56
            sc = 1 + (1 - a) * (0.22 if big else 0.08)
            cx, cy = xx + ww / 2, yy - size * 0.35
            ctx.c.save()
            ctx.c.translate(cx, cy)
            ctx.c.scale(sc, sc)
            ctx.c.translate(-cx, -cy)
            dy = (1 - a) * size * 0.15
            if ctx.dark:
                ctx.text(word, xx, yy + dy, "display", size, col, 0.5 * a, track, blur=size * 0.22, add=True)
            elif big:
                ctx.text(word, xx + 2, yy + dy + 2, "display", size, (120, 90, 60), 0.18 * a, track, blur=2.5)
            ctx.text(word, xx, yy + dy, "display", size, col, a, track, blur=(1 - a) * 5)
            ctx.c.restore()
            xx += ww + space
        yy += size * 0.3
    if cap:
        ta = t0 + k * stagger + 0.05
        a = eo(seg(lt, ta, ta + 0.35))
        cx = x if align == "left" else x - ctx.width(cap, "mono", 10, 3.2) / 2 if align == "center" else \
            x - ctx.width(cap, "mono", 10, 3.2)
        ctx.text(cap, cx, yy + cap_gap - 10, "mono", 10, "sub", 0.9 * a, track=3.2)
    return yy


def count_text(ctx, value, lt, t0, t1, fmt="{:,.0f}"):
    return fmt.format(value * eo(seg(lt, t0, t1)))


# ---------------------------------------------------------------------------
# HUD
# ---------------------------------------------------------------------------
PROJECT = "WENMING · 文明"
TL_YEARS = [(-3000, "3000 BC"), (-2000, "2000"), (-1000, "1000"), (0, "0"), (1000, "1000"), (2000, "2000")]


def year_str(y):
    if isinstance(y, str):
        return y
    y = int(round(y))
    return f"{-y} BC" if y < 0 else f"AD {y}"


def year_x(y, x0=405, x1=875):
    if isinstance(y, str):
        return x1
    return x0 + (clamp((y + 3000) / 5100)) * (x1 - x0 - 24)


def hud(ctx, shot, prev):
    lt = ctx.lt
    a = 0.9
    tcol = "text"
    for x, y, sx, sy in [(36, 36, 1, 1), (1244, 36, -1, 1), (36, 684, 1, -1), (1244, 684, -1, -1)]:
        ctx.line([(x, y + 14 * sy), (x, y), (x + 14 * sx, y)], "sub", 0.55, 1.0)
    ctx.text(shot["ch"], 64, 58, "mono", 10.5, tcol, 0.85 * a, track=2.6)
    ctx.text(PROJECT, 1216, 58, "mono", 10.5, tcol, 0.85 * a, track=2.6, align="right")
    frame_no = int((shot["start"] + lt) * FPS)
    ctx.text(f"文 × 5000   {frame_no:05d}", 1216, 74, "mono", 7.5, "sub", 0.55, track=1.6, align="right")

    # year, rolling from the previous shot's year
    y1 = shot["year"]
    y0 = prev["year"] if prev and prev.get("hud") else y1
    if shot.get("year_to") is not None:
        y0, y1 = shot["year"], shot["year_to"]
        r = ease(seg(lt, 0.3, shot["dur"] - 0.3))
    else:
        r = eo(seg(lt, 0.0, 0.35))
    if isinstance(y1, str) or isinstance(y0, str):
        ys, yv = year_str(y1), y1
    else:
        yv = lerp(y0, y1, r)
        ys = year_str(yv)
    ctx.text("YEAR", 64, 638, "mono", 7.5, "sub", 0.55, track=2.2)
    ctx.text(ys, 64, 665, "mono", 18, tcol, a, track=1.2)

    # timeline
    x0, x1, ty = 405, 875, 676
    ctx.line([(x0, ty), (x1, ty)], "sub", 0.5, 0.8)
    for yr, lab in TL_YEARS:
        xx = year_x(yr)
        ctx.line([(xx, ty - 3), (xx, ty + 3)], "sub", 0.6, 0.8)
        ctx.text(lab, xx, ty - 9, "mono", 6.5, "sub", 0.5, align="center")
    ctx.text("∞", x1 - 6, ty - 9, "mono", 7, "sub", 0.6, align="center")
    xm = year_x(yv)
    ctx.line([(x0, ty), (xm, ty)], "acc" if not ctx.dark else "gold", 0.95, 2.0)
    ctx.poly([(xm - 4, ty - 8), (xm + 4, ty - 8), (xm, ty - 3)], fill="acc" if not ctx.dark else "gold", stroke=None)

    # Kardashev meter
    k1 = shot["k"]
    k0 = prev["k"] if prev and prev.get("hud") else k1
    kv = lerp(k0, k1, eo(seg(lt, 0.0, 0.6 if k1 - k0 < 0.5 else 1.4)))
    ctx.text("KARDASHEV", 1216, 638, "mono", 7.5, "sub", 0.55, track=2.2, align="right")
    ctx.text(f"K {kv:.3f}", 1216, 665, "mono", 18, tcol, a, track=1.2, align="right")
    mx0, mx1 = 1042, 1216
    ctx.line([(mx0, ty), (mx1, ty)], "sub", 0.5, 0.8)
    for i in range(4):
        xx = lerp(mx0, mx1, i / 3)
        ctx.line([(xx, ty - 3), (xx, ty + 3)], "sub", 0.6, 0.8)
    ctx.line([(mx0, ty), (lerp(mx0, mx1, clamp(kv / 3)), ty)], "acc" if not ctx.dark else "gold", 0.95, 2.0)


# ---------------------------------------------------------------------------
# The motif: the character 文 written in light, and drifting sparks
# ---------------------------------------------------------------------------
WEN = [  # strokes of 文 in a unit box: (x, y, width)
    [(0.46, 0.02, 0.035), (0.51, 0.08, 0.055), (0.54, 0.15, 0.04)],
    [(0.10, 0.31, 0.025), (0.30, 0.30, 0.045), (0.60, 0.29, 0.045), (0.87, 0.28, 0.04), (0.91, 0.29, 0.02)],
    [(0.72, 0.33, 0.045), (0.66, 0.50, 0.05), (0.52, 0.68, 0.05), (0.32, 0.84, 0.04), (0.10, 0.96, 0.012)],
    [(0.30, 0.37, 0.02), (0.42, 0.56, 0.035), (0.58, 0.74, 0.05), (0.76, 0.88, 0.07), (0.94, 0.95, 0.03)],
]


def wen(ctx, x, y, size, prog=1.0, a=1.0, core=(255, 238, 190), halo="gold"):
    """文 written stroke by stroke; returns the brush position."""
    strokes = [[(x + (px - 0.5) * size, y + (py - 0.5) * size, pw * size) for px, py, pw in s] for s in WEN]
    lens = [sum(math.dist(s[i][:2], s[i + 1][:2]) for i in range(len(s) - 1)) for s in strokes]
    total = sum(lens)
    goal = total * clamp(prog)
    tip = strokes[0][0][:2]
    for passes in ((halo, 0.3 * a, size * 0.035, 1.8), (core, a, 0, 1.0)):
        col, alpha, blur, wmul = passes
        if alpha <= 0:
            continue
        acc = 0.0
        for s, L in zip(strokes, lens):
            if acc >= goal:
                break
            upto = clamp((goal - acc) / L)
            pts = []
            for j in range(40):
                t = j / 39 * upto
                pos = t * (len(s) - 1)
                i0 = min(int(pos), len(s) - 2)
                f = pos - i0
                pts.append((lerp(s[i0][0], s[i0 + 1][0], f), lerp(s[i0][1], s[i0 + 1][1], f),
                            lerp(s[i0][2], s[i0 + 1][2], f)))
            for j in range(len(pts) - 1):
                p = ctx.paint(col, alpha, pts[j][2] * wmul, blur=blur, add=True)
                ctx.c.drawLine(pts[j][0], pts[j][1], pts[j + 1][0], pts[j + 1][1], p)
            tip = pts[-1][:2]
            acc += L
    return tip


def sparks(ctx, x, y, lt, n=40, spread=30, rise=170, col=(255, 205, 120), seed=0, size=1.8, a=1.0):
    for j in range(n):
        life = 0.9 + rnd(j, seed) * 1.1
        ph = ((lt + rnd(j, seed + 1) * life) % life) / life
        px = x + (rnd(j, seed + 2) - 0.5) * spread + math.sin(lt * 3 + j) * 10 * ph
        py = y - ph * rise * (0.4 + rnd(j, seed + 3))
        al = (1 - ph) ** 1.5 * a
        ctx.circle(px, py, size * (1 - 0.5 * ph), fill=col, fa=al, stroke=None, add=True)


def flame(ctx, x, y, h, lt, a=1.0, seed=0):
    """A flickering flame whose base sits at (x, y)."""
    fl = 1 + 0.06 * math.sin(lt * 23 + seed) + 0.04 * math.sin(lt * 37 + seed * 2)
    ctx.glow(x, y - h * 0.4, h * 2.2, (255, 150, 60), 0.35 * a)
    for k, (col, s, al) in enumerate([((255, 110, 40), 1.0, 0.55), ((255, 180, 80), 0.75, 0.7),
                                      ((255, 240, 200), 0.45, 0.95)]):
        hh = h * s * fl
        ww = h * 0.26 * s
        sway = math.sin(lt * 5 + k + seed) * ww * 0.25
        pts = bez((x - ww, y), (x - ww * 1.1, y - hh * 0.55), (x + sway, y - hh)) + \
            bez((x + sway, y - hh), (x + ww * 1.1, y - hh * 0.55), (x + ww, y))[1:]
        p = ctx.paint(col, al * a, fill=True, blur=h * 0.06 * (3 - k), add=True)
        ctx.c.drawPath(ctx.path(pts, True), p)


def seal(ctx, x, y, s, chars, rot=-4, a=1.0):
    """A red square seal with white characters."""
    ctx.c.save()
    ctx.c.translate(x, y)
    ctx.c.rotate(rot)
    red = (180, 30, 26) if not ctx.dark else (220, 60, 40)
    ctx.poly([(-s / 2, -s / 2), (s / 2, -s / 2), (s / 2, s / 2), (-s / 2, s / 2)], fill=red, fa=0.92 * a, stroke=None)
    ctx.poly([(-s * .42, -s * .42), (s * .42, -s * .42), (s * .42, s * .42), (-s * .42, s * .42)],
             fill=None, stroke=(248, 236, 220), sa=0.9 * a, w=s * 0.035)
    if len(chars) == 1:
        ctx.text(chars, 0, s * 0.27, "cjk", s * 0.62, (250, 240, 228), a, align="center")
    else:
        pos = [(0.2, -0.05), (0.2, 0.33), (-0.2, -0.05), (-0.2, 0.33)] if len(chars) == 4 else \
            [(0, -0.06), (0, 0.33)]
        for ch, (px, py) in zip(chars, pos):
            ctx.text(ch, px * s, py * s, "cjk", s * 0.34, (250, 240, 228), a, align="center")
    ctx.c.restore()


# ---------------------------------------------------------------------------
# Backgrounds and film finish
# ---------------------------------------------------------------------------
def _noise(shape, cells, seed):
    rng = np.random.default_rng(seed)
    small = (rng.random((cells[1], cells[0])) * 255).astype(np.uint8)
    return np.asarray(Image.fromarray(small).resize(shape, Image.BICUBIC), np.float32) / 255


def make_bg(kind):
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    r = np.sqrt(((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2)
    if kind == "paper":
        base = np.array([228, 217, 194], np.float32)
        mott = 0.6 * _noise((W, H), (14, 8), 1) + 0.4 * _noise((W, H), (40, 24), 2)
        fine = _noise((W, H), (640, 360), 3)
        img = base * (0.93 + 0.1 * mott[..., None]) * (0.985 + 0.03 * fine[..., None])
        burn = np.clip(r - 0.55, 0, 1) ** 1.6
        img = img * (1 - 0.45 * burn[..., None]) + np.array([90, 60, 30], np.float32) * 0.25 * burn[..., None]
        # faint warm light from the top right
        light = np.exp(-(((xx - 900) / 700) ** 2 + ((yy - 120) / 500) ** 2))
        img += light[..., None] * np.array([10, 8, 4], np.float32)
    else:
        warm = kind == "ember"
        base = np.array([20, 15, 11] if warm else [11, 13, 20], np.float32)
        lift = np.array([44, 30, 20] if warm else [22, 25, 36], np.float32)
        img = base + lift * np.clip(1 - r * 0.8, 0, 1)[..., None] ** 2
        img *= (0.94 + 0.08 * _noise((W, H), (20, 12), 5))[..., None]
        rng = np.random.default_rng(9)
        nstars = 700 if kind == "space" else 220
        for _ in range(nstars):
            x, y = rng.integers(0, W), rng.integers(0, H)
            img[y, x] += rng.random() * (120 if kind == "space" else 50)
    rgba = np.dstack([np.clip(img, 0, 255).astype(np.uint8), np.full((H, W), 255, np.uint8)])
    return skia.Image.fromarray(rgba)


_G = {}


def worker_state():
    if not _G:
        ensure_fonts()
        _G["surface"] = skia.Surface(W, H)
        _G["bg"] = {k: make_bg(k) for k in ("paper", "dark", "ember", "space")}
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        r = np.sqrt(((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2)
        _G["vig"] = (1 - 0.32 * np.clip(r - 0.35, 0, 1) ** 1.5)[..., None].astype(np.float32)
        rng = np.random.default_rng(4)
        _G["grain"] = [(rng.random((H, W)).astype(np.float32) - 0.5)[..., None] for _ in range(6)]
        _G["icons"] = {}
    return _G


def finish(rgb, dark, i, cut, flash):
    f = rgb.astype(np.float32) * (1 / 255)
    if dark:
        small = Image.fromarray(rgb).resize((W // 4, H // 4), Image.BILINEAR).filter(ImageFilter.GaussianBlur(5))
        bl = np.asarray(small.resize((W, H), Image.BILINEAR), np.float32) * (1 / 255)
        f += np.clip(bl - 0.28, 0, 1) * 0.85
    s = 1 + int(round(cut * 5))
    out = f.copy()
    out[:, s:, 0] = f[:, :-s, 0]
    out[:, :-s, 2] = f[:, s:, 2]
    out = out * _G["vig"] + _G["grain"][i % 6] * (0.07 if not dark else 0.05)
    out *= 1 + 0.02 * (rnd(i, 11) - 0.5)
    if flash > 0:
        out += (1 - out) * flash
    return (np.clip(out, 0, 1) * 255).astype(np.uint8)


# ---------------------------------------------------------------------------
# Shots. Each art function draws one illustration at local time lt (seconds)
# and progress p (0..1); headlines and the HUD are drawn on top by the renderer.
# ---------------------------------------------------------------------------
STEMS = "甲乙丙丁戊己庚辛壬癸子丑寅卯辰巳午未申酉戌亥"
TRIGRAMS = [(1, 1, 1), (0, 1, 1), (1, 0, 1), (0, 0, 1), (1, 1, 0), (0, 1, 0), (1, 0, 0), (0, 0, 0)]


def trigram(ctx, x, y, ang, s, bits, col="ink", a=1.0, w=2.0):
    ca, sa = math.cos(math.radians(ang)), math.sin(math.radians(ang))
    for k, b in enumerate(bits):
        o = (k - 1) * s * 0.45
        cx, cy = x + ca * o, y + sa * o
        dx, dy = -sa * s * 0.6, ca * s * 0.6
        if b:
            ctx.line([(cx - dx, cy - dy), (cx + dx, cy + dy)], col, a, w, cap=None) if False else \
                ctx.line([(cx - dx, cy - dy), (cx + dx, cy + dy)], col, a, w)
        else:
            ctx.line([(cx - dx, cy - dy), (cx - dx * 0.2, cy - dy * 0.2)], col, a, w)
            ctx.line([(cx + dx * 0.2, cy + dy * 0.2), (cx + dx, cy + dy)], col, a, w)


def art_ring(ctx, lt, p, cx=640, cy=360, R=300, a=0.3, spin=4.0):
    """The astrolabe-like ring behind the opening and the ending."""
    rot = lt * spin
    ctx.circle(cx, cy, R, stroke="ink", a=a, w=1.0)
    ctx.circle(cx, cy, R - 34, stroke="ink", a=a * 0.8, w=0.8)
    ctx.circle(cx, cy, R * 0.55, stroke="ink", a=a * 0.5, w=0.7)
    for i in range(72):
        ang = math.radians(rot + i * 5)
        r0 = R - (10 if i % 3 else 18)
        ctx.line([(cx + r0 * math.cos(ang), cy + r0 * math.sin(ang)), (cx + R * math.cos(ang), cy + R * math.sin(ang))],
                 "ink", a * 0.8, 0.8)
    for i, ch in enumerate(STEMS):
        ang = math.radians(rot + i * 360 / len(STEMS) - 90)
        ctx.c.save()
        ctx.c.translate(cx + (R - 24) * math.cos(ang), cy + (R - 24) * math.sin(ang))
        ctx.c.rotate(math.degrees(ang) + 90)
        ctx.text(ch, 0, 5, "cjk", 13, "ink", a * 1.1, align="center")
        ctx.c.restore()
    for i, bits in enumerate(TRIGRAMS):
        ang = rot * -0.6 + i * 45 - 90
        rr = R * 0.55 + 24
        x, y = cx + rr * math.cos(math.radians(ang)), cy + rr * math.sin(math.radians(ang))
        trigram(ctx, x, y, ang, 18, bits, "ink", a * 1.2, 2.0)
    # an inscribed star of lines
    pts = [(cx + R * 0.55 * math.cos(math.radians(rot * 0.5 + i * 135)),
            cy + R * 0.55 * math.sin(math.radians(rot * 0.5 + i * 135))) for i in range(9)]
    ctx.line(pts, "ink", a * 0.35, 0.7)


def compass_body(ctx, lt, cx, cy, sc, prog, label_a=0.0):
    """The Song dynasty south-pointer: a lodestone spoon on a diviner's board."""
    c = ctx.c
    c.save()
    c.translate(cx, cy)
    c.scale(sc, sc * 0.6)
    R = 250
    th = 24 / 0.6
    for k, off in enumerate((th, 0)):
        pts = [(-R, -R + off), (R, -R + off), (R, R + off), (-R, R + off)]
        if k == 0:
            ctx.poly([(-R, R), (R, R), (R, R + th), (-R, R + th)], fill="fill", stroke="ink", sa=prog, w=1.4,
                     hatch=dict(gap=4, ang=90, a=0.35))
            ctx.poly([(R, -R), (R, R), (R, R + th), (R, -R + th)], fill="fill", stroke="ink", sa=prog, w=1.4, shade=0.1)
        else:
            ctx.poly(pts, fill="fill", stroke="ink", sa=prog, w=1.6)
    ctx.line([(-R + 14, -R + 14), (R - 14, -R + 14), (R - 14, R - 14), (-R + 14, R - 14)], "ink", 0.7, 1.0,
             prog=prog, closed=True)
    for i in range(28):  # lunar mansions along the square border
        t = i / 28
        side, u = int(t * 4), (t * 4) % 1
        x, y = [(lerp(-R + 14, R - 14, u), -R + 14), (R - 14, lerp(-R + 14, R - 14, u)),
                (lerp(R - 14, -R + 14, u), R - 14), (-R + 14, lerp(R - 14, -R + 14, u))][side]
        ctx.circle(x, y, 2.2, fill="ink", fa=0.6 * prog, stroke=None)
    for rr, al in ((205, 1.0), (182, 0.8), (150, 0.8), (118, 0.6)):
        ctx.line(circle_pts(0, 0, rr, n=90), "ink", al, 1.3, prog=prog)
    for i in range(24):
        ang = math.radians(i * 15 - 90)
        ctx.line([(182 * math.cos(ang), 182 * math.sin(ang)), (205 * math.cos(ang), 205 * math.sin(ang))],
                 "ink", 0.8 * prog, 1.0)
        ctx.text(STEMS[i % len(STEMS)], 166 * math.cos(ang + 0.13), 166 * math.sin(ang + 0.13) + 6, "cjk", 15, "ink",
                 0.8 * prog, align="center")
    # the spoon settles, handle to the south
    ang = 90 + 75 * math.exp(-1.5 * lt) * math.cos(5.2 * lt)
    ca, sa = math.cos(math.radians(ang)), math.sin(math.radians(ang))
    bowl = [(-38 * ca - 30 * sa * math.sin(t) + 38 * ca * math.cos(t) * 0 + 36 * math.cos(t) * ca - 28 * math.sin(t) * sa,
             -38 * sa + 36 * math.cos(t) * sa + 28 * math.sin(t) * ca) for t in np.linspace(0, 2 * math.pi, 40)]
    handle = [(-10 * sa - 8 * ca, 10 * ca - 8 * sa), (-4 * sa + 105 * ca, 4 * ca + 105 * sa),
              (4 * sa + 105 * ca, -4 * ca + 105 * sa), (10 * sa - 8 * ca, -10 * ca - 8 * sa)]
    sh = [(x + 10, y + 26) for x, y in bowl]
    ctx.poly(sh, fill="ink", fa=0.18 * prog, stroke=None)
    ctx.poly(handle, fill="fill", stroke="ink", sa=prog, w=1.5, hatch=dict(gap=3.5, ang=30, a=0.5))
    ctx.poly(bowl, fill="fill", stroke="ink", sa=prog, w=1.6, hatch=dict(gap=3.5, ang=-30, a=0.55))
    ctx.ellipse(-40 * ca, -40 * sa, 14, 10, fill="acc", fa=0.8 * prog, stroke=None)
    ctx.line([(-40 * ca, -40 * sa), (110 * ca, 110 * sa)], "acc", 0.9 * prog, 1.4)
    c.restore()


def art_compass_open(ctx, lt, p):
    art_ring(ctx, lt, p, cx=640, cy=360, R=330, a=0.18)
    compass_body(ctx, lt, 640, 330, 0.95, eo(seg(lt, 0, 0.8)))
    a = eo(seg(lt, 0.4, 0.9))
    ctx.text("AD 1088", 640, 610, "mono", 26, "gold", a, track=9, align="center")
    ctx.text("SHEN KUO · DREAM POOL ESSAYS", 640, 636, "mono", 9, "sub", a * 0.8, track=3, align="center")


def art_compass(ctx, lt, p):
    ctx.rays(900, 390, 70, 230, 900, 0.16, "ink", 0.7)
    compass_body(ctx, lt, 900, 390, 1.0, eo(seg(lt, 0, 0.9)))


def art_cangjie(ctx, lt, p):
    art_ring(ctx, lt, p, R=320, a=0.16)
    prog = ease(seg(lt, 0.5, 2.3))
    tip = wen(ctx, 640, 480, 170, prog)
    if prog < 1:
        sparks(ctx, tip[0], tip[1], lt, n=26, spread=18, rise=90, seed=1)
    sparks(ctx, 640, 470, lt, n=24, spread=120, rise=260, seed=2, a=0.6 * prog)


def art_never(ctx, lt, p):
    art_ring(ctx, lt + 2.6, p, R=320, a=0.16)
    wen(ctx, 640, 480, 170, 1.0, a=1.0)
    ctx.glow(640, 480, 260, "gold", 0.12)
    sparks(ctx, 640, 470, lt, n=50, spread=140, rise=320, seed=3)


def art_rocket_flash(ctx, lt, p):
    a = (0.4 + 0.6 * eo(seg(lt, 0, 0.15))) * (1 - seg(lt, 1.0, 1.4)) * (0.85 + 0.15 * math.sin(lt * 60))
    rocket_outline(ctx, 640, 610, 1.25, a)


def rocket_outline(ctx, x, base, s, a, col="ink"):
    """Long March 2F, front view."""
    def R(x0, y0, x1, y1):
        ctx.poly([(x + x0 * s, base - y0 * s), (x + x1 * s, base - y0 * s), (x + x1 * s, base - y1 * s),
                  (x + x0 * s, base - y1 * s)], fill="fill", fa=a, stroke=col, sa=a, w=1.3)
    for side in (-1, 1):
        bx = side * 30
        R(bx - 11, 0, bx + 11, 190)
        ctx.poly([(x + (bx - 11) * s, base - 190 * s), (x + (bx + 11) * s, base - 190 * s), (x + bx * s, base - 226 * s)],
                 fill="fill", fa=a, stroke=col, sa=a, w=1.3)
    R(-18, 0, 18, 300)
    R(-22, 300, 22, 350)
    ctx.poly([(x - 22 * s, base - 350 * s), (x + 22 * s, base - 350 * s), (x + 10 * s, base - 385 * s),
              (x - 10 * s, base - 385 * s)], fill="fill", fa=a, stroke=col, sa=a, w=1.3)
    ctx.line([(x, base - 385 * s), (x, base - 440 * s)], col, a, 1.6)
    for yy in (60, 120, 180, 240):
        ctx.line([(x - 18 * s, base - yy * s), (x + 18 * s, base - yy * s)], col, a * 0.6, 0.9)
    ctx.text("中国航天", x + 2, base - 262 * s, "cjk", 9 * s, col, a * 0.9, align="center")


def art_yu(ctx, lt, p):
    """Yu the Great dredges the flood into channels."""
    center = bez((1330, 150), (900, 260), (1080, 520), (560, 760), n=60)
    pts = []
    for i in range(len(center)):
        a_, b_ = center[max(i - 1, 0)], center[min(i + 1, len(center) - 1)]
        dx, dy = b_[0] - a_[0], b_[1] - a_[1]
        L = math.hypot(dx, dy) or 1
        pts.append((center[i], (-dy / L, dx / L)))
    wid = 58
    for side in (-1, 1):
        ctx.line([(c[0] + n[0] * wid * side, c[1] + n[1] * wid * side) for c, n in pts], "ink", 1, 1.6,
                 prog=eo(seg(lt, 0, 0.7)))
        # a hatched bank
        for i in range(0, len(pts) - 1, 1):
            c, n = pts[i]
            q0 = (c[0] + n[0] * wid * side, c[1] + n[1] * wid * side)
            q1 = (c[0] + n[0] * (wid + 12) * side, c[1] + n[1] * (wid + 12) * side)
            if i / len(pts) < eo(seg(lt, 0.1, 0.8)):
                ctx.line([q0, q1], "ink", 0.35, 0.8)
    for k in range(5):  # flowing water lines
        off = (k - 2) * 20
        ph = (lt * 0.25 + k * 0.17) % 1
        wl = [(c[0] + n[0] * (off + 4 * math.sin(i * 0.5 + lt * 3 + k)), c[1] + n[1] * (off + 4 * math.sin(i * 0.5 + lt * 3 + k)))
              for i, (c, n) in enumerate(pts)]
        ctx.line(wl, "ink", 0.35, 0.8, dash=[18, 14 + 6 * k])
    # nine channels
    for j in range(9):
        i0 = 8 + j * 5
        c, n = pts[i0]
        side = 1 if j % 2 else -1
        st = (c[0] + n[0] * wid * side, c[1] + n[1] * wid * side)
        ln = 120 + 60 * rnd(j, 5)
        bend = (rnd(j, 6) - 0.5) * 120
        end = (st[0] + n[0] * ln * side + bend, st[1] + n[1] * ln * side + 40)
        mid = ((st[0] + end[0]) / 2 + n[1] * 30, (st[1] + end[1]) / 2 - n[0] * 30)
        path = bez(st, mid, end, n=20)
        pr = eo(seg(lt, 0.5 + j * 0.12, 1.1 + j * 0.12))
        ctx.line(path, "acc", 0.95, 2.2, prog=pr)
        if pr >= 1:
            ctx.circle(end[0], end[1], 3.5, fill="acc", stroke=None)
    for i, (mx, my, mw, mh) in enumerate([(640, 500, 60, 150), (720, 505, 45, 100), (575, 510, 40, 80),
                                           (1200, 600, 70, 170), (1275, 610, 50, 110)]):
        mountain(ctx, mx, my, mw, mh, eo(seg(lt, 0.2 + i * 0.1, 0.7 + i * 0.1)), seed=i)
    seal(ctx, 1150, 250, 46, "禹", a=eo(seg(lt, 1.2, 1.5)))


PLASTRON = [(0, -222), (40, -220), (78, -205), (100, -180), (112, -140), (116, -100), (122, -72), (152, -60),
            (176, -38), (182, -4), (176, 30), (152, 50), (124, 62), (126, 110), (118, 150), (100, 185), (70, 208),
            (40, 216), (20, 222), (0, 204)]


def art_oracle(ctx, lt, p):
    cx, cy = 900, 390
    c = ctx.c
    c.save()
    c.translate(cx, cy)
    c.rotate(-8)
    outline = [(x, y) for x, y in PLASTRON] + [(-x, y) for x, y in reversed(PLASTRON)]
    ctx.poly([(x + 12, y + 16) for x, y in outline], fill="ink", fa=0.15, stroke=None)
    pr = eo(seg(lt, 0, 0.7))
    ctx.poly(outline, fill=(232, 216, 182) if not ctx.dark else "fill", stroke="ink", sa=pr, w=1.8)
    ctx.hatch_path(ctx.path(outline, True), gap=3.2, ang=70, a=0.18)
    zig = [(6 * (1 if i % 2 else -1), -212 + i * 18) for i in range(25)]
    ctx.line(zig, "ink", 0.7, 1.0, prog=pr)
    for yy in (-130, -45, 50, 135):
        ctx.line(bez((-150, yy + 10), (0, yy - 18), (150, yy + 10)), "ink", 0.6, 1.0, prog=pr)
    holes = [(-80, -150), (80, -150), (-95, -80), (95, -80), (-100, 5), (100, 5), (-90, 90), (90, 90), (-60, 160), (60, 160)]
    for k, (hx, hy) in enumerate(holes):
        a = eo(seg(lt, 0.3 + k * 0.05, 0.6 + k * 0.05))
        ctx.ellipse(hx, hy, 9, 14, fill="ink", fa=0.55 * a, stroke="ink", a=a, w=1)
        # the crack: 卜
        pr2 = eo(seg(lt, 0.6 + k * 0.08, 1.0 + k * 0.08))
        sgn = 1 if hx > 0 else -1
        ctx.line([(hx, hy - 16), (hx + sgn * 2, hy + 4), (hx - sgn * 1, hy + 26)], "acc", 1, 1.6, prog=pr2)
        ctx.line([(hx + sgn * 1, hy), (hx - sgn * 18, hy - 8), (hx - sgn * 30, hy - 5)], "acc", 1, 1.4,
                 prog=seg(pr2, 0.4, 1))
    chars = ["貞今日雨", "王占曰吉", "其受年"]
    for ci, col in enumerate(chars):
        for j, ch in enumerate(col):
            a = eo(seg(lt, 0.9 + ci * 0.25 + j * 0.06, 1.2 + ci * 0.25 + j * 0.06))
            ctx.text(ch, -38 + ci * 38, -150 + j * 30 + 110, "cjk", 21, "ink", 0.85 * a, align="center")
    c.restore()


def leiwen(ctx, quad, u0, u1, v0, v1, n, a=0.8, w=0.9):
    sp = [(0.1, 0.1), (0.9, 0.1), (0.9, 0.9), (0.25, 0.9), (0.25, 0.3), (0.7, 0.3), (0.7, 0.7), (0.45, 0.7)]
    for k in range(n):
        ua, ub = lerp(u0, u1, k / n), lerp(u0, u1, (k + 1) / n)
        ctx.line([ctx.bilinear(quad, lerp(ua, ub, x), lerp(v0, v1, y)) for x, y in sp], "ink", a, w)


def ding_deco(ctx, q):
    leiwen(ctx, q, 0.04, 0.96, 0.78, 0.95, 9)
    leiwen(ctx, q, 0.04, 0.96, 0.05, 0.2, 9)
    for side in (-1, 1):  # the taotie mask: eyes, brows, horns
        ex = 0.5 + side * 0.14
        eye = [ctx.bilinear(q, ex + 0.05 * math.cos(t), 0.5 + 0.1 * math.sin(t)) for t in np.linspace(0, 6.3, 24)]
        ctx.poly(eye, fill="fill", stroke="ink", w=1.3)
        ctx.circle(*ctx.bilinear(q, ex, 0.5), 3.2, fill="acc", stroke=None)
        brow = [ctx.bilinear(q, 0.5 + side * (0.08 + 0.3 * t), 0.66 + 0.1 * math.sin(t * 3)) for t in np.linspace(0, 1, 16)]
        ctx.line(brow, "ink", 0.9, 1.4)
        curl = [ctx.bilinear(q, 0.5 + side * (0.36 - 0.06 * math.cos(t) * (1 - t / 9)),
                             0.42 + 0.08 * math.sin(t) * (1 - t / 9)) for t in np.linspace(0, 9, 30)]
        ctx.line(curl, "ink", 0.8, 1.0)
    ctx.line([ctx.bilinear(q, 0.5, 0.22), ctx.bilinear(q, 0.5, 0.74)], "ink", 0.8, 1.6)


def art_ding(ctx, lt, p):
    ctx.rays(890, 260, 64, 120, 800, 0.14, "ink", 0.7, a0=180, a1=360)
    cam = Cam(yaw=-28, pitch=16, dist=520, f=950, cx=890, cy=470, target=(0, 80, 0))
    g = eo(seg(lt, 0, 0.8))
    faces = []
    legh = 52 * g
    for lx in (-38, 38):
        for lz in (-24, 24):
            faces += cyl(lx, lz, 9, 0, legh, n=12, top=False, hatch=dict(gap=3, ang=90, a=0.35))
    bh = 80 * eo(seg(lt, 0.2, 0.9))
    if bh > 1:
        fb = box(-58, legh, -40, 58, legh + bh, 40)
        fb[0]["deco"] = ding_deco if bh > 70 else None
        fb[3]["deco"] = ding_deco if bh > 70 else None
        fb[4]["fill"] = "ink"
        fb[4]["fa"] = 0.75
        faces += fb
        hy = legh + bh
        ha = eo(seg(lt, 0.8, 1.1))
        if ha > 0:
            for hx in (-44, 44):
                faces += box(hx - 4, hy, -20, hx + 4, hy + 34 * ha, -13)
                faces += box(hx - 4, hy, 13, hx + 4, hy + 34 * ha, 20)
                faces += box(hx - 4, hy + 28 * ha, -20, hx + 4, hy + 34 * ha, 20)
    ctx.ellipse(890, 600, 190, 26, fill="ink", fa=0.12, stroke=None)
    ctx.mesh(cam, faces, w=1.3)



# --- II · Zhou ---------------------------------------------------------------
def art_formation(ctx, lt, p):
    """Sun Tzu: the orthodox force holds, the unorthodox wings swing around."""
    cam = Cam(yaw=0, pitch=52, dist=900, f=1050, cx=880, cy=430)
    g = lambda x, z: cam.p(x, 0, z)[:2]
    for i in range(-6, 7):  # ground grid
        ctx.line([g(i * 50, -300), g(i * 50, 380)], "ink", 0.12, 0.7)
    for j in range(-6, 8):
        ctx.line([g(-300, j * 50), g(300, j * 50)], "ink", 0.12, 0.7)
    for k in range(4):  # contour lines of a hill
        ctx.line([g(230 + 40 * math.cos(t) * (1 + k * 0.6), 60 + 30 * math.sin(t) * (1 + k * 0.6))
                  for t in np.linspace(0, 6.3, 40)], "ink", 0.3, 0.8)

    def unit(x, z, s=8, fill="ink", hatch=None, a=1.0):
        q = [g(x - s, z - s), g(x + s, z - s), g(x + s, z + s), g(x - s, z + s)]
        ctx.poly(q, fill=fill, fa=a if fill else 0, stroke="ink", sa=a, w=1.0, hatch=hatch)

    ea = eo(seg(lt, 0, 0.5))
    for r in range(3):
        for c in range(9):
            unit(-96 + c * 24, 200 + r * 22, fill="fill", hatch=dict(gap=3, ang=45, a=0.6), a=ea)
    sa = eo(seg(lt, 0.15, 0.6))
    for r in range(3):
        for c in range(7):
            unit(-72 + c * 24, -100 + r * 22, a=sa)
    mv = ease(seg(lt, 0.7, 2.1))
    for side in (-1, 1):
        path3 = [(side * (140 + 60 * math.sin(t * math.pi) + 40 * t), -90 + 330 * t) for t in np.linspace(0, 1, 30)]
        ctx.line([g(x, z) for x, z in path3], "acc", 0.95, 2.2, prog=eo(seg(lt, 0.5, 1.3)))
        tipx, tipz = path3[-1]
        if seg(lt, 0.5, 1.3) >= 1:
            a1, a2 = g(tipx, tipz), g(tipx - side * 10, tipz - 22)
            a3 = g(tipx + side * 14, tipz - 18)
            ctx.poly([a1, a2, a3], fill="acc", stroke=None)
        bx, bz = path3[int(mv * 18)]
        for r in range(2):
            for c in range(3):
                unit(bx - 24 + c * 24, bz + r * 22, s=7, a=sa)
        ctx.text("奇", *g(bx, bz - 34), "cjk", 18, "acc", sa, align="center")
    ctx.text("正", *g(0, -150), "cjk", 22, "ink", sa, align="center")
    ctx.text("敵", *g(0, 290), "cjk", 18, "ink", ea * 0.8, align="center")


ANALECTS = "學而時習之不亦說乎有朋自遠方來不亦樂乎人不知而不慍不亦君子乎溫故而知新可以為師矣"
GOLDEN = "己所不欲勿施於人"


def art_slips(ctx, lt, p):
    cam = Cam(yaw=-16, pitch=38, dist=820, f=1050, cx=880, cy=450)
    n = 15
    unroll = eo(seg(lt, 0, 1.3))
    shown = unroll * n
    ctx.poly(cam.pp([(-230, -2, -190), (230, -2, -190), (230, -2, 190), (-230, -2, 190)]), fill="ink", fa=0.07,
             stroke=None)
    for i in range(n):
        x0 = 170 - i * 24
        if i > shown:
            break
        a = clamp(shown - i)
        quad = cam.pp([(x0 - 10, 0, -150), (x0 + 10, 0, -150), (x0 + 10, 0, 150), (x0 - 10, 0, 150)])
        special = i == 7
        ctx.poly(quad, fill=(214, 190, 140) if not ctx.dark else "fill", fa=a, stroke="ink", sa=a, w=1.1)
        side = cam.pp([(x0 - 10, 0, -150), (x0 + 10, 0, -150), (x0 + 10, -4, -150), (x0 - 10, -4, -150)])
        ctx.poly(side, fill="ink", fa=0.35 * a, stroke=None)
        ctx.line([ctx.bilinear(quad, 0.25, 0.02), ctx.bilinear(quad, 0.25, 0.98)], "ink", 0.18 * a, 0.7)
        text = GOLDEN if special else ANALECTS[(i * 8) % len(ANALECTS):][:8]
        for j, ch in enumerate(text):
            x, y, z = cam.p(x0, 0, 120 - j * 33)
            s = 1050 / z * 17
            ca = a * eo(seg(lt, 0.5 + i * 0.04 + j * 0.02, 0.8 + i * 0.04 + j * 0.02))
            ctx.c.save()
            ctx.c.translate(x, y)
            ctx.c.scale(1, 0.72)
            ctx.text(ch, 0, s * 0.38, "cjk", s, "acc" if special else "ink", ca * (1 if special else 0.8), align="center")
            ctx.c.restore()
    for zc in (-100, 100):  # the binding cords
        pts = [cam.p(170 - t * 24 * min(shown, n - 1) + 12, 1.5 + 1.5 * math.sin(t * 40), zc)[:2] for t in np.linspace(0, 1, 60)]
        ctx.line(pts, "acc" if not ctx.dark else "ink", 0.8, 1.6)
    if unroll < 1:  # the rolled-up bundle
        x0 = 170 - shown * 24 - 20
        for zc in (-150, 150):
            pass
        top = cam.p(x0, 20, -150)
        bot = cam.p(x0, 20, 150)
        r = 26 * (1 - unroll) + 6
        for k in range(3):
            ctx.line([top[:2], bot[:2]], "ink", 0.8, 2 * r - k * r * 0.6)
            ctx.line([top[:2], bot[:2]], "fill", 1, 2 * r - k * r * 0.6 - 2.5)


def taiji(ctx, cx, cy, r, rot, a=1.0):
    ctx.c.save()
    ctx.c.translate(cx, cy)
    ctx.c.rotate(rot)
    ctx.circle(0, 0, r, fill="fill", fa=a, stroke="ink", a=a, w=1.8)
    p = skia.Path()
    p.moveTo(0, -r)
    p.arcTo(skia.Rect.MakeLTRB(-r, -r, r, r), -90, 180, False)
    p.arcTo(skia.Rect.MakeLTRB(-r / 2, 0, r / 2, r), 90, 180, False)
    p.arcTo(skia.Rect.MakeLTRB(-r / 2, -r, r / 2, 0), 90, -180, False)
    p.close()
    ctx.c.drawPath(p, ctx.paint("ink", a, fill=True))
    ctx.circle(0, r / 2, r / 7, fill="fill", fa=a, stroke=None)
    ctx.circle(0, -r / 2, r / 7, fill="ink", fa=a, stroke=None)
    ctx.c.restore()


def art_bagua(ctx, lt, p):
    cx, cy = 900, 390
    rot = lt * 14
    pr = eo(seg(lt, 0, 0.9))
    ctx.line([(cx - 330, cy), (cx + 330, cy)], "ink", 0.18, 0.8)
    ctx.line([(cx, cy - 320), (cx, cy + 320)], "ink", 0.18, 0.8)
    for rr, al in ((300, 0.5), (255, 0.8), (235, 0.6), (140, 0.4)):
        ctx.line(circle_pts(cx, cy, rr, n=120), "ink", al, 1.1, prog=pr)
    for i in range(64):
        ang = math.radians(i * 360 / 64 + rot * 0.3)
        ctx.line([(cx + 235 * math.cos(ang), cy + 235 * math.sin(ang)), (cx + 255 * math.cos(ang), cy + 255 * math.sin(ang))],
                 "ink", 0.5 * pr, 0.8)
    names = "乾兌離震巽坎艮坤"
    for i, bits in enumerate(TRIGRAMS):
        ang = rot + i * 45 - 90
        a = eo(seg(lt, 0.2 + i * 0.07, 0.5 + i * 0.07))
        x, y = cx + 190 * math.cos(math.radians(ang)), cy + 190 * math.sin(math.radians(ang))
        ctx.ellipse(x + 6, y + 40, 26, 6, fill="ink", fa=0.1 * a, stroke=None)
        trigram(ctx, x, y, ang, 34, bits, "ink", a, 5.0)
        xn, yn = cx + 278 * math.cos(math.radians(ang)), cy + 278 * math.sin(math.radians(ang))
        ctx.text(names[i], xn, yn + 7, "cjk", 18, "acc" if i == 0 else "ink", a, align="center")
    taiji(ctx, cx, cy, 92 * eo(seg(lt, 0.3, 0.9)) + 0.01, -lt * 40)


# --- III · Qin ---------------------------------------------------------------
STATES = [("燕", 1010, 200), ("趙", 880, 270), ("齊", 1130, 320), ("魏", 890, 370), ("韓", 850, 460),
          ("楚", 1020, 545), ("秦", 700, 390)]


def art_unify(ctx, lt, p):
    cx, cy = 900, 390
    m = ease(seg(lt, 0.9, 1.6))
    ctx.rays(cx, cy, 80, 150, 900, 0.14 * m + 0.04, "ink", 0.7)
    for i, (ch, x, y) in enumerate(STATES):
        for j, (ch2, x2, y2) in enumerate(STATES):
            if j > i and math.dist((x, y), (x2, y2)) < 200:
                ctx.line([(lerp(x, cx, m), lerp(y, cy, m)), (lerp(x2, cx, m), lerp(y2, cy, m))], "ink", 0.35 * (1 - m),
                         1.0, dash=[4, 5])
    for i, (ch, x, y) in enumerate(STATES):
        a = eo(seg(lt, i * 0.08, 0.3 + i * 0.08)) * (1 - seg(m, 0.8, 1))
        px, py = lerp(x, cx, m), lerp(y, cy, m)
        ctx.circle(px, py, 44, fill="fill", fa=a, stroke="ink", a=a, w=1.5)
        ctx.circle(px, py, 38, stroke="ink", a=0.5 * a, w=0.8)
        ctx.text(ch, px, py + 12, "cjk", 34, "acc" if ch == "秦" else "ink", a, align="center")
    sa = eo(seg(lt, 1.45, 1.8))
    if sa > 0:
        ctx.c.save()
        ctx.c.translate(cx, cy)
        ctx.c.scale(1 + (1 - sa) * 0.4, 1 + (1 - sa) * 0.4)
        seal(ctx, 0, 0, 170, "書同文", rot=-3, a=sa) if False else seal(ctx, 0, 0, 170, "秦", rot=-3, a=sa)
        ctx.c.restore()
        for i in range(24):
            ang = math.radians(i * 15)
            ctx.line([(cx + 130 * math.cos(ang), cy + 130 * math.sin(ang)), (cx + 150 * math.cos(ang), cy + 150 * math.sin(ang))],
                     "acc", 0.8 * sa, 1.4)
        ctx.text("書同文 · 車同軌", cx, cy + 190, "cjk", 20, "ink", sa, track=4, align="center")


def art_wall(ctx, lt, p):
    """The Great Wall snaking over the ridges, from the near hill to the horizon."""
    for layer, (base, amp, a) in enumerate([(330, 60, 0.35), (380, 80, 0.5)]):
        ridge = [(x, base - amp * (0.5 + 0.5 * math.sin(x * 0.007 + layer * 2) * math.cos(x * 0.013 + layer)))
                 for x in range(420, 1300, 10)]
        ctx.poly(ridge + [(1300, 720), (420, 720)], fill="fill", stroke=None)
        ctx.line(ridge, "ink", a, 1.0)
        for i in range(0, len(ridge) - 1, 2):
            x, y = ridge[i]
            ctx.line([(x, y + 3), (x - 4, y + 18 + 10 * rnd(i, layer))], "ink", a * 0.5, 0.7)
    N = 180
    pts = []
    for i in range(N + 1):
        s = i / N
        x = lerp(1340, 520, s) + 70 * math.sin(s * 7.5)
        y = lerp(640, 380, s) - 45 * math.sin(s * 11) * (1 - 0.5 * s)
        k = lerp(1.35, 0.22, s ** 0.8)
        pts.append((x, y, k, s))
    grow = eo(seg(lt, 0, 1.6))
    # the hill under the wall
    hill = [(x, y + 6 * k) for x, y, k, s in pts] + [(520, 720), (1340, 720)]
    ctx.poly(hill, fill="fill", stroke=None)
    for i in range(0, N, 2):
        x, y, k, s = pts[i]
        for j in range(3):
            ctx.line([(x + j * 4 * k, y + 8 * k), (x + j * 4 * k - 10 * k, y + (40 + 30 * rnd(i, j)) * k)], "ink", 0.35, 0.8)
    for i in range(N - 1, -1, -1):
        x0, y0, k0, s0 = pts[i]
        x1, y1, k1, s1 = pts[i + 1]
        if s0 > grow:
            continue
        h0, h1 = 26 * k0, 26 * k1
        face_ = [(x0, y0), (x1, y1), (x1, y1 - h1), (x0, y0 - h0)]
        ctx.poly(face_, fill="fill", stroke=None, hatch=dict(gap=max(2.0, 4 * k0), ang=0, a=0.35))
        ctx.line([(x0, y0), (x1, y1)], "ink", 1, 1.2 * k0 + 0.3)
        top = [(x0, y0 - h0), (x1, y1 - h1)]
        ctx.poly([top[0], top[1], (x1 + 3 * k1, y1 - h1 - 5 * k1), (x0 + 3 * k0, y0 - h0 - 5 * k0)], fill="fill",
                 stroke="ink", w=0.8 * k0 + 0.3)
        if i % 2 == 0:  # crenels
            cw = 5 * k0
            ctx.poly([(x0, y0 - h0), (x0 + cw, y0 - h0), (x0 + cw, y0 - h0 - 8 * k0), (x0, y0 - h0 - 8 * k0)],
                     fill="fill", stroke="ink", w=0.7 * k0 + 0.3)
        if i % 22 == 11:  # watchtowers
            tw, th = 22 * k0, 62 * k0
            ctx.poly([(x0 - tw, y0 + 4 * k0), (x0 + tw, y0 + 4 * k0), (x0 + tw * 0.9, y0 - th), (x0 - tw * 0.9, y0 - th)],
                     fill="fill", stroke="ink", w=1.2 * k0 + 0.3, hatch=dict(gap=max(2.0, 3.5 * k0), ang=90, a=0.3))
            ctx.poly([(x0 - tw * 0.3, y0 - th * 0.55), (x0 + tw * 0.3, y0 - th * 0.55), (x0 + tw * 0.3, y0 - th * 0.8),
                      (x0 - tw * 0.3, y0 - th * 0.8)], fill="ink", fa=0.8, stroke=None)
            for c in range(4):
                xx = x0 - tw * 0.9 + c * tw * 0.6
                ctx.poly([(xx, y0 - th), (xx + tw * 0.3, y0 - th), (xx + tw * 0.3, y0 - th - 9 * k0), (xx, y0 - th - 9 * k0)],
                         fill="fill", stroke="ink", w=0.8 * k0 + 0.3)
    if grow < 1:
        x, y, k, s = pts[int(grow * N)]
        ctx.circle(x, y - 14 * k, 4, fill="acc", stroke=None)


def warrior(ctx, x, y, k, a=1.0, seed=0, fill=(186, 118, 84)):
    """A terracotta warrior standing at (x, y), k pixels per unit."""
    if ctx.dark:
        fill = ctx.pal["fill"]
    lw = 0.35 + 0.12 * k
    ctx.poly([(x - 3 * k, y), (x - 1.2 * k, y), (x - 1.4 * k, y - 6 * k), (x - 3 * k, y - 6 * k)], fill=fill, fa=a,
             stroke="ink", sa=a, w=lw)
    ctx.poly([(x + 1.2 * k, y), (x + 3 * k, y), (x + 3 * k, y - 6 * k), (x + 1.4 * k, y - 6 * k)], fill=fill, fa=a,
             stroke="ink", sa=a, w=lw)
    ctx.poly([(x - 4.4 * k, y - 5.5 * k), (x + 4.4 * k, y - 5.5 * k), (x + 3.6 * k, y - 11 * k), (x - 3.6 * k, y - 11 * k)],
             fill=fill, fa=a, stroke="ink", sa=a, w=lw, shade=0.1)
    ctx.poly([(x - 3.8 * k, y - 10 * k), (x + 3.8 * k, y - 10 * k), (x + 3.4 * k, y - 16 * k), (x - 3.4 * k, y - 16 * k)],
             fill=fill, fa=a, stroke="ink", sa=a, w=lw, hatch=dict(gap=max(1.6, 0.9 * k), ang=0, a=0.5 * a) if k > 2 else None,
             shade=0.18)
    for s in (-1, 1):
        ctx.line([(x + s * 3.6 * k, y - 15 * k), (x + s * 4.8 * k, y - 10.5 * k), (x + s * 3.2 * k, y - 9 * k)], "ink",
                 a, lw * 2.2)
    ctx.poly([(x - 1.2 * k, y - 16 * k), (x + 1.2 * k, y - 16 * k), (x + 1.1 * k, y - 17.2 * k), (x - 1.1 * k, y - 17.2 * k)],
             fill=fill, fa=a, stroke="ink", sa=a, w=lw)
    ctx.ellipse(x, y - 19 * k, 1.9 * k, 2.2 * k, fill=fill, fa=a, stroke="ink", a=a, w=lw)
    ctx.ellipse(x + 0.9 * k, y - 21.2 * k, 0.9 * k, 0.7 * k, fill=fill, fa=a, stroke="ink", a=a, w=lw)


def art_terracotta(ctx, lt, p):
    """Pit 1: corridors of warriors between rammed-earth walls, receding to the horizon."""
    hz, camh, f = 330, 62, 900
    proj = lambda x, y, d: (640 + x * f / d, hz + (camh - y) * f / d)
    rows = 22
    reveal = eo(seg(lt, 0, 1.3)) * rows
    far = 150 + rows * 22
    for c in range(-5, 6):  # wall tops, drawn far to near in pieces below
        pass
    ctx.poly([proj(-400, 0, far), proj(400, 0, far), proj(400, 14, far), proj(-400, 14, far)], fill="fill", stroke="ink",
             w=0.8, hatch=dict(gap=3, ang=0, a=0.3))
    for r in range(rows - 1, -1, -1):
        d = 150 + r * 22
        d2 = d + 22
        for c in range(-6, 7):  # rammed-earth walls between corridors
            wx = c * 56 + 28
            top = [proj(wx - 5, 12, d2), proj(wx + 5, 12, d2), proj(wx + 5, 12, d), proj(wx - 5, 12, d)]
            if top[2][0] < -50 or top[0][0] > W + 50:
                continue
            side_x = wx - 5 if wx > 0 else wx + 5
            side = [proj(side_x, 12, d2), proj(side_x, 12, d), proj(side_x, 0, d), proj(side_x, 0, d2)]
            ctx.poly(side, fill="fill", stroke=None, hatch=dict(gap=2.6, ang=0, a=0.4), shade=0.15)
            ctx.poly(top, fill="fill", stroke=None, shade=-0.05)
            ctx.line([top[0], top[3]], "ink", 0.8, 0.8)
            ctx.line([top[1], top[2]], "ink", 0.8, 0.8)
        if r > reveal:
            continue
        a = clamp(reveal - r)
        for c in range(-6, 7):
            for off in (-14, 0, 14):
                x = c * 56 + off + (3 if r % 2 else -3)
                sx, sy = proj(x, 0, d)
                if -60 < sx < W + 60:
                    warrior(ctx, sx, sy, f / d * 1.0, a)


# --- IV · Han ----------------------------------------------------------------
COAST = [
    # Afro-Eurasia, counter-clockwise from Tangier, including the Mediterranean and Black Sea
    [(-5.8, 35.8), (-9.8, 31.5), (-13.2, 27.7), (-16.0, 23.7), (-17.1, 20.9), (-16.5, 19.4), (-17.5, 14.7), (-16.7, 12.3),
     (-15.0, 10.8), (-13.2, 8.9), (-11.5, 6.9), (-7.5, 4.4), (-4.0, 5.2), (1.0, 5.9), (4.5, 6.3), (6.0, 4.3), (8.5, 4.5),
     (9.8, 2.5), (9.3, -1.0), (11.8, -4.8), (13.4, -9.0), (12.3, -13.5), (11.8, -17.2), (14.5, -22.9), (15.2, -26.6),
     (17.0, -29.5), (18.4, -33.9), (20.0, -34.8), (22.5, -34.0), (25.6, -33.9), (27.9, -33.0), (30.9, -30.0),
     (32.6, -26.0), (35.5, -24.0), (35.0, -20.0), (36.9, -17.8), (40.5, -15.0), (40.6, -10.5), (39.3, -6.8),
     (39.7, -4.0), (40.2, -3.2), (41.6, -1.7), (45.3, 2.0), (48.0, 5.0), (51.2, 10.4), (51.3, 11.8), (48.0, 11.2),
     (44.0, 10.4), (43.3, 11.9), (41.7, 13.9), (39.5, 15.6), (37.3, 18.7), (36.5, 22.0), (35.6, 23.9), (34.0, 26.6),
     (32.6, 29.9), (34.2, 27.9), (35.0, 29.5), (36.6, 25.8), (39.1, 21.5), (41.2, 17.8), (42.8, 14.8), (43.5, 12.7),
     (45.0, 12.8), (49.0, 14.5), (52.2, 15.6), (55.0, 17.0), (57.8, 18.9), (59.8, 22.5), (58.5, 23.6), (56.4, 26.4),
     (54.0, 24.2), (51.6, 25.3), (51.2, 26.1), (50.1, 26.6), (48.5, 28.4), (47.9, 29.9), (50.3, 29.3), (51.4, 27.9),
     (54.5, 26.6), (56.3, 27.2), (57.3, 25.8), (61.6, 25.2), (66.6, 25.4), (67.0, 24.8), (68.5, 23.5), (70.0, 22.6),
     (72.6, 21.2), (72.8, 19.0), (73.7, 15.8), (74.9, 12.9), (75.8, 11.2), (76.3, 9.9), (77.5, 8.1), (79.0, 9.2),
     (79.9, 10.3), (80.3, 13.1), (80.1, 15.8), (82.3, 16.6), (84.9, 19.3), (86.9, 21.0), (88.2, 21.7), (90.6, 22.0),
     (91.8, 22.3), (92.3, 20.7), (94.2, 16.0), (97.6, 16.5), (98.2, 13.0), (98.5, 10.5), (98.3, 8.0), (100.3, 5.4),
     (101.4, 2.7), (102.3, 2.2), (103.5, 1.3), (104.2, 1.5), (103.4, 4.0), (102.3, 6.2), (101.2, 6.9), (100.3, 8.4),
     (99.2, 10.3), (99.9, 12.6), (100.5, 13.5), (101.5, 12.6), (102.9, 11.6), (104.7, 10.4), (104.8, 8.6), (106.7, 10.3),
     (107.2, 10.4), (109.2, 12.2), (109.2, 13.8), (108.2, 16.1), (106.8, 17.6), (105.7, 19.0), (106.7, 20.7), (108.1, 21.5),
     (109.7, 21.4), (110.4, 20.3), (110.8, 21.4), (113.3, 22.2), (114.2, 22.3), (116.7, 23.4), (118.1, 24.5), (119.6, 25.9),
     (120.4, 27.5), (121.9, 29.9), (121.9, 30.9), (120.9, 32.7), (119.4, 34.7), (120.3, 36.1), (122.6, 37.4), (120.8, 37.8),
     (119.0, 37.5), (117.7, 38.9), (119.5, 39.9), (121.9, 40.8), (121.3, 38.8), (122.9, 39.7), (124.4, 39.9), (125.2, 37.7),
     (126.5, 34.5), (129.0, 35.1), (129.4, 36.0), (128.6, 38.3), (127.4, 39.8), (129.7, 40.8), (130.7, 42.3), (131.9, 43.1),
     (135.1, 43.5), (138.5, 47.0), (140.5, 50.5), (141.3, 53.0), (137.5, 54.0), (135.1, 54.7), (141.0, 59.0), (148.0, 59.5),
     (155.0, 59.5), (156.7, 51.0), (160.0, 54.0), (163.0, 58.0), (170.0, 60.0), (180.0, 65.0), (180.0, 70.0), (140.0, 72.5),
     (113.0, 73.8), (100.0, 77.5), (80.0, 73.5), (70.0, 73.0), (66.0, 69.0), (55.0, 68.5), (44.0, 68.5), (40.0, 66.2),
     (33.0, 69.4), (25.0, 71.1), (15.0, 68.5), (10.0, 63.5), (5.0, 61.0), (5.5, 58.8), (7.0, 58.0), (10.6, 59.9),
     (11.5, 58.0), (12.7, 56.0), (8.1, 56.8), (8.6, 55.5), (8.9, 54.0), (6.5, 53.4), (4.8, 52.4), (3.2, 51.3), (1.6, 50.9),
     (0.1, 49.5), (-1.6, 49.6), (-4.7, 48.4), (-2.2, 47.2), (-1.2, 45.6), (-1.5, 43.4), (-8.0, 43.7), (-9.3, 43.0),
     (-8.9, 41.0), (-9.5, 38.7), (-8.9, 37.0), (-6.3, 36.5), (-5.6, 36.0), (-4.4, 36.7), (-0.5, 38.3), (-0.3, 39.5),
     (0.9, 41.0), (3.2, 41.9), (3.0, 43.3), (4.8, 43.4), (7.3, 43.7), (8.9, 44.4), (10.3, 43.5), (12.2, 41.7), (14.3, 40.8),
     (15.7, 40.0), (15.6, 38.2), (16.1, 38.0), (17.2, 39.0), (16.9, 40.4), (18.5, 40.1), (16.9, 41.1), (14.2, 42.4),
     (12.3, 44.5), (12.3, 45.4), (13.7, 45.6), (15.2, 44.2), (17.4, 43.0), (19.4, 41.8), (19.4, 40.4), (20.2, 39.5),
     (21.1, 38.3), (21.7, 36.8), (22.5, 36.4), (23.0, 37.9), (24.0, 38.0), (22.9, 40.6), (26.0, 40.8), (26.5, 40.2),
     (28.9, 41.0), (29.1, 41.2), (28.0, 41.9), (27.9, 43.2), (28.6, 44.2), (30.7, 46.5), (32.0, 46.6), (33.5, 45.0),
     (33.4, 44.6), (35.0, 44.8), (36.6, 45.3), (38.3, 47.1), (37.8, 44.7), (39.7, 43.6), (41.6, 41.6), (40.0, 41.0),
     (36.3, 41.3), (34.9, 42.0), (33.3, 41.8), (31.4, 41.1), (29.1, 41.2), (29.0, 40.9), (26.4, 40.1), (26.1, 39.5),
     (26.8, 38.4), (27.3, 37.0), (28.2, 36.7), (30.6, 36.8), (32.8, 36.1), (34.6, 36.8), (36.0, 36.6), (35.8, 35.5),
     (35.5, 34.0), (34.8, 32.1), (34.2, 31.3), (32.3, 31.3), (31.0, 31.6), (29.9, 31.2), (25.2, 31.6), (23.9, 32.1),
     (20.1, 32.1), (19.2, 30.3), (15.5, 31.8), (13.2, 32.9), (11.1, 33.3), (10.1, 34.3), (11.1, 35.2), (10.2, 36.8),
     (9.2, 37.2), (5.1, 36.8), (3.1, 36.8), (-0.6, 35.7), (-2.9, 35.3), (-5.3, 35.9), (-5.8, 35.8)],
    [(47.6, 45.6), (49.2, 46.4), (51.3, 47.0), (53.0, 46.8), (53.2, 45.3), (51.3, 44.5), (52.7, 42.5), (53.0, 40.0),
     (54.0, 37.4), (51.5, 36.8), (49.0, 37.5), (48.9, 38.4), (49.4, 40.3), (48.6, 41.8), (47.5, 43.0), (47.6, 45.6)],
    [(-5.7, 50.1), (1.4, 51.2), (1.7, 52.7), (0.2, 53.5), (-1.6, 55.6), (-2.0, 57.6), (-3.0, 58.6), (-5.0, 58.6),
     (-6.2, 56.6), (-4.8, 55.0), (-3.0, 53.9), (-4.6, 53.3), (-5.2, 51.7), (-3.0, 51.5), (-5.7, 50.1)],
    [(-6.0, 52.2), (-6.2, 54.0), (-8.2, 55.2), (-10.0, 53.9), (-10.3, 51.8), (-8.0, 51.6), (-6.0, 52.2)],
    [(129.8, 33.0), (130.6, 31.2), (131.4, 31.4), (132.0, 33.2), (134.7, 33.8), (135.8, 33.5), (137.0, 34.6), (139.8, 34.9),
     (140.9, 36.9), (141.5, 38.3), (142.0, 39.6), (141.4, 41.4), (139.9, 40.6), (139.8, 38.4), (138.6, 37.9), (137.2, 36.8),
     (135.9, 35.7), (133.2, 35.6), (131.1, 34.4), (129.8, 33.0)],
    [(140.0, 41.5), (141.2, 41.8), (143.3, 42.0), (145.5, 43.3), (144.3, 44.1), (141.9, 45.4), (141.3, 43.3), (140.0, 42.5),
     (140.0, 41.5)],
    [(120.1, 23.0), (120.7, 22.0), (121.6, 23.6), (121.9, 25.0), (121.0, 25.1), (120.1, 23.0)],
    [(108.6, 19.2), (109.5, 18.2), (110.6, 18.9), (111.0, 19.7), (110.3, 20.1), (109.2, 19.9), (108.6, 19.2)],
    [(79.8, 7.2), (79.9, 8.0), (80.2, 9.8), (81.2, 8.6), (81.9, 7.0), (81.0, 6.0), (80.0, 6.0), (79.8, 7.2)],
    [(95.3, 5.6), (97.5, 5.2), (100.4, 2.3), (103.7, -1.0), (106.0, -3.0), (105.8, -5.8), (104.5, -5.8), (102.3, -4.0),
     (100.4, -1.0), (98.7, 1.7), (96.0, 4.1), (95.3, 5.6)],
    [(105.2, -6.8), (106.7, -6.0), (108.3, -6.2), (110.4, -6.9), (112.7, -6.9), (114.4, -7.8), (114.4, -8.7), (111.0, -8.2),
     (108.0, -7.8), (105.4, -6.9), (105.2, -6.8)],
    [(109.0, 1.5), (111.4, 2.4), (113.0, 3.2), (115.4, 5.0), (116.8, 7.0), (117.7, 6.4), (119.2, 5.4), (118.2, 4.3),
     (117.9, 1.0), (117.0, -0.5), (116.5, -2.5), (116.0, -3.7), (114.6, -4.0), (113.0, -3.2), (111.0, -3.0), (110.0, -1.6),
     (109.0, 0.0), (109.0, 1.5)],
    [(49.3, -12.0), (50.4, -15.5), (49.8, -17.0), (47.1, -24.9), (45.2, -25.5), (43.7, -23.3), (43.3, -21.7), (44.4, -19.6),
     (44.0, -17.0), (46.3, -15.8), (47.8, -14.2), (49.3, -12.0)],
    [(120.6, 18.5), (122.2, 18.5), (122.1, 16.3), (121.6, 14.1), (124.0, 13.0), (120.9, 13.8), (120.0, 16.0), (120.6, 18.5)],
    [(122.0, 7.0), (125.4, 9.8), (126.5, 7.3), (125.6, 5.6), (124.0, 6.4), (122.0, 7.0)],
    [(12.4, 37.8), (15.6, 38.3), (15.1, 36.7), (12.4, 37.8)],
    [(8.6, 41.0), (9.8, 41.0), (9.6, 39.2), (8.4, 39.0), (8.6, 41.0)],
    [(9.4, 43.0), (9.5, 42.0), (8.6, 41.6), (9.4, 43.0)],
    [(24.0, 35.5), (26.3, 35.2), (25.0, 34.9), (23.5, 35.3), (24.0, 35.5)],
    [(32.3, 35.1), (34.6, 35.6), (33.9, 34.6), (32.3, 35.1)],
]


class MapProj:
    def __init__(self, lon0, lat0, k, x0, y0):
        self.lon0, self.lat0, self.k, self.x0, self.y0 = lon0, lat0, k, x0, y0
        self.c = math.cos(math.radians(lat0))

    def __call__(self, lon, lat):
        return (self.x0 + (lon - self.lon0) * self.c * self.k, self.y0 - (lat - self.lat0) * self.k)


def draw_map(ctx, proj, prog, lons=range(-20, 181, 10), lats=range(-40, 81, 10), a=1.0):
    for lo in lons:
        ctx.line([proj(lo, la) for la in range(-40, 81, 5)], "ink", 0.1 * a, 0.6)
    for la in lats:
        ctx.line([proj(lo, la) for lo in range(-20, 181, 5)], "ink", 0.1 * a, 0.6)
    for poly in COAST:
        pts = [proj(lo, la) for lo, la in poly]
        ctx.poly(pts, fill="fill", fa=0.55 * a * prog, stroke=None, hatch=None)
        ctx.line(pts, "ink", 0.85 * a, 1.0, prog=prog)


def route(ctx, proj, stops, lt, t0, t1, labels=True, dash=None, lab_a=1.0, w=2.0):
    pts = []
    for i in range(len(stops) - 1):
        (a_, ax, ay), (b_, bx, by) = stops[i], stops[i + 1]
        p0, p1 = proj(ax, ay), proj(bx, by)
        mid = ((p0[0] + p1[0]) / 2 + (p1[1] - p0[1]) * 0.12, (p0[1] + p1[1]) / 2 - (p1[0] - p0[0]) * 0.12)
        seg_ = bez(p0, mid, p1, n=14)
        pts += seg_ if not pts else seg_[1:]
    pr = ease(seg(lt, t0, t1))
    ctx.line(pts, "acc", 0.95, w, prog=pr, dash=dash)
    total = len(stops)
    for i, (name, lo, la) in enumerate(stops):
        x, y = proj(lo, la)
        ta = t0 + (t1 - t0) * i / max(total - 1, 1)
        a = eo(seg(lt, ta, ta + 0.2))
        ctx.circle(x, y, 4 if i in (0, total - 1) else 2.6, fill="acc", fa=a, stroke="ink", a=0.8 * a, w=0.8)
        if labels:
            ctx.text(name, x + 6, y - 6, "mono", 8.5, "ink", 0.85 * a * lab_a, track=1.2)
    if 0 < pr < 1:
        x, y = point_at(pts, pr)
        ctx.circle(x, y, 6, fill="acc", fa=0.3, stroke="acc", a=0.9, w=1.2)
    return pts


SILK = [("CHANG'AN", 108.9, 34.3), ("DUNHUANG", 94.7, 40.1), ("KASHGAR", 76.0, 39.5), ("SAMARKAND", 67.0, 39.7),
        ("MERV", 61.8, 37.6), ("CTESIPHON", 44.6, 33.1), ("PALMYRA", 38.3, 34.6), ("ANTIOCH", 36.2, 36.2),
        ("ROMA", 12.5, 41.9)]


def art_silkroad(ctx, lt, p):
    proj = MapProj(60, 38, 7.6, 800, 330)
    draw_map(ctx, proj, eo(seg(lt, 0, 0.8)))
    route(ctx, proj, SILK, lt, 0.5, 2.1)
    x, y = proj(108.9, 34.3)
    ctx.circle(x, y, 12, stroke="acc", a=eo(seg(lt, 0.4, 0.6)), w=1.4)
    ctx.text("絲綢之路", proj(80, 44)[0], proj(80, 44)[1], "cjk", 18, "ink", 0.7 * eo(seg(lt, 1, 1.4)), track=6)


def art_paper(ctx, lt, p):
    cam = Cam(yaw=-32, pitch=30, dist=760, f=1000, cx=880, cy=470, target=(40, 50, 0))
    ctx.rays(880, 250, 60, 150, 800, 0.13, "ink", 0.7, a0=180, a1=360)
    faces = []
    faces.append(face([(-120, 0, -75), (120, 0, -75), (120, 0, 75), (-120, 0, 75)], fill="ink", fa=0.12, stroke=None))
    for f in box(-120, 0, -75, 120, 80, 75):
        faces.append(f)
    faces = faces[:-2] + [faces[-1]]
    ctx.mesh(cam, faces[:1])
    vat = box(-120, 0, -75, 120, 80, 75)
    back = [vat[1], vat[2]]  # far walls first (inner side)
    for f in back:
        ctx.poly(cam.pp(f["pts"]), fill="fill", stroke="ink", w=1.3, shade=0.2)
    water = cam.pp([(-120, 62, -75), (120, 62, -75), (120, 62, 75), (-120, 62, 75)])
    ctx.poly(water, fill=(150, 170, 170) if not ctx.dark else "fill", fa=0.35, stroke="ink", sa=0.6, w=1.0)
    for k in range(6):
        v = (k + 0.5) / 6
        ctx.line([ctx.bilinear(water, u, v + 0.02 * math.sin(u * 20 + lt * 4 + k)) for u in np.linspace(0.05, 0.95, 30)],
                 "ink", 0.25, 0.8)
    for f in (vat[0], vat[3]):
        ctx.poly(cam.pp(f["pts"]), fill="fill", stroke="ink", w=1.4, shade=f["shade"],
                 hatch=dict(gap=4, ang=90, a=0.3))
    rim = cam.pp([(-120, 80, -75), (120, 80, -75), (120, 80, 75), (-120, 80, 75)])
    ctx.line(rim, "ink", 1, 1.6, closed=True)
    lift = ease(seg(lt, 0.4, 1.6))
    y = lerp(58, 175, lift)
    tilt = 12 * (1 - lift)
    frame = [(-90, y - tilt, -55), (90, y + tilt, -55), (90, y + tilt, 55), (-90, y - tilt, 55)]
    fq = cam.pp(frame)
    ctx.poly(fq, fill=(240, 232, 214) if not ctx.dark else "fill", fa=0.97, stroke="ink", w=2.4)
    for k in range(1, 30):
        ctx.line([ctx.bilinear(fq, k / 30, 0), ctx.bilinear(fq, k / 30, 1)], "ink", 0.18, 0.6)
    for k in range(1, 4):
        ctx.line([ctx.bilinear(fq, 0, k / 4), ctx.bilinear(fq, 1, k / 4)], "ink", 0.5, 1.0)
    inner = [ctx.bilinear(fq, u, v) for u, v in ((0.04, 0.06), (0.96, 0.06), (0.96, 0.94), (0.04, 0.94))]
    ctx.poly(inner, fill=(247, 241, 226) if not ctx.dark else "fill", fa=0.75 * lift, stroke=None,
             hatch=dict(gap=2.5, ang=20, a=0.08 * lift))
    for d in range(10):  # drips
        u = 0.05 + 0.9 * rnd(d, 7)
        x0, y0 = ctx.bilinear(fq, u, 0.0)
        ph = (lt * 1.6 + rnd(d, 8)) % 1
        if lift > 0.1:
            ctx.line([(x0, y0 + ph * 60), (x0, y0 + ph * 60 + 8)], "ink", 0.5 * (1 - ph), 1.2)
    for i in range(12):  # finished sheets
        yy = i * 3.2 * eo(seg(lt, 0.2 + i * 0.05, 0.5 + i * 0.05))
        sheet = cam.pp([(170, yy, -60), (300, yy, -60), (300, yy, 60), (170, yy, 60)])
        ctx.poly(sheet, fill=(244, 238, 222) if not ctx.dark else "fill", stroke="ink", w=0.9)
    seal(ctx, *cam.p(235, 40, 0)[:2], 40, "紙", a=eo(seg(lt, 1.2, 1.5)))


def art_seismo(ctx, lt, p):
    cx, cy = 900, 380
    for rr, al in ((300, 0.25), (270, 0.4), (240, 0.2)):
        ctx.line(circle_pts(cx, cy + 20, rr, n=120), "ink", al, 1.0)
    for i, ch in enumerate("北東南西"):
        ang = math.radians(-90 + i * 90)
        ctx.text(ch, cx + 285 * math.cos(ang), cy + 20 + 285 * math.sin(ang) + 7, "cjk", 18, "ink", 0.6, align="center")
    for i in range(48):
        ang = math.radians(i * 7.5)
        ctx.line([(cx + 270 * math.cos(ang), cy + 20 + 270 * math.sin(ang)),
                  (cx + (262 if i % 2 else 254) * math.cos(ang), cy + 20 + (262 if i % 2 else 254) * math.sin(ang))],
                 "ink", 0.4, 0.8)
    pr = eo(seg(lt, 0, 0.8))
    base_y = cy + 150
    ctx.ellipse(cx, base_y + 6, 250, 50, fill="ink", fa=0.08, stroke="ink", a=0.35, w=1.0)
    prof = [(0, -210), (40, -205), (80, -185), (112, -150), (122, -118), (150, -60), (160, 0), (152, 60), (135, 110),
            (118, 150)]
    body = [(cx + x, cy + y) for x, y in prof] + [(cx - x, cy + y) for x, y in reversed(prof)]
    ctx.poly(body, fill="fill", stroke="ink", sa=pr, w=1.8)
    shade = [(cx + x, cy + y) for x, y in prof] + [(cx + x * 0.45, cy + y) for x, y in reversed(prof)]
    ctx.hatch_path(ctx.path(shade, True), gap=3.4, ang=80, a=0.35)
    for yy, rx in ((-150, 112), (-118, 122), (70, 150), (110, 135)):
        ctx.arc(cx, cy + yy, rx, 0, 180, "ink", 0.7 * pr, 1.1, ry=rx * 0.16)
    # the pendulum, in cutaway
    sw = 16 * math.sin(lt * 5) * (1 if lt < 1.0 else math.exp(-(lt - 1) * 2))
    ctx.line([(cx, cy - 150), (cx + sw, cy + 60)], "acc", 0.7, 1.2, dash=[5, 4])
    ctx.circle(cx + sw, cy + 70, 10, stroke="acc", a=0.7, w=1.2)
    # eight dragons and eight toads
    order = sorted(range(8), key=lambda i: math.cos(math.radians(i * 45 + 20)))
    for i in order:
        ang = math.radians(i * 45 + 20)
        depth = math.cos(ang)
        if depth < -0.35:
            continue
        s = 1.0 + 0.35 * depth
        dx = cx + 132 * math.sin(ang)
        dy = cy - 45
        sg = 1 if math.sin(ang) >= 0 else -1
        a = eo(seg(lt, 0.3 + i * 0.04, 0.6 + i * 0.04)) * (0.55 + 0.45 * (depth + 1) / 2)
        body_ = catmull([(dx - sg * 6 * s, dy - 120 * s), (dx + sg * 10 * s, dy - 95 * s), (dx - sg * 4 * s, dy - 60 * s),
                         (dx + sg * 12 * s, dy - 25 * s), (dx + sg * 26 * s, dy - 4 * s)], 8)
        ctx.line(body_, "ink", a, 9 * s)
        ctx.line(body_, "fill", a, 6 * s)
        for q in body_[2:-2:4]:
            ctx.line([(q[0] - 2.5 * s, q[1]), (q[0] + 2.5 * s, q[1])], "ink", 0.6 * a, 0.8)
        hx, hy = dx + sg * 30 * s, dy + 2 * s
        head = [(hx + sg * u * s, hy + v * s) for u, v in
                ((-12, -6), (-4, -11), (10, -9), (22, -5), (24, -1), (10, 1), (21, 6), (18, 10), (2, 10), (-10, 6))]
        ctx.poly(head, fill="fill", fa=a, stroke="ink", sa=a, w=1.3, hatch=dict(gap=2.6, ang=70, a=0.35 * a))
        ctx.circle(hx + sg * 3 * s, hy - 5 * s, 2 * s, fill="ink", fa=a, stroke=None)
        ctx.line([(hx - sg * 4 * s, hy - 10 * s), (hx - sg * 14 * s, hy - 22 * s), (hx - sg * 9 * s, hy - 24 * s)], "ink", a, 1.4)
        tx, ty = cx + 215 * math.sin(ang), base_y + 36 * depth
        ctx.ellipse(tx, ty, 30 * s, 17 * s, fill="fill", fa=a, stroke="ink", a=a, w=1.3,
                    hatch=dict(gap=3, ang=30, a=0.4 * a))
        for e in (-1, 1):
            ctx.circle(tx + e * 13 * s, ty - 13 * s, 4 * s, fill="fill", fa=a, stroke="ink", a=a, w=1)
        ctx.ellipse(tx, ty - 9 * s, 10 * s, 5 * s, fill="ink", fa=0.85 * a, stroke=None)
        falling = i == 1
        if falling:
            t = seg(lt, 1.0, 1.45)
            bx = lerp(hx + sg * 17 * s, tx, t)
            by = lerp(hy + 4 * s, ty - 10 * s, t * t)
            ctx.circle(bx, by, 7 * s, fill="acc", stroke="ink", a=a, w=1)
            if t >= 1:
                ctx.circle(tx, ty - 10 * s, 14 * s + 20 * seg(lt, 1.45, 1.9), stroke="acc", a=1 - seg(lt, 1.45, 1.9), w=1.5)
        else:
            ctx.circle(hx + sg * 17 * s, hy + 4 * s, 6.5 * s, fill="fill", fa=a, stroke="ink", a=a, w=1.2)



def quad_matrix(far_left, far_right, near_left):
    """Affine map from a 100x100 text box onto a projected quad (top edge = far edge)."""
    ax = ((far_right[0] - far_left[0]) / 100, (far_right[1] - far_left[1]) / 100)
    ay = ((near_left[0] - far_left[0]) / 100, (near_left[1] - far_left[1]) / 100)
    return skia.Matrix.MakeAll(ax[0], ay[0], far_left[0], ax[1], ay[1], far_left[1], 0, 0, 1)


def cyl_x(y, z, r, x0, x1, n=14, **kw):
    """A cylinder lying along the x axis."""
    out = []
    for i in range(n):
        a0, a1 = 2 * math.pi * i / n, 2 * math.pi * (i + 1) / n
        p0 = (y + r * math.cos(a0), z + r * math.sin(a0))
        p1 = (y + r * math.cos(a1), z + r * math.sin(a1))
        d = dict(kw)
        d["shade"] = d.get("shade", 0) + 0.2 * (0.5 - 0.5 * math.cos(a0))
        out.append(face([(x0, p0[0], p0[1]), (x1, p0[0], p0[1]), (x1, p1[0], p1[1]), (x0, p1[0], p1[1])], **d))
    for xe in (x0, x1):
        out.append(face([(xe, y + r * math.cos(2 * math.pi * i / n), z + r * math.sin(2 * math.pi * i / n))
                         for i in range(n)], **kw))
    return out


def soft_panel(ctx, x, y, w, h):
    """A soft wash of the background colour so a headline stays legible over a busy map."""
    col = ctx.pal["fill"] if not ctx.dark else (12, 14, 22)
    shader = skia.GradientShader.MakeRadial(skia.Point(x + w / 2, y + h / 2), max(w, h) * 0.6,
                                            [skia.ColorSetARGB(215, *col), skia.ColorSetARGB(0, *col)], [0.55, 1.0])
    ctx.c.save()
    ctx.c.translate(x + w / 2, y + h / 2)
    ctx.c.scale(1, h / w)
    ctx.c.translate(-(x + w / 2), -(y + h / 2))
    ctx.c.drawCircle(x + w / 2, y + h / 2, max(w, h) * 0.6, skia.Paint(AntiAlias=True, Shader=shader))
    ctx.c.restore()


# --- V · Tang ----------------------------------------------------------------
def art_changan(ctx, lt, p):
    cam = Cam(yaw=-20, pitch=38, dist=2500, f=1150, cx=880, cy=470)
    xs = np.linspace(-485, 485, 12)
    zs = np.linspace(-430, 330, 12)
    faces = []
    grow = lt / 1.2
    for i in range(len(xs) - 1):
        for j in range(len(zs) - 1):
            x0, x1 = xs[i] + 7, xs[i + 1] - 7
            z0, z1 = zs[j] + 7, zs[j + 1] - 7
            if abs((x0 + x1) / 2) < 60:
                continue  # Zhuque Avenue
            d = math.hypot((x0 + x1) / 2, (z0 + z1) / 2) / 650
            h = 9 * eo(seg(grow, d * 0.8, d * 0.8 + 0.3))
            if h <= 0.2:
                continue
            market = (i, j) in ((2, 5), (8, 5))
            hatch = dict(gap=3, ang=45, a=0.5) if market else (dict(gap=4, ang=0, a=0.18) if rnd(i * 13 + j, 4) > 0.6 else None)
            fb = box(x0, 0, z0, x1, h, z1, w=0.9)
            fb[4]["hatch"] = hatch
            fb[4]["fill"] = "acc" if market else "fill"
            fb[4]["fa"] = 0.35 if market else 1
            faces += fb
    ph = 30 * eo(seg(lt, 0.6, 1.2))
    if ph > 0.5:
        faces += box(-150, 0, 340, 150, ph, 430, w=1.3, hatch=dict(gap=3, ang=90, a=0.35))
        faces += box(-60, ph, 370, 60, ph + 14 * eo(seg(lt, 0.9, 1.3)), 410, w=1.2, fill="acc", fa=0.5)
    wall = []
    for (x0, z0), (x1, z1) in (((-495, -440), (495, -440)), ((495, -440), (495, 440)), ((495, 440), (-495, 440)),
                               ((-495, 440), (-495, -440))):
        wall.append(face([(x0, 0, z0), (x1, 0, z1), (x1, 16, z1), (x0, 16, z0)], w=1.4, shade=0.1,
                         hatch=dict(gap=2.5, ang=0, a=0.4)))
    ctx.mesh(cam, wall[2:3] + wall[1:2] + wall[3:4])
    ctx.mesh(cam, faces)
    ctx.mesh(cam, wall[0:1])
    av = [cam.p(0, 1, z)[:2] for z in np.linspace(-440, 340, 40)]
    ctx.line(av, "acc", 1, 3.0, prog=eo(seg(lt, 0.2, 1.0)))
    for k in range(14):  # travellers on the avenue
        z = -440 + ((lt * 60 + k * 60) % 780)
        x, y, _ = cam.p(-20 + 40 * rnd(k, 2), 2, z)
        ctx.circle(x, y, 2.2, fill="ink", fa=0.8, stroke=None)
    gx, gy, _ = cam.p(0, 30, -440)
    ctx.text("長安", gx, gy + 60, "cjk", 30, "acc", eo(seg(lt, 1.0, 1.4)), track=10, align="center")


POEM = ["床前明月光", "疑是地上霜", "举头望明月", "低头思故乡"]
POEM_EN = ["Before my bed, the moonlight gleams —", "I thought it frost upon the ground.",
           "I raise my head to see the moon,", "then bow it low, and think of home."]


def art_poem(ctx, lt, p):
    mx, my, mr = 1030, 215, 105
    ctx.rays(mx, my, 48, mr + 16, mr + 170, 0.2, "ink", 0.7)
    ctx.circle(mx, my, mr, fill="fill", stroke="ink", w=1.6)
    cres = skia.Path()
    cres.addCircle(mx, my, mr)
    cut = skia.Path()
    cut.addCircle(mx - 38, my - 14, mr)
    ctx.hatch_path(skia.Op(cres, cut, skia.PathOp.kDifference_PathOp), gap=3, ang=60, a=0.5)
    for k in range(5):
        ctx.ellipse(mx - 30 + 55 * rnd(k, 1), my - 40 + 70 * rnd(k, 2), 8 + 10 * rnd(k, 3), 6 + 7 * rnd(k, 4),
                    stroke="ink", a=0.35, w=0.8)
    n = 0
    for c, col in enumerate(POEM):
        for j, ch in enumerate(col):
            t0 = 0.25 + n * 0.07
            n += 1
            a = eo(seg(lt, t0, t0 + 0.2))
            x = 1180 - c * 62
            y = 385 + j * 54
            ctx.text(ch, x, y + (1 - a) * 6, "brush", 50, "ink", a, align="center", blur=(1 - a) * 3)
    seal(ctx, 930, 640, 34, "李白", a=eo(seg(lt, 1.8, 2.1)))
    for i, line in enumerate(POEM_EN):
        a = eo(seg(lt, 0.4 + i * 0.35, 0.8 + i * 0.35))
        ctx.text(line, 92, 400 + i * 34, "italic", 25, "text", 0.85 * a)


def art_diamond(ctx, lt, p):
    un = eo(seg(lt, 0.1, 1.4))
    x0, y0, y1 = 470, 300, 520
    x1 = lerp(x0 + 40, 1260, un)
    ctx.poly([(x0 + 8, y0 + 10), (x1 + 8, y0 + 10), (x1 + 8, y1 + 10), (x0 + 8, y1 + 10)], fill="ink", fa=0.12, stroke=None)
    ctx.poly([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], fill=(238, 226, 196) if not ctx.dark else "fill", stroke="ink", w=1.4)
    ctx.line([(x0, y0 + 10), (x1, y0 + 10)], "ink", 0.6, 0.8)
    ctx.line([(x0, y1 - 10), (x1, y1 - 10)], "ink", 0.6, 0.8)
    ctx.c.save()
    ctx.c.clipRect(skia.Rect.MakeLTRB(x0, y0, x1, y1))
    fx0, fx1 = x0 + 20, x0 + 250
    ctx.poly([(fx0, y0 + 20), (fx1, y0 + 20), (fx1, y1 - 20), (fx0, y1 - 20)], fill=None, stroke="ink", w=1.1)
    bx, by = (fx0 + fx1) / 2, y0 + 120
    for r in (58, 44):
        ctx.circle(bx, by - 12, r, stroke="ink", a=0.6, w=0.9)
    ctx.rays(bx, by - 12, 36, 60, 90, 0.35, "ink", 0.6)
    ctx.circle(bx, by - 30, 13, fill="fill", stroke="ink", w=1.2)
    ctx.poly([(bx - 34, by + 38), (bx - 20, by - 14), (bx + 20, by - 14), (bx + 34, by + 38)], fill="fill", stroke="ink",
             w=1.2, hatch=dict(gap=3, ang=80, a=0.4))
    for k in range(7):
        ctx.arc(bx - 42 + k * 14, by + 50, 9, 180, 180, "ink", 0.8, 1.0)
    ctx.poly([(bx - 70, by - 84), (bx + 70, by - 84), (bx + 55, by - 72), (bx - 55, by - 72)], fill="acc", fa=0.4,
             stroke="ink", w=1.0)
    for side in (-1, 1):
        for k in range(3):
            fx = bx + side * (75 + k * 0)
            fy = by + 30 - k * 40
            ctx.circle(fx, fy, 7, stroke="ink", a=0.7, w=0.9)
            ctx.line([(fx, fy + 7), (fx, fy + 24)], "ink", 0.7, 1.0)
    sutra = "如是我聞一時佛在舍衛國祇樹給孤獨園與大比丘眾千二百五十人俱爾時世尊食時著衣持鉢入舍衛大城乞食於其城中次第乞已還至本處飯食訖收衣鉢洗足已敷座而坐"
    cols = int((x1 - fx1 - 30) / 22)
    for c in range(max(cols, 0)):
        cx = fx1 + 24 + c * 22
        for j in range(9):
            ch = sutra[(c * 9 + j) % len(sutra)]
            ctx.text(ch, cx, y0 + 40 + j * 20, "cjk", 15, "ink", 0.8, align="center")
    ctx.c.restore()
    if un >= 1:
        a = eo(seg(lt, 1.4, 1.7))
        for j, ch in enumerate("咸通九年四月十五日"):
            ctx.text(ch, 1236, y0 + 36 + j * 20, "cjk", 15, "acc", a, align="center")
    r = 24 * (1 - un) + 10
    ctx.poly([(x1 - r / 2, y0 - 8), (x1 + r / 2, y0 - 8), (x1 + r / 2, y1 + 8), (x1 - r / 2, y1 + 8)], fill="fill",
             stroke="ink", w=1.4, hatch=dict(gap=2.5, ang=90, a=0.5))
    cam = Cam(yaw=-30, pitch=40, dist=700, f=900, cx=620, cy=600)
    ctx.mesh(cam, box(-90, 0, -40, 90, 22, 40, hatch=dict(gap=3, ang=0, a=0.25)))
    top = cam.pp([(-80, 22, 32), (80, 22, 32), (-80, 22, -32)])
    ctx.c.save()
    ctx.c.concat(quad_matrix(*top))
    for c in range(8):
        for j in range(4):
            ctx.text(sutra[c * 4 + j][::-1], 8 + c * 12, 24 + j * 22, "cjk", 16, "ink", 0.75)
    ctx.c.restore()


# --- VI · Song ---------------------------------------------------------------
QIANZI = "天地玄黃宇宙洪荒日月盈昃辰宿列張寒來暑往秋收冬藏閏餘成歲律呂調陽雲騰致雨露結為霜"


def art_movable(ctx, lt, p):
    cam = Cam(yaw=-22, pitch=48, dist=900, f=1050, cx=880, cy=420)
    ctx.mesh(cam, box(-190, -12, -120, 190, 0, 120, hatch=dict(gap=4, ang=0, a=0.25)))
    blocks = []
    for r in range(5):
        for c in range(8):
            i = r * 8 + c
            t0 = 0.1 + (i * 7 % 40) * 0.03
            drop = 160 * (1 - eo(seg(lt, t0, t0 + 0.35)))
            if lt < t0:
                continue
            x0, z0 = -176 + c * 44, 76 - r * 44 + 0
            blocks.append((cam.p(x0 + 20, drop, z0 + 20)[2], i, x0, z0, drop))
    blocks.sort(key=lambda b: -b[0])
    for _, i, x0, z0, drop in blocks:
        hot = i == 18
        fb = box(x0, drop, z0, x0 + 40, drop + 24, z0 + 40, w=1.1)
        fb[4]["fill"] = "acc" if hot else "fill"
        fb[4]["fa"] = 0.85 if hot else 1
        ctx.mesh(cam, fb)
        top = cam.pp([(x0, drop + 24, z0 + 40), (x0 + 40, drop + 24, z0 + 40), (x0, drop + 24, z0)])
        ctx.c.save()
        ctx.c.concat(quad_matrix(*top))
        ctx.text(QIANZI[i], 50, 80, "cjk", 70, (250, 240, 228) if hot else "ink", 0.95, align="center")
        ctx.c.restore()


def art_firearrow(ctx, lt, p):
    traj = bez((480, 640), (800, 170), (1330, 330), n=60)
    ctx.line(traj, "ink", 0.35, 1.0, dash=[6, 7])
    t = ease(seg(lt, 0.1, 2.3)) * 0.8
    trail = trim(traj, t)
    for k in range(18):  # smoke puffs
        u = t - k * 0.02
        if u <= 0:
            break
        x, y = point_at(traj, u)
        r = 6 + k * 1.6
        ctx.circle(x + 3 * math.sin(k * 2 + lt), y + k * 0.8, r, fill="fill", fa=0.9, stroke="ink", a=0.3 * (1 - k / 18),
                   w=0.8, hatch=dict(gap=3, ang=45, a=0.12 * (1 - k / 18)))
    x, y = trail[-1]
    x2, y2 = point_at(traj, max(t - 0.01, 0))
    ang = math.degrees(math.atan2(y - y2, x - x2))
    ctx.c.save()
    ctx.c.translate(x, y)
    ctx.c.rotate(ang)
    ctx.c.scale(1.5, 1.5)
    for k in range(10):
        fx = -60 - k * 6
        ctx.circle(fx, 7 * math.sin(lt * 40 + k), 3 + k * 0.7, fill="acc", fa=0.6 * (1 - k / 10), stroke=None)
    ctx.line([(-150, 0), (40, 0)], "ink", 1, 2.0)
    ctx.poly([(40, -6), (58, 0), (40, 6)], fill="ink", stroke=None)
    for s in (-1, 1):
        ctx.poly([(-150, 0), (-128, 0), (-138, 10 * s), (-160, 10 * s)], fill="fill", stroke="ink", w=1.0,
                 hatch=dict(gap=2, ang=0, a=0.6))
    ctx.poly([(-55, -8), (5, -8), (5, 8), (-55, 8)], fill="fill", stroke="ink", w=1.4, hatch=dict(gap=3, ang=90, a=0.5))
    ctx.line([(-35, -8), (-35, 8)], "acc", 1, 2)
    ctx.line([(-15, -8), (-15, 8)], "acc", 1, 2)
    ctx.c.restore()
    for i, (ch, cx, cy) in enumerate([("硝", 160, 560), ("硫", 250, 560), ("炭", 340, 560)]):
        a = eo(seg(lt, 0.5 + i * 0.12, 0.8 + i * 0.12))
        ctx.circle(cx, cy, 30, fill="fill", fa=a, stroke="ink", a=a, w=1.3)
        ctx.text(ch, cx, cy + 9, "cjk", 26, "ink", a, align="center")
        ctx.line([(cx, cy + 30), (250, 630)], "ink", 0.5 * a, 1.0)
    a = eo(seg(lt, 0.9, 1.2))
    ctx.circle(250, 648, 18, fill="acc", fa=0.85 * a, stroke=None)
    ctx.text("火藥", 290, 655, "cjk", 18, "acc", a)


def person(ctx, x, y, s, a=1.0, hat=True, pose=0.0):
    ctx.circle(x, y - 17 * s, 3.2 * s, fill="fill", fa=a, stroke="ink", a=a, w=0.9)
    if hat:
        ctx.line([(x - 6 * s, y - 19 * s), (x + 6 * s, y - 19 * s)], "ink", a, 1.3)
    ctx.poly([(x - 4 * s, y - 13 * s), (x + 4 * s, y - 13 * s), (x + 5 * s, y), (x - 5 * s, y)], fill="fill", fa=a,
             stroke="ink", sa=a, w=0.9, hatch=dict(gap=2, ang=70, a=0.4 * a))
    ctx.line([(x - 2 * s, y), (x - 3 * s + pose * s, y + 5 * s)], "ink", a, 1)
    ctx.line([(x + 2 * s, y), (x + 3 * s - pose * s, y + 5 * s)], "ink", a, 1)


def art_bridge(ctx, lt, p):
    pan = -50 * ease(p)
    ctx.c.save()
    ctx.c.translate(pan, 0)
    for k in range(9):  # the river
        yy = 520 + k * 14
        ctx.line([(x, yy + 3 * math.sin(x * 0.03 + lt * 2 + k)) for x in range(380, 1400, 12)], "ink", 0.25, 0.8)
    for side in (-1, 1):
        bx = 900 + side * 360
        ctx.poly([(bx - side * 40, 470), (bx + side * 400, 470), (bx + side * 400, 520), (bx - side * 10, 520)], fill="fill",
                 stroke="ink", w=1.2, hatch=dict(gap=4, ang=0, a=0.3))
        for tr in range(2):  # willows
            tx = bx + side * (80 + tr * 110)
            ctx.line(catmull([(tx, 470), (tx - 6, 420), (tx + 4, 370), (tx - 2, 330)], 6), "ink", 1, 3)
            for s in range(14):
                sx = tx - 50 + s * 8
                ctx.line(catmull([(sx, 330 + 10 * math.sin(s)), (sx - 4, 380), (sx + 3 * math.sin(lt * 2 + s), 430)], 6),
                         "ink", 0.5, 0.9)
    for i, (hx, hw, hh) in enumerate([(430, 70, 60), (510, 60, 48), (1330, 80, 64), (1410, 60, 50)]):  # houses
        ctx.poly([(hx - hw / 2, 470), (hx + hw / 2, 470), (hx + hw / 2, 470 - hh), (hx - hw / 2, 470 - hh)], fill="fill",
                 stroke="ink", w=1.2, hatch=dict(gap=3, ang=90, a=0.3))
        ctx.poly([(hx - hw / 2 - 14, 470 - hh), (hx + hw / 2 + 14, 470 - hh), (hx + hw / 2 - 4, 470 - hh - 26),
                  (hx - hw / 2 + 4, 470 - hh - 26)], fill="fill", stroke="ink", w=1.3, hatch=dict(gap=3, ang=0, a=0.5))
        ctx.poly([(hx - 8, 470), (hx + 8, 470), (hx + 8, 470 - hh * 0.55), (hx - 8, 470 - hh * 0.55)], fill="ink",
                 fa=0.6, stroke=None)
    arch = [(900 + 290 * math.cos(math.radians(a)), 505 - 170 * math.sin(math.radians(a))) for a in range(180, -1, -5)]
    for k in range(4):
        ctx.line([(x, y + k * 9) for x, y in arch], "ink", 1 if k in (0, 3) else 0.6, 1.4 if k in (0, 3) else 0.9,
                 prog=eo(seg(lt, 0, 0.8)))
    for i in range(1, len(arch) - 1, 1):
        x, y = arch[i]
        ctx.line([(x, y), (x + (6 if i % 2 else -6), y + 27)], "ink", 0.7, 1.0)
    deck = [(x, y - 16) for x, y in arch]
    ctx.line(deck, "ink", 1, 1.3)
    for i in range(0, len(deck), 2):
        x, y = deck[i]
        ctx.line([(x, y), (x, y + 16)], "ink", 0.8, 1.0)
    for k in range(9):
        u = ((k * 0.11 + lt * (0.05 if k % 2 else -0.04)) % 0.8) + 0.1
        x, y = point_at(deck, u)
        person(ctx, x, y, 1.1, pose=math.sin(lt * 8 + k))
    bxp = 640 + 120 * ease(p)
    hull = catmull([(bxp - 120, 540), (bxp - 90, 568), (bxp + 80, 572), (bxp + 130, 545)], 8)
    ctx.poly(hull + [(bxp + 120, 535), (bxp - 110, 532)], fill="fill", stroke="ink", w=1.5, hatch=dict(gap=3, ang=0, a=0.4))
    ctx.poly([(bxp - 60, 532), (bxp + 60, 532), (bxp + 50, 500), (bxp - 50, 500)], fill="fill", stroke="ink", w=1.2,
             hatch=dict(gap=3, ang=90, a=0.35))
    mast = 60 + 25 * ease(p)
    ctx.line([(bxp, 500), (bxp + 150 * math.cos(math.radians(mast)), 500 - 150 * math.sin(math.radians(mast)))], "ink", 1, 2.2)
    for k in range(3):
        person(ctx, bxp - 70 + k * 60, 530, 1.1)
    ctx.c.restore()
    for yy in (215, 668):  # scroll borders
        ctx.line([(0, yy), (W, yy)], "ink", 0.7, 1.2)
        ctx.line([(0, yy + (6 if yy < 400 else -6)), (W, yy + (6 if yy < 400 else -6))], "ink", 0.4, 0.8)


# --- VII · Ming --------------------------------------------------------------
def junk(ctx, x, y, s, lt, a=1.0, sails=True):
    """A Ming treasure ship, bow to the left."""
    ctx.c.save()
    ctx.c.translate(x, y)
    ctx.c.rotate(1.2 * math.sin(lt * 1.6))
    ctx.c.scale(s, s)
    hull = catmull([(-265, -45), (-150, -22), (0, -25), (150, -45), (240, -95), (262, -118)], 8) + \
        [(268, -30)] + catmull([(250, 20), (100, 38), (-120, 34), (-240, 15)], 8)
    ctx.poly(hull, fill="fill", fa=a, stroke="ink", sa=a, w=2.0, hatch=dict(gap=4, ang=0, a=0.35 * a))
    for k in range(5):
        yy = -10 + k * 9
        ctx.line([(-230 + k * 8, yy), (240 - k * 6, yy - 20 + k * 6)], "ink", 0.35 * a, 0.9)
    ctx.poly([(150, -45), (240, -95), (245, -140), (150, -85)], fill="fill", fa=a, stroke="ink", sa=a, w=1.6,
             hatch=dict(gap=3, ang=90, a=0.4 * a))
    ctx.circle(-225, -22, 8, fill="acc", fa=0.8 * a, stroke="ink", a=a, w=1)
    if sails:
        for i, (mx, mh, sw) in enumerate([(-200, 200, 70), (-110, 290, 95), (-10, 320, 105), (90, 280, 95), (175, 190, 70)]):
            ctx.line([(mx, -25), (mx, -25 - mh)], "ink", a, 2.4)
            top, bot = -25 - mh + 10, -60
            sail = [(mx - sw * 0.35, top), (mx + sw * 0.75, top + 20), (mx + sw * 0.85, bot), (mx - sw * 0.45, bot)]
            ctx.poly(sail, fill=(222, 180, 150) if not ctx.dark else "fill", fa=0.95 * a, stroke="ink", sa=a, w=1.4)
            for b in range(1, 8):
                v = b / 8
                ctx.line([ctx.bilinear(sail, 0, v), ctx.bilinear(sail, 1, v)], "ink", 0.7 * a, 1.0)
            ctx.poly([(mx, -25 - mh), (mx + 26, -25 - mh + 6 + 3 * math.sin(lt * 6 + i)), (mx, -25 - mh + 12)],
                     fill="acc", fa=a, stroke=None)
    ctx.c.restore()


def waves(ctx, y0, lt, n=6, a=0.5, x0=0, x1=W):
    for k in range(n):
        yy = y0 + k * 16
        ctx.line([(x, yy + 5 * math.sin(x * 0.025 + lt * 2.5 + k * 1.3)) for x in range(x0, x1 + 10, 10)], "ink",
                 a * (1 - k / (n + 2)), 1.0)


def art_1405(ctx, lt, p):
    a = eo(seg(lt, 0.05, 0.35))
    sc = 1 + 0.15 * (1 - a)
    ctx.c.save()
    ctx.c.translate(860, 330)
    ctx.c.scale(sc, sc)
    ctx.text("1405", 0, 110, "display", 300, "acc", 0.9 * a, track=4, align="center")
    ctx.c.restore()
    x = lerp(1050, 860, ease(p))
    junk(ctx, x, 540, 0.95, lt, eo(seg(lt, 0.3, 0.8)))
    waves(ctx, 555, lt, 8, 0.6, 380, W)


ZHENGHE = [("NANJING", 118.8, 32.1), ("CHANGLE", 119.5, 25.9), ("CHAMPA", 109.2, 13.8), ("MALACCA", 102.25, 2.2),
           ("SEMUDERA", 97.1, 5.2), ("CEYLON", 80.2, 6.0), ("CALICUT", 75.8, 11.25), ("HORMUZ", 56.4, 27.1),
           ("ADEN", 45.0, 12.8), ("MOGADISHU", 45.3, 2.0), ("MALINDI", 40.1, -3.2)]


def art_zhenghe(ctx, lt, p):
    proj = MapProj(80, 12, 10.5, 820, 400)
    draw_map(ctx, proj, eo(seg(lt, 0, 0.7)))
    pts = route(ctx, proj, ZHENGHE, lt, 0.4, 2.2, dash=[7, 5])
    for k in range(3):
        u = clamp(ease(seg(lt, 0.4, 2.2)) - k * 0.05)
        if u > 0.02:
            x, y = point_at(pts, u)
            ctx.c.save()
            ctx.c.translate(x, y)
            ctx.c.scale(-1, 1)
            junk(ctx, 0, -2, 0.06, lt, 1.0)
            ctx.c.restore()
    soft_panel(ctx, 40, 90, 640, 260)


GIRAFFE = [(745, 188), (760, 172), (784, 166), (800, 172), (806, 186), (820, 215), (840, 262), (862, 310), (884, 345),
           (920, 352), (960, 366), (1000, 380), (1016, 392), (1020, 418), (1012, 440), (1006, 470), (1000, 520), (996, 580),
           (998, 630), (1004, 642), (990, 642), (986, 630), (984, 580), (986, 520), (988, 470), (975, 448), (900, 452),
           (892, 480), (888, 540), (886, 600), (888, 640), (876, 642), (872, 630), (872, 580), (870, 520), (866, 470),
           (858, 440), (846, 400), (830, 350), (812, 300), (792, 250), (776, 212), (766, 200), (752, 202), (745, 195)]


def art_giraffe(ctx, lt, p):
    ctx.rays(880, 300, 70, 160, 800, 0.15, "ink", 0.7)
    for k in range(3):  # auspicious clouds
        cx, cy = 640 + k * 280, 600 + 20 * (k % 2)
        for j in range(3):
            ctx.line(catmull([(cx - 40 + j * 30 + 12 * math.cos(t), cy - 12 * math.sin(t)) for t in np.linspace(0, 5, 8)], 5),
                     "ink", 0.4, 1.0)
    dx = 20 * ease(p)
    pts = [(x + dx, y) for x, y in GIRAFFE]
    pr = eo(seg(lt, 0, 1.0))
    for off in ((16, 0),):  # far legs
        for lx in (880, 1000):
            ctx.poly([(lx + off[0] + dx, 450), (lx + off[0] + 12 + dx, 450), (lx + off[0] + 10 + dx, 640), (lx + off[0] + dx, 640)],
                     fill="fill", fa=pr, stroke="ink", sa=pr, w=1.2, hatch=dict(gap=3, ang=45, a=0.5 * pr))
    body = ctx.path(pts, True)
    ctx.poly(pts, fill="fill", fa=pr, stroke=None)
    ctx.c.save()
    ctx.c.clipPath(body, doAntiAlias=True)
    for gx in range(700, 1060, 24):
        for gy in range(150, 660, 24):
            jx, jy = 6 * (rnd(gx, gy) - 0.5), 6 * (rnd(gy, gx) - 0.5)
            q = [(gx + dx + jx + 3, gy + jy + 3), (gx + dx + jx + 20, gy + jy + 4), (gx + dx + jx + 19, gy + jy + 20),
                 (gx + dx + jx + 4, gy + jy + 19)]
            ctx.poly(q, fill=(176, 104, 60) if not ctx.dark else "ink", fa=0.55 * pr, stroke=None)
    ctx.c.restore()
    ctx.line(pts, "ink", 1, 1.8, prog=pr, closed=True)
    for ox in (0, 12):  # ossicones
        ctx.line([(778 + ox + dx, 168), (774 + ox + dx, 148)], "ink", pr, 2.2)
        ctx.circle(774 + ox + dx, 146, 3.5, fill="ink", fa=pr, stroke=None)
    ctx.circle(772 + dx, 180, 3, fill="ink", fa=pr, stroke=None)
    ctx.line([(1016 + dx, 395), (1040 + dx, 430), (1044 + dx, 500)], "ink", pr, 1.6)
    ctx.poly([(1040 + dx, 498), (1050 + dx, 498), (1046 + dx, 520)], fill="ink", fa=pr, stroke=None)
    for i in range(4):  # the mane
        ctx.line([(810 + i * 18 + dx, 200 + i * 38), (822 + i * 18 + dx, 196 + i * 38)], "ink", pr, 1.4)
    seal(ctx, 690 + dx, 250, 50, "麒麟", a=eo(seg(lt, 1.1, 1.4)))


def art_porcelain(ctx, lt, p):
    cx, base = 900, 640
    blue = ctx.pal["blue"]
    prof = [(38, 0), (46, 10), (62, 60), (88, 150), (112, 230), (126, 290), (120, 330), (96, 368), (58, 392), (34, 402),
            (30, 418), (38, 432), (36, 438)]
    s = 1.0
    right = [(cx + r * s, base - y * s) for r, y in prof]
    left = [(cx - r * s, base - y * s) for r, y in reversed(prof)]
    shape = right + left
    ctx.rays(cx, base - 250, 60, 180, 800, 0.14, "ink", 0.7)
    ctx.ellipse(cx + 10, base + 4, 90, 12, fill="ink", fa=0.15, stroke=None)
    ctx.poly(shape, fill=(242, 240, 232) if not ctx.dark else "fill", stroke="ink", w=1.8)
    body = ctx.path(shape, True)
    ctx.c.save()
    ctx.c.clipPath(body, doAntiAlias=True)
    pr = eo(seg(lt, 0.2, 1.4))
    for y, r in ((60, 62), (150, 88), (300, 124), (368, 96)):
        ctx.arc(cx, base - y, r + 4, 0, 180, blue, 0.9 * pr, 2.0, ry=(r + 4) * 0.12)
    for k in range(10):  # lotus panels at the foot
        ang = -80 + k * 18
        x = cx + 75 * math.sin(math.radians(ang))
        ctx.line(catmull([(x - 12, base - 62), (x - 10, base - 110), (x, base - 138), (x + 10, base - 110), (x + 12, base - 62)], 6),
                 blue, 0.9 * pr, 1.6)
    # a dragon among clouds on the belly
    dr = [(cx - 120 + t * 240, base - 220 + 35 * math.sin(t * 9 + 0.5)) for t in np.linspace(0, 1, 60)]
    ctx.line(dr, blue, pr, 7)
    ctx.line(dr, (242, 240, 232) if not ctx.dark else "fill", pr, 3)
    for k in range(6):
        u = k / 5
        x, y = dr[int(u * 59)]
        ctx.line([(x, y - 4), (x - 10, y - 22)], blue, pr, 1.6)
        ctx.line([(x, y + 4), (x - 8, y + 20)], blue, pr, 1.6)
    ctx.circle(dr[-1][0], dr[-1][1], 10, fill=blue, fa=pr, stroke=None)
    for k in range(5):
        cx2, cy2 = cx - 90 + k * 45, base - 270 + (k % 2) * 110
        ctx.line([(cx2 + 10 * math.cos(t) * (1 - t / 12), cy2 + 8 * math.sin(t) * (1 - t / 12)) for t in np.linspace(0, 10, 30)],
                 blue, 0.8 * pr, 1.4)
    ctx.hatch_path(ctx.path([(cx + 40, base), (cx + 200, base), (cx + 200, base - 440), (cx + 40, base - 440)], True),
                   gap=3.5, ang=90, col=blue, a=0.18)
    ctx.c.restore()
    ctx.line(shape, "ink", 1, 1.8, closed=True)


def art_forbidden(ctx, lt, p):
    cam = Cam(yaw=-22, pitch=12, dist=1150, f=2050, cx=860, cy=470, target=(0, 70, 0))
    ctx.rays(870, 330, 80, 250, 900, 0.14, "ink", 0.7, a0=180, a1=360)
    g = lambda a_, b_: eo(seg(lt, a_, b_))
    faces = []
    for i, (w_, d_, y0) in enumerate(((150, 90, 0), (135, 80, 12), (120, 70, 24))):
        h = 12 * g(i * 0.15, i * 0.15 + 0.3)
        if h > 0.3:
            faces += box(-w_, y0, -d_, w_, y0 + h, d_, w=1.2, fill=(236, 232, 222) if not ctx.dark else "fill",
                         hatch=dict(gap=3, ang=0, a=0.25))
    ctx.mesh(cam, faces)
    for i, (w_, d_, y0) in enumerate(((150, 90, 0), (135, 80, 12), (120, 70, 24))):  # balustrades
        if g(i * 0.15, i * 0.15 + 0.3) >= 1:
            for k in range(25):
                x = -w_ + k * w_ * 2 / 24
                ctx.line([cam.p(x, y0 + 12, -d_)[:2], cam.p(x, y0 + 17, -d_)[:2]], "ink", 0.8, 1.0)
            ctx.line([cam.p(-w_, y0 + 17, -d_)[:2], cam.p(w_, y0 + 17, -d_)[:2]], "ink", 0.8, 1.0)
    hb = g(0.45, 0.8)
    if hb > 0:
        faces = box(-70, 36, -36, 70, 36 + 38 * hb, 36, fill="acc", fa=0.85, w=1.3)
        front = faces[0]

        def cols(ctx_, q):
            for k in range(1, 11):
                ctx_.line([ctx_.bilinear(q, k / 11, 0), ctx_.bilinear(q, k / 11, 1)], "ink", 0.7, 1.2)
            for k in range(3, 8):
                a0 = ctx_.bilinear(q, k / 11 + 0.01, 0.05)
                ctx_.poly([a0, ctx_.bilinear(q, (k + 1) / 11 - 0.01, 0.05), ctx_.bilinear(q, (k + 1) / 11 - 0.01, 0.8),
                           ctx_.bilinear(q, k / 11 + 0.01, 0.8)], fill=None, stroke="ink", sa=0.6, w=0.8,
                          hatch=dict(gap=2.5, ang=90, a=0.35))
        front["deco"] = cols
        ctx.mesh(cam, faces)
    rg = g(0.7, 1.1)
    if rg > 0:
        y1 = 74
        yl = y1 + 14 * rg
        low = [face([(-70, y1, -36), (70, y1, -36), (92, y1 - 8, -52), (-92, y1 - 8, -52)]),
               face([(70, y1, -36), (70, y1, 36), (92, y1 - 8, 52), (92, y1 - 8, -52)]),
               face([(-70, y1, -36), (-92, y1 - 8, -52), (-92, y1 - 8, 52), (-70, y1, 36)])]
        roof_col = (212, 160, 60) if not ctx.dark else "fill"
        for f in low:
            f["fill"] = roof_col
            f["hatch"] = dict(gap=3, ang=90, a=0.45)
        ctx.mesh(cam, low)
        up = box(-60, y1, -28, 60, yl, 28, fill="acc", fa=0.85, w=1.2)
        ctx.mesh(cam, up)
        top_y = yl + 36 * rg
        ridge = 44
        e = yl - 6
        roof = [face([(-86, e, -46), (86, e, -46), (ridge, top_y, 0), (-ridge, top_y, 0)], shade=0.0),
                face([(86, e, -46), (86, e, 46), (ridge, top_y, 0)], shade=0.12),
                face([(-86, e, -46), (-ridge, top_y, 0), (-86, e, 46)], shade=0.12),
                face([(86, e, 46), (-86, e, 46), (-ridge, top_y, 0), (ridge, top_y, 0)], shade=0.2)]
        for f in roof:
            f["fill"] = roof_col
            f["hatch"] = dict(gap=3, ang=90, a=0.45)
        ctx.mesh(cam, roof)
        for sx, sz in ((-86, -46), (86, -46), (86, 46), (-86, 46), (-92, -52), (92, -52)):
            yy = e if abs(sx) == 86 else y1 - 8
            a0 = cam.p(sx, yy, sz)
            a1 = cam.p(sx * 1.08, yy + 9, sz * 1.1)
            ctx.line([a0[:2], a1[:2]], "ink", 1, 2.0)
        ctx.line([cam.p(-ridge, top_y, 0)[:2], cam.p(ridge, top_y, 0)[:2]], "ink", 1, 3.0)
        for sx in (-ridge, ridge):
            q = cam.p(sx, top_y, 0)
            ctx.poly([(q[0] - 5, q[1]), (q[0] + 5, q[1]), (q[0] + 3, q[1] - 14), (q[0] - 4, q[1] - 10)], fill="ink", stroke=None)
    stair = [cam.p(-18, 36, -70)[:2], cam.p(18, 36, -70)[:2], cam.p(18, 0, -118)[:2], cam.p(-18, 0, -118)[:2]]
    ctx.poly(stair, fill="fill", stroke="ink", w=1.2, hatch=dict(gap=3, ang=0, a=0.5))


# --- VIII · Night ------------------------------------------------------------
def gate(ctx, lt, openness, light):
    """A palace gate; openness 0 (shut) .. 1 (wide open)."""
    x0, x1, y0, y1 = 830, 1190, 210, 630
    cx = (x0 + x1) / 2
    wall = [(x0 - 50, y0 - 60), (x1 + 50, y0 - 60), (x1 + 50, y1), (x0 - 50, y1)]
    ctx.poly(wall, fill=(150, 40, 30) if not ctx.dark else (60, 18, 14), fa=0.9, stroke="ink", w=1.5,
             hatch=dict(gap=4, ang=0, a=0.2))
    ctx.poly([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], fill=(250, 238, 200) if not ctx.dark else (255, 205, 120),
             fa=0.95 * light, stroke="ink", w=1.4)
    if light > 0:
        ctx.glow(cx, (y0 + y1) / 2, 420, (255, 214, 140), 0.55 * light)
        ctx.rays(cx, (y0 + y1) / 2, 90, 60, 1000, 0.3 * light, "gold" if ctx.dark else "ink", 1.0)
    ang = math.radians(78 * openness)
    lw = (x1 - x0) / 2
    for side in (-1, 1):
        hx = x0 if side < 0 else x1
        ix = hx - side * lw * math.cos(ang)
        sh = 36 * math.sin(ang)
        leaf = [(hx, y0), (ix, y0 + sh), (ix, y1 - sh), (hx, y1)] if side < 0 else [(ix, y0 + sh), (hx, y0), (hx, y1), (ix, y1 - sh)]
        ctx.poly(leaf, fill=(170, 44, 32) if not ctx.dark else (80, 24, 18), fa=1, stroke="ink", w=1.6,
                 hatch=dict(gap=3, ang=90, a=0.25))
        for i in range(9):
            for j in range(9):
                u = (i + 0.7) / 9.6
                v = (j + 0.8) / 9.8
                q = leaf if side < 0 else [leaf[1], leaf[0], leaf[3], leaf[2]]
                x, y = ctx.bilinear([q[0], q[1], q[2], q[3]], u * 0.92, v)
                r = 6.5 * (1 - 0.45 * math.sin(ang) * u)
                ctx.circle(x, y, r * max(math.cos(ang), 0.25) + 0.8, fill=(222, 170, 70), fa=1, stroke="ink", a=0.7, w=0.8)
        q = leaf if side < 0 else [leaf[1], leaf[0], leaf[3], leaf[2]]
        kx, ky = ctx.bilinear([q[0], q[1], q[2], q[3]], 0.9, 0.52)
        ctx.circle(kx, ky, 16 * max(math.cos(ang), 0.3), fill=(222, 170, 70), stroke="ink", w=1.2)
        ctx.ellipse(kx, ky + 22, 12 * max(math.cos(ang), 0.3), 14, stroke="ink", a=1, w=2.2)
    ctx.poly([(x0 - 70, y0 - 60), (x1 + 70, y0 - 60), (x1 + 30, y0 - 115), (x0 - 30, y0 - 115)],
             fill=(212, 160, 60) if not ctx.dark else (90, 70, 30), stroke="ink", w=1.5, hatch=dict(gap=3, ang=90, a=0.45))


def art_close(ctx, lt, p):
    o = 1 - ease(seg(lt, 0.2, 1.8))
    gate(ctx, lt, o, o ** 0.7)


def art_open(ctx, lt, p):
    o = ease(seg(lt, 0.15, 1.5))
    gate(ctx, lt, o, o ** 0.6)


def art_ruins(ctx, lt, p):
    ground = 560
    ctx.line([(300, ground), (1280, ground)], "ink", 0.6, 1.0)
    for i in range(40):
        x = 320 + i * 24
        ctx.line([(x, ground + 4), (x - 30, ground + 40 + 20 * rnd(i, 1))], "ink", 0.2, 0.8)
    a = eo(seg(lt, 0, 0.8))
    # the broken arch of the western mansions
    for side in (-1, 1):
        px = 900 + side * 170
        h = 330 if side < 0 else 250
        ctx.poly([(px - 34, ground), (px + 34, ground), (px + 34, ground - h), (px - 34, ground - h)], fill="fill", fa=a,
                 stroke="ink", sa=a, w=1.6, hatch=dict(gap=3.2, ang=90, a=0.35 * a))
        for k in range(4):
            yy = ground - 50 - k * 70
            if yy > ground - h + 20:
                ctx.poly([(px - 24, yy), (px + 24, yy), (px + 24, yy - 50), (px - 24, yy - 50)], fill=None, stroke="ink",
                         sa=0.7 * a, w=1.0)
                ctx.circle(px, yy - 25, 10, stroke="ink", a=0.6 * a, w=0.9)
        ctx.poly([(px - 44, ground - h), (px + 44, ground - h), (px + 38, ground - h - 16), (px - 38, ground - h - 16)],
                 fill="fill", fa=a, stroke="ink", sa=a, w=1.3)
    outer = [(900 + 204 * math.cos(math.radians(t)), ground - 346 - 150 * math.sin(math.radians(t))) for t in range(180, 97, -3)]
    inner = [(900 + 136 * math.cos(math.radians(t)), ground - 346 - 100 * math.sin(math.radians(t))) for t in range(180, 111, -3)]
    band = outer + list(reversed(inner))
    ctx.poly(band, fill="fill", fa=a, stroke="ink", sa=a, w=1.5)
    for t in range(174, 110, -12):
        c_, s_ = math.cos(math.radians(t)), math.sin(math.radians(t))
        ctx.line([(900 + 136 * c_, ground - 346 - 100 * s_), (900 + 204 * c_, ground - 346 - 150 * s_)], "ink", 0.7 * a, 1.0)
    ctx.line([outer[-1], (outer[-1][0] - 6, outer[-1][1] + 20), (inner[-1][0] + 10, inner[-1][1] - 8), inner[-1]], "ink", a, 1.5)
    for i, (dx, dw, rot) in enumerate([(-360, 60, 0), (-290, 50, 12), (200, 70, -8), (290, 55, 0), (360, 40, 20)]):
        x = 900 + dx
        ctx.c.save()
        ctx.c.translate(x, ground - 18)
        ctx.c.rotate(rot)
        ctx.poly([(-dw / 2, -18), (dw / 2, -18), (dw / 2, 18), (-dw / 2, 18)], fill="fill", fa=a, stroke="ink", sa=a, w=1.2,
                 hatch=dict(gap=3, ang=0, a=0.35 * a))
        ctx.ellipse(dw / 2, 0, 7, 18, fill="fill", fa=a, stroke="ink", a=a, w=1.2)
        ctx.c.restore()
    for k in range(6):  # smoke
        x = 700 + k * 90
        rise = (lt * 30 + k * 40) % 200
        pts = [(x + 25 * math.sin(t * 2 + lt + k), ground - 60 - rise - t * 60) for t in np.linspace(0, 3, 20)]
        ctx.line(pts, "sub", 0.25 * (1 - rise / 200), 5, blur=4)
    sparks(ctx, 900, ground - 10, lt, n=30, spread=500, rise=260, col=(255, 140, 60), seed=4, size=1.6, a=0.8)


MADMAN = "我翻開歷史一查這歷史沒有年代歪歪斜斜的每頁上都寫著仁義道德幾個字我橫豎睡不著仔細看了半夜才從字縫裡看出字來滿本都寫著兩個字是吃人"


def art_lamp(ctx, lt, p):
    lx, ly = 560, 470
    ctx.glow(lx, ly - 60, 420, (255, 170, 80), 0.3)
    ctx.poly([(lx - 50, ly), (lx + 50, ly), (lx + 34, ly + 30), (lx - 34, ly + 30)], fill="fill", stroke="ink", w=1.4,
             hatch=dict(gap=3, ang=90, a=0.4))
    ctx.poly([(lx - 12, ly + 30), (lx + 12, ly + 30), (lx + 20, ly + 110), (lx - 20, ly + 110)], fill="fill", stroke="ink",
             w=1.4)
    ctx.ellipse(lx, ly + 112, 50, 10, fill="fill", stroke="ink", w=1.4)
    flame(ctx, lx, ly - 4, 70, lt)
    sparks(ctx, lx, ly - 60, lt, n=16, spread=16, rise=140, seed=6, size=1.4)
    cam = Cam(yaw=0, pitch=50, dist=700, f=900, cx=930, cy=470)
    for side in (-1, 1):
        pts3 = [(0, 0, -130), (side * 190, 12, -130), (side * 190, 12, 130), (0, 0, 130)]
        page = cam.pp(pts3)
        ctx.poly(page, fill=(150, 126, 92), fa=0.95, stroke="ink", w=1.4)
        n = 0
        for c in range(7):
            u = (c + 0.6) / 7.6 if side > 0 else 1 - (c + 0.6) / 7.6
            for j in range(9):
                ch = MADMAN[((c + (0 if side > 0 else 7)) * 9 + j) % len(MADMAN)]
                t0 = 0.3 + ((0 if side > 0 else 63) + c * 9 + j) * 0.012
                if lt < t0:
                    continue
                x, y = ctx.bilinear([page[0], page[1], page[2], page[3]], 1 - u if side > 0 else u, (j + 0.8) / 9.6)
                ctx.text(ch, x, y + 6, "cjk", 15, (40, 28, 20), 0.9, align="center")
    q = cam.pp([(-150, 13, 40), (-60, 13, 40), (-60, 13, -40), (-150, 13, -40)])
    a = eo(seg(lt, 1.3, 1.7))
    for j, ch in enumerate("救救孩子"):
        x, y = ctx.bilinear(q, 0.5, (j + 0.5) / 4)
        ctx.text(ch, x, y + 10, "brush", 34, "acc", a, align="center")
    b0, b1 = cam.p(120, 40, 150)[:2], cam.p(260, 40, -60)[:2]
    ctx.line([b0, b1], "ink", 1, 7)
    ctx.line([b0, b1], (120, 70, 40), 1, 4.5)
    ctx.poly([(b1[0] - 5, b1[1] + 4), (b1[0] + 4, b1[1] - 5), (b1[0] + 26, b1[1] - 28)], fill="ink", stroke=None)



# --- IX · Fuxing -------------------------------------------------------------
def art_shenzhen(ctx, lt, p):
    cam = Cam(yaw=-8, pitch=8, dist=2300, f=1450, cx=830, cy=590, target=(0, 0, 150))
    grow = seg(lt, 0.25, 2.3)
    for k in range(14):  # the bay
        z = -420 + k * 30
        pts = [cam.p(x, 0, z)[:2] for x in range(-900, 901, 60)]
        ctx.line([(x, y + 1.5 * math.sin(x * 0.05 + lt * 3 + k)) for x, y in pts], "ink", 0.18 + 0.02 * k, 0.8)
    faces = []
    tops = []
    for i in range(36):
        x = -660 + i * 38 + 10 * (rnd(i, 1) - 0.5)
        z = 70 + 240 * rnd(i, 2)
        w_ = 24 + 16 * rnd(i, 3)
        hmax = 50 + 250 * rnd(i, 4) ** 2
        if i == 18:
            x, z, w_, hmax = 10, 150, 46, 420
        t0 = 0.05 + 0.65 * rnd(i, 5)
        h = lerp(10, hmax, eo(seg(grow, t0, t0 + 0.3)))
        fb = box(x - w_ / 2, 0, z - w_ / 2, x + w_ / 2, h, z + w_ / 2, w=1.0)

        def win(ctx_, q, h=h, i=i):
            n = int(h / 14)
            for f_ in range(1, n):
                ctx_.line([ctx_.bilinear(q, 0.08, f_ / n), ctx_.bilinear(q, 0.92, f_ / n)], "ink", 0.3, 0.6)
            if i % 3 == 0:
                for m in range(1, 4):
                    ctx_.line([ctx_.bilinear(q, m / 4, 0), ctx_.bilinear(q, m / 4, 1)], "ink", 0.25, 0.6)
        fb[0]["deco"] = win
        fb[3]["hatch"] = dict(gap=3, ang=90, a=0.3)
        if i == 18:
            fb[0]["fill"] = "acc"
            fb[0]["fa"] = 0.25
            tops.append((x, h, z))
        faces += fb
    ctx.mesh(cam, faces)
    for x, h, z in tops:
        if h > 200:
            ctx.line([cam.p(x, h, z)[:2], cam.p(x, h + 50 * seg(h, 200, 420), z)[:2]], "ink", 1, 2)
    for k in range(4):  # fishing boats give way to the city
        bx, by = cam.p(-400 + k * 260, 0, -120 + 40 * k)[:2]
        junk(ctx, bx, by - 4, 0.09, lt + k, 1 - seg(grow, 0.1, 0.5))


POVERTY = [(1981, 88.1), (1984, 76.0), (1987, 61.0), (1990, 72.0), (1993, 57.0), (1996, 42.0), (1999, 40.2),
           (2002, 31.7), (2005, 18.5), (2008, 14.8), (2010, 11.2), (2012, 6.5), (2013, 1.9), (2015, 1.2),
           (2016, 0.8), (2018, 0.4), (2019, 0.1)]


def art_poverty(ctx, lt, p):
    ox, oy, cw, chh = 640, 600, 560, 380
    X = lambda yr: ox + (yr - 1980) / 40 * cw
    Y = lambda v: oy - v / 90 * chh
    ctx.line([(ox, oy - chh - 10), (ox, oy), (ox + cw + 10, oy)], "ink", 1, 1.2)
    for v in (20, 40, 60, 80):
        ctx.line([(ox, Y(v)), (ox + cw, Y(v))], "ink", 0.2, 0.8, dash=[3, 5])
        ctx.text(f"{v}%", ox - 10, Y(v) + 4, "mono", 9, "sub", 0.8, align="right")
    for yr in range(1980, 2021, 10):
        ctx.line([(X(yr), oy), (X(yr), oy + 5)], "ink", 0.8, 1)
        ctx.text(str(yr), X(yr), oy + 20, "mono", 9, "sub", 0.8, align="center")
    ctx.text("EXTREME POVERTY RATE · CHINA", ox + 10, oy - chh - 22, "mono", 9, "sub", 0.9, track=2)
    pts = catmull([(X(y), Y(v)) for y, v in POVERTY], 6)
    pr = ease(seg(lt, 0.3, 2.2))
    ctx.poly([(X(1981), oy)] + trim(pts, pr) + [(trim(pts, pr)[-1][0], oy)], fill="acc", fa=0.12, stroke=None)
    ctx.line(pts, "acc", 1, 2.4, prog=pr)
    x, y = trim(pts, pr)[-1]
    ctx.circle(x, y, 5, fill="acc", stroke="ink", w=1)
    yr = lerp(1981, 2019, (x - X(1981)) / (X(2019) - X(1981)))
    val = np.interp(yr, [a for a, _ in POVERTY], [b for _, b in POVERTY])
    ctx.text(f"{val:.1f}%", x + 10, y - 10, "mono", 12, "acc", 1)


def art_dam(ctx, lt, p):
    cam = Cam(yaw=-36, pitch=17, dist=1800, f=1350, cx=820, cy=440, target=(0, 70, 100))
    for side in (-1, 1):  # gorge walls
        xs = side * 540
        prof = [(z, 200 + 90 * math.sin(z * 0.008 + side) + 40 * math.sin(z * 0.03)) for z in range(-500, 1001, 50)]
        for (z0, h0), (z1, h1) in zip(prof, prof[1:]):
            q = cam.pp([(xs, 0, z0), (xs, 0, z1), (xs + side * 180, h1, z1), (xs + side * 180, h0, z0)])
            ctx.poly(q, fill="fill", stroke=None, hatch=dict(gap=3.5, ang=80, a=0.3))
        ctx.line([cam.p(xs + side * 180, h, z)[:2] for z, h in prof], "ink", 0.9, 1.3)
        ctx.line([cam.p(xs, 0, z)[:2] for z, h in prof], "ink", 0.5, 1.0)
    water = cam.pp([(-540, 100, 24), (540, 100, 24), (540, 100, 1000), (-540, 100, 1000)])
    ctx.poly(water, fill=(170, 180, 175) if not ctx.dark else "fill", fa=0.3, stroke=None)
    for k in range(10):
        z = 60 + k * 90
        ctx.line([cam.p(x, 100, z + 6 * math.sin(x * 0.02 + lt * 2 + k))[:2] for x in range(-520, 521, 40)], "ink", 0.3, 0.8)
    g = eo(seg(lt, 0, 0.9))
    fb = box(-540, 0, -26, 540, 115 * g, 26, w=1.5)

    def gates(ctx_, q):
        for k in range(23):
            u = 0.28 + k * 0.019
            ctx_.poly([ctx_.bilinear(q, u, 0.35), ctx_.bilinear(q, u + 0.011, 0.35), ctx_.bilinear(q, u + 0.011, 0.75),
                       ctx_.bilinear(q, u, 0.75)], fill="ink", fa=0.7, stroke=None)
        for v in (0.85, 0.2):
            ctx_.line([ctx_.bilinear(q, 0, v), ctx_.bilinear(q, 1, v)], "ink", 0.6, 0.9)
        for k in range(1, 30):
            ctx_.line([ctx_.bilinear(q, k / 30, 0.85), ctx_.bilinear(q, k / 30, 1)], "ink", 0.4, 0.7)
    fb[0]["deco"] = gates if g > 0.95 else None
    fb[0]["hatch"] = dict(gap=4, ang=90, a=0.2)
    ctx.mesh(cam, fb)
    for k in range(23):  # spillway jets
        x = -540 + (0.28 + k * 0.019 + 0.005) * 1080
        if g < 1:
            break
        top = cam.p(x, 55, -26)
        pts = [cam.p(x, 55 - 55 * t * t, -26 - 70 * t)[:2] for t in np.linspace(0, 1, 10)]
        ctx.line(pts, "ink", 0.5, 1.6, dash=[6, 4])
        fx, fy = pts[-1]
        ph = (lt * 2 + k * 0.3) % 1
        ctx.circle(fx, fy, 3 + 10 * ph, stroke="ink", a=0.4 * (1 - ph), w=0.8)
    for k in range(8):
        z = -120 - k * 60
        ctx.line([cam.p(x, 0, z + 8 * math.sin(x * 0.03 - lt * 4 + k))[:2] for x in range(-520, 521, 40)], "ink", 0.3, 0.8)


def art_train(ctx, lt, p):
    speed = 1100
    off = (lt * speed) % 220
    ctx.line([(0, 505), (W, 505)], "ink", 1, 1.4)
    ctx.line([(0, 520), (W, 520)], "ink", 1, 1.4)
    ctx.hatch_path(ctx.path([(0, 505), (W, 505), (W, 520), (0, 520)], True), gap=3, ang=90, a=0.4)
    for k in range(8):
        x = k * 220 - off
        ctx.poly([(x - 16, 520), (x + 16, 520), (x + 22, 720), (x - 22, 720)], fill="fill", stroke="ink", w=1.2,
                 hatch=dict(gap=3, ang=90, a=0.3))
    for k in range(4):  # far hills, slower
        x = (k * 520 - (lt * 120) % 520) - 100
        mountain(ctx, x + 200, 520, 160, 120 + 30 * (k % 2), a=0.5, seed=k + 20)
    vib = 0.6 * math.sin(lt * 50)
    ctx.c.save()
    ctx.c.translate(0, vib)
    top = bez((560, 385), (420, 388), (300, 488))
    body = [(1400, 385)] + top + [(305, 496), (360, 502), (1400, 502)]
    ctx.poly(body, fill=(246, 244, 238) if not ctx.dark else "fill", stroke="ink", w=1.8)
    ctx.poly([(300, 470), (1400, 470), (1400, 480), (318, 480)], fill="acc", stroke=None)
    ctx.poly([(300, 485), (1400, 485), (1400, 489), (330, 489)], fill=(212, 160, 60), stroke=None)
    ctx.poly(bez((470, 404), (410, 408), (370, 440)) + [(430, 440), (500, 416)], fill="ink", fa=0.85, stroke=None)
    for k in range(20):
        x = 560 + k * 38
        ctx.poly([(x, 408), (x + 24, 408), (x + 24, 426), (x, 426)], fill="ink", fa=0.75, stroke=None)
    for x in (820, 1160):
        ctx.line([(x, 386), (x, 500)], "ink", 0.8, 1.2)
    for x in (640, 780, 1000, 1140):
        ctx.circle(x, 506, 10, fill="fill", stroke="ink", w=1.4)
    ctx.line([(900, 385), (930, 360), (970, 360)], "ink", 1, 1.6)
    ctx.c.restore()
    for k in range(26):  # speed lines
        y = 360 + 150 * rnd(k, 3)
        x = (1400 - ((lt * 2400 + k * 170) % 1800))
        ctx.line([(x, y), (x + 120 + 80 * rnd(k, 4), y)], "ink", 0.3, 1.0)


# --- X · Tian ----------------------------------------------------------------
def art_launch(ctx, lt, p):
    base = 600
    rise = 230 * seg(lt, 0.5, 2.4) ** 2
    ground = [(300, base), (1280, base)]
    ctx.line(ground, "ink", 0.6, 1.2)
    tx = 1010
    for k in range(12):  # tower
        y = base - k * 42
        ctx.line([(tx, y), (tx + 50, y)], "ink", 0.7, 1.0)
        ctx.line([(tx, y), (tx + 50, y - 42)], "ink", 0.4, 0.8)
    ctx.line([(tx, base), (tx, base - 500)], "ink", 0.9, 1.4)
    ctx.line([(tx + 50, base), (tx + 50, base - 500)], "ink", 0.9, 1.4)
    rx, rb = 880, base - 40 - rise
    for k in range(16):  # smoke billows
        ph = (lt * 0.8 + k * 0.13) % 1
        side = 1 if k % 2 else -1
        x = rx + side * (40 + 260 * ph * (0.5 + rnd(k, 1)))
        r = 20 + 60 * ph
        a = (1 - ph) * seg(lt, 0.2, 0.6)
        ctx.circle(x, base - 20 - 30 * ph, r, fill=(40, 34, 30), fa=0.9 * a, stroke="ink", a=0.5 * a, w=1.0)
    ign = seg(lt, 0.1, 0.5)
    flame(ctx, rx, rb + 10, 160 * ign, lt, a=ign) if False else None
    if ign > 0:
        ctx.glow(rx, rb + 60, 420, (255, 150, 60), 0.5 * ign)
        for k, (col, wd, al) in enumerate([((255, 110, 40), 30, 0.6), ((255, 190, 90), 18, 0.8), ((255, 245, 210), 8, 1.0)]):
            ln = (260 + 40 * math.sin(lt * 30 + k)) * ign
            pts = [(rx - wd, rb), (rx + wd, rb), (rx + wd * 0.4, rb + ln), (rx - wd * 0.4, rb + ln)]
            ctx.c.drawPath(ctx.path(pts, True), ctx.paint(col, al, fill=True, blur=6, add=True))
        sparks(ctx, rx, rb + 200, -lt, n=40, spread=120, rise=-200, col=(255, 190, 110), seed=9, a=ign)
    rocket_outline(ctx, rx, rb, 1.0, 1.0)


def art_fast(ctx, lt, p):
    cx, cy = 880, 470
    for i, (mx, mh) in enumerate([(430, 150), (560, 110), (1240, 170), (1150, 120)]):
        pts = catmull([(mx - 90, 560), (mx - 30, 560 - mh), (mx + 20, 560 - mh * 0.9), (mx + 100, 560)], 8)
        ctx.line(pts, "ink", 0.6, 1.2)
    pr = eo(seg(lt, 0, 1.0))
    for k in range(9):
        t = k / 8
        rx = 340 * (1 - t * 0.85)
        ry = 95 * (1 - t * 0.85)
        ctx.line(circle_pts(cx, cy + 90 * math.sin(t * math.pi / 2) * 1.0, rx, ry, n=90), "ink", 0.8 if k == 0 else 0.45,
                 1.6 if k == 0 else 0.9, prog=pr)
    for k in range(36):
        a0 = math.radians(k * 10)
        pts = []
        for j in range(9):
            t = j / 8
            pts.append((cx + 340 * (1 - t * 0.85) * math.cos(a0), cy + 90 * math.sin(t * math.pi / 2) +
                        95 * (1 - t * 0.85) * math.sin(a0)))
        ctx.line(pts, "ink", 0.35, 0.8, prog=pr)
    fx, fy = cx, cy - 170
    ta = eo(seg(lt, 0.6, 1.2))
    for k in range(6):
        a0 = math.radians(k * 60 + 30)
        bx, by = cx + 380 * math.cos(a0), cy + 105 * math.sin(a0)
        ctx.line([(bx, by), (bx, by - 260)], "ink", ta, 1.6)
        ctx.line([(bx, by - 260), (fx, fy)], "ink", 0.6 * ta, 0.9)
    ctx.poly([(fx - 16, fy - 8), (fx + 16, fy - 8), (fx + 20, fy + 8), (fx - 20, fy + 8)], fill="fill", fa=ta, stroke="ink",
             sa=ta, w=1.4)
    ctx.glow(fx, fy, 60, "gold", 0.4 * ta)
    for k in range(5):  # incoming waves from the sky
        ph = (lt * 0.7 + k * 0.2) % 1
        r = 60 + ph * 300
        ctx.arc(fx, fy - 420, r, 60, 60, "gold", 0.5 * (1 - ph), 1.4)


def moon_ground(ctx, y0, lt):
    pts = [(x, y0 + 12 * math.sin(x * 0.004)) for x in range(0, W + 20, 20)]
    ctx.poly(pts + [(W, H), (0, H)], fill=(40, 40, 46), fa=1, stroke="ink", sa=0.5, w=1.0)
    for k in range(14):
        x = 80 + 1150 * rnd(k, 1)
        y = y0 + 40 + 230 * rnd(k, 2)
        rx = 20 + 70 * rnd(k, 3) * (y - y0) / 260
        ctx.ellipse(x, y, rx, rx * 0.22, fill=(28, 28, 34), fa=0.9, stroke="ink", a=0.4, w=0.9)


def art_farside(ctx, lt, p):
    moon_ground(ctx, 440, lt)
    cam = Cam(yaw=-25, pitch=14, dist=700, f=1000, cx=780, cy=470, target=(0, 30, 0))
    g = eo(seg(lt, 0, 0.6))
    faces = box(-45, 30, -45, 45, 30 + 55 * g, 45, hatch=dict(gap=3, ang=45, a=0.45), w=1.3)
    for lx, lz in ((-60, -60), (60, -60), (60, 60), (-60, 60)):
        faces += box(lx - 8, 0, lz - 8, lx + 8, 4, lz + 8)
    ctx.mesh(cam, faces)
    for lx, lz in ((-60, -60), (60, -60), (60, 60), (-60, 60)):
        ctx.line([cam.p(lx, 4, lz)[:2], cam.p(lx * 0.7, 40, lz * 0.7)[:2]], "ink", 1, 1.6)
    ctx.line([cam.p(20, 85, 0)[:2], cam.p(20, 150, 0)[:2]], "ink", 1, 1.4)
    ctx.ellipse(*cam.p(20, 150, 0)[:2], 16, 6, stroke="ink", w=1.3)
    rxp = 130 + 110 * ease(seg(lt, 0.4, 2.4))
    for side in (-9, 9):
        ctx.line([cam.p(x, 0, 40 + side)[:2] for x in np.linspace(70, rxp - 20, 20)], "gold", 0.5, 1.0, dash=[3, 3])
    rv = box(rxp - 20, 10, 25, rxp + 20, 26, 55, hatch=dict(gap=2.5, ang=45, a=0.5), w=1.2)
    rv += [face([(rxp - 20, 26, 25), (rxp - 20, 26, 55), (rxp - 48, 30, 55), (rxp - 48, 30, 25)], fill=(40, 70, 130),
                fa=0.6, w=1.0),
           face([(rxp + 20, 26, 25), (rxp + 20, 26, 55), (rxp + 48, 30, 55), (rxp + 48, 30, 25)], fill=(40, 70, 130),
                fa=0.6, w=1.0)]
    ctx.mesh(cam, rv)
    for wx in (-14, 0, 14):
        for wz in (22, 58):
            x, y, _ = cam.p(rxp + wx, 7, wz)
            ctx.circle(x, y, 5, fill="fill", stroke="ink", w=1.1)
    ctx.line([cam.p(rxp + 10, 26, 40)[:2], cam.p(rxp + 10, 48, 40)[:2]], "ink", 1, 1.3)
    qx, qy = 1180, 120
    ctx.circle(qx, qy, 4, fill="gold", stroke=None)
    ctx.text("QUEQIAO RELAY", qx - 12, qy - 12, "mono", 8, "sub", 0.8, track=1.5, align="right")
    ctx.line([(qx, qy), cam.p(20, 150, 0)[:2]], "gold", 0.4, 1.0, dash=[4, 6])
    ctx.text("NO EARTH IN THIS SKY", 1216, 230, "mono", 8, "sub", 0.6 * eo(seg(lt, 1.0, 1.4)), track=2, align="right")


def art_tiangong(ctx, lt, p):
    ctx.glow(640, 1480, 1150, (60, 120, 230), 0.45)
    ctx.circle(640, 1480, 1000, fill=(10, 22, 50), fa=1, stroke=(90, 150, 240), a=0.8, w=1.5)
    for k in range(-6, 7):
        ang = math.radians(90 + k * 6 + lt * 1.5)
        ctx.line(circle_pts(640, 1480, 1000 * abs(math.cos(math.radians(90 + k * 12))) + 1, 1000, n=80, a0=200, a1=340),
                 (90, 150, 240), 0.12, 0.8)
    cam = Cam(yaw=-30 + lt * 6, pitch=22, dist=900, f=1100, cx=840, cy=320)
    faces = cyl_x(0, 0, 22, -150, 50, fill="fill", w=1.1)
    faces += cyl_x(0, 0, 14, -200, -150, fill="fill", w=1.0)
    for s in (-1, 1):
        lab = cyl_x(0, 0, 20, 0, 170, fill="fill", w=1.1)
        for f in lab:
            f["pts"] = [(70 + s * 0 + 0, y, s * x + 0) for x, y, z in [(v[0], v[1], v[2]) for v in f["pts"]]] if False else \
                [(70 + v[2], v[1], s * (v[0] + 30)) for v in f["pts"]]
        faces += lab
        faces.append(face([(40, -3, s * 150), (100, -3, s * 150), (100, 3, s * 380), (40, 3, s * 380)], fill=(40, 70, 140),
                          fa=0.7, w=1.0, hatch=dict(gap=6, ang=0, a=0.6)))
    faces.append(face([(-120, -3, -40), (-80, -3, -40), (-80, 3, -150), (-120, 3, -150)], fill=(40, 70, 140), fa=0.7, w=1.0))
    faces.append(face([(-120, -3, 40), (-80, -3, 40), (-80, 3, 150), (-120, 3, 150)], fill=(40, 70, 140), fa=0.7, w=1.0))
    ctx.mesh(cam, faces, a=eo(seg(lt, 0, 0.6)))
    x, y, _ = cam.p(70, 0, 0)
    ctx.glow(x, y, 50, "gold", 0.25)


def art_mars(ctx, lt, p):
    mx, my, mr = 1000, 380, 230
    ctx.glow(mx, my, mr * 1.5, (240, 110, 60), 0.25)
    sh = skia.GradientShader.MakeRadial(skia.Point(mx - 70, my - 80), mr * 1.4,
                                        [skia.ColorSetARGB(255, 214, 96, 52), skia.ColorSetARGB(255, 120, 40, 24),
                                         skia.ColorSetARGB(255, 30, 12, 10)], [0, 0.6, 1])
    ctx.c.drawCircle(mx, my, mr, skia.Paint(AntiAlias=True, Shader=sh))
    ctx.circle(mx, my, mr, stroke="gold", a=0.8, w=1.4)
    for k in range(12):
        a0 = rnd(k, 1) * 6.28
        rr = mr * 0.85 * math.sqrt(rnd(k, 2))
        cx, cy = mx + rr * math.cos(a0), my + rr * math.sin(a0)
        ctx.ellipse(cx, cy, 8 + 14 * rnd(k, 3), (8 + 14 * rnd(k, 3)) * 0.7, stroke=(255, 190, 140), a=0.35, w=0.9)
    ctx.ellipse(mx, my - mr + 20, 40, 10, fill=(250, 240, 230), fa=0.8, stroke=None)
    ex, ey = 300, 560
    ctx.glow(ex, ey, 60, (70, 140, 235), 0.5)
    ctx.circle(ex, ey, 28, fill=(30, 70, 150), stroke=(120, 180, 255), w=1.2)
    path = bez((ex + 20, ey - 20), (620, 260), (mx - mr * 0.6, my + 60), n=50)
    ctx.line(path, "gold", 0.4, 1.0, dash=[4, 6])
    for k in range(40):
        u = (lt * 0.35 + k / 40) % 1
        x, y = point_at(path, u)
        ctx.circle(x, y, 1.8, fill="gold", fa=0.9 * math.sin(u * math.pi), stroke=None, add=True)
    sx, sy = mx + 60, my - 70
    ta = eo(seg(lt, 1.0, 1.4))
    ctx.circle(sx, sy, 6, fill="acc", fa=ta, stroke=None)
    ctx.circle(sx, sy, 14 + 8 * math.sin(lt * 6), stroke="acc", a=ta, w=1.2)
    ctx.text("UTOPIA PLANITIA", sx + 22, sy - 10, "mono", 9, "text", ta, track=2)


# --- XI · Huo ----------------------------------------------------------------
def art_tokamak(ctx, lt, p):
    cam = Cam(yaw=lt * 10, pitch=28, dist=900, f=1000, cx=880, cy=400)
    R, r = 200, 80
    segs = []
    for i in range(32):  # poloidal rings
        th = 2 * math.pi * i / 32
        ring = [cam.p((R + r * math.cos(ph)) * math.cos(th), r * math.sin(ph), (R + r * math.cos(ph)) * math.sin(th))
                for ph in np.linspace(0, 2 * math.pi, 28)]
        z = sum(q[2] for q in ring) / len(ring)
        segs.append((z, [q[:2] for q in ring], i % 4 == 0))
    for j in range(10):  # toroidal lines
        ph = 2 * math.pi * j / 10
        line = [cam.p((R + r * math.cos(ph)) * math.cos(th), r * math.sin(ph), (R + r * math.cos(ph)) * math.sin(th))
                for th in np.linspace(0, 2 * math.pi, 64)]
        ctx.line([q[:2] for q in line], "ink", 0.25, 0.8)
    zmid = sorted(s[0] for s in segs)[len(segs) // 2]
    for z, pts, coil in sorted(segs, key=lambda s: -s[0]):
        back = z > zmid
        ctx.line(pts, "ink", (0.25 if back else 0.7) * (1.6 if coil else 1), 2.4 if coil else 0.9)
    on = eo(seg(lt, 0.5, 1.2))
    plasma = [cam.p(R * math.cos(th), 0, R * math.sin(th))[:2] for th in np.linspace(0, 2 * math.pi, 120)]
    pulse = 0.85 + 0.15 * math.sin(lt * 9)
    ctx.line(plasma, (255, 120, 200), 0.5 * on * pulse, 40, blur=16, add=True)
    ctx.line(plasma, (255, 170, 120), 0.8 * on * pulse, 14, blur=5, add=True)
    ctx.line(plasma, (255, 245, 230), on, 3, add=True)
    ctx.glow(880, 400, 380, (255, 140, 180), 0.18 * on)


# --- XII · Weilai ------------------------------------------------------------
def art_dyson(ctx, lt, p):
    cx, cy = 900, 380
    ctx.glow(cx, cy, 300, (255, 210, 130), 0.55)
    ctx.circle(cx, cy, 40, fill=(255, 244, 220), stroke=None, blur=6, add=True)
    for k in range(6):
        tilt = -60 + k * 24
        rx, ry = 150 + k * 28, 40 + k * 18
        ca, sa = math.cos(math.radians(tilt)), math.sin(math.radians(tilt))
        orb = [(cx + rx * math.cos(t) * ca - ry * math.sin(t) * sa, cy + rx * math.cos(t) * sa + ry * math.sin(t) * ca)
               for t in np.linspace(0, 2 * math.pi, 90)]
        ctx.line(orb, "gold", 0.25, 0.8)
        for j in range(26):
            t = j / 26 * 2 * math.pi + lt * (0.6 - k * 0.07)
            x = cx + rx * math.cos(t) * ca - ry * math.sin(t) * sa
            y = cy + rx * math.cos(t) * sa + ry * math.sin(t) * ca
            front = math.sin(t) > 0
            s = 5 if front else 3.5
            hexp = [(x + s * math.cos(math.radians(60 * i)), y + s * math.sin(math.radians(60 * i))) for i in range(6)]
            ctx.poly(hexp, fill="gold", fa=0.9 if front else 0.35, stroke=None)
    sparks(ctx, cx, cy, lt, n=30, spread=260, rise=-80, seed=12, size=1.3, a=0.5)


def art_galaxy(ctx, lt, p, cx=900, cy=380, scale=1.0, a=1.0):
    ctx.glow(cx, cy, 200 * scale, (255, 220, 160), 0.5 * a)
    for i in range(1500):
        arm = i % 2
        t = rnd(i, 1)
        rr = (20 + 380 * t) * scale
        ang = arm * math.pi + t * 5.2 + lt * 0.25 + (rnd(i, 2) - 0.5) * 0.9 * (1 - t * 0.5)
        x = cx + rr * math.cos(ang)
        y = cy + rr * math.sin(ang) * 0.42
        br = (1 - t) ** 0.8
        col = (255, 235, 200) if rnd(i, 3) > 0.3 else (160, 190, 255)
        ctx.circle(x, y, 1.1 + 1.2 * rnd(i, 4), fill=col, fa=a * (0.3 + 0.7 * br), stroke=None, add=True)


def get_icon(name):
    """A shot's illustration re-drawn in gold on navy, cropped to a disc."""
    g = worker_state()
    if name not in g["icons"]:
        s = next(s for s in SHOTS if s["art"].__name__ == name)
        surf = skia.Surface(W, H)
        cv = surf.getCanvas()
        cv.clear(skia.ColorSetARGB(255, 14, 16, 24))
        s["art"](Ctx(cv, "dark", s["dur"] - 0.05, s["dur"], s), s["dur"] - 0.05, 1.0)
        arr = surf.makeImageSnapshot().toarray(colorType=skia.kRGBA_8888_ColorType)
        cx, cy, r = s["icon"]
        big = np.zeros((H + 2 * r, W + 2 * r, 4), np.uint8)
        big[..., :3] = (14, 16, 24)
        big[..., 3] = 255
        big[r:r + H, r:r + W] = arr
        crop = big[cy:cy + 2 * r, cx:cx + 2 * r]
        im = Image.fromarray(crop).resize((256, 256), Image.LANCZOS)
        g["icons"][name] = skia.Image.fromarray(np.ascontiguousarray(np.asarray(im)))
    return g["icons"][name]


def medallion(ctx, name, x, y, r, a=1.0):
    img = get_icon(name)
    pth = skia.Path()
    pth.addCircle(x, y, r)
    ctx.c.save()
    ctx.c.clipPath(pth, doAntiAlias=True)
    p = skia.Paint(AntiAlias=True)
    p.setAlphaf(a)
    ctx.c.drawImageRect(img, skia.Rect.MakeLTRB(x - r, y - r, x + r, y + r), skia.SamplingOptions(skia.FilterMode.kLinear), p)
    ctx.c.restore()
    ctx.circle(x, y, r, stroke="gold", a=0.9 * a, w=1.5)
    ctx.circle(x, y, r + 5, stroke="gold", a=0.35 * a, w=0.8)


RING = ["art_ding", "art_bagua", "art_wall", "art_silkroad", "art_paper", "art_seismo", "art_poem", "art_movable",
        "art_compass", "art_1405", "art_forbidden", "art_launch", "art_farside", "art_tokamak"]
FLIP = [("art_yu", "2070 BC"), ("art_oracle", "1250 BC"), ("art_unify", "221 BC"), ("art_paper", "AD 105"),
        ("art_diamond", "AD 868"), ("art_compass", "AD 1088"), ("art_1405", "AD 1405"), ("art_launch", "AD 2003"),
        ("art_tokamak", "AD 2025")]


def art_flip(ctx, lt, p):
    art_ring(ctx, lt, p, cx=640, cy=330, R=250, a=0.2)
    i = min(int(lt / (ctx.dur / len(FLIP))), len(FLIP) - 1)
    name, label = FLIP[i]
    ctx.rays(640, 330, 90, 180, 900, 0.18, "gold", 1.0, spin=lt * 20)
    medallion(ctx, name, 640, 330, 170)
    ctx.text(label, 640, 590, "display", 92, "white", 1, track=4, align="center")
    ctx.text(label, 640, 590, "display", 92, "gold", 0.6, track=4, align="center", blur=14, add=True)
    for k, (_, lab) in enumerate(FLIP):  # the strip of years
        x = 640 + (k - i) * 150
        ctx.text(lab, x, 60, "mono", 11, "gold" if k == i else "sub", 1 if k == i else 0.5, track=2, align="center")


def ring_of_medallions(ctx, t, a=1.0, cx=640, cy=440, rx=470, ry=150, appear=0.0):
    items = []
    n = len(RING)
    for i, name in enumerate(RING):
        th = math.radians(t * 9 + i * 360 / n)
        x, y = cx + rx * math.cos(th), cy + ry * math.sin(th)
        depth = math.sin(th)
        items.append((depth, i, name, x, y))
    items.sort()
    for depth, i, name, x, y in items:
        s = 0.62 + 0.38 * (depth + 1) / 2
        al = a * (0.45 + 0.55 * (depth + 1) / 2) * eo(seg(appear, i * 0.06, i * 0.06 + 0.3))
        if al > 0.01:
            medallion(ctx, name, x, y, 58 * s, al)


def art_5000(ctx, lt, p):
    art_galaxy(ctx, lt + 5, p, cx=640, cy=380, scale=1.25, a=0.55)


def art_inkwet(ctx, lt, p):
    art_ring(ctx, lt, p, cx=640, cy=440, R=330, a=0.12)
    ring_of_medallions(ctx, lt, appear=lt)
    tip = wen(ctx, 640, 470, 150, ease(seg(lt, 0.2, 1.6)))
    sparks(ctx, tip[0], tip[1], lt, n=24, spread=20, rise=100, seed=14)
    sparks(ctx, 640, 470, lt, n=30, spread=120, rise=260, seed=15, a=0.6)


def art_quote(ctx, lt, p):
    art_ring(ctx, lt + 3, p, cx=640, cy=440, R=330, a=0.12)
    ring_of_medallions(ctx, lt + 3.0, appear=9)
    wen(ctx, 640, 470, 150, 1.0)
    sparks(ctx, 640, 470, lt, n=40, spread=120, rise=300, seed=16)
    a = eo(seg(lt, 0.3, 0.9))
    ctx.text("天行健，君子以自強不息", 640, 130, "cjk", 34, "gold", a, track=8, align="center")
    ctx.text("天行健，君子以自強不息", 640, 130, "cjk", 34, "gold", 0.5 * a, track=8, align="center", blur=10, add=True)
    b = eo(seg(lt, 0.9, 1.5))
    ctx.text("As heaven moves on without rest, the noble one never ceases to strive.", 640, 172, "italic", 22,
             "text", 0.9 * b, align="center")
    ctx.text("— I CHING · THE BOOK OF CHANGES", 640, 200, "mono", 9, "sub", 0.8 * b, track=3, align="center")


def art_final(ctx, lt, p):
    art_ring(ctx, lt + 6, p, cx=640, cy=400, R=330, a=0.14 * (1 - seg(lt, 2.8, 4.0)))
    wen(ctx, 640, 420, 190, 1.0, a=0.9)
    ctx.glow(640, 420, 320, "gold", 0.12)
    sparks(ctx, 640, 440, lt, n=60, spread=140, rise=360, seed=17)


# ---------------------------------------------------------------------------
# The storyboard
# ---------------------------------------------------------------------------
def S(art, dur, bg="paper", ch="", year=0, k=0.4, head=None, cap=None, hx=92, hy=150, align="left",
      zoom=(1.0, 1.06), focus=(900, 400), hud=True, icon=None, year_to=None, flash=0.0, **kw):
    d = dict(art=art, dur=dur, bg=bg, ch=ch, year=year, k=k, head=head, cap=cap, hx=hx, hy=hy, align=align,
             zoom=zoom, focus=focus, hud=hud, icon=icon, year_to=year_to, flash=flash)
    d.update(kw)
    return d


CH1 = "I · 夏商 XIA · SHANG"
CH2 = "II · 周 ZHOU"
CH3 = "III · 秦 QIN"
CH4 = "IV · 汉 HAN"
CH5 = "V · 唐 TANG"
CH6 = "VI · 宋 SONG"
CH7 = "VII · 明 MING"
CH8 = "VIII · 夜 YE"
CH9 = "IX · 复兴 FUXING"
CH10 = "X · 天 TIAN"
CH11 = "XI · 火 HUO"
CH12 = "XII · 未来 WEILAI"

SHOTS = [
    # cold open
    S(art_compass_open, 2.2, "dark", hud=False, focus=(640, 360), zoom=(1.08, 1.0)),
    S(art_cangjie, 2.6, "dark", hud=False, head=[("CANGJIE", "gold", 92), ("INVENTED *WRITING.", "white", 40)],
      hx=640, hy=150, align="center", focus=(640, 400), stagger=0.3),
    S(art_never, 2.4, "dark", hud=False, head=[("WE NEVER PUT", "white", 50), ("DOWN THE *BRUSH.", "white", 50)],
      hx=640, hy=150, align="center", focus=(640, 400), stagger=0.22),
    S(art_rocket_flash, 1.4, "dark", hud=False, focus=(640, 360), zoom=(1.0, 1.1)),
    # I
    S(art_yu, 2.2, ch=CH1, year=-2070, k=0.401, head=[("WE TAMED", "ink", 46), ("THE FLOOD.", "red", 66)],
      cap="YU THE GREAT · NINE RIVERS · c. 2070 BC", flash=0.5, icon=(900, 450, 260)),
    S(art_oracle, 2.4, ch=CH1, year=-1250, k=0.408, head=[("WE ASKED", "ink", 46), ("HEAVEN.", "red", 70)],
      cap="ORACLE BONES · ANYANG · c. 1250 BC", icon=(900, 390, 250)),
    S(art_ding, 2.4, ch=CH1, year=-1200, k=0.412, head=[("THEN WE CAST", "ink", 46), ("BRONZE.", "red", 70)],
      cap="HOUMUWU DING · 832 KG · c. 1200 BC", icon=(890, 450, 220)),
    # II
    S(art_formation, 2.3, ch=CH2, year=-500, k=0.414, head=[("KNOW THE ENEMY.", "ink", 40), ("KNOW YOURSELF.", "red", 58)],
      cap="THE ART OF WAR · SUN TZU · c. 500 BC", flash=0.4, icon=(880, 430, 260)),
    S(art_slips, 2.4, ch=CH2, year=-479, k=0.416, head=[("WE ASKED", "ink", 46), ("HOW TO LIVE.", "red", 66)],
      cap="THE ANALECTS · CONFUCIUS · 551–479 BC", icon=(880, 440, 240)),
    S(art_bagua, 2.3, ch=CH2, year=-400, k=0.418, head=[("WE SOUGHT", "ink", 46), ("THE WAY.", "red", 70)],
      cap="DAODEJING · LAOZI · c. 400 BC", icon=(900, 390, 300)),
    # III
    S(art_unify, 2.4, ch=CH3, year=-221, k=0.421, head=[("ONE EMPIRE.", "ink", 46), ("ONE SCRIPT.", "red", 70)],
      cap="QIN SHI HUANG · 221 BC", flash=0.4, icon=(900, 390, 200)),
    S(art_wall, 2.6, ch=CH3, year=-214, k=0.423, head=[("THEN WE BUILT", "ink", 46), ("THE WALL.", "red", 70)],
      cap="21,196 KM · TWO THOUSAND YEARS OF BUILDING", focus=(800, 450), icon=(900, 480, 260)),
    S(art_terracotta, 2.6, ch=CH3, year=-210, k=0.424, head=[("AN ARMY", "ink", 46), ("OF CLAY.", "red", 70)],
      cap="TERRACOTTA ARMY · 8,000 SOLDIERS · 210 BC", hx=640, hy=70, align="center", focus=(640, 420),
      icon=(640, 470, 240)),
    # IV
    S(art_silkroad, 2.6, ch=CH4, year=-138, k=0.428, head=[("WE OPENED", "ink", 42), ("THE SILK ROAD.", "red", 58)],
      cap="ZHANG QIAN · 138 BC · 6,400 KM", hx=92, hy=470, flash=0.4, focus=(700, 330), icon=(640, 330, 260)),
    S(art_paper, 2.3, ch=CH4, year=105, k=0.432, head=[("THEN WE MADE", "ink", 46), ("PAPER.", "red", 72)],
      cap="CAI LUN · AD 105", icon=(880, 420, 250)),
    S(art_seismo, 2.4, ch=CH4, year=132, k=0.433, head=[("WE HEARD", "ink", 46), ("THE EARTH.", "red", 66)],
      cap="ZHANG HENG'S SEISMOSCOPE · AD 132", icon=(900, 390, 270)),
    # V
    S(art_changan, 2.4, ch=CH5, year=700, k=0.441, head=[("THE LARGEST CITY", "ink", 42), ("ON EARTH.", "red", 66)],
      cap="CHANG'AN · ONE MILLION PEOPLE · c. AD 700", flash=0.4, icon=(860, 470, 280)),
    S(art_poem, 2.8, ch=CH5, year=726, k=0.444, head=[("WE WROTE", "ink", 46), ("48,900 POEMS.", "red", 62)],
      cap="QUIET NIGHT THOUGHT · LI BAI · c. 726", icon=(1080, 330, 230)),
    S(art_diamond, 2.3, ch=CH5, year=868, k=0.449, head=[("THE OLDEST", "ink", 46), ("PRINTED BOOK.", "red", 62)],
      cap="THE DIAMOND SUTRA · DATED AD 868", icon=(700, 410, 220)),
    # VI
    S(art_movable, 2.4, ch=CH6, year=1040, k=0.458, head=[("THEN THE LETTERS", "ink", 42), ("LEARNED TO MOVE.", "red", 56)],
      cap="BI SHENG · MOVABLE TYPE · c. 1040", flash=0.4, icon=(880, 420, 230)),
    S(art_firearrow, 2.3, ch=CH6, year=1044, k=0.462, head=[("WE TAUGHT", "ink", 46), ("FIRE TO FLY.", "red", 64)],
      cap="GUNPOWDER · WUJING ZONGYAO · 1044", icon=(900, 300, 260)),
    S(art_compass, 2.3, ch=CH6, year=1088, k=0.466, head=[("WE FOUND", "ink", 46), ("SOUTH.", "red", 72)],
      cap="THE MAGNETIC NEEDLE · SHEN KUO · 1088", icon=(900, 390, 250)),
    S(art_bridge, 2.6, ch=CH6, year=1120, k=0.47, head=[("WE PAINTED", "ink", 46), ("THE CITY.", "red", 66)],
      cap="ALONG THE RIVER DURING QINGMING · ZHANG ZEDUAN", hy=34, hx=92, icon=(900, 430, 250)),
    # VII
    S(art_1405, 2.4, ch=CH7, year=1405, k=0.48, head=[("THE TREASURE FLEET", "ink", 34), ("SET SAIL.", "red", 54)],
      cap="ZHENG HE · 317 SHIPS · 27,800 MEN", hy=110, flash=0.5, icon=(860, 420, 250)),
    S(art_zhenghe, 2.6, ch=CH7, year=1409, k=0.482, head=[("ALL THE WAY", "ink", 46), ("TO AFRICA.", "red", 66)],
      cap="SEVEN VOYAGES · 1405–1433", focus=(700, 400), icon=(700, 360, 260)),
    S(art_giraffe, 2.4, ch=CH7, year=1414, k=0.484, head=[("WE CAME HOME", "ink", 42), ("WITH A GIRAFFE.", "red", 58)],
      cap="HAILED AS A QILIN · 1414", icon=(880, 400, 260)),
    S(art_forbidden, 2.6, ch=CH7, year=1420, k=0.487, head=[("THEN WE BUILT", "ink", 46), ("A PALACE.", "red", 68)],
      cap="THE FORBIDDEN CITY · 980 BUILDINGS · 1420", icon=(870, 400, 240)),
    S(art_porcelain, 2.3, ch=CH7, year=1430, k=0.49, head=[("THE WORLD", "ink", 46), ("WANTED CHINA.", "red", 62)],
      cap="BLUE-AND-WHITE PORCELAIN · JINGDEZHEN", icon=(900, 420, 250)),
    # VIII
    S(art_close, 2.4, "ember", ch=CH8, year=1433, k=0.49, head=[("THEN WE", "white", 46), ("CLOSED THE *DOORS.", "white", 52)],
      cap="THE LAST VOYAGE · 1433", flash=0.3, icon=(890, 400, 260)),
    S(art_ruins, 2.6, "ember", ch=CH8, year=1860, k=0.5, head=[("THE LIGHTS", "white", 50), ("WENT *OUT.", "white", 70)],
      cap="THE OLD SUMMER PALACE BURNS · 1860", icon=(900, 380, 240)),
    S(art_lamp, 2.8, "ember", ch=CH8, year=1918, k=0.53, head=[("BUT THE BRUSH", "white", 46), ("KEPT *MOVING.", "white", 60)],
      cap="LU XUN · A MADMAN'S DIARY · 1918", icon=(700, 440, 260)),
    # IX
    S(art_open, 2.3, ch=CH9, year=1978, k=0.58, head=[("THEN WE", "ink", 46), ("OPENED THE DOORS.", "red", 50)],
      cap="REFORM AND OPENING UP · 1978", flash=0.8, icon=(1010, 420, 260)),
    S(art_shenzhen, 2.6, ch=CH9, year=1980, year_to=2020, k=0.62, head=[("A FISHING VILLAGE", "ink", 40),
                                                                        ("BECAME A CITY.", "red", 62)],
      cap="SHENZHEN · 1980: 30,000 PEOPLE · 2020: 17,560,000", icon=(820, 420, 240)),
    S(art_poverty, 2.6, ch=CH9, year=1981, year_to=2019, k=0.64,
      head=lambda lt: [(f"{int(800_000_000 * eo(seg(lt, 0.3, 2.2))):,}", "red", 64), ("OUT OF POVERTY.", "ink", 44)],
      cap="WORLD BANK · 1981–2019", icon=(900, 420, 260)),
    S(art_dam, 2.4, ch=CH9, panel=(40, 90, 620, 230), year=2012, k=0.672, head=[("THREE GORGES.", "ink", 46), ("22,500 MW.", "red", 70)],
      cap="THE LARGEST POWER STATION ON EARTH · 2012", icon=(820, 420, 260)),
    S(art_train, 2.3, ch=CH9, year=2023, k=0.69, head=[("WE LAID", "ink", 46), ("45,000 KM OF RAIL.", "red", 56)],
      cap="HIGH-SPEED · MORE THAN THE REST OF THE WORLD COMBINED", icon=(520, 450, 200)),
    # X
    S(art_launch, 2.6, "dark", ch=CH10, year=2003, k=0.7, head=[("THEN WE", "white", 50), ("LEFT.", "gold", 128)],
      cap="SHENZHOU 5 · YANG LIWEI · OCTOBER 15, 2003", flash=0.6, icon=(900, 380, 280)),
    S(art_fast, 2.3, "dark", ch=CH10, year=2016, k=0.71, head=[("WE BUILT", "white", 48), ("AN EAR.", "gold", 80)],
      cap="FAST · 500 M DISH · GUIZHOU · 2016", icon=(880, 400, 300)),
    S(art_farside, 2.5, "space", ch=CH10, year=2019, k=0.716, head=[("THE FAR SIDE", "white", 50), ("OF THE MOON.", "gold", 66)],
      cap="CHANG'E 4 · THE FIRST LANDING THERE · 2019", icon=(820, 420, 220)),
    S(art_mars, 2.4, "space", ch=CH10, year=2021, k=0.72, head=[("ZHURONG", "white", 50), ("ON MARS.", "gold", 80)],
      cap="TIANWEN-1 · MAY 15, 2021", icon=(1000, 380, 250)),
    S(art_tiangong, 2.4, "space", ch=CH10, year=2022, k=0.724, head=[("A HOME", "white", 50), ("IN ORBIT.", "gold", 80)],
      cap="TIANGONG SPACE STATION · 2022", icon=(840, 320, 260)),
    # XI
    S(art_tokamak, 2.6, "dark", ch=CH11, year=2025, k=0.73, head=[("WE LIT", "white", 50), ("A SUN ON EARTH.", "gold", 66)],
      cap="EAST TOKAMAK · 1,066 SECONDS · HEFEI · 2025", flash=0.6, icon=(880, 400, 290)),
    # XII
    S(art_dyson, 2.4, "space", ch=CH12, year="+1,000 YRS", k=2.0, head=[("KARDASHEV", "white", 50), ("TYPE II.", "gold", 84)],
      cap="HARNESS A STAR", flash=0.4),
    S(art_galaxy, 2.4, "space", ch=CH12, year="+100,000 YRS", k=2.9, head=[("TYPE", "white", 50), ("III.", "gold", 120)],
      cap="HARNESS A GALAXY"),
    S(art_flip, 2.2, "dark", hud=False, focus=(640, 360)),
    S(art_5000, 2.4, "space", hud=False, head=[("5,000 YEARS.", "white", 84)], hx=640, hy=300, align="center",
      focus=(640, 380), stagger=0.3, t0=0.2),
    # the end
    S(art_inkwet, 3.0, "dark", hud=False, head=[("THE INK", "white", 56), ("IS STILL *WET.", "white", 56)], hx=640, hy=70,
      align="center", focus=(640, 420), zoom=(1.0, 1.04), stagger=0.25, t0=0.4, flash=0.5),
    S(art_quote, 3.6, "dark", hud=False, focus=(640, 420), zoom=(1.04, 1.08)),
    S(art_final, 4.4, "dark", hud=False, head=[("UNBROKEN.", "gold", 104)], hx=640, hy=420, align="center",
      cap="WENMING · 文明 · 2070 BC — ∞", focus=(640, 420), zoom=(1.0, 1.06), t0=0.5, fade_out=1.3),
]


BEAT = 0.5  # 120 BPM: every cut lands on a beat


def schedule():
    t = 0.0
    for i, s in enumerate(SHOTS):
        s["dur"] = max(BEAT, round(s["dur"] / BEAT) * BEAT)
        s["start"] = t
        s["index"] = i
        t += s["dur"]
    return t


TOTAL = schedule()


def draw_shot(canvas, s, lt, prev, with_text=True, mode=None):
    mode = mode or BG_MODE[s["bg"]]
    ctx = Ctx(canvas, mode, lt, s["dur"], s)
    p = clamp(lt / s["dur"])
    z = lerp(s["zoom"][0], s["zoom"][1], ease(p))
    fx, fy = s["focus"]
    canvas.save()
    canvas.translate(fx + 0.35 * math.sin(lt * 7.1), fy + 0.35 * math.cos(lt * 5.3))
    canvas.scale(z, z)
    canvas.translate(-fx, -fy)
    s["art"](ctx, lt, p)
    canvas.restore()
    if with_text and s["hud"]:  # keep the HUD legible over busy art
        col = ctx.pal["fill"] if not ctx.dark else ((22, 16, 12) if s["bg"] == "ember" else (11, 13, 20))
        for y0, y1 in ((720, 600), (0, 96)):
            sh = skia.GradientShader.MakeLinear([skia.Point(0, y0), skia.Point(0, y1)],
                                                [skia.ColorSetARGB(200, *col), skia.ColorSetARGB(0, *col)])
            canvas.drawRect(skia.Rect.MakeLTRB(0, min(y0, y1), W, max(y0, y1)), skia.Paint(Shader=sh))
    if with_text and s.get("panel"):
        soft_panel(ctx, *s["panel"])
    if with_text and s["head"]:
        lines = s["head"](lt) if callable(s["head"]) else s["head"]
        headline(ctx, lines, s["hx"], s["hy"], cap=s["cap"], align=s["align"],
                 stagger=s.get("stagger", 0.13), t0=s.get("t0", 0.12))
    if with_text and s["hud"]:
        hud(ctx, s, prev)
    return ctx


def render_frame(i):
    g = worker_state()
    t = i / FPS
    idx = max(j for j, s in enumerate(SHOTS) if s["start"] <= t + 1e-6)
    s = SHOTS[idx]
    lt = t - s["start"]
    prev = SHOTS[idx - 1] if idx else None
    canvas = g["surface"].getCanvas()
    canvas.clear(skia.ColorBLACK)
    canvas.drawImage(g["bg"][s["bg"]], 0, 0)
    draw_shot(canvas, s, lt, prev)
    fade = s.get("fade_out")
    if fade and lt > s["dur"] - fade:
        a = seg(lt, s["dur"] - fade, s["dur"])
        canvas.drawRect(skia.Rect.MakeWH(W, H), skia.Paint(Color=skia.ColorSetARGB(int(255 * a), 0, 0, 0)))
    rgb = g["surface"].makeImageSnapshot().toarray(colorType=skia.kRGBA_8888_ColorType)[..., :3]
    cut = max(0.0, 1 - lt / 0.12) if idx else 0.0
    flash = s["flash"] * max(0.0, 1 - lt / 0.2)
    return finish(np.ascontiguousarray(rgb), BG_MODE[s["bg"]] == "dark", i, cut, flash).tobytes()



# ---------------------------------------------------------------------------
# Soundtrack: synthesized guzheng, bass, pads, taiko and a dizi-like lead
# ---------------------------------------------------------------------------
SR = 44100
MINOR = [62, 65, 67, 69, 72]      # D yu mode (D F G A C)
MAJOR = [62, 64, 66, 69, 71]      # D gong mode (D E F# A B)


def hz(m):
    return 440.0 * 2 ** ((m - 69) / 12)


def deg(scale, d, octave=0):
    return scale[d % 5] + 12 * (d // 5 + octave)


def env(n, a, d, sustain=0.0, sr=SR):
    t = np.arange(n) / sr
    e = np.minimum(t / max(a, 1e-4), 1.0) * np.exp(-t / d) * (1 - sustain) + sustain * np.minimum(t / max(a, 1e-4), 1.0)
    return e


def pluck(f, dur=2.0, amp=0.3, bright=1.0):
    n = int(dur * SR)
    t = np.arange(n) / SR
    out = np.zeros(n)
    for k in range(1, 9):
        fk = f * k * (1 + 0.0004 * k * k)
        out += (bright ** (k - 1)) / k * np.sin(2 * np.pi * fk * t) * np.exp(-t * (1.6 + 1.5 * k))
    out *= np.minimum(t / 0.002, 1)
    return amp * out


def tone(f, dur, amp=0.2, harm=(1.0, 0.5, 0.25, 0.12), a=0.02, d=0.6, vib=0.0, sustain=0.0):
    n = int(dur * SR)
    t = np.arange(n) / SR
    ph = 2 * np.pi * f * t + (vib * np.sin(2 * np.pi * 5.2 * t) * np.minimum(t / 0.3, 1) if vib else 0)
    out = sum(h * np.sin(ph * (k + 1)) for k, h in enumerate(harm))
    e = env(n, a, d, sustain)
    rel = np.minimum(1, (n - np.arange(n)) / (0.08 * SR))
    return amp * out * e * rel


def pad(freqs, dur, amp=0.08, a=0.6):
    n = int(dur * SR)
    t = np.arange(n) / SR
    out = np.zeros(n)
    for f in freqs:
        for det in (-0.25, 0.0, 0.25):
            ff = f * 2 ** (det / 12)
            for k in range(1, 7):
                out += np.sin(2 * np.pi * ff * k * t + k * det) / (k * 1.3)
    e = np.minimum(t / a, 1) * np.minimum(1, (n - np.arange(n)) / (0.5 * SR))
    return amp * out * e / (len(freqs) * 3)


def taiko(amp=0.8, dur=1.2):
    n = int(dur * SR)
    t = np.arange(n) / SR
    f = 48 + 90 * np.exp(-t * 18)
    body = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 4.5)
    rng = np.random.default_rng(1)
    slap = np.convolve(rng.standard_normal(n), np.ones(24) / 24, "same") * np.exp(-t * 40)
    return amp * (body + 0.35 * slap)


def tick(amp=0.12, f=1800):
    n = int(0.08 * SR)
    t = np.arange(n) / SR
    rng = np.random.default_rng(2)
    return amp * (np.sin(2 * np.pi * f * t) * np.exp(-t * 90) + 0.3 * rng.standard_normal(n) * np.exp(-t * 200))


def gong(amp=0.5, dur=7.0):
    n = int(dur * SR)
    t = np.arange(n) / SR
    out = np.zeros(n)
    for k, (r, d) in enumerate(((1.0, 3.5), (1.48, 2.8), (2.03, 2.2), (2.74, 1.6), (3.51, 1.2), (4.3, 0.9))):
        out += np.sin(2 * np.pi * 88 * r * t + 2 * np.sin(2 * np.pi * 0.7 * t) * (k + 1) * 0.1) * np.exp(-t / d) / (k + 1)
    return amp * out * np.minimum(t / 0.01, 1)


def riser(dur, amp=0.25):
    n = int(dur * SR)
    t = np.arange(n) / SR
    rng = np.random.default_rng(3)
    noise = np.convolve(rng.standard_normal(n), np.ones(6) / 6, "same")
    sweep = np.sin(2 * np.pi * np.cumsum(200 + 1400 * (t / dur) ** 2) / SR)
    return amp * (0.5 * noise + 0.5 * sweep) * (t / dur) ** 2.2


def kick(amp=0.9):
    n = int(0.35 * SR)
    t = np.arange(n) / SR
    f = 42 + 110 * np.exp(-t * 35)
    return amp * np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 9)


def snare(amp=0.5):
    n = int(0.3 * SR)
    t = np.arange(n) / SR
    rng = np.random.default_rng(6)
    noise = rng.standard_normal(n)
    noise = noise - np.convolve(noise, np.ones(4) / 4, "same")
    return amp * (0.6 * noise * np.exp(-t * 18) + 0.5 * np.sin(2 * np.pi * 190 * t) * np.exp(-t * 25))


def crash(amp=0.3, dur=2.5):
    n = int(dur * SR)
    t = np.arange(n) / SR
    rng = np.random.default_rng(7)
    noise = rng.standard_normal(n)
    noise = noise - np.convolve(noise, np.ones(3) / 3, "same")
    return amp * noise * np.exp(-t * 2.2) * np.minimum(t / 0.002, 1)


def stab(freqs, amp=0.12, dur=0.35):
    """A short brass-like chord hit."""
    out = sum(tone(f, dur, amp, harm=(1, .8, .6, .45, .3, .2, .12), a=0.01, d=0.18) for f in freqs)
    return out / max(len(freqs), 1) * 2


def compose(total):
    n = int((total + 3) * SR)
    L = np.zeros(n)
    Rr = np.zeros(n)

    def put(sig, t, pan=0.0, gain=1.0):
        i = int(t * SR)
        if i >= n or t < 0:
            return
        sig = sig[: n - i] * gain
        L[i:i + len(sig)] += sig * math.sqrt(0.5 * (1 - pan))
        Rr[i:i + len(sig)] += sig * math.sqrt(0.5 * (1 + pan))

    def start_of(pred):
        return next(s["start"] for s in SHOTS if pred(s))

    t_act1 = start_of(lambda s: s["ch"] == CH1)
    t_qin = start_of(lambda s: s["ch"] == CH3)
    t_tang = start_of(lambda s: s["ch"] == CH5)
    t_night = start_of(lambda s: s["ch"] == CH8)
    t_reb = start_of(lambda s: s["ch"] == CH9)
    t_sky = start_of(lambda s: s["ch"] == CH10)
    t_future = start_of(lambda s: s["ch"] == CH12)
    t_flip = start_of(lambda s: s["art"] is art_flip)
    t_5000 = start_of(lambda s: s["art"] is art_5000)
    t_end = start_of(lambda s: s["art"] is art_inkwet)
    t_quote = start_of(lambda s: s["art"] is art_quote)
    t_final = start_of(lambda s: s["art"] is art_final)
    bar = 4 * BEAT
    s16 = BEAT / 4

    chords_min = [[50, 57, 62, 65], [46, 53, 58, 62], [48, 55, 60, 64], [45, 52, 57, 60]]
    chords_maj = [[50, 57, 62, 66], [47, 54, 59, 62], [43, 50, 55, 59], [45, 52, 57, 61]]
    ost_pat = [0, 2, 3, 2, 4, 3, 2, 3, 0, 2, 3, 2, 5, 4, 3, 2]
    motif_a = [(4, 1), (3, .5), (2, .5), (3, 1), (1, 1), (2, 1.5), (1, .5), (0, 2)]
    motif_b = [(5, 1), (4, .5), (3, .5), (4, 1), (6, 1), (7, 1.5), (6, .5), (5, 2)]

    # cold open: a pulsing ostinato that builds from the first frame
    b = 0
    t = 0.0
    while t < t_act1 - 1e-6:
        ch = chords_min[b % 4]
        grow = t / t_act1
        put(pad([hz(m) for m in ch[1:]], bar + 0.2, 0.10 + 0.06 * grow, a=0.2), t)
        for k in range(16):
            tt = t + k * s16
            if tt >= t_act1:
                break
            m = deg(MINOR, ost_pat[k], -1)
            put(tone(hz(m), s16 * 1.2, 0.07 + 0.08 * grow, harm=(1, .7, .5, .35, .2), a=0.003, d=0.07), tt,
                pan=0.3 * (1 if k % 2 else -1))
        for k in range(4):
            tt = t + k * BEAT
            if tt < t_act1:
                put(kick(0.5 + 0.4 * grow), tt)
                put(tone(hz(ch[0] - 12), BEAT, 0.16, harm=(1, .5, .2), a=0.004, d=0.2), tt)
        t += bar
        b += 1
    for s in SHOTS[:4]:
        put(taiko(0.9), s["start"])
        put(stab([hz(m) for m in (50, 57, 62, 65)], 0.14), s["start"])
    put(riser(2.0, 0.3), t_act1 - 2.0)
    for k in range(8):  # snare fill into the first act
        put(snare(0.25 + 0.05 * k), t_act1 - 1.0 + k * BEAT / 4)

    # the main drive
    b = 0
    t = t_act1
    while t < t_end - 1e-6:
        night = t_night <= t < t_reb
        bright = t >= t_reb
        climax = t >= t_sky
        scale = MAJOR if bright else MINOR
        ch = (chords_maj if bright else chords_min)[b % 4]
        lvl = 1 + (t >= t_qin) + (t >= t_tang) + bright + climax      # 1..5 layers
        blen = min(bar, t_end - t)
        put(pad([hz(m) for m in ch[1:]], blen + 0.2, 0.09 + 0.02 * lvl, a=0.15), t)
        # sixteenth-note staccato ostinato, doubled an octave up once things build
        for k in range(16):
            tt = t + k * s16
            if tt >= t_end:
                break
            d = ost_pat[k] + (b % 2)
            m = deg(scale, d, -1)
            acc = 1.25 if k % 4 == 0 else 1.0
            put(tone(hz(m), s16 * 1.2, (0.10 + 0.012 * lvl) * acc, harm=(1, .7, .5, .35, .2), a=0.003, d=0.07),
                tt, pan=-0.3)
            if lvl >= 3 and not night:
                put(tone(hz(m + 12), s16 * 1.1, 0.05 + 0.01 * lvl, harm=(1, .5, .3), a=0.003, d=0.06), tt, pan=0.3)
        # octave bass in eighths
        for k in range(8):
            tt = t + k * BEAT / 2
            if tt >= t_end:
                break
            m = ch[0] - 12 + (12 if k % 2 else 0)
            put(tone(hz(m), BEAT / 2, 0.2, harm=(1, .6, .3, .15), a=0.003, d=0.15), tt)
        # drums: four on the floor, backbeat, hats; half-time and heavy at night
        for k in range(4):
            tt = t + k * BEAT
            if tt >= t_end:
                break
            if night:
                if k == 0:
                    put(taiko(1.0, 1.4), tt)
                if k == 2:
                    put(snare(0.45), tt)
                put(kick(0.6), tt)
                continue
            put(kick(0.85), tt)
            if k in (1, 3) and lvl >= 2:
                put(snare(0.42 + 0.04 * lvl), tt)
            if k == 0:
                put(taiko(0.5 + 0.1 * lvl), tt)
            hats = 4 if lvl >= 3 else 2
            for h in range(hats):
                put(tick(0.045 + 0.01 * lvl, 6000 + 800 * (h % 2)), tt + h * BEAT / hats, pan=0.4 * (h % 2 * 2 - 1))
        # lead melody from the Tang dynasty on; a crying erhu line at night
        if lvl >= 3 or night:
            motif = motif_a if b % 4 < 2 else motif_b
            half = (b % 2) * 4
            tt = t
            pos = 0
            for d, ln in motif:
                if pos < half:
                    pos += ln
                    continue
                if pos >= half + 4 or tt >= t_end:
                    break
                f = hz(deg(scale, d, 0 if not night else -1))
                if night:
                    put(tone(f, ln * BEAT, 0.12, harm=(1, .45, .3, .15, .1), a=0.06, d=1.5, vib=2.5, sustain=0.5), tt)
                else:
                    put(tone(f * 2, ln * BEAT, 0.06 + 0.012 * lvl, harm=(1, .3, .12, .05), a=0.02, d=1.0, vib=1.2,
                             sustain=0.6), tt, pan=-0.1)
                    put(pluck(f, 1.2, 0.14), tt, pan=0.15)
                tt += ln * BEAT
                pos += ln
        t += bar
        b += 1

    # every cut gets a hit; chapter changes get a fill, a crash and a stab
    prev_ch = None
    for s in SHOTS[4:]:
        if s["start"] >= t_end:
            break
        chord = [hz(m) for m in (50, 57, 62, 66 if s["start"] >= t_reb else 65)]
        if s["ch"] != prev_ch:
            put(crash(0.28), s["start"])
            put(stab(chord, 0.18), s["start"])
            put(taiko(1.0), s["start"])
            for k in range(4):
                put(snare(0.3 + 0.06 * k), s["start"] - BEAT + k * BEAT / 4)
        else:
            put(stab(chord, 0.08, 0.2), s["start"])
        prev_ch = s["ch"]
    put(gong(0.5), t_night)
    put(riser(2.0, 0.3), t_reb - 2.0)
    # the flip: an accelerating snare roll into 5,000 years
    k = 0
    tt = t_flip
    while tt < t_5000:
        put(snare(0.2 + 0.3 * (tt - t_flip) / (t_5000 - t_flip)), tt)
        tt += BEAT / (2 if tt < t_flip + 1.0 else 4 if tt < t_5000 - 0.6 else 8)
    put(riser(t_5000 - t_flip, 0.3), t_flip)
    put(crash(0.4, 3.5), t_5000)
    put(gong(0.7), t_5000)
    put(taiko(1.2, 2.0), t_5000)
    put(stab([hz(m) for m in (38, 50, 57, 62, 66)], 0.3, 1.2), t_5000)

    # the ending: still driving through "the ink is still wet", calmer for the quote, one last hit
    put(pad([hz(m) for m in (50, 57, 62, 66, 69)], total - t_end + 2, 0.16, a=0.4), t_end)
    tt = t_end
    while tt < t_quote - 1e-6:
        for k in range(4):
            put(kick(0.8), tt + k * BEAT)
            if k in (1, 3):
                put(snare(0.4), tt + k * BEAT)
        for k in range(16):
            put(tone(hz(deg(MAJOR, ost_pat[k], -1)), s16 * 1.2, 0.11, harm=(1, .7, .5, .35, .2), a=0.003, d=0.07),
                tt + k * s16)
        tt += bar
    put(crash(0.3), t_end)
    put(taiko(1.0), t_end)
    for k in range(int((t_final - t_quote) / (BEAT / 2))):
        d = [0, 2, 4, 5, 7, 5, 4, 2][k % 8]
        put(pluck(hz(deg(MAJOR, d, 0)), 1.6, 0.16), t_quote + k * BEAT / 2, pan=0.4 * math.sin(k))
        if k % 2 == 0:
            put(taiko(0.35, 1.0), t_quote + k * BEAT / 2)
    put(gong(0.8, 8.0), t_final)
    put(taiko(1.3, 2.0), t_final)
    put(crash(0.35, 4.0), t_final)
    put(stab([hz(m) for m in (38, 50, 57, 62, 66)], 0.3, 2.0), t_final)

    keys = [(0, 0.8), (t_act1, 0.85), (t_night - 0.3, 0.95), (t_night + 0.3, 0.8), (t_reb - 0.3, 0.85),
            (t_reb + 0.3, 0.92), (t_sky, 1.0), (t_quote, 1.0), (t_quote + 0.5, 0.75), (total + 3, 0.75)]
    tt = np.arange(n) / SR
    gcurve = np.interp(tt, [k for k, _ in keys], [v for _, v in keys])
    L *= gcurve
    Rr *= gcurve

    rng = np.random.default_rng(5)
    ir_n = int(1.6 * SR)
    ir = rng.standard_normal(ir_n) * np.exp(-np.arange(ir_n) / (0.3 * SR))
    ir = np.convolve(ir, np.ones(8) / 8, "same")
    ir /= np.abs(ir).sum() / 12
    size = 1 << int(np.ceil(np.log2(n + ir_n)))
    IR = np.fft.rfft(ir, size)
    out = []
    for chn in (L, Rr):
        wet = np.fft.irfft(np.fft.rfft(chn, size) * IR, size)[:n]
        out.append(chn + 0.22 * wet)
    st = np.stack(out, 1)
    fade = np.ones(n)
    fe = int(total * SR)
    fs = int((total - 2.5) * SR)
    fade[fs:fe] = np.linspace(1, 0, fe - fs)
    fade[fe:] = 0
    st *= fade[:, None]
    st /= np.percentile(np.abs(st), 99.5) + 1e-9
    st = np.tanh(st * 1.1) * 0.92
    return st[: int(total * SR)]


def write_wav(path, st):
    data = (np.clip(st, -1, 1) * 32767).astype(np.int16)
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(data.tobytes())


def render():
    ensure_fonts()
    os.makedirs(OUT_DIR, exist_ok=True)
    wav = os.path.join(OUT_DIR, "_soundtrack.wav")
    out = os.path.join(OUT_DIR, OUT_NAME + ".mp4")
    print("composing soundtrack ...")
    write_wav(wav, compose(TOTAL))
    nframes = int(round(TOTAL * FPS))
    cmd = [imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
           "-i", wav, "-map", "0:v", "-map", "1:a",
           "-c:v", "libx264", "-preset", "slow", "-crf", "26", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", out]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    print(f"rendering {nframes} frames ({TOTAL:.1f} s, {len(SHOTS)} shots) ...")
    with Pool(os.cpu_count()) as pool:
        for i, frame in enumerate(pool.imap(render_frame, range(nframes), chunksize=4)):
            proc.stdin.write(frame)
            if i % (FPS * 10) == 0:
                print(f"  {i / FPS:5.1f} s")
    proc.stdin.close()
    proc.wait()
    print("wrote", out)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def stills(at=0.85):
    """One frame per shot (at `at` of its duration), tiled into contact sheets."""
    os.makedirs(OUT_DIR, exist_ok=True)
    frames = [int((s["start"] + s["dur"] * at) * FPS) for s in SHOTS]
    with Pool(os.cpu_count()) as pool:
        imgs = pool.map(render_frame, frames)
    per = 12
    for k in range(0, len(imgs), per):
        sheet = Image.new("RGB", (640 * 3, 360 * 4))
        for j, b in enumerate(imgs[k:k + per]):
            im = Image.frombytes("RGB", (W, H), b).resize((640, 360), Image.LANCZOS)
            sheet.paste(im, ((j % 3) * 640, (j // 3) * 360))
        sheet.save(os.path.join(OUT_DIR, f"_sheet_{k // per:02d}.png"))
    for n in sys.argv[2:]:
        Image.frombytes("RGB", (W, H), imgs[int(n)]).save(os.path.join(OUT_DIR, f"_still_{int(n):02d}.png"))
    print(f"{len(SHOTS)} shots, {TOTAL:.1f} s")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--stills":
        stills()
    else:
        render()
