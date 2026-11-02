"""同采集内重复转写残余的自动折叠（SUPERSEDED）。

说话人归属永久下线后，ASR 把同一句话切分成两段时，未被采用的那段不再有任何
去处：它确认不了（也不该写进正本），却会永远卡住定稿冻结，只能让民警每场
手工丢弃。这里在片段被正式消费（挂接答案 / 生成动态提问 / 确认入库）之后做
一次同采集清扫：剩余 PENDING/EDITED、未被任何操作认领的片段，若其文字与同
采集内已消费片段的文字构成重复识别，自动标 SUPERSEDED 并写审计。

保守边界：
- 只折叠**同采集**（同一次录音）里的相似文字；跨采集的文字哪怕相同也不动，
  避免误伤"确实又照着说了一遍"的独立段落。
- "逐字包含"（残余是已消费文字的子串）对任何锚点都成立——这是切分残余的
  强信号。
- "高相似但非包含"只对**嫌疑人答案锚点**（QUESTION_ANSWER）生效：答案是
  自由陈述，高相似基本只有重复识别一种解释。民警提问是模板句式（"第一个
  问题？"/"第二个问题？"彼此高度相似），绝不能按相似度折叠。
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

from app.database.models import ASRFragment, ProcessedSpeechFragment
from app.repositories import audit as audit_repo

# 比较前去掉空白与常见中英文标点，避免标点/空格差异干扰子串与相似度判断。
_NOISE = re.compile(r"[\s，。？！、,.?!;；:：\"'“”‘’…—\-·()（）\[\]【】]")

# 同采集内、去标点后与已消费答案相似度不低于该值的残余，视为同一句话的重复识别。
_SIMILARITY_RATIO = 0.8
def _normalize(text: str | None) -> str:
    return _NOISE.sub("", str(text or ""))


def _fragment_text(row: ASRFragment) -> str:
    return _normalize(row.edited_text or row.raw_text)


def supersede_duplicate_fragments(db: Session, case_id: str) -> list[str]:
    """折叠 case 内同采集的重复转写残余，返回被标 SUPERSEDED 的 fragment_id。"""
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

    candidates = list(db.scalars(
        select(ASRFragment).where(
            ASRFragment.case_id == case_id,
            ASRFragment.state.in_(("PENDING", "EDITED")),
            ASRFragment.confirmed_message_id.is_(None),
        )
    ))
    superseded_ids: list[str] = []
    for candidate in candidates:
        if candidate.id in untouchable_ids:
            continue
        candidate_text = _fragment_text(candidate)
        if not candidate_text:
            continue
        match = _best_match(candidate, candidate_text, consumed)
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
) -> tuple[ASRFragment, float] | None:
    """在同采集已消费片段里找与残余最相似的一条；找不到返回 None。"""
    best: tuple[ASRFragment, float] | None = None
    for anchor, anchor_text, similarity_allowed in consumed:
        if anchor.capture_session_id != candidate.capture_session_id:
            continue
        if candidate_text in anchor_text:
            # 残余是已消费文字的子串：必然是同句的重复识别，相似度取包含比例。
            similarity = len(candidate_text) / len(anchor_text)
        elif similarity_allowed:
            similarity = SequenceMatcher(None, candidate_text, anchor_text).ratio()
            if similarity < _SIMILARITY_RATIO:
                continue
        else:
            continue
        if best is None or similarity > best[1]:
            best = (anchor, similarity)
    return best
