/*
 * functrace.cpp - Intel Pin tool to trace all function calls
 *
 * Captures for each function:
 *   - Image/module name (file containing the function)
 *   - Symbol name
 *   - Source file and line number (if debug info available)
 *   - Start address and end address (start + size)
 *
 * Test mode (-runtime_dump):
 *   When enabled, intercepts calls to pin_rts_dump_coverage() and dumps
 *   accumulated function coverage to per-test log files. This integrates
 *   with GoogleTest via PinTestListener.
 *
 * Usage:
 *   pin -t obj-intel64/functrace.so -- ./your_program
 *   pin -t obj-intel64/functrace.so -runtime_dump -logdir unittests -- ./unittests
 *
 * Output written to functrace.out (or specify with -o option)
 */

#include "pin.H"
#include <fstream>
#include <iostream>
#include <string>
#include <unordered_set>
#include <unordered_map>
#include <mutex>
#include <sys/stat.h>
#include <unistd.h>

/* ===================================================================== */
/* Command Line Options                                                  */
/* ===================================================================== */

KNOB<std::string> KnobOutputFile(KNOB_MODE_WRITEONCE, "pintool",
    "o", "functrace.out", "Output file name");

KNOB<BOOL> KnobLogAllCalls(KNOB_MODE_WRITEONCE, "pintool",
    "all", "0", "Log every call (1) or unique functions only (0)");

KNOB<BOOL> KnobIncludeLibs(KNOB_MODE_WRITEONCE, "pintool",
    "libs", "1", "Include library functions (1) or main executable only (0)");

KNOB<std::string> KnobFilterImage(KNOB_MODE_WRITEONCE, "pintool",
    "filter", "", "Only trace functions from images containing this substring");

KNOB<std::string> KnobExclude(KNOB_MODE_WRITEONCE, "pintool",
    "exclude", "libc.so,ld-linux,libm.so,libpthread,libdl.so,libstdc++,libc++",
    "Comma-separated list of image substrings to exclude");

KNOB<BOOL> KnobNoExclude(KNOB_MODE_WRITEONCE, "pintool",
    "no-exclude", "0", "Disable default exclusions (trace everything)");

/* Test mode options */
KNOB<BOOL> KnobRuntimeDump(KNOB_MODE_WRITEONCE, "pintool",
    "runtime_dump", "0", "Enable runtime coverage dumps for test tracking");

KNOB<std::string> KnobLogDir(KNOB_MODE_WRITEONCE, "pintool",
    "logdir", "trace_logs", "Directory for per-test log files (runtime_dump mode)");

KNOB<std::string> KnobModulesFile(KNOB_MODE_WRITEONCE, "pintool",
    "modules", "", "Output file for module list (optional)");

KNOB<BOOL> KnobFollowChild(KNOB_MODE_WRITEONCE, "pintool",
    "follow_child", "0", "Follow child processes (fork/exec)");

/* ===================================================================== */
/* Global Variables                                                      */
/* ===================================================================== */

static std::ofstream TraceFile;
static UINT64 CallCount = 0;
static std::unordered_set<ADDRINT> SeenFunctions;
static std::mutex TraceLock;

/* Test mode state */
static int DumpCount = 0;
static std::ofstream LookupFile;
static std::unordered_set<ADDRINT> CurrentTestFunctions;
static std::string ProcessSuffix;  // Unique suffix for this process (PID-based)

/* Function metadata for coverage dumps */
struct FunctionInfo {
    std::string imgName;
    std::string imgPath;
    std::string rtnName;
    std::string srcFile;
    ADDRINT rtnAddr;
    ADDRINT imgLow;
    UINT32 rtnSize;
    INT32 srcLine;
};
static std::unordered_map<ADDRINT, FunctionInfo> FunctionMetadata;

/* Main executable info for output header */
static std::string MainExeName;
static std::string MainExePath;

/* ===================================================================== */
/* Helper Functions                                                      */
/* ===================================================================== */

// Extract just the filename from a full path
static std::string BaseName(const std::string& path)
{
    size_t pos = path.find_last_of("/\\");
    if (pos == std::string::npos)
        return path;
    return path.substr(pos + 1);
}

