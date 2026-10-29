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
          ├── 办案页知识提示（按题目/要素匹配，带来源与版本）
          ├── 建议问法（只给候选，民警采纳才建草稿题）
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

## 5. RK3588 部署顺序

> 未部署前不要执行。以下为上线步骤。

1. **发布代码**：走现有生产重部署流水线（`rk3588-production-redeploy.yml`），它会构建前后端并原子切换。
2. **数据库迁移**（部署脚本已包含 `alembic upgrade head`，确认落在 `0028`）：

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
| 条目在后台可见但办案页无提示 | 条目 `status=pending` 或已停用 | 核实后改 `verified` 并重新导入 |
| 搜索 2 字词命中少 | FTS5 trigram 只支持 ≥3 字，短词走 LIKE | 属预期；用更长关键词 |
| 导入后内容没变 | 文件 sha256 未变（可能没保存） | 确认 Obsidian 已落盘 |
| 导入报冲突 | 同路径条目是系统内手工建的 | 在后台改标题/删除手工条目，或换文件路径 |
| FTS 建表失败 | SQLite 未编译 FTS5/不支持 trigram | 自动退回 LIKE，功能可用但大库变慢；日志有 warning |

## 8. 已知边界（本阶段）

- 不做双向同步，不做 Obsidian 插件/MCP。
- 不做向量检索与 Embedding（先关键词 + FTS5）。
- 建议问法是**规则抽取**（条目里的「建议问法」小节），不调用 LLM。
- 知识不参与正式笔录生成，所有引用都带 `entryId + version + sourceRef`，仅供民警判断。
