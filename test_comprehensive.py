#!/usr/bin/env python3
"""
Comprehensive Test Suite for Night Logger System

Tests all components:
- Repository code (night_logger_github.py, sync_nightlogger.py)
- Local system files (nightlog CLI, systemd services)
- Integration between components
- Error handling and edge cases
- Security and data integrity
"""

import base64
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open
import requests

# Add current directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import the modules we're testing
try:
    from night_logger_github import GitHubAPI, is_between_23_and_359_local, local_ymd, open_db, already_posted_today, mark_posted_today
    from sync_nightlogger import BeeminderAPI, NightLoggerSync
except ImportError as e:
    print(f"Warning: Could not import modules: {e}")


class TestNightLoggerGitHub(unittest.TestCase):
    """Test night_logger_github.py functionality"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.test_db = Path(self.temp_dir) / "test.db"

    def tearDown(self):
        if self.test_db.exists():
            self.test_db.unlink()

    def test_time_detection_comprehensive(self):
        """Test night time detection with comprehensive edge cases"""
        test_cases = [
            # Standard cases
            (datetime(2023, 8, 15, 22, 59, 59), False),  # Just before night
            (datetime(2023, 8, 15, 23, 0, 0), True),    # Exactly 23:00
            (datetime(2023, 8, 15, 23, 30, 0), True),   # Middle of night
            (datetime(2023, 8, 16, 0, 0, 0), True),     # Midnight
            (datetime(2023, 8, 16, 1, 30, 0), True),    # Early morning
            (datetime(2023, 8, 16, 3, 59, 59), True),   # Just before end
            (datetime(2023, 8, 16, 4, 0, 0), False),    # Exactly 4:00
            (datetime(2023, 8, 16, 12, 0, 0), False),   # Midday

            # Edge cases around hour boundaries
            (datetime(2023, 8, 15, 22, 59, 59, 999999), False),
            (datetime(2023, 8, 16, 3, 59, 59, 999999), True),
            (datetime(2023, 8, 16, 4, 0, 0, 1), False),
        ]

        for dt, expected in test_cases:
            with self.subTest(time=dt.strftime("%H:%M:%S.%f")):
                result = is_between_23_and_359_local(dt)
                self.assertEqual(result, expected,
                    f"Time {dt.strftime('%H:%M:%S.%f')} should be {'night' if expected else 'day'}")

    def test_database_operations_comprehensive(self):
        """Test comprehensive database operations"""
        # Test database creation
        conn = open_db(str(self.test_db))
        self.assertIsNotNone(conn)

        # Verify schema
        cursor = conn.execute("SELECT sql FROM sqlite_master WHERE type='table';")
        schemas = [row[0] for row in cursor.fetchall()]

        # Check that both tables exist with correct schema
        logs_schema = next((s for s in schemas if 'logs' in s), None)
        posts_schema = next((s for s in schemas if 'posts' in s), None)

        self.assertIsNotNone(logs_schema)
        self.assertIsNotNone(posts_schema)
        self.assertIn('is_night', logs_schema)
        self.assertIn('CHECK(is_night IN (0,1))', logs_schema)
        self.assertIn('ymd TEXT PRIMARY KEY', posts_schema)

        # Test constraint enforcement
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO logs (is_night) VALUES (2);")  # Invalid value

        # Test valid insertions
        conn.execute("INSERT INTO logs (is_night) VALUES (0);")
        conn.execute("INSERT INTO logs (is_night) VALUES (1);")
        conn.commit()

        # Test data retrieval
        cursor = conn.execute("SELECT COUNT(*) FROM logs;")
        self.assertEqual(cursor.fetchone()[0], 2)

        # Test post management
        ymd = "2023-08-15"
        self.assertFalse(already_posted_today(conn, ymd))

        mark_posted_today(conn, ymd)
        self.assertTrue(already_posted_today(conn, ymd))

        # Test idempotency
        mark_posted_today(conn, ymd)  # Should not raise error
        cursor = conn.execute("SELECT COUNT(*) FROM posts WHERE ymd = ?;", (ymd,))
        self.assertEqual(cursor.fetchone()[0], 1)

        conn.close()

    def test_local_ymd_formatting(self):
        """Test date formatting edge cases"""
        test_cases = [
            (datetime(2023, 1, 1, 0, 0, 0), "2023-01-01"),
            (datetime(2023, 12, 31, 23, 59, 59), "2023-12-31"),
            (datetime(2000, 2, 29, 12, 0, 0), "2000-02-29"),  # Leap year
            (datetime(1999, 12, 31, 23, 59, 59), "1999-12-31"),  # Y2K
        ]

        for dt, expected in test_cases:
            with self.subTest(date=dt.strftime("%Y-%m-%d")):
                result = local_ymd(dt)
                self.assertEqual(result, expected)


class TestGitHubAPI(unittest.TestCase):
    """Test GitHub API functionality"""

    def setUp(self):
        self.api = GitHubAPI("test_token", "test_user/test_repo")
        self.temp_dir = tempfile.mkdtemp()
        self.test_db = Path(self.temp_dir) / "test.db"

    def tearDown(self):
        if self.test_db.exists():
            self.test_db.unlink()

    def test_github_api_initialization(self):
        """Test GitHub API object initialization"""
        self.assertEqual(self.api.token, "test_token")
        self.assertEqual(self.api.repo, "test_user/test_repo")
        self.assertIn("Authorization", self.api.headers)
        self.assertEqual(self.api.headers["Authorization"], "token test_token")

    @patch('requests.put')
    @patch('requests.get')
    @patch('requests.post')
    def test_upload_database_new_branch(self, mock_post, mock_get, mock_put):
        """Test database upload when branch doesn't exist"""
        # Create test database
        conn = open_db(str(self.test_db))
        conn.execute("INSERT INTO logs (is_night) VALUES (1);")
        conn.commit()
        conn.close()

        # Mock branch doesn't exist, then main branch exists, then file doesn't exist
        mock_get.side_effect = [
            MagicMock(status_code=404),  # Branch doesn't exist
            MagicMock(status_code=200, json=lambda: {"object": {"sha": "main_sha"}}),  # Main branch
            MagicMock(status_code=404)  # File doesn't exist yet
        ]

        # Mock successful branch creation
        mock_post.return_value = MagicMock(status_code=201)

        # Mock successful file upload
        mock_put.return_value = MagicMock(status_code=201)

        result = self.api.upload_database_to_branch(str(self.test_db))
        self.assertTrue(result)

    @patch('requests.post')
    def test_trigger_workflow(self, mock_post):
        """Test workflow triggering"""
        mock_post.return_value = MagicMock(status_code=204)

        result = self.api.trigger_workflow("test-event")
        self.assertTrue(result)

        # Verify correct API call
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        self.assertIn("dispatches", call_args[0][0])
        self.assertEqual(call_args[1]["json"]["event_type"], "test-event")

    @patch('requests.post')
    def test_trigger_workflow_failure(self, mock_post):
        """Test workflow triggering failure handling"""
        mock_post.side_effect = requests.exceptions.RequestException("API Error")

        result = self.api.trigger_workflow("test-event")
        self.assertFalse(result)


