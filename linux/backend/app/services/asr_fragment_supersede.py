"""重复转写残余的自动折叠（SUPERSEDED）。

说话人归属永久下线后，ASR 的重复识别残余不再有任何去处：它确认不了（也不该
写进正本），却会永远卡住定稿冻结，只能让民警每场手工丢弃。这里在片段被正式
消费（挂接答案 / 生成动态提问 / 确认入库）之后做一次清扫：剩余 PENDING/EDITED、
未被任何操作认领的片段，若其文字与已消费片段的文字构成重复识别，自动标
SUPERSEDED 并写审计。

实测的真实形态：每次录答是独立采集，重复来自"同一题的答案重录"——旧的
一遍没挂接，新的一遍挂进笔录，旧采集里的片段永久滞留。因此折叠规则按
"内容是否已被挂接答案覆盖"判定，不要求同采集：

- "逐字包含"（残余全文是已消费文字的子串）：内容已被完全覆盖，对任何锚点
  都折叠（同采集切分残余 / 跨采集重录都适用）。
- "高相似但非包含"（相似度 ≥ 0.8）：只对**嫌疑人答案锚点**（QUESTION_ANSWER）
  且**残余的采集早于锚点的采集**时折叠——这正是"重录了新的一遍、旧的一遍
  没用"的语义。答案是自由陈述，先录的旧相似稿基本只有重录残余一种解释；
  反过来（残余更新）则保留，可能是民警还想挂接的新识别。民警提问是模板句式
  （"第一个问题？"/"第二个问题？"彼此高度相似），绝不能按相似度折叠。
- 残余比已消费文字**多出内容**且相似度不足时保持原状（信息可能还没进正本，
  交给民警自己判断）。
- 已被任何 ProcessedSpeechFragment 认领（含 RAW_ONLY）的片段一律不动。
- SUPERSEDED 不进正本、可审计追溯（列表接口 include_superseded=true 可见）。
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import ASRCaptureSession, ASRFragment, ProcessedSpeechFragment
from app.repositories import audit as audit_repo

# 比较前去掉空白与常见中英文标点，避免标点/空格差异干扰子串与相似度判断。
_NOISE = re.compile(r"[\s，。？！、,.?!;；:：\"'“”‘’…—\-·()（）\[\]【】]")

# 去标点后与已消费答案相似度不低于该值的旧采集残余，视为同一句话的重录。
_SIMILARITY_RATIO = 0.8


def _normalize(text: str | None) -> str:
    return _NOISE.sub("", str(text or ""))


def _fragment_text(row: ASRFragment) -> str:
    return _normalize(row.edited_text or row.raw_text)


def supersede_duplicate_fragments(db: Session, case_id: str) -> list[str]:
    """折叠 case 内重复的转写残余，返回被标 SUPERSEDED 的 fragment_id。"""
    consumed_rows = list(db.scalars(
        select(ASRFragment).where(
            ASRFragment.case_id == case_id,
            ASRFragment.state == "CONFIRMED",
        )
    ))
    # 认领表一次读出，按 action 分区：
    # - answer_ids：挂到题目答案的自由陈述，可作高相似折叠的锚点；
    # - 其余认领（LIVE_QUESTION、RAW_ONLY、…）：只允许"逐字包含"折叠；
    # - 所有被认领的片段本身一律不折叠。
    claims = list(db.execute(
        select(ProcessedSpeechFragment.fragment_id, ProcessedSpeechFragment.action).where(
            ProcessedSpeechFragment.case_id == case_id,
        )
    ).all())
    untouchable_ids = {row[0] for row in claims}
    answer_ids = {row[0] for row in claims if row[1] == "QUESTION_ANSWER"}
    anchor_ids = {row[0] for row in claims if row[1] in ("QUESTION_ANSWER", "LIVE_QUESTION")}
    if anchor_ids:
        consumed_rows.extend(db.scalars(
            select(ASRFragment).where(ASRFragment.id.in_(anchor_ids))
        ))
    # consumed 条目：(锚点片段, 去标点文字, 是否允许按相似度折叠)。
    consumed: list[tuple[ASRFragment, str, bool]] = []
    for row in consumed_rows:
        text = _fragment_text(row)
        if text:
            consumed.append((row, text, row.id in answer_ids))
    if not consumed:
        return []

    # 采集开始时间表：相似度折叠要求"残余的采集早于锚点的采集"（重录语义）。
    capture_ids = {row.capture_session_id for row in consumed_rows}
    candidates = list(db.scalars(
        select(ASRFragment).where(
            ASRFragment.case_id == case_id,
            ASRFragment.state.in_(("PENDING", "EDITED")),
            ASRFragment.confirmed_message_id.is_(None),
        )
    ))
    capture_ids.update(row.capture_session_id for row in candidates)
    capture_started: dict[str, object] = {}
    if capture_ids:
        capture_started = {
            row.id: row.started_at
            for row in db.scalars(
                select(ASRCaptureSession).where(ASRCaptureSession.id.in_(capture_ids))
            )
        }

    superseded_ids: list[str] = []
    for candidate in candidates:
        if candidate.id in untouchable_ids:
            continue
        candidate_text = _fragment_text(candidate)
        if not candidate_text:
            continue
        match = _best_match(candidate, candidate_text, consumed, capture_started)
        if match is None:
            continue
        anchor, similarity = match
        before = {"state": candidate.state}
        candidate.state = "SUPERSEDED"
        audit_repo.add(
            db, case_id=case_id, action="ASR_FRAGMENT_SUPERSEDE_AUTO",
            target_type="ASR_FRAGMENT", target_id=candidate.id,
            before=before, after={"state": "SUPERSEDED"},
            detail={
                "anchor_fragment_id": anchor.id,
                "anchor_text": str(anchor.edited_text or anchor.raw_text or "")[:200],
                "candidate_text": str(candidate.edited_text or candidate.raw_text or "")[:200],
                "similarity": round(similarity, 4),
                "capture_session_id": candidate.capture_session_id,
            },
        )
        superseded_ids.append(candidate.id)
    if superseded_ids:
        db.flush()
    return superseded_ids


def _best_match(
    candidate: ASRFragment,
    candidate_text: str,
    consumed: list[tuple[ASRFragment, str, bool]],
    capture_started: dict[str, object],
) -> tuple[ASRFragment, float] | None:
    """在已消费片段里找与残余最匹配的一条；找不到返回 None。"""
    best: tuple[ASRFragment, float] | None = None
    candidate_started = capture_started.get(candidate.capture_session_id)
    for anchor, anchor_text, similarity_allowed in consumed:
        if candidate_text in anchor_text:
            # 残余全文已被挂接/确认的文字覆盖：必然是重复识别，相似度取包含比例。
            similarity = len(candidate_text) / len(anchor_text)
        else:
            # 高相似折叠：只对答案锚点，且残余的采集不得晚于锚点的采集——
            # 同采集 = 一次录音里的重复识别；跨采集更早 = 同题重录的旧稿。
            anchor_started = capture_started.get(anchor.capture_session_id)
            if not (similarity_allowed and candidate_started is not None
                    and anchor_started is not None and candidate_started <= anchor_started):
                continue
            similarity = SequenceMatcher(None, candidate_text, anchor_text).ratio()
            if similarity < _SIMILARITY_RATIO:
                continue
        if best is None or similarity > best[1]:
            best = (anchor, similarity)
    return best
