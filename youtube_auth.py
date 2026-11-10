
import os
import json

from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build


# ==========================================
# CONFIGURATION
# ==========================================

BASE_DIR = os.path.dirname(
    os.path.abspath(__file__)
)

CLIENT_SECRET_FILE = os.path.join(
    BASE_DIR,
    "client_secret.json"
)

TOKEN_FILE = os.path.join(
    BASE_DIR,
    "youtube_token.json"
)

SCOPES = [
    "https://www.googleapis.com/auth/youtube.force-ssl"
]


# ==========================================
# GOOGLE AUTHENTICATION
# ==========================================

def get_credentials():

    credentials = None

    if os.path.exists(TOKEN_FILE):

        credentials = Credentials.from_authorized_user_file(
            TOKEN_FILE,
            SCOPES
        )

    if credentials and credentials.expired and credentials.refresh_token:

        print("[AUTH] Refreshing access token...")

        credentials.refresh(Request())

    elif not credentials or not credentials.valid:

        if not os.path.exists(CLIENT_SECRET_FILE):

            raise FileNotFoundError(
                "client_secret.json not found"
            )

        print("[AUTH] Opening Google login...")

        flow = InstalledAppFlow.from_client_secrets_file(
            CLIENT_SECRET_FILE,
            SCOPES
        )

        credentials = flow.run_local_server(
            port=0,
            open_browser=True
        )

    if not credentials or not credentials.valid:

        raise RuntimeError(
            "Google authentication failed"
        )

    with open(
        TOKEN_FILE,
        "w",
        encoding="utf-8"
    ) as file:

        file.write(
            credentials.to_json()
        )

    return credentials


# ==========================================
# TEST YOUTUBE CONNECTION
# ==========================================

def test_connection():

    credentials = get_credentials()

    youtube = build(
        "youtube",
        "v3",
        credentials=credentials
    )

    print("\n[AUTH] Checking YouTube account...")

    response = youtube.channels().list(
        part="snippet",
        mine=True
    ).execute()

    channels = response.get("items", [])

    if not channels:

        print(
            "[WARNING] Authentication succeeded, "
            "but no YouTube channel was found."
        )

        return

    print("\n===== CONNECTED CHANNEL =====")

    for channel in channels:

        print(
            "Channel:",
            channel["snippet"]["title"]
        )

        print(
            "Channel ID:",
            channel["id"]
        )

    print("\n[SUCCESS] YouTube OAuth connection works.")
    print("[INFO] No comments were posted.")


# ==========================================
# MAIN
# ==========================================

if __name__ == "__main__":

    try:
        test_connection()

    except Exception as error:

        print(
            f"\n[AUTH ERROR] {error}"
        )
