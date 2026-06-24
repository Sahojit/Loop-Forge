import time
import requests
import streamlit as st

API_BASE = "http://localhost:8010"

st.set_page_config(page_title="LoopForge", layout="wide", initial_sidebar_state="expanded")


# ── HTTP helpers ──────────────────────────────────────────────────────────────

def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _post(path: str, payload: dict, token: str | None = None) -> dict:
    h = _headers(token) if token else {}
    try:
        r = requests.post(f"{API_BASE}{path}", json=payload, headers=h, timeout=30)
        return r.json()
    except Exception as e:
        return {"error": str(e)}


def _get(path: str, token: str, params: dict | None = None) -> dict:
    try:
        r = requests.get(f"{API_BASE}{path}", headers=_headers(token), params=params, timeout=15)
        return r.json()
    except Exception as e:
        return {"error": str(e)}


def _patch(path: str, token: str) -> dict:
    try:
        r = requests.patch(f"{API_BASE}{path}", headers=_headers(token), timeout=15)
        return r.json()
    except Exception as e:
        return {"error": str(e)}


def _delete(path: str, token: str) -> int:
    try:
        r = requests.delete(f"{API_BASE}{path}", headers=_headers(token), timeout=15)
        return r.status_code
    except Exception:
        return 500


# ── Auth pages ────────────────────────────────────────────────────────────────

def login_page():
    st.title("LoopForge")
    st.caption("Loop Engineering Agentic AI Platform")

    tab_login, tab_register = st.tabs(["Login", "Register"])

    with tab_login:
        with st.form("login"):
            email = st.text_input("Email")
            password = st.text_input("Password", type="password")
            if st.form_submit_button("Login", use_container_width=True):
                result = _post("/auth/login", {"email": email, "password": password})
                if "access_token" in result:
                    st.session_state["access_token"] = result["access_token"]
                    st.session_state["refresh_token"] = result["refresh_token"]
                    st.session_state["logged_in"] = True
                    st.rerun()
                else:
                    st.error("Invalid credentials")

    with tab_register:
        with st.form("register"):
            reg_email = st.text_input("Email", key="re")
            reg_pass = st.text_input("Password (min 8 chars)", type="password", key="rp")
            if st.form_submit_button("Register", use_container_width=True):
                result = _post("/auth/register", {"email": reg_email, "password": reg_pass})
                if "user_id" in result:
                    st.success("Registered! Please log in.")
                else:
                    st.error(result.get("error", "Registration failed"))


# ── Sidebar nav ───────────────────────────────────────────────────────────────

def sidebar_nav() -> str:
    with st.sidebar:
        st.title("LoopForge")
        page = st.radio(
            "Navigate",
            ["Tasks", "Skills", "Loops", "Hooks", "Notifications", "History"],
            label_visibility="collapsed",
        )
        st.divider()
        if st.button("Logout", use_container_width=True):
            st.session_state.clear()
            st.rerun()
    return page


# ── Tasks page ────────────────────────────────────────────────────────────────

def tasks_page(token: str):
    st.header("Run a Task")

    strategy = st.radio("Strategy", ["auto", "fast", "thorough"], horizontal=True)
    with st.form("task_form"):
        task_input = st.text_area("Task Input", height=140, max_chars=2000)
        max_iter = st.slider("Max Iterations", 1, 5, 3) if strategy == "auto" else None
        if st.form_submit_button("Run Task", use_container_width=True):
            payload = {"input": task_input, "strategy": strategy}
            if max_iter:
                payload["max_iterations"] = max_iter
            result = _post("/tasks/run-task", payload, token=token)
            if "task_id" in result:
                st.session_state["current_task_id"] = result["task_id"]
                st.session_state["score_history"] = []
            else:
                st.error(result.get("error", "Failed to submit"))

    if "current_task_id" in st.session_state:
        task_id = st.session_state["current_task_id"]
        st.divider()
        st.subheader(f"Task `{task_id[:8]}…`")
        status_box = st.empty()
        chart_box = st.empty()
        output_box = st.empty()

        with st.spinner("Running loop…"):
            while True:
                data = _get(f"/tasks/task/{task_id}", token)
                scores = data.get("score_history", [])
                if scores:
                    chart_box.line_chart({"Score": scores})
                status_box.markdown(
                    f"**Status:** `{data.get('status','running')}` | "
                    f"**Iter:** {data.get('iterations',0)} | "
                    f"**Score:** {data.get('final_score') or '…'}"
                )
                if data.get("status") in ("converged", "max_iter_reached", "failed"):
                    break
                time.sleep(3)

        st.divider()
        c1, c2, c3 = st.columns(3)
        c1.metric("Final Score", f"{data.get('final_score', 0):.2f}" if data.get("final_score") else "N/A")
        c2.metric("Iterations", data.get("iterations", 0))
        c3.metric("Tokens", data.get("tokens_used", 0))

        if data.get("final_output"):
            output_box.markdown(f"### Output\n{data['final_output']}")
        if st.button("Clear"):
            del st.session_state["current_task_id"]
            st.rerun()


