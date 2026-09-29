"""CSV -> DuckDB table, plus the schema context the LLM sees for that table."""

import json
from pathlib import Path
from uuid import UUID

import duckdb

from natural_language_insights.database import db_query, db_records
from natural_language_insights.jobs import JobError

LOW_CARDINALITY = 25  # list every value when a column has at most this many
EXAMPLE_COUNT = 5
MAX_VALUE_LENGTH = 60


def table_name(dataset_id: UUID) -> str:
    # Safe to interpolate: a UUID renders as hex digits and dashes only.
    return f'"dataset_{dataset_id}"'


def quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def ingest(dataset_id: UUID, path: Path) -> dict:
    try:
        load_csv(dataset_id, path)
        context = build_schema_context(dataset_id)
    except Exception as exc:
        message = str(exc) if isinstance(exc, JobError) else "Ingestion failed."
        db_query(
            "UPDATE datasets SET status = 'failed', error = ? WHERE id = ?",
            [message, dataset_id],
        )
        raise
    db_query(
        "UPDATE datasets SET status = 'ready', row_count = ?, schema_context = ? WHERE id = ?",
        [context["row_count"], json.dumps(context, default=str), dataset_id],
    )
    return {"dataset_id": str(dataset_id), "row_count": context["row_count"]}


def load_csv(dataset_id: UUID, path: Path) -> None:
    # Full-file type inference (sample_size=-1): a late non-numeric value would
    # otherwise fail the load. Latin-1 fallback covers most legacy exports.
    last_error: duckdb.Error | None = None
    for encoding in ("utf-8", "latin-1"):
        try:
            db_query(
                f"CREATE TABLE {table_name(dataset_id)} AS "
                "SELECT * FROM read_csv(?, sample_size = -1, encoding = ?)",
                [str(path), encoding],
            )
            return
        except duckdb.Error as exc:
            last_error = exc
    first_line = str(last_error).splitlines()[0][:300]
    raise JobError(f"Could not parse the file as CSV: {first_line}")


def build_schema_context(dataset_id: UUID) -> dict:
    """Describe each column from the data itself: type, nulls, range, example values."""
    table = table_name(dataset_id)
    [(row_count,)] = db_query(f"SELECT COUNT(*) FROM {table}")
    if row_count == 0:
        raise JobError("The CSV has a header but no rows.")

    columns = []
    for stats in db_records(f"SUMMARIZE {table}"):
        name = stats["column_name"]
        distinct = stats["approx_unique"]
        limit = LOW_CARDINALITY if distinct <= LOW_CARDINALITY else EXAMPLE_COUNT
        values = db_query(
            f"SELECT {quote(name)} FROM {table} WHERE {quote(name)} IS NOT NULL "
            f"GROUP BY 1 ORDER BY COUNT(*) DESC LIMIT {limit}"
        )
        columns.append(
            {
                "name": name,
                "type": stats["column_type"],
                "null_percent": float(stats["null_percentage"] or 0),
                "approx_distinct": distinct,
                "min": clip(stats["min"]),
                "max": clip(stats["max"]),
                "all_values" if distinct <= LOW_CARDINALITY else "common_values": [
                    clip(value) for (value,) in values
                ],
            }
        )
    return {"table": table, "row_count": row_count, "columns": columns}


def clip(value):
    if value is None or isinstance(value, int | float | bool):
        return value
    text = str(value)
    return text if len(text) <= MAX_VALUE_LENGTH else text[:MAX_VALUE_LENGTH] + "…"
