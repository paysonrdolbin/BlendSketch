"""Line icons drawn from inline SVG, tinted for normal and checked states."""

from __future__ import annotations

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

_S = 'fill="none" stroke="{c}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"'
_F = 'fill="{c}"'

PATHS = {
    "pen": (_S, '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/>'),
    "brush": (_S, '<path d="m9.06 11.9 8.07-8.06a2.85 2.85 0 1 1 4.03 4.03l-8.06 8.08"/><path d="M7.07 14.94c-1.66 0-3 1.35-3 3.02 0 1.33-2.5 1.52-2 2.02 1.08 1.1 2.49 2.02 4 2.02 2.2 0 4-1.8 4-4.04a3.01 3.01 0 0 0-3-3.02z"/>'),
    "smudge": (_S, '<path d="M18 11V6a2 2 0 0 0-4 0v0"/><path d="M14 10V4a2 2 0 0 0-4 0v2"/><path d="M10 10.5V6a2 2 0 0 0-4 0v8"/><path d="M18 8a2 2 0 1 1 4 0v6a8 8 0 0 1-8 8h-2c-2.8 0-4.5-.86-5.99-2.34l-3.6-3.6a2 2 0 0 1 2.83-2.83L7 15"/>'),
    "line": (_S, '<path d="M5 19 19 5"/>'),
    "arrow": (_S, '<path d="M5 19 19 5"/><path d="M10 5h9v9"/>'),
    "rect": (_S, '<rect x="4" y="6" width="16" height="12" rx="1"/>'),
    "ellipse": (_S, '<ellipse cx="12" cy="12" rx="8.5" ry="6.5"/>'),
    "text": (_S, '<path d="M5 6V4h14v2"/><path d="M12 4v16"/><path d="M9 20h6"/>'),
    "eraser": (_S, '<path d="m7 21-4.3-4.3c-1-1-1-2.5 0-3.4l9.6-9.6c1-1 2.5-1 3.4 0l5.6 5.6c1 1 1 2.5 0 3.4L13 21"/><path d="M22 21H7"/><path d="m5 11 9 9"/>'),
    "picker": (_S, '<path d="m2 22 1-1h3l9-9"/><path d="M3 21v-3l9-9"/><path d="m15 6 3.4-3.4a2.1 2.1 0 1 1 3 3L18 9l.4.4a2.1 2.1 0 1 1-3 3l-3.8-3.8a2.1 2.1 0 1 1 3-3l.4.4Z"/>'),
    "palette": (_S, '<circle cx="13.5" cy="6.5" r="1.5"/><circle cx="17.5" cy="10.5" r="1.5"/><circle cx="8.5" cy="7.5" r="1.5"/><circle cx="6.5" cy="12.5" r="1.5"/><path d="M12 2a10 10 0 0 0 0 20c.9 0 1.6-.7 1.6-1.6 0-.4-.2-.8-.4-1.1-.3-.3-.4-.7-.4-1.1 0-.9.7-1.6 1.6-1.6H16a6 6 0 0 0 6-6c0-4.9-4.5-8.6-10-8.6Z"/>'),
    "undo": (_S, '<path d="M9 14 4 9l5-5"/><path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H11"/>'),
    "redo": (_S, '<path d="m15 14 5-5-5-5"/><path d="M20 9H9.5a5.5 5.5 0 0 0 0 11H13"/>'),
    "first": (_F, '<path d="M6 5h2v14H6zM20 5v14L9 12z"/>'),
    "prev": (_F, '<path d="M15 5v14L6 12z"/><path d="M17 5h2v14h-2z"/>'),
    "play": (_F, '<path d="M7 4v16l13-8z"/>'),
    "pause": (_F, '<path d="M6 4h4v16H6zM14 4h4v16h-4z"/>'),
    "next": (_F, '<path d="M9 5v14l9-7z"/><path d="M5 5h2v14H5z"/>'),
    "last": (_F, '<path d="M16 5h2v14h-2zM4 5v14l11-7z"/>'),
    "prevmark": (_S, '<path d="m15 6-6 6 6 6"/><path d="M5 9v6"/>'),
    "nextmark": (_S, '<path d="m9 6 6 6-6 6"/><path d="M19 9v6"/>'),
    "sound": (_S, '<path d="M11 5 6 9H2v6h4l5 4z"/><path d="M15.5 8.5a5 5 0 0 1 0 7"/><path d="M19 5a10 10 0 0 1 0 14"/>'),
    "mute": (_S, '<path d="M11 5 6 9H2v6h4l5 4z"/><path d="m22 9-6 6"/><path d="m16 9 6 6"/>'),
    "camera": (_S, '<path d="M14.5 4h-5L7 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-3l-2.5-3z"/><circle cx="12" cy="13" r="3"/>'),
    "plus": (_S, '<path d="M12 5v14"/><path d="M5 12h14"/>'),
    "minus": (_S, '<path d="M5 12h14"/>'),
    "link": (_S, '<path d="M10 13a5 5 0 0 0 7.5.5l3-3a5 5 0 0 0-7-7l-1.7 1.7"/><path d="M14 11a5 5 0 0 0-7.5-.5l-3 3a5 5 0 0 0 7 7l1.7-1.7"/>'),
    "fit": (_S, '<path d="M8 3H5a2 2 0 0 0-2 2v3"/><path d="M21 8V5a2 2 0 0 0-2-2h-3"/><path d="M3 16v3a2 2 0 0 0 2 2h3"/><path d="M16 21h3a2 2 0 0 0 2-2v-3"/>'),
    "comment": (_S, '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>'),
    "eye": (_S, '<path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/>'),
}

