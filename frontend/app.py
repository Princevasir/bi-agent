import streamlit as st

from client import BackendError, get_json

st.title("BI Agent")

if st.button("Call backend"):
    with st.spinner("Calling backend..."):
        try:
            st.success(get_json("/hello")["message"])
        except BackendError as e:
            st.error(str(e))