import pandas as pd
import streamlit as st

import client
from charts import build_figure
from client import BackendError
from presentation import is_declined, is_no_data, pretty_label, single_value, status_for

st.set_page_config(page_title="Trailhead BI Agent", page_icon="🏔️", layout="wide")

BRAND = "Trailhead Outfitters"
EXAMPLES = {
    "analyst": [
        "What was revenue by region in September 2026?",
        "Show revenue by month",
        "Which region had the highest revenue in September 2026?",
        "How many orders were cancelled?",
    ],
    "limited": ["List the regions", "How many regions are there?"],
}
STATE = {"messages": [], "conversation_id": None, "token": None, "role": None, "username": None}

st.markdown("""
<style>
  .block-container {padding-top: 2rem; max-width: 1200px;}
  [data-testid="stChatMessage"] {border-radius: 12px;}
  .brand-sub {color: #5C6B63; margin-top: -0.6rem;}
</style>
""", unsafe_allow_html=True)

for key, default in STATE.items():
    st.session_state.setdefault(key, [] if key == "messages" else default)


def reset(keep_user=True):
    for key, default in STATE.items():
        if keep_user and key in ("token", "role", "username"):
            continue
        st.session_state[key] = [] if key == "messages" else default


def plain(text):
    """Streamlit markdown reads $...$ as maths; answers about money must show dollars."""
    return str(text).replace("$", r"\$")


def examples():
    return EXAMPLES.get(st.session_state.role, EXAMPLES["limited"])


def ask_later(question):
    st.session_state.pending = question


# ---- sign-in -------------------------------------------------------------------------------

def sign_in_page():
    _, middle, _ = st.columns([1, 1.3, 1])
    with middle, st.container(border=True):
        st.markdown(f"## 🏔️ {BRAND}")
        st.markdown("**BI Agent.** Ask questions about your business data in plain English and get "
                    "an answer, the SQL behind it, a table and a chart.")
        with st.form("login"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Sign in", type="primary", width="stretch")
        st.caption("Every query is checked and runs read-only with your role's permissions.")
    if submitted:
        try:
            data = client.login(username, password)
        except BackendError as e:
            st.error(str(e), icon="🔒")
        else:
            st.session_state.update(token=data["access_token"], role=data["role"], username=username)
            st.rerun()


# ---- answers -------------------------------------------------------------------------------

def show_status(status):
    getattr(st, status["kind"])(status["text"], icon=status["icon"])


def show_answer(msg, index):
    if msg.get("error"):
        show_status(msg["error"])
        return
    if is_declined(msg):
        st.info(msg["answer"], icon="💬")
        return
    if is_no_data(msg):
        st.info(msg["answer"], icon="📭")
        with st.expander("SQL"):
            st.code(msg["sql"], language="sql")
        return

    st.markdown(f"##### {plain(msg['answer'])}")
    if msg.get("interpreted_as") and msg["interpreted_as"] != msg.get("question"):
        st.caption(f"Interpreted as: {plain(msg['interpreted_as'])}")
    card = single_value(msg["columns"], msg["rows"])
    if card:
        st.metric(card[0], card[1], border=True)

    fig = None if card else build_figure(msg.get("chart"), msg["columns"], msg["rows"])
    labels = (["📊 Chart"] if fig else []) + ["🧾 Table", "🧩 SQL"]
    tabs = dict(zip(labels, st.tabs(labels)))
    if fig:
        with tabs["📊 Chart"]:
            st.plotly_chart(fig, width="stretch", key=f"chart-{index}",
                            config={"displaylogo": False})
    with tabs["🧾 Table"]:
        df = pd.DataFrame(msg["rows"], columns=[pretty_label(c) for c in msg["columns"]])
        st.dataframe(df, hide_index=True, width="stretch")
        if msg.get("truncated"):
            st.caption(f"Showing the first {len(msg['rows'])} rows.")
    with tabs["🧩 SQL"]:
        st.code(msg["sql"], language="sql")


def handle(question):
    st.session_state.messages.append({"role": "user", "content": question})
    payload = {"message": question, "conversation_id": st.session_state.conversation_id}
    with st.spinner("Thinking…"):
        try:
            try:
                result = client.post_json("/ask", payload, token=st.session_state.token)
            except BackendError as e:
                if e.status_code != 404:
                    raise
                st.info("The conversation was reset, so earlier context is gone.")
                st.session_state.conversation_id = payload["conversation_id"] = None
                result = client.post_json("/ask", payload, token=st.session_state.token)
        except BackendError as e:
            if e.status_code == 401:
                reset(keep_user=False)
                st.warning("Your session expired. Please sign in again.", icon="🔑")
                st.stop()
            st.session_state.messages.append({"role": "assistant", "error": status_for(e)})
            return
    st.session_state.conversation_id = result["conversation_id"]
    st.session_state.messages.append({"role": "assistant", **result})


# ---- page ------------------------------------------------------------------------------------

if not st.session_state.token:
    sign_in_page()
    st.stop()

with st.sidebar:
    st.markdown(f"### 🏔️ {BRAND}")
    st.markdown(f"Signed in as **{st.session_state.username}**  \nRole: `{st.session_state.role}`")
    left, right = st.columns(2)
    if left.button("New chat", key="new-conversation", width="stretch"):
        reset()
        st.rerun()
    if right.button("Sign out", key="sign-out", width="stretch"):
        reset(keep_user=False)
        st.rerun()
    st.divider()
    st.markdown("**Try asking**")
    for i, q in enumerate(examples()):
        st.button(q, key=f"side-example-{i}", on_click=ask_later, args=(q,), width="stretch")

st.markdown("## BI Agent")
st.markdown('<p class="brand-sub">Answers from your company data. Every query is checked before it runs.</p>',
            unsafe_allow_html=True)

question = st.chat_input("Ask a question about your data") or st.session_state.pop("pending", None)
if question:
    handle(question)

if not st.session_state.messages:
    st.subheader("What would you like to know?")
    columns = st.columns(2)
    for i, q in enumerate(examples()):
        columns[i % 2].button(q, key=f"example-{i}", on_click=ask_later, args=(q,), width="stretch")

for i, m in enumerate(st.session_state.messages):
    with st.chat_message(m["role"], avatar="🧑" if m["role"] == "user" else "🏔️"):
        if m["role"] == "user":
            st.markdown(plain(m["content"]))
        else:
            show_answer(m, i)
