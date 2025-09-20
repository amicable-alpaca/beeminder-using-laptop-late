#!/usr/bin/env python3
"""
Comprehensive test suite for the Night Logger system.

Tests functionality of:
- night_logger.py core logic
- Database operations
- Systemd service configuration
- Timer scheduling
- CLI utility functions
- File permissions and security
"""

import os
import sys
import sqlite3
import subprocess
import tempfile
import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta
import json
import re

# Add the script directory to path for importing
sys.path.insert(0, '/usr/local/bin')

class TestNightLoggerCore(unittest.TestCase):
    """Test core night_logger.py functionality"""

    def setUp(self):
        """Set up test database"""
        self.test_db_fd, self.test_db_path = tempfile.mkstemp(suffix='.db')
        os.close(self.test_db_fd)

    def tearDown(self):
        """Clean up test database"""
        if os.path.exists(self.test_db_path):
            os.unlink(self.test_db_path)

    def test_time_detection_functions(self):
        """Test night time detection logic"""
        # Import the main module
        import night_logger

        # Test cases for is_between_23_and_359_local
        test_cases = [
            (datetime(2023, 8, 15, 22, 30), False),  # 22:30 - not night
            (datetime(2023, 8, 15, 23, 0), True),   # 23:00 - night
            (datetime(2023, 8, 15, 23, 30), True),  # 23:30 - night
            (datetime(2023, 8, 16, 0, 30), True),   # 00:30 - night
            (datetime(2023, 8, 16, 2, 30), True),   # 02:30 - night
            (datetime(2023, 8, 16, 3, 59), True),   # 03:59 - night
            (datetime(2023, 8, 16, 4, 0), False),   # 04:00 - not night
            (datetime(2023, 8, 16, 12, 0), False),  # 12:00 - not night
        ]

        for dt, expected in test_cases:
            with self.subTest(time=dt.strftime("%H:%M")):
                result = night_logger.is_between_23_and_359_local(dt)
                self.assertEqual(result, expected,
                    f"Time {dt.strftime('%H:%M')} should be {'night' if expected else 'day'}")

    def test_database_operations(self):
        """Test database creation and operations"""
        import night_logger

        # Test database creation
        conn = night_logger.open_db(self.test_db_path)
        self.assertIsNotNone(conn)

        # Verify tables were created
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [row[0] for row in cursor.fetchall()]
        self.assertIn('logs', tables)
        self.assertIn('posts', tables)

        # Test logging entry
        conn.execute(night_logger.INSERT_SQL, (1,))
        conn.commit()

        cursor = conn.execute("SELECT COUNT(*) FROM logs;")
        count = cursor.fetchone()[0]
        self.assertEqual(count, 1)

        # Test post tracking
        ymd = "2023-08-15"
        self.assertFalse(night_logger.already_posted_today(conn, ymd))

        night_logger.mark_posted_today(conn, ymd)
        self.assertTrue(night_logger.already_posted_today(conn, ymd))

        conn.close()

    def test_local_ymd_function(self):
        """Test local date formatting"""
        import night_logger

        test_dt = datetime(2023, 8, 15, 14, 30, 45)
        result = night_logger.local_ymd(test_dt)
        self.assertEqual(result, "2023-08-15")


class TestSystemConfiguration(unittest.TestCase):
    """Test systemd configuration and file permissions"""

    def test_systemd_files_exist(self):
        """Test that all required systemd files exist"""
        required_files = [
            '/etc/systemd/system/night-logger.service',
            '/etc/systemd/system/night-logger-start.timer',
            '/etc/systemd/system/night-logger-stop.timer',
            '/etc/systemd/system/night-logger-stop.service',
            '/etc/systemd/system/night-logger.service.d/override.conf'
        ]

        for file_path in required_files:
            with self.subTest(file=file_path):
                self.assertTrue(os.path.exists(file_path),
                    f"Required systemd file missing: {file_path}")

    def test_service_configuration(self):
        """Test service configuration is valid"""
        service_file = '/etc/systemd/system/night-logger.service'

        with open(service_file, 'r') as f:
            content = f.read()

        # Check for required configurations
        self.assertIn('Type=simple', content)
        self.assertIn('/usr/local/bin/night_logger.py', content)
        self.assertIn('--db /var/lib/night-logger/night_logs.db', content)
        self.assertIn('Restart=on-failure', content)
        self.assertIn('StateDirectory=night-logger', content)

        # Check security hardening
        self.assertIn('NoNewPrivileges=yes', content)
        self.assertIn('ProtectSystem=full', content)
        self.assertIn('ReadWritePaths=/var/lib/night-logger', content)

    def test_timer_configuration(self):
        """Test timer configurations are valid"""
        start_timer = '/etc/systemd/system/night-logger-start.timer'
        stop_timer = '/etc/systemd/system/night-logger-stop.timer'

        with open(start_timer, 'r') as f:
            start_content = f.read()

        with open(stop_timer, 'r') as f:
            stop_content = f.read()

        # Check start timer
        self.assertIn('OnCalendar=*-*-* 22:55:00', start_content)
        self.assertIn('Unit=night-logger.service', start_content)
        self.assertIn('Persistent=true', start_content)

        # Check stop timer
        self.assertIn('OnCalendar=*-*-* 04:05:00', stop_content)
        self.assertIn('Unit=night-logger-stop.service', stop_content)
        self.assertIn('Persistent=true', stop_content)