# ── Skills page ───────────────────────────────────────────────────────────────

def skills_page(token: str):
    st.header("Skills")
    tab_list, tab_create, tab_search = st.tabs(["My Skills", "Create", "Search"])

    with tab_list:
        data = _get("/skills", token)
        skills = data.get("skills", [])
        if not skills:
            st.info("No skills yet. Create one →")
        for s in skills:
            with st.expander(f"**{s['name']}** — v{s.get('version',1)}"):
                st.caption(s.get("description", ""))
                if s.get("tool_tags"):
                    st.write("Tools:", ", ".join(s["tool_tags"]))
                col1, col2 = st.columns(2)
                if col1.button("Test render", key=f"test_{s['id']}"):
                    res = _post(f"/skills/{s['id']}/test", {}, token=token)
                    if res.get("success"):
                        st.code(res["rendered_prompt"], language="markdown")
                    else:
                        st.error(res.get("error"))
                if col2.button("Delete", key=f"del_{s['id']}"):
                    _delete(f"/skills/{s['id']}", token)
                    st.rerun()

    with tab_create:
        with st.form("create_skill"):
            name = st.text_input("Skill Name")
            desc = st.text_area("Description", height=80)
            template = st.text_area(
                "Prompt Template (Jinja2)",
                height=200,
                placeholder="Today is {{ date_today }}.\n\nTask: {{ user_input }}\n\nRecent emails: {{ emails }}"
            )
            tags = st.text_input("Tool tags (comma-separated)", placeholder="tavily, calculator")
            is_public = st.checkbox("Make public")
            if st.form_submit_button("Create Skill", use_container_width=True):
                tag_list = [t.strip() for t in tags.split(",") if t.strip()]
                res = _post("/skills", {
                    "name": name, "description": desc,
                    "prompt_template": template, "tool_tags": tag_list, "is_public": is_public,
                }, token=token)
                if "skill_id" in res:
                    st.success(f"Skill created: {res['skill_id']}")
                else:
                    st.error(res.get("error", "Failed"))

    with tab_search:
        q = st.text_input("Search skills", placeholder="research news summarize")
        if q:
            res = _get("/skills/search", token, params={"q": q})
            for hit in res.get("results", []):
                st.write(f"**{hit.get('skill_name')}** — {hit.get('document', '')[:100]}")


# ── Loops page ────────────────────────────────────────────────────────────────

