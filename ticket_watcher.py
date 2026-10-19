"""
Watches the A.R.T. "1972" page and emails/texts you when any performance
stops showing "Sold Out".

Setup:
    pip install requests beautifulsoup4

Set these environment variables (don't hard-code your password):
    SMTP_USER      your Gmail address, e.g. you@gmail.com
    SMTP_PASS      a Gmail *App Password* (not your normal password)
    ALERT_TO       comma-separated recipients, e.g.
                   "you@gmail.com,6175551234@vtext.com"
    NTFY_TOPIC     (optional) an ntfy.sh topic name for phone push alerts

Run:
    python ticket_watcher.py
"""

import json
import os
import re
import smtplib
import time
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path

import requests
from bs4 import BeautifulSoup

URL = "https://americanrepertorytheater.org/shows-events/1972-a-rock-opera/"
CHECK_EVERY_SECONDS = 10 * 60
STATE_FILE = Path(__file__).with_name("ticket_state.json")

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS")
ALERT_TO = [a.strip() for a in os.getenv("ALERT_TO", "").split(",") if a.strip()]
NTFY_TOPIC = os.getenv("NTFY_TOPIC")

WEEKDAYS = {"Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"}
TIME_RE = re.compile(r"^\d{1,2}(:\d{2})?\s*(AM|PM)\s*ET$", re.I)
HEADERS = {"User-Agent": "Mozilla/5.0 (personal ticket availability checker)"}


def log(msg):
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


def get_performances():
    """Return {"Tuesday October 27 7:30PM ET": "Sold Out" | "Available"}."""
    html = requests.get(URL, headers=HEADERS, timeout=30).text
    soup = BeautifulSoup(html, "html.parser")
    lines = [l.strip() for l in soup.get_text("\n").splitlines() if l.strip()]

    shows = {}
    for i, line in enumerate(lines):
        if not TIME_RE.match(line) or i < 2:
            continue
        label = f"{lines[i - 2]} {lines[i - 1]} {line}"
        # Look at the lines after the time, up to the next performance.
        status = "Available"
        for nxt in lines[i + 1 : i + 8]:
            if nxt in WEEKDAYS or TIME_RE.match(nxt):
                break
            if "sold out" in nxt.lower():
                status = "Sold Out"
                break
        shows[label] = status
    return shows


def notify(subject, body):
    if SMTP_USER and SMTP_PASS and ALERT_TO:
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = SMTP_USER, ", ".join(ALERT_TO), subject
        msg.set_content(body)
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
            s.starttls()
            s.login(SMTP_USER, SMTP_PASS)
            s.send_message(msg)
        log(f"Email sent to {ALERT_TO}")
    if NTFY_TOPIC:
        requests.post(f"https://ntfy.sh/{NTFY_TOPIC}", data=body.encode(),
                      headers={"Title": subject, "Click": URL}, timeout=15)
        log("ntfy push sent")


def load_state():
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {}


def check_once():
    shows = get_performances()
    if not shows:
        log("Couldn't find any performances. The page layout may have changed.")
        return

    previous = load_state()
    open_now = [name for name, st in shows.items() if st == "Available"]
    newly_open = [n for n in open_now if previous.get(n) != "Available"]

    log(f"{len(shows)} performances found, {len(open_now)} available")
    if newly_open:
        body = "Tickets may be available for:\n\n" + "\n".join(f"  - {n}" for n in newly_open)
        body += f"\n\nBook here: {URL}"
        notify("1972 tickets available!", body)

    STATE_FILE.write_text(json.dumps(shows, indent=2))


if __name__ == "__main__":
    if "--test" in os.sys.argv:
        notify("Ticket watcher test", "If you got this, alerts are working.")
        raise SystemExit
    if "--once" in os.sys.argv:  # used by GitHub Actions: check once and exit
        check_once()
        raise SystemExit
    log("Watching " + URL)
    while True:
        try:
            check_once()
        except Exception as e:
            log(f"Error: {e}")
        time.sleep(CHECK_EVERY_SECONDS)
