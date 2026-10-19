"""Tests for ``evoflow.runtime.ports.get_channel_service`` port resolver.

Regression test for: ``AttributeError: 'function' object has no attribute 'restart_channel'``
when proactive / wecom_binding called ``service.restart_channel()`` but ``service``
was the factory function registered by ``runtime_adapters.py``.

Two layers need to keep working:

1. App process path: the port holds a callable factory; calling the port must
   resolve to the actual singleton (or ``None`` if not started).
2. Off-process path (langgraph-only / harness tests): no adapter registered;
   the port must return ``None`` so the proactive module's restart helpers noop
   cleanly instead of crashing.
"""

from __future__ import annotations

import pytest

import evoflow.runtime.ports as ports


@pytest.fixture(autouse=True)
def _reset_ports_registry():
    """Reset ``ports._impls`` so each test starts from a clean state."""
    ports._impls.clear()
    yield
    ports._impls.clear()


def test_no_adapter_returns_none():
    assert ports.get_channel_service() is None


def test_callable_factory_is_resolved():
    """Runtime adapter registers a callable factory; the port must call it."""
    sentinel = object()

    def factory():
        return sentinel

    ports.register("channels.service", factory)
    assert ports.get_channel_service() is sentinel


def test_callable_factory_returning_none_passes_through():
    """When the factory itself returns ``None`` (service not started), we report None."""

    def factory():
        return None

    ports.register("channels.service", factory)
    assert ports.get_channel_service() is None


def test_callable_factory_raising_exception_returns_none():
    """A misbehaving factory must not propagate — proactive modules rely on graceful noop."""

    def factory():
        raise RuntimeError("boom")

    ports.register("channels.service", factory)
    assert ports.get_channel_service() is None


def test_instance_registration_is_returned_as_is():
    """Legacy direct-instance registration (e.g. tests injecting a ChannelService) still works."""
    sentinel = object()
    ports.register("channels.service", sentinel)
    assert ports.get_channel_service() is sentinel


@pytest.mark.asyncio
async def test_resolved_service_exposes_methods():
    """End-to-end shape check: a fake service with restart_channel round-trips through the port."""

    class _FakeService:
        def __init__(self):
            self.restarted = []

        async def restart_channel(self, name: str) -> bool:
            self.restarted.append(name)
            return True

    fake = _FakeService()
    ports.register("channels.service", lambda: fake)
    resolved = ports.get_channel_service()
    assert resolved is fake
    assert await resolved.restart_channel("wecom") is True
    assert fake.restarted == ["wecom"]
