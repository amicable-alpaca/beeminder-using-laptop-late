#!/usr/bin/env python3
"""
night_logger_github.py - Tamper-Resistant Version

What it does
------------
- Every 5 seconds, logs whether the local time is between 23:00–03:59.
- On the first 1 of the (local) day, it:
  1) Uploads the local database to GitHub
  2) Triggers GitHub Actions workflow for sync with Beeminder
  3) Exits cleanly (so systemd won't restart it with Restart=on-failure).

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


def extract_violations(db_path: str) -> Dict:
    """Extract all violations from the database"""
    from pathlib import Path
    import tempfile
    import shutil
    from datetime import datetime

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

        # Verify the copy has the required tables
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='logs';")
        if not cursor.fetchone():
            raise Exception("Copied database missing required tables")

        # Clean up temp file after we're done
        temp_cleanup = temp_path
    except Exception as e:
        # Fallback to direct access if copy fails
        conn = sqlite3.connect(db_path, timeout=30.0)
        cursor = conn.cursor()
        temp_cleanup = None

    # Get all violations with their timestamps
    # Apply night logger logic in SQL: 00:00-03:59 violations belong to previous day
    cursor.execute("""
        SELECT
            CASE
                WHEN CAST(strftime('%H', logged_at) AS INTEGER) <= 3
                THEN DATE(logged_at, '-1 day')
                ELSE DATE(logged_at)
            END as violation_date,
            MIN(logged_at) as first_violation_timestamp,
            COUNT(*) as violation_count
        FROM logs
        WHERE is_night = 1
        GROUP BY
            CASE
                WHEN CAST(strftime('%H', logged_at) AS INTEGER) <= 3
                THEN DATE(logged_at, '-1 day')
                ELSE DATE(logged_at)
            END
        ORDER BY violation_date DESC
    """)

    violations = []
    for violation_date, first_violation_timestamp, count in cursor.fetchall():
        violations.append({
            "date": violation_date,
            "timestamp": first_violation_timestamp,
            "value": 1,  # Beeminder value for violation
            "comment": f"Night logger violation ({count} detections)",
            "daystamp": violation_date.replace("-", "")  # Beeminder format: YYYYMMDD
        })

    # Check which dates have already been posted to avoid duplicates
    try:
        cursor.execute("SELECT ymd FROM posts ORDER BY ymd")
        posted_dates = {row[0] for row in cursor.fetchall()}
    except sqlite3.OperationalError:
        # If posts table doesn't exist or is inaccessible, assume no posted dates
        posted_dates = set()

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
        "posted_dates": list(posted_dates),
        "last_updated": datetime.utcnow().isoformat() + "Z",
        "total_violations": len(violations),
        "unposted_violations": [v for v in violations if v["date"] not in posted_dates]
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

    def upload_violations_to_branch(self, db_path: str, branch: str = "violations-data") -> bool:
        """Generate violations.json from database and upload to a specific branch"""
        try:
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
                        print(f"Already posted for {ymd}; exiting without posting again.")
                    sys.exit(0)

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

                    # Upload violations data to GitHub
                    if args.verbose:
                        print(f"Generating and uploading violations data to GitHub...")

                    upload_success = github_api.upload_violations_to_branch(args.db)
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

                    # Mark as posted locally - reopen connection
                    temp_conn = open_db(args.db)
                    mark_posted_today(temp_conn, ymd)
                    temp_conn.close()

                    if args.verbose:
                        print(f"Triggered GitHub sync for date={ymd}. Exiting.")

                    sys.exit(0)

                except Exception as e:
                    print(f"Failed to sync with GitHub: {e}", file=sys.stderr)
                    sys.exit(1)

            time.sleep(args.interval)

    except KeyboardInterrupt:
        if args.verbose:
            print("\nStopping. Goodbye!")
    finally:
        try:
            cursor.close()
        finally:
            conn.close()


if __name__ == "__main__":
    main()