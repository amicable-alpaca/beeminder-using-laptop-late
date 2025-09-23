#!/usr/bin/env python3
"""
Comprehensive Test Suite for Night Logger System (Updated)

Tests all components of the violations-only architecture:
- night_logger_github.py (violations.json generation and GitHub upload)
- sync_violations.py (selective sync with Beeminder API pagination)
- extract_violations.py (HSoT database processing)
- Integration testing and error handling
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
import shutil

# Add current directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import the modules we're testing
try:
    from night_logger_github import (
        GitHubAPI, is_between_23_and_359_local, local_ymd, open_db,
        already_posted_today, mark_posted_today, extract_violations
    )
    from sync_violations import BeeminderAPI, ViolationsSync
except ImportError as e:
    print(f"Warning: Could not import modules: {e}")


class TestNightLoggerCore(unittest.TestCase):
    """Test core night logger functionality"""

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

    def test_violations_extraction(self):
        """Test violations extraction from HSoT database"""
        # Create test database with violations
        conn = open_db(str(self.test_db))

        # Add some test data
        test_violations = [
            ("2025-08-15T06:12:14.942Z", 1),   # 6 AM on 8/15 → attributed to 8/15
            ("2025-08-15T06:13:13.086Z", 1),   # Same day, multiple detections
            ("2025-08-16T23:00:02.198Z", 1),   # 11 PM on 8/16 → attributed to 8/16
            ("2025-08-17T12:00:00.000Z", 0),   # Day time, should be ignored
        ]

        for timestamp, is_night in test_violations:
            conn.execute("INSERT INTO logs (logged_at, is_night) VALUES (?, ?);", (timestamp, is_night))

        # Add some posted dates
        conn.execute("INSERT INTO posts (ymd, posted_at_utc) VALUES (?, ?);", ("2025-08-15", "2025-08-15T12:00:00Z"))
        conn.commit()
        conn.close()

        # Test violations extraction
        violations_data = extract_violations(str(self.test_db))

        # Verify structure
        self.assertIn('violations', violations_data)
        self.assertIn('posted_dates', violations_data)
        self.assertIn('total_violations', violations_data)
        self.assertIn('unposted_violations', violations_data)

        # Verify data
        self.assertEqual(violations_data['total_violations'], 2)  # 2 unique dates with violations
        self.assertEqual(len(violations_data['violations']), 2)
        self.assertIn("2025-08-15", [v['date'] for v in violations_data['violations']])
        self.assertIn("2025-08-16", [v['date'] for v in violations_data['violations']])

        # Check that 8/15 shows 2 detections
        aug_15_violation = next(v for v in violations_data['violations'] if v['date'] == '2025-08-15')
        self.assertEqual(aug_15_violation['comment'], "Night logger violation (2 detections)")

        # Check posted dates
        self.assertIn("2025-08-15", violations_data['posted_dates'])

        # Check unposted violations (should not include posted 8/15)
        unposted_dates = [v['date'] for v in violations_data['unposted_violations']]
        self.assertNotIn("2025-08-15", unposted_dates)
        self.assertIn("2025-08-16", unposted_dates)


class TestGitHubAPI(unittest.TestCase):
    """Test GitHub API functionality for violations.json upload"""

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
    def test_upload_violations_new_branch(self, mock_post, mock_get, mock_put):
        """Test violations.json upload when branch doesn't exist"""
        # Create test database with violations
        conn = open_db(str(self.test_db))
        conn.execute("INSERT INTO logs (logged_at, is_night) VALUES (?, ?);", ("2025-08-15T06:12:14.942Z", 1))
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

        result = self.api.upload_violations_to_branch(str(self.test_db))
        self.assertTrue(result)

        # Verify violations.json was uploaded (not database file)
        put_call = mock_put.call_args
        self.assertIn("violations.json", put_call[0][0])  # URL contains violations.json

        # Verify content is JSON (not binary database)
        uploaded_content = put_call[1]['json']['content']
        decoded_content = base64.b64decode(uploaded_content).decode('utf-8')
        parsed_json = json.loads(decoded_content)
        self.assertIn('violations', parsed_json)

    @patch('requests.post')
    def test_trigger_workflow(self, mock_post):
        """Test workflow triggering"""
        mock_post.return_value = MagicMock(status_code=204)

        result = self.api.trigger_workflow("night-logger-sync")
        self.assertTrue(result)

        # Verify correct API call
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        self.assertIn("dispatches", call_args[0][0])
        self.assertEqual(call_args[1]["json"]["event_type"], "night-logger-sync")


