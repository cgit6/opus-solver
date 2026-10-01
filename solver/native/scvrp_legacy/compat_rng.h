#ifndef MKP_SCVRP_LEGACY_COMPAT_RNG_H
#define MKP_SCVRP_LEGACY_COMPAT_RNG_H

#include <stdint.h>
#include <stdlib.h>

extern "C" void scvrp_msvc_srand(unsigned int seed);
extern "C" int scvrp_msvc_rand(void);
extern "C" uint32_t scvrp_msvc_rand_state(void);
extern "C" uint64_t scvrp_msvc_rand_draw_count(void);

/*
 * The archived executable was built with MSVC/UCRT, whose rand() returns a
 * 15-bit value.  Legacy translation units are compiled with this header
 * force-included so their source remains byte-for-byte identical.
 */
#undef RAND_MAX
#define RAND_MAX 32767
#define rand scvrp_msvc_rand
#define srand scvrp_msvc_srand

#endif
