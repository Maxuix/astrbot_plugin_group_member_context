"""Per-QQ-group member identity context plugin for AstrBot."""

from __future__ import annotations

import asyncio
import base64
import copy
import hashlib
import inspect
import json
import re
from collections import deque
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiohttp
from PIL import Image, ImageChops

from astrbot.api import AstrBotConfig
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import At, Plain
from astrbot.api.platform import MessageType
from astrbot.api.provider import ProviderRequest
from astrbot.api.star import Context, Star
from astrbot.api.web import error_response, json_response, request
from astrbot.core.agent.message import TextPart
from astrbot.core.star.filter.command import GreedyStr

from .identity_card import IDENTITY_CARD_TEMPLATE

from .member_context import (
    BOT_RELATIONSHIP_MARKER,
    DEFAULT_MESSAGE_WINDOW_SIZE,
    DEFAULT_USAGE_RULES,
    LOG_DETAIL_FULL,
    MAX_ALIAS_COUNT,
    MAX_CUSTOM_IDENTITY_FIELD_COUNT,
    MAX_CUSTOM_IDENTITY_FIELD_LENGTH,
    MAX_IDENTITY_VALUE_COUNT,
    MAX_TEXT_LENGTH,
    MAX_MESSAGE_WINDOW_SIZE,
    STORE_VERSION,
    build_bot_relationship_prompt,
    build_identity_prompt,
    build_session_key,
    clean_text,
    clear_member_identity,
    collect_window_participant_ids,
    empty_relationship_graph,
    has_custom_identity,
    merge_remote_members,
    normalize_custom_identity_fields,
    normalize_enabled,
    normalize_id,
    normalize_log_detail,
    normalize_member_list,
    normalize_message_window_size,
    normalize_match_text,
    normalize_member,
    normalize_qq_id_list,
    normalize_relationship_graph,
    normalize_revision,
    normalize_store,
    normalize_usage_rules,
    relationship_graph_is_empty,
    select_members_for_window,
    select_relationships_for_window,
)

PLUGIN_NAME = "astrbot_plugin_group_member_context"
STORE_KEY = "group_member_profiles"
PROMPT_MARKER = "<group_member_identity_context>"
BOT_PROMPT_MARKER = BOT_RELATIONSHIP_MARKER
LLM_INJECTION_LOG_MARKER = "astrbot_plugin_group_member_context.llm_injection"
WINDOW_RECORDED_EXTRA = "_group_member_context_window_recorded"
MAX_WINDOW_MESSAGE_TEXT_LENGTH = 4000
AVATAR_CDN_URL = "https://q1.qlogo.cn/g"
AVATAR_SIZE = 100
MAX_AVATAR_CHECK_COUNT = 100
AVATAR_CHECK_CONCURRENCY = 8
AVATAR_REQUEST_TIMEOUT_SECONDS = 5
MAX_IDENTITY_CARD_AVATAR_BYTES = 2 * 1024 * 1024
ADMIN_COMMAND_WHITELIST_KEY = "admin_command_whitelist"
ADMIN_COMMAND_BLACKLIST_KEY = "admin_command_blacklist"
ALLOW_MEMBER_ADMIN_COMMANDS_KEY = "allow_members_admin_commands"
HELP_CARD_IMAGE_PATH = (
    Path(__file__).resolve().parent / "assets" / "group_identity_help.png"
)
WRITABLE_STANDARD_IDENTITY_FIELDS = {
    "昵称": "nicknames",
    "外号": "aliases",
    "真名": "real_names",
}
RESERVED_IDENTITY_FIELDS = {
    "QQ号",
    "平台昵称",
    "群名片",
    "群角色",
    "群头衔",
    "备注",
    "补充说明",
}


