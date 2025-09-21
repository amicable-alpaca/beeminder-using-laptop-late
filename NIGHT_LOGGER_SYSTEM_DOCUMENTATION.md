# Night Logger System Documentation

## Overview

The Night Logger system automatically tracks computer usage between 23:00-03:59 local time and reports to Beeminder using a **tamper-resistant architecture**. The system has evolved from a direct Beeminder integration to a three-tier approach for data integrity.

## Architecture

### Current System (Tamper-Resistant)
```
Local Computer (HSoT) → GitHub (SoT) → Beeminder (Display)
```

- **HSoT Database**: Highest Source of Truth - Local computer database
- **SoT Database**: Source of Truth hosted on GitHub with public audit trail
- **Beeminder**: Display/notification layer (automatically synchronized)

### Data Flow
1. **Local Detection**: Night usage triggers local logging
2. **GitHub Upload**: HSoT database uploaded to GitHub branch
3. **GitHub Actions**: Workflow synchronizes all databases
4. **Tamper Protection**: Manual Beeminder edits automatically overwritten

## Core Components

### 1. Local System (Deployed)

#### Main Application
- **File**: `/usr/local/bin/night_logger_github.py` (299 lines)
- **Purpose**: Tamper-resistant logging application
- **Features**:
  - Logs 1/0 values for night time detection (23:00-03:59)
  - Uploads database to GitHub on first night detection
  - Triggers GitHub Actions workflow
  - Exits after triggering to prevent duplicate submissions

#### Database Files
- **Location**: `/var/lib/night-logger/`
- **Main DB (HSoT)**: `night_logs.db` (root:nightlog-readers, 640 permissions)
- **Read-only Copy**: `night_logs_ro.db` (root:nightlog-readers, 640 permissions)
- **Current Data**: 4,806 log entries, 17 posted days (last: 2025-09-19)

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
- Faster restart (5s delay) on failure
- RuntimeMaxSec=5h20m backstop

**Timer Files**
- **Start Timer**: `/etc/systemd/system/night-logger-start.timer`
  - Triggers at 22:55:00 daily
- **Stop Timer**: `/etc/systemd/system/night-logger-stop.timer`
  - Triggers at 04:05:00 daily

### 2. GitHub Actions System

#### Workflow File
- **Location**: `.github/workflows/sync-nightlogger.yml`
- **Triggers**:
  - Repository dispatch (night-logger-sync) from local system
  - Daily schedule at 12 PM NYC time (17:00 UTC)
  - Manual workflow dispatch
- **Environment**: Beeminder credentials from GitHub secrets

#### Sync Program
- **File**: `sync_nightlogger.py` (380 lines)
- **Purpose**: Three-tier database synchronization
- **Features**:
  - Downloads HSoT database from GitHub branch
  - Syncs HSoT → SoT (HSoT is authoritative)
  - Syncs SoT → Beeminder (SoT is authoritative)
  - Handles Beeminder API pagination (300+ datapoints)
  - Commits updated SoT database to repository

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
- `sync_nightlogger.py` - GitHub Actions synchronization program
- `.github/workflows/sync-nightlogger.yml` - GitHub Actions workflow

### Testing & Validation
- `test_comprehensive.py` - Complete test suite (26 tests, 100% success rate)
  - Core functionality testing
  - GitHub/Beeminder API testing
  - System integration testing
  - Security and performance testing

### Documentation
- `README.md` - Quick start guide and project overview
- `SETUP_TAMPER_RESISTANT.md` - Complete deployment guide
- `NIGHT_LOGGER_SYSTEM_DOCUMENTATION.md` - This technical reference
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
2. **23:00-03:59**: Service logs 1/0 values every 5 seconds to HSoT database
3. **First "1" value**: Service uploads HSoT to GitHub, triggers workflow, exits
4. **GitHub Actions**: Downloads HSoT, syncs to SoT, syncs SoT to Beeminder
5. **04:05 Daily**: Timer stops any running service
6. **12:00 PM NYC**: Scheduled sync ensures data integrity

### Tamper Resistance
- **Manual Beeminder Edits**: Automatically overwritten by next sync
- **Data Integrity**: GitHub commit history provides immutable audit trail
- **Redundancy**: Three-tier backup (HSoT → SoT → Beeminder)
- **Transparency**: All changes visible in public GitHub repository

## System Status (Current)

### Active Configuration
- **Architecture**: Tamper-resistant system fully deployed
- **Service**: Running as "Night Logger (Beeminder) - Tamper Resistant"
- **Database**: 4,806 log entries across 17 posted days
- **Last Activity**: 2025-09-19
- **Schedule**: Active timers for 22:55 start, 04:05 stop

### Data Statistics
- **Total Logs**: 4,806 entries
- **Night Logs**: 23 entries (is_night=1)
- **Posted Days**: 17 days successfully posted
- **Database Size**: ~184KB
- **Permissions**: Admin users have read access via nightlog-readers group

## Usage Examples

### System Monitoring
```bash
# Check complete system status
nightlog status

# View live service logs
nightlog logs

# Test complete system
python3 test_comprehensive.py
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
python3 test_comprehensive.py
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
sync_nightlogger.py                      # Sync program
.github/workflows/sync-nightlogger.yml   # GitHub Actions
test_comprehensive.py                    # Test suite
```

This system provides robust automated tracking with comprehensive error handling, security hardening, tamper resistance, and administrative tools for maintenance and troubleshooting.