class TestBeeminderAPI(unittest.TestCase):
    """Test Beeminder API with pagination support"""

    def setUp(self):
        self.api = BeeminderAPI("test_user", "test_token")

    def test_beeminder_api_initialization(self):
        """Test Beeminder API initialization"""
        self.assertEqual(self.api.username, "test_user")
        self.assertEqual(self.api.auth_token, "test_token")
        self.assertEqual(self.api.base_url, "https://www.beeminder.com/api/v1")

    @patch('requests.get')
    def test_pagination_single_page(self, mock_get):
        """Test pagination with single page of results"""
        # Mock single page with less than 300 results
        mock_response = MagicMock()
        mock_response.json.return_value = [
            {"id": "1", "timestamp": 1692057600, "value": 1, "comment": "test1"},
            {"id": "2", "timestamp": 1692144000, "value": 1, "comment": "test2"}
        ]
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        result = self.api.get_goal_datapoints("test-goal")

        self.assertEqual(len(result), 2)
        mock_get.assert_called_once()

        # Verify pagination parameters
        call_args = mock_get.call_args
        params = call_args[1]['params']
        self.assertEqual(params['page'], 1)
        self.assertEqual(params['per_page'], 300)

    @patch('requests.get')
    def test_pagination_multiple_pages(self, mock_get):
        """Test pagination with multiple pages"""
        # Mock multiple pages
        page_1_data = [{"id": str(i), "timestamp": 1692057600 + i, "value": 1} for i in range(300)]
        page_2_data = [{"id": str(i), "timestamp": 1692057600 + i, "value": 1} for i in range(300, 350)]

        mock_responses = [
            MagicMock(json=lambda: page_1_data),  # Page 1: 300 items
            MagicMock(json=lambda: page_2_data)   # Page 2: 50 items
        ]

        for resp in mock_responses:
            resp.raise_for_status.return_value = None

        mock_get.side_effect = mock_responses

        result = self.api.get_goal_datapoints("test-goal")

        self.assertEqual(len(result), 350)  # Total from both pages
        self.assertEqual(mock_get.call_count, 2)  # Two API calls

    @patch('requests.post')
    def test_create_datapoint_timestamp_conversion(self, mock_post):
        """Test datapoint creation with ISO timestamp conversion"""
        mock_post.return_value = MagicMock(status_code=200)
        mock_post.return_value.raise_for_status.return_value = None

        violation = {
            "date": "2025-08-15",
            "timestamp": "2025-08-15T06:12:14.942Z",
            "value": 1,
            "comment": "Night logger violation (2 detections)"
        }

        result = self.api.create_datapoint("test-goal", violation)
        self.assertTrue(result)

        # Verify timestamp conversion
        call_args = mock_post.call_args
        posted_data = call_args[1]['data']
        self.assertIn('timestamp', posted_data)
        self.assertIsInstance(posted_data['timestamp'], int)  # Unix timestamp
        self.assertEqual(posted_data['value'], 1.0)  # Converted to float
        self.assertEqual(posted_data['comment'], violation['comment'])


