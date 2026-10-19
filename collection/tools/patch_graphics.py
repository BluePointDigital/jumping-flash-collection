"""Collection-only recorded-geometry history fix for delayed/triple buffering."""
from pathlib import Path


def framegen_fit_source(text):
    """Prune camera hypotheses that cannot improve the strict inlier winner."""
    old='''            uint32_t c = 0;
            for (uint32_t i = 0; i < np; i++) c += (uint32_t)is_inlier(m, r.t, a[i], b[i], hb[i], p);
            if (c > best_n) { best_n = c; best_r = r; }'''
    new='''            uint32_t c = 0;
            for (uint32_t i = 0; i < np; i++) {
                c += (uint32_t)is_inlier(m, r.t, a[i], b[i], hb[i], p);
                /* Strictly better is required below; stop once this model
                 * can no longer exceed the best complete model. */
                if (c + (np - i - 1u) <= best_n) break;
            }
            if (c > best_n) { best_n = c; best_r = r; }'''
    if text.count(new)==1 and old not in text:return text
    if text.count(old)!=1 or new in text:
        raise ValueError('Camera-fit RANSAC winner anchor changed or is ambiguous')
    return text.replace(old,new,1)


def patch_camera_fit(framework):
    path=Path(framework)/'runtime/src/frame_gen.c'
    original=path.read_text(encoding='utf-8')
    candidate=framegen_camera_source(original)
    if candidate!=original:path.write_text(candidate,encoding='utf-8')


def framegen_camera_source(text):
    """Prepare the exact camera matching and fitting implementation."""
    import hashlib
    if hashlib.sha256(text.encode()).hexdigest()=='21fcb863c40aa7a8c8a498b7b74e0203e8c9a9dd68f04eb9cf6cf2d4e0e14276':
        return text
    return framegen_tolerance_source(framegen_pair_source(framegen_fit_source(text)))


def framegen_tolerance_source(text):
    """Compute the unchanged squared inlier tolerance once per matched pair."""
    import hashlib
    before='70b572073f5b64f085ea0183ba15d576cf4d530cdb4bf2d0fe14f51204d49e91'
    after='21fcb863c40aa7a8c8a498b7b74e0203e8c9a9dd68f04eb9cf6cf2d4e0e14276'
    digest=hashlib.sha256(text.encode()).hexdigest()
    if digest==after:return text
    if digest!=before:raise ValueError('Camera inlier implementation changed')
    anchor='''static int is_inlier(const double m[9], const double t[3], const float a[3], const float b[3],
                     float h, const FgCamParams *p) {'''
    helper='''static double inlier_tol2(float tol_px, const float b[3], float h) {
    /* Keep the original expression and operation order exactly; only evaluate
     * it once per matched source rather than once per RANSAC hypothesis. */
    const double tol = tol_px * fmax(fabs(b[2]), 1.0) / fmax(h, 1.0);
    return tol * tol;
}

static int is_inlier(const double m[9], const double t[3], const float a[3], const float b[3],
                     double tol2) {'''
    replacements=[
        (anchor,helper,1),
        ('''    /* In screen pixels at the point's depth. */
    const double tol = p->tol_px * fmax(fabs(b[2]), 1.0) / fmax(h, 1.0);
    return e < tol * tol;''','    return e < tol2;',1),
        ('float *hb = (float *)malloc(((size_t)nb + 1) * sizeof *hb);',
         'double *tol2 = (double *)malloc(((size_t)nb + 1) * sizeof *tol2);',1),
        ('a && b && bi && hb && i < nb','a && b && bi && tol2 && i < nb',1),
        ('hb[np] = sb[i].h;','/* Fill tolerance cache only after the pair-count guard. */',1),
        ('if (np < p->min_pairs) { v->why = "few pairs"; goto done; }',
         'if (np < p->min_pairs) { v->why = "few pairs"; goto done; }\n    for (uint32_t i = 0; i < np; i++)\n        tol2[i] = inlier_tol2(p->tol_px, b[i], sb[bi[i]].h);',1),
        ('!a || !b || !bi || !hb || !in || !idx','!a || !b || !bi || !tol2 || !in || !idx',1),
        ('is_inlier(m, r.t, a[i], b[i], hb[i], p)','is_inlier(m, r.t, a[i], b[i], tol2[i])',1),
        ('is_inlier(m, best_r.t, a[i], b[i], hb[i], p)','is_inlier(m, best_r.t, a[i], b[i], tol2[i])',2),
        ('free(sa); free(a); free(b); free(bi); free(hb);','free(sa); free(a); free(b); free(bi); free(tol2);',1),
    ]
    for old,new,count in replacements:
        if text.count(old)!=count:raise ValueError('Camera inlier anchor changed')
        text=text.replace(old,new)
    if hashlib.sha256(text.encode()).hexdigest()!=after:
        raise ValueError('Camera inlier transformation differs from verified source')
    return text


