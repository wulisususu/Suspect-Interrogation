# Linux Suspect Interrogation

面向 **RK3588 Linux 一体机** 的本地化嫌疑人审核 / 审讯辅助系统。

项目采用 **Vue 3 Kiosk + FastAPI + SQLite + Linux Hardware HAL + 本地 AI Runtime** 架构，身份证读取、语音识别、声纹、笔录、签名、案件数据和 AI 推理均在本地设备或受控内网中完成。

> **部署定位：完全内网 / 离线运行。**
>
> 正式环境不依赖公网、不调用云端 AI API，也不以 Internet SaaS、跨租户或零信任网络作为设计目标。系统默认运行在物理隔离或受控专用局域网中，允许同一可信内网中的 Kiosk 与授权浏览器终端访问 RK3588 服务。

---

## 项目定位

本项目不是普通的网页问答 Demo，而是一套围绕线下审讯场景构建的 Linux 原生一体机系统，重点解决：

- 身份证读卡器接入与身份信息采集；
- 嫌疑人 / 民警声纹注册与说话人识别；
- 连续语音采集、VAD、ASR 与实时片段管理；
- 审讯模板、问题轮次和正式问答记录；
- 人工修订、版本记录、事实项与案件时间线；
- 笔录冻结、SHA-256 快照、电子签名和报告状态；
- 本地 LLM / OCR / ASR / Speaker 模型调度；
- RK3588 本地部署、systemd 托管、备份恢复和健康检查。

系统优先保证 **离线可用、设备可控、业务状态可恢复、模型缺失可降级、数据保留在本地**。

---

## 正式产品架构

```text
┌─────────────────────────────────────────────────────┐
│                  受控专用局域网                     │
│                                                     │
│  RK3588 本机 Kiosk            内网浏览器终端         │
│       │                            │                 │
│       └────────── HTTPS / WSS ─────┘                 │
│                       │                             │
│              Vue 3 Linux Web App                   │
│                       │                             │
│               LinuxHttpWsAdapter                   │
│                       │                             │
│            FastAPI /api/v1 + WebSocket             │
│                       │                             │
│        SQLite + SQLAlchemy + Alembic               │
│                       │                             │
│       ┌───────────────┴────────────────┐            │
│       │                                │            │
│ Linux Hardware HAL              Offline AI Runtime │
│ ├── 身份证读卡器                ├── ASR            │
│ ├── ALSA 音频                   ├── VAD            │
│ ├── V4L2/UVC 摄像头             ├── Speaker        │
│ └── 电子签名                    ├── OCR            │
│                                 └── Qwen / LLM     │
│                                                     │
│ Audit / Snapshot / Backup / Health / systemd       │
└─────────────────────────────────────────────────────┘
```

正式运行链路不要求访问互联网。

---

## 内网部署模型

典型生产拓扑：

```text
RK3588
├── interrogation-api.service
├── ai-worker.service
├── kiosk.service
├── SQLite 数据库
├── 本地模型目录
├── USB / ALSA / V4L2 硬件
└── HTTPS :18080
        │
        ├── 本机 Kiosk
        └── 同一受控局域网中的浏览器终端
```

生产环境可监听：

```text
0.0.0.0:18080
```

该监听方式用于 **受控内网中的跨设备访问**，不是用于公网暴露。

推荐的网络前提：

- RK3588 与浏览器终端处于专用局域网 / VLAN；
- 路由器或防火墙不对公网转发 `18080`；
- 不配置公网反向代理、Cloudflare Tunnel、FRP 等外网入口；
- 模型、数据库、录音和备份均保留在本地设备或内部存储中；
- Windows / 其他内网浏览器通过项目 LAN CA 访问 HTTPS 服务。

---

## 安全边界与威胁模型

当前正式产品的安全边界是：

```text
公网 / 不可信网络
        ×
        │ 不属于正式部署面
        ×
受控专用局域网
        │
        ├── RK3588 Kiosk
        ├── 内网浏览器
        └── 本地硬件与模型
```

因此当前版本的设计前提是：

1. **系统完全运行在可信内网中**；
2. 不向 Internet 公开 API / WebSocket；
3. 不存在公网匿名用户或多租户场景；
4. 内网客户端由部署方统一管理；
5. 网络隔离本身是整体安全模型的一部分。

