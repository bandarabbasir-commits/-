from datetime import datetime
from typing import Any, Literal, Optional
from pydantic import BaseModel, Field, field_validator


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=256)


class BootstrapAdminRequest(BaseModel):
    username: str = Field("admin", min_length=2, max_length=64, pattern=r"^[A-Za-z0-9_.\-]+$")
    display_name: str = Field(..., min_length=2, max_length=120)
    password: str = Field(..., min_length=8, max_length=128)


class ThemeUpdateRequest(BaseModel):
    theme_preference: Literal["system", "light", "dark"]


class UserPublicMinimal(BaseModel):
    id: int
    display_name: str
    job_title: str
    department: str
    avatar_color: str
    is_online: bool = False


class UserAdminOut(BaseModel):
    id: int
    username: str
    display_name: str
    job_title: str
    department: str
    display_access_level: str
    org_role_type: str
    roles: list[str]
    is_active: bool
    is_deleted: bool
    avatar_color: str
    theme_preference: str
    open_assignment_count: int = 0
    created_at: datetime


class UserCreateRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=64, pattern=r"^[A-Za-z0-9_.\-]+$")
    display_name: str = Field(..., min_length=2, max_length=120)
    password: str = Field(..., min_length=8, max_length=128)
    job_title: str = Field("", max_length=120)
    department: str = Field("عمومی", min_length=1, max_length=120)
    display_access_level: Literal["employee", "supervisor", "expert"] = "employee"
    org_role_type: Literal["followup", "referral", "office", "technical"] = "followup"
    roles: list[Literal["admin", "manager", "author", "employee", "expert"]] = Field(..., min_length=1)


class UserUpdateRequest(BaseModel):
    display_name: str = Field(..., min_length=2, max_length=120)
    job_title: str = Field("", max_length=120)
    department: str = Field(..., min_length=1, max_length=120)
    display_access_level: Literal["employee", "supervisor", "expert"]
    org_role_type: Literal["followup", "referral", "office", "technical"]
    roles: list[Literal["admin", "manager", "author", "employee", "expert"]] = Field(..., min_length=1)
    version: int = Field(..., ge=1)


class UserPasswordResetRequest(BaseModel):
    new_password: str = Field(..., min_length=8, max_length=128)


class UserStatusToggleRequest(BaseModel):
    is_active: bool
    version: int = Field(..., ge=1)


class TaskDirectCreateRequest(BaseModel):
    source_type: Literal["sms", "phone", "in_person", "social"]
    requester_name: str = Field(..., min_length=2, max_length=120)
    requester_phone: str = Field(..., min_length=5, max_length=32)
    body: str = Field(..., min_length=5, max_length=5000)
    priority: Literal["urgent", "medium", "normal"] = "normal"
    action_flag: Literal["action", "followup"] = "action"
    manager_note: str = Field("", max_length=2000)
    receiver_ids: list[int] = Field(..., min_length=1, max_length=2)
    idempotency_key: Optional[str] = Field(None, max_length=128)

    @field_validator("receiver_ids")
    @classmethod
    def check_unique_receivers(cls, v: list[int]) -> list[int]:
        if len(set(v)) != len(v):
            raise ValueError("گیرندگان انتخاب‌شده نباید تکراری باشند.")
        return v


class TaskActionRequest(BaseModel):
    status: Literal["in_progress", "success", "failed"]
    report_text: str = Field(..., min_length=3, max_length=4000)
    is_private: bool = False
    forward_to_ids: list[int] = Field(default_factory=list, max_length=2)
    forward_reason: str = Field("", max_length=500)
    version: int = Field(..., ge=1)
    idempotency_key: Optional[str] = Field(None, max_length=128)


class TaskManagerUpdateRequest(BaseModel):
    priority: Literal["urgent", "medium", "normal"]
    action_flag: Literal["action", "followup"]
    manager_note: str = Field("", max_length=2000)
    receiver_ids: Optional[list[int]] = Field(None, min_length=1, max_length=2)
    version: int = Field(..., ge=1)

    @field_validator("receiver_ids")
    @classmethod
    def check_unique_update_receivers(cls, v: Optional[list[int]]) -> Optional[list[int]]:
        if v is not None and len(set(v)) != len(v):
            raise ValueError("گیرندگان انتخاب‌شده نباید تکراری باشند.")
        return v


class TaskSingleArchiveRequest(BaseModel):
    reason: str = Field("", max_length=300)


