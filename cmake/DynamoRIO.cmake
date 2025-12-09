# Fetch the DynamoRIO release.
include(FetchContent)
if (WIN32)
    set(DynamoRIO_URL "https://github.com/DynamoRIO/dynamorio/releases/download/cronbuild-11.90.20418/DynamoRIO-Windows-11.90.20418.zip")
endif (WIN32)
if (UNIX)
    set(DynamoRIO_URL "https://github.com/DynamoRIO/dynamorio/releases/download/cronbuild-11.90.20418/DynamoRIO-Linux-11.90.20418.tar.gz")
endif (UNIX)
if ("${DynamoRIO_URL}" STREQUAL "")
	message(FATAL_ERROR "Your OS is currently not supported by DynamoRIO.")
endif()
message("Downloading DynamoRIO from ${DynamoRIO_URL}...")
FetchContent_Declare(
  dynamorio
  URL ${DynamoRIO_URL}
)
FetchContent_MakeAvailable(dynamorio)
FetchContent_GetProperties(dynamorio SOURCE_DIR DynamoRIO_ROOT)
FILE(TO_CMAKE_PATH "${DynamoRIO_ROOT}/cmake" DynamoRIO_DIR)
message("Using DynamoRIO_DIR=${DynamoRIO_DIR} for build...")

# Load DynamoRIO config from DynamoRIO_DIR/cmake/DynamoRIOConfig.cmake.in
find_package(DynamoRIO)
if (NOT DynamoRIO_FOUND)
    message(FATAL_ERROR "DynamoRIO package required to build")
endif(NOT DynamoRIO_FOUND)