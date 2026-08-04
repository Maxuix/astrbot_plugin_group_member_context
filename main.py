"""Per-QQ-group member identity context plugin for AstrBot."""

from __future__ import annotations

import asyncio
import copy
import inspect
import json
from collections import deque
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from astrbot.api import AstrBotConfig
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.platform import MessageType
from astrbot.api.provider import ProviderRequest
from astrbot.api.star import Context, Star
from astrbot.api.web import error_response, json_response, request
from astrbot.core.agent.message import TextPart

from .member_context import (
    DEFAULT_MESSAGE_WINDOW_SIZE,
    LOG_DETAIL_FULL,
    MAX_MESSAGE_WINDOW_SIZE,
    STORE_VERSION,
    build_identity_prompt,
    build_session_key,
    clean_text,
    clear_member_identity,
    has_custom_identity,
    merge_remote_members,
    normalize_custom_identity_fields,
    normalize_custom_prompt,
    normalize_id,
    normalize_log_detail,
    normalize_member_list,
    normalize_message_window_size,
    normalize_store,
    select_members_for_window,
)

PLUGIN_NAME = "astrbot_plugin_group_member_context"
STORE_KEY = "group_member_profiles"
PROMPT_MARKER = "<group_member_identity_context>"
LLM_INJECTION_LOG_MARKER = "astrbot_plugin_group_member_context.llm_injection"
WINDOW_RECORDED_EXTRA = "_group_member_context_window_recorded"
MAX_WINDOW_MESSAGE_TEXT_LENGTH = 4000


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
        self._store_lock = asyncio.Lock()
        self._store_loaded = False
        self._store: dict[str, Any] = {"version": STORE_VERSION, "sessions": {}}
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
            self._store_loaded = True

    async def _persist_store(self) -> None:
        await self.put_kv_data(STORE_KEY, self._store)

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

    def _custom_identity_fields(self) -> list[str]:
        return normalize_custom_identity_fields(
            self._store.get("custom_identity_fields", [])
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

    def _log_llm_injection_report(
        self,
        report: Mapping[str, Any],
        prompt: str = "",
    ) -> None:
        """Write one compact JSON report through AstrBot's plugin logger."""

        try:
            payload = dict(report)
            if self._configured_log_detail() == LOG_DETAIL_FULL:
                payload["prompt"] = prompt
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
    ) -> tuple[str, dict[str, Any], list[str]]:
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
            "custom_prompt": normalize_custom_prompt(payload.get("custom_prompt")),
            "message_window_size": normalize_message_window_size(
                payload.get("message_window_size", DEFAULT_MESSAGE_WINDOW_SIZE)
            ),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        return session_key, profile, custom_identity_fields

    @staticmethod
    def _group_label(profile: Mapping[str, Any]) -> str:
        return clean_text(profile.get("group_name"), max_length=200) or str(
            profile.get("group_id", "")
        )

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
                        "has_profile": bool(
                            normalize_custom_prompt(saved_profile.get("custom_prompt"))
                            or any(
                                has_custom_identity(member)
                                for member in saved_profile.get("members", [])
                                if isinstance(member, Mapping)
                            )
                        ),
                        "member_count": len(saved_profile.get("members", [])),
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
                    "has_profile": bool(
                        normalize_custom_prompt(profile.get("custom_prompt"))
                        or any(
                            has_custom_identity(member)
                            for member in profile.get("members", [])
                            if isinstance(member, Mapping)
                        )
                    ),
                    "member_count": len(profile.get("members", [])),
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
        return json_response(
            {
                "session_key": session_key,
                "platform_id": platform_id,
                "group_id": group_id,
                "group_name": group_name,
                "members": members,
                "custom_identity_fields": self._custom_identity_fields(),
                "custom_prompt": normalize_custom_prompt(
                    profile.get("custom_prompt") if isinstance(profile, Mapping) else ""
                ),
                "message_window_size": self._configured_message_window_size(),
            }
        )

    async def save_profile(self):
        """Persist a group profile and return the generated prompt for verification."""

        payload = await request.json(default={})
        if not isinstance(payload, Mapping):
            return error_response("请求数据格式错误。", status_code=400)
        try:
            session_key, profile, custom_identity_fields = self._profile_from_payload(
                payload
            )
            prompt = build_identity_prompt(
                group_id=profile["group_id"],
                group_name=profile["group_name"],
                members=profile["members"],
                custom_prompt=profile["custom_prompt"],
                custom_identity_fields=custom_identity_fields,
            )
        except ValueError as exc:
            return error_response(str(exc), status_code=400)

        await self._ensure_store_loaded()
        async with self._store_lock:
            self._store["custom_identity_fields"] = custom_identity_fields
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
                "custom_prompt_enabled": bool(profile["custom_prompt"]),
                "custom_identity_fields": custom_identity_fields,
                "message_window_size": self._configured_message_window_size(),
                "prompt": prompt,
            }
        )

    async def reset_profile(self):
        """Clear all member identity data and the custom prompt for one group."""

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
                "custom_prompt": "",
                "message_window_size": self._configured_message_window_size(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            sessions[session_key] = reset_profile
            await self._persist_store()

        return json_response(
            {
                "reset": True,
                "session_key": session_key,
                "member_count": len(reset_members),
                "configured_member_count": 0,
                "custom_prompt_enabled": False,
                "members": reset_members,
                "custom_identity_fields": self._custom_identity_fields(),
                "message_window_size": self._configured_message_window_size(),
            }
        )

    async def preview_profile(self):
        """Generate a prompt without changing persistent data."""

        payload = await request.json(default={})
        if not isinstance(payload, Mapping):
            return error_response("请求数据格式错误。", status_code=400)
        try:
            _, profile, custom_identity_fields = self._profile_from_payload(payload)
            prompt = build_identity_prompt(
                group_id=profile["group_id"],
                group_name=profile["group_name"],
                members=profile["members"],
                custom_prompt=profile["custom_prompt"],
                custom_identity_fields=custom_identity_fields,
            )
        except ValueError as exc:
            return error_response(str(exc), status_code=400)
        return json_response(
            {
                "prompt": prompt,
                "custom_identity_fields": custom_identity_fields,
                "message_window_size": self._configured_message_window_size(),
            }
        )

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
            "custom_prompt": False,
            "prompt_injected": False,
            "prompt_length": 0,
        }
        prompt = ""
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
            profile_members = profile.get("members", [])
            if isinstance(profile_members, list):
                report["profile_member_count"] = len(profile_members)
                report["configured_member_count"] = sum(
                    1
                    for member in profile_members
                    if isinstance(member, Mapping) and has_custom_identity(member)
                )
            normalized_custom_prompt = normalize_custom_prompt(
                profile.get("custom_prompt", "")
            )
            report["custom_prompt"] = bool(normalized_custom_prompt)
            custom_identity_fields = self._custom_identity_fields()
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
            active_members, match_reasons = select_members_for_window(
                profile_members,
                window_messages,
                custom_identity_fields=custom_identity_fields,
            )
            report["injected_member_ids"] = [
                member["user_id"] for member in active_members
            ]
            report["match_reasons"] = self._match_reasons_for_log(match_reasons)
            prompt = build_identity_prompt(
                group_id=group_id,
                group_name=profile.get("group_name", ""),
                members=active_members,
                custom_prompt=normalized_custom_prompt,
                match_reasons=match_reasons,
                custom_identity_fields=custom_identity_fields,
            )
            report["prompt_length"] = len(prompt)
            if not prompt:
                report["reason"] = "no_matching_member_or_custom_prompt"
                return

            parts = getattr(req, "extra_user_content_parts", None)
            if parts is None:
                req.extra_user_content_parts = []
                parts = req.extra_user_content_parts
            if any(
                isinstance(getattr(part, "text", None), str)
                and part.text.startswith(PROMPT_MARKER)
                for part in parts
            ):
                report["status"] = "duplicate"
                report["reason"] = "prompt_marker_already_present"
                return
            parts.append(TextPart(text=prompt).mark_as_temp())
            report["status"] = "injected"
            report["reason"] = (
                "matched_members" if active_members else "custom_prompt_only"
            )
            report["prompt_injected"] = True
        except Exception:
            report["status"] = "error"
            report["reason"] = "exception"
            # A plugin context helper must never make the main LLM request fail.
            self.logger.exception("注入群成员身份上下文失败。")
        finally:
            self._log_llm_injection_report(report, prompt)
