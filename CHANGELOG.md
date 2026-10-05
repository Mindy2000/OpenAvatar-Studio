# Changelog / 更新记录

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
