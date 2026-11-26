from datetime import date, datetime
from typing import Any, Optional
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), nullable=False)
    username_lower: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    job_title: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    department: Mapped[str] = mapped_column(String(120), nullable=False, default="عمومی")
    display_access_level: Mapped[str] = mapped_column(String(32), nullable=False, default="employee")
    org_role_type: Mapped[str] = mapped_column(String(32), nullable=False, default="followup")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    avatar_color: Mapped[str] = mapped_column(String(16), nullable=False, default="#0D9488")
    theme_preference: Mapped[str] = mapped_column(String(16), nullable=False, default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    roles: Mapped[list["UserRole"]] = relationship(
        back_populates="user", foreign_keys="UserRole.user_id", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("display_access_level IN ('employee', 'supervisor', 'expert')", name="ck_user_disp_lvl"),
        CheckConstraint("org_role_type IN ('followup', 'referral', 'office', 'technical')", name="ck_user_org_type"),
        CheckConstraint("theme_preference IN ('system', 'light', 'dark')", name="ck_user_theme"),
        Index("ix_users_active_dept", "is_active", "is_deleted", "department"),
    )


class UserRole(Base):
    __tablename__ = "user_roles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    granted_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    user: Mapped["User"] = relationship(back_populates="roles", foreign_keys=[user_id])

    __table_args__ = (
        UniqueConstraint("user_id", "role", name="uq_user_roles_user_role"),
        CheckConstraint("role IN ('admin', 'manager', 'author', 'employee', 'expert')", name="ck_user_roles_valid"),
        Index("ix_user_roles_role", "role"),
    )


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    csrf_token: Mapped[str] = mapped_column(String(64), nullable=False)
    ip_address: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    user_agent: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    idle_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    absolute_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    revoke_reason: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        Index("ix_sessions_user_active", "user_id", "revoked_at"),
    )


class SmsTask(Base):
    __tablename__ = "sms_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_type: Mapped[str] = mapped_column(String(24), nullable=False, default="sms")
    body: Mapped[str] = mapped_column(Text, nullable=False)
    body_normalized: Mapped[str] = mapped_column(Text, nullable=False, default="")
    requester_name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    requester_phone_norm: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    priority: Mapped[str] = mapped_column(String(16), nullable=False, default="normal")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    action_flag: Mapped[str] = mapped_column(String(16), nullable=False, default="action")
    manager_note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    first_action_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    latest_report_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    latest_action_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("task_actions.id", ondelete="SET NULL", use_alter=True, name="fk_sms_tasks_latest_action"),
        nullable=True,
    )
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    view_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    needs_reassignment: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, unique=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __table_args__ = (
        CheckConstraint("source_type IN ('sms', 'phone', 'in_person', 'social')", name="ck_sms_task_source"),
        CheckConstraint("priority IN ('urgent', 'medium', 'normal')", name="ck_sms_task_priority"),
        CheckConstraint("status IN ('pending', 'in_progress', 'success', 'failed')", name="ck_sms_task_status"),
        CheckConstraint("action_flag IN ('action', 'followup')", name="ck_sms_task_flag"),
        Index("ix_sms_tasks_status_created", "is_deleted", "status", "created_at", "id"),
        Index("ix_sms_tasks_first_action", "first_action_at", "id"),
        Index(
            "ix_sms_tasks_body_trgm",
            "body_normalized",
            postgresql_using="gin",
            postgresql_ops={"body_normalized": "gin_trgm_ops"},
        ),
    )


class TaskAssignment(Base):
    __tablename__ = "task_assignments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("sms_tasks.id", ondelete="CASCADE"), nullable=False)
    sender_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    receiver_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    priority_at_assignment: Mapped[str] = mapped_column(String(16), nullable=False, default="normal")
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    end_reason: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    forward_reason: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        Index(
            "uq_active_task_receiver",
            "task_id",
            "receiver_id",
            unique=True,
            postgresql_where=text("is_active = true"),
        ),
        Index("ix_task_assignments_receiver_active", "receiver_id", "is_active", "task_id"),
        Index("ix_task_assignments_task_active", "task_id", "is_active"),
    )


