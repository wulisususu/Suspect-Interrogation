# 模板、知识库与录音接口对接

接口前缀为 `/api/v1`，JSON 返回 `{ok, code, message, data}`。音频成功时返回 `audio/wav`，失败仍返回统一错误信封。生产环境完成民警身份配置后沿用会话认证；录音调阅即使在预览模式也必须认证。

## 模板目录与版本

| 方法与路径 | 请求 / 返回 |
| --- | --- |
| `GET /templates/catalog` | 启用模板列表，可直接映射 `TemplateCatalogItem` |
| `GET /templates?includeDisabled=true` | 管理列表，含停用模板 |
| `GET /templates/{templateId}` | 模板目录字段、当前版本与结构 |
| `POST /templates` | `{id, backendKey, catalog, structure}`，新建模板 |
| `PATCH /templates/{templateId}` | `{active: false}` 停用；`true` 启用 |
| `GET /templates/{templateId}/versions` | 从新到旧的不可变版本列表 |
| `POST /templates/{templateId}/versions` | `{structure, catalog?}`，保存新版本 |
| `GET /cases/{caseId}/template-selection` | 本案所选模板与结构快照；未选择返回 404 |
| `POST /cases/{caseId}/template-selection` | `{templateId}` 或 `{blank: true}`；返回本案 workspace |

目录包含 `id/title/category/tag/tagTone/badge/learning/summary/elements/minutes/scene/presetQuestions/backendKey`，另有 `active/version/learnedCount/elementDefinitions/structure/updatedAt`。分类为 `theft/injury/traffic/other`。

已学习份数暂由维护人显式填写 `catalog.learnedCount`，种子模板为 0，不使用示例统计数。版本保存时可只提供需要更新的目录字段；新建时至少包含 `title/category`。

```json
{
  "elements": [{"key": "incident_time", "label": "案发时间"}],
  "questions": [{"key": "time_question", "text": "事情是什么时候发生的？", "elementKey": "incident_time"}],
  "topics": [{"key": "facts", "title": "事实经过", "fields": [{"key": "time", "label": "时间", "type": "text"}]}]
}
```

`elements/questions` 必填，`topics` 是可选结构树。题目可附 `regexPatterns/aliases`。要素 key 在模板内唯一，题目 `elementKey` 必须属于该结构；身份与建档专用字段不能覆盖为核心要素。

选择模板会生成关联要素的正文题，并保留固定开头、结尾题。空白笔录只保留固定题且核心要素为空。已有回答、问答草稿或采集记录时更换模板返回 `TEMPLATE_SELECTION_HAS_WORK`；重复选择当前模板不重建题目。冻结、签署、归档或作废案件不可更换。模板改版、停用不会更改既有案件快照。

## 知识库

| 方法与路径 | 请求 / 返回 |
| --- | --- |
| `GET /knowledge/categories` | 可用分类，默认问话要点 / 法规条文 / 取证规范 / 安全提示 |
| `POST /knowledge/categories` | `{name}` |
| `PATCH /knowledge/categories/{id}` | `{name}` |
| `DELETE /knowledge/categories/{id}` | 停用分类；仍含未删除条目时返回 409 |
| `GET /knowledge/entries?categoryId=&active=&q=` | 管理条目列表 |
| `POST /knowledge/entries` | `{title, categoryId, content, keywords?: [], active?: true}` |
| `GET /knowledge/entries/{id}` | 条目详情 |
| `PATCH /knowledge/entries/{id}` | 上述字段的非空更新集合 |
| `DELETE /knowledge/entries/{id}` | 软删除，保留历史版本 |
| `GET /knowledge/entries/{id}/versions` | 创建、编辑、停用、删除的版本快照 |
| `GET /knowledge/guidance?categoryId=&q=` | 问话引导用列表，排除停用与已删除条目 |

停用使用 `PATCH {active:false}`，重新启用使用 `PATCH {active:true}`。前端问话引导应从 `/knowledge/guidance` 获取内容；后台列表可查看停用条目。

## 录音设置与调阅

| 方法与路径 | 请求 / 返回 |
| --- | --- |
| `GET /cases/{id}/recording-options` | `{caseId, fullRecordingEnabled}` |
| `PATCH /cases/{id}/recording-options` | `{fullRecordingEnabled: boolean}` |
| `GET /cases/{id}/recordings` | `{caseId, fullRecordingEnabled, questions, originals, originalAccessRequiresAdmin}` |
| `GET /cases/{id}/recordings/questions/{questionId}/captures/{captureId}/audio` | 本题采集完整分段 WAV |
| `GET /cases/{id}/recordings/questions/{questionId}/captures/{captureId}/fragments/{fragmentId}/audio` | 旧问答轮次关联片段范围 WAV |
| `GET /cases/{id}/recordings/originals/{captureId}/audio?reason=核对录音` | 管理员凭认证会话调阅原始全程文件，原因必填 |

`questions` 每条包含 `questionId/questionNumber/question/questionActive/captureSessionId/fragmentId/startSample/endSample/startMs/durationMs/startedAt/status/available/audioUrl`。`questionNumber` 是当前可见题号；历史已删除题的题号为 `null`，`questionActive=false`。新采集按后端保存的目标题归属，旧记录按问答轮次片段归属。只有完整保存的真实录音有可播放 `audioUrl`。

`originals` 每条包含 `captureSessionId/filename/durationMs/sizeBytes/sha256/startedAt/accessRequiresAdmin`。每次采集独立保存原始 WAV，案件可能有多个文件。调阅成功后落审计记录，包含真实民警警号、原因、采集编号与校验值。普通民警不能调阅通道②原始文件。

全程开关默认开启以保持旧行为；每次开始采集时保存当时开关快照。关闭时仍保留保障转写和逐题回听所需的耐久分段，但不生成通道②原始文件。后来重新打开不会追溯生成此前关闭采集的原始文件。采集中、冻结后或作废后不能改开关。

文件生成和回听使用耐久存档的实际采样数据，并校验完整性。没有录音不返回示例文件；存档损坏返回 `RECORDING_INTEGRITY_ERROR`。音频响应禁止共享缓存。录音服务未就绪返回 503，未认证返回 401，原始文件权限不足返回 403。
