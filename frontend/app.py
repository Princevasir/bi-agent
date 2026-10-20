import streamlit as st

from client import BackendError, post_json

st.title("BI Agent")

if "messages" not in st.session_state:
    st.session_state.messages = []
    st.session_state.conversation_id = None

with st.sidebar:
    if st.button("New conversation"):
        st.session_state.messages = []
        st.session_state.conversation_id = None
        st.rerun()


def show(msg):
    st.write(msg["answer"])
    if msg.get("interpreted_as") and msg["interpreted_as"] != msg["question"]:
        st.caption(f"Interpreted as: {msg['interpreted_as']}")
    with st.expander("SQL"):
        st.code(msg["sql"], language="sql")


def ask(question):
    payload = {"message": question, "conversation_id": st.session_state.conversation_id}
    try:
        return post_json("/ask", payload)
    except BackendError as e:
        if e.status_code == 404:
            st.info("The conversation was reset, so earlier context is gone.")
            st.session_state.conversation_id = None
            payload["conversation_id"] = None
            return post_json("/ask", payload)
        raise


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
                st.error(str(e))
            else:
                st.session_state.conversation_id = result["conversation_id"]
                msg = {"role": "assistant", **result}
                st.session_state.messages.append(msg)
                show(msg)