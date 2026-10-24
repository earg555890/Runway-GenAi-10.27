"""UI formatting: re-exports the shared plain-English wording (wording.py), plus UI-only settings."""
import streamlit as st

from wording import (SOURCE_PLAIN, STUDENT_NAME, balance, change, day, describe, dollars,  # noqa: F401
                     event_name, html, md, money, ordinal, strip_ids, term_name, things, value, weeks_words)

# Proof tables: "What" and "Amount" first and narrow enough that both fit on a phone (~400 px).
PROOF_COLUMNS = {"What": st.column_config.TextColumn(width="medium"),
                 "Amount": st.column_config.TextColumn(width="small"),
                 "Date": st.column_config.TextColumn(width="small"),
                 "Where": st.column_config.TextColumn(width="medium")}
