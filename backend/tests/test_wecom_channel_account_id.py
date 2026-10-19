"""Unit tests for WecomChannel ``account_id`` per-employee binding.

Step 1 of the wecom-accounts refactor. These tests lock down the **minimum
contract** that downstream steps (ChannelService multi-instance, manager routing,
panel UI) will rely on:

Invariant 2 (no employee bound → main agent):
    * ``account_id == ""`` (primary bot) emits ``InboundMessage.metadata["account_id"] == ""``
      so ChannelManager's default fall-through delivers the message to ``lead_agent``.

Anti-collision between bots:
    * Two channel instances (different ``account_id``) must not share dedup,
      reply-req-id, or last-chat-req-id caches.

Backwards compatibility:
    * Old call sites that pass only ``(bus, config)`` keep the empty account_id
      and behave identically to the pre-refactor code path.

No real network access: we exercise ``_on_message`` directly with synthetic
``aibot_msg_callback`` payloads — same shape as production code receives from
the WeCom WebSocket.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from app.channels.message_bus import MessageBus
from app.channels.wecom import WecomChannel


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_channel(bus: MessageBus, account_id: str = "") -> WecomChannel:
    """Construct a WecomChannel that shares the supplied MessageBus and never starts a real WebSocket.

    The text-batching delay is zeroed so ``_on_message`` publishes immediately
    instead of waiting 0.6s — these tests assert behavior synchronously.
    """
    config: dict[str, Any] = {
        # Credentials are required by __init__ but we never call .start()
        # in these unit tests, so they only need to be non-empty.
        "bot_id": f"bot-{account_id or 'primary'}",
        "secret": "test-secret",
    }
    channel = WecomChannel(bus=bus, config=config, account_id=account_id)
    # Flush text batches immediately in tests.
    channel._text_batch_delay_seconds = 0.0
    channel._text_batch_split_delay_seconds = 0.0
    return channel


def _dm_payload(msgid: str, sender_id: str = "user-A", text: str = "hello") -> dict[str, Any]:
    """Build a synthetic ``aibot_msg_callback`` body for a DM (no ``chattype``)."""
    return {
        "msgid": msgid,
        "chattype": "single",  # is_group = False in _on_message
        "from": {"userid": sender_id},
        "msgtype": "text",
        "text": {"content": text},
    }


def _wrapped_callback(body: dict[str, Any], req_id: str = "req-1") -> dict[str, Any]:
    """Wrap the body into the outer ``aibot_msg_callback`` envelope."""
    return {
        "cmd": "aibot_msg_callback",
        "headers": {"req_id": req_id},
        "body": body,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_default_account_id_is_empty_for_backwards_compatibility() -> None:
    """Old callers that pass only ``(bus, config)`` keep ``account_id == ""``."""
    channel = WecomChannel(bus=MessageBus(), config={"bot_id": "x", "secret": "y"})
    assert channel._account_id == ""


def test_account_id_is_stripped() -> None:
    """Whitespace-only / surrounding spaces collapse to ``""`` (primary)."""
    channel = WecomChannel(
        bus=MessageBus(),
        config={"bot_id": "x", "secret": "y"},
        account_id="   ",
    )
    assert channel._account_id == ""


@pytest.mark.asyncio
async def test_primary_bot_inbound_carries_empty_account_id() -> None:
    """Invariant 2: primary bot messages must carry ``metadata.account_id == ""``
    so ChannelManager's default fall-through routes them to ``lead_agent``."""
    bus = MessageBus()
    channel = _make_channel(bus, "")

    await channel._on_message(_wrapped_callback(_dm_payload("m-1", text="ping")))

    msg = await asyncio.wait_for(bus.get_inbound(timeout=2.0), timeout=2.5)
    assert msg.metadata["account_id"] == ""
    assert msg.metadata["chat_type"] == "dm"
    assert msg.text == "ping"


@pytest.mark.asyncio
async def test_employee_bot_inbound_carries_its_account_id() -> None:
    """Bound employee bot messages must carry the bound agent_code so the manager
    can route to that proactive role."""
    bus = MessageBus()
    channel = _make_channel(bus, "sales-bot")

    await channel._on_message(_wrapped_callback(_dm_payload("m-2", text="ping")))

    msg = await asyncio.wait_for(bus.get_inbound(timeout=2.0), timeout=2.5)
    assert msg.metadata["account_id"] == "sales-bot"


