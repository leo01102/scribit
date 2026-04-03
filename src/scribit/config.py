import os
import json
from pathlib import Path
from typing import Dict, Any
import platformdirs
from dotenv import set_key, load_dotenv

# Constants & Paths
APP_NAME = "scribit"
CONFIG_DIR = Path(platformdirs.user_config_dir(APP_NAME))
LOG_DIR = Path(platformdirs.user_log_dir(APP_NAME))
SETTINGS_FILE = CONFIG_DIR / "settings.json"
ENV_FILE = Path(__file__).resolve().parent.parent.parent / ".env"

# Load environment variables from .env if it exists
load_dotenv(ENV_FILE)

# Ensure directories exist
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

# Supported Languages for AssemblyAI Streaming
SUPPORTED_LANGUAGES = [
    ("English", "en"),
    ("Spanish", "es"),
    ("French", "fr"),
    ("German", "de"),
    ("Italian", "it"),
    ("Portuguese", "pt"),
    ("Dutch", "nl"),
    ("Turkish", "tr"),
    ("Russian", "ru"),
    ("Japanese", "ja"),
    ("Chinese", "zh"),
    ("Korean", "ko"),
    ("Hindi", "hi"),
]

def load_settings() -> Dict[str, Any]:
    """Load settings from JSON file with defaults."""
    defaults = {
        "api_key": os.getenv("ASSEMBLYAI_API_KEY", ""),
        "device_index": 2,
        "save_logs": False,
        "language_code": "en"
    }
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r") as f:
                settings = json.load(f)
                return {**defaults, **settings}
        except Exception:
            pass
    return defaults

def save_settings(settings: Dict[str, Any]):
    """Save settings to JSON file."""
    with open(SETTINGS_FILE, "w") as f:
        json.dump(settings, f, indent=4)
    # Also update .env for compatibility
    if settings.get("api_key"):
        set_key(str(ENV_FILE), "ASSEMBLYAI_API_KEY", settings["api_key"])
