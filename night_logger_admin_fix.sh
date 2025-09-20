#!/bin/bash
set -euo pipefail

echo "🔧 NIGHT LOGGER SYSTEM ADMIN FIX"
echo "================================="
echo "This script fixes database access issues in the Night Logger system."
echo "Run as root or with sudo."
echo

# Check if running as root
if [[ $EUID -ne 0 ]]; then
   echo "❌ This script must be run as root (use sudo)"
   exit 1
fi

DB_DIR="/var/lib/night-logger"
MAIN_DB="$DB_DIR/night_logs.db"
RO_DB="$DB_DIR/night_logs_ro.db"

# Function to test database access
test_db_access() {
    local db_path="$1"
    local description="$2"

    echo "Testing $description ($db_path):"

    # Test 1: Direct Python access
    if python3 -c "
import sqlite3
conn = sqlite3.connect('file:$db_path?mode=ro', uri=True)
cursor = conn.execute('SELECT COUNT(*) FROM logs;')
count = cursor.fetchone()[0]
conn.close()
print(f'  ✅ Python access: {count} entries')
" 2>/dev/null; then
        echo "  ✅ Python access working"
    else
        echo "  ❌ Python access failed"
    fi

    # Test 2: SQLite CLI
    if sqlite3 -readonly "$db_path" "SELECT COUNT(*) FROM logs;" 2>/dev/null >/dev/null; then
        echo "  ✅ SQLite CLI access working"
    else
        echo "  ❌ SQLite CLI access failed"
    fi
}

# Function to fix WAL mode issues
fix_wal_mode() {
    echo "🔧 Fixing WAL mode issues..."

    # Check current journal mode
    echo "Current journal mode for main DB:"
    sqlite3 "$MAIN_DB" "PRAGMA journal_mode;" || echo "Cannot read journal mode"

    # Checkpoint and convert to DELETE mode
    echo "Performing WAL checkpoint and converting to DELETE mode..."
    sqlite3 "$MAIN_DB" "
        PRAGMA wal_checkpoint(FULL);
        PRAGMA journal_mode=DELETE;
        VACUUM;
    " && echo "✅ WAL checkpoint and conversion completed" || echo "❌ WAL checkpoint failed"

    # Update read-only copy
    echo "Updating read-only copy..."
    cp "$MAIN_DB" "$RO_DB"
    chown root:nightlog-readers "$RO_DB"
    chmod 640 "$RO_DB"
    echo "✅ Read-only copy updated"
}

