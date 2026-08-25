import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from astrbot_plugin_group_member_context import main as plugin_module
from jinja2 import Template
from PIL import Image, ImageDraw

from astrbot.api.message_components import At, Plain
from astrbot.api.platform import MessageType


class FakeClient:
    def __init__(self):
        self.member_payload = [
            {
                "user_id": 2001,
                "nickname": "A",
                "card": "A的名片",
                "role": "owner",
                "title": "群头衔",
            }
        ]

    async def call_action(self, action, **params):
        if action == "get_group_list":
            return [{"group_id": 1001, "group_name": "研发群"}]
        if action == "get_group_member_list":
            assert params == {"group_id": 1001}
            return self.member_payload
        if action == "get_group_member_info":
            user_id = str(params["user_id"])
            for member in self.member_payload:
                if str(member["user_id"]) == user_id:
                    return member
            raise RuntimeError("member not found")
        if action == "get_group_info":
            return {"group_id": 1001, "group_name": "研发群"}
        raise AssertionError(f"unexpected action: {action}")


class FakePlatform:
    def __init__(self):
        self.client = FakeClient()

    def meta(self):
        return SimpleNamespace(id="bot-a", name="aiocqhttp")

    def get_client(self):
        return self.client


class FakeContext:
    def __init__(self):
        self.platform_manager = SimpleNamespace(platform_insts=[FakePlatform()])
        self.registered_web_apis = []

    def register_web_api(self, *args):
        self.registered_web_apis.append(args)


class FakeRequest:
    def __init__(self, *, query=None, body=None):
        self.query = query or {}
        self.body = body

    async def json(self, default=None):
        return self.body if self.body is not None else default


class FakePluginConfig(dict):
    def __init__(self, **values):
        super().__init__(values)
        self.saved_values = []

    async def save_config_async(self, replace_config=None):
        if replace_config:
            self.update(replace_config)
            self.saved_values.append(dict(replace_config))
        return True


class FakeEvent:
    def __init__(
        self,
        group_id,
        sender_id="2001",
        message_text="",
        mentioned_user_ids=None,
        message_components=None,
        sender_role="member",
    ):
        self.group_id = group_id
        self.sender_id = sender_id
        self.message_text = message_text
        self.mentioned_user_ids = list(mentioned_user_ids or [])
        self.message_components = message_components
        self._extras = {}
        self.message_obj = SimpleNamespace(
            raw_message={"sender": {"role": sender_role}}
        )

    def get_group_id(self):
        return self.group_id

    def get_sender_id(self):
        return self.sender_id

    def get_sender_name(self):
        return f"sender-{self.sender_id}"

    def get_message_str(self):
        return self.message_text

    def get_messages(self):
        if self.message_components is not None:
            return self.message_components
        return [SimpleNamespace(qq=user_id) for user_id in self.mentioned_user_ids]

    def get_self_id(self):
        return "9999"

    def get_message_type(self):
        return MessageType.GROUP_MESSAGE

    def get_platform_id(self):
        return "bot-a"

    def get_platform_name(self):
        return "aiocqhttp"

    def set_extra(self, key, value):
        self._extras[key] = value

    def get_extra(self, key=None, default=None):
        if key is None:
            return self._extras
        return self._extras.get(key, default)

    def plain_result(self, text):
        return SimpleNamespace(kind="plain", text=text)

    def image_result(self, image):
        return SimpleNamespace(kind="image", image=image)


def response_json(response):
    return json.loads(response.body.decode("utf-8"))


def latest_llm_report(logger):
    call = logger.info.call_args
    assert call is not None
    assert call.args[0] == "%s %s"
    assert call.args[1] == plugin_module.LLM_INJECTION_LOG_MARKER
    return json.loads(call.args[2])


async def collect_results(generator):
    return [result async for result in generator]


def test_identity_card_template_renders_field_values():
    html = Template(plugin_module.IDENTITY_CARD_TEMPLATE).render(
        user_id="2002",
        display_name="A",
        avatar_data_url="data:image/png;base64,YQ==",
        avatar_text="A",
        fields=[{"label": "游戏名", "values": ["Tony"]}],
    )
    assert "游戏名" in html
    assert "Tony" in html
    assert "data:image/png;base64,YQ==" in html


def test_rendered_card_crop_removes_default_viewport_whitespace(tmp_path):
    source = tmp_path / "rendered.png"
    rendered = Image.new("RGB", (760, 720), (239, 239, 232))
    draw = ImageDraw.Draw(rendered)
    draw.rectangle((30, 30, 729, 346), fill=(248, 248, 242))
    rendered.save(source)
    plugin = plugin_module.Main(FakeContext())

    cropped_path = plugin._crop_rendered_card_image(str(source))

    assert cropped_path.endswith("_cropped.png")
    assert not source.exists()
    with Image.open(cropped_path) as cropped:
        assert cropped.size == (760, 377)


