"""
studio.py — taklifnoma dizayni, musiqasi va videosini yasaydigan modul.

Hamma narsa kod bilan chiziladi (tashqi rasm/musiqa kerak emas):
  • fon + naqshlar (mandala, suzani, miḥrob/arka, yulduz, o'simlik) — PIL bilan
  • matn qatlamlari (ism, sana, manzil...) — ketma-ket paydo bo'ladi
  • musiqa — numpy bilan sintez qilinadi (yoki tayyor mp3 berilsa, o'sha ishlatiladi)
  • video — ffmpeg bilan yig'iladi (9:16)
Bu modul sinxron ishlaydi; botda `asyncio.to_thread` bilan chaqiriladi.
"""
import base64
import colorsys
import io
import math
import os
import random
import re
import shutil
import subprocess
import tempfile
import zlib

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from fontdata import FONTS_B64Z

# ----------------------------------------------------------------------------------------------
# Umumiy o'lchamlar
# ----------------------------------------------------------------------------------------------
W, H = 720, 1280              # video o'lchami (9:16)
PADX, PADY = 20, 36           # fon biroz katta chiziladi — sekin siljish (drift) uchun
BW, BH = W + 2 * PADX, H + 2 * PADY
SS = 2                        # naqshlar 2x o'lchamda chizilib, kichraytiriladi (silliq chiziqlar)
DURATION = 11.0               # video davomiyligi (soniya)
FPS = 24

# ----------------------------------------------------------------------------------------------
# Shriftlar (fontdata.py ichidan, vaqtinchalik papkaga yoziladi)
# ----------------------------------------------------------------------------------------------
_FONT_DIR = os.path.join(tempfile.gettempdir(), "taklif_fonts")
_font_cache = {}


def _font_file(key):
    os.makedirs(_FONT_DIR, exist_ok=True)
    path = os.path.join(_FONT_DIR, key + ".font")
    if not os.path.exists(path) or os.path.getsize(path) < 1000:
        raw = zlib.decompress(base64.b64decode("".join(FONTS_B64Z[key])))
        with open(path, "wb") as fh:
            fh.write(raw)
    return path


def font(key, size):
    k = (key, int(size))
    if k not in _font_cache:
        _font_cache[k] = ImageFont.truetype(_font_file(key), int(size))
    return _font_cache[k]


# ----------------------------------------------------------------------------------------------
# Ranglar palitralari
# ----------------------------------------------------------------------------------------------
def _rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _hex(c):
    return "#%02x%02x%02x" % tuple(int(max(0, min(255, v))) for v in c)


def _lum(c):
    r, g, b = [v / 255 for v in c]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


# nomi: (fon yuqori, fon past, naqsh/aksent, asosiy matn, ikkinchi matn)
PALETTES = {
    "bordo":    ("#6b1d34", "#26080f", "#d8b66f", "#fbf3e6", "#e6cfa4"),
    "zumrad":   ("#0f5c44", "#052117", "#dcbb73", "#f7f1e0", "#e2cd9a"),
    "qora":     ("#23232b", "#050507", "#d4af37", "#f8f3e4", "#d9c79a"),
    "binafsha": ("#51306f", "#190c2b", "#e2c98a", "#faf3ff", "#e5d3a8"),
    "kobalt":   ("#16407a", "#071a3a", "#e6c985", "#f6f3ea", "#e3d3a2"),
    "firuza":   ("#0f6e6e", "#042b32", "#ebd7a6", "#f5f8f0", "#e3d6ae"),
    "krem":     ("#fcf6ea", "#ecdfc6", "#b48a4b", "#3b2a1c", "#7a5a36"),
    "pushti":   ("#fff3f4", "#f6d4da", "#c98591", "#5b2a37", "#8c4f5f"),
    "osmon":    ("#f6f8fc", "#d6e1ef", "#6f8fb6", "#22344f", "#4f6a8d"),
    "shalfey":  ("#f3f6ee", "#d8e2cc", "#7e9a63", "#2f3f27", "#5d7447"),
}
PALETTE_ALIASES = {
    "bordo": "bordo", "burgundy": "bordo", "qizil": "bordo", "red": "bordo", "wine": "bordo",
    "zumrad": "zumrad", "yashil": "zumrad", "green": "zumrad", "emerald": "zumrad",
    "qora": "qora", "black": "qora", "dark": "qora",
    "binafsha": "binafsha", "purple": "binafsha", "violet": "binafsha",
    "kobalt": "kobalt", "ko'k": "kobalt", "blue": "kobalt", "navy": "kobalt",
    "firuza": "firuza", "turquoise": "firuza", "teal": "firuza",
    "krem": "krem", "cream": "krem", "oltin": "krem", "gold": "krem", "beige": "krem",
    "pushti": "pushti", "pink": "pushti", "rose": "pushti",
    "osmon": "osmon", "sky": "osmon", "light blue": "osmon",
    "shalfey": "shalfey", "olive": "shalfey", "sage": "shalfey",
}
STYLES = ("mandala", "suzani", "arch", "star", "vine")


