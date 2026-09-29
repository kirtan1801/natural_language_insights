from uuid import uuid4

import pytest
from conftest import wait_for_job
from langchain_core.runnables import RunnableLambda

from natural_language_insights import qa
from natural_language_insights.jobs import JobError
from natural_language_insights.qa import SqlPlan


def plan(sql: str = "", answerable: bool = True, reason: str = "") -> SqlPlan:
    return SqlPlan(answerable=answerable, reason=reason, sql=sql, explanation="e", assumptions=[])


@pytest.fixture
def llm(monkeypatch):
    """Replace the model with a queue of canned plans; records what it was sent."""
    calls = []

    def install(*plans: SqlPlan):
        queue = list(plans)

        def fake(question, context, history=(), failures=()):
            calls.append(
                {
                    "question": question,
                    "context": context,
                    "history": history,
                    "failures": list(failures),
                }
            )
            return queue.pop(0)

        monkeypatch.setattr(qa, "generate_sql", fake)
        return calls

    return install


def ask(client, dataset_id, question="Revenue by country?"):
    response = client.post(f"/api/v1/datasets/{dataset_id}/questions", json={"question": question})
    assert response.status_code == 202, response.json()
    return wait_for_job(client, response.json()["job_id"])


def test_answer_runs_generated_sql(client, dataset_id, llm):
    table = f'"dataset_{dataset_id}"'
    calls = llm(
        plan(f"SELECT country, SUM(amount) AS revenue FROM {table} GROUP BY 1 ORDER BY 2 DESC")
    )
    job = ask(client, dataset_id)
    assert job["status"] == "succeeded"
    assert job["result"]["columns"] == ["country", "revenue"]
    assert job["result"]["rows"] == [["UK", 10.75], ["FR", 3.0]]
    # The model only ever sees the profile built from the file.
    assert [c["name"] for c in calls[0]["context"]["columns"]] == ["order_id", "amount", "country"]


def test_refusal_is_a_successful_answer(client, dataset_id, llm):
    llm(plan(answerable=False, reason="No profit column."))
    job = ask(client, dataset_id, "What was our profit margin?")
    assert job["status"] == "succeeded"
    assert job["result"] == {"answerable": False, "reason": "No profit column."}


def test_bad_sql_is_retried_with_error_feedback(client, dataset_id, llm):
    table = f'"dataset_{dataset_id}"'
    calls = llm(plan(f"SELECT nope FROM {table}"), plan(f"SELECT COUNT(*) AS n FROM {table}"))
    job = ask(client, dataset_id)
    assert job["result"]["rows"] == [[3]]
    assert "nope" in calls[1]["failures"][0]["plan"].sql
    assert "nope" in calls[1]["failures"][0]["error"]
    assert job["result"]["attempts"] == 2


def test_gives_up_after_max_attempts(client, dataset_id, llm):
    calls = llm(plan("DROP TABLE x"), plan("DELETE FROM x"), plan("SELECT * FROM other"))
    job = ask(client, dataset_id)
    assert job["status"] == "failed"
    assert "after 3 attempts" in job["error"]
    assert len(calls) == 3
    # Each retry carries every earlier failure, not only the last one.
    assert [len(call["failures"]) for call in calls] == [0, 1, 2]


def test_third_attempt_can_succeed(client, dataset_id, llm):
    table = f'"dataset_{dataset_id}"'
    llm(
        plan(f"SELECT ARRAY_AGG(country LIMIT 1) FROM {table}"),
        plan(f"SELECT nope FROM {table}"),
        plan(f"SELECT COUNT(*) AS n FROM {table}"),
    )
    job = ask(client, dataset_id)
    assert job["status"] == "succeeded"
    assert job["result"]["attempts"] == 3


def test_repeating_a_failed_query_is_not_run_again(client, dataset_id, llm):
    table = f'"dataset_{dataset_id}"'
    calls = llm(
        plan(f"SELECT nope FROM {table}"),
        plan(f"SELECT nope FROM {table}"),
        plan(f"SELECT COUNT(*) AS n FROM {table}"),
    )
    job = ask(client, dataset_id)
    assert job["status"] == "succeeded"
    assert "same query" in calls[2]["failures"][1]["error"]


def test_question_on_unknown_dataset_is_404(client):
    response = client.post(f"/api/v1/datasets/{uuid4()}/questions", json={"question": "Hi?"})
    assert response.status_code == 404


def test_empty_question_is_422(client, dataset_id):
    response = client.post(f"/api/v1/datasets/{dataset_id}/questions", json={"question": ""})
    assert response.status_code == 422


def test_provider_errors_become_job_errors(monkeypatch):
    def boom(_messages):
        raise ConnectionError("provider down")

    monkeypatch.setattr(qa, "planner", lambda: RunnableLambda(boom))
    with pytest.raises(JobError, match="unavailable"):
        qa.generate_sql("q", {"table": "t", "columns": []})


