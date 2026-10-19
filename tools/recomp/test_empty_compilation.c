#include "autocompile.h"
#include "overlay_loader.h"
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <assert.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>

static int rescans;
void overlay_loader_rescan(void) { ++rescans; }
OverlayPreparedImage *overlay_loader_prepare_published(const char *path) { (void)path; return NULL; }
int overlay_loader_commit_published(OverlayPreparedImage *image) { (void)image; return 0; }
void overlay_loader_discard_prepared(OverlayPreparedImage *image) { (void)image; }

static void run(const char *command, int expected) {
    int before = rescans;
    autocompile_configure(command, ".");
    assert(autocompile_request());
    ULONGLONG deadline = GetTickCount64() + 10000;
    do { autocompile_poll_main(); Sleep(1); }
    while (autocompile_busy() && GetTickCount64() < deadline);
    assert(!autocompile_busy());
    if (rescans - before != expected) {
        char status[8192]; autocompile_status_json(status, sizeof(status));
        fprintf(stderr, "%s: %s\n", command, status);
    }
    assert(rescans - before == expected);
    autocompile_shutdown();
}

int main(int argc, char **argv) {
    if (argc > 1 && !strcmp(argv[1], "failure")) {
        run("cmd /c echo PSX_SHARD_RESULT ok=0 failed=1 skipped=0 & rem", 1);
    } else {
        run("cmd /c echo PSX_SHARD_RESULT ok=0 failed=0 skipped=7 & rem", 0);
        run("cmd /c echo PSX_SHARD_RESULT ok=1 failed=0 skipped=0 & rem", 1);
        run("cmd /c echo PSX_SHARD_RESULT ok=0 failed=0 skipped=0 & rem", 0);
        run("cmd /c echo unknown compiler output & rem", 1);
    }
    puts("Empty compilation rescan checks passed.");
}
