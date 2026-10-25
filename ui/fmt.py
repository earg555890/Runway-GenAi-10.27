"""UI formatting: re-exports the shared plain-English wording (wording.py), plus UI-only settings."""
import streamlit as st

from wording import (SOURCE_PLAIN, STUDENT_NAME, balance, change, day, describe, dollars,  # noqa: F401
                     event_name, html, md, money, ordinal, strip_ids, term_name, things, value, weeks_words)

# Proof tables: "What" and "Amount" first and narrow enough that both fit on a phone (~400 px).
PROOF_COLUMNS = {"What": st.column_config.TextColumn(width="medium"),
                 "Amount": st.column_config.TextColumn(width="small"),
                 "Date": st.column_config.TextColumn(width="small"),
                 "Where": st.column_config.TextColumn(width="medium")}

# One color per spending category, everywhere in the app (Budget tab donut, table, progress bars). The 7 hues are
# the reference categorical palette (dataviz skill) in a validated order, light and dark steps; red is left out
# because red means "below $0" in Runway. Categories without a hue fold into "Other" (gray) in charts.
CATEGORY_COLORS = {
    "Rent": ("#2a78d6", "#3987e5"), "Shopping": ("#eb6834", "#d95926"), "Groceries": ("#1baf7a", "#199e70"),
    "Eating out": ("#eda100", "#c98500"), "School": ("#e87ba4", "#d55181"),
    "Bills & utilities": ("#008300", "#008300"), "Subscriptions": ("#6250d6", "#9085e9"),
}
OTHER_COLOR = ("#9ca3af", "#6b7280")
OTHER = "Other"


def dark():
    try:
        return st.context.theme.type == "dark"
    except Exception:                      # bare mode / tests: light
        return False


def category_color(name):
    pair = CATEGORY_COLORS.get(name, OTHER_COLOR)
    return pair[1] if dark() else pair[0]
