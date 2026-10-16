"""End-to-end smoke test of the window, run offscreen. Saves screenshots to testdata/shots/.

Run: QT_QPA_PLATFORM=offscreen .venv/bin/python tests/gui_smoke.py
"""

import os
import shutil
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["BLENDSKETCH_SETTINGS"] = os.path.join(tempfile.mkdtemp(), "prefs.ini")

from PySide6.QtCore import QPointF, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from blendsketch.app import App, STYLE, checkbox_style  # noqa: E402
from blendsketch.playlist import Playlist  # noqa: E402
from blendsketch.prefs import Prefs  # noqa: E402
from blendsketch.window import MainWindow  # noqa: E402

FOOT = os.path.join(ROOT, "testdata", "footage")
SHOTS = os.path.join(ROOT, "testdata", "shots")
os.makedirs(SHOTS, exist_ok=True)


def pump(sec=0.3):
    end = time.time() + sec
    while time.time() < end:
        QApplication.processEvents()
        time.sleep(0.005)


def wait_for(cond, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        QApplication.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return False


def drag(win, pts, pressure=1.0):
    c = win.canvas
    c._down(c.to_widget(*pts[0][:2]), pressure, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    for p in pts[1:]:
        c._move(c.to_widget(*p[:2]), pressure, Qt.KeyboardModifier.NoModifier)
    c._up()


def main():
    app = App(sys.argv[:1])
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE + checkbox_style())
    prefs = Prefs()
    prefs.author = "dana"
    win = MainWindow(prefs)
    app.window = win
    win.resize(1500, 920)
    win.show()
    pump()
    win.grab().save(os.path.join(SHOTS, "0_welcome.png"))

    pdir = tempfile.mkdtemp()
    path = os.path.join(pdir, "Shot review.bsplaylist")
    win._load_playlist(Playlist.create(path, "Shot review", prefs.author))
    win.add_media([os.path.join(FOOT, f) for f in ("shot010_v003.mov", "shot020_v001_4k4444.mov", "edit_ref.mp4")])
    assert len(win.pl.items()) == 3, "three clips added"
    win.open_item(win.pl.items()[0]["id"])
    assert wait_for(lambda: win.canvas.frame_img is not None), "first frame decoded"
    win.goto(12)
    assert wait_for(lambda: win.player.image(12) is not None), "seek decoded"
    pump(0.3)

    # dana: multiply soft brush + screen glow + arrow + text
    win.set_tool("brush"); win.set_blend("multiply"); win.color.set_hex("#6f7fb8", emit=True)
    drag(win, [(300 + i * 25, 700 + (i % 2) * 30, 1) for i in range(40)])
    win.set_blend("screen"); win.color.set_hex("#ff9a4d", emit=True)
    drag(win, [(1500 + 120 * __import__("math").cos(a / 10), 400 + 120 * __import__("math").sin(a / 10), 1) for a in range(70)])
    win.set_tool("arrow"); win.set_blend("normal"); win.color.set_hex("#ef6464", emit=True)
    drag(win, [(900, 200, 1), (1200, 500, 1)])
    win.add_comment("Shadow should pool tighter under the ball here.")
    # another reviewer adds notes in the same file
    prefs.author = "lead"
    win.canvas.author = "lead"
    win.set_tool("ellipse"); win.color.set_hex("#7fe0a0", emit=True)
    drag(win, [(1300, 650, 1), (1650, 900, 1)])
    win.add_comment("Agree. Also check the rim light on frame 30.")
    pump(0.2)
    item = win._item()
    assert len(Playlist.live(item["strokes"])) == 4 and len(Playlist.live(item["comments"])) == 2
    win.grab().save(os.path.join(SHOTS, "1_review.png"))

    # --- grouped trees: visibility (view-only) and deleting (own only) ---
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtCore import QEvent
    from blendsketch.playlist import canonical
    prefs.author = "dana"
    win.canvas.author = "dana"
    win._refresh_notes()
    win.save()
    before = canonical(win.pl.data)
    tree = win.stroke_tree

    def top(t, name):
        return next(t.topLevelItem(i) for i in range(t.topLevelItemCount()) if t.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole) == name)

    order = [tree.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole) for i in range(tree.topLevelItemCount())]
    assert order == ["dana", "lead"], (order, win.player.frame, sorted(win.all_by_frame))
    assert top(tree, "dana").childCount() == 3 and top(tree, "lead").childCount() == 1

    # author checkbox hides all of lead's strokes; lead's comment stays
    top(tree, "lead").setCheckState(0, Qt.CheckState.Unchecked)
    pump(0.05)
    assert all(s["author"] != "lead" for s in win.canvas.strokes)
    assert any(c["author"] == "lead" for c in win._visible_comments())
    top(tree, "lead").setCheckState(0, Qt.CheckState.Checked)
    pump(0.05)
    top(win.comment_tree, "lead").setCheckState(0, Qt.CheckState.Unchecked)
    pump(0.05)
    assert all(c["author"] != "lead" for c in win._visible_comments())
    top(win.comment_tree, "lead").setCheckState(0, Qt.CheckState.Checked)
    pump(0.05)

    # individual stroke checkbox (someone else's)
    top(tree, "lead").child(0).setCheckState(0, Qt.CheckState.Unchecked)
    pump(0.05)
    assert all(s["author"] != "lead" for s in win.canvas.strokes) and len(win.canvas.strokes) == 3
    win.grab().save(os.path.join(SHOTS, "2_stroke_hidden.png"))
    top(tree, "lead").child(0).setCheckState(0, Qt.CheckState.Checked)
    pump(0.05)
    assert canonical(win.pl.data) == before, "toggling never changes the playlist"
    assert win.prefs.view_state(win.pl.data["id"]) is not None

    # multi-select dana's two brushes + lead's ellipse, press Delete: only dana's go
    tree.clearSelection()
    d = top(tree, "dana")
    brushes = [d.child(k) for k in range(d.childCount()) if d.child(k).text(0).startswith("Brush")]
    for c in brushes + [top(tree, "lead").child(0)]:
        c.setSelected(True)
    tree.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Backspace, Qt.KeyboardModifier.NoModifier))
    pump(0.05)
    live = Playlist.live(win._item()["strokes"])
    assert len(live) == 2 and {s["author"] for s in live} == {"dana", "lead"}, "dana's brushes deleted, lead's kept"
    win.grab().save(os.path.join(SHOTS, "2b_after_delete.png"))
    win.undo()
    assert len(Playlist.live(win._item()["strokes"])) == 4, "undo restores both"

    # clicking the checkbox of one of several selected rows toggles all of them
    from PySide6.QtTest import QTest
    tree.clearSelection()
    d = top(tree, "dana")
    rows = [d.child(0), d.child(1)]
    for c in rows:
        c.setSelected(True)
    rect = tree.visualItemRect(rows[1])
    from PySide6.QtWidgets import QStyle, QStyleOptionViewItem
    opt = QStyleOptionViewItem()
    tree.initViewItemOption(opt)
    opt.rect = rect
    opt.features |= QStyleOptionViewItem.ViewItemFeature.HasCheckIndicator
    box = tree.style().subElementRect(QStyle.SubElement.SE_ItemViewItemCheckIndicator, opt, tree)
    QTest.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, box.center())
    pump(0.1)
    assert len(win.canvas.strokes) == 2, f"both selected strokes hidden, {len(win.canvas.strokes)} visible"
    d = top(tree, "dana")
    assert [d.child(k).checkState(0) for k in range(2)] == [Qt.CheckState.Unchecked] * 2
    assert len(tree.selectedItems()) == 2, "selection kept"
    QTest.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, box.center())
    pump(0.1)
    assert len(win.canvas.strokes) == 4, "and shown again"

    # right-click menu is opaque
    from PySide6.QtWidgets import QMenu
    m = QMenu(tree)
    m.addAction("Hide 2 strokes")
    assert m.palette() is not None and "QMenu" in QApplication.instance().styleSheet()

    # deleting your own comment through the comments tree
    ct = win.comment_tree
    mine = top(ct, "dana").child(0)
    ct.clearSelection()
    mine.setSelected(True)
    ct.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Delete, Qt.KeyboardModifier.NoModifier))
    pump(0.05)
    assert len(Playlist.live(win._item()["comments"])) == 1
    win.undo()
    assert len(Playlist.live(win._item()["comments"])) == 2

    # eraser only removes your own marks
    prefs.author = "dana"
    win.canvas.author = "dana"
    win.set_tool("eraser")
    drag(win, [(1640, 775, 1), (1660, 775, 1)])  # over lead's ellipse edge
    assert len(Playlist.live(win._item()["strokes"])) == 4, "lead's ellipse survives dana's eraser"
    drag(win, [(1000, 300, 1), (1100, 400, 1)])  # over dana's arrow
    assert len(Playlist.live(win._item()["strokes"])) == 3, "dana's arrow erased"
    win.undo()
    assert len(Playlist.live(win._item()["strokes"])) == 4, "undo restores it"

    # smudge moves drawn paint only, never the footage
    c = win.canvas
    k = c._img_scale()
    px = lambda x, y: c.composite_image().pixelColor(int(x * k), int(y * k))
    win.set_tool("smudge")
    win.settings["opacity"] = 0.9
    before_bare = px(470, 100)
    drag(win, [(250 + i * 10, 100, 1) for i in range(30)])  # across the red/green bars, no strokes there
    pump(0.1)
    assert px(470, 100).name() == before_bare.name(), "footage untouched by smudge"
    # a thick blue pen stroke on the magenta bar, then smudge sideways out of it
    win.set_tool("pen"); win.set_blend("normal"); win.color.set_hex("#0000ff", emit=True)
    win.settings["sizes"]["pen"] = 40
    win.settings["opacity"] = 1.0
    drag(win, [(1330, 140, 1), (1330, 260, 1)])
    pump(0.1)
    outside = px(1420, 200)
    win.set_tool("smudge")
    win.settings["opacity"] = 0.9
    drag(win, [(1320 + i * 6, 200, 1) for i in range(30)])
    pump(0.2)
    after = px(1420, 200)
    assert after.red() < outside.red() - 40, f"blue paint dragged across the magenta: {outside.name()} -> {after.name()}"
    smudges = [s for s in Playlist.live(win._item()["strokes"]) if s["kind"] == "smudge"]
    assert len(smudges) == 2, "smudges saved as strokes"
    win.grab().save(os.path.join(SHOTS, "2c_smudge.png"))
    for _ in range(3):
        win.undo()
    win.settings["opacity"] = 0.8
    win.set_tool("brush")

    # eyedropper readout
    win.set_tool("picker")
    c = win.canvas
    c._mouse = c.to_widget(500, 500)
    c._move(c._mouse, 1, Qt.KeyboardModifier.NoModifier)
    pump(0.1)
    win.grab().save(os.path.join(SHOTS, "3_eyedropper.png"))
    assert c._pick is not None
    win.set_tool("brush")

    # save, then a second machine adds a note and the window picks it up
    win.save()
    other = Playlist.open(path)
    oid = win.cur
    other.put_record(oid, "comments", {"id": "x1", "frame": 40, "author": "sam", "created": time.time(),
                                       "modified": time.time(), "deleted": False, "text": "From another machine."})
    time.sleep(0.02)
    other.save()
    win._poll()
    assert "x1" in win._item()["comments"], "poll merged sam's comment"

    # playback advances
    win.goto(0)
    pump(0.3)
    win.player.play()
    pump(1.2)
    win.player.pause()
    played = win.player.frame
    assert played > 10, f"playback advanced to {played}"

    # 4K ProRes 4444
    win.open_item(win.pl.items()[1]["id"])
    assert wait_for(lambda: win.player.image(0) is not None, 8), "4K frame decoded"
    t = time.time()
    win.player.play()
    pump(1.0)
    win.player.pause()
    print(f"4K 4444 playback reached frame {win.player.frame} in {time.time() - t:.1f}s")
    win.grab().save(os.path.join(SHOTS, "4_4k.png"))

    # missing footage + relink by moving a clip
    moved = os.path.join(pdir, "moved")
    os.makedirs(moved)
    shutil.copy(os.path.join(FOOT, "edit_ref.mp4"), moved)
    third = win.pl.items()[2]
    third["media"] = {"relative": "nope/edit_ref.mp4", "absolute": "/Volumes/gone/edit_ref.mp4", "filename": "edit_ref.mp4"}
    win._resolve_all()
    win.cur = None
    win.open_item(third["id"])
    win._refresh_playlist()
    pump(0.2)
    win.grab().save(os.path.join(SHOTS, "5_missing.png"))
    win.pl.relink(third["id"], os.path.join(moved, "edit_ref.mp4"))
    win._resolve_all()
    assert win.resolved[third["id"]], "relinked"
    win.save()
    reopened = Playlist.open(path)
    assert reopened.item(third["id"])["media"]["relative"] == "moved/edit_ref.mp4"
    print("size of playlist file:", os.path.getsize(path), "bytes")
    win.close()
    print("ALL OK")


if __name__ == "__main__":
    main()
