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

1. **Test Complete System (Including Exit Logic Fix)**:
   ```bash
   python3 test_complete_with_fix.py
   ```
   Expected: 56 tests, 100% success rate

2. **Test Comprehensive System Only**:
   ```bash
   python3 test_comprehensive.py
   ```
   Expected: 50 tests, 100% success rate

3. **Test Exit Logic Fix Only**:
   ```bash
   python3 test_exit_logic_fix.py
   ```
   Expected: 6 tests, 100% success rate

2. **Check Local System Status**:
   ```bash
   nightlog status
   ```
   Expected: Service running, database accessible, recent logs visible

3. **Test GitHub Actions Workflow**:
   - Go to Actions tab in your GitHub repository: https://github.com/amicable-alpaca/beeminder-using-laptop-late/actions
   - Look for "Sync Night Logger Data" workflow
   - Manually trigger with "Run workflow" to test

4. **Verify Tamper Resistance**:
   - Manually delete a Beeminder datapoint
   - Wait for next scheduled sync (12 PM NYC) or trigger manually
   - Datapoint should be automatically restored

## Exit Logic Fix (September 2025)

### Problem Identified
The original night logger had a critical bug where it would exit immediately after uploading existing violations, missing subsequent night usage on the same night.

**Original Broken Flow**:
1. 22:55 - Service starts
2. 23:00:01 - Detects first night usage, uploads violations, **exits immediately**
3. 23:00:05+ - User continues using computer but service has exited (missed data!)

### Fix Implemented
**Fixed Flow**:
1. 22:55 - Service starts
2. 23:00:01 - Detects first night usage, uploads violations, **continues logging**
3. 23:00:05+ - Service continues logging all night usage
4. 04:05 - Service stopped by timer (natural termination)

### Deployment Instructions

1. **Deploy the Fix**:
   ```bash
   # Run the deployment script
   ./deploy_fix.sh
   ```

   The script will:
   - Stop the current service
   - Backup the original file
   - Install the fixed version
   - Restart the service

2. **Verify Fix Deployment**:
   ```bash
   # Check that fixed version is running
   nightlog status

   # Run comprehensive tests including exit logic fix
   python3 test_complete_with_fix.py
   ```

3. **Monitor Next Night Session**:
   - Wait for next night usage (23:00-03:59)
   - Check logs: `nightlog logs`
   - Verify multiple log entries are captured instead of just one
   - Confirm violation is properly uploaded to Beeminder

### Technical Changes Made
- Removed premature `sys.exit(0)` after successful upload
- Added proper database connection reopening after GitHub operations
- Enhanced `already_posted_today` guard to prevent duplicate uploads
- Maintained one-violation-per-day guarantee
- Added 6 comprehensive tests to verify fix behavior

## How It Works

### Daily Operation

1. **Night Usage Detected** (23:00-03:59):
   - Local computer logs usage to HSoT database
   - On first detection, generates violations.json from HSoT
   - Uploads violations.json to both main and violations-data branches
   - Triggers GitHub Actions workflow

2. **GitHub Actions Workflow**:
   - Downloads fresh violations.json from main branch
   - Uses selective sync: only adds/updates/deletes datapoints as needed
   - Preserves existing Beeminder data (prevents goal derailment)
   - No database uploads - works purely with violations.json

3. **Scheduled Sync** (12 PM NYC time):
   - Daily verification sync runs automatically
   - Ensures Beeminder stays in sync with violations.json
   - Handles any missed violations or corrections

### Tamper Resistance

- **Manual Beeminder Edits**: Selectively corrected by GitHub Actions
- **Data Integrity**: GitHub commit history provides audit trail
- **Redundancy**: Multiple backup points (local HSoT, GitHub violations.json, Beeminder)
- **Transparency**: All changes visible in public GitHub repository
- **Race Condition Protection**: Dual branch uploads and database copy fallback

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

- `night_logger_github.py`: Tamper-resistant night logger with exit logic fix (generates violations.json and uploads to GitHub)
- `night_logger_github_fixed_v3.py`: Latest fixed version with continuous logging behavior
- `sync_violations.py`: GitHub Actions sync program with selective updates and Beeminder pagination
- `.github/workflows/sync-violations.yml`: GitHub Actions workflow
- `test_comprehensive.py`: Comprehensive test suite (50 tests)
- `test_exit_logic_fix.py`: Exit logic fix tests (6 tests)
- `test_complete_with_fix.py`: Complete test suite (56 tests, 100% success rate)
- `deploy_fix.sh`: Deployment script for exit logic fix
- `.env.template`: Environment template for local setup
- `SETUP_TAMPER_RESISTANT.md`: This setup guide