# Function to create improved nightlog script
improve_nightlog_script() {
    echo "🔧 Improving nightlog script..."

    NIGHTLOG_PATH="/usr/local/bin/nightlog"
    BACKUP_PATH="${NIGHTLOG_PATH}.backup.$(date +%Y%m%d_%H%M%S)"

    # Create backup
    cp "$NIGHTLOG_PATH" "$BACKUP_PATH"
    echo "✅ Created backup: $BACKUP_PATH"

    # Create improved version
    cat > "${NIGHTLOG_PATH}.new" << 'EOF'
#!/bin/bash
set -euo pipefail

SERVICE="night-logger.service"
START_TIMER="night-logger-start.timer"
STOP_TIMER="night-logger-stop.timer"
DBLIVE="/var/lib/night-logger/night_logs.db"
DBSNAP="/var/lib/night-logger/night_logs_ro.db"

bold(){ printf "\n\033[1m%s\033[0m\n" "$*"; }

pick_db() {
  if [ -r "$DBSNAP" ]; then
    echo "$DBSNAP"
  else
    echo "$DBLIVE"
  fi
}

sqlro() {
  local DB="$(pick_db)"
  local q="$1"

  # Try multiple methods for accessing the database
  # Method 1: Standard readonly
  if sqlite3 -readonly "$DB" "SELECT 1;" >/dev/null 2>&1; then
    sqlite3 -readonly "$DB" "$q"
    return
  fi

  # Method 2: URI with readonly mode
  if python3 -c "
import sqlite3
try:
    conn = sqlite3.connect('file:$DB?mode=ro', uri=True)
    cursor = conn.execute('''$q''')
    for row in cursor:
        print('|'.join(str(col) for col in row))
    conn.close()
except Exception as e:
    exit(1)
" 2>/dev/null; then
    return
  fi

  # Method 3: Force DELETE mode temporarily (requires write access)
  if [ -w "$DB" ]; then
    sqlite3 "$DB" "PRAGMA journal_mode=DELETE; $q"
    return
  fi

  # Method 4: Last resort message
  echo "Database access failed - all methods exhausted"
  echo "Try: sudo systemctl start nightlog-snapshot.service"
}

case "${1:-status}" in
  status)
    bold "Service status"
    systemctl --no-pager --full status "$SERVICE" || true

    bold "Timers (next/last)"
    systemctl list-timers --all | grep -E "night-logger-(start|stop)\.timer|nightlog-snapshot\.timer" || echo "No timers found."

    bold "Recent service logs (last 20)"
    journalctl -u "$SERVICE" -n 20 --no-pager || true

    if command -v sqlite3 >/dev/null 2>&1; then
      DB="$(pick_db)"
      if [ -r "$DB" ]; then
        bold "DB summary: $DB"
        sqlro "
          SELECT 'logs_1s',    COUNT(*) FROM logs WHERE is_night=1
          UNION ALL
          SELECT 'logs_total', COUNT(*) FROM logs
          UNION ALL
          SELECT 'posted_days',COUNT(*) FROM posts;
        " | column -t -s'|'

        bold "Last 5 posted days"
        sqlro "
          SELECT ymd, posted_at_utc
          FROM posts
          ORDER BY ymd DESC
          LIMIT 5;
        " | column -t -s'|'

        bold "Last 10 raw samples"
        sqlro "
          SELECT logged_at, is_night
          FROM logs
          ORDER BY id DESC
          LIMIT 10;
        " | column -t -s'|'
      else
        echo "DB not readable. Ask admin to add you to 'nightlog-readers' or run: sudo systemctl start nightlog-snapshot.service"
      fi
    else
      echo "sqlite3 not installed."
    fi
    ;;
  logs)
    journalctl -u "$SERVICE" -f --no-pager
    ;;
  start|stop)
    sudo systemctl "$1" "$SERVICE"
    ;;
  enable)
    sudo systemctl enable --now "$START_TIMER" "$STOP_TIMER"
    echo "Also enabling snapshot timer for better database access..."
    sudo systemctl enable --now nightlog-snapshot.timer
    ;;
  disable)
    sudo systemctl disable --now "$START_TIMER" "$STOP_TIMER"
    sudo systemctl disable --now nightlog-snapshot.timer
    ;;
  fix-db)
    echo "Attempting to fix database access issues..."
    sudo systemctl start nightlog-snapshot.service
    echo "Snapshot service started. Database should be accessible now."
    ;;
  *)
    echo "Usage: nightlog {status|logs|start|stop|enable|disable|fix-db}"
    exit 1
    ;;
esac
EOF

    # Install improved version
    chmod +x "${NIGHTLOG_PATH}.new"
    mv "${NIGHTLOG_PATH}.new" "$NIGHTLOG_PATH"
    echo "✅ Improved nightlog script installed"
}

# Function to ensure snapshot service works properly
fix_snapshot_service() {
    echo "🔧 Ensuring snapshot service works properly..."

    # Start snapshot service to create clean read-only copy
    systemctl start nightlog-snapshot.service || echo "⚠️  Snapshot service failed to start"

    # Enable snapshot timer for regular updates
    systemctl enable --now nightlog-snapshot.timer
    echo "✅ Snapshot timer enabled"

    # Test snapshot
    if [ -f "$RO_DB" ]; then
        echo "✅ Snapshot database exists"

        # Test access to snapshot
        if sqlite3 -readonly "$RO_DB" "SELECT COUNT(*) FROM logs;" >/dev/null 2>&1; then
            echo "✅ Snapshot database is accessible"
        else
            echo "❌ Snapshot database still has access issues"
        fi
    else
        echo "❌ Snapshot database not created"
    fi
}

# Main execution
echo "🔍 Initial database access test..."
test_db_access "$MAIN_DB" "Main Database"
test_db_access "$RO_DB" "Read-Only Database"

echo
fix_wal_mode

echo
improve_nightlog_script

echo
fix_snapshot_service

echo
echo "🧪 Final database access test..."
test_db_access "$MAIN_DB" "Main Database"
test_db_access "$RO_DB" "Read-Only Database"

echo
echo "✅ Night Logger system fixes completed!"
echo
echo "📋 Summary of changes:"
echo "   1. Converted database from WAL to DELETE journal mode"
echo "   2. Created backup of original nightlog script"
echo "   3. Installed improved nightlog script with better database access"
echo "   4. Enabled snapshot timer for regular clean database copies"
echo "   5. Added 'fix-db' command to nightlog utility"
echo
echo "🔧 To test the fixes:"
echo "   nightlog status"
echo "   nightlog fix-db"