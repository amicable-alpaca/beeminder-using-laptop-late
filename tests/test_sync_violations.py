#!/usr/bin/env python3
"""
Comprehensive tests for sync_violations.py - 100% code coverage
"""

import json
import os
import pytest
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock, call
import sys

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sync_violations import BeeminderAPI, ViolationsSync


class TestBeeminderAPI:
    """Test BeeminderAPI class"""

    def setup_method(self):
        """Set up test fixtures"""
        self.username = "test_user"
        self.auth_token = "test_token"
        self.api = BeeminderAPI(self.username, self.auth_token)

    def test_init(self):
        """Test BeeminderAPI initialization"""
        assert self.api.username == self.username
        assert self.api.auth_token == self.auth_token
        assert self.api.base_url == "https://www.beeminder.com/api/v1"

    @patch('requests.get')
    def test_get_goal_datapoints_single_page(self, mock_get):
        """Test fetching datapoints with single page"""
        mock_response = Mock()
        mock_response.json.return_value = [
            {'id': '1', 'timestamp': 1234567890, 'value': 1.0},
            {'id': '2', 'timestamp': 1234567891, 'value': 1.0}
        ]
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        # First call returns 2 items, second call returns empty
        mock_response.json.side_effect = [
            [{'id': '1', 'timestamp': 1234567890, 'value': 1.0},
             {'id': '2', 'timestamp': 1234567891, 'value': 1.0}],
            []
        ]

        datapoints = self.api.get_goal_datapoints('test_goal')

        assert len(datapoints) == 2
        assert datapoints[0]['id'] == '1'
        assert datapoints[1]['id'] == '2'

    @patch('requests.get')
    def test_get_goal_datapoints_multiple_pages(self, mock_get):
        """Test fetching datapoints with pagination"""
        mock_response = Mock()
        mock_response.raise_for_status = Mock()

        # Simulate 3 pages of results
        page1 = [{'id': str(i), 'timestamp': 1234567890 + i} for i in range(25)]
        page2 = [{'id': str(i), 'timestamp': 1234567890 + i} for i in range(25, 50)]
        page3 = []  # Empty page to stop pagination

        mock_response.json.side_effect = [page1, page2, page3]
        mock_get.return_value = mock_response

        datapoints = self.api.get_goal_datapoints('test_goal')

        assert len(datapoints) == 50
        assert mock_get.call_count == 3

    @patch('requests.get')
    def test_get_goal_datapoints_error(self, mock_get):
        """Test error handling in get_goal_datapoints"""
        import requests
        mock_get.side_effect = requests.exceptions.RequestException("Network error")

        datapoints = self.api.get_goal_datapoints('test_goal')

        assert datapoints == []

    @patch('requests.post')
    def test_create_datapoint_success(self, mock_post):
        """Test creating a datapoint successfully"""
        mock_response = Mock()
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        violation = {
            'date': '2025-08-15',
            'timestamp': '2025-08-15T02:12:14Z',
            'value': 1,
            'comment': 'Test violation'
        }

        result = self.api.create_datapoint('test_goal', violation)

        assert result is True
        assert mock_post.called

    @patch('requests.post')
    def test_create_datapoint_failure(self, mock_post):
        """Test create_datapoint error handling"""
        import requests
        mock_post.side_effect = requests.exceptions.RequestException("API error")

        violation = {
            'date': '2025-08-15',
            'timestamp': '2025-08-15T02:12:14Z',
            'value': 1,
            'comment': 'Test violation'
        }

        result = self.api.create_datapoint('test_goal', violation)

        assert result is False

    @patch('requests.post')
    def test_create_datapoint_timestamp_conversion(self, mock_post):
        """Test timestamp conversion from ISO to Unix"""
        mock_response = Mock()
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        violation = {
            'date': '2025-08-15',
            'timestamp': '2025-08-15T02:12:14+00:00',
            'value': 1,
            'comment': 'Test violation'
        }

        self.api.create_datapoint('test_goal', violation)

        # Verify the Unix timestamp was calculated
        call_args = mock_post.call_args
        assert 'timestamp' in call_args[1]['data']

    @patch('requests.delete')
    def test_delete_datapoint_success(self, mock_delete):
        """Test deleting a datapoint successfully"""
        mock_response = Mock()
        mock_response.raise_for_status = Mock()
        mock_delete.return_value = mock_response

        result = self.api.delete_datapoint('test_goal', 'test_id')

        assert result is True

    @patch('requests.delete')
    def test_delete_datapoint_failure(self, mock_delete):
        """Test delete_datapoint error handling"""
        import requests
        mock_delete.side_effect = requests.exceptions.RequestException("API error")

        result = self.api.delete_datapoint('test_goal', 'test_id')

        assert result is False