def test_help_card_separates_command_formats_from_examples():
    html = Template(plugin_module.HELP_CARD_TEMPLATE).render()

    assert "普通成员命令" in html
    assert "管理员命令" in html
    assert "使用示例" in html
    assert "/群身份 add &lt;@群成员/QQ号&gt;" in html
    assert "/群身份 add @小明 游戏名=Tony Stark" in html


def test_tag_commands_are_registered_under_group_identity():
    root = plugin_module.Main.group_identity.parent_group
    tag_group = next(
        item
        for item in root.sub_command_filters
        if getattr(item, "group_name", "") == "tag"
    )

    assert {item.command_name for item in tag_group.sub_command_filters} == {
        "add",
        "remove",
    }


def test_native_config_keeps_group_policy_out_of_astrbot_config_page():
    schema_path = Path(plugin_module.__file__).with_name("_conf_schema.json")
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    assert "admin_command_whitelist" not in schema
    assert "admin_command_blacklist" not in schema
    assert "allow_members_admin_commands" not in schema
    assert (
        "更多配置项请通过插件 Web UI 进行配置"
        in schema["avatar_preview_enabled"]["hint"]
    )


@pytest.mark.asyncio
async def test_legacy_global_admin_policy_migrates_to_existing_groups_once():
    plugin = plugin_module.Main(
        FakeContext(),
        config={
            "admin_command_whitelist": ["2001"],
            "admin_command_blacklist": ["2002"],
            "allow_members_admin_commands": True,
        },
    )
    plugin.get_kv_data = AsyncMock(
        return_value={
            "sessions": {
                "bot-a:GroupMessage:1001": {
                    "platform_id": "bot-a",
                    "group_id": "1001",
                    "members": [],
                }
            }
        }
    )
    plugin.put_kv_data = AsyncMock()

    await plugin.initialize()

    profile = plugin._store["sessions"]["bot-a:GroupMessage:1001"]
    assert profile["admin_command_whitelist"] == ["2001"]
    assert profile["admin_command_blacklist"] == ["2002"]
    assert profile["allow_members_admin_commands"] is True
    assert plugin._store["admin_policy_migrated"] is True
    plugin.put_kv_data.assert_awaited_once()


@pytest.mark.asyncio
async def test_webui_can_read_and_save_shared_plugin_config(monkeypatch):
    config = FakePluginConfig(
        message_window_size=18,
        log_detail="摘要",
        avatar_preview_enabled=False,
    )
    plugin = plugin_module.Main(FakeContext(), config=config)

    current = response_json(await plugin.get_plugin_config())
    assert current == {
        "message_window_size": 18,
        "log_detail": "摘要",
        "avatar_preview_enabled": False,
    }

    monkeypatch.setattr(
        plugin_module,
        "request",
        FakeRequest(
            body={
                "message_window_size": 48,
                "log_detail": "全部",
                "avatar_preview_enabled": True,
            }
        ),
    )
    saved = response_json(await plugin.save_plugin_config())

    assert saved == {
        "saved": True,
        "message_window_size": 48,
        "log_detail": "全部",
        "avatar_preview_enabled": True,
    }
    assert config == {
        "message_window_size": 48,
        "log_detail": "全部",
        "avatar_preview_enabled": True,
    }
    assert config.saved_values == [
        {
            "message_window_size": 48,
            "log_detail": "全部",
            "avatar_preview_enabled": True,
        }
    ]
    assert plugin._configured_message_window_size() == 48
    assert plugin._configured_log_detail() == plugin_module.LOG_DETAIL_FULL
    assert plugin._configured_avatar_preview_enabled() is True


@pytest.mark.asyncio
async def test_avatar_preview_is_disabled_by_default_and_skips_network_checks():
    plugin = plugin_module.Main(FakeContext(), config={})
    plugin._check_avatar_revisions = AsyncMock()

    current = response_json(await plugin.get_plugin_config())
    result = response_json(await plugin.check_avatar_updates())

    assert current["avatar_preview_enabled"] is False
    assert result == {"enabled": False, "checked_count": 0, "avatars": []}
    plugin._check_avatar_revisions.assert_not_awaited()


@pytest.mark.asyncio
async def test_avatar_check_validates_deduplicates_and_returns_stable_revisions(
    monkeypatch,
):
    plugin = plugin_module.Main(
        FakeContext(),
        config={"avatar_preview_enabled": True},
    )
    plugin._check_avatar_revisions = AsyncMock(
        return_value=[
            {"user_id": "2001", "available": True, "revision": "revision-a"},
            {"user_id": "2002", "available": False, "revision": ""},
        ]
    )
    monkeypatch.setattr(
        plugin_module,
        "request",
        FakeRequest(body={"user_ids": [2001, "2001", "invalid", "2002"]}),
    )

    result = response_json(await plugin.check_avatar_updates())

    assert result == {
        "enabled": True,
        "checked_count": 2,
        "avatars": [
            {"user_id": "2001", "available": True, "revision": "revision-a"},
            {"user_id": "2002", "available": False, "revision": ""},
        ],
    }
    plugin._check_avatar_revisions.assert_awaited_once_with(["2001", "2002"])


