"""
oauth_setup.py — run this ONCE locally to get your Gmail refresh token.

Usage:
  1. Create a Google Cloud project and OAuth 2.0 Desktop credentials
     (see README.md for step-by-step)
  2. Set GMAIL_CLIENT_ID and GMAIL_CLIENT_SECRET as environment variables
     OR paste them directly into the constants below
  3. Run:  python oauth_setup.py
  4. A browser window opens — sign in and grant access
  5. Copy the refresh_token printed to the console
  6. Add it as a GitHub secret: GMAIL_REFRESH_TOKEN

You only need to run this once. The refresh token doesn't expire unless
you revoke access in your Google account.
"""

import os
import json
import urllib.request
import urllib.parse
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler

CLIENT_ID     = os.environ.get("GMAIL_CLIENT_ID", "PASTE_CLIENT_ID_HERE")
CLIENT_SECRET = os.environ.get("GMAIL_CLIENT_SECRET", "PASTE_CLIENT_SECRET_HERE")
REDIRECT_URI  = "http://localhost:8080"
SCOPES        = "https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/gmail.send"

auth_code = None


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        global auth_code
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        if "code" in params:
            auth_code = params["code"][0]
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"<h2>Auth complete. You can close this window.</h2>")
        else:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"No code received.")

    def log_message(self, *args):
        pass  # suppress server logs


def main():
    auth_url = (
        "https://accounts.google.com/o/oauth2/v2/auth"
        f"?client_id={CLIENT_ID}"
        f"&redirect_uri={urllib.parse.quote(REDIRECT_URI)}"
        f"&response_type=code"
        f"&scope={urllib.parse.quote(SCOPES)}"
        f"&access_type=offline"
        f"&prompt=consent"
    )

    print("Opening browser for Google OAuth...")
    print(f"\nIf it doesn't open automatically, go to:\n{auth_url}\n")
    webbrowser.open(auth_url)

    server = HTTPServer(("localhost", 8080), Handler)
    print("Waiting for OAuth callback on localhost:8080...")
    server.handle_request()

    if not auth_code:
        print("ERROR: No auth code received.")
        return

    # Exchange code for tokens
    body = urllib.parse.urlencode({
        "code":          auth_code,
        "client_id":     CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "redirect_uri":  REDIRECT_URI,
        "grant_type":    "authorization_code",
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://oauth2.googleapis.com/token",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        tokens = json.loads(resp.read().decode("utf-8"))

    print("\n" + "=" * 60)
    print("SUCCESS — add these to your GitHub repo secrets:")
    print("=" * 60)
    print(f"\nGMAIL_REFRESH_TOKEN:\n{tokens.get('refresh_token', 'NOT PRESENT — re-run with prompt=consent')}")
    print("\n(GMAIL_CLIENT_ID and GMAIL_CLIENT_SECRET you already have)")
    print("=" * 60)


if __name__ == "__main__":
    main()
