# Night Logger for Beeminder

Automatically track and report late-night computer usage (23:00-03:59) to Beeminder.

## Quick Start

```bash
# Check system status
nightlog status

# View live logs
nightlog logs

# Fix database issues (if needed)
sudo nightlog fix-db
```

## What It Does

- **Monitors**: Computer usage between 23:00-03:59 local time
- **Logs**: Samples every 5 seconds (1 = night time, 0 = day time)
- **Reports**: Posts daily datapoints to Beeminder automatically
- **Reconciles**: Checks for and repairs missing Beeminder data

## System Components

- **Main Script**: `/usr/local/bin/night_logger.py` - Core logging application
- **Database**: `/var/lib/night-logger/night_logs.db` - Local SQLite storage
- **Service**: `night-logger.service` - Systemd service (runs 22:55-04:05)
- **CLI Tool**: `nightlog` - Status and control commands

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

- **Database**: 4,806 log entries across 17 posted days
- **Schedule**: Runs automatically at 22:55, stops at 04:05
- **Permissions**: Admin users can read database via `nightlog-readers` group

## Files

- `NIGHT_LOGGER_SYSTEM_DOCUMENTATION.md` - Complete technical documentation
- `night_logger_admin_fix.sh` - System repair script
- `fix_night_logger_db_access.py` - Database troubleshooting utility
- `test_night_logger.py` - Comprehensive test suite

## Troubleshooting

If you see database access errors:
```bash
sudo ./night_logger_admin_fix.sh
```

For detailed system information:
```bash
nightlog status
```

## Configuration

Beeminder credentials are stored in `/etc/night-logger/beeminder.env` (root access only).