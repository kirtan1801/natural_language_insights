import json
from uuid import uuid4

from conftest import upload, wait_for_job


def test_upload_is_async_and_ingests(client):
    response = upload(client)
    assert response.status_code == 202
    job = wait_for_job(client, response.json()["job_id"])
    assert job["status"] == "succeeded"
    assert job["result"]["row_count"] == 3


def test_get_dataset_lists_inferred_columns(client, dataset_id):
    body = client.get(f"/api/v1/datasets/{dataset_id}").json()
    assert body["status"] == "ready"
    assert body["row_count"] == 3
    assert [(c["name"], c["type"]) for c in body["columns"]] == [
        ("order_id", "BIGINT"),
        ("amount", "DOUBLE"),
        ("country", "VARCHAR"),
    ]


def test_latin1_csv_is_ingested(client):
    content = "product,price\nCafé crème,2.5\n".encode("latin-1")
    job = wait_for_job(client, upload(client, content).json()["job_id"])
    assert job["status"] == "succeeded"


def test_header_only_csv_fails(client):
    accepted = upload(client, b"a,b\n").json()
    job = wait_for_job(client, accepted["job_id"])
    assert job["status"] == "failed"
    assert "no rows" in job["error"]
    dataset = client.get(f"/api/v1/datasets/{accepted['dataset_id']}").json()
    assert dataset["status"] == "failed"


def test_non_csv_rejected(client):
    response = upload(client, filename="orders.txt")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "http_error"


def test_empty_file_rejected(client):
    assert upload(client, b"").status_code == 400


def test_oversized_upload_rejected(client):
    response = upload(client, b"a\n" + b"1\n" * 600_000)  # > 1 MB test limit
    assert response.status_code == 413


def test_unknown_dataset_is_404(client):
    response = client.get(f"/api/v1/datasets/{uuid4()}")
    assert response.status_code == 404
    assert response.json() == {"error": {"code": "http_error", "message": "Dataset not found."}}


def test_non_uuid_id_is_422(client):
    response = client.get('/api/v1/datasets/x"; DROP TABLE t; --')
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_unknown_job_is_404(client):
    assert client.get(f"/api/v1/jobs/{uuid4()}").status_code == 404


def test_job_events_stream_until_done(client):
    accepted = upload(client).json()
    events = []
    with client.stream("GET", f"/api/v1/jobs/{accepted['job_id']}/events") as response:
        assert response.headers["content-type"].startswith("text/event-stream")
        for line in response.iter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line.removeprefix("data: "))["status"])
    assert events[-1] == "succeeded"
    assert events == sorted(set(events), key=events.index)  # each status sent once


def test_job_events_unknown_job_is_404(client):
    assert client.get(f"/api/v1/jobs/{uuid4()}/events").status_code == 404