def framegen_pair_source(text):
    """Merge sorted source IDs without changing nearest-candidate tie order."""
    import hashlib
    before='d769c105ae6599ccfa52ed92dd4861f4356a22f1401f50f00d5a866398861328'
    after='70b572073f5b64f085ea0183ba15d576cf4d530cdb4bf2d0fe14f51204d49e91'
    digest=hashlib.sha256(text.encode()).hexdigest()
    if digest==after:return text
    # This relies on gather's exact sort and the original per-ID scan order.
    if digest!=before:raise ValueError('Camera pairing implementation or sort changed')
    lower='''static uint32_t lower(const Src *s, uint32_t n, uint32_t id) {
    uint32_t lo = 0, hi = n;
    while (lo < hi) { const uint32_t m = (lo + hi) / 2; if (s[m].id < id) lo = m + 1; else hi = m; }
    return lo;
}

'''
    old='''    uint32_t np = 0;
    for (uint32_t i = 0; a && b && bi && hb && i < nb; i++) {
        uint32_t j = lower(sa, na, sb[i].id);'''
    new='''    uint32_t np = 0, sa_cursor = 0;
    for (uint32_t i = 0; a && b && bi && hb && i < nb; i++) {
        /* Both gathered lists are sorted by source id then position. Advance
         * the older-list lower bound once per distinct newer id, preserving
         * the same range and per-id nearest-candidate scan as lower(). */
        if (i == 0 || sb[i].id != sb[i - 1].id)
            while (sa_cursor < na && sa[sa_cursor].id < sb[i].id) sa_cursor++;
        uint32_t j = sa_cursor;'''
    if text.count(lower)!=1 or text.count(old)!=1:
        raise ValueError('Camera pairing anchors changed')
    candidate=text.replace(lower,'',1).replace(old,new,1)
    if hashlib.sha256(candidate.encode()).hexdigest()!=after:
        raise ValueError('Camera pairing transformation differs from verified source')
    return candidate


def framegen_completion_source(text):
    """Schedule from actual generated-swap completion and handle failed draws."""
    if '// COLLECTION_FG_COMPLETION_V1' in text:
        return text
    replacements=[
        ('static void fg_generate_timed(double t) {',
         '// COLLECTION_FG_COMPLETION_V1\nstatic int fg_generate_timed(double t) {'),
        ('''    rthf_resume();
}

/* Keep the composed back buffer (a real frame) for later. 1 when kept. */''',
         '''    rthf_resume();
    return ok;
}

/* Keep the composed back buffer (a real frame) for later. 1 when kept. */'''),
        ('''            fg_generate_timed(t);
            s_fg_k++;
            fg_note_present(now);
            return s_fg_due;''',
         '''            if(fg_generate_timed(t)){
                s_fg_k++;
                fg_note_present(rt_now_ns());
                return s_fg_due;
            }
            fg_flush();
            return 0;''')]
    for old,new in replacements:
        if text.count(old)!=1:
            raise ValueError(f'Frame-generation completion anchor changed: {old[:80]}')
        text=text.replace(old,new,1)
    return text


