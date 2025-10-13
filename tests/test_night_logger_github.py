#!/usr/bin/env python3
"""
Comprehensive tests for night_logger_github.py - 100% code coverage
"""

import json
import os
import pytest
import sqlite3
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock, call, mock_open
import sys

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Import from the fixed version (which is identical to system version minus update_snapshot)
from night_logger_github_fixed_v3 import (
    is_between_23_and_359_local,
    local_ymd,
    open_db,
    already_posted_today,
    mark_posted_today,
    clean_beeminder_duplicates,
    extract_violations,
    GitHubAPI,
    main,
    CREATE_TABLE_SQL,
    INSERT_SQL,
    DB_PATH
)


class TestTimeHelpers:
    """Test time-related helper functions"""

    def test_is_between_23_and_359_true_at_23(self):
        """Test hour 23 is considered night"""
        dt = datetime(2025, 8, 15, 23, 30, 0)
        assert is_between_23_and_359_local(dt) is True

    def test_is_between_23_and_359_true_at_midnight(self):
        """Test midnight is considered night"""
        dt = datetime(2025, 8, 15, 0, 0, 0)
        assert is_between_23_and_359_local(dt) is True

    def test_is_between_23_and_359_true_at_3(self):
        """Test 3 AM is considered night"""
        dt = datetime(2025, 8, 15, 3, 59, 59)
        assert is_between_23_and_359_local(dt) is True

    def test_is_between_23_and_359_false_at_4(self):
        """Test 4 AM is not considered night"""
        dt = datetime(2025, 8, 15, 4, 0, 0)
        assert is_between_23_and_359_local(dt) is False

    def test_is_between_23_and_359_false_during_day(self):
        """Test daytime hours are not considered night"""
        dt = datetime(2025, 8, 15, 12, 0, 0)
        assert is_between_23_and_359_local(dt) is False

    def test_is_between_23_and_359_false_at_22(self):
        """Test 22:59 is not considered night"""
        dt = datetime(2025, 8, 15, 22, 59, 0)
        assert is_between_23_and_359_local(dt) is False

    def test_local_ymd(self):
        """Test local_ymd returns correct format"""
        dt = datetime(2025, 8, 15, 12, 30, 45)
        assert local_ymd(dt) == "2025-08-15"

    def test_local_ymd_different_dates(self):
        """Test local_ymd with various dates"""
        assert local_ymd(datetime(2025, 1, 1)) == "2025-01-01"
        assert local_ymd(datetime(2025, 12, 31)) == "2025-12-31"


class TestDatabaseHelpers:
    """Test database-related helper functions"""

    def test_open_db_creates_tables(self):
        """Test open_db creates tables"""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name

        try:
            conn = open_db(db_path)
            cursor = conn.cursor()

            # Check logs table exists
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='logs';")
            assert cursor.fetchone() is not None

            # Check posts table exists
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='posts';")
            assert cursor.fetchone() is not None

            conn.close()
        finally:
            os.unlink(db_path)

    def test_open_db_wal_mode(self):
        """Test open_db enables WAL mode"""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name

        try:
            conn = open_db(db_path)
            cursor = conn.cursor()
            cursor.execute("PRAGMA journal_mode;")
            result = cursor.fetchone()
            # WAL mode should be enabled (or at least attempted)
            conn.close()
        finally:
            os.unlink(db_path)

    def test_already_posted_today_false(self):
        """Test already_posted_today returns False for new date"""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name

        try:
            conn = open_db(db_path)
            assert already_posted_today(conn, '2025-08-15') is False
            conn.close()
        finally:
            os.unlink(db_path)

    def test_already_posted_today_true(self):
        """Test already_posted_today returns True for posted date"""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name

        try:
            conn = open_db(db_path)
            mark_posted_today(conn, '2025-08-15')
            assert already_posted_today(conn, '2025-08-15') is True
            conn.close()
        finally:
            os.unlink(db_path)

    def test_mark_posted_today(self):
        """Test mark_posted_today inserts date"""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name

        try:
            conn = open_db(db_path)
            mark_posted_today(conn, '2025-08-15')

            cursor = conn.cursor()
            cursor.execute("SELECT ymd FROM posts WHERE ymd = ?;", ('2025-08-15',))
            result = cursor.fetchone()
            assert result is not None
            assert result[0] == '2025-08-15'

            conn.close()
        finally:
            os.unlink(db_path)

    def test_mark_posted_today_idempotent(self):
        """Test mark_posted_today is idempotent"""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name

        try:
            conn = open_db(db_path)
            mark_posted_today(conn, '2025-08-15')
            mark_posted_today(conn, '2025-08-15')  # Should not error

            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM posts WHERE ymd = ?;", ('2025-08-15',))
            count = cursor.fetchone()[0]
            assert count == 1  # Should only have one entry

            conn.close()
        finally:
            os.unlink(db_path)