def resolve_palette(spec, rng):
    """spec: palitra nomi (str), {'bg1','bg2','accent','text'} (hex) yoki None (tasodifiy)."""
    if isinstance(spec, dict):
        try:
            bg1, bg2, acc = _rgb(spec["bg1"]), _rgb(spec.get("bg2") or spec["bg1"]), _rgb(spec["accent"])
            txt = _rgb(spec["text"]) if spec.get("text") else None
            light = _lum(bg1) > 0.6
            if txt is None or abs(_lum(txt) - _lum(bg1)) < 0.45:      # matn bilan fon kontrasti yetmasa
                txt = (35, 30, 28) if light else (250, 245, 235)
            sub = tuple(int(0.55 * a + 0.45 * t) for a, t in zip(acc, txt))
            if abs(_lum(acc) - _lum(bg1)) < 0.18:                       # aksent fonga qo'shilib ketmasin
                acc = (110, 80, 40) if light else (225, 195, 120)
            return {"bg1": bg1, "bg2": bg2, "acc": acc, "txt": txt, "sub": sub, "light": light}
        except Exception:
            spec = None
    if isinstance(spec, str):
        key = PALETTE_ALIASES.get(spec.strip().lower(), spec.strip().lower())
        if key not in PALETTES:
            key = None
        spec = key
    if not spec:
        spec = rng.choice(list(PALETTES))
    bg1, bg2, acc, txt, sub = [_rgb(x) for x in PALETTES[spec]]
    return {"bg1": bg1, "bg2": bg2, "acc": acc, "txt": txt, "sub": sub, "light": _lum(bg1) > 0.6, "name": spec}


# ----------------------------------------------------------------------------------------------
# Chizma yordamchilari (hammasi SS barobar kattalashtirilgan kanvasda)
# ----------------------------------------------------------------------------------------------
def _s(v):
    return int(round(v * SS))


def _rot(pts, ang, cx, cy):
    ca, sa = math.cos(ang), math.sin(ang)
    return [(cx + x * ca - y * sa, cy + x * sa + y * ca) for x, y in pts]


def petal_pts(cx, cy, ang, length, width, r0=0.0, steps=22):
    """Mandala bargi (tig' shaklida), markazdan `r0` masofadan boshlanadi."""
    top, bot = [], []
    for i in range(steps + 1):
        t = i / steps
        x = r0 + (length - r0) * t
        y = (width / 2) * (math.sin(math.pi * t) ** 0.85)
        top.append((x, y))
        bot.append((x, -y))
    return _rot(top + bot[::-1], ang, cx, cy)


def rosette(d, cx, cy, r, n, col, lw, rings=3, rot=0.0, dots=True):
    """Gul-mandala: ichma-ich barglar, aylanalar, nuqtalar."""
    for k in range(rings):
        rr = r * (1 - 0.27 * k)
        w = rr * (0.62 if k == 0 else 0.55)
        for j in range(n):
            ang = rot + 2 * math.pi * j / n + (k % 2) * math.pi / n
            pts = petal_pts(cx, cy, ang, rr, w, r0=rr * 0.08)
            d.line(pts + [pts[0]], fill=col, width=lw, joint="curve")
    for fr in (0.16, 1.18):
        rr = r * fr
        d.ellipse((cx - rr, cy - rr, cx + rr, cy + rr), outline=col, width=lw)
    d.ellipse((cx - r * 0.07, cy - r * 0.07, cx + r * 0.07, cy + r * 0.07), fill=col)
    if dots:
        for j in range(n):
            ang = rot + 2 * math.pi * (j + 0.5) / n
            px, py = cx + math.cos(ang) * r * 1.32, cy + math.sin(ang) * r * 1.32
            rd = r * 0.035
            d.ellipse((px - rd, py - rd, px + rd, py + rd), fill=col)


def leaf(d, x, y, ang, length, width, col, lw, fill=False):
    pts = petal_pts(x, y, ang, length, width, steps=14)
    if fill:
        d.polygon(pts, fill=col)
    else:
        d.line(pts + [pts[0]], fill=col, width=lw, joint="curve")


def diamond(d, cx, cy, r, col, fill=True, lw=2):
    pts = [(cx, cy - r), (cx + r, cy), (cx, cy + r), (cx - r, cy)]
    if fill:
        d.polygon(pts, fill=col)
    else:
        d.line(pts + [pts[0]], fill=col, width=lw)


def star8(d, cx, cy, r, col, lw):
    """8 qirrali yulduz (ikki kvadrat)."""
    for off in (0, math.pi / 4):
        pts = [(cx + r * math.cos(off + i * math.pi / 2), cy + r * math.sin(off + i * math.pi / 2)) for i in range(4)]
        d.line(pts + [pts[0]], fill=col, width=lw, joint="curve")


def rounded_frame(d, x0, y0, x1, y1, rad, col, lw):
    d.rounded_rectangle((x0, y0, x1, y1), radius=rad, outline=col, width=lw)


