from astrbot_plugin_group_member_context.member_context import (
    build_identity_prompt,
    build_session_key,
    clear_member_identity,
    merge_remote_members,
    normalize_member,
    normalize_custom_identity_fields,
    normalize_message_window_size,
    normalize_log_detail,
    normalize_store,
    select_members_for_window,
)


def test_session_key_matches_astrbot_group_message_origin():
    assert build_session_key("onebot-main", "123456") == (
        "onebot-main:GroupMessage:123456"
    )


def test_message_window_size_is_bounded_with_a_twenty_message_default():
    assert normalize_message_window_size(None) == 20
    assert normalize_message_window_size(0) == 1
    assert normalize_message_window_size(999) == 200
    assert normalize_message_window_size("invalid") == 20


def test_log_detail_accepts_the_plugin_config_labels():
    assert normalize_log_detail("摘要") == "summary"
    assert normalize_log_detail("全部") == "full"
    assert normalize_log_detail("unexpected") == "summary"


def test_remote_members_keep_saved_aliases_and_notes():
    members = merge_remote_members(
        [
            {"user_id": 1001, "nickname": "A", "card": "A的群名片"},
            {"user_id": 1002, "nickname": "B"},
        ],
        [
            {
                "user_id": "1001",
                "aliases": ["Tony", "tony", "A哥"],
                "note": "项目负责人",
            }
        ],
    )
    assert members[0]["aliases"] == ["Tony", "A哥"]
    assert members[0]["note"] == "项目负责人"
    assert members[1]["aliases"] == []


def test_clear_member_identity_preserves_imported_metadata_only():
    member = clear_member_identity(
        {
            "user_id": "1001",
            "nickname": "A",
            "card": "群名片 A",
            "role": "owner",
            "title": "群头衔",
            "aliases": ["Tony"],
            "real_names": ["Tony Wang"],
            "nicknames": ["老王"],
            "custom_fields": {"游戏名": ["TonyGame"]},
            "note": "项目负责人",
        }
    )
    assert member["user_id"] == "1001"
    assert member["nickname"] == "A"
    assert member["card"] == "群名片 A"
    assert member["role"] == "owner"
    assert member["title"] == "群头衔"
    assert member["aliases"] == []
    assert member["real_names"] == []
    assert member["nicknames"] == []
    assert member["custom_fields"] == {}
    assert member["note"] == ""


def test_member_identity_fields_are_kept_separate():
    member = normalize_member(
        {
            "user_id": "1001",
            "nickname": "平台昵称 A",
            "aliases": ["A哥"],
            "real_names": ["Tony Wang"],
            "nicknames": ["老王"],
            "role": "owner",
            "title": "群头衔",
        }
    )
    assert member["aliases"] == ["A哥"]
    assert member["real_names"] == ["Tony Wang"]
    assert member["nicknames"] == ["老王"]
    assert member["nickname"] == "平台昵称 A"


def test_custom_identity_fields_are_normalized_and_written_with_their_labels():
    assert normalize_custom_identity_fields(["游戏名", "游戏名", "花名"]) == [
        "游戏名",
        "花名",
    ]
    member = normalize_member(
        {
            "user_id": "1001",
            "custom_fields": {"游戏名": ["TonyGame", "tonygame"], "花名": "老王"},
        }
    )
    assert member["custom_fields"] == {"游戏名": ["TonyGame"], "花名": ["老王"]}
    prompt = build_identity_prompt(
        group_id="123456",
        group_name="研发群",
        members=[member],
        custom_identity_fields=["花名", "游戏名"],
    )
    assert "- 花名：老王" in prompt
    assert "- 游戏名：TonyGame" in prompt


def test_custom_identity_fields_can_match_recent_message_text():
    members, reasons = select_members_for_window(
        [
            {
                "user_id": "1001",
                "custom_fields": {"游戏名": ["TonyGame"]},
            }
        ],
        [{"sender_id": "9999", "text": "TonyGame 今天上线了"}],
        custom_identity_fields=["游戏名"],
    )
    assert [member["user_id"] for member in members] == ["1001"]
    assert reasons["1001"]["mentions"] == ["TonyGame"]
    excluded, _ = select_members_for_window(
        [{"user_id": "1001", "custom_fields": {"游戏名": ["TonyGame"]}}],
        [{"sender_id": "9999", "text": "TonyGame 今天上线了"}],
        custom_identity_fields=[],
    )
    assert excluded == []


def test_prompt_contains_group_and_member_identity_data():
    prompt = build_identity_prompt(
        group_id="123456",
        group_name="研发群",
        members=[
            {
                "user_id": "1001",
                "nickname": "A",
                "aliases": ["Tony", "老板"],
                "real_names": ["Tony Wang"],
                "nicknames": ["老王"],
                "note": "项目负责人",
                "role": "owner",
                "title": "群头衔",
            }
        ],
    )
    assert "研发群" in prompt
    assert "1001" in prompt
    assert "Tony" in prompt
    assert "项目负责人" in prompt
    assert "外号：Tony、老板" in prompt
    assert "真名：Tony Wang" in prompt
    assert "自定义昵称：老王" in prompt
    assert "平台昵称：A" in prompt
    assert "owner" not in prompt
    assert "群头衔" not in prompt