在这一部署模型下，公网场景常见的 OAuth、互联网级 RBAC、WAF、公网 API Gateway、跨租户隔离等能力 **不属于当前产品目标**。

项目仍保留本机侧和数据侧的安全措施，例如：

- HTTPS / WSS；
- 非 root systemd 服务账户；
- `NoNewPrivileges`、`ProtectSystem=strict` 等 systemd 沙箱；
- SQLite 外键、WAL 与数据库迁移；
- 审计记录；
- 文档冻结与 SHA-256 快照；
- 数据备份与完整性校验；
- 模型目录约束与离线运行；
- 生产数据目录权限控制。

> 如果未来需要跨网段、不可信 Wi-Fi、VPN 多用户、政务云或公网部署，应重新评估认证、授权、访问控制、审计身份和网络边界；当前 README 描述的是现阶段的 **完全内网一体机部署模型**。

---

## 核心业务链路

```text
身份读取 / 确认
      ↓
案件建立
      ↓
嫌疑人声纹注册
      ↓
审讯会话开始
      ↓
连续录音 / VAD / ASR / Speaker
      ↓
问题轮次与实时问答
      ↓
人工复核 / 修订 / 事实整理
      ↓
笔录冻结
      ↓
SHA-256 Snapshot
      ↓
嫌疑人 / 民警签名
      ↓
报告生成
```

业务状态由后端状态机控制，不依赖前端页面状态作为唯一事实来源。

---

## 语音与说话人链路

系统支持两种音频输入来源：

### RK3588 本机

```text
ALSA Microphone
      ↓
VAD
      ↓
ASR
      ↓
Speaker Embedding
      ↓
角色识别
      ↓
ASR Fragment
```

### 内网浏览器

```text
Browser Microphone
      ↓
WSS PCM Stream
      ↓
BrowserAudioInput
      ↓
VAD / ASR / Speaker
      ↓
ASR Fragment
```

正式声纹主模型当前使用 `eres2net_large`，设备校准记录用于确定实际运行时阈值与 margin。

---

## 离线 AI

正式环境不依赖任何云端 AI API。

模型由部署人员预先放入本地模型目录，通过：

```text
linux/backend/config/model-registry.yaml
```

进行注册。

当前 Runtime 覆盖：

- ASR：Paraformer / FunASR；
- VAD：FSMN-VAD；
- Speaker：ERes2Net Large；
- OCR：本地 OCR Runtime；
- LLM：本地 Qwen / llama.cpp / NPU Runtime。

模型缺失时，系统返回类似：

```text
MODEL_NOT_INSTALLED
NOT_CONFIGURED
ERROR
```

而不是让整个业务服务直接崩溃。

---

## 数据与证据链

核心数据保存在 SQLite 中，包括：

- Case；
- Person；
- InterrogationSession；
- Message / MessageRevision；
- Fact；
- Timeline；
- AuditLog；
- ASR Capture / Fragment；
- Voiceprint；
- DocumentSnapshot；
- SignatureRecord。

笔录冻结时会生成 canonical JSON，并计算 SHA-256：

```text
正式笔录内容
    ↓
Canonical JSON
    ↓
SHA-256
    ↓
Frozen Snapshot
    ↓
Signature Binding
```

冻结后的正式版本与后续签名、报告状态保持版本关联。

---

## Hardware HAL

业务代码不会直接依赖 `ctypes`、ALSA、V4L2 或厂商 SDK，而是通过 Linux Hardware HAL 访问设备。

```text
Business Service
      ↓
LinuxHardwareGateway
      ↓
DeviceManager
      ↓
Hardware Driver / Vendor SDK
```

目前覆盖：

- 身份证读卡器；
- 麦克风 / ALSA；
- 摄像头 / V4L2 / UVC；
- 电子签名设备；
- Mock / Simulator 测试模式。

---

## 目录职责

```text
.
├── linux/backend/       # 唯一正式 Linux 后端
├── webapp/              # Vue 3 + TypeScript Kiosk
├── deploy/              # 安装、升级、原子发布、回滚
├── systemd/             # API / AI / Kiosk 服务
├── scripts/             # 备份、恢复、健康检查、板端验收
├── tests/               # Release / E2E / Reliability 测试
├── docs/                # 架构、发布、安全与任务文档
├── backend-dev/         # 历史浏览器行为参考 / 开发工具
└── backend-fastapi/     # 早期迁移参考，不属于正式生产后端
```