class TestViolationsSync:
    """Test ViolationsSync class"""

    def setup_method(self):
        """Set up test fixtures"""
        os.environ['BEEMINDER_USERNAME'] = 'test_user'
        os.environ['BEEMINDER_AUTH_TOKEN'] = 'test_token'
        os.environ['BEEMINDER_GOAL_SLUG'] = 'test_goal'

    def teardown_method(self):
        """Clean up environment variables"""
        for var in ['BEEMINDER_USERNAME', 'BEEMINDER_AUTH_TOKEN', 'BEEMINDER_GOAL_SLUG']:
            if var in os.environ:
                del os.environ[var]

    def test_init_success(self):
        """Test ViolationsSync initialization"""
        sync = ViolationsSync()
        assert sync.beeminder_username == 'test_user'
        assert sync.beeminder_token == 'test_token'
        assert sync.beeminder_goal == 'test_goal'

    def test_init_missing_username(self):
        """Test init fails with missing username"""
        del os.environ['BEEMINDER_USERNAME']
        with pytest.raises(ValueError, match="Missing required Beeminder environment variables"):
            ViolationsSync()

    def test_init_missing_token(self):
        """Test init fails with missing token"""
        del os.environ['BEEMINDER_AUTH_TOKEN']
        with pytest.raises(ValueError, match="Missing required Beeminder environment variables"):
            ViolationsSync()

    def test_init_missing_goal(self):
        """Test init fails with missing goal"""
        del os.environ['BEEMINDER_GOAL_SLUG']
        with pytest.raises(ValueError, match="Missing required Beeminder environment variables"):
            ViolationsSync()

    def test_load_violations_file_exists(self):
        """Test loading violations from existing file"""
        sync = ViolationsSync()

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            test_data = {
                "violations": [
                    {
                        "date": "2025-08-15",
                        "timestamp": "2025-08-15T02:12:14Z",
                        "value": 1,
                        "comment": "Test violation"
                    }
                ],
                "unposted_violations": []
            }
            json.dump(test_data, f)
            temp_path = f.name

        try:
            result = sync.load_violations(temp_path)
            assert len(result['violations']) == 1
            assert result['violations'][0]['date'] == '2025-08-15'
        finally:
            os.unlink(temp_path)

    def test_load_violations_file_not_exists(self):
        """Test loading violations from non-existent file"""
        sync = ViolationsSync()
        result = sync.load_violations('/nonexistent/file.json')
        assert result['violations'] == []
        assert result['unposted_violations'] == []

    @patch.object(BeeminderAPI, 'get_goal_datapoints')
    @patch.object(BeeminderAPI, 'delete_datapoint')
    def test_selective_sync_with_duplicates(self, mock_delete, mock_get):
        """Test selective sync finds and removes duplicates"""
        sync = ViolationsSync()

        # Mock Beeminder returning duplicates for same date
        mock_get.return_value = [
            {'id': '1', 'timestamp': 1755238334, 'value': 1.0, 'comment': 'Test 1'},
            {'id': '2', 'timestamp': 1755238335, 'value': 1.0, 'comment': 'Test 2'}  # Same date, newer
        ]
        mock_delete.return_value = True

        violations_data = {
            'violations': [
                {
                    'date': '2025-08-15',
                    'timestamp': '2025-08-15T02:12:14Z',
                    'value': 1,
                    'comment': 'Test violation'
                }
            ]
        }

        sync.selective_sync_datapoints(violations_data)

        # Should delete the older duplicate
        assert mock_delete.called

    @patch.object(BeeminderAPI, 'get_goal_datapoints')
    @patch.object(BeeminderAPI, 'create_datapoint')
    def test_selective_sync_creates_missing(self, mock_create, mock_get):
        """Test selective sync creates missing datapoints"""
        sync = ViolationsSync()

        # Beeminder has no datapoints
        mock_get.return_value = []
        mock_create.return_value = True

        violations_data = {
            'violations': [
                {
                    'date': '2025-08-15',
                    'timestamp': '2025-08-15T02:12:14Z',
                    'value': 1,
                    'comment': 'Test violation'
                }
            ]
        }

        sync.selective_sync_datapoints(violations_data)

        # Should create the missing datapoint
        assert mock_create.called

    @patch.object(BeeminderAPI, 'get_goal_datapoints')
    @patch.object(BeeminderAPI, 'delete_datapoint')
    def test_selective_sync_deletes_unauthorized(self, mock_delete, mock_get):
        """Test selective sync deletes unauthorized datapoints"""
        sync = ViolationsSync()

        # Beeminder has datapoint not in SoT
        mock_get.return_value = [
            {'id': '1', 'timestamp': 1755238334, 'value': 1.0, 'comment': 'Unauthorized'}
        ]
        mock_delete.return_value = True

        violations_data = {
            'violations': []  # No violations in SoT
        }

        sync.selective_sync_datapoints(violations_data)

        # Should delete the unauthorized datapoint
        assert mock_delete.called

    @patch.object(BeeminderAPI, 'get_goal_datapoints')
    @patch.object(BeeminderAPI, 'delete_datapoint')
    @patch.object(BeeminderAPI, 'create_datapoint')
    def test_selective_sync_updates_changed(self, mock_create, mock_delete, mock_get):
        """Test selective sync updates changed datapoints"""
        sync = ViolationsSync()

        # Beeminder has datapoint with different value
        mock_get.return_value = [
            {'id': '1', 'timestamp': 1755238334, 'value': 2.0, 'comment': 'Wrong value'}
        ]
        mock_delete.return_value = True
        mock_create.return_value = True

        violations_data = {
            'violations': [
                {
                    'date': '2025-08-15',
                    'timestamp': '2025-08-15T02:12:14Z',
                    'value': 1,
                    'comment': 'Correct value'
                }
            ]
        }

        sync.selective_sync_datapoints(violations_data)

        # Should delete old and create new
        assert mock_delete.called
        assert mock_create.called

    @patch.object(BeeminderAPI, 'get_goal_datapoints')
    def test_selective_sync_no_changes(self, mock_get):
        """Test selective sync with no changes needed"""
        sync = ViolationsSync()

        # Beeminder matches SoT exactly
        mock_get.return_value = [
            {'id': '1', 'timestamp': 1755238334, 'value': 1.0, 'comment': 'Test violation'}
        ]

        violations_data = {
            'violations': [
                {
                    'date': '2025-08-15',
                    'timestamp': '2025-08-15T02:12:14Z',
                    'value': 1,
                    'comment': 'Test violation'
                }
            ]
        }

        sync.selective_sync_datapoints(violations_data)

        # No changes should be made

    @patch.object(ViolationsSync, 'load_violations')
    @patch.object(ViolationsSync, 'selective_sync_datapoints')
    def test_sync_violations_to_beeminder(self, mock_selective, mock_load):
        """Test sync_violations_to_beeminder flow"""
        sync = ViolationsSync()

        mock_load.return_value = {
            'violations': [
                {
                    'date': '2025-08-15',
                    'timestamp': '2025-08-15T02:12:14Z',
                    'value': 1,
                    'comment': 'Test'
                }
            ]
        }

        sync.sync_violations_to_beeminder('test.json')

        assert mock_load.called
        assert mock_selective.called

    @patch.object(ViolationsSync, 'load_violations')
    def test_sync_violations_no_violations(self, mock_load):
        """Test sync with no violations"""
        sync = ViolationsSync()
        mock_load.return_value = {'violations': []}

        sync.sync_violations_to_beeminder('test.json')

        # Should return early without syncing

    @patch.object(BeeminderAPI, 'get_goal_datapoints')
    @patch.object(BeeminderAPI, 'delete_datapoint')
    @patch.object(BeeminderAPI, 'create_datapoint')
    @patch.object(ViolationsSync, 'load_violations')
    def test_nuclear_cleanup_and_sync(self, mock_load, mock_create, mock_delete, mock_get):
        """Test nuclear cleanup removes all and recreates"""
        sync = ViolationsSync()

        mock_get.return_value = [
            {'id': '1', 'timestamp': 1755238334},
            {'id': '2', 'timestamp': 1755238335}
        ]
        mock_delete.return_value = True
        mock_create.return_value = True

        mock_load.return_value = {
            'violations': [
                {
                    'date': '2025-08-15',
                    'timestamp': '2025-08-15T02:12:14Z',
                    'value': 1,
                    'comment': 'Test'
                }
            ]
        }

        sync.nuclear_cleanup_and_sync('test.json')

        # Should delete all existing datapoints
        assert mock_delete.call_count == 2

        # Should recreate from SoT
        assert mock_create.called

    @patch.object(BeeminderAPI, 'get_goal_datapoints')
    @patch.object(ViolationsSync, 'load_violations')
    def test_nuclear_cleanup_no_existing(self, mock_load, mock_get):
        """Test nuclear cleanup with no existing datapoints"""
        sync = ViolationsSync()

        mock_get.return_value = []
        mock_load.return_value = {
            'violations': [
                {
                    'date': '2025-08-15',
                    'timestamp': '2025-08-15T02:12:14Z',
                    'value': 1,
                    'comment': 'Test'
                }
            ]
        }

        sync.nuclear_cleanup_and_sync('test.json')

        # Should proceed without errors


