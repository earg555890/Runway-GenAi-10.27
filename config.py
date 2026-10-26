"""All settings in one place, read from .env (real environment variables win).

    import config
    config.NVIDIA_PLAN_MODEL, config.NVIDIA_EXPLAIN_MODEL, config.DEMO_TODAY
    config.require("ZETARIS_PASSWORD")   # raises a clear error if missing
"""
import os
from contextlib import contextmanager
from datetime import date
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


# NVIDIA Nemotron. PLAN = fast model that picks tools (JSON, thinking off);
# EXPLAIN = larger model that writes the answer (thinking on). See rule 9 in CLAUDE.md.
NVIDIA_API_KEY = get("NVIDIA_API_KEY")
NVIDIA_PLAN_MODEL = get("NVIDIA_PLAN_MODEL")
NVIDIA_EXPLAIN_MODEL = get("NVIDIA_EXPLAIN_MODEL")
NVIDIA_BASE_URL = get("NVIDIA_BASE_URL")

# Demo timeline: the fixed "today" the demo runs on (Fall 2026 semester).
DEMO_TODAY = date.fromisoformat(get("DEMO_TODAY") or "2026-10-26")
SEMESTER_START = date(2026, 8, 24)
SEMESTER_END = date(2026, 12, 18)

# Data access (see data_access.py). Paths are relative to the project root.
PROJECT_ROOT = Path(__file__).resolve().parent
DATA_BACKEND = (get("DATA_BACKEND") or "local").lower()          # "local" or "zetaris"
DATA_DIR = PROJECT_ROOT / (get("DATA_DIR") or "data/maya")
# The student's own uploaded bank data (rule 7): gitignored, never committed, never in demo answers.
USER_DATA_DIR = PROJECT_ROOT / (get("USER_DATA_DIR") or "user_data")
DATA_START = date(2026, 7, 1)              # the earliest history question that makes sense (Maya's data starts in July)
BUDGET_HISTORY_START = date(2026, 8, 1)    # budget averages cover this day to today (Maya: Aug-Oct)


@contextmanager
def as_of(today, start, end, history_start):
    """Run the engine on other dates (My data mode: "today" is the last day in her bank file, the end date is hers).
    Restores Maya's demo dates afterwards. One local user, so a module-level swap is enough."""
    names = ("DEMO_TODAY", "SEMESTER_START", "SEMESTER_END", "DATA_START", "BUDGET_HISTORY_START")
    g = globals()
    saved = {k: g[k] for k in names}
    g.update(DEMO_TODAY=today, SEMESTER_START=start, SEMESTER_END=end, DATA_START=history_start,
             BUDGET_HISTORY_START=history_start)
    try:
        yield
    finally:
        g.update(saved)
ZETARIS_CACHE = (get("ZETARIS_CACHE") or "on").lower() in ("on", "true", "1", "yes")
ZETARIS_CACHE_DIR = PROJECT_ROOT / ".cache" / "zetaris"
ZETARIS_CONTAINER = get("ZETARIS_CONTAINER") or "zetaris-driver-1"
ZETARIS_DATA_ROOT = get("ZETARIS_DATA_ROOT") or "/home/zetaris/customer-data/shared/runway"

# Ask Runway answers (agent.py): live = always call the models; cached = reuse a saved answer for the
# same question and what-ifs if there is one (.cache/answers/ first, then demo_answers/); replay = only the
# committed demo answers, typed out (no key needed). Live answers are saved to .cache/answers/;
# pregenerate_answers.py writes demo_answers/.
ANSWER_MODE = (get("ANSWER_MODE") or "cached").lower()
ANSWER_CACHE_DIR = PROJECT_ROOT / ".cache" / "answers"
DEMO_ANSWERS_DIR = PROJECT_ROOT / "demo_answers"
# The check-in's one friendly greeting line, written by the fast model (greeting.py) when a key is set and
# ANSWER_MODE is not replay; "off" always uses the deterministic line. It never blocks the page.
AI_GREETING = (get("AI_GREETING") or "on").lower() != "off"

# Zetaris
ZETARIS_JDBC_URL = get("ZETARIS_JDBC_URL")
ZETARIS_USER = get("ZETARIS_USER")
ZETARIS_PASSWORD = get("ZETARIS_PASSWORD")
ZETARIS_JDBC_JAR = get("ZETARIS_JDBC_JAR")
JAVA_HOME = get("JAVA_HOME")
