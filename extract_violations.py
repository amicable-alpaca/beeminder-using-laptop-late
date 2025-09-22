#!/usr/bin/env python3
"""
Extract violations from HSoT database and create violations.json for upload
"""

import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Dict

def extract_violations(db_path: str) -> Dict:
    """Extract all violations from the database"""

    if not Path(db_path).exists():
        print(f"Database not found: {db_path}")
        return {"violations": [], "last_updated": datetime.utcnow().isoformat() + "Z"}

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    cursor = conn.cursor()

    # Get all violations with their timestamps
    cursor.execute("""
        SELECT
            DATE(logged_at) as date,
            logged_at,
            COUNT(*) as violation_count
        FROM logs
        WHERE is_night = 1
        GROUP BY DATE(logged_at)
        ORDER BY date DESC
    """)

    violations = []
    for date, first_violation_timestamp, count in cursor.fetchall():
        violations.append({
            "date": date,
            "timestamp": first_violation_timestamp,
            "value": 1,  # Beeminder value for violation
            "comment": f"Night logger violation ({count} detections)",
            "daystamp": date.replace("-", "")  # Beeminder format: YYYYMMDD
        })

    # Check which dates have already been posted to avoid duplicates
    try:
        cursor.execute("SELECT ymd FROM posts ORDER BY ymd")
        posted_dates = {row[0] for row in cursor.fetchall()}
    except sqlite3.OperationalError:
        # If posts table doesn't exist or is inaccessible, assume no posted dates
        posted_dates = set()

    conn.close()

    result = {
        "violations": violations,
        "posted_dates": list(posted_dates),
        "last_updated": datetime.utcnow().isoformat() + "Z",
        "total_violations": len(violations),
        "unposted_violations": [v for v in violations if v["date"] not in posted_dates]
    }

    return result

def main():
    # Use read-only database for safety
    db_path = "/var/lib/night-logger/night_logs_ro.db"

    if len(sys.argv) > 1:
        db_path = sys.argv[1]

    violations_data = extract_violations(db_path)

    # Write to violations.json
    output_file = "violations.json"
    with open(output_file, 'w') as f:
        json.dump(violations_data, f, indent=2)

    print(f"Extracted {violations_data['total_violations']} violations to {output_file}")
    print(f"Unposted violations: {len(violations_data['unposted_violations'])}")

    # Show recent unposted violations
    for violation in violations_data['unposted_violations'][-5:]:
        print(f"  {violation['date']}: {violation['comment']}")

if __name__ == "__main__":
    main()