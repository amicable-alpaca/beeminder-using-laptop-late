#!/usr/bin/env python3
"""
night_logger_github.py - Tamper-Resistant Version with Fixed extract_violations and Deduplication

FIXED:
1. extract_violations now uses posts table as authoritative source
2. Added deduplication logic to clean up Beeminder before uploading
3. Ensures violations.json matches HSoT database exactly

What it does
------------
- Every 5 seconds, logs whether the local time is between 23:00–03:59.
- On the first 1 of the (local) day, it:
  1) Uploads the local database to GitHub
  2) Triggers GitHub Actions workflow for sync with Beeminder
  3) Continues logging instead of exiting (fixed!)

- The local SQLite DB is the Highest Source of Truth (HSoT):
  - `logs` keeps the raw 0/1 samples
  - `posts` keeps local days (YYYY-MM-DD) that have been posted

Usage
-----
    python3 night_logger_github.py [--verbose] [--interval 5] [--db night_logs.db]
    # GitHub credentials via env:
    GITHUB_TOKEN=... GITHUB_REPO=... python3 night_logger_github.py

System deps
-----------
- requests (install with: sudo apt-get install -y python3-requests)
"""

import argparse
import base64
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, List
import requests  # apt: python3-requests
from collections import defaultdict

DB_PATH = "night_logs.db"

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    logged_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    is_night INTEGER NOT NULL CHECK(is_night IN (0,1))
);
CREATE TABLE IF NOT EXISTS posts (
    ymd TEXT PRIMARY KEY,          -- e.g., 2025-08-15 (LOCAL date)
    posted_at_utc TEXT NOT NULL    -- when we posted to GitHub (UTC timestamp)
);
"""

INSERT_SQL = "INSERT INTO logs (is_night) VALUES (?);"


# ----------------- time / db helpers -----------------

def is_between_23_and_359_local(now: datetime) -> bool:
    """Return True if local time is between 23:00 and 03:59 inclusive."""
    return now.hour >= 23 or now.hour <= 3


def local_ymd(now: datetime) -> str:
    """Local calendar date as YYYY-MM-DD."""
    return now.strftime("%Y-%m-%d")


def open_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    try:
        conn.execute("PRAGMA journal_mode = WAL;")
    except sqlite3.Error:
        pass
    conn.executescript(CREATE_TABLE_SQL)  # create both tables
    conn.commit()
    return conn


def already_posted_today(conn: sqlite3.Connection, ymd: str) -> bool:
    cur = conn.execute("SELECT 1 FROM posts WHERE ymd = ? LIMIT 1;", (ymd,))
    return cur.fetchone() is not None


def mark_posted_today(conn: sqlite3.Connection, ymd: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO posts (ymd, posted_at_utc) VALUES (?, strftime('%Y-%m-%dT%H:%M:%fZ','now'));",
        (ymd,),
    )
    conn.commit()


def clean_beeminder_duplicates(username: str, auth_token: str, goal_slug: str, verbose: bool = False) -> bool:
    """Remove duplicate datapoints from Beeminder, keeping the most recent one for each date"""
    try:
        # Get all datapoints
        url = f"https://www.beeminder.com/api/v1/users/{username}/goals/{goal_slug}/datapoints.json"
        params = {'auth_token': auth_token, 'sort': 'daystamp'}

        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        datapoints = response.json()

        # Group by date
        by_date = defaultdict(list)
        for dp in datapoints:
            by_date[dp['daystamp']].append(dp)

        # Find duplicates
        duplicates_removed = 0
        for date, dps in by_date.items():
            if len(dps) > 1:
                # Sort by ID (most recent first) and keep the first one
                dps_sorted = sorted(dps, key=lambda x: x['id'], reverse=True)
                keep = dps_sorted[0]
                remove = dps_sorted[1:]

                if verbose:
                    print(f"🗑️  Found {len(dps)} datapoints for {date}, keeping ID {keep['id']}, removing {len(remove)} duplicates")

                # Remove duplicates
                for dp in remove:
                    delete_url = f"https://www.beeminder.com/api/v1/users/{username}/goals/{goal_slug}/datapoints/{dp['id']}.json"
                    delete_params = {'auth_token': auth_token}

                    delete_response = requests.delete(delete_url, params=delete_params, timeout=30)
                    if delete_response.status_code == 200:
                        duplicates_removed += 1
                        if verbose:
                            print(f"  ✅ Removed duplicate datapoint {dp['id']} for {date}")
                    else:
                        if verbose:
                            print(f"  ❌ Failed to remove datapoint {dp['id']} for {date}: {delete_response.status_code}")

        if verbose:
            print(f"🧹 Cleaned {duplicates_removed} duplicate datapoints from Beeminder")

        return True

    except requests.exceptions.RequestException as e:
        if verbose:
            print(f"❌ Failed to clean duplicates: {e}")
        return False


def extract_violations(db_path: str) -> Dict:
    """Extract all violations from the database using posts table as authoritative source"""
    from pathlib import Path
    import tempfile
    import shutil

    if not Path(db_path).exists():
        return {
            "violations": [],
            "posted_dates": [],
            "last_updated": datetime.utcnow().isoformat() + "Z",
            "total_violations": 0,
            "unposted_violations": []
        }

    # Work around WAL mode/permission issues by copying database to temp location
    try:
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as temp_db:
            temp_path = temp_db.name

        # Copy database to temp location
        shutil.copy2(db_path, temp_path)

        # Connect to the copy
        conn = sqlite3.connect(temp_path)
        cursor = conn.cursor()

        # Clean up temp file after we're done
        temp_cleanup = temp_path
    except Exception as e:
        # Fallback to direct access if copy fails
        conn = sqlite3.connect(db_path, timeout=30.0)
        cursor = conn.cursor()
        temp_cleanup = None

    # Use posts table as the authoritative source - it knows which dates were posted
    try:
        cursor.execute("SELECT ymd FROM posts ORDER BY ymd")
        posted_dates = [row[0] for row in cursor.fetchall()]
    except sqlite3.OperationalError:
        # If posts table doesn't exist or is inaccessible, assume no posted dates
        posted_dates = []

    violations = []
    # For each posted date, get violation data from logs
    for date_str in posted_dates:
        # Get violations for this specific date using the same logic as the main loop
        cursor.execute("""
            SELECT COUNT(*) as detections, MIN(logged_at) as first_detection
            FROM logs
            WHERE is_night = 1
            AND (
                (strftime('%H', logged_at) <= '03' AND date(logged_at, '-1 day') = ?)
                OR (strftime('%H', logged_at) > '03' AND date(logged_at) = ?)
            )
        """, (date_str, date_str))

        row = cursor.fetchone()
        if row and row[0] > 0:
            detections = row[0]
            first_detection = row[1]

            violations.append({
                "date": date_str,
                "timestamp": first_detection,
                "value": 1,  # Beeminder value for violation
                "comment": f"Night logger violation ({detections} detections)",
                "daystamp": date_str.replace("-", "")  # Beeminder format: YYYYMMDD
            })

    conn.close()

    # Clean up temporary database file if we created one
    if temp_cleanup:
        try:
            import os
            os.unlink(temp_cleanup)
        except:
            pass

    result = {
        "violations": violations,
        "posted_dates": posted_dates,
        "last_updated": datetime.utcnow().isoformat() + "Z",
        "total_violations": len(violations),
        "unposted_violations": []  # All violations in this function are posted by definition
    }

    return result


# ----------------- GitHub API -----------------

class GitHubAPI:
    """Handle GitHub API operations"""

    def __init__(self, token: str, repo: str):
        self.token = token
        self.repo = repo  # format: "owner/repo"
        self.base_url = "https://api.github.com"
        self.headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "night-logger-github/1.0"
        }

    def upload_violations_to_branch(self, db_path: str, branch: str = "main", clean_duplicates: bool = True) -> bool:
        """Generate violations.json from database and upload to a specific branch"""
        try:
            # Clean Beeminder duplicates first (optional)
            if clean_duplicates:
                # Get Beeminder credentials from environment
                username = os.getenv('BEEMINDER_USERNAME')
                auth_token = os.getenv('BEEMINDER_AUTH_TOKEN')
                goal_slug = os.getenv('BEEMINDER_GOAL_SLUG')

                if username and auth_token and goal_slug:
                    print("🧹 Cleaning Beeminder duplicates before upload...")
                    clean_beeminder_duplicates(username, auth_token, goal_slug, verbose=True)
                else:
                    print("ℹ️  Skipping duplicate cleanup - Beeminder credentials not available")

            # Extract violations from the HSoT database
            violations_data = extract_violations(db_path)

            # Convert to JSON
            violations_json = json.dumps(violations_data, indent=2)
            violations_base64 = base64.b64encode(violations_json.encode('utf-8')).decode('utf-8')

            # Check if branch exists
            branch_url = f"{self.base_url}/repos/{self.repo}/git/refs/heads/{branch}"
            branch_response = requests.get(branch_url, headers=self.headers)

            if branch_response.status_code == 404:
                # Create branch from main
                main_ref_url = f"{self.base_url}/repos/{self.repo}/git/refs/heads/main"
                main_response = requests.get(main_ref_url, headers=self.headers)
                main_response.raise_for_status()
                main_sha = main_response.json()["object"]["sha"]

                # Create new branch
                create_branch_data = {
                    "ref": f"refs/heads/{branch}",
                    "sha": main_sha
                }
                create_response = requests.post(
                    f"{self.base_url}/repos/{self.repo}/git/refs",
                    headers=self.headers,
                    json=create_branch_data
                )
                create_response.raise_for_status()
                print(f"✅ Created branch '{branch}'")

            # Get current file SHA if it exists
            file_url = f"{self.base_url}/repos/{self.repo}/contents/violations.json"
            file_params = {"ref": branch}
            file_response = requests.get(file_url, headers=self.headers, params=file_params)

            file_data = {
                "message": f"Update violations data - {datetime.utcnow().isoformat()}Z",
                "content": violations_base64,
                "branch": branch
            }

            if file_response.status_code == 200:
                # File exists, update it
                file_data["sha"] = file_response.json()["sha"]

            # Upload/update file
            upload_response = requests.put(file_url, headers=self.headers, json=file_data)
            upload_response.raise_for_status()

            unposted_count = len(violations_data.get('unposted_violations', []))
            total_count = len(violations_data.get('violations', []))
            print(f"✅ Violations data uploaded to branch '{branch}' ({unposted_count} unposted, {total_count} total)")
            return True

        except requests.exceptions.RequestException as e:
            print(f"❌ Failed to upload violations data: {e}")
            return False

    def trigger_workflow(self, event_type: str = "night-logger-sync") -> bool:
        """Trigger GitHub Actions workflow via repository dispatch"""
        try:
            url = f"{self.base_url}/repos/{self.repo}/dispatches"
            data = {
                "event_type": event_type,
                "client_payload": {
                    "triggered_at": datetime.utcnow().isoformat() + "Z",
                    "trigger_source": "night_logger_github"
                }
            }

            response = requests.post(url, headers=self.headers, json=data)
            response.raise_for_status()

            print(f"✅ Triggered GitHub Actions workflow: {event_type}")
            return True

        except requests.exceptions.RequestException as e:
            print(f"❌ Failed to trigger workflow: {e}")
            return False


# ----------------- main loop -----------------

def main():
    parser = argparse.ArgumentParser(description="Log 23:00–03:59 and trigger GitHub Actions sync.")
    parser.add_argument("--verbose", "-v", action="store_true", help="Print each sample as it is logged.")
    parser.add_argument("--interval", type=float, default=5.0, help="Sampling interval in seconds (default: 5).")
    parser.add_argument("--db", default=DB_PATH, help=f"SQLite DB path (default: {DB_PATH}).")

    # GitHub credentials (env only for security)
    parser.add_argument("--github-token", default=os.getenv("GITHUB_TOKEN"), help="GitHub token (or set GITHUB_TOKEN).")
    parser.add_argument("--github-repo", default=os.getenv("GITHUB_REPO"), help="GitHub repo owner/name (or set GITHUB_REPO).")

    args = parser.parse_args()

    conn = open_db(args.db)
    cursor = conn.cursor()

    try:
        if args.verbose:
            print("Starting night logger (GitHub mode)… Press Ctrl+C to stop.")

        while True:
            now = datetime.now()  # local device time
            value = 1 if is_between_23_and_359_local(now) else 0
            cursor.execute(INSERT_SQL, (value,))
            conn.commit()

            if args.verbose:
                print(f"[{now.strftime('%Y-%m-%d %H:%M:%S')}] logged is_night={value}", flush=True)

            if value == 1:
                # Treat 00:00-03:59 as part of previous day's night session
                if now.hour <= 3:
                    ymd = local_ymd(now - timedelta(days=1))
                else:
                    ymd = local_ymd(now)

                # Once-per-night guard
                if already_posted_today(conn, ymd):
                    if args.verbose:
                        print(f"Already posted for {ymd}; continuing to log without posting again.")
                    # Continue logging instead of exiting
                else:
                    # Must have GitHub credentials to trigger sync
                    if not (args.github_token and args.github_repo):
                        print(
                            "is_night=1 detected, but GitHub credentials are missing. "
                            "Set GITHUB_TOKEN and GITHUB_REPO environment variables.",
                            file=sys.stderr,
                        )
                        sys.exit(2)

                    # Generate violations.json and upload to GitHub
                    github_api = GitHubAPI(args.github_token, args.github_repo)

                    try:
                        # Ensure database is fully synced before extraction
                        conn.close()

                        # Mark as posted locally FIRST so extract_violations includes this date
                        temp_conn = open_db(args.db)
                        mark_posted_today(temp_conn, ymd)
                        temp_conn.close()

                        # Upload violations data to GitHub with deduplication
                        if args.verbose:
                            print(f"Generating and uploading violations data to GitHub...")

                        upload_success = github_api.upload_violations_to_branch(args.db, clean_duplicates=True)
                        if not upload_success:
                            print("Failed to upload violations data to GitHub", file=sys.stderr)
                            sys.exit(1)

                        # Trigger GitHub Actions workflow
                        if args.verbose:
                            print(f"Triggering GitHub Actions workflow...")

                        trigger_success = github_api.trigger_workflow()
                        if not trigger_success:
                            print("Failed to trigger GitHub Actions workflow", file=sys.stderr)
                            sys.exit(1)

                        # Reopen main connection to continue logging
                        conn = open_db(args.db)
                        cursor = conn.cursor()

                        if args.verbose:
                            print(f"Triggered GitHub sync for date={ymd}. Continuing to log...")

                        # Continue logging instead of exiting - let the timer stop the service

                    except Exception as e:
                        print(f"Failed to sync with GitHub: {e}", file=sys.stderr)
                        sys.exit(1)

            time.sleep(args.interval)

    except KeyboardInterrupt:
        if args.verbose:
            print("\nStopped by user.")
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


if __name__ == "__main__":
    main()