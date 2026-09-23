// SPDX-License-Identifier: MIT
// Disposable-session pointer fixture. Generate its protocol header/code with
// wayland-scanner from Hyprland's wlr-virtual-pointer-unstable-v1.xml.
#include "frame-pointer-protocol.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <wayland-client.h>

static struct zwlr_virtual_pointer_manager_v1 *manager;
static void global(void *data, struct wl_registry *registry, uint32_t name, const char *interface, uint32_t version) {
    if (!strcmp(interface, zwlr_virtual_pointer_manager_v1_interface.name))
        manager = wl_registry_bind(registry, name, &zwlr_virtual_pointer_manager_v1_interface, 1);
}
static void removed(void *data, struct wl_registry *registry, uint32_t name) {}
static const struct wl_registry_listener listener = {global, removed};
int main(int argc, char **argv) {
    const char *runtime = getenv("XDG_RUNTIME_DIR");
    assert(runtime && !strncmp(runtime, "/tmp/", 5));
    struct wl_display *display = wl_display_connect(NULL);
    assert(display);
    wl_registry_add_listener(wl_display_get_registry(display), &listener, NULL);
    assert(wl_display_roundtrip(display) >= 0 && manager);
    struct zwlr_virtual_pointer_v1 *pointer = zwlr_virtual_pointer_manager_v1_create_virtual_pointer(manager, NULL);
    if (argc > 1 && !strcmp(argv[1], "--stream")) {
        char line[128];
        unsigned time = 100;
        puts("ready"); fflush(stdout);
        while (fgets(line, sizeof(line), stdin)) {
            double x, y;
            time += 20;
            if (sscanf(line, "move %lf %lf", &x, &y) == 2)
                zwlr_virtual_pointer_v1_motion(pointer, time, wl_fixed_from_double(x), wl_fixed_from_double(y));
            else if (!strncmp(line, "down", 4))
                zwlr_virtual_pointer_v1_button(pointer, time, 272, WL_POINTER_BUTTON_STATE_PRESSED);
            else if (!strncmp(line, "up", 2))
                zwlr_virtual_pointer_v1_button(pointer, time, 272, WL_POINTER_BUTTON_STATE_RELEASED);
            else if (!strncmp(line, "quit", 4)) break;
            else return 2;
            zwlr_virtual_pointer_v1_frame(pointer);
            assert(wl_display_roundtrip(display) >= 0);
            puts("ok"); fflush(stdout);
        }
        zwlr_virtual_pointer_v1_destroy(pointer);
        wl_display_roundtrip(display);
        wl_display_disconnect(display);
        return 0;
    }
    uint32_t button = argc > 1 ? atoi(argv[1]) : 272;
    zwlr_virtual_pointer_v1_button(pointer, 100, button, WL_POINTER_BUTTON_STATE_PRESSED);
    zwlr_virtual_pointer_v1_frame(pointer);
    assert(wl_display_roundtrip(display) >= 0);
    puts("down");
    fflush(stdout);
    // Python checks the pressed state before allowing release. A drag sends an
    // actual motion event, so cancellation exercises the real input listener.
    int command = getchar();
    if (command == 'd') {
        zwlr_virtual_pointer_v1_motion(pointer, 200, wl_fixed_from_int(-100), 0);
        zwlr_virtual_pointer_v1_frame(pointer);
        assert(wl_display_roundtrip(display) >= 0);
    }
    zwlr_virtual_pointer_v1_button(pointer, 300, button, WL_POINTER_BUTTON_STATE_RELEASED);
    zwlr_virtual_pointer_v1_frame(pointer);
    assert(wl_display_roundtrip(display) >= 0);
    zwlr_virtual_pointer_v1_destroy(pointer);
    wl_display_roundtrip(display);
    wl_display_disconnect(display);
}
