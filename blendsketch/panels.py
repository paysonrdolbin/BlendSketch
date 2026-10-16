"""Side panels: playlist, authors, this frame, comments, preferences."""

from __future__ import annotations

import datetime as dt

from PySide6.QtCore import QRunnable, QSize, Qt, QThreadPool, QObject, Signal
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QPlainTextEdit, QPushButton, QScrollArea, QSizePolicy, QSpinBox,
    QToolButton, QVBoxLayout, QWidget,
)

from .colors import author_color
from .icons import icon
from .strokes import BLENDS, TOOL_LABELS

THUMB = QSize(80, 45)


def fmt_time(t: float) -> str:
    d = dt.datetime.fromtimestamp(t)
    today = dt.date.today()
    if d.date() == today:
        return d.strftime("%H:%M")
    return d.strftime("%b %d %H:%M").replace(" 0", " ")


def dot_icon(color: str, size=12) -> QIcon:
    pm = QPixmap(size * 2, size * 2)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor(color))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(0, 0, size * 2, size * 2, 6, 6)
    p.end()
    pm.setDevicePixelRatio(2)
    return QIcon(pm)


# ---------------------------------------------------------------- thumbnails

class _ThumbSignals(QObject):
    done = Signal(str, QImage)


class _ThumbJob(QRunnable):
    def __init__(self, path, frames, signals):
        super().__init__()
        self.path, self.frames, self.signals = path, frames, signals

    def run(self):
        from .media import VideoReader, frame_to_qimage
        try:
            r = VideoReader(self.path)
            f = r.read(max(0, int(self.frames * 0.1)))
            img = frame_to_qimage(f, THUMB.width() * 2, THUMB.height() * 2) if f is not None else QImage()
            r.close()
        except Exception:
            img = QImage()
        self.signals.done.emit(self.path, img)


