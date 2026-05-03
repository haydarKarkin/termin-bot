#!/usr/bin/env python3
"""
Auslaenderamt — Appointment Monitor (Playwright edition)

Navigates the terminland.de multi-step booking form using a real browser,
then reads the calendar for free slots.
"""

import asyncio
import json
import os
import re
import requests
from datetime import datetime, timedelta

from playwright.async_api import async_playwright, Page, TimeoutError as PWTimeout

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_URL: str = os.environ.get("TERMIN_URL", "").rstrip("/") + "/"

if not os.environ.get("TERMIN_URL"):
    raise EnvironmentError("TERMIN_URL secret is not set.")

STATE_FILE = "last_state.json"
TIMEOUT    = 15_000   # ms — max wait per element


# ---------------------------------------------------------------------------
# Browser automation
# ---------------------------------------------------------------------------

async def get_free_dates() -> list[str]:
    """
    Opens the booking site in a headless Chromium browser, fills in every
    form step, and returns a sorted list of free dates (ISO-8601 strings).
    """
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page    = await browser.new_page()

        # Capture console errors for debugging
        page.on("console", lambda m: print(f"  [browser] {m.text}") if m.type == "error" else None)

        try:
            return await _fill_form(page)
        except PWTimeout as exc:
            print(f"[ERROR] Timed out: {exc}")
            await page.screenshot(path="debug_timeout.png", full_page=True)
            return []
        except Exception as exc:
            print(f"[ERROR] Unexpected error: {exc}")
            await page.screenshot(path="debug_error.png", full_page=True)
            return []
        finally:
            await browser.close()


async def _select_option_containing(page: Page, text: str):
    """
    Finds the first <select> that has an <option> containing `text` and selects it.
    select_option(label=...) only accepts plain strings, not regex patterns.
    """
    for sel in await page.locator("select").all():
        options = await sel.locator("option").all()
        for opt in options:
            opt_text = (await opt.inner_text()).strip()
            if text.lower() in opt_text.lower():
                await sel.select_option(label=opt_text)
                print(f"  → selected option: {opt_text!r}")
                return
    raise ValueError(f"No <option> containing {text!r} found on this page.")


async def _click_radio_label(page: Page, pattern: re.Pattern):
    """
    Clicks the <label> associated with a radio button whose label text matches
    the given pattern. Falls back to force-clicking the hidden input if no
    visible label is found. terminland.de hides the actual <input> and styles
    the <label> instead, so .check() fails with 'element is not visible'.
    """
    # Try clicking a visible label whose text matches
    label = page.locator("label").filter(has_text=pattern).first
    if await label.count():
        await label.click()
        return

    # Fallback: find the hidden radio and force-click it
    radio = page.get_by_role("radio", name=pattern).first
    await radio.click(force=True)


async def _fill_form(page: Page) -> list[str]:
    """Walks through every booking step and returns the free calendar dates."""

    print("[STEP 0] Opening booking page")
    await page.goto(BASE_URL, wait_until="networkidle", timeout=30_000)

    # ── Step 1 — Location ─────────────────────────────────────────────────
    print("[STEP 1] Selecting location")
    await _click_radio_label(page, re.compile("ausländeramt", re.I))
    await _click_weiter(page)

    # ── Step 2 — Service type ─────────────────────────────────────────────
    print("[STEP 2] Selecting service type")
    await _click_radio_label(page, re.compile("niederlassungserlaubnis", re.I))
    await _click_weiter(page)

    # ── Step 3 — Surname initial range ────────────────────────────────────
    print("[STEP 3] Selecting surname range")
    await _select_option_containing(page, "G-M")
    await _click_weiter(page)

    # ── Step 4 — Application already submitted? ───────────────────────────
    print("[STEP 4] Selecting application status")
    await _click_radio_label(page, re.compile("antrag liegt bereits", re.I))
    await _click_weiter(page)

    # ── Step 5 — Country of origin ────────────────────────────────────────
    print("[STEP 5] Selecting country option")
    await _select_option_containing(page, "Nein")
    await _click_weiter(page)

    # ── Step 6 — Number of people ─────────────────────────────────────────
    print("[STEP 6] Selecting number of people")
    await _click_radio_label(page, re.compile("drei personen", re.I))
    await _click_weiter(page)

    # ── Calendar ──────────────────────────────────────────────────────────
    print("[STEP 7] Waiting for calendar…")
    await page.wait_for_selector(".date-picker, td.free, [id^='cell']", timeout=TIMEOUT)
    await page.screenshot(path="debug_calendar.png", full_page=True)

    return await _parse_calendar(page)


