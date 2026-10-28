# 民警名录、认证与签名接口

全部业务接口前缀为 `/api/v1`，JSON 返回 `{ok, code, message, data}`。请求与响应字段使用 camelCase。
下列能力不依赖声纹库；数据表由 `0023_officer_identity` 创建。

## 初始配置与身份边界

没有默认账号或默认密码。先按项目流程运行 Alembic 迁移，再在可信的主机终端配置账号：

```bash
cd linux/backend
python -m app.auth.provision --badge-number 038291 --name 张伟 --unit 刑侦 --admin
```

密码在终端隐藏输入并二次核对，要求12–256字符，不作为命令行参数或明文写入数据库。该命令读取
`DATABASE_URL` / `SUSPECT_DB_PATH`，不会用 `create_all()` 代替迁移。

未配置启用管理员时，既有接口继续保持预览模式，`GET /auth/session` 返回
`configured=false, required=false`。预览模式没有匿名新增管理员接口。配置首名启用管理员后，API和音频
WebSocket自动要求身份验证；`SUSPECT_AUTH_REQUIRED=1` 可在配置前使受保护接口拒绝匿名请求。
已有启用管理员时，环境变量不能关闭身份保护。为了避免锁死管理，不能停用或降权最后一名启用管理员。

认证通过服务端随机会话，数据库只存令牌SHA-256摘要；浏览器收到 HttpOnly、SameSite=Strict cookie，
HTTPS 下带 Secure。受保护API从会话解析操作人，`actor_id` 请求值和 `X-Actor-Id` 不是可信身份来源。
名录写操作限管理员；预录入签名限本人或管理员维护；**调用签名必须由签名民警本人确认**。

## 认证

| 方法与路径 | 请求 | 结果 |
|---|---|---|
| `POST /auth/login` | `badgeNumber, password` | 设置会话cookie，返回当前民警及免验时间 |
| `GET /auth/session` | — | `configured, required, authenticated, locked, officer, exemptionRemainingSeconds, expiresAt, exemptionUntil` |
| `POST /auth/lock` | — | 锁定当前会话，受保护请求返回423 |
| `POST /auth/unlock` | `{}` 或 `{password}` | 免验有效时直接解锁，过期后要求重新验证密码 |
| `POST /auth/logout` | — | 删除当前会话并清理cookie |

免验从成功验证起固定10分钟，普通请求不会延长。登录会话最长8小时。5次错误密码后该账号暂停登录1分钟；
计数在数据库中保留。停用账号或修改密码会撤销其已有会话。过期或无效cookie不会阻止加载静态页面或重新登录。

## 民警与本案人员

| 方法与路径 | 请求 / 返回 |
|---|---|
| `GET /officers?activeOnly=true` | 认证用户可获取名录；`badgeNumber, name, unit, enabled, isAdmin, displayName`，无密码字段 |
| `POST /officers` | 管理员提交 `badgeNumber, name, unit, password, isAdmin` |
| `PATCH /officers/{badgeNumber}` | 管理员提交 `name, unit, enabled, password, isAdmin` 中需修改的字段 |
| `GET /cases/{caseId}/officers` | 返回 `caseId, interrogator, recorder`，后两项为民警对象或null |
| `PUT /cases/{caseId}/officers` | `interrogatorBadgeNumber, recorderBadgeNumber`；null清除对应角色 |

人员关联存警号而不是姓名。停用人员不能新绑定；已冻结文书不能重新绑定。询问人与记录员不能选择同一人。
更新名录不会改写历史签名图像或签名调用记录。

## 预录入签名与调用

| 方法与路径 | 请求 / 返回 |
|---|---|
| `GET /officers/{badgeNumber}/signatures` | 签名版本列表：`id, badgeNumber, version, imageData, enabled, createdAt` |
| `POST /officers/{badgeNumber}/signatures` | `imageData`（PNG data URL），每次新增不可变版本 |
| `PATCH /officer-signatures/{signatureId}` | `{enabled}`，只改变是否可被调用，保留旧图像与记录 |
| `POST /cases/{caseId}/officer-signatures/apply` | `{signatureId}`；调用人必须是签名本人，且已绑定为本案询问人或记录员 |
| `GET /officers/{badgeNumber}/signature-uses?limit=100` | 本人或管理员查调用时间、案件、冻结快照、签名版本及调用人 |

签名图像限有效PNG、不超过512KB、边长不超过4096像素、像素总量不超过4194304。
校验PNG结构、CRC和有界解压结果，不接受任意文件URL。调用仅在既有文书签署允许状态进行，沿用
`OFFICER` 文书签名角色（当前文书模型每份冻结快照该角色只签一次）。复制的图像写入文书签名记录，
与调用日志在同一个事务提交，后续更换或停用预录入签名不会改动已签文书。

若前端要显示询问人和记录员各自独立签名，应先扩展既有文书的签名角色/冻结规则；本接口没有擅自改变
旧文书 `SUSPECT + OFFICER` 的签署完成条件。

## 中央注册

`create_app()` 注册 `app.api.officers.router`，并添加
`OfficerAuthMiddleware(session_factory=app.state.session_factory)`。
`app.database.officer_models` 必须在开发建库与 Alembic metadata 装载前导入。
审计仓储通过 `app.auth.context.current_actor_id()` 获取当前可信警号，优先于请求体传入值。

本接口文档说明本地实现契约；真实认证、签名设备与生产部署仍须按仓库验收流程验证。
