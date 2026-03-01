"""Unit tests for the BoothStateMachine (13-state FSM)."""

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


# ── Helpers ─────────────────────────────────────────────────────────

async def _advance_to_idle(sm):
    """INITIALIZING → IDLE."""
    await sm.fire(Trigger.HARDWARE_READY)

async def _advance_to_onboarding(sm):
    """→ ONBOARDING."""
    await _advance_to_idle(sm)
    await sm.fire(Trigger.SESSION_START)

async def _advance_to_payment(sm):
    """→ AWAITING_PAYMENT."""
    await _advance_to_onboarding(sm)
    await sm.fire(Trigger.ONBOARDING_DONE)

async def _advance_to_capture_setup(sm):
    """→ CAPTURE_SETUP."""
    await _advance_to_payment(sm)
    await sm.fire(Trigger.PAYMENT_CONFIRMED)

async def _advance_to_countdown(sm):
    """→ COUNTDOWN."""
    await _advance_to_capture_setup(sm)
    await sm.fire(Trigger.CAPTURE_SETUP_READY)

async def _advance_to_processing(sm):
    """→ PROCESSING (after first capture)."""
    await _advance_to_countdown(sm)
    await sm.fire(Trigger.COUNTDOWN_DONE)
    await sm.fire(Trigger.CAPTURE_DONE)

async def _advance_to_customization(sm):
    """→ CUSTOMIZATION."""
    await _advance_to_processing(sm)
    await sm.fire(Trigger.ALL_PHOTOS_DONE)

async def _advance_to_preview(sm):
    """→ PREVIEW."""
    await _advance_to_customization(sm)
    await sm.fire(Trigger.CUSTOMIZATION_DONE)

async def _advance_to_printing(sm):
    """→ PRINTING."""
    await _advance_to_preview(sm)
    await sm.fire(Trigger.PRINT_REQUESTED)

async def _advance_to_complete(sm):
    """→ COMPLETE."""
    await _advance_to_printing(sm)
    await sm.fire(Trigger.PRINT_DONE)


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
        """Walk through the full 13-state happy path."""
        await sm.fire(Trigger.HARDWARE_READY)
        assert sm.state == State.IDLE

        await sm.fire(Trigger.SESSION_START)
        assert sm.state == State.ONBOARDING

        await sm.fire(Trigger.ONBOARDING_DONE)
        assert sm.state == State.AWAITING_PAYMENT

        await sm.fire(Trigger.PAYMENT_CONFIRMED)
        assert sm.state == State.CAPTURE_SETUP

        await sm.fire(Trigger.CAPTURE_SETUP_READY)
        assert sm.state == State.COUNTDOWN

        await sm.fire(Trigger.COUNTDOWN_DONE)
        assert sm.state == State.CAPTURING

        await sm.fire(Trigger.CAPTURE_DONE)
        assert sm.state == State.PROCESSING

        await sm.fire(Trigger.ALL_PHOTOS_DONE)
        assert sm.state == State.CUSTOMIZATION

        await sm.fire(Trigger.CUSTOMIZATION_DONE)
        assert sm.state == State.PREVIEW

        await sm.fire(Trigger.PRINT_REQUESTED)
        assert sm.state == State.PRINTING

        await sm.fire(Trigger.PRINT_DONE)
        assert sm.state == State.COMPLETE

        await sm.fire(Trigger.SESSION_COMPLETE)
        assert sm.state == State.IDLE

    @pytest.mark.asyncio
    async def test_multi_photo_session(self, sm):
        """Take multiple photos by cycling PROCESSING → COUNTDOWN → …"""
        await _advance_to_processing(sm)
        assert sm.state == State.PROCESSING

        # More photos remain → loop back to COUNTDOWN
        await sm.fire(Trigger.NEXT_PHOTO)
        assert sm.state == State.COUNTDOWN

        await sm.fire(Trigger.COUNTDOWN_DONE)
        await sm.fire(Trigger.CAPTURE_DONE)
        assert sm.state == State.PROCESSING

        # Third photo
        await sm.fire(Trigger.NEXT_PHOTO)
        assert sm.state == State.COUNTDOWN

        await sm.fire(Trigger.COUNTDOWN_DONE)
        await sm.fire(Trigger.CAPTURE_DONE)
        assert sm.state == State.PROCESSING

        # All done
        await sm.fire(Trigger.ALL_PHOTOS_DONE)
        assert sm.state == State.CUSTOMIZATION


