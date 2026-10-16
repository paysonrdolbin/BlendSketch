# BlendSketch

Frame-accurate review for footage, with drawing tools that blend (Multiply, Screen, Overlay and ten more) and shared playlist files.

- **Plays ProRes directly.** FFmpeg (through PyAV) is built in, so ProRes 422/4444, DNxHR, H.264 (including 10-bit and 4:2:2), HEVC, image sequences' single frames and most other formats play with no proxies or conversion.
- **Playlists are files.** A `.bsplaylist` holds the clip list plus every stroke and comment. Footage is referenced by path, not copied in, so the file stays small (kilobytes).
- **Shared, merged notes.** Several people can have the same playlist open. Each save merges with what's on disk, and the app picks up others' notes every couple of seconds. Every note carries its author; the Authors panel shows or hides each person's notes.

## Running from source

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python run.py
```

Check that a file decodes (no window opens):

```bash
.venv/bin/python run.py --check /path/to/clip.mov
```

The packaged app takes the same flag, e.g. `BlendSketch.app/Contents/MacOS/BlendSketch --check clip.mov`.

## Building the app

PyInstaller builds for the OS it runs on.

```bash
.venv/bin/pip install pyinstaller
QT_QPA_PLATFORM=offscreen .venv/bin/python packaging/make_icons.py   # once
.venv/bin/pyinstaller --noconfirm BlendSketch.spec
```

Output: `dist/BlendSketch.app` on macOS, `dist/BlendSketch/BlendSketch.exe` on Windows, `dist/BlendSketch/BlendSketch` on Linux.
`.github/workflows/build.yml` builds all three on GitHub Actions (run it from the Actions tab, or push a `v*` tag).

The macOS build is ad-hoc signed, not notarized. On another Mac, the first launch needs right-click ▸ Open (or `xattr -dr com.apple.quarantine BlendSketch.app`).

## How footage is found

Each clip stores a path relative to the playlist file and the absolute path it was added from. When a playlist opens, BlendSketch tries, in order:

1. the relative path (works whenever footage and playlist sit on the same server, whatever it's mounted as),
2. the absolute path,
3. the absolute path rewritten through **Preferences ▸ Path mappings**, for servers mounted at different roots, e.g. `/Volumes/prod = P:/ = /mnt/prod`.

Clips that still can't be found show as **Missing**. Double-click one (or File ▸ Relink Footage) and pick the file; BlendSketch then looks in that folder and the folder above it for the other missing clips by name and offers to relink them too. Relinking updates the playlist for everyone.

## Shared editing

Every stroke, comment and clip is a record with an id, an author and a modified time. Deleting writes a tombstone, so a merge can't bring a deleted note back. When two versions of the same record meet, the newer one wins. Saving is automatic (under a second after each change) and atomic (write to a temp file, then rename), so a reader never sees a half-written file.

Your name comes from Preferences (it defaults to your login name).

The inspector lists the current frame's **Strokes** and **Comments**, grouped by person:

```
☑ dana (you)   3
    ☑ Brush   Multiply 80%
    ☑ Arrow   Normal 80%
☑ lead   1
    ☐ Ellipse   Normal 80%
```

- A person's checkbox shows or hides everything they've made, on every frame, including notes they add later. The item checkboxes underneath show or hide single notes. Hiding is saved per playlist on your machine and never changes the file, so you can hide anyone's notes.
- Select notes (Shift- or ⌘/Ctrl-click for several) and press Delete/Backspace, or right-click ▸ Delete. Only your own notes are deleted; other people's are skipped and can only be hidden. ⌘/Ctrl+Z undoes a delete. The eraser and Edit ▸ Clear My Marks follow the same rule.

## Shortcuts

| Key | Action | Key | Action |
| --- | --- | --- | --- |
| P B L A R O T E | Pen, brush, line, arrow, rect, ellipse, text, eraser | Space | Play / pause |
| I, or hold Alt/Option | Eyedropper | ← → | Previous / next frame |
| 1 2 3 | Normal, Multiply, Screen | Shift+← → | Previous / next noted frame |
| [ ] | Brush size | ↑ ↓ | Previous / next clip |
| H | Show / hide marks | Home / End | First / last frame |
| F, ⌘/Ctrl+1 | Fit, actual pixels | M | Mute |
| ⌘/Ctrl+Z, ⇧⌘/Ctrl+Shift+Z | Undo, redo | ⌘/Ctrl+E | Export frame with marks |

Scroll wheel or pinch zooms; trackpad scroll or middle-drag pans. Shift constrains lines to 45° and shapes to squares and circles.

## Layout

```
blendsketch/
  app.py        entry point, theme, --check
  window.py     main window: playlist, undo, autosave, merge polling, relinking, export
  canvas.py     viewer: zoom/pan, tablet pressure, live strokes, eraser, text, eyedropper loupe
  strokes.py    stroke rendering, blend-mode compositing, hit testing
  media.py      PyAV decoding thread, frame cache, audio playback and clock
  playlist.py   file format, merging, path resolution
  timeline.py   scrub bar
  widgets.py    blend, color (RGB/HSV/HSL/CMYK sliders, recent colors) and brush controls
  panels.py     playlist, authors, this frame, comments, preferences
tests/          merge tests and an offscreen end-to-end test
prototype/      the original web version, for reference
```
