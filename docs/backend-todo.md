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

## 10. 前端遗留组件清理（待办）

按设计稿改版后以下组件已不再挂载，可在声纹清理（第 8 项）时一并删除：
`FormalTemplatePanel`（③④ 改为只读预览 `DictationRecordPreview` / `ReviewRecordPreview`）、
`SessionControls`（③ 由题卡开始 / 暂停，④「确认定稿」由后端结束询问）、`LiveDialoguePanel`、
`QuestionPreparationPanel`、`CasePreparationPage`、`VoiceprintSetupPage`、`AiSettingsPanel`。
AI 设置是否需要新的入口待定。前端 MOSS 转写代码已删除（见第 11 项）。

## 11. MOSS 转写下线（待办，已决定不再使用）

前端 MOSS 面板、接口、类型与测试已于 2026-10-27 删除。后端与板端仍在运行：生产板 `moss-worker.service`
处于启用状态并占用 NPU，生产部署工作流每次都会重启它（`python -m moss_worker.main`），因此后端代码不能单独删。
需要按顺序：

1. 部署流水线：`rk3588-production-redeploy.yml` 的「Restart MOSS worker」步骤改为停用并移除
   `moss-worker.service`；`rk3588-service-bootstrap.yml` 去掉 MOSS 引导；删除 `rk3588-moss-embed-probe.yml`
   以及 `linux-ai-runtime-rk3588.yml` 中的 MOSS 相关检查（修改 `.github/workflows` 需要带 `workflow` 权限的令牌）。
2. 板端：停用并禁用 `moss-worker.service`。模型包 `/opt/suspect-interrogation/models/moss-rk3588`、
   运行时 `/opt/suspect-interrogation/runtime/moss-env`、任务目录 `/var/lib/suspect-interrogation/moss` 是否删除待定。
3. 后端代码：`app/api/moss_transcription.py`、`app/services/moss_transcription*.py`、`app/ai/moss/`、
   `app/repositories/moss_transcriptions.py`、`app/database/moss_models.py`、`moss_worker/`、`app/main.py` 中的路由与协调器、
   `app/health.py` 的 `moss` 能力、`app/ai/registry.py` / `settings.py` / `config/model-registry.yaml` 的 MOSS 配置、
   `requirements-moss-rk3588.txt`，以及约 20 个 `tests/test_moss_*.py`。
4. 数据库：MOSS 相关表（`0013_moss_transcription_integration`）是保留还是新增迁移删除，待定（删表不可恢复）。
5. 其他：`systemd/moss-worker.service`、`deploy/rebuild_moss_manifest.py`、`deploy/tmpfiles-suspect-interrogation.conf`、
   `tools/moss_rk3588/`、`scripts/ci/probe-moss-rk3588.py`、`tests/release` 与 `tests/tools` 中的 MOSS 测试、相关文档。

## 附：已知的预存测试失败

以下 9 个后端测试在改版前的代码上即失败（本机缺语音 worker / 模型路径不同），与本次改版无关，
Linux CI 的 Python tests 步骤因此失败：

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
