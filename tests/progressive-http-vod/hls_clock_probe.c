/* SPDX-License-Identifier: BSD-3-Clause
 * Focused MediaEngine playback/seek check with software frame consumption.
 * Not a DXGI/VR renderer or a remote-service test. Use run_hls_clock.py only.
 */
#define COBJMACROS
#include <windows.h>
#include <stdio.h>
#include <math.h>
#include <mfapi.h>
#include <mfmediaengine.h>
#include <mferror.h>
#include <wincodec.h>
#include <dxgiformat.h>

struct callback
{
    IMFMediaEngineNotify iface;
    LONG refs, loaded, errors, seeks, error_code, extended_error;
};

static HRESULT WINAPI query(IMFMediaEngineNotify *iface, REFIID iid, void **obj)
{
    if (!obj) return E_POINTER;
    *obj = NULL;
    if (!IsEqualIID(iid, &IID_IUnknown) && !IsEqualIID(iid, &IID_IMFMediaEngineNotify))
        return E_NOINTERFACE;
    *obj = iface;
    IMFMediaEngineNotify_AddRef(iface);
    return S_OK;
}

static ULONG WINAPI addref(IMFMediaEngineNotify *iface)
{
    return InterlockedIncrement(&((struct callback *)iface)->refs);
}

static ULONG WINAPI release(IMFMediaEngineNotify *iface)
{
    return InterlockedDecrement(&((struct callback *)iface)->refs);
}

static HRESULT WINAPI notify(IMFMediaEngineNotify *iface, DWORD event, DWORD_PTR p1, DWORD p2)
{
    struct callback *cb = (struct callback *)iface;
    printf("event=%lu\n", (unsigned long)event);
    fflush(stdout);
    if (event == MF_MEDIA_ENGINE_EVENT_NOTIFYSTABLESTATE) SetEvent((HANDLE)p1);
    if (event == MF_MEDIA_ENGINE_EVENT_CANPLAY) InterlockedExchange(&cb->loaded, 1);
    if (event == MF_MEDIA_ENGINE_EVENT_SEEKED) InterlockedIncrement(&cb->seeks);
    if (event == MF_MEDIA_ENGINE_EVENT_ERROR)
    {
        InterlockedExchange(&cb->error_code, (LONG)p1);
        InterlockedExchange(&cb->extended_error, (LONG)p2);
        InterlockedIncrement(&cb->errors);
        printf("event=error code=%llu detail=%08lx\n", (unsigned long long)p1, (unsigned long)p2);
        fflush(stdout);
    }
    return S_OK;
}

static IMFMediaEngineNotifyVtbl vtbl = {query, addref, release, notify};

static LONG read_counter(LONG *value)
{
    return InterlockedCompareExchange(value, 0, 0);
}

static BOOL valid_video_size(UINT width, UINT height)
{
    return width && height && width <= 1920 && height <= 1080;
}

static BOOL get_bitmap_rect(IWICBitmap *bitmap, RECT *rect)
{
    UINT width, height;

    if (FAILED(IWICBitmap_GetSize(bitmap, &width, &height))) return FALSE;
    *rect = (RECT){0, 0, width, height};
    return TRUE;
}

static BOOL progress(IMFMediaEngine *engine, IWICBitmap *bitmap, struct callback *cb,
        unsigned phase, double target)
{
    ULONGLONG start = GetTickCount64(), next = start;
    LONGLONG pts, first = MINLONGLONG, last = MINLONGLONG;
    DWORD frames = 0, transfers = 0;
    RECT rect;
    double clock = 0;
    BOOL success = FALSE;
    if (!get_bitmap_rect(bitmap, &rect)) return FALSE;
    while (GetTickCount64() - start < 10000 && !read_counter(&cb->errors))
    {
        HRESULT hr = IMFMediaEngine_OnVideoStreamTick(engine, &pts);
        clock = IMFMediaEngine_GetCurrentTime(engine);
        if (hr == S_OK && pts != last)
        {
            if (first == MINLONGLONG) first = pts;
            last = pts;
            ++frames;
            hr = IMFMediaEngine_TransferVideoFrame(engine, (IUnknown *)bitmap, NULL, &rect, NULL);
            if (FAILED(hr))
            {
                printf("phase=%u transfer_error=%08lx\n", phase, (unsigned long)hr);
                break;
            }
            ++transfers;
        }
        if (GetTickCount64() >= next)
        {
            printf("phase=%u ms=%llu clock=%.6f pts=%lld frames=%lu seeking=%d paused=%d\n",
                    phase, (unsigned long long)(GetTickCount64() - start), clock,
                    (long long)last, (unsigned long)frames,
                    IMFMediaEngine_IsSeeking(engine), IMFMediaEngine_IsPaused(engine));
            fflush(stdout);
            next = GetTickCount64() + 500;
        }
        if (isfinite(clock) && clock >= target + 2 && clock < target + 8 &&
                transfers >= 30 && first != MINLONGLONG && last - first >= 20000000 &&
                last >= (LONGLONG)((target + 2) * 10000000) &&
                !IMFMediaEngine_IsSeeking(engine) && !IMFMediaEngine_IsPaused(engine))
        {
            success = TRUE;
            break;
        }
        Sleep(16);
    }
    printf("phase=%u pass=%d clock=%.6f first=%lld last=%lld frames=%lu transfers=%lu seeks=%ld\n",
            phase, success, clock, (long long)first, (long long)last,
            (unsigned long)frames, (unsigned long)transfers, read_counter(&cb->seeks));
    fflush(stdout);
    return success;
}

