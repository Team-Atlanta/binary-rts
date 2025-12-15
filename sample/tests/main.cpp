#include <gtest/gtest.h>
#include <iostream>
#include <fstream>

#ifdef PIN_LISTENER
#include "pin_test_listener.h"

class CoverageEventListener : public testing::EmptyTestEventListener {
public:

    void OnTestProgramStart(const testing::UnitTest& test) override {
        startRun();
        PinTestListener::TestProgramStart();
    }

    void OnTestSuiteStart(const testing::TestSuite& testSuite) override {
        PinTestListener::TestSuiteStart(testSuite.name());
    }

    void OnTestStart(const testing::TestInfo& testInfo) override {
        PinTestListener::TestStart(testInfo.name());
    }

    void OnTestEnd(const testing::TestInfo& test_info) override {
        PinTestListener::TestEnd(test_info.result()->Passed() ? "PASSED": "FAILED");
    }

    void OnTestSuiteEnd(const testing::TestSuite& testSuite) override {
        PinTestListener::TestSuiteEnd(testSuite.Passed() ? "PASSED" : "FAILED");
    }

    void OnTestProgramEnd(const testing::UnitTest& test) override {
        PinTestListener::TestProgramEnd();
        finishRun();
    }

private:
    void finishRun() {
        std::cout << "After OnTestProgramEnd in CoverageEventListener" << std::endl;
    }
    void startRun() {
        std::cout << "Before OnTestProgramStart in CoverageEventListener" << std::endl;
    }
};

#elif defined(TEST_LISTENER)
#include "test_listener.h"

class CoverageEventListener : public testing::EmptyTestEventListener {
public:

    void OnTestProgramStart(const testing::UnitTest& test) override {
        startRun();
        BinaryRTSTestListener::TestProgramStart();
    }

    void OnTestSuiteStart(const testing::TestSuite& testSuite) override {
        BinaryRTSTestListener::TestSuiteStart(testSuite.name());
    }

    void OnTestStart(const testing::TestInfo& testInfo) override {
        BinaryRTSTestListener::TestStart(testInfo.name());
    }

    void OnTestEnd(const testing::TestInfo& test_info) override {
        BinaryRTSTestListener::TestEnd(test_info.result()->Passed() ? "PASSED": "FAILED");
    }

    void OnTestSuiteEnd(const testing::TestSuite& testSuite) override {
        BinaryRTSTestListener::TestSuiteEnd(testSuite.Passed() ? "PASSED" : "FAILED");
    }

    void OnTestProgramEnd(const testing::UnitTest& test) override {
        BinaryRTSTestListener::TestProgramEnd();
        finishRun();
    }

private:
    void finishRun() {
        std::cout << "After OnTestProgramEnd in CoverageEventListener" << std::endl;
    }
    void startRun() {
        std::cout << "Before OnTestProgramStart in CoverageEventListener" << std::endl;
    }
};

#endif

class CustomEnvironment : public ::testing::Environment {
public:
    ~CustomEnvironment() override = default;

    void SetUp() override {
        std::cout << "Global SetUp" << std::endl;
        std::ofstream file;
        file.open("output.txt");
        file << "Random text\n";
        file.close();
    }

    // Override this to define how to tear down the environment.
    void TearDown() override {
        std::cout << "Global TearDown" << std::endl;
    }
};

int main(int argc, char **argv) {
    ::testing::InitGoogleTest(&argc, argv);
    ::testing::AddGlobalTestEnvironment(new CustomEnvironment);
#ifdef TEST_SELECTION
    if (const char* excludes_file = GetTestExcludesFileFromEnv()) {
        std::string previousFilter = ::testing::GTEST_FLAG(filter);
        std::cout << "BEFORE: " << previousFilter << "\n";
        ::testing::GTEST_FLAG(filter) = ParseExcludesFileToGoogleTestFilter(excludes_file, previousFilter);
    }
#endif
#if defined(TEST_LISTENER) || defined(PIN_LISTENER)
    // Gets hold of the event listener list.
    ::testing::UnitTest::GetInstance()->listeners().Append(new CoverageEventListener());
#endif
    return RUN_ALL_TESTS();
}
