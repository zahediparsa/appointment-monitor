"""Configuration, read from environment variables. Nothing sensitive lives in the code."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Optional, Tuple


class ConfigError(RuntimeError):
    """Raised when required settings are missing or invalid."""


def _pair(env: Mapping[str, str], name: str, default: Tuple[float, float]) -> Tuple[float, float]:
    raw = env.get(name)
    if raw is None:
        return default
    try:
        lo, hi = (float(part) for part in raw.split(","))
    except ValueError as exc:
        raise ConfigError(f"{name} must look like '30,50'") from exc
    if lo < 0 or hi < lo:
        raise ConfigError(f"{name} needs 0 <= low <= high")
    return lo, hi


def _number(env: Mapping[str, str], name: str, default, cast=float):
    raw = env.get(name)
    if raw is None:
        return default
    try:
        value = cast(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number") from exc
    if value <= 0:
        raise ConfigError(f"{name} must be positive")
    return value


@dataclass(frozen=True)
class Config:
    email: str
    password: str = field(repr=False)  # never printed or logged
    base_url: str

    firefox_profile: Path = Path(".firefox-profile")  # dedicated profile: keeps cookies between runs
    screenshot_dir: Path = Path("screenshots")

    step_delay: Tuple[float, float] = (30.0, 50.0)    # pause (s) after each page action
    micro_delay: Tuple[float, float] = (0.5, 1.3)     # tiny pause (s) between keystrokes/clicks
    confirm_delay: Tuple[float, float] = (4.0, 8.0)   # pause (s) between slot confirmations

    poll_interval_min: float = 15.0   # minutes between full passes over the calendar
    backoff_start_min: float = 5.0    # first cooldown (min) after a rate-limit page
    backoff_max_min: float = 60.0
    challenge_timeout_s: float = 180.0  # how long to wait for a manual challenge solve
    max_failures: int = 5             # consecutive failures before giving up
    confirmations: int = 2            # consecutive observations needed before alerting

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> "Config":
        env = os.environ if env is None else env
        missing = [k for k in ("MONITOR_EMAIL", "MONITOR_PASSWORD", "MONITOR_BASE_URL") if not env.get(k)]
        if missing:
            raise ConfigError("Missing required settings: " + ", ".join(missing))
        return cls(
            email=env["MONITOR_EMAIL"],
            password=env["MONITOR_PASSWORD"],
            base_url=env["MONITOR_BASE_URL"],
            firefox_profile=Path(env.get("MONITOR_FIREFOX_PROFILE", ".firefox-profile")),
            step_delay=_pair(env, "MONITOR_STEP_DELAY", (30.0, 50.0)),
            poll_interval_min=_number(env, "MONITOR_POLL_INTERVAL_MIN", 15.0),
            backoff_start_min=_number(env, "MONITOR_BACKOFF_START_MIN", 5.0),
            backoff_max_min=_number(env, "MONITOR_BACKOFF_MAX_MIN", 60.0),
            max_failures=_number(env, "MONITOR_MAX_FAILURES", 5, int),
            confirmations=_number(env, "MONITOR_CONFIRMATIONS", 2, int),
        )