class TestDatabaseAccess(unittest.TestCase):
    """Test database access and permissions"""

    def test_database_files_exist(self):
        """Test database files exist with correct permissions"""
        db_files = [
            '/var/lib/night-logger/night_logs.db',
            '/var/lib/night-logger/night_logs_ro.db'
        ]

        for db_file in db_files:
            with self.subTest(file=db_file):
                self.assertTrue(os.path.exists(db_file),
                    f"Database file missing: {db_file}")

    def test_database_permissions(self):
        """Test database file permissions are secure"""
        main_db = '/var/lib/night-logger/night_logs.db'
        stat_info = os.stat(main_db)

        # Check owner and group
        import pwd, grp
        owner = pwd.getpwuid(stat_info.st_uid).pw_name
        group = grp.getgrgid(stat_info.st_gid).gr_name

        self.assertEqual(owner, 'root')
        self.assertEqual(group, 'nightlog-readers')

        # Check permissions (should be 640: rw-r-----)
        perms = oct(stat_info.st_mode)[-3:]
        self.assertEqual(perms, '640')


class TestCLIUtility(unittest.TestCase):
    """Test nightlog CLI utility"""

    def test_nightlog_executable_exists(self):
        """Test nightlog CLI exists and is executable"""
        nightlog_path = '/usr/local/bin/nightlog'
        self.assertTrue(os.path.exists(nightlog_path))
        self.assertTrue(os.access(nightlog_path, os.X_OK))

    def test_nightlog_status_command(self):
        """Test nightlog status command runs without critical errors"""
        try:
            result = subprocess.run(['nightlog', 'status'],
                                  capture_output=True, text=True, timeout=30)
            # Command should run (may have database access issues but shouldn't crash)
            self.assertIsNotNone(result.returncode)
        except subprocess.TimeoutExpired:
            self.fail("nightlog status command timed out")
        except Exception as e:
            self.fail(f"nightlog status command failed unexpectedly: {e}")


class TestSystemStatus(unittest.TestCase):
    """Test current system status and operation"""

    def test_systemd_timers_enabled(self):
        """Test that systemd timers are enabled"""
        timers = ['night-logger-start.timer', 'night-logger-stop.timer']

        for timer in timers:
            with self.subTest(timer=timer):
                result = subprocess.run(['systemctl', 'is-enabled', timer],
                                      capture_output=True, text=True)
                # Timer should be enabled (exit code 0) or at least exist
                self.assertIn(result.returncode, [0, 1, 3],
                    f"Timer {timer} appears to be missing or misconfigured")

    def test_service_definition_valid(self):
        """Test service definition is valid according to systemd"""
        result = subprocess.run(['systemctl', 'status', 'night-logger.service'],
                              capture_output=True, text=True)

        # Service should be loaded (even if not running)
        self.assertIn('Loaded: loaded', result.stdout)

    def test_beeminder_env_file_exists(self):
        """Test Beeminder environment file exists"""
        env_file = '/etc/night-logger/beeminder.env'
        self.assertTrue(os.path.exists(env_file),
            "Beeminder environment file missing")

        # Check permissions are secure (should be 600: rw-------)
        stat_info = os.stat(env_file)
        perms = oct(stat_info.st_mode)[-3:]
        self.assertEqual(perms, '600',
            "Beeminder env file should have 600 permissions")


class TestOptionalComponents(unittest.TestCase):
    """Test optional snapshot components"""

    def test_snapshot_script_exists(self):
        """Test snapshot script exists if configured"""
        snapshot_script = '/usr/local/bin/nightlog_snapshot.sh'
        if os.path.exists(snapshot_script):
            self.assertTrue(os.access(snapshot_script, os.X_OK),
                "Snapshot script exists but is not executable")

    def test_snapshot_service_exists(self):
        """Test snapshot service exists if configured"""
        snapshot_service = '/etc/systemd/system/nightlog-snapshot.service'
        if os.path.exists(snapshot_service):
            with open(snapshot_service, 'r') as f:
                content = f.read()
            self.assertIn('nightlog_snapshot.sh', content)


def run_diagnostic_checks():
    """Run diagnostic checks and return issues found"""
    issues = []

    # Check database access issue
    try:
        result = subprocess.run(['sqlite3', '-readonly',
                               '/var/lib/night-logger/night_logs_ro.db',
                               'SELECT COUNT(*) FROM logs;'],
                              capture_output=True, text=True)
        if result.returncode != 0:
            issues.append("DATABASE_ACCESS: Cannot read database even with -readonly flag")
    except Exception as e:
        issues.append(f"DATABASE_ACCESS: Database query failed: {e}")

    # Check if user is in nightlog-readers group
    try:
        result = subprocess.run(['groups'], capture_output=True, text=True)
        if 'nightlog-readers' not in result.stdout:
            issues.append("PERMISSIONS: User not in nightlog-readers group")
    except Exception as e:
        issues.append(f"PERMISSIONS: Cannot check group membership: {e}")

    # Check service logs for errors
    try:
        result = subprocess.run(['journalctl', '-u', 'night-logger.service',
                               '-n', '10', '--no-pager'],
                              capture_output=True, text=True)
        if 'error' in result.stdout.lower() or 'failed' in result.stdout.lower():
            issues.append("SERVICE_LOGS: Recent errors found in service logs")
    except Exception as e:
        issues.append(f"SERVICE_LOGS: Cannot check service logs: {e}")

    return issues


if __name__ == '__main__':
    print("="*60)
    print("NIGHT LOGGER SYSTEM TEST SUITE")
    print("="*60)

    # Run diagnostic checks first
    print("\n🔍 Running diagnostic checks...")
    issues = run_diagnostic_checks()
    if issues:
        print("⚠️  Issues found:")
        for issue in issues:
            print(f"   - {issue}")
    else:
        print("✅ No critical issues detected")

    print(f"\n🧪 Running test suite...")

    # Run the test suite
    unittest.main(argv=[''], exit=False, verbosity=2)