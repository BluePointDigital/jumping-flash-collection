"""Bounded diagnostic serialization for future collection preparations."""
from pathlib import Path
import hashlib


_RANGE_SIGNATURE = "static void handle_wtrace_ranges(int id, const char *json)"
_RANGE_BEFORE = "42af3cc68bd3bcb79f1a8039c7b5d5b7417d6bd9a68d83d9052bf5f05eb2acef"
_RANGE_AFTER = "b981b3cc7584ae3272965762ca826f14d68c9e3ed9c9b43fc8220cbcede9532a"
_RANGE_REPLACEMENT = r'''static void handle_wtrace_ranges(int id, const char *json)
{
    (void)json;
    enum { WTRACE_RANGE_ROW_CAP = 64, WTRACE_RANGE_JSON_OVERHEAD = 128 };
    int count = s_wtrace_range_count;
    if (count < 0 || count > WTRACE_MAX_RANGES) {
        send_err(id, "invalid wtrace range count");
        return;
    }

    /* Every row has fixed-width hexadecimal fields and a slot <= 63. */
    const size_t buf_sz = WTRACE_RANGE_JSON_OVERHEAD +
                          (size_t)count * WTRACE_RANGE_ROW_CAP;
    char *buf = (char *)malloc(buf_sz);
    if (!buf) { send_err(id, "oom"); return; }

    size_t pos = 0;
    int n = snprintf(buf + pos, buf_sz - pos,
                     "{\"id\":%d,\"ok\":true,\"count\":%d,\"ranges\":[", id, count);
    if (n < 0 || (size_t)n >= buf_sz - pos) goto overflow;
    pos += (size_t)n;
    for (int i = 0; i < count; i++) {
        n = snprintf(buf + pos, buf_sz - pos,
                     "%s{\"slot\":%d,\"lo\":\"0x%08X\",\"hi\":\"0x%08X\"}",
                     (i == 0) ? "" : ",", i,
                     s_wtrace_ranges[i].lo, s_wtrace_ranges[i].hi);
        if (n < 0 || (size_t)n >= buf_sz - pos) goto overflow;
        pos += (size_t)n;
    }
    n = snprintf(buf + pos, buf_sz - pos, "]}");
    if (n < 0 || (size_t)n >= buf_sz - pos) goto overflow;
    debug_server_send_line(buf);
    free(buf);
    return;

overflow:
    free(buf);
    send_err(id, "wtrace range response overflow");
}'''


def range_serializer_source(text):
    if text.count(_RANGE_SIGNATURE) != 1:
        raise ValueError("Expected one write-trace range serializer")
    start = text.index(_RANGE_SIGNATURE)
    end = text.find("\n}\n", start)
    if end < 0:
        raise ValueError("Write-trace serializer end changed")
    end += 2
    current = text[start:end]
    digest = hashlib.sha256(current.encode()).hexdigest()
    if digest == _RANGE_BEFORE:
        text = text[:start] + _RANGE_REPLACEMENT + text[end:]
    elif digest != _RANGE_AFTER:
        raise ValueError("Write-trace range serializer source drifted")
    old = '        send_err(id, "max ranges reached (8)"); return;'
    new = '''        char err[64];
        snprintf(err, sizeof(err), "max ranges reached (%d)", WTRACE_MAX_RANGES);
        send_err(id, err);
        return;'''
    if text.count(old) == 1 and new not in text:
        text = text.replace(old, new, 1)
    elif old in text or text.count(new) != 1:
        raise ValueError("Write-trace capacity error anchor drifted")
    return text


def patch_range_serializer(framework):
    path = Path(framework) / "runtime/src/debug_server.c"
    original = path.read_text(encoding="utf-8")
    candidate = range_serializer_source(original)
    if candidate != original:
        path.write_text(candidate, encoding="utf-8")


MARKER = "LUNA_AMBIENT_MEMORY_TRACE_DEFAULT_OFF_V2"
HOOK_SIGNATURE = "void debug_server_trace_write_check(uint32_t phys, uint32_t old_val,"
HOOK_BEFORE = "063baf47a8343b4ac1d4f5cf91a410a2bfd4cef1f874c62d679a804e5b8feb42"
HOOK_AFTER = "041b88f58c29c76c24438c5f7c26f06cbe3bb0b22c98a1fbce27297449089282"

