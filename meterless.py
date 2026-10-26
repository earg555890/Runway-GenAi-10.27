"""Meterless Runtime checks (the Nightshift desktop app serves it), per the Meterless Runtime 0.90.0 provider contract
(docs/agent-ready/add-meterless-provider.md in github.com/Meterless/Meterless):

    status(base, token)    GET /v1/models decides: 401/403 "unauthorized", 200 with meterless ids "online", else "offline"
    healthz(base)          GET /healthz (only proves the process is up)
    auto_detect()          ports 8088, 8090, 8787, 11434 on 127.0.0.1, localhost, [::1]; saves the first online or
                           unauthorized hit to .cache/meterless_runtime.json
    text_check(model)      a plain text request returns a string, with the routed model from the receipt
    run_checks()           all of the above for Behind the scenes

The token is never logged or returned.
"""
import json
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field

import config

PORTS = (8088, 8090, 8787, 11434)
HOSTS = ("127.0.0.1", "localhost", "[::1]")
SAVED = config.PROJECT_ROOT / ".cache" / "meterless_runtime.json"
PROBE_TIMEOUT_S = 3


@dataclass
class Status:
    base_url: str
    state: str                      # online | unauthorized | offline
    http_status: int | None = None
    routing_modes: list = field(default_factory=list)   # meterless/* ids
    models: list = field(default_factory=list)          # every other id (concrete models, e.g. nvidia/...)
    detail: str = ""


def _get(url, token=None, timeout=PROBE_TIMEOUT_S):
    headers = {"meterless-app": config.METERLESS_APP}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def _error_code(body):
    try:
        return (json.loads(body).get("error") or {}).get("code") or ""
    except (ValueError, AttributeError):
        return ""


def status(base_url=None, token=None, timeout=PROBE_TIMEOUT_S):
    """The runtime's state from GET /v1/models, per the contract."""
    base = config.normalize_meterless_url(base_url or config.METERLESS_BASE_URL)
    try:
        code, body = _get(base + "/models", token, timeout)
    except Exception as exc:                                       # refused, timed out, DNS...
        return Status(base, "offline", None, detail=type(exc).__name__)
    if code in (401, 403):
        return Status(base, "unauthorized", code, detail=_error_code(body) or "unauthorized")
    if code != 200:
        return Status(base, "offline", code, detail=_error_code(body))
    try:
        ids = [m["id"] for m in json.loads(body).get("data", [])]
    except (ValueError, KeyError, TypeError, AttributeError):
        return Status(base, "offline", code, detail="not a model list")
    modes = [i for i in ids if i.startswith("meterless/")]
    if not modes:
        return Status(base, "offline", code, models=ids, detail="no meterless ids")
    return Status(base, "online", code, modes, [i for i in ids if not i.startswith("meterless/")])


def healthz(base_url=None):
    """GET /healthz: (HTTP status or None, body). Only proves the process is up."""
    root = config.normalize_meterless_url(base_url or config.METERLESS_BASE_URL)[:-len("/v1")]
    try:
        return _get(root + "/healthz")
    except Exception as exc:
        return None, type(exc).__name__


def candidates():
    return [f"http://{h}:{p}/v1" for p in PORTS for h in HOSTS]


def auto_detect(token=None, save=True, probe=status):
    """The first runtime that is online or unauthorized; saved for next time. None if nothing answers."""
    for url in candidates():
        st = probe(url, token)
        if st.state in ("online", "unauthorized"):
            if save:
                SAVED.parent.mkdir(parents=True, exist_ok=True)
                SAVED.write_text(json.dumps({"base_url": url, "state": st.state, "found": time.time()}),
                                 encoding="utf-8")
            return st
    return None


def text_check(model, timeout=config.METERLESS_TIMEOUT_S):
    """A plain text request through the runtime: {"ok", "model", "routed_model", "receipt_id", "text", "seconds",
    "error"}."""
    import llm_client
    start = time.perf_counter()
    try:
        client = llm_client.get_client("meterless")
        resp = client.chat.completions.create(model=model, messages=[{"role": "user", "content": "Say OK."}],
                                              max_tokens=llm_client.MIN_MAX_TOKENS, timeout=timeout,
                                              extra_headers={"meterless-scope": "user"},
                                              extra_body={"chat_template_kwargs": {"enable_thinking": False}})
        text = resp.choices[0].message.content
        receipt = llm_client.receipt_of(resp)
        return {"ok": isinstance(text, str) and bool(text.strip()), "model": model,
                "routed_model": receipt.get("routed_model") or resp.model, "receipt_id": receipt.get("receipt_id"),
                "text": (text or "")[:40], "seconds": round(time.perf_counter() - start, 2), "error": None}
    except Exception as exc:
        body = getattr(exc, "body", None)
        code = (body.get("error") or body).get("code") if isinstance(body, dict) else None
        return {"ok": False, "model": model, "routed_model": None, "receipt_id": None, "text": "",
                "seconds": round(time.perf_counter() - start, 2),
                "error": f"{type(exc).__name__}" + (f": {code}" if code else "")}


def run_checks(models=None):
    """Connection, authorization, model discovery and text requests, for Behind the scenes and demo_check.py."""
    health = healthz()
    st = status(token=config.METERLESS_RUNTIME_TOKEN)
    wrong = status(token="runway-wrong-token-check")             # must be "unauthorized", not "offline"
    models = models or [config.METERLESS_ROUTING_MODE, config.NVIDIA_PLAN_MODEL, config.THINK_MODEL]
    texts = [text_check(m) for m in dict.fromkeys(models)] if st.state == "online" else []
    return {"provider": config.AI_PROVIDER, "base_url": st.base_url, "healthz": health[0],
            "status": asdict(st), "wrong_token_state": wrong.state,
            "discovered_nemotron": [m for m in st.models if "nemotron" in m],
            "text_checks": texts, "checked_at": time.time()}
