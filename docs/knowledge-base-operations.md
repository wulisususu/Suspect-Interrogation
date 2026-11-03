# 知识库操作说明（Obsidian → SQLite 单向同步）

本文覆盖：Obsidian 安装、Vault 初始化、知识导入、RK3588 部署与验收。
**当前交付只包含代码与本地测试，尚未部署**；等准备上线时按第 5 节顺序执行。

---

## 1. 架构

```text
Obsidian（编辑端，唯一权威）
   └── obsidian-vault/*.md
          │  单向导入（sha256 增量）
          ▼
RK3588  SQLite：knowledge_entries / _versions / _links / asr_term_corrections
          │
          ├── 题后知识提示（③ 题卡内自动出现；按题目/要素/刚才的回答匹配，带来源与版本）
          ├── 建议追问（只给候选，民警点选才在本题后建草稿题）
          ├── 定稿校验规则（按本案模板 / 案由加载到 ④ 定稿校验与定稿抽屉，逐项标明来源条目）
          └── 热词导出（corrections.json → asr-stack）
```

约定：

- **单向**：系统不写回 Markdown，避免双写冲突。
- **raw 不导入**：`raw/` 只作为 `source` 溯源目标。
- **wiki 正文入库**：双链解析成条目关联，正文同样可检索。
- **不改变证据链**：知识只用于提示与草稿，不直接改笔录、不生成事实。

## 2. 安装 Obsidian

1. 从 <https://obsidian.md> 下载桌面版（Windows / macOS / Linux），按默认选项安装。
2. 首次启动选择 **Open folder as vault**（打开文件夹作为仓库），指向 Vault 目录，**不要**选“新建仓库”，否则会覆盖已有结构。
3. 不要安装会改写文件的双向同步/网盘插件；`raw/` 内文件保持原样。

> 板子是 headless kiosk，不安装 Obsidian。编辑在民警电脑完成，改完通过内网同步到板子。

## 3. 初始化 Vault

仓库自带一份可直接使用的模板：`obsidian-vault/`。

```bash
# 本地（开发）：直接打开仓库里的 obsidian-vault
# 板端（生产）：
sudo install -d -o suspect-interrogation -g suspect-interrogation -m 0750 \
  /var/lib/suspect-interrogation/knowledge-vault
sudo rsync -a --delete /path/to/obsidian-vault/ /var/lib/suspect-interrogation/knowledge-vault/
sudo chown -R suspect-interrogation:suspect-interrogation /var/lib/suspect-interrogation/knowledge-vault
```

结构：

```text
obsidian-vault/
├── src.md            # 入口索引（不导入）
├── raw/              # 原始资料（不导入，只做溯源）
├── dict/faq/         # 问答知识 → kind=faq
├── rules/            # 定稿校验规则（frontmatter templates 绑定模板 / 案由）
└── wiki/             # 概念与双链 → kind=wiki
```

Frontmatter 字段（`uid` 必填且全局唯一）见 `obsidian-vault/README.md`，摘要：

```yaml
uid: faq-incident-time
title: 案发时间核对要点
category: 问话要点
kind: faq
status: verified          # verified | pending
keywords: [案发时间, 时间]
source: raw/接警记录规范.md
corrections:              # 仅 faq，导入为热词
  - wrong: 死老虎派出所
    right: 紫琅湖派出所
# 引用链（法规 / 规范条目建议填全）
source_document: 中华人民共和国治安管理处罚法
source_locator: 第四十九条第一款
source_version: 2012 修正
effective_from: 2013-01-01
effective_until: 2026-01-01   # 当日起失效
superseded_by: law-public-order-2025   # 新版条目的 uid；也可只写 superseded: true
```

## 4. 导入

### 4.1 板端 CLI（推荐）

```bash
cd /opt/suspect-interrogation/current
sudo -u suspect-interrogation env SUSPECT_DB_PATH=/var/lib/suspect-interrogation/interrogation.db \
  ./runtime/*/bin/python scripts/knowledge_sync.py \
  --vault /var/lib/suspect-interrogation/knowledge-vault
```

先跑默认的 **dry-run**，确认输出：

```text
[DRY-RUN] added=4 updated=0 unchanged=0 disabled=0 conflicts=0 rejected=0 corrections=0
```

确认无误后加 `--apply`：

```bash
... scripts/knowledge_sync.py --vault ... --apply --export-corrections /tmp/corrections.json
```

退出码：`0` 正常，`1` 存在冲突或拒绝项（需人工看输出），`2` Vault 目录不存在。

