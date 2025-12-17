# Makefile for functrace Pin tool (Pin 4.x compatible)
#
# Usage:
#   make PIN_ROOT=/path/to/pin                             # Build functrace with gcc
#   make listener CC=clang CXX_BASE=clang++                # Build listener with clang
#   make all-with-listener PIN_ROOT=/path/to/pin CC=clang CXX_BASE=clang++
#
# Example:
#   make PIN_ROOT=~/post/pin-external-4.0-99633-g5ca9893f2-gcc-linux
#   make all-with-listener PIN_ROOT=~/post/pin-external-4.0-99633-g5ca9893f2-gcc-linux CC=clang CXX_BASE=clang++

# Pin kit root - must be set by user
PIN_ROOT ?= $(HOME)/pin

# Compiler selection for listener library - defaults to gcc
# Set CC=clang CXX_BASE=clang++ to build listener with clang
# Note: Pin tool (functrace.so) always uses pin-g++ wrapper (gcc-based)
#       as Pin doesn't provide a clang-compatible wrapper
CC ?= gcc
CXX_BASE ?= g++

# Architecture detection
ARCH := $(shell uname -m)
ifeq ($(ARCH),x86_64)
    TARGET := intel64
else
    TARGET := ia32
endif

# Output directory
OBJDIR := obj-$(TARGET)/

# Tool name
TOOL_NAME := functrace
TOOL := $(OBJDIR)$(TOOL_NAME).so

# Pin 4.x uses its own compiler wrapper
CXX := $(PIN_ROOT)/$(TARGET)/pinrt/bin/pin-g++

# Include paths for Pin 4.x
PIN_INCLUDES := -I$(PIN_ROOT)/source/include/pin \
                -I$(PIN_ROOT)/source/include/pin/gen \
                -I$(PIN_ROOT)/extras/components/include \
                -I$(PIN_ROOT)/extras/xed-$(TARGET)/include/xed \
                -I$(PIN_ROOT)/$(TARGET)/pinrt/include/adaptor \
                -I$(PIN_ROOT)/source/tools/Utils \
                -I$(PIN_ROOT)/source/tools/InstLib

# Compiler flags for Pin 4.x
PIN_CXXFLAGS := -std=c++17 -Wall -Wno-error=maybe-uninitialized -Wno-unknown-pragmas \
                -fno-stack-protector -fno-exceptions \
                -funwind-tables -fasynchronous-unwind-tables \
                -fno-rtti -fPIC -faligned-new \
                $(PIN_INCLUDES) -O3

# Linker flags
PIN_LDFLAGS := -shared \
               -Wl,-Bsymbolic \
               -Wl,--version-script=$(PIN_ROOT)/source/include/pin/pintool.ver \
               -L$(PIN_ROOT)/$(TARGET)/lib \
               -L$(PIN_ROOT)/$(TARGET)/lib-ext \
               -L$(PIN_ROOT)/$(TARGET)/pinrt/lib \
               -L$(PIN_ROOT)/extras/xed-$(TARGET)/lib

# Libraries for Pin 4.x
PIN_LIBS := -lpin -lpinrt-adaptor-static -lxed -lpindwarf -ldwarf -lunwind-dynamic

# ========================================
# Listener library for test programs
# ========================================

LISTENER_DIR := pin_listener
LISTENER_LIB := $(LISTENER_DIR)/libpin_listener.a
LISTENER_SRCS := $(LISTENER_DIR)/pin_annotations.c $(LISTENER_DIR)/pin_test_listener.cpp
LISTENER_OBJS := $(LISTENER_DIR)/pin_annotations.o $(LISTENER_DIR)/pin_test_listener.o

# Default target
all: $(OBJDIR) $(TOOL)

# Build everything including listener
all-with-listener: $(OBJDIR) $(TOOL) $(LISTENER_LIB)

$(OBJDIR):
	mkdir -p $(OBJDIR)

$(OBJDIR)%.o: %.cpp
	$(CXX) $(PIN_CXXFLAGS) -c -o $@ $<

$(TOOL): $(OBJDIR)$(TOOL_NAME).o
	$(CXX) $(PIN_LDFLAGS) -o $@ $< $(PIN_LIBS)

# Listener library targets
$(LISTENER_DIR)/pin_annotations.o: $(LISTENER_DIR)/pin_annotations.c $(LISTENER_DIR)/pin_annotations.h
	$(CC) -c -fPIC -O2 -o $@ $<

$(LISTENER_DIR)/pin_test_listener.o: $(LISTENER_DIR)/pin_test_listener.cpp $(LISTENER_DIR)/pin_test_listener.h $(LISTENER_DIR)/pin_annotations.h
	$(CXX_BASE) -std=c++17 -c -fPIC -O2 -I$(LISTENER_DIR) -o $@ $<

$(LISTENER_LIB): $(LISTENER_OBJS)
	ar rcs $@ $^

listener: $(LISTENER_LIB)
	@echo "Built $(LISTENER_LIB)"

clean:
	rm -rf obj-* *.out
	rm -f $(LISTENER_DIR)/*.o $(LISTENER_DIR)/*.a

# Check if PIN_ROOT is valid
check:
	@if [ ! -d "$(PIN_ROOT)" ]; then \
		echo "Error: PIN_ROOT=$(PIN_ROOT) does not exist"; \
		exit 1; \
	fi
	@if [ ! -f "$(CXX)" ]; then \
		echo "Error: Pin compiler not found at $(CXX)"; \
		echo "Make sure you're using Pin 4.x"; \
		exit 1; \
	fi
	@echo "PIN_ROOT=$(PIN_ROOT) - OK"
	@echo "Compiler=$(CXX) - OK"
	@echo "Target: $(TARGET)"

# Test program
test_program: test_program.c
	$(CC) -g -o test_program test_program.c

# Run the tool on test program
test: $(TOOL) test_program
	$(PIN_ROOT)/pin -t $(TOOL) -- ./test_program
	@echo "Output written to functrace.out"
	@head -30 functrace.out

# Show usage
help:
	@echo "Function Trace Pin Tool - Build System"
	@echo ""
	@echo "Usage:"
	@echo "  make PIN_ROOT=/path/to/pin      Build the tool"
	@echo "  make listener                   Build the listener library"
	@echo "  make all-with-listener          Build tool and listener"
	@echo "  make test PIN_ROOT=/path/to/pin Build and run test"
	@echo "  make clean                      Remove build artifacts"
	@echo "  make check                      Verify PIN_ROOT is set correctly"
	@echo ""
	@echo "Running the tool:"
	@echo "  \$${PIN_ROOT}/pin -t $(TOOL) -- ./your_program"
	@echo ""
	@echo "Test mode (with per-test coverage):"
	@echo "  \$${PIN_ROOT}/pin -t $(TOOL) -runtime_dump -logdir unittests -- ./unittests"
	@echo ""
	@echo "Options:"
	@echo "  -o <file>        Output file (default: functrace.out)"
	@echo "  -all 1           Log every call, not just unique functions"
	@echo "  -libs 0          Only trace main executable, skip libraries"
	@echo "  -filter <str>    Only trace images containing <str>"
	@echo "  -runtime_dump    Enable per-test coverage dumps"
	@echo "  -logdir <dir>    Directory for per-test log files"
	@echo ""
	@echo "Listener library:"
	@echo "  Link test programs with $(LISTENER_LIB) and use PinTestListener"
	@echo "  for GoogleTest integration."

.PHONY: all all-with-listener clean check help test listener
