"""
Ali Noori x Claude — Video Downloader API
Flask + yt-dlp.  Endpoints:
  GET  /api/health
  GET  /api/info?url=...            -> metadata + available qualities
  POST /api/prepare {url,quality}   -> {job}   (starts download on server)
  GET  /api/progress/<job>          -> {status, percent, speed, eta}
  GET  /api/file/<job>              -> the finished file (attachment)
"""
import os
import re
import shutil
import tempfile
import threading
import time
import uuid
from urllib.parse import urlparse

from flask import Flask, jsonify, request, send_file, after_this_request

app = Flask(__name__)

ALLOWED_ORIGIN = os.environ.get("ALLOWED_ORIGIN", "*")  # e.g. https://USER.github.io
COOKIES_FILE = os.environ.get("COOKIES_FILE")  # optional, helps Instagram / age-gated videos
MAX_HEIGHT = 1080
MAX_DURATION = int(os.environ.get("MAX_DURATION", 3 * 3600))  # seconds
JOB_TTL = 15 * 60
MAX_PARALLEL = int(os.environ.get("MAX_PARALLEL", 3))
WORKDIR = os.path.join(tempfile.gettempdir(), "aln_downloads")
os.makedirs(WORKDIR, exist_ok=True)

ALLOWED_HOSTS = (
    "youtube.com", "youtu.be", "youtube-nocookie.com",
    "tiktok.com", "vm.tiktok.com", "vt.tiktok.com",
    "instagram.com", "instagr.am",
)

JOBS = {}
LOCK = threading.Lock()
SEM = threading.Semaphore(MAX_PARALLEL)


@app.after_request
def cors(resp):
    resp.headers["Access-Control-Allow-Origin"] = ALLOWED_ORIGIN
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    resp.headers["Access-Control-Expose-Headers"] = "Content-Disposition, Content-Length"
    return resp


@app.route("/api/<path:_>", methods=["OPTIONS"])
def preflight(_):
    return ("", 204)


def valid_url(u):
    try:
        p = urlparse(u)
    except Exception:
        return False
    if p.scheme not in ("http", "https") or not p.hostname:
        return False
    h = p.hostname.lower()
    return any(h == d or h.endswith("." + d) for d in ALLOWED_HOSTS)


def base_opts():
    o = {"quiet": True, "no_warnings": True, "noplaylist": True, "socket_timeout": 20}
    if COOKIES_FILE and os.path.exists(COOKIES_FILE):
        o["cookiefile"] = COOKIES_FILE
    return o


def platform_of(u):
    h = (urlparse(u).hostname or "").lower()
    if "tiktok" in h:
        return "tiktok"
    if "instagram" in h or "instagr.am" in h:
        return "instagram"
    return "youtube"


def cleanup_loop():
    while True:
        time.sleep(120)
        now = time.time()
        with LOCK:
            dead = [k for k, j in JOBS.items() if now - j["created"] > JOB_TTL]
            for k in dead:
                shutil.rmtree(JOBS[k]["dir"], ignore_errors=True)
                del JOBS[k]


threading.Thread(target=cleanup_loop, daemon=True).start()


@app.get("/api/health")
def health():
    return jsonify(ok=True)


@app.get("/api/info")
def info():
    url = (request.args.get("url") or "").strip()
    if not valid_url(url):
        return jsonify(error="لینک معتبر نیست. فقط یوتیوب، تیک‌تاک و اینستاگرام پشتیبانی می‌شود."), 400
    import yt_dlp
    try:
        with yt_dlp.YoutubeDL(base_opts()) as ydl:
            d = ydl.extract_info(url, download=False)
    except Exception as e:
        return jsonify(error="دریافت اطلاعات ناموفق بود: " + short_err(e)), 422
    if d.get("_type") == "playlist" and d.get("entries"):
        d = next(iter(d["entries"]))
    dur = d.get("duration") or 0
    if dur and dur > MAX_DURATION:
        return jsonify(error="این ویدیو خیلی طولانی است."), 422
    heights = sorted({f["height"] for f in d.get("formats", [])
                      if f.get("height") and f.get("vcodec") not in (None, "none")})
    # offer every standard quality the source can reach (small tolerance for odd sizes)
    qualities = [h for h in (360, 480, 720, 1080) if any(x >= h * 0.9 for x in heights)]
    if not qualities:
        qualities = [360]  # source is smaller than 360p (or heights unknown): "best available <=360"
    return jsonify(
        title=d.get("title"),
        uploader=d.get("uploader") or d.get("channel"),
        duration=dur,
        thumbnail=d.get("thumbnail"),
        platform=platform_of(url),
        qualities=qualities,
        max_height=max(heights) if heights else None,
    )


