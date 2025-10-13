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
        """Get all datapoints for a specific goal with pagination support"""
        all_datapoints = []
        page = 1
        per_page = 300  # Request max, but API may return less

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
                print(f"📄 Fetched page {page} for {goal_slug}: {len(page_data)} datapoints")

                page += 1

            except requests.exceptions.RequestException as e:
                print(f"❌ Error fetching goal data for {goal_slug} (page {page}): {e}")
                break

        print(f"📊 Total datapoints fetched for {goal_slug}: {len(all_datapoints)}")
        return all_datapoints

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

    def selective_sync_datapoints(self, violations_data: Dict) -> None:
        """Selective sync: Only add/remove/update datapoints as needed (prevents derailment)"""
        print("🔄 Selective sync - comparing SoT with Beeminder datapoints...")

        # Get current Beeminder datapoints
        beeminder_datapoints = self.beeminder.get_goal_datapoints(self.beeminder_goal)

        # Convert violations to date-based mapping for comparison
        sot_violations = {v['date']: v for v in violations_data.get('violations', [])}

        # Convert Beeminder datapoints to date-based mapping
        from datetime import datetime
        beeminder_by_date = {}
        duplicates_to_delete = []

        for dp in beeminder_datapoints:
            date_str = datetime.fromtimestamp(dp['timestamp']).strftime('%Y-%m-%d')
            if date_str in beeminder_by_date:
                # Found duplicate - mark older one for deletion
                existing_dp = beeminder_by_date[date_str]
                if dp['timestamp'] > existing_dp['timestamp']:
                    # This datapoint is newer, delete the existing one
                    duplicates_to_delete.append(existing_dp)
                    beeminder_by_date[date_str] = dp
                else:
                    # Existing datapoint is newer, delete this one
                    duplicates_to_delete.append(dp)
            else:
                beeminder_by_date[date_str] = dp

        # Delete duplicate datapoints first
        if duplicates_to_delete:
            print(f"🧹 Found {len(duplicates_to_delete)} duplicate datapoints to clean up")
            for dp in duplicates_to_delete:
                dp_id = dp.get('id')
                if dp_id and self.beeminder.delete_datapoint(self.beeminder_goal, str(dp_id)):
                    date_str = datetime.fromtimestamp(dp['timestamp']).strftime('%Y-%m-%d')
                    print(f"🗑️  Deleted duplicate datapoint for {date_str}")

        # Refresh Beeminder datapoints after duplicate cleanup
        if duplicates_to_delete:
            beeminder_datapoints = self.beeminder.get_goal_datapoints(self.beeminder_goal)
            beeminder_by_date = {}
            for dp in beeminder_datapoints:
                date_str = datetime.fromtimestamp(dp['timestamp']).strftime('%Y-%m-%d')
                beeminder_by_date[date_str] = dp

        print(f"📊 Current state: {len(sot_violations)} SoT violations, {len(beeminder_by_date)} Beeminder datapoints")

        # Find differences
        sot_dates = set(sot_violations.keys())
        beeminder_dates = set(beeminder_by_date.keys())

        to_create = sot_dates - beeminder_dates  # In SoT but not in Beeminder
        to_delete = beeminder_dates - sot_dates  # In Beeminder but not in SoT
        to_check = sot_dates & beeminder_dates   # In both - check if they match

        # Check for datapoints that need updating
        to_update = set()
        for date in to_check:
            sot_violation = sot_violations[date]
            beeminder_dp = beeminder_by_date[date]

            # Convert SoT timestamp to Unix for comparison
            iso_timestamp = sot_violation['timestamp']
            if iso_timestamp.endswith('Z'):
                iso_timestamp = iso_timestamp[:-1] + '+00:00'
            dt = datetime.fromisoformat(iso_timestamp)
            sot_unix_timestamp = int(dt.timestamp())

            # Check if they differ (timestamp, value, or comment)
            if (abs(beeminder_dp['timestamp'] - sot_unix_timestamp) > 1 or  # Allow 1s tolerance
                beeminder_dp.get('value', 0) != sot_violation['value'] or
                beeminder_dp.get('comment', '') != sot_violation['comment']):
                to_update.add(date)

        print(f"📋 Changes needed: {len(to_create)} create, {len(to_delete)} delete, {len(to_update)} update")

        # Apply changes
        changes_made = 0

        # Delete extra datapoints
        for date in to_delete:
            dp = beeminder_by_date[date]
            dp_id = dp.get('id')
            if dp_id and self.beeminder.delete_datapoint(self.beeminder_goal, str(dp_id)):
                print(f"🗑️  Deleted unauthorized datapoint for {date}")
                changes_made += 1

        # Update changed datapoints (delete + recreate)
        for date in to_update:
            dp = beeminder_by_date[date]
            dp_id = dp.get('id')
            if dp_id and self.beeminder.delete_datapoint(self.beeminder_goal, str(dp_id)):
                if self.beeminder.create_datapoint(self.beeminder_goal, sot_violations[date]):
                    print(f"🔄 Updated datapoint for {date}")
                    changes_made += 1
                else:
                    print(f"❌ Failed to recreate updated datapoint for {date}")

        # Create missing datapoints
        for date in to_create:
            if self.beeminder.create_datapoint(self.beeminder_goal, sot_violations[date]):
                print(f"➕ Created new datapoint for {date}")
                changes_made += 1

        if changes_made == 0:
            print("✅ No changes needed - Beeminder is already in sync with SoT")
        else:
            print(f"✅ Applied {changes_made} changes to sync Beeminder with SoT")

    def sync_violations_to_beeminder(self, violations_file: str) -> None:
        """Sync violations to Beeminder using selective sync (prevents derailment)"""
        print("🔄 Syncing violations to Beeminder...")

        # Load violations data
        violations_data = self.load_violations(violations_file)

        if not violations_data.get('violations'):
            print("ℹ️  No violations in SoT database")
            return

        # Use selective sync instead of nuclear cleanup
        self.selective_sync_datapoints(violations_data)

    def nuclear_cleanup_and_sync(self, violations_file: str) -> None:
        """Nuclear option: Remove ALL datapoints and recreate from SoT (for emergencies)"""
        print("💥 NUCLEAR CLEANUP - removing ALL datapoints and recreating...")

        violations_data = self.load_violations(violations_file)

        # Step 1: Nuclear cleanup
        beeminder_datapoints = self.beeminder.get_goal_datapoints(self.beeminder_goal)
        if beeminder_datapoints:
            print(f"🗑️  Removing all {len(beeminder_datapoints)} existing datapoints")
            removed_count = 0
            for dp in beeminder_datapoints:
                dp_id = dp.get('id')
                if dp_id and self.beeminder.delete_datapoint(self.beeminder_goal, str(dp_id)):
                    removed_count += 1
            print(f"✅ Removed {removed_count}/{len(beeminder_datapoints)} datapoints")

        # Step 2: Recreate all
        all_violations = violations_data.get('violations', [])
        if all_violations:
            print(f"📊 Recreating {len(all_violations)} violations from SoT database")
            success_count = 0
            for violation in all_violations:
                if self.beeminder.create_datapoint(self.beeminder_goal, violation):
                    success_count += 1
            print(f"✅ Successfully recreated {success_count}/{len(all_violations)} violations")

def main():
    parser = argparse.ArgumentParser(description="Violations-Only Sync to Beeminder")
    parser.add_argument('--violations-file', default='violations.json',
                       help='Violations JSON file (default: violations.json)')
    parser.add_argument('--nuclear-cleanup', action='store_true',
                       help='Use nuclear cleanup: delete ALL datapoints and recreate (emergency use only)')

    args = parser.parse_args()

    try:
        sync = ViolationsSync()

        if args.nuclear_cleanup:
            sync.nuclear_cleanup_and_sync(args.violations_file)
        else:
            sync.sync_violations_to_beeminder(args.violations_file)

        print("✅ Violations sync completed successfully!")

    except Exception as e:
        print(f"❌ Sync failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()