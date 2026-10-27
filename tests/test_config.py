import pytest

from appointment_monitor.config import Config, ConfigError


@pytest.fixture
def env():
    return {"MONITOR_EMAIL": "user@example.test", "MONITOR_PASSWORD": "password",
            "MONITOR_BASE_URL": "https://example.test/start", "MONITOR_SLOT_SELECTOR": "button.available"}


@pytest.mark.parametrize("name,value", [
    ("MONITOR_STEP_DELAY", "nan,50"), ("MONITOR_STEP_DELAY", "1,inf"),
    ("MONITOR_STEP_DELAY", "1,2,3"), ("MONITOR_POLL_INTERVAL_MIN", "nan"),
    ("MONITOR_POLL_INTERVAL_MIN", "inf"), ("MONITOR_POLL_INTERVAL_MIN", "0"),
    ("MONITOR_MAX_FAILURES", "1.5"), ("MONITOR_CONFIRMATIONS", "0"),
    ("MONITOR_BACKOFF_START_MIN", "61"), ("MONITOR_SLOT_SELECTOR", " "),
    ("MONITOR_EMAIL", " "), ("MONITOR_PASSWORD", " "),
    ("MONITOR_BASE_URL", "file:///tmp/page"), ("MONITOR_BASE_URL", "https://"),
    ("MONITOR_BASE_URL", "https://user:password@example.test"),
    ("MONITOR_BASE_URL", "https://["),
])
def test_invalid_environment_values(env, name, value):
    env[name] = value
    with pytest.raises(ConfigError):
        Config.from_env(env)


def test_valid_environment_values(env):
    env.update(MONITOR_STEP_DELAY="0,0", MONITOR_CONFIRMATIONS="3", MONITOR_BACKOFF_MAX_MIN="90")
    cfg = Config.from_env(env)
    assert cfg.step_delay == (0, 0)
    assert cfg.confirmations == 3
    assert cfg.backoff_max_min == 90
    assert cfg.slot_selector == "button.available"