### 4.2 HTTP 接口（后台页面用的就是这两个）

```bash
# 预演
curl -s -X POST https://127.0.0.1:18080/api/v1/knowledge/import \
  -H 'Content-Type: application/json' \
  -d '{"dryRun": true}' --cacert /etc/suspect-interrogation/tls/ca.crt

# 写入
curl -s -X POST https://127.0.0.1:18080/api/v1/knowledge/import \
  -H 'Content-Type: application/json' -d '{"dryRun": false}' \
  --cacert /etc/suspect-interrogation/tls/ca.crt
```

`root` 省略时用 `SUSPECT_KNOWLEDGE_VAULT`（默认 `/var/lib/suspect-interrogation/knowledge-vault`）。

### 4.3 导入行为

| 情况 | 结果 |
| --- | --- |
| 新文件 | 新增，`origin=vault`，写 v1 版本 + `KNOWLEDGE_IMPORT_CREATE` 审计 |
| sha256 未变 | 跳过（不产生版本） |
| 内容变了 | 更新，版本 +1，写 `KNOWLEDGE_IMPORT_UPDATE` |
| 同名路径但是系统内手工建的 | **冲突**，不覆盖，报告 `SOURCE_CONFLICT` |
| 文件删除/改名 | `active=false` 软停用，纠错项一并停用（不硬删） |
| `uid` 缺失/非法/重复、正文为空 | 拒绝并给出原因，不影响其他文件 |
| 同一 `wrong` 两种 `right` | 保留先导入者，报告 `CORRECTION_CONFLICT` |

每次导入（含 dry-run 之外的正式导入）写一条 `knowledge_sync_runs`，含各计数与完整报告 JSON。

### 4.4 定稿校验规则（按模板 / 案由）

规则就是知识条目：`templates` 列出适用的模板 backendKey（如 `THEFT_EBIKE_V1`）或模板分类（`theft` / `injury` / `traffic` / `other`），
正文「校验项」小节每行一项（写法见 `obsidian-vault/README.md` 第五节）。绑定关系存在 `knowledge_check_bindings`（迁移 `0031`）。

- 加载：`GET /api/v1/knowledge/check-rules?caseId=…`（或 `?templateKey=…&caseType=…` 预览），只取已验证且启用的条目；
  模板专属规则排在案由通用规则前。
- 展示：④ 定稿校验「定稿前检查」与③定稿抽屉，排在固定检查之后，每项带「来源 · 知识库《条目》v版本 · 路径」；
  正本回答出现任一说法或关联要素已确认即通过，否则「待确认」。**只提示，不阻断定稿。**
- 仓库内置规则（`obsidian-vault/rules/`）：盗窃电动车、盗窃类通用、故意伤害、电信网络诈骗（`FRAUD_TELECOM_V1`，在模板管理中创建该模板后生效）。
  从未入库的 uid 在第一次打开校验时自动入库（origin=vault），之后的修改与停用走正常 Vault 导入；系统里删除过的规则不会被重新加入。
  板端 Vault 目录若是旧拷贝、缺少 `rules/`，正式导入会把这些规则软停用——同步 Vault 时带上 `rules/`。
- 手工条目可在 `PATCH /api/v1/knowledge/entries/{id}` 里用 `checkTemplates` 绑定；手工条目默认 `pending`，核实为 `verified` 后才进入校验。

## 5. RK3588 部署顺序

> 未部署前不要执行。以下为上线步骤。

1. **发布代码**：走现有生产重部署流水线（`rk3588-production-redeploy.yml`），它会构建前后端并原子切换。
2. **数据库迁移**（部署脚本已包含 `alembic upgrade head`，确认落在当前 head，见 `.github/workflows/rk3588-production-redeploy.yml`）：

   ```bash
   cd /opt/suspect-interrogation/current/linux/backend
   sudo -u suspect-interrogation .venv/bin/alembic -c alembic.ini upgrade head
   ```

   迁移会：加 7 个溯源/状态列、建 `knowledge_entry_links` / `knowledge_sync_runs` / `asr_term_corrections`、建 FTS5 索引与触发器，并把既有条目回填为 `status=verified`（避免它们突然从提示里消失）。

3. **准备 Vault 目录**（第 3 节），确认属主与权限 `0750`。
4. **确认环境变量** `/etc/suspect-interrogation/runtime.env`：

   ```text
   SUSPECT_KNOWLEDGE_VAULT=/var/lib/suspect-interrogation/knowledge-vault
   ```

