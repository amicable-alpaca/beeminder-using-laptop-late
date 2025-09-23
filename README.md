# Night Logger for Beeminder

Automatically track and report late-night computer usage (23:00-03:59) to Beeminder with **tamper-resistant architecture**.

## 🔒 Tamper-Resistant Architecture

**Flow**: `Local Computer (HSoT) → violations.json → GitHub → Beeminder`

- **HSoT Database**: Highest Source of Truth on local computer (`/var/lib/night-logger/night_logs.db`)
- **violations.json**: Processed violation data uploaded to GitHub (public audit trail)
- **Beeminder**: Display/notification layer (gets selectively synced)

This prevents manual tampering since GitHub Actions automatically restores any deleted/modified Beeminder data.

## Quick Start

### Current System Status
```bash
# Check system status
nightlog status

# View live logs
nightlog logs

# Fix database issues (if needed)
sudo nightlog fix-db
```

### Test Suite
```bash
# Run comprehensive tests
python3 test_comprehensive.py
```

## What It Does

- **Monitors**: Computer usage between 23:00-03:59 local time
- **Logs**: Samples every 5 seconds (1 = night time, 0 = day time)
- **Syncs**: Local → violations.json → GitHub → Beeminder with selective updates
- **Protects**: Against manual data tampering via immutable GitHub audit trail

## System Components

### Local System (Deployed)
- **Main Script**: `/usr/local/bin/night_logger_github.py` - Tamper-resistant logging application
- **Database**: `/var/lib/night-logger/night_logs.db` - Local SQLite storage (HSoT)
- **Service**: `night-logger.service` - Systemd service (runs 22:55-04:05)
- **CLI Tool**: `nightlog` - Status and control commands
- **Environment**: `/home/admin/.env` - GitHub API credentials

### GitHub Actions (Repository)
- **Workflow**: `.github/workflows/sync-violations.yml` - Daily sync at 12 PM NYC
- **Sync Script**: `sync_violations.py` - Handles violations.json → Beeminder selective sync
- **violations.json**: GitHub-hosted violations data (1KB vs 50KB+ database)

## Commands

```bash
nightlog status    # Show service status and recent data
nightlog logs      # Follow live service logs
nightlog start     # Start service manually
nightlog stop      # Stop service manually
nightlog enable    # Enable automatic timers
nightlog disable   # Disable automatic timers
nightlog fix-db    # Fix database access issues
```

## Current Status

- **Database**: 20+ violations tracked across multiple posted days
- **Schedule**: Runs automatically at 22:55, stops at 04:05
- **Permissions**: Admin users can read database via `nightlog-readers` group
- **Architecture**: Tamper-resistant system fully deployed with dual branch uploads

## Repository Files

### Core Tamper-Resistant System
- `night_logger_github.py` - Night logger (generates violations.json and uploads to GitHub)
- `sync_violations.py` - GitHub Actions sync program with selective updates and Beeminder pagination
- `.github/workflows/sync-violations.yml` - GitHub Actions workflow
- `test_comprehensive.py` - Complete test suite (38 tests, 100% coverage)

### Documentation & Setup
- `SETUP_TAMPER_RESISTANT.md` - Complete deployment guide
- `NIGHT_LOGGER_SYSTEM_DOCUMENTATION.md` - Technical reference documentation
- `.env.template` - Environment configuration template

## Setup Instructions

1. **Deploy System**: Follow `SETUP_TAMPER_RESISTANT.md` for complete configuration
2. **Test Setup**: Run `python3 test_comprehensive.py` to verify all components
3. **Monitor**: Use `nightlog status` to check ongoing operation

## Troubleshooting

For detailed system information:
```bash
nightlog status
```

For any issues:
```bash
python3 test_comprehensive.py
```

## Security & Configuration

- **GitHub Secrets**: Beeminder credentials stored securely in repository secrets
- **Local Environment**: GitHub API credentials in `/home/admin/.env` (600 permissions)
- **Database Access**: `nightlog-readers` group for admin access