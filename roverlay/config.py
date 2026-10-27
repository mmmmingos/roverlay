"""Where Roverlay keeps things, and the user's settings.

- Settings: %APPDATA%\\Roverlay\\settings.json
- Models and llama.cpp: %LOCALAPPDATA%\\Roverlay\\models, or the "models_dir" in settings.json
- Voice memory: Documents\\Roverlay\\voice (plain text, meant to be opened and read)
"""
import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

VERSION = "0.1.0"
APP_DIR = Path(os.environ.get("APPDATA", Path.home())) / "Roverlay"
DATA_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Roverlay"
DEFAULT_MODELS_DIR = DATA_DIR / "models"
MEMORY_DIR = Path.home() / "Documents" / "Roverlay" / "voice"
SETTINGS_FILE = APP_DIR / "settings.json"

# Pinned so every install gets the same files. Sizes are what Hugging Face and GitHub reported on 2026-10-27.
LLAMA_RELEASE = "b11899"
LLAMA_ASSETS = [
    f"https://github.com/ggml-org/llama.cpp/releases/download/{LLAMA_RELEASE}/llama-{LLAMA_RELEASE}-bin-win-cuda-12.4-x64.zip",
    f"https://github.com/ggml-org/llama.cpp/releases/download/{LLAMA_RELEASE}/cudart-llama-bin-win-cuda-12.4-x64.zip",
]
MODELS = {
    "9b": {"label": "Qwen3.5 9B", "file": "Qwen3.5-9B-Q4_K_M.gguf", "size_gb": 5.7,
           "url": "https://huggingface.co/unsloth/Qwen3.5-9B-GGUF/resolve/main/Qwen3.5-9B-Q4_K_M.gguf"},
    "4b": {"label": "Qwen3.5 4B", "file": "Qwen3.5-4B-Q4_K_M.gguf", "size_gb": 2.7,
           "url": "https://huggingface.co/unsloth/Qwen3.5-4B-GGUF/resolve/main/Qwen3.5-4B-Q4_K_M.gguf"},
}


@dataclass
class Settings:
    hotkey: str = "Ctrl+Shift+Space"
    model: str = "9b"
    memory_enabled: bool = True
    launch_at_startup: bool = False
    paused: bool = False
    my_names: list = field(default_factory=list)
    models_dir: str = ""  # optional: models already downloaded somewhere else (no Settings control; edit the file)

    @classmethod
    def load(cls):
        try:
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        s = cls(**known)
        if s.model not in MODELS:
            s.model = "9b"
        return s

    def save(self):
        APP_DIR.mkdir(parents=True, exist_ok=True)
        tmp = SETTINGS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        tmp.replace(SETTINGS_FILE)


def models_dir():
    custom = Settings.load().models_dir
    return Path(custom) if custom else DEFAULT_MODELS_DIR


def llama_dir():
    return models_dir() / "llama.cpp"


def model_path(name):
    return models_dir() / MODELS[name]["file"]


def llama_ready():
    """llama.cpp is usable only once its download finished unpacking: a half-extracted folder has the exe without
    its DLLs and would otherwise never be fetched again. A folder of llama.cpp the user put there themselves (no
    marker, but the exe and a CUDA runtime present) also counts."""
    d = llama_dir()
    return (d / "llama-server.exe").exists() and ((d / ".complete").exists() or any(d.glob("cudart64_*.dll")))


def llama_server():
    return llama_dir() / "llama-server.exe"
