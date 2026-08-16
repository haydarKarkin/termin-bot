# termin-bot

[![Appointment Check](https://github.com/haydarKarkin/termin-bot/actions/workflows/check_appointments.yml/badge.svg?branch=main)](https://github.com/haydarKarkin/termin-bot/actions/workflows/check_appointments.yml)

A GitHub Actions workflow that periodically checks a web page and sends a Telegram notification when a change is detected.

## Setup

1. Fork this repository (must be public for free Actions minutes)
2. Add the following secrets under **Settings → Secrets and variables → Actions**:

| Secret | Description |
|--------|-------------|
| `TERMIN_URL` | Target URL to monitor |
| `TELEGRAM_TOKEN` | Telegram bot token |
| `TELEGRAM_CHAT_ID` | Telegram chat ID |

3. Enable workflows under the **Actions** tab.

## Usage

Runs automatically every hour. To trigger manually: **Actions → Appointment Check → Run workflow**.

## License

MIT
