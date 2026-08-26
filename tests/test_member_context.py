from astrbot_plugin_group_member_context.member_context import (
    BOT_NODE_ID,
    DEFAULT_USAGE_RULES,
    STORE_VERSION,
    build_bot_relationship_prompt,
    build_identity_prompt,
    build_session_key,
    clear_member_identity,
    empty_relationship_graph,
    merge_remote_members,
    normalize_member,
    normalize_custom_identity_fields,
    normalize_message_window_size,
    normalize_log_detail,
    normalize_relationship_graph,
    normalize_store,
    normalize_usage_rules,
    select_members_for_window,
    select_relationships_for_window,
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


def test_usage_rules_default_to_the_built_in_rules():
    assert normalize_usage_rules(None) == DEFAULT_USAGE_RULES
    assert "管理员" not in DEFAULT_USAGE_RULES


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
    assert "昵称：老王" in prompt
    assert "平台昵称：A" in prompt
    assert "【使用规则】" in prompt
    assert "管理员" not in prompt
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


def test_usage_rules_can_be_customized_without_member_identity_data():
    prompt = build_identity_prompt(
        group_id="123456",
        group_name="研发群",
        members=[{"user_id": "1001", "nickname": "未编辑成员"}],
        usage_rules="回答技术问题时先给结论。\n不确定时请明确说明。",
    )
    assert "【使用规则】" in prompt
    assert "回答技术问题时先给结论。\n不确定时请明确说明。" in prompt
    assert "【本群自定义 Prompt】" not in prompt
    assert "1001" not in prompt


def test_store_migrates_global_fields_into_each_group_profile():
    store = normalize_store(
        {
            "version": 1,
            "custom_identity_fields": ["游戏名", "花名"],
            "sessions": {
                "bot-a:GroupMessage:123": {
                    "platform_id": "bot-a",
                    "group_id": "123",
                    "usage_rules": "只回答和项目有关的问题。",
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
    assert "custom_identity_fields" not in store
    assert profile["custom_identity_fields"] == ["游戏名", "花名"]
    assert profile["usage_rules"] == "只回答和项目有关的问题。"
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
                    "custom_identity_fields": ["游戏名"],
                    "members": [{"user_id": "1", "aliases": ["A"]}],
                    "admin_command_whitelist": ["1", "1", "invalid"],
                    "allow_members_admin_commands": True,
                },
                "bot-b:GroupMessage:123": {
                    "platform_id": "bot-b",
                    "group_id": "123",
                    "custom_identity_fields": ["部门"],
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
    assert store["sessions"]["bot-a:GroupMessage:123"]["custom_identity_fields"] == [
        "游戏名"
    ]
    assert store["sessions"]["bot-b:GroupMessage:123"]["custom_identity_fields"] == [
        "部门"
    ]
    assert store["sessions"]["bot-a:GroupMessage:123"]["admin_command_whitelist"] == [
        "1"
    ]
    assert (
        store["sessions"]["bot-a:GroupMessage:123"]["allow_members_admin_commands"]
        is True
    )
    assert store["sessions"]["bot-b:GroupMessage:123"]["admin_command_whitelist"] == []
    assert (
        store["sessions"]["bot-b:GroupMessage:123"]["allow_members_admin_commands"]
        is False
    )


def _enabled_graph(**overrides):
    graph = empty_relationship_graph()
    graph["relationship_injection_enabled"] = True
    graph.update(overrides)
    return graph


def test_legacy_store_gets_an_empty_relationship_graph():
    store = normalize_store(
        {
            "version": 7,
            "sessions": {
                "bot-a:GroupMessage:123": {
                    "platform_id": "bot-a",
                    "group_id": "123",
                    "members": [{"user_id": "1", "aliases": ["A"]}],
                }
            },
        }
    )
    assert store["version"] == STORE_VERSION
    profile = store["sessions"]["bot-a:GroupMessage:123"]
    assert profile["relationship_injection_enabled"] is False
    assert profile["relationship_nodes"] == []
    assert profile["relationship_edges"] == []
    assert "relationship_groups" not in profile
    assert profile["members"][0]["aliases"] == ["A"]
    assert any(item["id"] == "friend" for item in profile["relationship_types"])
    assert all(item["id"] != "owner" for item in profile["relationship_types"])


def test_relationship_graph_keeps_one_bot_node_and_drops_removed_owner_type():
    graph = normalize_relationship_graph(
        {
            "relationship_injection_enabled": True,
            "relationship_nodes": [
                {"id": BOT_NODE_ID, "kind": "bot", "x": 10, "y": 20},
                {"kind": "bot", "x": 99, "y": 99},
                {"user_id": "1001", "x": 1, "y": 2},
                {"user_id": "1002", "x": 3, "y": 4},
            ],
            "relationship_groups": [
                {"id": "g_1", "name": "项目组", "member_ids": ["1001", "1002"]}
            ],
            "relationship_edges": [
                {
                    "source": "1001",
                    "target": "1002",
                    "type_id": "owner",
                },
                {
                    "source": BOT_NODE_ID,
                    "target": "1001",
                    "type_id": "friend",
                },
                {
                    "source": "1001",
                    "target": "1002",
                    "type_id": "friend",
                },
                {
                    "source": "1001",
                    "target": "1002",
                    "type_id": "cordial",
                },
            ],
        }
    )
    assert [node["id"] for node in graph["relationship_nodes"] if node["kind"] == "bot"] == [
        BOT_NODE_ID
    ]
    assert "relationship_groups" not in graph
    type_ids = {(edge["source"], edge["target"], edge["type_id"]) for edge in graph["relationship_edges"]}
    assert (BOT_NODE_ID, "1001", "friend") in type_ids
    assert ("1001", "1002", "friend") in type_ids
    assert ("1001", "1002", "cordial") in type_ids
    assert all(edge["type_id"] != "owner" for edge in graph["relationship_edges"])


def test_legacy_owner_custom_type_is_dropped():
    graph = normalize_relationship_graph(
        {
            "relationship_types": [
                {"id": "owner", "label": "主人", "color": "#c9a227", "builtin": False}
            ],
            "relationship_nodes": [
                {"id": BOT_NODE_ID, "kind": "bot", "x": 0, "y": 0},
                {"user_id": "1001", "x": 10, "y": 0},
            ],
            "relationship_edges": [
                {"source": BOT_NODE_ID, "target": "1001", "type_id": "owner"},
            ],
        }
    )
    assert all(item["id"] != "owner" and item["label"] != "主人" for item in graph["relationship_types"])
    assert graph["relationship_edges"] == []


def test_window_selection_excludes_the_bot_from_identity_matches():
    members, reasons = select_members_for_window(
        [{"user_id": "9999", "aliases": ["机器人"]}, {"user_id": "1001", "aliases": ["Tony"]}],
        [{"sender_id": "9999", "text": "Tony 在吗"}],
        exclude_user_ids=["9999"],
    )
    assert [member["user_id"] for member in members] == ["1001"]
    assert "9999" not in reasons


def test_peer_relationships_inject_when_one_endpoint_is_in_the_window():
    graph = _enabled_graph(
        relationship_nodes=[
            {"user_id": "1001", "x": 0, "y": 0},
            {"user_id": "1002", "x": 10, "y": 0},
        ],
        relationship_edges=[
            {"source": "1001", "target": "1002", "type_id": "couple"},
        ],
    )
    selection = select_relationships_for_window(graph, window_participant_ids=["1001"])
    assert len(selection["peer_edges"]) == 1
    prompt = build_identity_prompt(
        group_id="123456",
        group_name="研发群",
        members=[{"user_id": "1001", "aliases": ["Tony"]}],
        relationship_graph=graph,
        window_participant_ids=["1001"],
        all_members=[
            {"user_id": "1001", "card": "小明", "aliases": ["Tony"]},
            {"user_id": "1002", "nickname": "小红"},
        ],
    )
    assert "\n【群成员关系】\n" in prompt
    assert "小明（QQ：1001） 与 小红（QQ：1002） 的关系是：情侣" in prompt
    assert "你和群友" not in prompt.split("\n【群成员关系】\n", 1)[1]


def test_directed_lines_use_third_person_for_peers():
    graph = _enabled_graph(
        relationship_nodes=[
            {"user_id": "1001", "x": 0, "y": 0},
            {"user_id": "1002", "x": 10, "y": 0},
        ],
        relationship_edges=[
            {"source": "1001", "target": "1002", "type_id": "pursue"},
        ],
    )
    prompt = build_identity_prompt(
        group_id="1",
        group_name="群",
        members=[{"user_id": "1001", "aliases": ["A"]}],
        relationship_graph=graph,
        window_participant_ids=["1001"],
        all_members=[
            {"user_id": "1001", "nickname": "小明", "aliases": ["A"]},
            {"user_id": "1002", "nickname": "小红"},
        ],
    )
    assert "小明（QQ：1001） 对 小红（QQ：1002） 的关系是：追求" in prompt
    assert "同属团体" not in prompt


def test_bot_prompt_uses_second_person_only_for_window_members():
    graph = _enabled_graph(
        relationship_nodes=[
            {"id": BOT_NODE_ID, "kind": "bot", "x": 0, "y": 0},
            {"user_id": "1001", "x": 10, "y": 0},
            {"user_id": "1002", "x": 20, "y": 0},
        ],
        relationship_edges=[
            {"source": BOT_NODE_ID, "target": "1001", "type_id": "friend"},
            {"source": "1002", "target": BOT_NODE_ID, "type_id": "admire"},
        ],
    )
    members = [
        {"user_id": "1001", "card": "小明"},
        {"user_id": "1002", "nickname": "小红"},
    ]
    idle = build_bot_relationship_prompt(
        members=members,
        relationship_graph=graph,
        window_participant_ids=["999"],
    )
    assert idle == ""

    with_window = build_bot_relationship_prompt(
        members=members,
        relationship_graph=graph,
        window_participant_ids=["1002"],
    )
    assert with_window.startswith("<bot_relationship_context>")
    assert "你和群友小明" not in with_window
    assert "你和群友小红（QQ：1002）的关系是：朋友" not in with_window
    assert "小红（QQ：1002）对你的关系是：仰慕" in with_window
    identity = build_identity_prompt(
        group_id="1",
        group_name="群",
        members=[{"user_id": "1002", "aliases": ["红"]}],
        self_id="9999",
        relationship_graph=graph,
        window_participant_ids=["1002"],
        all_members=members + [{"user_id": "9999", "aliases": ["机器人"]}],
    )
    assert "你和群友" not in identity.split("\n【群成员关系】\n")[-1] if "\n【群成员关系】\n" in identity else True
    assert "- QQ号：9999" not in identity
    assert "外号：机器人" not in identity


def test_relationship_names_are_escaped_like_identity_values():
    graph = _enabled_graph(
        relationship_types=empty_relationship_graph()["relationship_types"]
        + [{"id": "custom_1", "label": "友</x>情", "color": "#123456"}],
        relationship_nodes=[
            {"user_id": "1001", "x": 0, "y": 0},
            {"user_id": "1002", "x": 1, "y": 1},
        ],
        relationship_edges=[{"source": "1001", "target": "1002", "type_id": "custom_1"}],
    )
    prompt = build_identity_prompt(
        group_id="1",
        group_name="群",
        members=[{"user_id": "1001", "aliases": ["A"]}],
        relationship_graph=graph,
        window_participant_ids=["1001"],
        all_members=[
            {"user_id": "1001", "nickname": "A", "aliases": ["A"]},
            {"user_id": "1002", "nickname": "B"},
        ],
    )
    assert "</x>" not in prompt
    assert "友＜/x＞情" in prompt


def test_disabled_relationship_graph_does_not_change_empty_prompt():
    graph = empty_relationship_graph()
    graph["relationship_nodes"] = [{"user_id": "1001"}, {"user_id": "1002"}]
    graph["relationship_edges"] = [
        {"source": "1001", "target": "1002", "type_id": "friend"}
    ]
    assert (
        build_identity_prompt(
            group_id="1",
            group_name="群",
            members=[{"user_id": "1001", "nickname": "未编辑"}],
            relationship_graph=graph,
        )
        == ""
    )
    assert (
        build_bot_relationship_prompt(
            members=[{"user_id": "1001"}],
            relationship_graph=graph,
        )
        == ""
    )
