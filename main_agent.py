
import os
import html
import time
import sqlite3
import argparse
import re

from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
from googleapiclient.discovery import build
from langgraph_agent import agent


# ==========================================
# CONFIGURATION
# ==========================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

load_dotenv(os.path.join(BASE_DIR, ".env"))

API_KEY = os.getenv("YOUTUBE_API_KEY")
DB_PATH = os.path.join(BASE_DIR, "videos.db")

MAX_RUNS = 3
INTERVAL_MINUTES = 20
SEARCH_QUERIES = ("Arda Güler", "Arda Guler")
OFFICIAL_CHANNELS = {"Real Madrid": "@realmadrid", "LALIGA": "@LaLiga"}
MAX_CHANNEL_PAGES = 3
LALIGA_MADRID_PATTERN = re.compile(
    r"real[\s-]+madrid|madrid[\s-]+cf|los[\s-]+blancos|merengues|\brma\b",
    re.IGNORECASE
)
MAX_RESULTS = 10
ANALYSIS_BATCH_SIZE = 10

if not API_KEY:
    raise RuntimeError("YOUTUBE_API_KEY missing")

youtube = build(
    "youtube",
    "v3",
    developerKey=API_KEY
)


# ==========================================
# DATABASE
# ==========================================

def initialize_database():

    with sqlite3.connect(DB_PATH) as db:

        db.execute("""
            CREATE TABLE IF NOT EXISTS videos (
                video_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                discovered_at TEXT NOT NULL,
                status TEXT NOT NULL
            )
        """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS langgraph_results (
                video_id TEXT PRIMARY KEY,
                decision TEXT NOT NULL,
                reason TEXT NOT NULL
            )
        """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS comment_drafts (
                video_id TEXT PRIMARY KEY,
                comment TEXT NOT NULL,
                review_status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (video_id)
                    REFERENCES videos(video_id)
            )
        """)

        columns = {row[1] for row in db.execute("PRAGMA table_info(videos)")}
        if "published_at" not in columns:
            db.execute("ALTER TABLE videos ADD COLUMN published_at TEXT")

        db.commit()


# ==========================================
# YOUTUBE SEARCH
# ==========================================

