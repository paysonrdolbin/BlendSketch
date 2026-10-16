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

from blendsketch.app import App, STYLE  # noqa: E402
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
    app.setStyleSheet(STYLE)
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

    # --- visibility toggles (view-only: the playlist must not change) ---
    from blendsketch.playlist import canonical
    prefs.author = "dana"
    win.canvas.author = "dana"
    win.save()
    before = canonical(win.pl.data)

    # hide all of the lead's strokes: their comment stays
    win._author_toggled("lead", "strokes", False)
    assert all(s["author"] != "lead" for s in win.canvas.strokes)
    assert any(c["author"] == "lead" for c in win._visible_comments()), "lead's comment still shown"
    win._author_toggled("lead", "comments", False)
    assert all(c["author"] != "lead" for c in win._visible_comments())
    win._author_toggled("lead", "comments", True)
    win._author_toggled("lead", "strokes", True)

    # hide one individual stroke of someone else's through the This frame list
    lst = win.frame_panel.list
    lead_row = next(lst.item(i) for i in range(lst.count()) if "lead" in lst.item(i).text())
    lead_row.setCheckState(Qt.CheckState.Unchecked)
    pump(0.1)
    assert all(s["author"] != "lead" for s in win.canvas.strokes), "lead's ellipse hidden"
    assert len(win.canvas.strokes) == 3
    win.grab().save(os.path.join(SHOTS, "2_stroke_hidden.png"))

    # hide one of dana's own strokes; "Clear mine" must leave hidden and others' strokes alone
    arrow = next(s for s in win.canvas.strokes if s["kind"] == "arrow")
    win._stroke_toggled(arrow["id"], False)
    assert canonical(win.pl.data) == before, "toggling never changes the playlist"
    assert win.prefs.view_state(win.pl.data["id"])["strokes"], "hidden state remembered on this machine"
    win.clear_mine()
    live = Playlist.live(win._item()["strokes"])
    assert {s["author"] for s in live} == {"dana", "lead"} and len(live) == 2, "only dana's visible brushes cleared"
    win.undo()
    win._show_all_on_frame()
    assert len(win.canvas.strokes) == 4, "Show all brings both back"

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
