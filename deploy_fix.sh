#!/bin/bash
set -e

echo "Deploying fixed night logger..."

# Stop the service
echo "Stopping night-logger service..."
sudo systemctl stop night-logger.service

# Backup the current version
echo "Backing up current version..."
sudo cp /usr/local/bin/night_logger_github.py /usr/local/bin/night_logger_github.py.backup

# Install the fixed version
echo "Installing fixed version..."
sudo cp night_logger_github_fixed.py /usr/local/bin/night_logger_github.py
sudo chmod +x /usr/local/bin/night_logger_github.py

# Restart the service
echo "Starting night-logger service..."
sudo systemctl start night-logger.service

# Check status
echo "Checking service status..."
sudo systemctl status night-logger.service --no-pager -l

echo "✅ Fixed version deployed successfully!"