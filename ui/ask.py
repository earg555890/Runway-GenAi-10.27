"""Ask Runway: the answer area. A placeholder today; tomorrow render() gets an on_ask handler and an answer."""
import streamlit as st

SUGGESTED = ["Can I afford a $400 flight home for Thanksgiving?", "How long will my money last?",
             "Where is my money leaking?"]


def render(on_ask=None, answer=None):
    """on_ask(question) -> None runs PLAN + engine + EXPLAIN; answer is what to show. Both None = coming soon."""
    enabled = on_ask is not None
    with st.container(border=True):
        st.subheader("Ask Runway")
        with st.container(horizontal=True, gap="small"):
            for i, q in enumerate(SUGGESTED):
                st.button(q, key=f"ask_suggest_{i}", disabled=not enabled,
                          on_click=on_ask if enabled else None, args=(q,) if enabled else None)
        st.chat_input("Ask Runway anything (coming soon)" if not enabled else "Ask Runway anything",
                      key="ask_input", disabled=not enabled)
        if answer is not None:
            st.markdown(answer)
        elif not enabled:
            st.caption("Coming soon: answers written by NVIDIA Nemotron from the numbers above, with every claim "
                       "linked to its evidence.")
