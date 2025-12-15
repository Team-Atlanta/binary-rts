/*
 * pin_test_listener.h - Test listener for Pin-based coverage
 *
 * Provides static methods to be called from GoogleTest event listeners.
 * Mirrors the interface of BinaryRTSTestListener from binary-rts.
 */

#ifndef PIN_TEST_LISTENER_H
#define PIN_TEST_LISTENER_H

#include <string>

class PinTestListener {
public:
    static const std::string TestCaseSeparator;

    /* Called when test program starts */
    static void TestProgramStart();

    /* Called when a test suite begins */
    static void TestSuiteStart(const std::string& testSuiteIdentifier);

    /* Called when an individual test begins */
    static void TestStart(const std::string& testIdentifier);

    /* Called when an individual test ends. Result is "PASSED" or "FAILED" */
    static void TestEnd(const std::string& result);

    /* Called when a test suite ends. Result is "PASSED" or "FAILED" */
    static void TestSuiteEnd(const std::string& result);

    /* Called when test program ends */
    static void TestProgramEnd();

    /* Control whether parameterized tests get separate coverage dumps */
    static bool enableParameterizedTests;

private:
    static bool isCurrentTestSuiteParameterized;
    static int testCounter;
    static int testSuiteCounter;
    static std::string currentTestIdentifier;
    static std::string currentTestSuiteIdentifier;
};

/*
 * Parse excludes file and return GoogleTest filter string.
 * Matches the format used by binary-rts for test selection.
 */
std::string ParseExcludesFileToGoogleTestFilter(
    const std::string& path,
    const std::string& previousFilter = std::string());

/*
 * Get the excludes file path from environment variable GTEST_EXCLUDES_FILE.
 */
const char* GetTestExcludesFileFromEnv();

#endif /* PIN_TEST_LISTENER_H */
