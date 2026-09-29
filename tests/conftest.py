import os
import tempfile
import time

import pytest

# Must run before the app is imported: settings are read at import time.
_tmp = tempfile.mkdtemp()
os.environ["DATABASE_PATH"] = f"{_tmp}/test.db"
os.environ["UPLOAD_DIRECTORY"] = f"{_tmp}/uploads"
os.environ["MAX_UPLOAD_MB"] = "1"

from fastapi.testclient import TestClient

from natural_language_insights.main import app

CSV = b"order_id,amount,country\n1,9.5,UK\n2,3.0,FR\n3,1.25,UK\n"


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as client:
        yield client


def wait_for_job(client, job_id: str, timeout: float = 10) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = client.get(f"/api/v1/jobs/{job_id}").json()
        if job["status"] in ("succeeded", "failed"):
            return job
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} did not finish")


def upload(client, content: bytes = CSV, filename: str = "orders.csv"):
    return client.post("/api/v1/datasets", files={"file": (filename, content, "text/csv")})


@pytest.fixture
def dataset_id(client) -> str:
    accepted = upload(client).json()
    assert wait_for_job(client, accepted["job_id"])["status"] == "succeeded"
    return accepted["dataset_id"]
