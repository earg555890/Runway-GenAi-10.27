"""A little CSS: calm spacing, a readable width, the big status card. Works in light and dark themes."""
import streamlit as st

CSS = """
<style>
.block-container {max-width: 1080px; padding-top: 2.2rem; padding-bottom: 4rem;}
.rw-hello {font-size: 1.05rem; opacity: .75; margin: 0;}
.rw-brand {font-size: 1.5rem; font-weight: 700; margin: 0;}
.rw-status {border-radius: 16px; padding: 1.2rem 1.4rem; margin: 1rem 0 .6rem; line-height: 1.35;}
.rw-status .rw-big {font-size: 1.7rem; font-weight: 650;}
.rw-status .rw-why {font-size: 1.05rem; margin-top: .45rem; opacity: .85;}
.rw-status .rw-plan {font-size: .9rem; margin-top: .55rem; opacity: .7;}
.rw-bad {background: rgba(239, 68, 68, .10); border: 1px solid rgba(239, 68, 68, .40);}
.rw-good {background: rgba(34, 197, 94, .10); border: 1px solid rgba(34, 197, 94, .40);}
.rw-answer {font-size: 1.6rem; font-weight: 650; margin: .4rem 0 .2rem;}
.rw-red {color: #dc2626;} .rw-green {color: #16a34a;}
div[data-testid="stTabs"] button p {font-size: 1.05rem;}
.rw-today {font-size: 3.2rem; font-weight: 750; line-height: 1.05; letter-spacing: -0.02em;}
.rw-today-cap {font-size: 1rem; opacity: .7; margin-top: .2rem;}
.rw-fig {font-size: 1.1rem; margin: .25rem 0;}
.rw-fig-label {opacity: .75;}
.rw-fig-value {font-weight: 700; font-size: 1.25rem;}
.rw-delta {font-size: .9rem; font-weight: 600; margin-left: .45rem; padding: .05rem .45rem; border-radius: 999px;}
.rw-up {color: #16a34a; background: rgba(34, 197, 94, .12);} .rw-down {color: #dc2626; background: rgba(239, 68, 68, .12);}
</style>
"""


def apply():
    st.markdown(CSS, unsafe_allow_html=True)
