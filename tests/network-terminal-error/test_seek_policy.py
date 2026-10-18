#!/usr/bin/env python3
"""Mutation controls for seek source-audit branches; not runtime evidence."""

import unittest

from seek_policy import check_seek_ownership, ordered


TEARDOWN = """
static HRESULT WINAPI media_source_Shutdown()
{
    winedmo_demuxer_set_cancelled(source->demuxer, TRUE);
    WaitForSingleObject(source->demux_thread, INFINITE);
    winedmo_demuxer_destroy(&source->demuxer);
}
static const IMFMediaSourceVtbl vtbl;
static HRESULT media_source_create()
{
    winedmo_demuxer_set_cancelled(object->demuxer, TRUE);
    WaitForSingleObject(object->demux_thread, INFINITE);
    winedmo_demuxer_destroy(&object->demuxer);
}
static HRESULT result_entry_create();
"""
SERIALIZED = """
static HRESULT media_source_start()
{
        source->demux_seek_pending = true;
        LeaveCriticalSection(&source->cs);
        EnterCriticalSection(&source->demuxer_cs);
        EnterCriticalSection(&source->cs);
        if (FAILED(seek_error = media_source_get_demux_error(source)))
            status = STATUS_SUCCESS;
        else if (source->state == SOURCE_SHUTDOWN || source->demux_thread_shutdown)
            status = STATUS_CANCELLED;
        else
        {
            LeaveCriticalSection(&source->cs);
            status = winedmo_demuxer_seek(source->demuxer, position->hVal.QuadPart);
            EnterCriticalSection(&source->cs);
            if (!status && (source->state == SOURCE_SHUTDOWN
                    || source->demux_thread_shutdown))
                status = STATUS_CANCELLED;
        }
        source->demux_seek_pending = false;
        WakeAllConditionVariable(&source->work_cv);
        LeaveCriticalSection(&source->demuxer_cs);
}
static HRESULT media_source_pause();
"""
LEGACY = """
static HRESULT media_source_start()
{
    winedmo_demuxer_set_cancelled(source->demuxer, TRUE);
    EnterCriticalSection(&source->demuxer_cs);
    winedmo_demuxer_set_cancelled(source->demuxer, FALSE);
    winedmo_demuxer_seek(source->demuxer, position->hVal.QuadPart);
}
static HRESULT media_source_pause();
"""


class SeekPolicyTests(unittest.TestCase):
    def reject(self, source=SERIALIZED, unix="", teardown=TEARDOWN):
        with self.assertRaises(ValueError):
            check_seek_ownership(teardown + source, unix)

    def test_both_complete_policies(self):
        self.assertEqual(check_seek_ownership(TEARDOWN + SERIALIZED, ""), "serialized")
        self.assertEqual(check_seek_ownership(
            TEARDOWN + LEGACY, "BOOL cancelled_read_pending_recovery;"), "interrupt-reuse")

    def test_order_consumes_distinct_repeated_terms(self):
        ordered("lock; seek; lock;", "lock;", "seek;", "lock;")
        with self.assertRaises(ValueError):
            ordered("lock; seek;", "lock;", "seek;", "lock;")

    def test_teardown_must_cancel_before_join(self):
        cancel = "winedmo_demuxer_set_cancelled(source->demuxer, TRUE);"
        join = "WaitForSingleObject(source->demux_thread, INFINITE);"
        self.reject(teardown=TEARDOWN.replace(cancel, "").replace(join, join + cancel))

    def test_failed_constructor_must_join_before_destroy(self):
        self.reject(teardown=TEARDOWN.replace(
            "WaitForSingleObject(object->demux_thread, INFINITE);", ""))

    def test_legacy_cannot_lose_recovery(self):
        self.reject(source=LEGACY)

    def test_legacy_cannot_lose_reset(self):
        self.reject(source=LEGACY.replace(
            "winedmo_demuxer_set_cancelled(source->demuxer, FALSE);", ""),
            unix="BOOL cancelled_read_pending_recovery;")

    def test_pending_precedes_demux_wait(self):
        pending = "source->demux_seek_pending = true;"
        lock = "EnterCriticalSection(&source->demuxer_cs);"
        self.reject(SERIALIZED.replace(pending, "").replace(lock, lock + pending))

    def test_source_mutex_must_be_released_before_demux_wait(self):
        self.reject(SERIALIZED.replace("LeaveCriticalSection(&source->cs);", "", 1))

    def test_prior_terminal_error_check_is_mandatory(self):
        self.reject(SERIALIZED.replace("media_source_get_demux_error(source)", "S_OK"))

    def test_shutdown_checked_before_and_after_native_seek(self):
        for number in (1, 2):
            before, after = SERIALIZED.rsplit("source->state == SOURCE_SHUTDOWN", 1)
            changed = (before + "FALSE" + after if number == 2 else
                       SERIALIZED.replace("source->state == SOURCE_SHUTDOWN", "FALSE", 1))
            self.reject(changed)

    def test_pending_has_common_clear_wake_and_unlock(self):
        for term in ("source->demux_seek_pending = false;",
                     "WakeAllConditionVariable(&source->work_cv);",
                     "LeaveCriticalSection(&source->demuxer_cs);"):
            self.reject(SERIALIZED.replace(term, ""))

    def test_pending_cannot_return_or_goto_around_cleanup(self):
        for escape in ("return E_FAIL;", "goto done;"):
            self.reject(SERIALIZED.replace("status = STATUS_SUCCESS;", escape))

    def test_no_additional_cancellation_or_reset(self):
        for call in ("winedmo_demuxer_set_cancelled(other->demuxer, TRUE);",
                     "winedmo_demuxer_set_cancelled(source->demuxer, FALSE);"):
            self.reject(teardown=TEARDOWN + call)

    def test_no_unreachable_recovery_latch(self):
        self.reject(unix="BOOL cancelled_read_pending_recovery;")

    def test_no_error_or_eof_clear(self):
        for statement in ("pb->error = 0;", "demuxer->ctx->pb->eof_reached = 0;"):
            self.reject(unix=statement)


if __name__ == "__main__":
    unittest.main()
