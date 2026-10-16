"""Draws the app icon and writes packaging/icon.icns (macOS), icon.ico (Windows) and icon.png (Linux).

The icon, kept flat and minimal: a film frame with a dusk scene, two marks drawn across it with
the app's blend modes (blue Multiply darkens, orange Screen brightens, and their crossing shows
both), and a pencil finishing the Screen stroke. The marks use the same Qt blend modes as the app.

Run:  QT_QPA_PLATFORM=offscreen .venv/bin/python packaging/make_icons.py [--preview out.png]
"""

import math
import os
import shutil
import subprocess
import sys

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush, QColor, QGuiApplication, QImage, QLinearGradient, QPainter, QPainterPath, QPainterPathStroker, QPen, QPolygonF,
    QRadialGradient,
)

HERE = os.path.dirname(os.path.abspath(__file__))
S = 1024  # master size; smaller sizes are scaled from it
CM = QPainter.CompositionMode


def soft_stroke(size: int, pts, radius: float, color: str, alpha: float = 0.35) -> QImage:
    """A soft airbrush stroke: many feathered passes of the same path, widest and faintest first."""
    layer = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    layer.fill(Qt.GlobalColor.transparent)
    p = QPainter(layer)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath(QPointF(*pts[0]))
    for pt in pts[1:]:
        path.lineTo(*pt)
    passes = 90
    for i in range(passes):
        w = 2 * radius * (1 - i / passes)
        c = QColor(color)
        c.setAlphaF(alpha / passes * 2.2)
        p.setPen(QPen(c, w, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.drawPath(path)
    p.end()
    return layer


def curve(points, n=40):
    """Catmull-Rom through a few control points, for smooth hand-drawn strokes."""
    out = []
    P = [points[0]] + points + [points[-1]]
    for i in range(1, len(P) - 2):
        p0, p1, p2, p3 = P[i - 1], P[i], P[i + 1], P[i + 2]
        for k in range(n):
            t = k / n
            t2, t3 = t * t, t * t * t
            out.append(tuple(0.5 * ((2 * p1[j]) + (-p0[j] + p2[j]) * t + (2 * p0[j] - 5 * p1[j] + 4 * p2[j] - p3[j]) * t2
                                    + (-p0[j] + 3 * p1[j] - 3 * p2[j] + p3[j]) * t3) for j in (0, 1)))
    out.append(points[-1])
    return out


def flat_stroke(pts, width: float) -> QPainterPath:
    path = QPainterPath(QPointF(*pts[0]))
    for pt in pts[1:]:
        path.lineTo(*pt)
    stroker = QPainterPathStroker()
    stroker.setWidth(width)
    stroker.setCapStyle(Qt.PenCapStyle.RoundCap)
    stroker.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return stroker.createStroke(path).simplified()


FILM = "#8e939c"  # mid gray: reads as film, lets the amber pencil stand out


def draw_master(film: str | None = None) -> QImage:
    img = QImage(S, S, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)

    # app tile (macOS grid: 100 px margin at 1024)
    tile = QPainterPath()
    tile.addRoundedRect(QRectF(100, 100, 824, 824), 185, 185)
    p.fillPath(tile, QColor("#1b1f27"))

    # film frame: flat cream with a few sprocket holes
    frame = QRectF(196, 250, 632, 500)
    fp = QPainterPath()
    fp.addRoundedRect(frame, 56, 56)
    p.fillPath(fp, QColor(film or FILM))
    hw, hh = 46, 30
    for y in (frame.top() + 26, frame.bottom() - 26 - hh):
        for i in range(5):
            x = frame.left() + 78 + i * (frame.width() - 156 - hw) / 4
            hole = QPainterPath()
            hole.addRoundedRect(QRectF(x, y, hw, hh), 9, 9)
            p.fillPath(hole, QColor("#1b1f27"))

    # the picture: flat dusk with a sun
    pic = frame.adjusted(30, 82, -30, -82)
    clip = QPainterPath()
    clip.addRoundedRect(pic, 28, 28)
    p.save()
    p.setClipPath(clip)
    p.fillRect(pic, QColor("#6d4f8f"))

    tip = (pic.left() + 420, pic.top() + 150)
    # two marks drawn with the app's blend modes: Multiply darkens, Screen brightens
    mult = flat_stroke(curve([(pic.left() - 30, pic.bottom() - 70), (pic.left() + 150, pic.top() + 120),
                              (pic.left() + 330, pic.bottom() - 40), (pic.right() + 30, pic.top() + 90)], 30), 74)
    p.setCompositionMode(CM.CompositionMode_Multiply)
    p.fillPath(mult, QColor("#6f8cff"))
    scr = flat_stroke(curve([(pic.left() + 40, pic.top() + 40), (pic.left() + 210, pic.bottom() - 60), tip], 30), 74)
    p.setCompositionMode(CM.CompositionMode_Screen)
    p.fillPath(scr, QColor("#f08a3c"))
    p.setCompositionMode(CM.CompositionMode_SourceOver)
    p.restore()

    # flat pencil, its tip on the end of the Screen stroke, body toward the lower right
    p.save()
    p.translate(*tip)
    p.rotate(45)
    L, W = 300, 82
    p.setBrush(QColor("#f3d9b1"))
    p.drawPolygon(QPolygonF([QPointF(0, 0), QPointF(78, -W / 2), QPointF(78, W / 2)]))
    p.setBrush(QColor("#1b1f27"))
    k = 26 / 78
    p.drawPolygon(QPolygonF([QPointF(0, 0), QPointF(26, -W / 2 * k), QPointF(26, W / 2 * k)]))
    p.fillRect(QRectF(78, -W / 2, L - 150, W), QColor("#f2b84b"))
    p.fillRect(QRectF(78, 0, L - 150, W / 2), QColor("#e3a43a"))
    p.fillRect(QRectF(L - 72, -W / 2, 34, W), QColor("#c8ccd6"))
    er = QPainterPath()
    er.addRoundedRect(QRectF(L - 50, -W / 2, 56, W), 18, 18)
    p.fillPath(er, QColor("#ef7f8f"))
    p.fillRect(QRectF(L - 72, -W / 2, 34, W), QColor("#c8ccd6"))
    p.restore()

    p.end()
    return img


def scaled(master: QImage, px: int) -> QImage:
    if px == S:
        return master
    return master.scaled(px, px, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)


def main():
    QGuiApplication(sys.argv[:1])
    master = draw_master()
    if "--preview" in sys.argv:
        out = sys.argv[sys.argv.index("--preview") + 1]
        sheet = QImage(1024 + 512 + 256 + 128 + 64 + 32 + 16 + 120, 1024, QImage.Format.Format_ARGB32_Premultiplied)
        sheet.fill(QColor("#7d8496"))
        sp = QPainter(sheet)
        x = 0
        for size in (1024, 512, 256, 128, 64, 32, 16):
            sp.drawImage(x, (1024 - size) // 2, scaled(master, size))
            x += size + 20
        sp.end()
        sheet.save(out)
        print("preview written to", out)
        return
    scaled(master, 512).save(os.path.join(HERE, "icon.png"))
    scaled(master, 256).save(os.path.join(HERE, "icon.ico"))
    if sys.platform == "darwin" and shutil.which("iconutil"):
        iconset = os.path.join(HERE, "icon.iconset")
        os.makedirs(iconset, exist_ok=True)
        for s in (16, 32, 128, 256, 512):
            scaled(master, s).save(os.path.join(iconset, f"icon_{s}x{s}.png"))
            scaled(master, s * 2).save(os.path.join(iconset, f"icon_{s}x{s}@2x.png"))
        subprocess.run(["iconutil", "-c", "icns", iconset, "-o", os.path.join(HERE, "icon.icns")], check=True)
        shutil.rmtree(iconset)
    print("icons written to", HERE)


if __name__ == "__main__":
    main()