static BOOL consume_for(IMFMediaEngine *engine, IWICBitmap *bitmap, struct callback *cb,
        DWORD duration)
{
    RECT rect;
    ULONGLONG until = GetTickCount64() + duration;
    LONGLONG pts;
    if (!get_bitmap_rect(bitmap, &rect)) return FALSE;
    do
    {
        HRESULT hr = IMFMediaEngine_OnVideoStreamTick(engine, &pts);
        if (FAILED(hr))
        {
            printf("stage=consume tick_error=%08lx\n", (unsigned long)hr);
            fflush(stdout);
            return FALSE;
        }
        if (hr == S_OK)
        {
            hr = IMFMediaEngine_TransferVideoFrame(engine, (IUnknown *)bitmap, NULL, &rect, NULL);
            if (FAILED(hr))
            {
                printf("stage=consume transfer_error=%08lx\n", (unsigned long)hr);
                fflush(stdout);
                return FALSE;
            }
        }
        if (read_counter(&cb->errors)) return FALSE;
        Sleep(16);
    } while (GetTickCount64() < until);
    return TRUE;
}

/* A seek-bar cadence, not a frame-less API loop: keep consuming between
 * requests, including when the preceding seek has not completed. */
static BOOL seek_burst(IMFMediaEngine *engine, IWICBitmap *bitmap, struct callback *cb,
        unsigned wave, BOOL scrub)
{
    /* Sanitized HEVC source-seek positions and inter-call delays from the
     * 2026-09-12 co-test. They are not an assertion of the world's UI calls. */
    static const double targets[] = {10.4226732, 11.652667, 28.5403919, 12.4202384,
        23.1096343, 7.5467562, 21.5236244, 14.2446002, 31.1200733, 12.778779};
    static const DWORD delays[] = {2228, 973, 729, 660, 580, 770, 817, 771, 1110, 650};
    unsigned i;
    for (i = 0; i < sizeof(targets) / sizeof(targets[0]); ++i)
    {
        BOOL overlap = IMFMediaEngine_IsSeeking(engine);
        HRESULT hr;
        if (scrub)
        {
            if (FAILED(IMFMediaEngine_Pause(engine))) return FALSE;
            if (!consume_for(engine, bitmap, cb, 50)) return FALSE;
        }
        hr = IMFMediaEngine_SetCurrentTime(engine, targets[i]);
        printf("wave=%u seek=%u target=%.3f overlap=%d hr=%08lx\n",
                wave, i, targets[i], overlap, (unsigned long)hr);
        fflush(stdout);
        if (FAILED(hr)) return FALSE;
        if (scrub)
        {
            if (!consume_for(engine, bitmap, cb, 50)) return FALSE;
            if (FAILED(IMFMediaEngine_Play(engine))) return FALSE;
        }
        if (!consume_for(engine, bitmap, cb, delays[i])) return FALSE;
    }
    return progress(engine, bitmap, cb, wave, targets[i - 1]);
}

/* Concurrent ordinary controls, not an imitation of a particular world's
 * scripts. The parent runner bounds even a call which never returns. */