class Main(Star):
    """Maintain identity mappings and inject them into the matching group only."""

    def __init__(
        self,
        context: Context,
        config: AstrBotConfig | None = None,
    ) -> None:
        super().__init__(context)
        self.config = config if config is not None else {}
        if not getattr(self, "plugin_id", None):
            self.plugin_id = f"local/{PLUGIN_NAME}"
        self._config_lock = asyncio.Lock()
        self._store_lock = asyncio.Lock()
        self._store_loaded = False
        self._store: dict[str, Any] = {
            "version": STORE_VERSION,
            "admin_policy_migrated": False,
            "sessions": {},
        }
        self._window_lock = asyncio.Lock()
        self._recent_messages: dict[str, deque[dict[str, Any]]] = {}
        self._window_seeded: set[str] = set()

        prefix = f"/{PLUGIN_NAME}"
        context.register_web_api(
            f"{prefix}/groups",
            self.list_groups,
            ["GET"],
            "List connected OneBot QQ groups",
        )
        context.register_web_api(
            f"{prefix}/members",
            self.list_members,
            ["GET"],
            "Refresh the latest members from a QQ group",
        )
        context.register_web_api(
            f"{prefix}/profile/status",
            self.profile_status,
            ["GET"],
            "Read a group profile revision without refreshing OneBot members",
        )
        context.register_web_api(
            f"{prefix}/config",
            self.get_plugin_config,
            ["GET"],
            "Read the shared plugin configuration",
        )
        context.register_web_api(
            f"{prefix}/config",
            self.save_plugin_config,
            ["POST"],
            "Save the shared plugin configuration",
        )
        context.register_web_api(
            f"{prefix}/avatars/check",
            self.check_avatar_updates,
            ["POST"],
            "Check QQ avatar revisions without downloading image bodies",
        )
        context.register_web_api(
            f"{prefix}/profiles",
            self.save_profile,
            ["POST"],
            "Save a QQ group member identity profile",
        )
        context.register_web_api(
            f"{prefix}/reset",
            self.reset_profile,
            ["POST"],
            "Reset a QQ group member identity profile",
        )
        context.register_web_api(
            f"{prefix}/preview",
            self.preview_profile,
            ["POST"],
            "Preview the generated group identity prompt",
        )

    async def initialize(self) -> None:
        try:
            await self._ensure_store_loaded()
        except Exception:
            self.logger.exception("加载群成员身份资料失败，将在下次请求时重试。")

    async def _ensure_store_loaded(self) -> None:
        if self._store_loaded:
            return
        async with self._store_lock:
            if self._store_loaded:
                return
            raw = await self.get_kv_data(STORE_KEY, {})
            self._store = normalize_store(raw)
            await self._migrate_legacy_admin_policy()
            self._store_loaded = True

    async def _persist_store(self) -> None:
        await self.put_kv_data(STORE_KEY, self._store)

    async def _migrate_legacy_admin_policy(self) -> None:
        """Copy the former global command policy into every existing group once."""

        if self._store.get("admin_policy_migrated") is True:
            return
        whitelist = self._configured_admin_command_whitelist()
        blacklist = self._configured_admin_command_blacklist()
        allow_members = self._configured_allow_member_admin_commands()
        sessions = self._stored_sessions()
        for profile in sessions.values():
            if not isinstance(profile, dict):
                continue
            profile[ADMIN_COMMAND_WHITELIST_KEY] = list(whitelist)
            profile[ADMIN_COMMAND_BLACKLIST_KEY] = list(blacklist)
            profile[ALLOW_MEMBER_ADMIN_COMMANDS_KEY] = allow_members
        self._store["admin_policy_migrated"] = True
        if sessions or whitelist or blacklist or allow_members:
            await self._persist_store()

    @staticmethod
    def _platform_id(platform: object) -> str:
        try:
            metadata = platform.meta()
        except Exception:
            return ""
        platform_id = getattr(metadata, "id", None)
        if not platform_id:
            config = getattr(platform, "config", {})
            platform_id = config.get("id", "") if isinstance(config, Mapping) else ""
        return clean_text(platform_id, max_length=128)

    def _aiocqhttp_platforms(self) -> list[tuple[str, object]]:
        manager = getattr(self.context, "platform_manager", None)
        platforms = getattr(manager, "platform_insts", [])
        result: list[tuple[str, object]] = []
        for platform in platforms:
            try:
                metadata = platform.meta()
            except Exception:
                continue
            if getattr(metadata, "name", "") != "aiocqhttp":
                continue
            platform_id = self._platform_id(platform)
            if platform_id:
                result.append((platform_id, platform))
        return result

    def _find_aiocqhttp_platform(self, platform_id: str) -> object | None:
        for current_id, platform in self._aiocqhttp_platforms():
            if current_id == platform_id:
                return platform
        return None

    @staticmethod
    def _extract_list(payload: object) -> list[Mapping[str, Any]] | None:
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, Mapping)]
        if isinstance(payload, Mapping) and isinstance(payload.get("data"), list):
            return [item for item in payload["data"] if isinstance(item, Mapping)]
        return None

    @staticmethod
    async def _call_onebot_action(
        platform: object,
        action: str,
        **params: Any,
    ) -> object:
        get_client = getattr(platform, "get_client", None)
        if not callable(get_client):
            raise RuntimeError("当前平台没有可用的 OneBot 客户端")
        client = get_client()
        call_action = getattr(client, "call_action", None)
        if not callable(call_action):
            raise RuntimeError("当前平台客户端不支持 OneBot Action")
        result = call_action(action, **params)
        if inspect.isawaitable(result):
            return await result
        return result

    def _stored_sessions(self) -> dict[str, Any]:
        sessions = self._store.get("sessions")
        if not isinstance(sessions, dict):
            sessions = {}
            self._store["sessions"] = sessions
        return sessions

    @staticmethod
    def _profile_custom_identity_fields(profile: Mapping[str, Any]) -> list[str]:
        return normalize_custom_identity_fields(
            profile.get("custom_identity_fields", [])
        )

    def _configured_message_window_size(self) -> int:
        configured_value = (
            self.config.get("message_window_size", DEFAULT_MESSAGE_WINDOW_SIZE)
            if isinstance(self.config, Mapping)
            else DEFAULT_MESSAGE_WINDOW_SIZE
        )
        return normalize_message_window_size(configured_value)

    def _configured_log_detail(self) -> str:
        configured_value = (
            self.config.get("log_detail", "摘要")
            if isinstance(self.config, Mapping)
            else "摘要"
        )
        return normalize_log_detail(configured_value)

    @staticmethod
    def _normalize_config_bool(value: object) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value == 1
        if isinstance(value, str):
            return value.strip().casefold() in {
                "1",
                "true",
                "yes",
                "on",
                "开启",
                "启用",
            }
        return False

    def _configured_avatar_preview_enabled(self) -> bool:
        configured_value = (
            self.config.get("avatar_preview_enabled", False)
            if isinstance(self.config, Mapping)
            else False
        )
        return self._normalize_config_bool(configured_value)

    @staticmethod
    def _normalize_qq_id_list(value: object) -> list[str]:
        return normalize_qq_id_list(value)

    def _configured_admin_command_whitelist(self) -> list[str]:
        value = (
            self.config.get(ADMIN_COMMAND_WHITELIST_KEY, [])
            if isinstance(self.config, Mapping)
            else []
        )
        return self._normalize_qq_id_list(value)

    def _configured_admin_command_blacklist(self) -> list[str]:
        value = (
            self.config.get(ADMIN_COMMAND_BLACKLIST_KEY, [])
            if isinstance(self.config, Mapping)
            else []
        )
        return self._normalize_qq_id_list(value)

    def _configured_allow_member_admin_commands(self) -> bool:
        value = (
            self.config.get(ALLOW_MEMBER_ADMIN_COMMANDS_KEY, False)
            if isinstance(self.config, Mapping)
            else False
        )
        return self._normalize_config_bool(value)

    def _plugin_config_snapshot(self) -> dict[str, Any]:
        """Return config values in the same labels shown by AstrBot's schema."""

        log_detail = (
            "全部" if self._configured_log_detail() == LOG_DETAIL_FULL else "摘要"
        )
        return {
            "message_window_size": self._configured_message_window_size(),
            "log_detail": log_detail,
            "avatar_preview_enabled": self._configured_avatar_preview_enabled(),
        }

    async def _persist_plugin_config(self, values: Mapping[str, Any]) -> None:
        """Persist plugin config without blocking the event loop when supported."""

        save_async = getattr(self.config, "save_config_async", None)
        if callable(save_async):
            result = save_async(dict(values))
            if inspect.isawaitable(result):
                await result
            return

        save_sync = getattr(self.config, "save_config", None)
        if callable(save_sync):
            result = save_sync(dict(values))
            if inspect.isawaitable(result):
                await result
            return

        raise RuntimeError("当前 AstrBot 配置对象不支持保存插件配置。")

    def _log_llm_injection_report(
        self,
        report: Mapping[str, Any],
        prompt: str = "",
        bot_prompt: str = "",
    ) -> None:
        """Write one compact JSON report through AstrBot's plugin logger."""

        try:
            payload = dict(report)
            if self._configured_log_detail() == LOG_DETAIL_FULL:
                payload["prompt"] = prompt
                payload["bot_prompt"] = bot_prompt
            self.logger.info(
                "%s %s",
                LLM_INJECTION_LOG_MARKER,
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            )
        except Exception:
            # Logging must never make an LLM request fail.
            return

    @staticmethod
    def _window_report_ids(
        window_messages: list[dict[str, Any]],
    ) -> tuple[list[str], list[str]]:
        """Summarize sender and direct-mention IDs without logging message text."""

        speaker_ids: list[str] = []
        mentioned_ids: list[str] = []
        for message in window_messages:
            sender_id = normalize_id(message.get("sender_id"))
            if sender_id and sender_id not in speaker_ids:
                speaker_ids.append(sender_id)
            direct_mentions = message.get("mentioned_user_ids", [])
            if isinstance(direct_mentions, (str, int)):
                direct_mentions = [direct_mentions]
            if not isinstance(direct_mentions, list):
                continue
            for user_id in direct_mentions:
                normalized_user_id = normalize_id(user_id)
                if normalized_user_id and normalized_user_id not in mentioned_ids:
                    mentioned_ids.append(normalized_user_id)
        return speaker_ids, mentioned_ids

    @staticmethod
    def _match_reasons_for_log(
        match_reasons: Mapping[str, Mapping[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        """Keep the log useful while excluding the full generated prompt."""

        result: dict[str, dict[str, Any]] = {}
        for user_id, reason in match_reasons.items():
            if not isinstance(reason, Mapping):
                continue
            mentions = reason.get("mentions", [])
            if isinstance(mentions, (str, int)):
                mentions = [mentions]
            mention_values = []
            if isinstance(mentions, list):
                mention_values = [
                    clean_text(value) for value in mentions if clean_text(value)
                ]
            result[normalize_id(user_id)] = {
                "speaker": bool(reason.get("speaker")),
                "mentioned_as": mention_values,
            }
        return {user_id: reason for user_id, reason in result.items() if user_id}

    @staticmethod
    def _window_text(value: object) -> str:
        if value is None or isinstance(value, bool):
            return ""
        text = str(value).replace("\x00", "").strip()
        text = " ".join(text.split())
        return text[:MAX_WINDOW_MESSAGE_TEXT_LENGTH]

    @classmethod
    def _window_message_from_event(
        cls,
        event: AstrMessageEvent,
    ) -> dict[str, Any]:
        message_text = ""
        get_message_str = getattr(event, "get_message_str", None)
        if callable(get_message_str):
            try:
                message_text = get_message_str() or ""
            except Exception:
                message_text = ""
        if not message_text:
            message_text = getattr(event, "message_str", "") or ""

        mentioned_user_ids: list[str] = []
        get_messages = getattr(event, "get_messages", None)
        if callable(get_messages):
            try:
                components = get_messages() or []
            except Exception:
                components = []
            for component in components:
                user_id = normalize_id(getattr(component, "qq", None))
                if user_id and user_id not in mentioned_user_ids:
                    mentioned_user_ids.append(user_id)
                if not message_text:
                    component_text = getattr(component, "text", "")
                    if component_text:
                        message_text += str(component_text)

        history_id = event.get_extra("_current_platform_message_history_id")
        return {
            "message_id": str(history_id) if history_id is not None else "",
            "sender_id": normalize_id(event.get_sender_id()),
            "text": cls._window_text(message_text),
            "mentioned_user_ids": mentioned_user_ids,
            "is_user": True,
        }

    @classmethod
    def _window_message_from_history_record(
        cls,
        record: object,
    ) -> dict[str, Any] | None:
        content = getattr(record, "content", None)
        role = content.get("type") if isinstance(content, Mapping) else "user"
        if role in {"bot", "assistant"}:
            return None

        text_parts: list[str] = []
        mentioned_user_ids: list[str] = []
        parts = content.get("message", []) if isinstance(content, Mapping) else []
        if isinstance(parts, list):
            for part in parts:
                if not isinstance(part, Mapping):
                    continue
                part_type = str(part.get("type", "")).casefold()
                if part_type in {"plain", "text"}:
                    text = part.get("text", "")
                    if text:
                        text_parts.append(str(text))
                elif part_type == "at":
                    user_id = normalize_id(part.get("user_id") or part.get("qq"))
                    if user_id and user_id not in mentioned_user_ids:
                        mentioned_user_ids.append(user_id)
                    if not user_id and part.get("name"):
                        text_parts.append(str(part["name"]))
                elif part_type == "reply" and part.get("text"):
                    text_parts.append(str(part["text"]))

        sender_id = normalize_id(getattr(record, "sender_id", None))
        message_id = getattr(record, "id", None)
        text = cls._window_text(" ".join(text_parts))
        if not sender_id and not text and not mentioned_user_ids:
            return None
        return {
            "message_id": str(message_id) if message_id is not None else "",
            "sender_id": sender_id,
            "text": text,
            "mentioned_user_ids": mentioned_user_ids,
            "is_user": True,
        }

    async def _load_history_messages(
        self,
        platform_id: str,
        session_key: str,
        current_history_id: object = None,
    ) -> list[dict[str, Any]]:
        """Best-effort seed from AstrBot's platform history after a restart."""

        manager = getattr(self.context, "message_history_manager", None)
        get_history = getattr(manager, "get", None)
        if not callable(get_history):
            return []

        try:
            history = get_history(
                platform_id=platform_id,
                user_id=session_key,
                page=1,
                page_size=MAX_MESSAGE_WINDOW_SIZE,
            )
            if inspect.isawaitable(history):
                history = await history
        except Exception as exc:
            self.logger.debug(
                "无法回填群消息窗口 platform=%s session=%s: %s",
                platform_id,
                session_key,
                exc,
            )
            return []

        messages: list[dict[str, Any]] = []
        for record in history or []:
            record_id = getattr(record, "id", None)
            if (
                current_history_id is not None
                and record_id is not None
                and str(record_id) == str(current_history_id)
            ):
                continue
            message = self._window_message_from_history_record(record)
            if message is not None:
                messages.append(message)
        return messages[-MAX_MESSAGE_WINDOW_SIZE:]

    async def _record_group_message_window(
        self,
        event: AstrMessageEvent,
        session_key: str,
        platform_id: str,
    ) -> list[dict[str, Any]]:
        """Record one incoming group message and return the current window."""

        await self._ensure_store_loaded()
        async with self._window_lock:
            messages = self._recent_messages.get(session_key)
            if messages is None:
                messages = deque(maxlen=MAX_MESSAGE_WINDOW_SIZE)
                self._recent_messages[session_key] = messages

            if session_key not in self._window_seeded:
                seeded = await self._load_history_messages(
                    platform_id,
                    session_key,
                    current_history_id=event.get_extra(
                        "_current_platform_message_history_id"
                    ),
                )
                messages.extend(seeded)
                self._window_seeded.add(session_key)

            already_recorded = event.get_extra(WINDOW_RECORDED_EXTRA, False)
            if not already_recorded:
                messages.append(self._window_message_from_event(event))
                event.set_extra(WINDOW_RECORDED_EXTRA, True)

            window_size = self._configured_message_window_size()
            return list(messages)[-window_size:]

    @filter.platform_adapter_type(filter.PlatformAdapterType.ALL)
    async def track_group_message(self, event: AstrMessageEvent) -> None:
        """Track every incoming group message for dynamic member selection."""

        try:
            message_type = event.get_message_type()
            if message_type not in (
                MessageType.GROUP_MESSAGE,
                MessageType.GROUP_MESSAGE.value,
            ):
                return
            group_id = normalize_id(event.get_group_id())
            if not group_id:
                return
            platform_id = clean_text(
                event.get_platform_id() or event.get_platform_name(),
                max_length=128,
            )
            if not platform_id:
                return
            await self._record_group_message_window(
                event,
                build_session_key(platform_id, group_id),
                platform_id,
            )
        except Exception:
            # Tracking must never interrupt normal message processing.
            self.logger.exception("记录群成员动态窗口失败。")

    @staticmethod
    def _profile_from_payload(
        payload: Mapping[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        platform_id = clean_text(payload.get("platform_id"), max_length=128)
        group_id = normalize_id(payload.get("group_id"))
        if not platform_id:
            raise ValueError("缺少平台实例 ID")
        if not group_id:
            raise ValueError("缺少有效的 QQ 群号")
        session_key = build_session_key(platform_id, group_id)
        members = normalize_member_list(payload.get("members", []))
        custom_identity_fields = normalize_custom_identity_fields(
            payload.get("custom_identity_fields", [])
        )
        profile = {
            "platform_id": platform_id,
            "group_id": group_id,
            "group_name": clean_text(payload.get("group_name"), max_length=200),
            "members": members,
            "custom_identity_fields": custom_identity_fields,
            "usage_rules": normalize_usage_rules(payload.get("usage_rules")),
            "injection_enabled": normalize_enabled(
                payload.get("injection_enabled"),
                default=True,
            ),
            ADMIN_COMMAND_WHITELIST_KEY: normalize_qq_id_list(
                payload.get(ADMIN_COMMAND_WHITELIST_KEY, [])
            ),
            ADMIN_COMMAND_BLACKLIST_KEY: normalize_qq_id_list(
                payload.get(ADMIN_COMMAND_BLACKLIST_KEY, [])
            ),
            ALLOW_MEMBER_ADMIN_COMMANDS_KEY: normalize_enabled(
                payload.get(ALLOW_MEMBER_ADMIN_COMMANDS_KEY),
                default=False,
            ),
            "revision": normalize_revision(payload.get("revision")),
            "message_window_size": normalize_message_window_size(
                payload.get("message_window_size", DEFAULT_MESSAGE_WINDOW_SIZE)
            ),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            **normalize_relationship_graph(payload),
        }
        return session_key, profile

    @staticmethod
    def _group_label(profile: Mapping[str, Any]) -> str:
        return clean_text(profile.get("group_name"), max_length=200) or str(
            profile.get("group_id", "")
        )

    @staticmethod
    def _profile_has_local_data(profile: Mapping[str, Any]) -> bool:
        members = profile.get("members", [])
        return bool(
            normalize_usage_rules(profile.get("usage_rules")) != DEFAULT_USAGE_RULES
            or any(
                has_custom_identity(member)
                for member in members
                if isinstance(member, Mapping)
            )
            or bool(normalize_qq_id_list(profile.get(ADMIN_COMMAND_WHITELIST_KEY, [])))
            or bool(normalize_qq_id_list(profile.get(ADMIN_COMMAND_BLACKLIST_KEY, [])))
            or normalize_enabled(
                profile.get(ALLOW_MEMBER_ADMIN_COMMANDS_KEY),
                default=False,
            )
            or not relationship_graph_is_empty(profile)
        )

    @staticmethod
    def _empty_bot_snapshot() -> dict[str, str]:
        return {"user_id": "", "nickname": ""}

    @staticmethod
    def _bot_snapshot_from_login(raw: object) -> dict[str, str]:
        if not isinstance(raw, Mapping):
            return Main._empty_bot_snapshot()
        payload = raw.get("data") if isinstance(raw.get("data"), Mapping) else raw
        if not isinstance(payload, Mapping):
            return Main._empty_bot_snapshot()
        user_id = normalize_id(payload.get("user_id") or payload.get("userId"))
        return {
            "user_id": user_id,
            "nickname": clean_text(payload.get("nickname") or payload.get("nick")),
        }

    def _build_profile_prompts(
        self,
        profile: Mapping[str, Any],
        *,
        self_id: object = "",
        window_messages: list[dict[str, Any]] | None = None,
        match_reasons: Mapping[str, Mapping[str, Any]] | None = None,
        active_members: list[dict[str, Any]] | None = None,
    ) -> tuple[str, str]:
        custom_identity_fields = self._profile_custom_identity_fields(profile)
        exclude_ids = [normalize_id(self_id)] if normalize_id(self_id) else []
        participant_ids = None
        if window_messages is not None:
            participant_ids = collect_window_participant_ids(
                window_messages,
                profile.get("members", []),
                custom_identity_fields=custom_identity_fields,
                exclude_user_ids=exclude_ids,
            )
        graph = normalize_relationship_graph(profile)
        identity_members = (
            active_members
            if active_members is not None
            else profile.get("members", [])
        )
        identity_prompt = build_identity_prompt(
            group_id=profile.get("group_id"),
            group_name=profile.get("group_name", ""),
            members=identity_members,
            usage_rules=profile.get("usage_rules"),
            match_reasons=match_reasons,
            custom_identity_fields=custom_identity_fields,
            self_id=self_id,
            relationship_graph=graph,
            window_participant_ids=participant_ids,
            all_members=profile.get("members", []),
        )
        bot_prompt = build_bot_relationship_prompt(
            members=profile.get("members", []),
            relationship_graph=graph,
            window_participant_ids=participant_ids,
        )
        return identity_prompt, bot_prompt

    async def list_groups(self):
        """Return current groups from every connected OneBot adapter."""

        await self._ensure_store_loaded()
        sessions = copy.deepcopy(self._stored_sessions())
        groups: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        live_session_keys: set[str] = set()

        for platform_id, platform in self._aiocqhttp_platforms():
            try:
                raw_groups = await self._call_onebot_action(platform, "get_group_list")
                group_items = self._extract_list(raw_groups)
                if group_items is None:
                    raise RuntimeError("OneBot 返回的群列表格式不正确")
            except Exception as exc:
                self.logger.warning(
                    "读取 OneBot 群列表失败 platform=%s: %s",
                    platform_id,
                    exc,
                )
                errors.append(
                    {
                        "platform_id": platform_id,
                        "message": "无法读取群列表，请确认 OneBot 连接正常。",
                    }
                )
                continue

            for item in group_items:
                group_id = normalize_id(item.get("group_id") or item.get("id"))
                if not group_id:
                    continue
                session_key = build_session_key(platform_id, group_id)
                live_session_keys.add(session_key)
                saved_profile = sessions.get(session_key, {})
                if not isinstance(saved_profile, Mapping):
                    saved_profile = {}
                group_name = clean_text(
                    item.get("group_name") or item.get("name"),
                    max_length=200,
                ) or self._group_label(saved_profile)
                groups.append(
                    {
                        "session_key": session_key,
                        "platform_id": platform_id,
                        "platform_name": "aiocqhttp",
                        "group_id": group_id,
                        "group_name": group_name,
                        "available": True,
                        "has_profile": self._profile_has_local_data(saved_profile),
                        "member_count": len(saved_profile.get("members", [])),
                        "injection_enabled": normalize_enabled(
                            saved_profile.get("injection_enabled"),
                            default=True,
                        ),
                        "revision": normalize_revision(saved_profile.get("revision")),
                        "message_window_size": self._configured_message_window_size(),
                    }
                )

        # Keep a saved profile visible when the adapter is temporarily offline.
        for session_key, profile in sessions.items():
            if session_key in live_session_keys or not isinstance(profile, Mapping):
                continue
            platform_id = clean_text(profile.get("platform_id"), max_length=128)
            group_id = normalize_id(profile.get("group_id"))
            if not platform_id or not group_id:
                continue
            groups.append(
                {
                    "session_key": session_key,
                    "platform_id": platform_id,
                    "platform_name": "aiocqhttp",
                    "group_id": group_id,
                    "group_name": self._group_label(profile),
                    "available": False,
                    "has_profile": self._profile_has_local_data(profile),
                    "member_count": len(profile.get("members", [])),
                    "injection_enabled": normalize_enabled(
                        profile.get("injection_enabled"),
                        default=True,
                    ),
                    "revision": normalize_revision(profile.get("revision")),
                    "message_window_size": self._configured_message_window_size(),
                }
            )

        groups.sort(
            key=lambda item: (
                str(item.get("platform_id", "")),
                str(item.get("group_name", "")).casefold(),
                str(item.get("group_id", "")),
            )
        )
        return json_response({"groups": groups, "errors": errors})

    async def get_plugin_config(self):
        """Return the plugin settings shared with AstrBot's config page."""

        return json_response(self._plugin_config_snapshot())

    @staticmethod
    def _avatar_revision_from_headers(headers: Mapping[str, Any]) -> str:
        """Build a stable, URL-safe revision from QQ CDN response metadata."""

        source = ""
        for header_name in ("ETag", "Last-Modified", "X-Bcheck"):
            value = headers.get(header_name)
            if value:
                source = str(value).strip()
                break
        if not source:
            return ""
        return hashlib.sha256(source.encode("utf-8")).hexdigest()[:16]

    async def _check_avatar_revisions(
        self,
        user_ids: list[str],
    ) -> list[dict[str, Any]]:
        """Read current avatar revisions with body-free, concurrency-limited HEADs."""

        timeout = aiohttp.ClientTimeout(total=AVATAR_REQUEST_TIMEOUT_SECONDS)
        connector = aiohttp.TCPConnector(limit=AVATAR_CHECK_CONCURRENCY)
        semaphore = asyncio.Semaphore(AVATAR_CHECK_CONCURRENCY)
        headers = {
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
            "User-Agent": f"AstrBot/{PLUGIN_NAME}",
        }

        async with aiohttp.ClientSession(
            timeout=timeout,
            connector=connector,
            headers=headers,
            trust_env=True,
        ) as session:

            async def check_one(user_id: str) -> dict[str, Any]:
                try:
                    async with semaphore:
                        async with session.head(
                            AVATAR_CDN_URL,
                            params={"b": "qq", "nk": user_id, "s": str(AVATAR_SIZE)},
                            allow_redirects=True,
                        ) as response:
                            revision = self._avatar_revision_from_headers(
                                response.headers
                            )
                            return {
                                "user_id": user_id,
                                "available": 200 <= response.status < 400
                                and bool(revision),
                                "revision": revision,
                            }
                except (aiohttp.ClientError, asyncio.TimeoutError):
                    return {
                        "user_id": user_id,
                        "available": False,
                        "revision": "",
                    }

            return list(
                await asyncio.gather(*(check_one(user_id) for user_id in user_ids))
            )

    async def check_avatar_updates(self):
        """Return current revisions so the browser only reloads changed QQ avatars."""

        if not self._configured_avatar_preview_enabled():
            return json_response(
                {
                    "enabled": False,
                    "checked_count": 0,
                    "avatars": [],
                }
            )

        payload = await request.json(default={})
        if not isinstance(payload, Mapping):
            return error_response("请求数据格式错误。", status_code=400)

        raw_user_ids = payload.get("user_ids", [])
        if not isinstance(raw_user_ids, list):
            return error_response("头像校验成员列表格式错误。", status_code=400)
        if len(raw_user_ids) > MAX_AVATAR_CHECK_COUNT:
            return error_response(
                f"每次最多校验 {MAX_AVATAR_CHECK_COUNT} 位成员头像。",
                status_code=400,
            )

        user_ids: list[str] = []
        for raw_user_id in raw_user_ids:
            user_id = normalize_id(raw_user_id)
            if user_id and user_id not in user_ids:
                user_ids.append(user_id)
        if not user_ids:
            return json_response(
                {
                    "enabled": True,
                    "checked_count": 0,
                    "avatars": [],
                }
            )

        avatars = await self._check_avatar_revisions(user_ids)
        return json_response(
            {
                "enabled": True,
                "checked_count": len(user_ids),
                "avatars": avatars,
            }
        )

    async def save_plugin_config(self):
        """Validate and persist settings shared with AstrBot's config page."""

        payload = await request.json(default={})
        if not isinstance(payload, Mapping):
            return error_response("请求数据格式错误。", status_code=400)

        current = self._plugin_config_snapshot()
        values = {
            "message_window_size": normalize_message_window_size(
                payload.get("message_window_size", current["message_window_size"])
            ),
            "log_detail": (
                "全部"
                if normalize_log_detail(
                    payload.get("log_detail", current["log_detail"])
                )
                == LOG_DETAIL_FULL
                else "摘要"
            ),
            "avatar_preview_enabled": self._normalize_config_bool(
                payload.get(
                    "avatar_preview_enabled",
                    current["avatar_preview_enabled"],
                )
            ),
        }

        try:
            async with self._config_lock:
                await self._persist_plugin_config(values)
        except Exception as exc:
            self.logger.exception("保存插件配置失败。")
            return error_response(f"保存插件配置失败：{exc}", status_code=500)

        return json_response({"saved": True, **values})

    async def profile_status(self):
        """Return lightweight state used by the Page to detect external edits."""

        platform_id = clean_text(request.query.get("platform_id"), max_length=128)
        group_id = normalize_id(request.query.get("group_id"))
        if not platform_id or not group_id:
            return error_response(
                "请提供有效的平台实例 ID 和 QQ 群号。", status_code=400
            )
        await self._ensure_store_loaded()
        profile = self._stored_sessions().get(build_session_key(platform_id, group_id))
        if not isinstance(profile, Mapping):
            return json_response(
                {
                    "revision": 0,
                    "injection_enabled": True,
                    ADMIN_COMMAND_WHITELIST_KEY: [],
                    ADMIN_COMMAND_BLACKLIST_KEY: [],
                    ALLOW_MEMBER_ADMIN_COMMANDS_KEY: False,
                    "exists": False,
                }
            )
        return json_response(
            {
                "revision": normalize_revision(profile.get("revision")),
                "injection_enabled": normalize_enabled(
                    profile.get("injection_enabled"),
                    default=True,
                ),
                ADMIN_COMMAND_WHITELIST_KEY: normalize_qq_id_list(
                    profile.get(ADMIN_COMMAND_WHITELIST_KEY, [])
                    if isinstance(profile, Mapping)
                    else []
                ),
                ADMIN_COMMAND_BLACKLIST_KEY: normalize_qq_id_list(
                    profile.get(ADMIN_COMMAND_BLACKLIST_KEY, [])
                    if isinstance(profile, Mapping)
                    else []
                ),
                ALLOW_MEMBER_ADMIN_COMMANDS_KEY: normalize_enabled(
                    profile.get(ALLOW_MEMBER_ADMIN_COMMANDS_KEY)
                    if isinstance(profile, Mapping)
                    else None,
                    default=False,
                ),
                "exists": True,
            }
        )

    async def list_members(self):
        """Fetch and merge the current member list for one selected QQ group."""

        platform_id = clean_text(request.query.get("platform_id"), max_length=128)
        group_id = normalize_id(request.query.get("group_id"))
        if not platform_id or not group_id:
            return error_response(
                "请提供有效的平台实例 ID 和 QQ 群号。", status_code=400
            )

        platform = self._find_aiocqhttp_platform(platform_id)
        if platform is None:
            return error_response("未找到对应的 OneBot QQ 平台实例。", status_code=404)

        try:
            raw_members = await self._call_onebot_action(
                platform,
                "get_group_member_list",
                group_id=int(group_id),
            )
            member_items = self._extract_list(raw_members)
            if member_items is None:
                raise RuntimeError("OneBot 返回的群成员列表格式不正确")
        except Exception as exc:
            self.logger.warning(
                "读取 OneBot 群成员失败 platform=%s group=%s: %s",
                platform_id,
                group_id,
                exc,
            )
            return error_response(
                "无法读取该群成员列表，请确认机器人仍在群内并检查 OneBot 权限。",
                status_code=502,
            )

        await self._ensure_store_loaded()
        session_key = build_session_key(platform_id, group_id)
        profile = self._stored_sessions().get(session_key, {})
        saved_members = (
            profile.get("members", []) if isinstance(profile, Mapping) else []
        )
        members = merge_remote_members(member_items, saved_members)
        group_name = (
            clean_text(profile.get("group_name"), max_length=200)
            if isinstance(profile, Mapping)
            else ""
        )
        bot = self._empty_bot_snapshot()
        try:
            bot = self._bot_snapshot_from_login(
                await self._call_onebot_action(platform, "get_login_info")
            )
        except Exception as exc:
            self.logger.warning(
                "读取 OneBot 登录号失败 platform=%s group=%s: %s",
                platform_id,
                group_id,
                exc,
            )
        graph = normalize_relationship_graph(
            profile if isinstance(profile, Mapping) else {}
        )
        return json_response(
            {
                "session_key": session_key,
                "platform_id": platform_id,
                "group_id": group_id,
                "group_name": group_name,
                "members": members,
                "bot": bot,
                "custom_identity_fields": self._profile_custom_identity_fields(
                    profile if isinstance(profile, Mapping) else {}
                ),
                "usage_rules": normalize_usage_rules(
                    profile.get("usage_rules") if isinstance(profile, Mapping) else None
                ),
                "injection_enabled": normalize_enabled(
                    profile.get("injection_enabled")
                    if isinstance(profile, Mapping)
                    else None,
                    default=True,
                ),
                ADMIN_COMMAND_WHITELIST_KEY: normalize_qq_id_list(
                    profile.get(ADMIN_COMMAND_WHITELIST_KEY, [])
                    if isinstance(profile, Mapping)
                    else []
                ),
                ADMIN_COMMAND_BLACKLIST_KEY: normalize_qq_id_list(
                    profile.get(ADMIN_COMMAND_BLACKLIST_KEY, [])
                    if isinstance(profile, Mapping)
                    else []
                ),
                ALLOW_MEMBER_ADMIN_COMMANDS_KEY: normalize_enabled(
                    profile.get(ALLOW_MEMBER_ADMIN_COMMANDS_KEY)
                    if isinstance(profile, Mapping)
                    else None,
                    default=False,
                ),
                "revision": normalize_revision(
                    profile.get("revision") if isinstance(profile, Mapping) else None
                ),
                "default_usage_rules": DEFAULT_USAGE_RULES,
                "message_window_size": self._configured_message_window_size(),
                **graph,
            }
        )

    async def save_profile(self):
        """Persist a group profile and return the generated prompt for verification."""

        payload = await request.json(default={})
        if not isinstance(payload, Mapping):
            return error_response("请求数据格式错误。", status_code=400)
        try:
            session_key, profile = self._profile_from_payload(payload)
            custom_identity_fields = self._profile_custom_identity_fields(profile)
            bot_user_id = ""
            raw_bot = payload.get("bot")
            if isinstance(raw_bot, Mapping):
                bot_user_id = normalize_id(raw_bot.get("user_id"))
            prompt, bot_prompt = self._build_profile_prompts(
                profile,
                self_id=bot_user_id,
            )
        except ValueError as exc:
            return error_response(str(exc), status_code=400)

        await self._ensure_store_loaded()
        async with self._store_lock:
            existing = self._stored_sessions().get(session_key)
            existing_profile = existing if isinstance(existing, Mapping) else {}
            current_revision = normalize_revision(existing_profile.get("revision"))
            submitted_revision = payload.get("revision")
            if submitted_revision is not None and (
                normalize_revision(submitted_revision) != current_revision
            ):
                return error_response(
                    "本群资料已由群指令或其他页面更新，请刷新后再保存。",
                    status_code=409,
                )
            profile["revision"] = current_revision + 1
            self._stored_sessions()[session_key] = profile
            await self._persist_store()
        return json_response(
            {
                "saved": True,
                "session_key": session_key,
                "member_count": len(profile["members"]),
                "configured_member_count": sum(
                    1 for member in profile["members"] if has_custom_identity(member)
                ),
                "usage_rules": profile["usage_rules"],
                "usage_rules_customized": profile["usage_rules"] != DEFAULT_USAGE_RULES,
                "default_usage_rules": DEFAULT_USAGE_RULES,
                "custom_identity_fields": custom_identity_fields,
                "injection_enabled": profile["injection_enabled"],
                ADMIN_COMMAND_WHITELIST_KEY: profile[ADMIN_COMMAND_WHITELIST_KEY],
                ADMIN_COMMAND_BLACKLIST_KEY: profile[ADMIN_COMMAND_BLACKLIST_KEY],
                ALLOW_MEMBER_ADMIN_COMMANDS_KEY: profile[
                    ALLOW_MEMBER_ADMIN_COMMANDS_KEY
                ],
                "revision": profile["revision"],
                "message_window_size": self._configured_message_window_size(),
                "prompt": prompt,
                "bot_prompt": bot_prompt,
                "relationship_injection_enabled": profile[
                    "relationship_injection_enabled"
                ],
            }
        )

    async def reset_profile(self):
        """Clear all member identity data and restore usage rules for one group."""

        payload = await request.json(default={})
        if not isinstance(payload, Mapping):
            return error_response("请求数据格式错误。", status_code=400)

        platform_id = clean_text(payload.get("platform_id"), max_length=128)
        group_id = normalize_id(payload.get("group_id"))
        if not platform_id or not group_id:
            return error_response(
                "请提供有效的平台实例 ID 和 QQ 群号。", status_code=400
            )
        try:
            session_key = build_session_key(platform_id, group_id)
        except ValueError as exc:
            return error_response(str(exc), status_code=400)

        await self._ensure_store_loaded()
        async with self._store_lock:
            sessions = self._stored_sessions()
            existing = sessions.get(session_key)
            existing_profile = existing if isinstance(existing, Mapping) else {}
            current_revision = normalize_revision(existing_profile.get("revision"))
            submitted_revision = payload.get("revision")
            if submitted_revision is not None and (
                normalize_revision(submitted_revision) != current_revision
            ):
                return error_response(
                    "本群资料已由群指令或其他页面更新，请刷新后再重置。",
                    status_code=409,
                )
            source_members = existing_profile.get("members", [])
            if not isinstance(source_members, list) or (
                not source_members and isinstance(payload.get("members"), list)
            ):
                source_members = payload.get("members", [])
            if not isinstance(source_members, list):
                source_members = []

            reset_members = []
            for raw_member in source_members:
                if not isinstance(raw_member, Mapping):
                    continue
                try:
                    reset_members.append(clear_member_identity(raw_member))
                except ValueError:
                    continue

            reset_profile = {
                "platform_id": platform_id,
                "group_id": group_id,
                "group_name": clean_text(
                    existing_profile.get("group_name") or payload.get("group_name"),
                    max_length=200,
                ),
                "members": reset_members,
                "custom_identity_fields": self._profile_custom_identity_fields(
                    existing_profile
                ),
                "usage_rules": DEFAULT_USAGE_RULES,
                "injection_enabled": normalize_enabled(
                    existing_profile.get("injection_enabled"),
                    default=True,
                ),
                ADMIN_COMMAND_WHITELIST_KEY: normalize_qq_id_list(
                    existing_profile.get(ADMIN_COMMAND_WHITELIST_KEY, [])
                ),
                ADMIN_COMMAND_BLACKLIST_KEY: normalize_qq_id_list(
                    existing_profile.get(ADMIN_COMMAND_BLACKLIST_KEY, [])
                ),
                ALLOW_MEMBER_ADMIN_COMMANDS_KEY: normalize_enabled(
                    existing_profile.get(ALLOW_MEMBER_ADMIN_COMMANDS_KEY),
                    default=False,
                ),
                "revision": current_revision + 1,
                "message_window_size": self._configured_message_window_size(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
                **empty_relationship_graph(),
            }
            sessions[session_key] = reset_profile
            await self._persist_store()

        return json_response(
            {
                "reset": True,
                "session_key": session_key,
                "member_count": len(reset_members),
                "configured_member_count": 0,
                "usage_rules": DEFAULT_USAGE_RULES,
                "usage_rules_customized": False,
                "default_usage_rules": DEFAULT_USAGE_RULES,
                "members": reset_members,
                "custom_identity_fields": reset_profile["custom_identity_fields"],
                "injection_enabled": reset_profile["injection_enabled"],
                ADMIN_COMMAND_WHITELIST_KEY: reset_profile[ADMIN_COMMAND_WHITELIST_KEY],
                ADMIN_COMMAND_BLACKLIST_KEY: reset_profile[ADMIN_COMMAND_BLACKLIST_KEY],
                ALLOW_MEMBER_ADMIN_COMMANDS_KEY: reset_profile[
                    ALLOW_MEMBER_ADMIN_COMMANDS_KEY
                ],
                "revision": reset_profile["revision"],
                "message_window_size": self._configured_message_window_size(),
                **empty_relationship_graph(),
            }
        )

    async def preview_profile(self):
        """Generate a prompt without changing persistent data."""

        payload = await request.json(default={})
        if not isinstance(payload, Mapping):
            return error_response("请求数据格式错误。", status_code=400)
        try:
            _, profile = self._profile_from_payload(payload)
            custom_identity_fields = self._profile_custom_identity_fields(profile)
            bot_user_id = ""
            raw_bot = payload.get("bot")
            if isinstance(raw_bot, Mapping):
                bot_user_id = normalize_id(raw_bot.get("user_id"))
            prompt, bot_prompt = self._build_profile_prompts(
                profile,
                self_id=bot_user_id,
            )
        except ValueError as exc:
            return error_response(str(exc), status_code=400)
        return json_response(
            {
                "prompt": prompt,
                "bot_prompt": bot_prompt,
                "relationship_injection_enabled": profile[
                    "relationship_injection_enabled"
                ],
                "custom_identity_fields": custom_identity_fields,
                "injection_enabled": profile["injection_enabled"],
                ADMIN_COMMAND_WHITELIST_KEY: profile[ADMIN_COMMAND_WHITELIST_KEY],
                ADMIN_COMMAND_BLACKLIST_KEY: profile[ADMIN_COMMAND_BLACKLIST_KEY],
                ALLOW_MEMBER_ADMIN_COMMANDS_KEY: profile[
                    ALLOW_MEMBER_ADMIN_COMMANDS_KEY
                ],
                "revision": profile["revision"],
                "usage_rules": profile["usage_rules"],
                "usage_rules_customized": profile["usage_rules"] != DEFAULT_USAGE_RULES,
                "default_usage_rules": DEFAULT_USAGE_RULES,
                "message_window_size": self._configured_message_window_size(),
            }
        )

    @staticmethod
    def _command_event_ids(event: AstrMessageEvent) -> tuple[str, str]:
        group_id = normalize_id(event.get_group_id())
        platform_id = clean_text(
            event.get_platform_id() or event.get_platform_name(),
            max_length=128,
        )
        if not group_id or not platform_id:
            raise ValueError("该指令只能在已连接的 QQ 群中使用。")
        return platform_id, group_id

    @staticmethod
    def _onebot_mapping(payload: object) -> Mapping[str, Any] | None:
        if not isinstance(payload, Mapping):
            return None
        data = payload.get("data")
        if isinstance(data, Mapping):
            return data
        return payload

    async def _ensure_command_profile(
        self,
        event: AstrMessageEvent,
    ) -> tuple[str, str, str, object]:
        platform_id, group_id = self._command_event_ids(event)
        platform = self._find_aiocqhttp_platform(platform_id)
        if platform is None:
            raise ValueError("未找到当前 QQ 平台连接。")
        await self._ensure_store_loaded()
        session_key = build_session_key(platform_id, group_id)
        if isinstance(self._stored_sessions().get(session_key), Mapping):
            return session_key, platform_id, group_id, platform

        raw_members = await self._call_onebot_action(
            platform,
            "get_group_member_list",
            group_id=int(group_id),
        )
        member_items = self._extract_list(raw_members)
        if member_items is None:
            raise ValueError("无法读取当前群成员。")
        group_name = ""
        try:
            raw_group = await self._call_onebot_action(
                platform,
                "get_group_info",
                group_id=int(group_id),
            )
            group_info = self._onebot_mapping(raw_group)
            if group_info:
                group_name = clean_text(
                    group_info.get("group_name") or group_info.get("name"),
                    max_length=200,
                )
        except Exception:
            group_name = ""

        profile = {
            "platform_id": platform_id,
            "group_id": group_id,
            "group_name": group_name,
            "members": merge_remote_members(member_items),
            "custom_identity_fields": [],
            "usage_rules": DEFAULT_USAGE_RULES,
            "injection_enabled": True,
            ADMIN_COMMAND_WHITELIST_KEY: [],
            ADMIN_COMMAND_BLACKLIST_KEY: [],
            ALLOW_MEMBER_ADMIN_COMMANDS_KEY: False,
            "revision": 1,
            "message_window_size": self._configured_message_window_size(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        async with self._store_lock:
            if not isinstance(self._stored_sessions().get(session_key), Mapping):
                self._stored_sessions()[session_key] = profile
                await self._persist_store()
        return session_key, platform_id, group_id, platform

    async def _fetch_group_member(
        self,
        platform: object,
        group_id: str,
        user_id: str,
    ) -> dict[str, Any]:
        try:
            payload = await self._call_onebot_action(
                platform,
                "get_group_member_info",
                group_id=int(group_id),
                user_id=int(user_id),
                no_cache=False,
            )
            member_info = self._onebot_mapping(payload)
            if member_info is None:
                raise ValueError
            return normalize_member(member_info)
        except Exception as exc:
            raise ValueError("目标不是当前群成员或成员信息读取失败。") from exc

    @staticmethod
    def _sender_role_from_event(event: AstrMessageEvent) -> str:
        message_obj = getattr(event, "message_obj", None)
        raw_message = getattr(message_obj, "raw_message", None)
        if isinstance(raw_message, Mapping):
            sender = raw_message.get("sender")
            if isinstance(sender, Mapping):
                return clean_text(sender.get("role"), max_length=32).casefold()
        return ""

    async def _admin_command_allowed(
        self,
        event: AstrMessageEvent,
        platform: object,
        group_id: str,
    ) -> bool:
        sender_id = normalize_id(event.get_sender_id())
        if not sender_id:
            return False
        role = self._sender_role_from_event(event)
        if role not in {"owner", "admin", "member"}:
            try:
                sender = await self._fetch_group_member(platform, group_id, sender_id)
                role = clean_text(sender.get("role"), max_length=32).casefold()
            except ValueError:
                return False

        has_base_permission = role in {"owner", "admin"}
        platform_id = self._platform_id(platform)
        profile = self._stored_sessions().get(
            build_session_key(platform_id, group_id),
            {},
        )
        if not isinstance(profile, Mapping):
            profile = {}
        if (
            normalize_enabled(
                profile.get(ALLOW_MEMBER_ADMIN_COMMANDS_KEY),
                default=False,
            )
            and role == "member"
        ):
            has_base_permission = True
        if not has_base_permission:
            return False

        whitelist = normalize_qq_id_list(profile.get(ADMIN_COMMAND_WHITELIST_KEY, []))
        if whitelist:
            return sender_id in whitelist
        return sender_id not in normalize_qq_id_list(
            profile.get(ADMIN_COMMAND_BLACKLIST_KEY, [])
        )

    @staticmethod
    def _target_mentions(event: AstrMessageEvent) -> tuple[list[str], bool]:
        target_ids: list[str] = []
        mentioned_all = False
        self_id = normalize_id(event.get_self_id())
        for component in event.get_messages() or []:
            if not isinstance(component, At):
                continue
            if str(component.qq).casefold() == "all":
                mentioned_all = True
                continue
            user_id = normalize_id(component.qq)
            if user_id and user_id != self_id and user_id not in target_ids:
                target_ids.append(user_id)
        return target_ids, mentioned_all

    @staticmethod
    def _plain_after_target(event: AstrMessageEvent, target_id: str) -> str:
        found_target = False
        parts: list[str] = []
        for component in event.get_messages() or []:
            if isinstance(component, At) and normalize_id(component.qq) == target_id:
                found_target = True
                continue
            if found_target and isinstance(component, Plain):
                text = str(component.text).strip()
                if text:
                    parts.append(text)
        return " ".join(parts).strip()

    def _target_and_expression(
        self,
        event: AstrMessageEvent,
        payload: str,
    ) -> tuple[str, str]:
        target_ids, mentioned_all = self._target_mentions(event)
        if mentioned_all:
            raise ValueError("不能把全体成员作为目标。")
        if len(target_ids) > 1:
            raise ValueError("一次只能指定一名群成员。")
        if target_ids:
            target_id = target_ids[0]
            expression = self._plain_after_target(event, target_id)
            if not expression:
                match = re.search(
                    rf"\({re.escape(target_id)}\)\s*(.+)$",
                    str(payload).strip(),
                )
                expression = match.group(1).strip() if match else ""
            return target_id, expression

        parts = str(payload).strip().split(maxsplit=1)
        target_id = normalize_id(parts[0]) if parts else ""
        if not target_id:
            raise ValueError("请使用真实 @ 或 QQ 号指定一名群成员。")
        return target_id, parts[1].strip() if len(parts) > 1 else ""

    def _list_target(self, event: AstrMessageEvent, payload: str) -> str:
        target_ids, mentioned_all = self._target_mentions(event)
        if mentioned_all:
            raise ValueError("不能查看全体成员。")
        if len(target_ids) > 1:
            raise ValueError("一次只能查看一名群成员。")
        if target_ids:
            return target_ids[0]
        raw_target = str(payload).strip()
        if not raw_target:
            return normalize_id(event.get_sender_id())
        target_id = normalize_id(raw_target)
        if not target_id:
            raise ValueError("请使用真实 @ 或 QQ 号指定一名群成员。")
        return target_id

    @staticmethod
    def _parse_identity_expression(expression: str) -> tuple[str, str]:
        normalized_expression = " ".join(str(expression).replace("\x00", "").split())
        if not normalized_expression:
            raise ValueError("缺少身份内容。")
        separator_index = -1
        for separator in ("=", "＝"):
            current_index = normalized_expression.find(separator)
            if current_index >= 0 and (
                separator_index < 0 or current_index < separator_index
            ):
                separator_index = current_index
        if separator_index >= 0:
            raw_label = normalized_expression[:separator_index].strip()
            raw_value = normalized_expression[separator_index + 1 :].strip()
            if not raw_label or not raw_value:
                raise ValueError("身份标签和身份内容都不能为空。")
            if len(raw_label) > MAX_CUSTOM_IDENTITY_FIELD_LENGTH:
                raise ValueError("身份标签过长。")
            label = clean_text(
                raw_label,
                max_length=MAX_CUSTOM_IDENTITY_FIELD_LENGTH,
            )
            value = raw_value
        else:
            label = "昵称"
            value = normalized_expression
        if len(value) > MAX_TEXT_LENGTH:
            raise ValueError("身份内容过长。")
        return label, clean_text(value, max_length=MAX_TEXT_LENGTH)

    async def _mutate_member_identity(
        self,
        event: AstrMessageEvent,
        *,
        target_id: str,
        expression: str,
        remove: bool,
        self_service: bool,
    ) -> str:
        (
            session_key,
            _platform_id,
            group_id,
            platform,
        ) = await self._ensure_command_profile(event)
        if self_service and target_id != normalize_id(event.get_sender_id()):
            return "失败：普通成员只能修改自己的身份。"
        remote_member = await self._fetch_group_member(platform, group_id, target_id)
        label, value = self._parse_identity_expression(expression)
        reserved_keys = {field.casefold() for field in RESERVED_IDENTITY_FIELDS}
        if label.casefold() in reserved_keys:
            return "失败：该字段由平台维护，不能通过指令修改。"
        standard_field = next(
            (
                field
                for field_label, field in WRITABLE_STANDARD_IDENTITY_FIELDS.items()
                if field_label.casefold() == label.casefold()
            ),
            "",
        )
        if self_service and not standard_field:
            if not await self._admin_command_allowed(event, platform, group_id):
                return "失败：自定义身份标签仅限管理员使用。"
            profile = self._stored_sessions().get(session_key, {})
            fields = self._profile_custom_identity_fields(
                profile if isinstance(profile, Mapping) else {}
            )
            if not any(field.casefold() == label.casefold() for field in fields):
                return "失败：身份标签不存在，请先使用 /群身份 tag add 创建。"

        async with self._store_lock:
            raw_profile = self._stored_sessions().get(session_key)
            if not isinstance(raw_profile, dict):
                return "失败：本群身份资料不存在。"
            members = raw_profile.get("members")
            if not isinstance(members, list):
                members = []
                raw_profile["members"] = members
            member = next(
                (
                    item
                    for item in members
                    if isinstance(item, dict)
                    and normalize_id(item.get("user_id")) == target_id
                ),
                None,
            )
            if member is None:
                member = remote_member
                members.append(member)
            else:
                member = merge_remote_members([remote_member], [member])[0]
                member_index = next(
                    index
                    for index, item in enumerate(members)
                    if isinstance(item, Mapping)
                    and normalize_id(item.get("user_id")) == target_id
                )
                members[member_index] = member

            fields = self._profile_custom_identity_fields(raw_profile)
            custom_label = next(
                (field for field in fields if field.casefold() == label.casefold()),
                "",
            )
            if not standard_field and not custom_label:
                if remove:
                    return "失败：身份标签不存在。"
                if self_service:
                    return "失败：身份标签不存在，请先使用 /群身份 tag add 创建。"
                if len(fields) >= MAX_CUSTOM_IDENTITY_FIELD_COUNT:
                    return "失败：本群自定义身份标签已达到上限。"
                fields.append(label)
                raw_profile["custom_identity_fields"] = fields
                custom_label = label

            if standard_field:
                values = member.get(standard_field)
                if not isinstance(values, list):
                    values = []
                    member[standard_field] = values
                max_count = (
                    MAX_ALIAS_COUNT
                    if standard_field == "aliases"
                    else MAX_IDENTITY_VALUE_COUNT
                )
            else:
                custom_fields = member.get("custom_fields")
                if not isinstance(custom_fields, dict):
                    custom_fields = {}
                    member["custom_fields"] = custom_fields
                values = custom_fields.get(custom_label)
                if not isinstance(values, list):
                    values = []
                    custom_fields[custom_label] = values
                max_count = MAX_IDENTITY_VALUE_COUNT

            value_key = normalize_match_text(value)
            matching_indexes = [
                index
                for index, current in enumerate(values)
                if normalize_match_text(current) == value_key
            ]
            if remove:
                if not matching_indexes:
                    return "失败：未找到对应身份。"
                for index in reversed(matching_indexes):
                    values.pop(index)
            else:
                if matching_indexes:
                    return "成功：该身份已存在。"
                if len(values) >= max_count:
                    return "失败：该身份标签的内容已达到上限。"
                values.append(value)

            raw_profile["revision"] = (
                normalize_revision(raw_profile.get("revision")) + 1
            )
            raw_profile["updated_at"] = datetime.now(timezone.utc).isoformat()
            await self._persist_store()
        return "成功：身份已删除。" if remove else "成功：身份已添加。"

    async def _set_group_injection(
        self,
        event: AstrMessageEvent,
        enabled: bool,
    ) -> str:
        (
            session_key,
            _platform_id,
            group_id,
            platform,
        ) = await self._ensure_command_profile(event)
        if not await self._admin_command_allowed(event, platform, group_id):
            return "失败：你没有权限执行该指令。"
        async with self._store_lock:
            profile = self._stored_sessions().get(session_key)
            if not isinstance(profile, dict):
                return "失败：本群身份资料不存在。"
            profile["injection_enabled"] = enabled
            profile["revision"] = normalize_revision(profile.get("revision")) + 1
            profile["updated_at"] = datetime.now(timezone.utc).isoformat()
            await self._persist_store()
        return f"成功：身份注入已{'开启' if enabled else '关闭'}。"

    async def _mutate_group_tag(
        self,
        event: AstrMessageEvent,
        label: str,
        *,
        remove: bool,
    ) -> str:
        (
            session_key,
            _platform_id,
            group_id,
            platform,
        ) = await self._ensure_command_profile(event)
        if not await self._admin_command_allowed(event, platform, group_id):
            return "失败：你没有权限执行该指令。"
        raw_label = " ".join(str(label).replace("\x00", "").split())
        if not raw_label:
            return "失败：缺少身份标签。"
        if len(raw_label) > MAX_CUSTOM_IDENTITY_FIELD_LENGTH:
            return "失败：身份标签过长。"
        normalized_label = clean_text(
            raw_label,
            max_length=MAX_CUSTOM_IDENTITY_FIELD_LENGTH,
        )
        protected_labels = {
            *(field.casefold() for field in RESERVED_IDENTITY_FIELDS),
            *(field.casefold() for field in WRITABLE_STANDARD_IDENTITY_FIELDS),
        }
        if normalized_label.casefold() in protected_labels:
            return "失败：内置身份标签不能添加或删除。"

        async with self._store_lock:
            profile = self._stored_sessions().get(session_key)
            if not isinstance(profile, dict):
                return "失败：本群身份资料不存在。"
            fields = self._profile_custom_identity_fields(profile)
            existing_label = next(
                (
                    field
                    for field in fields
                    if field.casefold() == normalized_label.casefold()
                ),
                "",
            )
            if remove:
                if not existing_label:
                    return "失败：身份标签不存在。"
                for member in profile.get("members", []):
                    if not isinstance(member, Mapping):
                        continue
                    custom_fields = member.get("custom_fields", {})
                    values = (
                        custom_fields.get(existing_label, [])
                        if isinstance(custom_fields, Mapping)
                        else []
                    )
                    if isinstance(values, list) and any(
                        clean_text(value) for value in values
                    ):
                        return "失败：该标签仍在使用，请先删除对应身份。"
                fields.remove(existing_label)
                for member in profile.get("members", []):
                    if not isinstance(member, dict):
                        continue
                    custom_fields = member.get("custom_fields")
                    if isinstance(custom_fields, dict):
                        custom_fields.pop(existing_label, None)
            else:
                if existing_label:
                    return "成功：该身份标签已存在。"
                if len(fields) >= MAX_CUSTOM_IDENTITY_FIELD_COUNT:
                    return "失败：本群自定义身份标签已达到上限。"
                fields.append(normalized_label)
            profile["custom_identity_fields"] = fields
            profile["revision"] = normalize_revision(profile.get("revision")) + 1
            profile["updated_at"] = datetime.now(timezone.utc).isoformat()
            await self._persist_store()
        return "成功：身份标签已删除。" if remove else "成功：身份标签已添加。"

    @staticmethod
    def _identity_card_fields(
        member: Mapping[str, Any],
        custom_identity_fields: list[str],
    ) -> list[dict[str, Any]]:
        fields: list[dict[str, Any]] = []
        for label, key in (
            ("外号", "aliases"),
            ("真名", "real_names"),
            ("昵称", "nicknames"),
        ):
            values = member.get(key, [])
            if isinstance(values, list) and values:
                fields.append({"label": label, "values": values})
        custom_fields = member.get("custom_fields", {})
        if isinstance(custom_fields, Mapping):
            for label in custom_identity_fields:
                values = custom_fields.get(label, [])
                if isinstance(values, list) and values:
                    fields.append({"label": label, "values": values})
        return fields

    async def _download_identity_avatar(self, user_id: str) -> str:
        timeout = aiohttp.ClientTimeout(total=AVATAR_REQUEST_TIMEOUT_SECONDS)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(
                    AVATAR_CDN_URL,
                    params={"b": "qq", "nk": user_id, "s": "140"},
                ) as response:
                    if response.status < 200 or response.status >= 300:
                        return ""
                    content_type = response.headers.get("Content-Type", "").split(
                        ";", 1
                    )[0]
                    if not content_type.casefold().startswith("image/"):
                        return ""
                    body = await response.content.read(
                        MAX_IDENTITY_CARD_AVATAR_BYTES + 1
                    )
                    if not body or len(body) > MAX_IDENTITY_CARD_AVATAR_BYTES:
                        return ""
        except (aiohttp.ClientError, asyncio.TimeoutError):
            return ""
        encoded = base64.b64encode(body).decode("ascii")
        return f"data:{content_type};base64,{encoded}"

    def _crop_rendered_card_image(self, image_path: str, padding: int = 30) -> str:
        """裁掉 Playwright 默认视口产生的空白，并保留模板外边距。"""

        source = Path(str(image_path))
        if not source.is_file():
            return image_path
        try:
            with Image.open(source) as rendered:
                rendered.load()
                rgb = rendered.convert("RGB")
                background = Image.new("RGB", rgb.size, rgb.getpixel((0, 0)))
                content_box = ImageChops.difference(rgb, background).getbbox()
                if content_box is None:
                    return image_path
                left = max(0, content_box[0] - padding)
                top = max(0, content_box[1] - padding)
                right = min(rendered.width, content_box[2] + padding)
                bottom = min(rendered.height, content_box[3] + padding)
                crop_box = (left, top, right, bottom)
                if crop_box == (0, 0, rendered.width, rendered.height):
                    return image_path
                cropped = rendered.crop(crop_box)
                output = source.with_name(f"{source.stem}_cropped.png")
                cropped.save(output, format="PNG", optimize=True)
            source.unlink(missing_ok=True)
            return str(output)
        except Exception as exc:
            self.logger.warning("裁剪群身份图片空白失败 path=%s: %s", source, exc)
            return image_path

    @filter.command_group("群身份")
    def group_identity(self):
        """管理当前 QQ 群的成员身份。"""

    @group_identity.command("add", alias={"添加"})
    async def group_identity_add(
        self,
        event: AstrMessageEvent,
        payload: GreedyStr,
    ):
        """为指定群成员添加身份，仅管理员可用。"""

        try:
            (
                _session_key,
                _platform_id,
                group_id,
                platform,
            ) = await self._ensure_command_profile(event)
            if not await self._admin_command_allowed(event, platform, group_id):
                yield event.plain_result("失败：你没有权限执行该指令。")
                return
            target_id, expression = self._target_and_expression(event, payload)
            result = await self._mutate_member_identity(
                event,
                target_id=target_id,
                expression=expression,
                remove=False,
                self_service=False,
            )
            yield event.plain_result(result)
        except ValueError as exc:
            yield event.plain_result(f"失败：{exc}")
        except Exception:
            self.logger.exception("群身份 add 指令执行失败。")
            yield event.plain_result("失败：插件内部错误。")

    @group_identity.command("remove", alias={"删除", "rm"})
    async def group_identity_remove(
        self,
        event: AstrMessageEvent,
        payload: GreedyStr,
    ):
        """删除指定群成员的身份，仅管理员可用。"""

        try:
            (
                _session_key,
                _platform_id,
                group_id,
                platform,
            ) = await self._ensure_command_profile(event)
            if not await self._admin_command_allowed(event, platform, group_id):
                yield event.plain_result("失败：你没有权限执行该指令。")
                return
            target_id, expression = self._target_and_expression(event, payload)
            result = await self._mutate_member_identity(
                event,
                target_id=target_id,
                expression=expression,
                remove=True,
                self_service=False,
            )
            yield event.plain_result(result)
        except ValueError as exc:
            yield event.plain_result(f"失败：{exc}")
        except Exception:
            self.logger.exception("群身份 remove 指令执行失败。")
            yield event.plain_result("失败：插件内部错误。")

    @group_identity.command("me", alias={"我"})
    async def group_identity_me_add(
        self,
        event: AstrMessageEvent,
        expression: GreedyStr,
    ):
        """为自己添加身份，自定义标签仅管理员可用。"""

        try:
            result = await self._mutate_member_identity(
                event,
                target_id=normalize_id(event.get_sender_id()),
                expression=expression,
                remove=False,
                self_service=True,
            )
            yield event.plain_result(result)
        except ValueError as exc:
            yield event.plain_result(f"失败：{exc}")
        except Exception:
            self.logger.exception("群身份 me 指令执行失败。")
            yield event.plain_result("失败：插件内部错误。")

    @group_identity.command("merm", alias={"我删"})
    async def group_identity_me_remove(
        self,
        event: AstrMessageEvent,
        expression: GreedyStr,
    ):
        """删除自己的身份，自定义标签仅管理员可用。"""

        try:
            result = await self._mutate_member_identity(
                event,
                target_id=normalize_id(event.get_sender_id()),
                expression=expression,
                remove=True,
                self_service=True,
            )
            yield event.plain_result(result)
        except ValueError as exc:
            yield event.plain_result(f"失败：{exc}")
        except Exception:
            self.logger.exception("群身份 merm 指令执行失败。")
            yield event.plain_result("失败：插件内部错误。")

    @group_identity.command("list", alias={"查看"})
    async def group_identity_list(
        self,
        event: AstrMessageEvent,
        target: str = "",
    ):
        """以图片列出指定群成员的身份。"""

        try:
            (
                session_key,
                _platform_id,
                group_id,
                platform,
            ) = await self._ensure_command_profile(event)
            target_id = self._list_target(event, target)
            remote_member = await self._fetch_group_member(
                platform,
                group_id,
                target_id,
            )
            profile = self._stored_sessions().get(session_key)
            if not isinstance(profile, Mapping):
                raise ValueError("本群身份资料不存在。")
            saved_members = profile.get("members", [])
            member = merge_remote_members(
                [remote_member],
                saved_members if isinstance(saved_members, list) else [],
            )[0]
            fields = self._identity_card_fields(
                member,
                self._profile_custom_identity_fields(profile),
            )
            display_name = member.get("card") or member.get("nickname") or target_id
            avatar_data_url = await self._download_identity_avatar(target_id)
            image = await self.html_render(
                IDENTITY_CARD_TEMPLATE,
                {
                    "user_id": target_id,
                    "display_name": display_name,
                    "avatar_data_url": avatar_data_url,
                    "avatar_text": str(display_name)[:2],
                    "fields": fields,
                },
                return_url=False,
                options={
                    "type": "png",
                    "full_page": True,
                    "animations": "disabled",
                    "scale": "device",
                },
            )
            image = await asyncio.to_thread(
                self._crop_rendered_card_image,
                image,
                12,
            )
            yield event.image_result(image)
        except ValueError as exc:
            yield event.plain_result(f"失败：{exc}")
        except Exception:
            self.logger.exception("群身份 list 指令执行失败。")
            yield event.plain_result("失败：身份卡片生成失败。")

    @group_identity.group("tag", alias={"标签"})
    def group_identity_tag(self):
        """管理本群自定义身份标签，仅管理员可用。"""

    @group_identity_tag.command("add", alias={"添加"})
    async def group_identity_tag_add(
        self,
        event: AstrMessageEvent,
        label: GreedyStr,
    ):
        """添加本群自定义身份标签，仅管理员可用。"""

        try:
            yield event.plain_result(
                await self._mutate_group_tag(event, label, remove=False)
            )
        except ValueError as exc:
            yield event.plain_result(f"失败：{exc}")
        except Exception:
            self.logger.exception("群身份 tag add 指令执行失败。")
            yield event.plain_result("失败：插件内部错误。")

    @group_identity_tag.command("remove", alias={"删除", "rm"})
    async def group_identity_tag_remove(
        self,
        event: AstrMessageEvent,
        label: GreedyStr,
    ):
        """删除本群自定义身份标签，仅管理员可用。"""

        try:
            yield event.plain_result(
                await self._mutate_group_tag(event, label, remove=True)
            )
        except ValueError as exc:
            yield event.plain_result(f"失败：{exc}")
        except Exception:
            self.logger.exception("群身份 tag remove 指令执行失败。")
            yield event.plain_result("失败：插件内部错误。")

    @group_identity.command("on", alias={"开启"})
    async def group_identity_on(self, event: AstrMessageEvent):
        """开启本群身份注入，仅管理员可用。"""

        try:
            yield event.plain_result(await self._set_group_injection(event, True))
        except ValueError as exc:
            yield event.plain_result(f"失败：{exc}")
        except Exception:
            self.logger.exception("群身份 on 指令执行失败。")
            yield event.plain_result("失败：插件内部错误。")

    @group_identity.command("off", alias={"关闭"})
    async def group_identity_off(self, event: AstrMessageEvent):
        """关闭本群身份注入，仅管理员可用。"""

        try:
            yield event.plain_result(await self._set_group_injection(event, False))
        except ValueError as exc:
            yield event.plain_result(f"失败：{exc}")
        except Exception:
            self.logger.exception("群身份 off 指令执行失败。")
            yield event.plain_result("失败：插件内部错误。")

    @group_identity.command("help", alias={"帮助"})
    async def group_identity_help(self, event: AstrMessageEvent):
        """发送预渲染的群身份指令帮助图片。"""

        if not HELP_CARD_IMAGE_PATH.is_file():
            self.logger.error("群身份帮助图片不存在 path=%s", HELP_CARD_IMAGE_PATH)
            yield event.plain_result("失败：帮助图片不存在，请联系插件管理员。")
            return
        yield event.image_result(str(HELP_CARD_IMAGE_PATH))

    @filter.on_llm_request()
    async def inject_member_context(
        self,
        event: AstrMessageEvent,
        req: ProviderRequest,
    ) -> None:
        """Append only the identity profile belonging to this exact group session."""

        report: dict[str, Any] = {
            "status": "skipped",
            "reason": "not_started",
            "message_type": "",
            "platform_id": "",
            "group_id": "",
            "session_key": "",
            "profile_member_count": 0,
            "configured_member_count": 0,
            "window_message_count": 0,
            "window_limit": 0,
            "window_speaker_ids": [],
            "window_direct_mention_ids": [],
            "injected_member_ids": [],
            "match_reasons": {},
            "usage_rules_customized": False,
            "prompt_injected": False,
            "prompt_length": 0,
            "relationship_edge_count": 0,
            "bot_relationship_count": 0,
            "bot_prompt_injected": False,
            "bot_prompt_length": 0,
        }
        prompt = ""
        bot_prompt = ""
        try:
            group_id = normalize_id(event.get_group_id())
            report["group_id"] = group_id
            if not group_id:
                report["reason"] = "missing_group_id"
                return
            message_type = event.get_message_type()
            report["message_type"] = str(getattr(message_type, "value", message_type))
            if message_type not in (
                MessageType.GROUP_MESSAGE,
                MessageType.GROUP_MESSAGE.value,
            ):
                report["reason"] = "not_group_message"
                return

            platform_id = clean_text(
                event.get_platform_id() or event.get_platform_name(),
                max_length=128,
            )
            report["platform_id"] = platform_id
            if not platform_id:
                report["reason"] = "missing_platform_id"
                return
            session_key = build_session_key(platform_id, group_id)
            report["session_key"] = session_key

            await self._ensure_store_loaded()
            profile = self._stored_sessions().get(session_key)
            if not isinstance(profile, Mapping):
                report["reason"] = "profile_not_found"
                return
            if not normalize_enabled(profile.get("injection_enabled"), default=True):
                report["reason"] = "group_injection_disabled"
                return
            profile_members = profile.get("members", [])
            if isinstance(profile_members, list):
                report["profile_member_count"] = len(profile_members)
                report["configured_member_count"] = sum(
                    1
                    for member in profile_members
                    if isinstance(member, Mapping) and has_custom_identity(member)
                )
            normalized_usage_rules = normalize_usage_rules(
                profile.get("usage_rules", DEFAULT_USAGE_RULES)
            )
            report["usage_rules_customized"] = (
                normalized_usage_rules != DEFAULT_USAGE_RULES
            )
            custom_identity_fields = self._profile_custom_identity_fields(profile)
            window_messages = await self._record_group_message_window(
                event,
                session_key,
                platform_id,
            )
            report["window_message_count"] = len(window_messages)
            report["window_limit"] = self._configured_message_window_size()
            (
                report["window_speaker_ids"],
                report["window_direct_mention_ids"],
            ) = self._window_report_ids(window_messages)
            self_id = normalize_id(event.get_self_id())
            active_members, match_reasons = select_members_for_window(
                profile_members,
                window_messages,
                custom_identity_fields=custom_identity_fields,
                exclude_user_ids=[self_id] if self_id else [],
            )
            report["injected_member_ids"] = [
                member["user_id"] for member in active_members
            ]
            report["match_reasons"] = self._match_reasons_for_log(match_reasons)
            graph = normalize_relationship_graph(profile)
            participant_ids = collect_window_participant_ids(
                window_messages,
                profile_members,
                custom_identity_fields=custom_identity_fields,
                exclude_user_ids=[self_id] if self_id else [],
            )
            if graph["relationship_injection_enabled"]:
                selection = select_relationships_for_window(
                    graph,
                    window_participant_ids=participant_ids,
                )
                report["relationship_edge_count"] = len(selection["peer_edges"])
                report["bot_relationship_count"] = len(selection["bot_edges"])
            prompt, bot_prompt = self._build_profile_prompts(
                profile,
                self_id=self_id,
                window_messages=window_messages,
                match_reasons=match_reasons,
                active_members=active_members,
            )
            report["prompt_length"] = len(prompt)
            report["bot_prompt_length"] = len(bot_prompt)
            if not prompt and not bot_prompt:
                report["reason"] = "no_matching_member_or_custom_usage_rules"
                return

            parts = getattr(req, "extra_user_content_parts", None)
            if parts is None:
                req.extra_user_content_parts = []
                parts = req.extra_user_content_parts
            existing_texts = [
                part.text
                for part in parts
                if isinstance(getattr(part, "text", None), str)
            ]
            if any(
                text.startswith(PROMPT_MARKER) or text.startswith(BOT_PROMPT_MARKER)
                for text in existing_texts
            ):
                report["status"] = "duplicate"
                report["reason"] = "prompt_marker_already_present"
                return
            if prompt:
                parts.append(TextPart(text=prompt).mark_as_temp())
                report["prompt_injected"] = True
            if bot_prompt:
                parts.append(TextPart(text=bot_prompt).mark_as_temp())
                report["bot_prompt_injected"] = True
            report["status"] = "injected"
            if active_members:
                report["reason"] = "matched_members"
            elif report["relationship_edge_count"] or report["bot_relationship_count"]:
                report["reason"] = "relationships_only"
            else:
                report["reason"] = "usage_rules_only"
        except Exception:
            report["status"] = "error"
            report["reason"] = "exception"
            # A plugin context helper must never make the main LLM request fail.
            self.logger.exception("注入群成员身份上下文失败。")
        finally:
            self._log_llm_injection_report(report, prompt, bot_prompt)