def scallops(d, y, x0, x1, r, col, lw, up=True):
    """Yarim aylanalardan iborat bezak chizig'i (suzani chetlari)."""
    x = x0 + r
    while x <= x1 - r + 1:
        box = (x - r, y - r, x + r, y + r)
        d.arc(box, 180, 360, fill=col, width=lw) if up else d.arc(box, 0, 180, fill=col, width=lw)
        x += 2 * r


def vine(d, x0, y0, x1, y1, amp, waves, col, lw, leaf_len, rng, side=1):
    """Sinus shaklidagi o'simlik shoxi, ikki tomonga barglar bilan."""
    steps = 140
    pts = []
    for i in range(steps + 1):
        t = i / steps
        x = x0 + (x1 - x0) * t + amp * math.sin(2 * math.pi * waves * t) * side
        y = y0 + (y1 - y0) * t
        pts.append((x, y))
    d.line(pts, fill=col, width=lw, joint="curve")
    for i in range(6, steps - 3, 9):
        (xa, ya), (xb, yb) = pts[i], pts[i + 2]
        base = math.atan2(yb - ya, xb - xa)
        for sgn in (-1, 1):
            leaf(d, xa, ya, base + sgn * 0.95, leaf_len * (0.8 + 0.4 * rng.random()), leaf_len * 0.36, col, max(1, lw - 1))


# ----------------------------------------------------------------------------------------------
# Fon yaratish
# ----------------------------------------------------------------------------------------------
def gradient_bg(pal):
    """Yuqoridan pastga + biroz markaziy yorug'lik (vinyetka) bilan gradient."""
    ys = np.linspace(0, 1, BH, dtype=np.float32)[:, None, None]
    xs = np.linspace(-1, 1, BW, dtype=np.float32)[None, :, None]
    c1 = np.array(pal["bg1"], dtype=np.float32)[None, None, :]
    c2 = np.array(pal["bg2"], dtype=np.float32)[None, None, :]
    img = c1 * (1 - ys) + c2 * ys
    glow = np.clip(1.0 - (xs ** 2 * 0.9 + (ys - 0.22) ** 2 * 1.6), 0, 1)
    lift = 22 if not pal["light"] else 10
    img = img + glow * lift
    # engil qog'oz tekisligi (noise)
    rng = np.random.default_rng(7)
    noise = rng.normal(0, 1.6, (BH, BW, 1)).astype(np.float32)
    img = np.clip(img + noise, 0, 255).astype(np.uint8)
    return Image.fromarray(img, "RGB")


