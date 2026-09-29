"""Run the eval set against a running server.

    uv run python scripts/run_evals.py path/to/online_retail.csv

Expected answers are not stored as numbers: each case carries reference SQL written by
hand (one query per acceptable interpretation) and computed here from the same CSV.
A case passes if the app's answer matches any of them. Unanswerable cases pass only
when the app refuses. Exit code is non-zero if any case fails.
"""

import argparse
import json
import sys
import time
from pathlib import Path

import duckdb
import httpx

EVALS = Path(__file__).parent.parent / "evals" / "questions.json"
RELATIVE_TOLERANCE = 0.01


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("csv", help="the CSV the eval questions are written against")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--dataset-id", help="reuse an already-loaded dataset")
    parser.add_argument("--only", help="run a single case by id")
    args = parser.parse_args()

    cases = json.loads(EVALS.read_text())
    if args.only:
        cases = [case for case in cases if case["id"] == args.only]

    reference = duckdb.connect()
    reference.execute("CREATE TABLE t AS SELECT * FROM read_csv(?, sample_size = -1)", [args.csv])

    client = httpx.Client(base_url=args.base_url + "/api/v1", timeout=60)
    dataset_id = args.dataset_id or upload(client, args.csv)

    # Submit every question up front, then poll: exercises the job queue concurrently.
    job_ids = {case["id"]: ask(client, dataset_id, case["question"]) for case in cases}
    passed = 0
    for case in cases:
        job = wait(client, job_ids[case["id"]])
        ok, detail = grade(case, job, reference)
        passed += ok
        print(f"{'PASS' if ok else 'FAIL'}  {case['id']:<26} {detail}")
    print(f"\n{passed}/{len(cases)} passed")
    return 0 if passed == len(cases) else 1


def upload(client: httpx.Client, csv: str) -> str:
    with open(csv, "rb") as file:
        response = client.post("/datasets", files={"file": (Path(csv).name, file, "text/csv")})
    response.raise_for_status()
    accepted = response.json()
    job = wait(client, accepted["job_id"])
    if job["status"] != "succeeded":
        sys.exit(f"Ingestion failed: {job['error']}")
    return accepted["dataset_id"]


def ask(client: httpx.Client, dataset_id: str, question: str) -> str:
    response = client.post(f"/datasets/{dataset_id}/questions", json={"question": question})
    response.raise_for_status()
    return response.json()["job_id"]


def wait(client: httpx.Client, job_id: str, timeout: float = 300) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = client.get(f"/jobs/{job_id}").json()
        if job["status"] in ("succeeded", "failed"):
            return job
        time.sleep(1)
    return {"status": "failed", "error": "timed out waiting for job"}


def grade(case: dict, job: dict, reference: duckdb.DuckDBPyConnection) -> tuple[bool, str]:
    if job["status"] != "succeeded":
        return False, f"job failed: {job['error']}"
    answer = job["result"]

    if case["match"] == "refuse":
        if answer["answerable"]:
            return False, f"answered instead of refusing: {answer['rows'][:3]}"
        return True, f"refused: {answer['reason']}"
    if not answer["answerable"]:
        return False, f"refused: {answer['reason']}"

    cells = [cell for row in answer["rows"] for cell in row]
    expectations = [reference.execute(sql).fetchall() for sql in case["reference_sql"]]
    for expected in expectations:
        if matches(case, expected, cells):
            return True, ""
    return False, f"expected one of {summarize(case, expectations)}, got {answer['rows'][:5]}"


def matches(case: dict, expected: list[tuple], cells: list) -> bool:
    if case["match"] == "top_values":
        texts = {str(cell).strip().lower() for cell in cells}
        wanted = [row[: case.get("columns", 1)] for row in expected[: case["k"]]]
        return all(str(value).strip().lower() in texts for row in wanted for value in row)
    if case["match"] == "numbers":
        numbers = [float(cell) for cell in cells if isinstance(cell, int | float)]
        return all(any(close(value, n) for n in numbers) for value in expected[0])
    raise ValueError(f"unknown match type {case['match']!r}")


def close(expected: float, actual: float) -> bool:
    # Shares may come back as a fraction or a percentage.
    return any(
        abs(actual * scale - expected) <= RELATIVE_TOLERANCE * abs(expected)
        for scale in (1, 100, 0.01)
    )


def summarize(case: dict, expectations: list[list[tuple]]) -> list:
    if case["match"] == "numbers":
        return [rows[0] for rows in expectations]
    return [[row[: case.get("columns", 1)] for row in rows[: case["k"]]] for rows in expectations]


if __name__ == "__main__":
    sys.exit(main())
