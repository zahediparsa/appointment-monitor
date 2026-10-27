from unittest.mock import Mock

import pytest
from selenium.common.exceptions import TimeoutException, WebDriverException

from appointment_monitor.browser import SeleniumPage, Selectors, SiteText
from appointment_monitor.config import Config
from appointment_monitor.machine import PageError, PageKind as K


class Element:
    def __init__(self, text="", *, visible=True, enabled=True, aria_disabled=None):
        self.text, self.visible, self.enabled = text, visible, enabled
        self.aria_disabled = aria_disabled
        self.value = "old value"
        self.clicked = False

    def is_displayed(self): return self.visible
    def is_enabled(self): return self.enabled
    def get_attribute(self, name): return self.aria_disabled if name == "aria-disabled" else None
    def clear(self): self.value = ""
    def send_keys(self, value): self.value += value
    def click(self): self.clicked = True


@pytest.fixture
def page():
    # Exercise the real adapter methods without starting Firefox or contacting a site.
    page = SeleniumPage.__new__(SeleniumPage)
    page.cfg = Config(email="u", password="p", base_url="https://example.test", slot_selector="button.available")
    page.sel, page.text, page.timeout_s = Selectors(), SiteText(), 0
    page._in_booking_flow = False
    page.driver = Mock()
    page.driver.title = "Booking"
    page.driver.find_element.return_value = Element("Calendar")
    page.elements = {}
    page.driver.find_elements.side_effect = lambda by, css: page.elements.get(css, [])
    return page


def test_unknown_booking_page_does_not_become_a_slot(page):
    page._in_booking_flow = True
    page.elements[page.sel.user_icon] = [Element()]
    assert page.classify() is K.UNKNOWN


@pytest.mark.parametrize("slot", [Element(visible=False), Element(enabled=False), Element(aria_disabled="true")])
def test_inactive_slot_does_not_alert(page, slot):
    page.elements[page.cfg.slot_selector] = [slot]
    assert page.classify() is K.UNKNOWN


def test_visible_enabled_slot_is_positive_evidence(page):
    page.elements[page.cfg.slot_selector] = [Element(visible=False), Element()]
    assert page.classify() is K.CALENDAR_SLOTS


def test_no_slots_notice_wins_over_slot_element(page):
    page.elements[page.cfg.slot_selector] = [Element()]
    page.elements[page.sel.no_appointments] = [Element(page.text.no_slots)]
    assert page.classify() is K.CALENDAR_NO_SLOTS


def test_normal_logout_menu_does_not_force_logout(page):
    page.elements[page.sel.logout] = [Element(page.text.logout_label)]
    page.elements[page.sel.user_icon] = [Element()]
    assert page.classify() is K.LOGGED_IN
    page.elements[page.sel.email] = [Element()]
    assert page.classify() is K.LOGOUT_BUTTON


def test_hidden_login_field_is_ignored(page):
    page.elements[page.sel.email] = [Element(visible=False)]
    page.elements[page.cfg.slot_selector] = [Element()]
    assert page.classify() is K.CALENDAR_SLOTS


@pytest.mark.parametrize("text,kind", [("Error 1015", K.RATE_LIMITED), ("Verify you are human", K.CHALLENGE)])
def test_visible_block_page_takes_priority(page, text, kind):
    page.driver.find_element.return_value = Element(text)
    page.elements[page.cfg.slot_selector] = [Element()]
    assert page.classify() is kind


def test_script_text_does_not_trigger_challenge(page):
    page.driver.page_source = '<script>"verify you are human"</script>'
    page.elements[page.cfg.slot_selector] = [Element()]
    assert page.classify() is K.CALENDAR_SLOTS


def test_login_replaces_existing_field_values(page):
    email, password, submit = Element(), Element(), Element()
    page.elements.update({page.sel.email: [email], page.sel.password: [password], page.sel.login_btn: [submit]})
    page._micro = lambda: None
    assert page.login("new@example.test", "new-password")
    assert email.value == "new@example.test" and password.value == "new-password"
    assert submit.clicked


def test_failed_start_navigation_becomes_recoverable_error(page):
    page.driver.get.side_effect = WebDriverException("failed")
    with pytest.raises(PageError):
        page.open(page.cfg.base_url)


def test_no_next_month_finishes_pass(page):
    assert page.next_month() is False


def test_disabled_next_month_finishes_pass(page):
    page.elements[page.sel.next_month] = [Element(aria_disabled="true")]
    assert page.next_month() is False


def test_failed_next_month_click_is_not_an_empty_pass(page):
    page.elements[page.sel.next_month] = [Element()]
    page._click = lambda _: False
    with pytest.raises(PageError):
        page.next_month()


def test_next_month_must_change_visible_page(page):
    page.elements[page.sel.next_month] = [Element()]
    page._click = lambda _: True
    with pytest.raises(PageError):
        page.next_month()


def test_changed_month_is_success(page):
    page.elements[page.sel.next_month] = [Element()]
    page._click = lambda _: True
    page.driver.find_element.side_effect = [Element("January"), Element("February")]
    assert page.next_month() is True


def test_driver_read_failure_is_unknown(page):
    page.driver.find_elements.side_effect = TimeoutException()
    assert page.classify() is K.UNKNOWN
