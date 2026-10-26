"""The student's meal plan settings and meal log, kept on this computer only and never committed.

    data = mealplan.load("maya")                       # {"settings": {...} or None, "log": [...], "next": 4}
    s = mealplan.settings(data, ds)                    # engine.MealSettings: hers, else her school's plan
    problem = mealplan.add(data, day, meals=1)         # None, or a friendly message (nothing logged)
    mealplan.save("maya", data)
    engine.Scenario(**mealplan.scenario_part(data, ds, today))

Maya (the demo) keeps hers in .cache/mealplan.json; My data mode keeps hers in user_data/mealplan.json (rule 7:
what she enters stays with her own data). Both folders are gitignored. The engine does all the math.
"""
import json
from datetime import date
from decimal import Decimal

import config
import engine

FOLDER = None                    # tests point this at a temp folder


def path(mode):
    if FOLDER is not None:
        return FOLDER / f"mealplan-{mode}.json"
    return (config.USER_DATA_DIR if mode == "mine" else config.PROJECT_ROOT / ".cache") / "mealplan.json"


def empty():
    return {"settings": None, "log": [], "next": 1}


def load(mode):
    p = path(mode)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return {**empty(), **data}
    except (OSError, ValueError):
        return empty()


def save(mode, data):
    p = path(mode)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=1), encoding="utf-8")


def to_dict(s):
    return {"meals": s.meals, "meals_per": s.meals_per, "points": str(s.points), "points_per": s.points_per,
            "start": s.start.isoformat(), "end": s.end.isoformat(), "week_starts": s.week_starts,
            "rolls_over": s.rolls_over}


def from_dict(d):
    return engine.MealSettings(int(d["meals"]), d["meals_per"], Decimal(d["points"]), d["points_per"],
                               date.fromisoformat(d["start"]), date.fromisoformat(d["end"]), int(d["week_starts"]),
                               bool(d["rolls_over"]))


def settings(data, ds):
    """Her settings, else her school's plan (Maya), else None (My data mode before she sets one)."""
    if data.get("settings"):
        try:
            return from_dict(data["settings"])
        except (KeyError, ValueError, TypeError):
            pass
    return engine.default_meal_settings(ds)


def is_custom(data, ds):
    """True when her settings differ from her school's plan."""
    return bool(data.get("settings")) and settings(data, ds) != engine.default_meal_settings(ds)


def entries(data):
    return tuple(engine.MealEntry(date.fromisoformat(e["date"]), int(e["meals"]), Decimal(e["points"]),
                                  e.get("note", ""), e["id"]) for e in data["log"])


def set_settings(data, s):
    data["settings"] = to_dict(s)


def add(data, day, meals=0, points=0, note="", today=None, ds=None):
    """Log meals and/or points on a day. Returns None, or a friendly message (and nothing is logged)."""
    s = settings(data, ds)
    if not s:
        return "Set up your meal plan first."
    problem = engine.meal_entry_problem(day, meals, points, s, today)
    if problem:
        return problem
    data["log"].append({"id": f"LOG-{data['next']}", "date": day.isoformat(), "meals": int(meals or 0),
                        "points": str(engine.D(points or 0)), "note": (note or "").strip()[:80]})
    data["next"] += 1
    return None


def add_meal(data, day, ds=None, today=None):
    """One tap: one more meal on day (added to that day's newest meals-only entry while it has under 10)."""
    for e in reversed(data["log"]):
        if e["date"] == day.isoformat() and Decimal(e["points"]) == 0 and not e.get("note"):
            if 0 < e["meals"] < engine.MAX_MEALS_ENTRY:
                e["meals"] += 1
                return None
            break
    return add(data, day, meals=1, ds=ds, today=today)


def remove(data, entry_id):
    data["log"] = [e for e in data["log"] if e["id"] != entry_id]


def undo_meal(data, day):
    """Takes one meal back off day: the newest meals-only entry that day, or one meal from the newest entry with
    meals. False when there is none."""
    for e in reversed(data["log"]):
        if e["date"] == day.isoformat() and e["meals"]:
            if e["meals"] == 1 and Decimal(e["points"]) == 0:
                remove(data, e["id"])
            else:
                e["meals"] -= 1
            return True
    return False


def meals_on(data, day):
    return sum(e["meals"] for e in data["log"] if e["date"] == day.isoformat())


def scenario_part(data, ds, today=None):
    """Engine.Scenario fields: nothing at all when she has her school's plan and an empty log (Maya's default state
    stays exactly the same), else her settings (when custom), her log and the meal plan's "today"."""
    custom, log = is_custom(data, ds), entries(data)
    if not custom and not log and (today is None or today == config.DEMO_TODAY):
        return {}
    s = settings(data, ds)
    if not s:
        return {}
    return {"meal_settings": s if custom else None, "meal_log": log,
            "meal_today": today if today and today != config.DEMO_TODAY else None}


def memory_text(s, dollars):
    """"Your meal plan: 14 meals a week, $150 points a semester." (dollars: the UI's money words)."""
    return (f"Your meal plan: {s.meals} meal{'s' if s.meals != 1 else ''} a {s.meals_per}, {dollars(s.points)} "
            f"points a {s.points_per}" + (", unused ones roll over" if s.rolls_over and not s.pooled else "") + ".")
