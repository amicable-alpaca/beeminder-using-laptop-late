#!/usr/bin/env python3
"""
Sync Night Logger Data - Tamper-Resistant Architecture

This program implements a three-tier synchronization system:
1. HSoT DB (Highest Source of Truth) - Local computer database
2. SoT DB (Source of Truth) - GitHub-hosted database
3. Beeminder API - Display/notification layer

Flow: HSoT DB -> SoT DB -> Beeminder API
Each higher tier overwrites lower tiers to maintain data integrity.
"""

import argparse
import json
import os
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
import requests
import base64


class BeeminderAPI:
    """Handle Beeminder API operations with pagination support"""

    def __init__(self, username: str, auth_token: str):
        self.username = username
        self.auth_token = auth_token
        self.base_url = "https://www.beeminder.com/api/v1"

    def get_goal_datapoints(self, goal_slug: str) -> List[Dict]:
        """Get all datapoints for a specific goal with pagination support"""
        all_datapoints = []
        page = 1
        per_page = 300  # Maximum allowed by Beeminder API

        while True:
            url = f"{self.base_url}/users/{self.username}/goals/{goal_slug}/datapoints.json"
            params = {
                'auth_token': self.auth_token,
                'page': page,
                'per_page': per_page,
                'sort': 'timestamp'  # Consistent ordering
            }

            try:
                response = requests.get(url, params=params, timeout=30)
                response.raise_for_status()
                page_data = response.json()

                if not page_data:  # No more data
                    break

                all_datapoints.extend(page_data)

                # If we got less than per_page, we're done
                if len(page_data) < per_page:
                    break

                page += 1
                print(f"Fetched page {page-1} for {goal_slug}: {len(page_data)} datapoints")

            except requests.exceptions.RequestException as e:
                print(f"Error fetching goal data for {goal_slug} (page {page}): {e}")
                break

        print(f"Total datapoints fetched for {goal_slug}: {len(all_datapoints)}")
        return all_datapoints

    def create_datapoint(self, goal_slug: str, value: float, timestamp: int,
                        comment: str = "", requestid: Optional[str] = None) -> bool:
        """Create a datapoint on Beeminder"""
        url = f"{self.base_url}/users/{self.username}/goals/{goal_slug}/datapoints.json"

        data = {
            'auth_token': self.auth_token,
            'value': value,
            'timestamp': timestamp,
            'comment': comment
        }

        if requestid:
            data['requestid'] = requestid

        try:
            response = requests.post(url, data=data, timeout=30)
            response.raise_for_status()
            return True
        except requests.exceptions.RequestException as e:
            print(f"Error creating datapoint: {e}")
            return False

    def delete_datapoint(self, goal_slug: str, datapoint_id: str) -> bool:
        """Delete a datapoint from Beeminder"""
        url = f"{self.base_url}/users/{self.username}/goals/{goal_slug}/datapoints/{datapoint_id}.json"

        params = {'auth_token': self.auth_token}

        try:
            response = requests.delete(url, params=params, timeout=30)
            response.raise_for_status()
            return True
        except requests.exceptions.RequestException as e:
            print(f"Error deleting datapoint {datapoint_id}: {e}")
            return False


