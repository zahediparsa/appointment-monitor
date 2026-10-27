import random

import pytest

from appointment_monitor.config import Config, ConfigError
from appointment_monitor.machine import Monitor, Outcome, PageKind as K


class FakePage:
    """Scripted page: classify() walks the script and repeats the last entry."""

    def __init__(self, script, *, next_month_ok=True, login_ok=True):
        self.script, self.i = list(script), 0
        self.next_month_ok, self.login_ok = next_month_ok, login_ok
        self.actions, self.opened, self.shots = [], [], []

    def classify(self):
        kind = self.script[min(self.i, len(self.script) - 1)]
        self.i += 1
        return kind

    def open(self, url): self.opened.append(url)
    def screenshot(self, label): self.shots.append(label)
    def logout(self): self.actions.append("logout"); return True
    def login(self, email, password): self.actions.append("login"); return self.login_ok
    def open_dashboard(self): self.actions.append("dashboard"); return True
    def select_group(self): self.actions.append("select_group"); return True
    def start_booking(self): self.actions.append("start_booking"); return True
    def next_month(self): self.actions.append("next_month"); return self.next_month_ok


def run(script, *, max_cycles=None, page_kw=None, **cfg_kw):
    cfg = Config(
        email="user@example.test", password="pw", base_url="https://example.test/start",
        step_delay=(0, 0), micro_delay=(0, 0), confirm_delay=(0, 0), **cfg_kw,
    )
    page, alerts, sleeps = FakePage(script, **(page_kw or {})), [], []
    monitor = Monitor(page, cfg, alerts.append, sleep=sleeps.append,
                      rng=random.Random(1), max_cycles=max_cycles)
    return monitor.run(), page, alerts, sleeps


def test_full_flow_alerts_once_after_confirmation():
    outcome, page, alerts, _ = run([K.LOGGED_OUT, K.GROUP_PICKER, K.BOOKING_ENTRY, K.CALENDAR_SLOTS])
    assert outcome is Outcome.SLOT_FOUND
    assert page.actions == ["login", "select_group", "start_booking"]
    assert len(alerts) == 1 and "slot" in alerts[0].lower()
    assert page.opened[0] == "https://example.test/start"


def test_unconfirmed_slot_is_a_false_alarm():
    # First reading says "slots", the confirmation reading says "no slots".
    outcome, _, alerts, _ = run([K.CALENDAR_SLOTS, K.CALENDAR_NO_SLOTS],
                                max_cycles=1, page_kw={"next_month_ok": False})
    assert outcome is Outcome.STOPPED
    assert alerts == []


def test_walks_through_months_until_slot():
    outcome, page, alerts, _ = run([K.CALENDAR_NO_SLOTS, K.CALENDAR_NO_SLOTS, K.CALENDAR_SLOTS])
    assert outcome is Outcome.SLOT_FOUND
    assert page.actions == ["next_month", "next_month"]
    assert len(alerts) == 1


def test_stale_session_logs_out_then_in():
    outcome, page, _, _ = run([K.LOGOUT_BUTTON, K.LOGGED_OUT, K.CALENDAR_SLOTS])
    assert outcome is Outcome.SLOT_FOUND
    assert page.actions == ["logout", "login"]


def test_polls_again_after_an_empty_pass():
    outcome, page, alerts, sleeps = run([K.CALENDAR_NO_SLOTS], max_cycles=2,
                                        page_kw={"next_month_ok": False})
    assert outcome is Outcome.STOPPED and alerts == []
    assert len(page.opened) == 2                      # initial load + one reload between passes
    assert any(14 * 60 <= s <= 17 * 60 for s in sleeps)  # ~15 min poll interval


def test_rate_limit_backoff_doubles_with_jitter():
    outcome, _, _, sleeps = run([K.RATE_LIMITED, K.RATE_LIMITED, K.CALENDAR_SLOTS])
    long_waits = [s for s in sleeps if s >= 60]
    assert outcome is Outcome.SLOT_FOUND
    assert len(long_waits) == 2
    assert 300 <= long_waits[0] <= 345      # 5 min + 15-45 s jitter
    assert 600 <= long_waits[1] <= 645      # doubled


def test_challenge_is_waited_out_not_failed():
    outcome, _, _, sleeps = run([K.CHALLENGE, K.CHALLENGE, K.CALENDAR_SLOTS])
    assert outcome is Outcome.SLOT_FOUND
    assert 2.0 in sleeps


def test_unsolved_challenge_eventually_gives_up():
    outcome, _, alerts, _ = run([K.CHALLENGE], challenge_timeout_s=6)
    assert outcome is Outcome.GAVE_UP and alerts == []


def test_unknown_page_never_alerts_and_gives_up():
    outcome, page, alerts, _ = run([K.UNKNOWN])
    assert outcome is Outcome.GAVE_UP
    assert alerts == [] and "failure" in page.shots


def test_login_loop_is_detected_as_stuck():
    # Login "succeeds" but the page never changes (e.g. wrong password).
    outcome, page, alerts, _ = run([K.LOGGED_OUT])
    assert outcome is Outcome.GAVE_UP
    assert alerts == [] and page.actions.count("login") < 40


def test_config_requires_credentials_and_hides_password():
    with pytest.raises(ConfigError):
        Config.from_env({})
    cfg = Config.from_env({"MONITOR_EMAIL": "a@b.c", "MONITOR_PASSWORD": "secret", "MONITOR_BASE_URL": "https://x"})
    assert "secret" not in repr(cfg)


def test_config_rejects_bad_delay():
    env = {"MONITOR_EMAIL": "a@b.c", "MONITOR_PASSWORD": "p", "MONITOR_BASE_URL": "https://x",
           "MONITOR_STEP_DELAY": "50,30"}
    with pytest.raises(ConfigError):
        Config.from_env(env)
