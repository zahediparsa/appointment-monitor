"""Entry point:  python -m appointment_monitor"""
from __future__ import annotations

import argparse
import logging
import sys

from .alerts import notify
from .config import Config, ConfigError
from .machine import Monitor, Outcome


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="appointment_monitor", description=__doc__)
    parser.add_argument("--log-level", default="INFO")
    parser.add_argument("--max-cycles", type=int, default=None, help="stop after N empty passes")
    args = parser.parse_args(argv)

    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    logging.basicConfig(
        level=args.log_level.upper(),
        format="%(asctime)s [%(levelname)8s] %(message)s",
        handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler("monitor.log", encoding="utf-8")],
    )
    try:
        cfg = Config.from_env()
    except ConfigError as exc:
        logging.error("%s (see .env.example)", exc)
        return 2

    from selenium.common.exceptions import WebDriverException
    from .browser import SeleniumPage

    outcome = None
    try:
        with SeleniumPage(cfg) as page:
            outcome = Monitor(page, cfg, notify, max_cycles=args.max_cycles).run()
            if outcome is Outcome.SLOT_FOUND:
                input("Possible slot found. The browser stays open so you can check it. Press Enter to close... ")
    except WebDriverException as exc:
        logging.error("Browser error: %s", type(exc).__name__)
        return 2
    except KeyboardInterrupt:
        logging.info("Interrupted")
        return 130
    logging.info("Finished: %s", outcome.value if outcome else "no result")
    return 0 if outcome is Outcome.SLOT_FOUND else 1


if __name__ == "__main__":
    raise SystemExit(main())
