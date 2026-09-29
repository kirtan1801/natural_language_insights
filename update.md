# Code Review: Natural Language Insights (WIP)

**Verdict:** Not senior-level yet. The structure is solid, but there are 2 crash bugs, 1 injection hole, blocking I/O in async handlers, a broken test suite, and ~430MB of data one `git add .` away from being committed.

## What's good
- App factory (`create_app`) + `lifespan` for DB connection lifecycle
- Versioned router (`/api/v1/datasets`)
- `pydantic-settings` for config, `uv` for packaging
- Chunked upload streaming; file cleanup on save/DB failure

## Must fix (bugs / security)

1. **404 path crashes** — `src/natural_language_insights/api/routes/datasets.py:90`
   `details=` should be `detail=`. Every "not found" request raises `TypeError` and returns 500. Also add `from None` to the raise.

2. **SQL injection via table name** — `datasets.py:81-85`
   `dataset_id: str` from the URL is interpolated into `"dataset_{dataset_id}"`. A `"` in the id breaks out of the quoted identifier. Fix: type it as `dataset_id: UUID` — FastAPI rejects bad ids with 422.

3. **Test suite broken** — `tests/test_database.py:1`
   Imports `create_connection`, which doesn't exist. pytest fails on import.

4. **`data/` not gitignored** — `.gitignore`
   5 identical 78MB CSVs + 39MB DuckDB file. Add `data/`.

## Should fix (senior signals)

5. **Blocking I/O in `async def` handlers**
   Sync file writes and DuckDB `CREATE TABLE` on a 78MB CSV block the event loop — the whole server stalls, including `/health`. Make handlers plain `def` (FastAPI runs them in a threadpool); write with `shutil.copyfileobj(file.file, output)`.

6. **Shared DuckDB connection across threads** — `database/__init__.py:13`
   Once handlers run in the threadpool, a single connection isn't safe for concurrent use. Use `connection.cursor()` per call in `db_query`.

7. **Settings ignored**
   - `settings.upload_directory` is unused; `datasets.py:13` hardcodes `Path("data/uploads")`.
   - `main.py:19-20` duplicates app name/version instead of using settings (and title typo: "natural Language").
   - Relative paths depend on the working directory.

8. **No upload size limit** — disk can fill. Add a `max_upload_bytes` setting; abort, clean up, and return 413 when exceeded.

9. **No response models**
   Add Pydantic models (`DatasetCreated`, `DatasetSchema`, `Column`) for OpenAPI docs and a typed contract. Drop `table_name` from responses — it's an internal detail.

10. **README empty** — reviewers weigh this heavily. Add: how to run, how to test, design decisions and trade-offs.

## Cleanup (cheap, but reviewers notice)
- Typos: `databse` (`database/__init__.py:6`, `main.py:6`), `get_detaset_schema` (`datasets.py:81`), "Failname" (`datasets.py:21`)
- Unused imports: `settings` in `database/connection.py:3`, `Path` in `config/settings.py:2`
- Unused function: `get_connection()` in `database/__init__.py:10`
- `self.__connection` → `self._connection` (name-mangling is pointless here)
- `__init__.py:main()` prints "Hello"; the `project.scripts` entry is dead. Make it run uvicorn or delete it.
- `pyproject.toml:4` placeholder description
- Run `ruff format` + `ruff check` (e.g. `chunk:=`, `"name":column[0]`, missing EOF newlines)
- `@router.post("/")` — `POST /api/v1/datasets` (no slash) gets a 307 redirect; consider `""`

## Tests to add (`tests/test_datasets.py`)
Use FastAPI `TestClient` with a `tmp_path` DB/upload dir via settings override.
- Upload valid CSV → 201, correct `row_count`
- Upload non-CSV → 400
- GET uploaded id → columns + `row_count`
- GET unknown UUID → 404
- GET non-UUID id → 422

## Worth noting in README as trade-offs (not fixing now)
- Raw CSV kept after ingest → data stored twice (file + table).
- No metadata table (original filename, created_at) — needed once a list endpoint exists.
- No dedupe of identical uploads.

## Verification
```
uv run ruff check . && uv run ruff format --check .
uv run pytest
uv run uvicorn natural_language_insights.main:app
curl -F file=@sample.csv localhost:8000/api/v1/datasets/
curl localhost:8000/api/v1/datasets/<id>          # 200
curl localhost:8000/api/v1/datasets/not-a-uuid    # 422
curl localhost:8000/api/v1/datasets/$(uuidgen)    # 404
```