class TestBeeminderAPI(unittest.TestCase):
    """Test Beeminder API functionality"""

    def setUp(self):
        self.api = BeeminderAPI("test_user", "test_token")

    @patch('requests.get')
    def test_get_goal_datapoints_with_pagination(self, mock_get):
        """Test paginated datapoint retrieval"""
        # Mock paginated responses
        page1_data = []
        for i in range(300):  # Full page
            page1_data.append({
                "id": str(i+1),
                "timestamp": 1609459200 + i*86400,
                "comment": f"test datapoint {i+1}",
                "value": 1
            })

        page2_data = [
            {"id": "301", "timestamp": 1609459200 + 300*86400, "comment": "final datapoint", "value": 1}
        ]

        mock_responses = [
            MagicMock(status_code=200, json=lambda: page1_data),
            MagicMock(status_code=200, json=lambda: page2_data)
        ]
        mock_get.side_effect = mock_responses

        result = self.api.get_goal_datapoints("test_goal")

        # Should fetch both pages
        self.assertEqual(len(result), 301)
        self.assertEqual(result[0]["id"], "1")
        self.assertEqual(result[-1]["id"], "301")
        self.assertEqual(mock_get.call_count, 2)

    @patch('requests.get')
    def test_get_goal_datapoints_empty(self, mock_get):
        """Test empty goal handling"""
        mock_get.return_value = MagicMock(status_code=200, json=lambda: [])

        result = self.api.get_goal_datapoints("empty_goal")
        self.assertEqual(len(result), 0)

    @patch('requests.post')
    def test_create_datapoint(self, mock_post):
        """Test datapoint creation"""
        mock_post.return_value = MagicMock(status_code=200)

        result = self.api.create_datapoint(
            "test_goal", 1.0, 1609459200, "test comment", "test_id"
        )
        self.assertTrue(result)

    @patch('requests.delete')
    def test_delete_datapoint(self, mock_delete):
        """Test datapoint deletion"""
        mock_delete.return_value = MagicMock(status_code=200)

        result = self.api.delete_datapoint("test_goal", "123")
        self.assertTrue(result)