def test_avatar_revision_prefers_standard_cache_validators():
    etag_revision = plugin_module.Main._avatar_revision_from_headers(
        {"ETag": '"avatar-v2"', "Last-Modified": "yesterday"}
    )
    modified_revision = plugin_module.Main._avatar_revision_from_headers(
        {"Last-Modified": "yesterday"}
    )

    assert len(etag_revision) == 16
    assert len(modified_revision) == 16
    assert etag_revision != modified_revision
    assert plugin_module.Main._avatar_revision_from_headers({}) == ""


@pytest.mark.asyncio
async def test_page_flow_and_exact_session_injection(monkeypatch):
    plugin = plugin_module.Main(FakeContext())
    plugin.get_kv_data = AsyncMock(return_value={})
    plugin.put_kv_data = AsyncMock()
    await plugin.initialize()

    groups = response_json(await plugin.list_groups())
    assert groups["groups"][0]["session_key"] == "bot-a:GroupMessage:1001"

    monkeypatch.setattr(
        plugin_module,
        "request",
        FakeRequest(query={"platform_id": "bot-a", "group_id": "1001"}),
    )
    imported = response_json(await plugin.list_members())
    assert imported["members"][0]["nickname"] == "A"

    monkeypatch.setattr(
        plugin_module,
        "request",
        FakeRequest(
            body={
                "platform_id": "bot-a",
                "group_id": "1001",
                "group_name": "研发群",
                "custom_identity_fields": ["游戏名"],
                "members": [
                    {
                        "user_id": "2001",
                        "nickname": "A",
                        "aliases": ["Tony"],
                        "real_names": ["Tony Wang"],
                        "nicknames": ["老王"],
                        "custom_fields": {"游戏名": ["TonyGame"]},
                        "note": "项目负责人",
                    },
                ],
                "usage_rules": "回答技术问题时先给结论。",
                "admin_command_whitelist": ["2001"],
                "admin_command_blacklist": ["2002"],
                "allow_members_admin_commands": True,
                "message_window_size": 20,
            }
        ),
    )
    saved = response_json(await plugin.save_profile())
    assert saved["saved"] is True
    assert saved["custom_identity_fields"] == ["游戏名"]
    assert saved["usage_rules"] == "回答技术问题时先给结论。"
    assert saved["usage_rules_customized"] is True
    assert saved["admin_command_whitelist"] == ["2001"]
    assert saved["admin_command_blacklist"] == ["2002"]
    assert saved["allow_members_admin_commands"] is True
    plugin.put_kv_data.assert_awaited_once()

    plugin._find_aiocqhttp_platform("bot-a").get_client().member_payload = [
        {
            "user_id": 2001,
            "nickname": "A的新昵称",
            "card": "A的新群名片",
            "role": "member",
            "title": "",
        }
    ]
    monkeypatch.setattr(
        plugin_module,
        "request",
        FakeRequest(query={"platform_id": "bot-a", "group_id": "1001"}),
    )
    refreshed = response_json(await plugin.list_members())
    refreshed_member = refreshed["members"][0]
    assert refreshed_member["nickname"] == "A的新昵称"
    assert refreshed_member["card"] == "A的新群名片"
    assert refreshed_member["aliases"] == ["Tony"]
    assert refreshed_member["real_names"] == ["Tony Wang"]
    assert refreshed_member["nicknames"] == ["老王"]
    assert refreshed_member["custom_fields"] == {"游戏名": ["TonyGame"]}
    assert refreshed_member["note"] == "项目负责人"
    assert refreshed["usage_rules"] == "回答技术问题时先给结论。"
    assert refreshed["admin_command_whitelist"] == ["2001"]
    assert refreshed["admin_command_blacklist"] == ["2002"]
    assert refreshed["allow_members_admin_commands"] is True
    assert refreshed["default_usage_rules"] == plugin_module.DEFAULT_USAGE_RULES

    matching_request = SimpleNamespace(extra_user_content_parts=[])
    await plugin.inject_member_context(FakeEvent("1001"), matching_request)
    assert len(matching_request.extra_user_content_parts) == 1
    injected = matching_request.extra_user_content_parts[0]
    assert "Tony" in injected.text
    assert "外号：Tony" in injected.text
    assert "真名：Tony Wang" in injected.text
    assert "昵称：老王" in injected.text
    assert "游戏名：TonyGame" in injected.text
    assert "【使用规则】\n回答技术问题时先给结论。" in injected.text
    assert "【本群自定义 Prompt】" not in injected.text
    assert "管理员" not in injected.text
    assert "owner" not in injected.text
    assert "群头衔" not in injected.text
    assert injected.model_dump_for_context()["_no_save"] is True

    other_group_request = SimpleNamespace(extra_user_content_parts=[])
    await plugin.inject_member_context(FakeEvent("1002"), other_group_request)
    assert other_group_request.extra_user_content_parts == []


