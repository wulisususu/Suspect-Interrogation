"""同采集重复转写残余自动折叠（SUPERSEDED）的行为守护。

背景：声纹/说话人归属永久下线后，ASR 把同一句话切成两段时，未被采用的残余
既不能确认（恒 UNKNOWN）、内容又已被答案覆盖，只会永远卡住定稿冻结。消费
入口（挂接答案 / 动态提问 / 确认入库）现在会就地把同采集的重复残余折叠成
SUPERSEDED。这里守护折叠的触发条件与保守边界。
"""

import json

from sqlalchemy import select

from app.database.models import AuditLog
from app.repositories import asr_fragments as asr_repo
from app.services.template_workspace_service import TemplateWorkspaceService
from test_question_recording_ownership import db, fragment, question


def _supersede_actions(db, fragment_id):
    return list(db.scalars(select(AuditLog).where(
        AuditLog.case_id == 'CASE-OWN',
        AuditLog.action == 'ASR_FRAGMENT_SUPERSEDE_AUTO',
        AuditLog.target_id == fragment_id,
    )))


def test_attach_answer_folds_prefix_residual_in_same_capture(db):
    service = TemplateWorkspaceService(db)
    q = question(db)
    capture = asr_repo.create_capture_session(db, case_id='CASE-OWN', interrogation_session_id=None, sample_rate=16000)
    kept = fragment(db, capture, 0, '认识字体')
    residual = fragment(db, capture, 1, '认识字')
    service.attach_case_question_answer_fragments('CASE-OWN', q['id'], fragment_ids=[kept.id], draft=True)
    db.refresh(residual)
    assert residual.state == 'SUPERSEDED'
    assert asr_repo.get_processed(db, residual.id) is None
    audits = _supersede_actions(db, residual.id)
    assert len(audits) == 1
    assert json.loads(audits[0].detail_json)['anchor_fragment_id'] == kept.id
    # 子串情形的相似度 = 长度包含比例（3/4）。
    assert json.loads(audits[0].detail_json)['similarity'] == 0.75


def test_attach_answer_folds_similar_retranscription_in_same_capture(db):
    """同一句的另一种识别（非子串、高相似）也要折叠。"""
    service = TemplateWorkspaceService(db)
    q = question(db)
    capture = asr_repo.create_capture_session(db, case_id='CASE-OWN', interrogation_session_id=None, sample_rate=16000)
    kept = fragment(db, capture, 0, '听清楚了没有要求')
    residual = fragment(db, capture, 1, '我看清楚了没有要求')
    service.attach_case_question_answer_fragments('CASE-OWN', q['id'], fragment_ids=[kept.id], draft=True)
    db.refresh(residual)
    assert residual.state == 'SUPERSEDED'


def test_similar_text_in_other_capture_is_preserved(db):
    """跨采集的相似文字不折叠：可能是确实又照着说了一遍。"""
    service = TemplateWorkspaceService(db)
    q = question(db)
    first = asr_repo.create_capture_session(db, case_id='CASE-OWN', interrogation_session_id=None, sample_rate=16000)
    second = asr_repo.create_capture_session(db, case_id='CASE-OWN', interrogation_session_id=None, sample_rate=16000)
    kept = fragment(db, first, 0, '听清楚了没有要求')
    repeated = fragment(db, second, 0, '我看清楚了没有要求')
    service.attach_case_question_answer_fragments('CASE-OWN', q['id'], fragment_ids=[kept.id], draft=True)
    db.refresh(repeated)
    assert repeated.state == 'PENDING'
    assert _supersede_actions(db, repeated.id) == []


def test_residual_with_extra_content_is_preserved(db):
    """残余比已消费文字多出内容且相似度不足时不折叠，信息交给民警判断。"""
    service = TemplateWorkspaceService(db)
    q = question(db)
    capture = asr_repo.create_capture_session(db, case_id='CASE-OWN', interrogation_session_id=None, sample_rate=16000)
    kept = fragment(db, capture, 0, '认识字')
    richer = fragment(db, capture, 1, '认识字体呀并且写了名字')
    service.attach_case_question_answer_fragments('CASE-OWN', q['id'], fragment_ids=[kept.id], draft=True)
    db.refresh(richer)
    assert richer.state == 'PENDING'
    assert _supersede_actions(db, richer.id) == []