def test_prompt_skips_members_without_custom_identity_data():
    prompt = build_identity_prompt(
        group_id="123456",
        group_name="研发群",
        members=[
            {"user_id": "1001", "nickname": "未编辑成员"},
            {"user_id": "1002", "nickname": "A", "aliases": ["Tony"]},
        ],
    )
    assert "1001" not in prompt
    assert "未编辑成员" not in prompt
    assert "1002" in prompt
    assert "Tony" in prompt


def test_prompt_is_empty_when_no_member_was_modified():
    assert (
        build_identity_prompt(
            group_id="123456",
            group_name="研发群",
            members=[{"user_id": "1001", "nickname": "未编辑成员", "card": "群名片"}],
        )
        == ""
    )


def test_window_selection_unions_speakers_and_name_mentions():
    members, reasons = select_members_for_window(
        [
            {
                "user_id": "1001",
                "nickname": "A",
                "card": "A的群名片",
                "real_names": ["Tony Wang"],
                "nicknames": ["老王"],
            },
            {"user_id": "1002", "aliases": ["小红"]},
            {"user_id": "1003", "nickname": "未配置成员"},
        ],
        [
            {"sender_id": "1003", "text": "Tony Wang、老王和小红都来过了"},
            {"sender_id": "9999", "text": "请问 A的群名片是谁？"},
        ],
    )

    assert [member["user_id"] for member in members] == ["1001", "1002"]
    assert set(reasons["1001"]["mentions"]) == {
        "Tony Wang",
        "老王",
        "A的群名片",
        "A",
    }
    assert reasons["1002"]["mentions"] == ["小红"]
    assert "1003" not in reasons


def test_window_selection_keeps_all_members_when_a_name_is_ambiguous():
    members, reasons = select_members_for_window(
        [
            {"user_id": "1001", "aliases": ["Tony"]},
            {"user_id": "1002", "real_names": ["Tony"]},
        ],
        [{"sender_id": "9999", "text": "Tony来了"}],
    )

    assert {member["user_id"] for member in members} == {"1001", "1002"}
    assert reasons["1001"]["mentions"] == ["Tony"]
    assert reasons["1002"]["mentions"] == ["Tony"]


def test_custom_prompt_can_be_injected_without_member_identity_data():
    prompt = build_identity_prompt(
        group_id="123456",
        group_name="研发群",
        members=[{"user_id": "1001", "nickname": "未编辑成员"}],
        custom_prompt="回答技术问题时先给结论。\n不确定时请明确说明。",
    )
    assert "【本群自定义 Prompt】" in prompt
    assert "回答技术问题时先给结论。\n不确定时请明确说明。" in prompt
    assert "1001" not in prompt


def test_store_keeps_separate_fields_and_custom_prompt():
    store = normalize_store(
        {
            "version": 1,
            "custom_identity_fields": ["游戏名", "花名"],
            "sessions": {
                "bot-a:GroupMessage:123": {
                    "platform_id": "bot-a",
                    "group_id": "123",
                    "custom_prompt": "只回答和项目有关的问题。",
                    "members": [
                        {
                            "user_id": "1",
                            "aliases": ["A哥"],
                            "real_names": ["Tony"],
                            "nicknames": ["老王"],
                        }
                    ],
                }
            },
        }
    )
    profile = store["sessions"]["bot-a:GroupMessage:123"]
    assert store["custom_identity_fields"] == ["游戏名", "花名"]
    assert profile["custom_prompt"] == "只回答和项目有关的问题。"
    assert profile["members"][0]["real_names"] == ["Tony"]
    assert profile["members"][0]["nicknames"] == ["老王"]


def test_store_keeps_profiles_isolated_by_platform_and_group():
    store = normalize_store(
        {
            "version": 1,
            "sessions": {
                "bot-a:GroupMessage:123": {
                    "platform_id": "bot-a",
                    "group_id": "123",
                    "members": [{"user_id": "1", "aliases": ["A"]}],
                },
                "bot-b:GroupMessage:123": {
                    "platform_id": "bot-b",
                    "group_id": "123",
                    "members": [{"user_id": "1", "aliases": ["B"]}],
                },
            },
        }
    )
    assert set(store["sessions"]) == {
        "bot-a:GroupMessage:123",
        "bot-b:GroupMessage:123",
    }
    assert store["sessions"]["bot-a:GroupMessage:123"]["members"][0]["aliases"] == ["A"]
    assert store["sessions"]["bot-b:GroupMessage:123"]["members"][0]["aliases"] == ["B"]