@pytest.mark.asyncio
async def test_reset_profile_clears_current_group_identity_data(monkeypatch):
    plugin = plugin_module.Main(FakeContext(), config={"message_window_size": 30})
    plugin.get_kv_data = AsyncMock(return_value={})
    plugin.put_kv_data = AsyncMock()
    await plugin.initialize()

    monkeypatch.setattr(
        plugin_module,
        "request",
        FakeRequest(
            body={
                "platform_id": "bot-a",
                "group_id": "1001",
                "group_name": "研发群",
                "custom_identity_fields": ["游戏名"],
                "members": [
                    {
                        "user_id": "2001",
                        "nickname": "A",
                        "card": "群名片 A",
                        "role": "owner",
                        "title": "群头衔",
                        "aliases": ["Tony"],
                        "real_names": ["Tony Wang"],
                        "nicknames": ["老王"],
                        "custom_fields": {"游戏名": ["TonyGame"]},
                        "note": "项目负责人",
                    },
                    {"user_id": "2002", "nickname": "未配置成员"},
                ],
                "usage_rules": "只回答技术问题。",
            }
        ),
    )
    await plugin.save_profile()

    monkeypatch.setattr(
        plugin_module,
        "request",
        FakeRequest(body={"platform_id": "bot-a", "group_id": "1001"}),
    )
    reset = response_json(await plugin.reset_profile())

    assert reset["reset"] is True
    assert reset["member_count"] == 2
    assert reset["configured_member_count"] == 0
    assert reset["usage_rules_customized"] is False
    assert reset["usage_rules"] == plugin_module.DEFAULT_USAGE_RULES
    assert reset["custom_identity_fields"] == ["游戏名"]
    assert reset["message_window_size"] == 30
    assert reset["members"][0]["nickname"] == "A"
    assert reset["members"][0]["card"] == "群名片 A"
    assert reset["members"][0]["role"] == "owner"
    assert reset["members"][0]["aliases"] == []
    assert reset["members"][0]["real_names"] == []
    assert reset["members"][0]["nicknames"] == []
    assert reset["members"][0]["custom_fields"] == {}
    assert reset["members"][0]["note"] == ""
    assert (
        plugin._stored_sessions()["bot-a:GroupMessage:1001"]["usage_rules"]
        == plugin_module.DEFAULT_USAGE_RULES
    )
    assert plugin.put_kv_data.await_count == 2


@pytest.mark.asyncio
async def test_reset_profile_can_initialize_an_unsaved_group_from_page_members(
    monkeypatch,
):
    plugin = plugin_module.Main(FakeContext())
    plugin.get_kv_data = AsyncMock(return_value={})
    plugin.put_kv_data = AsyncMock()
    await plugin.initialize()

    monkeypatch.setattr(
        plugin_module,
        "request",
        FakeRequest(
            body={
                "platform_id": "bot-a",
                "group_id": "1001",
                "group_name": "研发群",
                "members": [
                    {
                        "user_id": "2001",
                        "nickname": "A",
                        "aliases": ["不应保留"],
                    }
                ],
            }
        ),
    )
    reset = response_json(await plugin.reset_profile())

    assert reset["reset"] is True
    assert reset["member_count"] == 1
    assert reset["members"][0]["nickname"] == "A"
    assert reset["members"][0]["aliases"] == []
    assert reset["members"][0]["real_names"] == []
    assert reset["members"][0]["nicknames"] == []
    assert plugin.put_kv_data.await_count == 1


@pytest.mark.asyncio
async def test_dynamic_window_injects_only_recent_speakers(monkeypatch):
    plugin = plugin_module.Main(FakeContext(), config={"message_window_size": 2})
    plugin.get_kv_data = AsyncMock(return_value={})
    plugin.put_kv_data = AsyncMock()
    await plugin.initialize()

    monkeypatch.setattr(
        plugin_module,
        "request",
        FakeRequest(
            body={
                "platform_id": "bot-a",
                "group_id": "1001",
                "group_name": "研发群",
                "message_window_size": 2,
                "members": [
                    {"user_id": "2001", "aliases": ["窗口外成员"]},
                    {"user_id": "2002", "aliases": ["窗口内成员B"]},
                    {"user_id": "2003", "aliases": ["窗口内成员C"]},
                ],
            }
        ),
    )
    await plugin.save_profile()

    first = FakeEvent("1001", "2001")
    second = FakeEvent("1001", "2002")
    current = FakeEvent("1001", "2003")
    await plugin.track_group_message(first)
    await plugin.track_group_message(second)
    await plugin.track_group_message(current)

    request = SimpleNamespace(extra_user_content_parts=[])
    await plugin.inject_member_context(current, request)
    assert len(request.extra_user_content_parts) == 1
    prompt = request.extra_user_content_parts[0].text
    assert "QQ号：2001" not in prompt
    assert "窗口外成员" not in prompt
    assert "QQ号：2002" in prompt
    assert "窗口内成员B" in prompt
    assert "QQ号：2003" in prompt
    assert "窗口内成员C" in prompt


