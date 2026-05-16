from __future__ import annotations

from enum import Enum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class InputType(str, Enum):
    url = "url"
    text = "text"


class Mode(str, Enum):
    short = "Short"
    balanced = "Balanced"
    detailed = "Detailed"


class DeriveRequest(BaseModel):
    inputType: InputType
    mode: Mode = Mode.balanced

    url: str | None = None
    text: str | None = None

    # Optional label to show in the Word doc.
    sourceLabel: str | None = None

    @field_validator("url", mode="before")
    @classmethod
    def strip_url(cls, v: object) -> object:
        if isinstance(v, str):
            return v.strip()
        return v

    @field_validator("text", mode="before")
    @classmethod
    def strip_text(cls, v: object) -> object:
        if isinstance(v, str):
            return v.strip()
        return v

    def validate_input(self) -> None:
        if self.inputType == InputType.url:
            if not self.url:
                raise ValueError("url is required when inputType=url")
        if self.inputType == InputType.text:
            if not self.text or not self.text.strip():
                raise ValueError("text is required when inputType=text")


class JobStatus(str, Enum):
    queued = "queued"
    running = "running"
    failed = "failed"
    done = "done"
    notes_saved = "notes_saved"


SNIPPET_MAX_LENGTH = 200


def clamp_snippet(snippet: str, *, max_length: int = SNIPPET_MAX_LENGTH) -> str:
    """Keep citations within schema limits; prefix of a source quote stays verifiable."""
    s = snippet.strip()
    if len(s) <= max_length:
        return s
    return s[:max_length].rstrip()


class Citation(BaseModel):
    snippet: str = Field(min_length=1, max_length=SNIPPET_MAX_LENGTH)
    chunkIndex: int | None = None

    @field_validator("snippet", mode="before")
    @classmethod
    def normalize_snippet(cls, v: object) -> object:
        if isinstance(v, str):
            return clamp_snippet(v)
        return v


class Bullet(BaseModel):
    id: str = Field(min_length=1, max_length=120)
    text: str = Field(min_length=1, max_length=600)
    citations: list[Citation] = Field(default_factory=list)


class Topic(BaseModel):
    id: str = Field(min_length=1, max_length=120)
    title: str = Field(min_length=1, max_length=160)
    bullets: list[Bullet] = Field(default_factory=list)


class DeriveTopics(BaseModel):
    topics: list[Topic]
    coverageNote: str | None = None
    coverageScore: float | None = None


class JobData(BaseModel):
    job_id: str
    inputType: InputType
    sourceLabel: str
    status: JobStatus
    progress: int = 0

    # LLM-generated draft topics.
    topics: list[Topic] = Field(default_factory=list)
    coverageNote: str | None = None
    coverageScore: float | None = None
    # User-edited version; if absent, we use `topics` for download.
    notes: list[Topic] | None = None

    error: str | None = None


class SaveNotesRequest(BaseModel):
    topics: list[Topic]

