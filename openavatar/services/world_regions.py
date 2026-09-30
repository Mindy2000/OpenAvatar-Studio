from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from openavatar.db import Database


WORLD_REGIONS: dict[str, dict[str, Any]] = {
    "mainland_china": {
        "name_zh": "中国大陆",
        "name_en": "Mainland China",
        "daily_clock": ["通勤", "学习/工作", "家庭联系", "晚间休息"],
        "social_rules": ["家庭关系压力", "熟人社会", "节日返乡", "工作强度"],
        "holidays": ["春节", "中秋", "国庆"],
        "default_modules": ["family_pressure", "workload", "festival_return", "housing"],
        "event_pool": [
            ("mainland_family_ping", "家庭联系提醒", "家庭成员或亲近关系带来一个低影响联系。", {"resource.stress": 0.04, "resource.social_battery": -0.03}),
            ("mainland_work_shift", "工作/学习节奏变化", "工作、学习或通勤安排发生轻微调整。", {"resource.energy": -0.05, "resource.stress": 0.04}),
            ("mainland_festival_plan", "节日安排浮现", "节日、聚会或返乡计划进入近期日程。", {"resource.social_battery": -0.02, "resource.stress": 0.02}),
        ],
        "consistency_keywords": ["春节", "中秋", "国庆", "家庭", "通勤", "租房", "加班"],
        "builder_prompts": {
            "world_overview": "这个角色生活在中国大陆语境下的哪个城市/地区？家庭、学校、工作和城市生活对 TA 有什么影响？",
            "daily_life": "写 TA 的通勤、作息、工作/学习节奏、家庭联系频率，以及节假日时生活如何变化。",
            "organizations": "写 TA 所在学校、公司、社团或行业，以及其中的职级、同事/同学关系和压力来源。",
        },
    },
    "north_america": {
        "name_zh": "北美",
        "name_en": "North America",
        "daily_clock": ["commute", "work/school", "errands", "personal time"],
        "social_rules": ["personal boundaries", "independent living", "rent and credit", "insurance"],
        "holidays": ["Thanksgiving", "Christmas", "Independence Day"],
        "default_modules": ["housing", "credit_bills", "community", "career_mobility"],
        "event_pool": [
            ("na_housing_bill", "居住或账单提醒", "租房、账单、保险或信用记录出现一个低影响变化。", {"resource.stress": 0.05, "resource.energy": -0.02}),
            ("na_networking", "社区或 networking 机会", "社区、学校或工作网络里出现一次轻量互动。", {"resource.social_battery": -0.04}),
            ("na_mobility", "出行和城市移动", "开车、公共交通或搬家计划改变了今天的安排。", {"resource.energy": -0.04, "resource.stress": 0.03}),
        ],
        "consistency_keywords": ["insurance", "credit", "rent", "Thanksgiving", "commute", "networking"],
        "builder_prompts": {
            "world_overview": "这个角色生活在北美的哪个国家/城市？独立居住、通勤、学校/工作和社区关系如何影响 TA？",
            "daily_life": "写 TA 的居住方式、交通方式、账单/保险/信用压力、工作或学校节奏。",
            "organizations": "写 TA 的学校、公司、社区组织、networking 场景或职业流动路径。",
        },
    },
    "japan": {
        "name_zh": "日本",
        "name_en": "Japan",
        "daily_clock": ["通勤", "学校/会社", "便利店/车站", "夜间恢复"],
        "social_rules": ["敬语", "前后辈关系", "会社礼仪", "隐含情绪"],
        "holidays": ["新年", "樱花季", "盂兰盆节", "祭典"],
        "default_modules": ["keigo", "commute_station", "senpai_kohai", "company_school"],
        "event_pool": [
            ("jp_commute_delay", "通勤节奏被打乱", "车站、天气或通勤安排让今天出现轻微波动。", {"resource.energy": -0.04, "resource.stress": 0.04}),
            ("jp_senpai_ping", "前后辈关系变化", "学校、会社或社团中的关系出现一次低影响互动。", {"resource.social_battery": -0.04, "resource.stress": 0.02}),
            ("jp_seasonal_scene", "季节性场景出现", "樱花、新年、祭典或季节变化影响了今天的氛围。", {"resource.stress": -0.02}),
        ],
        "consistency_keywords": ["敬语", "会社", "前辈", "后辈", "通勤", "车站", "新年", "樱花"],
        "builder_prompts": {
            "world_overview": "这个角色生活在日本的哪个城市/地区？学校、会社、社团、通勤和礼仪关系如何影响 TA？",
            "daily_life": "写 TA 的通勤路线、学校/会社节奏、便利店/车站等日常地点，以及情绪表达方式。",
            "organizations": "写 TA 所属学校、会社、社团或项目，以及前后辈关系、敬语边界和组织压力。",
        },
    },
    "europe": {
        "name_zh": "欧洲",
        "name_en": "Europe",
        "daily_clock": ["public transport", "work/school", "public services", "holiday planning"],
        "social_rules": ["work-life boundaries", "public transport", "cross-cultural communication", "welfare systems"],
        "holidays": ["Christmas", "Easter", "summer holiday"],
        "default_modules": ["public_transport", "cross_border", "work_life", "housing_contract"],
        "event_pool": [
            ("eu_public_transit", "公共交通变化", "公共交通、城市移动或天气影响了今天的安排。", {"resource.energy": -0.03, "resource.stress": 0.03}),
            ("eu_admin_task", "公共服务或手续提醒", "签证、租房、公共服务或行政手续出现一个低影响事项。", {"resource.stress": 0.05}),
            ("eu_holiday_boundary", "假期与生活边界", "休假、旅行或工作生活边界影响了近期计划。", {"resource.stress": -0.02, "resource.social_battery": -0.02}),
        ],
        "consistency_keywords": ["公共交通", "签证", "租房合同", "Christmas", "Easter", "holiday", "welfare"],
        "builder_prompts": {
            "world_overview": "这个角色生活在欧洲的哪个国家/城市？多语言、公共交通、福利制度和工作生活边界如何影响 TA？",
            "daily_life": "写 TA 的公共交通、工作/学习节奏、假期安排、跨文化沟通和日常公共服务。",
            "organizations": "写 TA 的学校、公司、公共机构、签证/合同关系或跨国移动路径。",
        },
    },
    "custom": {
        "name_zh": "自定义",
        "name_en": "Custom",
        "daily_clock": ["自定义作息", "自定义组织", "自定义事件"],
        "social_rules": ["用户自定义规则"],
        "holidays": [],
        "default_modules": ["custom_rules", "custom_resources", "custom_events"],
        "event_pool": [
            ("custom_rule_event", "自定义世界规则触发", "一个由自定义世界规则驱动的低影响事件发生。", {"resource.energy": -0.03, "resource.stress": 0.03}),
            ("custom_resource_shift", "自定义资源变化", "世界的资源、组织或禁忌产生轻微变化。", {"resource.stress": 0.02}),
            ("custom_social_shift", "自定义关系变化", "一个符合自定义社会结构的关系互动出现。", {"resource.social_battery": -0.03}),
        ],
        "consistency_keywords": ["世界规则", "自定义", "禁忌", "资源", "组织"],
        "builder_prompts": {
            "world_overview": "描述这个自定义世界的名称、地理结构、技术/魔法水平、政治或组织系统，以及哪些规则稳定不可变。",
            "daily_life": "写这个世界的日常作息、交通/移动方式、资源消耗、常见活动和角色生活节奏。",
            "organizations": "写这个世界的组织、阶层、职业/任务系统、社会关系和冲突来源。",
        },
    },
}