FG = "#e6e8ee"
INK = "#1b1404"
_cache: dict = {}


def _render(name: str, color: str, px: int = 48) -> QPixmap:
    attrs, body = PATHS[name]
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><g {attrs.format(c=color)}>{body}</g></svg>'
    r = QSvgRenderer(QByteArray(svg.encode()))
    img = QImage(px, px, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    r.render(p, QRectF(0, 0, px, px))
    p.end()
    pm = QPixmap.fromImage(img)
    pm.setDevicePixelRatio(2)
    return pm


def icon(name: str, color: str = FG, checked_color: str = INK) -> QIcon:
    key = (name, color, checked_color)
    ic = _cache.get(key)
    if ic is None:
        ic = QIcon()
        ic.addPixmap(_render(name, color), QIcon.Mode.Normal, QIcon.State.Off)
        ic.addPixmap(_render(name, checked_color), QIcon.Mode.Normal, QIcon.State.On)
        ic.addPixmap(_render(name, "#5b6170"), QIcon.Mode.Disabled, QIcon.State.Off)
        _cache[key] = ic
    return ic


def checkbox_images() -> tuple[str, str]:
    """Write checked/unchecked checkbox PNGs (with @2x versions) and return their paths for stylesheets."""
    import os
    import tempfile
    folder = os.path.join(tempfile.gettempdir(), "blendsketch-ui")
    os.makedirs(folder, exist_ok=True)
    box = '<rect x="1" y="1" width="12" height="12" rx="3" fill="{fill}" stroke="{stroke}" stroke-width="1"/>'
    tick = '<path d="M3.6 7.2 6 9.6l4.6-5" fill="none" stroke="#1b1404" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"/>'
    svgs = {
        "check_on": box.format(fill="#f2b84b", stroke="#f2b84b") + tick,
        "check_off": box.format(fill="#0b0c10", stroke="#5b6170"),
    }
    paths = []
    for name, body in svgs.items():
        svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 14 14">{body}</svg>'
        r = QSvgRenderer(QByteArray(svg.encode()))
        for scale, suffix in ((1, ""), (2, "@2x")):
            img = QImage(14 * scale, 14 * scale, QImage.Format.Format_ARGB32_Premultiplied)
            img.fill(Qt.GlobalColor.transparent)
            p = QPainter(img)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            r.render(p, QRectF(0, 0, 14 * scale, 14 * scale))
            p.end()
            img.save(os.path.join(folder, f"{name}{suffix}.png"))
        paths.append(os.path.join(folder, f"{name}.png").replace("\\", "/"))
    return paths[0], paths[1]
