#include <stdint.h>

static uint32_t state = 1;
static uint64_t draw_count = 0;

extern "C" void scvrp_msvc_srand(unsigned int seed) {
    state = static_cast<uint32_t>(seed);
    draw_count = 0;
}

extern "C" int scvrp_msvc_rand(void) {
    state = state * 214013u + 2531011u;
    ++draw_count;
    return static_cast<int>((state >> 16u) & 0x7fffu);
}

extern "C" uint32_t scvrp_msvc_rand_state(void) {
    return state;
}

extern "C" uint64_t scvrp_msvc_rand_draw_count(void) {
    return draw_count;
}
