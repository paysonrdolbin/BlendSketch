"""The viewer: shows the current frame with its marks and handles drawing input."""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen
from PySide6.QtWidgets import QLineEdit, QWidget

from . import strokes as S
from .colors import to_hex

PAINT_TOOLS = ("pen", "brush")
SHAPE_TOOLS = ("line", "arrow", "rect", "ellipse")
RING_TOOLS = ("pen", "brush", "smudge", "eraser")


class Canvas(QWidget):
    strokeCommitted = Signal(dict)
    eraseCommitted = Signal(list)
    colorPicked = Signal(str)
    decodeSizeWanted = Signal(int, int)
    zoomChanged = Signal(float)

    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        self.settings = settings  # shared with the window: tool, color, sizes, opacity, blend...
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.setMinimumSize(320, 200)
        self.src_w, self.src_h = 0, 0
        self.frame_img: QImage | None = None
        self.frame_index = 0
        self.strokes: list[dict] = []
        self.author = ""
        self.show_marks = True
        self.message = ""
        self.zoom = 1.0
        self.pan = QPointF(0, 0)
        self.raster = S.RasterCache()
        self._base: QImage | None = None       # footage + this frame's visible strokes
        self._base_key: list | None = None      # ids of the strokes in _base, in order
        self._base_src: QImage | None = None    # the frame image _base was built from
        self._base_scale = 0.0
        self._stack = None                      # S.LayerStack behind _base
        self._smudge_done: str | None = None    # id of a smudge already applied to _stack live
        self._comp: QImage | None = None
        self.live: dict | None = None
        self._live_layer: QImage | None = None
        self._brush_state = {}
        self._smudge_stack = None  # S.LayerStack while a smudge is being drawn
        self._smudgers = []
        self._footage: QImage | None = None
        self._erasing: set | None = None
        self._panning = None
        self._space = False
        self._mouse: QPointF | None = None
        self._tablet = False
        self._pick = None
        self._text_at = None
        self.text_edit = QLineEdit(self)
        self.text_edit.hide()
        self.text_edit.returnPressed.connect(self._commit_text)
        self.text_edit.editingFinished.connect(self._commit_text)
        self.text_edit.installEventFilter(self)
        self._size_timer = QTimer(self, singleShot=True, interval=120)
        self._size_timer.timeout.connect(self._emit_decode_size)

    # ------------------------------------------------------------ state from the window

    @property
    def tool(self) -> str:
        return self.settings["tool"]

    def set_source(self, w: int, h: int):
        self.src_w, self.src_h = w, h
        self.zoom, self.pan = 1.0, QPointF(0, 0)
        self.frame_img = None
        self.raster.clear()
        self.invalidate()
        self._size_timer.start(0)

    def set_frame(self, index: int, img: QImage | None, strokes: list[dict]):
        self.frame_index = index
        if img is not None:
            self.frame_img = img
        self.strokes = strokes
        self.invalidate()

    def set_strokes(self, strokes: list[dict]):
        self.strokes = strokes
        self.invalidate()

    def invalidate(self):
        """Something changed; _ensure_base works out whether a full rebuild is needed."""
        self._comp = None
        self.update()

    # ------------------------------------------------------------ geometry

    def _scale(self) -> float:
        if not self.src_w:
            return 1.0
        fit = min(self.width() / self.src_w, self.height() / self.src_h)
        return fit * self.zoom

    def _origin(self) -> QPointF:
        s = self._scale()
        return QPointF((self.width() - self.src_w * s) / 2 + self.pan.x(), (self.height() - self.src_h * s) / 2 + self.pan.y())

    def to_src(self, p: QPointF) -> tuple[float, float]:
        o, s = self._origin(), self._scale()
        return (p.x() - o.x()) / s, (p.y() - o.y()) / s

    def to_widget(self, x: float, y: float) -> QPointF:
        o, s = self._origin(), self._scale()
        return QPointF(o.x() + x * s, o.y() + y * s)

    def _img_scale(self) -> float:
        return self.frame_img.width() / self.src_w if self.frame_img is not None and self.src_w else 1.0

    def wanted_decode_size(self) -> tuple[int, int]:
        if not self.src_w:
            return (16, 16)
        dpr = self.devicePixelRatioF()
        k = min(1.0, self._scale() * dpr)
        w = max(16, int(self.src_w * k) // 2 * 2)
        h = max(16, int(self.src_h * k) // 2 * 2)
        return (w, h)

    def _emit_decode_size(self):
        self.decodeSizeWanted.emit(*self.wanted_decode_size())

    def resizeEvent(self, e):
        self._size_timer.start()
        super().resizeEvent(e)

    def fit(self):
        self.zoom, self.pan = 1.0, QPointF(0, 0)
        self._size_timer.start(0)
        self.zoomChanged.emit(self.zoom)
        self.update()

    def set_actual_pixels(self):
        if not self.src_w:
            return
        fit = min(self.width() / self.src_w, self.height() / self.src_h)
        self.zoom = 1 / (fit * self.devicePixelRatioF())
        self.pan = QPointF(0, 0)
        self._size_timer.start(0)
        self.zoomChanged.emit(self.zoom)
        self.update()

    def zoom_at(self, factor: float, at: QPointF):
        before = self.to_src(at)
        self.zoom = max(0.1, min(64.0, self.zoom * factor))
        after = self.to_widget(*before)
        self.pan += at - after
        self._size_timer.start()
        self.zoomChanged.emit(self.zoom)
        self.update()

    # ------------------------------------------------------------ compositing

    def _visible_strokes(self):
        if not self.show_marks:
            return []
        if self._erasing:
            return [s for s in self.strokes if s["id"] not in self._erasing]
        return self.strokes

    def _ensure_base(self):
        """Bring _base up to date. Adding strokes on top (the usual case) only draws the new
        strokes; a full rebuild, which re-runs every smudge, happens only when strokes are
        removed, hidden or reordered, or the frame or zoom changes."""
        strokes = self._visible_strokes()
        key = [s["id"] for s in strokes]
        scale = self._img_scale()
        same = self._base is not None and self._base_src is self.frame_img and self._base_scale == scale
        if same and key == self._base_key:
            return
        pending, self._smudge_done = self._smudge_done, None
        n = len(self._base_key) if self._base_key is not None else -1
        if same and n >= 0 and key[:n] == self._base_key and (pending is None or pending in key[n:]):
            new = strokes[n:]
            if any(s["kind"] == "smudge" for s in new):
                for s in new:
                    if s["id"] != pending:  # a smudge drawn live is already in the stack
                        self._stack.push(s)
                base = self.frame_img.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
                self._stack.draw(base)
                self._base = base
            else:
                for s in new:
                    self._stack.push(s)
                S.composite(self._base, new, scale, self.raster)  # just the new strokes, on top
        else:
            stack = S.LayerStack(self.frame_img.size(), scale, self.raster)
            for s in strokes:
                stack.push(s)
            base = self.frame_img.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
            stack.draw(base)
            self._stack, self._base = stack, base
        self._base_key, self._base_src, self._base_scale = key, self.frame_img, scale
        self._comp = None

    def composite_image(self) -> QImage | None:
        if self.frame_img is None:
            return None
        self._ensure_base()
        if self.live is None:
            return self._base
        if self.live["kind"] == "smudge":
            if self._comp is None:
                out = self._footage.copy()
                self._smudge_stack.draw(out)
                self._comp = out
            return self._comp
        if self._comp is None:
            out = self._base.copy()
            if self.live["kind"] in PAINT_TOOLS and self._live_layer is not None:
                S.composite_layer(out, self._live_layer, self.live)
            else:
                hit = S.rasterize(self.live, self._img_scale())
                if hit:
                    img, x, y = hit
                    g = QPainter(out)
                    g.setCompositionMode(S.BLENDS[self.live["blend"]][1])
                    g.setOpacity(self.live["opacity"])
                    g.drawImage(x, y, img)
                    g.end()
            self._comp = out
        return self._comp

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#0b0c10"))
        img = self.composite_image()
        if img is None:
            if self.message:
                p.setPen(QColor("#8a91a2"))
                p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, self.message)
            return
        s = self._scale()
        o = self._origin()
        target = QRectF(o.x(), o.y(), self.src_w * s, self.src_h * s)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, s * self.devicePixelRatioF() < self._img_scale() * 0.999 or self.zoom <= 1.0)
        p.drawImage(target, img)
        self._paint_overlays(p, s)

    def _paint_overlays(self, p: QPainter, s: float):
        if self._mouse is None:
            return
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if self.tool in RING_TOOLS and not self._pick and not self._panning:
            d = max(4.0, self.settings["sizes"][self.tool] * s)
            for color, w in (("#000000", 3), ("#ffffff", 1)):
                p.setPen(QPen(QColor(color), w))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(self._mouse, d / 2, d / 2)
        if self._pick:
            self._paint_loupe(p)

    def _paint_loupe(self, p: QPainter):
        pos, rgb, patch = self._pick
        L = 96
        cx = min(max(pos.x(), L / 2 + 6), self.width() - L / 2 - 6)
        top = pos.y() + 20
        box_h = 40
        if top + L + 6 + box_h > self.height():
            top = pos.y() - 20 - L - 6 - box_h
        loupe = QRectF(cx - L / 2, top, L, L)
        p.save()
        clip = loupe.adjusted(1, 1, -1, -1)
        p.setClipRect(clip)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        p.fillRect(loupe, QColor("#000"))
        p.drawImage(loupe, patch)
        cell = L / patch.width()
        c = QRectF(loupe.left() + cell * (patch.width() // 2), loupe.top() + cell * (patch.height() // 2), cell, cell)
        p.setPen(QPen(QColor("#000"), 3))
        p.drawRect(c)
        p.setPen(QPen(QColor("#fff"), 1))
        p.drawRect(c)
        p.restore()
        p.setPen(QPen(QColor("#ffffff"), 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(loupe, 6, 6)
        # readout
        hexs = to_hex(rgb)
        font = QFont("Menlo")
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setPixelSize(11)
        p.setFont(font)
        line1 = [("R ", "#c8ccd6"), (f"{rgb[0]:>3}  ", "#ff8a8a"), ("G ", "#c8ccd6"), (f"{rgb[1]:>3}  ", "#7fe0a0"), ("B ", "#c8ccd6"), (f"{rgb[2]:>3}", "#8fb3ff")]
        fm = p.fontMetrics()
        w1 = sum(fm.horizontalAdvance(t) for t, _ in line1)
        bw = max(w1, fm.horizontalAdvance(hexs)) + 16 + 22
        box = QRectF(cx - bw / 2, top + L + 6, bw, box_h)
        p.setPen(QPen(QColor("#2d323d"), 1))
        p.setBrush(QColor(11, 12, 16, 235))
        p.drawRoundedRect(box, 5, 5)
        sw = QRectF(box.left() + 8, box.top() + 8, 16, box_h - 16)
        p.setPen(QPen(QColor(255, 255, 255, 90), 1))
        p.setBrush(QColor(*rgb))
        p.drawRoundedRect(sw, 3, 3)
        x = box.left() + 30
        y1 = box.top() + 16
        for t, col in line1:
            p.setPen(QColor(col))
            p.drawText(QPointF(x, y1), t)
            x += fm.horizontalAdvance(t)
        p.setPen(QColor("#8a91a2"))
        p.drawText(QPointF(box.left() + 30, y1 + 15), hexs)

    # ------------------------------------------------------------ eyedropper

    def _update_pick(self, pos: QPointF):
        img = self.composite_image()
        if img is None:
            self._pick = None
            return
        x, y = self.to_src(pos)
        if not (0 <= x < self.src_w and 0 <= y < self.src_h):
            self._pick = None
            return
        k = self._img_scale()
        ix, iy = int(x * k), int(y * k)
        n = 11
        patch = img.copy(ix - n // 2, iy - n // 2, n, n)
        c = QColor(img.pixel(min(ix, img.width() - 1), min(iy, img.height() - 1)))
        self._pick = (pos, (c.red(), c.green(), c.blue()), patch)

    def picking(self) -> bool:
        return self.tool == "picker"

    def refresh_pick(self):
        if self.picking() and self._mouse is not None:
            self._update_pick(self._mouse)
        else:
            self._pick = None
        self.update()

    # ------------------------------------------------------------ input

    def _down(self, pos: QPointF, pressure: float, button, mods):
        if self.frame_img is None:
            return
        self.setFocus()
        if button == Qt.MouseButton.MiddleButton or (button == Qt.MouseButton.LeftButton and self._space):
            self._panning = (pos, QPointF(self.pan))
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        if button != Qt.MouseButton.LeftButton:
            return
        if self.picking():
            self._update_pick(pos)
            if self._pick:
                self.colorPicked.emit(to_hex(self._pick[1]))
            return
        x, y = self.to_src(pos)
        pt = (x, y, pressure)
        tool = self.tool
        if tool == "text":
            self._open_text(pos, pt)
            return
        if tool == "eraser":
            self._erasing = set()
            self._erase_at(x, y)
            return
        st = dict(self.settings)
        st["size"] = self.settings["sizes"][tool]
        if tool == "smudge":
            # The smudge works on this frame's stroke layers, never the footage. It reuses the
            # layers behind the current image, so earlier smudges aren't re-run.
            self._ensure_base()
            self.live = S.make_stroke(tool, self.frame_index, self.author, st, pt)
            self.live["blend"] = "normal"
            self._footage = self.frame_img.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
            stack = self._stack
            self._smudge_stack = stack
            self._smudgers = stack.smudgers(self.live)
            for sm in self._smudgers:
                sm.advance()
            self._comp = None
            self.update()
            return
        self.live = S.make_stroke(tool, self.frame_index, self.author, st, pt)
        if tool in PAINT_TOOLS:
            k = self._img_scale()
            layer = QImage(self.frame_img.width(), self.frame_img.height(), QImage.Format.Format_ARGB32_Premultiplied)
            layer.fill(Qt.GlobalColor.transparent)
            g = QPainter(layer)
            g.setRenderHint(QPainter.RenderHint.Antialiasing)
            g.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            g.scale(k, k)
            if tool == "pen":
                S.pen_dot(g, self.live)
            else:
                S.brush_start(g, self.live, self._brush_state)
            g.end()
            self._live_layer = layer
        else:
            self.live["pts"].append(list(pt))
        self._comp = None
        self.update()

    def _move(self, pos: QPointF, pressure: float, mods):
        self._mouse = pos
        if self._panning:
            start, pan0 = self._panning
            self.pan = pan0 + (pos - start)
            self.update()
            return
        if self.picking():
            self._update_pick(pos)
            self.update()
            return
        self._pick = None
        if self._erasing is not None:
            self._erase_at(*self.to_src(pos))
            self.update()
            return
        if self.live is None:
            if self.tool in RING_TOOLS:
                self.update()
            return
        x, y = self.to_src(pos)
        s = self.live
        if s["kind"] == "smudge":
            last = s["pts"][-1]
            if math.hypot(x - last[0], y - last[1]) >= 0.75 / max(self._scale(), 0.01):
                s["pts"].append([x, y, pressure])
                for sm in self._smudgers:
                    sm.advance()
                self._comp = None
                self.update()
            return
        if s["kind"] in PAINT_TOOLS:
            last = s["pts"][-1]
            if math.hypot(x - last[0], y - last[1]) < 0.75 / max(self._scale(), 0.01):
                return
            s["pts"].append([x, y, pressure])
            k = self._img_scale()
            g = QPainter(self._live_layer)
            g.setRenderHint(QPainter.RenderHint.Antialiasing)
            g.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            g.scale(k, k)
            if s["kind"] == "pen":
                S.pen_seg(g, s, len(s["pts"]) - 1)
            else:
                S.brush_seg(g, s, len(s["pts"]) - 1, self._brush_state)
            g.end()
        else:
            if mods & Qt.KeyboardModifier.ShiftModifier:
                x, y = self._constrain(s, x, y)
            s["pts"][1] = [x, y, pressure]
        self._comp = None
        self.update()

    def _constrain(self, s, x, y):
        a = s["pts"][0]
        dx, dy = x - a[0], y - a[1]
        if s["kind"] in ("rect", "ellipse"):
            m = max(abs(dx), abs(dy))
            return a[0] + math.copysign(m, dx or 1), a[1] + math.copysign(m, dy or 1)
        ang = round(math.atan2(dy, dx) / (math.pi / 4)) * (math.pi / 4)
        L = math.hypot(dx, dy)
        return a[0] + math.cos(ang) * L, a[1] + math.sin(ang) * L

    def _up(self):
        if self._panning:
            self._panning = None
            self.unsetCursor()
            self._size_timer.start()
            return
        if self._erasing is not None:
            ids = list(self._erasing)
            self._erasing = None
            if ids:
                self.eraseCommitted.emit(ids)
            self.invalidate()
            return
        s = self.live
        if s is None:
            return
        self.live = None
        self._live_layer = None
        self._smudge_stack = None
        self._smudgers = []
        self._footage = None
        self._comp = None
        if s["kind"] == "smudge":
            self._smudge_done = s["id"]  # already applied to the stack while drawing
        if s["kind"] not in PAINT_TOOLS + ("smudge",) and math.hypot(s["pts"][0][0] - s["pts"][1][0], s["pts"][0][1] - s["pts"][1][1]) < 3:
            self.update()
            return
        self.strokeCommitted.emit(S.tidy(s))

    def _erase_at(self, x, y):
        r = self.settings["sizes"]["eraser"] / 2
        for s in self.strokes:
            if s["author"] != self.author:  # the eraser only removes your own marks
                continue
            if s["id"] not in self._erasing and S.hit(s, x, y, r):
                self._erasing.add(s["id"])
                self._base_key = None  # erasing: rebuild without the hit strokes
        self._comp = None

    def mousePressEvent(self, e):
        if self._tablet:
            return
        self._down(e.position(), 1.0, e.button(), e.modifiers())

    def mouseMoveEvent(self, e):
        if self._tablet:
            return
        self._move(e.position(), 1.0, e.modifiers())

    def mouseReleaseEvent(self, e):
        if self._tablet:
            return
        self._up()

    def tabletEvent(self, e):
        t = e.type()
        p = max(0.05, e.pressure())
        if t == e.Type.TabletPress:
            self._tablet = True
            self._down(e.position(), p, e.button(), e.modifiers())
        elif t == e.Type.TabletMove:
            self._move(e.position(), p, e.modifiers())
        elif t == e.Type.TabletRelease:
            self._up()
            QTimer.singleShot(0, self._tablet_done)
        e.accept()

    def _tablet_done(self):
        self._tablet = False

    def leaveEvent(self, e):
        self._mouse = None
        self._pick = None
        self.update()

    def wheelEvent(self, e):
        if self.frame_img is None:
            return
        if not e.pixelDelta().isNull() and not (e.modifiers() & Qt.KeyboardModifier.ControlModifier):
            self.pan += QPointF(e.pixelDelta())  # trackpad scroll pans
            self.update()
        else:
            steps = e.angleDelta().y() / 120
            self.zoom_at(1.15 ** steps, e.position())

    def event(self, e):
        if e.type() == e.Type.NativeGesture and self.frame_img is not None:
            if e.gestureType() == Qt.NativeGestureType.ZoomNativeGesture:
                self.zoom_at(1 + e.value(), e.position())
                return True
        return super().event(e)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Space and not e.isAutoRepeat():
            self._space = True
            e.ignore()  # let the window toggle playback when not dragging
            return
        super().keyPressEvent(e)

    def keyReleaseEvent(self, e):
        if e.key() == Qt.Key.Key_Space and not e.isAutoRepeat():
            self._space = False
        super().keyReleaseEvent(e)

    # ------------------------------------------------------------ text tool

    def _open_text(self, pos: QPointF, pt):
        if self._text_at:
            self._commit_text()
        self._text_at = pt
        size = self.settings["sizes"]["text"]
        f = S.text_font({"size": size})
        f.setPixelSize(max(8, int(size * 4 * self._scale())))
        self.text_edit.setFont(f)
        self.text_edit.setStyleSheet(
            f"QLineEdit {{ background: rgba(0,0,0,90); color: {self.settings['color']}; border: 1px dashed #f2b84b; padding: 0 4px; }}")
        self.text_edit.clear()
        h = int(f.pixelSize() * 1.5)
        self.text_edit.setGeometry(int(pos.x()), int(pos.y()), 320, h)
        self.text_edit.show()
        self.text_edit.setFocus()

    def _commit_text(self):
        if not self._text_at:
            return
        text = self.text_edit.text().strip()
        pt = self._text_at
        self._text_at = None
        self.text_edit.hide()
        self.setFocus()
        if not text:
            return
        st = dict(self.settings)
        st["size"] = self.settings["sizes"]["text"]
        s = S.make_stroke("text", self.frame_index, self.author, st, (pt[0], pt[1], 1.0))
        s["text"] = text
        self.strokeCommitted.emit(S.tidy(s))

    def cancel_text(self):
        self._text_at = None
        self.text_edit.hide()

    def eventFilter(self, obj, e):
        if obj is self.text_edit and e.type() == e.Type.KeyPress and e.key() == Qt.Key.Key_Escape:
            self.cancel_text()
            return True
        return super().eventFilter(obj, e)

    # ------------------------------------------------------------ export

    def render_full(self, frame_img: QImage, strokes) -> QImage:
        """Composite marks onto a full-resolution frame (for snapshots)."""
        out = frame_img.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
        S.composite(out, strokes, out.width() / self.src_w, S.RasterCache())
        return out

    def sizeHint(self):
        return QSize(960, 540)
