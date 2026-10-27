"""My data mode: upload a bank export, check the detected columns (fix them with dropdowns), import. The file stays
on this computer (user_data/, rule 7); nothing is sent anywhere by importing it."""
from datetime import timedelta

import pandas as pd
import streamlit as st

import config
import importer
import mydata
from ui import fmt

PRIVACY = ("Your file stays on this computer, in user_data/. Nothing from it is committed or uploaded. When you ask "
           "PocketMoney a question, it goes through Meterless Nightshift on this computer. Nightshift keeps a local log of "
           "requests. It sends only that question and the numbers it needs to NVIDIA to write the answer.")


@st.cache_resource(show_spinner=False)
def _dataset(imported, backend):
    return mydata.dataset(backend)


def load():
    """Her Dataset (cached until she imports again)."""
    return _dataset(mydata.meta().get("imported"), config.DATA_BACKEND)


def _mapping_controls(m, header):
    """Dropdowns to fix the detected mapping. Returns the (possibly changed) Mapping."""
    none = "(none)"
    cols = st.columns(3)
    m.date = cols[0].selectbox("Date column", header, index=header.index(m.date), key="imp_date")
    m.date_format = cols[1].selectbox("Date format", importer.DATE_FORMATS,
                                      index=importer.DATE_FORMATS.index(m.date_format), key="imp_fmt",
                                      format_func=lambda f: f.replace("%Y", "YYYY").replace("%y", "YY")
                                      .replace("%m", "MM").replace("%d", "DD").replace("%b", "Mon"))
    m.description = cols[2].selectbox("Description column", header, index=header.index(m.description), key="imp_desc")
    cols = st.columns(3)
    m.sign = cols[0].selectbox("Amounts", list(importer.SIGNS), index=list(importer.SIGNS).index(m.sign),
                               format_func=importer.SIGNS.get, key="imp_sign")
    if m.sign == "debit_credit":
        m.debit = cols[1].selectbox("Money out column", header, key="imp_debit",
                                    index=header.index(m.debit) if m.debit in header else 0)
        m.credit = cols[2].selectbox("Money in column", header, key="imp_credit",
                                     index=header.index(m.credit) if m.credit in header else 0)
        m.amount = None
    else:
        m.amount = cols[1].selectbox("Amount column", header, key="imp_amount",
                                     index=header.index(m.amount) if m.amount in header else 0)
        m.debit = m.credit = None
    choice = cols[2].selectbox("Balance column", [none, *header], key="imp_bal",
                               index=([none, *header].index(m.balance) if m.balance else 0))
    m.balance = None if choice == none else choice
    return m


def render():
    """The import screen (My data mode with no data yet, or "Import a different file")."""
    st.markdown("### Use your own bank data")
    st.markdown(fmt.md("Download your checking account history as a CSV file from your bank's website, then add it "
                       "here. PocketMoney reads the dates, amounts and balance and shows you what it found before "
                       "importing."))
    st.caption(PRIVACY)
    up = st.file_uploader("Your bank export (.csv)", type=["csv", "txt"], key="imp_file")
    if not up:
        return
    text = up.getvalue().decode("utf-8-sig", errors="replace")
    try:
        m = importer.detect(text)
    except importer.ImportProblem as exc:
        st.error(str(exc))
        return
    st.markdown("**Here's what I found.** Fix anything that's wrong.")
    for n in m.notes:
        st.warning(n)
    m = _mapping_controls(m, m.header)
    try:
        rows = importer.normalize_rows(text, m)
    except importer.ImportProblem as exc:
        st.error(str(exc))
        return
    st.dataframe(pd.DataFrame([{"Date": fmt.day(r["date"]), "Description": r["description"],
                                "Amount": fmt.money(r["amount"]),
                                "Balance": fmt.money(r["balance"]) if r["balance"] is not None else ""}
                               for r in rows[:6]]), hide_index=True, width="stretch")
    st.caption(f"{len(rows)} transactions from {fmt.day(rows[0]['date'])} to {fmt.day(rows[-1]['date'])}. "
               "Money out is shown with a minus sign.")
    balance = None
    if not m.balance:
        balance = st.number_input("This file has no balance. What's in your checking account now? ($)", step=10.0,
                                  format="%.2f", key="imp_balance")
    last = rows[-1]["date"]
    end = st.date_input("Plan until", value=mydata.default_end(last), min_value=last + timedelta(days=7),
                        format="MM/DD/YYYY", key="imp_end", help="PocketMoney shows how long your money lasts until this "
                        "date (for example, the end of your semester).")
    if st.button("Import my data", type="primary", icon=":material/upload_file:", key="imp_go"):
        mydata.save(rows, m, up.name, balance_today=balance, end_date=end)
        _dataset.clear()
        st.rerun()


def manage():
    """In My data mode: which file is in use, and replace or remove it."""
    meta = mydata.meta()
    with st.expander(f"Your data: {meta.get('file')} ({meta.get('rows')} transactions)", icon=":material/lock:"):
        st.caption(PRIVACY)
        if meta.get("zetaris"):
            st.caption(f"Zetaris: {meta['zetaris']}.")
        c1, c2 = st.columns(2)
        if c1.button("Import a different file", key="imp_again", icon=":material/upload_file:"):
            mydata.clear()
            _dataset.clear()
            st.rerun()
        if c2.button("Remove my data", key="imp_remove", icon=":material/delete:", type="tertiary"):
            mydata.clear()
            _dataset.clear()
            st.session_state.data_mode = "maya"
            st.rerun()
