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


# AI provider (llm_client.py). "meterless" (the default and primary): Meterless Runtime served by the Nightshift
# desktop app, OpenAI-compatible, with the NVIDIA key configured inside Nightshift. "nvidia": NVIDIA's API directly
# (only a fallback, used when the Meterless Runtime is unreachable or refuses the token, and only if NVIDIA_API_KEY
# is set).
AI_PROVIDER = (get("AI_PROVIDER") or "meterless").lower()

# Meterless Runtime 0.90.0 contract (docs/agent-ready/add-meterless-provider.md in github.com/Meterless/Meterless).
METERLESS_DEFAULT_URL = "http://127.0.0.1:8088/v1"
METERLESS_APP = "runway"                 # the meterless-app header: a stable lowercase id for this app
METERLESS_TIMEOUT_S = 180                # a model load can take minutes
METERLESS_STATE_DIR = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "ai.meterless.runtime"


def normalize_meterless_url(url):
    """Any pasted runtime address -> <scheme>://<host>/v1: with or without a scheme, /v1, /v1/chat/completions,
    /v1/models or /healthz. Never /v1/v1."""
    url = (url or "").strip().rstrip("/")
    if not url:
        return METERLESS_DEFAULT_URL
    if "://" not in url:
        url = "http://" + url
    scheme, rest = url.split("://", 1)
    host = rest.split("/", 1)[0]
    return f"{scheme}://{host}/v1"


def meterless_token(env_value=None, state_dir=None):
    """The Runtime API key: METERLESS_RUNTIME_TOKEN, else the token the runtime writes to <stateDir>/proxy-token.
    The placeholder rt-local is rejected (None)."""
    token = (env_value if env_value is not None else get("METERLESS_RUNTIME_TOKEN") or "").strip()
    if not token:
        path = Path(state_dir or METERLESS_STATE_DIR) / "proxy-token"
        try:
            token = path.read_text(encoding="utf-8").strip()
        except OSError:
            token = ""
    return None if not token or token == "rt-local" else token


def _detected_url():
    """The address Auto Detect saved (meterless.auto_detect), used when METERLESS_BASE_URL isn't set."""
    try:
        import json
        return json.loads((Path(__file__).resolve().parent / ".cache" / "meterless_runtime.json")
                          .read_text(encoding="utf-8")).get("base_url")
    except (OSError, ValueError, AttributeError):
        return None


METERLESS_BASE_URL = normalize_meterless_url(get("METERLESS_BASE_URL") or _detected_url())
METERLESS_RUNTIME_TOKEN = meterless_token()
# Routing mode for general requests (model ids are routing modes: meterless/auto, fast, deep, ...). PLAN and the
# answers use the concrete Nemotron ids below, read from the runtime's model discovery.
METERLESS_ROUTING_MODE = get("METERLESS_ROUTING_MODE") or "meterless/auto"

# NVIDIA Nemotron models (the same ids in Nightshift's discovery and on NVIDIA's API). PLAN = Lightning, picks
# tools (JSON, thinking off), and writes fast answers (thinking off). Think harder: THINK_MODEL through Nightshift;
# NVIDIA_EXPLAIN_MODEL (Super) only on the direct fallback. See rule 9 in CLAUDE.md.
NVIDIA_API_KEY = get("NVIDIA_API_KEY")
NVIDIA_PLAN_MODEL = get("NVIDIA_PLAN_MODEL") or "nvidia/nemotron-3.5-lightning-30b-a3b"
NVIDIA_EXPLAIN_MODEL = get("NVIDIA_EXPLAIN_MODEL")
NVIDIA_BASE_URL = get("NVIDIA_BASE_URL")
THINK_MODEL = get("THINK_MODEL") or "nvidia/nemotron-3-ultra-550b-a55b"
FAST_EXPLAIN_MODEL = get("FAST_EXPLAIN_MODEL")       # optional: the fast-answer model through Nightshift


def general_model():
    """The model id for general requests (the check-in greeting, the Budget line, web-search extraction): the
    routing mode through Nightshift (meterless/auto), Lightning on the direct provider. PLAN and the answers use the
    explicit Nemotron ids."""
    return METERLESS_ROUTING_MODE if AI_PROVIDER == "meterless" else NVIDIA_PLAN_MODEL


def fast_explain_model(provider=None):
    """The model that writes fast answers (thinking off): FAST_EXPLAIN_MODEL through Nightshift, else Lightning.
    On the direct provider always Lightning."""
    if (provider or AI_PROVIDER) == "nvidia":
        return NVIDIA_PLAN_MODEL
    return FAST_EXPLAIN_MODEL or NVIDIA_PLAN_MODEL


def think_model(provider=None):
    """The Think harder model for this provider."""
    return NVIDIA_EXPLAIN_MODEL if (provider or AI_PROVIDER) == "nvidia" else THINK_MODEL


def ai_configured():
    """True if live answers can be asked for: the Meterless token, or (direct provider or fallback) an NVIDIA key.
    Never in SAMPLE_MODE."""
    if SAMPLE_MODE:
        return False
    return bool(METERLESS_RUNTIME_TOKEN if AI_PROVIDER == "meterless" else NVIDIA_API_KEY) or bool(NVIDIA_API_KEY)

# Demo timeline: the fixed "today" the demo runs on (Fall 2026 semester).
DEMO_TODAY = date.fromisoformat(get("DEMO_TODAY") or "2026-10-26")
SEMESTER_START = date(2026, 8, 24)
SEMESTER_END = date(2026, 12, 18)

# SAMPLE_MODE=true (the judge-friendly default in .env.example): runs from a clean clone with no Zetaris, no
# Nightshift and no keys. Maya's local files and the recorded answers (DATA_BACKEND=local, ANSWER_MODE=replay);
# no AI provider is called. SAMPLE_MODE=false uses DATA_BACKEND and ANSWER_MODE as set. With no .env at all (a fresh
# clone), sample mode is on.
SAMPLE_MODE = (get("SAMPLE_MODE") or ("false" if ENV_FILE.exists() else "true")).lower() in ("true", "1", "yes", "on")

# Data access (see data_access.py). Paths are relative to the project root.
PROJECT_ROOT = Path(__file__).resolve().parent
DATA_BACKEND = "local" if SAMPLE_MODE else (get("DATA_BACKEND") or "local").lower()     # "local" or "zetaris"
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
ANSWER_MODE = "replay" if SAMPLE_MODE else (get("ANSWER_MODE") or "cached").lower()
ANSWER_CACHE_DIR = PROJECT_ROOT / ".cache" / "answers"
# One JSON line per question answered live (agent.write_trace): plan, tools, queries, model calls, timings, checks.
LOGS_DIR = PROJECT_ROOT / "logs"
DEMO_ANSWERS_DIR = PROJECT_ROOT / "demo_answers"
# The check-in's one friendly greeting line, written by the fast model (greeting.py) when a key is set and
# ANSWER_MODE is not replay; "off" always uses the deterministic line. It never blocks the page.
AI_GREETING = (get("AI_GREETING") or "on").lower() != "off"
# Web search for scholarships (websearch.py): Firecrawl keyless search works without a key; a key raises its limits.
FIRECRAWL_API_KEY = get("FIRECRAWL_API_KEY")

# Zetaris
ZETARIS_JDBC_URL = get("ZETARIS_JDBC_URL")
ZETARIS_USER = get("ZETARIS_USER")
ZETARIS_PASSWORD = get("ZETARIS_PASSWORD")
ZETARIS_JDBC_JAR = get("ZETARIS_JDBC_JAR")
JAVA_HOME = get("JAVA_HOME")
