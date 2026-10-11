# Changelog / 更新记录

## Unreleased / 尚未发布

### 中文

- 增加三步首次配置指南：对话服务 → 可选声音/看图 → 完成人物并聊天。检查已保存路由、启用、授权、凭据存在和预算，复用原设置/创建入口，不调用模型；空库首次显示，可跳过并重新打开，已有用户不强弹。
- 浏览器语音通话取消固定3轮限制，开始前设置最长时长及本次人民币估算额度；默认10分钟/5元，可设1～120分钟/0.01～1000元。接近限额提示，到时或不足以下一次请求时结束。开始时本机预检声音配置/授权/凭据/预算，每轮先联合检查对话及最多3段语音的估算；预检不调用云服务，不重复预留。
- 通话回复保留80字符、已配置模型和所选音色，按句分段并顺序朗读；每轮最多3次TTS请求。打断停止旧播放及队列，失败不自动重试或切换服务。分段可能改变按请求计费的总额，尚未承诺实际延迟改善。
- 支持显式阅读聊天里的TXT、MD、CSV和文本PDF并提问：文本≤2 MB，PDF≤10 MB/20页，提取文本≤20,000字符，无OCR。上传不自动分析；逐次确认数据发送及费用，每次提问最多一次调用，不自动重试。回复含文件来源，普通后续聊天不自动附带全文。
- 在文字和有转写的语音消息旁增加记住、纠正和停用。经确认后只在本机处理，保留原聊天和修订记录；纠正/停用排除原消息与同轮回复的后续上下文，停用关联记忆。修改/停用已合并来源也停用包含它的合并记忆，弹窗事先说明；预览与正式记忆不能互合，睡眠整理跳过显式聊天记忆及合并派生。人物包导出记忆ID，导入映射修订及合并来源，保留相关控制；不删除原聊天或独立资料。

本次时长和额度控制使用估算预留，不是实际扣款或服务商账单硬上限；失败或已打断的请求仍可能收费，不退回已用预留。此次升级尚未进行真实付费服务验收；旧版的真实通话/自拍看图结论不能自动覆盖新流程。应用版本仍为0.1.0-rc.5，本节不代表新安装包已经发布。

### English

- Add three-step first-run guidance: configure Chat → optional Voice/Images → finish an avatar and chat. Checks saved routes, enabled state, consent, credential presence, and budgets, then reuses existing settings/creation without calling a model. It appears for new empty installations, remembers dismissal, can be reopened, and does not force existing users through it.
- Remove the fixed three-turn browser-call limit. Set duration and estimated CNY allowance before starting; defaults are ten minutes/CNY 5, with ranges of 1–120 minutes/CNY 0.01–1,000. Warn near limits and end at the deadline or when the next request cannot fit. Local startup checks cover voice configuration, consent, credentials, and budgets; each turn first checks the combined chat/maximum-three-segment estimate without cloud probes or duplicate reservations.
- Keep the configured model, selected voice, and 80-character replies while synthesizing/playing sentence segments in order, with at most three TTS requests per reply. Interruption stops old playback and queues; failures do not automatically retry or switch providers. Per-request billing totals may change; actual latency improvement is not yet claimed.
- Explicitly read and question chat TXT, MD, CSV, and text-layer PDFs: text ≤2 MB, PDFs ≤10 MB/20 pages, extracted text ≤20,000 characters, without OCR. Uploads do not trigger analysis. Each submission confirms data transfer/costs and makes at most one call without automatic retry. Replies include a file source; ordinary later chat does not automatically include the full document.
- Add remember, correct, and deactivate controls beside text/transcribed voice messages. Confirmed actions run locally and retain chats and revisions. Correction/deactivation excludes the source and same-turn reply from later context; deactivation disables linked memories. Changing/stopping merged sources also disables memories containing them, with an advance dialog notice. Preview and official memories cannot be merged together; sleep consolidation skips explicit chat notes and merged derivatives. Packages export memory IDs and remap revisions and merge provenance on import, preserving these controls without deleting original chats or independent material.

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
