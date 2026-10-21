import streamlit as st
import pandas as pd

from client import BackendError, login, post_json

st.title("BI Agent")

if "messages" not in st.session_state:
    st.session_state.messages = []
    st.session_state.conversation_id = None

with st.sidebar:
    if st.button("New conversation"):
        st.session_state.messages = []
        st.session_state.conversation_id = None
        st.rerun()


def render_chart(spec, df):
    if not spec or spec.get("x") not in df.columns or spec.get("y") not in df.columns:
        return
    series = df.set_index(spec["x"])[spec["y"]]
    if spec["type"] == "line":
        st.line_chart(series)
    elif spec["type"] == "bar":
        st.bar_chart(series)


def show(msg):
    st.write(msg["answer"])
    if msg.get("interpreted_as") and msg["interpreted_as"] != msg["question"]:
        st.caption(f"Interpreted as: {msg['interpreted_as']}")
    with st.expander("SQL"):
        st.code(msg["sql"], language="sql")
    if msg["rows"]:
        df = pd.DataFrame(msg["rows"], columns=msg["columns"])
        st.dataframe(df, hide_index=True)
        render_chart(msg.get("chart"), df)


def ask(question):
    payload = {"message": question, "conversation_id": st.session_state.conversation_id}
    token = st.session_state.token
    try:
        return post_json("/ask", payload, token=token)
    except BackendError as e:
        if e.status_code == 404:
            st.info("The conversation was reset, so earlier context is gone.")
            st.session_state.conversation_id = None
            payload["conversation_id"] = None
            return post_json("/ask", payload, token=token)
        raise

for key, default in (("messages", []), ("conversation_id", None), ("token", None),
                     ("role", None), ("username", None)):
    st.session_state.setdefault(key, default)

if not st.session_state.token:
    with st.form("login"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Sign in")
    if submitted:
        try:
            data = login(username, password)
        except BackendError as e:
            st.error(str(e))
        else:
            st.session_state.token = data["access_token"]
            st.session_state.role = data["role"]
            st.session_state.username = username
            st.rerun()
    st.stop()


for m in st.session_state.messages:
    with st.chat_message(m["role"]):
        if m["role"] == "user":
            st.write(m["content"])
        else:
            show(m)

question = st.chat_input("Ask a question about your data")
if question:
    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.write(question)
    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            try:
                result = ask(question)
            except BackendError as e:
                if e.status_code == 401:
                    for key in ("token", "role", "username", "messages", "conversation_id"):
                        st.session_state[key] = None if key != "messages" else []
                    st.warning("Your session expired. Please sign in again.")
                    st.stop()
                st.error(str(e))
            else:
                st.session_state.conversation_id = result["conversation_id"]
                msg = {"role": "assistant", **result}
                st.session_state.messages.append(msg)
                show(msg)