"""Selenium/Firefox implementation of the Page protocol.

All site-specific knowledge (selectors, UI text, rate-limit markers) lives in
``Selectors`` and ``SiteText`` so the state machine stays generic. The class
names below reflect the site's markup at the time of writing and are the part
most likely to break when the site changes.
"""
from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass
from typing import Optional, Tuple

from selenium import webdriver
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from .config import Config
from .machine import PageKind

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Selectors:
    logout: str = 'span[type="button"].TlsButton_tls-button__syUS5.TlsButton_--outline__Gz93Y'
    user_icon: str = 'div[role="listitem"] svg[aria-label="User icon"]'
    my_application: str = "#my-application"
    email: str = 'input[name="username"], #email-input-field'
    password: str = 'input[name="password"], #password-input-field'
    login_btn: str = 'button[type="submit"], #btn-login'
    select_group: str = 'button[data-testid="btn-select-group"]'
    book: str = 'a[data-testid="btn-book-appointment"], #book-appointment-btn'
    no_appointments: str = "p.mb-2.text-center.text-lg.font-semibold.text-primary-500"
    next_month: str = 'a[data-testid="btn-next-month-available"]'


@dataclass(frozen=True)
class SiteText:
    logout_label: str = "خروج"
    no_slots: str = "در حال حاضر هیچ وقت ملاقات در دسترس نداریم"
    rate_limited: Tuple[str, ...] = ("error 1015", "you are being rate limited", "error code: 1015")
    challenge: Tuple[str, ...] = (
        "verify you are human", "just a moment", "attention required",
        "در حال تایید", "در حال تأیید",
    )


class SeleniumPage:
    def __init__(self, cfg: Config, selectors: Selectors = Selectors(), text: SiteText = SiteText(),
                 timeout_s: float = 30.0) -> None:
        self.cfg, self.sel, self.text, self.timeout_s = cfg, selectors, text, timeout_s
        cfg.firefox_profile.mkdir(parents=True, exist_ok=True)
        opts = Options()
        opts.add_argument("-profile")  # dedicated profile -> cookies persist between runs
        opts.add_argument(str(cfg.firefox_profile.resolve()))
        self.driver = webdriver.Firefox(options=opts, service=Service())  # geckodriver on PATH
        self._in_booking_flow = False

    # -- context manager ------------------------------------------------------
    def __enter__(self) -> "SeleniumPage":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        try:
            self.driver.quit()
        except WebDriverException:
            pass

    # -- low-level helpers ----------------------------------------------------
    def _first(self, css: str):
        found = self.driver.find_elements(By.CSS_SELECTOR, css)
        return found[0] if found else None

    def _click(self, css: str) -> bool:
        try:
            WebDriverWait(self.driver, self.timeout_s).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, css))
            ).click()
            return True
        except WebDriverException as exc:  # includes TimeoutException and stale elements
            log.warning("click failed for %r: %s", css, type(exc).__name__)
            return False

    def _micro(self) -> None:
        time.sleep(random.uniform(*self.cfg.micro_delay))

    def _page_text(self) -> str:
        return ((self.driver.title or "") + " " + self.driver.page_source).lower()

    # -- Page protocol --------------------------------------------------------
    def open(self, url: str) -> None:
        self._in_booking_flow = False
        self.driver.get(url)

    def classify(self) -> PageKind:
        try:
            text = self._page_text()
            if any(m in text for m in self.text.rate_limited):
                return PageKind.RATE_LIMITED
            if any(m in text for m in self.text.challenge):
                return PageKind.CHALLENGE

            logout: Optional[object] = self._first(self.sel.logout)
            if logout is not None and self.text.logout_label in (logout.text or ""):
                return PageKind.LOGOUT_BUTTON
            if self._first(self.sel.email):
                return PageKind.LOGGED_OUT

            notice = self._first(self.sel.no_appointments)
            if notice is not None and self.text.no_slots in (notice.text or ""):
                return PageKind.CALENDAR_NO_SLOTS
            if self._first(self.sel.select_group):
                return PageKind.GROUP_PICKER
            if self._first(self.sel.book):
                return PageKind.BOOKING_ENTRY
            if self._in_booking_flow:
                # In the booking flow, no recognised page and no "no slots" notice.
                # The state machine confirms this several times before alerting.
                return PageKind.CALENDAR_SLOTS
            if self._first(self.sel.user_icon):
                return PageKind.LOGGED_IN
        except WebDriverException as exc:
            log.warning("classify failed: %s", type(exc).__name__)
        return PageKind.UNKNOWN

    def logout(self) -> bool:
        return self._click(self.sel.logout)

    def login(self, email: str, password: str) -> bool:
        try:
            field = WebDriverWait(self.driver, self.timeout_s).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, self.sel.email))
            )
            field.send_keys(email)
            self._micro()
            password_field, submit = self._first(self.sel.password), self._first(self.sel.login_btn)
            if password_field is None or submit is None:
                return False
            password_field.send_keys(password)
            self._micro()
            submit.click()
            log.info("credentials submitted")
            return True
        except WebDriverException as exc:
            log.warning("login failed: %s", type(exc).__name__)
            return False

    def open_dashboard(self) -> bool:
        if not self._click(self.sel.user_icon):
            return False
        time.sleep(0.6)  # let the avatar menu render
        return self._click(self.sel.my_application)

    def select_group(self) -> bool:
        return self._click(self.sel.select_group)

    def start_booking(self) -> bool:
        ok = self._click(self.sel.book)
        self._in_booking_flow = self._in_booking_flow or ok
        return ok

    def next_month(self) -> bool:
        if self._first(self.sel.next_month) is None:
            return False
        return self._click(self.sel.next_month)

    def screenshot(self, label: str) -> None:
        try:
            self.cfg.screenshot_dir.mkdir(parents=True, exist_ok=True)
            self.driver.save_screenshot(str(self.cfg.screenshot_dir / f"{label}_{int(time.time())}.png"))
        except (OSError, WebDriverException):
            pass
