# Natural Language Insights Engine

Load any transactional CSV, then ask it questions in plain English. Each answer comes with the SQL that produced it and the assumptions behind it, and the app refuses questions the data can't answer.

- **Design document:** [docs/design.md](docs/design.md) (architecture, the path a question takes, decisions, what's next)
- **Demo GIFs:** [docs/gifs/](docs/gifs/)

## Run it

You need an API key for one LLM provider (Anthropic, OpenAI, Google, or a local Ollama), plus either Docker or [uv](https://docs.astral.sh/uv/).

```bash
git clone <repo> && cd <repo>
cp .env.example .env          # set LLM_MODEL + that provider's API key
docker compose up --build     # http://localhost:8000
```

Without Docker:

```bash
uv sync --all-extras               # or: --extra openai / google / ollama
uv run natural_language_insights   # http://localhost:8000
```

Open http://localhost:8000 for the UI, or http://localhost:8000/docs for the OpenAPI reference.

## Ask a question

In the UI (a chat, like ChatGPT): attach a CSV with 📎 or drop it on the page, then ask questions. Follow-ups work ("what about France?", "only 2011") because each chat keeps its history. Earlier chats are in the sidebar and survive a reload.

Over HTTP, every long-running call returns a job. Submit the work, then poll for the result:

```bash
# 1. Load a CSV (returns immediately)
curl -F file=@online_retail.csv localhost:8000/api/v1/datasets
# {"job_id":"…","dataset_id":"…"}

# 2. Stream status until "succeeded" or "failed" (or poll GET /api/v1/jobs/<job_id>)
curl -N localhost:8000/api/v1/jobs/<job_id>/events

# 3. Ask
curl -X POST localhost:8000/api/v1/datasets/<dataset_id>/questions \
     -H 'Content-Type: application/json' \
     -d '{"question": "Top 10 products by revenue"}'
curl localhost:8000/api/v1/jobs/<job_id>
```

A finished question job looks like this:

```json
{
  "status": "succeeded",
  "result": {
    "answerable": true,
    "explanation": "Sums line revenue per product description …",
    "assumptions": ["Revenue = sum of line_revenue on product lines, net of cancellations"],
    "sql": "SELECT description, SUM(line_revenue) AS revenue FROM … LIMIT 10",
    "columns": ["description", "revenue"],
    "rows": [["REGENCY CAKESTAND 3 TIER", 158569.32], …],
    "truncated": false
  }
}
```

An unanswerable question also succeeds, with `{"answerable": false, "reason": "…"}`.

### API

| Method | Path | Result |
|---|---|---|
| `POST` | `/api/v1/datasets` (multipart `file`) | `202 {job_id, dataset_id}`, or `400` not a .csv / empty, `413` too large |
| `GET` | `/api/v1/datasets` | all datasets with status |
| `GET` | `/api/v1/datasets/{id}` | status, row count, inferred columns; `404`, `422` bad id |
| `POST` | `/api/v1/datasets/{id}/questions` `{question}` | one-off question, no history: `202 {job_id}`; `404`, `409` not ready, `422` invalid |
| `POST` | `/api/v1/conversations` `{dataset_id}` | `201` a chat on a ready dataset; `404`, `409` |
| `GET` | `/api/v1/conversations[/{id}]` | chats; one chat with all its turns (question, status, result) |
| `POST` | `/api/v1/conversations/{id}/questions` `{question}` | `202 {job_id}`; the model sees the last 6 answered turns |
| `GET` | `/api/v1/jobs/{id}` | `queued`, `running`, `succeeded` + `result`, or `failed` + `error` |
| `GET` | `/api/v1/jobs/{id}/events` | Server-Sent Events: one `status` event per change, closes when done (the UI uses this) |
| `GET` | `/health` | `{"status": "ok"}` |

Errors always look like `{"error": {"code": "...", "message": "..."}}`. Stack traces are never returned.

## Configure

All settings come from environment variables or `.env` (see [.env.example](.env.example)):

| Variable | Default | |
|---|---|---|
| `LLM_MODEL` | `anthropic:claude-opus-5-5` | `provider:model`, resolved by LangChain `init_chat_model`: `openai:gpt-5`, `google_genai:gemini-2.5-pro`, `ollama:llama3.1`, … |
| provider key | — | `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_API_KEY` (Ollama needs none) |
| `LLM_KWARGS` | `{}` | extra model settings as JSON, e.g. `{"temperature": 0}` or `{"output_config": {"effort": "high"}}` for Anthropic |
| `PORT` | `8000` | for `uv run natural_language_insights`; with Docker change the host side of `ports` in `compose.yaml` |
| `JOB_WORKERS` | `4` | concurrent ingest/question jobs |
| `MAX_UPLOAD_MB` | `500` | |
| `QUERY_TIMEOUT_SECONDS` | `30` | generated SQL is interrupted after this |
| `MAX_RESULT_ROWS` | `1000` | |
| `MAX_SQL_ATTEMPTS` | `3` | model writes SQL; on failure it sees every earlier error and tries again |
| `DATABASE_PATH` / `UPLOAD_DIRECTORY` | `data/…` | |

## Test and evaluate

```bash
uv run pytest                 # unit + API tests, model stubbed; runs in CI on every push
uv run ruff check . && uv run ruff format --check .

# Evals against a running server (needs a model key); exits non-zero on failure.
# Run it once per LLM_MODEL to compare providers on the same questions.
uv run python scripts/run_evals.py path/to/online_retail.csv
```

The eval set ([evals/questions.json](evals/questions.json)) covers the five questions from the brief plus five that should be refused (profit margin with no cost data, marketing channel, a forecast, a year outside the data, customer satisfaction). The expected answers are hand-written reference SQL, one query per defensible interpretation, computed from the same CSV at run time.

## Layout

```
src/natural_language_insights/
  main.py            app factory, error envelope, UI route
  api/routes/        datasets, conversations, jobs (+ SSE stream)
  jobs.py            job lifecycle + thread pool
  ingest.py          CSV → table, schema context
  qa.py              prompt, LangChain model call, SQL guard, retry loop, execution
  prompts/           DuckDB dialect notes appended to the system prompt
  database/          DuckDB connection + metadata schema
  static/index.html  chat UI (no build step)
tests/               pytest suite
evals/, scripts/     eval set + runner
docs/                design doc, architecture image, GIFs
```

## What I cut

See [docs/design.md → What I cut](docs/design.md#what-i-cut) and [What I would build next](docs/design.md#what-i-would-build-next-in-order).