class PlaylistPanel(QWidget):
    itemSelected = Signal(str)
    orderChanged = Signal(list)
    addRequested = Signal()
    removeRequested = Signal(str)
    relinkRequested = Signal(str)
    renameRequested = Signal(str)
    filesDropped = Signal(list)
    thumbReady = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)
        head = QHBoxLayout()
        self.name = QLineEdit()
        self.name.setObjectName("PlaylistName")
        self.name.setPlaceholderText("Playlist name")
        self.name.editingFinished.connect(lambda: self.renameRequested.emit(self.name.text().strip()))
        head.addWidget(self.name, 1)
        lay.addLayout(head)
        self.path_label = QLabel()
        self.path_label.setObjectName("Muted")
        self.path_label.setWordWrap(True)
        lay.addWidget(self.path_label)
        self.list = QListWidget()
        self.list.setObjectName("PlaylistList")
        self.list.setIconSize(THUMB)
        self.list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.list.setSpacing(2)
        self.list.setWordWrap(True)
        self.list.currentItemChanged.connect(self._current)
        self.list.model().rowsMoved.connect(self._moved)
        self.list.itemDoubleClicked.connect(self._double)
        lay.addWidget(self.list, 1)
        btns = QHBoxLayout()
        self.add_btn = QPushButton(icon("plus"), "Add media")
        self.add_btn.clicked.connect(self.addRequested)
        self.relink_btn = QToolButton()
        self.relink_btn.setIcon(icon("link"))
        self.relink_btn.setToolTip("Relink footage")
        self.relink_btn.clicked.connect(lambda: self._with_current(self.relinkRequested))
        self.remove_btn = QToolButton()
        self.remove_btn.setIcon(icon("minus"))
        self.remove_btn.setToolTip("Remove from playlist")
        self.remove_btn.clicked.connect(lambda: self._with_current(self.removeRequested))
        btns.addWidget(self.add_btn, 1)
        btns.addWidget(self.relink_btn)
        btns.addWidget(self.remove_btn)
        lay.addLayout(btns)
        self.setAcceptDrops(True)
        self.thumbs: dict[str, QImage] = {}
        self._pending = set()
        self._signals = _ThumbSignals()
        self._signals.done.connect(self._thumb_done)
        self._building = False

    def _with_current(self, sig):
        it = self.list.currentItem()
        if it:
            sig.emit(it.data(Qt.ItemDataRole.UserRole))

    def _current(self, cur, prev):
        if cur and not self._building:
            self.itemSelected.emit(cur.data(Qt.ItemDataRole.UserRole))

    def _moved(self, *a):
        ids = [self.list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.list.count())]
        self.orderChanged.emit(ids)

    def _double(self, it):
        if it.data(Qt.ItemDataRole.UserRole + 1):  # missing
            self.relinkRequested.emit(it.data(Qt.ItemDataRole.UserRole))

    def set_items(self, rows: list[dict], current: str | None):
        """rows: id, label, detail, missing, path, frames, notes"""
        self._building = True
        self.list.clear()
        for r in rows:
            it = QListWidgetItem()
            note = f" · {r['notes']} note{'s' if r['notes'] != 1 else ''}" if r["notes"] else ""
            if r["missing"]:
                it.setText(f"{r['label']}\nMissing: double-click to relink")
                it.setForeground(QColor("#ef6464"))
            else:
                it.setText(f"{r['label']}\n{r['detail']}{note}")
            it.setData(Qt.ItemDataRole.UserRole, r["id"])
            it.setData(Qt.ItemDataRole.UserRole + 1, r["missing"])
            it.setSizeHint(QSize(0, THUMB.height() + 16))
            if r["path"] and r["path"] in self.thumbs and not self.thumbs[r["path"]].isNull():
                it.setIcon(QIcon(QPixmap.fromImage(self.thumbs[r["path"]])))
            elif r["path"] and r["path"] not in self._pending:
                self._pending.add(r["path"])
                QThreadPool.globalInstance().start(_ThumbJob(r["path"], r["frames"], self._signals))
            self.list.addItem(it)
            if r["id"] == current:
                self.list.setCurrentItem(it)
        self._building = False

    def _thumb_done(self, path, img):
        self._pending.discard(path)
        img.setDevicePixelRatio(2)
        self.thumbs[path] = img
        self.thumbReady.emit()

    def set_playlist(self, name: str, path: str):
        self.name.setText(name)
        self.path_label.setText(path)
        self.path_label.setToolTip(path)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if paths:
            self.filesDropped.emit(paths)


# ---------------------------------------------------------------- authors

class AuthorsPanel(QWidget):
    """One row per person: show or hide all of their strokes, and separately all of their comments.
    Hiding only changes what you see; it never changes the playlist."""

    visibilityChanged = Signal(str, str, bool)  # author, "strokes" | "comments", visible

    def __init__(self, parent=None):
        super().__init__(parent)
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(4)

    def set_authors(self, counts: dict[str, tuple[int, int]], hidden_strokes: set[str], hidden_comments: set[str], me: str):
        while self.lay.count():
            w = self.lay.takeAt(0).widget()
            if w:
                w.hide()
                w.deleteLater()
        names = sorted(set(counts) | {me}, key=lambda n: (n != me, n.lower()))
        for n in names:
            ns, nc = counts.get(n, (0, 0))
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(10)
            who = QLabel(f"{n}{'  (you)' if n == me else ''}")
            who.setStyleSheet(f"color: {author_color(n)}; font-weight: 600;")
            who.setMinimumWidth(0)
            who.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            who.setToolTip(n)
            h.addWidget(who, 1)
            for kind, ic, count, hidden in (("strokes", "brush", ns, hidden_strokes), ("comments", "comment", nc, hidden_comments)):
                b = QToolButton()
                b.setObjectName("VisToggle")
                b.setCheckable(True)
                b.setChecked(n not in hidden)
                b.setIcon(icon(ic, "#5b6170", "#e6e8ee"))
                b.setText(str(count))
                b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
                b.setToolTip(f"Show or hide all of {n}'s {kind} (only on this machine)")
                b.toggled.connect(lambda on, nn=n, k=kind: self.visibilityChanged.emit(nn, k, on))
                h.addWidget(b)
            self.lay.addWidget(row)


# ---------------------------------------------------------------- this frame