def short_err(e):
    s = re.sub(r"\x1b\[[0-9;]*m", "", str(e))
    s = s.replace("ERROR: ", "")
    return s[:220]


def run_job(jid, url, quality):
    import yt_dlp
    job = JOBS[jid]

    def hook(d):
        if d["status"] == "downloading":
            tot = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            if tot:
                job["percent"] = round(d.get("downloaded_bytes", 0) * 100 / tot, 1)
            job["speed"] = d.get("speed")
            job["eta"] = d.get("eta")
            job["status"] = "downloading"
        elif d["status"] == "finished":
            job["status"] = "processing"

    opts = base_opts()
    opts.update({
        "outtmpl": os.path.join(job["dir"], "%(title).80B [%(id)s].%(ext)s"),
        "progress_hooks": [hook],
        "restrictfilenames": False,
        "windowsfilenames": True,
        "concurrent_fragment_downloads": 4,
    })
    if quality == "audio":
        opts.update({
            "format": "bestaudio/best",
            "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}],
        })
    else:
        h = int(quality)
        opts.update({
            "format": f"bv*[height<={h}][ext=mp4]+ba[ext=m4a]/bv*[height<={h}]+ba/b[height<={h}]/b",
            "merge_output_format": "mp4",
        })
    with SEM:
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
            files = [f for f in os.listdir(job["dir"]) if not f.endswith((".part", ".ytdl"))]
            if not files:
                raise RuntimeError("فایلی ساخته نشد")
            job["file"] = os.path.join(job["dir"], files[0])
            job["percent"] = 100
            job["status"] = "done"
        except Exception as e:
            job["status"] = "error"
            job["error"] = short_err(e)


@app.post("/api/prepare")
def prepare():
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    quality = str(data.get("quality", "720"))
    if not valid_url(url):
        return jsonify(error="لینک معتبر نیست."), 400
    if quality != "audio" and quality not in ("360", "480", "720", "1080"):
        return jsonify(error="کیفیت نامعتبر است."), 400
    jid = uuid.uuid4().hex
    d = os.path.join(WORKDIR, jid)
    os.makedirs(d, exist_ok=True)
    with LOCK:
        JOBS[jid] = {"status": "queued", "percent": 0, "dir": d, "created": time.time(),
                     "speed": None, "eta": None, "file": None, "error": None}
    threading.Thread(target=run_job, args=(jid, url, quality), daemon=True).start()
    return jsonify(job=jid)


@app.get("/api/progress/<jid>")
def progress(jid):
    j = JOBS.get(jid)
    if not j:
        return jsonify(error="درخواست پیدا نشد یا منقضی شده."), 404
    return jsonify(status=j["status"], percent=j["percent"], speed=j["speed"],
                   eta=j["eta"], error=j["error"])


@app.get("/api/file/<jid>")
def file(jid):
    j = JOBS.get(jid)
    if not j or j["status"] != "done" or not j["file"] or not os.path.exists(j["file"]):
        return jsonify(error="فایل آماده نیست."), 404
    return send_file(j["file"], as_attachment=True, download_name=os.path.basename(j["file"]))


@app.get("/")
def root():
    return jsonify(name="Ali Noori x Claude downloader API", ok=True)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
