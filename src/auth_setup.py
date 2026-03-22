"""
auth_setup.py — One-time OAuth2 authorization for Google Drive/Docs access.

Run this once to authorize the app and save credentials/token.json.
After that, write_doc.py will use the saved token automatically.

Usage:
  python src/auth_setup.py

Prerequisites:
  1. Go to Google Cloud Console → APIs & Services → Credentials
  2. Create an OAuth 2.0 Client ID (Application type: Desktop app)
  3. Download the JSON and save as credentials/oauth_credentials.json
"""

from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
OAUTH_CREDS_FILE = PROJECT_ROOT / "credentials/oauth_credentials.json"
TOKEN_FILE = PROJECT_ROOT / "credentials/token.json"

SCOPES = [
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive",
]


def main():
    if not OAUTH_CREDS_FILE.exists():
        print(f"ERROR: OAuth credentials file not found at {OAUTH_CREDS_FILE}")
        print()
        print("To create it:")
        print("  1. Go to https://console.cloud.google.com")
        print("  2. APIs & Services → Credentials → Create Credentials")
        print("  3. Choose 'OAuth 2.0 Client ID' → Application type: Desktop app")
        print("  4. Download JSON → save as credentials/oauth_credentials.json")
        return

    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(str(OAUTH_CREDS_FILE), SCOPES)
    creds = flow.run_local_server(port=0)

    TOKEN_FILE.write_text(creds.to_json())
    print(f"Authorization complete. Token saved to {TOKEN_FILE}")
    print("You can now run the lesson plan workflow normally.")


if __name__ == "__main__":
    main()