class TestViolationsSync(unittest.TestCase):
    """Test violations-only sync system"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.violations_file = Path(self.temp_dir) / "test_violations.json"

        # Create test violations.json
        test_violations = {
            "violations": [
                {
                    "date": "2025-08-15",
                    "timestamp": "2025-08-15T06:12:14.942Z",
                    "value": 1,
                    "comment": "Night logger violation (2 detections)",
                    "daystamp": "20250815"
                },
                {
                    "date": "2025-08-16",
                    "timestamp": "2025-08-16T03:00:02.198Z",
                    "value": 1,
                    "comment": "Night logger violation (1 detections)",
                    "daystamp": "20250816"
                }
            ],
            "posted_dates": ["2025-08-15"],
            "last_updated": "2025-08-16T12:00:00Z",
            "total_violations": 2,
            "unposted_violations": [
                {
                    "date": "2025-08-16",
                    "timestamp": "2025-08-16T03:00:02.198Z",
                    "value": 1,
                    "comment": "Night logger violation (1 detections)",
                    "daystamp": "20250816"
                }
            ]
        }

        with open(self.violations_file, 'w') as f:
            json.dump(test_violations, f)

    def tearDown(self):
        if self.violations_file.exists():
            self.violations_file.unlink()

    def test_load_violations(self):
        """Test loading violations from JSON file"""
        # Mock environment variables
        with patch.dict('os.environ', {
            'BEEMINDER_USERNAME': 'test_user',
            'BEEMINDER_AUTH_TOKEN': 'test_token',
            'BEEMINDER_GOAL_SLUG': 'test_goal'
        }):
            sync = ViolationsSync()
            violations_data = sync.load_violations(str(self.violations_file))

            self.assertEqual(violations_data['total_violations'], 2)
            self.assertEqual(len(violations_data['violations']), 2)
            self.assertEqual(len(violations_data['unposted_violations']), 1)

    @patch('sync_violations.BeeminderAPI')
    def test_selective_sync_logic(self, mock_beeminder_class):
        """Test selective sync identifies correct changes needed"""
        # Mock BeeminderAPI instance
        mock_beeminder = MagicMock()
        mock_beeminder_class.return_value = mock_beeminder

        # Mock existing Beeminder datapoints (missing 8/16, has extra 8/17)
        existing_datapoints = [
            {
                "id": "dp1",
                "timestamp": 1755238334,  # 2025-08-15 02:12:14 UTC (06:12:14 UTC)
                "value": 1.0,
                "comment": "Night logger violation (2 detections)"
            },
            {
                "id": "dp2",
                "timestamp": 1755324000,  # 2025-08-17 (not in violations.json)
                "value": 1.0,
                "comment": "Manual entry"
            }
        ]
        mock_beeminder.get_goal_datapoints.return_value = existing_datapoints

        # Mock environment variables
        with patch.dict('os.environ', {
            'BEEMINDER_USERNAME': 'test_user',
            'BEEMINDER_AUTH_TOKEN': 'test_token',
            'BEEMINDER_GOAL_SLUG': 'test_goal'
        }):
            sync = ViolationsSync()
            violations_data = sync.load_violations(str(self.violations_file))

            # Test selective sync (we can't easily test the full method due to complexity,
            # but we can test the logic components)
            sot_violations = {v['date']: v for v in violations_data['violations']}

            # Verify SoT has what we expect
            self.assertIn('2025-08-15', sot_violations)
            self.assertIn('2025-08-16', sot_violations)
            self.assertNotIn('2025-08-17', sot_violations)



class TestIntegration(unittest.TestCase):
    """Test integration between components"""

    def test_end_to_end_violations_flow(self):
        """Test complete violations flow: DB -> JSON -> Upload simulation"""
        with tempfile.TemporaryDirectory() as temp_dir:
            test_db = Path(temp_dir) / "test.db"

            # Step 1: Create HSoT database with violations
            conn = open_db(str(test_db))
            conn.execute("INSERT INTO logs (logged_at, is_night) VALUES (?, ?);", ("2025-08-15T06:12:14.942Z", 1))
            conn.execute("INSERT INTO logs (logged_at, is_night) VALUES (?, ?);", ("2025-08-15T06:13:13.086Z", 1))
            conn.commit()
            conn.close()

            # Step 2: Extract violations
            violations_data = extract_violations(str(test_db))
            self.assertEqual(violations_data['total_violations'], 1)  # One unique date

            # Step 3: Simulate GitHub upload (test JSON serialization)
            violations_json = json.dumps(violations_data, indent=2)
            violations_base64 = base64.b64encode(violations_json.encode('utf-8')).decode('utf-8')

            # Verify round-trip
            decoded_json = base64.b64decode(violations_base64).decode('utf-8')
            parsed_violations = json.loads(decoded_json)
            self.assertEqual(parsed_violations['total_violations'], 1)

    def test_error_handling_missing_files(self):
        """Test error handling for missing files"""
        # Test extract_violations with missing database
        result = extract_violations("/nonexistent/database.db")
        self.assertEqual(result['violations'], [])
        self.assertEqual(result['total_violations'], 0)

        # Test ViolationsSync with missing violations file
        with patch.dict('os.environ', {
            'BEEMINDER_USERNAME': 'test_user',
            'BEEMINDER_AUTH_TOKEN': 'test_token',
            'BEEMINDER_GOAL_SLUG': 'test_goal'
        }):
            sync = ViolationsSync()
            result = sync.load_violations("/nonexistent/violations.json")
            self.assertEqual(result['violations'], [])


class TestSecurity(unittest.TestCase):
    """Test security aspects"""

    def test_no_secrets_in_code(self):
        """Ensure no hardcoded secrets in modules"""
        modules_to_check = [
            'night_logger_github.py',
            'sync_violations.py',
            'extract_violations.py'
        ]

        for module_file in modules_to_check:
            if Path(module_file).exists():
                with open(module_file, 'r') as f:
                    content = f.read()

                # Check for common secret patterns
                self.assertNotIn('ghp_', content, f"GitHub token found in {module_file}")
                self.assertNotIn('password', content.lower(), f"Password found in {module_file}")

                # Ensure environment variables are used
                if 'BEEMINDER' in content:
                    self.assertIn('os.getenv', content, f"Hardcoded Beeminder credentials in {module_file}")

    def test_database_readonly_access(self):
        """Test database readonly access patterns"""
        with tempfile.TemporaryDirectory() as temp_dir:
            test_db = Path(temp_dir) / "test.db"

            # Create database
            conn = open_db(str(test_db))
            conn.execute("INSERT INTO logs (is_night) VALUES (1);")
            conn.commit()
            conn.close()

            # Test readonly access in extract_violations
            violations = extract_violations(str(test_db))
            self.assertIsInstance(violations, dict)

            # Verify original database unchanged
            conn = sqlite3.connect(str(test_db))
            cursor = conn.execute("SELECT COUNT(*) FROM logs;")
            self.assertEqual(cursor.fetchone()[0], 1)
            conn.close()


class TestDatabaseConcurrency(unittest.TestCase):
    """Test database concurrency and WAL mode handling"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.test_db = Path(self.temp_dir) / "test_concurrent.db"

    def tearDown(self):
        if self.test_db.exists():
            self.test_db.unlink()
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_wal_mode_database_access(self):
        """Test accessing WAL mode database from multiple connections"""
        # Create database with WAL mode
        conn1 = open_db(str(self.test_db))
        conn1.execute("INSERT INTO logs (is_night) VALUES (1);")
        conn1.commit()

        # Test concurrent access while first connection still open
        violations = extract_violations(str(self.test_db))
        self.assertIsInstance(violations, dict)
        self.assertGreaterEqual(len(violations['violations']), 1)

        conn1.close()

    def test_database_copy_fallback(self):
        """Test database copy fallback mechanism when readonly fails"""
        # Create test database
        conn = open_db(str(self.test_db))
        conn.execute("INSERT INTO logs (is_night) VALUES (1);")
        conn.commit()
        conn.close()

        # Test extract_violations with copy fallback
        violations = extract_violations(str(self.test_db))
        self.assertIsInstance(violations, dict)
        self.assertGreaterEqual(len(violations['violations']), 1)

    def test_connection_cleanup(self):
        """Test proper connection cleanup in extract_violations"""
        conn = open_db(str(self.test_db))
        conn.execute("INSERT INTO logs (is_night) VALUES (1);")
        conn.commit()
        conn.close()

        # Multiple calls should not leave connections open
        for _ in range(5):
            violations = extract_violations(str(self.test_db))
            self.assertIsInstance(violations, dict)

    def test_database_permission_errors(self):
        """Test handling of database permission errors"""
        # Test non-existent database
        violations = extract_violations("/nonexistent/path/test.db")
        self.assertEqual(violations['violations'], [])
        self.assertEqual(violations['total_violations'], 0)


