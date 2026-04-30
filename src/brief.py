"""
Daily Brief — fetches news via Anthropic web search, scans Gmail for flagged
senders, and emails an HTML brief to the configured recipient.

Required environment variables (set as GitHub Actions secrets):
  ANTHROPIC_API_KEY   — from console.anthropic.com
  GMAIL_CLIENT_ID     — from Google Cloud Console OAuth 2.0 credentials
  GMAIL_CLIENT_SECRET — from Google Cloud Console OAuth 2.0 credentials
  GMAIL_REFRESH_TOKEN — generated once via oauth_setup.py
  BRIEF_RECIPIENT     — email address to send the brief to (e.g. you@gmail.com)
"""

import os
import json
import base64
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

ANTHROPIC_API_KEY   = os.environ["ANTHROPIC_API_KEY"]
GMAIL_CLIENT_ID     = os.environ["GMAIL_CLIENT_ID"]
GMAIL_CLIENT_SECRET = os.environ["GMAIL_CLIENT_SECRET"]
GMAIL_REFRESH_TOKEN = os.environ["GMAIL_REFRESH_TOKEN"]
BRIEF_RECIPIENT     = os.environ["BRIEF_RECIPIENT"]

CENTRAL = timezone(timedelta(hours=-5))  # CST; CDT is -6 but close enough for display

FLAGGED_SENDERS = [
    "lyon", "scott lyon", "caseworker", "guardian", "gal",
    "juvenile court", "dhs", "dept of human services", "foster",
]
FLAGGED_SUBJECTS = [
    "hearing", "tpr", "cina", "guardian", "placement",
    "court", "custody", "visitation", "order",
]

NEWS_SYSTEM_PROMPT = """You are a geopolitical and domestic policy analyst producing a daily brief \
for Paul, a software engineering manager in Ankeny Iowa. He wants structural and strategic framing — \
what developments actually mean, not AP wire summaries. He tracks: US-Iran conflict, \
China-Taiwan posture, Trump administration domestic and foreign policy, 2026 midterm election \
race ratings, Iowa agriculture and state politics.

Be analytical. Flag genuine signal. If a topic is quiet, say so in one line. Never pad.

Format your entire response as clean inline-styled HTML for email embedding. \
Use this exact structure for each topic:

<h3 style='color:#333;margin:20px 0 8px;font-size:15px;border-left:3px solid #ddd;padding-left:10px;'>TOPIC NAME</h3>

Each item:
<div style='margin-bottom:14px;'>
  <div style='font-size:14px;font-weight:600;color:#222;'>Headline</div>
  <p style='font-size:13px;color:#444;margin:4px 0 0;line-height:1.6;'>Two-sentence analytical summary.</p>
</div>

If quiet:
<p style='font-size:13px;color:#999;font-style:italic;margin:0 0 16px;'>Quiet — no significant movement.</p>

No markdown. No backticks. No preamble or postamble. Start directly with the first h3 tag."""

NEWS_USER_PROMPT = """Search for significant developments in the last 24 hours and produce \
the daily brief covering these topics in order:
1. Iran and Middle East — military, diplomatic, nuclear
2. China and Taiwan — military posture, trade, diplomatic signals
3. Trump administration — significant domestic and foreign policy moves
4. 2026 midterm elections — race rating changes, polling shifts, notable developments
5. Iowa — agriculture markets, state politics, anything Ankeny/DSM relevant"""


# ---------------------------------------------------------------------------
# HTTP helpers (no third-party dependencies)
# ---------------------------------------------------------------------------

def http_post(url, headers, body):
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code} from {url}: {e.read().decode()}") from e


def http_get(url, headers):
    req = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ---------------------------------------------------------------------------
# Gmail OAuth
# ---------------------------------------------------------------------------

def get_gmail_access_token():
    body = {
        "client_id":     GMAIL_CLIENT_ID,
        "client_secret": GMAIL_CLIENT_SECRET,
        "refresh_token": GMAIL_REFRESH_TOKEN,
        "grant_type":    "refresh_token",
    }
    data = urllib.parse.urlencode(body).encode("utf-8")
    req = urllib.request.Request(
        "https://oauth2.googleapis.com/token",
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))["access_token"]


def search_gmail(access_token):
    sender_q  = " OR ".join(f'from:"{s}"' for s in FLAGGED_SENDERS)
    subject_q = " OR ".join(f'subject:"{s}"' for s in FLAGGED_SUBJECTS)
    query = urllib.parse.quote(f"({sender_q}) OR ({subject_q}) newer_than:2d")
    url = f"https://gmail.googleapis.com/gmail/v1/users/me/messages?q={query}&maxResults=15"
    headers = {"Authorization": f"Bearer {access_token}"}

    result = http_get(url, headers)
    messages = result.get("messages", [])
    if not messages:
        return []

    items = []
    for msg in messages[:10]:
        detail = http_get(
            f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{msg['id']}?format=metadata&metadataHeaders=From&metadataHeaders=Subject",
            headers,
        )
        headers_list = detail.get("payload", {}).get("headers", [])
        from_val    = next((h["value"] for h in headers_list if h["name"] == "From"), "")
        subject_val = next((h["value"] for h in headers_list if h["name"] == "Subject"), "")
        snippet     = detail.get("snippet", "")[:160]

        from_lower    = from_val.lower()
        subject_lower = subject_val.lower()
        is_urgent = any(kw in from_lower or kw in subject_lower
                        for kw in ["lyon", "hearing", "tpr", "order", "court"])

        items.append({
            "from":      from_val,
            "subject":   subject_val,
            "snippet":   snippet,
            "is_urgent": is_urgent,
        })

    return items