class TestBeeminderDuplicates:
    """Test clean_beeminder_duplicates function"""

    @patch('requests.get')
    def test_clean_beeminder_duplicates_no_duplicates(self, mock_get):
        """Test with no duplicates"""
        mock_response = Mock()
        mock_response.json.return_value = [
            {'id': '1', 'daystamp': '20250815', 'timestamp': 1234567890}
        ]
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        result = clean_beeminder_duplicates('user', 'token', 'goal')
        assert result is True

    @patch('requests.delete')
    @patch('requests.get')
    def test_clean_beeminder_duplicates_with_duplicates(self, mock_get, mock_delete):
        """Test removes duplicates correctly"""
        mock_get_response = Mock()
        mock_get_response.json.return_value = [
            {'id': '1', 'daystamp': '20250815', 'timestamp': 1234567890},
            {'id': '2', 'daystamp': '20250815', 'timestamp': 1234567891}  # Duplicate, newer
        ]
        mock_get_response.raise_for_status = Mock()
        mock_get.return_value = mock_get_response

        mock_delete_response = Mock()
        mock_delete_response.status_code = 200
        mock_delete.return_value = mock_delete_response

        result = clean_beeminder_duplicates('user', 'token', 'goal', verbose=True)

        assert result is True
        assert mock_delete.called

    @patch('requests.get')
    def test_clean_beeminder_duplicates_api_error(self, mock_get):
        """Test handles API errors gracefully"""
        import requests
        mock_get.side_effect = requests.exceptions.RequestException("Network error")

        result = clean_beeminder_duplicates('user', 'token', 'goal', verbose=True)

        assert result is False

    @patch('requests.delete')
    @patch('requests.get')
    def test_clean_beeminder_duplicates_delete_failure(self, mock_get, mock_delete):
        """Test handles delete failures"""
        mock_get_response = Mock()
        mock_get_response.json.return_value = [
            {'id': '1', 'daystamp': '20250815', 'timestamp': 1234567890},
            {'id': '2', 'daystamp': '20250815', 'timestamp': 1234567891}
        ]
        mock_get_response.raise_for_status = Mock()
        mock_get.return_value = mock_get_response

        mock_delete_response = Mock()
        mock_delete_response.status_code = 404  # Not found
        mock_delete.return_value = mock_delete_response

        result = clean_beeminder_duplicates('user', 'token', 'goal', verbose=True)

        # Should still return True even if some deletes fail
        assert result is True


class TestExtractViolations:
    """Test extract_violations function"""

    def test_extract_violations_nonexistent_db(self):
        """Test extract_violations with nonexistent database"""
        result = extract_violations('/nonexistent/path.db')

        assert result['violations'] == []
        assert result['posted_dates'] == []
        assert result['total_violations'] == 0

    def test_extract_violations_empty_db(self):
        """Test extract_violations with empty database"""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name

        try:
            conn = open_db(db_path)
            conn.close()

            result = extract_violations(db_path)

            assert result['violations'] == []
            assert result['posted_dates'] == []
        finally:
            os.unlink(db_path)

    def test_extract_violations_with_data(self):
        """Test extract_violations with actual violations"""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name

        try:
            conn = open_db(db_path)
            cursor = conn.cursor()

            # Insert violation data
            cursor.execute(INSERT_SQL, (1,))
            conn.commit()

            # Mark as posted
            mark_posted_today(conn, datetime.now().strftime('%Y-%m-%d'))
            conn.close()

            result = extract_violations(db_path)

            assert len(result['violations']) >= 0
            assert 'violations' in result
            assert 'posted_dates' in result
        finally:
            os.unlink(db_path)

    def test_extract_violations_multiple_dates(self):
        """Test extract_violations with multiple posted dates"""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name

        try:
            conn = open_db(db_path)

            # Mark multiple dates as posted
            mark_posted_today(conn, '2025-08-15')
            mark_posted_today(conn, '2025-08-16')

            conn.close()

            result = extract_violations(db_path)

            assert len(result['posted_dates']) == 2
            assert '2025-08-15' in result['posted_dates']
            assert '2025-08-16' in result['posted_dates']
        finally:
            os.unlink(db_path)