class FramePanel(QWidget):
    """Strokes on the current frame, each with its own show/hide checkbox."""

    clearRequested = Signal()
    strokeToggled = Signal(str, bool)
    showAllRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.info = QLabel()
        lay.addWidget(self.info)
        top = QHBoxLayout()
        top.addStretch(1)
        self.show_all = QPushButton("Show all")
        self.show_all.setToolTip("Show every stroke you've hidden on this frame")
        self.show_all.clicked.connect(self.showAllRequested)
        self.clear_btn = QPushButton("Clear mine")
        self.clear_btn.setToolTip("Delete your visible marks on this frame. Other people's marks can only be hidden.")
        self.clear_btn.clicked.connect(self.clearRequested)
        top.addWidget(self.show_all)
        top.addWidget(self.clear_btn)
        lay.addLayout(top)
        self.list = QListWidget()
        self.list.setObjectName("StrokeList")
        self.list.setMaximumHeight(150)
        self.list.itemChanged.connect(self._changed)
        lay.addWidget(self.list)

    def _changed(self, it):
        sid = it.data(Qt.ItemDataRole.UserRole)
        if sid:
            self.strokeToggled.emit(sid, it.checkState() == Qt.CheckState.Checked)

    def set_frame(self, frame: int, strokes: list[dict], hidden_ids: set[str], hidden_authors: set[str], me: str):
        n_hidden = sum(1 for s in strokes if s["id"] in hidden_ids or s["author"] in hidden_authors)
        text = f"Frame {frame + 1}  ·  {len(strokes)} mark{'s' if len(strokes) != 1 else ''}"
        if n_hidden:
            text += f"  ·  {n_hidden} hidden"
        self.info.setText(text)
        self.show_all.setVisible(any(s["id"] in hidden_ids for s in strokes))
        self.clear_btn.setEnabled(any(s["author"] == me and s["id"] not in hidden_ids and me not in hidden_authors for s in strokes))
        self.list.blockSignals(True)
        self.list.clear()
        if not strokes:
            it = QListWidgetItem("Nothing drawn on this frame.")
            it.setForeground(QColor("#8a91a2"))
            self.list.addItem(it)
        for s in reversed(strokes):
            label = TOOL_LABELS.get(s["kind"], s["kind"])
            if s["kind"] == "text":
                label += f" “{s.get('text', '')[:16]}”"
            it = QListWidgetItem(dot_icon(s["color"], 10), f"{label}  —  {s['author']}    {BLENDS.get(s['blend'], ('?',))[0]} {round(s['opacity'] * 100)}%")
            it.setData(Qt.ItemDataRole.UserRole, s["id"])
            if s["author"] in hidden_authors:
                # Hidden along with all of this person's strokes: unhide them in Authors first.
                it.setFlags(Qt.ItemFlag.ItemIsUserCheckable)
                it.setCheckState(Qt.CheckState.Unchecked)
                it.setToolTip(f"Hidden with all of {s['author']}'s strokes. Turn them back on in Authors.")
            else:
                it.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsSelectable)
                it.setCheckState(Qt.CheckState.Unchecked if s["id"] in hidden_ids else Qt.CheckState.Checked)
                it.setToolTip("Show or hide this stroke (only on this machine)")
            self.list.addItem(it)
        self.list.blockSignals(False)


# ---------------------------------------------------------------- comments

class CommentCard(QFrame):
    def __init__(self, c: dict, tc: str, here: bool, mine: bool, on_jump, on_delete):
        super().__init__()
        self.setObjectName("CommentHere" if here else "Comment")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 8)
        lay.setSpacing(4)
        head = QHBoxLayout()
        jump = QPushButton(f"F {c['frame'] + 1} · {tc}")
        jump.setObjectName("FrameChip")
        jump.clicked.connect(on_jump)
        who = QLabel(c["author"])
        who.setStyleSheet(f"color: {author_color(c['author'])}; font-weight: 600;")
        when = QLabel(fmt_time(c["created"]))
        when.setObjectName("Muted")
        head.addWidget(jump)
        head.addWidget(who)
        head.addWidget(when)
        head.addStretch(1)
        if mine:
            d = QToolButton()
            d.setText("✕")
            d.setObjectName("DeleteBtn")
            d.setToolTip("Delete comment")
            d.clicked.connect(on_delete)
            head.addWidget(d)
        lay.addLayout(head)
        body = QLabel(c["text"])
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(body)


