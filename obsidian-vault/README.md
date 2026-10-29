# 知识库 Vault 规范（v1）

本目录既是 Obsidian 可直接打开的 Vault，也是系统知识库的导入源。
**单向同步**：Obsidian → 系统。系统侧不写回 Markdown，避免双写冲突。

```text
obsidian-vault/
├── src.md                 # 入口索引（不导入）
├── raw/                   # 原始资料，不导入，仅作溯源目标
├── dict/faq/              # 问答知识，导入为 kind=faq
└── wiki/                  # 概念知识与双链，导入为 kind=wiki
```

`.obsidian/` 由 Obsidian 自己创建，导入器会跳过所有以 `.` 开头的目录。

## 一、Frontmatter 字段

```yaml
---
uid: faq-incident-time          # 必填，稳定 ID，小写字母/数字/连字符，3–64 位，全局唯一
title: 案发时间核对要点          # 必填，≤256 字；双链按标题解析，标题应唯一
category: 问话要点               # 必填，映射到知识分类名；不存在则自动创建
kind: faq                       # 必填，faq | wiki（raw 目录整体不导入）
status: verified                # 可选，verified | pending，默认 pending
version: 1                      # 可选，仅作提示；系统以数据库版本为准
keywords:                       # 可选，≤100 个，≤128 字/个
  - 案发时间
  - 时间
source: raw/接警记录规范.md      # 可选，溯源路径，可带 #小节 锚点
corrections:                    # 可选，仅 faq；导入为同音纠错/热词
  - wrong: 死老虎派出所
    right: 紫琅湖派出所
---
```

规则：

- `uid` 缺失或重复 → 该文件记为 `REJECTED`，不导入，报告里给出原因。
- `title` 缺失 → 用文件名（去扩展名）代替。
- `category` 缺失 → 落到「问话要点」，并在报告中提示。
- `status` 只接受 `verified` / `pending`；其它值按 `pending` 处理并提示。
- 正文（frontmatter 之后的部分）整段作为 `content`；`wiki` 的正文**同样入库可检索**。

## 二、导入行为

| 情况 | 行为 |
| --- | --- |
| 新文件 | 新增条目，`origin=VAULT`，写 v1 版本与 `KNOWLEDGE_IMPORT_CREATE` 审计 |
| 文件 sha256 未变 | 跳过，不产生版本 |
| 文件已变且条目 `origin=VAULT` | 更新正文/元数据，版本 +1，写 `KNOWLEDGE_IMPORT_UPDATE` |
| 文件已变但条目 `origin=MANUAL`（系统内手工建的） | **冲突**，不覆盖，报告 `SOURCE_CONFLICT` |
| 文件被删除/改名 | 条目 `active=false` 软停用（**不硬删**），写 `KNOWLEDGE_IMPORT_DISABLE` |
| 双链目标不存在 | 保留 `target_title` 待下次解析，不报错 |
| `corrections` 出现在非 faq 条目 | 忽略并提示 |

每次导入写一条 `knowledge_sync_runs` 记录（是否 dry-run、新增/更新/停用/冲突/拒绝数量、报告 JSON），并写 `KNOWLEDGE_IMPORT` 总审计。

## 三、双链

`[[笔记标题]]` 会被解析为条目间关联：

- 按 `title` 精确匹配（同库内标题应唯一，重复标题只连第一条并提示）；
- 支持 `[[标题|显示文字]]`，只取 `标题`；
- 解析结果写入 `knowledge_entry_links`，未匹配的保留 `to_entry_id=NULL`。

## 四、热词 / 同音纠错

`corrections` 导入 `asr_term_corrections` 表（`wrong_text` → `right_text`），并随条目启停：

- 条目停用 → 对应纠错项一并停用；
- 同一 `wrong_text` 在多处定义且 `right_text` 不同 → 报告 `CORRECTION_CONFLICT`，以先导入者为准，不覆盖；
- 可导出为 asr-stack 认的 `corrections.json` 与热词列表（部署时使用）。

纠错只作用于**识别文本**，不改变已定稿笔录；定稿后的修改仍走人工修订并留痕。

## 五、在 Obsidian 中使用

1. 安装 Obsidian → 「打开文件夹作为仓库」→ 选择本目录。
2. 不要启用会改写文件的外部同步插件（如双向网盘同步），避免与导入时的 sha256 判定打架。
3. 建议用「属性视图」维护 frontmatter，避免手写 YAML 缩进错误。
4. `raw/` 里的资料保持原样，不要为了导入去改写它。