def loops_page(token: str):
    st.header("Loops")
    tab_list, tab_create = st.tabs(["My Loops", "Create"])

    with tab_list:
        data = _get("/loops", token)
        for lp in data.get("loops", []):
            status_icon = "🟢" if lp["is_active"] else "⚪"
            with st.expander(f"{status_icon} **{lp['name']}** — `{lp['cron_expression']}`"):
                st.caption(lp.get("description", ""))
                st.write(f"Next run: `{lp.get('next_run_at') or 'not scheduled'}`")
                st.write(f"Last run: `{lp.get('last_run_at') or 'never'}`")

                c1, c2, c3, c4 = st.columns(4)
                if lp["is_active"]:
                    if c1.button("Deactivate", key=f"deact_{lp['id']}"):
                        _patch(f"/loops/{lp['id']}/deactivate", token)
                        st.rerun()
                else:
                    if c1.button("Activate", key=f"act_{lp['id']}"):
                        _patch(f"/loops/{lp['id']}/activate", token)
                        st.rerun()
                if c2.button("Trigger now", key=f"trig_{lp['id']}"):
                    res = _post(f"/loops/{lp['id']}/trigger", {}, token=token)
                    st.toast(res.get("message", "Triggered"))
                if c3.button("History", key=f"hist_{lp['id']}"):
                    st.session_state["view_loop_history"] = lp["id"]
                if c4.button("Delete", key=f"dellp_{lp['id']}"):
                    _delete(f"/loops/{lp['id']}", token)
                    st.rerun()

        if "view_loop_history" in st.session_state:
            loop_id = st.session_state["view_loop_history"]
            st.divider()
            st.subheader("Loop Run History")
            hist = _get(f"/loops/{loop_id}/history", token)
            runs = hist.get("runs", [])
            if runs:
                scores = [r.get("final_score") or 0 for r in runs]
                st.line_chart({"Score": scores})
                for r in runs:
                    st.write(
                        f"`{r['status']}` | score={r.get('final_score') or 'N/A'} "
                        f"| iter={r.get('iterations',0)} | {r.get('started_at','')[:19]}"
                    )
            else:
                st.info("No runs yet")

    with tab_create:
        skills_data = _get("/skills", token)
        skill_options = {s["name"]: s["id"] for s in skills_data.get("skills", [])}

        with st.form("create_loop"):
            name = st.text_input("Loop Name")
            desc = st.text_area("Description", height=60)
            skill_name = st.selectbox("Skill", ["(none)"] + list(skill_options.keys()))
            st.markdown("**Cron Schedule**")
            col_m, col_h, col_d, col_mo, col_dw = st.columns(5)
            minute = col_m.text_input("Minute", "0")
            hour = col_h.text_input("Hour", "9")
            day = col_d.text_input("Day", "*")
            month = col_mo.text_input("Month", "*")
            weekday = col_dw.text_input("Weekday", "*")
            tz = st.selectbox("Timezone", ["UTC", "Asia/Kolkata", "America/New_York", "Europe/London", "Asia/Tokyo"])
            max_iter = st.slider("Max Iterations", 1, 5, 3)

            if st.form_submit_button("Create Loop", use_container_width=True):
                cron = f"{minute} {hour} {day} {month} {weekday}"
                payload = {
                    "name": name, "description": desc,
                    "cron_expression": cron, "timezone": tz,
                    "max_iterations": max_iter,
                }
                if skill_name != "(none)":
                    payload["skill_id"] = skill_options[skill_name]
                res = _post("/loops", payload, token=token)
                if "loop_id" in res:
                    st.success(f"Loop created: {res['loop_id']}")
                else:
                    st.error(res.get("error", "Failed"))


# ── Hooks page ────────────────────────────────────────────────────────────────

def hooks_page(token: str):
    st.header("Hooks")
    tab_list, tab_create = st.tabs(["My Hooks", "Create"])

    with tab_list:
        data = _get("/hooks", token)
        for h in data.get("hooks", []):
            with st.expander(f"**{h['event']}** → `{h['action']}`"):
                st.write(f"Loop: `{h.get('loop_id') or 'any'}`")
                st.write(f"Active: {h.get('is_active')}")
                c1, c2 = st.columns(2)
                if c1.button("Test", key=f"testhk_{h['id']}"):
                    res = _post(f"/hooks/{h['id']}/test", {}, token=token)
                    st.write(res)
                if c2.button("Delete", key=f"delhk_{h['id']}"):
                    _delete(f"/hooks/{h['id']}", token)
                    st.rerun()

    with tab_create:
        loops_data = _get("/loops", token)
        loop_options = {"(global)": None} | {lp["name"]: lp["id"] for lp in loops_data.get("loops", [])}

        with st.form("create_hook"):
            loop_name = st.selectbox("Loop", list(loop_options.keys()))
            event = st.selectbox("Event", ["PostRun", "OnFailure", "OnConverge", "OnMaxIter", "OnBudgetExceeded"])
            action = st.selectbox("Action", ["notify", "webhook", "log"])
            if action == "webhook":
                url = st.text_input("Webhook URL")
                secret = st.text_input("Signing Secret", type="password")
                config = {"url": url, "secret": secret}
            elif action == "notify":
                channel = st.selectbox("Channel", ["telegram", "slack", "email"])
                config = {"channel": channel}
            else:
                config = {}

            if st.form_submit_button("Create Hook", use_container_width=True):
                payload = {
                    "loop_id": loop_options[loop_name],
                    "event": event, "action": action, "config": config,
                }
                res = _post("/hooks", payload, token=token)
                if "hook_id" in res:
                    st.success(f"Hook created: {res['hook_id']}")
                else:
                    st.error(res.get("error", "Failed"))


# ── Notifications page ────────────────────────────────────────────────────────

