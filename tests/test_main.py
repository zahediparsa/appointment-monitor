import logging
from unittest.mock import MagicMock, Mock

import pytest

from appointment_monitor import __main__ as cli
from appointment_monitor.config import Config, ConfigError
from appointment_monitor.machine import Outcome


@pytest.fixture
def app(monkeypatch):
    import dotenv
    import appointment_monitor.browser as browser

    monkeypatch.setattr(dotenv, "load_dotenv", lambda: None)
    monkeypatch.setattr(cli.logging, "FileHandler", lambda *a, **kw: logging.NullHandler())
    cfg = Config(email="u", password="p", base_url="https://example.test", slot_selector="button.available")
    monkeypatch.setattr(cli.Config, "from_env", Mock(return_value=cfg))
    page = MagicMock()
    page.__enter__.return_value = page
    page.__exit__.return_value = False
    monkeypatch.setattr(browser, "SeleniumPage", Mock(return_value=page))
    monitor = Mock()
    monkeypatch.setattr(cli, "Monitor", Mock(return_value=monitor))
    return page, monitor


@pytest.mark.parametrize("args", [["--max-cycles", "0"], ["--max-cycles", "-1"],
                                 ["--max-cycles", "1.5"], ["--log-level", "invalid"]])
def test_invalid_cli_arguments(args):
    with pytest.raises(SystemExit) as exc:
        cli.main(args)
    assert exc.value.code == 2


@pytest.mark.parametrize("outcome", [Outcome.GAVE_UP, Outcome.STOPPED])
def test_unsuccessful_monitor_returns_one_and_closes_browser(app, outcome):
    page, monitor = app
    monitor.run.return_value = outcome
    assert cli.main([]) == 1
    page.__exit__.assert_called_once()


@pytest.mark.parametrize("closed_input", [False, True])
def test_slot_alert_waits_for_input_and_closes_browser(app, monkeypatch, closed_input):
    page, monitor = app
    monitor.run.return_value = Outcome.SLOT_FOUND
    reader = Mock(side_effect=EOFError()) if closed_input else Mock(return_value="")
    monkeypatch.setattr("builtins.input", reader)
    assert cli.main(["--log-level", "DEBUG"]) == 0
    reader.assert_called_once()
    page.__exit__.assert_called_once()
    assert logging.getLogger("selenium").level == logging.WARNING
    assert logging.getLogger("urllib3").level == logging.WARNING


def test_invalid_configuration_returns_two(app, monkeypatch):
    monkeypatch.setattr(cli.Config, "from_env", Mock(side_effect=ConfigError("Missing required settings")))
    assert cli.main([]) == 2


def test_unwritable_log_returns_two(app, monkeypatch, capsys):
    monkeypatch.setattr(cli.logging, "FileHandler", Mock(side_effect=PermissionError()))
    assert cli.main([]) == 2
    assert "Could not open monitor.log" in capsys.readouterr().err


def test_browser_startup_failure_returns_two(app, monkeypatch):
    import appointment_monitor.browser as browser

    monkeypatch.setattr(browser, "SeleniumPage", Mock(side_effect=OSError()))
    assert cli.main([]) == 2


def test_keyboard_interrupt_closes_browser(app):
    page, monitor = app
    monitor.run.side_effect = KeyboardInterrupt()
    assert cli.main([]) == 130
    page.__exit__.assert_called_once()