# ── Onboarding ──────────────────────────────────────────────────────

class TestOnboarding:
    @pytest.mark.asyncio
    async def test_session_start_goes_to_onboarding(self, sm):
        await _advance_to_idle(sm)
        await sm.fire(Trigger.SESSION_START)
        assert sm.state == State.ONBOARDING

    @pytest.mark.asyncio
    async def test_onboarding_done_goes_to_payment(self, sm):
        await _advance_to_onboarding(sm)
        await sm.fire(Trigger.ONBOARDING_DONE)
        assert sm.state == State.AWAITING_PAYMENT

    @pytest.mark.asyncio
    async def test_cancel_from_onboarding(self, sm):
        await _advance_to_onboarding(sm)
        await sm.fire(Trigger.SESSION_CANCEL)
        assert sm.state == State.IDLE


# ── Payment ─────────────────────────────────────────────────────────

class TestPayment:
    @pytest.mark.asyncio
    async def test_payment_confirmed(self, sm):
        await _advance_to_payment(sm)
        await sm.fire(Trigger.PAYMENT_CONFIRMED)
        assert sm.state == State.CAPTURE_SETUP

    @pytest.mark.asyncio
    async def test_payment_failed(self, sm):
        await _advance_to_payment(sm)
        await sm.fire(Trigger.PAYMENT_FAILED)
        assert sm.state == State.IDLE

    @pytest.mark.asyncio
    async def test_payment_cancelled(self, sm):
        await _advance_to_payment(sm)
        await sm.fire(Trigger.PAYMENT_CANCELLED)
        assert sm.state == State.IDLE


# ── Capture Setup ───────────────────────────────────────────────────

class TestCaptureSetup:
    @pytest.mark.asyncio
    async def test_capture_setup_ready(self, sm):
        await _advance_to_capture_setup(sm)
        await sm.fire(Trigger.CAPTURE_SETUP_READY)
        assert sm.state == State.COUNTDOWN

    @pytest.mark.asyncio
    async def test_capture_setup_timeout(self, sm):
        await _advance_to_capture_setup(sm)
        await sm.fire(Trigger.CAPTURE_SETUP_TIMEOUT)
        assert sm.state == State.COUNTDOWN

    @pytest.mark.asyncio
    async def test_cancel_from_capture_setup(self, sm):
        await _advance_to_capture_setup(sm)
        await sm.fire(Trigger.SESSION_CANCEL)
        assert sm.state == State.IDLE


# ── Customization ───────────────────────────────────────────────────

class TestCustomization:
    @pytest.mark.asyncio
    async def test_customization_done(self, sm):
        await _advance_to_customization(sm)
        await sm.fire(Trigger.CUSTOMIZATION_DONE)
        assert sm.state == State.PREVIEW

    @pytest.mark.asyncio
    async def test_retake_from_customization(self, sm):
        """Retake → COUNTDOWN → full capture cycle → back to CUSTOMIZATION."""
        await _advance_to_customization(sm)
        await sm.fire(Trigger.RETAKE_REQUESTED)
        assert sm.state == State.COUNTDOWN

        # Complete the retake capture cycle
        await sm.fire(Trigger.COUNTDOWN_DONE)
        assert sm.state == State.CAPTURING
        await sm.fire(Trigger.CAPTURE_DONE)
        assert sm.state == State.PROCESSING
        await sm.fire(Trigger.ALL_PHOTOS_DONE)
        assert sm.state == State.CUSTOMIZATION

    @pytest.mark.asyncio
    async def test_cancel_from_customization(self, sm):
        await _advance_to_customization(sm)
        await sm.fire(Trigger.SESSION_CANCEL)
        assert sm.state == State.IDLE


# ── Preview ─────────────────────────────────────────────────────────

