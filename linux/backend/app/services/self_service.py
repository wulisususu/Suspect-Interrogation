"""自助模式：当事人本人确认留痕。

自助模式下由当事人对照屏幕逐题口述回答，回答仍以「待摘入」草稿挂在题目上，最终由
在场民警核对后摘入正本。本服务只记录当事人本人的确认动作（身份信息无误、本题回答
无误、交回民警），全部写入审计日志，不新建表、不改正本。

状态从审计日志按时间顺序回放得出；本题确认带着确认时的回答原文，回答被重录或改动
后原文对不上，确认自动失效，需要本人重新确认。
"""
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import AuditLog, CaseQuestion, QuestionRound
from app.domain.errors import DomainError
from app.repositories import audit as audit_repo, cases as case_repo
from app.services.formal_record_policy import assert_formal_record_mutable
from app.services.serializers import iso_utc


EVENT_ACTIONS = {
    'IDENTITY_CONFIRM': 'SELF_SERVICE_IDENTITY_CONFIRM',
    'ANSWER_CONFIRM': 'SELF_SERVICE_ANSWER_CONFIRM',
    'ANSWER_UNCONFIRM': 'SELF_SERVICE_ANSWER_UNCONFIRM',
    'HANDOVER': 'SELF_SERVICE_HANDOVER',
}
QUESTION_EVENTS = {'ANSWER_CONFIRM', 'ANSWER_UNCONFIRM'}


class SelfServiceService:
    def __init__(self, db: Session):
        self.db = db

    def _question(self, case_id: str, question_id: str | None) -> CaseQuestion:
        row = self.db.get(CaseQuestion, question_id) if question_id else None
        if row is None or row.case_id != case_id or not row.active:
            raise DomainError('CASE_QUESTION_NOT_FOUND', '题目不存在', 404)
        return row

    def _answer_text(self, question: CaseQuestion) -> str:
        """与前端展示一致：正本回答优先，否则取最近一轮未脱离的待摘入回答。"""
        formal = (question.formal_answer_text or '').strip()
        if formal:
            return formal
        rounds = self.db.scalars(select(QuestionRound)
                                 .where(QuestionRound.case_question_id == question.id, QuestionRound.status != 'DETACHED')
                                 .order_by(QuestionRound.round_no.desc()))
        for round_row in rounds:
            if (round_row.answer_text or '').strip():
                return round_row.answer_text.strip()
        return ''

    def record(self, case_id: str, kind: str, question_id: str | None = None) -> dict:
        action = EVENT_ACTIONS.get(kind)
        if action is None:
            raise DomainError('INVALID_SELF_SERVICE_EVENT', '不支持的自助确认类型', 400)
        assert_formal_record_mutable(self.db, case_id)
        after: dict = {}
        target_type, target_id = 'CASE', case_id
        if kind in QUESTION_EVENTS:
            question = self._question(case_id, question_id)
            target_type, target_id = 'CASE_QUESTION', question.id
            after = {'questionId': question.id}
            if kind == 'ANSWER_CONFIRM':
                answer = self._answer_text(question)
                if not answer:
                    raise DomainError('SELF_SERVICE_NO_ANSWER', '本题还没有回答，不能确认', 400)
                after['answerText'] = answer
        audit_repo.add(self.db, case_id=case_id, action=action, target_type=target_type, target_id=target_id, after=after)
        return self.state(case_id)

    def state(self, case_id: str) -> dict:
        case_repo.get(self.db, case_id)
        rows = self.db.scalars(select(AuditLog)
                               .where(AuditLog.case_id == case_id, AuditLog.action.in_(EVENT_ACTIONS.values()))
                               .order_by(AuditLog.created_at, AuditLog.id))
        identity_at = handover_at = None
        confirmed: dict[str, tuple[str, str]] = {}
        for row in rows:
            if row.action == EVENT_ACTIONS['IDENTITY_CONFIRM']:
                identity_at = iso_utc(row.created_at)
            elif row.action == EVENT_ACTIONS['HANDOVER']:
                handover_at = iso_utc(row.created_at)
            elif row.action == EVENT_ACTIONS['ANSWER_CONFIRM']:
                confirmed[row.target_id] = (json.loads(row.after_json or '{}').get('answerText', ''), iso_utc(row.created_at))
            elif row.action == EVENT_ACTIONS['ANSWER_UNCONFIRM']:
                confirmed.pop(row.target_id, None)
        answers = []
        for question_id, (text, at) in confirmed.items():
            question = self.db.get(CaseQuestion, question_id)
            if question is not None and question.active and text and self._answer_text(question) == text:
                answers.append({'questionId': question_id, 'confirmedAt': at})
        return {'caseId': case_id, 'identityConfirmedAt': identity_at, 'handedOverAt': handover_at, 'confirmedAnswers': answers}
