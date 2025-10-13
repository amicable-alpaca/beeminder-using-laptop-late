# Test Suite Documentation

## Overview

This repository now has comprehensive test coverage for all Python code, ensuring reliability and correctness.

## Test Statistics

- **Total Tests**: 60
- **Test Files**: 2
  - `tests/test_sync_violations.py`: 27 tests
  - `tests/test_night_logger_github.py`: 33 tests
- **Test Status**: ✅ All 60 tests passing

## Files Under Test

### 1. `sync_violations.py`
Beeminder synchronization script with violations-only processing.

**Test Coverage:**
- `BeeminderAPI` class (9 tests)
  - Initialization
  - Datapoint fetching with pagination
  - Datapoint creation
  - Datapoint deletion
  - Error handling
- `ViolationsSync` class (15 tests)
  - Initialization and environment variable validation
  - Violations file loading
  - Selective sync (duplicates, creates, updates, deletes)
  - Nuclear cleanup mode
- Main CLI function (3 tests)
  - Normal sync mode
  - Nuclear cleanup flag
  - Missing environment variables

### 2. `night_logger_github_fixed_v3.py`
Night logger with GitHub integration and tamper-resistant design.

**Test Coverage:**
- Time helpers (8 tests)
  - `is_between_23_and_359_local()`: All hour ranges
  - `local_ymd()`: Date formatting
- Database helpers (6 tests)
  - `open_db()`: Table creation, WAL mode
  - `already_posted_today()`: Posted date checking
  - `mark_posted_today()`: Idempotent posting
- Beeminder duplicate cleaning (4 tests)
  - No duplicates
  - With duplicates
  - API errors
  - Delete failures
- Violations extraction (4 tests)
  - Nonexistent database
  - Empty database
  - With violations
  - Multiple dates
- `GitHubAPI` class (8 tests)
  - Initialization
  - File upload (new/existing)
  - Branch creation
  - Workflow triggering
  - Error handling
- Main function (3 tests)
  - Keyboard interrupt handling
  - Verbose mode
  - Missing credentials

## Running Tests

### Prerequisites

```bash
# Install test dependencies
pip install -r requirements-test.txt
```

Required packages:
- pytest >= 7.4.0
- pytest-cov >= 4.1.0
- pytest-mock >= 3.11.1
- coverage >= 7.3.0
- requests-mock >= 1.11.0

### Run All Tests

```bash
# Run with verbose output
pytest -v

# Run specific test file
pytest tests/test_sync_violations.py -v
pytest tests/test_night_logger_github.py -v

# Run with coverage report
pytest --cov=. --cov-report=html --cov-report=term-missing
```

### Run Specific Tests

```bash
# Run a specific test class
pytest tests/test_sync_violations.py::TestBeeminderAPI -v

# Run a specific test
pytest tests/test_sync_violations.py::TestBeeminderAPI::test_init -v
```

## Test Configuration

### pytest.ini
Configures pytest behavior:
- Test discovery patterns
- Default verbosity
- Coverage settings (when pytest-cov is installed)
- Custom test markers (slow, integration, unit)

### .coveragerc
Configures coverage reporting:
- Source files to include
- Files/patterns to omit
- Coverage thresholds
- HTML report directory

## Test Structure

Each test file follows this organization:

```python
class TestFeatureName:
    """Test suite for specific feature/class"""

    def setup_method(self):
        """Set up test fixtures before each test"""
        pass

    def teardown_method(self):
        """Clean up after each test"""
        pass

    def test_specific_behavior(self):
        """Test a specific behavior with clear assertions"""
        pass
```

## Mocking Strategy

Tests use `unittest.mock` for external dependencies:
- **HTTP requests** (`requests` library): Mocked to avoid network calls
- **Filesystem**: Temporary files used, cleaned up automatically
- **Environment variables**: Patched for isolation
- **Database**: SQLite in-memory or temp files

## Coverage Goals

- **Line coverage**: Aim for 100% on all production code
- **Branch coverage**: Test all conditional paths
- **Error handling**: Test both success and failure cases
- **Edge cases**: Test boundary conditions

## Continuous Integration

To add CI/CD:

```yaml
# .github/workflows/test.yml
name: Tests
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - uses: actions/setup-python@v2
        with:
          python-version: '3.10'
      - run: pip install -r requirements-test.txt
      - run: pytest -v --cov=. --cov-report=xml
      - uses: codecov/codecov-action@v2
```

## Adding New Tests

When adding new features:

1. Write tests first (TDD approach recommended)
2. Ensure all code paths are tested
3. Test both success and failure cases
4. Use descriptive test names
5. Keep tests independent and isolated
6. Run full test suite before committing

Example test template:

```python
def test_new_feature_success(self):
    """Test new_feature succeeds with valid input"""
    # Arrange
    input_data = "valid input"
    expected = "expected output"

    # Act
    result = new_feature(input_data)

    # Assert
    assert result == expected

def test_new_feature_failure(self):
    """Test new_feature handles invalid input"""
    with pytest.raises(ValueError):
        new_feature("invalid input")
```

## Troubleshooting

### Tests fail with import errors
- Ensure you're running from the repository root
- Check Python path includes parent directory

### Mock assertions fail
- Verify mock is configured correctly
- Check mock.call_count and mock.call_args
- Use `mock.assert_called_once_with()` for specific checks

### Database tests fail
- Ensure temp files are cleaned up in teardown
- Check for database locks (close connections properly)

## Test Metrics

Current test execution time: **~1.8 seconds**

- Fast unit tests enable rapid development
- No external dependencies (all mocked)
- Can run offline

## Future Improvements

1. Add integration tests with real Beeminder API (test environment)
2. Add performance/load tests
3. Add mutation testing for test quality verification
4. Set up automated coverage reporting
5. Add property-based testing with Hypothesis

## Contributing

When submitting PRs:
1. ✅ All tests must pass
2. ✅ New code must have tests
3. ✅ Maintain or improve coverage
4. ✅ Follow existing test patterns
