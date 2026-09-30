# 人物包协议 v3

[English](OPENAVATAR_PACKAGE_EN.md) · [用户手册](GUIDE.md)

扩展名 `.openavatar.zip`。当前导出 `format: openavatar.package`、`version: 3`，导入接受 v1、v2、v3。实现位于 `openavatar/services/packages.py`。

人物包用于迁移人物内容，不复制系统凭据库，不是完整数据库快照。完整备份与恢复应使用数据库备份功能。

## 文件结构

预检要求 `manifest.json`、`memories.json`、`messages.json`。其余部分按内容可选；当前导出通常写出这些 JSON，即使部分已被隐私选项清空。

| 文件 | 内容 |
|---|---|
| `manifest.json` | 版本、导出时间、人物与人格、语言/地区、旧模型设置与连接提示、协议及隐私声明 |
| `language_profile.json`、`world_region_profile.json` | 人物语言和地区运行规则；不迁移使用者的界面语言 |
| `memories.json`、`messages.json`、`evidence.json`、`rights.json` | 记忆、对话、证据与授权记录 |
| `world_facts.json`、`world_events.json`、`world_fact_proposals.json` | 世界事实、事件和提案 |
| `world_modules.json`、`world_runtime_settings.json`、`world_conflicts.json`、`world_snapshots.json` | 模块、运行配置、冲突和快照 |
| `memory_revisions.json`、`memory_graph_nodes.json`、`memory_graph_edges.json` | 记忆修订与图谱 |
| `persona_core.json`、`persona_feedback_rules.json` | 人格核心缓存与反馈规则 |
| `visual_assets.json`、`visual_asset_sets.json`、`scene_profiles.json`、`video_keyframes.json` | 视觉登记、连续性素材组、场景和视频关键帧 |
| `voice_profiles.json`、`voice_transcriptions.json`、`voice_events.json` | 声音档案、转写与事件 |
| `media_reviews.json`、`build_reports.json`、`builder_answers.json`、`quality_evaluations.json` | 媒体评审、构建、问答和评估 |
| `proactive_rules.json`、`decision_explanations.json`、`usage_events.json` | 主动联系规则、决策摘要与用量 |
| `realtime_call_sessions.json`、`realtime_call_turns.json` | 通话 session 与轮次记录 |
| `imports.json`、`provider_assets.json` | 导入元数据与外部资产引用 |
| `assets/` | 此人物的导入与生成文件，按导出开关筛选 |

新统一服务中心的连接和能力路由不作为可直接使用的凭据环境迁移。`model_connection_hint` 仅是旧连接的名称/地址/模型等提示，不含专用 Key 字段。

## 导出选项

| 选项关闭时 | 当前处理 |
|---|---|
| 对话 | 清空运行消息，过滤 conversation/imported 记忆和相关聊天证据、聊天源文件；清空决策解释、记忆修订、图谱与人格核心缓存 |
| 音频 | 排除导入音频和生成音频文件，清空转写，过滤声音 provider 资产；不代表删除所有声音档案元数据 |
| 图片 | 排除图片文件、生成图和视频关键帧文件；清空视觉登记、素材组、场景、关键帧及相关视觉/视频评审 |
| 视频 | 排除生成视频文件，清空关键帧记录并过滤视频资产与评审；独立图片开关仍影响关键帧文件 |
| 通话记录 | 清空实时通话 sessions 和 turns；不自动替代对话开关 |

API 参数为 `include_conversations`、`include_audio`、`include_images`、`include_video`、`include_call_history`。界面明确传入五项；旧客户端省略 `include_video` 时会沿用图片选项。

这些开关不是匿名化规则。画像摘要、世界事实、用户输入的秘密和图片里的文字仍可能存在；详见[隐私说明](PRIVACY.md)。不要把清单中的密钥声明视为全文秘密扫描。

## 导入与兼容

- 预检检查格式、版本、必要文件、成员路径、数量和展开大小，并显示资料与模型提示；在本机完成。
- 限制为最多 2,000 个成员、展开后合计不超过 1 GiB。导入上传上限为 `min(MAX_UPLOAD_MB × 10, 1024)` MiB，默认 500 MiB；普通素材默认上限为 50 MiB。
- 拒绝绝对路径、父目录穿越、反斜杠和 Windows 盘符形式；必要 JSON 类型也会校验。
- 用户确认资料使用权后，创建新人物 ID 并重写素材路径；专用 API Key 不导入。
- 外部服务绑定资产需重新检查/绑定，不能因保留服务端 ID 就认为新账号可用。
- v1/v2 缺少的新部分按实现补缺省值。旧 v1 预检提示文案仍可能提到 v2，这不改变当前 v3 导出版本。

人物包不导出完整 `chat_timeline_branches` 和 `historical_memory_corrections` 表，不能保证恢复所有封存分支、显示校正和内部 ID 关系。需要精确保留整个本机状态时使用数据库及素材目录备份。

## 状态

登记素材 API 接受 `candidate`、`approved`、`canonical`、`rejected`、`retired`。空白角色模板中的 `draft` 仅指设定草稿，不是登记素材的可写状态。用户批准前不得将候选当作 canonical 身份参考。

就绪级别为 `required`、`recommended`、`advanced`。世界事实使用 `real_verified`、`user_confirmed`、`fictional_canon`、`fictional_runtime`、`hybrid_derived`；可变性包括 `locked`、`approval_only`、`evolving`、`historical`。
