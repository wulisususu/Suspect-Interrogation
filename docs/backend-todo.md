# 后端待办（按设计稿改版前端后遗留）

来源：2026-10-27 起按《笔录智能工作台 · 被害人报案版》设计稿改版 ①选模板、②建档、③问答录入，
并将声纹移出办理流程。下列各项前端已按设计稿就位（或做了占位），需要后端补能力后才能真正生效。

状态：`待办` = 未开始；`前端就绪` = 前端已能消费，等后端提供数据。

## 1. 题目 ↔ 模板要素归属（前端就绪）

- 现状：案件题目没有「属于哪个核心要素」的数据。正文题的 `templateItemKey` 为空，开头/结尾固定题的
  `templateItemKey` 是 `opening-rights` 这类编号；要素（facts 的 `time` / `place` / `motive` …）只有状态，
  不知道是哪道题答出来的。
- 需要：
  - `case_questions` 增加 `element_key`（取值为该模板的核心要素 key），含 Alembic 迁移与回填。
  - 模板题目种子数据标注 `element_key`；现场追加的题（`source=LIVE`）允许民警指定或由后端推断。
  - `template-workspace` 返回题目时带 `elementKey`。
  - 题目作答（摘入正本）后同步更新对应要素的状态，供「已覆盖 N/M」使用。
- 前端：`FormalQuestion.elementKey` 已声明；`DictationRecordPreview.vue` 在有数据时自动按要素分段
  （「① 案发时间与地点 ✓已入正本」/「待补（模板要素 · 以下待摘入）」），无数据时按题号标注。

## 2. 模板目录与选模板（待办）

- 现状：每个案件只自动带出一个模板（`SUSPECT_INQUIRY_V1`）。①选模板页的其余 5 张卡是前端示例数据，
  见 `webapp/src/config/templateCatalog.ts`，选中示例模板时页面会如实提示「尚未接入后端」。
- 需要：
  - 模板目录接口：名称、分类（盗窃 / 伤害 / 交通 / 其他）、标签（推荐 / 最快 / 自助式不适用）、
    已学习份数、预估时长、适用场景、核心要素、预设问法。返回结构可直接对齐 `TemplateCatalogItem`。
  - 为案件选定模板：按所选模板生成题目与要素（结构快照，后续改模板不影响已建笔录）。
  - 「跳过模板 · 空白笔录」与「新建模板」（目前按钮禁用）。
  - 模板管理：版本化、停用不删除、版本历史（后台「模板管理 / 模板编辑」页目前为占位）。

## 3. 逐题录音的后端归属（待办）

- 现状：③问答录入「点卡即录」由前端编排——停止录音后按 `captureSessionId` 收集本次片段，
  再调 `POST /cases/{id}/questions/{qid}/answer-fragments`（`draft` / `replace`）挂成待摘入草稿。
  录音过程中刷新页面或断网，这一段的归属会丢失，片段留在未处理列表里。
- 需要：开始采集时接收 `target_question_id`（或 `mode=QUESTION`），片段落库即挂到该题草稿；
  前端的收集逻辑随之删除（`InterrogationWorkspace.vue` 的 `startCardAnswer` / `stopCardAnswer`）。

## 4. 追加一问（语音）（待办）

- 现状：按住说话追加问题时，前端把本次片段文字拼成新题，再逐条调用丢弃接口，避免挡住定稿冻结。
- 需要：「由多个片段创建问题」的接口，一次完成建题并把这些片段标记为已处理（现有
  `questions/from-fragment` 只接受一个片段）。

## 5. 同音字纠错与定稿校验（待办）

- ③答区的「纠错：雅迪 → 雅笛？同音字待确认 · 采纳 / 忽略」提示。
- ④定稿校验中的「时间线一致」「同音字纠错」两项目前标为待接入。

## 6. 建档能力（待办）

- 建档页「放置身份证 · 点击读取」：目前读卡只在新建询问时进行，建档页按钮禁用。
- 「开启全程录音（双通道录音）」开关：目前只显示、不可改；需要后端按案件保存并控制通道②全程录音。
- 指纹捺印采集（⑤签署归档热区）。

## 7. 民警名录与认证（待办）

- 询问人 / 记录员原先从民警声纹库取名单；声纹移除后改为手工填写。设计稿是「下拉选择 · 默认当前警官」，
  需要独立的民警名录（姓名、警号、单位）。
- 民警身份验证（警号 + 密码、验证后 10 分钟免验、手动锁屏），顶栏「认证尚未接入」。
- 民警签名预录入与调用记录（后台「民警签名管理」为占位）。

## 8. 声纹清理（阶段 3，待办）

声纹已移出办理流程（开始审讯与 ASR 采集不再要求声纹，片段说话人记为 UNKNOWN），但代码与数据仍在：

- 后端：`app/api/voiceprints.py`、`app/websocket/voiceprint_enrollment.py`、`voiceprint_service`、
  `officer_voiceprint_library`、`speaker_calibration_*`、`speaker_reference_rebuild`、说话人分析任务
  （`live_speech_coordinator` 的 SPEAKER 任务）、`voiceprint_models` 等表；删除需要 Alembic 迁移。
- 前端：`stores/interrogation.ts` 中的声纹状态与轮询、`VoiceprintPreparationPanel` /
  `VoiceprintEnrollmentGate` / `OfficerVoiceprintLibrary` / `SpeakerCalibrationCenter` /
  `SystemSettingsView`、`audio/browserVoiceprintCapture.ts`、`composables/useAutoVoiceprintEnrollment.ts`。