class CommentsPanel(QWidget):
    jumpRequested = Signal(int)
    deleteRequested = Signal(str)
    addRequested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.box = QVBoxLayout()
        self.box.setSpacing(6)
        lay.addLayout(self.box)
        self.text = QPlainTextEdit()
        self.text.setObjectName("Compose")
        self.text.setFixedHeight(64)
        self.text.installEventFilter(self)
        lay.addWidget(self.text)
        row = QHBoxLayout()
        row.addStretch(1)
        self.add = QPushButton("Add comment")
        self.add.clicked.connect(self._submit)
        row.addWidget(self.add)
        lay.addLayout(row)

    def eventFilter(self, obj, e):
        if obj is self.text and e.type() == e.Type.KeyPress and e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) \
                and e.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier):
            self._submit()
            return True
        return super().eventFilter(obj, e)

    def _submit(self):
        t = self.text.toPlainText().strip()
        if t:
            self.addRequested.emit(t)
            self.text.clear()

    def set_comments(self, comments: list[dict], frame: int, me: str, tc):
        while self.box.count():
            w = self.box.takeAt(0).widget()
            if w:
                w.hide()
                w.deleteLater()
        self.text.setPlaceholderText(f"Comment on frame {frame + 1}  (⌘/Ctrl+Enter)")
        if not comments:
            lab = QLabel("No comments yet. Notes attach to the frame you're on.")
            lab.setObjectName("Muted")
            lab.setWordWrap(True)
            self.box.addWidget(lab)
            return
        for c in sorted(comments, key=lambda c: (c["frame"], c["created"])):
            self.box.addWidget(CommentCard(
                c, tc(c["frame"]), c["frame"] == frame, c["author"] == me,
                lambda _=False, f=c["frame"]: self.jumpRequested.emit(f),
                lambda _=False, i=c["id"]: self.deleteRequested.emit(i)))


# ---------------------------------------------------------------- preferences

class PrefsDialog(QDialog):
    def __init__(self, prefs, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Preferences")
        self.prefs = prefs
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.author = QLineEdit(prefs.author)
        form.addRow("Your name", self.author)
        hint = QLabel("Shown on your strokes and comments.")
        hint.setObjectName("Muted")
        form.addRow("", hint)
        self.cache = QSpinBox()
        self.cache.setRange(256, 65536)
        self.cache.setSingleStep(256)
        self.cache.setSuffix(" MB")
        self.cache.setValue(prefs.cache_mb)
        form.addRow("Frame cache", self.cache)
        lay.addLayout(form)
        lab = QLabel("Path mappings")
        lab.setStyleSheet("font-weight: 600; margin-top: 8px;")
        lay.addWidget(lab)
        expl = QLabel(
            "When the same server is mounted at different paths on different machines, list the equivalent roots "
            "on one line, separated by “=”. BlendSketch tries each when footage isn't found.")
        expl.setWordWrap(True)
        expl.setObjectName("Muted")
        lay.addWidget(expl)
        self.maps = QPlainTextEdit(prefs.mappings_text)
        self.maps.setPlaceholderText("/Volumes/prod = P:/ = /mnt/prod")
        self.maps.setMinimumHeight(90)
        lay.addWidget(self.maps)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.resize(520, 380)

    def accept(self):
        if self.author.text().strip():
            self.prefs.author = self.author.text().strip()
        self.prefs.cache_mb = self.cache.value()
        self.prefs.mappings_text = self.maps.toPlainText()
        super().accept()


def scroll_wrap(w: QWidget) -> QScrollArea:
    sa = QScrollArea()
    sa.setWidget(w)
    sa.setWidgetResizable(True)
    sa.setFrameShape(QFrame.Shape.NoFrame)
    sa.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    return sa
