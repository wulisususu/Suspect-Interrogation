# 冻结正本导出接口

后端接口统一使用 `/api/v1` 前缀与 `{ok, code, message, data}` 信封。以下接口在预览模式下也要求真实民警登录会话；不接受前端传入操作人或存储路径。

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| POST | `/cases/{caseId}/exports` | 生成新文件，入参 `{"format":"DOCX"}` 或 `{"format":"PDF"}` |
| GET | `/cases/{caseId}/exports?limit=100&offset=0` | 导出历史，`limit` 上限 200 |
| GET | `/cases/{caseId}/exports/{exportId}/file` | 校验后下载文件，并记录调阅审计 |

生成结果包含 `id`、`caseId`、`snapshotId`、`snapshotHash`、`format`、`fileName`、`sha256`、`sizeBytes`、`actorId`、`createdAt`、`signatureCount`、`fingerprintSha256`、`downloadUrl` 和本案累计 `exportCount`。列表返回 `{caseId, exportCount, items}`。下载返回附件，`Cache-Control: no-store`。

DOCX 是实际 Office Open XML 文件，内容来自最新持久化冻结快照。追加题与模板题统一使用快照 `questions[].formalAnswerText`；采集回合草稿不混入正本。历史快照没有 `questions` 时才读取历史回合。纯文字版不包含签名或指纹图片。

新冻结快照保存当时的案件身份资料、询问人/记录人名录与会话起止时间。两种格式均保留询问起止时间、询问地点、询问人、记录人、被询问人及证件号码、案件编号。时间统一显示北京时间（UTC+08:00）；地点和历史手工记录人取冻结 `facts`，名录身份优先取冻结案件元数据。导出不回查实时身份、民警名录或案件要素。旧快照及其原始哈希不修改，缺少字段显示“未记录”，不以建案时间冒充询问开始时间。

PDF 同样只读取冻结快照，并要求案件已签署或已归档、同一快照的 `SUSPECT` 和 `OFFICER` 两类签名完整、同一快照的真实设备指纹已采集。每次生成重新验证冻结内容 SHA-256、签名 PNG 有效性和指纹图像 SHA-256。PDF 文末放置双方签名及指纹图像；数据库保存本次引用的签名图像哈希和指纹哈希。签名图像不是数字证书签名；文件 SHA-256 用于完整性校验。

文件仅写入配置 `RuntimeSettings.data_dir/exports`，使用随机 UUID 文件名；导出目录和下载文件拒绝越界符号链接。下载时验证案件归属、文件名、大小及 SHA-256。创建文件、导出记录和审计记录必须全部成功；失败则回滚记录并删除生成文件。没有删除或覆盖历史导出的接口。

审计动作 `DOCUMENT_EXPORT` 包含格式、快照版本哈希、文件哈希和累计次数；`DOCUMENT_EXPORT_DOWNLOAD` 记录下载人、格式与文件哈希。迁移为 `0026_document_exports`，上游 `0025_case_recordings`；运行依赖新增 `python-docx`、`reportlab`、`Pillow`。

常见状态码：401 未认证；404 跨案件或记录不存在；409 未冻结、快照校验失败、未完成双方签名、缺指纹或图像校验失败。作废案件按统一规则禁止导出和下载。

## 版式与验证边界

输出为 A4 中文笔录，问句尽可能与回答保持在同页。PDF 使用 ReportLab `STSong-Light` 中文 CID 字体，不依赖设备安装宋体，但不会嵌入完整字体文件；离线打印及目标设备阅读器仍需验收，当前不宣称符合 PDF/A。DOCX 声明宋体，实际字形取决于 Word 阅读环境。

本地使用 15 问中文样例生成并逐页检查两页 PDF。环境未安装 LibreOffice，`render_docx.py` 无法调用 `soffice.exe`，因此使用已安装 Microsoft Word 的只读导出功能生成 PDF，再以捆绑 PDFium 渲染逐页检查 DOCX 的两页版面。测试覆盖真实 DOCX ZIP、纯文字内容、同快照签名与指纹、身份校验、路径与文件篡改、失败回滚、API 下载和 Alembic 升降级。生产设备及真实采集器尚待联调验收。
