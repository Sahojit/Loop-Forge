import time
import requests
import streamlit as st

API_BASE = "http://localhost:8010"

st.set_page_config(page_title="LoopForge", layout="wide")


def _api_post(path: str, payload: dict, token: str | None = None) -> dict:
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    resp = requests.post(f"{API_BASE}{path}", json=payload, headers=headers, timeout=30)
    return resp.json()


def _api_get(path: str, token: str) -> dict:
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.get(f"{API_BASE}{path}", headers=headers, timeout=15)
    return resp.json()


def login_page():
    st.title("LoopForge — Login")
    with st.form("login_form"):
        email = st.text_input("Email")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Login")

    if submitted:
        result = _api_post("/auth/login", {"email": email, "password": password})
        if "access_token" in result:
            st.session_state["access_token"] = result["access_token"]
            st.session_state["refresh_token"] = result["refresh_token"]
            st.session_state["logged_in"] = True
            st.rerun()
        else:
            st.error("Login failed. Check your credentials.")

    st.markdown("---")
    st.subheader("New user? Register")
    with st.form("register_form"):
        reg_email = st.text_input("Email", key="reg_email")
        reg_pass = st.text_input("Password (min 8 chars)", type="password", key="reg_pass")
        reg_submit = st.form_submit_button("Register")

    if reg_submit:
        result = _api_post("/auth/register", {"email": reg_email, "password": reg_pass})
        if "user_id" in result:
            st.success("Registered! Please log in.")
        else:
            st.error(result.get("error", "Registration failed"))


def task_page():
    token = st.session_state.get("access_token", "")

    st.title("LoopForge — Loop Engineering Agent")

    _, col2 = st.columns([3, 1])
    with col2:
        if st.button("Logout"):
            st.session_state.clear()
            st.rerun()

    st.subheader("Submit a Task")

    strategy = st.radio(
        "Loop Strategy",
        options=["auto", "fast", "thorough"],
        horizontal=True,
        help="fast=2 iterations, thorough=max iterations, auto=meta loop decides",
    )

    max_iter_map = {"fast": 2, "thorough": 5, "auto": None}
    iteration_label = "Max iterations" if strategy == "auto" else f"Fixed: {max_iter_map[strategy]}"

    with st.form("task_form"):
        task_input = st.text_area("Task Input", height=150, max_chars=2000)
        if strategy == "auto":
            max_iterations = st.slider("Max Iterations", min_value=1, max_value=5, value=3)
        else:
            max_iterations = max_iter_map[strategy]
            st.info(f"{iteration_label}")
        submitted = st.form_submit_button("Run Task")

    if submitted and task_input.strip():
        payload = {
            "input": task_input,
            "strategy": strategy,
            "max_iterations": max_iterations,
        }
        result = _api_post("/tasks/run-task", payload, token=token)

        if "task_id" in result:
            st.session_state["current_task_id"] = result["task_id"]
            st.session_state["score_history"] = []
            st.success(f"Task submitted: `{result['task_id']}`")
        else:
            st.error(result.get("error", "Failed to submit task"))

    if "current_task_id" in st.session_state:
        task_id = st.session_state["current_task_id"]
        st.markdown("---")
        st.subheader(f"Task Progress — `{task_id}`")

        status_placeholder = st.empty()
        score_chart_placeholder = st.empty()
        output_placeholder = st.empty()

        with st.spinner("Running loop..."):
            while True:
                status = _api_get(f"/tasks/task/{task_id}", token)

                current_scores = status.get("score_history", [])
                if current_scores:
                    st.session_state["score_history"] = current_scores
                    score_chart_placeholder.line_chart(
                        {"Score": current_scores},
                        use_container_width=True,
                    )

                task_status = status.get("status", "running")
                iterations = status.get("iterations", 0)
                final_score = status.get("final_score")

                status_placeholder.markdown(
                    f"**Status:** `{task_status}` | "
                    f"**Iterations:** {iterations} | "
                    f"**Score:** {final_score or 'pending'}"
                )

                if task_status in ("converged", "max_iter_reached", "failed"):
                    break

                time.sleep(3)

        st.markdown("---")
        st.subheader("Result")

        convergence = status.get("convergence_status", "unknown")
        final_score = status.get("final_score")
        tokens = status.get("tokens_used", 0)
        tools = status.get("tools_used", [])
        iterations = status.get("iterations", 0)

        col_a, col_b, col_c = st.columns(3)
        col_a.metric("Final Score", f"{final_score:.2f}" if final_score else "N/A")
        col_b.metric("Iterations", iterations)
        col_c.metric("Tokens Used", tokens)

        if tools:
            st.caption(f"Tools used: {', '.join(tools)}")

        if convergence == "converged":
            st.success("Converged successfully")
        elif convergence == "max_iter_reached":
            st.warning("Max iterations reached")
        elif convergence == "failed":
            st.error("Task failed")

        final_output = status.get("final_output")
        if final_output:
            output_placeholder.markdown("### Final Output")
            output_placeholder.write(final_output)
        else:
            output_placeholder.info("Output not yet available.")

        if st.session_state.get("score_history"):
            st.subheader("Score History")
            st.line_chart({"Score per Iteration": st.session_state["score_history"]})

        if st.button("Clear Task"):
            del st.session_state["current_task_id"]
            st.session_state.pop("score_history", None)
            st.rerun()


def main():
    if not st.session_state.get("logged_in"):
        login_page()
    else:
        task_page()


if __name__ == "__main__":
    main()
