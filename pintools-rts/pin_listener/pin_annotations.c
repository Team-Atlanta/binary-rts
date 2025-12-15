/*
 * pin_annotations.c - Implementation of Pin marker functions
 *
 * These are intentionally minimal - the Pin tool intercepts calls to
 * these functions and extracts their arguments. The actual function
 * body doesn't need to do anything.
 */

#include "pin_annotations.h"

/*
 * Marker function for coverage dumps.
 *
 * The noinline attribute prevents the compiler from inlining this,
 * ensuring Pin can find and instrument the function by name.
 *
 * The used attribute prevents the linker from removing it as unused.
 *
 * The asm volatile prevents the compiler from optimizing away the
 * function body entirely.
 */
__attribute__((noinline, used))
void pin_rts_dump_coverage(const char* dump_id)
{
    /* Prevent compiler from optimizing this away */
    __asm__ volatile("" : : "r"(dump_id) : "memory");
}
