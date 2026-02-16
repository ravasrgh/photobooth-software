"""Unit tests for the BoothStateMachine."""

import pytest
from hw_controller.core.state_machine import (
    BoothStateMachine,
    InvalidTransitionError,
    State,
    Trigger,
)


@pytest.fixture
def sm():
    """Create a fresh state machine."""
    return BoothStateMachine()


@pytest.fixture
def sm_with_callback():
    """State machine that records transition events."""
    events = []

    async def on_transition(prev, next_state, trigger, context):
        events.append((prev, next_state, trigger, context))

    machine = BoothStateMachine(on_transition=on_transition)
    return machine, events


# ── Initial state ───────────────────────────────────────────────────

class TestInitialState:
    def test_starts_in_initializing(self, sm):
        assert sm.state == State.INITIALIZING

    def test_error_context_is_none(self, sm):
        assert sm.error_context is None


# ── Valid transitions ───────────────────────────────────────────────

class TestValidTransitions:
    @pytest.mark.asyncio
    async def test_hardware_ready(self, sm):
        result = await sm.fire(Trigger.HARDWARE_READY)
        assert result == State.IDLE
        assert sm.state == State.IDLE

    @pytest.mark.asyncio
    async def test_full_happy_path(self, sm):
        """Walk through a complete session: INIT → IDLE → … → IDLE."""
        await sm.fire(Trigger.HARDWARE_READY)
        assert sm.state == State.IDLE

        await sm.fire(Trigger.SESSION_START)
        assert sm.state == State.COUNTDOWN

        await sm.fire(Trigger.COUNTDOWN_DONE)
        assert sm.state == State.CAPTURING

        await sm.fire(Trigger.CAPTURE_DONE)
        assert sm.state == State.PROCESSING

        await sm.fire(Trigger.PROCESSING_DONE)
        assert sm.state == State.REVIEW

        await sm.fire(Trigger.PRINT_REQUESTED)
        assert sm.state == State.PRINTING

        await sm.fire(Trigger.PRINT_DONE)
        assert sm.state == State.IDLE

    @pytest.mark.asyncio
    async def test_multi_photo_session(self, sm):
        """Take multiple photos by cycling REVIEW → COUNTDOWN → CAPTURE → …"""
        await sm.fire(Trigger.HARDWARE_READY)
        await sm.fire(Trigger.SESSION_START)
        await sm.fire(Trigger.COUNTDOWN_DONE)
        await sm.fire(Trigger.CAPTURE_DONE)
        await sm.fire(Trigger.PROCESSING_DONE)
        assert sm.state == State.REVIEW

        # Take another photo
        await sm.fire(Trigger.NEXT_PHOTO)
        assert sm.state == State.COUNTDOWN

        await sm.fire(Trigger.COUNTDOWN_DONE)
        await sm.fire(Trigger.CAPTURE_DONE)
        await sm.fire(Trigger.PROCESSING_DONE)
        assert sm.state == State.REVIEW

        # Complete without printing
        await sm.fire(Trigger.SESSION_COMPLETE)
        assert sm.state == State.IDLE

    @pytest.mark.asyncio
    async def test_session_cancel(self, sm):
        await sm.fire(Trigger.HARDWARE_READY)
        await sm.fire(Trigger.SESSION_START)
        assert sm.state == State.COUNTDOWN

        await sm.fire(Trigger.SESSION_CANCEL)
        assert sm.state == State.IDLE


# ── Error handling ──────────────────────────────────────────────────

