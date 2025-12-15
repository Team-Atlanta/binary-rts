# functrace - Pin Tool for Function Tracing

Traces all function calls and dumps metadata including symbol name, address range, and source location (if debug info available).

## Build

```bash
make PIN_ROOT=/path/to/pin-kit
```

Example:
```bash
make PIN_ROOT=/opt/pin-external-4.0-99633-g5ca9893f2-gcc-linux
```

## Usage

```bash
$PIN_ROOT/pin -t obj-intel64/functrace.so [options] -- ./your_program
```

### Options

| Option | Description |
|--------|-------------|
| `-o <file>` | Output file (default: `functrace.out`) |
| `-libs 0` | Only trace main executable, skip all libraries |
| `-all 1` | Log every call, not just unique functions |
| `-filter <str>` | Only trace images containing `<str>` |
| `-exclude <list>` | Comma-separated substrings to exclude (default: `libc.so,ld-linux,libm.so,libpthread,libdl.so,libstdc++,libc++`) |
| `-no-exclude 1` | Disable default exclusions, trace everything |

### Examples

```bash
# Default: traces app + non-system libs (excludes libc, ld-linux, etc.)
$PIN_ROOT/pin -t obj-intel64/functrace.so -- ./myapp

# Only main executable (skip all libraries)
$PIN_ROOT/pin -t obj-intel64/functrace.so -libs 0 -- ./myapp

# Trace everything including libc/ld-linux
$PIN_ROOT/pin -t obj-intel64/functrace.so -no-exclude 1 -- ./myapp

# Custom exclusion list
$PIN_ROOT/pin -t obj-intel64/functrace.so -exclude "libssl,libcrypto" -- ./myapp

# Filter to specific library only
$PIN_ROOT/pin -t obj-intel64/functrace.so -filter "libcrypto" -- ./myapp

# Custom output file
$PIN_ROOT/pin -t obj-intel64/functrace.so -o trace.log -- ./myapp
```

## Output Format

```
call# | image | symbol | start_addr | end_addr | offset_range | source:line
```

Example output:
```
772 | test_program | main | 0x55fa4e3e32ac | 0x55fa4e3e33f7 | +0x12ac-0x13f7 | test_program.c:30
810 | test_program | add | 0x55fa4e3e31a9 | 0x55fa4e3e31c0 | +0x11a9-0x11c0 | test_program.c:10
```

## Notes

- Source file and line number require debug symbols (`-g` flag when compiling)
- Without debug info, source shows as `??:0`
- Inlined functions are not visible (they don't exist at runtime)
