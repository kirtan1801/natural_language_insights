import json
from datetime import datetime
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, UploadFile, status
from pydantic import BaseModel, Field

from natural_language_insights import jobs
from natural_language_insights.config.settings import settings
from natural_language_insights.database import db_query, db_records
from natural_language_insights.ingest import ingest
from natural_language_insights.qa import answer_question

router = APIRouter(prefix="/api/v1/datasets", tags=["datasets"])

CHUNK_SIZE = 1024 * 1024


class Column(BaseModel):
    name: str
    type: str


class Dataset(BaseModel):
    dataset_id: UUID
    filename: str
    status: str
    row_count: int | None
    error: str | None
    created_at: datetime
    columns: list[Column] = []


class JobAccepted(BaseModel):
    job_id: UUID
    dataset_id: UUID


class QuestionRequest(BaseModel):
    question: str = Field(min_length=3, max_length=1000)


def load_dataset(dataset_id: UUID) -> Dataset:
    rows = db_records("SELECT * FROM datasets WHERE id = ?", [dataset_id])
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Dataset not found.")
    return to_dataset(rows[0], with_columns=True)


def to_dataset(row: dict, with_columns: bool = False) -> Dataset:
    columns = []
    if with_columns and row["schema_context"]:
        context = json.loads(row["schema_context"])
        columns = [Column(name=c["name"], type=c["type"]) for c in context["columns"]]
    return Dataset(
        dataset_id=row["id"],
        filename=row["filename"],
        status=row["status"],
        row_count=row["row_count"],
        error=row["error"],
        created_at=row["created_at"],
        columns=columns,
    )


# Plain `def` handlers: FastAPI runs them in a threadpool, so file and DuckDB I/O
# don't block the event loop.
@router.post("", status_code=status.HTTP_202_ACCEPTED, response_model=JobAccepted)
def upload_dataset(file: UploadFile) -> JobAccepted:
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A .csv file is required.")

    upload_directory = Path(settings.upload_directory)
    upload_directory.mkdir(parents=True, exist_ok=True)
    dataset_id = uuid4()
    destination = upload_directory / f"{dataset_id}.csv"
    save_upload(file, destination)

    db_query(
        "INSERT INTO datasets (id, filename, status) VALUES (?, ?, 'ingesting')",
        [dataset_id, file.filename],
    )
    job_id = jobs.submit(
        "ingest",
        dataset_id,
        {"filename": file.filename},
        lambda: ingest(dataset_id, destination),
    )
    return JobAccepted(job_id=job_id, dataset_id=dataset_id)


def save_upload(file: UploadFile, destination: Path) -> None:
    max_bytes = settings.max_upload_mb * 1024 * 1024
    written = 0
    try:
        with destination.open("wb") as output:
            while chunk := file.file.read(CHUNK_SIZE):
                written += len(chunk)
                if written > max_bytes:
                    raise HTTPException(
                        status.HTTP_413_CONTENT_TOO_LARGE,
                        f"File exceeds the {settings.max_upload_mb} MB limit.",
                    )
                output.write(chunk)
    except HTTPException:
        destination.unlink(missing_ok=True)
        raise
    except OSError as exc:
        destination.unlink(missing_ok=True)
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to save uploaded file."
        ) from exc
    finally:
        file.file.close()
    if written == 0:
        destination.unlink(missing_ok=True)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The file is empty.")


@router.get("", response_model=list[Dataset])
def list_datasets() -> list[Dataset]:
    rows = db_records("SELECT * FROM datasets ORDER BY created_at DESC")
    return [to_dataset(row) for row in rows]


@router.get("/{dataset_id}", response_model=Dataset)
def get_dataset(dataset_id: UUID) -> Dataset:
    return load_dataset(dataset_id)


@router.post(
    "/{dataset_id}/questions",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=JobAccepted,
)
def ask_question(dataset_id: UUID, body: QuestionRequest) -> JobAccepted:
    """One-off question with no conversation history (used by scripts and the evals)."""
    job_id = submit_question(dataset_id, body.question)
    return JobAccepted(job_id=job_id, dataset_id=dataset_id)


def require_ready(dataset_id: UUID) -> Dataset:
    dataset = load_dataset(dataset_id)
    if dataset.status != "ready":
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"Dataset is {dataset.status}; it must be ready."
        )
    return dataset


def submit_question(
    dataset_id: UUID,
    question: str,
    conversation_id: UUID | None = None,
    history: list[dict] = (),
) -> UUID:
    require_ready(dataset_id)
    return jobs.submit(
        "question",
        dataset_id,
        {"question": question},
        lambda: answer_question(dataset_id, question, history),
        conversation_id=conversation_id,
    )
