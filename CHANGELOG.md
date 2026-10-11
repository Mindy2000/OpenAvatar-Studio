# Changelog / 更新记录

## Unreleased / 尚未发布

### 中文

2026-10-12 全系统复核修复（仍未发布）：

- 数据库迁移升至 schema v9：升级前备份，当前源码拒绝打开高于其支持版本的库；旧安装包不因此获得降级保护。恢复先校验 OpenAvatar 表结构、完整性和关联并迁移临时副本，失败不覆盖当前库。恢复前安全备份可在原列表选回，通知游标随恢复重置。
- 人物包预检和导入共用 CRC、JSON 结构和数值校验；素材暂存与数据库事务绑定，失败清理。兼容 v1/v2/v3，重新映射世界快照的证据及事件、整理记忆的来源。
- 导入审核支持分页及跨页选择，只确认已查看且勾选的行；维护页可编辑已显示的旧记忆。重新批准恢复记忆原类别，人物分析和聊天统一使用正式、有效、已纠正资料，Persona Core 随设定和世界状态更新。
- 记忆整理不重复生成同源摘要，来源修改后停用旧摘要及相关派生；关闭对话导出也过滤带聊天来源的整理摘要。聊天检索涵盖千条之后的旧记忆并补充中文词片段匹配。世界回滚同步退回事件状态；不同值的待审批事实明确提示冲突。
- 主动联系开关与规则整体保存，失败尝试计入间隔/滚动24小时次数，连续三次失败暂停，检查连接后保存设置可恢复。关闭或修改规则会丢弃旧在途问候；提示上下文沿用有效记忆、人物语言和地区规则。
- 看图缓存绑定源消息版本和有效时间线，修改、回退、停用后清理并拒绝迟到结果。普通朗读限制单个在途请求及播放器。视频通话离开时先停止本机设备，迟到会话尝试补偿释放，释放失败保留重试入口。
- 未实际探测的媒体能力不显示为测试成功；废弃且不参与运行的旧任务路由不再允许保存。已配置能力路由失效时不静默转用旧账号，转写、复刻及媒体使用所选连接、模型和地址。
- 统一路由调用在事务中检查并预留估算费用，固定本次估价，完成后只结算一次；失败/取消保留预留并标记结算未知。有预算而缺少估价时拦截；没有预算的未知价格标为未知，不能视为免费。未配置相应能力路由的历史兼容入口（包括旧模型、阿里云及 North 配置）和独立 OCR 仍不具备统一预算保证。
- 视频提交、轮询和下载防止重复执行，取消后的迟到结果不自动启用资产；缺少审核帧不视作通过。同步后台工作移到工作线程，执行期间续租，避免阻塞本机请求或提前释放执行权。

上述验证使用临时资料、协议替身和前端流程检查；不增加真实本地模型、实时视频、其他服务商或硬件的验收结论。17 项后续体验建议不属于本次缺陷修复范围。

- 增加三步首次配置指南：对话服务 → 可选声音/看图 → 完成人物并聊天。检查已保存路由、启用、授权、凭据存在和预算，复用原设置/创建入口，不调用模型；空库首次显示，可跳过并重新打开，已有用户不强弹。
- 浏览器语音通话取消固定3轮限制，开始前设置最长时长及本次人民币估算额度；默认10分钟/5元，可设1～120分钟/0.01～1000元。接近限额提示，到时或不足以下一次请求时结束。开始时本机预检声音配置/授权/凭据/预算，每轮先联合检查对话及最多3段语音的估算；预检不调用云服务，不重复预留。
- 通话回复保留80字符、已配置模型和所选音色，按句分段并顺序朗读；每轮最多3次TTS请求。打断停止旧播放及队列，失败不自动重试或切换服务。分段可能改变按请求计费的总额，尚未承诺实际延迟改善。
- 支持显式阅读聊天里的TXT、MD、CSV和文本PDF并提问：文本≤2 MB，PDF≤10 MB/20页，提取文本≤20,000字符，无OCR。上传不自动分析；逐次确认数据发送及费用，每次提问最多一次调用，不自动重试。回复含文件来源，普通后续聊天不自动附带全文。
- 在文字和有转写的语音消息旁增加记住、纠正和停用。经确认后只在本机处理，保留原聊天和修订记录；纠正/停用排除原消息与同轮回复的后续上下文，停用关联记忆。修改/停用已合并来源也停用包含它的合并记忆，弹窗事先说明；预览与正式记忆不能互合，睡眠整理跳过显式聊天记忆及合并派生。人物包导出记忆ID，导入映射修订及合并来源，保留相关控制；不删除原聊天或独立资料。