### 正式代码边界

正式生产实现以以下目录为准：

```text
linux/backend/
webapp/
deploy/
systemd/
scripts/
```

`backend-dev/`、`backend-fastapi/` 等历史目录不应被视为当前正式后端。

---

## 本地开发

### Backend

```bash
cd linux/backend
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
alembic -c alembic.ini upgrade head
uvicorn app.main:app --host 127.0.0.1 --port 18080
```

### Web

```bash
cd webapp
npm ci
npm run dev
```

开发环境默认使用 loopback，避免无意中将测试服务暴露到局域网。

---

## 生产部署

项目提供 systemd 与部署脚本用于 RK3588：

```text
interrogation-api.service
ai-worker.service
kiosk.service
```

正式部署采用 release 目录 + `current` 链接方式切换版本，并在部署过程中执行数据库迁移、前端构建和健康检查。

生产环境示例：

```text
SUSPECT_API_HOST=0.0.0.0
SUSPECT_API_PORT=18080
SUSPECT_DEBUG=false
AI_MODE=real
MODELSCOPE_OFFLINE=1
HF_HUB_OFFLINE=1
TRANSFORMERS_OFFLINE=1
```

模型权重不进入 Git 仓库，而是部署到 RK3588 本地持久化目录。

---

## HTTPS / LAN CA

内网浏览器访问麦克风等 Web API 时需要安全上下文，因此生产环境提供 LAN TLS。

典型访问地址：

```text
https://192.168.2.109:18080
```

CA 与服务端私钥由部署环境生成并保存在 `/etc/suspect-interrogation/`，不会提交进仓库。

Windows 等内网客户端安装项目 CA 后即可正常通过 HTTPS / WSS 访问。

---

## 备份与恢复

备份脚本使用 SQLite Online Backup API 生成一致性数据库副本，并附带 SHA-256 manifest。

```bash
scripts/backup.sh
```

备份流程会：

1. 检查数据目录；
2. 拒绝不安全的 symlink；
3. 使用 SQLite backup API 复制数据库；
4. 执行 `PRAGMA integrity_check`；
5. 生成文件 SHA-256 manifest；
6. 打包数据；
7. 按 retention 自动清理旧备份。

---

## 测试与验证

### Python

```bash
PYTHONPATH=linux/backend python3 -m pytest linux/backend/tests -q
```

### Vue

```bash
cd webapp
npm test
npm run typecheck
npm run build
```

### 数据库迁移

```bash
scripts/ci/db-migration-gate.sh
```

### RK3588

仓库同时包含板端 smoke、真实设备、语音链路和 release 验收脚本。

GitHub Actions 的 `.github/workflows/linux-ci.yml` 负责 Hosted Linux 与 RK3588 self-hosted Runner 的持续验证。

---

## 设计原则

项目当前遵循以下原则：

- **Offline first**：核心业务不依赖公网；
- **Local data first**：案件和生物特征数据留在本机 / 内网；
- **Linux native**：正式产品不依赖 Android Runtime；
- **Hardware abstraction**：业务层不直接依赖厂商 SDK；
- **Fail closed on missing prerequisites**：关键前置条件缺失时拒绝进入正式流程；
- **Observable**：模型、设备、校准和服务状态可查询；
- **Recoverable**：数据库迁移、备份、恢复、release rollback 有明确链路；
- **Evidence oriented**：正式笔录、修订、审计、冻结和签名保留版本关系；
- **Trusted intranet deployment**：网络边界以受控专用局域网为前提，而不是公网 SaaS。

---

## 当前平台

主要目标环境：

```text
Architecture : aarch64
Platform     : RK3588 Linux
Frontend     : Vue 3 + TypeScript
Backend      : FastAPI + SQLAlchemy
Database     : SQLite + Alembic
Process      : systemd
Transport    : HTTPS + WebSocket
AI           : fully local / offline
Network      : trusted LAN only
```

项目仍在持续迭代中。正式部署前应以对应版本的 CI、RK3588 板端验收和项目现场测试结果为准。