HELPER = '''/* Ambient diagnostic tracing is opt-in; explicit range recording is separate. */
static int s_memory_trace_ambient = 0;
static int memory_trace_env_enabled(void) {
    const char *e = getenv("PSX_MEMORY_TRACE");
    if (!e || !*e) e = getenv("PSX_COLLECTION_DIAGNOSTICS");
    return e && *e && *e != '0' && strcmp(e, "false") != 0 && strcmp(e, "off") != 0;
}'''

AMBIENT_BODY = '''    /* Layer-1 fingerprints, catch-all rings, and title-default ranges are
     * ambient diagnostics. Keep them available with PSX_MEMORY_TRACE=1, but
     * avoid hashing/storing every guest write in ordinary emulation. */
    if (s_memory_trace_ambient) {
        if (is_card_critical_addr(phys)) card_trace_record(phys, old_val, new_val, width);
        fp_record_write(phys, new_val, g_debug_last_store_pc);
        wtrace_all_record(phys, new_val, width);
    }
    /* record_frame is an explicit one-frame diagnostic and remains independent
     * of the ambient switch. Its recorder cheaply returns unless armed. */
    if (s_rec_frame >= 0) {
        uint32_t ra = debug_cpu_ptr ? debug_cpu_ptr->gpr[31] : 0;
        if (phys < psx_ram_live_bytes())
            rec_event(REC_KIND_RAM_W, phys, new_val, g_debug_last_store_pc, ra);
        else if (phys >= 0x1F800000u && phys <= 0x1F8003FFu)
            rec_event(REC_KIND_SP_W, phys, new_val, g_debug_last_store_pc, ra);
    }
    /* Environment-specified boot/transition ranges and explicit wtrace_arm
     * continue to work. With ambient mode off, built-in default ranges are
     * cleared during init, so this remains a small/explicit filter. */
    if (s_wtrace_trans_range_count) wtrace_transition_record(phys, old_val, new_val, width);
    if (s_wtrace_boot_range_count) wtrace_boot_record(phys, old_val, new_val, width);
    if (s_wtrace_range_count == 0) return;
'''