def collection_aspect_source(text):
    """Activate collection display choices through the native presentation API."""
    if '// COLLECTION_DISPLAY_ASPECT_V3' in text:
        return text
    if '// COLLECTION_DISPLAY_ASPECT_V2' in text:
        old='        gpu_ws_set_gte_game_mode(1);\n'
        if text.count(old)!=1:
            raise ValueError('Collection aspect V2 upgrade anchor changed')
        return text.replace(old,'',1).replace('// COLLECTION_DISPLAY_ASPECT_V2','// COLLECTION_DISPLAY_ASPECT_V3',1)
    def replace(old,new):
        nonlocal text
        if text.count(old)!=1:
            raise ValueError(f'Collection aspect anchor changed: {old[:80]}')
        text=text.replace(old,new,1)
    replace('static int           g_video_aspect_den = 3;',
        'static int           g_video_aspect_den = 3;\n'
        '// COLLECTION_DISPLAY_ASPECT_V3\n'
        'static uint32_t collection_display_num=4,collection_display_den=3;')
    replace('''        if (us.has_aspect_ratio) {
            g_video_aspect_num = us.aspect_num;
            g_video_aspect_den = us.aspect_den;
        }''','''        if (us.has_aspect_ratio) {
            g_video_aspect_num = us.aspect_num;
            g_video_aspect_den = us.aspect_den;
            if(collection_mode&&((us.aspect_num==4&&us.aspect_den==3)||
                (us.aspect_num==16&&(us.aspect_den==9||us.aspect_den==10)))){
                collection_display_num=us.aspect_num;collection_display_den=us.aspect_den;
            }
        }''')
    replace('''    /* Display aspect. Identity at the default 4:3. The present letterbox uses
     * this aspect; native-wide fills it with a genuinely wider frame (no
     * stretch), squash mode stretches the 4:3 frame into it. */
    gl_renderer_set_display_aspect(g_video_aspect_num, g_video_aspect_den);''','''    /* Collection owns its integrated view setting after legacy settings and
     * optional mod resolution. Keep the renderer's FMV/2D native-aspect gates. */
    if(collection_mode){
        (void)psx_mod_set_fixed_display_aspect(collection_display_num,collection_display_den);
    }
    /* Display aspect. Identity at the default 4:3. The present letterbox uses
     * this aspect; native-wide fills it with a genuinely wider frame (no
     * stretch), squash mode stretches the 4:3 frame into it. */
    gl_renderer_set_display_aspect(g_video_aspect_num, g_video_aspect_den);''')
    return text

def framegen_restore_source(text):
    """Discard the old frame-generation timeline at the existing restore barrier."""
    helper='''// COLLECTION_FG_RESTORE_HISTORY_V1
/* State restore is a timeline break: drop any held pre-restore image without
 * presenting it, then make the first restored flip a new frame. */
static void fg_reset_discontinuity(void) {
    s_fg_pending = 0;
    s_fg_n = s_fg_k = 0;
    s_fg_pa = s_fg_pb = -1;
    s_fg_t0 = s_fg_step_ns = s_fg_flip_ns = 0;
    s_fg_due = s_fg_last_present_ns = 0;
    s_fg_bp_seen = s_fg_bp_ns_seen = 0;
    s_fg_vblanks = 0;
    s_fg_last_dx = s_fg_last_dy = 0;
    s_fg_nbuf = 0;
    memset(s_fg_buf, 0, sizeof s_fg_buf);
    s_fg_real_kept = 0;
    /* Keep the owned realloc buffer/capacity; the next present overwrites it. */
    atomic_store(&s_fg_flip_vb, 1);
    atomic_store(&s_fg_last_gen_ns, 0);
    fg_invalidate();
}

'''
    declaration='static void      fg_invalidate(void);\n'
    reset='    hold_invalidate();\n    interp_reset_history();\n'
    anchor="/* A new surface's first touch (the driver backing its storage) happens here,"
    changes=[(declaration,declaration+'static void      fg_reset_discontinuity(void);\n'),
             (reset,reset+'    fg_reset_discontinuity();\n'),(anchor,helper+anchor)]
    if '// COLLECTION_FG_RESTORE_HISTORY_V1' in text:
        if any(text.count(new)!=1 for _,new in changes):
            raise ValueError('Frame restore history patch is incomplete or changed')
        return text
    for old,new in changes:
        if text.count(old)!=1:
            raise ValueError(f'Frame restore history anchor changed: {old[:80]}')
        text=text.replace(old,new,1)
    return text


