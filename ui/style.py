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
</style>
"""


def apply():
    st.markdown(CSS, unsafe_allow_html=True)
