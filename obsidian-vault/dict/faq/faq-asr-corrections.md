---
uid: faq-asr-corrections
title: 常见同音误识与纠错词
category: 语音纠错
kind: faq
status: verified
version: 1
keywords:
  - 纠错
  - 同音
  - 盗窃
  - 报警
  - 派出所
corrections:
  - wrong: 实时倒贴
    right: 实施盗窃
  - wrong: 实时盗窃
    right: 实施盗窃
  - wrong: 倒贴
    right: 盗窃
  - wrong: 抱警
    right: 报警
  - wrong: 抱案
    right: 报案
  - wrong: 派处所
    right: 派出所
  - wrong: 身份正
    right: 身份证
  - wrong: 交通是故
    right: 交通事故
  - wrong: 较通是故
    right: 交通事故
source: raw/接警记录规范.md
---
# 常见同音误识与纠错词

语音识别对办案高频词存在同音误识。以下纠错规则均为现场实测确认（2026-11-02 整理收编），
按"确定性短语替换"原则生效，识别结果落库前自动替换：

## 盗窃案问法（AAC708 实测）

- 实时倒贴 → 实施盗窃
- 实时盗窃 → 实施盗窃（"实施"误识为"实时"）
- 倒贴 → 盗窃

## 接警与身份类

- 抱警 → 报警
- 抱案 → 报案
- 派处所 → 派出所
- 身份正 → 身份证

## 事故类

- 交通是故 → 交通事故
- 较通是故 → 交通事故

注意事项：

- 替换只作用于识别文本，不改动数字/号码附近的内容（避免误改时间、金额）；
- 新增纠错词须先现场实测确认再入本清单；若某条在正常语境被误改，优先停用该条并复盘。