@pytest.mark.asyncio
async def test_dynamic_window_injects_members_mentioned_by_name(monkeypatch):
    plugin = plugin_module.Main(FakeContext(), config={"message_window_size": 3})
    plugin.logger = Mock()
    plugin.get_kv_data = AsyncMock(return_value={})
    plugin.put_kv_data = AsyncMock()
    await plugin.initialize()

    monkeypatch.setattr(
        plugin_module,
        "request",
        FakeRequest(
            body={
                "platform_id": "bot-a",
                "group_id": "1001",
                "group_name": "研发群",
                "message_window_size": 3,
                "members": [
                    {
                        "user_id": "2001",
                        "nickname": "A",
                        "card": "A的群名片",
                        "real_names": ["Tony Wang"],
                        "nicknames": ["老王"],
                    },
                    {
                        "user_id": "2002",
                        "card": "小红的群名片",
                        "aliases": ["小红"],
                    },
                    {"user_id": "2003", "nickname": "未配置成员"},
                ],
            }
        ),
    )
    await plugin.save_profile()

    first = FakeEvent("1001", "2003", "Tony Wang 和小红刚才在讨论")
    second = FakeEvent("1001", "2999", "我也听说老王要来了")
    current = FakeEvent("1001", "2999", "继续说这个项目")
    await plugin.track_group_message(first)
    await plugin.track_group_message(second)
    await plugin.track_group_message(current)

    request = SimpleNamespace(extra_user_content_parts=[])
    await plugin.inject_member_context(current, request)
    assert len(request.extra_user_content_parts) == 1
    prompt = request.extra_user_content_parts[0].text
    assert "QQ号：2001" in prompt
    assert "真名：Tony Wang" in prompt
    assert "昵称：老王" in prompt
    assert "QQ号：2002" in prompt
    assert "外号：小红" in prompt
    assert "QQ号：2003" not in prompt
    assert "消息中提到：" in prompt
    assert "Tony Wang" in prompt
    assert "老王" in prompt

    report = latest_llm_report(plugin.logger)
    assert report["status"] == "injected"
    assert report["reason"] == "matched_members"
    assert report["window_message_count"] == 3
    assert report["window_limit"] == 3
    assert report["window_speaker_ids"] == ["2003", "2999"]
    assert report["injected_member_ids"] == ["2001", "2002"]
    assert report["match_reasons"]["2001"]["speaker"] is False
    assert set(report["match_reasons"]["2001"]["mentioned_as"]) >= {
        "Tony Wang",
        "老王",
    }
    assert report["prompt_injected"] is True
    assert report["prompt_length"] > 0
    assert "prompt" not in report

    await plugin.inject_member_context(current, request)
    duplicate_report = latest_llm_report(plugin.logger)
    assert duplicate_report["status"] == "duplicate"
    assert duplicate_report["reason"] == "prompt_marker_already_present"
    assert duplicate_report["prompt_injected"] is False
    assert len(request.extra_user_content_parts) == 1


@pytest.mark.asyncio
async def test_dynamic_window_supports_direct_at_member_reference(monkeypatch):
    plugin = plugin_module.Main(FakeContext())
    plugin.get_kv_data = AsyncMock(return_value={})
    plugin.put_kv_data = AsyncMock()
    await plugin.initialize()

    monkeypatch.setattr(
        plugin_module,
        "request",
        FakeRequest(
            body={
                "platform_id": "bot-a",
                "group_id": "1001",
                "members": [
                    {"user_id": "2001", "aliases": ["Tony"]},
                    {"user_id": "2002", "aliases": ["小红"]},
                ],
            }
        ),
    )
    await plugin.save_profile()

    current = FakeEvent(
        "1001",
        "2999",
        "看一下这个人",
        mentioned_user_ids=["2002"],
    )
    await plugin.track_group_message(current)

    request = SimpleNamespace(extra_user_content_parts=[])
    await plugin.inject_member_context(current, request)
    prompt = request.extra_user_content_parts[0].text
    assert "QQ号：2002" in prompt
    assert "@2002" in prompt
    assert "QQ号：2001" not in prompt


