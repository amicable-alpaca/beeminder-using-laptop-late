# Setup Guide: Tamper-Resistant Night Logger

This guide explains how to set up the tamper-resistant version of the Night Logger system.

## Architecture Overview

```
Local Computer (HSoT) -> GitHub (SoT) -> Beeminder (Display)
```

- **HSoT DB**: Highest Source of Truth - Local computer database
- **SoT DB**: Source of Truth - GitHub-hosted database
- **Beeminder**: Display/notification layer (gets overwritten by SoT)

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
   - Database: 4,806 log entries, 17 posted days
   - Last activity: 2025-09-19

### 3. Testing & Verification

1. **Test Complete System**:
   ```bash
   python3 test_comprehensive.py
   ```
   Expected: 26 tests, 100% success rate

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

## How It Works

### Daily Operation

1. **Night Usage Detected** (23:00-03:59):
   - Local computer logs usage to HSoT database
   - On first detection, uploads HSoT database to GitHub
   - Triggers GitHub Actions workflow

2. **GitHub Actions Workflow**:
   - Downloads HSoT database from GitHub branch
   - Syncs HSoT → SoT (HSoT overwrites SoT)
   - Syncs SoT → Beeminder (SoT overwrites Beeminder)
   - Commits updated SoT database to repository

3. **Scheduled Sync** (12 PM NYC time):
   - Daily verification sync runs automatically
   - Ensures Beeminder stays in sync with SoT database
   - Restores any manually deleted/modified Beeminder data

### Tamper Resistance

- **Manual Beeminder Edits**: Automatically overwritten by GitHub Actions
- **Data Integrity**: GitHub commit history provides audit trail
- **Redundancy**: Multiple backup points (local HSoT, GitHub SoT, Beeminder)
- **Transparency**: All changes visible in public GitHub repository

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

4. **Database Sync Issues**:
   - Check GitHub Actions logs for detailed error messages
   - Verify HSoT database upload succeeded

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

- `night_logger_github.py`: Modified night logger (triggers GitHub instead of Beeminder)
- `sync_nightlogger.py`: GitHub Actions sync program
- `.github/workflows/sync-nightlogger.yml`: GitHub Actions workflow
- `.env.template`: Environment template for local setup
- `SETUP_TAMPER_RESISTANT.md`: This setup guide