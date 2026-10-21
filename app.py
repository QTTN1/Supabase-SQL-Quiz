import os

import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from postgrest.exceptions import APIError
from psycopg2 import Error as PostgresError
from supabase import create_client
from supabase_auth.errors import AuthApiError

from quiz import QUESTIONS, grade_query, run_read_query


load_dotenv()

st.set_page_config(page_title="Makeup SQL Quiz", page_icon="💄", layout="wide")

st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=DM+Serif+Display&family=Nunito+Sans:wght@400;500;600;700&display=swap');

    :root {
        --quiz-pink: #fff3f6;
        --quiz-mint: #e8f7f1;
        --quiz-aqua: #58a994;
        --quiz-yellow: #fff1b8;
        --quiz-ink: #3d2932;
    }

    [data-testid="stAppViewContainer"] {
        background:
            radial-gradient(ellipse at 8% 0%, #ffe2eb 0, transparent 34rem),
            linear-gradient(145deg, var(--quiz-pink), #fffaf0 58%, #eefaf5);
        color: var(--quiz-ink);
    }

    .stApp {
        font-family: "Nunito Sans", "Segoe UI", sans-serif;
    }

    [data-testid="stHeader"] {
        background: rgba(255, 243, 246, 0.82);
    }

    [data-testid="stMainBlockContainer"] {
        max-width: 1120px;
        padding-top: 2rem;
        padding-bottom: 3rem;
    }

    h1, h2, h3 {
        color: var(--quiz-ink);
        font-family: "DM Serif Display", Georgia, serif;
        font-weight: 400;
        letter-spacing: 0.01em;
    }

    [data-testid="stTextArea"] textarea {
        font-family: "Cascadia Code", "Consolas", "Courier New", monospace;
    }

    [data-testid="stCaptionContainer"] {
        color: #69545d;
    }

    [data-testid="stForm"] {
        border: 1px solid #c5e8dc;
        border-radius: 16px;
        background: rgba(255, 255, 255, 0.68);
        padding: 1rem;
    }

    [data-testid="stExpander"] {
        border: 1px solid #f0dda0;
        border-radius: 14px;
        background: rgba(255, 249, 222, 0.72);
    }

    [data-testid="stTextArea"] textarea,
    [data-testid="stTextInput"] input {
        border-color: #a9d8ca;
        border-radius: 10px;
        background: #fffdfd;
        color: var(--quiz-ink);
    }

    [data-testid="stBaseButton-primary"] {
        border: 1px solid #4c9d88;
        border-radius: 10px;
        background: var(--quiz-aqua);
        color: #fff;
    }

    [data-testid="stBaseButton-primary"]:hover {
        border-color: #347d6c;
        background: #478f7d;
        color: #fff;
    }

    [data-testid="stBaseButton-secondary"] {
        border: 1px solid #ead27e;
        border-radius: 10px;
        background: var(--quiz-yellow);
        color: var(--quiz-ink);
    }

    [data-testid="stBaseButton-secondary"]:hover {
        border-color: #d8bc5d;
        background: #ffe99a;
        color: var(--quiz-ink);
    }

    [data-testid="stDataFrame"] {
        border: 1px solid #c5e8dc;
        border-radius: 12px;
        overflow: hidden;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def setting(name: str) -> str:
    value = os.getenv(name)
    if value:
        return value
    try:
        return str(st.secrets.get(name, ""))
    except FileNotFoundError:
        return ""


def app_configuration() -> dict[str, str]:
    keys = (
        "SUPABASE_URL",
        "SUPABASE_ANON_KEY",
        "POSTGRES_DB",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "DB_HOST",
        "DB_PORT",
        "DB_SSLMODE",
    )
    return {key: setting(key) for key in keys}


def clear_auth_state() -> None:
    for key in (
        "access_token",
        "refresh_token",
        "user_id",
        "user_email",
        "saved_answers",
    ):
        st.session_state.pop(key, None)


def save_auth_session(auth_session, user) -> None:
    if not auth_session or not user:
        return
    st.session_state["access_token"] = auth_session.access_token
    st.session_state["refresh_token"] = auth_session.refresh_token
    st.session_state["user_id"] = str(user.id)
    st.session_state["user_email"] = user.email or ""


def has_unsaved_answer(question_index: int, query: str) -> bool:
    question_id = QUESTIONS[question_index].question_id
    saved_answers = st.session_state.get("saved_answers", {})
    return is_answer_unsaved(query, saved_answers.get(question_id))


def is_answer_unsaved(query: str, saved_query: str | None) -> bool:
    return bool(query.strip()) and saved_query != query


def switch_to_question(question_index: int) -> None:
    st.session_state["active_question_index"] = question_index
    st.session_state["question_selector"] = question_index
    st.session_state["query_input"] = ""
    st.session_state.pop("pending_question_index", None)
    st.session_state.pop("last_query_result", None)


def question_selection_changed() -> None:
    selected_index = st.session_state["question_selector"]
    active_index = st.session_state["active_question_index"]
    if selected_index == active_index:
        return

    query = st.session_state.get("query_input", "")
    if has_unsaved_answer(active_index, query):
        st.session_state["pending_question_index"] = selected_index
        st.session_state["question_selector"] = active_index
        return

    switch_to_question(selected_index)


def save_answer(client, question_index: int, query: str) -> None:
    question = QUESTIONS[question_index]
    client.table("quiz_answers").insert(
        {
            "user_id": st.session_state["user_id"],
            "question_id": question.question_id,
            "submitted_sql": query,
        }
    ).execute()

    saved_answers = dict(st.session_state.get("saved_answers", {}))
    saved_answers[question.question_id] = query
    st.session_state["saved_answers"] = saved_answers


def log_quiz_activity(
    client,
    user_id: str,
    question_id: str,
    action: str,
    query: str,
    result_correct: bool | None = None,
) -> None:
    activity = {
        "user_id": user_id,
        "question_id": question_id,
        "action": action,
        "submitted_sql": query,
        "result_correct": result_correct,
    }
    client.table("quiz_activity_log").insert(activity).execute()


def render_sign_in(client) -> None:
    st.title("Makeup SQL Quiz")
    st.write(
        "Sign in to run SQL against the makeup catalog and save your answers. "
        "The quiz has five questions worth 20 points total; harder questions "
        "are worth more points."
    )

    sign_in_tab, create_account_tab = st.tabs(("Sign in", "Create account"))
    with sign_in_tab:
        with st.form("sign_in_form"):
            email = st.text_input("Email")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Sign in")
        if submitted:
            try:
                response = client.auth.sign_in_with_password(
                    {"email": email, "password": password}
                )
                save_auth_session(response.session, response.user)
                if response.session:
                    st.rerun()
                st.error("Sign-in succeeded without an active session. Try again.")
            except AuthApiError as error:
                st.error(f"Sign-in failed: {error.message}")

    with create_account_tab:
        with st.form("create_account_form"):
            email = st.text_input("Email", key="create_email")
            password = st.text_input(
                "Password", type="password", key="create_password"
            )
            submitted = st.form_submit_button("Create account")
        if submitted:
            try:
                response = client.auth.sign_up(
                    {"email": email, "password": password}
                )
                if response.session:
                    save_auth_session(response.session, response.user)
                    st.rerun()
                st.success(
                    "Account created. Check your email to confirm the account, "
                    "then sign in."
                )
            except AuthApiError as error:
                st.error(f"Account creation failed: {error.message}")


def render_quiz(client, configuration: dict[str, str]) -> None:
    st.session_state.setdefault("active_question_index", 0)
    st.session_state.setdefault(
        "question_selector", st.session_state["active_question_index"]
    )

    st.title("Makeup SQL Quiz")
    st.caption(
        f"Signed in as {st.session_state['user_email']} · "
        f"{sum(item.points for item in QUESTIONS)} points total"
    )
    if st.button("Sign out"):
        try:
            client.auth.sign_out()
        except AuthApiError as error:
            st.warning(f"Could not clear the Supabase session: {error.message}")
        finally:
            clear_auth_state()
        st.rerun()

    pending_index = st.session_state.get("pending_question_index")
    if pending_index is not None:
        pending_question = QUESTIONS[pending_index]
        st.warning(
            "You have an answer for this question that hasn’t been saved. "
            f"Save it before switching to **{pending_question.title}**?"
        )
        save_column, discard_column, stay_column = st.columns(3)
        with save_column:
            save_and_switch = st.button(
                "Save & switch", key="confirm_save_and_switch", type="primary"
            )
        with discard_column:
            switch_without_saving = st.button(
                "Switch without saving", key="confirm_discard_and_switch"
            )
        with stay_column:
            stay_on_question = st.button(
                "Stay here", key="cancel_question_switch"
            )

        if save_and_switch:
            current_index = st.session_state["active_question_index"]
            current_query = st.session_state.get("query_input", "")
            try:
                save_answer(client, current_index, current_query)
            except APIError as error:
                st.error(f"Could not save your answer: {error.message}")
            else:
                switch_to_question(pending_index)
                st.rerun()
        elif switch_without_saving:
            switch_to_question(pending_index)
            st.rerun()
        elif stay_on_question:
            st.session_state.pop("pending_question_index", None)
            st.session_state["question_selector"] = st.session_state[
                "active_question_index"
            ]
            st.rerun()

    question_index = st.selectbox(
        "Choose a question",
        range(len(QUESTIONS)),
        format_func=lambda index: (
            f"{QUESTIONS[index].question_id.replace('-', ' ').title()}: "
            f"{QUESTIONS[index].title} ({QUESTIONS[index].points} points)"
        ),
        key="question_selector",
        on_change=question_selection_changed,
    )
    question_index = st.session_state["active_question_index"]
    question = QUESTIONS[question_index]
    if st.session_state.pop("answer_saved_message", False):
        st.success("Answer saved to your account.")
    st.caption(
        f"Question {question_index + 1} of {len(QUESTIONS)} · "
        f"{question.points} point(s)"
    )
    st.subheader(question.title)
    st.write(question.prompt)
    st.caption(
        "Available tables: products (brand_id, category_id, name, price, "
        "currency, created_at, description), brands (id, name), "
        "categories (id, name)."
    )

    hint_key = f"hint_level_{question.question_id}"
    hint_level = st.session_state.get(hint_key, 0)
    if hint_level:
        st.info(f"Hint {hint_level}: {question.hints[hint_level - 1]}")
    if hint_level < len(question.hints):
        if st.button(
            "Show next hint",
            key=f"show_hint_{question.question_id}",
        ):
            st.session_state[hint_key] = hint_level + 1
            st.rerun()

    query = st.text_area(
        "Your SQL query",
        key="query_input",
        height=230,
        placeholder="Write one SELECT query...",
    )
    run_column, save_column = st.columns(2)
    with run_column:
        run_clicked = st.button("Run query", type="primary")
    with save_column:
        save_clicked = st.button("Save answer")
    submit_clicked = st.button("Submit answer")

    if run_clicked:
        st.session_state.pop("last_query_result", None)
        try:
            columns, rows, truncated = run_read_query(configuration, query)
        except ValueError as error:
            st.error(str(error))
        except PostgresError as error:
            message = str(error).casefold()
            if "password authentication failed" in message:
                st.error(
                    "Supabase rejected the database username/password. For the "
                    "Session pooler, copy its User, Host, and Port from Supabase "
                    "Connect and use the current project database password. "
                    "The query was not run."
                )
            elif "tenant or user not found" in message:
                st.error(
                    "Supabase could not find that pooler user or project. Check "
                    "the Session pooler User and Host in Supabase Connect. "
                    "The query was not run."
                )
            else:
                st.error(f"Database query failed: {error}")
        else:
            st.session_state["last_query_result"] = {
                "columns": columns,
                "rows": rows,
                "truncated": truncated,
            }
            try:
                log_quiz_activity(
                    client,
                    st.session_state["user_id"],
                    question.question_id,
                    "run",
                    query,
                )
            except APIError as error:
                st.warning(f"Query ran, but its activity could not be logged: {error.message}")

    if submit_clicked:
        st.session_state.pop("last_query_result", None)
        try:
            columns, rows, truncated, correct = grade_query(
                configuration, question, query
            )
        except ValueError as error:
            st.error(str(error))
        except PostgresError as error:
            st.error(f"Database query failed: {error}")
        else:
            st.session_state["last_query_result"] = {
                "columns": columns,
                "rows": rows,
                "truncated": truncated,
            }
            submission_results = dict(
                st.session_state.get("submission_results", {})
            )
            submission_results[question.question_id] = {
                "correct": correct,
                "query": query,
                "hint_level": hint_level,
            }
            st.session_state["submission_results"] = submission_results
            try:
                log_quiz_activity(
                    client,
                    st.session_state["user_id"],
                    question.question_id,
                    "submit",
                    query,
                    result_correct=correct,
                )
            except APIError as error:
                st.warning(f"Answer was graded, but its activity could not be logged: {error.message}")

    submission = st.session_state.get("submission_results", {}).get(
        question.question_id
    )
    if submission and submission["query"] == query:
        if submission["correct"]:
            st.success(
                f"Correct! You earned {question.points} points. "
                "Your submitted results are shown below."
            )
        else:
            st.error(
                "That query ran, but its results do not match the answer key. "
                "Review the hints and try again."
            )
            if (
                hint_level < len(question.hints)
                or submission.get("hint_level", 0) < len(question.hints)
            ):
                st.warning(
                    "View both hints, then submit another query that runs but "
                    "returns an incorrect result before viewing the expected "
                    "result."
                )
            else:
                expected_key = f"show_expected_{question.question_id}"
                if st.button("Reveal expected output", key=expected_key):
                    st.session_state[
                        f"expected_revealed_{question.question_id}"
                    ] = True
            if st.session_state.get(
                f"expected_revealed_{question.question_id}", False
            ):
                st.markdown("**Expected result**")
                st.write(question.expected_result)

    submissions = st.session_state.get("submission_results", {})
    if submissions:
        earned_points = sum(
            item.points
            for item in QUESTIONS
            if submissions.get(item.question_id, {}).get("correct")
        )
        st.subheader("Your quiz results")
        st.metric("Score", f"{earned_points} / {sum(item.points for item in QUESTIONS)}")
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Question": item.title,
                        "Status": (
                            "Correct"
                            if submissions.get(item.question_id, {}).get("correct")
                            else "Incorrect"
                            if item.question_id in submissions
                            else "Not submitted"
                        ),
                        "Points earned": (
                            item.points
                            if submissions.get(item.question_id, {}).get("correct")
                            else 0
                        ),
                        "Points possible": item.points,
                    }
                    for item in QUESTIONS
                ]
            ),
            hide_index=True,
            use_container_width=True,
        )

    if "last_query_result" in st.session_state:
        result = st.session_state["last_query_result"]
        st.subheader("Query result")
        st.dataframe(
            pd.DataFrame(result["rows"], columns=result["columns"]),
            use_container_width=True,
        )
        row_count = len(result["rows"])
        suffix = " (showing first 200 rows)" if result["truncated"] else ""
        st.caption(f"{row_count} row(s){suffix}")

    if save_clicked:
        if not query.strip():
            st.error("Enter a SQL query before saving your answer.")
        else:
            try:
                save_answer(client, question_index, query)
            except APIError as error:
                st.error(f"Could not save your answer: {error.message}")
            else:
                try:
                    log_quiz_activity(
                        client,
                        st.session_state["user_id"],
                        question.question_id,
                        "save",
                        query,
                    )
                except APIError as error:
                    st.warning(
                        "Answer was saved, but its activity could not be logged: "
                        f"{error.message}"
                    )
                else:
                    st.success("Answer saved to your account.")


def main() -> None:
    configuration = app_configuration()
    missing = [key for key, value in configuration.items() if not value]
    if missing:
        st.error(
            "Configure these app secrets before starting the quiz: "
            + ", ".join(missing)
        )
        st.stop()

    client = create_client(
        configuration["SUPABASE_URL"], configuration["SUPABASE_ANON_KEY"]
    )
    if st.session_state.get("access_token") and st.session_state.get("refresh_token"):
        try:
            response = client.auth.set_session(
                st.session_state["access_token"],
                st.session_state["refresh_token"],
            )
            save_auth_session(response.session, response.user)
        except AuthApiError:
            clear_auth_state()
            st.info("Your sign-in expired. Please sign in again.")

    if st.session_state.get("access_token"):
        render_quiz(client, configuration)
    else:
        render_sign_in(client)


if __name__ == "__main__":
    main()
