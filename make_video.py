#!/usr/bin/env python3
"""Render a short ink-wash style video about Chinese civilization with Chinese subtitles.

Everything is generated procedurally: scenes are drawn with Pillow/numpy, the
soundtrack is a synthesized pentatonic guzheng-style melody, and the video is
encoded with ffmpeg (from imageio-ffmpeg). Subtitles are burned into the picture
and also embedded as a soft subtitle track and written to a standalone .srt file.

    pip install pillow numpy imageio-ffmpeg
    python3 make_video.py
"""
import math
import os
import subprocess
import sys
import urllib.request
import wave
from contextlib import contextmanager

import imageio_ffmpeg
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = os.path.dirname(os.path.abspath(__file__))
FONT_DIR = os.path.join(ROOT, "fonts")
OUT_DIR = os.path.join(ROOT, "output")
FONTS = {
    # Both fonts are SIL Open Font License, served by Google Fonts.
    "brush": ("MaShanZheng.ttf",
              "https://fonts.gstatic.com/s/mashanzheng/v18/NaPecZTRCLxvwo41b4gvzkXaRMQ.ttf"),
    "serif": ("NotoSerifSC-Bold.ttf",
              "https://fonts.gstatic.com/s/notoserifsc/v35/H4cyBXePl9DZ0Xe7gG9cyOj7uK2-n-D2rd4FY7RlrCWv.ttf"),
}

W, H = 1280, 720            # output size
FPS = 24
ZOOM = 1.1                  # scene canvases are drawn larger for the Ken Burns move
CW, CH = int(W * ZOOM), int(H * ZOOM)
SS = 2                      # supersampling for anti-aliased shapes
XFADE = 1.0                 # crossfade between scenes, seconds

PAPER = np.array([238, 228, 205], dtype=np.float32)
INK = (28, 28, 34)
RED = (178, 34, 34)

# ---------------------------------------------------------------------------
# Script: (era title, date line, scene duration, subtitle lines, drawing fn name)
# ---------------------------------------------------------------------------
SCRIPT = [
    ("", "", 12, [
        "在东亚大地上，有一个延续五千多年、从未中断的文明。",
        "它就是——中华文明。",
    ], "title"),
    ("文明曙光", "约公元前7000年 — 前2000年", 16, [
        "黄河与长江，两条母亲河孕育了最早的农耕村落。",
        "仰韶的彩陶、良渚的玉器，闪耀着文明的曙光。",
        "北方种粟，南方种稻，先民在这里繁衍生息。",
    ], "rivers"),
    ("夏商周", "约公元前2070年 — 前256年", 16, [
        "夏商周三代，国家与礼制逐渐形成。",
        "商代的甲骨文，是汉字成熟的早期形态。",
        "厚重的青铜鼎，象征着权力与礼乐秩序。",
    ], "bronze"),
    ("春秋战国", "公元前770年 — 前221年", 16, [
        "春秋战国，天下纷争，思想却空前活跃。",
        "孔子讲“仁”，老子论“道”，墨子倡“兼爱”。",
        "百家争鸣，奠定了中国思想的根基。",
    ], "bamboo"),
    ("秦汉", "公元前221年 — 公元220年", 16, [
        "公元前221年，秦统一六国，书同文，车同轨。",
        "万里长城，蜿蜒于崇山峻岭之间。",
        "张骞出使西域，丝绸之路连接起东方与西方。",
    ], "wall"),
    ("四大发明", "造纸术 · 印刷术 · 火药 · 指南针", 16, [
        "造纸术、印刷术、火药和指南针——",
        "中国古代的四大发明，深刻地改变了世界。",
        "知识得以广泛传播，航船得以远渡重洋。",
    ], "inventions"),
    ("唐宋", "公元618年 — 1279年", 16, [
        "唐朝开放包容，长安是当时世界上最繁华的都市之一。",
        "李白、杜甫的诗篇，苏轼、李清照的词章，传唱千年。",
        "宋代的商业、科技与艺术，也达到了新的高峰。",
    ], "poetry"),
    ("元明清", "公元1271年 — 1912年", 16, [
        "明代郑和七下西洋，庞大的船队远航至东非海岸。",
        "紫禁城巍峨壮丽，见证了明清两代的兴衰。",
        "《红楼梦》等古典名著，描绘出人间百态。",
    ], "ming"),
    ("走向未来", "传承 · 创新", 16, [
        "近代以来，中华民族历经磨难，自强不息。",
        "今天，古老的文明与现代科技交相辉映。",
        "从甲骨到芯片，从丝路到星辰大海。",
    ], "future"),
    ("", "", 13, [
        "传承千年的智慧，仍在照亮前行的道路。",
        "中华文明，生生不息。",
    ], "ending"),
]


# ---------------------------------------------------------------------------
# Fonts
# ---------------------------------------------------------------------------
def ensure_fonts():
    os.makedirs(FONT_DIR, exist_ok=True)
    for name, url in FONTS.values():
        path = os.path.join(FONT_DIR, name)
        if not os.path.exists(path) or os.path.getsize(path) < 100_000:
            print(f"downloading {name} ...")
            urllib.request.urlretrieve(url, path)


_font_cache = {}


def font(kind, size):
    key = (kind, size)
    if key not in _font_cache:
        _font_cache[key] = ImageFont.truetype(os.path.join(FONT_DIR, FONTS[kind][0]), size)
    return _font_cache[key]


# ---------------------------------------------------------------------------
# Drawing helpers
# ---------------------------------------------------------------------------
def fbm(n, seed, base=5, octaves=6, persistence=0.5):
    """1-D fractal noise in [0, 1] — linear interpolation gives crisp ridges."""
    rng = np.random.default_rng(seed)
    x = np.linspace(0, 1, n)
    total = np.zeros(n)
    amp, freq = 1.0, base
    for _ in range(octaves):
        pts = rng.random(freq + 1)
        total += amp * np.interp(x * freq, np.arange(freq + 1), pts)
        amp *= persistence
        freq *= 2
    total -= total.min()
    return total / total.max()


