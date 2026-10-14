"""Local settings: NCBI contact email, API key, and repo paths.

Settings are read from a `.env` file in the repo root (copy `.env.example`
to `.env` and fill it in). `.env` is git-ignored, so your key stays local.
A real environment variable with the same name overrides the file.
"""

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = REPO_ROOT / ".env"
TOPICS_FILE = REPO_ROOT / "topics.toml"
DATA_DIR = REPO_ROOT / "data"


def read_env_file(path=ENV_FILE):
    """KEY=VALUE pairs from a .env file. Blank lines and # comments are
    ignored, and matching quotes around a value are stripped."""
    values = {}
    path = Path(path)
    if not path.is_file():      # missing, or a folder by mistake: no settings
        return values
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def get(name, default="", path=ENV_FILE):
    """Environment variable if set, else the .env value, else default."""
    if os.environ.get(name):
        return os.environ[name]
    return read_env_file(path).get(name, default)
