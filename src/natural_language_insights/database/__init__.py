from pathlib import Path

from natural_language_insights.config.settings import settings
from natural_language_insights.database.connection import DuckDBManager

database = DuckDBManager(database_path=Path(settings.database_path))

SCHEMA = """
CREATE TABLE IF NOT EXISTS datasets (
    id UUID PRIMARY KEY,
    filename VARCHAR NOT NULL,
    status VARCHAR NOT NULL,          -- ingesting | ready | failed
    row_count BIGINT,
    schema_context JSON,
    error VARCHAR,
    created_at TIMESTAMP NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS jobs (
    id UUID PRIMARY KEY,
    kind VARCHAR NOT NULL,            -- ingest | question
    dataset_id UUID NOT NULL,
    status VARCHAR NOT NULL,          -- queued | running | succeeded | failed
    input JSON,
    result JSON,
    error VARCHAR,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now()
);
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS conversation_id UUID;
CREATE TABLE IF NOT EXISTS conversations (
    id UUID PRIMARY KEY,
    dataset_id UUID NOT NULL,
    title VARCHAR,
    created_at TIMESTAMP NOT NULL DEFAULT now()
);
"""


def init_schema() -> None:
    with database.get_connection().cursor() as cursor:
        cursor.execute(SCHEMA)
        # Work in flight when the process died will never finish; say so instead of
        # leaving callers polling forever.
        cursor.execute(
            "UPDATE jobs SET status = 'failed', error = 'Interrupted by server restart.', "
            "updated_at = now() WHERE status IN ('queued', 'running')"
        )
        cursor.execute(
            "UPDATE datasets SET status = 'failed', error = 'Interrupted by server restart.' "
            "WHERE status = 'ingesting'"
        )


def db_query(query: str, parameters: list | None = None) -> list[tuple]:
    # Cursor per call: a DuckDB connection is not safe to share across threads.
    with database.get_connection().cursor() as cursor:
        return cursor.execute(query, parameters or []).fetchall()


def db_records(query: str, parameters: list | None = None) -> list[dict]:
    with database.get_connection().cursor() as cursor:
        cursor.execute(query, parameters or [])
        names = [column[0] for column in cursor.description]
        return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]
