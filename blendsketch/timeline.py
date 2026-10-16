"""Scrub bar: frame ticks, playhead, drawn-on frames, comment frames and the cached range."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QWidget


class Timeline(QWidget):
    seek = Signal(int)
    scrubbing = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(46)
        self.setMouseTracking(True)
        self.frames = 1
        self.current = 0
        self.marks: dict[int, list[str]] = {}  # frame -> author colors
        self.comment_frames: set[int] = set()
        self.cached: set[int] = set()
        self._drag = False
        self._hover = None

    def set_frames(self, n: int):
        self.frames = max(1, n)
        self.update()

    def set_current(self, i: int):
        self.current = i
        self.update()

    def set_marks(self, marks: dict[int, list[str]], comment_frames: set[int]):
        self.marks = marks
        self.comment_frames = comment_frames
        self.update()

    def set_cached(self, cached: set[int]):
        if cached != self.cached:
            self.cached = cached
            self.update()

    def _x(self, f: float) -> float:
        return 6 + (f + 0.5) / self.frames * (self.width() - 12)

    def _frame_at(self, x: float) -> int:
        return max(0, min(self.frames - 1, int((x - 6) / max(1, self.width() - 12) * self.frames)))

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        p.setPen(QPen(QColor("#2d323d"), 1))
        p.setBrush(QColor("#0b0c10"))
        p.drawRoundedRect(r, 5, 5)
        w = self.width() - 12
        step = w / self.frames
        # ticks: every frame when there's room, else every second
        p.setPen(QPen(QColor("#2d323d"), 1))
        h = self.height()
        if step >= 4:
            for f in range(self.frames + 1):
                x = 6 + f * step
                p.drawLine(QPointF(x, h - 10), QPointF(x, h - 4))
        # cached frames strip
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(143, 179, 255, 70))
        for f in self.cached:
            if 0 <= f < self.frames:
                p.drawRect(QRectF(6 + f * step, h - 4, max(1.0, step), 2))
        # drawn-on frames: stacked author colors
        for f, colors in self.marks.items():
            x = self._x(f)
            bw = max(3.0, min(6.0, step * 0.8))
            seg = 14 / max(1, len(colors))
            for k, c in enumerate(colors):
                p.setBrush(QColor(c))
                p.drawRect(QRectF(x - bw / 2, 5 + k * seg, bw, seg))
        # comments
        p.setBrush(QColor("#e6e8ee"))
        for f in self.comment_frames:
            p.drawEllipse(QPointF(self._x(f), 25), 3, 3)
        # hover
        if self._hover is not None and not self._drag:
            p.setPen(QPen(QColor(230, 232, 238, 60), 1))
            x = self._x(self._hover)
            p.drawLine(QPointF(x, 2), QPointF(x, h - 2))
        # playhead
        x = self._x(self.current)
        p.setPen(QPen(QColor("#f2b84b"), 2))
        p.drawLine(QPointF(x, 1), QPointF(x, h - 1))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#f2b84b"))
        p.drawPolygon(QPolygonF([QPointF(x - 5, 1), QPointF(x + 5, 1), QPointF(x, 7)]))

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag = True
            self.scrubbing.emit(True)
            self.seek.emit(self._frame_at(e.position().x()))

    def mouseMoveEvent(self, e):
        f = self._frame_at(e.position().x())
        if self._drag:
            self.seek.emit(f)
        self._hover = f
        self.setToolTip(f"Frame {f + 1}")
        self.update()

    def mouseReleaseEvent(self, e):
        if self._drag:
            self._drag = False
            self.scrubbing.emit(False)

    def leaveEvent(self, e):
        self._hover = None
        self.update()
