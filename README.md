# Night Logger for Beeminder

Automatically track and report late-night computer usage (23:00-03:59) to Beeminder with **tamper-resistant architecture**.

**Live Beeminder Goal**: https://www.beeminder.com/zarathustra/using-laptop-late

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
```

### Test Suite
```bash
# Run all tests (60 tests, all passing)
pytest -v

# Run with coverage report
pytest --cov=. --cov-report=html --cov-report=term-missing

# Run specific test files
pytest tests/test_sync_violations.py -v
pytest tests/test_night_logger_github.py -v
```

See [TESTING.md](docs/TESTING.md) for complete test documentation.

## What It Does

- **Monitors**: Computer usage between 23:00-03:59 local time
- **Logs**: Samples every 60 seconds to local SQLite database
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
- **Workflow**: `.github/workflows/sync-violations.yml` - Automated sync
- **Sync Script**: `sync_violations.py` - Handles violations.json → Beeminder sync with pagination
- **violations.json**: GitHub-hosted violations data

## Commands

```bash
nightlog status    # Show service status and recent data
nightlog logs      # Follow live service logs
nightlog start     # Start service manually
nightlog stop      # Stop service manually
nightlog enable    # Enable automatic timers
nightlog disable   # Disable automatic timers
```

## Repository Files

### Core System
- `sync_violations.py` - Beeminder sync script (used by GitHub Actions)
- `night_logger_github_fixed_v3.py` - Night logger source (for reference/development)
- `.github/workflows/sync-violations.yml` - GitHub Actions workflow
- `violations.json` - Current violations data

### Testing
- `tests/test_sync_violations.py` - Tests for sync script (27 tests)
- `tests/test_night_logger_github.py` - Tests for night logger (33 tests)
- `pytest.ini` - Test configuration
- `.coveragerc` - Coverage configuration
- `requirements-test.txt` - Test dependencies

### Documentation
- `README.md` - This file
- `docs/TESTING.md` - Comprehensive test documentation
- `docs/NIGHT_LOGGER_SYSTEM_DOCUMENTATION.md` - Technical reference
- `docs/SETUP_TAMPER_RESISTANT.md` - Deployment guide
- `.env.template` - Environment configuration template

## Setup Instructions

1. **Deploy System**: Follow `docs/SETUP_TAMPER_RESISTANT.md` for complete configuration
2. **Test Setup**: Run `pytest -v` to verify all components (60 tests)
3. **Monitor**: Use `nightlog status` to check ongoing operation

## Key Features

### Pagination Fix (October 2025)
- Fixed bug where sync script only fetched first page of Beeminder datapoints
- Now properly paginates through all datapoints
- Prevents duplicate datapoints from accumulating

### Service Timer Fix (October 2025)
- Fixed `Restart=always` causing service to restart after stop timer
- Changed to `Restart=on-failure` for proper timer control
- Service now correctly runs 22:55 PM - 04:05 AM window

### Test Suite (October 2025)
- Added comprehensive test coverage (60 tests)
- 100% of critical code paths tested
- All tests passing with no external dependencies

## Troubleshooting

```bash
# Check complete system status
nightlog status

# View recent logs
journalctl -u night-logger.service -n 50

# Run tests to verify functionality
pytest -v
```

For detailed documentation, see:
- [Technical Documentation](docs/NIGHT_LOGGER_SYSTEM_DOCUMENTATION.md)
- [Setup Guide](docs/SETUP_TAMPER_RESISTANT.md)
- [Test Documentation](docs/TESTING.md)

## Security & Configuration

- **GitHub Secrets**: Beeminder credentials stored securely in repository secrets
- **Local Environment**: GitHub API credentials in `/home/admin/.env` (600 permissions)
- **Database Access**: Read-only copy available at `/var/lib/night-logger/night_logs_ro.db`