5. **首次导入**：`--apply`（第 4.1 节）。
6. **重启业务服务**：`sudo systemctl restart interrogation-api.service`。
7. **验收**：

   ```bash
   # 条目已入库
   curl -s 'https://127.0.0.1:18080/api/v1/knowledge/entries' --cacert ... | head -c 400
   # 提示匹配可用（返回带 sourceRef / version）
   curl -s 'https://127.0.0.1:18080/api/v1/knowledge/guidance/match?q=派出所' --cacert ...
   # 前端：https://192.168.0.26:18080/?view=admin-placeholder&panel=knowledge
   #       应显示真实列表（不再是“功能待接入”）
   ```

   页面验收点：分类栏有四个内置分类；条目显示「Vault/手工」「已验证/待确认」「v版本」「溯源」；「从 Vault 导入」先出预演报告，确认后才写入。

   `0032_knowledge_citations` 再加 7 列引用链（依据文件、条款/页码、文件版本、生效/失效日期、是否被取代、取代它的条目）。
   用普通 `ADD COLUMN`，不重建表，FTS 触发器不受影响；既有条目全部为空，效力按「现行」处理。

## 6. 热词上线

1. 导出：

   ```bash
   ... scripts/knowledge_sync.py --vault ... --apply \
     --export-corrections /tmp/corrections.json
   ```

   同时生成 `/tmp/corrections.hotwords.txt`（供离线精修热词使用）。

2. 合并到 asr-stack（**不要整文件覆盖**，先比对现有规则）：

   ```bash
   diff /home/youyeetoo/asr-stack/config/corrections.json /tmp/corrections.json
   sudo -u youyeetoo cp /tmp/corrections.json /home/youyeetoo/asr-stack/config/corrections.json
   ```

3. 重启语音离线 worker（热词是加载期注入）：

   ```bash
   sudo systemctl restart asr-worker.service   # 若以独立 unit 运行
   curl -s http://127.0.0.1:8011/health | grep hotwords
   ```

4. 验收：识别文本里 `死老虎派出所` 被替换为 `紫琅湖派出所`；**已定稿笔录不受影响**，定稿后的修改仍走人工修订并留痕。

## 7. 故障处理

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| 导入报 `KNOWLEDGE_VAULT_NOT_FOUND` | 目录不存在或 `SUSPECT_KNOWLEDGE_VAULT` 未配 | 按第 3 节建目录；核对 env |
| 条目在后台可见但办案页无提示 | 条目 `status=pending`、已停用，或已失效 / 尚未生效 / 已被取代（后台列表有标记） | 核实后改 `verified` 并重新导入 |
| 问法和条目说法不同，提示没出来 | 匹配是词面归一，不是语义向量；该说法不在概念词表里 | 在条目关键词里补上常见说法，或在 `app/services/knowledge_matching.py` 的 `CONCEPTS` 增加同义说法 |
| 搜索 2 字词命中少 | FTS5 trigram 只支持 ≥3 字，短词走 LIKE | 属预期；用更长关键词 |
| 导入后内容没变 | 文件 sha256 未变（可能没保存） | 确认 Obsidian 已落盘 |
| 导入报冲突 | 同路径条目是系统内手工建的 | 在后台改标题/删除手工条目，或换文件路径 |
| FTS 建表失败 | SQLite 未编译 FTS5/不支持 trigram | 自动退回 LIKE，功能可用但大库变慢；日志有 warning |

## 8. 办案页怎么用知识（③ 问答录入）

设计稿 P24：「问话时由系统自动调用并附在题后」。知识提示不再单独占一栏，也不用点按钮：

- **挂在哪张卡上**：正在录音的题；否则民警点选的题；否则第一道还没答的题。定稿冻结后不显示。
- **用什么匹配**：这道题的文字、题目别名、所属要素，加上这道题刚才的回答（录音中取实时转写，录完取草稿 / 正本，只取最后 300 字）。回答在变时停顿约 1.2 秒再查。
- **怎么匹配**：先把口语说法归到概念词（「什么时候 / 几点 / 哪天」→ 时间，「转出去 / 汇款 / 打钱」→ 转账，「锁了 / 车锁」→ 上锁 …），再按关键词、标题、正文概念重合打分。只返回 `verified` 条目。
- **智能追问助手**（见第 9 节）：在同一张卡里推荐下一问，民警点「采纳」或「不适用」。
- 条目可展开看首句正文、版本、出处（《依据文件》条款（版本），没填时退回原件路径 `sourceRef`）与命中原因。
- **效力**：失效日期当日起、生效日期之前、或标记为「已被取代」的条目不进提示和建议追问；后台列表照常显示，并标「已失效 / 尚未生效 / 已被取代」。

