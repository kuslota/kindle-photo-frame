"""Read-only bundled resources and writable per-user locations."""
from pathlib import Path
import os
import sys


def resource_path(name: str) -> Path:
    # PyInstaller sets __file__ to the module's location inside its bundle.
    return Path(__file__).resolve().parent / name


def user_data_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        configured = Path(os.environ.get("XDG_DATA_HOME", ""))
        base = configured if configured.is_absolute() else Path.home() / ".local" / "share"
    return base / "Kindle Photo Prep"


def default_output_dirs() -> dict[str, Path]:
    folders = {
        "basic_older": "Kindle Basic older",
        "basic_11": "Kindle Basic 11",
        "pw1_2": "Paperwhite 1-2",
        "pw3": "Paperwhite 3",
        "pw4": "Paperwhite 4",
        "voyage": "Voyage",
        "oasis1": "Oasis 1",
        "pw5": "Paperwhite 5",
        "oasis2_3": "Oasis 2-3",
        "scribe1": "Scribe 1",
        "custom": "Custom Kindle",
    }
    return {device: Path.home() / "Kindle Photo Prep Exports" / folder
            for device, folder in folders.items()}
