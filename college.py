"""Her college ("My college"), jobs near campus found online, and her school's published costs, kept on this computer
only and never committed.

    data = college.load("maya")              # {"college": {...} | {} (removed) | None (default), "jobs": [...], ...}
    c = college.current(data, "maya")        # her college, else Maya's demo school, else None (My data mode)
    problem = college.set_college(data, "Example University", "Champaign, IL", "off", "5")
    college.save("maya", data)
    engine.Scenario(**college.scenario_part(data))          # jobs she added and costs she confirmed

Maya (the demo) keeps hers in .cache/college.json; My data mode keeps hers in user_data/college.json (rule 7). Both
folders are gitignored.

Online results (jobs, costs) use the same web search as the scholarships (websearch.py: Firecrawl keyless search)
and the same guardrails: only what is written on each page is shown. Pay, hours, place, amounts and the academic
year appear only if that exact text is on the page; otherwise "see website". Runway never says she qualifies, never
applies for her, and nothing found online enters her forecast until she types or confirms the numbers herself.
"""
import json
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse

import config
import engine
import websearch

FOLDER = None                    # tests point this at a temp folder
SEE = websearch.SEE
DEMO = {"name": "State University", "city": "", "housing": "", "travel": "", "demo": True}   # from her job record
HOUSING = {"": "Not set", "on": "On campus", "off": "Off campus"}
TRAVEL = {"": "Not set", "campus": "On campus only", "walk": "Walking distance", "5": "Within 5 miles",
          "10": "Within 10 miles", "25": "Within 25 miles"}
MAX_NAME, MAX_CITY = 80, 60
PAY = re.compile(r"\$\s?\d{1,3}(?:\.\d{2})?(?:\s?(?:-|–|to)\s?\$?\s?\d{1,3}(?:\.\d{2})?)?\s?(?:/|an?\s|per\s)\s?(?:hour|hr)\b",
                 re.I)
HOURS = re.compile(r"\b\d{1,2}(?:\s?(?:-|–|to)\s?\d{1,2})?\s?(?:hours?|hrs?)\s?(?:/|per|a)\s?(?:week|wk)\b", re.I)
YEAR = re.compile(r"\b(20\d\d)\s?[-–/]\s?(?:20)?(\d\d)\b")
COST_WORDS = (("tuition", "Tuition"), ("fee", "Fees"), ("housing", "Housing"), ("room", "Housing"),
              ("meal", "Meal plan"), ("board", "Meal plan"), ("food", "Food"))


# --- storage ---------------------------------------------------------------------------------------------------
def path(mode):
    if FOLDER is not None:
        return FOLDER / f"college-{mode}.json"
    return (config.USER_DATA_DIR if mode == "mine" else config.PROJECT_ROOT / ".cache") / "college.json"


def empty():
    return {"college": None, "jobs": [], "estimates": [], "next": 1}


def load(mode):
    try:
        return {**empty(), **json.loads(path(mode).read_text(encoding="utf-8"))}
    except (OSError, ValueError):
        return empty()


def save(mode, data):
    p = path(mode)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=1), encoding="utf-8")


def current(data, mode):
    """Her college: what she set, else Maya's demo school (Maya mode), else None. Removed: None."""
    c = data.get("college")
    if c is None:
        return dict(DEMO) if mode == "maya" else None
    return c or None


def set_college(data, name, city="", housing="", travel=""):
    """Save her college. Returns None, or a friendly message (and nothing is saved)."""
    name, city = " ".join(str(name or "").split()), " ".join(str(city or "").split())
    if not name:
        return "Type your college's name."
    if len(name) > MAX_NAME or len(city) > MAX_CITY:
        return "That name is too long."
    if housing not in HOUSING or travel not in TRAVEL:
        return "Pick one of the choices."
    data["college"] = {"name": name, "city": city, "housing": housing, "travel": travel, "demo": False}
    return None


def remove_college(data):
    data["college"] = {}


def reset(data):
    """Back to the start: Maya's demo school (or nothing in My data mode), no jobs, no estimates."""
    data.clear()
    data.update(empty())