def patch_history(framework):
    path=Path(framework)/'runtime/src/gpu_gl_renderer.c'
    original=path.read_text(encoding='utf-8')
    text=framegen_restore_source(original)
    if '// COLLECTION_FRAME_HISTORY_V3' in text:
        if text!=original:path.write_text(text,encoding='utf-8')
        return
    if '// COLLECTION_FRAME_HISTORY_V2' in text:
        text=text.replace('for(int k=0;k<COLLECTION_FG_HISTORY;k++){\n            if(k==s_fg_older',
            'for(int k=0;k<(s_fg_reproject?4:COLLECTION_FG_HISTORY);k++){\n            if(k==s_fg_older')
        text=text.replace('if(free_slot<0 || s_fg_l[k].sequence<s_fg_l[free_slot].sequence)free_slot=k;',
            'if(free_slot<0 || (!s_fg_reproject && s_fg_l[k].sequence<s_fg_l[free_slot].sequence))free_slot=k;')
        path.write_text(text.replace('COLLECTION_FRAME_HISTORY_V2','COLLECTION_FRAME_HISTORY_V3'),encoding='utf-8')
        return
    if '// COLLECTION_FRAME_HISTORY_V1' in text:
        text=text.replace('    int pair_a=-1;\n    const int pair_b=collection_frame_pair(history,COLLECTION_FG_HISTORY,s_fg_cur,\n                                          disp,s_fg_display_sequence,&pair_a);',pair_selection())
        text=text.replace('    if(B)s_fg_display_sequence=B->sequence;',
            '    if(s_fg_reproject && B->valid && (B->disp[0]!=disp[0] || B->disp[1]!=disp[1]))B=A=NULL;\n'
            '    if(B && !s_fg_reproject)s_fg_display_sequence=B->sequence;')
        path.write_text(text.replace('COLLECTION_FRAME_HISTORY_V1','COLLECTION_FRAME_HISTORY_V2'),encoding='utf-8')
        patch_history(framework)
        return
    def replace(old,new):
        nonlocal text
        if text.count(old)!=1:raise ValueError(f'Graphics history anchor changed: {old[:80]}')
        text=text.replace(old,new,1)
    replace('} FgList;','    uint64_t sequence;\n} FgList;')
    replace('static FgList    s_fg_l[4];                   /* older, newer, capturing, spare */',
        '// COLLECTION_FRAME_HISTORY_V3\n#include "frame_history.h"\n'
        '#define COLLECTION_FG_HISTORY 6\n'
        'static FgList s_fg_l[COLLECTION_FG_HISTORY];\n'
        'static uint64_t s_fg_sequence=0, s_fg_display_sequence=0;')
    replace('    l->len = 0; l->n = 0; l->valid = 0;',
        '    l->len = 0; l->n = 0; l->valid = 0; l->sequence = 0;')
    replace('    l->valid = 1;\n    memcpy(l->disp, disp, sizeof l->disp);',
        '    l->valid = 1; l->sequence = ++s_fg_sequence;\n    memcpy(l->disp, disp, sizeof l->disp);')
    start=text.index('    /* A slot no frame in use holds (a schedule pins its pair). */')
    end=text.index('    s_fg_cur = free_slot;',start)
    text=text[:start]+'''    /* Keep the last displayed frame even when two newer buffers are ready.
     * Reuse the oldest unpinned list; an active schedule owns both its lists. */
    int free_slot=-1;
    for(int retry=0;retry<2 && free_slot<0;retry++){
        for(int k=0;k<(s_fg_reproject?4:COLLECTION_FG_HISTORY);k++){
            if(k==s_fg_older || k==s_fg_newer ||
               (s_fg_l[k].sequence && s_fg_l[k].sequence==s_fg_display_sequence) ||
               (s_fg_pending && (k==s_fg_pa || k==s_fg_pb)))continue;
            if(free_slot<0 || (!s_fg_reproject && s_fg_l[k].sequence<s_fg_l[free_slot].sequence))free_slot=k;
        }
        if(free_slot<0)fg_flush();
    }
''' +text[end:]
    replace('    for (int i = 0; i < 4; i++) s_fg_l[i].valid = 0;',
        '    for (int i = 0; i < COLLECTION_FG_HISTORY; i++) s_fg_l[i].valid = 0;\n    s_fg_display_sequence=0;')
    replace('        for (int i = 0; i < 4; i++) if (i != s_fg_cur) s_fg_l[i].valid = 0;',
        '        for (int i = 0; i < COLLECTION_FG_HISTORY; i++) if (i != s_fg_cur) s_fg_l[i].valid = 0;\n        s_fg_display_sequence=0;')
    replace('    FgList *A = &s_fg_l[s_fg_older], *B = &s_fg_l[s_fg_newer];\n'
        '    if (B->valid && (B->disp[0] != disp[0] || B->disp[1] != disp[1])) B = A = NULL;',
        '''    CollectionFrameRecord history[COLLECTION_FG_HISTORY];
    for(int i=0;i<COLLECTION_FG_HISTORY;i++){
        history[i].sequence=s_fg_l[i].sequence; history[i].valid=s_fg_l[i].valid;
        memcpy(history[i].rect,s_fg_l[i].disp,sizeof history[i].rect);
    }
''' +pair_selection()+'''
    FgList *A=pair_a>=0?&s_fg_l[pair_a]:NULL;
    FgList *B=pair_b>=0?&s_fg_l[pair_b]:NULL;
    if(s_fg_reproject && B->valid && (B->disp[0]!=disp[0] || B->disp[1]!=disp[1]))B=A=NULL;
    if(B && !s_fg_reproject)s_fg_display_sequence=B->sequence;''')
    # A missing prior display is a discontinuity, not an invalid dereference.
    replace(': !A->valid ? "older list invalid"',': !A || !A->valid ? "older list invalid"')
    replace('    s_fg_pa = s_fg_older; s_fg_pb = s_fg_newer;',
        '    s_fg_pa = pair_a; s_fg_pb = pair_b;')
    path.write_text(text,encoding='utf-8')

