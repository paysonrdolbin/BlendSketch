"""Draws the app icon and writes packaging/icon.icns (macOS), icon.ico (Windows) and icon.png (Linux)."""

import os
import shutil
import subprocess
import sys

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPainterPath

HERE = os.path.dirname(os.path.abspath(__file__))


def draw(px: int) -> QImage:
    img = QImage(px, px, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    m = px * 0.09
    tile = QRectF(m, m, px - 2 * m, px - 2 * m)
    path = QPainterPath()
    path.addRoundedRect(tile, px * 0.2, px * 0.2)
    p.fillPath(path, QColor("#1a1d24"))
    r = px * 0.2
    cy = px * 0.5
    # left disc Multiply-blue, right disc Screen-amber: the overlap is drawn with Screen
    p.setBrush(QColor("#6f7fb8"))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(QRectF(px * 0.5 - r * 1.45, cy - r, 2 * r, 2 * r))
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Screen)
    p.setBrush(QColor("#f2b84b"))
    p.drawEllipse(QRectF(px * 0.5 - r * 0.55, cy - r, 2 * r, 2 * r))
    p.end()
    return img


def main():
    QGuiApplication(sys.argv[:1])
    draw(512).save(os.path.join(HERE, "icon.png"))
    draw(256).save(os.path.join(HERE, "icon.ico"))
    if sys.platform == "darwin" and shutil.which("iconutil"):
        iconset = os.path.join(HERE, "icon.iconset")
        os.makedirs(iconset, exist_ok=True)
        for s in (16, 32, 128, 256, 512):
            draw(s).save(os.path.join(iconset, f"icon_{s}x{s}.png"))
            draw(s * 2).save(os.path.join(iconset, f"icon_{s}x{s}@2x.png"))
        subprocess.run(["iconutil", "-c", "icns", iconset, "-o", os.path.join(HERE, "icon.icns")], check=True)
        shutil.rmtree(iconset)
    print("icons written to", HERE)


if __name__ == "__main__":
    main()