class TaskAction(Base):
    __tablename__ = "task_actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("sms_tasks.id", ondelete="CASCADE"), nullable=False)
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    status_after: Mapped[str] = mapped_column(String(24), nullable=False)
    report_text: Mapped[str] = mapped_column(Text, nullable=False)
    report_normalized: Mapped[str] = mapped_column(Text, nullable=False, default="")
    is_private: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_task_actions_task_created", "task_id", "created_at", "id"),
        Index("ix_task_actions_actor", "actor_id", "created_at"),
        Index(
            "ix_task_actions_report_trgm",
            "report_normalized",
            postgresql_using="gin",
            postgresql_ops={"report_normalized": "gin_trgm_ops"},
        ),
    )


class TaskEvent(Base):
    __tablename__ = "task_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("sms_tasks.id", ondelete="CASCADE"), nullable=False)
    actor_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    actor_display_name: Mapped[str] = mapped_column(String(120), nullable=False, default="سامانه")
    actor_role_label: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    event_type: Mapped[str] = mapped_column(String(48), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    __table_args__ = (
        Index("ix_task_events_task_created", "task_id", "created_at", "id"),
    )


class TaskNote(Base):
    __tablename__ = "task_notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("sms_tasks.id", ondelete="CASCADE"), nullable=False)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    visibility: Mapped[str] = mapped_column(String(32), nullable=False, default="private")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint("visibility IN ('private', 'shared_active_manager')", name="ck_task_note_visibility"),
        Index("ix_task_notes_task_owner", "task_id", "owner_id", "visibility"),
    )


class TaskReminder(Base):
    __tablename__ = "task_reminders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("sms_tasks.id", ondelete="CASCADE"), nullable=False)
    assignment_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("task_assignments.id", ondelete="SET NULL"), nullable=True
    )
    receiver_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    note: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    fired: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    fired_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    cancel_reason: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index(
            "ix_task_reminders_due_pending",
            "due_at",
            postgresql_where=text("fired = false AND cancelled_at IS NULL"),
        ),
        Index("ix_task_reminders_task_receiver", "task_id", "receiver_id"),
    )


class Draft(Base):
    __tablename__ = "drafts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    source_type: Mapped[str] = mapped_column(String(24), nullable=False, default="sms")
    requester_name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    requester_phone_norm: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    body: Mapped[str] = mapped_column(Text, nullable=False)
    body_normalized: Mapped[str] = mapped_column(Text, nullable=False, default="")
    priority: Mapped[str] = mapped_column(String(16), nullable=False, default="normal")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="new")
    action_flag: Mapped[str] = mapped_column(String(16), nullable=False, default="action")
    manager_note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    edited_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    distributed_task_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("sms_tasks.id", ondelete="SET NULL"), nullable=True, unique=True
    )
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    delete_reason: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, unique=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('new', 'edited', 'ready_to_distribute', 'distributed', 'closed')",
            name="ck_draft_status",
        ),
        CheckConstraint("priority IN ('urgent', 'medium', 'normal')", name="ck_draft_priority"),
        CheckConstraint("source_type IN ('sms', 'phone', 'in_person', 'social')", name="ck_draft_source"),
        Index("ix_drafts_status_author", "is_deleted", "status", "author_id", "created_at"),
    )


class PublicVisit(Base):
    __tablename__ = "public_visits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    creator_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    person_or_org: Mapped[str] = mapped_column(String(160), nullable=False)
    phone_norm: Mapped[str] = mapped_column(String(20), nullable=False)
    request_desc: Mapped[str] = mapped_column(Text, nullable=False)
    followup_desc: Mapped[str] = mapped_column(Text, nullable=False)
    action_taken: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending_review")
    review_note: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    reviewed_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint("status IN ('pending_review', 'approved', 'rejected')", name="ck_visit_status"),
        Index("ix_visits_status_creator", "is_deleted", "status", "creator_id", "created_at"),
    )


class VisitFolder(Base):
    __tablename__ = "visit_folders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_visit_folder_user_name"),)


class VisitFolderItem(Base):
    __tablename__ = "visit_folder_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    folder_id: Mapped[int] = mapped_column(ForeignKey("visit_folders.id", ondelete="CASCADE"), nullable=False)
    visit_id: Mapped[int] = mapped_column(ForeignKey("public_visits.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (UniqueConstraint("user_id", "visit_id", name="uq_visit_folder_item_user_visit"),)


class PersonalFolder(Base):
    __tablename__ = "personal_folders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_personal_folder_user_name"),)