def memory_text(c):
    """"You attend Example University in Champaign, IL. You live off campus. You can travel within 5 miles for work.\""""
    s = f"You attend {c['name']}" + (f" in {c['city']}" if c.get("city") else "") + "."
    if c.get("housing"):
        s += f" You live {HOUSING[c['housing']].lower()}."
    if c.get("travel"):
        s += {"campus": " You want work on campus.", "walk": " You can walk to work."}.get(
            c["travel"], f" You can travel within {c['travel']} miles for work.")
    return s


# --- jobs she added to her plan, and the costs she confirmed -------------------------------------------------------
def job_to_dict(j):
    return {"hourly_rate": str(j.hourly_rate), "hours_per_week": str(j.hours_per_week), "start": j.start.isoformat(),
            "schedule": j.schedule, "withholding_pct": str(j.withholding_pct), "name": j.name}


def job_from_dict(d):
    return engine.NewJob(Decimal(d["hourly_rate"]), Decimal(d["hours_per_week"]), date.fromisoformat(d["start"]),
                         d["schedule"], Decimal(d["withholding_pct"]), d["name"])


def jobs(data):
    out = []
    for d in data.get("jobs") or []:
        try:
            out.append(job_from_dict(d))
        except (KeyError, ValueError, InvalidOperation):
            pass
    return tuple(out)


def add_job(data, job):
    if job_to_dict(job) not in data["jobs"]:
        data["jobs"].append(job_to_dict(job))


def remove_job(data, i):
    if 0 <= i < len(data["jobs"]):
        data["jobs"].pop(i)


def estimate_to_dict(e):
    return {"label": e.label, "amount": str(e.amount), "due": e.due.isoformat(), "school": e.school, "year": e.year,
            "url": e.url}


def estimates(data):
    out = []
    for d in data.get("estimates") or []:
        try:
            out.append(engine.CostEstimate(d["label"], Decimal(d["amount"]), date.fromisoformat(d["due"]),
                                           d.get("school", ""), d.get("year", ""), d.get("url", "")))
        except (KeyError, ValueError, InvalidOperation):
            pass
    return tuple(out)


def set_estimates(data, items):
    data["estimates"] = [estimate_to_dict(e) for e in items]


def scenario_part(data):
    """engine.Scenario fields: nothing at all until she adds a job or confirms estimates (Maya's default state
    stays exactly the same)."""
    part = {}
    if jobs(data):
        part["new_jobs"] = jobs(data)
    if estimates(data):
        part["cost_estimates"] = estimates(data)
    return part


# --- jobs near campus, found online ---------------------------------------------------------------------------------
def job_queries(c):
    """Search phrases from her college, city and how far she can travel. No private data."""
    where = " ".join(x for x in (c["name"], c.get("city", "")) if x)
    out = [f"student jobs on campus {where}"]
    if c.get("travel") != "campus":
        miles = f" within {c['travel']} miles" if c.get("travel") in ("5", "10", "25") else ""
        out.append(f"part-time jobs for college students near {where}{miles}")
    return out


def _one(pattern, page):
    """The text the pattern finds on the page when it finds exactly one distinct value (a listing page with many
    jobs has many pays: then "see website")."""
    found = {re.sub(r"\s+", " ", m.group(0)).strip() for m in pattern.finditer(page or "")}
    return found.pop() if len(found) == 1 else SEE


def parse_job(item, c, query=""):
    """One result: title, employer (the site), place (her city, only if the page says it), link, pay and hours
    (only if the page states exactly one)."""
    url = item.get("url") or ""
    page = item.get("markdown") or item.get("description") or ""
    city = (c or {}).get("city", "")
    return {"title": re.sub(r"\s+", " ", item.get("title") or url).strip()[:120],
            "employer": websearch._site(url, item.get("metadata")), "url": url,
            "place": city if city and websearch.on_page(city.split(",")[0], page) else SEE,
            "pay": _one(PAY, page), "hours": _one(HOURS, page), "query": query}


