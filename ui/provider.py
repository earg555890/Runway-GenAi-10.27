"""Behind the scenes: the AI provider. Meterless Nightshift's connection, authorization, model discovery and
text-request checks (meterless.run_checks), run once in a background thread so the page never waits."""
import time

import pandas as pd
import streamlit as st

import config
import meterless
from ui import background

KEY = "meterless_checks"
STATE_WORDS = {"online": ":green[online]", "unauthorized": ":orange[unauthorized: paste the Runtime token]",
               "offline": ":red[offline]"}


def _show(r):
    if r is None:
        st.caption("Checking Meterless Nightshift...")
        return
    st_ = r["status"]
    st.markdown(f"**Provider:** {'Meterless Nightshift (primary)' if r['provider'] == 'meterless' else 'NVIDIA API directly'}"
                f" · `{r['base_url']}` · runtime {STATE_WORDS.get(st_['state'], st_['state'])}")
    rows = [
        {"check": "Connection (GET /healthz)", "result": f"HTTP {r['healthz']}" if r["healthz"] else "no answer",
         "passed": bool(r["healthz"] == 200)},
        {"check": "Authorization (GET /v1/models with the Runtime token)",
         "result": f"HTTP {st_['http_status']}: {st_['state']}", "passed": st_["state"] == "online"},
        {"check": "A wrong token shows unauthorized, not offline", "result": r["wrong_token_state"],
         "passed": r["wrong_token_state"] == "unauthorized"},
        {"check": "Model discovery", "result": f"{len(st_['routing_modes'])} routing modes, "
                                               f"{len(r['discovered_nemotron'])} Nemotron models",
         "passed": bool(st_["routing_modes"])},
    ] + [{"check": f"Text request on {t['model']}",
          "result": (f"\"{t['text']}\" from {t['routed_model']} in {t['seconds']} s (receipt {t['receipt_id']})"
                     if t["ok"] else f"failed: {t['error']}"), "passed": t["ok"]} for t in r["text_checks"]]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch",
                 column_config={"passed": st.column_config.CheckboxColumn(width="small"),
                                "result": st.column_config.TextColumn(width="large")})
    st.caption(f"Nemotron models discovered: {', '.join(r['discovered_nemotron']) or 'none'}. "
               f"PLAN and fast answers: `{config.NVIDIA_PLAN_MODEL}`; Think harder: `{config.THINK_MODEL}`; "
               f"general requests: `{config.METERLESS_ROUTING_MODE}`. Checked "
               f"{time.strftime('%H:%M:%S', time.localtime(r['checked_at']))}.")


def render():
    st.markdown("#### AI provider")
    if config.SAMPLE_MODE:
        st.caption("Sample mode: Runway shows recorded answers and calls no AI provider. Set SAMPLE_MODE=false and "
                   "start Meterless Nightshift for live answers (NVIDIA Nemotron through Nightshift).")
        return
    if config.AI_PROVIDER != "meterless":
        st.caption("Runway is set to call the NVIDIA API directly (AI_PROVIDER=nvidia). Meterless Nightshift is the "
                   "default; remove AI_PROVIDER from .env to use it.")
        return
    background.start(KEY, meterless.run_checks)
    background.slot(KEY, None, _show)
    if st.button("Run the checks again", key="meterless_recheck", type="tertiary", icon=":material/refresh:"):
        background.forget(KEY)
        st.rerun()
