"""Finding cards: held refund, leaks (duplicate subscriptions, overdraft fee), cash crunch."""
import streamlit as st

import config
import engine
from ui import fmt


def _refund(ds, scenario):
    f = engine.refund_status(scenario, ds, engine.Ledger())
    if not f:
        return
    c = f.computed
    hold = ds.row(f.row_ids[("bursar", "holds")][0]) if f.row_ids[("bursar", "holds")] else None
    reqs = [ds.row(r) for r in f.row_ids[("aid", "requirements")]]
    with st.container(border=True):
        st.markdown("#### :material/lock_clock: Your refund is on hold")
        st.metric("Held refund", fmt.money(c["refund_amount"].value))
        st.markdown(f"**Why:** your {fmt.money(c['pell_held'].value)} Pell Grant can't be paid until the aid office "
                    f"gets {', '.join(r.description for r in reqs) or 'a missing document'}"
                    + (f", and the {hold.description.lower()} hold (since {fmt.day(c['hold_since'].value)}) "
                       "blocks refunds." if hold else "."))
        st.markdown(f"**What unblocks it:** submit the form. The refund is released "
                    f"{c['release_rule_business_days'].value} business days after the hold clears: "
                    f"{fmt.day(c['release_date'].value)} if you submit it {fmt.day(scenario.submit_date)}.")
        st.caption(f"Fall charges {fmt.money(c['fall_charges'].value)}; aid already paid "
                   f"{fmt.money(c['aid_disbursed'].value)}.")


def _leaks(ds, scenario):
    for leak in engine.find_leaks(scenario, ds, engine.Ledger()):
        with st.container(border=True):
            if leak.kind == "duplicate_subscriptions":
                monthly = [c for c in leak.computed if c.label.endswith("monthly cost")]
                combined = next(c for c in leak.computed if c.label.startswith("combined"))
                pick = next(c for c in leak.computed if c.label.startswith("which"))
                savings = [c for c in leak.computed if c.label.startswith("cancel ")]
                st.markdown("#### :material/library_music: Two music subscriptions")
                st.markdown(" + ".join(f"{c.label.removesuffix(' monthly cost')} {fmt.money(c.value)}" for c in monthly)
                            + f" = **{fmt.money(combined.value)} a month** for the same thing.")
                st.markdown(f"**Cancel {pick.value}.** "
                            + "; ".join(f"{c.label.split(':')[0].removeprefix('cancel ')} saves "
                                        f"{fmt.money(c.value)} before {fmt.day(config.SEMESTER_END)}" for c in savings)
                            + ".")
                st.caption("Timing matters: a credit-card charge only reaches checking when the card bill is paid.")
            else:
                fee = next(c for c in leak.computed if c.label.startswith("fee "))
                before = next((c for c in leak.computed if c.label.startswith("checking balance before")), None)
                after = next((c for c in leak.computed if c.label.startswith("checking balance after")), None)
                pay = next((c for c in leak.computed if c.label.startswith("next paycheck")), None)
                est = leak.savings
                st.markdown(f"#### :material/money_off: {fmt.money(fee.value)} overdraft fee")
                st.markdown(leak.title.split(": ", 1)[-1].capitalize() + "."
                            + (f" Checking had {fmt.money(before.value)} the night before and dropped to "
                               f"{fmt.money(after.value)}." if before and after else "")
                            + (f" The next paycheck ({fmt.money(pay.value)}) arrived a day too late." if pay else ""))
                st.markdown(f"**Estimated** fees you could avoid by {fmt.day(config.SEMESTER_END)}: "
                            f"{fmt.money(est.value)} (estimated)")
                st.caption(est.how)


def _crunch(ds, scenario):
    for f in engine.cash_crunches(scenario, ds, engine.Ledger()):
        c = f.computed
        with st.container(border=True):
            st.markdown("#### :material/event_busy: Tight week in November")
            st.markdown(f"The {fmt.money(c['installment'].value)} payment-plan installment is due "
                        f"{fmt.day(c['installment_due'].value)}, the same week as the {fmt.day(c['paycheck_date'].value)} "
                        f"paycheck, which covers only {c['scheduled_hours'].value} hours "
                        f"(a normal pay period is {c['normal_period_hours'].value} hours).")
            st.markdown(f"That paycheck is **{fmt.money(c['paycheck_net'].value)}**, vs "
                        f"{fmt.money(c['normal_net'].value)} in a normal pay period.")
            notes = sorted({ds.row(i).note for i in c["scheduled_hours"].inputs if i.startswith("SHF-") and ds.row(i).note})
            if notes:
                st.caption("Shift schedule note: " + "; ".join(notes))


def render(ds, scenario):
    st.subheader("What Runway found")
    left, right = st.columns(2)
    with left:
        _refund(ds, scenario)
        _crunch(ds, scenario)
    with right:
        _leaks(ds, scenario)
