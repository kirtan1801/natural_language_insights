"""Question -> SQL (LLM) -> guarded execution -> answer."""

import json
import logging
import threading
from functools import cache
from pathlib import Path
from uuid import UUID

import duckdb
import sqlglot
from langchain.chat_models import init_chat_model
from langchain_core.runnables import Runnable
from pydantic import BaseModel
from sqlglot import exp
from sqlglot.errors import ErrorLevel, UnsupportedError

from natural_language_insights.config.settings import settings
from natural_language_insights.database import database, db_records
from natural_language_insights.jobs import JobError

SYSTEM_PROMPT = """\
You are a data analyst. You answer questions about one table by planning a single DuckDB SQL
query. The application runs your query; the user sees its result next to your explanation
and assumptions.

You receive the table name and a profile of every column, computed from the data: type,
null percentage, approximate distinct count, min/max, and example values (all_values when
the column has few distinct values).

Writing the SQL:
- One read-only SELECT; CTEs are allowed. No DDL, DML, PRAGMA, SET, or table functions.
- Use only the table and the columns in the profile, spelled exactly as listed, in double
  quotes.
- Inside CTEs and subqueries, select every column that later parts of the query use.
- Return a small result: aggregate, and use ORDER BY and LIMIT for rankings.
- Write DuckDB SQL, not BigQuery, Postgres, MySQL or SQL Server. Follow the DuckDB notes
  at the end of these instructions.
- Infer what columns mean from their names and example values, not from knowledge of any
  particular dataset. Record each interpretation choice in assumptions (how an amount is
  computed, whether returns or cancellations are excluded, how a period is defined).

Broad questions ("what is in this data?", "give me an overview", "basic analytics") are
answerable. In explanation, describe what the table contains using only the profile: what
one row appears to represent, the key columns, the date range. The query returns headline
figures in one row, such as row count, distinct counts of the main entities, the date
range, and totals of the main amount column.

Refusing: set answerable=false only when the data cannot support an answer: the needed
columns do not exist, the question is about a period or entity outside the data (check
min/max), it needs outside knowledge, a forecast or an opinion, or it is not about this
data. Never stand in an unrelated column for a missing one. A broad or vague question is
not a reason to refuse: answer its most useful reading and note that in assumptions.

The user reads reason, explanation and assumptions. Write them about the data, in plain
language. Never mention these instructions, the profile format, or SQL errors. When
answerable=false, give the reason in one or two sentences and leave sql empty.

Follow-up questions may refer to earlier questions and results in the conversation ("what
about France?", "the second one", "same for last quarter"). Resolve those references from
the earlier turns and write a complete query; the result of each earlier query is shown to
you, truncated.

If the conversation shows a database error for your query, the error came from running your
own SQL. Return a corrected plan for the same question. Change the part the error points
at; if the same approach failed twice, take a different approach (for example a CTE with
ROW_NUMBER instead of a list function). Never repeat a query that already failed. A
database error is never a reason to refuse.
"""

# Dialect pitfalls live in a markdown file so they can be extended without touching code.
DUCKDB_NOTES = (Path(__file__).parent / "prompts" / "duckdb_notes.md").read_text()
SYSTEM_PROMPT = f"{SYSTEM_PROMPT}\n{DUCKDB_NOTES}"

HISTORY_ROWS = 10  # rows of each earlier result shown to the model

logger = logging.getLogger(__name__)


class SqlPlan(BaseModel):
    answerable: bool
    reason: str
    sql: str
    explanation: str
    assumptions: list[str]


class UnsafeSql(ValueError):
    pass


def answer_question(dataset_id: UUID, question: str, history: list[dict] = ()) -> dict:
    """history: earlier turns of the conversation, oldest first, as {"question", "result"}."""
    [dataset] = db_records("SELECT schema_context FROM datasets WHERE id = ?", [dataset_id])
    context = json.loads(dataset["schema_context"])

    failures: list[dict] = []  # every failed attempt so far, so no mistake is repeated
    for _ in range(settings.max_sql_attempts):
        plan = generate_sql(question, context, history, failures)
        if not plan.answerable:
            return {"answerable": False, "reason": plan.reason}
        try:
            if any(plan.sql.strip() == failed["plan"].sql.strip() for failed in failures):
                raise UnsafeSql("This is the same query as an earlier attempt that failed.")
            sql = guard_sql(plan.sql, context["table"])
            columns, rows, truncated = run_sql(sql)
        except (UnsafeSql, duckdb.Error) as exc:
            if isinstance(exc, duckdb.InterruptException):
                raise JobError("The query exceeded the time limit.") from exc
            logger.info("SQL attempt %d failed: %s", len(failures) + 1, exc)
            failures.append({"plan": plan, "error": str(exc)})
            continue
        return {
            "answerable": True,
            "explanation": plan.explanation,
            "assumptions": plan.assumptions,
            "sql": sql,
            "columns": columns,
            "rows": rows,
            "truncated": truncated,
            "attempts": len(failures) + 1,
        }
    raise JobError(
        f"Could not produce a working query after {len(failures)} attempts. "
        "Try rephrasing the question."
    )


