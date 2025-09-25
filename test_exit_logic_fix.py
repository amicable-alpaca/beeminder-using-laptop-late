#!/usr/bin/env python3
"""
Test Suite for Night Logger Exit Logic Fix

Tests the specific fix for premature exit behavior:
- Service should continue logging after successful upload
- Service should not exit immediately when night usage is detected
- Service should maintain one-violation-per-day guarantee
"""

import json
import os
import sqlite3
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock, call
import threading
import signal

# Add current directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import the fixed module
try:
    from night_logger_github_fixed import (
        main, GitHubAPI, is_between_23_and_359_local, local_ymd, open_db,
        already_posted_today, mark_posted_today, extract_violations
    )
except ImportError as e:
    print(f"Warning: Could not import fixed module: {e}")


class TestFixedExitLogic(unittest.TestCase):
    """Test the fixed exit logic behavior"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.test_db = Path(self.temp_dir) / "test_fixed.db"

    def tearDown(self):
        if self.test_db.exists():
            self.test_db.unlink()

    def test_continue_logging_after_upload_success(self):
        """Test that service continues logging after successful upload"""

        # Track function calls to verify behavior
        call_log = []

        # Mock GitHub API to simulate successful upload
        with patch('night_logger_github_fixed.GitHubAPI') as mock_github_class:
            mock_github = MagicMock()
            mock_github.upload_violations_to_branch.return_value = True
            mock_github.trigger_workflow.return_value = True
            mock_github_class.return_value = mock_github

            # Mock sys.exit to prevent actual exit
            with patch('night_logger_github_fixed.sys.exit') as mock_exit:

                # Mock datetime.now to simulate night time sequence
                test_times = [
                    datetime(2025, 9, 24, 23, 0, 0),   # First detection - should trigger upload
                    datetime(2025, 9, 24, 23, 0, 5),   # 5 seconds later - should continue logging
                    datetime(2025, 9, 24, 23, 0, 10),  # 10 seconds later - should continue logging
                    datetime(2025, 9, 24, 23, 0, 15),  # 15 seconds later - should continue logging
                ]

                with patch('night_logger_github_fixed.datetime') as mock_datetime:
                    mock_datetime.now.side_effect = test_times
                    mock_datetime.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)

                    # Mock time.sleep to avoid actual delays
                    with patch('night_logger_github_fixed.time.sleep') as mock_sleep:

                        # Mock environment variables
                        with patch.dict('os.environ', {
                            'GITHUB_TOKEN': 'test_token',
                            'GITHUB_REPO': 'test/repo'
                        }):

                            # Mock command line arguments
                            test_args = [
                                'night_logger_github_fixed.py',
                                '--db', str(self.test_db),
                                '--interval', '5',
                                '--verbose'
                            ]

                            with patch('sys.argv', test_args):

                                # Mock keyboard interrupt after a few iterations to end test
                                def interrupt_after_calls(*args, **kwargs):
                                    call_log.append('sleep_called')
                                    if len(call_log) >= 4:  # After 4 sleep calls, simulate interrupt
                                        raise KeyboardInterrupt("Test interrupt")

                                mock_sleep.side_effect = interrupt_after_calls

                                try:
                                    main()
                                except KeyboardInterrupt:
                                    pass  # Expected for test cleanup

                                # Verify behavior
                                # Should NOT have called sys.exit during night detection
                                mock_exit.assert_not_called()

                                # Should have uploaded violations
                                mock_github.upload_violations_to_branch.assert_called_once()
                                mock_github.trigger_workflow.assert_called_once()

                                # Should have continued logging (multiple sleep calls)
                                self.assertGreaterEqual(len(call_log), 4)

    def test_already_posted_continues_without_upload(self):
        """Test that service continues logging without re-uploading when already posted"""

        # Pre-populate database with posted date
        conn = open_db(str(self.test_db))
        mark_posted_today(conn, "2025-09-24")  # Mark as already posted
        conn.close()

        call_log = []

        with patch('night_logger_github_fixed.GitHubAPI') as mock_github_class:
            mock_github = MagicMock()
            mock_github_class.return_value = mock_github

            # Mock sys.exit to prevent actual exit
            with patch('night_logger_github_fixed.sys.exit') as mock_exit:

                # Mock datetime.now to simulate night time
                test_times = [
                    datetime(2025, 9, 24, 23, 0, 0),   # Night time - already posted
                    datetime(2025, 9, 24, 23, 0, 5),   # Continue logging
                    datetime(2025, 9, 24, 23, 0, 10),  # Continue logging
                ]

                with patch('night_logger_github_fixed.datetime') as mock_datetime:
                    mock_datetime.now.side_effect = test_times
                    mock_datetime.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)

                    with patch('night_logger_github_fixed.time.sleep') as mock_sleep:

                        def interrupt_after_calls(*args, **kwargs):
                            call_log.append('sleep_called')
                            if len(call_log) >= 3:
                                raise KeyboardInterrupt("Test interrupt")

                        mock_sleep.side_effect = interrupt_after_calls

                        test_args = [
                            'night_logger_github_fixed.py',
                            '--db', str(self.test_db),
                            '--interval', '5',
                            '--verbose'
                        ]

                        with patch('sys.argv', test_args):
                            try:
                                main()
                            except KeyboardInterrupt:
                                pass

                            # Should NOT have called sys.exit
                            mock_exit.assert_not_called()

                            # Should NOT have uploaded (already posted)
                            mock_github.upload_violations_to_branch.assert_not_called()
                            mock_github.trigger_workflow.assert_not_called()

                            # Should have continued logging
                            self.assertGreaterEqual(len(call_log), 3)

    def test_database_connection_reopen_after_upload(self):
        """Test that database connection is properly reopened after upload"""

        with patch('night_logger_github_fixed.GitHubAPI') as mock_github_class:
            mock_github = MagicMock()
            mock_github.upload_violations_to_branch.return_value = True
            mock_github.trigger_workflow.return_value = True
            mock_github_class.return_value = mock_github

            # Track database operations
            db_operations = []

            # Mock open_db to track calls
            original_open_db = open_db
            def track_open_db(path):
                db_operations.append(f'open_db({path})')
                return original_open_db(path)

            with patch('night_logger_github_fixed.open_db', side_effect=track_open_db):
                with patch('night_logger_github_fixed.sys.exit') as mock_exit:

                    test_times = [
                        datetime(2025, 9, 24, 23, 0, 0),   # First night detection
                        datetime(2025, 9, 24, 23, 0, 5),   # Continue logging
                    ]

                    with patch('night_logger_github_fixed.datetime') as mock_datetime:
                        mock_datetime.now.side_effect = test_times
                        mock_datetime.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)

                        with patch('night_logger_github_fixed.time.sleep') as mock_sleep:
                            mock_sleep.side_effect = [None, KeyboardInterrupt("Test end")]

                            with patch.dict('os.environ', {
                                'GITHUB_TOKEN': 'test_token',
                                'GITHUB_REPO': 'test/repo'
                            }):

                                test_args = [
                                    'night_logger_github_fixed.py',
                                    '--db', str(self.test_db),
                                    '--interval', '5'
                                ]

                                with patch('sys.argv', test_args):
                                    try:
                                        main()
                                    except KeyboardInterrupt:
                                        pass

                                    # Should have reopened database after upload
                                    # Initial open + temp connection for mark_posted + reopen for continued logging
                                    self.assertGreaterEqual(len(db_operations), 3)

                                    # Should NOT have called sys.exit
                                    mock_exit.assert_not_called()

    def test_one_violation_per_day_guarantee(self):
        """Test that one-violation-per-day guarantee is maintained"""

        upload_calls = []

        with patch('night_logger_github_fixed.GitHubAPI') as mock_github_class:
            mock_github = MagicMock()

            def track_upload(*args, **kwargs):
                upload_calls.append('upload_called')
                return True

            mock_github.upload_violations_to_branch.side_effect = track_upload
            mock_github.trigger_workflow.return_value = True
            mock_github_class.return_value = mock_github

            with patch('night_logger_github_fixed.sys.exit') as mock_exit:

                # Simulate multiple night detections on same day
                test_times = [
                    datetime(2025, 9, 24, 23, 0, 0),   # First detection - should upload
                    datetime(2025, 9, 24, 23, 0, 5),   # Second detection - should NOT upload
                    datetime(2025, 9, 24, 23, 0, 10),  # Third detection - should NOT upload
                    datetime(2025, 9, 24, 23, 0, 15),  # Fourth detection - should NOT upload
                ]

                with patch('night_logger_github_fixed.datetime') as mock_datetime:
                    mock_datetime.now.side_effect = test_times
                    mock_datetime.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)

                    call_count = 0
                    def limited_sleep(*args, **kwargs):
                        nonlocal call_count
                        call_count += 1
                        if call_count >= 4:
                            raise KeyboardInterrupt("Test end")

                    with patch('night_logger_github_fixed.time.sleep', side_effect=limited_sleep):
                        with patch.dict('os.environ', {
                            'GITHUB_TOKEN': 'test_token',
                            'GITHUB_REPO': 'test/repo'
                        }):

                            test_args = [
                                'night_logger_github_fixed.py',
                                '--db', str(self.test_db),
                                '--interval', '5'
                            ]

                            with patch('sys.argv', test_args):
                                try:
                                    main()
                                except KeyboardInterrupt:
                                    pass

                                # Should have uploaded only ONCE despite multiple night detections
                                self.assertEqual(len(upload_calls), 1)

                                # Should NOT have called sys.exit
                                mock_exit.assert_not_called()


class TestFixedBehaviorVsOriginal(unittest.TestCase):
    """Compare fixed behavior vs original broken behavior"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.test_db = Path(self.temp_dir) / "test_comparison.db"

    def tearDown(self):
        if self.test_db.exists():
            self.test_db.unlink()

    def test_original_vs_fixed_logging_count(self):
        """Test that fixed version logs more data points than original"""

        # Simulate what would happen with original (immediate exit) vs fixed (continue logging)

        # Original behavior: 1 log entry then exit
        original_log_count = 1

        # Fixed behavior: Multiple log entries before test interruption
        fixed_log_entries = []

        with patch('night_logger_github_fixed.GitHubAPI') as mock_github_class:
            mock_github = MagicMock()
            mock_github.upload_violations_to_branch.return_value = True
            mock_github.trigger_workflow.return_value = True
            mock_github_class.return_value = mock_github

            with patch('night_logger_github_fixed.sys.exit') as mock_exit:

                # Mock INSERT operations to track logging
                original_execute = None

                def track_inserts(self, sql, params=None):
                    if sql.startswith("INSERT INTO logs"):
                        fixed_log_entries.append(params)
                    return original_execute(sql, params) if params else original_execute(sql)

                # Night time for multiple detections
                test_times = [datetime(2025, 9, 24, 23, 0, min(i * 5, 59)) for i in range(10)]

                with patch('night_logger_github_fixed.datetime') as mock_datetime:
                    mock_datetime.now.side_effect = test_times
                    mock_datetime.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)

                    call_count = 0
                    def limited_sleep(*args, **kwargs):
                        nonlocal call_count
                        call_count += 1
                        if call_count >= 5:  # Stop after 5 iterations
                            raise KeyboardInterrupt("Test end")

                    with patch('night_logger_github_fixed.time.sleep', side_effect=limited_sleep):
                        with patch.dict('os.environ', {
                            'GITHUB_TOKEN': 'test_token',
                            'GITHUB_REPO': 'test/repo'
                        }):

                            test_args = [
                                'night_logger_github_fixed.py',
                                '--db', str(self.test_db),
                                '--interval', '5'
                            ]

                            with patch('sys.argv', test_args):
                                try:
                                    main()
                                except KeyboardInterrupt:
                                    pass

                                # Check database directly for logged entries
                                conn = open_db(str(self.test_db))
                                cursor = conn.execute("SELECT COUNT(*) FROM logs WHERE is_night = 1")
                                night_log_count = cursor.fetchone()[0]
                                conn.close()

                                # Fixed version should log more entries than original would
                                self.assertGreater(night_log_count, original_log_count)

                                # Should have multiple night time detections
                                self.assertGreaterEqual(night_log_count, 5)

    def test_service_lifetime_comparison(self):
        """Test that fixed service runs longer than original would"""

        service_lifetime_tracking = {
            'start_time': None,
            'end_time': None,
            'total_iterations': 0
        }

        with patch('night_logger_github_fixed.GitHubAPI') as mock_github_class:
            mock_github = MagicMock()
            mock_github.upload_violations_to_branch.return_value = True
            mock_github.trigger_workflow.return_value = True
            mock_github_class.return_value = mock_github

            with patch('night_logger_github_fixed.sys.exit') as mock_exit:

                # Track service lifetime
                def track_iterations(*args, **kwargs):
                    if service_lifetime_tracking['start_time'] is None:
                        service_lifetime_tracking['start_time'] = time.time()

                    service_lifetime_tracking['total_iterations'] += 1

                    # End test after reasonable number of iterations
                    if service_lifetime_tracking['total_iterations'] >= 10:
                        service_lifetime_tracking['end_time'] = time.time()
                        raise KeyboardInterrupt("Test end")

                # Night time sequence
                test_times = [datetime(2025, 9, 24, 23, i // 12, (i * 5) % 60) for i in range(15)]

                with patch('night_logger_github_fixed.datetime') as mock_datetime:
                    mock_datetime.now.side_effect = test_times
                    mock_datetime.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)

                    with patch('night_logger_github_fixed.time.sleep', side_effect=track_iterations):
                        with patch.dict('os.environ', {
                            'GITHUB_TOKEN': 'test_token',
                            'GITHUB_REPO': 'test/repo'
                        }):

                            test_args = [
                                'night_logger_github_fixed.py',
                                '--db', str(self.test_db),
                                '--interval', '5'
                            ]

                            with patch('sys.argv', test_args):
                                try:
                                    main()
                                except KeyboardInterrupt:
                                    pass

                                # Fixed version should complete many iterations (original would exit after 1)
                                self.assertGreaterEqual(service_lifetime_tracking['total_iterations'], 10)

                                # Should NOT have called sys.exit during night detection
                                mock_exit.assert_not_called()


def run_exit_logic_tests():
    """Run all exit logic fix tests"""
    test_suite = unittest.TestSuite()

    test_classes = [
        TestFixedExitLogic,
        TestFixedBehaviorVsOriginal
    ]

    for test_class in test_classes:
        test_suite.addTest(unittest.makeSuite(test_class))

    runner = unittest.TextTestRunner(verbosity=2, buffer=True)
    result = runner.run(test_suite)

    return result.wasSuccessful(), len(result.failures), len(result.errors)


if __name__ == "__main__":
    print("🧪 Running Exit Logic Fix Test Suite")
    print("=" * 50)

    success, failures, errors = run_exit_logic_tests()

    print("=" * 50)
    if success:
        print("✅ All exit logic fix tests passed!")
    else:
        print(f"❌ Tests failed: {failures} failures, {errors} errors")
        sys.exit(1)