cmake_minimum_required(VERSION 3.15)

include(../../cmake/GoogleTest.cmake)

# Option to use Pin listener instead of DynamoRIO listener
option(USE_PIN_LISTENER "Use Pin-based listener instead of DynamoRIO" ON)

# define source files
set(test_SRCS main.cpp mockbar.h testfoo.cpp testfoo.h)

# create binary for test execution
add_executable(unittests ${test_SRCS})

if(USE_PIN_LISTENER)
    # Pin listener configuration
    set(PIN_LISTENER_DIR "${CMAKE_SOURCE_DIR}/../pintools-rts/pin_listener")

    target_include_directories(unittests PRIVATE ${PIN_LISTENER_DIR})
    target_link_libraries(unittests
            gtest_main
            gmock_main
            libfoo
            ${PIN_LISTENER_DIR}/libpin_listener.a
    )
    target_compile_definitions(unittests PRIVATE PIN_LISTENER)
else()
    # DynamoRIO listener configuration (default)
    target_link_libraries(unittests
            gtest_main
            gmock_main
            libfoo
            binary_rts_listener
    )
    target_compile_definitions(unittests PRIVATE TEST_LISTENER)
    target_compile_definitions(unittests PRIVATE TEST_SELECTION)
endif()
