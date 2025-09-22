#!/usr/bin/env python3
"""
Violations-Only Sync Script
Processes violations.json instead of full database for efficient syncing
"""

import argparse
import json
import os
import requests
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List

class BeeminderAPI:
    """Handle Beeminder API operations for violations"""

    def __init__(self, username: str, auth_token: str):
        self.username = username
        self.auth_token = auth_token
        self.base_url = "https://www.beeminder.com/api/v1"

    def get_goal_datapoints(self, goal_slug: str) -> List[Dict]:
        """Get all datapoints for a goal"""
        url = f"{self.base_url}/users/{self.username}/goals/{goal_slug}/datapoints.json"
        params = {'auth_token': self.auth_token, 'sort': 'timestamp'}

        response = requests.get(url, params=params)
        response.raise_for_status()
        return response.json()

    def create_datapoint(self, goal_slug: str, violation: Dict) -> bool:
        """Create a datapoint for a violation"""
        url = f"{self.base_url}/users/{self.username}/goals/{goal_slug}/datapoints.json"

        # Convert ISO timestamp to Unix timestamp
        from datetime import datetime
        iso_timestamp = violation['timestamp']
        if iso_timestamp.endswith('Z'):
            iso_timestamp = iso_timestamp[:-1] + '+00:00'
        dt = datetime.fromisoformat(iso_timestamp)
        unix_timestamp = int(dt.timestamp())

        data = {
            'auth_token': self.auth_token,
            'timestamp': unix_timestamp,
            'value': float(violation['value']),
            'comment': violation['comment']
        }

        try:
            response = requests.post(url, data=data)
            response.raise_for_status()
            print(f"✅ Created datapoint for {violation['date']}")
            return True
        except requests.RequestException as e:
            print(f"❌ Failed to create datapoint for {violation['date']}: {e}")
            return False

    def delete_datapoint(self, goal_slug: str, datapoint_id: str) -> bool:
        """Delete a datapoint by ID"""
        url = f"{self.base_url}/users/{self.username}/goals/{goal_slug}/datapoints/{datapoint_id}.json"
        params = {'auth_token': self.auth_token}

        try:
            response = requests.delete(url, params=params)
            response.raise_for_status()
            return True
        except requests.RequestException:
            return False

class ViolationsSync:
    """Sync violations.json to Beeminder"""

    def __init__(self):
        self.beeminder_username = os.getenv('BEEMINDER_USERNAME')
        self.beeminder_token = os.getenv('BEEMINDER_AUTH_TOKEN')
        self.beeminder_goal = os.getenv('BEEMINDER_GOAL_SLUG')

        if not all([self.beeminder_username, self.beeminder_token, self.beeminder_goal]):
            raise ValueError("Missing required Beeminder environment variables")

        self.beeminder = BeeminderAPI(self.beeminder_username, self.beeminder_token)

    def load_violations(self, violations_file: str) -> Dict:
        """Load violations from JSON file"""
        violations_path = Path(violations_file)
        if not violations_path.exists():
            print(f"❌ Violations file not found: {violations_file}")
            return {"violations": [], "unposted_violations": []}

        with open(violations_path, 'r') as f:
            return json.load(f)

    def sync_violations_to_beeminder(self, violations_file: str) -> None:
        """Sync violations to Beeminder"""
        print("🔄 Syncing violations to Beeminder...")

        # Load violations data
        violations_data = self.load_violations(violations_file)
        unposted_violations = violations_data.get('unposted_violations', [])

        if not unposted_violations:
            print("ℹ️  No unposted violations to sync")
            return

        print(f"📊 Found {len(unposted_violations)} unposted violations")

        # Get existing Beeminder datapoints to avoid duplicates
        beeminder_datapoints = self.beeminder.get_goal_datapoints(self.beeminder_goal)

        # Extract dates from existing night_logger datapoints
        existing_dates = set()
        for dp in beeminder_datapoints:
            comment = (dp.get('comment') or '').lower()
            if 'night_logger' in comment or 'night logger' in comment:
                # Extract date from timestamp
                timestamp = dp.get('timestamp')
                if timestamp:
                    try:
                        dt = datetime.fromtimestamp(int(float(timestamp)))
                        date_str = dt.strftime('%Y-%m-%d')
                        existing_dates.add(date_str)
                    except (ValueError, TypeError):
                        pass

        # Sync only new violations
        new_violations = [v for v in unposted_violations if v['date'] not in existing_dates]

        if not new_violations:
            print("ℹ️  All violations already exist in Beeminder")
            return

        print(f"📝 Syncing {len(new_violations)} new violations to Beeminder")

        success_count = 0
        for violation in new_violations:
            if self.beeminder.create_datapoint(self.beeminder_goal, violation):
                success_count += 1

        print(f"✅ Successfully synced {success_count}/{len(new_violations)} violations")

def main():
    parser = argparse.ArgumentParser(description="Violations-Only Sync to Beeminder")
    parser.add_argument('--violations-file', default='violations.json',
                       help='Violations JSON file (default: violations.json)')

    args = parser.parse_args()

    try:
        sync = ViolationsSync()
        sync.sync_violations_to_beeminder(args.violations_file)
        print("✅ Violations sync completed successfully!")

    except Exception as e:
        print(f"❌ Sync failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()