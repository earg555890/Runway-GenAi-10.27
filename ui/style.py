"""Runway's look: "night runway". Night navy, warm paper, one amber accent (runway lights); alert red only for below $0,
signal green only for "covered / good news". Fonts (config.toml): Atkinson Hyperlegible body, Bricolage Grotesque
headings, DM Mono for big numbers and dates (tabular figures).

Readability wins over style: body text 16 px+, short lines, generous spacing, text contrast of at least 4.5:1 in light
and dark (red and green text use a darker shade on paper and a lighter one on navy; lines and fills use the brand
colors). The palette is defined once as CSS variables per theme (st.context.theme) and reused by cards, buttons,
chips and the chart (ui/chart.py reads PALETTE).

Motion: one orchestrated page load (header, notices, tabs, then the graph line drawing left to right) and a single
soft pulse on the chat button, under 600 ms, CSS only, on element creation only (Streamlit keeps the elements across
reruns, so nothing replays), and off under prefers-reduced-motion. Small hover lifts on cards and buttons.
"""
import streamlit as st

NAVY, PAPER, AMBER, GREEN, RED = "#0F1B2D", "#F6F2EA", "#F2A33A", "#2E8F62", "#C8402F"
PALETTE = {
    "light": {"ink": NAVY, "card": "#FFFDF8", "card_border": "#E4DACA", "muted": "#4A5568", "red_text": "#B23A2A",
              "green_text": "#22704C", "link": "#2F5F9E", "good_bg": "rgba(46,143,98,.10)",
              "bad_bg": "rgba(200,64,47,.07)", "shadow": "rgba(15,27,45,.10)", "axis": "#5A6577",
              "band_top": "#13223A", "band": NAVY, "band_border": "rgba(15,27,45,.0)"},
    "dark": {"ink": "#F3EEE4", "card": "#18283F", "card_border": "#2A3D58", "muted": "#B9C2D0", "red_text": "#F08A78",
             "green_text": "#63C394", "link": "#8FB4E8", "good_bg": "rgba(46,143,98,.16)",
             "bad_bg": "rgba(200,64,47,.14)", "shadow": "rgba(0,0,0,.40)", "axis": "#A4AFC2",
             "band_top": "#0B1525", "band": "#070E19", "band_border": "rgba(243,238,228,.14)"},
}
# Runway Body / Runway Mono (config.toml fontFaces): Atkinson Hyperlegible and DM Mono with DM Sans digits (plain zero)
HEADING, BODY, MONO = "'Bricolage Grotesque', sans-serif", "'Runway Body', sans-serif", "'Runway Mono', monospace"
CARDS = ('[class*="st-key-card_"], [class*="st-key-ci_card_"], [class*="st-key-fm_card_"], .st-key-balance_card, '
         '.st-key-shift_planner, .st-key-meal_card, .st-key-college_card, .st-key-jobs_card, .st-key-costs_card')
HOVERED = ", ".join(s + ":hover" for s in CARDS.split(", "))


def mode():
    """'light' or 'dark' (the viewer's Streamlit theme; light when unknown)."""
    try:
        return "dark" if (st.context.theme.type or "light") == "dark" else "light"
    except Exception:
        return "light"


