# Appointment availability monitor

A Python/Selenium tool that logs in to a booking site, walks the calendar month by
month, and raises a local alert when an appointment slot may be available. It is
built around a small, testable state machine that recovers from changing page states.

**It only alerts.** It never books, never solves challenges, and never submits
anything beyond your own login. You finish the booking yourself in the open browser.

## Design

| Concern | How it is handled |
| --- | --- |
| Changing page states | Every cycle the page is *classified* (login form, group picker, calendar, rate-limit page, ...) and the matching handler acts, so the monitor recovers from expired sessions and stray redirects instead of assuming a fixed sequence. |
| Recovery and retries | Failures are counted; each one triggers a pause and a reload from the start page. After `MONITOR_MAX_FAILURES` consecutive failures it stops and keeps a screenshot. |
| Stuck detection | Handling the same page 5 times in a row (for example a wrong password) counts as a failure instead of looping forever. |
| Rate limiting | A rate-limit page triggers an exponential cooldown (5, 10, 20 ... up to 60 min, plus jitter). Normal pacing is 30-50 s between actions and 15 min between full passes. |
| Challenges | The monitor does not try to bypass them. It waits up to 3 min for you to solve one in the browser. |
| False alarms | A page that is merely unrecognised never triggers an alert. A slot candidate must be observed several times in a row before the alert fires. |
| Sessions | A dedicated Firefox profile keeps cookies between runs. |
| Secrets | Credentials come from environment variables / `.env`, never from code, and are excluded from `repr` and logs. |
| Evidence | Failures and slot candidates save screenshots; everything is logged to the console and `monitor.log`. |

The state machine (`machine.py`) has no Selenium dependency. It talks to a `Page`
protocol, so the recovery logic is unit-tested with a scripted fake page.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env                                # then edit it
python -m appointment_monitor                       # needs Firefox + geckodriver on PATH
```

## Tests

```bash
pytest
```

Covered: full login-to-slot flow, month walking, stale-session recovery, repeated
passes, rate-limit backoff, challenge waiting and timeout, no alert on unknown
pages, stuck-login detection, and configuration validation.

## Limitations

- The CSS selectors and UI text in `browser.py` match one site's markup at the time
  of writing and will break when it changes. They are isolated in `Selectors` and `SiteText`.
- The browser layer is not covered by automated tests; the state machine is.
- Automated access may be restricted by a site's terms of use. Check them before use.
  Keep the pacing conservative and use your own account only.
