import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from astrbot_plugin_group_member_context import main as plugin_module

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
    ):
        self.group_id = group_id
        self.sender_id = sender_id
        self.message_text = message_text
        self.mentioned_user_ids = list(mentioned_user_ids or [])
        self._extras = {}

    def get_group_id(self):
        return self.group_id

    def get_sender_id(self):
        return self.sender_id

    def get_sender_name(self):
        return f"sender-{self.sender_id}"

    def get_message_str(self):
        return self.message_text

    def get_messages(self):
        return [SimpleNamespace(qq=user_id) for user_id in self.mentioned_user_ids]

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


def response_json(response):
    return json.loads(response.body.decode("utf-8"))


def latest_llm_report(logger):
    call = logger.info.call_args
    assert call is not None
    assert call.args[0] == "%s %s"
    assert call.args[1] == plugin_module.LLM_INJECTION_LOG_MARKER
    return json.loads(call.args[2])


@pytest.mark.asyncio
async def test_webui_can_read_and_save_shared_plugin_config(monkeypatch):
    config = FakePluginConfig(
        message_window_size=18,
        log_detail="摘要",
    )
    plugin = plugin_module.Main(FakeContext(), config=config)

    current = response_json(await plugin.get_plugin_config())
    assert current == {
        "message_window_size": 18,
        "log_detail": "摘要",
    }

    monkeypatch.setattr(
        plugin_module,
        "request",
        FakeRequest(
            body={
                "message_window_size": 48,
                "log_detail": "全部",
            }
        ),
    )
    saved = response_json(await plugin.save_plugin_config())

    assert saved == {
        "saved": True,
        "message_window_size": 48,
        "log_detail": "全部",
    }
    assert config == {
        "message_window_size": 48,
        "log_detail": "全部",
    }
    assert config.saved_values == [
        {
            "message_window_size": 48,
            "log_detail": "全部",
        }
    ]
    assert plugin._configured_message_window_size() == 48
    assert plugin._configured_log_detail() == plugin_module.LOG_DETAIL_FULL


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
                "message_window_size": 20,
            }
        ),
    )
    saved = response_json(await plugin.save_profile())
    assert saved["saved"] is True
    assert saved["custom_identity_fields"] == ["游戏名"]
    assert saved["usage_rules"] == "回答技术问题时先给结论。"
    assert saved["usage_rules_customized"] is True
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
