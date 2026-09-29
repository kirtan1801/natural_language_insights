from uuid import uuid4

from natural_language_insights.database import db_query, init_schema


def test_restart_fails_jobs_left_in_flight(client):
    job_id, dataset_id = uuid4(), uuid4()
    db_query(
        "INSERT INTO datasets (id, filename, status) VALUES (?, 'x.csv', 'ingesting')", [dataset_id]
    )
    db_query(
        "INSERT INTO jobs (id, kind, dataset_id, status) VALUES (?, 'ingest', ?, 'running')",
        [job_id, dataset_id],
    )

    init_schema()  # what startup runs

    job = client.get(f"/api/v1/jobs/{job_id}").json()
    assert job["status"] == "failed"
    assert "restart" in job["error"]
    assert client.get(f"/api/v1/datasets/{dataset_id}").json()["status"] == "failed"