def send_gmail(access_token, subject, html_body):
    msg = MIMEMultipart("alternative")
    msg["To"]      = BRIEF_RECIPIENT
    msg["From"]    = BRIEF_RECIPIENT
    msg["Subject"] = subject
    msg.attach(MIMEText(html_body, "html"))

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
    http_post(
        "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
        {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
        {"raw": raw},
    )


# ---------------------------------------------------------------------------
# Anthropic — news via web search
# ---------------------------------------------------------------------------

def fetch_news():
    body = {
        "model":      "claude-sonnet-4-20250514",
        "max_tokens": 2500,
        "tools": [{"type": "web_search_20250305", "name": "web_search"}],
        "system":     NEWS_SYSTEM_PROMPT,
        "messages":   [{"role": "user", "content": NEWS_USER_PROMPT}],
    }
    headers = {
        "Content-Type":    "application/json",
        "x-api-key":       ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
    }
    data = http_post("https://api.anthropic.com/v1/messages", headers, body)
    text_blocks = [b["text"] for b in data.get("content", []) if b.get("type") == "text"]
    return "\n".join(text_blocks) if text_blocks else "<p style='color:#999;'>News unavailable.</p>"


# ---------------------------------------------------------------------------
# HTML assembly
# ---------------------------------------------------------------------------

def render_email_section(html_items, empty_msg):
    if not html_items:
        return f"<p style='font-size:13px;color:#999;font-style:italic;'>{empty_msg}</p>"
    return html_items


def render_email_items(items):
    if not items:
        return ""
    rows = []
    for item in items:
        badge_style = (
            "background:#FCEBEB;color:#A32D2D;" if item["is_urgent"]
            else "background:#E6F1FB;color:#185FA5;"
        )
        badge_label = "URGENT" if item["is_urgent"] else "FLAGGED"
        rows.append(f"""
<div style='padding:8px 0;border-bottom:1px solid #f0f0f0;'>
  <div style='font-size:14px;'>
    <span style='font-size:11px;padding:2px 8px;border-radius:4px;margin-right:8px;{badge_style}'>{badge_label}</span>
    <strong>{item['from']}</strong> — {item['subject']}
  </div>
  <div style='font-size:13px;color:#666;margin-top:3px;'>{item['snippet']}</div>
</div>""")
    return "\n".join(rows)


def build_email(now_ct, email_items, news_html):
    date_str  = now_ct.strftime("%A, %B %-d, %Y")
    time_str  = now_ct.strftime("%-I:%M %p CT")
    subj_str  = now_ct.strftime("%a %b %-d")

    email_section = render_email_items(email_items)
    email_block   = render_email_section(email_section, "No flagged email in last 48 hours.")

    return subj_str, f"""<!DOCTYPE html>
<html><body style='font-family:-apple-system,Arial,sans-serif;max-width:680px;margin:0 auto;color:#222;padding:24px 16px;'>

<div style='border-bottom:2px solid #222;padding-bottom:12px;margin-bottom:24px;'>
  <h1 style='font-size:22px;font-weight:600;margin:0;'>Morning Brief</h1>
  <p style='font-size:13px;color:#888;margin:4px 0 0;'>{date_str} &nbsp;·&nbsp; {time_str}</p>
</div>

<h2 style='font-size:12px;font-weight:600;letter-spacing:0.07em;text-transform:uppercase;color:#999;margin:0 0 10px;'>Legal &amp; Email Alerts</h2>
{email_block}

<h2 style='font-size:12px;font-weight:600;letter-spacing:0.07em;text-transform:uppercase;color:#999;margin:28px 0 4px;'>News &amp; Geopolitical Signal</h2>
{news_html}

<hr style='margin:32px 0 16px;border:none;border-top:1px solid #eee;'>
<p style='font-size:11px;color:#ccc;margin:0;'>Daily Brief · Ankeny IA · {now_ct.isoformat()}</p>

</body></html>"""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    now_ct = datetime.now(CENTRAL)
    print(f"[brief] Starting — {now_ct.strftime('%Y-%m-%d %H:%M CT')}")

    print("[brief] Fetching Gmail access token...")
    access_token = get_gmail_access_token()

    print("[brief] Searching Gmail for flagged email...")
    email_items = search_gmail(access_token)
    print(f"[brief] Found {len(email_items)} flagged email(s)")

    print("[brief] Fetching news from Anthropic (web search)...")
    news_html = fetch_news()
    print("[brief] News fetched")

    subject_date, html_body = build_email(now_ct, email_items, news_html)
    subject = f"Morning Brief — {subject_date}"

    print(f"[brief] Sending to {BRIEF_RECIPIENT}...")
    send_gmail(access_token, subject, html_body)
    print("[brief] Done.")


if __name__ == "__main__":
    main()
