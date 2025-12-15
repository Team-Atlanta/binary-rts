/*
 * pin_test_listener.cpp - Test listener implementation for Pin-based coverage
 *
 * This mirrors the binary-rts test_listener.cpp but uses pin_rts_dump_coverage
 * instead of DynamoRIO's DYNAMORIO_ANNOTATE_LOG.
 */

#include "pin_test_listener.h"
#include "pin_annotations.h"

#include <string>
#include <algorithm>
#include <fstream>
#include <iostream>
#include <cstdlib>
#include <vector>
#include <sstream>

#ifdef __linux__
    #include <unistd.h>
    #include <cstdint>
#elif _WIN32
    #include <windows.h>
#endif

#define DEBUG 0

namespace {
    const char* globalTestSetupDumpIdentifier = "GLOBAL_TEST_SETUP";
    const std::string testIdSeparator = "!!!";
    constexpr size_t maxPathLength = 512;

    std::vector<std::string> split(const std::string& s, char delim) {
        std::vector<std::string> result;
        std::stringstream ss(s);
        std::string item;
        while (getline(ss, item, delim)) {
            result.push_back(item);
        }
        return result;
    }

    std::string getCurrentExecutableName() {
        std::string executableName;
#ifdef __linux__
        char exe[maxPathLength] = {0};
        ssize_t ret = readlink("/proc/self/exe", exe, sizeof(exe) - 1);
        if (ret != -1) {
            executableName = split(exe, '/').back();
        }
#elif _WIN32
        TCHAR exe[maxPathLength] = {0};
        DWORD bufSize = sizeof(exe) / sizeof(*exe);
        if (GetModuleFileName(NULL, exe, bufSize) < bufSize) {
            executableName = split(exe, '\\').back();
        }
#endif
        return executableName;
    }
}

/* Static member initialization */
const std::string PinTestListener::TestCaseSeparator = ".";
bool PinTestListener::enableParameterizedTests = true;
bool PinTestListener::isCurrentTestSuiteParameterized = false;
int PinTestListener::testCounter = 0;
int PinTestListener::testSuiteCounter = 0;
std::string PinTestListener::currentTestIdentifier;
std::string PinTestListener::currentTestSuiteIdentifier;

static void DumpCoverage(const char* dumpId) {
#if DEBUG
    std::cout << "Pin: Dumping with ID: " << dumpId << std::endl;
#endif
    pin_rts_dump_coverage(dumpId);
}

void PinTestListener::TestProgramStart() {
    /* Coverage before first test is captured in GLOBAL_TEST_SETUP */
}

void PinTestListener::TestSuiteStart(const std::string& testSuiteIdentifier) {
    currentTestSuiteIdentifier = testSuiteIdentifier;
    if (currentTestSuiteIdentifier.find('/') != std::string::npos) {
        isCurrentTestSuiteParameterized = true;
    }
    if (testSuiteCounter++ == 0) {
        DumpCoverage(globalTestSetupDumpIdentifier);
    }
}

void PinTestListener::TestStart(const std::string& testIdentifier) {
    currentTestIdentifier = currentTestSuiteIdentifier + TestCaseSeparator + testIdentifier;
    if (testCounter++ == 0) {
        std::string message = currentTestSuiteIdentifier + "___setup";
        DumpCoverage(message.c_str());
    }
}

void PinTestListener::TestEnd(const std::string& result) {
    /* Trigger coverage dump after each test case for test-specific coverage.
       We encode the test result in the dump identifier. */
    if (enableParameterizedTests || !isCurrentTestSuiteParameterized) {
        std::string message = currentTestIdentifier + "___" + result;
        DumpCoverage(message.c_str());
    }
}

void PinTestListener::TestSuiteEnd(const std::string& result) {
    std::string message = currentTestSuiteIdentifier + "___" + result;
    DumpCoverage(message.c_str());
    testCounter = 0;
    isCurrentTestSuiteParameterized = false;
}

void PinTestListener::TestProgramEnd() {
    testSuiteCounter = 0;
    DumpCoverage(globalTestSetupDumpIdentifier);
}

std::string ParseExcludesFileToGoogleTestFilter(
    const std::string& path,
    const std::string& previousFilter)
{
    std::ifstream file(path);
    std::cout << "Starting to parse excluded tests from " << path << "\n";
    std::string testFilter = "-";

    std::string executableName = getCurrentExecutableName();

    /* Handle previous filter - either append with ':' or start new exclude with '-' */
    if (!previousFilter.empty()) {
        std::size_t excludesFilterPos = previousFilter.find('-');
        if (excludesFilterPos == std::string::npos) {
            testFilter = previousFilter + "-";
        } else {
            testFilter = previousFilter + ":";
        }
    }

    if (file.is_open()) {
        std::string line;
        uint64_t counter = 0;
        while (std::getline(file, line)) {
            /* Remove test module name prefix from identifier */
            std::size_t moduleIdEnd = line.find(testIdSeparator);
            line = line.substr(moduleIdEnd + testIdSeparator.size());
            line.replace(line.find(testIdSeparator), testIdSeparator.size(), ".");
            if (counter > 0) {
                testFilter += ":";
            }
            testFilter += line;
            ++counter;
        }
        std::cout << "Found " << counter << " tests: " << testFilter << "\n";
        file.close();
    }

    return testFilter;
}

const char* GetTestExcludesFileFromEnv() {
    return std::getenv("GTEST_EXCLUDES_FILE");
}