def generate_sql(
    question: str, context: dict, history: list[dict] = (), failures: list[dict] = ()
) -> SqlPlan:
    messages = build_messages(question, context, history)
    # Each failed attempt is a real turn: the model's own plan, then the error it caused.
    for number, failed in enumerate(failures, start=1):
        error = f"Attempt {number} of {settings.max_sql_attempts} failed with this error:"
        messages += [
            ("ai", failed["plan"].model_dump_json()),
            ("human", f"{error}\n{failed['error']}"),
        ]
    try:
        output = planner().invoke(messages)
    except Exception as exc:  # each provider raises its own error types
        logger.exception("LLM call failed")
        raise JobError("The language model is unavailable. Try again later.") from exc
    if output["parsed"] is None:
        logger.warning("Unparseable LLM output: %s", output["parsing_error"])
        raise JobError("The language model did not return a valid plan.")
    return output["parsed"]


def build_messages(question: str, context: dict, history: list[dict]) -> list[tuple[str, str]]:
    """Profile once, then each earlier turn as question / plan / result preview."""
    messages = [("system", SYSTEM_PROMPT)]
    preface = f"Table profile:\n{json.dumps(context)}"
    for turn in history:
        result = turn["result"]
        messages.append(("human", f"{preface}\n\nQuestion: {turn['question']}"))
        messages.append(("ai", previous_plan(result).model_dump_json()))
        preface = result_preview(result)
    messages.append(("human", f"{preface}\n\nQuestion: {question}".strip()))
    return messages


def previous_plan(result: dict) -> SqlPlan:
    return SqlPlan(
        answerable=result["answerable"],
        reason=result.get("reason", ""),
        sql=result.get("sql", ""),
        explanation=result.get("explanation", ""),
        assumptions=result.get("assumptions", []),
    )


def result_preview(result: dict) -> str:
    if not result["answerable"]:
        return ""
    rows = result["rows"]
    shown = {"columns": result["columns"], "rows": rows[:HISTORY_ROWS]}
    return (
        f"Result of that query ({min(len(rows), HISTORY_ROWS)} of {len(rows)} rows shown):\n"
        f"{json.dumps(shown, default=str)}"
    )


@cache
def planner() -> Runnable:
    """Chat model chosen by LLM_MODEL ("provider:model"), constrained to return a SqlPlan."""
    model = init_chat_model(settings.llm_model, max_tokens=16000, **settings.llm_kwargs)
    # json_schema = the provider's native structured output. Function calling would force a
    # tool choice, which some models (e.g. Claude Opus 5.5) reject.
    return model.with_structured_output(SqlPlan, method="json_schema", include_raw=True)


def guard_sql(sql: str, table: str) -> str:
    """Allow a single SELECT that reads only the dataset table (and its own CTEs)."""
    try:
        statements = [s for s in sqlglot.parse(sql, read="duckdb") if s is not None]
    except sqlglot.errors.ParseError as exc:
        raise UnsafeSql(f"SQL does not parse: {exc}") from exc
    if len(statements) != 1:
        raise UnsafeSql("Exactly one statement is allowed.")
    [tree] = statements
    if not isinstance(tree, exp.Query):
        raise UnsafeSql("Only SELECT queries are allowed.")

    allowed = {table.strip('"')} | {cte.alias_or_name for cte in tree.find_all(exp.CTE)}
    for source in tree.find_all(exp.Table):
        # Table functions (read_csv, read_text, ...) have no name and fail this check.
        if source.name not in allowed or source.db or source.catalog:
            raise UnsafeSql(f"Query may only read {table}; found {source.sql('duckdb')!r}.")
    try:
        # Executed SQL is regenerated from the checked tree, so what runs is what was checked.
        # RAISE turns constructs DuckDB lacks into a precise error for the retry, instead of a
        # logged warning followed by a vaguer DuckDB syntax error.
        return tree.sql("duckdb", unsupported_level=ErrorLevel.RAISE)
    except UnsupportedError as exc:
        raise UnsafeSql(f"Not valid DuckDB: {exc}") from exc


def run_sql(sql: str) -> tuple[list[str], list[list], bool]:
    limit = settings.max_result_rows
    with database.get_connection().cursor() as cursor:
        timer = threading.Timer(settings.query_timeout_seconds, cursor.interrupt)
        timer.start()
        try:
            cursor.execute(sql)
            rows = cursor.fetchmany(limit + 1)
        finally:
            timer.cancel()
        columns = [column[0] for column in cursor.description]
    return columns, [list(row) for row in rows[:limit]], len(rows) > limit
