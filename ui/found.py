"""Tab 3, "What we found": up to four short cards, each with a "Show proof" section."""
from datetime import timedelta

import pandas as pd
import streamlit as st

import engine
from ui import fmt


def _proof(ds, key, row_ids, how):
    with st.expander("Show proof"):
        rows = []
        for rid in dict.fromkeys(row_ids):
            rec = ds.row(rid)
            d, what, amount = fmt.describe(rec)
            rows.append({"Where": fmt.SOURCE_PLAIN[rec.source], "Date": fmt.day(d) if d else "", "What": what,
                         "Amount": amount})
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        st.markdown("**How we worked this out**")
        st.markdown(fmt.md(how))
        if st.toggle("Details for nerds", key=f"nerd_{key}"):
            queries = {rid: [ev.query for ev in ds.evidence if rid in ev.row_ids] for rid in dict.fromkeys(row_ids)}
            st.dataframe(pd.DataFrame([{"row ID": rid, "source": ds.row(rid).source, "table": ds.row(rid).table,
                                        "query": ", ".join(q)} for rid, q in queries.items()]),
                         hide_index=True, width="stretch")


def _card(title, sentence):
    st.markdown(f"#### {fmt.md(title)}")
    st.markdown(fmt.md(sentence))


def refund(ds, scenario):
    f = engine.refund_status(scenario, ds, engine.Ledger())
    if not f:
        return
    c = f.computed
    reqs = [ds.row(r) for r in f.row_ids[("aid", "requirements")]]
    form = reqs[0].description.split(" (")[0] if reqs else "a missing document"
    with st.container(border=True):
        _card(f"Your {fmt.money(c['refund_amount'].value)} refund is on hold",
              f"Financial aid is waiting for your verification form ({form}).")
        _proof(ds, "refund", [r for ids in f.row_ids.values() for r in ids],
               f"Your aid ({fmt.money(c['aid_disbursed'].value)} already paid plus your "
               f"{fmt.money(c['pell_held'].value)} Pell Grant on hold) is more than your fall charges "
               f"({fmt.money(c['fall_charges'].value)}); the difference, {fmt.money(c['refund_amount'].value)}, comes "
               f"back to you. The hold has been on since {fmt.day(c['hold_since'].value)}, and the refund is released "
               f"{c['release_rule_business_days'].value} business days after it clears: around "
               f"{fmt.day(c['release_date'].value)} if you send the form {fmt.day(scenario.submit_date)}.")


def leaks(ds, scenario):
    for leak in engine.find_leaks(scenario, ds, engine.Ledger()):
        by = {c.label: c for c in leak.computed}
        with st.container(border=True):
            if leak.kind == "duplicate_subscriptions":
                names = [c.label.removesuffix(" monthly cost") for c in leak.computed if c.label.endswith("monthly cost")]
                combined = next(c for c in leak.computed if c.label.startswith("combined"))
                pick = next(c for c in leak.computed if c.label.startswith("which"))
                _card(f"You pay for {len(names)} music apps",
                      f"{fmt.money(combined.value)} a month for {' and '.join(sorted(names, reverse=True))}.")
                _proof(ds, "music", leak.row_ids,
                       f"{combined.how} {pick.how.replace('saves checking', 'saves you')} A card charge only "
                       "leaves your checking account when you pay the card bill, so the timing matters.")
            else:
                fee = next(c for c in leak.computed if c.label.startswith("fee "))
                before = next(c for c in leak.computed if c.label.startswith("checking balance before"))
                after = next(c for c in leak.computed if c.label.startswith("checking balance after"))
                due = by.get("rent due day")
                pay_row = next(ds.row(r) for r in leak.row_ids
                               if ds.row(r).source == "checking" and getattr(ds.row(r), "category", "") == "income")
                _card(f"Rent caused a {fmt.money(fee.value)} overdraft fee",
                      f"Rent is due the {fmt.ordinal(due.value)} but your paycheck came {fmt.day(pay_row.date)}."
                      if due else leak.title)
                _proof(ds, "fee", leak.row_ids,
                       f"You had {fmt.money(before.value)} the night before. Rent took your balance to "
                       f"{fmt.money(after.value)}, so the bank charged {fmt.money(fee.value)}. Estimated: staying "
                       f"above $0 could save you about {fmt.money(leak.savings.value)} in fees by the end of the "
                       "semester (estimated).")


def crunch(ds, scenario):
    for f in engine.cash_crunches(scenario, ds, engine.Ledger()):
        c = f.computed
        due = c["installment_due"].value
        with st.container(border=True):
            _card(f"Money is tight the week of {fmt.day(due - timedelta(days=due.weekday())).split(' ', 1)[1]}",
                  f"A {fmt.money(c['installment'].value)} tuition payment is due {fmt.day(due)}, right after a small "
                  f"paycheck ({fmt.money(c['paycheck_net'].value)} on {fmt.day(c['paycheck_date'].value)}).")
            notes = sorted({ds.row(i).note for i in c["scheduled_hours"].inputs
                            if i.startswith("SHF-") and ds.row(i).note})
            _proof(ds, "crunch", [r for ids in f.row_ids.values() for r in ids],
                   f"That paycheck covers only {c['scheduled_hours'].value} hours of shifts; a normal one covers "
                   f"{c['normal_period_hours'].value} hours ({fmt.money(c['normal_net'].value)}). "
                   + c["paycheck_net"].how + (f" Your schedule says: {notes[0]}." if notes else ""))


def render(ds, scenario):
    left, right = st.columns(2)
    with left:
        refund(ds, scenario)
        crunch(ds, scenario)
    with right:
        leaks(ds, scenario)
