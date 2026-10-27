"""Observe-and-act state machine for the appointment monitor.

The machine never touches Selenium. It talks to a ``Page`` (a Protocol), so its
decision logic (recovery, backoff, stuck detection, slot confirmation) can be
tested with a scripted fake page.

Design: every cycle the page is *classified* (what am I looking at?) and the
matching handler acts. Because the next step depends on what is actually on
screen, not on what the program assumes, the machine recovers from expired
sessions, stray redirects and half-loaded pages.
"""
from __future__ import annotations

import logging
import random
import time
from enum import Enum
from typing import Callable, Dict, Optional, Protocol, Tuple

from .config import Config


class PageKind(Enum):
    RATE_LIMITED = "rate_limited"
    CHALLENGE = "challenge"
    LOGOUT_BUTTON = "logout_button"      # stale session: a logout button blocks the login form
    LOGGED_OUT = "logged_out"
    LOGGED_IN = "logged_in"
    GROUP_PICKER = "group_picker"
    BOOKING_ENTRY = "booking_entry"
    CALENDAR_NO_SLOTS = "calendar_no_slots"
    CALENDAR_SLOTS = "calendar_slots"
    UNKNOWN = "unknown"


class Outcome(Enum):
    SLOT_FOUND = "slot_found"
    GAVE_UP = "gave_up"
    STOPPED = "stopped"  # reached max_cycles (used for testing / one-shot runs)


class Page(Protocol):
    def open(self, url: str) -> None: ...
    def classify(self) -> PageKind: ...
    def logout(self) -> bool: ...
    def login(self, email: str, password: str) -> bool: ...
    def open_dashboard(self) -> bool: ...
    def select_group(self) -> bool: ...
    def start_booking(self) -> bool: ...
    def next_month(self) -> bool: ...
    def screenshot(self, label: str) -> None: ...


Handler = Callable[[], Optional[Outcome]]