class TestErrorHandling:
    @pytest.mark.asyncio
    async def test_capture_fail_goes_to_error(self, sm):
        await sm.fire(Trigger.HARDWARE_READY)
        await sm.fire(Trigger.SESSION_START)
        await sm.fire(Trigger.COUNTDOWN_DONE)
        assert sm.state == State.CAPTURING

        error_ctx = {"error_code": "CAMERA_DISCONNECTED", "message": "USB unplugged"}
        await sm.fire(Trigger.CAPTURE_FAIL, context=error_ctx)
        assert sm.state == State.ERROR
        assert sm.error_context == error_ctx

    @pytest.mark.asyncio
    async def test_error_resolved_goes_to_idle(self, sm):
        await sm.fire(Trigger.HARDWARE_FAIL, context={"error": "no camera"})
        assert sm.state == State.ERROR

        await sm.fire(Trigger.ERROR_RESOLVED)
        assert sm.state == State.IDLE
        assert sm.error_context is None

    @pytest.mark.asyncio
    async def test_error_restart(self, sm):
        await sm.fire(Trigger.HARDWARE_FAIL)
        assert sm.state == State.ERROR

        await sm.fire(Trigger.RESTART)
        assert sm.state == State.INITIALIZING

    @pytest.mark.asyncio
    async def test_hardware_fail_at_startup(self, sm):
        await sm.fire(Trigger.HARDWARE_FAIL)
        assert sm.state == State.ERROR

    @pytest.mark.asyncio
    async def test_print_fail(self, sm):
        await sm.fire(Trigger.HARDWARE_READY)
        await sm.fire(Trigger.SESSION_START)
        await sm.fire(Trigger.COUNTDOWN_DONE)
        await sm.fire(Trigger.CAPTURE_DONE)
        await sm.fire(Trigger.PROCESSING_DONE)
        await sm.fire(Trigger.PRINT_REQUESTED)

        await sm.fire(Trigger.PRINT_FAIL, context={"error": "out of paper"})
        assert sm.state == State.ERROR


# ── Invalid transitions ────────────────────────────────────────────

class TestInvalidTransitions:
    @pytest.mark.asyncio
    async def test_cannot_capture_from_idle(self, sm):
        await sm.fire(Trigger.HARDWARE_READY)
        with pytest.raises(InvalidTransitionError):
            await sm.fire(Trigger.CAPTURE_DONE)

    @pytest.mark.asyncio
    async def test_cannot_start_session_from_initializing(self, sm):
        with pytest.raises(InvalidTransitionError):
            await sm.fire(Trigger.SESSION_START)

    @pytest.mark.asyncio
    async def test_cannot_print_from_idle(self, sm):
        await sm.fire(Trigger.HARDWARE_READY)
        with pytest.raises(InvalidTransitionError):
            await sm.fire(Trigger.PRINT_DONE)


# ── Utility methods ─────────────────────────────────────────────────

class TestUtilityMethods:
    @pytest.mark.asyncio
    async def test_can_fire(self, sm):
        assert sm.can_fire(Trigger.HARDWARE_READY) is True
        assert sm.can_fire(Trigger.SESSION_START) is False

    @pytest.mark.asyncio
    async def test_available_triggers(self, sm):
        triggers = sm.available_triggers()
        assert Trigger.HARDWARE_READY in triggers
        assert Trigger.HARDWARE_FAIL in triggers
        assert Trigger.SESSION_START not in triggers

    @pytest.mark.asyncio
    async def test_to_dict(self, sm):
        d = sm.to_dict()
        assert d["state"] == "INITIALIZING"
        assert d["error_context"] is None
        assert isinstance(d["available_triggers"], list)


# ── Callback ────────────────────────────────────────────────────────

class TestCallback:
    @pytest.mark.asyncio
    async def test_callback_fires(self, sm_with_callback):
        sm, events = sm_with_callback
        await sm.fire(Trigger.HARDWARE_READY)
        assert len(events) == 1
        prev, next_s, trigger, ctx = events[0]
        assert prev == State.INITIALIZING
        assert next_s == State.IDLE
        assert trigger == Trigger.HARDWARE_READY

    @pytest.mark.asyncio
    async def test_callback_receives_context(self, sm_with_callback):
        sm, events = sm_with_callback
        ctx = {"cameras": 1}
        await sm.fire(Trigger.HARDWARE_READY, context=ctx)
        assert events[0][3] == ctx
