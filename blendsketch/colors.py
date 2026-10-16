"""Color model conversions. HSV is the working model so hue and saturation survive grey and black."""

from __future__ import annotations


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def hsv_to_rgb(h: float, s: float, v: float) -> tuple[int, int, int]:
    def f(n):
        k = (n + h / 60) % 6
        return v - v * s * max(0.0, min(k, 4 - k, 1.0))
    return tuple(int(round(f(n) * 255)) for n in (5, 3, 1))


def rgb_to_hsv(r: int, g: int, b: int) -> tuple[float, float, float]:
    r, g, b = r / 255, g / 255, b / 255
    mx = max(r, g, b)
    d = mx - min(r, g, b)
    h = 0.0
    if d:
        if mx == r:
            h = ((g - b) / d) % 6
        elif mx == g:
            h = (b - r) / d + 2
        else:
            h = (r - g) / d + 4
        h *= 60
    return h, (d / mx if mx else 0.0), mx


def hsv_to_hsl(h, s, v):
    l = v * (1 - s / 2)
    sl = 0.0 if l in (0, 1) else (v - l) / min(l, 1 - l)
    return h, sl, l


def hsl_to_hsv(h, s, l):
    v = l + s * min(l, 1 - l)
    return h, (2 * (1 - l / v) if v else 0.0), v


def rgb_to_cmyk(r, g, b):
    r, g, b = r / 255, g / 255, b / 255
    k = 1 - max(r, g, b)
    if k >= 1:
        return 0.0, 0.0, 0.0, 1.0
    return (1 - r - k) / (1 - k), (1 - g - k) / (1 - k), (1 - b - k) / (1 - k), k


def cmyk_to_rgb(c, m, y, k):
    return tuple(int(round(255 * (1 - x) * (1 - k))) for x in (c, m, y))


def to_hex(rgb) -> str:
    return "#" + "".join(f"{clamp(int(x), 0, 255):02x}" for x in rgb)


def hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    n = int(h, 16)
    return (n >> 16) & 255, (n >> 8) & 255, n & 255


def parse_hex(text: str) -> str | None:
    t = text.strip().lstrip("#").lower()
    if len(t) in (3, 6) and all(c in "0123456789abcdef" for c in t):
        return to_hex(hex_to_rgb(t))
    return None


AUTHOR_COLORS = ["#8fb3ff", "#f2b84b", "#7fe0a0", "#ff8a8a", "#c79bff", "#5fd4e6", "#ffb37a", "#e889c9"]


def author_color(name: str) -> str:
    h = 0
    for ch in name:
        h = (h * 31 + ord(ch)) & 0xFFFFFFFF
    return AUTHOR_COLORS[h % len(AUTHOR_COLORS)]