// Check if image should be excluded based on -exclude patterns
static bool ShouldExcludeImage(const std::string& imgName)
{
    if (KnobNoExclude.Value())
        return false;

    std::string excludeList = KnobExclude.Value();
    if (excludeList.empty())
        return false;

    // Parse comma-separated exclusion patterns
    size_t start = 0;
    size_t end;
    while ((end = excludeList.find(',', start)) != std::string::npos) {
        std::string pattern = excludeList.substr(start, end - start);
        if (!pattern.empty() && imgName.find(pattern) != std::string::npos)
            return true;
        start = end + 1;
    }
    // Check last pattern (after final comma or if no commas)
    std::string pattern = excludeList.substr(start);
    if (!pattern.empty() && imgName.find(pattern) != std::string::npos)
        return true;

    return false;
}

// Create directory if it doesn't exist
static bool EnsureDirectory(const std::string& path)
{
    struct stat st;
    if (stat(path.c_str(), &st) == 0) {
        return S_ISDIR(st.st_mode);
    }
    return mkdir(path.c_str(), 0755) == 0;
}

/* ===================================================================== */
/* Coverage Dump Handler - Called when marker function is invoked        */
/* ===================================================================== */

static VOID HandleCoverageDump(ADDRINT dumpIdArg)
{
    const char* dumpId = reinterpret_cast<const char*>(dumpIdArg);

    std::lock_guard<std::mutex> guard(TraceLock);

    DumpCount++;

    // Write current coverage to numbered file (include PID suffix if following children)
    std::string filename = KnobLogDir.Value() + "/" + ProcessSuffix + std::to_string(DumpCount) + ".log";
    std::ofstream dumpFile(filename);

    if (dumpFile.is_open()) {
        // Header line: module_name<tab>module_path
        dumpFile << MainExeName << "\t" << MainExePath << "\n";

        // Write each function that was called during this test segment
        // Format: <tab>+<offset><tab><source_file><tab><symbol><tab><line>
        for (ADDRINT addr : CurrentTestFunctions) {
            auto it = FunctionMetadata.find(addr);
            if (it != FunctionMetadata.end()) {
                const FunctionInfo& info = it->second;
                ADDRINT offset = info.rtnAddr - info.imgLow;
                dumpFile << "\t+0x" << std::hex << offset << std::dec
                         << "\t" << (info.srcFile.empty() ? "??" : info.srcFile)
                         << "\t" << info.rtnName
                         << "\t" << info.srcLine
                         << "\n";
            }
        }
        dumpFile.close();
    }

    // Update lookup file (include suffix to match log filename)
    if (LookupFile.is_open()) {
        LookupFile << ProcessSuffix << DumpCount << ";" << dumpId << std::endl;
        LookupFile.flush();
    }

    // Reset coverage for next test segment
    CurrentTestFunctions.clear();
}

/* ===================================================================== */
/* Analysis Routines - Called at runtime                                 */
/* ===================================================================== */

// Called before every function execution
static VOID FunctionEntry(ADDRINT rtnAddr, const char* rtnName,
                          const char* imgName, ADDRINT imgLow,
                          UINT32 rtnSize, const char* srcFile, INT32 srcLine)
{
    std::lock_guard<std::mutex> guard(TraceLock);

    CallCount++;

    // In runtime_dump mode, track functions for current test segment
    if (KnobRuntimeDump.Value()) {
        CurrentTestFunctions.insert(rtnAddr);
    }

    // If not logging all calls, skip if we've seen this function
    if (!KnobLogAllCalls.Value()) {
        if (SeenFunctions.count(rtnAddr) > 0) {
            return;
        }
        SeenFunctions.insert(rtnAddr);
    }

    // Skip trace output if in runtime_dump mode (we only want per-test logs)
    if (KnobRuntimeDump.Value()) {
        return;
    }

    ADDRINT rtnEnd = rtnAddr + rtnSize;
    ADDRINT offsetStart = rtnAddr - imgLow;
    ADDRINT offsetEnd = rtnEnd - imgLow;

    // Format: call# | image | symbol | start_addr | end_addr | offset_range | source:line
    TraceFile << CallCount << " | "
              << BaseName(imgName) << " | "
              << rtnName << " | "
              << "0x" << std::hex << rtnAddr << " | "
              << "0x" << rtnEnd << " | "
              << "+0x" << offsetStart << "-0x" << offsetEnd << std::dec << " | "
              << (srcFile[0] ? srcFile : "??") << ":" << srcLine
              << std::endl;
}

