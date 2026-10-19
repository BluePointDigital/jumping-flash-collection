#include "common/recomp_runtime_ui_internal.h"
#include <assert.h>
#include <string.h>
#include <stdlib.h>

static RecompRuntimeUi* menu;
static int value, saves;
static int get(void* context,const RecompRuntimeUiItem* item,int* out) {*out=value;return 1;}
static int set(void* context,const RecompRuntimeUiItem* item,int next) {value=next;recomp_runtime_ui_set_status(menu,"Restart to apply.");return 1;}
static int act(void* context,const RecompRuntimeUiItem* item) {recomp_runtime_ui_set_status(menu,"Press a key. Escape cancels.");return 1;}
static int navigate(void* context,const RecompRuntimeUiItem* item) {
    recomp_runtime_ui_enter_section(menu,1);return 1;
}
static void save(void* context) {++saves;}
int main(void) {
    RecompRuntimeUiItem items[2]={{"renderer","Display","Renderer",NULL,RECOMP_RUNTIME_UI_INT,0,1,1},
        {"bind","Controls","Rebind",NULL,RECOMP_RUNTIME_UI_ACTION}};
    RecompRuntimeUiConfig config={0};config.title="Desktop";config.items=items;config.item_count=2;
    config.callbacks.get_value=get;config.callbacks.set_value=set;config.callbacks.run_action=act;config.callbacks.save=save;
    menu=recomp_runtime_ui_create(&config);assert(menu);recomp_runtime_ui_open(menu);
    recomp_runtime_ui_enter_section(menu,0);recomp_runtime_ui_adjust_current(menu,1,1,0);
    assert(value==1 && saves==1 && !strcmp(menu->status,"Restart to apply."));
    recomp_runtime_ui_enter_section(menu,1);recomp_runtime_ui_adjust_current(menu,1,1,0);
    assert(!strcmp(menu->status,"Press a key. Escape cancels."));
    recomp_runtime_ui_adjust_current(menu,1,1,1);assert(saves==1);
    uint32_t* pixels=calloc(640*480,sizeof(uint32_t));assert(pixels);
    recomp_runtime_ui_render_argb8888(menu,pixels,640,480,640*4);
    assert((pixels[0]>>24)>0 && (pixels[0]>>24)<255); // Gameplay stays visible behind dim.
    assert((pixels[20*640+320]>>24)>230); // Panel remains legible.
    memset(pixels,0,640*480*sizeof(uint32_t));
    recomp_runtime_ui_render_title_entries(pixels,640,480,640*4,5);
    assert(pixels[280*640+320]==0 && pixels[445*640+320]==0);
    assert((pixels[425*640+320]>>24)==255);
    free(pixels);
    recomp_runtime_ui_close(menu);assert(!recomp_runtime_ui_is_open(menu));recomp_runtime_ui_destroy(menu);
    RecompRuntimeUiItem nav[2]={{"mods","Game","Mods",NULL,RECOMP_RUNTIME_UI_ACTION},
        {"boost","Mods","Booster",NULL,RECOMP_RUNTIME_UI_BOOL,0,1,1}};
    config.items=nav;config.item_count=2;config.callbacks.run_action=navigate;
    menu=recomp_runtime_ui_create(&config);assert(menu);recomp_runtime_ui_open(menu);
    recomp_runtime_ui_enter_section(menu,0);recomp_runtime_ui_adjust_current(menu,1,1,0);
    assert(menu->in_section && menu->section_index==1 && menu->row_index==0);
    recomp_runtime_ui_destroy(menu);
}