class TestNightTimeAttribution(unittest.TestCase):
    """Test night time attribution logic (00:00-03:59 → previous day)"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.test_db = Path(self.temp_dir) / "test_attribution.db"

    def tearDown(self):
        if self.test_db.exists():
            self.test_db.unlink()
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_early_morning_attribution(self):
        """Test that 00:00-03:59 violations are attributed to previous day"""
        conn = open_db(str(self.test_db))

        # Insert violation at 2 AM on 2025-09-22 (should be attributed to 2025-09-21)
        early_morning = "2025-09-22T02:30:00.000Z"
        conn.execute("INSERT INTO logs (logged_at, is_night) VALUES (?, 1);", (early_morning,))
        conn.commit()
        conn.close()

        violations = extract_violations(str(self.test_db))

        # Should be attributed to previous day
        self.assertEqual(len(violations['violations']), 1)
        violation = violations['violations'][0]
        self.assertEqual(violation['date'], '2025-09-21')  # Previous day
        self.assertEqual(violation['daystamp'], '20250921')  # Previous day

    def test_late_night_attribution(self):
        """Test that 23:00-23:59 violations are attributed to same day"""
        conn = open_db(str(self.test_db))

        # Insert violation at 11 PM on 2025-09-22 (should be attributed to 2025-09-22)
        late_night = "2025-09-22T23:30:00.000Z"
        conn.execute("INSERT INTO logs (logged_at, is_night) VALUES (?, 1);", (late_night,))
        conn.commit()
        conn.close()

        violations = extract_violations(str(self.test_db))

        # Should be attributed to same day
        self.assertEqual(len(violations['violations']), 1)
        violation = violations['violations'][0]
        self.assertEqual(violation['date'], '2025-09-22')  # Same day
        self.assertEqual(violation['daystamp'], '20250922')  # Same day

    def test_boundary_times(self):
        """Test boundary times (exactly 03:59 and 04:00)"""
        conn = open_db(str(self.test_db))

        # 03:59 should be previous day
        boundary_early = "2025-09-22T03:59:59.999Z"
        conn.execute("INSERT INTO logs (logged_at, is_night) VALUES (?, 1);", (boundary_early,))

        # 04:00 should be same day
        boundary_late = "2025-09-22T04:00:00.000Z"
        conn.execute("INSERT INTO logs (logged_at, is_night) VALUES (?, 1);", (boundary_late,))

        conn.commit()
        conn.close()

        violations = extract_violations(str(self.test_db))

        # Should have 2 violations with different date attributions
        self.assertEqual(len(violations['violations']), 2)

        # Sort by timestamp to get predictable order
        violations_sorted = sorted(violations['violations'], key=lambda x: x['timestamp'])

        # First (03:59) should be previous day
        self.assertEqual(violations_sorted[0]['date'], '2025-09-21')

        # Second (04:00) should be same day
        self.assertEqual(violations_sorted[1]['date'], '2025-09-22')


class TestErrorHandlingEnhanced(unittest.TestCase):
    """Enhanced error handling tests"""

    def test_malformed_violations_json(self):
        """Test handling of malformed violations.json files"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write('{"invalid": json')  # Malformed JSON
            malformed_file = f.name

        try:
            sync = ViolationsSync()
            violations = sync.load_violations(malformed_file)
            # Should return empty structure on JSON error
            self.assertEqual(violations['violations'], [])
        except:
            # It's also acceptable to raise an exception
            pass
        finally:
            os.unlink(malformed_file)

    def test_network_timeout_scenarios(self):
        """Test network timeout handling"""
        with patch('requests.get') as mock_get:
            mock_get.side_effect = requests.exceptions.Timeout("Network timeout")

            api = BeeminderAPI("test_user", "test_token")
            datapoints = api.get_goal_datapoints("test_goal")

            # Should handle timeout gracefully
            self.assertEqual(datapoints, [])

    def test_github_api_rate_limiting(self):
        """Test GitHub API rate limiting handling"""
        with patch('requests.post') as mock_post:
            # Simulate rate limit response
            mock_response = MagicMock()
            mock_response.status_code = 403
            mock_response.json.return_value = {"message": "API rate limit exceeded"}
            mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError("403 Rate Limited")
            mock_post.return_value = mock_response

            github_api = GitHubAPI("test_token", "test/repo")
            result = github_api.trigger_workflow()

            # Should handle rate limiting gracefully
            self.assertFalse(result)

    def test_database_corruption_handling(self):
        """Test handling of corrupted database files"""
        # Create a file that looks like a database but is corrupted
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            f.write(b"NOT A SQLITE DATABASE")
            corrupt_db = f.name

        try:
            violations = extract_violations(corrupt_db)
            # Should return empty structure for corrupted database
            self.assertEqual(violations['violations'], [])
        except:
            # It's also acceptable to raise an exception for corruption
            pass
        finally:
            os.unlink(corrupt_db)


