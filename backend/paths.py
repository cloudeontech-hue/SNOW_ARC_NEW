import os
import sys
from pathlib import Path


def get_data_dir() -> Path:
    """Persistent, writable directory for app data (users.json, credentials.json,
    attachments.db).

    - Normal Python process (web deployment, local dev): behaves exactly as
      today — the `data/` folder next to the repo root.
    - Frozen desktop exe (PyInstaller): a `--onefile` build extracts to a fresh
      temp directory on every launch, so anything written relative to the
      script would be lost on exit. Use the OS user-data folder instead so
      data survives between runs.
    """
    if getattr(sys, "frozen", False):
        if sys.platform == "win32":
            base = Path(os.environ.get("APPDATA", Path.home())) / "SnowArc"
        else:
            base = Path.home() / ".snow_arc"
        base.mkdir(parents=True, exist_ok=True)
        return base
    return Path(__file__).resolve().parent.parent / "data"


def get_env_file_path() -> Path:
    """Location of the `.env` file to load.

    - Normal Python process (web deployment, local dev): repo root, same as
      `dotenv.load_dotenv()`'s own default search behavior.
    - Frozen desktop exe: a `--onefile` build's cwd is a temp extraction
      directory (see `get_data_dir` above), not the folder the exe actually
      lives in, so `.env` must be resolved next to the real executable
      instead — deployers configure SMTP/etc. by placing `.env` alongside
      the binary they run, not by baking secrets into the bundle.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / ".env"
    return Path(__file__).resolve().parent.parent / ".env"