def css(m="light"):
    p = PALETTE[m]
    return f"""
<style>
:root {{--rw-navy: {NAVY}; --rw-paper: {PAPER}; --rw-amber: {AMBER}; --rw-green: {GREEN}; --rw-red: {RED};
  --rw-ink: {p['ink']}; --rw-card: {p['card']}; --rw-card-border: {p['card_border']}; --rw-muted: {p['muted']};
  --rw-red-text: {p['red_text']}; --rw-green-text: {p['green_text']}; --rw-link: {p['link']};
  --rw-good-bg: {p['good_bg']}; --rw-bad-bg: {p['bad_bg']}; --rw-shadow: {p['shadow']};}}

/* page: warm paper (or night navy) with a very subtle layered glow */
.stApp {{background-image: radial-gradient(1100px 480px at -5% -12%, rgba(242,163,58,.10), transparent 60%),
  radial-gradient(900px 520px at 105% 0%, rgba(63,120,192,.08), transparent 62%);}}
.block-container {{max-width: 1080px; padding-top: 3.4rem; padding-bottom: 8rem !important;}}
.stMarkdown p, .stMarkdown li, .stCaption p {{max-width: 68ch;}}
.stMarkdown p, .stMarkdown li {{font-size: 1.05rem; line-height: 1.55;}}
[data-testid="stMarkdownContainer"] h4, .rw-card-head, .rw-ci-head, .rw-brand, .rw-big, .rw-ans
  {{font-family: {HEADING}; letter-spacing: -0.01em;}}
[data-testid="stMarkdownContainer"] h4 {{font-size: 1.3rem; font-weight: 700; margin: 1rem 0 .4rem;}}

/* header: the night-runway band (navy in both modes), a dashed centerline and a few amber runway lights */
.st-key-rw_header {{background: linear-gradient(180deg, {p['band_top']} 0%, {p['band']} 100%); color: #F3EEE4;
  border-radius: 18px; border: 1px solid {p['band_border']}; padding: 1.1rem 1.4rem 1.7rem; position: relative;
  overflow: hidden; box-shadow: 0 10px 30px -18px rgba(15,27,45,.7);}}
.st-key-rw_header::before {{content: ""; position: absolute; left: 1.4rem; right: 1.4rem; bottom: .75rem;
  border-top: 2px dashed rgba(243,238,228,.26);}}
.st-key-rw_header::after {{content: ""; position: absolute; left: 1.4rem; right: 1.4rem; bottom: .45rem; height: 8px;
  background: radial-gradient(circle, {AMBER} 0 2.2px, rgba(242,163,58,.25) 3px, transparent 4.5px) left / 64px 8px repeat-x;
  opacity: .9;}}
.st-key-rw_header .rw-brand {{font-size: 1.75rem; font-weight: 800; margin: 0; color: #F3EEE4;}}
.st-key-rw_header .rw-hello {{font-size: 1.05rem; margin: 0; color: rgba(243,238,228,.86); opacity: 1;}}
.st-key-rw_header .st-key-badges span {{color: #F3EEE4 !important;}}
.st-key-rw_header .st-key-badges [data-testid="stElementContainer"] > div > span,
.st-key-rw_header .st-key-badges [data-testid="stMarkdownContainer"] span {{background: rgba(243,238,228,.10) !important;}}
.rw-hello {{font-size: 1.05rem; opacity: .85; margin: 0;}}
.rw-brand {{font-size: 1.5rem; font-weight: 700; margin: 0;}}

/* the status card, with a departure-board label */
.rw-status {{border-radius: 16px; padding: 1.1rem 1.4rem 1.2rem; margin: 1rem 0 .8rem; line-height: 1.35;
  background: var(--rw-card); border: 1px solid var(--rw-card-border); box-shadow: 0 8px 24px -16px var(--rw-shadow);}}
.rw-status.rw-bad {{background: linear-gradient(0deg, var(--rw-bad-bg), var(--rw-bad-bg)), var(--rw-card);
  border-left: 5px solid var(--rw-red);}}
.rw-status.rw-good {{background: linear-gradient(0deg, var(--rw-good-bg), var(--rw-good-bg)), var(--rw-card);
  border-left: 5px solid var(--rw-green);}}
.rw-status .rw-big {{font-size: 1.75rem; font-weight: 750;}}
.rw-status .rw-why {{font-size: 1.1rem; margin-top: .4rem; opacity: .9;}}
.rw-board {{display: inline-block; font-family: {MONO}; font-variant-numeric: tabular-nums; font-size: .82rem;
  font-weight: 500; letter-spacing: .14em; padding: .22rem .6rem; border-radius: 6px; background: {NAVY};
  margin-bottom: .55rem;}}
.rw-board-bad {{color: #FFB45E;}} .rw-board-good {{color: #7BD6A6;}}
.rw-answer {{font-size: 1.7rem; font-weight: 700; margin: .5rem 0 .3rem;}}
.rw-red {{color: var(--rw-red-text);}} .rw-green {{color: var(--rw-green-text);}}

/* tabs: ink text on the selected tab, the amber underline from the theme */
div[data-testid="stTabs"] button p {{font-size: 1.1rem;}}
[data-testid="stTab"][aria-selected="true"] p {{color: var(--rw-ink) !important; font-weight: 700;}}

/* big numbers and dates like a departure board */
.rw-today {{font-family: {MONO}; font-variant-numeric: tabular-nums; font-size: 3.3rem; font-weight: 500;
  line-height: 1.05; letter-spacing: -0.04em;}}
.rw-today-cap {{font-size: 1rem; opacity: .85; margin-top: .25rem;}}
.rw-fig {{margin-top: .35rem;}}
.rw-fig-label {{font-size: .95rem; opacity: .85;}}
.rw-fig-value {{font-family: {MONO}; font-variant-numeric: tabular-nums; font-size: 1.45rem; font-weight: 400;
  line-height: 1.25; letter-spacing: -0.02em;}}
.rw-fig-when {{font-size: .9rem; opacity: .8;}}
.rw-card-head {{font-size: 1.2rem; font-weight: 700; margin: 0 0 .5rem;}}

/* the meal plan card: two big counters, then one-tap logging with big touch targets */
.rw-meal-row {{display: grid; grid-template-columns: 1fr 1fr; gap: .9rem; margin: .2rem 0 .4rem;}}
.rw-meal-box {{border: 1px solid var(--rw-card-border); border-radius: 14px; padding: .8rem .95rem;}}
.rw-meal-label {{font-size: 1rem; font-weight: 700;}}
.rw-meal-num {{font-family: {MONO}; font-variant-numeric: tabular-nums; font-size: 2.4rem; font-weight: 500;
  line-height: 1.1; letter-spacing: -0.03em; margin-top: .15rem;}}
.rw-meal-period {{font-size: 1rem; opacity: .85;}}
.rw-meal-line, .rw-meal-lose {{font-size: 1rem; line-height: 1.45; margin-top: .45rem;}}
.rw-meal-lose {{color: var(--rw-muted);}}
.rw-meal-today {{font-size: 1.1rem; min-width: 8.5rem; text-align: center;}}
.rw-meal-today b {{font-family: {MONO}; font-size: 1.5rem; font-weight: 500;}}
.rw-meal-recent {{font-size: 1rem; font-weight: 700; margin-top: .4rem;}}
.st-key-meal_minus button, .st-key-meal_plus button {{width: 3.25rem; height: 3.25rem; min-height: 3.25rem;
  border-radius: 50%; font-size: 1.4rem;}}
.st-key-meal_points_row button {{min-height: 2.75rem; min-width: 4.5rem;}}
[class*="st-key-meal_rm_"] button {{min-width: 2.75rem; min-height: 2.75rem;}}
@media (max-width: 640px) {{.rw-meal-row {{grid-template-columns: 1fr;}}}}
.rw-legend {{font-size: .95rem; opacity: .9; margin: .9rem 0 0;}}
.rw-sw {{display: inline-block; width: 24px; height: 0; vertical-align: middle; margin: 0 .45rem 0 1rem;}}
.rw-sw:first-child {{margin-left: 0;}}
.rw-sw-now {{border-top: 3.5px solid #3F78C0; border-radius: 2px;}}
.rw-sw-steps {{border-top: 3px dotted {GREEN};}}
.rw-plan-note {{margin-left: 1rem; color: var(--rw-green-text); font-weight: 700;}}
.rw-delta {{font-family: {MONO}; font-size: .78rem; font-weight: 500; margin-left: .35rem; padding: .05rem .4rem;
  border-radius: 999px; vertical-align: middle;}}
.rw-up {{color: var(--rw-green-text); background: var(--rw-good-bg);}}
.rw-down {{color: var(--rw-red-text); background: var(--rw-bad-bg);}}

/* cards: the same rounded card with a soft shadow in every tab and in the chat panel */
{CARDS} {{background: var(--rw-card); border-color: var(--rw-card-border) !important; border-radius: 16px;
  box-shadow: 0 1px 2px var(--rw-shadow), 0 10px 28px -20px var(--rw-shadow);
  transition: transform .18s ease, box-shadow .18s ease;}}
@media (hover: hover) {{
  {HOVERED} {{transform: translateY(-2px); box-shadow: 0 2px 4px var(--rw-shadow), 0 16px 32px -20px var(--rw-shadow);}}
  button[data-testid^="stBaseButton"]:hover {{transform: translateY(-1px);}}
}}
button[data-testid^="stBaseButton"] {{transition: transform .15s ease;}}
button[data-testid="stBaseButton-primary"], button[data-testid="stBaseButton-primary"] p {{color: {NAVY} !important;
  font-weight: 700;}}

/* the chat answer */
.rw-ans {{font-size: 1.5rem; font-weight: 750; line-height: 1.3; margin: .2rem 0 .5rem; max-width: 40ch;}}
.rw-why-list, .rw-do-list {{font-size: 1.05rem; line-height: 1.55; margin: 0 0 .6rem 1.2rem; max-width: 64ch;}}
.rw-why-list li, .rw-do-list li {{margin: .2rem 0;}}
.rw-do-head {{font-family: {MONO}; font-size: .82rem; font-weight: 500; text-transform: uppercase; letter-spacing: .12em;
  opacity: .9; margin-top: .4rem;}}
.rw-note {{font-size: .95rem; opacity: .85; margin: .3rem 0 .4rem; max-width: 64ch;}}
.rw-fn {{font-size: .65em; font-weight: 700; margin-left: .12em; color: var(--rw-link);}}
[class*="st-key-ask_suggest_"] button p {{font-size: .95rem; white-space: normal; text-align: left !important;}}
[class*="st-key-ask_suggest_"] button > div {{justify-content: flex-start !important;}}
[class*="st-key-ask_suggest_"] button {{height: auto; min-height: 2.4rem;}}

/* the check-in */
.rw-ci-head {{font-size: 1.3rem; font-weight: 750; margin: .2rem 0 0;}}
.rw-ci-line {{font-size: 1rem; opacity: .85; margin: .1rem 0 .5rem;}}
.rw-ci-title, .rw-card-title {{font-size: 1.05rem; font-weight: 700; line-height: 1.3;}}
.rw-ci-text, .rw-card-text {{font-size: 1rem; line-height: 1.45; margin-top: .25rem;}}
.rw-ci-memory {{font-size: .95rem; line-height: 1.4; margin-top: .35rem; color: var(--rw-link);}}
.st-key-checkin {{margin-bottom: .6rem;}}

/* budget, find money */
.rw-bud-line {{font-size: 1.15rem; line-height: 1.45; margin: .2rem 0 .6rem; max-width: 64ch;}}
.rw-bud-table {{width: 100%; border-collapse: collapse; font-size: 1rem;}}
.rw-bud-table th {{text-align: left; font-weight: 700; font-size: .9rem; opacity: .85; padding: .3rem .5rem;
  border-bottom: 1px solid var(--rw-card-border);}}
.rw-bud-table td {{padding: .35rem .5rem; border-bottom: 1px solid var(--rw-card-border);}}
.rw-bud-table td:not(:first-child), .rw-bud-table th:not(:first-child) {{text-align: right; white-space: nowrap;
  font-family: {MONO}; font-variant-numeric: tabular-nums;}}
.rw-sw-dot {{display: inline-block; width: .7rem; height: .7rem; border-radius: 3px; margin-right: .5rem;
  vertical-align: baseline;}}
.rw-muted {{opacity: .75;}}
.rw-fm-title {{font-size: 1.05rem; font-weight: 700; line-height: 1.3;}}
.rw-fm-meta {{font-size: .95rem; opacity: .85; margin: .15rem 0 .25rem;}}
.rw-bud-head {{font-size: 1.15rem; font-weight: 700; margin: .1rem 0 .4rem; max-width: 64ch;}}
.rw-bud-left {{font-size: 1.05rem; font-weight: 700;}}
.rw-bud-effect {{font-size: 1.1rem; margin: .3rem 0 .6rem; max-width: 64ch;}}
.rw-prog {{margin: .5rem 0 .7rem; max-width: 560px;}}
.rw-prog-top {{display: flex; justify-content: space-between; font-size: 1rem; gap: 1rem;}}
.rw-prog-track {{height: 10px; border-radius: 5px; background: rgba(128,128,128,.22); margin-top: .25rem;
  overflow: hidden;}}
.rw-prog-fill {{height: 100%; border-radius: 5px;}}
.rw-prog-sub {{font-size: .9rem; opacity: .85; margin-top: .15rem;}}
.rw-pace-on-pace {{opacity: .85;}} .rw-pace-spending-fast, .rw-pace-over {{font-weight: 700;}}
[class*="st-key-ci_acts_"] button p, [class*="st-key-fm_acts_"] button p, [class*="st-key-bud_refund"] button p,
[class*="st-key-fm_acts_"] label p {{font-size: .95rem !important;}}

/* the chat panel: a solid card over a dimmed, blurred page (a see-through overlay made the page under the panel's
   edge look like part of the panel) */
[data-testid="stDialog"] {{background: rgba(9,16,28,.62) !important; backdrop-filter: blur(3px);}}
[data-testid="stDialog"] div:has(> [role="dialog"]) {{background: var(--rw-card) !important;
  border: 1px solid var(--rw-card-border); box-shadow: 0 30px 80px -24px rgba(0,0,0,.6);}}
@media (min-width: 641px) {{
  [data-testid="stDialog"] [role="dialog"] {{min-height: min(76vh, 760px);}}
}}

/* the floating "Ask Runway" button: fixed bottom-left on every tab; the page keeps room below its last element */
.st-key-chat_fab {{position: fixed; left: 24px; bottom: 24px; z-index: 999990; width: auto !important;}}
.st-key-chat_fab button {{width: 64px; height: 64px; min-height: 64px; border-radius: 50%; padding: 0;
  border: 2px solid rgba(15,27,45,.12); box-shadow: 0 8px 22px rgba(15,27,45,.32);}}
.st-key-chat_fab button [data-testid="stIconMaterial"] {{font-size: 30px; margin: 0; color: {NAVY};}}
.st-key-chat_fab button p {{position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0);
  white-space: nowrap;}}

/* motion: one staggered reveal on load (elements are created once; reruns keep them, so nothing replays) */
@keyframes rw-rise {{from {{opacity: 0; transform: translateY(10px);}} to {{opacity: 1; transform: none;}}}}
@keyframes rw-draw {{from {{clip-path: inset(0 100% 0 0);}} to {{clip-path: inset(0 0 0 0);}}}}
@keyframes rw-pulse {{0% {{box-shadow: 0 0 0 0 rgba(242,163,58,.55), 0 8px 22px rgba(15,27,45,.32);}}
  100% {{box-shadow: 0 0 0 16px rgba(242,163,58,0), 0 8px 22px rgba(15,27,45,.32);}}}}
.st-key-rw_header {{animation: rw-rise .38s ease-out both;}}
.st-key-notices {{animation: rw-rise .4s ease-out .07s both;}}
div[data-testid="stTabs"] {{animation: rw-rise .4s ease-out .14s both;}}
.st-key-balance_chart {{animation: rw-draw .45s ease-out .15s both;}}
.st-key-chat_fab button {{animation: rw-pulse .55s ease-out .05s 1;}}
@media (prefers-reduced-motion: reduce) {{
  *, *::before, *::after {{animation: none !important; transition: none !important;}}
  {HOVERED}, button[data-testid^="stBaseButton"]:hover {{transform: none !important;}}
}}

@media (max-width: 640px) {{
  .st-key-badges {{justify-content: flex-start !important; flex-direction: row !important; flex-wrap: wrap !important;
      gap: .35rem !important;}}
  .st-key-badges > div {{width: auto !important; flex: 0 0 auto !important;}}
  .st-key-rw_header {{padding: 1rem 1rem 1.6rem;}}
  .rw-status .rw-big {{font-size: 1.45rem;}}
  .rw-today {{font-size: 2.7rem;}}
  .st-key-ci_top div[data-testid="stHorizontalBlock"] {{flex-wrap: nowrap !important; overflow-x: auto;
      scroll-snap-type: x mandatory; padding-bottom: .3rem;}}
  .st-key-ci_top div[data-testid="stColumn"] {{min-width: 84% !important; flex: 0 0 84% !important;
      scroll-snap-align: start;}}
  .st-key-ci_more > [data-testid="stLayoutWrapper"]:has([data-testid="stExpander"]) {{min-width: 100%;}}
  .st-key-bud_month [data-testid="stButtonGroup"] > div:last-child {{flex-wrap: wrap; row-gap: .3rem;}}
  .st-key-chat_fab {{left: 16px; bottom: 16px;}}
  [data-testid="stDialog"] [role="dialog"] {{width: calc(100vw - 16px) !important; max-width: calc(100vw - 16px) !important;
      min-height: 92vh; margin: 0 auto !important; border-radius: 16px; box-sizing: border-box;}}
  [data-testid="stDialog"] [role="dialog"] * {{max-width: 100%; box-sizing: border-box;}}
}}
</style>
"""


def apply():
    st.markdown(css(mode()), unsafe_allow_html=True)