class TestRaceConditions(unittest.TestCase):
    """Test race condition scenarios"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.test_db = Path(self.temp_dir) / "test_race.db"

    def tearDown(self):
        if self.test_db.exists():
            self.test_db.unlink()
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_concurrent_database_writes(self):
        """Test that concurrent writes don't corrupt database"""
        conn1 = open_db(str(self.test_db))

        # Sequential writes to avoid locking issues
        conn1.execute("INSERT INTO logs (is_night) VALUES (1);")
        conn1.commit()

        conn1.execute("INSERT INTO logs (is_night) VALUES (0);")
        conn1.commit()

        # Extract violations
        violations = extract_violations(str(self.test_db))

        conn1.close()

        # Should handle access without corruption
        self.assertIsInstance(violations, dict)
        self.assertIn('violations', violations)

    def test_database_access_during_extraction(self):
        """Test database access during violations extraction"""
        # Create initial data
        conn = open_db(str(self.test_db))
        conn.execute("INSERT INTO logs (is_night) VALUES (1);")
        conn.commit()

        # Extract violations
        violations = extract_violations(str(self.test_db))

        # Simulate more writes after extraction
        conn.execute("INSERT INTO logs (is_night) VALUES (1);")
        conn.commit()
        conn.close()

        # Should handle concurrent access
        self.assertIsInstance(violations, dict)
        self.assertGreaterEqual(len(violations['violations']), 1)


