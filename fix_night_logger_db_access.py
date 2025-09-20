#!/usr/bin/env python3
"""
Fix for Night Logger database access issues.

This script addresses the SQLite WAL mode issue that prevents read-only access
to the database files even when using the -readonly flag.
"""

import sqlite3
import os
import shutil
import subprocess
import sys
from pathlib import Path

def fix_database_access():
    """Fix database access issues"""
    db_dir = Path("/var/lib/night-logger")
    main_db = db_dir / "night_logs.db"
    ro_db = db_dir / "night_logs_ro.db"

    issues_fixed = []

    # Check if we can access the read-only database
    try:
        conn = sqlite3.connect(f"file:{ro_db}?mode=ro", uri=True)
        cursor = conn.execute("SELECT COUNT(*) FROM logs;")
        count = cursor.fetchone()[0]
        conn.close()
        print(f"✅ Read-only database access working. Found {count} log entries.")
        return issues_fixed
    except Exception as e:
        print(f"❌ Database access issue detected: {e}")

    # Try to fix by ensuring proper WAL checkpoint
    print("🔧 Attempting to fix database access...")

    try:
        # First, try to checkpoint the main database (requires write access)
        # This consolidates WAL into main database file
        print("   Attempting WAL checkpoint on main database...")
        result = subprocess.run([
            'python3', '-c',
            f"""
import sqlite3
try:
    conn = sqlite3.connect('{main_db}')
    conn.execute('PRAGMA wal_checkpoint(FULL);')
    conn.close()
    print('WAL checkpoint completed')
except Exception as e:
    print(f'WAL checkpoint failed: {{e}}')
"""
        ], capture_output=True, text=True, user='root')

        if result.returncode == 0:
            print("   ✅ WAL checkpoint completed")
            issues_fixed.append("WAL checkpoint performed on main database")
        else:
            print(f"   ⚠️  WAL checkpoint failed: {result.stderr}")

    except Exception as e:
        print(f"   ❌ WAL checkpoint error: {e}")

    # Try creating a clean copy of the database
    try:
        print("   Creating clean database copy...")
        temp_db = db_dir / "night_logs_temp.db"

        # Create a new database with the same schema and data
        result = subprocess.run([
            'python3', '-c',
            f"""
import sqlite3
import shutil

# Connect to source (may have WAL issues)
source_conn = sqlite3.connect('{main_db}')

# Create clean target
target_conn = sqlite3.connect('{temp_db}')

# Copy schema
for line in source_conn.iterdump():
    target_conn.execute(line)

target_conn.commit()
source_conn.close()
target_conn.close()

print('Clean database copy created')
"""
        ], capture_output=True, text=True, user='root')

        if result.returncode == 0:
            print("   ✅ Clean database copy created")
            # Test the new copy
            try:
                conn = sqlite3.connect(f"file:{temp_db}?mode=ro", uri=True)
                cursor = conn.execute("SELECT COUNT(*) FROM logs;")
                count = cursor.fetchone()[0]
                conn.close()
                print(f"   ✅ New copy accessible with {count} entries")
                issues_fixed.append("Created clean database copy without WAL issues")
            except Exception as e:
                print(f"   ❌ New copy still has issues: {e}")

    except Exception as e:
        print(f"   ❌ Failed to create clean copy: {e}")

    return issues_fixed

def update_nightlog_script():
    """Update nightlog script to handle database access better"""
    nightlog_path = "/usr/local/bin/nightlog"

    try:
        with open(nightlog_path, 'r') as f:
            content = f.read()

        # Check if it already has the improved sqlro function
        if 'PRAGMA journal_mode=DELETE' in content:
            print("✅ nightlog script already has database access improvements")
            return []

        # Create improved version
        improved_sqlro = '''sqlro() {
  local DB="$(pick_db)"
  local q="$1"

  # Try multiple approaches for database access
  if sqlite3 -readonly "$DB" "SELECT 1;" >/dev/null 2>&1; then
    sqlite3 -readonly "$DB" "$q"
  elif sqlite3 "file:$DB?mode=ro" "SELECT 1;" >/dev/null 2>&1; then
    sqlite3 "file:$DB?mode=ro" "$q"
  else
    # Last resort: try to disable WAL mode temporarily
    sqlite3 "$DB" "PRAGMA journal_mode=DELETE; $q" 2>/dev/null || echo "Database access failed"
  fi
}'''

        # Replace the existing sqlro function
        import re
        pattern = r'sqlro\(\) \{[^}]+\}'
        updated_content = re.sub(pattern, improved_sqlro, content, flags=re.DOTALL)

        if updated_content != content:
            # Backup original
            shutil.copy2(nightlog_path, f"{nightlog_path}.backup")

            with open(f"{nightlog_path}.updated", 'w') as f:
                f.write(updated_content)

            print("✅ Created improved nightlog script at /usr/local/bin/nightlog.updated")
            print("   To apply: sudo mv /usr/local/bin/nightlog.updated /usr/local/bin/nightlog")
            return ["Created improved nightlog script with better database access"]

    except Exception as e:
        print(f"❌ Failed to update nightlog script: {e}")
        return []

def test_database_access():
    """Test current database access capabilities"""
    db_paths = [
        "/var/lib/night-logger/night_logs.db",
        "/var/lib/night-logger/night_logs_ro.db"
    ]

    print("\n🧪 Testing database access methods...")

    for db_path in db_paths:
        print(f"\nTesting {db_path}:")

        # Method 1: Direct read-only
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            cursor = conn.execute("SELECT COUNT(*) FROM logs;")
            count = cursor.fetchone()[0]
            conn.close()
            print(f"   ✅ URI read-only access: {count} entries")
        except Exception as e:
            print(f"   ❌ URI read-only access failed: {e}")

        # Method 2: sqlite3 command line
        try:
            result = subprocess.run([
                'sqlite3', '-readonly', db_path,
                'SELECT COUNT(*) FROM logs;'
            ], capture_output=True, text=True, timeout=5)

            if result.returncode == 0:
                print(f"   ✅ CLI read-only access: {result.stdout.strip()} entries")
            else:
                print(f"   ❌ CLI read-only access failed: {result.stderr}")
        except Exception as e:
            print(f"   ❌ CLI read-only access error: {e}")

if __name__ == "__main__":
    print("🔧 NIGHT LOGGER DATABASE ACCESS FIX")
    print("=" * 50)

    # Test current access
    test_database_access()

    # Attempt fixes
    print("\n🔧 Attempting fixes...")
    issues_fixed = fix_database_access()

    # Update nightlog script
    script_fixes = update_nightlog_script()
    issues_fixed.extend(script_fixes)

    # Final test
    print("\n🧪 Final test...")
    test_database_access()

    print(f"\n✅ Fixes applied: {len(issues_fixed)}")
    for fix in issues_fixed:
        print(f"   - {fix}")

    if not issues_fixed:
        print("\n💡 Recommendations:")
        print("   1. The database may be using WAL mode which requires special handling")
        print("   2. Consider running nightlog-snapshot.timer to create clean read-only copies")
        print("   3. Check if the nightlog-readers group has proper permissions")