@pytest.mark.asyncio
async def test_two_bots_do_not_share_dedup_pool() -> None:
    """If the primary bot and an employee bot happen to see the same ``msgid``,
    each must dedup independently — otherwise cross-bot redeliveries cause
    one bot to silently drop a fresh message from the other."""
    bus = MessageBus()
    primary = _make_channel(bus, "")
    employee = _make_channel(bus, "sales-bot")

    # Same msgid arrives on both bots.
    payload = _wrapped_callback(_dm_payload("shared-msgid"))
    await primary._on_message(payload)
    await employee._on_message(payload)

    # Both should have published; if dedup collided, one would be silently dropped.
    a = await asyncio.wait_for(bus.get_inbound(timeout=2.0), timeout=2.5)
    b = await asyncio.wait_for(bus.get_inbound(timeout=2.0), timeout=2.5)
    seen = {a.metadata["account_id"], b.metadata["account_id"]}
    assert seen == {"", "sales-bot"}, f"expected one primary + one sales-bot inbound, got {seen}"


@pytest.mark.asyncio
async def test_employee_bot_dedups_its_own_redelivery() -> None:
    """A redelivered msgid on the same bot must still be deduped (regression)."""
    bus = MessageBus()
    employee = _make_channel(bus, "sales-bot")

    payload = _wrapped_callback(_dm_payload("dup-msgid"))
    await employee._on_message(payload)
    await employee._on_message(payload)  # redelivery → should be dropped

    msg = await asyncio.wait_for(bus.get_inbound(timeout=2.0), timeout=2.5)
    assert msg.metadata["account_id"] == "sales-bot"

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(bus.get_inbound(timeout=0.1), timeout=0.5)


@pytest.mark.asyncio
async def test_primary_bot_dedups_its_own_redelivery() -> None:
    """Regression: the original dedup behaviour still works for the primary bot
    when called with the legacy 2-arg constructor."""
    bus = MessageBus()
    primary = _make_channel(bus, "")

    payload = _wrapped_callback(_dm_payload("primary-dup"))
    await primary._on_message(payload)
    await primary._on_message(payload)

    msg = await asyncio.wait_for(bus.get_inbound(timeout=2.0), timeout=2.5)
    assert msg.metadata["account_id"] == ""

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(bus.get_inbound(timeout=0.1), timeout=0.5)


def test_reply_req_ids_are_namespaced_per_account() -> None:
    """Two bots must not collide when caching reply req_ids for the same msgid.

    We use ``_remember_reply_req_id`` + ``_reply_req_id_for_message`` directly
    because they encode the namespacing contract this test wants to lock down.
    """
    bus = MessageBus()
    primary = _make_channel(bus, "")
    employee = _make_channel(bus, "sales-bot")

    primary._remember_reply_req_id("msg-1", "req-primary")
    employee._remember_reply_req_id("msg-1", "req-employee")

    assert primary._reply_req_id_for_message("msg-1") == "req-primary"
    assert employee._reply_req_id_for_message("msg-1") == "req-employee"
    # Negative: a bot asking for the *other* bot's stored req_id should miss.
    assert primary._reply_req_id_for_message("msg-1") != "req-employee"


def test_chat_req_ids_are_namespaced_per_account() -> None:
    """Same contract as ``reply_req_ids`` for the last-chat fallback cache."""
    bus = MessageBus()
    primary = _make_channel(bus, "")
    employee = _make_channel(bus, "research-bot")

    primary._remember_chat_req_id("chat-X", "req-primary")
    employee._remember_chat_req_id("chat-X", "req-employee")

    # Same ``chat_id`` under two different bots must resolve to two different req_ids.
    assert primary._last_chat_req_ids.get(primary._account_key("chat-X")) == "req-primary"
    assert employee._last_chat_req_ids.get(employee._account_key("chat-X")) == "req-employee"


def test_account_key_prefix_is_stable_for_primary() -> None:
    """``_account_key`` must collapse empty ``account_id`` to a stable ``primary``
    prefix so cache keys are reproducible across restarts of the same bot."""
    bus = MessageBus()
    primary = _make_channel(bus, "")
    assert primary._account_key("anything") == "primary:anything"


def test_log_prefix_distinguishes_primary_from_employee() -> None:
    """Logs must make it obvious which bot a line belongs to — first line of
    defence when triaging cross-bot routing incidents."""
    bus = MessageBus()
    primary = _make_channel(bus, "")
    employee = _make_channel(bus, "sales-bot")
    assert primary._log_prefix() == "[Wecom:primary]"
    assert employee._log_prefix() == "[Wecom:sales-bot]"