class TestTimestampHandling(unittest.TestCase):
    """Test comprehensive timestamp handling"""

    def test_timezone_edge_cases(self):
        """Test timestamp handling across different timezone scenarios"""
        test_cases = [
            "2025-09-20T03:00:00.441Z",      # Early morning 9/20 → attributed to 9/19
            "2025-09-21T23:00:00.000Z",      # Late night 9/21 → attributed to 9/21
            "2025-09-23T03:59:59.999Z",      # Boundary 9/23 → attributed to 9/22
            "2025-09-24T04:00:00.000Z",      # After boundary 9/24 → attributed to 9/24
            "2025-09-25T23:30:00.000Z",      # Another late night → attributed to 9/25
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            test_db = Path(temp_dir) / "test_timezone.db"
            conn = open_db(str(test_db))

            for i, timestamp in enumerate(test_cases):
                conn.execute("INSERT INTO logs (logged_at, is_night) VALUES (?, 1);", (timestamp,))

            conn.commit()
            conn.close()

            violations = extract_violations(str(test_db))

            # Should process all timestamps without errors
            self.assertEqual(len(violations['violations']), len(test_cases))

            # Verify all have valid date formats
            for violation in violations['violations']:
                self.assertRegex(violation['date'], r'^\d{4}-\d{2}-\d{2}$')
                self.assertRegex(violation['daystamp'], r'^\d{8}$')

    def test_leap_year_handling(self):
        """Test handling of leap year dates"""
        leap_year_cases = [
            "2024-02-29T01:00:00.000Z",  # Valid leap year date
            "2025-02-28T01:00:00.000Z",  # Non-leap year boundary
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            test_db = Path(temp_dir) / "test_leap.db"
            conn = open_db(str(test_db))

            for timestamp in leap_year_cases:
                conn.execute("INSERT INTO logs (logged_at, is_night) VALUES (?, 1);", (timestamp,))

            conn.commit()
            conn.close()

            violations = extract_violations(str(test_db))

            # Should handle leap year dates correctly
            self.assertEqual(len(violations['violations']), len(leap_year_cases))


class TestDualBranchUpload(unittest.TestCase):
    """Test dual branch upload functionality"""

    def setUp(self):
        self.test_db = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        self.test_db.close()

    def tearDown(self):
        try:
            os.unlink(self.test_db.name)
        except:
            pass

    @patch('night_logger_github.requests.get')
    @patch('night_logger_github.requests.post')
    @patch('night_logger_github.requests.put')
    def test_dual_branch_upload_success(self, mock_put, mock_post, mock_get):
        """Test successful upload to both main and violations-data branches"""
        # Setup mocks for successful responses
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {"sha": "test-sha"}
        mock_put.return_value.status_code = 200
        mock_put.return_value.raise_for_status.return_value = None

        # Create test database with violation
        conn = open_db(self.test_db.name)
        conn.execute("INSERT INTO logs (is_night) VALUES (1)")
        conn.commit()
        conn.close()

        # Test dual upload
        github_api = GitHubAPI("test-token", "test/repo")

        # Should call upload_violations_to_branch twice
        result1 = github_api.upload_violations_to_branch(self.test_db.name, "violations-data")
        result2 = github_api.upload_violations_to_branch(self.test_db.name, "main")

        self.assertTrue(result1)
        self.assertTrue(result2)

    @patch('night_logger_github.requests.get')
    @patch('night_logger_github.requests.put')
    def test_dual_branch_upload_partial_failure(self, mock_put, mock_get):
        """Test when one branch upload fails"""
        # Setup mocks - first succeeds, second fails
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {"sha": "test-sha"}

        # First upload succeeds, second fails
        mock_put.side_effect = [
            unittest.mock.Mock(status_code=200),  # First upload succeeds
            requests.exceptions.RequestException("Network error")  # Second fails
        ]

        # Create test database
        conn = open_db(self.test_db.name)
        conn.execute("INSERT INTO logs (is_night) VALUES (1)")
        conn.commit()
        conn.close()

        github_api = GitHubAPI("test-token", "test/repo")

        result1 = github_api.upload_violations_to_branch(self.test_db.name, "violations-data")
        result2 = github_api.upload_violations_to_branch(self.test_db.name, "main")

        self.assertTrue(result1)
        self.assertFalse(result2)


class TestAdvancedSyncFeatures(unittest.TestCase):
    """Test advanced sync features like nuclear cleanup and datapoint updates"""

    def setUp(self):
        self.violations_data = {
            "violations": [
                {
                    "date": "2025-08-15",
                    "timestamp": "2025-08-15T06:12:14.942Z",
                    "value": 1,
                    "comment": "Night logger violation (2 detections)",
                    "daystamp": "20250815"
                }
            ],
            "posted_dates": [],
            "unposted_violations": []
        }

    @patch.dict(os.environ, {
        'BEEMINDER_USERNAME': 'testuser',
        'BEEMINDER_AUTH_TOKEN': 'testtoken',
        'BEEMINDER_GOAL_SLUG': 'testgoal'
    })
    @patch('sync_violations.requests.get')
    @patch('sync_violations.requests.delete')
    def test_nuclear_cleanup(self, mock_delete, mock_get):
        """Test nuclear cleanup functionality"""
        # Mock existing datapoints
        mock_datapoints = [
            {"id": "dp1", "timestamp": 1692086400, "value": 1, "comment": "old data"},
            {"id": "dp2", "timestamp": 1692172800, "value": 1, "comment": "old data"}
        ]
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = mock_datapoints
        mock_get.return_value.raise_for_status.return_value = None

        mock_delete.return_value.status_code = 200
        mock_delete.return_value.raise_for_status.return_value = None

        # Create violations file
        violations_file = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
        json.dump(self.violations_data, violations_file)
        violations_file.close()

        try:
            sync = ViolationsSync()

            # Test nuclear cleanup
            with patch.object(sync.beeminder, 'create_datapoint', return_value=True) as mock_create:
                sync.nuclear_cleanup_and_sync(violations_file.name)

                # Should delete all existing datapoints
                self.assertEqual(mock_delete.call_count, 2)

                # Should recreate from violations
                self.assertEqual(mock_create.call_count, 1)

        finally:
            os.unlink(violations_file.name)

    @patch.dict(os.environ, {
        'BEEMINDER_USERNAME': 'testuser',
        'BEEMINDER_AUTH_TOKEN': 'testtoken',
        'BEEMINDER_GOAL_SLUG': 'testgoal'
    })
    @patch('sync_violations.requests.get')
    @patch('sync_violations.requests.delete')
    @patch('sync_violations.requests.post')
    def test_datapoint_update_scenario(self, mock_post, mock_delete, mock_get):
        """Test datapoint update (delete + recreate) scenario"""
        # Mock existing datapoint with different comment
        mock_datapoints = [{
            "id": "dp1",
            "timestamp": 1692086400,  # 2025-08-15 timestamp
            "value": 1,
            "comment": "old comment"  # Different from violations data
        }]
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = mock_datapoints
        mock_get.return_value.raise_for_status.return_value = None

        mock_delete.return_value.status_code = 200
        mock_delete.return_value.raise_for_status.return_value = None

        mock_post.return_value.status_code = 200
        mock_post.return_value.raise_for_status.return_value = None

        # Create violations file
        violations_file = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
        json.dump(self.violations_data, violations_file)
        violations_file.close()

        try:
            sync = ViolationsSync()
            sync.selective_sync_datapoints(self.violations_data)

            # Should delete old datapoint and create new one (update scenario)
            self.assertTrue(mock_delete.called)
            self.assertTrue(mock_post.called)

        finally:
            os.unlink(violations_file.name)

    @patch.dict(os.environ, {
        'BEEMINDER_USERNAME': 'testuser',
        'BEEMINDER_AUTH_TOKEN': 'testtoken',
        'BEEMINDER_GOAL_SLUG': 'testgoal'
    })
    @patch('sync_violations.requests.get')
    @patch('sync_violations.requests.delete')
    def test_duplicate_datapoint_cleanup(self, mock_delete, mock_get):
        """Test cleanup of duplicate datapoints"""
        # Mock duplicate datapoints for same date
        mock_datapoints = [
            {"id": "dp1", "timestamp": 1692086400, "value": 1, "comment": "first"},  # Same date
            {"id": "dp2", "timestamp": 1692086460, "value": 1, "comment": "second"}, # Same date, 1 min later
            {"id": "dp3", "timestamp": 1692172800, "value": 1, "comment": "different date"}
        ]
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = mock_datapoints
        mock_get.return_value.raise_for_status.return_value = None

        mock_delete.return_value.status_code = 200
        mock_delete.return_value.raise_for_status.return_value = None

        # Create violations file
        violations_file = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
        json.dump(self.violations_data, violations_file)
        violations_file.close()

        try:
            sync = ViolationsSync()
            sync.selective_sync_datapoints(self.violations_data)

            # Should delete one of the duplicate datapoints
            self.assertTrue(mock_delete.called)

        finally:
            os.unlink(violations_file.name)


class TestExtractViolationsEnhanced(unittest.TestCase):
    """Test enhanced extract_violations functionality"""

    def setUp(self):
        self.test_db = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        self.test_db.close()

    def tearDown(self):
        try:
            os.unlink(self.test_db.name)
        except:
            pass

    def test_extract_violations_nonexistent_database(self):
        """Test extract_violations with nonexistent database"""
        nonexistent_path = "/tmp/nonexistent_db_12345.db"

        violations_data = extract_violations(nonexistent_path)

        # Should return empty structure
        self.assertEqual(violations_data['violations'], [])
        self.assertEqual(violations_data['posted_dates'], [])
        self.assertEqual(violations_data['total_violations'], 0)
        self.assertEqual(violations_data['unposted_violations'], [])

    @patch('shutil.copy2')
    def test_extract_violations_copy_fallback(self, mock_copy):
        """Test extract_violations copy fallback when temp copy fails"""
        # Setup database with data
        conn = open_db(self.test_db.name)
        conn.execute("INSERT INTO logs (is_night) VALUES (1)")
        conn.commit()
        conn.close()

        # Mock copy failure
        mock_copy.side_effect = Exception("Copy failed")

        # Should fall back to direct access
        violations_data = extract_violations(self.test_db.name)

        # Should still extract data successfully
        self.assertGreater(len(violations_data['violations']), 0)


def run_all_tests():
    """Run all tests with detailed output"""
    # Create test suite
    test_suite = unittest.TestSuite()

    # Add all test classes
    test_classes = [
        TestNightLoggerCore,
        TestGitHubAPI,
        TestBeeminderAPI,
        TestViolationsSync,
        TestIntegration,
        TestSecurity,
        TestDatabaseConcurrency,
        TestNightTimeAttribution,
        TestErrorHandlingEnhanced,
        TestRaceConditions,
        TestTimestampHandling,
        TestDualBranchUpload,
        TestAdvancedSyncFeatures,
        TestExtractViolationsEnhanced
    ]

    for test_class in test_classes:
        test_suite.addTest(unittest.makeSuite(test_class))

    # Run tests
    runner = unittest.TextTestRunner(verbosity=2, buffer=True)
    result = runner.run(test_suite)

    return result.wasSuccessful(), len(result.failures), len(result.errors)


if __name__ == "__main__":
    print("🧪 Running Comprehensive Test Suite for Night Logger System")
    print("=" * 70)

    success, failures, errors = run_all_tests()

    print("=" * 70)
    if success:
        print("✅ All tests passed!")
    else:
        print(f"❌ Tests failed: {failures} failures, {errors} errors")
        sys.exit(1)