# 设计走查 B 组后端对接与验收

本地实现基于 `linux-adaptation` 的 `7cd583b0`。尚未推送或部署，不代表线上页面已经变化。
接口统一以 `/api/v1` 为前缀，新增接口使用 `{ok, code, message, data}` 信封和 camelCase 字段。
既有 ASR 采集和片段接口保留原有直接返回结构，避免破坏当前前端；文件接口成功时返回文件流。

## 问答闭环

- `POST /cases/{caseId}/questions` 和 `PATCH /cases/{caseId}/questions/{questionId}` 接收可空 `elementKey`。
  固定开头/结尾不允许设置要素；正文取案件模板快照的要素 key。PATCH 不传表示保留，显式 null 表示解除关联。
- `GET /cases/{caseId}/template-workspace` 返回 `questions[].elementKey` 和所选模板的 `templateSelection` 快照。
- `PUT /cases/{caseId}/questions/{questionId}/answer` 的 `answerText` 摘入后确认对应要素，清空时按同要素其他有效题的正本回答重新计算。
  草稿不自动确认要素。
- `POST /cases/{caseId}/asr/capture/start` 接收 `{"targetQuestionId":"题目ID","replace":true}`。
  参数在录音开始前落库；最终片段在同事务进入题目草稿。`GET /cases/{caseId}/asr/capture` 返回目标题与替换参数，刷新恢复不靠前端临时变量。
  重录只在第一段有效文字替换旧草稿，后续片段追加；未产生文字不提前清空正本或旧草稿。
- `POST /cases/{caseId}/questions/from-fragments` 接收 `fragmentIds` 数组和可选 `afterQuestionId`。
  先校验全部片段和插入位置，再原子创建题目、标记处理；按采集时间与片段时间排序。相同完整集合重试返回原题，交叠/跨案集合拒绝。
- 已使用片段不再被旧的确认、丢弃、apply-all 重复消费；旧单片段与新多片段接口共享归属记录，并检查历史问答证据。
  保留原始片段与识别证据，不以删除证据完成消费。

## 建档与身份

案件创建/更新支持 `interrogatorBadgeNumber`、`recorderBadgeNumber`、`fullRecordingEnabled`，详情/列表返回民警结构与录音设置。
询问人与记录员必须为启用名录中的不同民警；认证后的 `operatorId` 和审计操作人采用真实会话身份，客户端不可伪造。
已建案件可沿用 `POST /identity/read` 的 `case_id`，冻结或作废后拒绝更新身份。

认证接口和无默认密码的管理员配置步骤见 [身份接口文档](backend-officer-api.md)。
首位启用管理员配置后自动开启旧新 API 的认证；生产也可设 `SUSPECT_AUTH_REQUIRED=true` 提前强制认证。
锁屏、退出、过期或停用会拦截已有 WebSocket 的后续收发。首次部署需与前端登录接入一起验收。

## 办理、审计与校验

| 接口 | 请求/行为 |
| --- | --- |
| `POST /cases/{caseId}/interruption` | `reason`、可选 `questionId`/`detail`；reason 为 `POWER_RECOVERY`、`PARTY_LEFT`、`NETWORK_INTERRUPTED`、`FINALIZATION_INTERRUPTED` |
| `GET /cases/{caseId}/management` | 中断原因、时间、`stoppedQuestionId/Number/Text`、作废原因/时间/操作人；案件列表也返回这些字段 |
| `POST /cases/{caseId}/void` | 必填 `reason`；只允许未完成/待定稿，保留案件和审计，不提供删除接口 |
| `GET /audit-logs` | `keyword/createdFrom/createdTo/action/actorId/result/category/caseId/page/pageSize`；结果含真实姓名警号、对象摘要、SUCCESS/FAILURE/UNKNOWN |
| `POST /cases/{caseId}/timeline-evidence` | `kind`、ISO `at`、明确 `source`，提供核验时间线的证据 |
| `GET /cases/{caseId}/validation` | 按证据返回时间先后冲突/待核实和纠错处理状态，缺证据不视为自动通过 |
| `POST /cases/{caseId}/corrections/scan` | 为当前正本回答产生版本绑定的词语候选 |
| `POST /cases/{caseId}/corrections/{id}/resolve` | `{"action":"ACCEPT"}` 或 `{"action":"IGNORE"}`；回答版本变化后拒绝采纳旧候选 |

同音词候选由 `SUSPECT_HOMOPHONE_CANDIDATES_JSON` 配置，例如 `{"雅笛":["雅迪"]}`；未配置明确返回 `configured:false`。
新失败业务请求记录 FAILURE 审计，不保存密码或请求体。历史无明确结果的日志为 UNKNOWN；历史声纹日志可筛为 SYSTEM。

## 资料与文书

模板、知识库、题目录音和全程原始录音见 [对应接口文档](backend-template-recording-api.md)。
全程开关只控制通道②独立原始文件生成，内部 ASR 持久录音证据仍用于断网/断电恢复。

`GET/POST /cases/{caseId}/document/fingerprint` 对应文末热区。POST 要求认证、当前冻结快照及真实设备 PNG；
保存快照 ID、图像 SHA-256、设备和操作人。未配置 SDK/驱动返回 `FINGERPRINT_NOT_CONFIGURED`，拒绝模拟结果。
Linux HAL 预留 `DeviceManager.capture_fingerprint()` 接口，当前仓库没有真实厂商实现，不虚报采集成功。

服务端 DOCX/PDF、导出次数和下载审计见 [导出接口文档](backend-export-api.md)。
现有文书沿用 `SUSPECT + OFFICER` 两角色；双方分开签名与指纹均归属同一冻结快照后才能生成签章 PDF。

## 迁移及部署边界

迁移依次为：`0021_question_capture_ownership` → `0022_template_knowledge_catalog` → `0023_officer_identity` →
`0024_case_management` → `0025_case_recordings` → `0026_document_exports` → `0027_document_fingerprints` → `0028_knowledge_vault_sync`。
部署先备份并执行 `python -m alembic upgrade head`，不得用 ORM create_all 替代迁移和回填。
新增依赖 `python-docx/reportlab/Pillow`。板端 Python3.10 与 CI Python3.11 均需验收；录音校验使用流式 SHA-256，不依赖 Python3.11 才提供的文件摘要接口。

声纹模型与任务默认关闭；仅历史兼容排查时设 `SUSPECT_LEGACY_VOICEPRINT_ENABLED=true`。
历史声纹表、样本和审计保留；完整删表需要单独的数据留存决定及迁移。本轮自助模式按要求暂缓。

生产验收必须遵守仓库 AGENTS.md：同一源提交原子部署前后端、验证迁移头/发布 SHA、可信 CA 的 HTTPS/WSS、
实际办理闭环、签名/真实指纹/导出、锁屏撤销连接权限、双通道录音开关，并证明 TCP8000 的原 FunASR 服务未改动。
当前只可报告本地实现和测试状态，尚未执行生产发布。

本地验证：后端全量 `744 passed, 12 skipped`；干净待提交快照发布检查 `71 passed`；独立安全/归属复查 `40 passed`。
Windows不具备 Unix socket 的用例保留平台条件，生产Linux仍须执行。PDF/DOCX中文两页样例已渲染检查，实际设备打印尚待验收。
