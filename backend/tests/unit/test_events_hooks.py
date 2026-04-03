"""Tests for event bus and hook system."""

import pytest

from app.core.events import EventBus
from app.core.hooks import HookRegistry


# ── Event Bus tests ────────────────────────────────────────────────────────


class TestEventBus:
    @pytest.fixture
    def bus(self):
        b = EventBus()
        yield b
        b.clear()

    @pytest.mark.asyncio
    async def test_publish_and_subscribe(self, bus):
        received = []

        @bus.on("test.event")
        async def handler(event):
            received.append(event.data)

        await bus.publish("test.event", {"key": "value"})
        assert len(received) == 1
        assert received[0]["key"] == "value"

    @pytest.mark.asyncio
    async def test_multiple_handlers(self, bus):
        count = {"value": 0}

        @bus.on("test.event")
        async def handler1(event):
            count["value"] += 1

        @bus.on("test.event")
        async def handler2(event):
            count["value"] += 10

        await bus.publish("test.event")
        assert count["value"] == 11

    @pytest.mark.asyncio
    async def test_wildcard_handler(self, bus):
        events = []

        @bus.on("*")
        async def catch_all(event):
            events.append(event.name)

        await bus.publish("a.b.c")
        await bus.publish("x.y.z")
        assert events == ["a.b.c", "x.y.z"]

    @pytest.mark.asyncio
    async def test_no_handlers(self, bus):
        result = await bus.publish("nobody.listening")
        assert result.success
        assert len(result.handler_results) == 0

    @pytest.mark.asyncio
    async def test_handler_error_captured(self, bus):
        @bus.on("test.error")
        async def bad_handler(event):
            raise ValueError("oops")

        result = await bus.publish("test.error")
        assert not result.success
        assert len(result.errors) == 1
        assert result.errors[0]["type"] == "ValueError"

    @pytest.mark.asyncio
    async def test_unsubscribe(self, bus):
        count = {"value": 0}

        async def handler(event):
            count["value"] += 1

        bus.subscribe("test.event", handler)
        await bus.publish("test.event")
        assert count["value"] == 1

        bus.unsubscribe("test.event", handler)
        await bus.publish("test.event")
        assert count["value"] == 1  # no change

    def test_list_handlers(self, bus):
        @bus.on("test.a")
        async def h1(event): ...

        @bus.on("test.b")
        async def h2(event): ...

        handlers = bus.list_handlers()
        assert "test.a" in handlers
        assert "test.b" in handlers


# ── Hook tests ─────────────────────────────────────────────────────────────


class TestHookRegistry:
    @pytest.fixture
    def hooks(self):
        h = HookRegistry()
        yield h
        h.clear()

    @pytest.mark.asyncio
    async def test_filter_chain(self, hooks):
        @hooks.filter("transform", priority=10)
        async def add_prefix(data):
            return f"[prefix] {data}"

        @hooks.filter("transform", priority=20)
        async def add_suffix(data):
            return f"{data} [suffix]"

        result = await hooks.apply_filters("transform", "hello")
        assert result == "[prefix] hello [suffix]"

    @pytest.mark.asyncio
    async def test_filter_priority_order(self, hooks):
        order = []

        @hooks.filter("test", priority=30)
        async def third(data):
            order.append(3)
            return data

        @hooks.filter("test", priority=10)
        async def first(data):
            order.append(1)
            return data

        @hooks.filter("test", priority=20)
        async def second(data):
            order.append(2)
            return data

        await hooks.apply_filters("test", "x")
        assert order == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_action_execution(self, hooks):
        side_effects = []

        @hooks.action("after_save")
        async def log_save(item_id=None):
            side_effects.append(f"saved:{item_id}")

        await hooks.do_actions("after_save", item_id="123")
        assert side_effects == ["saved:123"]

    @pytest.mark.asyncio
    async def test_action_error_non_propagating(self, hooks):
        """Actions should log errors but not propagate them."""

        @hooks.action("risky")
        async def bad_action():
            raise RuntimeError("boom")

        @hooks.action("risky")
        async def good_action():
            pass  # should still execute

        # Should not raise
        await hooks.do_actions("risky")

    @pytest.mark.asyncio
    async def test_filter_error_propagates(self, hooks):
        """Filter errors should propagate (they're in the critical path)."""

        @hooks.filter("critical")
        async def bad_filter(data):
            raise ValueError("bad data")

        with pytest.raises(ValueError, match="bad data"):
            await hooks.apply_filters("critical", "test")

    @pytest.mark.asyncio
    async def test_no_filters_returns_original(self, hooks):
        result = await hooks.apply_filters("nonexistent", {"key": "value"})
        assert result == {"key": "value"}

    def test_list_filters_and_actions(self, hooks):
        @hooks.filter("f1", priority=5)
        async def filt(data):
            return data

        @hooks.action("a1", priority=10)
        async def act(): ...

        assert "f1" in hooks.list_filters()
        assert "a1" in hooks.list_actions()