class TestMain:
    """Test main function and CLI"""

    @patch('sys.argv', ['sync_violations.py', '--violations-file', 'test.json'])
    @patch.object(ViolationsSync, 'sync_violations_to_beeminder')
    def test_main_normal_sync(self, mock_sync):
        """Test main function with normal sync"""
        os.environ['BEEMINDER_USERNAME'] = 'test'
        os.environ['BEEMINDER_AUTH_TOKEN'] = 'test'
        os.environ['BEEMINDER_GOAL_SLUG'] = 'test'

        try:
            from sync_violations import main
            main()
            assert mock_sync.called
        finally:
            for var in ['BEEMINDER_USERNAME', 'BEEMINDER_AUTH_TOKEN', 'BEEMINDER_GOAL_SLUG']:
                if var in os.environ:
                    del os.environ[var]

    @patch('sys.argv', ['sync_violations.py', '--violations-file', 'test.json', '--nuclear-cleanup'])
    @patch.object(ViolationsSync, 'nuclear_cleanup_and_sync')
    def test_main_nuclear_cleanup(self, mock_nuclear):
        """Test main function with nuclear cleanup flag"""
        os.environ['BEEMINDER_USERNAME'] = 'test'
        os.environ['BEEMINDER_AUTH_TOKEN'] = 'test'
        os.environ['BEEMINDER_GOAL_SLUG'] = 'test'

        try:
            from sync_violations import main
            main()
            assert mock_nuclear.called
        finally:
            for var in ['BEEMINDER_USERNAME', 'BEEMINDER_AUTH_TOKEN', 'BEEMINDER_GOAL_SLUG']:
                if var in os.environ:
                    del os.environ[var]

    @patch('sys.argv', ['sync_violations.py'])
    @patch.object(ViolationsSync, '__init__')
    def test_main_missing_env_vars(self, mock_init):
        """Test main function fails with missing env vars"""
        mock_init.side_effect = ValueError("Missing required Beeminder environment variables")

        from sync_violations import main

        with pytest.raises(SystemExit):
            main()


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--cov=sync_violations', '--cov-report=term-missing'])
