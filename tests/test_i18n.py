from openavatar.db import Database
from openavatar.desktop import desktop_language
from openavatar.services.guided_builder import _localized_item, FICTIONAL_MODULES


def test_desktop_reads_language_without_creating_database(tmp_path):
    assert desktop_language(tmp_path) == "zh-CN"
    assert not (tmp_path / "openavatar.sqlite").exists()
    db = Database(tmp_path / "openavatar.sqlite")
    db.initialize()
    db.set_setting("interface_language", "en-US")
    assert desktop_language(tmp_path) == "en-US"
    db.set_setting("interface_language", "zh-CN")
    assert desktop_language(tmp_path) == "zh-CN"
    db.set_setting("interface_language", "invalid")
    assert desktop_language(tmp_path) == "zh-CN"


def test_builder_questions_follow_interface_not_avatar_language():
    for item in FICTIONAL_MODULES:
        english = _localized_item(item, {"interface_language": "en-US", "avatar_primary_language": "zh-CN"})
        chinese = _localized_item(item, {"interface_language": "zh-CN", "avatar_primary_language": "en-US"})
        assert english["title"] != item["title"]
        assert english["key"] == chinese["key"] == item["key"]
        assert english["fact_key"] == chinese["fact_key"] == item["fact_key"]
        assert chinese["title"] == item["title"]
