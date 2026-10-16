#!/usr/bin/env python3
"""Serves Blendmark from ./local and converts videos the browser can't decode (uses ffmpeg when installed)."""
import json
import os
import shutil
import subprocess
import tempfile
import threading
import uuid
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "local")
FFMPEG, FFPROBE = shutil.which("ffmpeg"), shutil.which("ffprobe")
WORK = tempfile.mkdtemp(prefix="blendmark-")
JOBS = {}


def probe(path):
    info = {"codec": "", "fps": None, "duration": 0.0}
    if not FFPROBE:
        return info
    try:
        out = subprocess.run(
            [FFPROBE, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=codec_name,profile,pix_fmt,r_frame_rate:format=duration",
             "-of", "json", path],
            capture_output=True, text=True, timeout=30).stdout
        d = json.loads(out or "{}")
        s = (d.get("streams") or [{}])[0]
        info["codec"] = " ".join(x for x in (s.get("codec_name"), s.get("profile"), s.get("pix_fmt")) if x)
        num, _, den = (s.get("r_frame_rate") or "").partition("/")
        if num and den and float(den):
            info["fps"] = round(float(num) / float(den), 3)
        info["duration"] = float(d.get("format", {}).get("duration") or 0)
    except Exception:
        pass
    return info


def run_job(job):
    job.update(probe(job["src"]))
    cmd = [FFMPEG, "-hide_banner", "-nostats", "-y", "-i", job["src"],
           "-map", "0:v:0", "-map", "0:a:0?",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
           "-progress", "pipe:1", job["out"]]
    with open(job["log"], "w") as log:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=log, text=True)
        job["proc"] = p
        for line in p.stdout:
            if line.startswith("out_time_us=") and job["duration"]:
                try:
                    job["progress"] = min(0.99, int(line.split("=", 1)[1]) / 1e6 / job["duration"])
                except ValueError:
                    pass
        p.wait()
    try:
        os.remove(job["src"])
    except OSError:
        pass
    if job.get("cancelled"):
        job["state"] = "cancelled"
    elif p.returncode == 0:
        job["state"], job["progress"] = "done", 1.0
    else:
        with open(job["log"]) as f:
            job["error"] = "".join(f.readlines()[-4:]).strip() or "ffmpeg failed"
        job["state"] = "error"


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=ROOT, **kwargs)

    def log_message(self, fmt, *args):
        if "/api/" not in self.path:
            super().log_message(fmt, *args)

    def send_json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/health":
            return self.send_json({"ffmpeg": bool(FFMPEG)})
        if path.startswith("/api/convert/"):
            parts = path.split("/")[3:]
            job = JOBS.get(parts[0])
            if not job:
                return self.send_json({"error": "Unknown conversion"}, 404)
            if len(parts) > 1 and parts[1] == "file":
                if job["state"] != "done":
                    return self.send_json({"error": "Not finished"}, 409)
                self.send_response(200)
                self.send_header("Content-Type", "video/mp4")
                self.send_header("Content-Length", str(os.path.getsize(job["out"])))
                self.end_headers()
                with open(job["out"], "rb") as f:
                    shutil.copyfileobj(f, self.wfile)
                for k in ("out", "log"):
                    try:
                        os.remove(job[k])
                    except OSError:
                        pass
                JOBS.pop(job["id"], None)
                return
            return self.send_json({k: job.get(k) for k in ("state", "progress", "codec", "fps", "error")})
        return super().do_GET()

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/convert":
            if not FFMPEG:
                return self.send_json({"error": "ffmpeg is not installed"}, 503)
            job_id = uuid.uuid4().hex[:12]
            job = {"id": job_id, "state": "running", "progress": 0.0,
                   "src": os.path.join(WORK, job_id + ".src"),
                   "out": os.path.join(WORK, job_id + ".mp4"),
                   "log": os.path.join(WORK, job_id + ".log")}
            remaining = int(self.headers.get("Content-Length") or 0)
            with open(job["src"], "wb") as f:
                while remaining:
                    chunk = self.rfile.read(min(1 << 20, remaining))
                    if not chunk:
                        break
                    f.write(chunk)
                    remaining -= len(chunk)
            JOBS[job_id] = job
            threading.Thread(target=run_job, args=(job,), daemon=True).start()
            return self.send_json({"id": job_id})
        if path.startswith("/api/convert/") and path.endswith("/cancel"):
            job = JOBS.get(path.split("/")[3])
            if job and job.get("proc"):
                job["cancelled"] = True
                job["proc"].kill()
            return self.send_json({"ok": True})
        self.send_error(404)


def main():
    port = int(os.environ.get("PORT", "8080"))
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Blendmark running at http://127.0.0.1:{port}  (Ctrl+C to stop)")
    print("Video conversion: " + ("on (ffmpeg found)" if FFMPEG else "off; install ffmpeg to convert videos browsers can't play"))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        shutil.rmtree(WORK, ignore_errors=True)


if __name__ == "__main__":
    main()
