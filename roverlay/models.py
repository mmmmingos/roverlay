"""The model and llama.cpp: what's on disk, and downloading what's missing (resumable, with progress)."""
import threading
import urllib.request
import zipfile

from .config import LLAMA_ASSETS, LLAMA_DIR, MODELS, MODELS_DIR, llama_server, model_path

progress = {}  # name -> {"done": bytes, "total": bytes, "error": str|None}
_lock = threading.Lock()


def status(name):
    p = progress.get(name)
    if p and not p.get("finished"):
        total = p.get("total") or 1
        return {"label": MODELS[name]["label"], "size_gb": MODELS[name]["size_gb"], "status": "downloading",
                "pct": round(100 * p["done"] / total), "done_mb": round(p["done"] / 1e6), "total_mb": round(total / 1e6),
                "error": p.get("error")}
    ready = model_path(name).exists() and llama_server().exists()
    return {"label": MODELS[name]["label"], "size_gb": MODELS[name]["size_gb"],
            "status": "ready" if ready else "missing", "error": (p or {}).get("error")}


def _fetch(url, dest, on_bytes):
    """Download url to dest, resuming a partial .part file. on_bytes(done, total) reports progress."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    have = part.stat().st_size if part.exists() else 0
    req = urllib.request.Request(url, headers={"Range": f"bytes={have}-"} if have else {})
    with urllib.request.urlopen(req, timeout=60) as r:
        if have and r.status != 206:  # the server ignored the range: start over
            have = 0
        total = have + int(r.headers.get("Content-Length") or 0)
        with open(part, "ab" if have else "wb") as f:
            done = have
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                on_bytes(done, total)
    part.replace(dest)


def _ensure_llama():
    if llama_server().exists():
        return
    LLAMA_DIR.mkdir(parents=True, exist_ok=True)
    for url in LLAMA_ASSETS:
        z = LLAMA_DIR / url.rsplit("/", 1)[1]
        _fetch(url, z, lambda d, t: None)
        with zipfile.ZipFile(z) as zf:
            zf.extractall(LLAMA_DIR)
        z.unlink()


def download(name, on_done=None):
    """Start downloading a model (and llama.cpp if missing) in the background."""
    with _lock:
        if progress.get(name) and not progress[name].get("finished"):
            return
        progress[name] = {"done": 0, "total": 0, "error": None}

    def run():
        p = progress[name]
        try:
            _ensure_llama()
            if not model_path(name).exists():
                def on_bytes(done, total):
                    p["done"], p["total"] = done, total
                _fetch(MODELS[name]["url"], MODELS_DIR / MODELS[name]["file"], on_bytes)
            p["finished"] = True
            if on_done:
                on_done(name)
        except Exception as e:
            p["error"] = f"Download stopped: {type(e).__name__}. Click Download to resume."
            p["finished"] = True
    threading.Thread(target=run, daemon=True).start()