def search_jobs(c, post=None, limit=4):
    """Run the job searches. Returns {"found_at", "provider", "college", "results"}; raises on failure."""
    post = post or websearch._post
    seen, results = set(), []
    for q in job_queries(c):
        data = post(q, limit)
        for item in (data.get("data") or {}).get("web") or []:
            url = item.get("url") or ""
            if url and url not in seen:
                seen.add(url)
                results.append(parse_job(item, c, q))
    return {"found_at": datetime.now().isoformat(timespec="minutes"), "provider": "Firecrawl (keyless search)",
            "college": c["name"], "results": results}


# --- the school's published costs, found online ---------------------------------------------------------------------
def cost_query(c):
    return " ".join(x for x in (c["name"], c.get("city", ""), "cost of attendance tuition fees housing") if x)


def academic_year(page):
    """The newest academic year written on the page ("2026-2027" / "2026-27"), as written, or ""."""
    best = None
    for m in YEAR.finditer(page or ""):
        a, b = int(m.group(1)), int(m.group(2))
        if b == (a + 1) % 100 and (best is None or a > best[0]):
            best = (a, m.group(0))
    return best[1] if best else ""


def _money(text):
    m = websearch.MONEY.search(text)
    if not m:
        return None, None
    try:
        return m.group(0).replace(" ", ""), Decimal(m.group(0).replace("$", "").replace(",", "").strip())
    except InvalidOperation:
        return None, None


def parse_costs(item):
    """Cost lines from one page: each line that names tuition, fees, housing, meals or food and states a dollar
    amount. Kept as written: the line, its section heading, and the first amount on it."""
    page = item.get("markdown") or ""
    section, rows = "", []
    for raw in page.splitlines():
        line = raw.strip()
        if line.startswith("#") or (line.startswith("**") and line.endswith("**")):
            section = line.strip("#* ").strip()[:60]
            continue
        if "$" not in line:
            continue
        kind = next((k for w, k in COST_WORDS if w in line.lower()), None)
        if not kind:
            continue
        cells = [x.strip() for x in line.strip("|").split("|")] if line.startswith("|") else []
        label = (cells[0] if cells and "$" not in cells[0] else line.split("$")[0]).strip(" :-*")[:60] or kind
        text, value = _money(line)
        if value is None or value <= 0:
            continue
        rows.append({"kind": kind, "label": label, "section": section, "line": re.sub(r"\s+", " ", line)[:160],
                     "amount": text, "value": str(value)})
        if len(rows) == 8:
            break
    return {"url": item.get("url") or "", "title": re.sub(r"\s+", " ", item.get("title") or "").strip()[:120],
            "site": websearch._site(item.get("url") or "", item.get("metadata")), "year": academic_year(page),
            "items": rows}


def is_edu(url):
    return (urlparse(url).hostname or "").endswith(".edu")


def search_costs(c, post=None, limit=5):
    """The best page of published costs: a .edu page with cost lines first, else any page with cost lines. Returns
    {"found_at", "provider", "college", "page" (or None), "others": [links]}; raises on failure."""
    post = post or websearch._post
    pages = [parse_costs(item) for item in ((post(cost_query(c), limit).get("data") or {}).get("web") or [])
             if item.get("url")]
    ranked = sorted((p for p in pages if p["items"]), key=lambda p: not is_edu(p["url"]))
    best = ranked[0] if ranked else None
    return {"found_at": datetime.now().isoformat(timespec="minutes"), "provider": "Firecrawl (keyless search)",
            "college": c["name"], "page": best,
            "others": [{"title": p["title"], "url": p["url"]} for p in pages if p is not best][:4]}


def pay_number(text):
    """The pay per hour as a number when the page states exactly one ("$15 an hour" -> 15), else None (a range or
    "see website": she types it)."""
    if not text or text == SEE or re.search(r"(?:-|–|\bto\b)", text):
        return None
    m = re.search(r"\d+(?:\.\d{2})?", text)
    return Decimal(m.group(0)) if m else None


# --- the last jobs she found (the chat's find_jobs tool cites them as web links) ------------------------------------
ACTIVE_MODE = "maya"             # set by the UI on every run (ui/state.py): "maya" or "mine"


def found_path(mode):
    return path(mode).with_name(path(mode).stem + "-jobs.json")


def save_found(mode, found):
    p = found_path(mode)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(found, indent=1), encoding="utf-8")


def load_found(mode):
    try:
        return json.loads(found_path(mode).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