class Monitor:
    CHALLENGE_POLL_S = 2.0
    MAX_SAME_PAGE = 4  # same non-calendar page handled this many times in a row = stuck

    def __init__(
        self,
        page: Page,
        cfg: Config,
        notify: Callable[[str], None],
        *,
        sleep: Callable[[float], None] = time.sleep,
        rng: Optional[random.Random] = None,
        max_cycles: Optional[int] = None,
        log: Optional[logging.Logger] = None,
    ) -> None:
        self.page = page
        self.cfg = cfg
        self.notify = notify
        self._sleep = sleep
        self._rng = rng or random.Random()
        self.max_cycles = max_cycles
        self.log = log or logging.getLogger(__name__)

        self._failures = 0
        self._backoff_min = cfg.backoff_start_min
        self._cycles = 0
        self._last_kind: Optional[PageKind] = None
        self._same_count = 0

        self._handlers: Dict[PageKind, Handler] = {
            PageKind.RATE_LIMITED: self._on_rate_limited,
            PageKind.CHALLENGE: self._on_challenge,
            PageKind.LOGOUT_BUTTON: self._on_logout_button,
            PageKind.LOGGED_OUT: self._on_logged_out,
            PageKind.LOGGED_IN: self._on_logged_in,
            PageKind.GROUP_PICKER: self._on_group_picker,
            PageKind.BOOKING_ENTRY: self._on_booking_entry,
            PageKind.CALENDAR_NO_SLOTS: self._on_calendar_no_slots,
            PageKind.CALENDAR_SLOTS: self._on_calendar_slots,
            PageKind.UNKNOWN: self._on_unknown,
        }

    # ------------------------------------------------------------------ main loop
    def run(self) -> Outcome:
        self.log.info("Monitor started")
        self.page.open(self.cfg.base_url)
        self._micro()
        while True:
            kind = self.page.classify()
            self.log.debug("observed %s", kind.value)

            if kind is self._last_kind and kind is not PageKind.CALENDAR_NO_SLOTS:
                self._same_count += 1
            else:
                self._last_kind, self._same_count = kind, 1
            if self._same_count > self.MAX_SAME_PAGE:
                self._last_kind, self._same_count = None, 0
                outcome = self._fail(f"stuck on {kind.value}")
                if outcome is not None:
                    return outcome
                continue

            outcome = self._handlers[kind]()
            if outcome is not None:
                return outcome

    # ------------------------------------------------------------------ handlers
    def _on_rate_limited(self) -> Optional[Outcome]:
        minutes = self._backoff_min
        self._backoff_min = min(self._backoff_min * 2, self.cfg.backoff_max_min)
        wait = minutes * 60 + self._rng.uniform(15, 45)  # jitter so repeated runs don't sync
        self.log.error("Rate-limit page; cooling down %.1f min", wait / 60)
        return self._fail("rate limited", wait_s=wait)

    def _on_challenge(self) -> Optional[Outcome]:
        self.log.warning(
            "Challenge page. Solve it manually in the browser; waiting up to %d s",
            self.cfg.challenge_timeout_s,
        )
        waited = 0.0
        while waited < self.cfg.challenge_timeout_s and self.page.classify() is PageKind.CHALLENGE:
            self._sleep(self.CHALLENGE_POLL_S)
            waited += self.CHALLENGE_POLL_S
        if waited >= self.cfg.challenge_timeout_s:
            return self._fail("challenge not solved in time")
        return None

    def _on_logout_button(self) -> Optional[Outcome]:
        return self._act(self.page.logout(), "logout button not clickable")

    def _on_logged_out(self) -> Optional[Outcome]:
        return self._act(self.page.login(self.cfg.email, self.cfg.password), "login failed")

    def _on_logged_in(self) -> Optional[Outcome]:
        return self._act(self.page.open_dashboard(), "could not open dashboard")

    def _on_group_picker(self) -> Optional[Outcome]:
        return self._act(self.page.select_group(), "could not select group")

    def _on_booking_entry(self) -> Optional[Outcome]:
        return self._act(self.page.start_booking(), "could not start booking flow")

    def _on_calendar_no_slots(self) -> Optional[Outcome]:
        self._reached_calendar()
        self.log.info("No slots in the current month")
        if self.page.next_month():
            self._pause()
            return None
        return self._finish_cycle()

    def _on_calendar_slots(self) -> Optional[Outcome]:
        self._reached_calendar()
        # A "no 'no-slots' message" reading can also come from a half-loaded page.
        # Require several consecutive observations before alerting.
        for _ in range(self.cfg.confirmations - 1):
            self._sleep(self._uniform(self.cfg.confirm_delay))
            if self.page.classify() is not PageKind.CALENDAR_SLOTS:
                self.log.info("Slot candidate disappeared; treating as false alarm")
                return None
        self.page.screenshot("slot_candidate")
        self.notify("Possible appointment slot found")
        self.log.warning("SLOT MAY BE AVAILABLE")
        return Outcome.SLOT_FOUND

    def _on_unknown(self) -> Optional[Outcome]:
        # Never alert on a page we do not recognise: that was the old false-positive path.
        return self._fail("unrecognised page")

    # ------------------------------------------------------------------ helpers
    def _act(self, succeeded: bool, why: str) -> Optional[Outcome]:
        if not succeeded:
            return self._fail(why)
        self._pause()
        return None

    def _fail(self, why: str, wait_s: Optional[float] = None) -> Optional[Outcome]:
        self._failures += 1
        self.log.warning("%s (failure %d/%d)", why, self._failures, self.cfg.max_failures)
        self.page.screenshot("failure")
        if self._failures >= self.cfg.max_failures:
            self.log.error("Too many consecutive failures; giving up")
            return Outcome.GAVE_UP
        self._sleep(wait_s if wait_s is not None else self._uniform(self.cfg.step_delay))
        self.page.open(self.cfg.base_url)
        return None

    def _reached_calendar(self) -> None:
        self._failures = 0
        self._backoff_min = self.cfg.backoff_start_min

    def _finish_cycle(self) -> Optional[Outcome]:
        self._cycles += 1
        self.log.info("Pass %d complete: no slots", self._cycles)
        if self.max_cycles is not None and self._cycles >= self.max_cycles:
            return Outcome.STOPPED
        self._sleep(self.cfg.poll_interval_min * 60 * self._rng.uniform(0.9, 1.1))
        self.page.open(self.cfg.base_url)
        self._micro()
        return None

    def _uniform(self, pair: Tuple[float, float]) -> float:
        return self._rng.uniform(*pair)

    def _pause(self) -> None:
        self._sleep(self._uniform(self.cfg.step_delay))

    def _micro(self) -> None:
        self._sleep(self._uniform(self.cfg.micro_delay))