struct controls { IMFMediaEngine *engine; LONG stop; unsigned calls; ULONGLONG max_ms; BOOL failed; };
static DWORD WINAPI control_thread(void *arg)
{
    struct controls *c = arg;
    static const double volumes[] = {1.0, 0.5, 0.01, 0.0};
    if (FAILED(CoInitializeEx(NULL, COINIT_MULTITHREADED))) { c->failed = TRUE; return 1; }
    for (unsigned i = 0; i < 160 && !read_counter(&c->stop); ++i)
    {
        ULONGLONG start = GetTickCount64(), elapsed;
        HRESULT hr;
        double clock;
        printf("control=%u begin=volume-mute-clock\n", i);
        fflush(stdout);
        hr = IMFMediaEngine_SetVolume(c->engine, volumes[i % 4]);
        if (SUCCEEDED(hr)) hr = IMFMediaEngine_SetMuted(c->engine, (i / 10) % 2);
        clock = IMFMediaEngine_GetCurrentTime(c->engine);
        elapsed = GetTickCount64() - start;
        if (elapsed > c->max_ms) c->max_ms = elapsed;
        ++c->calls;
        printf("control=%u end_ms=%llu hr=%08lx clock=%.6f\n", i,
                (unsigned long long)elapsed, (unsigned long)hr, clock);
        fflush(stdout);
        if (FAILED(hr) || !isfinite(clock) || elapsed >= 1000) { c->failed = TRUE; break; }
        Sleep(80);
    }
    CoUninitialize();
    return c->failed;
}

