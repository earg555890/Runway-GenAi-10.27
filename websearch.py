"""Scholarships and emergency aid found on the open web: shown as "Found online - check before applying", never
as something she qualifies for, never in the forecast.

Provider: Firecrawl's keyless search (POST https://api.firecrawl.dev/v2/search, no Authorization header; Firecrawl
documents free keyless use capped per IP per day; tested Oct 25, 2026). FIRECRAWL_API_KEY in .env, if set, is sent
as a bearer token for higher limits. The search request asks for each result page's text (scrapeOptions markdown) so
there is one request per query.

Only what is written on each page is shown: the title, the site, the link, and an amount and a deadline only if that
exact text appears in the fetched page (string match). The fast model may suggest the amount and deadline; anything
it suggests that isn't on the page becomes "see website". Results are cached in .cache/websearch/; a saved set in
demo_answers/web_scholarships.json (recorded with its date) is used in replay mode and when the live search fails.
"""
import json
import re
import time
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime
from urllib.parse import urlparse

import config

URL = "https://api.firecrawl.dev/v2/search"
TIMEOUT_S = 60
PER_QUERY = 3
CACHE = config.PROJECT_ROOT / ".cache" / "websearch" / "results.json"
SAVED = config.DEMO_ANSWERS_DIR / "web_scholarships.json"
SEE = "see website"
MONEY = re.compile(r"\$\s?\d{1,3}(?:,\d{3})+(?:\.\d{2})?|\$\s?\d+(?:\.\d{2})?")
MONTHS = r"(?:January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|" \
         r"Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\.?"
DEADLINE = re.compile(r"deadline[^\n]{0,40}?(" + MONTHS + r"\s+\d{1,2}(?:,\s*\d{4})?|\d{1,2}/\d{1,2}/\d{2,4})", re.I)
AMOUNT_NEAR = re.compile(r"(?:award|amount|up to|worth|scholarship of|grant of|value)[^\n$]{0,40}(" + MONEY.pattern + ")",
                         re.I)


@dataclass
class WebResult:
    title: str
    organization: str
    url: str
    amount: str                  # exact text from the page, or "see website"
    deadline: str                # exact text from the page, or "see website"
    query: str


def queries(profile=None):
    """Search phrases for her situation (Maya: a sophomore Biology major). No private data: class year and major
    only, from the school profile; generic phrases when there is none (My data mode)."""
    out = ["emergency grants for college students"]
    if profile:
        out.insert(0, f"scholarships for college {profile.class_year}s")
        if profile.major:
            out.append(f"scholarships for {profile.major.lower()} majors")
    else:
        out.insert(0, "scholarships for college students")
    return out


def _post(query, limit=PER_QUERY):
    body = json.dumps({"query": query, "limit": limit, "scrapeOptions": {"formats": [{"type": "markdown"}]},
                       "timeout": TIMEOUT_S * 1000}).encode()
    headers = {"Content-Type": "application/json"}
    if getattr(config, "FIRECRAWL_API_KEY", None):
        headers["Authorization"] = f"Bearer {config.FIRECRAWL_API_KEY}"
    req = urllib.request.Request(URL, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=TIMEOUT_S + 10) as r:
        return json.loads(r.read().decode("utf-8"))


def _site(url, meta):
    return (meta or {}).get("ogSiteName") or (urlparse(url).hostname or "").removeprefix("www.")


def on_page(value, page):
    """True if value appears in the page text (spaces and case ignored)."""
    norm = lambda s: re.sub(r"\s+", " ", s or "").strip().lower()    # noqa: E731
    return bool(value) and norm(value) in norm(page)


def extract(title, url, page, meta=None, query="", llm=None):
    """A WebResult from one fetched page. Amount and deadline: the model's suggestion if one is given and it is on the
    page, else the first one the rules find on the page, else "see website"."""
    amount = next((m.group(1) for m in AMOUNT_NEAR.finditer(page) if _award_like(m.group(1), page[m.end():m.end() + 12])),
                  None)
    deadline = (DEADLINE.search(page) or [None, None])[1] if DEADLINE.search(page) else None
    if len({x.replace(" ", "") for x in MONEY.findall(page)}) > 4:      # a directory of many awards: no single amount
        amount = None
    if len({d.group(1) for d in DEADLINE.finditer(page)}) > 2:          # many deadlines: same
        deadline = None
    if llm is not None:
        try:
            sug = suggest(page, llm)
            amount = sug.get("amount") if on_page(sug.get("amount"), page) else amount
            deadline = sug.get("deadline") if on_page(sug.get("deadline"), page) else deadline
        except Exception:
            pass
    amount = amount if amount and on_page(amount, page) else SEE
    deadline = deadline if deadline and on_page(deadline, page) else SEE
    return WebResult(re.sub(r"\s+", " ", title or url).strip()[:120], _site(url, meta), url, amount.strip(),
                     deadline.strip(), query)


def _award_like(text, after):
    """An award amount, not a program total ("$2 million") or small change: $100 or more, no million/billion."""
    if re.match(r"\s*(?:million|billion|m\b|bn\b|k\b)", after, re.I):
        return False
    try:
        return float(text.replace("$", "").replace(",", "").strip()) >= 100
    except ValueError:
        return False


def suggest(page, llm):
    """The fast model's guess at the main amount and deadline, as JSON. Never trusted: extract() keeps a value only if
    it is written on the page."""
    import llm_client
    res = llm.chat([{"role": "system", "content": "From this scholarship page, copy the award amount and the "
                     "application deadline exactly as written. Reply with JSON only: {\"amount\": \"...\", "
                     "\"deadline\": \"...\"}; use null when the page doesn't say."},
                    {"role": "user", "content": page[:6000]}], thinking=False, model=config.NVIDIA_PLAN_MODEL,
                   timeout=30, retries=0, max_tokens=120)
    data = llm_client.parse_json(res.text)
    return data if isinstance(data, dict) else {}


def search(profile=None, llm=None, post=None):
    """Run the searches and extract the results (deduplicated by link). Returns {"found_at", "provider",
    "results": [...]} ; raises on failure (callers fall back to the cache or the saved set)."""
    post = post or _post
    seen, results = set(), []
    for q in queries(profile):
        data = post(q)
        for item in (data.get("data") or {}).get("web") or []:
            url = item.get("url") or ""
            if not url or url in seen:
                continue
            seen.add(url)
            page = item.get("markdown") or item.get("description") or ""
            results.append(asdict(extract(item.get("title"), url, page, item.get("metadata"), q, llm)))
    return {"found_at": datetime.now().isoformat(timespec="minutes"), "provider": "Firecrawl (keyless search)",
            "results": results}


def save(found, path=None):
    path = path or CACHE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(found, indent=2), encoding="utf-8")


def load(path):
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    except (OSError, ValueError):
        return None


def get(profile=None, mode=None, live=True, llm=None, fresh=False, post=None):
    """What to show: in replay mode the saved set; else the cache (fresh for a day, unless fresh=True), else a live
    search (cached), else the saved set. None if there is nothing. Never raises."""
    mode = (mode or config.ANSWER_MODE).lower()
    if mode == "replay":
        return load(SAVED)
    cached = load(CACHE)
    if cached and _age_h(cached) < 24 and not fresh:
        return cached
    if live:
        try:
            found = search(profile, llm, post)
            if found["results"]:
                save(found)
                return found
        except Exception:
            pass
    return cached or load(SAVED)


def _age_h(found):
    try:
        return (time.time() - datetime.fromisoformat(found["found_at"]).timestamp()) / 3600
    except (KeyError, ValueError):
        return 1e9
