# Night Logger System Documentation

## Overview

The Night Logger system automatically tracks computer usage between 23:00-03:59 local time and reports to Beeminder. It consists of a Python script, systemd services/timers, database files, and administrative utilities.

## Core Components

### 1. Main Application
- **File**: `/usr/local/bin/night_logger.py` (299 lines)
- **Purpose**: Core logging application that samples every 5 seconds during night hours
- **Features**:
  - Logs 1/0 values for night time detection (23:00-03:59)
  - Posts daily datapoints to Beeminder with reconciliation
  - Uses SQLite database for local persistence
  - Exits after posting to prevent duplicate submissions

### 2. Database Files
- **Location**: `/var/lib/night-logger/`
- **Main DB**: `night_logs.db` (184KB, root:nightlog-readers, 640 permissions)
- **Read-only Copy**: `night_logs_ro.db` (184KB, root:nightlog-readers, 640 permissions)
- **Current Data**: 4,806 log entries, 17 posted days

#### Database Schema
```sql
-- Raw 0/1 samples every 5 seconds
CREATE TABLE logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    logged_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    is_night INTEGER NOT NULL CHECK(is_night IN (0,1))
);

-- Days that have been posted to Beeminder
CREATE TABLE posts (
    ymd TEXT PRIMARY KEY,          -- e.g., 2025-08-15 (LOCAL date)
    posted_at_utc TEXT NOT NULL    -- when we posted to Beeminder (UTC timestamp)
);
```

### 3. Systemd Configuration

#### Service File: `/etc/systemd/system/night-logger.service`
- **Type**: Simple service with security hardening
- **Command**: `python3 /usr/local/bin/night_logger.py --db /var/lib/night-logger/night_logs.db --interval 5`
- **Environment**: Loads from `/etc/night-logger/beeminder.env`
- **Security Features**:
  - NoNewPrivileges, ProtectSystem=full, ProtectHome=yes
  - ReadWritePaths limited to `/var/lib/night-logger`
  - RuntimeMaxSec=5h20m (prevents running past dawn)
- **Auto-restart**: On failure with 60s delay

#### Override Configuration: `/etc/systemd/system/night-logger.service.d/override.conf`
- Clears bad time checks from main unit
- Sets faster restart (5s delay) on failure
- Confirms RuntimeMaxSec=5h20m backstop

#### Timer Files
- **Start Timer**: `/etc/systemd/system/night-logger-start.timer`
  - Triggers at 22:55:00 daily
  - Persistent=true for missed schedules
- **Stop Timer**: `/etc/systemd/system/night-logger-stop.timer`
  - Triggers at 04:05:00 daily
  - Stops service after night period

### 4. Configuration Files

#### Environment Configuration: `/etc/night-logger/beeminder.env`
- **Permissions**: 600 (root only read/write)
- **Contains**: Beeminder API credentials
  - BEEMINDER_USERNAME
  - BEEMINDER_AUTH_TOKEN
  - BEEMINDER_SLUG

### 5. Command Line Utility

#### File: `/usr/local/bin/nightlog`
- **Purpose**: Administrative interface for night logger system
- **Commands**:
  - `nightlog status` - Show service status, timers, logs, and database summary
  - `nightlog logs` - Follow live service logs
  - `nightlog start/stop` - Control service manually
  - `nightlog enable/disable` - Enable/disable timers
  - `nightlog fix-db` - Fix database access issues

#### Key Features
- Intelligent database access with multiple fallback methods
- Automatic read-only vs main database selection
- Formatted output with column alignment
- Shows recent log samples and posted days

## Administrative Scripts

### 1. System Fix Script: `night_logger_admin_fix.sh`
- **Purpose**: Comprehensive system repair and optimization
- **Functions**:
  - Converts database from WAL to DELETE journal mode
  - Creates clean read-only database copies
  - Improves nightlog CLI script with better database access
  - Enables snapshot services for regular clean copies
  - Tests database access before/after fixes

### 2. Database Access Fix: `fix_night_logger_db_access.py`
- **Purpose**: Python-based database access troubleshooting
- **Functions**:
  - WAL checkpoint operations
  - Clean database copy creation
  - Nightlog script improvements
  - Multi-method access testing

### 3. Test Suite: `test_night_logger.py`
- **Purpose**: Comprehensive system validation
- **Test Categories**:
  - Core night_logger.py functionality
  - System configuration validation
  - Database access and permissions
  - CLI utility operation
  - System status verification
- **Diagnostic Checks**: Database access, group membership, service logs

## Security and Permissions

### User Groups
- **nightlog-readers**: Group for database read access
- **Members**: standard, admin users

### File Permissions
- **Database files**: 640 (root:nightlog-readers)
- **Service configs**: 644 (root:root)
- **Environment file**: 600 (root only)
- **Scripts**: 755 (executable)

### Security Hardening
- Service runs with restricted permissions
- No new privileges allowed
- Protected system directories
- Limited write access to `/var/lib/night-logger` only

## Operation Flow

1. **22:55 Daily**: Timer starts night-logger.service
2. **23:00-03:59**: Service logs 1/0 values every 5 seconds
3. **First "1" value**: Service posts to Beeminder and exits
4. **04:05 Daily**: Timer stops any running service
5. **Reconciliation**: On first run of day, checks Beeminder for missing data and re-posts if needed

## Recent Fixes Applied

### Database Access Issues (September 2025)
- **Problem**: SQLite WAL mode prevented read-only access
- **Solution**: Converted to DELETE journal mode, created clean read-only copies
- **Result**: Admin users can now access database without sudo

### Permission Structure
- **Problem**: Database files not accessible to admin users
- **Solution**: Added nightlog-readers group, updated file permissions
- **Result**: Proper group-based access control

## File Locations Summary

```
/usr/local/bin/
├── night_logger.py              # Main application (299 lines)
└── nightlog                     # CLI utility

/etc/systemd/system/
├── night-logger.service         # Main service definition
├── night-logger-start.timer     # 22:55 start timer
├── night-logger-stop.timer      # 04:05 stop timer
├── night-logger-stop.service    # Stop service
└── night-logger.service.d/
    └── override.conf            # Service overrides

/etc/night-logger/
└── beeminder.env               # API credentials (600 perms)

/var/lib/night-logger/
├── night_logs.db               # Main database (184KB)
├── night_logs_ro.db           # Read-only copy (184KB)
├── night_logs_ro.db-shm       # SQLite shared memory
└── night_logs_ro.db-wal       # SQLite write-ahead log

~/repos/beeminder-using-laptop-late/
├── night_logger_admin_fix.sh   # System repair script
├── fix_night_logger_db_access.py # Python DB fix utility
├── test_night_logger.py        # Comprehensive test suite
└── NIGHT_LOGGER_ANALYSIS.md    # Previous analysis doc
```

## Usage Examples

```bash
# Check system status
nightlog status

# View live logs
nightlog logs

# Fix database access issues
sudo nightlog fix-db

# Manual service control
sudo systemctl start night-logger.service
sudo systemctl stop night-logger.service

# Test database access
sqlite3 /var/lib/night-logger/night_logs_ro.db "SELECT COUNT(*) FROM logs;"

# Run comprehensive tests
python3 test_night_logger.py
```

This system provides robust automated tracking with comprehensive error handling, security hardening, and administrative tools for maintenance and troubleshooting.