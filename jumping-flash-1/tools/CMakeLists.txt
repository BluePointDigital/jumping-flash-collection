cmake_minimum_required(VERSION 3.20)
project(JumpingFlash1Recomp LANGUAGES C CXX)
set(PSXRECOMP_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/psxrecomp")
set(PSX_RECOMP_UI ON CACHE BOOL "Desktop launcher" FORCE)
include("${PSXRECOMP_ROOT}/runtime/runtime.cmake")
psxrecomp_add_game_runtime(psx-runtime
    PRELOADED_MODS_DIR "NONE"
    WINDOW_TITLE "Jumping Flash! Recompiled"
    DEFAULT_GAME_CONFIG_PATH "game.toml"
    MAX_PLAYERS 1
    GEN_MARKER "generated/SCUS_941.03_dispatch.c"
    GEN_FULL_GLOB "generated/SCUS_941.03_full_*.c")
set_target_properties(psx-runtime PROPERTIES OUTPUT_NAME "JumpingFlash1_Recompiled")
target_compile_definitions(psx-runtime PRIVATE JF1_DESKTOP=1)
