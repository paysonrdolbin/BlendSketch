"""Stroke records, rasterizing and blend-mode compositing.

A stroke is a plain dict (it lives in the playlist JSON). Points are in source-pixel
coordinates so marks line up at any decode or display resolution. Each stroke is
rasterized once at full opacity into its own layer, then composited onto the frame with
its blend mode and opacity, so a semi-transparent Multiply stroke doesn't darken where it
crosses itself.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetricsF, QImage, QPainter, QPainterPath, QPen, QRadialGradient

from .playlist import new_id, now

CM = QPainter.CompositionMode
BLENDS = {
    "normal": ("Normal", CM.CompositionMode_SourceOver),
    "multiply": ("Multiply", CM.CompositionMode_Multiply),
    "screen": ("Screen", CM.CompositionMode_Screen),
    "overlay": ("Overlay", CM.CompositionMode_Overlay),
    "soft-light": ("Soft light", CM.CompositionMode_SoftLight),
    "hard-light": ("Hard light", CM.CompositionMode_HardLight),
    "add": ("Add (linear dodge)", CM.CompositionMode_Plus),
    "darken": ("Darken", CM.CompositionMode_Darken),
    "lighten": ("Lighten", CM.CompositionMode_Lighten),
    "color-dodge": ("Color dodge", CM.CompositionMode_ColorDodge),
    "color-burn": ("Color burn", CM.CompositionMode_ColorBurn),
    "difference": ("Difference", CM.CompositionMode_Difference),
    "exclusion": ("Exclusion", CM.CompositionMode_Exclusion),
}
MAIN_BLENDS = ("normal", "multiply", "screen")
TOOL_LABELS = {"pen": "Pen", "brush": "Brush", "line": "Line", "arrow": "Arrow", "rect": "Rect", "ellipse": "Ellipse", "text": "Text"}
TEXT_FAMILY = "Helvetica Neue"


def make_stroke(kind: str, frame: int, author: str, settings: dict, pt) -> dict:
    t = now()
    return {
        "id": new_id(),
        "frame": frame,
        "author": author,
        "created": t,
        "modified": t,
        "deleted": False,
        "kind": kind,
        "color": settings["color"],
        "size": settings["size"],
        "opacity": settings["opacity"],
        "blend": settings["blend"],
        "pressure": settings["pressure"],
        "fill": settings["fill"],
        "pts": [list(pt)],
    }


def tidy(stroke: dict) -> dict:
    """Round coordinates before saving so playlist files stay small."""
    stroke["pts"] = [[round(p[0], 1), round(p[1], 1), round(p[2], 2)] for p in stroke["pts"]]
    return stroke


# ---------------------------------------------------------------- painting

def _mid(a, b):
    return ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)


def _dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def pen_width(s, p):
    return max(0.6, s["size"] * ((0.25 + 0.75 * p) if s["pressure"] else 1))


def text_font(s) -> QFont:
    f = QFont(TEXT_FAMILY)
    f.setPixelSize(max(4, int(s["size"] * 4)))
    f.setWeight(QFont.Weight.DemiBold)
    return f


def _pen(s, w):
    pen = QPen(QColor(s["color"]))
    pen.setWidthF(w)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


def pen_dot(g: QPainter, s):
    a = s["pts"][0]
    r = pen_width(s, a[2]) / 2
    g.setPen(Qt.PenStyle.NoPen)
    g.setBrush(QColor(s["color"]))
    g.drawEllipse(QPointF(a[0], a[1]), r, r)


def pen_seg(g: QPainter, s, i):
    P = s["pts"]
    a, b = P[i - 1], P[i]
    m1 = a if i == 1 else _mid(P[i - 2], a)
    m2 = _mid(a, b)
    path = QPainterPath(QPointF(m1[0], m1[1]))
    path.quadTo(QPointF(a[0], a[1]), QPointF(m2[0], m2[1]))
    g.setPen(_pen(s, pen_width(s, (a[2] + b[2]) / 2)))
    g.setBrush(Qt.BrushStyle.NoBrush)
    g.drawPath(path)


def pen_tail(g: QPainter, s):
    P = s["pts"]
    if len(P) < 2:
        return
    a, b = P[-2], P[-1]
    m = _mid(a, b)
    g.setPen(_pen(s, pen_width(s, b[2])))
    g.drawLine(QPointF(*m), QPointF(b[0], b[1]))


_sprites: dict = {}


def dab_sprite(color: str) -> QImage:
    """A soft round dab, drawn once per color at 128 px and scaled per dab."""
    spr = _sprites.get(color)
    if spr is None:
        spr = QImage(128, 128, QImage.Format.Format_ARGB32_Premultiplied)
        spr.fill(Qt.GlobalColor.transparent)
        p = QPainter(spr)
        grad = QRadialGradient(64, 64, 64)
        c = QColor(color)
        for pos, a in ((0.0, 0.32), (0.45, 0.2), (1.0, 0.0)):
            cc = QColor(c)
            cc.setAlphaF(a)
            grad.setColorAt(pos, cc)
        p.fillRect(0, 0, 128, 128, QBrush(grad))
        p.end()
        _sprites[color] = spr
    return spr


def _spacing(s):
    return max(1.0, s["size"] * 0.07)


def _dab(g, s, x, y, p):
    k = (0.35 + 0.65 * p) if s["pressure"] else 1
    r = s["size"] / 2 * k
    g.drawImage(QRectF(x - r, y - r, r * 2, r * 2), dab_sprite(s["color"]))


def brush_start(g, s, state):
    a = s["pts"][0]
    _dab(g, s, a[0], a[1], a[2])
    state["next"] = _spacing(s)


def brush_seg(g, s, i, state):
    a, b = s["pts"][i - 1], s["pts"][i]
    d = _dist(a, b)
    step = _spacing(s)
    at = state["next"]
    while at <= d:
        t = at / d if d else 0
        _dab(g, s, a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t)
        at += step
    state["next"] = at - d


def head_len(s):
    return max(14.0, s["size"] * 4)


def paint(g: QPainter, s: dict):
    g.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    g.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    P = s["pts"]
    kind = s["kind"]
    color = QColor(s["color"])
    if kind == "pen":
        pen_dot(g, s)
        for i in range(1, len(P)):
            pen_seg(g, s, i)
        pen_tail(g, s)
    elif kind == "brush":
        state = {}
        brush_start(g, s, state)
        for i in range(1, len(P)):
            brush_seg(g, s, i, state)
    elif kind in ("line", "arrow"):
        a, b = P[0], P[1]
        ang = math.atan2(b[1] - a[1], b[0] - a[0])
        L = head_len(s)
        ex, ey = b[0], b[1]
        if kind == "arrow":
            ex -= math.cos(ang) * L * 0.6
            ey -= math.sin(ang) * L * 0.6
        g.setPen(_pen(s, s["size"]))
        g.drawLine(QPointF(a[0], a[1]), QPointF(ex, ey))
        if kind == "arrow":
            head = QPainterPath(QPointF(b[0], b[1]))
            head.lineTo(b[0] - math.cos(ang - 0.45) * L, b[1] - math.sin(ang - 0.45) * L)
            head.lineTo(b[0] - math.cos(ang + 0.45) * L, b[1] - math.sin(ang + 0.45) * L)
            head.closeSubpath()
            g.setPen(Qt.PenStyle.NoPen)
            g.setBrush(color)
            g.drawPath(head)
    elif kind in ("rect", "ellipse"):
        a, b = P[0], P[1]
        r = QRectF(QPointF(min(a[0], b[0]), min(a[1], b[1])), QPointF(max(a[0], b[0]), max(a[1], b[1])))
        if s["fill"]:
            g.setPen(Qt.PenStyle.NoPen)
            g.setBrush(color)
        else:
            pen = _pen(s, s["size"])
            pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin if kind == "rect" else Qt.PenJoinStyle.RoundJoin)
            g.setPen(pen)
            g.setBrush(Qt.BrushStyle.NoBrush)
        g.drawRect(r) if kind == "rect" else g.drawEllipse(r)
    elif kind == "text":
        g.setFont(text_font(s))
        g.setPen(color)
        fm = QFontMetricsF(g.font())
        g.drawText(QPointF(P[0][0], P[0][1] + fm.ascent()), s.get("text", ""))


def bbox(s: dict) -> QRectF:
    P = s["pts"]
    if s["kind"] == "text":
        fm = QFontMetricsF(text_font(s))
        w = fm.horizontalAdvance(s.get("text", ""))
        return QRectF(P[0][0] - 4, P[0][1] - 4, w + 8, fm.height() + 8)
    xs = [p[0] for p in P]
    ys = [p[1] for p in P]
    pad = (head_len(s) if s["kind"] == "arrow" else 0) + s["size"] / 2 + 3
    return QRectF(min(xs) - pad, min(ys) - pad, max(xs) - min(xs) + pad * 2, max(ys) - min(ys) + pad * 2)


class RasterCache:
    """Per-stroke layers at a given render scale, keyed by stroke id and modified time."""

    def __init__(self):
        self.d = {}

    def get(self, s: dict, scale: float):
        key = (s["id"], s.get("modified"), round(scale, 4))
        hit = self.d.get(key)
        if hit is None:
            hit = rasterize(s, scale)
            self.d[key] = hit
            if len(self.d) > 4000:
                self.d.clear()
                self.d[key] = hit
        return hit

    def clear(self):
        self.d.clear()


def rasterize(s: dict, scale: float):
    r = bbox(s)
    x0, y0 = math.floor(r.left() * scale), math.floor(r.top() * scale)
    w, h = math.ceil(r.right() * scale) - x0, math.ceil(r.bottom() * scale) - y0
    if w < 1 or h < 1 or w * h > 80_000_000:
        return None
    img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    g = QPainter(img)
    g.translate(-x0, -y0)
    g.scale(scale, scale)
    paint(g, s)
    g.end()
    return img, x0, y0


def composite(target: QImage, strokes, scale: float, cache: RasterCache):
    """Blend each stroke onto target (an image at `scale` x source resolution)."""
    g = QPainter(target)
    for s in strokes:
        hit = cache.get(s, scale)
        if hit is None:
            continue
        img, x, y = hit
        g.setCompositionMode(BLENDS.get(s["blend"], BLENDS["normal"])[1])
        g.setOpacity(s["opacity"])
        g.drawImage(x, y, img)
    g.end()


def composite_layer(target: QImage, layer: QImage, s: dict):
    g = QPainter(target)
    g.setCompositionMode(BLENDS.get(s["blend"], BLENDS["normal"])[1])
    g.setOpacity(s["opacity"])
    g.drawImage(0, 0, layer)
    g.end()


# ---------------------------------------------------------------- hit testing

def hit(s: dict, x: float, y: float, r: float) -> bool:
    tol = r + s["size"] / 2
    P = s["pts"]

    def seg_d(a, b):
        dx, dy = b[0] - a[0], b[1] - a[1]
        L = dx * dx + dy * dy
        t = max(0.0, min(1.0, ((x - a[0]) * dx + (y - a[1]) * dy) / L)) if L else 0.0
        return math.hypot(x - a[0] - t * dx, y - a[1] - t * dy)

    k = s["kind"]
    if k in ("pen", "brush"):
        if len(P) == 1:
            return math.hypot(x - P[0][0], y - P[0][1]) < tol
        return any(seg_d(P[i - 1], P[i]) < tol for i in range(1, len(P)))
    if k in ("line", "arrow"):
        return seg_d(P[0], P[1]) < tol
    if k == "rect":
        a, b = P
        x0, x1, y0, y1 = min(a[0], b[0]), max(a[0], b[0]), min(a[1], b[1]), max(a[1], b[1])
        inside = x0 - tol < x < x1 + tol and y0 - tol < y < y1 + tol
        if s["fill"]:
            return inside
        return inside and not (x0 + tol < x < x1 - tol and y0 + tol < y < y1 - tol)
    if k == "ellipse":
        a, b = P
        cx, cy = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
        rx, ry = max(1, abs(a[0] - b[0]) / 2), max(1, abs(a[1] - b[1]) / 2)
        d = math.hypot((x - cx) / rx, (y - cy) / ry)
        return d <= 1 + tol / min(rx, ry) if s["fill"] else abs(d - 1) * min(rx, ry) < tol
    if k == "text":
        return bbox(s).adjusted(-r, -r, r, r).contains(QPointF(x, y))
    return False