def paper_texture(w, h, seed=7):
    rng = np.random.default_rng(seed)
    coarse = Image.fromarray((rng.random((h // 16, w // 16)) * 255).astype(np.uint8))
    coarse = np.asarray(coarse.resize((w, h), Image.BICUBIC), dtype=np.float32) / 255
    fine = rng.random((h, w)).astype(np.float32)
    fibers = np.asarray(Image.fromarray((rng.random((h, w)) * 255).astype(np.uint8))
                        .filter(ImageFilter.BoxBlur(1)), dtype=np.float32) / 255
    grain = 0.55 * coarse + 0.25 * fine + 0.2 * fibers
    yy, xx = np.mgrid[0:h, 0:w]
    vignette = 1 - 0.18 * (((xx - w / 2) / (w / 2)) ** 2 + ((yy - h / 2) / (h / 2)) ** 2)
    return grain, vignette.astype(np.float32)


class Pen:
    """Coordinate-scaling wrapper around ImageDraw for supersampled masks."""

    def __init__(self, draw):
        self.d = draw

    @staticmethod
    def _s(pts):
        return [(x * SS, y * SS) for x, y in pts]

    def poly(self, pts):
        self.d.polygon(self._s(pts), fill=255)

    def ellipse(self, box):
        self.d.ellipse([v * SS for v in box], fill=255)

    def rect(self, box, radius=0):
        if radius:
            self.d.rounded_rectangle([v * SS for v in box], radius=radius * SS, fill=255)
        else:
            self.d.rectangle([v * SS for v in box], fill=255)

    def line(self, pts, width):
        self.d.line(self._s(pts), fill=255, width=max(1, int(width * SS)), joint="curve")

    def arc(self, box, start, end, width):
        self.d.arc([v * SS for v in box], start, end, fill=255, width=max(1, int(width * SS)))

    def text(self, xy, s, kind, size, anchor="mm"):
        self.d.text((xy[0] * SS, xy[1] * SS), s, font=font(kind, size * SS), fill=255, anchor=anchor)

    def vtext(self, x, y, s, kind, size, spacing=1.05):
        """Vertical text, top to bottom, centered on x."""
        for i, ch in enumerate(s):
            self.text((x, y + i * size * spacing), ch, kind, size, anchor="mt")


class Canvas:
    def __init__(self, w=CW, h=CH, bg=None):
        self.w, self.h = w, h
        self.arr = np.empty((h, w, 3), dtype=np.float32)
        self.arr[:] = PAPER if bg is None else bg

    @contextmanager
    def ink(self, color, alpha=1.0, blur=0.0):
        m = Image.new("L", (self.w * SS, self.h * SS), 0)
        yield Pen(ImageDraw.Draw(m))
        m = m.resize((self.w, self.h), Image.LANCZOS)
        if blur:
            m = m.filter(ImageFilter.GaussianBlur(blur))
        self.blend(color, np.asarray(m, dtype=np.float32) / 255 * alpha)

    def blend(self, color, a):
        a = a[..., None]
        self.arr = self.arr * (1 - a) + np.asarray(color, dtype=np.float32) * a

    def gradient_sky(self, top, bottom, y0=0, y1=None):
        y1 = self.h if y1 is None else y1
        t = np.clip((np.arange(self.h) - y0) / max(1, y1 - y0), 0, 1)[:, None, None]
        self.arr[:] = np.asarray(top, np.float32) * (1 - t) + np.asarray(bottom, np.float32) * t

    def mountains(self, base_y, height, color, alpha, seed, fade=160, base=4, x0=0, x1=None):
        """An ink-wash ridge: dark crest line, washing out into mist below."""
        x1 = self.w if x1 is None else x1
        prof = fbm(self.w, seed, base=base)
        edge = np.ones(self.w)
        span = x1 - x0
        xs = np.arange(self.w)
        edge = np.clip(np.minimum(xs - x0, x1 - xs) / (span * 0.25), 0, 1) if (x0 or x1 != self.w) else edge
        top = base_y - prof * height * np.sqrt(edge)
        yy = np.arange(self.h)[:, None].astype(np.float32)
        d = yy - top[None, :]
        a = np.clip(1 - d / fade, 0, 1) * (d >= 0)
        a = a * 0.75 + 0.35 * np.exp(-np.clip(d, 0, None) / 6) * (d >= 0)
        rng = np.random.default_rng(seed + 99)
        tex = np.asarray(Image.fromarray((rng.random((self.h // 4, self.w // 4)) * 255).astype(np.uint8))
                         .resize((self.w, self.h), Image.BICUBIC), np.float32) / 255
        a = a * (0.8 + 0.3 * tex) * alpha
        a[:, :x0] = 0
        a[:, x1:] = 0
        a = np.asarray(Image.fromarray((np.clip(a, 0, 1) * 255).astype(np.uint8))
                       .filter(ImageFilter.GaussianBlur(1.2)), np.float32) / 255
        self.blend(color, a)
        return top

    def glow(self, cx, cy, r, color, alpha):
        yy, xx = np.mgrid[0:self.h, 0:self.w]
        d = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
        self.blend(color, np.clip(1 - d / r, 0, 1) ** 2 * alpha)

    def finish(self, grain, vignette, amount=0.07):
        a = self.arr * ((1 - amount) + amount * 2 * grain[..., None]) * vignette[..., None]
        return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


def label(c, x, y, text, size=22):
    """A small caption on a paper tab so it stays legible over busy drawings."""
    w = len(text) * size + 24
    with c.ink((244, 236, 216), 0.9) as p:
        p.rect([x - w / 2, y - size * 0.85, x + w / 2, y + size * 0.85], radius=6)
    with c.ink(INK, 0.85) as p:
        p.text((x, y), text, "serif", size)


def seal(text, size=90, rot=-4, seed=3):
    """A red square seal (印章) as an RGBA image."""
    s = size * 2
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([6, 6, s - 6, s - 6], radius=14, fill=RED + (235,))
    d.rounded_rectangle([18, 18, s - 18, s - 18], radius=8, outline=(250, 235, 220, 255), width=5)
    f = font("brush", int(s * 0.36))
    if len(text) == 4:
        pos = [(0.68, 0.32), (0.68, 0.70), (0.32, 0.32), (0.32, 0.70)]  # read right column first
    else:
        pos = [(0.5, 0.31), (0.5, 0.71)]
    for ch, (px, py) in zip(text, pos):
        d.text((px * s, py * s), ch, font=f, fill=(250, 238, 225, 255), anchor="mm")
    rng = np.random.default_rng(seed)
    a = np.asarray(img.getchannel("A"), np.float32)
    a *= (rng.random(a.shape) > 0.06)
    img.putalpha(Image.fromarray(a.astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.6)))
    return img.rotate(rot, resample=Image.BICUBIC, expand=True).resize((size + 8, size + 8), Image.LANCZOS)


# ---------------------------------------------------------------------------
# Scenes (drawn on a CW x CH canvas; the centre W x H is what's mostly visible)
# ---------------------------------------------------------------------------
def scene_title(c):
    c.glow(900, 250, 260, (240, 200, 170), 0.35)
    with c.ink(RED, 0.88) as p:
        p.ellipse([840, 190, 960, 310])
    c.mountains(430, 220, INK, 0.28, seed=11, fade=260, base=3)
    c.mountains(520, 200, INK, 0.45, seed=12, fade=220)
    c.mountains(640, 180, INK, 0.75, seed=13, fade=180, base=6)
    with c.ink((190, 180, 160), 0.25, blur=12) as p:           # drifting mist
        p.ellipse([100, 470, 800, 560])
        p.ellipse([700, 560, 1400, 640])
    with c.ink(INK, 0.92) as p:
        p.vtext(420, 150, "中华文明", "brush", 118, 1.02)
    with c.ink((70, 60, 55), 0.85) as p:
        p.vtext(300, 260, "五千年的回响", "serif", 34, 1.25)


def scene_rivers(c):
    c.mountains(300, 120, INK, 0.18, seed=21, fade=160, base=3)
    # 黄河 (north) and 长江 (south) as broad flowing brush strokes
    xs = np.linspace(80, 1330, 200)
    yellow = 330 + 70 * np.sin(xs / 170) + 30 * np.sin(xs / 61)
    blue = 560 + 50 * np.sin(xs / 140 + 1.3) + 25 * np.sin(xs / 47)
    for ys, col, lab, lx in ((yellow, (196, 150, 60), "黄 河", 1180), (blue, (70, 110, 140), "长 江", 1180)):
        for width, al in ((34, 0.25), (18, 0.55), (7, 0.8)):
            with c.ink(col, al, blur=1.5) as p:
                p.line(list(zip(xs, ys)), width)
        with c.ink(INK, 0.85) as p:
            p.text((lx, ys[int((lx - 80) / 1250 * 199)] - 52), lab, "brush", 44)
    # 彩陶 painted pottery jar (Yangshao)
    cx, top, bot = 560, 390, 560
    body = [(cx + 95 * math.sin(math.pi * t) ** 0.7 * (1 if s else -1) * (1 - 0.35 * t), top + t * (bot - top))
            for s in (1, 0) for t in (np.linspace(0, 1, 40) if s else np.linspace(1, 0, 40))]
    with c.ink((170, 80, 45), 0.95) as p:
        p.poly(body)
        p.rect([cx - 38, top - 22, cx + 38, top + 6], radius=6)
    with c.ink(INK, 0.8) as p:  # swirl decoration
        for i in range(5):
            x = cx - 64 + i * 32
            p.arc([x - 16, 430, x + 16, 462], 180, 360, 4)
            p.arc([x, 446, x + 32, 478], 0, 180, 4)
        p.line([(cx - 88, 420), (cx + 88, 420)], 3)
        p.line([(cx - 86, 490), (cx + 86, 490)], 3)
    # 良渚 jade cong
    jx = 830
    with c.ink((95, 140, 110), 0.9) as p:
        p.rect([jx - 50, 410, jx + 50, 560], radius=6)
    with c.ink((150, 190, 160), 0.8) as p:
        p.ellipse([jx - 26, 398, jx + 26, 422])
        for y in (440, 490, 530):
            p.rect([jx - 50, y, jx + 50, y + 5])
    label(c, cx, 610, "仰韶彩陶")
    label(c, jx, 610, "良渚玉琮")


def scene_bronze(c):
    c.mountains(360, 110, INK, 0.12, seed=31, fade=200, base=3)
    # oracle bone (turtle plastron)
    ox, oy = 470, 440
    pts = []
    for i in range(80):
        a = 2 * math.pi * i / 80
        r = 1 + 0.05 * math.sin(7 * a) + (0.12 if abs(math.sin(a)) < 0.25 else 0)
        pts.append((ox + 150 * r * math.cos(a), oy + 190 * r * math.sin(a)))
    with c.ink((120, 95, 65), 0.5, blur=6) as p:
        p.poly([(x + 8, y + 10) for x, y in pts])
    with c.ink((226, 206, 168), 1.0) as p:
        p.poly(pts)
    with c.ink((150, 120, 85), 0.7) as p:
        p.line([(ox, oy - 185), (ox, oy + 185)], 3)
        for y in (-100, 0, 100):
            p.line([(ox - 145, oy + y), (ox + 145, oy + y + 10)], 2)
    with c.ink((110, 40, 25), 0.85) as p:   # burn marks and cracks (卜)
        for bx, by in ((ox - 75, oy - 55), (ox + 70, oy + 45), (ox - 60, oy + 120)):
            p.ellipse([bx - 9, by - 13, bx + 9, by + 13])
            p.line([(bx, by - 30), (bx, by + 30)], 2)
            p.line([(bx, by), (bx + 26, by - 14)], 2)
    with c.ink((70, 45, 30), 0.9) as p:
        p.vtext(ox + 70, oy - 140, "王贞", "brush", 40)
        p.vtext(ox - 10, oy - 130, "日雨", "brush", 40)
        p.vtext(ox - 90, oy + 10, "月人", "brush", 40)
    # bronze ding
    dx, dy, s = 930, 440, 150
    bronze, dark, light = (72, 104, 88), (38, 58, 48), (120, 150, 125)
    with c.ink((40, 40, 30), 0.35, blur=10) as p:
        p.ellipse([dx - s * 1.2, dy + s * 1.18, dx + s * 1.2, dy + s * 1.42])
    with c.ink(bronze, 1.0) as p:
        for lx in (-0.72, 0.72):
            p.poly([(dx + (lx - 0.14) * s, dy + 0.3 * s), (dx + (lx + 0.14) * s, dy + 0.3 * s),
                    (dx + (lx + 0.1) * s, dy + 1.3 * s), (dx + (lx - 0.1) * s, dy + 1.3 * s)])
        for ex in (-0.7, 0.52):  # ears
            p.rect([dx + ex * s, dy - 1.05 * s, dx + (ex + 0.18) * s, dy - 0.55 * s], radius=6)
        bowl = [(dx - s, dy - 0.55 * s)] + [(dx - s * math.cos(t), dy - 0.5 * s + 1.1 * s * math.sin(t) ** 0.8)
                                            for t in np.linspace(0, math.pi, 50)] + [(dx + s, dy - 0.55 * s)]
        p.poly(bowl)
        p.rect([dx - 1.08 * s, dy - 0.64 * s, dx + 1.08 * s, dy - 0.5 * s], radius=4)
    with c.ink((236, 226, 205), 1.0) as p:  # ear holes
        for ex in (-0.7, 0.52):
            p.rect([dx + (ex + 0.05) * s, dy - 0.95 * s, dx + (ex + 0.13) * s, dy - 0.7 * s], radius=3)
    with c.ink(dark, 0.9) as p:  # 雷纹 band
        p.rect([dx - 0.98 * s, dy - 0.42 * s, dx + 0.98 * s, dy - 0.38 * s])
        p.rect([dx - 0.96 * s, dy - 0.08 * s, dx + 0.96 * s, dy - 0.04 * s])
        n = 10
        for i in range(n):
            x = dx - 0.9 * s + i * 1.8 * s / n
            w = 1.8 * s / n * 0.7
            y0, y1 = dy - 0.34 * s, dy - 0.12 * s
            p.line([(x, y1), (x, y0), (x + w, y0), (x + w, y1 - 0.05 * s), (x + 0.25 * w, y1 - 0.05 * s),
                    (x + 0.25 * w, y0 + 0.06 * s), (x + 0.7 * w, y0 + 0.06 * s)], 3)
        # taotie eyes
        for ex in (-0.28, 0.28):
            p.ellipse([dx + (ex - 0.07) * s, dy + 0.12 * s, dx + (ex + 0.07) * s, dy + 0.26 * s])
    with c.ink(light, 0.35, blur=4) as p:
        p.poly([(dx - 0.8 * s, dy - 0.45 * s), (dx - 0.62 * s, dy - 0.45 * s), (dx - 0.5 * s, dy + 0.35 * s),
                (dx - 0.62 * s, dy + 0.38 * s)])
    label(c, ox, 638, "甲骨文")
    label(c, dx, 638, "青铜鼎")


def scene_bamboo(c):
    c.mountains(330, 120, INK, 0.12, seed=41, fade=200, base=3)
    quotes = ["学而时习之", "己所不欲", "勿施于人", "道可道非常道", "上善若水", "兼爱非攻", "天行健", "君子以自强不息",
              "知者不惑"]
    n = len(quotes)
    sw, gap, x0, y0, y1 = 62, 10, 380, 220, 640
    with c.ink((90, 70, 40), 0.35, blur=8) as p:
        p.rect([x0 + 10, y0 + 14, x0 + n * (sw + gap) + 10, y1 + 14])
    for i in range(n):
        x = x0 + i * (sw + gap)
        with c.ink((206, 176, 112), 1.0) as p:
            p.rect([x, y0, x + sw, y1], radius=6)
        with c.ink((160, 128, 72), 0.8) as p:
            p.rect([x + sw - 8, y0 + 4, x + sw - 3, y1 - 4], radius=2)
    with c.ink((110, 70, 40), 0.9) as p:  # binding strings
        for yy in (y0 + 60, y1 - 60):
            p.line([(x0 - 20, yy), (x0 + n * (sw + gap) + 10, yy + 3)], 4)
    with c.ink((30, 25, 20), 0.9) as p:  # right-to-left columns
        for i, q in enumerate(quotes):
            x = x0 + (n - 1 - i) * (sw + gap) + sw / 2 - 3
            size = 40 if len(q) <= 5 else 34 if len(q) <= 6 else 30
            total = len(q) * size * 1.08
            p.vtext(x, (y0 + y1) / 2 - total / 2, q, "brush", size, 1.08)
    with c.ink(RED, 0.8) as p:
        p.text((1130, 330), "仁", "brush", 150)
    with c.ink(INK, 0.85) as p:
        p.text((1130, 510), "道", "brush", 150)


def scene_wall(c):
    c.glow(1050, 230, 240, (240, 190, 150), 0.4)
    with c.ink((200, 60, 40), 0.85) as p:
        p.ellipse([1000, 180, 1100, 280])
    c.mountains(420, 150, INK, 0.22, seed=51, fade=220, base=3)
    ridge = c.mountains(560, 190, INK, 0.55, seed=53, fade=200, base=4)
    # the wall follows the near ridge
    xs = np.arange(40, 1370, 6)
    ys = ridge[xs] + 4
    wall = (120, 100, 80)
    with c.ink(wall, 0.95) as p:
        p.line(list(zip(xs, ys)), 12)
        for x, y in zip(xs[::3], ys[::3]):
            p.rect([x - 3, y - 14, x + 3, y - 4])
        for x in xs[::28]:
            y = ridge[x] + 4
            p.rect([x - 14, y - 36, x + 14, y + 4])
    with c.ink((70, 55, 45), 0.95) as p:
        for x in xs[::28]:
            y = ridge[x] + 4
            p.poly([(x - 20, y - 36), (x + 20, y - 36), (x + 12, y - 48), (x - 12, y - 48)])
    c.mountains(660, 70, (165, 125, 70), 0.9, seed=55, fade=140, base=2)   # desert dunes
    # camel caravan on the Silk Road
    for k, cx in enumerate((300, 380, 460, 540)):
        cy = 575 + 6 * math.sin(k)
        with c.ink((60, 45, 35), 0.92) as p:
            p.ellipse([cx - 32, cy - 26, cx + 30, cy + 2])
            p.ellipse([cx - 22, cy - 42, cx - 2, cy - 14])
            p.ellipse([cx + 2, cy - 40, cx + 20, cy - 14])
            p.line([(cx + 26, cy - 10), (cx + 40, cy - 34), (cx + 50, cy - 36)], 7)
            p.ellipse([cx + 42, cy - 42, cx + 60, cy - 30])
            for lx in (-24, -12, 14, 24):
                p.line([(cx + lx, cy - 4), (cx + lx + (3 if lx > 0 else -3), cy + 32)], 5)
    label(c, 420, 635, "丝绸之路")
    label(c, 1120, 330, "万里长城")


def scene_inventions(c):
    c.mountains(330, 100, INK, 0.1, seed=61, fade=200, base=3)
    centers = [(280, 430), (560, 430), (840, 430), (1120, 430)]
    r = 118
    for cx, cy in centers:
        with c.ink((120, 100, 70), 0.35, blur=8) as p:
            p.ellipse([cx - r + 6, cy - r + 10, cx + r + 6, cy + r + 10])
        with c.ink((246, 238, 220), 1.0) as p:
            p.ellipse([cx - r, cy - r, cx + r, cy + r])
        with c.ink(INK, 0.85) as p:
            p.arc([cx - r, cy - r, cx + r, cy + r], 0, 360, 4)
    # 造纸: a stack of sheets
    cx, cy = centers[0]
    for i in range(4):
        with c.ink((225, 215, 190) if i < 3 else (250, 246, 236), 1.0) as p:
            p.poly([(cx - 60 + i * 5, cy - 20 - i * 12), (cx + 50 + i * 5, cy - 35 - i * 12),
                    (cx + 66 + i * 5, cy + 30 - i * 12), (cx - 44 + i * 5, cy + 45 - i * 12)])
        with c.ink((120, 100, 70), 0.8) as p:
            p.line([(cx - 60 + i * 5, cy - 20 - i * 12), (cx + 50 + i * 5, cy - 35 - i * 12),
                    (cx + 66 + i * 5, cy + 30 - i * 12), (cx - 44 + i * 5, cy + 45 - i * 12),
                    (cx - 60 + i * 5, cy - 20 - i * 12)], 2)
    with c.ink(INK, 0.7) as p:
        p.vtext(cx + 12, cy - 60, "书", "brush", 36)
    # 印刷: movable type grid
    cx, cy = centers[1]
    chars = "文明传承千秋书香墨韵"
    with c.ink((150, 105, 60), 1.0) as p:
        for i in range(3):
            for j in range(3):
                x, y = cx - 69 + j * 46, cy - 69 + i * 46
                p.rect([x, y, x + 42, y + 42], radius=4)
    with c.ink((60, 35, 20), 0.95) as p:
        for i in range(3):
            for j in range(3):
                x, y = cx - 48 + j * 46, cy - 48 + i * 46
                p.text((x, y), chars[i * 3 + j], "brush", 30)
    # 火药: firework burst
    cx, cy = centers[2]
    for col, rr, n, w in (((210, 50, 40), 88, 24, 4), ((230, 170, 50), 60, 18, 3)):
        with c.ink(col, 0.95) as p:
            for k in range(n):
                a = 2 * math.pi * k / n
                p.line([(cx + 16 * math.cos(a), cy + 16 * math.sin(a)),
                        (cx + rr * math.cos(a), cy + rr * math.sin(a))], w)
                p.ellipse([cx + (rr + 8) * math.cos(a) - 4, cy + (rr + 8) * math.sin(a) - 4,
                           cx + (rr + 8) * math.cos(a) + 4, cy + (rr + 8) * math.sin(a) + 4])
    # 指南针: 司南 spoon on a bronze plate
    cx, cy = centers[3]
    with c.ink((150, 120, 70), 1.0) as p:
        p.rect([cx - 80, cy - 80, cx + 80, cy + 80], radius=6)
    with c.ink((220, 200, 150), 1.0) as p:
        p.ellipse([cx - 56, cy - 56, cx + 56, cy + 56])
    with c.ink((40, 40, 40), 1.0) as p:
        p.ellipse([cx - 30, cy - 16, cx + 18, cy + 22])
        p.poly([(cx + 10, cy - 4), (cx + 70, cy - 30), (cx + 72, cy - 24), (cx + 16, cy + 10)])
    with c.ink((120, 90, 50), 0.9) as p:
        for k in range(8):
            a = 2 * math.pi * k / 8
            p.line([(cx + 60 * math.cos(a), cy + 60 * math.sin(a)), (cx + 74 * math.cos(a), cy + 74 * math.sin(a))], 3)
    with c.ink(INK, 0.9) as p:
        for (cx, cy), lab in zip(centers, ("造纸术", "印刷术", "火 药", "指南针")):
            p.text((cx, cy + r + 42), lab, "brush", 44)


def scene_poetry(c):
    c.glow(900, 280, 300, (250, 245, 225), 0.6)
    with c.ink((250, 246, 230), 0.95) as p:
        p.ellipse([810, 190, 990, 370])
    with c.ink((215, 205, 180), 0.35, blur=3) as p:
        p.ellipse([850, 230, 900, 270])
        p.ellipse([900, 300, 940, 330])
    c.mountains(600, 120, INK, 0.3, seed=71, fade=200, base=3)
    # plum branch from the left edge
    rng = np.random.default_rng(72)
    blossoms = []

    def branch(p, x, y, ang, length, width, depth):
        pts = [(x, y)]
        for _ in range(4):
            ang += rng.normal(0, 0.25)
            x += math.cos(ang) * length / 4
            y += math.sin(ang) * length / 4
            pts.append((x, y))
        p.line(pts, width)
        if depth > 0:
            branch(p, x, y, ang + rng.uniform(0.3, 0.7), length * 0.62, width * 0.62, depth - 1)
            branch(p, x, y, ang - rng.uniform(0.2, 0.5), length * 0.7, width * 0.65, depth - 1)
        for px, py in pts[1:]:
            if depth < 3 and rng.random() < 0.8:
                blossoms.append((px + rng.normal(0, 6), py + rng.normal(0, 6)))

    with c.ink((40, 32, 28), 0.95) as p:
        branch(p, 20, 330, -0.1, 330, 20, 4)
    for bx, by in blossoms:
        rr = rng.uniform(7, 11)
        with c.ink((200, 50, 60), 0.85) as p:
            for k in range(5):
                a = 2 * math.pi * k / 5
                p.ellipse([bx + rr * 0.7 * math.cos(a) - rr * 0.6, by + rr * 0.7 * math.sin(a) - rr * 0.6,
                           bx + rr * 0.7 * math.cos(a) + rr * 0.6, by + rr * 0.7 * math.sin(a) + rr * 0.6])
    with c.ink((240, 200, 90), 0.9) as p:
        for bx, by in blossoms:
            p.ellipse([bx - 2, by - 2, bx + 2, by + 2])
    with c.ink(INK, 0.9) as p:  # 静夜思 in vertical columns, right to left
        lines = ["床前明月光", "疑是地上霜", "举头望明月", "低头思故乡"]
        for i, ln in enumerate(lines):
            p.vtext(1180 - i * 62, 220, ln, "brush", 50, 1.06)
    with c.ink((70, 60, 55), 0.85) as p:
        p.vtext(1180 - 4 * 62 - 6, 400, "李白", "serif", 22, 1.2)


def scene_ming(c):
    c.mountains(380, 90, INK, 0.12, seed=81, fade=160, base=3)
    # stylised sea
    with c.ink((70, 100, 120), 0.7) as p:
        for row in range(7):
            y = 520 + row * 34
            off = (row % 2) * 30
            for x in range(-60 + off, CW + 60, 60):
                p.arc([x, y, x + 60, y + 40], 180, 360, 3)
    # treasure ship
    sx, sy = 430, 520
    with c.ink((90, 55, 35), 1.0) as p:
        hull = [(sx - 250, sy - 60), (sx + 230, sy - 70), (sx + 190, sy + 10), (sx - 190, sy + 12)]
        p.poly(hull)
        p.rect([sx - 250, sy - 90, sx - 170, sy - 55])
        p.rect([sx + 160, sy - 95, sx + 235, sy - 62])
    with c.ink((160, 60, 40), 0.9) as p:
        p.rect([sx - 240, sy - 52, sx + 215, sy - 40])
    for mx, hh, ww in ((-150, 210, 105), (-10, 265, 135), (130, 225, 110)):
        with c.ink((60, 40, 25), 1.0) as p:
            p.line([(sx + mx, sy - 60), (sx + mx, sy - 60 - hh)], 6)
        with c.ink((200, 150, 90), 0.95) as p:
            p.poly([(sx + mx - ww / 2, sy - 80 - hh * 0.9), (sx + mx + ww / 2, sy - 90 - hh * 0.9),
                    (sx + mx + ww / 2 + 10, sy - 90), (sx + mx - ww / 2 + 5, sy - 80)])
        with c.ink((110, 80, 45), 0.8) as p:
            for k in range(1, 7):
                y = sy - 80 - hh * 0.9 * k / 7
                p.line([(sx + mx - ww / 2 + 2, y), (sx + mx + ww / 2 + 6, y - 8)], 2)
        with c.ink(RED, 0.95) as p:
            p.poly([(sx + mx, sy - 60 - hh), (sx + mx + 36, sy - 52 - hh), (sx + mx, sy - 44 - hh)])
    # Forbidden City hall
    px, py = 1080, 470
    with c.ink((236, 232, 222), 1.0) as p:  # marble terraces
        p.rect([px - 230, py + 40, px + 230, py + 70])
        p.rect([px - 200, py + 15, px + 200, py + 42])
    with c.ink((150, 140, 125), 0.8) as p:
        p.line([(px - 230, py + 40), (px + 230, py + 40)], 2)
        p.line([(px - 200, py + 15), (px + 200, py + 15)], 2)
    with c.ink((165, 35, 30), 1.0) as p:  # red columns / wall
        p.rect([px - 170, py - 70, px + 170, py + 15])
    with c.ink((120, 25, 20), 1.0) as p:
        for k in range(9):
            x = px - 150 + k * 37.5
            p.rect([x - 3, py - 70, x + 3, py + 15])
    with c.ink((205, 150, 40), 1.0) as p:  # double-eave yellow roof
        for (w1, w2, y0, y1) in ((250, 170, py - 70, py - 110), (200, 110, py - 130, py - 190)):
            p.poly([(px - w1, y0 - 18), (px - w1 + 30, y0), (px + w1 - 30, y0), (px + w1, y0 - 18),
                    (px + w2, y1), (px - w2, y1)])
        p.rect([px - 170, py - 132, px + 170, py - 108])
    with c.ink((150, 100, 20), 0.9) as p:
        p.line([(px - 110, py - 190), (px + 110, py - 190)], 5)
        for (w1, y0) in ((250, py - 70), (200, py - 130)):
            p.line([(px - w1, y0 - 18), (px - w1 + 30, y0), (px + w1 - 30, y0), (px + w1, y0 - 18)], 3)
    label(c, sx, 575, "郑和宝船")
    label(c, px, py + 105, "紫禁城")


def scene_future(c):
    c.gradient_sky((20, 30, 60), (220, 170, 130), 0, 620)
    rng = np.random.default_rng(91)
    with c.ink((255, 250, 235), 0.9) as p:
        for _ in range(140):
            x, y, r = rng.uniform(0, CW), rng.uniform(0, 330), rng.uniform(0.6, 1.8)
            p.ellipse([x - r, y - r, x + r, y + r])
    # rocket trail
    t = np.linspace(0, 1, 120)
    trail = list(zip(260 + 600 * t, 650 - 520 * t ** 1.6))
    with c.ink((255, 220, 170), 0.35, blur=6) as p:
        p.line(trail, 16)
    with c.ink((255, 245, 225), 0.9) as p:
        p.line(trail, 3)
    ex, ey = trail[-1]
    c.glow(ex, ey, 40, (255, 240, 210), 0.9)
    c.mountains(560, 180, (60, 55, 80), 0.55, seed=92, fade=260, base=3)
    # skyline
    xs = 0
    rng = np.random.default_rng(93)
    blocks = []
    while xs < CW:
        w = rng.uniform(30, 80)
        h = rng.uniform(60, 260) * (1.4 if 600 < xs < 800 else 1)
        blocks.append((xs, w, h))
        xs += w + rng.uniform(0, 8)
    with c.ink((25, 25, 40), 1.0) as p:
        for x, w, h in blocks:
            p.rect([x, 700 - h, x + w, CH])
        p.poly([(690, 700 - 390), (700, 700 - 470), (710, 700 - 390)])  # spire
        p.rect([680, 700 - 390, 720, CH])
    with c.ink((255, 210, 120), 0.85) as p:
        for x, w, h in blocks:
            for yy in np.arange(700 - h + 10, 700, 16):
                for xx in np.arange(x + 6, x + w - 6, 12):
                    if rng.random() < 0.3:
                        p.rect([xx, yy, xx + 5, yy + 7])
    with c.ink((240, 225, 200), 0.3) as p:  # a faint echo of the past: oracle glyphs in the sky
        for i, ch in enumerate("日月山川"):
            p.text((1000 + i * 70, 150 + 18 * math.sin(i)), ch, "brush", 56)


def scene_ending(c):
    c.glow(700, 300, 330, (240, 200, 170), 0.3)
    with c.ink(RED, 0.85) as p:
        p.ellipse([640, 150, 760, 270])
    c.mountains(470, 200, INK, 0.25, seed=101, fade=260, base=3)
    c.mountains(580, 180, INK, 0.5, seed=102, fade=200)
    c.mountains(700, 150, INK, 0.75, seed=103, fade=160, base=6)
    with c.ink(INK, 0.92) as p:
        p.text((CW / 2, 380), "生生不息", "brush", 150)


SCENES = {n[len("scene_"):]: f for n, f in globals().items() if n.startswith("scene_")}


def build_overlay(title, date, is_card, dark=False):
    """Static overlay in output space: era title, date and seal."""
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    if title:
        d.text((64, 40), title, font=font("brush", 84), fill=(245, 235, 215, 245) if dark else INK + (240,))
        tb = d.textbbox((64, 40), title, font=font("brush", 84))
        d.line([(68, tb[3] + 16), (68 + 260, tb[3] + 16)], fill=RED + (200,), width=3)
        d.text((68, tb[3] + 28), date, font=font("serif", 24), fill=(225, 215, 195, 235) if dark else (70, 60, 55, 235))
        s = seal("华夏", 62, rot=-5, seed=len(title))
        ov.alpha_composite(s, (tb[2] + 20, 50))
    if is_card:
        s = seal("中华文明", 96, rot=-3)
        ov.alpha_composite(s, (W - 170, 60))
    return ov


def subtitle_image(text):
    f = font("serif", 36)
    probe = ImageDraw.Draw(Image.new("L", (1, 1)))
    bb = probe.textbbox((0, 0), text, font=f, stroke_width=3)
    w, h = bb[2] - bb[0] + 60, bb[3] - bb[1] + 30
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, w - 1, h - 1], radius=12, fill=(15, 12, 10, 120))
    d.text((w / 2, h / 2), text, font=f, fill=(252, 246, 232, 255), anchor="mm",
           stroke_width=2, stroke_fill=(10, 8, 6, 255))
    return img


# ---------------------------------------------------------------------------
# Timeline
# ---------------------------------------------------------------------------
def timeline():
    t, out = 0.0, []
    for title, date, dur, lines, fn in SCRIPT:
        subs = []
        s0, s1 = 0.9, dur - 1.2
        share = (s1 - s0) / len(lines)
        for i, ln in enumerate(lines):
            subs.append((s0 + i * share, s0 + (i + 1) * share - 0.25, ln))
        out.append(dict(start=t, dur=dur, title=title, date=date, lines=lines, fn=fn, subs=subs))
        t += dur - XFADE
    return out, t + XFADE


def fmt_srt(t):
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def write_srt(scenes, path):
    idx, rows = 1, []
    for sc in scenes:
        for a, b, text in sc["subs"]:
            rows.append(f"{idx}\n{fmt_srt(sc['start'] + a)} --> {fmt_srt(sc['start'] + b)}\n{text}\n")
            idx += 1
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(rows))


# ---------------------------------------------------------------------------
# Music: pentatonic guzheng-style plucks, bass, drone, drum hits, reverb
# ---------------------------------------------------------------------------
SR = 44100


def midi_hz(m):
    return 440.0 * 2 ** ((m - 69) / 12)


def pluck(freq, amp, tail=3.0, vib=True):
    n = int(SR * tail)
    t = np.arange(n) / SR
    vibrato = 1 + (0.005 * np.sin(2 * np.pi * 5.2 * t) * np.clip((t - 0.35) / 0.4, 0, 1) if vib else 0)
    phase = 2 * np.pi * np.cumsum(freq * vibrato) / SR
    sig = np.zeros(n)
    for k in range(1, 9):
        sig += (1 / k ** 1.3) * np.sin(k * phase * (1 + 0.0003 * k * k)) * np.exp(-t * (1.2 + 1.1 * k))
    sig *= 1 - np.exp(-t / 0.003)
    noise = np.random.default_rng(int(freq)).normal(0, 1, n) * np.exp(-t / 0.008) * 0.15
    return (sig + noise) * amp


def drum(amp=0.6):
    n = int(SR * 1.5)
    t = np.arange(n) / SR
    f = 55 + 60 * np.exp(-t * 18)
    body = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 3.5)
    hit = np.random.default_rng(5).normal(0, 1, n) * np.exp(-t * 60) * 0.3
    return (body + hit) * amp


def compose_music(total, scene_starts):
    n = int(SR * (total + 4))
    mix = np.zeros(n)

    def add(sig, at):
        i = int(at * SR)
        if i >= n:
            return
        j = min(n, i + len(sig))
        mix[i:j] += sig[: j - i]

    rng = np.random.default_rng(2024)
    scale = [57, 59, 62, 64, 66, 69, 71, 74, 76, 78, 81, 83, 86]   # D-major pentatonic, A3..D6
    beat = 60 / 66
    t, idx, phrase = 1.0, 5, 0
    while t < total - 4:
        if phrase % 2 == 1:   # guzheng glissando into the phrase
            for k, m in enumerate(scale[2:10]):
                add(pluck(midi_hz(m), 0.10, 1.5, vib=False), t - 0.5 + k * 0.055)
        bars = 0
        while bars < 4 * 4 and t < total - 4:
            dur = rng.choice([1, 1, 0.5, 0.5, 1.5, 2]) * beat
            idx = int(np.clip(idx + rng.choice([-2, -1, -1, 0, 1, 1, 2]), 2, len(scale) - 2))
            add(pluck(midi_hz(scale[idx]), 0.22), t)
            if dur >= 1.5 * beat and rng.random() < 0.5:  # ornament
                add(pluck(midi_hz(scale[idx + 1]), 0.09, 1.2), t + 0.12)
            t += dur
            bars += dur / beat
        idx = rng.choice([2, 5, 7])     # resolve on D or A
        add(pluck(midi_hz(scale[idx]), 0.24), t)
        t += 2 * beat
        phrase += 1
    bass = [38, 43, 45, 38]
    b, k = 0.5, 0
    while b < total - 3:
        add(pluck(midi_hz(bass[(k // 2) % 4]), 0.20, 4.0, vib=False), b)
        add(pluck(midi_hz(bass[(k // 2) % 4] + 7), 0.08, 3.0, vib=False), b + 2 * beat)
        b += 4 * beat
        k += 1
    tt = np.arange(n) / SR
    drone = (np.sin(2 * np.pi * midi_hz(50) * tt) + 0.6 * np.sin(2 * np.pi * midi_hz(57) * tt))
    mix += drone * 0.035 * (0.7 + 0.3 * np.sin(2 * np.pi * tt / 11))
    for s in scene_starts:
        add(drum(0.35), max(0, s - 0.1))
    # reverb: convolve with a decaying noise tail
    ir_t = np.arange(int(SR * 2.8)) / SR
    ir = np.random.default_rng(9).normal(0, 1, len(ir_t)) * np.exp(-ir_t / 0.7)
    ir[0] = 0
    ir /= np.sqrt(np.sum(ir ** 2))
    size = 1 << int(np.ceil(np.log2(n + len(ir))))
    wet = np.fft.irfft(np.fft.rfft(mix, size) * np.fft.rfft(ir, size), size)[:n]
    out = mix * 0.75 + wet * 0.35
    out = out[: int(SR * total)]
    fade_in, fade_out = int(SR * 1.5), int(SR * 4)
    out[:fade_in] *= np.linspace(0, 1, fade_in)
    out[-fade_out:] *= np.linspace(1, 0, fade_out)
    out = np.tanh(out / np.max(np.abs(out)) * 1.2) * 0.85
    stereo = np.stack([out, np.roll(out, 300) * 0.96], axis=1)
    return (stereo * 32767).astype(np.int16)


def write_wav(path, data):
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(data.tobytes())


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
def ease(x):
    x = min(1.0, max(0.0, x))
    return x * x * (3 - 2 * x)


def petals(img, tl, seed):
    rng = np.random.default_rng(seed)
    d = ImageDraw.Draw(img)
    for _ in range(14):
        x0, y0, sp, ph = rng.uniform(0, W), rng.uniform(-200, H), rng.uniform(30, 60), rng.uniform(0, 6)
        y = (y0 + sp * tl) % (H + 60) - 30
        x = x0 + 40 * math.sin(tl * 0.8 + ph) + 12 * tl
        x %= W
        r = 5 + 2 * math.sin(tl * 3 + ph)
        d.ellipse([x - r, y - 3, x + r, y + 3], fill=(205, 70, 80))


def render():
    ensure_fonts()
    os.makedirs(OUT_DIR, exist_ok=True)
    scenes, total = timeline()
    print(f"{len(scenes)} scenes, {total:.1f}s")

    grain, vignette = paper_texture(CW, CH)
    for i, sc in enumerate(scenes):
        c = Canvas()
        SCENES[sc["fn"]](c)
        sc["img"] = c.finish(grain, vignette, 0.05 if sc["fn"] == "future" else 0.08)
        sc["overlay"] = build_overlay(sc["title"], sc["date"], sc["fn"] in ("title", "ending"), sc["fn"] == "future")
        sc["ov_alpha"] = sc["overlay"].getchannel("A")
        sc["sub_imgs"] = [subtitle_image(s[2]) for s in sc["subs"]]
        sc["pan"] = ((-1) ** i * 24, (-1) ** (i // 2) * 10)
        print(f"  drew scene {i}: {sc['fn']}")

    def scene_frame(sc, tl):
        p = tl / sc["dur"]
        z = 1.02 + 0.07 * ease(p)
        cw, ch = CW / z, CH / z
        cx = np.clip(CW / 2 + sc["pan"][0] * (p - 0.5), cw / 2, CW - cw / 2)
        cy = np.clip(CH / 2 + sc["pan"][1] * (p - 0.5), ch / 2, CH - ch / 2)
        box = (cx - cw / 2, cy - ch / 2, cx + cw / 2, cy + ch / 2)
        frame = sc["img"].resize((W, H), Image.BILINEAR, box=box)
        if sc["fn"] == "poetry":
            petals(frame, tl, 7)
        a = ease((tl - 0.4) / 1.6)
        if a > 0:
            mask = sc["ov_alpha"] if a >= 1 else sc["ov_alpha"].point(lambda v: int(v * a))
            frame.paste(sc["overlay"], (0, 0), mask)
        for (s0, s1, _), img in zip(sc["subs"], sc["sub_imgs"]):
            if s0 <= tl <= s1:
                f = min(1.0, (tl - s0) / 0.3, (s1 - tl) / 0.3)
                alpha = img.getchannel("A")
                if f < 1:
                    alpha = alpha.point(lambda v: int(v * f))
                frame.paste(img, ((W - img.width) // 2, H - 58 - img.height), alpha)
        return frame

    if "--stills" in sys.argv:   # quick preview: one still per scene, mid-way through
        for i, sc in enumerate(scenes):
            scene_frame(sc, sc["subs"][0][0] + 1).save(os.path.join(OUT_DIR, f"still_{i:02d}.png"))
        return

    srt = os.path.join(OUT_DIR, "chinese_civilization.srt")
    wav = os.path.join(OUT_DIR, "_music.wav")
    mp4 = os.path.join(OUT_DIR, "chinese_civilization.mp4")
    write_srt(scenes, srt)
    write_wav(wav, compose_music(total, [s["start"] for s in scenes]))
    print("music done")

    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    cmd = [ffmpeg, "-y", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
           "-i", wav, "-i", srt,
           "-map", "0:v", "-map", "1:a", "-map", "2:s",
           "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "160k", "-c:s", "mov_text",
           "-metadata:s:s:0", "language=chi", "-metadata:s:s:0", "title=中文字幕",
           "-metadata", "title=中华文明 · 五千年的回响",
           "-movflags", "+faststart", mp4]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    nframes = int(total * FPS)
    for fi in range(nframes):
        t = fi / FPS
        active = [sc for sc in scenes if sc["start"] <= t < sc["start"] + sc["dur"]]
        frame = scene_frame(active[0], t - active[0]["start"])
        if len(active) > 1:
            nxt = active[1]
            frame = Image.blend(frame, scene_frame(nxt, t - nxt["start"]), ease((t - nxt["start"]) / XFADE))
        if t < 1.0:                                   # fade in from black
            frame = Image.blend(Image.new("RGB", (W, H)), frame, ease(t))
        if t > total - 1.5:                           # fade out
            frame = Image.blend(Image.new("RGB", (W, H)), frame, ease((total - t) / 1.5))
        proc.stdin.write(frame.tobytes())
        if fi % (FPS * 10) == 0:
            print(f"  frame {fi}/{nframes}")
    proc.stdin.close()
    if proc.wait() != 0:
        raise SystemExit("ffmpeg failed")
    os.remove(wav)
    print("wrote", mp4, "and", srt)


if __name__ == "__main__":
    render()
