import enum
from datetime import datetime, timezone
# pyrefly: ignore [missing-import]
from pydantic import BaseModel, EmailStr, Field

class Role(str, enum.Enum):
    student = "student"
    faculty = "faculty"
    staff = "staff"
    administrator = "administrator"


class TicketStatus(str, enum.Enum):
    submitted = "submitted"
    assigned = "assigned"
    in_progress = "in_progress"
    resolved = "resolved"
    reopened = "reopened"
    escalated = "escalated"


class UserCreate(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=150)
    password: str = Field(min_length=8)
    role: Role = Role.student
    phone: str | None = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TicketCreate(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    description: str = Field(min_length=1)
    category_id: str
    department_id: str
    confidential: bool = False


class TicketUpdate(BaseModel):
    status: TicketStatus
    remarks: str | None = None
    attachments: list[str] = Field(default_factory=list)


class TicketAction(BaseModel):
    remarks: str | None = None
    attachments: list[str] = Field(default_factory=list)


class AppointmentProposal(BaseModel):
    starts_at: datetime
    ends_at: datetime


class AppointmentResponse(BaseModel):
    decision: str


class AcknowledgeRequest(BaseModel):
    technician_id: str
    name: str


class RoleVerification(BaseModel):
    role: Role


class AssignmentRequest(BaseModel):
    technician_id: str


class FeedbackCreate(BaseModel):
    rating: int = Field(ge=1, le=5)
    comment: str | None = None


class MessageCreate(BaseModel):
    text: str = Field(min_length=1)
    recipient_id: str | None = None
    thread_id: str | None = None


class RoleUpdate(BaseModel):
    role: Role

class SettingsUpdate(BaseModel):
    config: dict[str, object]

class NoticeCreate(BaseModel):
    title: str
    body: str

class AdminUserCreate(BaseModel):
    name: str = Field(min_length=1)
    email: EmailStr
    phone: str | None = None
    role: Role = Role.staff
    department: str | None = None

