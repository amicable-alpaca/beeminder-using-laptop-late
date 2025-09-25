#!/usr/bin/env python3
"""
Complete Test Suite for Night Logger System (Including Exit Logic Fix)

Tests all components of the violations-only architecture including the exit logic fix:
- night_logger_github_fixed.py (fixed version with continue-logging behavior)
- sync_violations.py (selective sync with Beeminder API pagination)
- extract_violations.py (HSoT database processing)
- Integration testing and error handling
- Security and data integrity
- Exit logic fix verification
"""

import os
import sys
import unittest

# Add current directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import all test modules
try:
    from test_comprehensive import *
    from test_exit_logic_fix import *
except ImportError as e:
    print(f"Warning: Could not import test modules: {e}")


def run_complete_test_suite():
    """Run all tests including exit logic fix tests"""

    print("🧪 Running Complete Test Suite (Original + Exit Logic Fix)")
    print("=" * 80)

    # Create test suite
    test_suite = unittest.TestSuite()

    # Original test classes from test_comprehensive.py
    original_test_classes = [
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

    # Exit logic fix test classes from test_exit_logic_fix.py
    exit_logic_test_classes = [
        TestFixedExitLogic,
        TestFixedBehaviorVsOriginal
    ]

    # Add all test classes
    all_test_classes = original_test_classes + exit_logic_test_classes

    test_count = 0
    for test_class in all_test_classes:
        suite = unittest.makeSuite(test_class)
        test_suite.addTest(suite)
        test_count += suite.countTestCases()

    print(f"📊 Total test cases: {test_count}")
    print(f"📊 Original test classes: {len(original_test_classes)}")
    print(f"📊 Exit logic fix test classes: {len(exit_logic_test_classes)}")
    print("-" * 80)

    # Run tests
    runner = unittest.TextTestRunner(verbosity=2, buffer=True)
    result = runner.run(test_suite)

    # Calculate statistics
    total_tests = result.testsRun
    failures = len(result.failures)
    errors = len(result.errors)
    skipped = len(result.skipped) if hasattr(result, 'skipped') else 0
    passed = total_tests - failures - errors - skipped

    print("=" * 80)
    print("📊 TEST RESULTS SUMMARY")
    print("-" * 80)
    print(f"Total Tests:     {total_tests}")
    print(f"Passed:          {passed}")
    print(f"Failed:          {failures}")
    print(f"Errors:          {errors}")
    print(f"Skipped:         {skipped}")
    print(f"Success Rate:    {(passed/total_tests)*100:.1f}%")

    if result.wasSuccessful():
        print("✅ ALL TESTS PASSED - 100% SUCCESS!")
        print("✅ Exit logic fix verified and working correctly!")
        print("✅ Original functionality maintained!")
    else:
        print("❌ SOME TESTS FAILED")

        if failures > 0:
            print(f"\n❌ FAILURES ({failures}):")
            for i, (test, traceback) in enumerate(result.failures, 1):
                print(f"  {i}. {test}")

        if errors > 0:
            print(f"\n❌ ERRORS ({errors}):")
            for i, (test, traceback) in enumerate(result.errors, 1):
                print(f"  {i}. {test}")

    print("=" * 80)

    return result.wasSuccessful(), failures, errors, passed, total_tests


def verify_test_coverage():
    """Verify that tests cover the key areas"""

    print("\n🔍 COVERAGE VERIFICATION")
    print("-" * 40)

    coverage_areas = {
        "Core Night Logger Logic": [
            "TestNightLoggerCore",
            "TestFixedExitLogic"
        ],
        "GitHub API Integration": [
            "TestGitHubAPI",
            "TestDualBranchUpload"
        ],
        "Beeminder API Integration": [
            "TestBeeminderAPI",
            "TestViolationsSync"
        ],
        "Database Operations": [
            "TestDatabaseConcurrency",
            "TestExtractViolationsEnhanced"
        ],
        "Time & Attribution Logic": [
            "TestNightTimeAttribution",
            "TestTimestampHandling"
        ],
        "Error Handling": [
            "TestErrorHandlingEnhanced",
            "TestRaceConditions"
        ],
        "Security": [
            "TestSecurity"
        ],
        "Exit Logic Fix": [
            "TestFixedExitLogic",
            "TestFixedBehaviorVsOriginal"
        ],
        "Advanced Features": [
            "TestAdvancedSyncFeatures",
            "TestIntegration"
        ]
    }

    # Get all available test classes
    available_classes = [cls.__name__ for cls in globals().values()
                        if isinstance(cls, type) and issubclass(cls, unittest.TestCase)]

    for area, required_classes in coverage_areas.items():
        covered_classes = [cls for cls in required_classes if cls in available_classes]
        coverage_pct = (len(covered_classes) / len(required_classes)) * 100
        status = "✅" if coverage_pct == 100 else "⚠️" if coverage_pct >= 50 else "❌"
        print(f"{status} {area}: {coverage_pct:.0f}% ({len(covered_classes)}/{len(required_classes)})")

    print("-" * 40)


if __name__ == "__main__":

    # Run coverage verification first
    verify_test_coverage()

    # Run complete test suite
    success, failures, errors, passed, total = run_complete_test_suite()

    # Exit with appropriate code
    if success:
        print("🎉 All tests passed! Ready for deployment!")
        sys.exit(0)
    else:
        print(f"💥 Tests failed: {failures} failures, {errors} errors")
        sys.exit(1)