def pair_selection():
    # Reprojection owns two snapshots taken at drawing boundaries. Retain its
    # existing pairing until those snapshots also support delayed presentation.
    return '''    int pair_a=s_fg_older, pair_b=s_fg_newer;
    if(!s_fg_reproject){
        pair_a=-1;
        pair_b=collection_frame_pair(history,COLLECTION_FG_HISTORY,s_fg_cur,
                                     disp,s_fg_display_sequence,&pair_a);
    }'''


def framegen_origin_cost_source(source):
    """Rebase recorded redraw targets and exclude failed render-cost queries."""
    import hashlib

    def replace_once(text, old, new, label):
        if text.count(old)!=1:raise ValueError(f"Frame-generation anchor changed: {label}")
        return text.replace(old,new,1)

    def function_hash(start,end):
        try:
            begin=source.index(start)
            finish=source.index(end,begin)
        except ValueError as error:raise ValueError("Frame-generation function boundary changed") from error
        return hashlib.sha256(source[begin:finish].rstrip().encode()).hexdigest()

    hashes=(function_hash("static int fg_generate(double t, int swap) {","\n/* ---- frame generation: schedule"),
            function_hash("static void fg_gen_cost_poll(void) {","\n/* One generated frame at phase t, timed"))
    before=("f194392286d094e525c16de5b476d1c6650d72e43a54da16df1d99f65f1a5dc1",
            "60610149641b7af3b5ae3b72d6d1e2911f3d2d3fa2a859e4c4445c196b02f565")
    after=('2360e9deeb357e8cb511e8f1fd1a81e11e961583d0d51db041fac1c38200ffb8', '1488ec069bef09b001da28a3eb554030a967b381327488a64431c88fcefe4b57')
    if hashes==after:
        if (source.count('static int       s_fg_q_success[4];')!=1 or
            source.count('s_fg_q_success[qi] = ok;')!=1):
            raise ValueError('Partially transformed frame-generation source')
        return source
    if hashes!=before or 's_fg_q_success[4];' in source:
        raise ValueError('Frame-generation implementation changed or is partially patched')

    s = replace_once(source, 'static uint64_t  s_fg_q_cpu[4];\n',
                     'static uint64_t  s_fg_q_cpu[4];\nstatic int       s_fg_q_success[4];\n', 'query success storage')
    s = replace_once(s, 'if (!a->valid || !b->valid || s_hiw) return 0;\n    if (b->wide && (g_wide_w <= 0 || g_wide_w != b->wide_w)) return 0;',
                     'if (!a->valid || !b->valid) return 0;\n    if (s_hiw) return 0;\n    if (b->wide && g_wide_w <= 0) return 0;\n    if (b->wide && g_wide_w != b->wide_w) return 0;', 'guard parity')

    old_preflight = '''        if (iw < 0) return 0;\n    }\n    /* Land the real stream's queued work on the real surfaces first. */'''
    new_preflight = '''        if (iw < 0) return 0;\n    }\n    /* B is the copied image; L is the replay target, possibly another VRAM origin. */\n    const FgList *L = s_fg_src_older ? a : b;\n    if (L->wide != b->wide ||\n        ((L->wide || b->wide) &&\n         (L->wide_w != b->wide_w || L->wide_w != g_wide_w ||\n          L->wide_off != b->wide_off || L->wide_off != g_wide_off))) return 0;\n    const double tl = s_fg_src_older ? 1.0 - t : t;\n    const int dy = b->disp[1] < 0 ? 0 : b->disp[1];\n    const int dh = b->disp[1] + b->disp[3] > VRAM_H ? VRAM_H - dy : b->disp[1] + b->disp[3] - dy;\n    const int ly = L->disp[1] < 0 ? 0 : L->disp[1];\n    const int lh = L->disp[1] + L->disp[3] > VRAM_H ? VRAM_H - ly : L->disp[1] + L->disp[3] - ly;\n    if (lh != dh || L->disp[2] != b->disp[2]) return 0;\n    int il = -1;\n    if (iw >= 0) {\n        for (int i = 0; i < WIDE_MAX_SURF; i++)\n            if (s_wide_fbo[i] && s_wide_base[i] == L->disp[0]) { il = i; break; }\n        if (il < 0) return 0;\n    }\n    /* Land the real stream's queued work on the real surfaces first. */'''
    s = replace_once(s, old_preflight, new_preflight, 'pre-mutation origin/layout validation')

    old_geometry = '''    /* The displayed buffer as the real frame has it, then swap the surfaces. */\n    const int dy = b->disp[1] < 0 ? 0 : b->disp[1];\n    const int dh = b->disp[1] + b->disp[3] > VRAM_H ? VRAM_H - dy : b->disp[1] + b->disp[3] - dy;\n    /* The redrawn frame (the older one when moving forward) is drawn where\n     * its own buffer is, over the newer real frame's image: what the\n     * in-between camera uncovers shows that. */\n    const FgList *L = s_fg_src_older ? a : b;\n    const double tl = s_fg_src_older ? 1.0 - t : t;\n    const int ly = L->disp[1] < 0 ? 0 : L->disp[1];\n    const int lh = L->disp[1] + L->disp[3] > VRAM_H ? VRAM_H - ly : L->disp[1] + L->disp[3] - ly;\n    if (L->disp[0] != b->disp[0] || lh != dh || L->disp[2] != b->disp[2]) return 0;\n'''
    s = replace_once(s, old_geometry, '    /* Display geometry was validated before touching real PGXP/depth state. */\n', 'remove late geometry guard')

    s = replace_once(s, 'int wst[4] = { 0, 0, 0, 0 };\n    if (iw >= 0) { wst[0] = s_wst_x0[iw]; wst[1] = s_wst_y0[iw]; wst[2] = s_wst_x1[iw]; wst[3] = s_wst_y1[iw]; }',
                     'int wst[4] = { 0, 0, 0, 0 };\n    if (il >= 0) { wst[0] = s_wst_x0[il]; wst[1] = s_wst_y0[il]; wst[2] = s_wst_x1[il]; wst[3] = s_wst_y1[il]; }\n    const GLuint wide_src_fbo = iw >= 0 ? s_wide_fbo[iw] : 0;', 'wide target dirty snapshot/source FBO')
    s = replace_once(s, 'fg_blit2(s_wide_fbo[iw], s_fg_w_fbo, 0, dy * S, 0, ly * S, g_wide_w * S, dh * S);',
                     'fg_blit2(wide_src_fbo, s_fg_w_fbo, 0, dy * S, 0, ly * S, g_wide_w * S, dh * S);', 'initial wide copy')
    s = replace_once(s, 'if (iw >= 0) {\n        wt = s_wide_tex[iw]; wf = s_wide_fbo[iw]; wr = s_wide_rb[iw]; was = s_wide_as[iw];\n        s_wide_tex[iw] = s_fg_w_tex; s_wide_fbo[iw] = s_fg_w_fbo; s_wide_rb[iw] = s_fg_w_rb;\n        s_wide_as[iw] = S;\n    }',
                     'if (il >= 0) {\n        wt = s_wide_tex[il]; wf = s_wide_fbo[il]; wr = s_wide_rb[il]; was = s_wide_as[il];\n        s_wide_tex[il] = s_fg_w_tex; s_wide_fbo[il] = s_fg_w_fbo; s_wide_rb[il] = s_fg_w_rb;\n        s_wide_as[il] = S;\n    }', 'borrow target wide surface')
    s = replace_once(s, 'if (iw >= 0) wst_add(iw, 0, ly, g_wide_w, ly + lh);', 'if (il >= 0) wst_add(il, 0, ly, g_wide_w, ly + lh);', 'target wide dirty mark')
    s = replace_once(s, 'if (iw >= 0) fg_blit2(wf, s_fg_w_fbo, 0, dy * S, 0, ly * S, g_wide_w * S, dh * S);',
                     'if (iw >= 0) fg_blit2(wide_src_fbo, s_fg_w_fbo, 0, dy * S, 0, ly * S, g_wide_w * S, dh * S);', 'wide fallback copy')
    s = replace_once(s, 'const GLuint src = iw >= 0 ? wf : f0, dst = iw >= 0 ? s_fg_w_fbo : s_fg_hr_fbo;\n        const int bx0 = iw >= 0 ? 0 : L->disp[0], sdy = dy - ly;',
                     'const GLuint src = iw >= 0 ? wide_src_fbo : f0, dst = iw >= 0 ? s_fg_w_fbo : s_fg_hr_fbo;\n        const int srcx0 = iw >= 0 ? 0 : b->disp[0];\n        const int dstx0 = iw >= 0 ? 0 : L->disp[0], sdy = dy - ly;', 'separate margin source and target origins')
    edge_lines = [
        ('if (ml) fg_blit2(src, dst, (bx0 + x1) * S, (y1 + sdy) * S, (bx0 + x1) * S, y1 * S, ml * S, h * S);',
         'if (ml) fg_blit2(src, dst, (srcx0 + x1) * S, (y1 + sdy) * S, (dstx0 + x1) * S, y1 * S, ml * S, h * S);'),
        ('if (mr) fg_blit2(src, dst, (bx0 + x2 - mr) * S, (y1 + sdy) * S, (bx0 + x2 - mr) * S, y1 * S, mr * S, h * S);',
         'if (mr) fg_blit2(src, dst, (srcx0 + x2 - mr) * S, (y1 + sdy) * S, (dstx0 + x2 - mr) * S, y1 * S, mr * S, h * S);'),
        ('if (mt) fg_blit2(src, dst, (bx0 + x1) * S, (y1 + sdy) * S, (bx0 + x1) * S, y1 * S, w * S, mt * S);',
         'if (mt) fg_blit2(src, dst, (srcx0 + x1) * S, (y1 + sdy) * S, (dstx0 + x1) * S, y1 * S, w * S, mt * S);'),
        ('if (mb) fg_blit2(src, dst, (bx0 + x1) * S, (y2 - mb + sdy) * S, (bx0 + x1) * S, (y2 - mb) * S, w * S, mb * S);',
         'if (mb) fg_blit2(src, dst, (srcx0 + x1) * S, (y2 - mb + sdy) * S, (dstx0 + x1) * S, (y2 - mb) * S, w * S, mb * S);')]
    for old, new in edge_lines: s = replace_once(s, old, new, 'edge-strip coordinate mapping')

    s = replace_once(s, 'if (iw >= 0) {\n        s_wide_tex[iw] = wt; s_wide_fbo[iw] = wf; s_wide_rb[iw] = wr; s_wide_as[iw] = was;\n        s_wst_x0[iw] = wst[0]; s_wst_y0[iw] = wst[1]; s_wst_x1[iw] = wst[2]; s_wst_y1[iw] = wst[3];\n    }',
                     'if (il >= 0) {\n        s_wide_tex[il] = wt; s_wide_fbo[il] = wf; s_wide_rb[il] = wr; s_wide_as[il] = was;\n        s_wst_x0[il] = wst[0]; s_wst_y0[il] = wst[1]; s_wst_x1[il] = wst[2]; s_wst_y1[il] = wst[3];\n    }', 'restore target wide surface')

    old_poll = '''        p_glGetQueryObjectui64v(s_fg_q[i], GL_QUERY_RESULT, &ns);\n        double c = (double)(ns > s_fg_q_cpu[i] ? ns : s_fg_q_cpu[i]) * 1e-9;\n        fg_cost_add(fg_cost(), c, s_fg_fit_s);\n        atomic_store(&s_fg_cost_ema_pub, fg_cost()->ema);\n        fg_gen_cost_publish((uint64_t)(c * 1e9));\n        s_fg_gen_gpu_ms = (double)ns * 1e-6;\n        s_fg_gen_cpu_ms = (double)s_fg_q_cpu[i] * 1e-6;\n        s_fg_qt++;'''
    new_poll = '''        if (s_fg_q_success[i]) {\n            p_glGetQueryObjectui64v(s_fg_q[i], GL_QUERY_RESULT, &ns);\n            double c = (double)(ns > s_fg_q_cpu[i] ? ns : s_fg_q_cpu[i]) * 1e-9;\n            fg_cost_add(fg_cost(), c, s_fg_fit_s);\n            atomic_store(&s_fg_cost_ema_pub, fg_cost()->ema);\n            fg_gen_cost_publish((uint64_t)(c * 1e9));\n            s_fg_gen_gpu_ms = (double)ns * 1e-6;\n            s_fg_gen_cpu_ms = (double)s_fg_q_cpu[i] * 1e-6;\n        }\n        s_fg_qt++;'''
    s = replace_once(s, old_poll, new_poll, 'success-only completed query accounting')

    old_queue = '''        p_glEndQuery(GL_TIME_ELAPSED);\n        s_fg_q_cpu[s_fg_qh % 4u] = cpu;\n        s_fg_qh++;'''
    new_queue = '''        p_glEndQuery(GL_TIME_ELAPSED);\n        const unsigned qi = s_fg_qh % 4u;\n        s_fg_q_cpu[qi] = cpu;\n        s_fg_q_success[qi] = ok;\n        s_fg_qh++;'''
    s = replace_once(s, old_queue, new_queue, 'success marker publication')
    return s


def patch_framegen_redraw(framework):
    path=Path(framework)/'runtime/src/gpu_gl_renderer.c'
    original=path.read_text(encoding='utf-8')
    candidate=framegen_origin_cost_source(framegen_completion_source(original))
    if candidate!=original:path.write_text(candidate,encoding='utf-8')