/* ===================================================================== */
/* Instrumentation Routines - Called at instrumentation time             */
/* ===================================================================== */

// Called for every routine (function) found in the binary
static VOID InstrumentRoutine(RTN rtn, VOID* v)
{
    if (!RTN_Valid(rtn))
        return;

    // Get image information
    IMG img = IMG_FindByAddress(RTN_Address(rtn));
    if (!IMG_Valid(img))
        return;

    std::string imgName = IMG_Name(img);

    // Filter: main executable only if -libs 0
    if (!KnobIncludeLibs.Value() && !IMG_IsMainExecutable(img))
        return;

    // Filter: exclude images matching -exclude patterns
    if (ShouldExcludeImage(imgName))
        return;

    // Filter: by image name substring if specified
    if (!KnobFilterImage.Value().empty()) {
        if (imgName.find(KnobFilterImage.Value()) == std::string::npos)
            return;
    }

    // Get routine information
    std::string rtnName = RTN_Name(rtn);
    ADDRINT rtnAddr = RTN_Address(rtn);
    UINT32 rtnSize = RTN_Size(rtn);
    ADDRINT imgLow = IMG_LowAddress(img);

    // Try to get source location (requires debug info)
    std::string srcFile;
    INT32 srcLine = 0;
    INT32 srcColumn = 0;

    PIN_GetSourceLocation(rtnAddr, &srcColumn, &srcLine, &srcFile);

    // In runtime_dump mode, store metadata for later dump
    if (KnobRuntimeDump.Value()) {
        FunctionInfo info;
        info.imgName = BaseName(imgName);
        info.imgPath = imgName;
        info.rtnName = rtnName;
        info.srcFile = srcFile;
        info.rtnAddr = rtnAddr;
        info.imgLow = imgLow;
        info.rtnSize = rtnSize;
        info.srcLine = srcLine;
        FunctionMetadata[rtnAddr] = info;
    }

    // Make copies for the analysis routine (strings need to persist)
    const char* rtnNameCopy = strdup(rtnName.c_str());
    const char* imgNameCopy = strdup(imgName.c_str());
    const char* srcFileCopy = strdup(srcFile.c_str());

    // Insert call to FunctionEntry at routine entry
    RTN_Open(rtn);

    RTN_InsertCall(rtn, IPOINT_BEFORE, (AFUNPTR)FunctionEntry,
                   IARG_ADDRINT, rtnAddr,
                   IARG_PTR, rtnNameCopy,
                   IARG_PTR, imgNameCopy,
                   IARG_ADDRINT, imgLow,
                   IARG_UINT32, rtnSize,
                   IARG_PTR, srcFileCopy,
                   IARG_UINT32, srcLine,
                   IARG_END);

    RTN_Close(rtn);
}

// Called when a new image (executable or library) is loaded
static VOID ImageLoad(IMG img, VOID* v)
{
    std::string imgName = IMG_Name(img);
    ADDRINT low = IMG_LowAddress(img);
    ADDRINT high = IMG_HighAddress(img);

    // Track main executable info
    if (IMG_IsMainExecutable(img)) {
        MainExePath = imgName;
        MainExeName = BaseName(imgName);
    }

    if (!KnobRuntimeDump.Value()) {
        TraceFile << "# IMAGE LOADED: " << imgName
                  << " [0x" << std::hex << low << " - 0x" << high << "]"
                  << std::dec << std::endl;
    }

    // In runtime_dump mode, look for our marker function
    if (KnobRuntimeDump.Value()) {
        RTN rtn = RTN_FindByName(img, "pin_rts_dump_coverage");
        if (RTN_Valid(rtn)) {
            RTN_Open(rtn);
            // Intercept the call and extract the first argument (dump_id string)
            RTN_InsertCall(rtn, IPOINT_BEFORE, (AFUNPTR)HandleCoverageDump,
                           IARG_FUNCARG_ENTRYPOINT_VALUE, 0,  // First arg = dump_id pointer
                           IARG_END);
            RTN_Close(rtn);
        }
    }
}

