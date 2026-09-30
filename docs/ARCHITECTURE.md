# 架构

[English](ARCHITECTURE_EN.md) · [用户手册](GUIDE.md)

## 运行结构

FastAPI 提供本机 HTTP API、流式聊天、WebSocket 和静态前端。桌面启动器使用同一后端并打开系统浏览器。SQLite 保存人物、证据、世界、时间线、连接元数据和运行记录；文件保存在数据目录，专用凭据存入系统凭据库。

`main.py` 装配应用、生命周期、监控中间件和路由。导入该模块会创建应用并初始化数据库，因此测试与维护程序必须先设置隔离的数据目录。桌面启动器在确定数据目录后才导入它。

## 模块职责

| 模块 | 职责 |
|---|---|
| `config.py`、`db.py`、`migrations.py` | 配置、SQLite WAL/事务、迁移与备份；当前 schema v8 |
| `application.py` | 路由与服务共享的应用上下文 |
| `routes/` | 系统、人物、导入、世界、身份、一致性、智能、媒体、档案、运行与聊天接口 |
| `routes/_shared.py` | 现有路由共享导入层，不能简单按未直接引用清除 |
| `services/provider_hub.py`、`model_connections.py` | 新能力路由与旧模型配置的兼容衔接 |
| `providers.py`、`local_model.py` | OpenAI 兼容、Ollama、本地适配器和凭据读写 |
| `services/minimax.py`、`aliyun.py`、`video_generation.py`、`video_call.py` | 服务商多模态适配；North/Atlas 实时通话 |
| `services/continuity.py`、`media_jobs.py`、`video_review.py` | 参考合同、视频任务轮询、关键帧和验收 |
| `services/persona*`、`memory_intelligence.py`、`evidence.py` | 人格、证据、记忆、反馈和 Persona Core |
| `services/world_*`、`guided_builder.py`、`readiness.py` | 地区规则、世界运行、问答构建及就绪门禁 |
| `services/timeline_archive.py`、`packages.py` | 时间线管理与人物包迁移 |
| `runtime.py`、`events.py` | 运行 ID、取消、指标、租约、后台 Supervisor、领域事件与 Outbox |
| `static/core.js`、`profile.js`、`settings.js` | 页面基础、人物工作室和设置 |
| `static/imports.js`、`chat.js`、`video-call.js`、`app.js` | 导入、聊天、LiveKit 与事件装配 |
| `i18n/` | 中英文界面资源，包含静态文案、动态提示与系统返回信息；模板参数保留用户原文 |

## 数据与时间线

`imports`、`evidence` 和非 `runtime_chat` 的 `memories` 构成导入历史。`historical_memory_corrections` 是校正叠加层。`messages` 保存运行对话，`chat_timeline_branches` 管理正式/预览的活动与封存分支。基于 `source_message_id` 的关联限制聊天编辑对世界和记忆的影响范围。

迁移前备份与恢复前安全备份使用 SQLite 备份机制。人物包仅包含协议列明的可迁移内容，不能替代数据库备份；当前不导出完整分支表和历史校正表。详见[人物包协议](OPENAVATAR_PACKAGE.md)。

## 服务与媒体

`provider_connections` 和 `capability_routes` 保存新连接、能力、授权、预算与路由。专用 Key 通过连接 ID 映射到凭据库。`model_connections`、旧云服务设置仍用于兼容。新路由可在人物级覆盖全局选择，失败时按候选服务处理。

MiniMax、阿里云和 OpenRouter 的能力不同；视频适配器消费连续性参考合同，没有通用的固定主备顺序。后台轮询下载视频，FFmpeg 提取关键帧，审核结果决定重试或人工确认。关键帧不会自动升级为人物 canonical。

North/Atlas 创建并释放远程 session，浏览器通过 CDN 加载 LiveKit 并订阅头像轨道；复刻 TTS 可发布到房间。另一个 `/ws/avatars/{id}/call` 网关当前处理文字输入与流式文本输出；二进制实时 ASR 尚未接入。

## 运行接口

- `POST /api/avatars/{id}/chat/stream`：流式聊天。
- `POST /api/runtime/runs/{run_id}/cancel`：取消任务。
- `/ws/avatars/{id}/call`：文字驱动通话 WebSocket。
- `GET /api/runtime/metrics`：指标与数据库完整性状态。
- `/api/system/backup`、`/api/system/backups`：数据库备份、列表和带确认的恢复。
- `GET /api/templates/character`：返回 Markdown/YAML 模板；源定义位于 `services/templates.py`。

完整接口由运行中的 `/docs` 和 `/openapi.json` 提供。标准启动只绑定回环地址，项目不是公网鉴权网关。

## 当前边界

本地模型连接的回环校验与网络限制，以及 OCR 自动调用、估算预算、连接测试、日志与删除范围，统一记录在[隐私说明](PRIVACY.md)。本地模型请求拒绝代理和重定向；其他功能仍按文档所述边界运行。

仓库模板是运行时模板的同步副本；修改源定义时应同时更新副本。空白模板不包含演示人物。文档修改和检查规则见[贡献指南](../CONTRIBUTING.md)。