def build_background(pal, style, rng):
    base = gradient_bg(pal).convert("RGBA")
    layer = Image.new("RGBA", (BW * SS, BH * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    acc = pal["acc"]
    strong = acc + (235,)
    mid = acc + (150,)
    soft = acc + (80,)
    faint = acc + (38,)
    lw = max(2, SS * 1)
    px, py = PADX, PADY                        # ko'rinadigan oyna chegarasi

    def P(x, y):                               # ko'rinadigan oyna koordinatasini SS kanvasga o'tkazish
        return _s(x + px), _s(y + py)

    # ---- umumiy: qo'sh ramka
    fo, fi = 34, 50
    rounded_frame(d, *P(fo, fo), *P(W - fo, H - fo), _s(34), mid, lw)
    rounded_frame(d, *P(fi, fi), *P(W - fi, H - fi), _s(26), soft, lw)

    corner_pair = rng.choice([("tl", "br"), ("tr", "bl")])

    def corner_xy(c):
        return {"tl": (0, 0), "tr": (W, 0), "bl": (0, H), "br": (W, H)}[c]

    if style == "mandala":
        n = rng.choice([8, 10, 12])
        for c in corner_pair:
            cx, cy = corner_xy(c)
            cxx, cyy = P(cx, cy)
            rosette(d, cxx, cyy, _s(rng.randint(150, 185)), n, strong, lw, rings=3, rot=rng.random())
            d.ellipse((cxx - _s(250), cyy - _s(250), cxx + _s(250), cyy + _s(250)), outline=soft, width=lw)
        # kichik ikkinchi gullar
        for c in [x for x in ("tl", "tr", "bl", "br") if x not in corner_pair]:
            cx, cy = corner_xy(c)
            rosette(d, *P(cx, cy), _s(rng.randint(60, 80)), 8, mid, lw, rings=2, dots=False)
    elif style == "suzani":
        r = _s(18)
        scallops(d, _s(fi + 34 + PADY), _s(fi + 12 + PADX), _s(W - fi - 12 + PADX), r, mid, lw, up=False)
        scallops(d, _s(H - fi - 34 + PADY), _s(fi + 12 + PADX), _s(W - fi - 12 + PADX), r, mid, lw, up=True)
        for c in ("tl", "tr", "bl", "br"):
            cx, cy = corner_xy(c)
            sx = 1 if cx == 0 else -1
            sy = 1 if cy == 0 else -1
            rosette(d, *P(cx + sx * 112, cy + sy * 112), _s(rng.randint(56, 70)), 8, strong, lw, rings=3, rot=rng.random())
        # yuqori va pastki markaziy gul-medalyon
        rosette(d, *P(W / 2, 118), _s(36), 8, strong, lw, rings=2)
        rosette(d, *P(W / 2, H - 118), _s(36), 8, strong, lw, rings=2)
        # osilgan "tillakosh" nuqtalari
        for i in range(9):
            x = 150 + i * 52
            d.ellipse((_s(x + px) - 3 * SS, _s(190 + py) - 3 * SS, _s(x + px) + 3 * SS, _s(190 + py) + 3 * SS), fill=soft)
    elif style == "arch":
        # miḥrob (uchli arka) — matn shu ichida turadi
        left, right, base_y, spring_y, peak = 88, W - 88, H - 150, 330, 168
        cx = W / 2
        rad = (right - left) / 2
        for k, (inset, col) in enumerate(((0, strong), (16, mid), (30, soft))):
            l, r_ = left + inset, right - inset
            rr = (r_ - l) / 2
            d.line([P(l, base_y), P(l, spring_y + k * 0)], fill=col, width=lw)
            d.line([P(r_, base_y), P(r_, spring_y + k * 0)], fill=col, width=lw)
            d.arc((_s(cx - rr + px), _s(peak + inset + py), _s(cx + rr + px), _s(peak + inset + 2 * rr + py)), 180, 360, fill=col, width=lw)
        diamond(d, *P(cx, peak - 18), _s(11), strong)
        rosette(d, *P(cx, 112), _s(34), 8, strong, lw, rings=2, dots=False)
        for c in ("bl", "br"):
            cxy = corner_xy(c)
            rosette(d, *P(cxy[0] + (92 if c == "bl" else -92), cxy[1] - 92), _s(48), 8, mid, lw, rings=2)
        for c in ("tl", "tr"):
            cxy = corner_xy(c)
            rosette(d, *P(cxy[0] + (84 if c == "tl" else -84), cxy[1] + 84), _s(40), 8, mid, lw, rings=2, dots=False)
        d.line([P(left - 14, base_y), P(right + 14, base_y)], fill=strong, width=lw)
    elif style == "star":
        # fon bo'ylab 8 qirrali yulduzlar to'ri
        step = rng.choice([118, 136])
        for iy in range(-1, int(H / step) + 2):
            for ix in range(-1, int(W / step) + 2):
                cx = ix * step + (step / 2 if iy % 2 else 0)
                cy = iy * step
                star8(d, *P(cx, cy), _s(step * 0.34), faint, lw)
        for c in corner_pair:
            cx, cy = corner_xy(c)
            rosette(d, *P(cx, cy), _s(rng.randint(130, 160)), 8, strong, lw, rings=3, rot=0.2)
            star8(d, *P(cx, cy), _s(230), soft, lw)
        for x in (W / 2,):
            star8(d, *P(x, 108), _s(34), strong, lw)
            star8(d, *P(x, H - 108), _s(34), strong, lw)
    else:  # vine
        for sx, side in ((92, 1), (W - 92, -1)):
            vine(d, *P(sx, 120), *P(sx + side * 6, H - 120), _s(30), 3.0, mid, lw, _s(26), rng, side=side)
        rosette(d, *P(W / 2, 112), _s(44), 10, strong, lw, rings=3)
        rosette(d, *P(W / 2, H - 112), _s(44), 10, strong, lw, rings=3)
        for c in ("tl", "tr", "bl", "br"):
            cx, cy = corner_xy(c)
            sx = 1 if cx == 0 else -1
            sy = 1 if cy == 0 else -1
            rosette(d, *P(cx + sx * 76, cy + sy * 76), _s(40), 8, strong, lw, rings=2, dots=False)

    layer = layer.resize((BW, BH), Image.LANCZOS)
    out = Image.alpha_composite(base, layer)
    return out.convert("RGB")


# ----------------------------------------------------------------------------------------------
# Matn qatlamlari
# ----------------------------------------------------------------------------------------------
def tracked(d, xy, text, fnt, fill, spacing):
    x, y = xy
    for ch in text:
        d.text((x, y), ch, font=fnt, fill=fill)
        x += d.textlength(ch, font=fnt) + spacing
    return x


def tracked_width(d, text, fnt, spacing):
    return sum(d.textlength(ch, font=fnt) + spacing for ch in text) - spacing


def wrap_text(d, text, fnt, max_w):
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if d.textlength(trial, font=fnt) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def fit_font(d, key, text, start, max_w, min_size=28):
    size = start
    while size > min_size and d.textlength(text, font=font(key, size)) > max_w:
        size -= 4
    return font(key, size)


_scratch = Image.new("RGBA", (10, 10))
_sd = ImageDraw.Draw(_scratch)


def fix_uz_quotes(text, lang):
    """o'zbek lotin: o' g' -> oʻ gʻ (to'g'ri belgi), boshqa tillarda oddiy apostrof."""
    text = re.sub(r"[’‘`´ʼ]", "'", text)
    if lang == "uz":
        text = re.sub(r"(?<=[A-Za-z])'(?=[A-Za-z])", "ʻ", text)
        text = re.sub(r"(?<=[OoGg])'", "ʻ", text)
    return text


LABELS = {
    "uz": {"head": "TO'YGA TAKLIF", "venue": "MANZIL", "at": "soat {t}"},
    "uz_cyrl": {"head": "ТЎЙГА ТАКЛИФ", "venue": "МАНЗИЛ", "at": "соат {t}"},
    "ru": {"head": "ПРИГЛАШЕНИЕ НА СВАДЬБУ", "venue": "МЕСТО", "at": "в {t}"},
    "en": {"head": "WEDDING INVITATION", "venue": "VENUE", "at": "at {t}"},
}
AND = {"uz": "&", "uz_cyrl": "&", "ru": "&", "en": "&"}


def split_names(raw):
    raw = raw.strip()
    parts = re.split(r"\s*(?:&|\+|,|;|\bva\b|\bи\b|\band\b|\bВА\b|\bва\b)\s*", raw, maxsplit=1, flags=re.I)
    parts = [p.strip() for p in parts if p.strip()]
    return parts[:2] if len(parts) >= 2 else [raw]


def build_groups(data, pal, style=None):
    """Matn qatlamlari: har biri alohida shaffof rasm + joylashuv + paydo bo'lish vaqti."""
    lang = data.get("lang", "uz")
    lab = LABELS.get(lang, LABELS["uz"])
    acc, txt, sub = pal["acc"], pal["txt"], pal["sub"]
    maxw = 560
    groups = []

    def layer(h):
        return Image.new("RGBA", (W, h), (0, 0, 0, 0))

    # 1) sarlavha + bezak chizig'i
    head = fix_uz_quotes(lab["head"], lang)
    fh = font("inter_sb", 25 if len(head) < 18 else 21)
    tw = tracked_width(_sd, head, fh, 5)
    im = layer(70)
    d = ImageDraw.Draw(im)
    tracked(d, ((W - tw) / 2, 4), head, fh, acc + (255,), 5)
    d.line([(W / 2 - 150, 52), (W / 2 - 22, 52)], fill=acc + (190,), width=2)
    d.line([(W / 2 + 22, 52), (W / 2 + 150, 52)], fill=acc + (190,), width=2)
    diamond(d, W / 2, 52, 7, acc + (255,))
    groups.append({"im": im, "h": 70, "gap": 46, "t": 0.7, "d": 1.2})

    # 2) ismlar
    names = [fix_uz_quotes(n, lang) for n in split_names(data["names"])]
    fnts = [fit_font(_sd, "lora_it", n, 118, maxw, 44) for n in names]
    amp_font = font("lora_it", 62)
    lines = []
    for i, (n, f) in enumerate(zip(names, fnts)):
        lines.append((n, f, txt))
        if i < len(names) - 1:
            lines.append(("&", amp_font, acc))
    gap = 6
    heights = [int(_sd.textbbox((0, 0), s, font=f)[3] + 14) for s, f, _ in lines]
    total = sum(heights) + gap * (len(lines) - 1)
    im = layer(total + 10)
    d = ImageDraw.Draw(im)
    y = 0
    for (s, f, col), hh in zip(lines, heights):
        w_ = d.textlength(s, font=f)
        d.text(((W - w_) / 2, y), s, font=f, fill=col + (255,))
        y += hh + gap
    groups.append({"im": im, "h": total + 10, "gap": 40, "t": 1.9, "d": 1.4})

    # 3) sana va vaqt
    date = fix_uz_quotes(data["date"], lang)
    tm = data.get("time", "").strip()
    fdate = fit_font(_sd, "lora", date, 50, maxw, 30)
    ftime = font("inter_m", 31)
    time_s = lab["at"].format(t=tm) if tm else ""
    hh = int(_sd.textbbox((0, 0), date, font=fdate)[3]) + 18 + (52 if time_s else 0)
    im = layer(hh + 12)
    d = ImageDraw.Draw(im)
    d.text(((W - d.textlength(date, font=fdate)) / 2, 0), date, font=fdate, fill=txt + (255,))
    yy = int(_sd.textbbox((0, 0), date, font=fdate)[3]) + 18
    if time_s:
        w_ = d.textlength(time_s, font=ftime)
        d.text(((W - w_) / 2, yy), time_s, font=ftime, fill=sub + (255,))
    groups.append({"im": im, "h": hh + 12, "gap": 38, "t": 3.3, "d": 1.2})

    # 4) manzil
    venue = fix_uz_quotes(data["venue"], lang)
    fl = font("inter_sb", 20)
    fv = font("inter_m", 31)
    vlines = wrap_text(_sd, venue, fv, maxw)[:3]
    hh = 34 + len(vlines) * 44 + 8
    im = layer(hh)
    d = ImageDraw.Draw(im)
    lw_ = tracked_width(d, lab["venue"], fl, 5)
    tracked(d, ((W - lw_) / 2, 0), lab["venue"], fl, acc + (255,), 5)
    for i, ln in enumerate(vlines):
        d.text(((W - d.textlength(ln, font=fv)) / 2, 36 + i * 44), ln, font=fv, fill=txt + (255,))
    groups.append({"im": im, "h": hh, "gap": 40, "t": 4.5, "d": 1.2})

    # 5) taklif matni
    body = fix_uz_quotes(data["text"], lang)
    size = 34
    while True:
        fb = font("lora_it", size)
        blines = wrap_text(_sd, body, fb, maxw)
        if len(blines) <= 5 or size <= 24:
            break
        size -= 2
    lh = int(size * 1.42)
    hh = lh * len(blines) + 10
    im = layer(hh)
    d = ImageDraw.Draw(im)
    for i, ln in enumerate(blines[:6]):
        d.text(((W - d.textlength(ln, font=fb)) / 2, i * lh), ln, font=fb, fill=sub + (255,))
    groups.append({"im": im, "h": hh, "gap": 0, "t": 5.8, "d": 1.4})

    # joylashuv: vertikal markazlash
    top_min = 238 if style == "arch" else 150
    bottom_max = 1118 if style == "arch" else 1160
    avail = bottom_max - top_min
    hs = sum(g["h"] for g in groups)
    gaps = sum(g["gap"] for g in groups[:-1]) or 1
    if hs + gaps > avail:                      # sig'masa — oraliqlarni siqamiz
        k = max(0.3, (avail - hs) / gaps)
        for g in groups:
            g["gap"] = int(g["gap"] * k)
    total_h = sum(g["h"] for g in groups) + sum(g["gap"] for g in groups[:-1])
    top = max(top_min, (H - total_h) // 2 - 6)
    y = top
    for g in groups:
        g["y"] = y
        y += g["h"] + g["gap"]
    return groups


def crop_group(g):
    """Qatlamni tarkibi (bbox) bo'yicha qirqib, kichik rasmga aylantiradi (ffmpeg uchun yengil)."""
    bbox = g["im"].getbbox()
    if not bbox:
        return None
    x0, y0, x1, y1 = bbox
    x0, y0 = max(0, x0 - 6), max(0, y0 - 6)
    x1, y1 = min(W, x1 + 6), min(g["h"], y1 + 6)
    return g["im"].crop((x0, y0, x1, y1)), x0, g["y"] + y0


# ----------------------------------------------------------------------------------------------
# Yaltirash (sparkle) va nur chizig'i qatlamlari
# ----------------------------------------------------------------------------------------------
def make_sparkles(pal, rng):
    """720x2560 (ikki bir xil yarim) — vertikal siljib, uzluksiz ko'rinadi."""
    half = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(half)
    col = pal["acc"] if pal["light"] else tuple(min(255, int(c * 0.6 + 120)) for c in pal["acc"])
    for _ in range(46):
        x, y = rng.randint(30, W - 30), rng.randint(0, H - 1)
        r = rng.choice([2, 2, 3, 3, 4, 6])
        a = rng.randint(120, 235)
        if r >= 4:       # to'rt qirrali yulduzcha
            pts = [(x, y - r * 2.1), (x + r * 0.5, y - r * 0.5), (x + r * 2.1, y), (x + r * 0.5, y + r * 0.5),
                   (x, y + r * 2.1), (x - r * 0.5, y + r * 0.5), (x - r * 2.1, y), (x - r * 0.5, y - r * 0.5)]
            d.polygon(pts, fill=col + (a,))
        else:
            d.ellipse((x - r, y - r, x + r, y + r), fill=col + (a,))
    full = Image.new("RGBA", (W, H * 2), (0, 0, 0, 0))
    full.paste(half, (0, 0))
    full.paste(half, (0, H))
    return full


def make_sweep(pal):
    """Diagonal nur chizig'i — chapdan o'ngga o'tadi."""
    bw = 300
    arr = np.zeros((H, bw, 4), dtype=np.uint8)
    xs = np.linspace(-1, 1, bw)[None, :]
    ys = np.linspace(0, 1, H)[:, None]
    # diagonal siljish
    shifted = xs + (ys - 0.5) * 0.9
    alpha = np.clip(1 - np.abs(shifted) * 1.15, 0, 1) ** 2 * (34 if not pal["light"] else 46)
    arr[..., 0:3] = 255 if not pal["light"] else 255
    arr[..., 3] = alpha.astype(np.uint8)
    return Image.fromarray(arr, "RGBA")


# ----------------------------------------------------------------------------------------------
# Musiqa sintezi
# ----------------------------------------------------------------------------------------------
_SR = 22050


def _note(freq, dur, kind="pluck"):
    n = int(_SR * dur)
    t = np.arange(n) / _SR
    if kind == "pluck":
        env = np.exp(-t * 3.4) * (1 - np.exp(-t * 90))
        w = np.sin(2 * np.pi * freq * t) + 0.35 * np.sin(4 * np.pi * freq * t) + 0.12 * np.sin(6 * np.pi * freq * t)
    elif kind == "bell":
        env = np.exp(-t * 2.0) * (1 - np.exp(-t * 120))
        w = np.sin(2 * np.pi * freq * t) + 0.5 * np.sin(2 * np.pi * freq * 2.76 * t) * np.exp(-t * 3)
    else:  # pad
        a, r = 0.9, 0.9
        env = np.minimum(1, t / a) * np.minimum(1, (dur - t) / r)
        env = np.clip(env, 0, 1)
        w = np.sin(2 * np.pi * freq * t) + 0.4 * np.sin(2 * np.pi * freq * 1.003 * t) + 0.2 * np.sin(4 * np.pi * freq * t)
    return w * env


def _reverb(x, rng_np):
    n = int(_SR * 1.4)
    t = np.arange(n) / _SR
    ir = rng_np.normal(0, 1, n) * np.exp(-t * 3.2)
    ir[0] = 1.0
    ir /= np.sqrt(np.sum(ir ** 2))
    size = 1 << int(np.ceil(np.log2(len(x) + n)))
    y = np.fft.irfft(np.fft.rfft(x, size) * np.fft.rfft(ir, size), size)[: len(x)]
    return 0.62 * x + 0.55 * y


def synth_music(path, seed, seconds=DURATION + 1.5):
    """Romantik, sokin musiqa (arpeggio + pad + qo'ng'iroqcha ohang) — har seed uchun boshqacha."""
    import wave
    rng = random.Random(seed)
    rng_np = np.random.default_rng(seed)
    root = rng.choice([48, 50, 52, 53, 55, 57])                  # C3..A3 (MIDI)
    minor = rng.random() < 0.35
    bpm = rng.choice([68, 72, 76, 80])
    beat = 60.0 / bpm
    scale = [0, 2, 3, 5, 7, 8, 10] if minor else [0, 2, 4, 5, 7, 9, 11]

    def midi(m):
        return 440.0 * 2 ** ((m - 69) / 12)

    def triad(deg):
        idx = [deg, deg + 2, deg + 4]
        return [root + scale[i % 7] + 12 * (i // 7) for i in idx]

    progs = [[0, 4, 5, 3], [5, 3, 0, 4], [0, 5, 3, 4], [0, 3, 5, 4], [0, 2, 3, 4]]
    prog = rng.choice(progs)
    total = int(_SR * seconds)
    mix = np.zeros(total + _SR * 3)
    bar = 4 * beat
    nbars = int(seconds / bar) + 2
    pattern = rng.choice([[0, 1, 2, 1, 2, 1, 0, 1], [0, 2, 1, 2, 0, 2, 1, 2], [0, 1, 2, 3, 2, 1, 2, 1]])
    for b in range(nbars):
        deg = prog[b % len(prog)]
        ch = triad(deg)
        start = b * bar
        # pad (past oktava akkord)
        for m in ch:
            wv = _note(midi(m - 12), bar + 0.8, "pad") * 0.13
            i0 = int(start * _SR)
            mix[i0:i0 + len(wv)] += wv[: len(mix) - i0]
        # arpeggio (8-nota)
        notes = ch + [ch[0] + 12]
        for k, pi in enumerate(pattern):
            m = notes[pi] + 12
            wv = _note(midi(m), 1.4, "pluck") * 0.22
            i0 = int((start + k * beat / 2) * _SR)
            if i0 < len(mix):
                mix[i0:i0 + len(wv)] += wv[: len(mix) - i0]
        # asosiy ohang (qo'ng'iroqcha)
        for k in (0, 2):
            if rng.random() < 0.85:
                m = rng.choice(ch) + 24
                wv = _note(midi(m), 2.2, "bell") * 0.16
                i0 = int((start + k * beat + (beat / 2 if rng.random() < 0.3 else 0)) * _SR)
                if i0 < len(mix):
                    mix[i0:i0 + len(wv)] += wv[: len(mix) - i0]
    mix = mix[:total]
    mix = _reverb(mix, rng_np)
    mix /= max(1e-6, np.max(np.abs(mix)))
    fade_in, fade_out = int(0.6 * _SR), int(1.8 * _SR)
    mix[:fade_in] *= np.linspace(0, 1, fade_in)
    mix[-fade_out:] *= np.linspace(1, 0, fade_out)
    pcm = (mix * 0.8 * 32767).astype(np.int16)
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(_SR)
        wf.writeframes(pcm.tobytes())
    return path


# ----------------------------------------------------------------------------------------------
# Yig'ish: poster (rasm) + video
# ----------------------------------------------------------------------------------------------
def ffmpeg_exe():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return shutil.which("ffmpeg") or "ffmpeg"


def compose_poster(bg, groups):
    frame = bg.crop((PADX, PADY, PADX + W, PADY + H)).convert("RGBA")
    for g in groups:
        c = crop_group(g)
        if c:
            im, x, y = c
            frame.alpha_composite(im, (x, y))
    return frame.convert("RGB")


def render_video(workdir, bg, groups, pal, rng, music_path, seed, duration=DURATION, fps=None, crf=26, preset=None):
    on_render = bool(os.getenv("RENDER"))          # Render'da (kuchsiz bepul server) avtomatik yengil rejim
    fps = fps or int(os.getenv("TK_FPS", "15" if on_render else str(FPS)))
    preset = preset or os.getenv("TK_PRESET", "ultrafast" if on_render else "veryfast")
    os.makedirs(workdir, exist_ok=True)
    bg_p = os.path.join(workdir, "bg.png")
    bg.save(bg_p)
    inputs = ["-loop", "1", "-framerate", str(fps), "-t", f"{duration}", "-i", bg_p]
    chains = []
    cur = "bg0"
    chains.append(f"[0:v]crop={W}:{H}:x='{PADX}+{PADX - 4}*sin(t*0.45)':y='{PADY}+{PADY - 6}*(1-t/{duration})',setsar=1[{cur}]")
    idx = 1
    # yaltirash — matn ostida
    sp_p = os.path.join(workdir, "sparkles.png")
    make_sparkles(pal, rng).save(sp_p)
    inputs += ["-loop", "1", "-framerate", str(fps), "-t", f"{duration}", "-i", sp_p]
    speed = rng.choice([34, 42, 50])
    chains.append(f"[{idx}:v]format=rgba,fade=t=in:st=0.3:d=1.6:alpha=1[sp]")
    chains.append(f"[{cur}][sp]overlay=x=0:y='-mod(t*{speed},{H})':format=auto[vs]")
    cur = "vs"
    idx += 1
    n = 0
    for g in groups:
        c = crop_group(g)
        if not c:
            continue
        im, x, y = c
        gp = os.path.join(workdir, f"g{n}.png")
        im.save(gp)
        inputs += ["-loop", "1", "-framerate", str(fps), "-t", f"{duration}", "-i", gp]
        chains.append(f"[{idx}:v]format=rgba,fade=t=in:st={g['t']}:d={g['d']}:alpha=1[t{n}]")
        chains.append(f"[{cur}][t{n}]overlay=x={x}:y={y}:format=auto[v{n}]")
        cur = f"v{n}"
        idx += 1
        n += 1
    # nur chizig'i
    sw_p = os.path.join(workdir, "sweep.png")
    make_sweep(pal).save(sw_p)
    inputs += ["-loop", "1", "-framerate", str(fps), "-t", f"{duration}", "-i", sw_p]
    chains.append(f"[{cur}][{idx}:v]overlay=x='-320+mod(t,6)*240':y=0:format=auto[vw]")
    cur = "vw"
    idx += 1
    chains.append(f"[{cur}]fade=t=out:st={duration - 0.9}:d=0.9,format=yuv420p[vout]")
    # audio
    inputs += ["-i", music_path]
    audio_idx = idx
    af = f"[{audio_idx}:a]atrim=0:{duration},afade=t=in:st=0:d=0.6,afade=t=out:st={duration - 1.6}:d=1.6,aformat=sample_rates=44100:channel_layouts=stereo[aout]"
    chains.append(af)
    out = os.path.join(workdir, "taklifnoma.mp4")
    cmd = [ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "error", *inputs,
           "-filter_complex", ";".join(chains), "-map", "[vout]", "-map", "[aout]",
           "-t", f"{duration}", "-r", str(fps), "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
           "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-c:a", "aac", "-b:a", "128k",
           "-threads", os.getenv("TK_THREADS", "0"), "-filter_threads", os.getenv("TK_THREADS", "0"), out]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if res.returncode != 0 or not os.path.exists(out) or os.path.getsize(out) < 5000:
        raise RuntimeError("ffmpeg xatosi: " + (res.stderr or "")[-600:])
    return out


def make_invitation(data, workdir, seed, music_path=None, want_video=True, music_seed=None):
    """
    data: {names, date, time, venue, text, lang, palette(None|str|dict), style(None|str)}
    Qaytaradi: (video_path | None, poster_path, info)   info = {"palette": ..., "style": ...}
    """
    rng = random.Random(seed)
    pal = resolve_palette(data.get("palette"), rng)
    style = data.get("style") if data.get("style") in STYLES else rng.choice(STYLES)
    bg = build_background(pal, style, rng)
    groups = build_groups(data, pal, style)
    os.makedirs(workdir, exist_ok=True)
    poster = compose_poster(bg, groups)
    poster_p = os.path.join(workdir, "taklifnoma.png")
    poster.save(poster_p, optimize=True)
    info = {"palette": pal.get("name", "custom"), "style": style}
    if not want_video:
        return None, poster_p, info
    if not music_path:
        music_path = synth_music(os.path.join(workdir, "music.wav"), seed if music_seed is None else music_seed)
    try:
        video = render_video(workdir, bg, groups, pal, rng, music_path, seed)
    except Exception:
        # tashqi musiqa buzuq bo'lishi mumkin — sintezlangan musiqa bilan qayta urinish
        music_path = synth_music(os.path.join(workdir, "music_fallback.wav"), seed if music_seed is None else music_seed)
        video = render_video(workdir, bg, groups, pal, rng, music_path, seed)
    return video, poster_p, info