- 修复文字聊天在等待首个响应时停止无效、连续发送后旧请求覆盖新请求状态的问题；请求始终绑定发送时的人物和预览/正式时间线。
- 升级后复核：修复快速切换人物/时间线及返回首页时，延迟响应覆盖当前页面；修复英文人物的语音识别语言，以及分块小数被提前断句。通话请求发起前即记录预算预留，结束后更新同一记录，打断后的在途语音仍计入日/月预算。
- 文件概括缓存仅复用当前时间线中未修改、未停用的完整问答；问答被编辑、回退或停用后不再返回旧结果；等待期间原问答变化或人物被删除，迟到回复不会复活聊天。
- 资料维护中的聊天记忆纠正/拒绝同步停用原上下文及合并派生；关闭聊天导出也排除含聊天来源的合并记忆。时间线回退同步停用派生记忆，恢复封存不会撤销之后明确做出的纠正/停用。

本次时长和额度控制使用估算预留，不是实际扣款或服务商账单硬上限；失败或已打断的请求仍可能收费，不退回已用预留。此次升级尚未进行真实付费服务验收；旧版的真实通话/自拍看图结论不能自动覆盖新流程。应用版本仍为0.1.0-rc.5，本节不代表新安装包已经发布。

### English

System-audit fixes dated 2026-10-12 (still unreleased):

- Move to schema v9 with pre-upgrade backups and future-version rejection in current source; this does not add downgrade protection to old binaries. Restore validates OpenAvatar tables, integrity and references, then migrates a disposable copy before replacing current data. Pre-restore backups appear in the restore list; restore resets the notification cursor identity.
- Share CRC, JSON-shape and numeric validation between package inspection/import. Stage assets with the database transaction and clean up failed imports. Retain v1/v2/v3 compatibility and remap snapshot evidence/events and consolidated-memory sources.
- Paginate import review and retain cross-page selections; confirm only reviewed, checked rows. Edit older visible maintenance records and restore their original kind on reapproval. Persona analysis/chat share active, corrected, official sources; Persona Core reflects current settings and world state.
- Deduplicate source-identical summaries and retire derivatives when sources change. Conversation-free exports also exclude summaries derived from chat. Retrieve older memories beyond the newest thousand with Chinese substring tokens. Rollback retires runtime events; differing pending fact values produce an explicit conflict.
- Save proactive enablement and rules together. Failed attempts count toward intervals/rolling 24-hour limits; three consecutive failures pause contact. Saving checked settings resumes it without erasing consumed attempts. Rule changes/disablement discard stale greetings; prompts use current memories, language and region policy.
- Bind image caches to source versions and active timelines; corrections, rollback and deactivation clear old results and reject late replies. Ordinary speech has one pending request/player. Leaving video calls stops local devices first, compensates late session creation and offers retry after release failure.
- Media capabilities that were not probed are not reported as successfully tested; inactive legacy task routes can no longer be saved. Unavailable configured capability routes do not silently use old accounts. Transcription, cloning and media honor selected connections, models and endpoints.
- Check and reserve routed estimates transactionally, freeze request pricing, and settle once. Failed/cancelled attempts retain reservations with unknown settlement. Configured budgets require a known estimate; unknown unbudgeted prices remain unknown, not free. Legacy paths without the corresponding capability route (including legacy model, Aliyun and North configurations) and independent OCR remain outside unified-budget guarantees.
- Prevent duplicate video submission/polling/downloads and late activation after cancellation. Missing review frames cannot pass acceptance. Synchronous background work runs in worker threads with renewed leases, keeping local requests responsive and execution ownership intact.

Validation uses temporary materials, protocol substitutes and frontend checks. It adds no live local-model, realtime-video, other-provider or hardware acceptance claim. The 17 separate experience suggestions are outside this defect-repair scope.

- Add three-step first-run guidance: configure Chat → optional Voice/Images → finish an avatar and chat. Checks saved routes, enabled state, consent, credential presence, and budgets, then reuses existing settings/creation without calling a model. It appears for new empty installations, remembers dismissal, can be reopened, and does not force existing users through it.
- Remove the fixed three-turn browser-call limit. Set duration and estimated CNY allowance before starting; defaults are ten minutes/CNY 5, with ranges of 1–120 minutes/CNY 0.01–1,000. Warn near limits and end at the deadline or when the next request cannot fit. Local startup checks cover voice configuration, consent, credentials, and budgets; each turn first checks the combined chat/maximum-three-segment estimate without cloud probes or duplicate reservations.
- Keep the configured model, selected voice, and 80-character replies while synthesizing/playing sentence segments in order, with at most three TTS requests per reply. Interruption stops old playback and queues; failures do not automatically retry or switch providers. Per-request billing totals may change; actual latency improvement is not yet claimed.
- Explicitly read and question chat TXT, MD, CSV, and text-layer PDFs: text ≤2 MB, PDFs ≤10 MB/20 pages, extracted text ≤20,000 characters, without OCR. Uploads do not trigger analysis. Each submission confirms data transfer/costs and makes at most one call without automatic retry. Replies include a file source; ordinary later chat does not automatically include the full document.
- Add remember, correct, and deactivate controls beside text/transcribed voice messages. Confirmed actions run locally and retain chats and revisions. Correction/deactivation excludes the source and same-turn reply from later context; deactivation disables linked memories. Changing/stopping merged sources also disables memories containing them, with an advance dialog notice. Preview and official memories cannot be merged together; sleep consolidation skips explicit chat notes and merged derivatives. Packages export memory IDs and remap revisions and merge provenance on import, preserving these controls without deleting original chats or independent material.