class TestNightLoggerSync(unittest.TestCase):
    """Test sync_nightlogger.py functionality"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.env_patcher = patch.dict(os.environ, {
            'BEEMINDER_USERNAME': 'test_user',
            'BEEMINDER_AUTH_TOKEN': 'test_token',
            'BEEMINDER_GOAL_SLUG': 'test_goal',
            'GITHUB_TOKEN': 'test_github_token'
        })
        self.env_patcher.start()

    def tearDown(self):
        self.env_patcher.stop()

    def test_sync_initialization(self):
        """Test sync object initialization"""
        sync = NightLoggerSync()
        self.assertEqual(sync.beeminder_username, 'test_user')
        self.assertEqual(sync.beeminder_token, 'test_token')
        self.assertEqual(sync.beeminder_goal, 'test_goal')
        self.assertEqual(sync.github_token, 'test_github_token')

    def test_sync_missing_env(self):
        """Test initialization with missing environment variables"""
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError):
                NightLoggerSync()

    def test_database_operations(self):
        """Test database synchronization operations"""
        sync = NightLoggerSync()
        test_db = Path(self.temp_dir) / "test.db"

        # Create test database
        conn = sqlite3.connect(test_db)
        conn.executescript("""
            CREATE TABLE logs (
                id INTEGER PRIMARY KEY,
                logged_at TEXT,
                is_night INTEGER
            );
            CREATE TABLE posts (
                ymd TEXT PRIMARY KEY,
                posted_at_utc TEXT
            );
            INSERT INTO posts VALUES ('2023-08-15', '2023-08-16T05:00:00Z');
            INSERT INTO logs VALUES (1, '2023-08-15T23:30:00Z', 1);
        """)
        conn.commit()
        conn.close()

        # Test data extraction
        posts = sync.get_posted_days_from_db(test_db)
        logs = sync.get_logs_from_db(test_db)

        self.assertEqual(posts, {"2023-08-15"})
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0], ("2023-08-15T23:30:00Z", 1))


class TestSystemIntegration(unittest.TestCase):
    """Test integration between components"""

    def test_systemd_service_file_exists(self):
        """Test systemd service file exists and is valid"""
        service_file = "/etc/systemd/system/night-logger.service"
        self.assertTrue(os.path.exists(service_file))

        with open(service_file, 'r') as f:
            content = f.read()

        # Check for required configurations
        self.assertIn('night_logger_github.py', content)
        self.assertIn('EnvironmentFile=/home/admin/.env', content)
        self.assertIn('Type=simple', content)

    def test_nightlog_cli_exists(self):
        """Test nightlog CLI exists and is executable"""
        nightlog_path = "/usr/local/bin/nightlog"
        self.assertTrue(os.path.exists(nightlog_path))
        self.assertTrue(os.access(nightlog_path, os.X_OK))

    def test_environment_file_security(self):
        """Test environment file has correct permissions"""
        env_file = "/home/admin/.env"
        if os.path.exists(env_file):
            stat_info = os.stat(env_file)
            perms = oct(stat_info.st_mode)[-3:]
            self.assertEqual(perms, '600', "Environment file should have 600 permissions")

    def test_database_permissions(self):
        """Test database files have correct permissions"""
        db_files = [
            "/var/lib/night-logger/night_logs.db",
            "/var/lib/night-logger/night_logs_ro.db"
        ]

        for db_file in db_files:
            if os.path.exists(db_file):
                with self.subTest(file=db_file):
                    stat_info = os.stat(db_file)
                    import pwd, grp

                    # Should be owned by root with nightlog-readers group
                    owner = pwd.getpwuid(stat_info.st_uid).pw_name
                    group = grp.getgrgid(stat_info.st_gid).gr_name

                    self.assertEqual(owner, 'root')
                    self.assertEqual(group, 'nightlog-readers')


class TestErrorHandling(unittest.TestCase):
    """Test error handling and edge cases"""

    def test_database_corruption_handling(self):
        """Test handling of corrupted database"""
        temp_dir = tempfile.mkdtemp()
        corrupt_db = Path(temp_dir) / "corrupt.db"

        # Create a file that's not a valid SQLite database
        with open(corrupt_db, 'w') as f:
            f.write("This is not a valid SQLite database")

        # Test that our code handles this gracefully
        with self.assertRaises(sqlite3.DatabaseError):
            open_db(str(corrupt_db))

    def test_network_failure_handling(self):
        """Test handling of network failures"""
        api = GitHubAPI("test_token", "test_user/test_repo")

        with patch('requests.post') as mock_post:
            mock_post.side_effect = requests.exceptions.ConnectionError("Network error")

            result = api.trigger_workflow("test-event")
            self.assertFalse(result)

    def test_invalid_time_handling(self):
        """Test handling of invalid time values"""
        # Test with various edge cases
        test_cases = [
            datetime(1970, 1, 1, 0, 0, 0),  # Unix epoch
            datetime(2038, 1, 19, 3, 14, 7),  # 32-bit timestamp limit
            datetime(9999, 12, 31, 23, 59, 59),  # Far future
        ]

        for dt in test_cases:
            with self.subTest(time=dt):
                # Should not raise exception
                result = is_between_23_and_359_local(dt)
                self.assertIsInstance(result, bool)


class TestSecurityAndDataIntegrity(unittest.TestCase):
    """Test security aspects and data integrity"""

    def test_sql_injection_protection(self):
        """Test protection against SQL injection"""
        temp_dir = tempfile.mkdtemp()
        test_db = Path(temp_dir) / "test.db"

        conn = open_db(str(test_db))

        # Try SQL injection in ymd parameter
        malicious_ymd = "'; DROP TABLE logs; --"

        # This should not cause any issues
        result = already_posted_today(conn, malicious_ymd)
        self.assertFalse(result)

        # Verify tables still exist
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [row[0] for row in cursor.fetchall()]
        self.assertIn('logs', tables)
        self.assertIn('posts', tables)

        conn.close()

    def test_file_path_traversal_protection(self):
        """Test protection against path traversal attacks"""
        api = GitHubAPI("test_token", "test_user/test_repo")

        # Try path traversal in database upload
        malicious_path = "../../../etc/passwd"

        # Should handle gracefully (file won't exist or access denied)
        try:
            result = api.upload_database_to_branch(malicious_path)
            self.assertFalse(result)
        except (FileNotFoundError, PermissionError):
            # Expected behavior - path traversal blocked
            pass

    def test_environment_variable_validation(self):
        """Test validation of environment variables"""
        with patch.dict(os.environ, {
            'BEEMINDER_USERNAME': '',  # Empty string
            'BEEMINDER_AUTH_TOKEN': 'test_token',
            'BEEMINDER_GOAL_SLUG': 'test_goal',
            'GITHUB_TOKEN': 'test_github_token'
        }):
            with self.assertRaises(ValueError):
                NightLoggerSync()


class TestPerformanceAndScalability(unittest.TestCase):
    """Test performance characteristics"""

    def test_large_database_handling(self):
        """Test handling of large databases"""
        temp_dir = tempfile.mkdtemp()
        test_db = Path(temp_dir) / "large_test.db"

        conn = open_db(str(test_db))

        # Insert a large number of records
        records = [(f"2023-08-{i:02d}T23:30:00Z", 1) for i in range(1, 32)]  # Month of data
        conn.executemany("INSERT INTO logs (logged_at, is_night) VALUES (?, ?);", records)
        conn.commit()

        # Test retrieval performance
        start_time = time.time()
        cursor = conn.execute("SELECT COUNT(*) FROM logs WHERE is_night = 1;")
        result = cursor.fetchone()[0]
        end_time = time.time()

        self.assertEqual(result, 31)
        self.assertLess(end_time - start_time, 1.0, "Query should complete quickly")

        conn.close()

    def test_pagination_efficiency(self):
        """Test that pagination works efficiently"""
        api = BeeminderAPI("test_user", "test_token")

        with patch('requests.get') as mock_get:
            # Mock pagination with proper stop condition
            page_responses = [
                # Page 1: Full page (300 items)
                MagicMock(status_code=200, json=lambda: [{"id": str(i), "timestamp": 1609459200 + i} for i in range(300)]),
                # Page 2: Partial page (50 items) - triggers stop
                MagicMock(status_code=200, json=lambda: [{"id": str(i), "timestamp": 1609459200 + i} for i in range(300, 350)])
            ]
            mock_get.side_effect = page_responses

            start_time = time.time()
            result = api.get_goal_datapoints("test_goal")
            end_time = time.time()

            self.assertEqual(len(result), 350)  # 300 + 50
            self.assertLess(end_time - start_time, 5.0, "Pagination should be efficient")


def run_comprehensive_tests():
    """Run all tests and generate detailed report"""
    print("🧪 COMPREHENSIVE NIGHT LOGGER TEST SUITE")
    print("=" * 60)

    # Discover and run all tests
    test_classes = [
        TestNightLoggerGitHub,
        TestGitHubAPI,
        TestBeeminderAPI,
        TestNightLoggerSync,
        TestSystemIntegration,
        TestErrorHandling,
        TestSecurityAndDataIntegrity,
        TestPerformanceAndScalability
    ]

    suite = unittest.TestSuite()
    for test_class in test_classes:
        tests = unittest.TestLoader().loadTestsFromTestCase(test_class)
        suite.addTests(tests)

    # Run tests with detailed output
    runner = unittest.TextTestRunner(verbosity=2, stream=sys.stdout)
    result = runner.run(suite)

    # Print summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    print(f"Tests run: {result.testsRun}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print(f"Success rate: {((result.testsRun - len(result.failures) - len(result.errors)) / result.testsRun * 100):.1f}%")

    if result.failures:
        print("\nFAILURES:")
        for test, traceback in result.failures:
            error_msg = traceback.split('AssertionError: ')[-1].split('\n')[0]
            print(f"- {test}: {error_msg}")

    if result.errors:
        print("\nERRORS:")
        for test, traceback in result.errors:
            error_msg = traceback.split('Exception: ')[-1].split('\n')[0]
            print(f"- {test}: {error_msg}")

    return result.wasSuccessful()


if __name__ == '__main__':
    success = run_comprehensive_tests()
    sys.exit(0 if success else 1)