class NightLoggerSync:
    """Main synchronization logic for Night Logger data"""

    def __init__(self):
        self.beeminder_username = os.getenv('BEEMINDER_USERNAME')
        self.beeminder_token = os.getenv('BEEMINDER_AUTH_TOKEN')
        self.beeminder_goal = os.getenv('BEEMINDER_GOAL_SLUG')
        self.github_token = os.getenv('GITHUB_TOKEN')

        if not all([self.beeminder_username, self.beeminder_token, self.beeminder_goal]):
            raise ValueError("Missing required Beeminder environment variables")

        self.beeminder = BeeminderAPI(self.beeminder_username, self.beeminder_token)
        self.sot_db_path = Path("sot_database.db")
        self.hsot_db_path = Path("hsot_database.db")  # Downloaded from computer

    def create_sot_database(self) -> None:
        """Create Source of Truth database if it doesn't exist"""
        if self.sot_db_path.exists():
            print("✅ SoT database already exists")
            return

        print("🔧 Creating new SoT database...")

        conn = sqlite3.connect(self.sot_db_path)
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                logged_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                is_night INTEGER NOT NULL CHECK(is_night IN (0,1))
            );

            CREATE TABLE IF NOT EXISTS posts (
                ymd TEXT PRIMARY KEY,          -- e.g., 2025-08-15 (LOCAL date)
                posted_at_utc TEXT NOT NULL    -- when we posted to Beeminder (UTC timestamp)
            );

            CREATE INDEX IF NOT EXISTS idx_logs_logged_at ON logs(logged_at);
            CREATE INDEX IF NOT EXISTS idx_posts_ymd ON posts(ymd);
        """)
        conn.commit()
        conn.close()

        print("✅ SoT database created successfully")

    def download_hsot_database(self) -> bool:
        """Download HSoT database from the computer (via GitHub branch)"""
        try:
            print("🔄 Downloading HSoT database from computer...")

            if not self.github_token:
                print("⚠️  No GitHub token - skipping HSoT download")
                return False

            # Download from hsot-database branch
            url = f"https://api.github.com/repos/{os.getenv('GITHUB_REPOSITORY', 'amicable-alpaca/beeminder-using-laptop-late')}/contents/hsot_database.db"
            headers = {
                "Authorization": f"token {self.github_token}",
                "Accept": "application/vnd.github.v3+json"
            }
            params = {"ref": "hsot-database"}

            response = requests.get(url, headers=headers, params=params, timeout=30)

            if response.status_code == 404:
                print("⚠️  HSoT database not found on GitHub - no sync needed")
                return False

            response.raise_for_status()
            file_data = response.json()

            # Decode base64 content
            import base64
            db_content = base64.b64decode(file_data['content'])

            # Write to local file
            with open(self.hsot_db_path, 'wb') as f:
                f.write(db_content)

            print(f"✅ HSoT database downloaded successfully ({len(db_content)} bytes)")
            return True

        except Exception as e:
            print(f"❌ Error downloading HSoT database: {e}")
            return False

    def get_posted_days_from_db(self, db_path: Path) -> Set[str]:
        """Get all posted days (ymd) from a database"""
        if not db_path.exists():
            return set()

        conn = sqlite3.connect(db_path)
        cursor = conn.execute("SELECT ymd FROM posts ORDER BY ymd")
        days = {row[0] for row in cursor.fetchall()}
        conn.close()

        return days

    def get_logs_from_db(self, db_path: Path) -> List[Tuple[str, int]]:
        """Get all log entries from a database"""
        if not db_path.exists():
            return []

        conn = sqlite3.connect(db_path)
        cursor = conn.execute("SELECT logged_at, is_night FROM logs ORDER BY logged_at")
        logs = cursor.fetchall()
        conn.close()

        return logs

    def sync_hsot_to_sot(self) -> None:
        """Sync HSoT database to SoT database (HSoT is authoritative)"""
        print("🔄 Syncing HSoT -> SoT databases...")

        if not self.hsot_db_path.exists():
            print("⚠️  No HSoT database found - skipping HSoT->SoT sync")
            return

        # Get data from both databases
        hsot_posts = self.get_posted_days_from_db(self.hsot_db_path)
        hsot_logs = self.get_logs_from_db(self.hsot_db_path)

        sot_posts = self.get_posted_days_from_db(self.sot_db_path)
        sot_logs = self.get_logs_from_db(self.sot_db_path)

        # Connect to SoT database for updates
        sot_conn = sqlite3.connect(self.sot_db_path)

        # Sync posts: HSoT is authoritative
        posts_to_add = hsot_posts - sot_posts
        posts_to_remove = sot_posts - hsot_posts

        if posts_to_add:
            print(f"📝 Adding {len(posts_to_add)} posts to SoT: {sorted(posts_to_add)}")
            # Get the posted_at_utc values from HSoT
            hsot_conn = sqlite3.connect(self.hsot_db_path)
            for ymd in posts_to_add:
                cursor = hsot_conn.execute("SELECT posted_at_utc FROM posts WHERE ymd = ?", (ymd,))
                row = cursor.fetchone()
                if row:
                    sot_conn.execute(
                        "INSERT OR REPLACE INTO posts (ymd, posted_at_utc) VALUES (?, ?)",
                        (ymd, row[0])
                    )
            hsot_conn.close()

        if posts_to_remove:
            print(f"🗑️  Removing {len(posts_to_remove)} posts from SoT: {sorted(posts_to_remove)}")
            for ymd in posts_to_remove:
                sot_conn.execute("DELETE FROM posts WHERE ymd = ?", (ymd,))

        # Sync logs: Replace all SoT logs with HSoT logs
        if hsot_logs != sot_logs:
            print(f"📝 Replacing SoT logs with {len(hsot_logs)} HSoT log entries")
            sot_conn.execute("DELETE FROM logs")
            sot_conn.executemany(
                "INSERT INTO logs (logged_at, is_night) VALUES (?, ?)",
                hsot_logs
            )

        sot_conn.commit()
        sot_conn.close()

        print("✅ HSoT -> SoT sync completed")

    def sync_sot_to_beeminder(self) -> None:
        """Sync SoT database to Beeminder (SoT is authoritative)"""
        print("🔄 Syncing SoT -> Beeminder...")

        # Get posted days from SoT database
        sot_posts = self.get_posted_days_from_db(self.sot_db_path)

        # Get all datapoints from Beeminder with pagination
        beeminder_datapoints = self.beeminder.get_goal_datapoints(self.beeminder_goal)

        # Filter for night_logger datapoints and extract dates
        beeminder_dates = set()
        beeminder_by_date = {}

        for dp in beeminder_datapoints:
            comment = (dp.get('comment') or '').lower()
            if 'night_logger' in comment or 'auto-logged' in comment:
                # Extract date from timestamp or comment
                timestamp = dp.get('timestamp')
                if timestamp:
                    try:
                        # Convert to local date - handle both int and string timestamps
                        ts = int(float(timestamp))
                        dt = datetime.fromtimestamp(ts)
                        ymd = dt.strftime('%Y-%m-%d')
                        beeminder_dates.add(ymd)
                        beeminder_by_date[ymd] = dp
                    except (ValueError, OSError) as e:
                        print(f"⚠️  Skipping invalid timestamp {timestamp}: {e}")
                        continue

        print(f"📊 SoT has {len(sot_posts)} posts, Beeminder has {len(beeminder_dates)} night_logger datapoints")

        # Calculate differences
        dates_to_add_to_beeminder = sot_posts - beeminder_dates
        dates_to_remove_from_beeminder = beeminder_dates - sot_posts

        # Add missing datapoints to Beeminder
        if dates_to_add_to_beeminder:
            print(f"📤 Adding {len(dates_to_add_to_beeminder)} datapoints to Beeminder: {sorted(dates_to_add_to_beeminder)}")

            for ymd in sorted(dates_to_add_to_beeminder):
                # Calculate timestamp for noon on that day (local time)
                try:
                    dt = datetime.strptime(ymd, '%Y-%m-%d').replace(hour=12, minute=0, second=0, microsecond=0)
                    timestamp = int(time.mktime(dt.timetuple()))
                except ValueError as e:
                    print(f"⚠️  Skipping invalid date {ymd}: {e}")
                    continue

                comment = f"Auto-logged by night_logger (restored from SoT) for {ymd}"
                requestid = f"night_logger_sot_{ymd}"

                success = self.beeminder.create_datapoint(
                    self.beeminder_goal,
                    value=1.0,
                    timestamp=timestamp,
                    comment=comment,
                    requestid=requestid
                )

                if success:
                    print(f"✅ Added datapoint for {ymd}")
                else:
                    print(f"❌ Failed to add datapoint for {ymd}")

        # Remove extra datapoints from Beeminder
        if dates_to_remove_from_beeminder:
            print(f"🗑️  Removing {len(dates_to_remove_from_beeminder)} datapoints from Beeminder: {sorted(dates_to_remove_from_beeminder)}")

            for ymd in sorted(dates_to_remove_from_beeminder):
                if ymd in beeminder_by_date:
                    dp_id = beeminder_by_date[ymd].get('id')
                    if dp_id:
                        success = self.beeminder.delete_datapoint(self.beeminder_goal, str(dp_id))
                        if success:
                            print(f"✅ Removed datapoint for {ymd}")
                        else:
                            print(f"❌ Failed to remove datapoint for {ymd}")

        print("✅ SoT -> Beeminder sync completed")

    def run_sync(self) -> None:
        """Run the complete synchronization process"""
        print("🚀 Starting Night Logger Sync Process")
        print("="*50)

        try:
            # Step 1: Create SoT database if needed
            self.create_sot_database()

            # Step 2: Download HSoT database from computer
            has_hsot = self.download_hsot_database()

            # Step 3: Sync HSoT -> SoT (if HSoT available)
            if has_hsot:
                self.sync_hsot_to_sot()

            # Step 4: Sync SoT -> Beeminder
            self.sync_sot_to_beeminder()

            print("✅ Sync process completed successfully!")

        except Exception as e:
            print(f"❌ Sync process failed: {e}")
            sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Night Logger Sync - Tamper-Resistant Data Synchronization")
    parser.add_argument('command', choices=['sync', 'download-hsot-db'],
                       help='Command to execute')

    args = parser.parse_args()

    if args.command == 'download-hsot-db':
        # For download, we only need GitHub credentials
        github_token = os.getenv('GITHUB_TOKEN')
        if not github_token:
            raise ValueError("Missing GITHUB_TOKEN environment variable")

        # Just do the download directly without full syncer initialization
        github_repo = os.getenv('GITHUB_REPOSITORY', 'amicable-alpaca/beeminder-using-laptop-late')

        import requests
        headers = {
            'Authorization': f'token {github_token}',
            'Accept': 'application/vnd.github.v3+json'
        }

        print("🔍 Checking for HSoT database in night-logger-upload branch...")

        try:
            # Try to download from the upload branch
            url = f'https://api.github.com/repos/{github_repo}/contents/night_logs.db?ref=night-logger-upload'
            response = requests.get(url, headers=headers)

            if response.status_code == 200:
                import base64
                content = response.json()['content']
                db_data = base64.b64decode(content)

                hsot_path = Path("hsot_database.db")
                with open(hsot_path, 'wb') as f:
                    f.write(db_data)

                print(f"✅ Downloaded HSoT database ({len(db_data)} bytes)")
            else:
                print(f"ℹ️  No HSoT database found in upload branch (HTTP {response.status_code})")

        except Exception as e:
            print(f"⚠️  Failed to download HSoT database: {e}")

    elif args.command == 'sync':
        syncer = NightLoggerSync()
        syncer.run_sync()


if __name__ == '__main__':
    main()