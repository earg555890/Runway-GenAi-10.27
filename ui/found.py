"""Tab 3, "Findings": up to four cards, each a title and one sentence, with the proof one click away."""
from datetime import timedelta

import pandas as pd
import streamlit as st

import engine
from ui import fmt


def _proof(ds, key, row_ids, how):
    """The source records (exact cents), then "How we worked this out" as short bullets."""
    with st.expander("Show proof"):
        rows = []
        for rid in dict.fromkeys(row_ids):
            rec = ds.row(rid)
            d, what, amount = fmt.describe(rec)
            rows.append({"What": what, "Amount": amount, "Date": fmt.day(d) if d else "",
                         "Where": fmt.SOURCE_PLAIN[rec.source]})
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch", column_config=fmt.PROOF_COLUMNS)
        st.markdown("**How we worked this out**")
        st.markdown(fmt.md("\n".join(f"- {line}" for line in how)))
        if st.toggle("Details for nerds", key=f"nerd_{key}"):
            queries = {rid: [ev.query for ev in ds.evidence if rid in ev.row_ids] for rid in dict.fromkeys(row_ids)}
            st.dataframe(pd.DataFrame([{"row ID": rid, "source": ds.row(rid).source, "table": ds.row(rid).table,
                                        "query": ", ".join(q)} for rid, q in queries.items()]),
                         hide_index=True, width="stretch")


def _card(title, sentence):
    """The same card head as the check-in and Find money: a bold title, then one sentence."""
    st.markdown(f'<div class="rw-card-title">{fmt.html(title)}</div><div class="rw-card-text">{fmt.html(sentence)}</div>',
                unsafe_allow_html=True)


def refund(ds, scenario):
    f = engine.refund_status(scenario, ds, engine.Ledger())
    if not f:
        return
    c = f.computed
    with st.container(border=True, key="card_found_refund"):
        _card(f"Your {fmt.dollars(c['refund_amount'].value)} refund is on hold",
              "Financial aid needs your verification form first.")
        _proof(ds, "refund", [r for ids in f.row_ids.values() for r in ids], [
            f"Aid already paid: {fmt.money(c['aid_disbursed'].value)}.",
            f"Pell Grant on hold: {fmt.money(c['pell_held'].value)}.",
            f"Fall charges: {fmt.money(c['fall_charges'].value)}.",
            f"What's left over comes back to you: {fmt.money(c['refund_amount'].value)}.",
            f"The hold started {fmt.day(c['hold_since'].value)}.",
            f"After you send the form, it takes {c['release_rule_business_days'].value} business days. "
            f"That's around {fmt.day(c['release_date'].value)}."])


def leaks(ds, scenario):
    for i, leak in enumerate(engine.find_leaks(scenario, ds, engine.Ledger())):
        by = {c.label: c for c in leak.computed}
        with st.container(border=True, key=f"card_found_leak_{i}"):
            if leak.kind == "duplicate_subscriptions":
                monthly = [c for c in leak.computed if c.label.endswith("monthly cost")]
                names = [c.label.removesuffix(" monthly cost") for c in monthly]
                combined = next(c for c in leak.computed if c.label.startswith("combined"))
                savings = [c for c in leak.computed if c.label.startswith("cancel ")]
                _card(f"You pay for {len(names)} music apps",
                      f"That's {fmt.dollars(combined.value)} a month for {' and '.join(sorted(names, reverse=True))}.")
                _proof(ds, "music", leak.row_ids,
                       [f"{n}: {fmt.money(c.value)} a month." for n, c in zip(names, monthly)]
                       + [f"Together: {fmt.money(combined.value)} a month."]
                       + [f"Cancelling {c.label.split(':')[0].removeprefix('cancel ')} saves {fmt.money(c.value)} "
                          "this semester." for c in savings]
                       + ["A card charge only leaves checking when you pay the card bill."])
            else:
                fee = next(c for c in leak.computed if c.label.startswith("fee "))
                before = next(c for c in leak.computed if c.label.startswith("checking balance before"))
                after = next(c for c in leak.computed if c.label.startswith("checking balance after"))
                due = by.get("rent due day")
                pay_row = next(ds.row(r) for r in leak.row_ids
                               if ds.row(r).source == "checking" and getattr(ds.row(r), "category", "") == "income")
                _card(f"Rent caused a {fmt.dollars(fee.value)} overdraft fee",
                      f"Rent is due the {fmt.ordinal(due.value)}. Your paycheck came {fmt.day(pay_row.date)}."
                      if due else leak.title)
                _proof(ds, "fee", leak.row_ids, [
                    f"You had {fmt.money(before.value)} the night before rent.",
                    f"Rent took you to {fmt.money(-after.value)} below zero.",
                    f"The bank charged a {fmt.money(fee.value)} fee.",
                    f"Staying above zero could save about {fmt.dollars(leak.savings.value)} more (estimated)."])


def crunch(ds, scenario):
    for i, f in enumerate(engine.cash_crunches(scenario, ds, engine.Ledger())):
        c = f.computed
        due = c["installment_due"].value
        week = fmt.day(due - timedelta(days=due.weekday())).split(", ", 1)[1]
        with st.container(border=True, key=f"card_found_crunch_{i}"):
            _card(f"Money is tight the week of {week}",
                  f"A {fmt.dollars(c['installment'].value)} tuition payment is due right after a small paycheck.")
            notes = sorted({ds.row(i).note for i in c["scheduled_hours"].inputs
                            if i.startswith("SHF-") and ds.row(i).note})
            _proof(ds, "crunch", [r for ids in f.row_ids.values() for r in ids], [
                f"The payment is due {fmt.day(due)}.",
                f"Your {fmt.day(c['paycheck_date'].value)} paycheck covers only {c['scheduled_hours'].value} hours.",
                f"That's {fmt.money(c['paycheck_net'].value)} after tax.",
                f"A normal pay period has {c['normal_period_hours'].value} hours "
                f"({fmt.money(c['normal_net'].value)})."]
                + ([f"Your schedule says: {notes[0]}."] if notes else []))


def render(ds, scenario):
    """One column: short lines, and the proof tables get the full width."""
    if not ds.refunds and not ds.installments:
        st.caption("Connect your school data to see your financial aid, student account and work schedule here.")
    refund(ds, scenario)
    leaks(ds, scenario)
    crunch(ds, scenario)
