import pandas as pd
import streamlit as st

import client
from charts import LABELS, build_figure
from client import BackendError
from presentation import is_declined, is_no_data, pretty_label, single_value, status_for

st.set_page_config(page_title="BI Agent", page_icon="📊", layout="wide")

BRAND = "BI Agent"
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
        st.markdown(f"## 📊 {BRAND}")
        st.markdown("Ask questions about your business data in plain English and get "
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
    if not msg.get("rows") and not msg.get("sql"):     # an answer about the data with nothing to list
        st.info(msg["answer"], icon="ℹ️")
        return

    st.markdown(f"##### {plain(msg['answer'])}")
    if msg.get("interpreted_as") and msg["interpreted_as"] != msg.get("question"):
        st.caption(f"Interpreted as: {plain(msg['interpreted_as'])}")
    if msg.get("chart_note"):
        st.info(msg["chart_note"], icon="ℹ️")
    card = single_value(msg["columns"], msg["rows"])
    if card:
        st.metric(card[0], card[1], border=True)

    spec = msg.get("chart") or {}
    offered = [o for o in spec.get("options") or [spec.get("type")] if o in LABELS]
    choice_key = f"chart-type-{index}"
    kind = st.session_state.get(choice_key) or spec.get("type")
    fig = None if card else build_figure(spec, msg["columns"], msg["rows"], kind=kind)
    labels = (["📊 Chart"] if fig else []) + ["🧾 Table"] + (["🧩 SQL"] if msg.get("sql") else [])
    tabs = dict(zip(labels, st.tabs(labels)))
    if fig:
        with tabs["📊 Chart"]:
            if len(offered) > 1:   # only the types the backend says fit this result
                st.selectbox("Chart type", offered, index=offered.index(kind), key=choice_key,
                             format_func=LABELS.get, width=220)
            st.plotly_chart(fig, width="stretch", key=f"chart-{index}",
                            config={"displaylogo": False})
            st.session_state._charts_drawn += 1   # lets the tests check what was redrawn, and when
    with tabs["🧾 Table"]:
        df = pd.DataFrame(msg["rows"], columns=[pretty_label(c) for c in msg["columns"]])
        st.dataframe(df, hide_index=True, width="stretch")
        if msg.get("truncated"):
            st.caption(f"Showing the first {len(msg['rows'])} rows.")
    if "🧩 SQL" in tabs:
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


# ---- Data catalog page (M29c) ----------------------------------------------------------------------

def ask_about(table):
    st.session_state.pending = f"Describe the {table} table"
    st.session_state.view = "Chat"


def _matches(table, text):
    if not text:
        return True
    text = text.lower()
    haystack = [table["name"], table["description"], table["domain"]] + \
        [c["name"] + " " + c["description"] for c in table["columns"]]
    return any(text in h.lower() for h in haystack)


def catalog_page():
    st.markdown("## Data catalog")
    st.caption("The tables and columns your role can query, with their meaning, keys and relationships. "
               "Columns with personal data are not shown.")
    try:
        data = client.get_json("/catalog", timeout=30, token=st.session_state.token)
    except BackendError as e:
        if e.status_code == 401:
            reset(keep_user=False)
            st.warning("Your session expired. Please sign in again.", icon="🔑")
            return
        show_status(status_for(e))
        return
    tables = data["tables"]
    areas = ["All business areas"] + list(dict.fromkeys(t["domain"] for t in tables))
    left, right = st.columns([2, 1])
    search = left.text_input("Search tables and columns", key="catalog-search",
                             placeholder="for example revenue, customer, status")
    area = right.selectbox("Business area", areas, key="catalog-area")
    shown = [t for t in tables if (area == areas[0] or t["domain"] == area) and _matches(t, search)]
    st.caption(f"{len(shown)} of {len(tables)} tables")
    for t in shown:
        with st.expander(f"{t['name']} · {t['domain']} · {t['description']}"):
            facts = [f"**Grain:** {t['grain']}" if t["grain"] else "",
                     f"**Primary key:** `{', '.join(t['primary_key'])}`" if t["primary_key"] else "",
                     f"**About {t['rows']:,} rows**" if t.get("rows") else ""]
            st.markdown("  \n".join(f for f in facts if f))
            if t["foreign_keys"]:
                st.markdown("**Points to:** " + ", ".join(f"`{f['column']}` → {f['table']}" for f in t["foreign_keys"]))
            if t["referenced_by"]:
                st.markdown("**Referenced by:** " + ", ".join(f"{r['table']}.`{r['column']}`" for r in t["referenced_by"]))
            for c in t["caveats"]:
                st.markdown(f"⚠️ {plain(c)}")
            rows = [[c["name"], c["type"], "PK" if c["primary_key"] else ("FK" if c.get("references") else ""),
                     c["description"] + (f" Values: {', '.join(c['values'])}." if c.get("values") else "")]
                    for c in t["columns"]]
            st.dataframe(pd.DataFrame(rows, columns=["Column", "Type", "Key", "Meaning"]), hide_index=True)
            st.button(f"Ask about {t['name']}", key=f"ask-{t['name']}", on_click=ask_about, args=(t["name"],))
    if data.get("metrics"):
        with st.expander("Governed metrics"):
            st.dataframe(pd.DataFrame([[m["name"], m["definition"], m["description"]] for m in data["metrics"]],
                                      columns=["Metric", "Definition", "Meaning"]), hide_index=True)


# ---- page ------------------------------------------------------------------------------------

if not st.session_state.token:
    sign_in_page()
    st.stop()

with st.sidebar:
    st.markdown(f"### 📊 {BRAND}")
    st.markdown(f"Signed in as **{st.session_state.username}**  \nRole: `{st.session_state.role}`")
    left, right = st.columns(2)
    if left.button("New chat", key="new-conversation", width="stretch"):
        reset()
        st.rerun()
    if right.button("Sign out", key="sign-out", width="stretch"):
        reset(keep_user=False)
        st.rerun()
    st.radio("View", ["Chat", "Data catalog"], key="view", horizontal=True)
    st.divider()
    st.markdown("**Try asking**")
    for i, q in enumerate(examples()):
        st.button(q, key=f"side-example-{i}", on_click=ask_later, args=(q,), width="stretch")

if st.session_state.get("view") == "Data catalog":
    catalog_page()
    st.stop()

st.markdown("## Ask your data")
st.markdown('<p class="brand-sub">Answers from your company data. Every query is checked before it runs.</p>',
            unsafe_allow_html=True)

# Draw everything already on screen before the slow backend call: Streamlit fades what it has
# not redrawn yet, so asking first would grey out the whole conversation while it thinks.
st.session_state._charts_drawn = 0
question = st.chat_input("Ask a question about your data") or st.session_state.pop("pending", None)

if not st.session_state.messages and not question:
    st.subheader("What would you like to know?")
    columns = st.columns(2)
    for i, q in enumerate(examples()):
        columns[i % 2].button(q, key=f"example-{i}", on_click=ask_later, args=(q,), width="stretch")

for i, m in enumerate(st.session_state.messages):
    with st.chat_message(m["role"], avatar="🧑" if m["role"] == "user" else "📊"):
        if m["role"] == "user":
            st.markdown(plain(m["content"]))
        else:
            show_answer(m, i)

if question:
    with st.chat_message("user", avatar="🧑"):
        st.markdown(plain(question))
    with st.chat_message("assistant", avatar="📊"):
        handle(question)
        show_answer(st.session_state.messages[-1], len(st.session_state.messages) - 1)