def test_unparseable_model_output_is_a_job_error(monkeypatch):
    output = {"raw": None, "parsed": None, "parsing_error": ValueError("bad json")}
    monkeypatch.setattr(qa, "planner", lambda: RunnableLambda(lambda _: output))
    with pytest.raises(JobError, match="valid plan"):
        qa.generate_sql("q", {"table": "t", "columns": []})


def test_model_is_chosen_by_setting(monkeypatch):
    seen = {}

    def fake_init(model, **kwargs):
        seen.update(model=model, **kwargs)
        raise RuntimeError("stop before any network call")

    monkeypatch.setattr(qa, "init_chat_model", fake_init)
    monkeypatch.setattr(qa.settings, "llm_model", "ollama:llama3.1")
    monkeypatch.setattr(qa.settings, "llm_kwargs", {"temperature": 0})
    qa.planner.cache_clear()
    with pytest.raises(RuntimeError):
        qa.planner()
    qa.planner.cache_clear()
    assert seen == {"model": "ollama:llama3.1", "max_tokens": 16000, "temperature": 0}


def test_retry_is_sent_as_a_conversation_turn(monkeypatch):
    seen = []
    parsed = plan("SELECT 1")
    monkeypatch.setattr(
        qa, "planner", lambda: RunnableLambda(lambda m: seen.append(m) or {"parsed": parsed})
    )
    failures = [
        {"plan": plan("SELECT bad"), "error": "Binder Error: bad"},
        {"plan": plan("SELECT worse"), "error": "Parser Error: worse"},
    ]
    qa.generate_sql("q", {}, failures=failures)
    roles = [role for role, _ in seen[0]]
    assert roles == ["system", "human", "ai", "human", "ai", "human"]
    assert "SELECT bad" in seen[0][2][1]
    assert "Attempt 1 of 3" in seen[0][3][1]
    assert "Binder Error" in seen[0][3][1]
    assert "Attempt 2 of 3" in seen[0][5][1]


def test_duckdb_notes_are_in_the_prompt():
    assert "LIMIT inside any aggregate" in qa.SYSTEM_PROMPT


def start_conversation(client, dataset_id) -> str:
    response = client.post("/api/v1/conversations", json={"dataset_id": dataset_id})
    assert response.status_code == 201
    return response.json()["conversation_id"]


def ask_in(client, conversation_id, question):
    response = client.post(
        f"/api/v1/conversations/{conversation_id}/questions", json={"question": question}
    )
    assert response.status_code == 202, response.json()
    return wait_for_job(client, response.json()["job_id"])


def test_follow_up_sees_earlier_turns(client, dataset_id, llm):
    table = f'"dataset_{dataset_id}"'
    calls = llm(
        plan(f"SELECT country, SUM(amount) AS revenue FROM {table} GROUP BY 1 ORDER BY 2 DESC"),
        plan(f"SELECT SUM(amount) AS revenue FROM {table} WHERE country = 'FR'"),
    )
    conversation_id = start_conversation(client, dataset_id)
    ask_in(client, conversation_id, "Revenue by country?")
    ask_in(client, conversation_id, "What about France only?")

    assert calls[0]["history"] == []
    [earlier] = calls[1]["history"]
    assert earlier["question"] == "Revenue by country?"
    assert earlier["result"]["rows"] == [["UK", 10.75], ["FR", 3.0]]

    body = client.get(f"/api/v1/conversations/{conversation_id}").json()
    assert body["title"] == "Revenue by country?"
    assert [t["question"] for t in body["turns"]] == [
        "Revenue by country?",
        "What about France only?",
    ]
    assert body["turns"][1]["result"]["rows"] == [[3.0]]


def test_conversations_are_listed(client, dataset_id):
    conversation_id = start_conversation(client, dataset_id)
    listed = client.get("/api/v1/conversations").json()
    assert conversation_id in [c["conversation_id"] for c in listed]
    assert listed[0]["filename"] == "orders.csv"


def test_conversation_needs_a_ready_dataset(client):
    response = client.post("/api/v1/conversations", json={"dataset_id": str(uuid4())})
    assert response.status_code == 404


def test_unknown_conversation_is_404(client):
    assert client.get(f"/api/v1/conversations/{uuid4()}").status_code == 404
    response = client.post(f"/api/v1/conversations/{uuid4()}/questions", json={"question": "Hi?"})
    assert response.status_code == 404


def test_history_becomes_conversation_turns():
    history = [
        {
            "question": "Revenue by country?",
            "result": {
                "answerable": True,
                "sql": "SELECT 1",
                "explanation": "e",
                "assumptions": [],
                "columns": ["country", "revenue"],
                "rows": [["UK", 10.75]] * 15,
            },
        },
        {"question": "Profit?", "result": {"answerable": False, "reason": "No cost column."}},
    ]
    messages = qa.build_messages("And France?", {"table": "t", "columns": []}, history)
    assert [role for role, _ in messages] == ["system", "human", "ai", "human", "ai", "human"]
    assert "Table profile" in messages[1][1]
    assert "Table profile" not in messages[3][1]  # profile sent once
    assert "10 of 15 rows" in messages[3][1]  # earlier result shown, truncated
    assert messages[5][1] == "Question: And France?"  # after a refusal there is no result
