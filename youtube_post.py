
import os
import sqlite3
import sys

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from youtube_auth import get_credentials


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "videos.db")


def get_approved_comments():
    with sqlite3.connect(DB_PATH) as db:
        return db.execute("""
            SELECT c.video_id, v.title, c.comment
            FROM comment_drafts c
            JOIN videos v ON v.video_id = c.video_id
            WHERE c.review_status = 'approved'
            ORDER BY c.created_at ASC
        """).fetchall()


def ensure_post_log():
    with sqlite3.connect(DB_PATH) as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS posted_comments (
                video_id TEXT PRIMARY KEY,
                youtube_comment_id TEXT,
                posted_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP
            )
        """)
        db.commit()


def already_posted(video_id):
    with sqlite3.connect(DB_PATH) as db:
        return db.execute("""
            SELECT 1 FROM posted_comments
            WHERE video_id = ?
        """, (video_id,)).fetchone() is not None


def post_one_comment(video_id, comment):
    credentials = get_credentials()

    youtube = build(
        "youtube",
        "v3",
        credentials=credentials
    )

    response = youtube.commentThreads().insert(
        part="snippet",
        body={
            "snippet": {
                "videoId": video_id,
                "topLevelComment": {
                    "snippet": {
                        "textOriginal": comment
                    }
                }
            }
        }
    ).execute()

    return response.get("id")


def record_success(video_id, comment_id):
    with sqlite3.connect(DB_PATH) as db:
        db.execute("""
            INSERT INTO posted_comments
                (video_id, youtube_comment_id)
            VALUES (?, ?)
        """, (video_id, comment_id))

        db.execute("""
            UPDATE comment_drafts
            SET review_status = 'posted'
            WHERE video_id = ?
              AND review_status = 'approved'
        """, (video_id,))

        db.commit()


def main():
    if not os.path.exists(DB_PATH):
        print("[ERROR] videos.db not found")
        return

    ensure_post_log()
    comments = get_approved_comments()

    available = [
        item for item in comments
        if not already_posted(item[0])
    ]

    if not available:
        print("[INFO] No approved comments to post.")
        return

    print("\n===== APPROVED COMMENTS =====")

    for number, (video_id, title, comment) in enumerate(
        available, start=1
    ):
        print(f"\n{number}. {title}")
        print(f"https://youtube.com/watch?v={video_id}")
        print(comment)

    print("\n0. Cancel")

    selection = input(
        "\nSelect ONE comment number: "
    ).strip()

    if selection == "0":
        print("[CANCELLED] Nothing posted.")
        return

    try:
        index = int(selection) - 1
        if not 0 <= index < len(available):
            raise ValueError()
    except ValueError:
        print("[ERROR] Invalid selection.")
        return

    video_id, title, comment = available[index]

    print("\n===== FINAL CONFIRMATION =====")
    print(f"VIDEO: {title}")
    print(f"URL: https://youtube.com/watch?v={video_id}")
    print(f"\nCOMMENT:\n{comment}")

    print(
        "\nThis will publish the comment "
        "to YouTube as your connected account."
    )

    confirmation = input(
        "Type POST to publish, or anything else to cancel: "
    ).strip()

    if confirmation != "POST":
        print("[CANCELLED] Nothing posted.")
        return

    if already_posted(video_id):
        print("[BLOCKED] Already posted.")
        return

    try:
        print("[YOUTUBE] Sending comment...")
        comment_id = post_one_comment(video_id, comment)
        print("[YOUTUBE] API accepted the comment.")
        record_success(video_id, comment_id)
        print("[SUCCESS] Comment recorded as posted.")
        print(f"[COMMENT ID] {comment_id}")

    except HttpError as error:
        print(f"[YOUTUBE ERROR] {error}")
        print("[INFO] Comment was not marked posted.")

    except Exception as error:
        print(f"[ERROR] {error}")
        print(
            "[WARNING] If the request reached YouTube, "
            "check the video before retrying."
        )


if __name__ == "__main__":
    main()
