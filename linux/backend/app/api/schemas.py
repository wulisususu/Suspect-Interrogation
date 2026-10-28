from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class FormalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class LegacyRequest(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class CaseCreateRequest(FormalRequest):
    fullRecordingEnabled: bool | None = None
    interrogatorBadgeNumber: str | None = Field(default=None, min_length=1, max_length=32)
    recorderBadgeNumber: str | None = Field(default=None, min_length=1, max_length=32)
    operator_id: str | None = None
    operatorId: str | None = None
    case_type: str = "suspect_interrogation"
    caseType: str | None = None
    suspectName: str | None = None
    gender: str | None = None
    age: str | int | None = None
    officerName: str | None = None


class CaseIntakeIdentity(FormalRequest):
    name: str = Field(min_length=1)
    gender: str | None = None
    nation: str | None = None
    birthDate: str | None = None
    idNumber: str = ""
    address: str | None = None
    source: str = "MANUAL"


class CaseIntakeRequest(CaseCreateRequest):
    identity: CaseIntakeIdentity


class CaseUpdateRequest(FormalRequest):
    fullRecordingEnabled: bool | None = None
    interrogatorBadgeNumber: str | None = Field(default=None, min_length=1, max_length=32)
    recorderBadgeNumber: str | None = Field(default=None, min_length=1, max_length=32)
    operator_id: str | None = None
    operatorId: str | None = None
    case_type: str | None = None
    caseType: str | None = None
    suspectName: str | None = None
    gender: str | None = None
    age: str | int | None = None
    officerName: str | None = None
    idNumber: str | None = None
    nation: str | None = None
    birthDate: str | None = None
    address: str | None = None
    stage: str | None = None
    actor_id: str | None = None


class ActorRequest(FormalRequest):
    actor_id: str | None = None


class SessionStartRequest(ActorRequest):
    interrogator_officer_id: str | None = None
    recorder_officer_id: str | None = None


class IdentityReadRequest(ActorRequest):
    case_id: str | None = None


class IdentityConfirmRequest(ActorRequest):
    case_id: str
    name: str
    id_number: str = ""
    gender: str | None = None
    nation: str | None = None
    birth_date: str | None = None
    address: str | None = None
    source: str = "MANUAL"
    portrait: str | None = None
    issuer: str | None = None
    valid_from: str | None = None
    valid_to: str | None = None


class MessageCreateRequest(ActorRequest):
    text: str
    speaker: str


class MessageUpdateRequest(ActorRequest):
    text: str
    reason: str = "警官修订"


class MessageMarkRequest(ActorRequest):
    mark: str


class StageRequest(ActorRequest):
    stage: str


class FactUpdateRequest(ActorRequest):
    value: str | None = None
    status: str | None = None
    suggestion: str | None = None


class DeviceActionRequest(FormalRequest):
    type: str


class SignatureRequest(ActorRequest):
    signer_role: str
    signer_name: str
    image_data: str
    strokes_json: str = "[]"


class DocumentSignRequest(FormalRequest):
    signer_role: Literal["SUSPECT", "OFFICER"] = Field(alias="signerRole")
    signer_name: str = Field(min_length=1, alias="signerName")
    image_data: str = Field(min_length=1, alias="imageDataUrl")
    strokes_json: str = Field(default="[]", alias="strokesJson")
    actor_id: str | None = Field(default=None, alias="actorId")


class LegacySignatureRequest(LegacyRequest):
    session_id: str | None = None
    data: str


class LegacyWorkMessageProfile(LegacyRequest):
    text: str
    from_: str = Field(alias="from")


class LegacyWorkMessageRequest(LegacyRequest):
    profile: LegacyWorkMessageProfile | None = None
    text: str | None = None
    from_: str | None = Field(default=None, alias="from")


class CaseQuestionCreateRequest(FormalRequest):
    text: str
    source: Literal["STANDARD", "CASE", "LIVE"] = "CASE"
    standard_question_id: str | None = Field(default=None, alias="standardQuestionId")
    regex_patterns: list[str] = Field(default_factory=list, alias="regexPatterns")
    after_question_id: str | None = Field(default=None, alias="afterQuestionId")
    element_key: str | None = Field(default=None, alias="elementKey", max_length=64)


class CaseQuestionUpdateRequest(FormalRequest):
    text: str | None = None
    regex_patterns: list[str] | None = Field(default=None, alias="regexPatterns")
    element_key: str | None = Field(default=None, alias="elementKey", max_length=64)


class QuestionReorderRequest(FormalRequest):
    question_ids: list[str] = Field(alias="questionIds")


class PendingAddRequest(FormalRequest):
    after_question_id: str | None = Field(default=None, alias="afterQuestionId")


class PendingLinkRequest(FormalRequest):
    case_question_id: str = Field(alias="caseQuestionId")
    round_mode: Literal["APPEND_EXISTING", "NEW_ROUND"] = Field(alias="roundMode")


class RoundReassociateRequest(FormalRequest):
    case_question_id: str | None = Field(default=None, alias="caseQuestionId")
    new_question_text: str | None = Field(default=None, alias="newQuestionText")


class RoundUpdateRequest(FormalRequest):
    answer_text: str = Field(alias="answerText")


class FragmentAnswerRequest(FormalRequest):
    fragment_ids: list[str] = Field(alias="fragmentIds", min_length=1)
    # draft: 只挂成该题的待摘入草稿，不写入正本；replace: 重录时替换原草稿而不是追加。
    draft: bool = False
    replace: bool = False


class LiveQuestionFragmentRequest(FormalRequest):
    fragment_id: str = Field(alias="fragmentId", min_length=1)
    after_question_id: str | None = Field(default=None, alias="afterQuestionId")


class LiveQuestionFragmentsRequest(FormalRequest):
    fragment_ids: list[str] = Field(alias="fragmentIds", min_length=1, max_length=256)
    after_question_id: str | None = Field(default=None, alias="afterQuestionId")


class SaveQuestionToLibraryRequest(FormalRequest):
    category: str = "通用"


class QAUnitResolutionRequest(FormalRequest):
    action: Literal["CREATE_LIVE", "LINK_QA", "LINK_ANSWER", "IGNORE"]
    case_question_id: str | None = Field(default=None, alias="caseQuestionId")
    formal_question: str | None = Field(default=None, alias="formalQuestion")
    formal_answer: str | None = Field(default=None, alias="formalAnswer")


class LegacyCaseCreateRequest(CaseCreateRequest):
    model_config = LegacyRequest.model_config


class LegacyCaseUpdateRequest(CaseUpdateRequest):
    model_config = LegacyRequest.model_config


class LegacyActorRequest(ActorRequest):
    model_config = LegacyRequest.model_config


class LegacyMessageUpdateRequest(MessageUpdateRequest):
    model_config = LegacyRequest.model_config


class LegacyMessageMarkRequest(MessageMarkRequest):
    model_config = LegacyRequest.model_config


class LegacyStageRequest(StageRequest):
    model_config = LegacyRequest.model_config


class LegacyFactUpdateRequest(FactUpdateRequest):
    model_config = LegacyRequest.model_config


class LegacyDeviceActionRequest(DeviceActionRequest):
    model_config = LegacyRequest.model_config