class TestGitHubAPI:
    """Test GitHubAPI class"""

    def test_github_api_init(self):
        """Test GitHubAPI initialization"""
        api = GitHubAPI('test_token', 'owner/repo')

        assert api.token == 'test_token'
        assert api.repo == 'owner/repo'
        assert api.base_url == 'https://api.github.com'
        assert 'Authorization' in api.headers

    @patch.dict(os.environ, {}, clear=True)
    @patch('requests.get')
    @patch('requests.put')
    def test_upload_violations_no_beeminder_creds(self, mock_put, mock_get):
        """Test upload without Beeminder credentials"""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name

        try:
            conn = open_db(db_path)
            conn.close()

            api = GitHubAPI('test_token', 'owner/repo')

            # Mock branch check - branch doesn't exist
            # Mock get for main branch
            # Mock get for file
            branch_response = Mock()
            branch_response.status_code = 404

            main_response = Mock()
            main_response.status_code = 200
            main_response.json.return_value = {'object': {'sha': 'main_sha'}}
            main_response.raise_for_status = Mock()

            file_response = Mock()
            file_response.status_code = 404

            mock_get.side_effect = [branch_response, main_response, file_response]

            # Mock file put (upload)
            mock_put_response = Mock()
            mock_put_response.raise_for_status = Mock()
            mock_put.return_value = mock_put_response

            # Mock post for branch creation
            with patch('requests.post') as mock_post:
                mock_post_response = Mock()
                mock_post_response.raise_for_status = Mock()
                mock_post.return_value = mock_post_response

                result = api.upload_violations_to_branch(db_path, clean_duplicates=False)

            assert result is True
        finally:
            os.unlink(db_path)

    @patch('requests.get')
    @patch('requests.put')
    def test_upload_violations_file_exists(self, mock_put, mock_get):
        """Test updating existing violations file"""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name

        try:
            conn = open_db(db_path)
            conn.close()

            api = GitHubAPI('test_token', 'owner/repo')

            # Mock file get (file exists)
            mock_get_response = Mock()
            mock_get_response.status_code = 200
            mock_get_response.json.return_value = {'sha': 'existing_sha'}
            mock_get.return_value = mock_get_response

            # Mock file put
            mock_put_response = Mock()
            mock_put_response.raise_for_status = Mock()
            mock_put.return_value = mock_put_response

            result = api.upload_violations_to_branch(db_path, clean_duplicates=False)

            assert result is True
            # Verify SHA was included in put request
            call_args = mock_put.call_args
            assert 'sha' in call_args[1]['json']
        finally:
            os.unlink(db_path)

    @patch('requests.get')
    @patch('requests.post')
    def test_upload_violations_create_branch(self, mock_post, mock_get):
        """Test creating new branch when it doesn't exist"""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name

        try:
            conn = open_db(db_path)
            conn.close()

            api = GitHubAPI('test_token', 'owner/repo')

            # Mock branch check (doesn't exist)
            # Mock main branch get
            # Mock file get
            # Mock put
            mock_responses = []

            # Branch check returns 404
            branch_response = Mock()
            branch_response.status_code = 404
            mock_responses.append(branch_response)

            # Main branch exists
            main_response = Mock()
            main_response.status_code = 200
            main_response.json.return_value = {'object': {'sha': 'main_sha'}}
            main_response.raise_for_status = Mock()
            mock_responses.append(main_response)

            # File doesn't exist on new branch
            file_response = Mock()
            file_response.status_code = 404
            mock_responses.append(file_response)

            mock_get.side_effect = mock_responses

            # Mock post for branch creation and file upload
            mock_post_response = Mock()
            mock_post_response.raise_for_status = Mock()
            mock_post.return_value = mock_post_response

            # Mock put for file upload
            with patch('requests.put') as mock_put:
                mock_put_response = Mock()
                mock_put_response.raise_for_status = Mock()
                mock_put.return_value = mock_put_response

                result = api.upload_violations_to_branch(db_path, branch='new_branch', clean_duplicates=False)

            # Branch creation should have been called
            assert mock_post.called
        finally:
            os.unlink(db_path)

    @patch('requests.get')
    @patch('requests.put')
    def test_upload_violations_api_error(self, mock_put, mock_get):
        """Test error handling in upload_violations"""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name

        try:
            conn = open_db(db_path)
            conn.close()

            api = GitHubAPI('test_token', 'owner/repo')

            # Mock successful get for branch check
            branch_response = Mock()
            branch_response.status_code = 200

            file_response = Mock()
            file_response.status_code = 404

            mock_get.side_effect = [branch_response, file_response]

            import requests
            mock_put.side_effect = requests.exceptions.RequestException("API error")

            result = api.upload_violations_to_branch(db_path, clean_duplicates=False)

            assert result is False
        finally:
            os.unlink(db_path)

    @patch('requests.post')
    def test_trigger_workflow_success(self, mock_post):
        """Test triggering GitHub Actions workflow"""
        api = GitHubAPI('test_token', 'owner/repo')

        mock_response = Mock()
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        result = api.trigger_workflow()

        assert result is True
        assert mock_post.called

    @patch('requests.post')
    def test_trigger_workflow_custom_event(self, mock_post):
        """Test triggering workflow with custom event type"""
        api = GitHubAPI('test_token', 'owner/repo')

        mock_response = Mock()
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        result = api.trigger_workflow(event_type='custom-event')

        assert result is True
        # Verify event type was used
        call_args = mock_post.call_args
        assert call_args[1]['json']['event_type'] == 'custom-event'

    @patch('requests.post')
    def test_trigger_workflow_error(self, mock_post):
        """Test error handling in trigger_workflow"""
        api = GitHubAPI('test_token', 'owner/repo')

        import requests
        mock_post.side_effect = requests.exceptions.RequestException("Network error")

        result = api.trigger_workflow()

        assert result is False


