# Daily Brief

Sends a personalized morning email brief every day at 7 AM — flagged Gmail alerts
(legal/court senders) + geopolitical and domestic news via Anthropic web search.

Zero dependencies beyond Python stdlib. Runs free on GitHub Actions.

---

## Setup (one time, ~30 minutes)

### Step 1 — Fork or push this repo to your GitHub account

Push the contents of this folder to a new repo at github.com/prhaugen.

### Step 2 — Get an Anthropic API key

1. Go to https://console.anthropic.com
2. API Keys → Create Key
3. Copy it — you'll add it as a GitHub secret in Step 4

### Step 3 — Create Google OAuth credentials

This gives the script permission to read your Gmail and send email as you.

1. Go to https://console.cloud.google.com
2. Create a new project (name it anything, e.g. "daily-brief")
3. APIs & Services → Enable APIs → search "Gmail API" → Enable
4. APIs & Services → Credentials → Create Credentials → OAuth 2.0 Client ID
5. Application type: **Desktop app** — name it "daily-brief"
6. Download the JSON — open it and copy `client_id` and `client_secret`
7. APIs & Services → OAuth consent screen
   - User type: External
   - App name: daily-brief
   - Add your Gmail address as a test user
   - Scopes: add `gmail.readonly` and `gmail.send`

### Step 4 — Get your Gmail refresh token (run once on your Windows machine)

```
# In a terminal (cmd or PowerShell):
set GMAIL_CLIENT_ID=your_client_id_here
set GMAIL_CLIENT_SECRET=your_client_secret_here
python src/oauth_setup.py
```

A browser window will open. Sign in with your Gmail account and grant access.
The script prints your `GMAIL_REFRESH_TOKEN` — copy it.

### Step 5 — Add GitHub Secrets

In your GitHub repo → Settings → Secrets and variables → Actions → New repository secret

Add these five secrets:

| Secret name          | Value                                      |
|----------------------|--------------------------------------------|
| `ANTHROPIC_API_KEY`  | From Step 2                                |
| `GMAIL_CLIENT_ID`    | From Step 3                                |
| `GMAIL_CLIENT_SECRET`| From Step 3                                |
| `GMAIL_REFRESH_TOKEN`| From Step 4                                |
| `BRIEF_RECIPIENT`    | Your Gmail address (where to send the brief)|

### Step 6 — Test it

In your GitHub repo → Actions → Daily Brief → Run workflow (manual trigger).

Check your Gmail inbox. The brief should arrive within 2-3 minutes.

### Step 7 — Enable the schedule

GitHub Actions schedules are enabled automatically once the workflow file is in the
repo. It will run daily at 13:00 UTC (7:00 AM CDT / 8:00 AM CST).

---

## Customizing

**Change delivery time:**
Edit `.github/workflows/daily-brief.yml` — adjust the cron line.
- 7 AM CDT (summer): `0 13 * * *`
- 7 AM CST (winter): `0 14 * * *`

**Change news topics or analytical framing:**
Edit `src/brief.py` — `NEWS_SYSTEM_PROMPT` and `NEWS_USER_PROMPT` at the top.

**Change flagged senders/subjects:**
Edit `src/brief.py` — `FLAGGED_SENDERS` and `FLAGGED_SUBJECTS` lists.

**Add calendar support:**
Google Calendar API uses the same OAuth credentials. Add a `fetch_calendar()`
function using the Calendar API v3 `events.list` endpoint with the same
access token pattern.

---

## Cost

- GitHub Actions: free (well within free tier limits)
- Anthropic API: ~$0.01-0.03 per brief (Sonnet with web search)
- Google APIs: free

Monthly cost: under $1.