def notifications_page(token: str):
    st.header("Notifications")
    tab_config, tab_log = st.tabs(["Configuration", "Delivery Log"])

    with tab_config:
        existing = _get("/notifications/config", token)
        configured = {c["channel"] for c in existing.get("configs", [])}
        if configured:
            st.success(f"Configured channels: {', '.join(configured)}")

        st.subheader("Telegram")
        with st.form("tg_form"):
            bot_token = st.text_input("Bot Token", type="password")
            chat_id = st.text_input("Chat ID")
            if st.form_submit_button("Save Telegram Config"):
                res = _post("/notifications/config", {
                    "channel": "telegram", "config": {"bot_token": bot_token, "chat_id": chat_id}
                }, token=token)
                st.success(res.get("message")) if "config_id" in res else st.error(res.get("error"))
        if "telegram" in configured:
            if st.button("Test Telegram"):
                res = _post("/notifications/test", {}, token=token)
                st.write(res)

        st.subheader("Slack")
        with st.form("slack_form"):
            slack_token = st.text_input("Bot Token", type="password", key="slk_t")
            channel = st.text_input("Channel", placeholder="#loop-alerts")
            if st.form_submit_button("Save Slack Config"):
                res = _post("/notifications/config", {
                    "channel": "slack", "config": {"bot_token": slack_token, "channel": channel}
                }, token=token)
                st.success(res.get("message")) if "config_id" in res else st.error(res.get("error"))
        if "slack" in configured:
            if st.button("Test Slack"):
                res = _post("/notifications/test", {}, token=token)
                st.write(res)

        st.subheader("Email (SendGrid)")
        with st.form("email_form"):
            sg_key = st.text_input("SendGrid API Key", type="password")
            recipient = st.text_input("Recipient Email")
            if st.form_submit_button("Save Email Config"):
                res = _post("/notifications/config", {
                    "channel": "email", "config": {"sendgrid_api_key": sg_key, "recipient": recipient}
                }, token=token)
                st.success(res.get("message")) if "config_id" in res else st.error(res.get("error"))

    with tab_log:
        log_data = _get("/notifications/log", token)
        logs = log_data.get("log", [])
        if not logs:
            st.info("No notifications sent yet.")
        for entry in logs:
            icon = "✅" if entry["status"] == "sent" else ("❌" if entry["status"] == "failed" else "⏳")
            st.write(f"{icon} `{entry['channel']}` — {entry['status']} — attempts: {entry['attempt_count']} — {entry.get('created_at','')[:19]}")


# ── History page ──────────────────────────────────────────────────────────────

def history_page(token: str):
    st.header("Loop Run History")

    col1, col2 = st.columns(2)
    status_filter = col1.selectbox("Status", ["all", "converged", "max_iter_reached", "failed", "running"])
    page = col2.number_input("Page", min_value=1, value=1, step=1)

    loops_data = _get("/loops", token)
    all_loops = {lp["id"]: lp["name"] for lp in loops_data.get("loops", [])}

    if not all_loops:
        st.info("No loops created yet.")
        return

    selected_loop = st.selectbox("Loop", list(all_loops.values()))
    loop_id = [k for k, v in all_loops.items() if v == selected_loop][0]

    hist = _get(f"/loops/{loop_id}/history", token, params={"page": page, "page_size": 20})
    runs = hist.get("runs", [])

    if not runs:
        st.info("No runs for this loop yet.")
        return

    filtered = runs if status_filter == "all" else [r for r in runs if r.get("status") == status_filter]

    scores = [r.get("final_score") or 0 for r in filtered if r.get("final_score")]
    if scores:
        st.line_chart({"Score": scores})

    for r in filtered:
        status_icon = {"converged": "✅", "max_iter_reached": "⚠️", "failed": "❌", "running": "🔄"}.get(r["status"], "❓")
        with st.expander(f"{status_icon} `{r['status']}` — score={r.get('final_score') or 'N/A'} — {r.get('started_at','')[:19]}"):
            st.write(f"Iterations: {r.get('iterations', 0)} | Tokens: {r.get('tokens_used', 0)}")
            if r.get("score_history"):
                st.line_chart({"Score": r["score_history"]})
            if r.get("final_output"):
                st.markdown(f"**Output:**\n{r['final_output']}")
            if r.get("hooks_fired"):
                st.caption(f"Hooks fired: {', '.join(r['hooks_fired'])}")

    st.caption(f"Total runs: {hist.get('total', 0)} | Page {page}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    if not st.session_state.get("logged_in"):
        login_page()
        return

    token = st.session_state.get("access_token", "")
    page = sidebar_nav()

    if page == "Tasks":
        tasks_page(token)
    elif page == "Skills":
        skills_page(token)
    elif page == "Loops":
        loops_page(token)
    elif page == "Hooks":
        hooks_page(token)
    elif page == "Notifications":
        notifications_page(token)
    elif page == "History":
        history_page(token)


if __name__ == "__main__":
    main()