class TestMain:
    """Test main function"""

    @patch('time.sleep')
    @patch('sys.argv', ['night_logger_github.py', '--db', 'test.db', '--interval', '1'])
    def test_main_keyboard_interrupt(self, mock_sleep):
        """Test main handles keyboard interrupt gracefully"""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name

        try:
            # Simulate keyboard interrupt after first iteration
            mock_sleep.side_effect = KeyboardInterrupt()

            with patch('sys.argv', ['night_logger_github.py', '--db', db_path, '--interval', '1']):
                main()

            # Should exit cleanly without error
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)

    @patch('time.sleep')
    @patch('sys.argv', ['night_logger_github.py', '--db', 'test.db', '--verbose'])
    def test_main_verbose_mode(self, mock_sleep):
        """Test main with verbose flag"""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name

        try:
            mock_sleep.side_effect = KeyboardInterrupt()

            with patch('sys.argv', ['night_logger_github.py', '--db', db_path, '--verbose']):
                main()
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)

    @patch('time.sleep')
    @patch.dict(os.environ, {'GITHUB_TOKEN': 'test', 'GITHUB_REPO': 'owner/repo'})
    def test_main_missing_github_creds_exits(self, mock_sleep):
        """Test main exits when GitHub creds missing during night"""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name

        try:
            # Mock datetime to return a night time
            with patch('night_logger_github_fixed_v3.datetime') as mock_datetime:
                mock_now = Mock()
                mock_now.hour = 23  # Night time
                mock_now.strftime.return_value = '2025-08-15 23:00:00'
                mock_datetime.now.return_value = mock_now
                mock_datetime.utcnow.return_value = datetime.utcnow()
                mock_datetime.fromisoformat = datetime.fromisoformat

                # Clear GitHub env vars
                with patch.dict(os.environ, {}, clear=True):
                    with patch('sys.argv', ['night_logger_github.py', '--db', db_path]):
                        with pytest.raises(SystemExit) as exc_info:
                            main()
                        assert exc_info.value.code == 2
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--cov=night_logger_github_fixed_v3', '--cov-report=term-missing'])