@pytest.mark.asyncio
async def test_history_seed_restores_message_mentions_and_skips_bot_rows(monkeypatch):
    plugin = plugin_module.Main(FakeContext())
    plugin.get_kv_data = AsyncMock(return_value={})
    plugin.put_kv_data = AsyncMock()
    await plugin.initialize()

    monkeypatch.setattr(
        plugin_module,
        "request",
        FakeRequest(
            body={
                "platform_id": "bot-a",
                "group_id": "1001",
                "members": [
                    {"user_id": "2001", "real_names": ["Tony"]},
                    {"user_id": "2002", "aliases": ["小红"]},
                ],
            }
        ),
    )
    await plugin.save_profile()
    history_manager = SimpleNamespace(
        get=AsyncMock(
            return_value=[
                SimpleNamespace(
                    id=1,
                    sender_id="2999",
                    content={
                        "type": "user",
                        "message": [{"type": "plain", "text": "Tony来了"}],
                    },
                ),
                SimpleNamespace(
                    id=2,
                    sender_id="bot",
                    content={
                        "type": "bot",
                        "message": [{"type": "plain", "text": "小红来了"}],
                    },
                ),
            ]
        )
    )
    plugin.context.message_history_manager = history_manager

    current = FakeEvent("1001", "2999", "继续聊")
    request = SimpleNamespace(extra_user_content_parts=[])
    await plugin.inject_member_context(current, request)

    prompt = request.extra_user_content_parts[0].text
    assert "QQ号：2001" in prompt
    assert "QQ号：2002" not in prompt
    history_manager.get.assert_awaited_once()


@pytest.mark.asyncio
async def test_llm_injection_report_records_missing_profile(monkeypatch):
    plugin = plugin_module.Main(FakeContext())
    plugin.logger = Mock()
    plugin.get_kv_data = AsyncMock(return_value={})
    plugin.put_kv_data = AsyncMock()
    await plugin.initialize()

    request = SimpleNamespace(extra_user_content_parts=[])
    await plugin.inject_member_context(FakeEvent("1002"), request)

    report = latest_llm_report(plugin.logger)
    assert report["status"] == "skipped"
    assert report["reason"] == "profile_not_found"
    assert report["group_id"] == "1002"
    assert report["prompt_injected"] is False
    assert request.extra_user_content_parts == []


@pytest.mark.asyncio
async def test_full_log_detail_includes_the_complete_injected_prompt(monkeypatch):
    plugin = plugin_module.Main(
        FakeContext(),
        config={"message_window_size": 1, "log_detail": "全部"},
    )
    plugin.logger = Mock()
    plugin.get_kv_data = AsyncMock(return_value={})
    plugin.put_kv_data = AsyncMock()
    await plugin.initialize()

    monkeypatch.setattr(
        plugin_module,
        "request",
        FakeRequest(
            body={
                "platform_id": "bot-a",
                "group_id": "1001",
                "members": [{"user_id": "2001", "aliases": ["Tony"]}],
            }
        ),
    )
    await plugin.save_profile()
    current = FakeEvent("1001", "2001", "你好")
    await plugin.track_group_message(current)
    request = SimpleNamespace(extra_user_content_parts=[])
    await plugin.inject_member_context(current, request)

    report = latest_llm_report(plugin.logger)
    assert report["status"] == "injected"
    assert report["prompt"] == request.extra_user_content_parts[0].text
    assert "【已配置的成员身份映射】" in report["prompt"]


@pytest.mark.asyncio
async def test_group_admin_can_add_group_scoped_custom_identity_with_at_target():
    context = FakeContext()
    context.platform_manager.platform_insts[0].client.member_payload = [
        {"user_id": 2001, "nickname": "管理员", "role": "owner"},
        {"user_id": 2002, "nickname": "A", "card": "A同学", "role": "member"},
    ]
    plugin = plugin_module.Main(context)
    plugin.get_kv_data = AsyncMock(return_value={})
    plugin.put_kv_data = AsyncMock()
    await plugin.initialize()
    event = FakeEvent(
        "1001",
        sender_id="2001",
        sender_role="owner",
        message_components=[
            Plain(text="/群身份 add"),
            At(qq="2002", name="A同学"),
            Plain(text="游戏名=Tony"),
        ],
    )

    results = await collect_results(
        plugin.group_identity_add(event, "@A同学(2002) 游戏名=Tony")
    )

    assert results[0].text == "成功：身份已添加。"
    profile = plugin._store["sessions"]["bot-a:GroupMessage:1001"]
    assert profile["custom_identity_fields"] == ["游戏名"]
    member = next(item for item in profile["members"] if item["user_id"] == "2002")
    assert member["custom_fields"] == {"游戏名": ["Tony"]}


