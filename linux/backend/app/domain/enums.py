from enum import Enum


class WorkflowState(str, Enum):
    INIT = "INIT"
    IDENTITY_REQUIRED = "IDENTITY_REQUIRED"
    IDENTITY_READY = "IDENTITY_READY"
    CASE_CREATED = "CASE_CREATED"
    QUESTIONING = "QUESTIONING"
    PAUSED = "PAUSED"
    SUMMARY = "SUMMARY"
    FROZEN = "FROZEN"
    SIGNED = "SIGNED"
    REPORT_GENERATED = "REPORT_GENERATED"
    VOIDED = "VOIDED"


class SessionStatus(str, Enum):
    READY = "READY"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"


class InterrogationStage(str, Enum):
    IDENTITY = "IDENTITY"
    STATEMENT = "STATEMENT"
    FOLLOW_UP = "FOLLOW_UP"
    SIGNING = "SIGNING"


class MessageMark(str, Enum):
    NONE = ""
    CONFLICT = "conflict"
    CONFIRMED = "confirmed"
    PENDING = "pending"
    HIGHLIGHT = "highlight"