async def _click_weiter(page: Page):
    """Clicks the 'Weiter' (next) button and waits for navigation to settle."""
    btn = page.get_by_role("button", name=re.compile("weiter|next|continue|fortfahren", re.I))
    await btn.first.click()
    await page.wait_for_load_state("networkidle", timeout=TIMEOUT)
    print(f"  → now at: {page.url}")


async def _parse_calendar(page: Page) -> list[str]:
    """
    Reads all calendar cells that carry 'freie Termine vorhanden' in their
    aria-label and returns their dates as sorted ISO-8601 strings.

    Expected HTML:
        <td class="free day"
            aria-label="Donnerstag, 08.10.2026 - freie Termine vorhanden">8</td>
    """
    cells = await page.locator("td.free").all()
    free_dates: list[str] = []

    for cell in cells:
        label = await cell.get_attribute("aria-label") or ""
        match = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", label)
        if match:
            day, month, year = match.group(1), match.group(2), match.group(3)
            iso = f"{year}-{month}-{day}"
            free_dates.append(iso)
            print(f"  [FREE] {iso}  — {label[:70]}")

    free_dates.sort()
    print(f"[RESULT] {len(free_dates)} free date(s) found.")
    return free_dates


# ---------------------------------------------------------------------------
# State management
# ---------------------------------------------------------------------------

def load_state() -> dict:
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(state: dict):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def should_notify(new: dict, old: dict) -> bool:
    if not new.get("free_dates"):
        return False
    if not old:
        return True
    if new.get("first_available") != old.get("first_available"):
        return True
    last = old.get("last_notified")
    if last:
        age = datetime.utcnow() - datetime.fromisoformat(last)
        if age > timedelta(hours=24):
            return True
    return False


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------

def send_telegram(data: dict):
    token, chat_id = os.environ.get("TELEGRAM_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("[NOTIFY] Telegram skipped — token / chat_id not set.")
        return

    first   = data.get("first_available") or "Unknown"
    checked = data["checked_at"][:16].replace("T", " ")
    dates   = " | ".join(data["free_dates"][:10])

    text = (
        "📅 <b>Appointment Available — Auslaenderamt!</b>\n\n"
        f"🕐 Checked: {checked} UTC\n"
        f"📅 First available: <b>{first}</b>\n"
        f"⏰ Free dates: {dates}\n\n"
        f"🔗 <a href='{BASE_URL}'>Book now</a>"
    )
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=15,
        )
        r.raise_for_status()
        print(f"[NOTIFY] Telegram → {chat_id}")
    except Exception as e:
        print(f"[NOTIFY] Telegram failed: {e}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print(f"Termin Bot  |  {datetime.utcnow().isoformat()} UTC")
    print(f"Target: {BASE_URL}")
    print("=" * 60)

    old = load_state()

    free_dates = asyncio.run(get_free_dates())

    new = {
        "checked_at":     datetime.utcnow().isoformat(),
        "url":            BASE_URL,
        "free_dates":     free_dates,
        "first_available": free_dates[0] if free_dates else None,
    }

    if should_notify(new, old):
        print("\n--- Sending notifications ---")
        send_telegram(new)
        new["last_notified"] = datetime.utcnow().isoformat()
    else:
        reason = "no free dates" if not free_dates else "no change since last run"
        print(f"\n[SKIP] No notification — {reason}.")
        if old.get("last_notified"):
            new["last_notified"] = old["last_notified"]

    save_state(new)
    print("\n[DONE]")


if __name__ == "__main__":
    main()
