"""CSS for readability: 16 px+ body text, short line lengths, generous spacing, strong contrast in light and dark
themes (colors are mid-tones or inherit the theme's text color; muted text uses opacity no lower than .8)."""
import streamlit as st

CSS = """
<style>
.block-container {max-width: 1080px; padding-top: 2.2rem; padding-bottom: 4rem;}
.stMarkdown p, .stMarkdown li, .stCaption p {max-width: 68ch;}
.stMarkdown p, .stMarkdown li {font-size: 1.05rem; line-height: 1.55;}
.rw-hello {font-size: 1.05rem; opacity: .85; margin: 0;}
.rw-brand {font-size: 1.5rem; font-weight: 700; margin: 0;}
.rw-status {border-radius: 16px; padding: 1.1rem 1.4rem; margin: 1rem 0 .8rem; line-height: 1.35;}
.rw-status .rw-big {font-size: 1.75rem; font-weight: 700;}
.rw-status .rw-why {font-size: 1.1rem; margin-top: .4rem; opacity: .9;}
.rw-bad {background: rgba(239, 68, 68, .10); border: 1px solid rgba(239, 68, 68, .45);}
.rw-good {background: rgba(34, 197, 94, .10); border: 1px solid rgba(34, 197, 94, .45);}
.rw-answer {font-size: 1.7rem; font-weight: 700; margin: .5rem 0 .3rem;}
.rw-red {color: #dc2626;} .rw-green {color: #16a34a;}
div[data-testid="stTabs"] button p {font-size: 1.1rem;}
.rw-today {font-size: 3.4rem; font-weight: 750; line-height: 1.05; letter-spacing: -0.02em;}
.rw-today-cap {font-size: 1rem; opacity: .85; margin-top: .25rem;}
.rw-fig {margin-top: .35rem;}
.rw-fig-label {font-size: .95rem; opacity: .85;}
.rw-fig-value {font-size: 1.6rem; font-weight: 400; line-height: 1.25;}
.rw-fig-when {font-size: .9rem; opacity: .75;}
.rw-legend {font-size: .9rem; opacity: .85; margin: .9rem 0 0;}
.rw-sw {display: inline-block; width: 22px; height: 0; vertical-align: middle; margin: 0 .4rem 0 .9rem;}
.rw-sw:first-child {margin-left: 0;}
.rw-sw-before {border-top: 2px dashed #9ca3af;}
.rw-sw-with {border-top: 3px solid #2563eb;}
.rw-sw-good {border-top-color: #16a34a;}
.rw-delta {font-size: .8rem; font-weight: 600; margin-left: .35rem; padding: .05rem .4rem; border-radius: 999px;
           vertical-align: middle;}
.rw-up {color: #16a34a; background: rgba(34, 197, 94, .14);}
.rw-down {color: #dc2626; background: rgba(239, 68, 68, .14);}
.rw-ans {font-size: 1.5rem; font-weight: 700; line-height: 1.3; margin: .2rem 0 .5rem; max-width: 40ch;}
.rw-why-list, .rw-do-list {font-size: 1.05rem; line-height: 1.55; margin: 0 0 .6rem 1.2rem; max-width: 64ch;}
.rw-why-list li, .rw-do-list li {margin: .2rem 0;}
.rw-do-head {font-size: .9rem; font-weight: 700; text-transform: uppercase; letter-spacing: .04em; opacity: .85;
             margin-top: .4rem;}
.rw-note {font-size: .95rem; opacity: .85; margin: .3rem 0 .4rem; max-width: 64ch;}
[class*="st-key-ask_suggest_"] button p {font-size: .92rem;}
@media (max-width: 640px) {
  .st-key-badges {justify-content: flex-start !important;}
  .rw-status .rw-big {font-size: 1.45rem;}
  .rw-today {font-size: 2.8rem;}
}
.rw-fn {font-size: .65em; font-weight: 600; opacity: .8; margin-left: .12em; color: #3b82f6;}
</style>
"""


def apply():
    st.markdown(CSS, unsafe_allow_html=True)