DEFAULT_RESET = '''    /* The default address sets are title-specific ambient diagnostics.
     * Explicit PSX_WTRACE_BOOT_RANGES are applied after this reset and
     * therefore remain available when ambient tracing is off. */
    if (!s_memory_trace_ambient) {
        s_wtrace_range_count = 0;
        s_wtrace_boot_range_count = 0;
        s_wtrace_trans_range_count = 0;
    }
'''


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def function_span(text: str, signature: str) -> tuple[int, int]:
    if text.count(signature) != 1:
        raise ValueError(f"expected one function signature: {signature}")
    start = text.index(signature)
    brace = text.index("{", start)
    depth = 0
    for i in range(brace, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return start, i + 1
    raise ValueError(f"unterminated function: {signature}")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise ValueError(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


def validate_applied(text: str) -> None:
    # A marker alone is insufficient: validate the exact helper and the hook
    # body, plus the init/allocation/range-clear anchors and their ordering.
    if text.count(MARKER) != 1 or text.count(HELPER) != 1:
        raise ValueError("ambient trace marker/helper drift")
    a, b = function_span(text, HOOK_SIGNATURE)
    if digest(text[a:b]) != HOOK_AFTER:
        raise ValueError("ambient trace hook body drift")
    if text.count("s_memory_trace_ambient = memory_trace_env_enabled();") != 1:
        raise ValueError("ambient trace init assignment drift")
    allocation = """    /* The large catch-all ring is needed only when ambient tracing is on. */
    if (s_memory_trace_ambient && !s_wtrace_all) {
        s_wtrace_all = (WriteTraceAllEntry *)calloc(WRITE_TRACE_ALL_CAP,
                                                    sizeof(WriteTraceAllEntry));
    }
"""
    if text.count(allocation) != 1 or text.count(DEFAULT_RESET) != 1:
        raise ValueError("ambient allocation/default-range reset drift")
    for anchor in (
        "s_wtrace_range_count = 22;",
        "s_wtrace_range_count = 32;",
        'wtrace_apply_env_ranges(getenv("PSX_WTRACE_BOOT_RANGES"));',
    ):
        if text.count(anchor) != 1:
            raise ValueError(f"ambient range ordering anchor drift: {anchor}")
    p22 = text.index("s_wtrace_range_count = 22;")
    p32 = text.index("s_wtrace_range_count = 32;", p22)
    preset = text.index(DEFAULT_RESET)
    penv = text.index('wtrace_apply_env_ranges(getenv("PSX_WTRACE_BOOT_RANGES"));')
    if not p22 < p32 < preset < penv:
        raise ValueError("ambient default-clear ordering changed")


def ambient_memory_trace_source(text: str) -> str:
    if MARKER in text:
        validate_applied(text)
        return memory_fingerprint_guard_source(text)

    # Five independent source guards permit harmless prefix/presentation edits
    # while pinning the write path and the integration sites.
    global_anchor = "static uint32_t s_wtrace_all_head = 0;"
    init_anchor = "void debug_server_init(int port)\n{\n    if (port > 0) s_port = port;"
    alloc_anchor = """    /* Always-on catch-all wtrace ring (8 MB). Records EVERY RAM write
     * with lean fields (no register window). Sized for ~1 second of
     * coverage at typical Tomba write rates. */
    if (!s_wtrace_all) {
        s_wtrace_all = (WriteTraceAllEntry *)calloc(WRITE_TRACE_ALL_CAP,
                                                    sizeof(WriteTraceAllEntry));
    }
"""
    env_anchor = '    wtrace_apply_env_ranges(getenv("PSX_WTRACE_BOOT_RANGES"));'
    for name, anchor in (("ambient helper insertion", global_anchor),
                         ("init assignment", init_anchor),
                         ("catch-all allocation", alloc_anchor),
                         ("environment range application", env_anchor)):
        if text.count(anchor) != 1:
            raise ValueError(f"{name} source anchor drift: count={text.count(anchor)}")

    a, b = function_span(text, HOOK_SIGNATURE)
    hook = text[a:b]
    if digest(hook) != HOOK_BEFORE:
        raise ValueError(f"write-hook source drift: {digest(hook)}")
    old_body = '''    if (is_card_critical_addr(phys)) card_trace_record(phys, old_val, new_val, width);
    fp_record_write(phys, new_val, g_debug_last_store_pc);
    {
        uint32_t ra = debug_cpu_ptr ? debug_cpu_ptr->gpr[31] : 0;
        if (phys < psx_ram_live_bytes())
            rec_event(REC_KIND_RAM_W, phys, new_val, g_debug_last_store_pc, ra);
        else if (phys >= 0x1F800000u && phys <= 0x1F8003FFu)
            rec_event(REC_KIND_SP_W, phys, new_val, g_debug_last_store_pc, ra);
    }
    wtrace_all_record(phys, new_val, width);
    wtrace_transition_record(phys, old_val, new_val, width);
    wtrace_boot_record(phys, old_val, new_val, width);
    if (s_wtrace_range_count == 0) return;
'''
    hook_new = replace_once(hook, old_body, AMBIENT_BODY, "write-hook body")
    if digest(hook_new) != HOOK_AFTER:
        raise ValueError("transformed write-hook hash mismatch")
    text = text[:a] + hook_new + text[b:]

    text = replace_once(text, global_anchor, global_anchor + "\n" + HELPER,
                        "ambient helper insertion")
    text = replace_once(text, init_anchor,
                        init_anchor + "\n    s_memory_trace_ambient = memory_trace_env_enabled();",
                        "ambient init")
    text = replace_once(text, alloc_anchor, """    /* The large catch-all ring is needed only when ambient tracing is on. */
    if (s_memory_trace_ambient && !s_wtrace_all) {
        s_wtrace_all = (WriteTraceAllEntry *)calloc(WRITE_TRACE_ALL_CAP,
                                                    sizeof(WriteTraceAllEntry));
    }
""", "ambient ring allocation")
    text = replace_once(text, env_anchor, DEFAULT_RESET + env_anchor,
                        "ambient default-range reset")
    result = "/* " + MARKER + " */\n" + text
    validate_applied(result)
    return memory_fingerprint_guard_source(result)



def patch_ambient_memory_trace(framework):
    path = Path(framework) / "runtime/src/debug_server.c"
    original = path.read_text(encoding="utf-8")
    candidate = ambient_memory_trace_source(original)
    if candidate != original:
        path.write_text(candidate, encoding="utf-8")


def memory_fingerprint_guard_source(text):
    signature = 'static void handle_frame_fingerprint(int id, const char *json)'
    start, end = function_span(text, signature)
    body = text[start:end]
    current = digest(body)
    if current == "dd31561fe011d5c8408b4237f1725e8d199af8de12f962d82bb4a89f0013f201":
        return text
    if current != "a8fa049fa5660b72a0426cffa0a2c103babe730055526231d7e3ae7ff8cd189a":
        raise ValueError("Frame-fingerprint handler source drifted")
    anchor = signature + "\n{\n"
    guard = '''    if (!s_memory_trace_ambient) {
        send_err(id, "Diagnostic disabled; restart with PSX_MEMORY_TRACE=1");
        return;
    }
'''
    body = replace_once(body, anchor, anchor + guard, "frame-fingerprint disabled guard")
    return text[:start] + body + text[end:]


_FREEZE_BEFORE = '''    if (!s_wedge_classification_paused &&
        freeze_dump_policy_observe(&s_dump_policy, wedge_kind,
                                   g_psx_fatal_reason != NULL)) {'''
_FREEZE_AFTER = '''    if (!s_wedge_classification_paused &&
        (wedge_kind == 0 ||
         collection_diagnostic_enabled("PSX_FREEZE_DUMPS")) &&
        freeze_dump_policy_observe(&s_dump_policy, wedge_kind,
                                   g_psx_fatal_reason != NULL)) {'''


def automatic_freeze_dump_source(text):
    include = '#include "collection_diagnostics.h"\n'
    if _FREEZE_AFTER in text:
        if text.count(_FREEZE_AFTER) != 1 or _FREEZE_BEFORE in text or text.count(include) != 1:
            raise ValueError("Automatic freeze-dump guard source drifted")
        return text
    text = replace_once(text, _FREEZE_BEFORE, _FREEZE_AFTER, "automatic freeze-dump policy")
    if text.count(include) > 1:
        raise ValueError("Automatic freeze-dump diagnostic include duplicated")
    if include not in text:
        text = include + text
    return text


def patch_automatic_freeze_dumps(framework):
    path = Path(framework) / 'runtime/src/freeze_heartbeat.c'
    original = path.read_text(encoding='utf-8')
    candidate = automatic_freeze_dump_source(original)
    if candidate != original:
        path.write_text(candidate, encoding='utf-8')


_BATCH_HANDLER = r'''static void handle_gl_batch_diag(int id, const char *json)
{
    if (!collection_diagnostic_enabled("PSX_GL_BATCH_DIAG")) {
        send_err(id, "Diagnostic disabled; restart with PSX_GL_BATCH_DIAG=1");
        return;
    }
    (void)json;
    extern void gl_renderer_batch_diag(uint64_t out[9]);
    uint64_t counts[9];
    gl_renderer_batch_diag(counts);
    send_fmt("{\"id\":%d,\"ok\":true,\"batch_diag\":[%llu,%llu,%llu,%llu,%llu,%llu,%llu,%llu,%llu]}",
             id, (unsigned long long)counts[0], (unsigned long long)counts[1],
             (unsigned long long)counts[2], (unsigned long long)counts[3],
             (unsigned long long)counts[4], (unsigned long long)counts[5],
             (unsigned long long)counts[6], (unsigned long long)counts[7],
             (unsigned long long)counts[8]);
}

'''
_BATCH_COMMAND = '    { "gl_batch_diag",     handle_gl_batch_diag },\n'


def batch_diagnostic_source(text):
    """Expose existing counters without requiring the competing GL timer pool."""
    signature = 'static void handle_gl_batch_diag(int id, const char *json)'
    if signature in text or '"gl_batch_diag"' in text:
        if (text.count(_BATCH_HANDLER) != 1 or text.count(_BATCH_COMMAND) != 1 or
                text.count(signature) != 1 or text.count('"gl_batch_diag"') != 1):
            raise ValueError('Independent batch diagnostic source drifted')
        return text
    if text.count('gl_renderer_batch_diag(br);') != 1:
        raise ValueError('Existing batch counter API changed')
    text = replace_once(text, 'static void handle_frame_perf(int id, const char *json)\n',
        _BATCH_HANDLER + 'static void handle_frame_perf(int id, const char *json)\n', 'batch diagnostic handler')
    return replace_once(text, '    { "frame_perf",        handle_frame_perf },\n',
        _BATCH_COMMAND + '    { "frame_perf",        handle_frame_perf },\n', 'batch diagnostic command')


def patch_batch_diagnostic(framework):
    path = Path(framework) / 'runtime/src/debug_server.c'
    original = path.read_text(encoding='utf-8')
    candidate = batch_diagnostic_source(original)
    if candidate != original:
        path.write_text(candidate, encoding='utf-8')


_GTE_TRACE_FLAGS = '''#ifndef PSX_NO_DEBUG_TOOLS
/* Debug rings are opt-in. Cache process-start env once so hot GTE dispatch
 * never calls getenv; diagnostics do not participate in projection math. */
static int gte_diag_rtp_enabled(void) {
    static const int enabled = collection_diagnostic_enabled("PSX_DIAG_GTE_RTP");
    return enabled;
}
static int gte_diag_intpl_enabled(void) {
    static const int enabled = collection_diagnostic_enabled("PSX_DIAG_GTE_INTPL");
    return enabled;
}
#endif

'''
_GTE_TRACE_SELECT = '''#ifndef PSX_NO_DEBUG_TOOLS
    const bool trace_rtp = (func == 0x01 || func == 0x30) && gte_diag_rtp_enabled();
    const bool trace_intpl = func == 0x11 && gte_diag_intpl_enabled();
#endif
'''
_GTE_TRACE_REPLACEMENTS = (
    ('#include "render_pass_projection.h"\n',
     '#include "render_pass_projection.h"\n#include "collection_diagnostics.h"\n'),
    ('// GTE projection ring (ALWAYS-ON)', '// GTE projection ring (opt-in diagnostic)'),
    ('static inline int gte_sxx(int32_t p)', _GTE_TRACE_FLAGS + 'static inline int gte_sxx(int32_t p)'),
    ('// GTE INTPL ring (ALWAYS-ON)', '// GTE INTPL ring (opt-in diagnostic)'),
    ('if (s->nproj==0 && !(k==0)) continue;',
     'if (s->nproj==0 && s->nintpl==0 && !(k==0)) continue;'),
    ('    uint8_t func = cmd & 0x3F;\n', '    uint8_t func = cmd & 0x3F;\n' + _GTE_TRACE_SELECT),
    ('    if (func == 0x11) {\n        intpl_pre_ir[0]=gte.IR0;',
     '    if (trace_intpl) {\n        intpl_pre_ir[0]=gte.IR0;'),
    ('    if (func == 0x01 || func == 0x30) gte_rtp_record(&gte, cmd);\n'
     '    if (func == 0x11) gte_intpl_record(&gte, intpl_pre_ir, intpl_pre_fc);',
     '    if (trace_rtp) gte_rtp_record(&gte, cmd);\n'
     '    if (trace_intpl) gte_intpl_record(&gte, intpl_pre_ir, intpl_pre_fc);'),
)


def gte_diagnostic_source(text):
    """Gate diagnostic copies while preserving projection math and FG sources."""
    patched = 'gte_diag_rtp_enabled' in text or 'PSX_DIAG_GTE_INTPL' in text
    if patched:
        # Reverse every exact edit before accepting an already-patched source.
        original = text
        for before, after in reversed(_GTE_TRACE_REPLACEMENTS):
            original = replace_once(original, after, before, 'GTE trace reverse')
        if 'gte_diag_rtp_enabled' in original or 'PSX_DIAG_GTE_INTPL' in original:
            raise ValueError('GTE diagnostic guard source drifted')
        return text
    for before, after in _GTE_TRACE_REPLACEMENTS:
        text = replace_once(text, before, after, 'GTE trace gate')
    return text


def patch_gte_diagnostics(framework):
    path = Path(framework) / 'runtime/src/gte.cpp'
    original = path.read_text(encoding='utf-8')
    candidate = gte_diagnostic_source(original)
    if candidate != original:
        path.write_text(candidate, encoding='utf-8')


_SREG_SIGNATURE = 'static void sreg_trace_record(uint32_t func_addr)'
_SREG_BEFORE = '16916aa20d99ee387d388ac5b6fb9b30a4ac3bd7de2c35b9ab329bc4d14e7f10'
_SREG_AFTER = '35728226a884fe5e36aed4599c4c50d3809685cd8e74786b8961c99bdc3a1c75'
_SREG_LATE_FILTER = '''    int focus_func = sreg_trace_focus_func(func_addr);
    if (!focus_func) {
        return;
    }
'''
_SREG_EARLY_FILTER = '''    /* This observer is interested in a small fixed set of function entries.
     * Reject all other entries before reading guest TCB memory. */
    int focus_func = sreg_trace_focus_func(func_addr);
    if (!focus_func) return;

'''


def sreg_trace_fastpath_source(text):
    """Preserve focused captures while skipping unrelated diagnostic RAM reads."""
    start, end = function_span(text, _SREG_SIGNATURE)
    body = text[start:end]
    current = digest(body)
    if current == _SREG_AFTER:
        return text
    if current != _SREG_BEFORE:
        raise ValueError(f'SREG observer source drifted: {current}')
    body = replace_once(body, _SREG_LATE_FILTER, '', 'SREG late filter')
    anchor = '    if (!cpu) return;\n\n'
    body = replace_once(body, anchor, anchor + _SREG_EARLY_FILTER, 'SREG early filter')
    if digest(body) != _SREG_AFTER:
        raise ValueError('SREG transform differs from the verified native function')
    return text[:start] + body + text[end:]


def patch_sreg_trace_fastpath(framework):
    path = Path(framework) / 'runtime/src/debug_server.c'
    original = path.read_text(encoding='utf-8')
    candidate = sreg_trace_fastpath_source(original)
    if candidate != original:
        path.write_text(candidate, encoding='utf-8')


_HOST_IMAGE_BASE_SIGNATURE = 'uint64_t host_sampler_image_base(void)'
_HOST_IMAGE_BASE_ORIGINAL = 'uint64_t host_sampler_image_base(void) { return (uint64_t)s_image_base; }'
_HOST_IMAGE_BASE_FIXED = '''uint64_t host_sampler_image_base(void) {
#if defined(_WIN32) && !defined(PSX_NO_DEBUG_TOOLS)
    /* The JF2 desktop build leaves the intrusive sampler off by default.
     * Diagnostic consumers still need the image base to convert raw PCs to
     * RVAs. GetModuleHandleW(NULL) is the same base assigned by
     * host_sampler_start(), without starting the sampler or mutating shared
     * state. This function is only queried by debug commands, not the charge
     * or sample hot path. */
    return (uint64_t)(uintptr_t)GetModuleHandleW(NULL);
#else
    return (uint64_t)s_image_base;
#endif
}'''


def host_image_base_source(text):
    """Resolve explicit Windows queries even when background sampling is off."""
    start, end = function_span(text, _HOST_IMAGE_BASE_SIGNATURE)
    body = text[start:end]
    if body == _HOST_IMAGE_BASE_FIXED:
        return text
    if body != _HOST_IMAGE_BASE_ORIGINAL:
        raise ValueError('Host image-base getter source drifted')
    if '#elif defined(_WIN32)\n#include <windows.h>' not in text:
        raise ValueError('Host image-base Windows include guard drifted')
    return text[:start] + _HOST_IMAGE_BASE_FIXED + text[end:]


def patch_host_image_base(framework):
    path = Path(framework) / 'runtime/src/host_sampler.c'
    original = path.read_text(encoding='utf-8')
    candidate = host_image_base_source(original)
    if candidate != original:
        path.write_text(candidate, encoding='utf-8')