class FolderItem(Base):
    __tablename__ = "folder_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    folder_id: Mapped[int] = mapped_column(ForeignKey("personal_folders.id", ondelete="CASCADE"), nullable=False)
    task_id: Mapped[int] = mapped_column(ForeignKey("sms_tasks.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "task_id", name="uq_folder_item_user_task"),
        Index("ix_folder_items_folder", "folder_id"),
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    channel: Mapped[str] = mapped_column(String(24), nullable=False, default="public")
    sender_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    client_msg_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint("channel IN ('public', 'announcements')", name="ck_chat_channel"),
        Index("ix_chat_messages_channel_created", "channel", "created_at", "id"),
    )


class ChatRead(Base):
    __tablename__ = "chat_reads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("chat_messages.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    read_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("message_id", "user_id", name="uq_chat_read_msg_user"),
        Index("ix_chat_reads_user", "user_id", "message_id"),
    )


class UserRating(Base):
    __tablename__ = "user_ratings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    task_id: Mapped[Optional[int]] = mapped_column(ForeignKey("sms_tasks.id", ondelete="SET NULL"), nullable=True)
    awarded_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    award_date_tehran: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint("score >= 1 AND score <= 5", name="ck_rating_score_range"),
        CheckConstraint(
            "source IN ('manual', 'auto_daily_login', 'auto_timely_action', 'auto_success')",
            name="ck_rating_source",
        ),
        Index("ix_user_ratings_user", "user_id", "created_at"),
    )


class LoginLog(Base):
    __tablename__ = "login_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    username_snapshot: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    ip_address: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    user_agent: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    session_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint("action IN ('login', 'logout')", name="ck_login_log_action"),
        Index(
            "uq_login_logs_session_logout",
            "session_id",
            unique=True,
            postgresql_where=text("action = 'logout' AND session_id IS NOT NULL"),
        ),
        Index("ix_login_logs_created", "created_at", "id"),
        Index("ix_login_logs_user", "user_id", "action", "created_at"),
    )


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    actor_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target_type: Mapped[str] = mapped_column(String(48), nullable=False)
    target_id: Mapped[str] = mapped_column(String(64), nullable=False)
    before_state: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    after_state: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    ip_address: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_audit_log_created", "created_at", "id"),
        Index("ix_audit_log_target", "target_type", "target_id"),
    )


class ArchivedTask(Base):
    __tablename__ = "archived_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("sms_tasks.id", ondelete="CASCADE"), nullable=False, unique=True)
    archived_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    archived_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)


class ArchivedVisit(Base):
    __tablename__ = "archived_visits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    visit_id: Mapped[int] = mapped_column(ForeignKey("public_visits.id", ondelete="CASCADE"), nullable=False, unique=True)
    archived_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    archived_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)


class OutboxEvent(Base):
    __tablename__ = "outbox_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    channel: Mapped[str] = mapped_column(String(64), nullable=False, default="global")
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        Index("ix_outbox_unpublished", "published_at", "id"),
    )


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    type: Mapped[str] = mapped_column(String(48), nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    body: Mapped[str] = mapped_column(String(500), nullable=False)
    task_id: Mapped[Optional[int]] = mapped_column(ForeignKey("sms_tasks.id", ondelete="SET NULL"), nullable=True)
    outbox_event_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("outbox_events.id", ondelete="SET NULL"), nullable=True
    )
    dedup_key: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    read_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_notifications_user_unread", "user_id", "is_read", "created_at", "id"),
    )


class WsPresence(Base):
    __tablename__ = "ws_presence"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False)
    connection_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    last_heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_ws_presence_expires", "expires_at"),
        Index("ix_ws_presence_user", "user_id", "expires_at"),
    )


class AuthRateLimit(Base):
    __tablename__ = "auth_rate_limits"

    bucket_key: Mapped[str] = mapped_column(String(160), primary_key=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    blocked_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"

    key: Mapped[str] = mapped_column(String(160), primary_key=True)
    scope: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_id: Mapped[int] = mapped_column(Integer, nullable=False)
    response_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
