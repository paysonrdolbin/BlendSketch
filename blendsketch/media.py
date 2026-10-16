"""Video and audio playback built on PyAV (FFmpeg).

Frames are decoded on a background thread straight to the size they'll be shown at,
kept in an LRU cache, and handed to the UI as QImages. ProRes and other intra-only
codecs seek directly to any frame; long-GOP codecs (H.264, HEVC) decode forward from
the nearest keyframe.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from fractions import Fraction

import av
from av.video.reformatter import VideoReformatter
from PySide6.QtCore import QObject, QThread, QTimer, Signal, Qt
from PySide6.QtGui import QImage

try:
    from PySide6.QtMultimedia import QAudioFormat, QAudioSink, QMediaDevices
except ImportError:  # QtMultimedia missing: play silently
    QAudioSink = None

INTRA_ONLY = {"prores", "dnxhd", "mjpeg", "png", "tiff", "v210", "qtrle", "rawvideo", "dpx", "exr", "cfhd", "hap"}


class MediaError(Exception):
    pass


def probe(path: str) -> dict:
    try:
        c = av.open(path)
    except Exception as e:  # av raises a family of FFmpegError subclasses
        raise MediaError(f"Couldn't open {path}: {e}") from e
    try:
        if not c.streams.video:
            raise MediaError("The file has no video stream.")
        vs = c.streams.video[0]
        cc = vs.codec_context
        rate = vs.average_rate or vs.guessed_rate or vs.base_rate or Fraction(24)
        fps = float(rate)
        if vs.duration:
            duration = float(vs.duration * vs.time_base)
        elif c.duration:
            duration = c.duration / av.time_base
        else:
            duration = 0.0
        frames = vs.frames or max(1, round(duration * fps))
        profile = getattr(cc, "profile", None) or ""
        return {
            "width": cc.width,
            "height": cc.height,
            "fps": round(fps, 4),
            "frames": int(frames),
            "duration": round(duration, 4),
            "codec": f"{cc.name} {profile}".strip(),
            "pix_fmt": cc.pix_fmt or "",
            "audio": bool(c.streams.audio),
        }
    finally:
        c.close()


def _colorspace_args(frame) -> dict:
    """Pick the YUV->RGB matrix and range so colors match what a grading suite shows."""
    cs = getattr(frame, "colorspace", None)
    try:
        cs = int(cs) if cs is not None else 2
    except (TypeError, ValueError):
        cs = 2
    if cs == 1:
        src = "ITU709"
    elif cs in (5, 6):
        src = "ITU601"
    else:
        src = "ITU709" if frame.height >= 720 else "ITU601"
    rng = getattr(frame, "color_range", None)
    try:
        rng = int(rng) if rng is not None else 1
    except (TypeError, ValueError):
        rng = 1
    return {"src_colorspace": src, "src_color_range": "JPEG" if rng == 2 else "MPEG", "dst_color_range": "JPEG"}


_local = threading.local()


def frame_to_qimage(frame, w: int, h: int) -> QImage:
    rf = getattr(_local, "reformatter", None)
    if rf is None:
        rf = _local.reformatter = VideoReformatter()
    args = _colorspace_args(frame)
    args["dst_colorspace"] = args["src_colorspace"]
    try:
        rgb = rf.reformat(frame, width=w, height=h, format="bgra", interpolation="BILINEAR", threads=0, **args)
    except (TypeError, ValueError):
        rgb = frame.reformat(width=w, height=h, format="bgra")
    plane = rgb.planes[0]  # rows may be padded, so use the plane's own stride
    img = QImage(memoryview(plane), w, h, plane.line_size, QImage.Format.Format_RGB32)
    return img.copy()


class VideoReader:
    """Frame-index access to one video stream. Not thread-safe; owned by one thread."""

    def __init__(self, path: str):
        self.c = av.open(path)
        self.vs = self.c.streams.video[0]
        self.intra = self.vs.codec_context.name in INTRA_ONLY
        # Frame threading holds back several frames after every seek; slice threading doesn't,
        # which makes scrubbing intra-only footage like ProRes about 10x faster.
        self.vs.thread_type = "SLICE" if self.intra else "AUTO"
        self.tb = self.vs.time_base
        rate = self.vs.average_rate or self.vs.guessed_rate or Fraction(24)
        self.fps = float(rate)
        self.start = self.vs.start_time or 0
        self.gen = None
        self.pos = None

    def close(self):
        self.c.close()

    def index_of(self, f) -> int:
        t = float((f.pts - self.start) * self.tb) if f.pts is not None else (f.time or 0.0)
        return int(round(t * self.fps))

    def _seek(self, index: int):
        pts = self.start + int(round(index / self.fps / self.tb))
        self.c.seek(max(pts, self.start), stream=self.vs, backward=True, any_frame=False)
        self.gen = self.c.decode(self.vs)
        self.pos = None

    def read(self, index: int):
        reach = 1 if self.intra else 48
        if self.gen is None or self.pos is None or index <= self.pos or index > self.pos + reach:
            self._seek(index)
        last = None
        try:
            for f in self.gen:
                i = self.index_of(f)
                self.pos = i
                last = f
                if i >= index:
                    return f
        except av.error.EOFError:
            pass
        self.gen = None
        return last


class FrameCache:
    def __init__(self, budget_mb: int):
        self.lock = threading.Lock()
        self.d: OrderedDict = OrderedDict()
        self.bytes = 0
        self.budget = budget_mb * 1024 * 1024

    def get(self, key):
        with self.lock:
            img = self.d.get(key)
            if img is not None:
                self.d.move_to_end(key)
            return img

    def has(self, key) -> bool:
        with self.lock:
            return key in self.d

    def put(self, key, img: QImage):
        with self.lock:
            if key in self.d:
                return
            self.d[key] = img
            self.bytes += img.sizeInBytes()
            while self.bytes > self.budget and len(self.d) > 1:
                _, old = self.d.popitem(last=False)
                self.bytes -= old.sizeInBytes()

    def frames_at(self, size) -> set[int]:
        with self.lock:
            return {k[0] for k in self.d if k[1] == size}

    def clear(self):
        with self.lock:
            self.d.clear()
            self.bytes = 0


class Decoder(QThread):
    frameReady = Signal(int)
    failed = Signal(str)

    def __init__(self, path: str, frames: int, cache: FrameCache, size: tuple[int, int]):
        super().__init__()
        self.path = path
        self.frames = frames
        self.cache = cache
        self.cond = threading.Condition()
        self.want = None
        self.playhead = 0
        self.playing = False
        self.looping = True
        self.size = size
        self._stop = False

    # called from the UI thread
    def request(self, index: int):
        with self.cond:
            self.want = index
            self.playhead = index
            self.cond.notify()

    def set_playing(self, playing: bool, playhead: int):
        with self.cond:
            self.playing = playing
            self.playhead = playhead
            self.cond.notify()

    def set_playhead(self, index: int):
        with self.cond:
            self.playhead = index
            self.cond.notify()

    def set_size(self, size):
        with self.cond:
            self.size = size
            self.cond.notify()

    def stop(self):
        with self.cond:
            self._stop = True
            self.cond.notify()
        self.wait(3000)

    def _next_missing(self, ph: int, size, playing: bool):
        span = 48 if playing else 16
        for k in range(span):
            i = ph + k
            if i >= self.frames:
                if not (playing and self.looping):
                    return None
                i %= self.frames
            if not self.cache.has((i, size)):
                return i
        return None

    def run(self):
        try:
            reader = VideoReader(self.path)
        except Exception as e:
            self.failed.emit(str(e))
            return
        try:
            while True:
                with self.cond:
                    if self._stop:
                        return
                    want, self.want = self.want, None
                    size, ph, playing = self.size, self.playhead, self.playing
                if want is not None:
                    key = (want, size)
                    if not self.cache.has(key):
                        self._decode(reader, want, size)
                    self.frameReady.emit(want)
                    continue
                target = self._next_missing(ph, size, playing)
                if target is None:
                    with self.cond:
                        if self.want is None and not self._stop:
                            self.cond.wait(0.05)
                    continue
                self._decode(reader, target, size)
                if not playing:
                    self.frameReady.emit(target)
        finally:
            reader.close()

    def _decode(self, reader: VideoReader, index: int, size):
        try:
            f = reader.read(index)
            if f is None:
                return
            self.cache.put((index, size), frame_to_qimage(f, size[0], size[1]))
        except Exception as e:
            reader.gen = None  # force a fresh seek next time
            self.failed.emit(f"Decode error at frame {index + 1}: {e}")


class AudioPlayer(QObject):
    """Plays a file's first audio track from a given time and reports its own clock."""

    RATE = 48000

    def __init__(self, path: str):
        super().__init__()
        self.path = path
        self.ok = QAudioSink is not None
        self.sink = None
        self.dev = None
        self.c = None
        self.gen = None
        self.t0 = 0.0
        self.skip = 0
        self.pending = b""
        self.volume = 1.0
        self.muted = False
        self.feed_timer = QTimer(self)
        self.feed_timer.setInterval(10)
        self.feed_timer.timeout.connect(self._feed)
        if self.ok:
            fmt = QAudioFormat()
            fmt.setSampleRate(self.RATE)
            fmt.setChannelCount(2)
            fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
            dev = QMediaDevices.defaultAudioOutput()
            if dev.isNull():
                self.ok = False
            else:
                self.sink = QAudioSink(dev, fmt, self)
                self.sink.setBufferSize(self.RATE * 4 // 5)  # 200 ms

    def start(self, t: float):
        self.stop()
        if not self.ok:
            return
        try:
            self.c = av.open(self.path)
            ast = self.c.streams.audio[0]
            if t > 0:
                self.c.seek(int(t / ast.time_base), stream=ast, backward=True)
            self.gen = self.c.decode(ast)
            self.resampler = av.AudioResampler(format="s16", layout="stereo", rate=self.RATE)
        except Exception:
            self.ok = False
            return
        self.t0 = t
        self.skip = None
        self.pending = b""
        self._apply_volume()
        self.dev = self.sink.start()
        self._feed()
        self.feed_timer.start()

    def stop(self):
        self.feed_timer.stop()
        if self.sink is not None:
            self.sink.stop()
        if self.c is not None:
            self.c.close()
            self.c = None
        self.gen = None
        self.dev = None

    def set_muted(self, muted: bool):
        self.muted = muted
        self._apply_volume()

    def _apply_volume(self):
        if self.sink is not None:
            self.sink.setVolume(0.0 if self.muted else self.volume)

    def clock(self) -> float | None:
        if not self.ok or self.dev is None:
            return None
        return self.t0 + self.sink.processedUSecs() / 1e6

    def _feed(self):
        if self.dev is None or self.gen is None:
            return
        free = self.sink.bytesFree()
        while len(self.pending) < free:
            try:
                frame = next(self.gen)
            except (StopIteration, av.error.EOFError):
                self.gen = None
                break
            except Exception:
                self.gen = None
                break
            for rf in self.resampler.resample(frame):
                data = rf.to_ndarray().tobytes()
                if self.skip is None:
                    start = frame.time if frame.time is not None else self.t0
                    self.skip = max(0, int((self.t0 - start) * self.RATE)) * 4
                if self.skip:
                    cut = min(self.skip, len(data))
                    data = data[cut:]
                    self.skip -= cut
                self.pending += data
        if self.pending and free:
            n = min(free, len(self.pending)) // 4 * 4
            written = self.dev.write(self.pending[:n])
            if written and written > 0:
                self.pending = self.pending[written:]


class Player(QObject):
    """Owns the decoder, cache and clock for the clip being reviewed."""

    frameChanged = Signal(int)
    imageReady = Signal(int)
    playingChanged = Signal(bool)
    error = Signal(str)

    def __init__(self, cache_mb: int = 2048):
        super().__init__()
        self.cache = FrameCache(cache_mb)
        self.decoder: Decoder | None = None
        self.audio: AudioPlayer | None = None
        self.info = None
        self.path = None
        self.frame = 0
        self.playing = False
        self.size = (16, 16)
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.setInterval(4)
        self.timer.timeout.connect(self._tick)
        self._t_start = 0.0
        self._f_start = 0
        self._pending_size = None
        self.muted = False

    @property
    def frames(self) -> int:
        return self.info["frames"] if self.info else 1

    @property
    def fps(self) -> float:
        return self.info["fps"] if self.info else 24.0

    def load(self, path: str | None, info: dict | None, size=None):
        self.unload()
        self.path, self.info = path, info
        self.frame = 0
        if not path:
            return
        if size:
            self.size = size
        self._pending_size = None
        self.decoder = Decoder(path, info["frames"], self.cache, self.size)
        self.decoder.frameReady.connect(self.imageReady)
        self.decoder.failed.connect(self.error)
        self.decoder.start()
        if info.get("audio"):
            self.audio = AudioPlayer(path)
            self.audio.set_muted(self.muted)

    def unload(self):
        self.pause()
        if self.decoder:
            self.decoder.stop()
            self.decoder.deleteLater()
            self.decoder = None
        if self.audio:
            self.audio.stop()
            self.audio.deleteLater()
            self.audio = None
        self.cache.clear()
        self.path = self.info = None

    def set_size(self, w: int, h: int, force: bool = False):
        """Change the decode resolution. Every change empties the useful cache, so changes are
        held until playback pauses, and changes under 10% are ignored unless more detail is needed."""
        size = (max(16, int(w)), max(16, int(h)))
        if size == self.size:
            return
        if self.playing and not force:
            self._pending_size = size
            return
        cw, ch = self.size
        same_shape = abs(size[0] / size[1] - cw / ch) < 0.01
        if not force and self.info and same_shape:
            if cw * 0.9 <= size[0] <= cw:
                return  # slightly smaller: the frames we have are already sharp enough
            if cw < size[0] <= cw * 1.02:
                return  # a pixel or two larger: invisible when scaled
        self.size = size
        if self.decoder:
            self.decoder.set_size(size)
            if not self.playing:
                self.decoder.request(self.frame)

    def image(self, index: int | None = None) -> QImage | None:
        return self.cache.get((self.frame if index is None else index, self.size))

    def cached_frames(self) -> set[int]:
        return self.cache.frames_at(self.size)

    def seek(self, index: int):
        if not self.info:
            return
        index = max(0, min(self.frames - 1, int(index)))
        if self.playing:
            self._f_start, self._t_start = index, time.monotonic()
            if self.audio:
                self.audio.start(index / self.fps)
        self.frame = index
        if self.decoder:
            self.decoder.request(index)
        self.frameChanged.emit(index)

    def play(self):
        if not self.info or self.frames <= 1 or self.playing:
            return
        self.playing = True
        self._f_start, self._t_start = self.frame, time.monotonic()
        if self.audio:
            self.audio.start(self.frame / self.fps)
        if self.decoder:
            self.decoder.set_playing(True, self.frame)
        self.timer.start()
        self.playingChanged.emit(True)

    def pause(self):
        if not self.playing:
            return
        self.playing = False
        self.timer.stop()
        if self.audio:
            self.audio.stop()
        if self.decoder:
            self.decoder.set_playing(False, self.frame)
            self.decoder.request(self.frame)
        pending, self._pending_size = self._pending_size, None
        if pending:
            self.set_size(*pending)
        self.playingChanged.emit(False)

    def toggle(self):
        self.pause() if self.playing else self.play()

    def set_muted(self, muted: bool):
        self.muted = muted
        if self.audio:
            self.audio.set_muted(muted)

    def _tick(self):
        clock = self.audio.clock() if self.audio else None
        if clock is not None and clock > 0:
            target = int(clock * self.fps + 1e-6)
        else:
            target = self._f_start + int((time.monotonic() - self._t_start) * self.fps + 1e-6)
        if target >= self.frames:
            # loop
            self._f_start, self._t_start = 0, time.monotonic()
            if self.audio:
                self.audio.start(0.0)
            target = 0
            self.frame = -1
        self.decoder.set_playhead(target)
        if target == self.frame:
            return
        # Show the newest decoded frame up to the clock; skip frames if decoding falls behind.
        lo = self.frame + 1 if 0 <= self.frame < target else target
        for i in range(target, lo - 1, -1):
            if self.cache.has((i, self.size)):
                self.frame = i
                self.frameChanged.emit(i)
                return
