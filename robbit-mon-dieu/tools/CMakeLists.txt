cmake_minimum_required(VERSION 3.20)
project(RobbitMonDieuRecomp LANGUAGES C CXX)
set(PSXRECOMP_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/psxrecomp")
set(PSX_RECOMP_UI ON CACHE BOOL "Desktop launcher" FORCE)
include("${PSXRECOMP_ROOT}/runtime/runtime.cmake")
psxrecomp_add_game_runtime(psx-runtime
    PRELOADED_MODS_DIR "NONE"
    WINDOW_TITLE "Robbit Mon Dieu Recompiled"
    DEFAULT_GAME_CONFIG_PATH "game.toml"
    MAX_PLAYERS 1
    GEN_MARKER "generated/SCPS_101.03_dispatch.c"
    GEN_FULL_GLOB "generated/SCPS_101.03_full_*.c")
target_compile_definitions(psx-runtime PRIVATE ROBBIT_DESKTOP=1)
target_include_directories(psx-runtime PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}/desktop")
