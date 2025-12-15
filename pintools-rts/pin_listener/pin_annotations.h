/*
 * pin_annotations.h - Marker functions for Pin tool instrumentation
 *
 * These functions are intercepted by the Pin tool to trigger coverage dumps.
 * The function bodies are intentionally minimal - Pin intercepts the call
 * and extracts the arguments before the function executes.
 *
 * Similar in concept to DynamoRIO's DYNAMORIO_ANNOTATE_LOG.
 */

#ifndef PIN_ANNOTATIONS_H
#define PIN_ANNOTATIONS_H

#ifdef __cplusplus
extern "C" {
#endif

/*
 * Signal the Pin tool to dump coverage for the current test segment.
 *
 * @param dump_id Identifier for this dump (e.g., "TestSuite.TestName___PASSED")
 *
 * The Pin tool intercepts this call and:
 * 1. Writes accumulated function coverage to a numbered log file
 * 2. Records the mapping from dump number to dump_id in lookup file
 * 3. Resets coverage tracking for the next test segment
 */
void pin_rts_dump_coverage(const char* dump_id);

#ifdef __cplusplus
}
#endif

#endif /* PIN_ANNOTATIONS_H */
