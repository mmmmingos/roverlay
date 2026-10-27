"""The model and llama.cpp: what's on disk, and downloading what's missing (resumable, size-checked, with progress)."""
import shutil
import tempfile
import threading
import urllib.request
import zipfile
from pathlib import Path

from .config import LLAMA_ASSETS, MODELS, llama_dir, llama_ready, model_path

progress = {}  # name -> {"done": bytes, "total": bytes, "phase": str, "error": str|None, "finished": bool}
_lock = threading.Lock()
_llama_lock = threading.Lock()  # both models share one llama.cpp: only one download of it at a time


def status(name):
    p = progress.get(name)
    if p and not p.get("finished"):
        total = p.get("total") or 1
        return {"label": MODELS[name]["label"], "size_gb": MODELS[name]["size_gb"], "status": "downloading",
                "pct": round(100 * p["done"] / total), "done_mb": round(p["done"] / 1e6), "total_mb": round(total / 1e6),
                "phase": p.get("phase"), "error": p.get("error")}
    ready = model_path(name).exists() and llama_ready()
    return {"label": MODELS[name]["label"], "size_gb": MODELS[name]["size_gb"],
            "status": "ready" if ready else "missing", "error": (p or {}).get("error")}


def _remote_size(url):
    req = urllib.request.Request(url, method="HEAD")
    with urllib.request.urlopen(req, timeout=60) as r:
        return int(r.headers.get("Content-Length") or 0)


def _fetch(url, dest, on_bytes):
    """Download url to dest, resuming a partial .part file. The file is only renamed into place once its size
    matches what the server said: a connection that closed early used to leave a truncated model marked ready."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    expected = _remote_size(url)
    have = part.stat().st_size if part.exists() else 0
    if expected and have >= expected:  # finished last time, only the rename was missed
        part.replace(dest)
        return
    req = urllib.request.Request(url, headers={"Range": f"bytes={have}-"} if have else {})
    with urllib.request.urlopen(req, timeout=60) as r:
        if have and r.status != 206:  # the server ignored the range: start over
            have = 0
        mode = "ab" if have else "wb"
        with open(part, mode) as f:
            done = have
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                on_bytes(done, expected or done)
    if expected and part.stat().st_size != expected:
        raise IOError(f"download ended at {part.stat().st_size} of {expected} bytes")
    part.replace(dest)


def _ensure_llama(on_bytes):
    with _llama_lock:
        if llama_ready():
            return
        target = llama_dir()
        staging = Path(tempfile.mkdtemp(prefix="roverlay-llama-", dir=target.parent if target.parent.exists() else None))
        try:
            for url in LLAMA_ASSETS:
                z = target.parent / url.rsplit("/", 1)[1]
                _fetch(url, z, on_bytes)
                with zipfile.ZipFile(z) as zf:
                    zf.extractall(staging)
            # Unpack somewhere else first, then swap it in whole, and mark it complete last.
            if target.exists():
                shutil.rmtree(target)
            shutil.move(str(staging), str(target))
            (target / ".complete").write_text("ok", encoding="utf-8")
            for url in LLAMA_ASSETS:
                (target.parent / url.rsplit("/", 1)[1]).unlink(missing_ok=True)
        finally:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)


def download(name, on_done=None):
    """Start downloading a model (and llama.cpp if missing) in the background."""
    with _lock:
        if progress.get(name) and not progress[name].get("finished"):
            return
        progress[name] = {"done": 0, "total": 0, "phase": "llama.cpp", "error": None, "finished": False}

    def run():
        p = progress[name]

        def on_bytes(done, total):
            p["done"], p["total"] = done, total
        try:
            model_path(name).parent.mkdir(parents=True, exist_ok=True)
            _ensure_llama(on_bytes)
            if not model_path(name).exists():
                p.update(phase="model", done=0, total=0)
                _fetch(MODELS[name]["url"], model_path(name), on_bytes)
            p["finished"] = True
            if on_done:
                on_done(name)
        except Exception as e:  # any failure must reach the page, or it shows "downloading" forever
            p["error"] = f"Download stopped ({type(e).__name__}). Click Download to resume."
            p["finished"] = True
    threading.Thread(target=run, daemon=True).start()