@pytest.mark.asyncio
async def test_group_admin_can_manage_custom_tags_without_deleting_used_data():
    context = FakeContext()
    context.platform_manager.platform_insts[0].client.member_payload = [
        {"user_id": 2001, "nickname": "管理员", "role": "owner"},
    ]
    plugin = plugin_module.Main(context)
    plugin.get_kv_data = AsyncMock(return_value={})
    plugin.put_kv_data = AsyncMock()
    await plugin.initialize()
    event = FakeEvent("1001", sender_id="2001", sender_role="owner")

    added = await collect_results(plugin.group_identity_tag_add(event, "游戏名"))
    assert added[0].text == "成功：身份标签已添加。"

    profile = plugin._store["sessions"]["bot-a:GroupMessage:1001"]
    profile["members"][0]["custom_fields"] = {"游戏名": ["Tony"]}
    refused = await collect_results(plugin.group_identity_tag_remove(event, "游戏名"))
    assert refused[0].text == "失败：该标签仍在使用，请先删除对应身份。"

    profile["members"][0]["custom_fields"]["游戏名"] = []
    removed = await collect_results(plugin.group_identity_tag_remove(event, "游戏名"))
    assert removed[0].text == "成功：身份标签已删除。"
    assert profile["custom_identity_fields"] == []


@pytest.mark.asyncio
async def test_admin_policy_is_isolated_per_group_and_can_allow_members():
    plugin = plugin_module.Main(FakeContext())
    plugin._store["sessions"] = {
        "bot-a:GroupMessage:1001": {
            "allow_members_admin_commands": True,
            "admin_command_whitelist": ["2002"],
            "admin_command_blacklist": [],
        },
        "bot-a:GroupMessage:1002": {
            "allow_members_admin_commands": False,
            "admin_command_whitelist": [],
            "admin_command_blacklist": [],
        },
    }
    platform = plugin._find_aiocqhttp_platform("bot-a")
    event = FakeEvent("1001", sender_id="2002", sender_role="member")

    assert await plugin._admin_command_allowed(event, platform, "1001") is True
    assert await plugin._admin_command_allowed(event, platform, "1002") is False


@pytest.mark.asyncio
async def test_numeric_target_and_self_commands_keep_spaced_default_identity():
    context = FakeContext()
    context.platform_manager.platform_insts[0].client.member_payload = [
        {"user_id": 2001, "nickname": "管理员", "role": "owner"},
        {"user_id": 2002, "nickname": "A", "role": "member"},
    ]
    plugin = plugin_module.Main(context)
    plugin.get_kv_data = AsyncMock(return_value={})
    plugin.put_kv_data = AsyncMock()
    await plugin.initialize()

    admin_event = FakeEvent("1001", sender_id="2001", sender_role="owner")
    added = await collect_results(
        plugin.group_identity_add(admin_event, "2002 Tony Stark")
    )
    removed = await collect_results(
        plugin.group_identity_remove(admin_event, "2002 Tony Stark")
    )

    member_event = FakeEvent("1001", sender_id="2002", sender_role="member")
    self_added = await collect_results(
        plugin.group_identity_me_add(member_event, "Tony Stark")
    )
    self_removed = await collect_results(
        plugin.group_identity_me_remove(member_event, "Tony Stark")
    )

    assert [
        result[0].text for result in (added, removed, self_added, self_removed)
    ] == [
        "成功：身份已添加。",
        "成功：身份已删除。",
        "成功：身份已添加。",
        "成功：身份已删除。",
    ]
    profile = plugin._store["sessions"]["bot-a:GroupMessage:1001"]
    member = next(item for item in profile["members"] if item["user_id"] == "2002")
    assert member["nicknames"] == []


@pytest.mark.asyncio
async def test_admin_command_whitelist_restricts_without_blacklist_override():
    plugin = plugin_module.Main(FakeContext())
    profile = {
        "admin_command_whitelist": ["2999"],
        "admin_command_blacklist": ["2001"],
    }
    plugin._store["sessions"]["bot-a:GroupMessage:1001"] = profile
    platform = plugin._find_aiocqhttp_platform("bot-a")
    event = FakeEvent("1001", sender_id="2001", sender_role="owner")

    assert await plugin._admin_command_allowed(event, platform, "1001") is False

    profile["admin_command_whitelist"] = ["2001"]
    assert await plugin._admin_command_allowed(event, platform, "1001") is True


@pytest.mark.asyncio
async def test_self_service_custom_labels_are_admin_only_and_must_exist():
    context = FakeContext()
    context.platform_manager.platform_insts[0].client.member_payload = [
        {"user_id": 2002, "nickname": "A", "role": "member"},
    ]
    plugin = plugin_module.Main(context)
    plugin.get_kv_data = AsyncMock(return_value={})
    plugin.put_kv_data = AsyncMock()
    await plugin.initialize()
    event = FakeEvent("1001", sender_id="2002", sender_role="member")

    rejected = await collect_results(plugin.group_identity_me_add(event, "游戏名=Tony"))
    assert rejected[0].text == "失败：自定义身份标签仅限管理员使用。"

    profile = plugin._store["sessions"]["bot-a:GroupMessage:1001"]
    profile["custom_identity_fields"] = ["游戏名"]
    still_rejected = await collect_results(
        plugin.group_identity_me_add(event, "游戏名=Tony")
    )
    assert still_rejected[0].text == "失败：自定义身份标签仅限管理员使用。"

    admin_event = FakeEvent("1001", sender_id="2002", sender_role="owner")
    accepted = await collect_results(
        plugin.group_identity_me_add(admin_event, "游戏名=Tony")
    )
    assert accepted[0].text == "成功：身份已添加。"


