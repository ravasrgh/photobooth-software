"""Finite State Machine for the photobooth session flow."""

import logging
from enum import Enum
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


class State(str, Enum):
    """All possible states of the photobooth backend (13 states)."""
    INITIALIZING     = "INITIALIZING"
    IDLE             = "IDLE"
    ONBOARDING       = "ONBOARDING"
    AWAITING_PAYMENT = "AWAITING_PAYMENT"
    CAPTURE_SETUP    = "CAPTURE_SETUP"
    COUNTDOWN        = "COUNTDOWN"
    CAPTURING        = "CAPTURING"
    PROCESSING       = "PROCESSING"
    CUSTOMIZATION    = "CUSTOMIZATION"
    PREVIEW          = "PREVIEW"
    PRINTING         = "PRINTING"
    COMPLETE         = "COMPLETE"
    ERROR            = "ERROR"


class Trigger(str, Enum):
    """Events that cause state transitions."""
    # Startup
    HARDWARE_READY       = "hardware_ready"
    HARDWARE_FAIL        = "hardware_fail"
    # Session lifecycle
    SESSION_START        = "session_start"
    SESSION_CANCEL       = "session_cancel"
    SESSION_COMPLETE     = "session_complete"
    # Onboarding
    ONBOARDING_DONE      = "onboarding_done"
    # Payment
    PAYMENT_CONFIRMED    = "payment_confirmed"
    PAYMENT_FAILED       = "payment_failed"
    PAYMENT_CANCELLED    = "payment_cancelled"
    # Capture setup
    CAPTURE_SETUP_READY  = "capture_setup_ready"
    CAPTURE_SETUP_TIMEOUT = "capture_setup_timeout"
    # Capture cycle
    COUNTDOWN_DONE       = "countdown_done"
    CAPTURE_DONE         = "capture_done"
    CAPTURE_FAIL         = "capture_fail"
    PROCESSING_DONE      = "processing_done"
    PROCESSING_FAIL      = "processing_fail"
    NEXT_PHOTO           = "next_photo"
    ALL_PHOTOS_DONE      = "all_photos_done"
    # Customization
    RETAKE_REQUESTED     = "retake_requested"
    CUSTOMIZATION_DONE   = "customization_done"
    # Preview / Print
    PRINT_REQUESTED      = "print_requested"
    BACK_TO_CUSTOMIZE    = "back_to_customize"
    PRINT_DONE           = "print_done"
    PRINT_FAIL           = "print_fail"
    # Error recovery
    ERROR_RESOLVED       = "error_resolved"
    RESTART              = "restart_requested"


