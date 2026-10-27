"""Where Roverlay keeps things, and the user's settings.

- Settings: %APPDATA%\\Roverlay\\settings.json
- Models and llama.cpp: %LOCALAPPDATA%\\Roverlay\\models
- Voice memory: Documents\\Roverlay\\voice (plain text, meant to be opened and read)
"""
import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

VERSION = "0.1.0"
APP_DIR = Path(os.environ.get("APPDATA", Path.home())) / "Roverlay"
DATA_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Roverlay"
MODELS_DIR = DATA_DIR / "models"
LLAMA_DIR = MODELS_DIR / "llama.cpp"
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
# Models downloaded before Roverlay existed (the prototype kept them here); used in place if present.
LEGACY_MODELS_DIR = Path.home() / "models"


@dataclass
class Settings:
    hotkey: str = "Ctrl+Shift+Space"
    model: str = "9b"
    memory_enabled: bool = True
    launch_at_startup: bool = False
    paused: bool = False
    my_names: list = field(default_factory=list)

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


def model_path(name):
    """Where a model's file is, preferring an existing download over a new one."""
    file = MODELS[name]["file"]
    for folder in (MODELS_DIR, LEGACY_MODELS_DIR):
        if (folder / file).exists():
            return folder / file
    return MODELS_DIR / file


def llama_server():
    for folder in (LLAMA_DIR, LEGACY_MODELS_DIR / "llama.cpp"):
        exe = folder / "llama-server.exe"
        if exe.exists():
            return exe
    return LLAMA_DIR / "llama-server.exe"
