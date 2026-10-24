"""Ask Runway: the answer area under the status sentence. Disabled today; tomorrow render() gets an
on_ask handler (question -> None) and the answer to show."""
import streamlit as st

SUGGESTED = ["Can I afford a $400 flight home for Thanksgiving?", "How long will my money last?",
             "Where is my money leaking?"]


def render(on_ask=None, answer=None):
    enabled = on_ask is not None
    with st.container():                      # inside a container the input stays here, not pinned to the bottom
        st.chat_input("Ask Runway anything" if enabled else "Ask Runway anything (coming soon)",
                      key="ask_input", disabled=not enabled)
    if answer is not None:
        st.markdown(answer)
