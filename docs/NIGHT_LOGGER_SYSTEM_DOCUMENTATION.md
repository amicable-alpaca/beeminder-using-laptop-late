# Night Logger System Documentation

## Overview

The Night Logger system automatically tracks computer usage between 23:00-03:59 local time and reports to Beeminder using a **tamper-resistant architecture**. The system has evolved from a direct Beeminder integration to a three-tier approach for data integrity.

## Architecture

### Current System (Tamper-Resistant)
```
Local Computer (HSoT) → violations.json → GitHub → Beeminder (Display)
```

- **HSoT Database**: Highest Source of Truth - Local computer database (`/var/lib/night-logger/night_logs.db`)
- **violations.json**: Processed violation data uploaded to GitHub (1KB vs 50KB+ database)
- **Beeminder**: Display/notification layer (selectively synchronized)

### Data Flow
1. **Local Detection**: Night usage triggers local logging
2. **violations.json Generation**: HSoT database processed into compact violations.json
3. **Dual Branch Upload**: violations.json uploaded to both main and violations-data branches
4. **GitHub Actions**: Workflow uses selective sync with Beeminder API pagination
5. **Tamper Protection**: Manual Beeminder edits selectively corrected

## Core Components

### 1. Local System (Deployed)

#### Main Application
- **File**: `/usr/local/bin/night_logger_github.py` (299 lines) - **FIXED VERSION**
- **Purpose**: Tamper-resistant logging application with continuous logging
- **Features**:
  - Logs 1/0 values for night time detection (23:00-03:59)
  - Uploads database to GitHub on first night detection
  - Triggers GitHub Actions workflow
  - **CONTINUES LOGGING** after upload (fixed premature exit bug)
  - One-violation-per-day protection via `already_posted_today` guard

#### Database Files
- **Location**: `/var/lib/night-logger/`
- **Main DB (HSoT)**: `night_logs.db` (root:nightlog-readers, 640 permissions)
- **Read-only Copy**: `night_logs_ro.db` (root:nightlog-readers, 640 permissions)
- **Current Data**: 20+ violations tracked across multiple posted days

#### Database Schema
```sql
-- Raw 0/1 samples every 5 seconds
CREATE TABLE logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    logged_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    is_night INTEGER NOT NULL CHECK(is_night IN (0,1))
);

-- Days that have been posted to GitHub/Beeminder
CREATE TABLE posts (
    ymd TEXT PRIMARY KEY,          -- e.g., 2025-08-15 (LOCAL date)
    posted_at_utc TEXT NOT NULL    -- when we posted to GitHub (UTC timestamp)
);
```

#### Systemd Configuration

**Service File**: `/etc/systemd/system/night-logger.service`
- **Type**: Simple service with security hardening
- **Command**: `python3 /usr/local/bin/night_logger_github.py --db /var/lib/night-logger/night_logs.db --interval 5`
- **Environment**: Loads from `/home/admin/.env`
- **Security Features**:
  - NoNewPrivileges, ProtectSystem=full, ProtectHome=yes
  - ReadWritePaths limited to `/var/lib/night-logger`
  - RuntimeMaxSec=5h20m (prevents running past dawn)
- **Status**: "Night Logger (Beeminder) - Tamper Resistant"

**Override Configuration**: `/etc/systemd/system/night-logger.service.d/override.conf`
```ini
[Unit]
After=network-online.target
Wants=network-online.target

[Service]
Restart=on-failure
RestartSec=30
```
- Only restarts on failures (not when stopped by timer)
- 30 second restart delay

**Timer Files**
- **Start Timer**: `/etc/systemd/system/night-logger-start.timer`
  - Triggers at 22:55:00 daily
- **Stop Timer**: `/etc/systemd/system/night-logger-stop.timer`
  - Triggers at 04:05:00 daily

### 2. GitHub Actions System

#### Workflow File
- **Location**: `.github/workflows/sync-violations.yml`
- **Triggers**:
  - Repository dispatch (night-logger-sync) from local system
  - Daily schedule at 12 PM NYC time (17:00 UTC)
  - Manual workflow dispatch
- **Environment**: Beeminder credentials from GitHub secrets

#### Sync Program
- **File**: `sync_violations.py`
- **Purpose**: Violations-only selective synchronization
- **Features**:
  - Downloads fresh violations.json from main branch
  - Uses selective sync: only adds/updates/deletes datapoints as needed
  - Handles Beeminder API pagination (300+ datapoints)
  - Prevents goal derailment by preserving existing valid data
  - No database uploads - works purely with violations.json

### 3. Configuration Files

#### Local Environment
- **File**: `/home/admin/.env`
- **Permissions**: 600 (admin read/write only)
- **Contains**: GitHub API credentials
  - GITHUB_TOKEN (Personal access token)
  - GITHUB_REPO (amicable-alpaca/beeminder-using-laptop-late)

#### GitHub Secrets
- **Location**: Repository Settings > Secrets and variables > Actions
- **Contains**: Beeminder API credentials
  - BEEMINDER_USERNAME
  - BEEMINDER_AUTH_TOKEN
  - BEEMINDER_GOAL_SLUG

### 4. Command Line Interface

#### CLI Tool: `/usr/local/bin/nightlog`
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

## Repository Files

### Core System
- `night_logger_github.py` - Tamper-resistant night logger application
- `sync_violations.py` - GitHub Actions synchronization program with selective updates
- `.github/workflows/sync-violations.yml` - GitHub Actions workflow

### Testing & Validation
- `tests/test_sync_violations.py` - Sync script tests (27 tests)
  - BeeminderAPI class: pagination, CRUD operations, error handling
  - ViolationsSync class: selective sync, duplicate cleanup, nuclear mode
  - CLI: argument parsing, environment variables, error cases