LANGUAGE_PROFILES: dict[str, dict[str, str]] = {
    "zh-CN": {"name_zh": "中文", "name_en": "Chinese", "instruction": "主要使用自然中文表达。"},
    "en-US": {"name_zh": "English", "name_en": "English", "instruction": "Respond primarily in natural English."},
    "bilingual": {"name_zh": "中英双语", "name_en": "Chinese-English bilingual", "instruction": "根据用户输入语言切换，可自然中英混合。"},
    "custom": {"name_zh": "自定义", "name_en": "Custom", "instruction": "遵循用户自定义语言策略。"},
}

RESPONSE_MODES: dict[str, dict[str, str]] = {
    "follow_user": {"name_zh": "跟随用户输入", "name_en": "Follow user input"},
    "fixed_primary": {"name_zh": "固定主要语言", "name_en": "Fixed primary language"},
    "bilingual_mix": {"name_zh": "允许中英混合", "name_en": "Allow bilingual mix"},
    "scene_based": {"name_zh": "按场景切换", "name_en": "Scene based"},
}


def normalize_region(value: str) -> str:
    return value if value in WORLD_REGIONS else "custom"


def normalize_world_type(value: str) -> str:
    return value if value in {"realistic", "fictional", "hybrid"} else "realistic"


def normalize_language(value: str) -> str:
    return value if value in LANGUAGE_PROFILES else "zh-CN"


