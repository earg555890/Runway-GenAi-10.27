"""All settings in one place, read from .env (real environment variables win).

    import config
    config.NVIDIA_MODEL
    config.require("ZETARIS_PASSWORD")   # raises a clear error if missing
"""
import os
from pathlib import Path

ENV_FILE = Path(__file__).resolve().parent / ".env"


def _load_env_file(path):
    """Parse KEY=VALUE lines into os.environ without overriding values already set."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key, value)


_load_env_file(ENV_FILE)


class MissingSetting(RuntimeError):
    pass


def get(name):
    """Return a setting, or None if it is missing or empty."""
    return os.environ.get(name) or None


def require(name):
    """Return a setting, or raise a clear error naming the missing variable."""
    value = get(name)
    if value is None:
        raise MissingSetting(
            f"Setting {name} is missing. Add it to {ENV_FILE} (see .env.example)."
        )
    return value


# NVIDIA Nemotron
NVIDIA_API_KEY = get("NVIDIA_API_KEY")
NVIDIA_MODEL = get("NVIDIA_MODEL")
NVIDIA_BASE_URL = get("NVIDIA_BASE_URL")

# Zetaris
ZETARIS_JDBC_URL = get("ZETARIS_JDBC_URL")
ZETARIS_USER = get("ZETARIS_USER")
ZETARIS_PASSWORD = get("ZETARIS_PASSWORD")
ZETARIS_JDBC_JAR = get("ZETARIS_JDBC_JAR")
JAVA_HOME = get("JAVA_HOME")
