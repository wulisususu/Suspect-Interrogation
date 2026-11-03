"""办案知识提示的问法归一与匹配。

民警的问法和当事人的回答很少与知识条目的标题、关键词逐字相同（「钱是什么时候转出去的」
对「转账时间」）。这里先把常见口语说法归到同一个概念词，再按概念与二字词重合打分。

这是确定性的词面扩展，不是语义向量召回：词表外的说法仍可能匹配不到，需要在条目关键词里补充，
或往 ``CONCEPTS`` 增加同义说法。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

# 概念词 → 口语说法。扫描时取最长匹配，所以「付款记录」归到凭证而不是转账，「多少钱」归到价值而不是资金。
CONCEPTS: dict[str, tuple[str, ...]] = {
    '时间': ('时间', '时段', '什么时候', '啥时候', '几点', '何时', '哪天', '哪一天', '几号', '日期'),
    '转账': ('转账', '转出去', '转出', '转走', '转过去', '转钱', '汇款', '汇出', '打款', '打钱', '付款', '支付'),
    '资金': ('资金', '钱款', '款项', '赃款', '钱'),
    '去向': ('去向', '流向', '去哪', '去了哪', '哪里去'),
    '地点': ('地点', '位置', '在哪', '哪里', '什么地方', '哪个地方', '地址'),
    '嫌疑人': ('嫌疑人', '对方', '骗子', '小偷', '那个人', '作案人'),
    '被盗': ('被盗', '被偷', '偷走', '偷了', '丢了', '丢失', '盗窃'),
    '电动车': ('电动车', '电瓶车', '电驴'),
    '上锁': ('上锁', '锁了', '锁车', '锁好', '车锁'),
    '价值': ('价值', '多少钱', '值多少钱', '值多少', '价格', '价钱', '损失'),
    '凭证': ('凭证', '发票', '收据', '购买记录', '付款记录', '转账记录'),
    '伤情': ('伤情', '受伤', '打伤', '伤到', '伤势'),
    '联系方式': ('联系方式', '电话', '手机号', '微信号', '微信', 'qq'),
    '聊天记录': ('聊天记录', '聊天截图', '聊天'),
    '监控': ('监控', '摄像头', '录像'),
    '经过': ('经过', '过程', '怎么回事', '发生了什么'),
    '体貌特征': ('体貌特征', '体貌', '长相', '长什么样', '穿着'),
    '派出所': ('派出所', '警务站'),
}

_SURFACES = sorted(
    ((surface.lower(), concept) for concept, surfaces in CONCEPTS.items() for surface in surfaces),
    key=lambda item: -len(item[0]),
)
_MAX_SURFACE = max(len(surface) for surface, _ in _SURFACES)
_SURFACE_MAP = dict(_SURFACES)
_DROP = re.compile(r'[^0-9a-z一-鿿]+')
# 二字词里出现这些虚词就不计入重合，免得「什么」「是否」之类把不相干的条目拉进来。
_STOP_CHARS = set('的了吗呢啊吧是否你我他她们这那有在和与及或就也都还请一下么什怎样个')


@dataclass(frozen=True)
class Normalized:
    text: str
    concepts: frozenset[str]
    grams: frozenset[str]


@lru_cache(maxsize=4096)
def normalize(raw: str | None) -> Normalized:
    """口语说法替换成概念词，去掉标点；返回归一文本、命中的概念和可比对的二字词。"""
    source = _DROP.sub(' ', (raw or '').lower())
    out: list[str] = []
    concepts: set[str] = set()
    index = 0
    while index < len(source):
        for size in range(min(_MAX_SURFACE, len(source) - index), 0, -1):
            concept = _SURFACE_MAP.get(source[index:index + size])
            if concept is not None:
                out.append(concept)
                concepts.add(concept)
                index += size
                break
        else:
            out.append(source[index])
            index += 1
    text = ''.join(out)
    grams = {
        text[i:i + 2] for i in range(len(text) - 1)
        if ' ' not in text[i:i + 2] and not (set(text[i:i + 2]) & _STOP_CHARS)
    }
    return Normalized(text=text, concepts=frozenset(concepts), grams=frozenset(grams))


def match_entry(context: Normalized, *, title: str, keywords: list[str], content: str) -> tuple[int, list[str]]:
    """按归一后的上下文给条目打分；没有任何命中返回 (0, [])。"""
    score = 0
    reasons: list[str] = []
    for keyword in keywords:
        normalized = normalize(keyword)
        if len(normalized.text.strip()) >= 2 and normalized.text in context.text:
            score += 4
            reasons.append(f'关键词命中：{keyword}')
    heading = normalize(title)
    shared_concepts = sorted(heading.concepts & context.concepts)
    shared_grams = heading.grams & context.grams
    if shared_concepts or len(shared_grams) >= 2:
        score += 3
        reasons.append('标题相关：' + '、'.join(shared_concepts or sorted(shared_grams)[:3]))
    body_concepts = sorted((normalize(content).concepts & context.concepts) - set(shared_concepts))
    if body_concepts and (reasons or len(body_concepts) >= 2):
        score += min(len(body_concepts), 3)
        reasons.append('正文涉及：' + '、'.join(body_concepts[:3]))
    return score, reasons


def similar_question(a: str, b: str) -> bool:
    """两个问法是否基本相同（用于不重复推荐案件里已经有的题）。"""
    left, right = normalize(a), normalize(b)
    if not left.grams or not right.grams:
        return left.text.strip() == right.text.strip()
    overlap = len(left.grams & right.grams) / len(left.grams | right.grams)
    return overlap >= 0.6