def parse_youtube_date(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def get_official_uploads_playlist(channel_name, handle):
    """Resolve an official channel by handle and obtain its uploads playlist."""
    response = youtube.channels().list(
        part="snippet,contentDetails", forHandle=handle
    ).execute()
    items = response.get("items", [])
    if not items:
        raise RuntimeError(f"Official channel not found: {handle}")

    channel = items[0]
    actual_name = channel["snippet"]["title"]
    normalized = actual_name.casefold()
    if channel_name == "Real Madrid" and "real madrid" not in normalized:
        raise RuntimeError(f"Unexpected Real Madrid channel: {actual_name}")
    if channel_name == "LALIGA" and "laliga" not in normalized.replace(" ", ""):
        raise RuntimeError(f"Unexpected LALIGA channel: {actual_name}")

    playlist_id = channel["contentDetails"]["relatedPlaylists"]["uploads"]
    print(f"[CHANNEL] {channel_name}: {actual_name} ({channel['id']})")
    return playlist_id


def get_recent_channel_videos(channel_name, handle, cutoff, now):
    """Read recent uploads directly, avoiding expensive channel search calls."""
    playlist_id = get_official_uploads_playlist(channel_name, handle)
    result = {}
    page_token = None

    for _ in range(MAX_CHANNEL_PAGES):
        request = dict(
            part="snippet,contentDetails",
            playlistId=playlist_id,
            maxResults=50,
        )
        if page_token:
            request["pageToken"] = page_token
        response = youtube.playlistItems().list(**request).execute()
        found_old = False

        for item in response.get("items", []):
            snippet = item.get("snippet", {})
            video_id = item.get("contentDetails", {}).get("videoId")
            if not video_id:
                continue
            # Playlist item publication can differ from the video publication;
            # the definitive 24-hour check happens in videos.list below.
            video_date = item.get("contentDetails", {}).get("videoPublishedAt")
            if video_date:
                published = parse_youtube_date(video_date)
                if published < cutoff:
                    found_old = True
                    continue
                if published > now:
                    continue

            if channel_name == "LALIGA":
                text = html.unescape(snippet.get("title", "")) + " " + html.unescape(snippet.get("description", ""))
                if not LALIGA_MADRID_PATTERN.search(text):
                    continue

            result[video_id] = channel_name

        page_token = response.get("nextPageToken")
        if not page_token or found_old:
            break

    print(f"[CHANNEL RESULTS] {channel_name}: {len(result)} candidates")
    return result


def search_youtube():
    print("\n[SEARCH] YouTube: last 24 hours, four sources")
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=24)
    published_after = cutoff.isoformat(timespec="seconds").replace("+00:00", "Z")
    candidates = {}  # video_id -> source name
    errors = []

    for query in SEARCH_QUERIES:
        print(f"[QUERY] {query}")
        try:
            response = youtube.search().list(
                part="snippet", q=query, type="video", order="date",
                publishedAfter=published_after, maxResults=MAX_RESULTS
            ).execute()
            for item in response.get("items", []):
                video_id = item.get("id", {}).get("videoId")
                if video_id:
                    candidates.setdefault(video_id, f"Search: {query}")
        except Exception as error:
            errors.append(f"Search {query}: {error}")
            print(f"[SOURCE ERROR] {errors[-1]}")

    for channel_name, handle in OFFICIAL_CHANNELS.items():
        try:
            channel_videos = get_recent_channel_videos(
                channel_name, handle, cutoff, now
            )
            for video_id, source in channel_videos.items():
                candidates.setdefault(video_id, source)
        except Exception as error:
            errors.append(f"{channel_name}: {error}")
            print(f"[SOURCE ERROR] {errors[-1]}")

    if errors:
        # Do not silently claim the search was complete when a source failed.
        raise RuntimeError("Some sources failed: " + " | ".join(errors))

    if not candidates:
        print("[SEARCH COMPLETE] No recent videos found")
        return 0

    new_count = 0
    skipped_old = 0
    with sqlite3.connect(DB_PATH) as db:
        # videos.list accepts at most 50 IDs per call.
        ids = list(candidates)
        for start in range(0, len(ids), 50):
            details = youtube.videos().list(
                part="snippet", id=",".join(ids[start:start + 50])
            ).execute()
            for item in details.get("items", []):
                video_id = item["id"]
                snippet = item["snippet"]
                published_at = parse_youtube_date(snippet["publishedAt"])
                if not (cutoff <= published_at <= now):
                    skipped_old += 1
                    continue

                # Double-check that LALIGA uploads concern Real Madrid.
                if candidates[video_id] == "LALIGA":
                    text = html.unescape(snippet.get("title", "")) + " " + html.unescape(snippet.get("description", ""))
                    if not LALIGA_MADRID_PATTERN.search(text):
                        continue

                title = html.unescape(snippet["title"])
                cursor = db.execute("""
                    INSERT OR IGNORE INTO videos
                    (video_id, title, discovered_at, status, published_at)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    video_id, title, now.isoformat(),
                    "pending_analysis", published_at.isoformat()
                ))
                if cursor.rowcount:
                    new_count += 1
                    print(f"[NEW VIDEO] [{candidates[video_id]}] {title}")
                    print(f"https://youtube.com/watch?v={video_id}")

    print(f"[SEARCH COMPLETE] {new_count} new; {skipped_old} old skipped")
    return new_count


# ==========================================
# VIDEO DESCRIPTION
# ==========================================

def get_video_description(video_id):

    response = youtube.videos().list(
        part="snippet",
        id=video_id
    ).execute()

    items = response.get("items", [])

    if not items:
        raise ValueError(f"Video not found: {video_id}")

    return html.unescape(
        items[0]["snippet"].get("description", "")
    )


# ==========================================
# ANALYZE VIDEO
# ==========================================

def analyze_video(db, video_id, title):

    print(f"\n[AI ANALYSIS] {title}")
    print(f"https://youtube.com/watch?v={video_id}")

    try:
        description = get_video_description(video_id)

        print(
            f"[DESCRIPTION] Retrieved "
            f"{len(description)} characters"
        )

        result = agent.invoke({
            "title": title,
            "description": description[:3000],
            "decision": "",
            "reason": "",
            "comment_draft": ""
        })

        decision = result["decision"]
        reason = result["reason"]
        comment = result.get("comment_draft", "").strip()

        if decision not in (
            "relevant", "irrelevant", "uncertain"
        ):
            raise ValueError("Invalid AI decision")

        if decision == "relevant" and not comment:
            raise ValueError("Comment draft is empty")

        existing = db.execute("""
            SELECT review_status
            FROM comment_drafts
            WHERE video_id = ?
        """, (video_id,)).fetchone()

        # Protect already reviewed comments.
        protected = (
            existing is not None
            and existing[0] != "pending_review"
        )

        db.execute("""
            INSERT INTO langgraph_results
            (video_id, decision, reason)
            VALUES (?, ?, ?)
            ON CONFLICT(video_id)
            DO UPDATE SET
                decision = excluded.decision,
                reason = excluded.reason
        """, (video_id, decision, reason))

        db.execute("""
            UPDATE videos
            SET status = ?
            WHERE video_id = ?
        """, (decision, video_id))

        if protected:
            print("[COMMENT] Existing reviewed draft preserved")

        elif decision == "relevant":

            db.execute("""
                INSERT INTO comment_drafts
                (video_id, comment, review_status, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(video_id)
                DO UPDATE SET
                    comment = excluded.comment,
                    review_status = excluded.review_status,
                    created_at = excluded.created_at
            """, (
                video_id,
                comment,
                "pending_review",
                datetime.now(timezone.utc).isoformat()
            ))

            print("[COMMENT SAVED] pending_review")

        else:
            db.execute("""
                DELETE FROM comment_drafts
                WHERE video_id = ?
                  AND review_status = 'pending_review'
            """, (video_id,))

        db.commit()

        print(f"[SAVED] {decision}")
        print(f"[REASON] {reason}")

        return True

    except Exception as error:
        db.rollback()
        print(f"[ANALYSIS ERROR] {error}")
        return False


# ==========================================
# NORMAL ANALYSIS
# ==========================================

def analyze_pending():

    with sqlite3.connect(DB_PATH) as db:

        videos = db.execute("""
            SELECT v.video_id, v.title
            FROM videos v
            LEFT JOIN langgraph_results r
                ON v.video_id = r.video_id
            WHERE r.video_id IS NULL
              AND v.published_at IS NOT NULL
              AND v.published_at >= ?
            ORDER BY v.discovered_at DESC
            LIMIT ?
        """, (
            (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat(),
            ANALYSIS_BATCH_SIZE
        )).fetchall()

        if not videos:
            print("[MEMORY] No unprocessed videos")
            return

        for video_id, title in videos:
            analyze_video(db, video_id, title)


# ==========================================
# REANALYSIS
# ==========================================

def reanalyze_existing(limit):

    print("\n===== REANALYSIS MODE =====")

    with sqlite3.connect(DB_PATH) as db:

        videos = db.execute("""
            SELECT video_id, title
            FROM videos
            ORDER BY discovered_at DESC
            LIMIT ?
        """, (limit,)).fetchall()

        if not videos:
            print("[MEMORY] No videos found")
            return

        success_count = 0

        for video_id, title in videos:
            if analyze_video(db, video_id, title):
                success_count += 1

        print("\n[REANALYSIS COMPLETE]")
        print(f"[PROCESSED] {success_count}/{len(videos)}")


# ==========================================
# VIEW COMMENT DRAFTS
# ==========================================

def show_comments():

    print("\n===== COMMENT DRAFTS =====")

    with sqlite3.connect(DB_PATH) as db:

        rows = db.execute("""
            SELECT
                v.title,
                c.video_id,
                c.comment,
                c.review_status
            FROM comment_drafts c
            JOIN videos v ON v.video_id = c.video_id
            ORDER BY c.created_at DESC
        """).fetchall()

        if not rows:
            print("[INFO] No comment drafts found")
            return

        for index, row in enumerate(rows, start=1):

            title, video_id, comment, status = row

            print(f"\n--- DRAFT {index} ---")
            print(f"VIDEO: {title}")
            print(
                f"URL: https://youtube.com/watch?v={video_id}"
            )
            print(f"COMMENT:\n{comment}")
            print(f"STATUS: {status}")

        print(f"\n[TOTAL DRAFTS] {len(rows)}")


# ==========================================
# RUN CYCLE
# ==========================================

def run_cycle(number):

    print(f"\n===== RUN {number}/{MAX_RUNS} =====")

    try:
        search_youtube()
    except Exception as error:
        print(f"[SEARCH ERROR] {error}")

    analyze_pending()

    print(f"\n[CYCLE {number} COMPLETE]")


# ==========================================
# MAIN
# ==========================================

def main():

    parser = argparse.ArgumentParser(
        description="Arda Guler AI YouTube Agent"
    )

    parser.add_argument(
        "--reanalyze",
        action="store_true"
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=5
    )

    parser.add_argument(
        "--comments",
        action="store_true"
    )

    args = parser.parse_args()

    if args.limit < 1:
        parser.error("--limit must be at least 1")

    initialize_database()

    try:
        if args.comments:
            show_comments()
            return

        if args.reanalyze:
            reanalyze_existing(args.limit)
            return

        for number in range(1, MAX_RUNS + 1):

            run_cycle(number)

            if number < MAX_RUNS:
                print(
                    f"\nWaiting {INTERVAL_MINUTES} minutes..."
                )
                time.sleep(INTERVAL_MINUTES * 60)

        print("\nRun limit reached. Agent stopped.")

    except KeyboardInterrupt:
        print("\nAgent stopped by user.")


if __name__ == "__main__":
    main()