// Called when program exits
static VOID Fini(INT32 code, VOID* v)
{
    if (KnobRuntimeDump.Value()) {
        // Close lookup file
        if (LookupFile.is_open()) {
            LookupFile.close();
        }
    } else {
        TraceFile << "# ========================================" << std::endl;
        TraceFile << "# Total function calls: " << CallCount << std::endl;
        TraceFile << "# Unique functions seen: " << SeenFunctions.size() << std::endl;
        TraceFile << "# ========================================" << std::endl;
        TraceFile.close();
    }
}

/* ===================================================================== */
/* Usage/Help                                                            */
/* ===================================================================== */

/* ===================================================================== */
/* Child Process Handling                                                */
/* ===================================================================== */

// Called before a child process is created (fork/exec)
// Return TRUE to inject Pin into the child, FALSE to let it run natively
static BOOL FollowChildProcess(CHILD_PROCESS childProcess, VOID* v)
{
    if (!KnobFollowChild.Value()) {
        return FALSE;  // Don't follow child processes
    }

    // Get info about the child
    OS_PROCESS_ID childPid = CHILD_PROCESS_GetId(childProcess);

    std::cerr << "[functrace] Following child process PID " << childPid << std::endl;

    return TRUE;  // Inject Pin into the child process
}

/* ===================================================================== */
/* Usage/Help                                                            */
/* ===================================================================== */

static INT32 Usage()
{
    std::cerr << "Function Trace Pin Tool" << std::endl;
    std::cerr << std::endl;
    std::cerr << "Traces all function calls and dumps metadata." << std::endl;
    std::cerr << std::endl;
    std::cerr << "Test mode (for unit test coverage):" << std::endl;
    std::cerr << "  -runtime_dump     Enable per-test coverage dumps" << std::endl;
    std::cerr << "  -logdir <dir>     Directory for per-test log files" << std::endl;
    std::cerr << "  -follow_child     Follow child processes (fork/exec)" << std::endl;
    std::cerr << std::endl;
    std::cerr << KNOB_BASE::StringKnobSummary() << std::endl;
    return -1;
}

/* ===================================================================== */
/* Main                                                                  */
/* ===================================================================== */

int main(int argc, char* argv[])
{
    // Initialize Pin and symbol processing
    PIN_InitSymbols();

    if (PIN_Init(argc, argv)) {
        return Usage();
    }

    // Runtime dump mode setup
    if (KnobRuntimeDump.Value()) {
        // Create log directory
        if (!EnsureDirectory(KnobLogDir.Value())) {
            std::cerr << "Error: Could not create log directory "
                      << KnobLogDir.Value() << std::endl;
            return 1;
        }

        // Set process suffix for unique filenames when following children
        if (KnobFollowChild.Value()) {
            ProcessSuffix = "pid" + std::to_string(PIN_GetPid()) + "_";
        } else {
            ProcessSuffix = "";
        }

        // Open lookup file (append mode when following children to collect all entries)
        std::string lookupPath = KnobLogDir.Value() + "/dump-lookup.log";
        std::ios_base::openmode mode = KnobFollowChild.Value() ?
            (std::ios::out | std::ios::app) : std::ios::out;
        LookupFile.open(lookupPath, mode);
        if (!LookupFile.is_open()) {
            std::cerr << "Error: Could not open lookup file "
                      << lookupPath << std::endl;
            return 1;
        }
    } else {
        // Standard mode - open output file
        TraceFile.open(KnobOutputFile.Value().c_str());
        if (!TraceFile.is_open()) {
            std::cerr << "Error: Could not open output file "
                      << KnobOutputFile.Value() << std::endl;
            return 1;
        }

        // Write header
        TraceFile << "# Function Trace Output" << std::endl;
        TraceFile << "# Format: call# | image | symbol | start_addr | end_addr | offset_range | source:line" << std::endl;
        TraceFile << "# ========================================" << std::endl;
    }

    // Register callbacks
    IMG_AddInstrumentFunction(ImageLoad, 0);
    RTN_AddInstrumentFunction(InstrumentRoutine, 0);
    PIN_AddFiniFunction(Fini, 0);

    // Register child process callback if enabled
    if (KnobFollowChild.Value()) {
        PIN_AddFollowChildProcessFunction(FollowChildProcess, 0);
    }

    // Start the program
    PIN_StartProgram();

    return 0;
}
