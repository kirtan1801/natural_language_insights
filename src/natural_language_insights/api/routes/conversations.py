import json
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from natural_language_insights.api.routes.datasets import (
    QuestionRequest,
    require_ready,
    submit_question,
)
from natural_language_insights.database import db_query, db_records

router = APIRouter(prefix="/api/v1/conversations", tags=["conversations"])

MAX_HISTORY_TURNS = 6  # earlier answered turns sent to the model with a follow-up
TITLE_LENGTH = 80


class ConversationCreate(BaseModel):
    dataset_id: UUID


class Conversation(BaseModel):
    conversation_id: UUID
    dataset_id: UUID
    filename: str
    title: str | None
    created_at: datetime


class Turn(BaseModel):
    job_id: UUID
    question: str
    status: str
    result: dict[str, Any] | None
    error: str | None
    created_at: datetime


class ConversationDetail(Conversation):
    turns: list[Turn]


class QuestionAccepted(BaseModel):
    job_id: UUID
    conversation_id: UUID


CONVERSATION_SQL = """
    SELECT c.id AS conversation_id, c.dataset_id, d.filename, c.title, c.created_at
    FROM conversations c JOIN datasets d ON d.id = c.dataset_id
"""


def load_conversation(conversation_id: UUID) -> Conversation:
    rows = db_records(CONVERSATION_SQL + " WHERE c.id = ?", [conversation_id])
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found.")
    return Conversation(**rows[0])


@router.post("", status_code=status.HTTP_201_CREATED, response_model=Conversation)
def create_conversation(body: ConversationCreate) -> Conversation:
    require_ready(body.dataset_id)
    conversation_id = uuid4()
    db_query(
        "INSERT INTO conversations (id, dataset_id) VALUES (?, ?)",
        [conversation_id, body.dataset_id],
    )
    return load_conversation(conversation_id)


@router.get("", response_model=list[Conversation])
def list_conversations() -> list[Conversation]:
    rows = db_records(CONVERSATION_SQL + " ORDER BY c.created_at DESC")
    return [Conversation(**row) for row in rows]


@router.get("/{conversation_id}", response_model=ConversationDetail)
def get_conversation(conversation_id: UUID) -> ConversationDetail:
    conversation = load_conversation(conversation_id)
    rows = db_records(
        "SELECT id, status, input, result, error, created_at FROM jobs "
        "WHERE conversation_id = ? ORDER BY created_at",
        [conversation_id],
    )
    turns = [
        Turn(
            job_id=row["id"],
            question=json.loads(row["input"])["question"],
            status=row["status"],
            result=json.loads(row["result"]) if row["result"] else None,
            error=row["error"],
            created_at=row["created_at"],
        )
        for row in rows
    ]
    return ConversationDetail(**conversation.model_dump(), turns=turns)


@router.post(
    "/{conversation_id}/questions",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=QuestionAccepted,
)
def ask_in_conversation(conversation_id: UUID, body: QuestionRequest) -> QuestionAccepted:
    conversation = load_conversation(conversation_id)
    job_id = submit_question(
        conversation.dataset_id, body.question, conversation_id, history(conversation_id)
    )
    db_query(
        "UPDATE conversations SET title = ? WHERE id = ? AND title IS NULL",
        [body.question[:TITLE_LENGTH], conversation_id],
    )
    return QuestionAccepted(job_id=job_id, conversation_id=conversation_id)


def history(conversation_id: UUID) -> list[dict]:
    """Last answered turns, oldest first. Failed turns are left out: nothing to build on."""
    rows = db_records(
        "SELECT input, result FROM jobs WHERE conversation_id = ? AND status = 'succeeded' "
        "ORDER BY created_at DESC LIMIT ?",
        [conversation_id, MAX_HISTORY_TURNS],
    )
    return [
        {"question": json.loads(row["input"])["question"], "result": json.loads(row["result"])}
        for row in reversed(rows)
    ]