- `tests/test_night_logger_github.py` - Night logger tests (33 tests)
  - Time helpers: hour detection, date formatting
  - Database operations: table creation, posting logic
  - Beeminder duplicate cleaning
  - Violations extraction
  - GitHub API integration
  - Main function: keyboard interrupt, verbose mode, credentials
- `pytest.ini` - Test configuration
- `.coveragerc` - Coverage reporting configuration
- `requirements-test.txt` - Test dependencies

**Total: 60 tests, all passing**

### Documentation
- `README.md` - Quick start guide and project overview
- `docs/TESTING.md` - Comprehensive test documentation
- `docs/SETUP_TAMPER_RESISTANT.md` - Complete deployment guide
- `docs/NIGHT_LOGGER_SYSTEM_DOCUMENTATION.md` - This technical reference
- `docs/DOCUMENTATION_STATUS.md` - Documentation update tracking
- `.env.template` - Environment configuration template

## Security and Permissions

### User Groups
- **nightlog-readers**: Group for database read access
- **Members**: standard, admin users

### File Permissions
- **Database files**: 640 (root:nightlog-readers)
- **Service configs**: 644 (root:root)
- **Environment file**: 600 (admin only)
- **Scripts**: 755 (executable)

### Security Hardening
- Service runs with restricted permissions
- No new privileges allowed
- Protected system directories
- Limited write access to `/var/lib/night-logger` only
- GitHub secrets encrypted and workflow-only access
- Local environment file with restricted permissions

## Operation Flow

### Daily Cycle
1. **22:55 Daily**: Timer starts night-logger.service
2. **23:00-03:59**: Service logs 1/0 values every 60 seconds to HSoT database
3. **First "1" value**: Service generates violations.json from HSoT, uploads to GitHub, triggers workflow, **CONTINUES LOGGING**
4. **Subsequent "1" values**: Service continues logging without re-uploading (protected by `already_posted_today`)
5. **GitHub Actions**: Downloads violations.json, uses selective sync with Beeminder (proper pagination)
6. **04:05 Daily**: Timer stops service (stays stopped due to `Restart=on-failure`)
7. **12:00 PM NYC**: Scheduled sync ensures data integrity

### Tamper Resistance
- **Manual Beeminder Edits**: Selectively corrected by next sync
- **Data Integrity**: GitHub commit history provides immutable audit trail
- **Redundancy**: Multi-tier backup (HSoT → violations.json → Beeminder)
- **Transparency**: All changes visible in public GitHub repository
- **Race Condition Protection**: Dual branch uploads and database copy fallback

## System Status (Current - October 2025)

### Active Configuration
- **Architecture**: Tamper-resistant system fully deployed
- **Service**: Running as "Night Logger (Beeminder) - Tamper Resistant"
- **Database**: 29 posted days with 7,189 1-second resolution detections
- **Schedule**: Active timers for 22:55 start, 04:05 stop
- **Testing**: 60 tests, all passing
- **Recent Fixes**:
  - Pagination bug fixed (now fetches all Beeminder datapoints)
  - Service timer fix (Restart=on-failure prevents restart after stop timer)
  - Duplicate datapoints cleaned up

### Data Statistics
- **Posted Days**: 29 days successfully posted
- **Database**: SQLite with WAL mode, copy fallback for concurrent access
- **Permissions**: Admin users have read access via nightlog-readers group
- **Last Posted**: 2025-10-06

## Usage Examples

### System Monitoring
```bash
# Check complete system status
nightlog status

# View live service logs
nightlog logs

# Run all tests (60 tests, all passing)
pytest -v

# Run with coverage report
pytest --cov=. --cov-report=html --cov-report=term-missing

# Run specific test files
pytest tests/test_sync_violations.py -v
pytest tests/test_night_logger_github.py -v
```

### Manual Control
```bash
# Service control
sudo systemctl start night-logger.service
sudo systemctl stop night-logger.service

# Timer control
sudo systemctl enable --now night-logger-start.timer
sudo systemctl disable --now night-logger-start.timer
```

### Database Access
```bash
# Read database directly
sqlite3 /var/lib/night-logger/night_logs_ro.db "SELECT COUNT(*) FROM logs;"

# Check recent activity
sqlite3 /var/lib/night-logger/night_logs_ro.db "SELECT ymd, posted_at_utc FROM posts ORDER BY ymd DESC LIMIT 5;"
```

### GitHub Actions
```bash
# Trigger manual sync
# Go to: https://github.com/amicable-alpaca/beeminder-using-laptop-late/actions
# Click "Run workflow" on "Sync Night Logger Data"
```

## Troubleshooting

### Common Commands
```bash
# Check service status
systemctl status night-logger.service

# View recent logs
journalctl -u night-logger.service -n 20

# Test database access
nightlog status

# Run diagnostic tests
pytest -v
```

### File Locations Quick Reference
```
Local System:
/usr/local/bin/night_logger_github.py    # Main application
/usr/local/bin/nightlog                  # CLI tool
/var/lib/night-logger/night_logs.db      # HSoT database
/home/admin/.env                         # GitHub credentials
/etc/systemd/system/night-logger.service # Service config

Repository:
sync_violations.py                       # Sync program (selective, with pagination fix)
.github/workflows/sync-violations.yml    # GitHub Actions
tests/test_sync_violations.py            # Sync script tests (27 tests)
tests/test_night_logger_github.py        # Night logger tests (33 tests)
night_logger_github_fixed_v3.py          # Night logger source (for reference)
pytest.ini                               # Test configuration
.coveragerc                              # Coverage configuration
requirements-test.txt                    # Test dependencies
violations.json                          # Current violations data
```

This system provides robust automated tracking with comprehensive error handling, security hardening, tamper resistance, and administrative tools for maintenance and troubleshooting.