int wmain(int argc, WCHAR **argv)
{
    struct callback cb = {{&vtbl}, 1, 0, 0, 0, 0, 0};
    IMFMediaEngineClassFactory *factory = NULL;
    IMFMediaEngine *engine = NULL;
    IMFAttributes *attrs = NULL;
    IWICImagingFactory *wic = NULL;
    IWICBitmap *bitmap = NULL;
    BSTR url = NULL;
    ULONGLONG start;
    double targets[] = {25.0, 8.0};
    unsigned i;
    DWORD width, height;
    HRESULT hr;
    int result = 1;
    BOOL scrub = argc == 3 && !wcscmp(argv[2], L"--seek-scrub");
    BOOL stress = scrub || (argc == 3 && !wcscmp(argv[2], L"--seek-stress"));
    BOOL filter_error = argc == 3 && !wcscmp(argv[2], L"--expect-filter-error");
    BOOL recovery = argc == 3 && !wcscmp(argv[2], L"--filter-recovery-seek");
    BOOL control = argc == 3 && !wcscmp(argv[2], L"--control-stress");
    BOOL live = argc == 3 && !wcscmp(argv[2], L"--rtsp-live");
    BOOL tailseek = argc == 3 && !wcscmp(argv[2], L"--http-tail-seek");
    if (argc < 2 || (argc != 2 && !stress && !filter_error && !live && !recovery && !control && !tailseek)) return 2;
    if (live ? wcscmp(argv[1], L"rtspt://127.0.0.1:18555/fixture") :
            wcsncmp(argv[1], L"http://127.0.0.1:", 17)) return 2;
    if (FAILED(CoInitializeEx(NULL, COINIT_MULTITHREADED))) return 3;
    if (FAILED(MFStartup(MF_VERSION, MFSTARTUP_FULL))) return 3;
#define CHECK(call) do { hr = (call); if (FAILED(hr)) { printf("line=%d hr=%08lx\n", __LINE__, (unsigned long)hr); fflush(stdout); goto done; } } while (0)
    CHECK(CoCreateInstance(&CLSID_MFMediaEngineClassFactory, NULL, CLSCTX_INPROC_SERVER,
            &IID_IMFMediaEngineClassFactory, (void **)&factory));
    CHECK(MFCreateAttributes(&attrs, 2));
    CHECK(IMFAttributes_SetUnknown(attrs, &MF_MEDIA_ENGINE_CALLBACK, (IUnknown *)&cb.iface));
    CHECK(IMFAttributes_SetUINT32(attrs, &MF_MEDIA_ENGINE_VIDEO_OUTPUT_FORMAT, DXGI_FORMAT_B8G8R8X8_UNORM));
    CHECK(IMFMediaEngineClassFactory_CreateInstance(factory, 0, attrs, &engine));
    CHECK(CoCreateInstance(&CLSID_WICImagingFactory, NULL, CLSCTX_INPROC_SERVER,
            &IID_IWICImagingFactory, (void **)&wic));
    url = SysAllocString(argv[1]);
    if (!url) goto done;
    CHECK(IMFMediaEngine_SetSource(engine, url));
    printf("stage=source-set\n");
    fflush(stdout);
    start = GetTickCount64();
    while (!read_counter(&cb.loaded) && !read_counter(&cb.errors) && GetTickCount64() - start < 15000) Sleep(10);
    printf("stage=ready-wait-ended loaded=%ld errors=%ld\n", read_counter(&cb.loaded), read_counter(&cb.errors));
    fflush(stdout);
    printf("ready=%ld errors=%ld audio=%d video=%d\n", read_counter(&cb.loaded), read_counter(&cb.errors),
            IMFMediaEngine_HasAudio(engine), IMFMediaEngine_HasVideo(engine));
    fflush(stdout);
    if (!read_counter(&cb.loaded) || read_counter(&cb.errors) || !IMFMediaEngine_HasAudio(engine) || !IMFMediaEngine_HasVideo(engine)) goto done;
    CHECK(IMFMediaEngine_GetNativeVideoSize(engine, &width, &height));
    printf("native_size=%lux%lu\n", (unsigned long)width, (unsigned long)height);
    fflush(stdout);
    if (!valid_video_size(width, height)) goto done;
    CHECK(IWICImagingFactory_CreateBitmap(wic, width, height, &GUID_WICPixelFormat32bppBGR,
            WICBitmapCacheOnLoad, &bitmap));
    CHECK(IMFMediaEngine_Play(engine));
    if (!progress(engine, bitmap, &cb, 0, 0)) goto done;
    if (live)
    {
        if (!consume_for(engine, bitmap, &cb, 10000)) goto done;
        if (!progress(engine, bitmap, &cb, 1, IMFMediaEngine_GetCurrentTime(engine))) goto done;
        InterlockedExchange(&cb.loaded, 0);
        CHECK(IMFMediaEngine_SetSource(engine, url));
        start = GetTickCount64();
        while (!read_counter(&cb.loaded) && !read_counter(&cb.errors) && GetTickCount64() - start < 15000) Sleep(10);
        if (!read_counter(&cb.loaded) || read_counter(&cb.errors)) goto done;
        CHECK(IMFMediaEngine_Play(engine));
        if (!progress(engine, bitmap, &cb, 2, 0)) goto done;
    }
    else if (tailseek)
    {
        double duration = IMFMediaEngine_GetDuration(engine);
        if (!isfinite(duration) || duration < 12 || duration > 120) goto done;
        for (i = 1; i <= 3; ++i)
        {
            CHECK(IMFMediaEngine_SetCurrentTime(engine, duration - 0.5));
            start = GetTickCount64();
            while (!IMFMediaEngine_IsEnded(engine) && GetTickCount64() - start < 8000)
                if (!consume_for(engine, bitmap, &cb, 16)) goto done;
            printf("tail=%u ended=%d clock=%.6f duration=%.6f\n", i,
                    IMFMediaEngine_IsEnded(engine), IMFMediaEngine_GetCurrentTime(engine), duration);
            fflush(stdout);
            if (!IMFMediaEngine_IsEnded(engine) || read_counter(&cb.errors)) goto done;
            CHECK(IMFMediaEngine_SetCurrentTime(engine, 5.0));
            CHECK(IMFMediaEngine_Play(engine));
            if (!progress(engine, bitmap, &cb, i, 5.0)) goto done;
        }
    }
    else if (control)
    {
        struct controls c = {engine, 0, 0, 0, FALSE};
        HANDLE thread = CreateThread(NULL, 0, control_thread, &c, 0, NULL);
        BOOL consumed;
        if (!thread) goto done;
        consumed = consume_for(engine, bitmap, &cb, 15000);
        InterlockedExchange(&c.stop, 1);
        if (WaitForSingleObject(thread, 2000) != WAIT_OBJECT_0)
        {
            printf("controls=timeout\n");
            fflush(stdout);
            ExitProcess(124); /* do not free objects still used by blocked worker */
        }
        CloseHandle(thread);
        printf("controls=%u max_ms=%llu failed=%d\n", c.calls,
                (unsigned long long)c.max_ms, c.failed);
        fflush(stdout);
        if (!consumed || c.failed || c.calls != 160) goto done;
        CHECK(IMFMediaEngine_SetMuted(engine, FALSE));
        CHECK(IMFMediaEngine_SetVolume(engine, 1.0));
        if (!progress(engine, bitmap, &cb, 1, IMFMediaEngine_GetCurrentTime(engine))) goto done;
    }
    else if (recovery)
    {
        BOOL advanced;
        consume_for(engine, bitmap, &cb, 10000);
        printf("recovery=before errors=%ld ended=%d\n", read_counter(&cb.errors), IMFMediaEngine_IsEnded(engine));
        fflush(stdout);
        if (!((read_counter(&cb.errors) == 0 && IMFMediaEngine_IsEnded(engine)) ||
                (read_counter(&cb.errors) == 1 && read_counter(&cb.error_code) == MF_MEDIA_ENGINE_ERR_DECODE &&
                 (HRESULT)read_counter(&cb.extended_error) == MF_E_INVALID_STREAM_DATA)))
        {
            printf("recovery=missing-expected-failure\n");
            fflush(stdout);
            goto done;
        }
        /* Reset observation only, not any MediaEngine/source state. */
        InterlockedExchange(&cb.errors, 0);
        hr = IMFMediaEngine_SetCurrentTime(engine, 8.0);
        printf("recovery=seek hr=%08lx\n", (unsigned long)hr);
        fflush(stdout);
        if (FAILED(hr)) goto done;
        hr = IMFMediaEngine_Play(engine);
        printf("recovery=play hr=%08lx\n", (unsigned long)hr);
        fflush(stdout);
        advanced = progress(engine, bitmap, &cb, 1, 8.0);
        if (FAILED(hr) || !advanced) goto done;
    }
    else if (filter_error)
    {
        WCHAR clean_url[512], *slash;
        consume_for(engine, bitmap, &cb, 10000);
        printf("filter_error errors=%ld code=%ld detail=%08lx ended=%d\n",
                read_counter(&cb.errors), read_counter(&cb.error_code),
                (unsigned long)read_counter(&cb.extended_error), IMFMediaEngine_IsEnded(engine));
        fflush(stdout);
        if (read_counter(&cb.errors) != 1 || read_counter(&cb.error_code) != MF_MEDIA_ENGINE_ERR_DECODE ||
                (HRESULT)read_counter(&cb.extended_error) != MF_E_INVALID_STREAM_DATA ||
                IMFMediaEngine_IsEnded(engine)) goto done;
        if (wcslen(argv[1]) >= 480) goto done;
        wcscpy(clean_url, argv[1]);
        if (!(slash = wcsrchr(clean_url, '/'))) goto done;
        wcscpy(slash + 1, L"clean.mp4");
        SysFreeString(url);
        if (!(url = SysAllocString(clean_url))) goto done;
        InterlockedExchange(&cb.loaded, 0);
        InterlockedExchange(&cb.errors, 0);
        CHECK(IMFMediaEngine_SetSource(engine, url));
        start = GetTickCount64();
        while (!read_counter(&cb.loaded) && !read_counter(&cb.errors) && GetTickCount64() - start < 15000) Sleep(10);
        if (!read_counter(&cb.loaded) || read_counter(&cb.errors)) goto done;
        CHECK(IMFMediaEngine_Play(engine));
        if (!progress(engine, bitmap, &cb, 1, 0)) goto done;
    }
    else if (stress)
    {
        /* The first captured HEVC failure followed ordinary playback, not an
         * immediate seek at load. Allow the source/decoder queues to settle. */
        if (!consume_for(engine, bitmap, &cb, 18000)) goto done;
        for (i = 1; i <= 3; ++i)
            if (!seek_burst(engine, bitmap, &cb, i, scrub)) goto done;
    }
    else for (i = 0; i < sizeof(targets) / sizeof(targets[0]); ++i)
    {
        CHECK(IMFMediaEngine_SetCurrentTime(engine, targets[i]));
        if (!progress(engine, bitmap, &cb, i + 1, targets[i])) goto done;
    }
    result = 0;
done:
    printf("result=%d errors=%ld\n", result, read_counter(&cb.errors));
    fflush(stdout);
    if (engine) IMFMediaEngine_Shutdown(engine);
    if (bitmap) IWICBitmap_Release(bitmap);
    if (wic) IWICImagingFactory_Release(wic);
    if (engine) IMFMediaEngine_Release(engine);
    if (attrs) IMFAttributes_Release(attrs);
    if (factory) IMFMediaEngineClassFactory_Release(factory);
    SysFreeString(url);
    MFShutdown();
    CoUninitialize();
    return result;
}