# ── Transition table (PRD §3.2) ────────────────────────────────────
# Maps (current_state, trigger) → next_state
TRANSITIONS: dict[tuple[State, Trigger], State] = {
    # Startup
    (State.INITIALIZING, Trigger.HARDWARE_READY):       State.IDLE,
    (State.INITIALIZING, Trigger.HARDWARE_FAIL):        State.ERROR,

    # Session start → onboarding
    (State.IDLE, Trigger.SESSION_START):                 State.ONBOARDING,

    # Onboarding
    (State.ONBOARDING, Trigger.ONBOARDING_DONE):        State.AWAITING_PAYMENT,
    (State.ONBOARDING, Trigger.SESSION_CANCEL):         State.IDLE,

    # Payment
    (State.AWAITING_PAYMENT, Trigger.PAYMENT_CONFIRMED):  State.CAPTURE_SETUP,
    (State.AWAITING_PAYMENT, Trigger.PAYMENT_FAILED):     State.IDLE,
    (State.AWAITING_PAYMENT, Trigger.PAYMENT_CANCELLED):  State.IDLE,

    # Capture setup
    (State.CAPTURE_SETUP, Trigger.CAPTURE_SETUP_READY):   State.COUNTDOWN,
    (State.CAPTURE_SETUP, Trigger.CAPTURE_SETUP_TIMEOUT): State.COUNTDOWN,
    (State.CAPTURE_SETUP, Trigger.SESSION_CANCEL):        State.IDLE,

    # Countdown
    (State.COUNTDOWN, Trigger.COUNTDOWN_DONE):          State.CAPTURING,
    (State.COUNTDOWN, Trigger.SESSION_CANCEL):          State.IDLE,

    # Capture
    (State.CAPTURING, Trigger.CAPTURE_DONE):            State.PROCESSING,
    (State.CAPTURING, Trigger.CAPTURE_FAIL):            State.ERROR,

    # Processing — branch: more photos or all done
    (State.PROCESSING, Trigger.NEXT_PHOTO):             State.COUNTDOWN,
    (State.PROCESSING, Trigger.ALL_PHOTOS_DONE):        State.CUSTOMIZATION,
    (State.PROCESSING, Trigger.PROCESSING_FAIL):        State.ERROR,

    # Customization
    (State.CUSTOMIZATION, Trigger.CUSTOMIZATION_DONE):  State.PREVIEW,
    (State.CUSTOMIZATION, Trigger.RETAKE_REQUESTED):    State.COUNTDOWN,
    (State.CUSTOMIZATION, Trigger.SESSION_CANCEL):      State.IDLE,

    # Preview
    (State.PREVIEW, Trigger.PRINT_REQUESTED):           State.PRINTING,
    (State.PREVIEW, Trigger.BACK_TO_CUSTOMIZE):         State.CUSTOMIZATION,

    # Printing
    (State.PRINTING, Trigger.PRINT_DONE):               State.COMPLETE,
    (State.PRINTING, Trigger.PRINT_FAIL):               State.ERROR,

    # Complete → auto-reset
    (State.COMPLETE, Trigger.SESSION_COMPLETE):          State.IDLE,

    # Error recovery
    (State.ERROR, Trigger.ERROR_RESOLVED):              State.IDLE,
    (State.ERROR, Trigger.RESTART):                     State.INITIALIZING,
}


class InvalidTransitionError(Exception):
    """Raised when a trigger is not valid for the current state."""
    pass


class BoothStateMachine:
    """
    Thread-safe Finite State Machine with async callbacks.

    The ``on_transition`` callback is invoked after every successful
    transition, making it the hook point for the IPC layer to push
    state-change events to Electron.
    """

    def __init__(self, on_transition: Optional[Callable] = None):
        """
        Args:
            on_transition: async callable(prev_state, next_state, trigger, context).
        """
        self._state = State.INITIALIZING
        self._on_transition = on_transition
        self._error_context: Optional[dict] = None

    @property
    def state(self) -> State:
        """Current state."""
        return self._state

    @property
    def error_context(self) -> Optional[dict]:
        """Error details when in ERROR state, None otherwise."""
        return self._error_context

    async def fire(self, trigger: Trigger, context: Optional[dict] = None) -> State:
        """Attempt a state transition.

        Args:
            trigger: The event triggering the transition.
            context: Optional dict with extra data (e.g. error info).

        Returns:
            The new State after the transition.

        Raises:
            InvalidTransitionError: if the (state, trigger) pair is invalid.
        """
        key = (self._state, trigger)
        next_state = TRANSITIONS.get(key)

        if next_state is None:
            raise InvalidTransitionError(
                f"No transition from {self._state.value} via {trigger.value}"
            )

        prev = self._state
        self._state = next_state

        # Track error context
        if next_state == State.ERROR:
            self._error_context = context or {}
        elif prev == State.ERROR:
            self._error_context = None

        logger.info(
            "State: %s → %s (trigger: %s)",
            prev.value, next_state.value, trigger.value,
        )

        # Notify listener
        if self._on_transition:
            await self._on_transition(prev, next_state, trigger, context)

        return next_state

    def can_fire(self, trigger: Trigger) -> bool:
        """Check whether a trigger is valid from the current state."""
        return (self._state, trigger) in TRANSITIONS

    def available_triggers(self) -> list[Trigger]:
        """Return all triggers valid from the current state."""
        return [t for s, t in TRANSITIONS if s == self._state]

    def to_dict(self) -> dict:
        """Serialise current state for IPC."""
        return {
            "state": self._state.value,
            "error_context": self._error_context,
            "available_triggers": [t.value for t in self.available_triggers()],
        }