def test_distinct_text_in_same_capture_is_preserved(db):
    service = TemplateWorkspaceService(db)
    q = question(db)
    capture = asr_repo.create_capture_session(db, case_id='CASE-OWN', interrogation_session_id=None, sample_rate=16000)
    kept = fragment(db, capture, 0, '因为我盗窃了')
    other = fragment(db, capture, 1, '我去年去过他家里')
    service.attach_case_question_answer_fragments('CASE-OWN', q['id'], fragment_ids=[kept.id], draft=True)
    db.refresh(other)
    assert other.state == 'PENDING'


def test_claimed_fragment_is_never_folded(db):
    """已被任何操作认领（含 RAW_ONLY）的片段不折叠。"""
    service = TemplateWorkspaceService(db)
    q = question(db)
    capture = asr_repo.create_capture_session(db, case_id='CASE-OWN', interrogation_session_id=None, sample_rate=16000)
    kept = fragment(db, capture, 0, '认识字体')
    raw_only = fragment(db, capture, 1, '认识字')
    asr_repo.mark_processed(db, fragment_id=raw_only.id, case_id='CASE-OWN', action='RAW_ONLY')
    service.attach_case_question_answer_fragments('CASE-OWN', q['id'], fragment_ids=[kept.id], draft=True)
    db.refresh(raw_only)
    assert raw_only.state == 'PENDING'
    assert _supersede_actions(db, raw_only.id) == []


def test_similar_officer_questions_in_same_capture_are_preserved(db):
    """民警提问是模板句式：同采集里两个高度相似的提问片段绝不能按相似度互折。

    场景来自回归：一次录音里民警连问"第一个问题？""第二个问题？"（去标点后
    相似度 0.83），生成动态提问后第二个问题片段必须保持 PENDING。
    """
    service = TemplateWorkspaceService(db)
    capture = asr_repo.create_capture_session(db, case_id='CASE-OWN', interrogation_session_id=None, sample_rate=16000)
    first = fragment(db, capture, 0, '第一个问题？')
    second = fragment(db, capture, 1, '第二个问题？')
    first.speaker = second.speaker = 'INTERROGATOR'
    db.flush()
    service.create_live_question_from_fragments('CASE-OWN', fragment_ids=[first.id])
    db.refresh(second)
    assert second.state == 'PENDING'


def test_live_question_creation_folds_prefix_residual(db):
    service = TemplateWorkspaceService(db)
    capture = asr_repo.create_capture_session(db, case_id='CASE-OWN', interrogation_session_id=None, sample_rate=16000)
    officer = fragment(db, capture, 0, '你因何事来公安机关？')
    residual = fragment(db, capture, 1, '因何事来公安机关')
    officer.speaker = 'INTERROGATOR'
    db.flush()
    service.create_live_question_from_fragments('CASE-OWN', fragment_ids=[officer.id])
    db.refresh(residual)
    assert residual.state == 'SUPERSEDED'


def test_legacy_confirm_path_folds_prefix_residual(db):
    """legacy 确认入库（写入 Message）后同样折叠同采集残余。

    注意：legacy 确认仍要求说话人已指定（_official_message_speaker 会拒绝
    UNKNOWN），这是"民警改说话人再确认"流程的后端依据，本测试先把锚点设为
    SUSPECT；残余片段不需要说话人即可被折叠。确认还会写入 Message，需要
    一个 RUNNING 的询问会话。
    """
    from app.api.asr import FragmentBatchRequest, apply_fragments
    from app.database.models import InterrogationSession

    db.add(InterrogationSession(id='session-supersede', case_id='CASE-OWN', status='RUNNING', stage='STATEMENT'))
    db.commit()
    capture = asr_repo.create_capture_session(db, case_id='CASE-OWN', interrogation_session_id='session-supersede', sample_rate=16000)
    kept = fragment(db, capture, 0, '认识字体')
    residual = fragment(db, capture, 1, '认识字')
    kept.speaker = 'SUSPECT'
    db.flush()
    result = apply_fragments('CASE-OWN', FragmentBatchRequest(fragment_ids=[kept.id]), db=db)
    assert result['confirmedCount'] == 1
    db.refresh(residual)
    assert residual.state == 'SUPERSEDED'