@pytest.mark.asyncio
async def test_list_command_renders_webui_style_identity_card_without_note():
    context = FakeContext()
    context.platform_manager.platform_insts[0].client.member_payload = [
        {"user_id": 2002, "nickname": "A", "card": "A同学", "role": "member"},
    ]
    plugin = plugin_module.Main(context)
    plugin.get_kv_data = AsyncMock(
        return_value={
            "sessions": {
                "bot-a:GroupMessage:1001": {
                    "platform_id": "bot-a",
                    "group_id": "1001",
                    "group_name": "研发群",
                    "custom_identity_fields": ["游戏名"],
                    "members": [
                        {
                            "user_id": "2002",
                            "nickname": "A",
                            "card": "A同学",
                            "nicknames": ["Tony"],
                            "custom_fields": {"游戏名": ["ValorantTony"]},
                            "note": "不应公开显示",
                        }
                    ],
                }
            }
        }
    )
    plugin.put_kv_data = AsyncMock()
    plugin.html_render = AsyncMock(return_value="identity-card.png")
    plugin._download_identity_avatar = AsyncMock(
        return_value="data:image/png;base64,YQ=="
    )
    await plugin.initialize()
    event = FakeEvent("1001", sender_id="2002")

    results = await collect_results(plugin.group_identity_list(event))

    assert results[0].kind == "image"
    assert results[0].image == "identity-card.png"
    render_data = plugin.html_render.await_args.args[1]
    assert render_data["fields"] == [
        {"label": "昵称", "values": ["Tony"]},
        {"label": "游戏名", "values": ["ValorantTony"]},
    ]
    assert "note" not in render_data
    assert "group_name" not in render_data
    assert render_data["display_name"] == "A同学"
    assert render_data["avatar_data_url"] == "data:image/png;base64,YQ=="
    assert plugin.html_render.await_args.kwargs["return_url"] is False


@pytest.mark.asyncio
async def test_help_command_renders_image_card():
    plugin = plugin_module.Main(FakeContext())
    plugin.html_render = AsyncMock(return_value="help-card.png")

    results = await collect_results(plugin.group_identity_help(FakeEvent("1001")))

    assert results[0].kind == "image"
    assert results[0].image == "help-card.png"
    assert plugin.html_render.await_args.args[0] == plugin_module.HELP_CARD_TEMPLATE
    assert plugin.html_render.await_args.kwargs["return_url"] is False


@pytest.mark.asyncio
async def test_disabled_group_skips_identity_injection():
    plugin = plugin_module.Main(FakeContext())
    plugin.logger = Mock()
    plugin.get_kv_data = AsyncMock(
        return_value={
            "sessions": {
                "bot-a:GroupMessage:1001": {
                    "platform_id": "bot-a",
                    "group_id": "1001",
                    "injection_enabled": False,
                    "members": [{"user_id": "2001", "aliases": ["Tony"]}],
                }
            }
        }
    )
    await plugin.initialize()
    request = SimpleNamespace(extra_user_content_parts=[])

    await plugin.inject_member_context(FakeEvent("1001", "2001"), request)

    assert request.extra_user_content_parts == []
    assert latest_llm_report(plugin.logger)["reason"] == "group_injection_disabled"


@pytest.mark.asyncio
async def test_webui_stale_revision_cannot_overwrite_command_changes(monkeypatch):
    plugin = plugin_module.Main(FakeContext())
    plugin.get_kv_data = AsyncMock(return_value={})
    plugin.put_kv_data = AsyncMock()
    await plugin.initialize()
    payload = {
        "platform_id": "bot-a",
        "group_id": "1001",
        "members": [{"user_id": "2001", "nicknames": ["Tony"]}],
        "revision": 0,
    }
    monkeypatch.setattr(plugin_module, "request", FakeRequest(body=payload))
    first = response_json(await plugin.save_profile())
    assert first["revision"] == 1

    plugin._store["sessions"]["bot-a:GroupMessage:1001"]["revision"] = 2
    monkeypatch.setattr(plugin_module, "request", FakeRequest(body=payload))
    stale_response = await plugin.save_profile()

    assert stale_response.status_code == 409
    assert "请刷新后再保存" in response_json(stale_response)["message"]
