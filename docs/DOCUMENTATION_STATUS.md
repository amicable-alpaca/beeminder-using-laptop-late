# Documentation Status

## Updated (October 2025)

### ✅ README.md
- Updated test references (60 tests total)
- Removed references to old test files
- Added October 2025 fixes section
- Corrected file paths and commands

### ✅ docs/TESTING.md
- Complete rewrite with new test suite
- 60 tests documented (27 + 33)
- Updated commands and examples
- Current and accurate

## Needs Update

### ⚠️ docs/NIGHT_LOGGER_SYSTEM_DOCUMENTATION.md
**Issues:**
- References old test files (test_comprehensive.py, test_exit_logic_fix.py, test_complete_with_fix.py)
- Shows old service override with `Restart=always` (now `Restart=on-failure`)
- References deploy_fix.sh which doesn't exist
- Test counts outdated (claims 56 tests, actually 60)

**Should update to:**
- tests/test_sync_violations.py (27 tests)
- tests/test_night_logger_github.py (33 tests)
- Service override: `Restart=on-failure`
- Current status: October 2025 fixes deployed

### ⚠️ docs/SETUP_TAMPER_RESISTANT.md
**Issues:**
- References old test files
- Has entire "Exit Logic Fix" section for September 2025 (already deployed)
- References deploy_fix.sh which doesn't exist
- Test commands use old Python files instead of pytest

**Should update to:**
- Use `pytest -v` for testing
- Remove historical "Exit Logic Fix" section
- Focus on current working system
- Update test file references

## Quick Fix Commands

To get current test info:
```bash
cd /home/admin/repos/beeminder-using-laptop-late
pytest --collect-only  # Shows all 60 tests
pytest -v              # Runs all tests
```

To check service config:
```bash
cat /etc/systemd/system/night-logger.service.d/override.conf
```

## Priority

1. ✅ README.md - **DONE**
2. ✅ TESTING.md - **DONE**
3. ⚠️ NIGHT_LOGGER_SYSTEM_DOCUMENTATION.md - Needs bulk find/replace
4. ⚠️ SETUP_TAMPER_RESISTANT.md - Needs simplification

The two remaining docs are reference material and less critical than README/TESTING which users see first.
