from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.report import ReportCategory, ReportSender, ReportStatus


class ReportCreate(BaseModel):
    category: ReportCategory
    description: str = Field(min_length=10, max_length=10_000)


class ReportAccessRequest(BaseModel):
    case_number: str = Field(min_length=5, max_length=20)
    pin: str = Field(min_length=8, max_length=64)
    session_token: str = Field(min_length=32, max_length=64)


class ReportReplyRequest(BaseModel):
    case_number: str = Field(min_length=5, max_length=20)
    pin: str = Field(min_length=8, max_length=64)
    session_token: str = Field(min_length=32, max_length=64)
    content: str = Field(min_length=1, max_length=5_000)


class MessageOut(BaseModel):
    id: UUID
    sender: ReportSender
    content: str
    sent_at: datetime

    model_config = {"from_attributes": True}


class ReportOut(BaseModel):
    id: UUID
    case_number: str
    category: ReportCategory
    status: ReportStatus
    submitted_at: datetime
    acknowledged_at: datetime | None
    feedback_due_at: datetime | None
    closed_at: datetime | None
    messages: list[MessageOut]

    model_config = {"from_attributes": True}


class ReportSubmitResult(BaseModel):
    case_number: str
    pin: str


class AdminStatusUpdate(BaseModel):
    status: ReportStatus


class AdminReplyRequest(BaseModel):
    content: str = Field(min_length=1, max_length=5_000)
