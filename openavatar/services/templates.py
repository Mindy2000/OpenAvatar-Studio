from __future__ import annotations


AVATAR_MD_TEMPLATE = """# 角色名

> 本文件用于创建原创虚构数字人。请不要填写任何未授权真人资料。

## 身份
- 显示名：
- 年龄/年龄观感：
- 性别/称谓：
- 主要语言：
- 所在城市/生活区域：
- 职业/学习状态：
- 角色来源：完全原创虚构，不对应、不复刻、不暗示任何现实中的特定个人。

## 核心性格
- 
- 
- 

## 说话风格
- 常用语言和语气：
- 回复长度：
- 口头语/节奏：
- 不应该出现的表达：

## 关系设定
- 与用户的初始关系：
- 关系发展顺序：
- 允许/不允许的关系方向：
- 共同经历规则：

## 世界模型
- 世界类型：现实城市 / 架空城市 / 奇幻 / 科幻 / 其他
- 主要地点：
- 固定人物：
- 日常循环：
- 时间推进规则：程序运行时推进 / 完全由用户触发 / 只按剧情推进
- 现实信息边界：

## 视觉身份
- 外貌方向：
- 发型/服装/气质：
- 候选图生成要求：
- 批准规则：candidate -> approved -> canonical，用户批准前不得作为正式身份。

## 声音设定
- 声音来源：provider_builtin / local_tts / api_tts / voice_clone / none
- 期望声线：
- 备选声音：
- 是否允许真人声音复刻：否

## 边界与禁止事项
- 不冒充真人。
- 不编造未设定的共同经历。
- 不把虚构世界冒充现实新闻。
- 

## 示例对话
用户：
角色：
"""


CHARACTER_YAML_TEMPLATE = """schema_version: 1
kind: openavatar.character
name: ""
fictional: true
source_policy:
  human_source_data: false
  rights_basis: "original_fiction"
  provider_transfer_allowed: false
identity:
  display_name: ""
  age: ""
  age_appearance: ""
  gender: ""
  primary_language: "中文"
  city: ""
  occupation: ""
persona:
  summary: ""
  traits:
    - ""
  strengths:
    - ""
  flaws:
    - ""
  boundaries:
    - "不冒充真人"
    - "不编造未设定的共同经历"
speaking_style:
  summary: ""
  reply_length: ""
  rhythm: ""
  common_phrases:
    - ""
  forbidden_phrases:
    - ""
relationship:
  initial_stage: "陌生人"
  stage_order: ["陌生人", "熟悉", "信任", "暧昧", "恋爱"]
  romance_allowed: false
  shared_history_policy: "只承认系统启用后真实发生并被记录的共同经历"
world_model:
  world_type: ""
  time_rule: "runtime_only"
  places:
    - id: "home"
      name: ""
      reality_kind: "fictional_canon"
      mutability: "approval_only"
  cast:
    - id: "main"
      name: ""
      role: "主角"
      protected_core: true
  daily_loop:
    - ""
  reality_boundary: "真实地点、天气、新闻和机构信息必须有来源；虚构事实不得冒充现实。"
visual_identity:
  status: "draft"
  workflow: ["draft", "candidate", "approved", "canonical", "retired"]
  description: ""
  locked_traits:
    age_appearance: ""
    face: ""
    hair: ""
    body: ""
    temperament: ""
  approval_policy: "用户批准前不得进入 approved/canonical。"
voice:
  selection_required: true
  allowed_sources: ["provider_builtin", "local_tts", "api_tts", "voice_clone", "none"]
  selected:
    provider: ""
    voice_id: ""
    voice_name: ""
    model: ""
  fallback:
    provider: "local_tts"
    voice_id: ""
examples:
  - user: ""
    character: ""
"""


def template_payload() -> dict[str, str]:
    return {
        "avatar_md": AVATAR_MD_TEMPLATE,
        "character_yaml": CHARACTER_YAML_TEMPLATE,
    }