class TaskReopenRequest(BaseModel):
    reason: str = Field(..., min_length=3, max_length=500)
    receiver_ids: list[int] = Field(default_factory=list, max_length=2)
    version: int = Field(..., ge=1)


class TaskNoteCreateRequest(BaseModel):
    body: str = Field(..., min_length=1, max_length=3000)
    visibility: Literal["private", "shared_active_manager"] = "private"


class TaskReminderCreateRequest(BaseModel):
    jalali_date: str = Field(..., min_length=8, max_length=16)
    tehran_time: str = Field("09:00", min_length=4, max_length=8)
    note: str = Field("", max_length=500)
    idempotency_key: Optional[str] = Field(None, max_length=128)


class FolderCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)


class TaskFolderAssignRequest(BaseModel):
    folder_id: Optional[int] = None


class DraftCreateRequest(BaseModel):
    source_type: Literal["sms", "phone", "in_person", "social"] = "sms"
    requester_name: str = Field("", max_length=120)
    requester_phone: str = Field("", max_length=32)
    body: str = Field(..., min_length=3, max_length=5000)
    priority: Literal["urgent", "medium", "normal"] = "normal"
    action_flag: Literal["action", "followup"] = "action"


class DraftUpdateRequest(BaseModel):
    body: str = Field(..., min_length=3, max_length=5000)
    priority: Literal["urgent", "medium", "normal"]
    action_flag: Literal["action", "followup"]
    manager_note: str = Field("", max_length=2000)
    mark_ready: bool = False
    version: int = Field(..., ge=1)


class DraftDistributeRequest(BaseModel):
    receiver_ids: list[int] = Field(..., min_length=1, max_length=2)
    version: int = Field(..., ge=1)
    idempotency_key: Optional[str] = Field(None, max_length=128)


class DraftCloseRequest(BaseModel):
    manager_note: str = Field("", max_length=2000)
    version: int = Field(..., ge=1)


class DraftTrashRequest(BaseModel):
    reason: str = Field(..., min_length=3, max_length=500)
    version: int = Field(..., ge=1)


class VisitCreateRequest(BaseModel):
    person_or_org: str = Field(..., min_length=2, max_length=160)
    phone: str = Field(..., min_length=5, max_length=32)
    request_desc: str = Field(..., min_length=3, max_length=4000)
    followup_desc: str = Field(..., min_length=3, max_length=4000)
    action_taken: str = Field(..., min_length=3, max_length=4000)


class VisitReviewRequest(BaseModel):
    decision: Literal["approved", "rejected"]
    review_note: str = Field("", max_length=500)
    version: int = Field(..., ge=1)


class VisitBulkActionRequest(BaseModel):
    visit_ids: list[int] = Field(..., min_length=1, max_length=200)
    reason: str = Field("", max_length=300)


class ChatSendRequest(BaseModel):
    body: str = Field(..., min_length=1, max_length=2000)
    client_msg_id: Optional[str] = Field(None, max_length=128)


class ChatReadMarkRequest(BaseModel):
    message_ids: list[int] = Field(..., min_length=1, max_length=100)


class RatingCreateRequest(BaseModel):
    user_id: int
    score: int = Field(..., ge=1, le=5)
    reason: str = Field(..., min_length=2, max_length=300)


class RatingUpdateRequest(BaseModel):
    score: int = Field(..., ge=1, le=5)
    reason: str = Field(..., min_length=2, max_length=300)


class TrashPurgeRequest(BaseModel):
    target_type: Literal["task", "visit"] = "task"
    ids: list[int] = Field(..., min_length=1, max_length=200)
    confirm_phrase: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=128)
    expected_count: int = Field(..., ge=1)


class TrashRestoreRequest(BaseModel):
    target_type: Literal["task", "visit"] = "task"
    version: int = Field(..., ge=1)


class ArchivePreviewRequest(BaseModel):
    target_type: Literal["task", "visit"]
    statuses: list[str] = Field(default_factory=list)
    before_jalali_date: Optional[str] = None
    reason: str = Field("", max_length=300)


class ArchiveRestoreRequest(BaseModel):
    target_type: Literal["task", "visit"]
    ids: list[int] = Field(..., min_length=1, max_length=200)


class BackupRestoreConfirmRequest(BaseModel):
    backup_payload: dict[str, Any]
    confirm_phrase: str
    password: str