- 部署流水线：`rk3588-production-redeploy.yml` 的源码检查仍断言上述声纹文件存在，且语音 worker 健康检查
  要求 `speaker` 模型与 `eres2net_large` 后端就绪；清理时同步调整。

## 9. 其他占位页面（待办）

- 后台「知识库管理」「录音查看（双通道）」接口。
- 首页「自助模式」（当事人自助问答，设计稿 P04 右侧卡片与自助问答页）未实现。

## 9a. 设计走查（2026-10-28）提出的后端事项（待办）

- **自助模式（走查 D01，已决定本轮不做）**：设计稿第 5、9、10 页的当事人自助问答（身份确认 → 逐题口述 →
  民警核对）。只适用于被害人报案类模板，嫌疑人询问不允许自助；依赖第 2 项模板目录、当事人身份确认与在场民警
  核对记录。实现前大厅不放不可用的入口。
- **操作日志检索（D12 / D13）**：关键词、时间范围、操作类型、操作人四项筛选，结果列与分页；审计记录补充
  操作人显示名与对象摘要，前端负责把动作码映射为业务名称。
- **未完成办理的中断原因与停留位置（D15）**：区分断电续做、当事人离开挂起、网络中断、定稿中断，记录停留题号。
- **作废（D16）**：未完成 / 待定稿案件作废，须填原因并二次确认，记录留痕不可删除。

## 10. 前端遗留组件清理（待办）

按设计稿改版后以下组件已不再挂载，可在声纹清理（第 8 项）时一并删除：
`FormalTemplatePanel`（③④ 改为只读预览 `DictationRecordPreview` / `ReviewRecordPreview`）、
`SessionControls`（③ 由题卡开始 / 暂停，④「确认定稿」由后端结束询问）、`LiveDialoguePanel`、
`QuestionPreparationPanel`、`CasePreparationPage`、`VoiceprintSetupPage`、`AiSettingsPanel`。
AI 设置是否需要新的入口待定。前端 MOSS 转写代码已删除（见第 11 项）。

## 11. MOSS 转写下线（已完成 2026-10-27）

已决定不再使用 MOSS，前后端与部署链路一并移除：

- 前端：MOSS 面板、接口、类型、样式与测试。
- 后端：MOSS API 路由、转写服务与协调器、`app/ai/moss`、`moss_worker`、仓储与 ORM 模型、健康检查 `moss`
  能力、AI 设置与模型注册表条目、`requirements-moss-rk3588.txt`、相关测试。
- 数据库：新增迁移 `0020_drop_moss_transcription` 删除 `moss_transcriptions` /
  `moss_transcription_revisions` / `moss_speaker_mappings`（历史 MOSS 转写数据不可恢复；降级只重建空表）。
- 部署：生产部署工作流的「Restart MOSS worker」改为「Retire the MOSS worker」——停用并删除
  `moss-worker.service`，删除板上 `/opt/suspect-interrogation/models/moss-rk3588`、
  `/opt/suspect-interrogation/runtime/moss-env`、`/var/lib/suspect-interrogation/moss`、
  `/etc/suspect-interrogation/moss-worker.env`；共享的 `/run/suspect-interrogation`（ai-worker 的 speech.sock）
  改由 `/etc/tmpfiles.d/suspect-interrogation.conf` 创建。删除 `rk3588-moss-embed-probe.yml`、
  `tools/moss_rk3588`、`scripts/ci/probe-moss-rk3588.py`、`systemd/moss-worker.service`、`deploy/README.md`（MOSS 部署说明）。
- 保留：`tests/fixtures/speaker_turn_corpus` 中的 `mossGs` / `mossRole` 字段是历史标注数据；
  `docs/superpowers` 下的 MOSS 设计与计划文档作为历史记录保留。

## 附：已知的预存测试失败

以下 9 个后端测试在改版前的代码上即失败（本机缺语音 worker / 模型路径不同），与本次改版无关，
Linux CI 的 Python tests 步骤因此失败。`tests/release` 另有 4 个同样在改版前即失败的用例
（`test_speech_worker_launcher.py::test_systemd_delegates_stale_socket_safety_to_worker_server` 与
`test_rebuild_speaker_reference.py` 的 3 个）：

```text
tests/test_asr_capture_service.py::test_audio_level_event_is_throttled_and_counts_suppressed_pcm
tests/test_asr_recognition_evidence.py::test_manual_correction_keeps_ai_evidence_and_appends_revision
tests/test_asr_recognition_evidence.py::test_text_only_correction_preserves_speaker_and_still_appends_revision
tests/test_funasr_runtime_adapter.py::test_default_model_paths_are_stable_opt_layout
tests/test_funasr_runtime_adapter.py::test_legacy_xvector_assets_are_not_loaded_by_the_eres_runtime
tests/test_health_contract.py::test_runtime_capabilities_endpoint_exposes_frontend_contract
tests/test_speech_calibration.py::test_eres2net_load_failure_keeps_asr_and_vad_available
tests/test_speech_session.py::test_active_utterance_emits_a_preview_without_waiting_for_vad_end
tests/test_speech_worker_server.py::test_server_round_trip_uses_unix_socket_and_session_lifecycle
```