## 9. 智能追问与采纳反馈（经验积累闭环 · 第一阶段）

方向：办理案件 → 积累经验 → 审核经验 → 改进辅助 → 服务下一案。本阶段只做前两步，并为第三步留好数据。

**民警看到什么**（③ 题卡内「智能追问助手」）：案件类型、当前**尚未确认**的要素（「锁具情况 · 尚未确认 · 需要核实」）与核实建议，下面是 1–3 条推荐追问，每条带来源条目与版本，按钮「采纳 / 不适用」。注明「所有问题由民警选择，采纳只生成草稿题，不会自动写入正式笔录」。

**推荐从哪来**：

1. 本案模板要素里状态不是「已确认」的要素（要素在某道正文题写进正本后即确认），当前题的要素排第一，其余按模板顺序。
2. 问法取自**绑定到本案模板 / 案由**、`verified`、启用且在效力期内的条目「建议问法」小节里带要素标记的行：

   ```markdown
   ## 建议问法

   - [lock] 停车时车上用了什么锁？
   - [last_seen] 你最后一次确认车还在原处，大概是什么时间？
   - 你是怎么记住这个时间的？      ← 不带标记：按当前题和回答匹配到时才推荐
   ```

3. 当前题与刚才的回答匹配到的通用条目里不带标记的问法，作为补充。
4. 本案已有的同义题、本案已采纳或标过不适用的问法不再推荐。
5. 同一要素下按历史「采纳 /（采纳 + 不适用）」平滑后的比例微调先后；只展示过不计分，没有反馈时保持条目里的原顺序。**采纳率只用于排序，不会自动改规则、不会把问题发布进知识库。**

**内置问法**：`obsidian-vault/rules/ask-*.md`（盗窃电动车、盗窃车内财物、故意伤害、嫌疑人询问）随代码发布，与定稿校验规则一样首次使用时自动入库。内容是示例，**请本单位审核**：不合适的问法直接在 Obsidian 修改后导入（生成新版本），或在后台改为「待确认」/ 停用。

**反馈怎么记**（表 `knowledge_suggestion_feedback`，迁移 `0033`）：每个案件每条问法一行，记录条目 ID 与版本、要素、问法文字、展示时间与人、处置（`ADOPTED` / `NOT_APPLICABLE`）、处置时间与人、采纳后生成的题目 ID。**不存当事人的回答**。重复展示、重复点击不新增行；已采纳的不能再改成不适用（请删除那道草稿题）。采纳与标不适用各写一条审计（`KNOWLEDGE_SUGGESTION_ADOPT` / `KNOWLEDGE_SUGGESTION_DISMISS`）。

- `POST /api/v1/knowledge/suggestions` `{caseId, questionId?, q?, limit?}`：返回 `focus`、`pendingElements`、`suggestions`（含 `key`、来源、汇总使用次数），并记录展示。
- `POST /api/v1/knowledge/suggestions/feedback` `{caseId, key, action}`：`ADOPTED` 在同一事务里建 LIVE 草稿题（插在该要素最后一道正文题之后），`NOT_APPLICABLE` 只记反馈。`key` 必须是本案展示过的，否则 404，避免跨案件串用。
- `GET /api/v1/knowledge/usage`、`GET /api/v1/knowledge/entries/{id}/usage`：后台「使用效果」列与详情里逐条问法的「推荐 / 采纳 / 不适用」案件数。

**下一阶段**（本阶段不做）：从已结案案件提炼可复用、已脱敏的问话经验，经民警审核后发布为新版条目。本阶段不训练或微调模型、不读取其他案件的问答内容、不上向量库 / 知识图谱、不自动发布、不改正式笔录。

## 10. 已知边界（本阶段）

- 不做双向同步，不做 Obsidian 插件/MCP。
- 不做向量检索与 Embedding：办案提示是关键词 + 概念词表归一，词表外的说法要靠条目关键词补齐。
- 匹配上下文只含当前题及其回答，尚未纳入已确认事实、未解决冲突与前几轮问答。
- 引用链由人工填写；导入只核对 `source` 指向的原件在 Vault 里存在，不校验条款文字是否与原件一致。
- 效力判断按板端本地日期；`superseded_by` 关系每次导入重算，不单独产生版本。
- 建议问法是**规则抽取**（条目里的「建议问法」小节），不调用 LLM。
- 知识不参与正式笔录生成，所有引用都带 `entryId + version + sourceRef`，仅供民警判断。