- Fix text-chat cancellation before response headers and stale request cleanup overwriting a newer request; every request remains bound to its original avatar and preview/official timeline.
- Post-upgrade review: ignore delayed responses after avatar/timeline navigation or returning home; fix English speech-recognition selection and split-chunk decimals. Call requests reserve connection budget before starting, then update the same usage row, so interrupted in-flight speech still counts toward daily/monthly estimates.
- Reuse document-summary caches only for unchanged, active question/answer pairs on the current timeline. Editing, rolling back, or deactivating a turn invalidates its old result; a late reply cannot revive a changed/deleted pending turn or a deleted avatar.
- Chat-memory corrections/rejections in Data Maintenance exclude source context and merged derivatives too; disabling conversation export also excludes memories merged from chat sources. Timeline rollback deactivates merged derivatives, and restoration preserves later explicit corrections/deactivations.

Limits use estimated reservations, not actual debits or hard caps on provider bills. Failed/interrupted requests may still be charged, so consumed reservations are not refunded. These upgrades have not undergone live paid-service acceptance; previous call/camera acceptance does not automatically cover them. The application version remains 0.1.0-rc.5; this section does not announce new published binaries.

## 0.1.0-rc.5 — 2026-10-05

### 中文

- 聊天输入区增加“＋”面板，集中提供图片/视频、拍摄、通话、文件、手动位置和收藏；通话包含语音和视频二级入口。
- 语音消息支持按住录音、松开发送、上滑取消。拍照默认镜像，可关闭；聊天图片可经授权交给已配置的视觉服务理解，失败需手动重试。
- 增加浏览器语音通话、连续回复、直接开口打断、静音、最小化和挂断。聊天与历史页只显示通话卡片，逐句文字仍在本机用于对话上下文。
- 普通、流式和语音消息回复统一限制为80字符；修正通话记录导出过滤，并说明旧合成音频的过滤范围。
- 修正人物包导入的零次主动联系设置、历史用量重复占用预算、问答就绪判断、记忆合并及世界冲突处理；主动问候结合本机时间。
- 修正统一服务中心的声音复刻费用估算及调用前预算检查：大陆 MiniMax 官方端点默认按人民币9.90元估算，其他连接须配置有效人民币估价。旧阿里云兼容入口不具备同一项预算预检，不能套用此保证。
- 同步中英文使用、隐私、架构、人物包文档，增加公开入门指南，并将新增聊天界面检查接入自动检查流程。

费用显示为估算，不是服务商账单上限。浏览器语音识别可能使用浏览器厂商的在线服务。文件与视频附件不会自动理解；二进制音频直送 WebSocket ASR 尚未实现。实时视频、本地模型、云端 OCR 和其他云服务商不在本轮真实服务验收结论内。桌面包仍为未签名的发布候选，不附带人物素材、私人数据或凭据。

### English

- Add a chat + panel for images/videos, camera, calls, files, manual locations, and favorites, with a voice/video call submenu.
- Support hold-to-record, release-to-send, and slide-to-cancel voice notes; mirrored camera capture with an off switch; and consented chat-image understanding with manual retries after failures.
- Add browser voice calls with consecutive replies, speech interruption, mute, minimize, and hangup. Chat and history show call cards; transcripts remain local for conversation context.
- Enforce an 80-character limit for ordinary, streamed, and voice-note replies. Correct call-history export filtering and document the treatment of legacy synthesized audio.
- Fix zero-contact limits and historical usage accounting on package import, guided readiness, memory merging, and world conflict handling. Proactive greetings use local time.
- Correct routed voice-cloning estimates and pre-call budget checks. Mainland MiniMax official endpoints default to CNY 9.90; other connections require an explicit valid CNY estimate. The legacy Aliyun compatibility path does not have the same budget preflight.
- Synchronize bilingual user, privacy, architecture, and package documentation, add public getting-started guides, and include new chat UI checks in the automated runner.

Costs remain estimates, not hard limits on provider bills. Browser recognition may use the browser vendor's online service. File/video attachments are not automatically interpreted, and binary-audio WebSocket ASR remains unimplemented. This acceptance round does not establish live verification of video calls, local models, cloud OCR, or other cloud providers. Desktop packages remain unsigned release candidates without avatar materials, private data, or credentials.
