import subprocess
import sys
from unittest.mock import Mock

import pytest

from appointment_monitor import alerts


@pytest.mark.parametrize("system", ["Linux", "Darwin"])
@pytest.mark.parametrize("error", [FileNotFoundError(), subprocess.CalledProcessError(1, "notifier"),
                                  subprocess.TimeoutExpired("notifier", 10)])
def test_notification_failures_fall_back_to_terminal(monkeypatch, capsys, system, error):
    monkeypatch.setattr(alerts.platform, "system", lambda: system)

    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(alerts.subprocess, "run", fail)
    alerts.notify("Possible slot")
    assert "\aPossible slot" in capsys.readouterr().out


@pytest.mark.parametrize("failed", [False, True])
def test_windows_beep_and_failure_fallback(monkeypatch, capsys, failed):
    sound = Mock()
    if failed:
        sound.Beep.side_effect = RuntimeError("Cannot beep")
    monkeypatch.setitem(sys.modules, "winsound", sound)
    monkeypatch.setattr(alerts.platform, "system", lambda: "Windows")
    monkeypatch.setattr(alerts.time, "sleep", lambda _: None)
    alerts.notify("Possible slot")
    if failed:
        assert "\aPossible slot" in capsys.readouterr().out
    else:
        assert sound.Beep.call_count == 5