def normalize_response_mode(value: str) -> str:
    return value if value in RESPONSE_MODES else "follow_user"


def region_rules(region: str, custom: dict[str, Any] | None = None) -> dict[str, Any]:
    key = normalize_region(region)
    data = deepcopy(WORLD_REGIONS[key])
    if key == "custom" and custom:
        data["custom"] = custom
        if custom.get("name"):
            data["name_zh"] = str(custom["name"])[:80]
            data["name_en"] = str(custom["name"])[:80]
        for field in ("daily_clock", "social_rules", "holidays", "default_modules", "consistency_keywords"):
            if isinstance(custom.get(field), list):
                data[field] = [str(item)[:120] for item in custom[field]][:40]
    return data


def avatar_language_profile(row: dict[str, Any]) -> dict[str, Any]:
    secondary_raw = row.get("avatar_secondary_languages") or "[]"
    custom_raw = row.get("world_region_custom_json") or "{}"
    try:
        secondary = json.loads(str(secondary_raw))
    except json.JSONDecodeError:
        secondary = []
    try:
        custom = json.loads(str(custom_raw))
    except json.JSONDecodeError:
        custom = {}
    primary = normalize_language(str(row.get("avatar_primary_language") or "zh-CN"))
    response_mode = normalize_response_mode(str(row.get("avatar_response_mode") or "follow_user"))
    region = normalize_region(str(row.get("world_region") or "mainland_china"))
    world_type = normalize_world_type(str(row.get("world_type") or "realistic"))
    return {
        "avatar_primary_language": primary,
        "avatar_secondary_languages": secondary if isinstance(secondary, list) else [],
        "avatar_response_mode": response_mode,
        "world_region": region,
        "world_type": world_type,
        "world_region_custom": custom if isinstance(custom, dict) else {},
        "language_label": LANGUAGE_PROFILES[primary],
        "response_mode_label": RESPONSE_MODES[response_mode],
        "world_region_rules": region_rules(region, custom if isinstance(custom, dict) else {}),
    }


def world_options() -> dict[str, Any]:
    return {
        "interface_languages": [
            {"key": "zh-CN", "label": "中文"},
            {"key": "en-US", "label": "English"},
        ],
        "avatar_languages": [
            {"key": key, **value} for key, value in LANGUAGE_PROFILES.items()
        ],
        "response_modes": [
            {"key": key, **value} for key, value in RESPONSE_MODES.items()
        ],
        "world_regions": [
            {"key": key, "name_zh": value["name_zh"], "name_en": value["name_en"], "social_rules": value["social_rules"]} for key, value in WORLD_REGIONS.items()
        ],
        "world_types": [
            {"key": "realistic", "name_zh": "现实", "name_en": "Realistic"},
            {"key": "fictional", "name_zh": "架空", "name_en": "Fictional"},
            {"key": "hybrid", "name_zh": "混合", "name_en": "Hybrid"},
        ],
    }


def current_interface_language(db: Database) -> str:
    return normalize_language(str(db.setting("interface_language", "zh-CN")))
