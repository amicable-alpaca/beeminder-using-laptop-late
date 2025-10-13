# Setup Guide: Tamper-Resistant Night Logger

This guide explains how to set up the tamper-resistant version of the Night Logger system.

## Architecture Overview

```
Local Computer (HSoT) -> violations.json -> GitHub -> Beeminder (Display)
```

- **HSoT DB**: Highest Source of Truth - Local computer database (`/var/lib/night-logger/night_logs.db`)
- **violations.json**: Processed violation data uploaded to GitHub (1KB vs 50KB+ database)
- **Beeminder**: Display/notification layer (gets selectively synced)

## Setup Steps

### 1. GitHub Repository Setup

1. **Create GitHub Personal Access Token**:
   - Go to GitHub Settings > Developer settings > Personal access tokens
   - Create a classic token with these scopes:
     - `repo` (full repository access)
     - `workflow` (update GitHub Actions workflows)
   - Save the token securely

2. **Configure GitHub Secrets**:
   - Go to your repository Settings > Secrets and variables > Actions
   - Add these repository secrets:
     ```
     BEEMINDER_USERNAME=your_beeminder_username
     BEEMINDER_AUTH_TOKEN=your_beeminder_auth_token
     BEEMINDER_GOAL_SLUG=your_goal_slug
     ```

### 2. Local Computer Setup (COMPLETED)

**Note**: This system has been fully deployed. The steps below are for reference.

1. **Environment Configuration** (✅ Completed):
   - Environment file created at `/home/admin/.env` with GitHub credentials
   - Permissions set to 600 for security

2. **Systemd Service Updated** (✅ Completed):
   - Tamper-resistant night logger deployed to `/usr/local/bin/night_logger_github.py`
   - Service configuration updated to use new script and environment file
   - Service restarted and verified working

3. **Current Configuration**:
   ```ini
   [Service]
   Type=simple
   ExecStart=/usr/bin/python3 /usr/local/bin/night_logger_github.py --db /var/lib/night-logger/night_logs.db --interval 5
   EnvironmentFile=/home/admin/.env
   # ... security hardening enabled
   ```

4. **System Status** (✅ Active):
   - Service running as "Night Logger (Beeminder) - Tamper Resistant"
   - Database: 20+ violations tracked across multiple posted days
   - Architecture: Dual branch uploads (main + violations-data)

### 3. Testing & Verification

1. **Run All Tests**:
   ```bash
   pytest -v
   ```
   Expected: 60 tests, all passing

2. **Run Tests with Coverage**:
   ```bash
   pytest --cov=. --cov-report=html --cov-report=term-missing
   ```
   Expected: Coverage report generated in `htmlcov/`

3. **Check Local System Status**:
   ```bash
   nightlog status
   ```
   Expected: Service running, database accessible, recent logs visible

4. **Test GitHub Actions Workflow**:
   - Go to Actions tab in your GitHub repository: https://github.com/amicable-alpaca/beeminder-using-laptop-late/actions
   - Look for "Sync Night Logger Data" workflow
   - Manually trigger with "Run workflow" to test

4. **Verify Tamper Resistance**:
   - Manually delete a Beeminder datapoint
   - Wait for next scheduled sync (12 PM NYC) or trigger manually
   - Datapoint should be automatically restored

## How It Works

### Daily Operation

1. **Night Usage Detected** (23:00-03:59):
   - Local computer logs usage to HSoT database every 60 seconds
   - On first detection, generates violations.json from HSoT
   - Uploads violations.json to GitHub
   - Triggers GitHub Actions workflow
   - **Continues logging** (service runs until 04:05 AM timer)

2. **GitHub Actions Workflow**:
   - Downloads violations.json
   - Uses selective sync with proper pagination (fixed October 2025)
   - Only adds/updates/deletes datapoints as needed
   - Preserves existing Beeminder data (prevents goal derailment)

3. **Scheduled Sync** (12 PM NYC time):
   - Daily verification sync runs automatically
   - Ensures Beeminder stays in sync with violations.json
   - Handles any missed violations or corrections

4. **Service Stop** (04:05 AM):
   - Stop timer terminates service
   - Service stays stopped (Restart=on-failure, fixed October 2025)
   - Will restart automatically at 22:55 PM

### Tamper Resistance

- **Manual Beeminder Edits**: Selectively corrected by GitHub Actions
- **Data Integrity**: GitHub commit history provides audit trail
- **Redundancy**: Multiple backup points (local HSoT, GitHub violations.json, Beeminder)
- **Transparency**: All changes visible in public GitHub repository
- **Pagination**: Properly fetches all Beeminder datapoints (fixed October 2025)

## Troubleshooting

### Common Issues

1. **GitHub API Errors**:
   - Check GITHUB_TOKEN has correct permissions
   - Verify GITHUB_REPO format: `username/repository`

2. **Beeminder API Errors**:
   - Verify GitHub secrets are set correctly
   - Check Beeminder goal exists and is accessible

3. **Workflow Not Triggering**:
   - Check repository_dispatch trigger is configured
   - Verify workflow file is in `.github/workflows/`

4. **Violations Sync Issues**:
   - Check GitHub Actions logs for detailed error messages
   - Verify violations.json upload succeeded to both branches

### Viewing Logs

- **Local Logs**: `journalctl -u night-logger.service -f`
- **GitHub Actions Logs**: Repository > Actions > Workflow run
- **Beeminder API**: Check workflow logs for API responses

## Security Notes

- Never commit `.env` file to repository
- GitHub secrets are encrypted and only accessible to workflows
- Local environment file should have restricted permissions:
  ```bash
  chmod 600 .env
  ```

## Files Overview

### Core System
- `sync_violations.py`: GitHub Actions sync program with selective updates and Beeminder pagination (fixed)
- `night_logger_github_fixed_v3.py`: Night logger source code (for reference/development)
- `.github/workflows/sync-violations.yml`: GitHub Actions workflow
- `violations.json`: Current violations data

### Testing
- `tests/test_sync_violations.py`: Sync script tests (27 tests)
- `tests/test_night_logger_github.py`: Night logger tests (33 tests)
- `pytest.ini`: Test configuration
- `.coveragerc`: Coverage configuration
- `requirements-test.txt`: Test dependencies

### Documentation
- `README.md`: Quick start guide
- `docs/TESTING.md`: Test documentation
- `docs/SETUP_TAMPER_RESISTANT.md`: This setup guide
- `docs/NIGHT_LOGGER_SYSTEM_DOCUMENTATION.md`: Technical reference
- `.env.template`: Environment template for local setup