class TestPreview:
    @pytest.mark.asyncio
    async def test_print_requested(self, sm):
        await _advance_to_preview(sm)
        await sm.fire(Trigger.PRINT_REQUESTED)
        assert sm.state == State.PRINTING

    @pytest.mark.asyncio
    async def test_back_to_customize(self, sm):
        await _advance_to_preview(sm)
        await sm.fire(Trigger.BACK_TO_CUSTOMIZE)
        assert sm.state == State.CUSTOMIZATION


# ── Printing & Complete ─────────────────────────────────────────────

class TestPrintingAndComplete:
    @pytest.mark.asyncio
    async def test_print_done_goes_to_complete(self, sm):
        await _advance_to_printing(sm)
        await sm.fire(Trigger.PRINT_DONE)
        assert sm.state == State.COMPLETE

    @pytest.mark.asyncio
    async def test_session_complete_goes_to_idle(self, sm):
        await _advance_to_complete(sm)
        await sm.fire(Trigger.SESSION_COMPLETE)
        assert sm.state == State.IDLE


# ── Session cancellation ────────────────────────────────────────────

class TestSessionCancel:
    @pytest.mark.asyncio
    async def test_cancel_from_countdown(self, sm):
        await _advance_to_countdown(sm)
        await sm.fire(Trigger.SESSION_CANCEL)
        assert sm.state == State.IDLE

    @pytest.mark.asyncio
    async def test_cancel_from_onboarding(self, sm):
        await _advance_to_onboarding(sm)
        await sm.fire(Trigger.SESSION_CANCEL)
        assert sm.state == State.IDLE

    @pytest.mark.asyncio
    async def test_cancel_from_capture_setup(self, sm):
        await _advance_to_capture_setup(sm)
        await sm.fire(Trigger.SESSION_CANCEL)
        assert sm.state == State.IDLE

    @pytest.mark.asyncio
    async def test_cancel_from_customization(self, sm):
        await _advance_to_customization(sm)
        await sm.fire(Trigger.SESSION_CANCEL)
        assert sm.state == State.IDLE


# ── Error handling ──────────────────────────────────────────────────

class TestErrorHandling:
    @pytest.mark.asyncio
    async def test_capture_fail_goes_to_error(self, sm):
        await _advance_to_countdown(sm)
        await sm.fire(Trigger.COUNTDOWN_DONE)
        assert sm.state == State.CAPTURING

        error_ctx = {"error_code": "CAMERA_DISCONNECTED", "message": "USB unplugged"}
        await sm.fire(Trigger.CAPTURE_FAIL, context=error_ctx)
        assert sm.state == State.ERROR
        assert sm.error_context == error_ctx

    @pytest.mark.asyncio
    async def test_processing_fail_goes_to_error(self, sm):
        await _advance_to_processing(sm)
        await sm.fire(Trigger.PROCESSING_FAIL, context={"error": "thumbnail failed"})
        assert sm.state == State.ERROR

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
        await _advance_to_printing(sm)
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

    @pytest.mark.asyncio
    async def test_cannot_pay_from_onboarding(self, sm):
        await _advance_to_onboarding(sm)
        with pytest.raises(InvalidTransitionError):
            await sm.fire(Trigger.PAYMENT_CONFIRMED)

    @pytest.mark.asyncio
    async def test_cannot_customize_from_countdown(self, sm):
        await _advance_to_countdown(sm)
        with pytest.raises(InvalidTransitionError):
            await sm.fire(Trigger.CUSTOMIZATION_DONE)

    @pytest.mark.asyncio
    async def test_cannot_complete_from_printing(self, sm):
        await _advance_to_printing(sm)
        with pytest.raises(InvalidTransitionError):
            await sm.fire(Trigger.SESSION_COMPLETE)


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

    @pytest.mark.asyncio
    async def test_available_triggers_in_idle(self, sm):
        await _advance_to_idle(sm)
        triggers = sm.available_triggers()
        assert Trigger.SESSION_START in triggers
        assert Trigger.HARDWARE_READY not in triggers

    @pytest.mark.asyncio
    async def test_available_triggers_in_customization(self, sm):
        await _advance_to_customization(sm)
        triggers = sm.available_triggers()
        assert Trigger.CUSTOMIZATION_DONE in triggers
        assert Trigger.RETAKE_REQUESTED in triggers
        assert Trigger.SESSION_CANCEL in triggers
        assert Trigger.PRINT_REQUESTED not in triggers


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
